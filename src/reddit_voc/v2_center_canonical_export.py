from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping
import uuid


BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
CANONICAL_FILES = {
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "manifest.json",
    "posts.jsonl",
    "provenance-ledger.jsonl",
    "quarantine.jsonl",
    "unresolved-parent-ledger.jsonl",
}
INPUT_KEYS = {
    "center_orchestration_receipt_sha256",
    "center_state_sha256",
    "latest_source_batch_manifest_sha256",
    "latest_source_batch_validation_receipt_sha256",
    "previous_canonical_manifest_sha256",
    "previous_canonical_validation_receipt_sha256",
}


class CenterCanonicalExportError(ValueError):
    """The governed center cannot be exported as a conserved V3 canonical bundle."""


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
        raise CenterCanonicalExportError("value is not canonical JSON") from exc


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or not value.isascii()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CenterCanonicalExportError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _jsonl(payload: bytes, label: str) -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise CenterCanonicalExportError(f"{label} must end with a newline")
    rows: list[dict[str, Any]] = []
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CenterCanonicalExportError(f"{label}:{ordinal} is invalid JSON") from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) != line:
            raise CenterCanonicalExportError(f"{label}:{ordinal} is not canonical JSON")
        rows.append(value)
    return rows


def _jsonl_bytes(rows: Iterable[Mapping[str, object]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) + b"\n" for row in rows)


def _read_previous_bundle(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise CenterCanonicalExportError("previous canonical bundle is unavailable or unsafe")
    inventory = {path.name for path in root.iterdir()}
    if inventory != CANONICAL_FILES:
        raise CenterCanonicalExportError("previous canonical bundle inventory is invalid")
    payloads: dict[str, bytes] = {}
    for name in sorted(CANONICAL_FILES):
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise CenterCanonicalExportError(f"previous canonical {name} is unsafe")
        payloads[name] = path.read_bytes()
    manifest = json.loads(payloads["manifest.json"])
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version")
        not in {
            "reddit_voc_canonical_snapshot_manifest_v1",
            "reddit_voc_canonical_snapshot_manifest_v2",
        }
        or manifest.get("status") != "candidate_built"
    ):
        raise CenterCanonicalExportError("previous canonical manifest is invalid")
    for name in sorted(CANONICAL_FILES - {"manifest.json"}):
        binding = manifest.get("files", {}).get(name)
        payload = payloads[name]
        if not isinstance(binding, dict) or binding != {
            "bytes": len(payload),
            "rows": payload.count(b"\n"),
            "sha256": _sha(payload),
        }:
            raise CenterCanonicalExportError(f"previous canonical {name} binding mismatch")
    return payloads


def _bare(fullname: str, prefix: str, label: str) -> str:
    if not isinstance(fullname, str) or not fullname.startswith(prefix):
        raise CenterCanonicalExportError(f"{label} has an invalid identity")
    value = fullname[len(prefix) :]
    if not value or value != value.casefold() or not value.isascii() or not value.isalnum():
        raise CenterCanonicalExportError(f"{label} has an invalid identity")
    return value


def _source_occurrence(payload: Mapping[str, Any]) -> dict[str, object]:
    return {
        "coverage_grade": payload.get("coverage_grade", "partial"),
        "run_id": payload.get("source_run_id"),
        "source_kind": "tencent_production_daily",
        "source_raw_capture_id": payload.get("source_raw_capture_id"),
    }


def _new_post_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    canonical_id = str(payload.get("post_id"))
    post_id = _bare(canonical_id, "t3_", "center post")
    created = payload.get("created_at_utc")
    reported = payload.get("num_comments_reported") or 0
    parsed = payload.get("parsed_comment_count") or 0
    coverage_grade = next(
        (
            occurrence.get("coverage_grade")
            for occurrence in [_source_occurrence(payload)]
            if isinstance(occurrence.get("coverage_grade"), str)
            and occurrence["coverage_grade"]
        ),
        "source_observed",
    )
    record = {
        "author_pseudonym": payload.get("author_hash"),
        "content": payload.get("selftext") or "",
        "created_at_utc": created,
        "event_created_at_utc": created,
        "evidence_id": f"post:{post_id}",
        "matched_keywords": payload.get("matched_keywords") or "",
        "media_urls": payload.get("media_urls") or "[]",
        "more_node_count": payload.get("more_node_count") or 0,
        "num_comments_reported": reported,
        "parsed_comment_count": parsed,
        "permalink": payload.get("source_url"),
        "post_id": post_id,
        "reddit_id": canonical_id,
        "score": payload.get("score") or 0,
        "source_kinds": ["tencent_production_daily"],
        "source_occurrences": [_source_occurrence(payload)],
        "structural_coverage_grade": coverage_grade,
        "count_completeness_status": "equal" if parsed == reported else "source_rows_only",
        "comment_coverage_status": "thread_complete" if parsed == reported else "source_rows_only",
        "subreddit": payload.get("subreddit") or "unknown",
        "title": payload.get("title") or "",
    }
    return {
        "canonical_identity_state": "canonical_identity",
        "canonical_reddit_id": canonical_id,
        "entity_type": "post",
        "post_id": post_id,
        "record": record,
        "record_authority": "governed_base",
        "schema_version": "reddit_voc_canonical_post_v1",
    }


def _new_comment_row(
    payload: Mapping[str, Any], relationship_status: str
) -> dict[str, Any]:
    canonical_id = str(payload.get("comment_id"))
    comment_id = _bare(canonical_id, "t1_", "center comment")
    full_post_id = str(payload.get("post_id"))
    post_id = _bare(full_post_id, "t3_", "center comment post")
    if relationship_status not in {"linked", "unresolved"}:
        raise CenterCanonicalExportError("center comment relationship status is invalid")
    state = "linked" if relationship_status == "linked" else "unresolved_parent"
    created = payload.get("created_at_utc")
    record: dict[str, Any] = {
        "author_pseudonym": payload.get("author_hash"),
        "body": payload.get("body") or "",
        "comment_id": canonical_id,
        "created_at_utc": created,
        "deleted_or_removed": bool(payload.get("deleted_or_removed")),
        "depth": payload.get("depth") or 0,
        "event_created_at_utc": created,
        "evidence_id": f"comment:{canonical_id}",
        "include_in_voc_metrics": state == "linked",
        "is_submitter": bool(payload.get("is_submitter")),
        "matched_keywords": payload.get("matched_keywords") or "",
        "parent_id": payload.get("parent_id"),
        "parent_link_status": state,
        "post_id": post_id,
        "reddit_id": canonical_id,
        "score": payload.get("score") or 0,
        "source_kinds": ["tencent_production_daily"],
        "source_occurrences": [_source_occurrence(payload)],
        "source_url": f"https://www.reddit.com/comments/{post_id}/comment/{comment_id}",
    }
    if state == "unresolved_parent":
        record["terminal_outcome"] = "unresolved_parent"
    return {
        "canonical_identity_state": "canonical_identity",
        "canonical_reddit_id": canonical_id,
        "comment_state": state,
        "entity_type": "comment",
        "immediate_parent_resolution": (
            "missing_root_post_entity" if state == "unresolved_parent" else "pending"
        ),
        "post_id": post_id,
        "record": record,
        "record_authority": "governed_base",
        "schema_version": "reddit_voc_canonical_comment_v1",
    }


def _parent_resolution(
    row: Mapping[str, Any], governed_comments: Mapping[str, Mapping[str, Any]]
) -> str:
    if row.get("comment_state") == "unresolved_parent":
        return "missing_root_post_entity"
    record = row["record"]
    parent_id = record.get("parent_id")
    if parent_id is None:
        return "missing_immediate_parent_id"
    if str(parent_id).startswith("t3_"):
        return "resolved_root_parent"
    if str(parent_id).startswith("t1_"):
        return (
            "resolved_nested_parent"
            if parent_id in governed_comments
            else "missing_parent_comment_entity"
        )
    raise CenterCanonicalExportError("center comment parent identity is invalid")


def _governed_provenance(row: Mapping[str, Any]) -> dict[str, object]:
    canonical_id = str(row["canonical_reddit_id"])
    record = row["record"]
    payload_sha = _sha(canonical_json_bytes(record))
    role = "governed_base_entity"
    occurrences = record.get("source_occurrences", record.get("source_kinds", []))
    count = len(occurrences) if isinstance(occurrences, list) else 0
    return {
        "canonical_reddit_id": canonical_id,
        "entity_type": row["entity_type"],
        "provenance_id": _sha(canonical_json_bytes([canonical_id, role, payload_sha])),
        "schema_version": "reddit_voc_canonical_provenance_v1",
        "source_occurrence_count": count,
        "source_payload_sha256": payload_sha,
        "source_role": role,
    }


def _unresolved_ledger(row: Mapping[str, Any]) -> dict[str, object]:
    record = row["record"]
    canonical_id = str(row["canonical_reddit_id"])
    post_id = str(row["post_id"])
    terminal = record.get("terminal_outcome", "unresolved_parent")
    return {
        "canonical_reddit_id": canonical_id,
        "comment_state": "unresolved_parent",
        "post_id": post_id,
        "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
        "source_parent_link": {
            "candidate_post_ids": [post_id],
            "comment_id": canonical_id,
            "context_available": False,
            "parent_link_status": "unresolved_parent",
            "post_id": post_id,
            "schema_version": "reddit_voc_center_parent_link_v1",
            "terminal_outcome": terminal,
        },
        "source_terminal_outcome": terminal,
    }


def _lineage_debt(comments: Mapping[str, Mapping[str, Any]]) -> dict[str, object]:
    governed = {
        key: row
        for key, row in comments.items()
        if row.get("record_authority") == "governed_base"
        and row.get("comment_state") == "linked"
    }
    missing_immediate = 0
    missing_parent = 0
    nested: dict[str, str] = {}
    for canonical_id, row in governed.items():
        parent = row["record"].get("parent_id")
        if parent is None:
            missing_immediate += 1
        elif str(parent).startswith("t1_"):
            if parent in governed:
                nested[canonical_id] = str(parent)
            else:
                missing_parent += 1
    return {
        "linked_definition": "post_id_resolves_to_canonical_post_not_complete_immediate_parent_chain",
        "missing_immediate_parent_id": missing_immediate,
        "missing_parent_comment_entity": missing_parent,
        "nested_links_whose_parent_record_lacks_immediate_parent_id": sum(
            governed[parent]["record"].get("parent_id") is None
            for parent in nested.values()
        ),
        "workbook_unresolved_parent_separate": True,
    }


def build_center_canonical_bundle(
    *,
    center_database: Path,
    previous_canonical_root: Path,
    previous_canonical_validation_receipt: Path,
    input_sha256: Mapping[str, str],
    dataset_id: str,
    output_root: Path,
) -> dict[str, object]:
    if not dataset_id.endswith("_canonical_v2"):
        raise CenterCanonicalExportError("dataset_id must end with _canonical_v2")
    if set(input_sha256) != INPUT_KEYS:
        raise CenterCanonicalExportError("center canonical input binding keys are invalid")
    inputs = {key: _require_sha(str(value), key) for key, value in input_sha256.items()}
    previous = _read_previous_bundle(previous_canonical_root)
    if _sha(previous["manifest.json"]) != inputs["previous_canonical_manifest_sha256"]:
        raise CenterCanonicalExportError("previous canonical manifest SHA binding mismatch")
    receipt_payload = previous_canonical_validation_receipt.read_bytes()
    if _sha(receipt_payload) != inputs["previous_canonical_validation_receipt_sha256"]:
        raise CenterCanonicalExportError("previous canonical receipt SHA binding mismatch")

    old_posts = {
        row["canonical_reddit_id"]: row
        for row in _jsonl(previous["posts.jsonl"], "previous posts")
    }
    old_comments = {
        row["canonical_reddit_id"]: row
        for row in _jsonl(previous["comments.jsonl"], "previous comments")
    }
    old_quarantine = {
        row["canonical_reddit_id"]: row
        for row in _jsonl(previous["quarantine.jsonl"], "previous quarantine")
    }
    old_provenance = _jsonl(previous["provenance-ledger.jsonl"], "previous provenance")
    old_unresolved = {
        row["canonical_reddit_id"]: row
        for row in _jsonl(previous["unresolved-parent-ledger.jsonl"], "previous unresolved")
    }
    previous_manifest = json.loads(previous["manifest.json"])

    uri = f"file:{center_database.resolve()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        posts = dict(old_posts)
        center_post_ids: set[str] = set()
        for source in connection.execute(
            "SELECT post_id, payload_json FROM canonical_posts ORDER BY post_id"
        ):
            payload = json.loads(source["payload_json"])
            embedded = payload.get("source_record")
            if isinstance(embedded, dict) and embedded.get("schema_version") == "reddit_voc_canonical_post_v1":
                row = embedded
            else:
                row = _new_post_row(payload)
            if row["canonical_reddit_id"] != source["post_id"]:
                raise CenterCanonicalExportError("center post payload identity mismatch")
            posts[source["post_id"]] = row
            center_post_ids.add(source["post_id"])

        comments = dict(old_comments)
        relationships: dict[str, str] = {}
        for source in connection.execute(
            """
            SELECT c.comment_id, c.payload_json, e.relationship_status
            FROM canonical_comments c
            JOIN comment_parent_edges e USING(comment_id)
            ORDER BY c.comment_id
            """
        ):
            payload = json.loads(source["payload_json"])
            embedded = payload.get("source_record")
            if isinstance(embedded, dict) and embedded.get("schema_version") == "reddit_voc_canonical_comment_v1":
                row = dict(embedded)
            else:
                row = _new_comment_row(payload, source["relationship_status"])
            if row["canonical_reddit_id"] != source["comment_id"]:
                raise CenterCanonicalExportError("center comment payload identity mismatch")
            state = "linked" if source["relationship_status"] == "linked" else "unresolved_parent"
            row["comment_state"] = state
            row["post_id"] = _bare(str(payload["post_id"]), "t3_", "center comment post")
            if row.get("record_authority") == "governed_base" and state == "unresolved_parent":
                row["record"]["terminal_outcome"] = "unresolved_parent"
            comments[source["comment_id"]] = row
            relationships[source["comment_id"]] = state
    finally:
        connection.close()

    center_comment_ids = set(relationships)
    if set(comments) != center_comment_ids:
        raise CenterCanonicalExportError("center comment identity conservation mismatch")
    if set(posts) != center_post_ids or set(posts) != {
        row["canonical_reddit_id"] for row in posts.values()
    }:
        raise CenterCanonicalExportError("center post identity conservation mismatch")
    governed_comments = {
        key: row for key, row in comments.items() if row.get("record_authority") == "governed_base"
    }
    for row in governed_comments.values():
        row["immediate_parent_resolution"] = _parent_resolution(row, governed_comments)

    unresolved = dict(old_unresolved)
    for canonical_id, row in comments.items():
        if row["comment_state"] == "unresolved_parent" and canonical_id not in unresolved:
            unresolved[canonical_id] = _unresolved_ledger(row)
        elif row["comment_state"] == "linked":
            unresolved.pop(canonical_id, None)
    if set(unresolved) != {
        key for key, row in comments.items() if row["comment_state"] == "unresolved_parent"
    }:
        raise CenterCanonicalExportError("unresolved parent ledger is not conserved")

    provenance = [
        row for row in old_provenance if row.get("source_role") == "workbook_occurrence"
    ]
    for row in [*posts.values(), *comments.values()]:
        if row.get("record_authority") == "governed_base":
            provenance.append(_governed_provenance(row))
    provenance.sort(key=lambda row: (row["canonical_reddit_id"], row["provenance_id"]))

    documents = {
        "comments.jsonl": _jsonl_bytes(comments[key] for key in sorted(comments)),
        "conflict-ledger.jsonl": previous["conflict-ledger.jsonl"],
        "posts.jsonl": _jsonl_bytes(posts[key] for key in sorted(posts)),
        "provenance-ledger.jsonl": _jsonl_bytes(provenance),
        "quarantine.jsonl": b"",
        "unresolved-parent-ledger.jsonl": _jsonl_bytes(
            unresolved[key] for key in sorted(unresolved)
        ),
    }
    linked = sum(row["comment_state"] == "linked" for row in comments.values())
    unresolved_count = len(comments) - linked
    source_accounting = previous_manifest["source_row_accounting"]
    if sum(source_accounting["terminal_outcomes"].values()) != source_accounting["source_rows"]:
        raise CenterCanonicalExportError("previous source row accounting is invalid")
    manifest: dict[str, object] = {
        "boundaries": dict(BOUNDARIES),
        "canonical_counts": {
            "comments_jsonl": len(comments),
            "linked_comments": linked,
            "posts": len(posts),
            "quarantined_comments": 0,
            "stored_comments": len(comments),
            "unresolved_parent_comments": unresolved_count,
        },
        "consumption_status": "blocked_pending_independent_validation",
        "dataset_id": dataset_id,
        "files": {
            name: {
                "bytes": len(payload),
                "rows": payload.count(b"\n"),
                "sha256": _sha(payload),
            }
            for name, payload in sorted(documents.items())
        },
        "governed_base_parent_lineage_debt": _lineage_debt(comments),
        "independent_validation_status": "pending",
        "inputs": dict(sorted(inputs.items())),
        "promotable": False,
        "schema_version": "reddit_voc_canonical_snapshot_manifest_v2",
        "source_row_accounting": source_accounting,
        "state_contract": {
            "canonical_identity": True,
            "comment_states": ["linked", "unresolved_parent", "quarantined"],
            "states_mutually_exclusive": True,
        },
        "status": "candidate_built",
        "validation_receipt_sha256": None,
    }
    documents["manifest.json"] = canonical_json_bytes(manifest) + b"\n"

    output = output_root.resolve()
    if output.exists():
        raise CenterCanonicalExportError("output bundle already exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output.parent, 0o700)
    stage = output.parent / f".{output.name}.stage-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        for name, payload in sorted(documents.items()):
            path = stage / name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise CenterCanonicalExportError(
                            f"short write while creating {name}"
                        )
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.rename(stage, output)
    finally:
        if stage.exists():
            for path in stage.iterdir():
                path.unlink()
            stage.rmdir()
    return {
        "canonical_counts": manifest["canonical_counts"],
        "dataset_id": dataset_id,
        "manifest_sha256": _sha(documents["manifest.json"]),
        "schema_version": manifest["schema_version"],
        "status": "candidate_built",
    }
