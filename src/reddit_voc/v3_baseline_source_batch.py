from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import REQUIRED_MEMBER_ROLES, load_source_batch


CANONICAL_SCHEMA_PAIRS = {
    "reddit_voc_canonical_snapshot_manifest_v1": (
        "reddit_voc_canonical_snapshot_validation_receipt_v1"
    ),
    "reddit_voc_canonical_snapshot_manifest_v2": (
        "reddit_voc_canonical_snapshot_validation_receipt_v2"
    ),
}
BRIDGE_RECEIPT_SCHEMA = "reddit_voc_v3_baseline_bridge_receipt_v1"
EXPECTED_CANONICAL_FILES = (
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "posts.jsonl",
    "provenance-ledger.jsonl",
    "quarantine.jsonl",
    "unresolved-parent-ledger.jsonl",
)


class V3BaselineSourceBatchError(ValueError):
    pass


@dataclass(frozen=True)
class V3BaselineSourceBatchResult:
    batch_root: Path
    manifest_path: Path
    manifest_sha256: str
    write_status: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V3BaselineSourceBatchError(f"{label} is invalid") from exc
    if not isinstance(value, dict) or payload != canonical_json_bytes(value) + b"\n":
        raise V3BaselineSourceBatchError(f"{label} is not canonical")
    return value, payload


def _jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise V3BaselineSourceBatchError(f"{label} is unavailable") from exc
    if payload and not payload.endswith(b"\n"):
        raise V3BaselineSourceBatchError(f"{label} must end with LF")
    for ordinal, line in enumerate(payload.splitlines(), start=1):
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise V3BaselineSourceBatchError(f"{label} row is invalid:{ordinal}") from exc
        if not isinstance(row, dict) or line != canonical_json_bytes(row):
            raise V3BaselineSourceBatchError(f"{label} row is not canonical:{ordinal}")
        rows.append(row)
    return rows


def _utc_z(value: object, *, label: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        raise V3BaselineSourceBatchError(f"{label} is invalid")
    if len(value) == 10:
        value = value + "T00:00:00Z"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise V3BaselineSourceBatchError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise V3BaselineSourceBatchError(f"{label} is not timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_time(record: Mapping[str, Any]) -> str | None:
    value = record.get("event_created_at_utc") or record.get("created_at_utc")
    if value is None:
        value = record.get("source_calendar_date")
    return _utc_z(value, label="V3 event time", allow_none=True)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with path.open("xb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(dict(row)) + b"\n")
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)
    return count


def _member(path: Path, role: str, root: Path) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "relative_path": path.relative_to(root).as_posix(),
        "role": role,
        "rows": len(path.read_bytes().splitlines()),
        "sha256": _sha256(path),
    }


def _raw_entry(path: Path, raw_object_id: str, root: Path, *, observed: bool) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "raw_object_id": raw_object_id,
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "terminal_disposition": "entity_observed" if observed else "no_entity",
    }


def _validated_inputs(
    canonical_root: Path, validation_receipt_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest_path = canonical_root / "manifest.json"
    manifest, manifest_payload = _canonical_object(manifest_path, "V3 canonical manifest")
    receipt, _receipt_payload = _canonical_object(
        validation_receipt_path, "V3 canonical validation receipt"
    )
    receipt_schema = CANONICAL_SCHEMA_PAIRS.get(str(manifest.get("schema_version")))
    if receipt_schema is None:
        raise V3BaselineSourceBatchError("V3 canonical manifest schema is unsupported")
    if receipt.get("schema_version") != receipt_schema or receipt.get("status") != "passed":
        raise V3BaselineSourceBatchError("V3 canonical validation receipt is not passed")
    if receipt.get("bundle_manifest_sha256") != hashlib.sha256(manifest_payload).hexdigest():
        raise V3BaselineSourceBatchError("V3 canonical validation receipt binding mismatch")
    if receipt.get("canonical_counts") != manifest.get("canonical_counts"):
        raise V3BaselineSourceBatchError("V3 canonical count receipt mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or tuple(sorted(files)) != EXPECTED_CANONICAL_FILES:
        raise V3BaselineSourceBatchError("V3 canonical file contract mismatch")
    documents: dict[str, list[dict[str, Any]]] = {}
    for name in EXPECTED_CANONICAL_FILES:
        contract = files.get(name)
        if not isinstance(contract, dict) or set(contract) != {"bytes", "rows", "sha256"}:
            raise V3BaselineSourceBatchError(f"V3 canonical file contract is invalid:{name}")
        path = canonical_root / name
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != contract["bytes"]
            or _sha256(path) != contract["sha256"]
        ):
            raise V3BaselineSourceBatchError(f"V3 canonical file binding mismatch:{name}")
        documents[name] = _jsonl(path, f"V3 canonical {name}")
        if len(documents[name]) != contract["rows"]:
            raise V3BaselineSourceBatchError(f"V3 canonical row count mismatch:{name}")
    return manifest, receipt, documents


def load_validated_v3_canonical_snapshot(
    canonical_root: Path | str, validation_receipt_path: Path | str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Load only a canonical V3 snapshot bound to a passed validation receipt."""
    return _validated_inputs(Path(canonical_root), Path(validation_receipt_path))


def _post(row: Mapping[str, Any]) -> dict[str, Any]:
    record = row.get("record")
    if not isinstance(record, dict):
        raise V3BaselineSourceBatchError("V3 canonical post record is invalid")
    post_id = str(row.get("canonical_reddit_id") or "")
    if not post_id.startswith("t3_"):
        raise V3BaselineSourceBatchError("V3 canonical post identity is invalid")
    return {
        "author_hash": record.get("author_pseudonym"),
        "created_at_utc": _event_time(record),
        "more_node_count": record.get("more_node_count", 0),
        "num_comments_reported": record.get("num_comments_reported", 0),
        "parsed_comment_count": record.get("parsed_comment_count", record.get("linked_comment_count", 0)),
        "post_id": post_id,
        "score": record.get("score"),
        "selftext": record.get("content") or record.get("selftext") or "",
        "source_record": dict(row),
        "source_url": record.get("permalink") or record.get("source_url") or "",
        "subreddit": record.get("subreddit") or "unknown",
        "title": record.get("title") or "",
    }


def _comment(row: Mapping[str, Any]) -> dict[str, Any]:
    record = row.get("record")
    if not isinstance(record, dict):
        raise V3BaselineSourceBatchError("V3 canonical comment record is invalid")
    comment_id = str(row.get("canonical_reddit_id") or "")
    post_id = str(row.get("post_id") or record.get("post_id") or "")
    if not comment_id.startswith("t1_") or not post_id:
        raise V3BaselineSourceBatchError("V3 canonical comment identity is invalid")
    relationship_status = str(row.get("comment_state") or "linked")
    parent_id = record.get("parent_id") if relationship_status == "linked" else None
    return {
        "body": record.get("body") or record.get("source_text") or "",
        "comment_id": comment_id,
        "created_at_utc": _event_time(record),
        "deleted_or_removed": bool(record.get("deleted_or_removed", False)),
        "parent_id": parent_id,
        "post_id": post_id if post_id.startswith("t3_") else "t3_" + post_id,
        "relationship_status": relationship_status,
        "score": record.get("score"),
        "source_record": dict(row),
    }


def _quarantined_comment(row: Mapping[str, Any]) -> dict[str, Any]:
    record = row.get("record")
    if not isinstance(record, dict):
        raise V3BaselineSourceBatchError("V3 quarantine record is invalid")
    comment_id = str(row.get("canonical_reddit_id") or "")
    post_id = str(record.get("missing_post_id") or "")
    if not comment_id.startswith("t1_") or not post_id:
        raise V3BaselineSourceBatchError("V3 quarantine identity is invalid")
    return {
        "body": "",
        "comment_id": comment_id,
        "created_at_utc": None,
        "deleted_or_removed": False,
        "parent_id": "quarantine_missing_post",
        "post_id": post_id if post_id.startswith("t3_") else "t3_" + post_id,
        "relationship_status": "quarantined",
        "score": None,
        "source_record": dict(row),
    }


def _build_in_staging(
    staging: Path,
    *,
    canonical_root: Path,
    validation_receipt_path: Path,
    batch_id: str,
) -> str:
    manifest, receipt, documents = _validated_inputs(canonical_root, validation_receipt_path)
    counts = manifest.get("canonical_counts")
    if not isinstance(counts, dict):
        raise V3BaselineSourceBatchError("V3 canonical counts are invalid")
    posts = [_post(row) for row in documents["posts.jsonl"]]
    source_comments = documents["comments.jsonl"]
    unresolved_ids = {
        str(row.get("canonical_reddit_id")) for row in documents["unresolved-parent-ledger.jsonl"]
    }
    comments = [_comment(row) for row in source_comments]
    comments.extend(_quarantined_comment(row) for row in documents["quarantine.jsonl"])
    post_ids = {row["post_id"] for row in posts}
    comment_ids = {row["comment_id"] for row in comments}
    source_comment_ids = {str(row.get("canonical_reddit_id")) for row in source_comments}
    source_comment_posts = {
        str(row.get("canonical_reddit_id")): (
            str(row.get("post_id"))
            if str(row.get("post_id")).startswith("t3_")
            else "t3_" + str(row.get("post_id"))
        )
        for row in source_comments
    }
    for comment in comments:
        if comment["relationship_status"] != "linked":
            continue
        parent_id = comment.get("parent_id")
        post_id = comment["post_id"]
        parent_is_resolved = (
            parent_id == post_id
            if isinstance(parent_id, str) and parent_id.startswith("t3_")
            else isinstance(parent_id, str)
            and parent_id.startswith("t1_")
            and source_comment_posts.get(parent_id) == post_id
        )
        if not parent_is_resolved:
            # V3's linked state proves root-post membership even when an immediate
            # reply parent was absent in the historical source. The original
            # immediate-parent evidence remains intact inside source_record.
            comment["parent_id"] = post_id
    quarantine_ids = {
        str(row.get("canonical_reddit_id")) for row in documents["quarantine.jsonl"]
    }
    linked = [row for row in comments if row["relationship_status"] == "linked"]
    if any(row["post_id"] not in post_ids for row in linked):
        raise V3BaselineSourceBatchError("V3 linked comment references missing post")
    if not unresolved_ids <= source_comment_ids or source_comment_ids & quarantine_ids:
        raise V3BaselineSourceBatchError("V3 structural comment states are inconsistent")
    if (
        len(posts) != counts.get("posts")
        or len(comments) != counts.get("stored_comments")
        or len(linked) != counts.get("linked_comments")
        or len(unresolved_ids) != counts.get("unresolved_parent_comments")
        or len(quarantine_ids) != counts.get("quarantined_comments")
        or len(comment_ids) != len(comments)
    ):
        raise V3BaselineSourceBatchError("V3 canonical conservation failed")

    raw_root = staging / "raw"
    raw_root.mkdir(mode=0o700)
    raw_sources = {
        "raw-v3-comments": canonical_root / "comments.jsonl",
        "raw-v3-conflicts": canonical_root / "conflict-ledger.jsonl",
        "raw-v3-manifest": canonical_root / "manifest.json",
        "raw-v3-posts": canonical_root / "posts.jsonl",
        "raw-v3-provenance": canonical_root / "provenance-ledger.jsonl",
        "raw-v3-quarantine": canonical_root / "quarantine.jsonl",
        "raw-v3-receipt": validation_receipt_path,
        "raw-v3-unresolved": canonical_root / "unresolved-parent-ledger.jsonl",
    }
    raw_paths: dict[str, Path] = {}
    for raw_id, source in raw_sources.items():
        target = raw_root / source.name
        if target.exists():
            target = raw_root / f"{raw_id}-{source.name}"
        shutil.copyfile(source, target)
        target.chmod(0o600)
        raw_paths[raw_id] = target

    post_occurrences = [
        {
            "occurrence_id": "v3-baseline-post-" + hashlib.sha256(row["post_id"].encode()).hexdigest(),
            "post_id": row["post_id"],
            "raw_object_id": "raw-v3-posts",
        }
        for row in posts
    ]
    comment_occurrences = []
    for row in comments:
        raw_id = "raw-v3-comments"
        if row["relationship_status"] == "unresolved_parent":
            raw_id = "raw-v3-unresolved"
        elif row["relationship_status"] == "quarantined":
            raw_id = "raw-v3-quarantine"
        comment_occurrences.append(
            {
                "comment_id": row["comment_id"],
                "occurrence_id": "v3-baseline-comment-"
                + hashlib.sha256(row["comment_id"].encode()).hexdigest(),
                "raw_object_id": raw_id,
            }
        )
    observed_raw = {
        "raw-v3-posts": bool(posts),
        "raw-v3-comments": bool(linked),
        "raw-v3-unresolved": bool(unresolved_ids),
        "raw-v3-quarantine": bool(quarantine_ids),
    }
    raw_index = [
        _raw_entry(path, raw_id, staging, observed=observed_raw.get(raw_id, False))
        for raw_id, path in sorted(raw_paths.items())
    ]
    event_times = [row["created_at_utc"] for row in posts + comments if row["created_at_utc"]]
    if not event_times:
        raise V3BaselineSourceBatchError("V3 baseline contains no event time")
    start = datetime.fromisoformat(min(event_times).replace("Z", "+00:00")).astimezone(timezone.utc)
    end_source = datetime.fromisoformat(max(event_times).replace("Z", "+00:00")).astimezone(timezone.utc)
    window_start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    window_end = datetime(end_source.year, end_source.month, end_source.day, tzinfo=timezone.utc) + timedelta(days=1)
    checkpoint = {
        "batch_id": batch_id,
        "canonical_manifest_sha256": _sha256(canonical_root / "manifest.json"),
        "canonical_validation_receipt_sha256": _sha256(validation_receipt_path),
        "status": "baseline_frozen",
    }
    documents_out: dict[str, list[dict[str, Any]]] = {
        "checkpoints": [checkpoint],
        "comment_occurrences": sorted(comment_occurrences, key=lambda row: row["occurrence_id"]),
        "comments": sorted(comments, key=lambda row: row["comment_id"]),
        "issues": [],
        "post_occurrences": sorted(post_occurrences, key=lambda row: row["occurrence_id"]),
        "posts": sorted(posts, key=lambda row: row["post_id"]),
        "raw_index": raw_index,
    }
    member_paths: dict[str, Path] = {}
    for role in REQUIRED_MEMBER_ROLES:
        path = staging / (role.replace("_", "-") + ".jsonl")
        _write_jsonl(path, documents_out[role])
        member_paths[role] = path
    query_sha = str(manifest.get("inputs", {}).get("source_manifest_sha256") or _sha256(canonical_root / "manifest.json"))
    coverage_sha = _sha256(validation_receipt_path)
    output_manifest = {
        "active_thread_policy": None,
        "batch_id": batch_id,
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        },
        "counts": {
            "comment_occurrences": len(comment_occurrences),
            "comments": len(comments),
            "issues": 0,
            "post_occurrences": len(post_occurrences),
            "posts": len(posts),
            "raw_objects": len(raw_index),
            "unresolved_continuations": 0,
        },
        "members": [_member(member_paths[role], role, staging) for role in REQUIRED_MEMBER_ROLES],
        "producer_type": "historical_backfill",
        "profiles": {
            "coverage_profile_sha256": coverage_sha,
            "coverage_profile_version": "v3-baseline-coverage-" + coverage_sha[:12],
            "query_profile_sha256": query_sha,
            "query_profile_version": "v3-baseline-query-" + query_sha[:12],
        },
        "schema_version": "reddit_voc_source_batch_v2",
        "status": "success",
        "window": {
            "metric_end_utc": window_end.isoformat().replace("+00:00", "Z"),
            "metric_start_utc": window_start.isoformat().replace("+00:00", "Z"),
            "new_post_discovery_end_utc": window_end.isoformat().replace("+00:00", "Z"),
            "new_post_discovery_start_utc": window_start.isoformat().replace("+00:00", "Z"),
            "timezone": "Asia/Shanghai",
        },
    }
    manifest_path = staging / "source-batch-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(output_manifest) + b"\n")
    manifest_path.chmod(0o600)
    load_source_batch(manifest_path, staging, require_consumable=True)
    return _sha256(manifest_path)


def build_v3_baseline_source_batch(
    *,
    canonical_root: Path | str,
    validation_receipt_path: Path | str,
    output_root: Path | str,
    batch_id: str,
) -> V3BaselineSourceBatchResult:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    target = root / batch_id
    staging = Path(tempfile.mkdtemp(prefix=f".{batch_id}.staging-", dir=root))
    staging.chmod(0o700)
    try:
        digest = _build_in_staging(
            staging,
            canonical_root=Path(canonical_root),
            validation_receipt_path=Path(validation_receipt_path),
            batch_id=batch_id,
        )
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise V3BaselineSourceBatchError("V3 baseline SourceBatch immutable collision")
            existing = load_source_batch(target / "source-batch-manifest.json", target)
            if existing.manifest_sha256 != digest:
                raise V3BaselineSourceBatchError("V3 baseline SourceBatch immutable collision")
            return V3BaselineSourceBatchResult(
                batch_root=target,
                manifest_path=target / "source-batch-manifest.json",
                manifest_sha256=digest,
                write_status="no_change",
            )
        os.rename(staging, target)
        return V3BaselineSourceBatchResult(
            batch_root=target,
            manifest_path=target / "source-batch-manifest.json",
            manifest_sha256=digest,
            write_status="created",
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def build_v3_baseline_bridge_receipt(
    *,
    canonical_root: Path | str,
    canonical_validation_receipt_path: Path | str,
    source_batch_manifest_path: Path | str,
    source_batch_validation_receipt_path: Path | str,
) -> dict[str, object]:
    canonical = Path(canonical_root)
    manifest, receipt, _documents = _validated_inputs(
        canonical, Path(canonical_validation_receipt_path)
    )
    batch = load_source_batch(source_batch_manifest_path, require_consumable=True)
    source_receipt, source_receipt_payload = _canonical_object(
        Path(source_batch_validation_receipt_path), "SourceBatch validation receipt"
    )
    if (
        source_receipt.get("status") != "passed"
        or source_receipt.get("consumable") is not True
        or source_receipt.get("manifest_sha256") != batch.manifest_sha256
    ):
        raise V3BaselineSourceBatchError("SourceBatch validation receipt binding mismatch")
    return {
        "bridge_version": "v3-canonical-to-source-batch-v1",
        "counts": manifest["canonical_counts"],
        "schema_version": BRIDGE_RECEIPT_SCHEMA,
        "source_batch_manifest_sha256": batch.manifest_sha256,
        "source_batch_validation_receipt_sha256": hashlib.sha256(source_receipt_payload).hexdigest(),
        "source_canonical_manifest_sha256": _sha256(canonical / "manifest.json"),
        "source_canonical_validation_receipt_sha256": _sha256(Path(canonical_validation_receipt_path)),
        "source_dataset_id": manifest["dataset_id"],
        "status": "passed",
        "upstream_validation_status": receipt["status"],
    }
