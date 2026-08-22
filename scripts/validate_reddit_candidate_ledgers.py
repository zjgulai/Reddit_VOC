#!/usr/bin/env python3
"""Independently validate one private Plan-A candidate ledger bundle."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Any, Iterable, Sequence

try:
    from scripts import build_reddit_v2_raw_snapshot as v2
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import build_reddit_v2_raw_snapshot as v2  # type: ignore[no-redef]


MANIFEST_SCHEMA = "reddit_voc_candidate_ledger_manifest_v2"
SOURCE_FREEZE_SCHEMA = "reddit_voc_candidate_source_freeze_v1"
BASE_SCHEMAS = {
    "reddit_voc_site_snapshot_manifest_v1",
    "reddit_voc_site_snapshot_manifest_v2",
}
IDENTITY_SCHEMA = "reddit_voc_v2_identity_freeze_v1"
RAW_SCHEMA = "reddit_voc_v2_raw_snapshot_v1"
HYDRATION_SCHEMA = "reddit_voc_existing_post_hydration_v1"
RECEIPT_SCHEMA = "reddit_voc_candidate_ledger_validation_receipt_v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
POST_ID_RE = re.compile(r"^[a-z0-9]{5,10}$")
COMMENT_ID_RE = re.compile(r"^t1_[a-z0-9]+$")

LEDGER_NAMES = (
    "source-occurrence-ledger.jsonl",
    "post-identity-delta-ledger.jsonl",
    "comment-identity-delta-ledger.jsonl",
    "coverage-work-ledger.jsonl",
)
MANIFEST_NAME = "candidate-ledger-manifest.json"
EXPECTED_BUNDLE_MEMBERS = frozenset((*LEDGER_NAMES, MANIFEST_NAME))

# This whitelist is intentionally explicit.  Source occurrence lineage is
# accounted in its own ledger and is not part of entity-upgrade semantics.
POST_MANAGED_FIELDS = (
    "title",
    "content",
    "subreddit",
    "permalink",
    "created_at_utc",
    "event_created_at_utc",
    "author_pseudonym",
    "pii_redaction_flags",
    "structural_coverage_grade",
    "comment_coverage_status",
    "count_completeness_status",
    "linked_comment_count",
    "parsed_comment_count",
    "num_comments_reported",
    "more_node_count",
    "comment_count_gap",
    "analysis",
    "tagging",
    "product_bindings",
    "brand_binding",
    "brand_binding_scope",
    "mentioned_brands",
    "discussion_mentioned_brands",
)
COMMENT_MANAGED_FIELDS = (
    "post_id",
    "parent_id",
    "body",
    "created_at_utc",
    "event_created_at_utc",
    "deleted_or_removed",
    "author_pseudonym",
    "pii_redaction_flags",
    "depth",
    "include_in_voc_metrics",
    "parent_link_status",
    "bot_detection_status",
    "is_bot",
    "analysis",
    "tagging",
    "product_bindings",
    "brand_binding",
    "brand_binding_scope",
    "mentioned_brands",
)
REJECTED_COMMENT_SOURCE_FIELDS = (
    "post_id",
    "parent_id",
    "body",
    "created_at_utc",
    "deleted_or_removed",
    "author_hash",
    "depth",
)

OCCURRENCE_STATUSES = {
    "accepted_new_occurrence",
    "accepted_duplicate_occurrence",
    "superseded_by_precedence",
    "rejected_invalid",
    "quarantined_input",
}
POST_STATUSES = {
    "newly_admitted",
    "existing_upgraded",
    "existing_unchanged",
    "pending_lineage",
    "rejected",
}
COMMENT_STATUSES = {
    "new_linked",
    "new_quarantined",
    "existing_upgraded",
    "existing_unchanged",
    "existing_quarantine_relinked",
    "existing_quarantine_retained",
    "rejected",
}
COVERAGE_STATUSES = {
    "closed_success",
    "closed_no_more",
    "superseded",
    "retryable_failed",
    "nonretryable_rejected",
    "open_carried",
}
EXTERNAL_REJECTION_REASONS = {
    "window_outside_subreddit_post",
    "window_inside_profile_post",
    "window_outside_profile_post",
    "raw_id_without_strict_search_row",
}
BOUNDARIES = {
    "provider_call": False,
    "provider_attempt_made": False,
    "database_write": False,
    "remote_write": False,
    "production_merge": False,
    "deployment": False,
    "live_send": False,
    "production_unchanged": True,
}
COMMENT_REPORT_FAILURE_REASONS = {
    "legacy_reply_source_chain_incomplete",
    "legacy_reply_source_predecessor_missing",
    "report_response_validation_failed",
}


class CandidateLedgerValidationError(ValueError):
    """One validation invariant failed with a non-sensitive reason code."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_builder_code_binding(path: Path, declared_sha256: object) -> str:
    _regular_file(path, label="builder_code")
    digest = _file_sha256(path)
    if (
        not isinstance(declared_sha256, str)
        or SHA256_RE.fullmatch(declared_sha256) is None
        or declared_sha256 != digest
    ):
        raise CandidateLedgerValidationError("builder_code_binding_invalid")
    return digest


def write_immutable_receipt(path: Path, value: dict[str, Any]) -> str:
    _reject_traversal(path, label="receipt")
    if path.name in {"", ".", ".."}:
        raise CandidateLedgerValidationError("receipt_path_invalid")
    payload = _canonical_bytes(value) + b"\n"
    if path.exists() or path.is_symlink():
        _regular_file(path, label="receipt", mode=0o600)
        if path.read_bytes() == payload:
            return "no_change"
        raise CandidateLedgerValidationError("receipt_immutable_collision")
    parent = path.parent
    if parent.exists() or parent.is_symlink():
        _directory(parent, label="receipt_parent", mode=0o700)
    else:
        _directory(parent.parent, label="receipt_grandparent")
        try:
            parent.mkdir(mode=0o700)
        except OSError as exc:
            raise CandidateLedgerValidationError("receipt_parent_create_failed") from exc
        _directory(parent, label="receipt_parent", mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.staging-", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink():
                raise CandidateLedgerValidationError("receipt_unsafe")
            _regular_file(path, label="receipt", mode=0o600)
            if path.read_bytes() != payload:
                raise CandidateLedgerValidationError(
                    "receipt_immutable_collision"
                )
            return "no_change"
        _regular_file(path, label="receipt", mode=0o600)
        if path.read_bytes() != payload:
            raise CandidateLedgerValidationError("receipt_write_verification_failed")
        return "created"
    except CandidateLedgerValidationError:
        raise
    except OSError as exc:
        raise CandidateLedgerValidationError("receipt_write_failed") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _identity_hash(values: Iterable[str]) -> str:
    return _sha256_bytes(
        "".join(f"{value}\n" for value in sorted(set(values))).encode("utf-8")
    )


def _parse_utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateLedgerValidationError(f"{label}_invalid") from exc
    if parsed.tzinfo is None:
        raise CandidateLedgerValidationError(f"{label}_invalid")
    return parsed.astimezone(timezone.utc)


def _reject_traversal(path: Path, *, label: str) -> None:
    if ".." in path.parts:
        raise CandidateLedgerValidationError(f"{label}_path_traversal")


def _lstat(path: Path, *, label: str) -> os.stat_result:
    _reject_traversal(path, label=label)
    try:
        return os.lstat(path)
    except OSError as exc:
        raise CandidateLedgerValidationError(f"{label}_missing") from exc


def _regular_file(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    metadata = _lstat(path, label=label)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CandidateLedgerValidationError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise CandidateLedgerValidationError(f"{label}_mode_invalid")
    return metadata


def _directory(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    metadata = _lstat(path, label=label)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise CandidateLedgerValidationError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise CandidateLedgerValidationError(f"{label}_mode_invalid")
    return metadata


def _load_json_value(
    path: Path, *, label: str, require_canonical: bool = True
) -> object:
    _regular_file(path, label=label)
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateLedgerValidationError(f"{label}_invalid") from exc
    if require_canonical and payload != _canonical_bytes(value) + b"\n":
        raise CandidateLedgerValidationError(f"{label}_noncanonical")
    return value


def _load_json(
    path: Path, *, label: str, require_canonical: bool = True
) -> dict[str, Any]:
    value = _load_json_value(
        path, label=label, require_canonical=require_canonical
    )
    if not isinstance(value, dict):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    return value


def _load_json_array(
    path: Path, *, label: str, require_canonical: bool = True
) -> list[dict[str, Any]]:
    value = _load_json_value(
        path, label=label, require_canonical=require_canonical
    )
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    return value


def _load_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    _regular_file(path, label=label, mode=0o600)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise CandidateLedgerValidationError(f"{label}_invalid") from exc
    if not payload or not payload.endswith(b"\n"):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    rows: list[dict[str, Any]] = []
    for line in payload.splitlines(keepends=True):
        if line == b"\n":
            raise CandidateLedgerValidationError(f"{label}_invalid")
        try:
            row = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CandidateLedgerValidationError(f"{label}_invalid") from exc
        if not isinstance(row, dict) or line != _canonical_bytes(row) + b"\n":
            raise CandidateLedgerValidationError(f"{label}_noncanonical")
        rows.append(row)
    return rows


def _normalize_managed(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return [_normalize_managed(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_managed(item)
            for key, item in sorted(value.items())
        }
    return value


def _managed_sha256(row: dict[str, Any], fields: Sequence[str]) -> str:
    selected = {
        field: _normalize_managed(row.get(field)) for field in sorted(set(fields))
    }
    return _sha256_bytes(_canonical_bytes(selected))


def _unique_map(
    rows: Sequence[dict[str, Any]],
    *,
    field: str,
    pattern: re.Pattern[str],
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(field)
        if not isinstance(identity, str) or pattern.fullmatch(identity) is None:
            raise CandidateLedgerValidationError(f"{label}_identity_invalid")
        if identity in result:
            raise CandidateLedgerValidationError(f"{label}_identity_duplicate")
        result[identity] = row
    return result


def _validated_base(root: Path, *, label: str) -> dict[str, Any]:
    _directory(root, label=label)
    manifest_path = root / "manifest.json"
    manifest = _load_json(
        manifest_path, label=f"{label}_manifest", require_canonical=False
    )
    if manifest.get("schema_version") not in BASE_SCHEMAS:
        raise CandidateLedgerValidationError(f"{label}_schema_invalid")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise CandidateLedgerValidationError(f"{label}_files_invalid")
    required = {"posts.json", "comments.json", "quarantine.json"}
    if not required <= set(files):
        raise CandidateLedgerValidationError(f"{label}_files_invalid")
    expected_members = {"manifest.json", *files}
    try:
        actual_members = {path.name for path in root.iterdir()}
    except OSError as exc:
        raise CandidateLedgerValidationError(f"{label}_unsafe") from exc
    if actual_members != expected_members:
        raise CandidateLedgerValidationError(f"{label}_member_set_invalid")
    for name, binding in files.items():
        if (
            not isinstance(name, str)
            or PurePosixPath(name).name != name
            or not isinstance(binding, dict)
        ):
            raise CandidateLedgerValidationError(f"{label}_files_invalid")
        path = root / name
        metadata = _regular_file(path, label=f"{label}_member")
        if (
            binding.get("bytes") != metadata.st_size
            or binding.get("sha256") != _file_sha256(path)
        ):
            raise CandidateLedgerValidationError(f"{label}_file_binding_invalid")

    posts = _load_json_array(
        root / "posts.json", label=f"{label}_posts", require_canonical=False
    )
    comments = _load_json_array(
        root / "comments.json", label=f"{label}_comments", require_canonical=False
    )
    quarantine = _load_json_array(
        root / "quarantine.json",
        label=f"{label}_quarantine",
        require_canonical=False,
    )
    post_map = _unique_map(
        posts, field="post_id", pattern=POST_ID_RE, label=f"{label}_post"
    )
    comment_map = _unique_map(
        comments,
        field="comment_id",
        pattern=COMMENT_ID_RE,
        label=f"{label}_comment",
    )
    quarantine_map = _unique_map(
        quarantine,
        field="comment_id",
        pattern=COMMENT_ID_RE,
        label=f"{label}_quarantine",
    )
    if set(comment_map) & set(quarantine_map):
        raise CandidateLedgerValidationError(f"{label}_comment_partition_invalid")
    if any(row.get("post_id") not in post_map for row in comments):
        raise CandidateLedgerValidationError(f"{label}_linked_parent_missing")
    if manifest.get("canonical_counts") != {
        "posts": len(post_map),
        "linked_comments": len(comment_map),
        "quarantined_comments": len(quarantine_map),
        "stored_comments": len(comment_map) + len(quarantine_map),
    }:
        raise CandidateLedgerValidationError(f"{label}_canonical_counts_invalid")
    return {
        "manifest": manifest,
        "manifest_sha256": _file_sha256(manifest_path),
        "posts": post_map,
        "comments": comment_map,
        "quarantine": quarantine_map,
    }


def _safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CandidateLedgerValidationError(f"{label}_invalid")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    return value


def _report_tree(root: Path) -> dict[str, Path]:
    _directory(root, label="report_root")
    result: dict[str, Path] = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort()
        file_names.sort()
        directory_path = Path(directory)
        for name in directory_names:
            metadata = _lstat(directory_path / name, label="report_directory")
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise CandidateLedgerValidationError("report_directory_unsafe")
        for name in file_names:
            path = directory_path / name
            _regular_file(path, label="report_member")
            relative = path.relative_to(root).as_posix()
            if relative in result:
                raise CandidateLedgerValidationError("report_member_duplicate")
            result[relative] = path
    return result


def _validated_source_freeze(
    manifest_path: Path,
    report_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    manifest = _load_json(manifest_path, label="source_freeze_manifest")
    if manifest.get("schema_version") != SOURCE_FREEZE_SCHEMA:
        raise CandidateLedgerValidationError("source_freeze_schema_invalid")
    cutoff = manifest.get("source_cutoff_utc")
    _parse_utc(cutoff, label="source_freeze_cutoff")
    assert isinstance(cutoff, str)
    entries = manifest.get("files")
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise CandidateLedgerValidationError("source_freeze_files_invalid")
    if manifest.get("file_count") != len(entries):
        raise CandidateLedgerValidationError("source_freeze_file_count_invalid")
    expected_row_keys = {
        "source_namespace",
        "source_kind",
        "relative_path",
        "destination_relative_path",
        "bytes",
        "mtime_ns",
        "sha256",
        "fusion_eligible",
    }
    normalized: list[dict[str, Any]] = []
    source_keys: set[tuple[str, str]] = set()
    for entry in entries:
        if set(entry) != expected_row_keys:
            raise CandidateLedgerValidationError("source_freeze_file_row_invalid")
        namespace = entry.get("source_namespace")
        if not isinstance(namespace, str) or NAMESPACE_RE.fullmatch(namespace) is None:
            raise CandidateLedgerValidationError("source_freeze_namespace_invalid")
        relative = _safe_relative(
            entry.get("relative_path"), label="source_freeze_relative_path"
        )
        destination = _safe_relative(
            entry.get("destination_relative_path"),
            label="source_freeze_destination_path",
        )
        if destination != (PurePosixPath("sources") / namespace / relative).as_posix():
            raise CandidateLedgerValidationError("source_freeze_destination_mismatch")
        byte_count = entry.get("bytes")
        mtime_ns = entry.get("mtime_ns")
        digest = entry.get("sha256")
        eligible = entry.get("fusion_eligible")
        if (
            not isinstance(entry.get("source_kind"), str)
            or not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
            or not isinstance(mtime_ns, int)
            or isinstance(mtime_ns, bool)
            or mtime_ns < 0
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
            or not isinstance(eligible, bool)
        ):
            raise CandidateLedgerValidationError("source_freeze_file_row_invalid")
        key = (namespace, relative)
        if key in source_keys:
            raise CandidateLedgerValidationError("source_freeze_file_duplicate")
        source_keys.add(key)
        normalized.append(entry)
    ordered = sorted(
        normalized,
        key=lambda row: (str(row["source_namespace"]), str(row["relative_path"])),
    )
    if normalized != ordered:
        raise CandidateLedgerValidationError("source_freeze_order_invalid")
    aggregate = "".join(
        f"{row['source_namespace']}|{row['relative_path']}|{row['bytes']}|"
        f"{row['mtime_ns']}|{row['sha256']}|"
        f"{str(row['fusion_eligible']).lower()}\n"
        for row in ordered
    ).encode("utf-8")
    if (
        manifest.get("total_bytes") != sum(int(row["bytes"]) for row in ordered)
        or manifest.get("fusion_eligible_file_count")
        != sum(row["fusion_eligible"] is True for row in ordered)
        or manifest.get("documentation_file_count")
        != sum(
            row["source_kind"] == "local_external_documentation" for row in ordered
        )
        or manifest.get("file_manifest_lf_sha256") != _sha256_bytes(aggregate)
    ):
        raise CandidateLedgerValidationError("source_freeze_accounting_invalid")
    if manifest.get("raw_payload_embedded_in_manifest") is not False:
        raise CandidateLedgerValidationError("source_freeze_privacy_invalid")
    if manifest.get("boundaries") != {
        "provider_call": False,
        "provider_attempt_made": False,
        "remote_write": False,
        "database_write": False,
        "deploy": False,
        "live_send": False,
    }:
        raise CandidateLedgerValidationError("source_freeze_boundary_invalid")

    expected_reports = {
        str(row["relative_path"]): (int(row["bytes"]), str(row["sha256"]))
        for row in ordered
        if row["source_namespace"] == "tencent_v2_reports"
    }
    actual_reports = _report_tree(report_root)
    if set(actual_reports) != set(expected_reports):
        raise CandidateLedgerValidationError("report_root_member_set_invalid")
    for relative, (byte_count, digest) in expected_reports.items():
        path = actual_reports[relative]
        if path.stat().st_size != byte_count or _file_sha256(path) != digest:
            raise CandidateLedgerValidationError("report_root_member_binding_invalid")
    return manifest, ordered, cutoff


def _expected_occurrences(
    entries: Sequence[dict[str, Any]],
    *,
    cutoff: str,
    input_evidence_sha256: str,
    invalid_report_sha256s: set[str],
    selected_governed_sha256s: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_content: set[tuple[int, str]] = set()
    seen_keys: set[str] = set()
    for entry in sorted(
        entries,
        key=lambda row: (
            str(row["source_namespace"]),
            str(row["relative_path"]),
            str(row["sha256"]),
        ),
    ):
        key_material = {
            "source_namespace": entry["source_namespace"],
            "relative_path": entry["relative_path"],
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
            "observed_cutoff": cutoff,
        }
        occurrence_key = _sha256_bytes(_canonical_bytes(key_material))
        if occurrence_key in seen_keys:
            raise CandidateLedgerValidationError("source_occurrence_key_collision")
        seen_keys.add(occurrence_key)
        content_key = (int(entry["bytes"]), str(entry["sha256"]))
        if entry["sha256"] in invalid_report_sha256s:
            status = "rejected_invalid"
            reason = "strict_report_or_lineage_validation_failed"
        elif content_key in seen_content:
            status = "accepted_duplicate_occurrence"
            reason = "frozen_content_duplicate"
        elif (
            entry["source_namespace"] == "governed_inputs"
            and entry["sha256"] not in selected_governed_sha256s
        ):
            status = "superseded_by_precedence"
            reason = "frozen_governed_input_not_selected_by_candidate_load_order"
        elif entry["fusion_eligible"] is True:
            status = "accepted_new_occurrence"
            reason = "frozen_fusion_eligible_input"
        else:
            status = "quarantined_input"
            reason = "frozen_plan_or_documentation_non_fusion"
        seen_content.add(content_key)
        rows.append(
            {
                "occurrence_key": occurrence_key,
                **key_material,
                "source_kind": entry["source_kind"],
                "fusion_eligible": entry["fusion_eligible"],
                "status": status,
                "reason_code": reason,
                "source_cutoff_utc": cutoff,
                "input_evidence_sha256": input_evidence_sha256,
            }
        )
    rows.sort(key=lambda row: str(row["occurrence_key"]))
    return rows


def _classify_external_post(
    records: Sequence[tuple[str, str, bool]],
    *,
    start: object,
    end: object,
) -> str:
    window_start = _parse_utc(start, label="event_window")
    window_end = _parse_utc(end, label="event_window")
    if window_start >= window_end:
        raise CandidateLedgerValidationError("event_window_invalid")
    normalized: list[tuple[str, bool, bool]] = []
    for typename, created_at, strict_subreddit in records:
        try:
            in_window = (
                window_start
                <= _parse_utc(created_at, label="search_event_time")
                < window_end
            )
        except CandidateLedgerValidationError:
            in_window = False
        normalized.append((typename, in_window, strict_subreddit))
    if any(
        typename == "SubredditPost" and strict and in_window
        for typename, in_window, strict in normalized
    ):
        return "admissible_current_window_subreddit_post"
    if any(
        typename == "SubredditPost" and strict
        for typename, _in_window, strict in normalized
    ):
        return "window_outside_subreddit_post"
    if any(
        typename == "ProfilePost" and in_window
        for typename, in_window, _strict in normalized
    ):
        return "window_inside_profile_post"
    if any(
        typename == "ProfilePost" for typename, _in_window, _strict in normalized
    ):
        return "window_outside_profile_post"
    return "raw_id_without_strict_search_row"


def _external_posts(
    *,
    baseline_post_ids: set[str],
    report_root: Path,
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    report_counts: Counter[str] = Counter()
    external_ids: set[str] = set()
    for path in v2._report_paths([report_root], v2.COMMENT_REPORT_NAMES):
        try:
            report, _report_sha = v2._load_report(path)
        except v2.ReportContractError as exc:
            raise CandidateLedgerValidationError(
                "comment_report_envelope_invalid"
            ) from exc
        post_id = v2._normalize_post_id(report.get("post_id"))
        if post_id is None or POST_ID_RE.fullmatch(post_id) is None:
            raise CandidateLedgerValidationError("comment_report_post_id_invalid")
        if post_id not in baseline_post_ids:
            external_ids.add(post_id)
            report_counts[post_id] += 1

    search_records: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
    for path in v2._report_paths([report_root], v2.SEARCH_REPORT_NAMES):
        try:
            report, _report_sha = v2._load_report(path)
            payload, _payload_sha = v2._validated_report_payload(
                report,
                schemas=v2.SEARCH_SCHEMAS,
                endpoint=v2.ENDPOINTS["search"],
            )
            records, _terminal_empty = v2._strict_search_records(payload)
        except (v2.ReportContractError, ValueError) as exc:
            raise CandidateLedgerValidationError("search_report_invalid") from exc
        for wrapper, raw_row in records:
            post_id = v2._normalize_post_id(raw_row.get("id"))
            if post_id not in external_ids:
                continue
            strict_subreddit = False
            if raw_row.get("__typename") == "SubredditPost":
                try:
                    v2._semantic_primary_post(wrapper, raw_row)
                except v2.ReportContractError:
                    strict_subreddit = False
                else:
                    strict_subreddit = True
            search_records[post_id].append(
                (
                    str(raw_row.get("__typename") or ""),
                    str(raw_row.get("createdAt") or ""),
                    strict_subreddit,
                )
            )

    rows: list[dict[str, Any]] = []
    for post_id in sorted(external_ids):
        records = search_records.get(post_id, [])
        reason = _classify_external_post(
            records,
            start=window.get("start"),
            end=window.get("end"),
        )
        if reason == "admissible_current_window_subreddit_post":
            raise CandidateLedgerValidationError(
                "admissible_external_post_missing_from_candidate"
            )
        if reason not in EXTERNAL_REJECTION_REASONS:
            raise CandidateLedgerValidationError("external_post_reason_invalid")
        rows.append(
            {
                "post_id": post_id,
                "reason_code": reason,
                "comment_report_occurrence_count": report_counts[post_id],
                "strict_search_occurrence_count": len(records),
            }
        )
    return rows


def _selected_governed_sha256s(
    candidate_manifest: dict[str, Any],
    baseline_manifest: dict[str, Any],
    baseline_manifest_sha256: str,
) -> set[str]:
    boundaries = candidate_manifest.get("source_boundaries")
    tagging = candidate_manifest.get("tagging")
    baseline_files = baseline_manifest.get("files")
    if (
        not isinstance(boundaries, dict)
        or not isinstance(tagging, dict)
        or not isinstance(baseline_files, dict)
    ):
        raise CandidateLedgerValidationError("governed_selection_binding_invalid")
    historical = boundaries.get("historical_canonical")
    production = boundaries.get("tencent_production_primary")
    staging = boundaries.get("tencent_isolated_staging")
    product = tagging.get("product_entity_resolution")
    if (
        not isinstance(historical, dict)
        or not isinstance(production, dict)
        or not isinstance(staging, dict)
        or not isinstance(product, dict)
    ):
        raise CandidateLedgerValidationError("governed_selection_binding_invalid")
    values: list[object] = [
        baseline_manifest_sha256,
        historical.get("database_sha256"),
        production.get("snapshot_sha256"),
        staging.get("snapshot_sha256"),
        tagging.get("dictionary_sha256"),
        product.get("ledger_sha256"),
    ]
    for binding in baseline_files.values():
        if not isinstance(binding, dict):
            raise CandidateLedgerValidationError(
                "governed_selection_binding_invalid"
            )
        values.append(binding.get("sha256"))
    if any(
        not isinstance(value, str) or SHA256_RE.fullmatch(value) is None
        for value in values
    ):
        raise CandidateLedgerValidationError("governed_selection_binding_invalid")
    return {str(value) for value in values}


def _validated_pending_lineage(
    *,
    identity: dict[str, Any],
    identity_sha256: str,
    raw: dict[str, Any],
    candidate_manifest: dict[str, Any],
    candidate_post_ids: set[str],
) -> list[str]:
    identity_sets = identity.get("identity_sets")
    raw_posts = raw.get("posts")
    raw_accounting = raw.get("accounting")
    raw_target = raw.get("target")
    boundaries = candidate_manifest.get("source_boundaries")
    current_site = identity.get("current_site")
    if (
        not isinstance(identity_sets, list)
        or not isinstance(raw_posts, list)
        or not isinstance(raw_accounting, dict)
        or not isinstance(raw_target, dict)
        or not isinstance(boundaries, dict)
        or not isinstance(current_site, dict)
    ):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    discovery_rows = [
        row
        for row in identity_sets
        if isinstance(row, dict) and row.get("set_id") == "discovery_only"
    ]
    if len(discovery_rows) != 1:
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    global_rows = [
        row
        for row in identity_sets
        if isinstance(row, dict) and row.get("set_id") == "global_known"
    ]
    if len(global_rows) != 1:
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    discovery_row = discovery_rows[0]
    global_row = global_rows[0]
    discovery_values = discovery_row.get("post_ids")
    if not isinstance(discovery_values, list) or len(discovery_values) != len(
        set(discovery_values)
    ):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    discovery: set[str] = set()
    for post_id in discovery_values:
        if not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None:
            raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
        discovery.add(post_id)
    global_values = global_row.get("post_ids")
    if not isinstance(global_values, list) or len(global_values) != len(
        set(global_values)
    ):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    global_known: set[str] = set()
    for post_id in global_values:
        if not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None:
            raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
        global_known.add(post_id)
    if (
        discovery_row.get("count") != len(discovery)
        or discovery_row.get("lf_sha256") != _identity_hash(discovery)
        or global_row.get("count") != len(global_known)
        or global_row.get("lf_sha256") != _identity_hash(global_known)
        or any(POST_ID_RE.fullmatch(post_id) is None for post_id in candidate_post_ids)
        or current_site.get("count") != len(candidate_post_ids)
        or current_site.get("lf_sha256") != _identity_hash(candidate_post_ids)
    ):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    raw_post_ids: set[str] = set()
    for row in raw_posts:
        if not isinstance(row, dict):
            raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
        post_id = row.get("post_id")
        if not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None:
            raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
        if post_id in raw_post_ids:
            raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
        raw_post_ids.add(post_id)
    pending_values = raw_accounting.get("lineage_missing_post_ids")
    if not isinstance(pending_values, list) or len(pending_values) != len(
        set(pending_values)
    ):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    pending = set(pending_values)
    if any(
        not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None
        for post_id in pending
    ):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    expected_pending = discovery - raw_post_ids
    expected_global_pending = global_known - candidate_post_ids
    v2_boundary = boundaries.get("tencent_v2_search_hydrated")
    if not isinstance(v2_boundary, dict):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    boundary_values = v2_boundary.get("lineage_gap_post_ids")
    if not isinstance(boundary_values, list):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    boundary_pending = set(boundary_values)
    if (
        pending != expected_pending
        or pending != expected_global_pending
        or global_known != candidate_post_ids | pending
        or set(candidate_post_ids) & pending != set()
        or boundary_pending != expected_pending
        or len(boundary_values) != len(boundary_pending)
        or v2_boundary.get("lineage_gap_count") != len(expected_pending)
        or v2_boundary.get("lineage_gap_lf_sha256")
        != _identity_hash(expected_pending)
        or v2_boundary.get("target_count") != len(discovery)
        or v2_boundary.get("target_lf_sha256") != _identity_hash(discovery)
        or v2_boundary.get("admitted_posts") != len(raw_post_ids)
        or raw_target.get("count") != len(discovery)
        or raw_target.get("identity_inventory_sha256") != identity_sha256
        or raw_target.get("post_ids_sha256") != _identity_hash(discovery)
        or raw_post_ids | expected_pending != discovery
    ):
        raise CandidateLedgerValidationError("pending_lineage_binding_invalid")
    return sorted(expected_pending)


def _full_comment_scan(
    *,
    report_root: Path,
    post_universe: set[str],
    expected_report_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        scan = v2._scan_comment_reports([report_root], post_universe)
        reachable = v2._reachable_comment_reports(
            tuple(sorted(post_universe)),
            scan["first_pages"],
            scan["replies"],
        )
    except (v2.SnapshotContractError, v2.ReportContractError, ValueError) as exc:
        raise CandidateLedgerValidationError("comment_report_scan_invalid") from exc
    failures = scan.get("failures")
    if not isinstance(failures, list):
        raise CandidateLedgerValidationError("comment_report_scan_invalid")
    failure_hashes: set[str] = set()
    for failure in failures:
        if not isinstance(failure, dict):
            raise CandidateLedgerValidationError("comment_report_scan_invalid")
        report_sha = failure.get("report_sha256")
        kind = failure.get("report_kind")
        reason = failure.get("reason")
        if (
            not isinstance(report_sha, str)
            or SHA256_RE.fullmatch(report_sha) is None
            or report_sha in failure_hashes
            or kind not in {"first_page", "reply"}
            or not isinstance(reason, str)
            or not reason
        ):
            raise CandidateLedgerValidationError("comment_report_scan_invalid")
        failure_hashes.add(report_sha)
        if kind == "reply":
            cursor_sha = failure.get("cursor_sha256")
            if not isinstance(cursor_sha, str) or SHA256_RE.fullmatch(cursor_sha) is None:
                raise CandidateLedgerValidationError("comment_report_scan_invalid")
    accepted_count = len(scan["first_pages"]) + len(scan["replies"])
    if (
        scan.get("report_file_count") != expected_report_count
        or accepted_count + len(failures) != expected_report_count
        or scan.get("ignored_non_target") != 0
        or scan.get("duplicate_first_pages") != 0
        or scan.get("duplicate_replies") != 0
        or scan.get("conflicts") != []
        or reachable.get("orphan_replies") != []
        or reachable.get("cursor_cycles") != []
        or len(reachable.get("reports", [])) != accepted_count
    ):
        raise CandidateLedgerValidationError("comment_report_accounting_invalid")
    return scan, reachable


def _rejected_external_comment_rows(
    *,
    external_posts: Sequence[dict[str, Any]],
    scan: dict[str, Any],
    candidate_comment_ids: set[str],
    cutoff: str,
    input_evidence_sha256: str,
) -> list[dict[str, Any]]:
    reason_by_post = {
        str(row["post_id"]): str(row["reason_code"]) for row in external_posts
    }
    external_ids = set(reason_by_post)
    first_pages: dict[object, dict[str, Any]] = {
        key: value
        for key, value in scan["first_pages"].items()
        if str(key) in external_ids and isinstance(value, dict)
    }
    replies: dict[object, dict[str, Any]] = {
        key: value
        for key, value in scan["replies"].items()
        if isinstance(key, tuple)
        and len(key) == 2
        and str(key[0]) in external_ids
        and isinstance(value, dict)
    }
    reachable = v2._reachable_comment_reports(
        tuple(sorted(external_ids)), first_pages, replies
    )
    if reachable["orphan_replies"] or reachable["cursor_cycles"]:
        raise CandidateLedgerValidationError("external_comment_lineage_invalid")
    comments, conflicts = v2._merge_comments(reachable["reports"])
    if conflicts:
        raise CandidateLedgerValidationError("external_comment_conflict")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for comment in comments:
        comment_id = comment.get("comment_id")
        post_id = comment.get("post_id")
        if (
            not isinstance(comment_id, str)
            or COMMENT_ID_RE.fullmatch(comment_id) is None
            or comment_id in seen
            or comment_id in candidate_comment_ids
            or post_id not in reason_by_post
        ):
            raise CandidateLedgerValidationError("external_comment_outcome_invalid")
        seen.add(comment_id)
        rows.append(
            {
                "comment_id": comment_id,
                "status": "rejected",
                "reason_code": "parent_post_" + reason_by_post[str(post_id)],
                "baseline_location": "absent",
                "candidate_location": "absent",
                "baseline_managed_sha256": None,
                "candidate_managed_sha256": None,
                "source_managed_sha256": _managed_sha256(
                    comment, REJECTED_COMMENT_SOURCE_FIELDS
                ),
                "release_net_new": False,
                "include_in_voc_metrics": False,
                "deleted_or_removed": bool(comment.get("deleted_or_removed")),
                "parent_link_status": "parent_post_rejected",
                "source_cutoff_utc": cutoff,
                "input_evidence_sha256": input_evidence_sha256,
            }
        )
    rows.sort(key=lambda row: str(row["comment_id"]))
    return rows


def _expected_posts(
    baseline: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
    external: Sequence[dict[str, Any]],
    pending_ids: object,
    *,
    cutoff: str,
    input_evidence_sha256: str,
) -> list[dict[str, Any]]:
    if not set(baseline) <= set(candidate):
        raise CandidateLedgerValidationError("p0_not_subset_p1")
    rows: list[dict[str, Any]] = []
    for post_id in sorted(candidate):
        current = candidate[post_id]
        previous = baseline.get(post_id)
        candidate_sha = _managed_sha256(current, POST_MANAGED_FIELDS)
        baseline_sha = (
            _managed_sha256(previous, POST_MANAGED_FIELDS)
            if previous is not None
            else None
        )
        if previous is None:
            status = "newly_admitted"
            reason = "candidate_identity_absent_from_production_baseline"
        elif baseline_sha == candidate_sha:
            status = "existing_unchanged"
            reason = "managed_fields_equal"
        else:
            status = "existing_upgraded"
            reason = "managed_fields_changed"
        rows.append(
            {
                "post_id": post_id,
                "status": status,
                "reason_code": reason,
                "baseline_managed_sha256": baseline_sha,
                "candidate_managed_sha256": candidate_sha,
                "release_net_new": previous is None,
                "source_cutoff_utc": cutoff,
                "input_evidence_sha256": input_evidence_sha256,
            }
        )
    if not isinstance(pending_ids, list):
        raise CandidateLedgerValidationError("pending_lineage_set_invalid")
    pending_set = set(pending_ids)
    if len(pending_set) != len(pending_ids) or any(
        not isinstance(post_id, str)
        or POST_ID_RE.fullmatch(post_id) is None
        or post_id in baseline
        or post_id in candidate
        for post_id in pending_set
    ):
        raise CandidateLedgerValidationError("pending_lineage_set_invalid")
    for post_id in sorted(pending_set):
        rows.append(
            {
                "post_id": post_id,
                "status": "pending_lineage",
                "reason_code": "v2_search_identity_lineage_missing",
                "baseline_managed_sha256": None,
                "candidate_managed_sha256": None,
                "release_net_new": False,
                "source_cutoff_utc": cutoff,
                "input_evidence_sha256": input_evidence_sha256,
            }
        )
    seen_external: set[str] = set()
    for item in external:
        post_id = item.get("post_id")
        reason = item.get("reason_code")
        if (
            not isinstance(post_id, str)
            or POST_ID_RE.fullmatch(post_id) is None
            or post_id in baseline
            or post_id in candidate
            or post_id in pending_set
            or post_id in seen_external
            or reason not in EXTERNAL_REJECTION_REASONS
        ):
            raise CandidateLedgerValidationError("external_post_outcome_invalid")
        seen_external.add(post_id)
        rows.append(
            {
                "post_id": post_id,
                "status": "rejected",
                "reason_code": reason,
                "baseline_managed_sha256": None,
                "candidate_managed_sha256": None,
                "release_net_new": False,
                "comment_report_occurrence_count": item[
                    "comment_report_occurrence_count"
                ],
                "strict_search_occurrence_count": item[
                    "strict_search_occurrence_count"
                ],
                "source_cutoff_utc": cutoff,
                "input_evidence_sha256": input_evidence_sha256,
            }
        )
    rows.sort(key=lambda row: str(row["post_id"]))
    return rows


def _expected_comments(
    baseline_linked: dict[str, dict[str, Any]],
    baseline_quarantine: dict[str, dict[str, Any]],
    candidate_linked: dict[str, dict[str, Any]],
    candidate_quarantine: dict[str, dict[str, Any]],
    *,
    cutoff: str,
    input_evidence_sha256: str,
    rejected_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    c0 = set(baseline_linked) | set(baseline_quarantine)
    c1 = set(candidate_linked) | set(candidate_quarantine)
    if not c0 <= c1:
        raise CandidateLedgerValidationError("c0_not_subset_c1")
    rows: list[dict[str, Any]] = []
    for comment_id in sorted(c1):
        old_linked = baseline_linked.get(comment_id)
        old_quarantine = baseline_quarantine.get(comment_id)
        new_linked = candidate_linked.get(comment_id)
        new_quarantine = candidate_quarantine.get(comment_id)
        old_location = (
            "linked"
            if old_linked is not None
            else "quarantine"
            if old_quarantine is not None
            else "absent"
        )
        new_location = "linked" if new_linked is not None else "quarantine"
        baseline_sha = (
            _managed_sha256(old_linked, COMMENT_MANAGED_FIELDS)
            if old_linked is not None
            else _managed_sha256(old_quarantine, tuple(sorted(old_quarantine)))
            if old_quarantine is not None
            else None
        )
        if new_linked is not None:
            candidate_sha = _managed_sha256(new_linked, COMMENT_MANAGED_FIELDS)
        elif new_quarantine is not None:
            candidate_sha = _managed_sha256(
                new_quarantine, tuple(sorted(new_quarantine))
            )
        else:  # c1 is the exact union of the two candidate partitions.
            raise CandidateLedgerValidationError("candidate_comment_missing")
        if old_location == "absent":
            status = "new_linked" if new_location == "linked" else "new_quarantined"
            reason = "candidate_identity_absent_from_production_baseline"
        elif old_location == "quarantine" and new_location == "linked":
            status = "existing_quarantine_relinked"
            reason = "existing_identity_parent_link_restored"
        elif old_location == "quarantine":
            status = "existing_quarantine_retained"
            reason = "existing_quarantine_identity_retained"
        elif new_location == "quarantine":
            raise CandidateLedgerValidationError("linked_comment_regressed")
        elif baseline_sha == candidate_sha:
            status = "existing_unchanged"
            reason = "managed_fields_equal"
        else:
            status = "existing_upgraded"
            reason = "managed_fields_changed"
        rows.append(
            {
                "comment_id": comment_id,
                "status": status,
                "reason_code": reason,
                "baseline_location": old_location,
                "candidate_location": new_location,
                "baseline_managed_sha256": baseline_sha,
                "candidate_managed_sha256": candidate_sha,
                "release_net_new": old_location == "absent",
                "include_in_voc_metrics": (
                    new_linked.get("include_in_voc_metrics")
                    if new_linked is not None
                    else False
                ),
                "deleted_or_removed": (
                    bool(new_linked.get("deleted_or_removed"))
                    if new_linked is not None
                    else None
                ),
                "parent_link_status": (
                    new_linked.get("parent_link_status")
                    if new_linked is not None
                    else "quarantine"
                ),
                "source_cutoff_utc": cutoff,
                "input_evidence_sha256": input_evidence_sha256,
            }
        )
    candidate_ids = {str(row["comment_id"]) for row in rows}
    rejected_ids: set[str] = set()
    for row in rejected_rows:
        comment_id = row.get("comment_id")
        if (
            not isinstance(comment_id, str)
            or COMMENT_ID_RE.fullmatch(comment_id) is None
            or comment_id in candidate_ids
            or comment_id in rejected_ids
            or row.get("status") != "rejected"
        ):
            raise CandidateLedgerValidationError("rejected_comment_outcome_invalid")
        rejected_ids.add(comment_id)
        rows.append(dict(row))
    rows.sort(key=lambda row: str(row["comment_id"]))
    return rows


def _coverage_row(
    work_type: str,
    components: Sequence[str],
    *,
    status: str,
    reason: str,
    source: str,
    cutoff: str,
    input_evidence_sha256: str,
    report_sha256: str | None = None,
    report_failure_sha256: str | None = None,
) -> dict[str, Any]:
    if status not in COVERAGE_STATUSES:
        raise CandidateLedgerValidationError("coverage_status_invalid")
    if work_type == "lineage_gap":
        key = f"lineage:{components[0]}"
    elif work_type == "comment_cursor":
        key = f"cursor:{components[0]}:{components[1]}"
    elif work_type == "comment_page":
        key = f"comment_page:{components[0]}"
    elif work_type == "comment_first_page":
        key = f"comment_first_page:{components[0]}"
    elif work_type == "search_lane":
        key = f"search_lane:{components[0]}:{components[1]}"
    elif work_type == "partial_thread":
        key = f"partial_thread:{components[0]}"
    elif work_type == "failed_report":
        key = f"failed_report:{components[0]}"
    else:
        raise CandidateLedgerValidationError("coverage_work_type_invalid")
    if report_sha256 is not None and SHA256_RE.fullmatch(report_sha256) is None:
        raise CandidateLedgerValidationError("coverage_report_evidence_invalid")
    if (
        report_failure_sha256 is not None
        and SHA256_RE.fullmatch(report_failure_sha256) is None
    ):
        raise CandidateLedgerValidationError("coverage_report_evidence_invalid")
    failed = status in {"retryable_failed", "nonretryable_rejected"}
    if work_type in {"comment_first_page", "comment_cursor"}:
        if status == "closed_success":
            valid_report_evidence = (
                report_sha256 is not None and report_failure_sha256 is None
            )
        elif failed:
            valid_report_evidence = (
                report_sha256 is not None and report_failure_sha256 is not None
            )
        else:
            valid_report_evidence = (
                report_sha256 is None and report_failure_sha256 is None
            )
    else:
        valid_report_evidence = (
            report_sha256 is None and report_failure_sha256 is None
        )
    if not valid_report_evidence:
        raise CandidateLedgerValidationError("coverage_report_evidence_invalid")
    row: dict[str, Any] = {
        "work_item_key": key,
        "work_type": work_type,
        "status": status,
        "reason_code": reason,
        "source": source,
        "source_cutoff_utc": cutoff,
        "input_evidence_sha256": input_evidence_sha256,
    }
    if work_type == "search_lane":
        row["lane_index"] = int(components[0])
        row["term_sha256"] = components[1]
    elif work_type == "comment_cursor":
        row["post_id"] = components[0]
        row["cursor_sha256"] = components[1]
    elif work_type == "failed_report":
        row["report_failure_sha256"] = components[0]
    else:
        row["post_id"] = components[0]
    if report_sha256 is not None:
        row["report_sha256"] = report_sha256
    if report_failure_sha256 is not None:
        row["report_failure_sha256"] = report_failure_sha256
    return row


def _legacy_expected_coverage(
    identity: dict[str, Any],
    raw: dict[str, Any],
    hydration: dict[str, Any],
    candidate_manifest: dict[str, Any],
    *,
    cutoff: str,
    input_evidence_sha256: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lanes = identity.get("coverage_ledger")
    if not isinstance(lanes, list):
        raise CandidateLedgerValidationError("search_coverage_invalid")
    for lane in lanes:
        if not isinstance(lane, dict):
            raise CandidateLedgerValidationError("search_coverage_invalid")
        lane_index = lane.get("lane_index")
        term_sha = lane.get("term_sha256")
        terminal = lane.get("terminal")
        debt = lane.get("debt")
        if (
            not isinstance(lane_index, int)
            or isinstance(lane_index, bool)
            or not isinstance(term_sha, str)
            or SHA256_RE.fullmatch(term_sha) is None
            or not isinstance(terminal, bool)
            or not isinstance(debt, bool)
            or terminal == debt
        ):
            raise CandidateLedgerValidationError("search_coverage_invalid")
        rows.append(
            _coverage_row(
                "search_lane",
                (str(lane_index), term_sha),
                status="closed_no_more" if terminal else "open_carried",
                reason="search_lane_terminal" if terminal else "search_lane_has_next",
                source="v2_identity_freeze",
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
            )
        )
    raw_accounting = raw.get("accounting")
    raw_posts = raw.get("posts")
    hydration_work = hydration.get("coverage_work_items")
    if (
        not isinstance(raw_accounting, dict)
        or not isinstance(raw_posts, list)
        or not isinstance(hydration_work, dict)
    ):
        raise CandidateLedgerValidationError("coverage_source_shape_invalid")

    def add_post_rows(
        work_type: str,
        values: object,
        *,
        reason: str,
        source: str,
    ) -> None:
        if not isinstance(values, list) or len(values) != len(set(values)):
            raise CandidateLedgerValidationError("coverage_post_set_invalid")
        for post_id in values:
            if not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None:
                raise CandidateLedgerValidationError("coverage_post_set_invalid")
            rows.append(
                _coverage_row(
                    work_type,
                    (post_id,),
                    status="open_carried",
                    reason=reason,
                    source=source,
                    cutoff=cutoff,
                    input_evidence_sha256=input_evidence_sha256,
                )
            )

    add_post_rows(
        "lineage_gap",
        raw_accounting.get("lineage_missing_post_ids"),
        reason="post_lineage_missing",
        source="v2",
    )
    add_post_rows(
        "comment_first_page",
        raw_accounting.get("first_page_missing_post_ids"),
        reason="first_page_missing",
        source="v2",
    )
    add_post_rows(
        "comment_page",
        raw_accounting.get("page_pagination_outstanding_post_ids"),
        reason="page_pagination_outstanding",
        source="v2",
    )
    raw_cursors = raw_accounting.get("cursor_outstanding")
    if not isinstance(raw_cursors, list):
        raise CandidateLedgerValidationError("coverage_cursor_set_invalid")
    for item in raw_cursors:
        if not isinstance(item, dict):
            raise CandidateLedgerValidationError("coverage_cursor_set_invalid")
        post_id = item.get("post_id")
        cursor_sha = item.get("cursor_sha256")
        if (
            not isinstance(post_id, str)
            or POST_ID_RE.fullmatch(post_id) is None
            or not isinstance(cursor_sha, str)
            or SHA256_RE.fullmatch(cursor_sha) is None
        ):
            raise CandidateLedgerValidationError("coverage_cursor_set_invalid")
        rows.append(
            _coverage_row(
                "comment_cursor",
                (post_id, cursor_sha),
                status="open_carried",
                reason="cursor_outstanding",
                source="v2",
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
            )
        )
    for post in raw_posts:
        if not isinstance(post, dict):
            raise CandidateLedgerValidationError("raw_post_invalid")
        if post.get("coverage_grade") == "partial":
            post_id = post.get("post_id")
            if not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None:
                raise CandidateLedgerValidationError("raw_post_invalid")
            rows.append(
                _coverage_row(
                    "partial_thread",
                    (post_id,),
                    status="open_carried",
                    reason="thread_partial",
                    source="v2",
                    cutoff=cutoff,
                    input_evidence_sha256=input_evidence_sha256,
                )
            )

    add_post_rows(
        "comment_first_page",
        hydration_work.get("first_page_missing_post_ids"),
        reason="first_page_missing",
        source="existing_post_hydration",
    )
    add_post_rows(
        "comment_page",
        hydration_work.get("page_pagination_outstanding_post_ids"),
        reason="page_pagination_outstanding",
        source="existing_post_hydration",
    )
    add_post_rows(
        "partial_thread",
        hydration_work.get("partial_post_ids"),
        reason="thread_partial",
        source="existing_post_hydration",
    )
    hydration_cursors = hydration_work.get("cursor_outstanding")
    if not isinstance(hydration_cursors, list):
        raise CandidateLedgerValidationError("coverage_cursor_set_invalid")
    for item in hydration_cursors:
        if not isinstance(item, dict):
            raise CandidateLedgerValidationError("coverage_cursor_set_invalid")
        post_id = item.get("post_id")
        cursor_sha = item.get("cursor_sha256")
        if (
            not isinstance(post_id, str)
            or POST_ID_RE.fullmatch(post_id) is None
            or not isinstance(cursor_sha, str)
            or SHA256_RE.fullmatch(cursor_sha) is None
        ):
            raise CandidateLedgerValidationError("coverage_cursor_set_invalid")
        rows.append(
            _coverage_row(
                "comment_cursor",
                (post_id, cursor_sha),
                status="open_carried",
                reason="cursor_outstanding",
                source="existing_post_hydration",
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
            )
        )
    failures = hydration_work.get("failed_reports")
    if not isinstance(failures, list):
        raise CandidateLedgerValidationError("coverage_failure_set_invalid")
    for failure in failures:
        if not isinstance(failure, dict) or not isinstance(failure.get("reason"), str):
            raise CandidateLedgerValidationError("coverage_failure_set_invalid")
        failure_sha = _sha256_bytes(_canonical_bytes(failure))
        rows.append(
            _coverage_row(
                "failed_report",
                (failure_sha,),
                status="nonretryable_rejected",
                reason=str(failure["reason"]),
                source="existing_post_hydration",
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
            )
        )

    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["work_item_key"])
        previous = by_key.get(key)
        if previous is not None and previous != row:
            raise CandidateLedgerValidationError("coverage_work_item_conflict")
        by_key[key] = row
    ordered = [by_key[key] for key in sorted(by_key)]
    union = candidate_manifest.get("fusion_accounting", {}).get(
        "comment_coverage_debt_union"
    )
    if not isinstance(union, dict):
        raise CandidateLedgerValidationError("candidate_coverage_union_missing")
    counts = Counter(str(row["work_type"]) for row in ordered)
    expected_counts = {
        "comment_first_page": union.get("first_page_missing"),
        "comment_cursor": union.get("cursor_outstanding"),
        "comment_page": union.get("page_pagination_outstanding"),
        "failed_report": union.get("failed_reports"),
        "partial_thread": union.get("partial_threads"),
    }
    if any(counts[key] != value for key, value in expected_counts.items()):
        raise CandidateLedgerValidationError("coverage_union_count_mismatch")
    return ordered


def _expected_coverage(
    identity: dict[str, Any],
    *,
    pending_lineage_ids: Sequence[str],
    post_universe: set[str],
    scan: dict[str, Any],
    reachable: dict[str, Any],
    cutoff: str,
    input_evidence_sha256: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lanes = identity.get("coverage_ledger")
    if not isinstance(lanes, list):
        raise CandidateLedgerValidationError("search_coverage_invalid")
    for lane in lanes:
        if not isinstance(lane, dict):
            raise CandidateLedgerValidationError("search_coverage_invalid")
        lane_index = lane.get("lane_index")
        term_sha = lane.get("term_sha256")
        terminal = lane.get("terminal")
        debt = lane.get("debt")
        if (
            not isinstance(lane_index, int)
            or isinstance(lane_index, bool)
            or not isinstance(term_sha, str)
            or SHA256_RE.fullmatch(term_sha) is None
            or not isinstance(terminal, bool)
            or not isinstance(debt, bool)
            or terminal == debt
        ):
            raise CandidateLedgerValidationError("search_coverage_invalid")
        rows.append(
            _coverage_row(
                "search_lane",
                (str(lane_index), term_sha),
                status="closed_no_more" if terminal else "open_carried",
                reason="search_lane_terminal" if terminal else "search_lane_has_next",
                source="v2_identity_freeze",
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
            )
        )

    for post_id in sorted(pending_lineage_ids):
        if post_id not in post_universe:
            raise CandidateLedgerValidationError("lineage_work_item_invalid")
        rows.append(
            _coverage_row(
                "lineage_gap",
                (post_id,),
                status="open_carried",
                reason="post_lineage_missing",
                source="v2",
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
            )
        )

    first_pages = scan.get("first_pages")
    replies = scan.get("replies")
    failures = scan.get("failures")
    if (
        not isinstance(first_pages, dict)
        or not isinstance(replies, dict)
        or not isinstance(failures, list)
    ):
        raise CandidateLedgerValidationError("comment_coverage_scan_invalid")
    failed_first: dict[str, dict[str, Any]] = {}
    failed_reply: dict[tuple[str, str], dict[str, Any]] = {}
    for failure in failures:
        if not isinstance(failure, dict):
            raise CandidateLedgerValidationError("comment_coverage_scan_invalid")
        post_id = failure.get("post_id")
        report_sha = failure.get("report_sha256")
        reason = failure.get("reason")
        if not isinstance(post_id, str) or post_id not in post_universe:
            raise CandidateLedgerValidationError("comment_coverage_scan_invalid")
        if not isinstance(report_sha, str) or SHA256_RE.fullmatch(report_sha) is None:
            raise CandidateLedgerValidationError("comment_report_sha256_invalid")
        if reason not in COMMENT_REPORT_FAILURE_REASONS:
            raise CandidateLedgerValidationError(
                "comment_report_failure_reason_invalid"
            )
        if failure.get("report_kind") == "first_page":
            if post_id in failed_first:
                raise CandidateLedgerValidationError("comment_first_page_conflict")
            failed_first[post_id] = failure
        elif failure.get("report_kind") == "reply":
            cursor_sha = failure.get("cursor_sha256")
            if not isinstance(cursor_sha, str) or SHA256_RE.fullmatch(cursor_sha) is None:
                raise CandidateLedgerValidationError("comment_cursor_invalid")
            key = (post_id, cursor_sha)
            if key in failed_reply:
                raise CandidateLedgerValidationError("comment_cursor_conflict")
            failed_reply[key] = failure
        else:
            raise CandidateLedgerValidationError("comment_coverage_scan_invalid")

    if set(str(key) for key in first_pages) & set(failed_first):
        raise CandidateLedgerValidationError("comment_first_page_conflict")
    for post_id in sorted(post_universe):
        if post_id in first_pages:
            report = first_pages[post_id]
            if not isinstance(report, dict):
                raise CandidateLedgerValidationError("comment_report_sha256_invalid")
            report_sha = report.get("report_sha256")
            if not isinstance(report_sha, str) or SHA256_RE.fullmatch(report_sha) is None:
                raise CandidateLedgerValidationError("comment_report_sha256_invalid")
            status = "closed_success"
            reason = "first_page_report_validated"
            source = "frozen_comment_reports"
            report_failure_sha = None
        elif post_id in failed_first:
            report_sha = str(failed_first[post_id]["report_sha256"])
            report_failure_sha = _sha256_bytes(
                _canonical_bytes(failed_first[post_id])
            )
            status = "nonretryable_rejected"
            reason = str(failed_first[post_id]["reason"])
            source = "frozen_comment_reports"
        else:
            report_sha = None
            report_failure_sha = None
            status = "open_carried"
            reason = "first_page_missing"
            source = "candidate_post_universe"
        rows.append(
            _coverage_row(
                "comment_first_page",
                (post_id,),
                status=status,
                reason=reason,
                source=source,
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
                report_sha256=report_sha,
                report_failure_sha256=report_failure_sha,
            )
        )

    accepted_reply: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_key, report in replies.items():
        if (
            not isinstance(raw_key, tuple)
            or len(raw_key) != 2
            or not isinstance(report, dict)
        ):
            raise CandidateLedgerValidationError("comment_cursor_invalid")
        post_id = str(raw_key[0])
        cursor_sha = report.get("cursor_sha256")
        report_sha = report.get("report_sha256")
        if (
            post_id not in post_universe
            or not isinstance(cursor_sha, str)
            or SHA256_RE.fullmatch(cursor_sha) is None
            or not isinstance(report_sha, str)
            or SHA256_RE.fullmatch(report_sha) is None
        ):
            raise CandidateLedgerValidationError("comment_cursor_invalid")
        key = (post_id, cursor_sha)
        if key in accepted_reply:
            raise CandidateLedgerValidationError("comment_cursor_conflict")
        accepted_reply[key] = report
    outstanding_values = reachable.get("cursor_outstanding")
    if not isinstance(outstanding_values, list):
        raise CandidateLedgerValidationError("comment_cursor_invalid")
    outstanding: set[tuple[str, str]] = set()
    for item in outstanding_values:
        if not isinstance(item, dict):
            raise CandidateLedgerValidationError("comment_cursor_invalid")
        post_id = item.get("post_id")
        cursor_sha = item.get("cursor_sha256")
        if (
            not isinstance(post_id, str)
            or post_id not in post_universe
            or not isinstance(cursor_sha, str)
            or SHA256_RE.fullmatch(cursor_sha) is None
        ):
            raise CandidateLedgerValidationError("comment_cursor_invalid")
        outstanding.add((post_id, cursor_sha))
    if (
        set(accepted_reply) & set(failed_reply)
        or set(accepted_reply) & outstanding
        or set(failed_reply) & outstanding
        or len(outstanding) != len(outstanding_values)
    ):
        raise CandidateLedgerValidationError("comment_cursor_conflict")
    for key in sorted(set(accepted_reply) | set(failed_reply) | outstanding):
        if key in accepted_reply:
            report_sha = str(accepted_reply[key]["report_sha256"])
            report_failure_sha = None
            status = "closed_success"
            reason = "reply_report_validated"
            source = "frozen_comment_reports"
        elif key in failed_reply:
            report_sha = str(failed_reply[key]["report_sha256"])
            report_failure_sha = _sha256_bytes(
                _canonical_bytes(failed_reply[key])
            )
            status = "nonretryable_rejected"
            reason = str(failed_reply[key]["reason"])
            source = "frozen_comment_reports"
        else:
            report_sha = None
            report_failure_sha = None
            status = "open_carried"
            reason = "cursor_outstanding"
            source = "derived_comment_coverage"
        rows.append(
            _coverage_row(
                "comment_cursor",
                key,
                status=status,
                reason=reason,
                source=source,
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
                report_sha256=report_sha,
                report_failure_sha256=report_failure_sha,
            )
        )

    page_values = reachable.get("page_has_next")
    if not isinstance(page_values, list) or len(page_values) != len(set(page_values)):
        raise CandidateLedgerValidationError("comment_page_invalid")
    for post_id in sorted(page_values):
        if not isinstance(post_id, str) or post_id not in post_universe:
            raise CandidateLedgerValidationError("comment_page_invalid")
        rows.append(
            _coverage_row(
                "comment_page",
                (post_id,),
                status="open_carried",
                reason="page_pagination_outstanding",
                source="derived_comment_coverage",
                cutoff=cutoff,
                input_evidence_sha256=input_evidence_sha256,
            )
        )

    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["work_item_key"])
        if key in by_key:
            raise CandidateLedgerValidationError("coverage_work_item_conflict")
        by_key[key] = row
    return [by_key[key] for key in sorted(by_key)]


def _ledger_meta(path: Path, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"rows": len(rows), "bytes": len(payload), "sha256": _sha256_bytes(payload)}


def _identity_set(values: set[str]) -> dict[str, Any]:
    return {"count": len(values), "ids_lf_sha256": _identity_hash(values)}


def _source_identity_values(
    rows: object,
    *,
    field: str,
    pattern: re.Pattern[str],
    label: str,
) -> set[str]:
    if not isinstance(rows, list):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    values: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise CandidateLedgerValidationError(f"{label}_invalid")
        value = row.get(field)
        if (
            not isinstance(value, str)
            or pattern.fullmatch(value) is None
            or value in values
        ):
            raise CandidateLedgerValidationError(f"{label}_invalid")
        values.add(value)
    return values


def _expected_source_identity_universe(
    *,
    raw: dict[str, Any],
    hydration: dict[str, Any],
    pending_lineage_ids: Sequence[str],
    external_post_ids: set[str],
    rejected_comment_rows: Sequence[dict[str, Any]],
    baseline_comment_ids: set[str],
    candidate_comment_ids: set[str],
) -> dict[str, Any]:
    raw_post_ids = _source_identity_values(
        raw.get("posts"),
        field="post_id",
        pattern=POST_ID_RE,
        label="source_universe_raw_posts",
    )
    raw_comment_ids = _source_identity_values(
        raw.get("comments"),
        field="comment_id",
        pattern=COMMENT_ID_RE,
        label="source_universe_raw_comments",
    )
    hydration_comment_ids = _source_identity_values(
        hydration.get("comments"),
        field="comment_id",
        pattern=COMMENT_ID_RE,
        label="source_universe_hydration_comments",
    )
    pending = set(pending_lineage_ids)
    if len(pending) != len(pending_lineage_ids) or any(
        POST_ID_RE.fullmatch(value) is None for value in pending
    ):
        raise CandidateLedgerValidationError("source_universe_pending_invalid")
    if any(POST_ID_RE.fullmatch(value) is None for value in external_post_ids):
        raise CandidateLedgerValidationError("source_universe_external_posts_invalid")
    rejected_comment_ids: set[str] = set()
    for row in rejected_comment_rows:
        comment_id = row.get("comment_id")
        if (
            not isinstance(comment_id, str)
            or COMMENT_ID_RE.fullmatch(comment_id) is None
            or comment_id in rejected_comment_ids
        ):
            raise CandidateLedgerValidationError(
                "source_universe_external_comments_invalid"
            )
        rejected_comment_ids.add(comment_id)
    if rejected_comment_ids & candidate_comment_ids:
        raise CandidateLedgerValidationError(
            "source_universe_external_comments_invalid"
        )
    expected_candidate_comment_ids = (
        baseline_comment_ids | raw_comment_ids | hydration_comment_ids
    )
    if candidate_comment_ids != expected_candidate_comment_ids:
        raise CandidateLedgerValidationError("candidate_comment_source_union_invalid")
    return {
        "v2_raw_posts": _identity_set(raw_post_ids),
        "v2_lineage_pending_posts": _identity_set(pending),
        "governed_external_rejected_posts": _identity_set(external_post_ids),
        "v2_raw_comments": _identity_set(raw_comment_ids),
        "existing_hydration_comments": _identity_set(hydration_comment_ids),
        "governed_external_rejected_comments": _identity_set(
            rejected_comment_ids
        ),
        "candidate_comment_union_exact": True,
    }


def _validate_source_identity_universe(
    actual: object,
    expected: dict[str, Any],
) -> None:
    if actual != expected:
        raise CandidateLedgerValidationError("source_identity_universe_invalid")


def _coverage_post_id_set(values: object, *, label: str) -> set[str]:
    if not isinstance(values, list):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    result: set[str] = set()
    for value in values:
        if (
            not isinstance(value, str)
            or POST_ID_RE.fullmatch(value) is None
            or value in result
        ):
            raise CandidateLedgerValidationError(f"{label}_invalid")
        result.add(value)
    return result


def _coverage_cursor_keys(
    values: object, *, label: str
) -> tuple[set[str], set[str]]:
    if not isinstance(values, list):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    keys: set[str] = set()
    post_ids: set[str] = set()
    for row in values:
        if not isinstance(row, dict):
            raise CandidateLedgerValidationError(f"{label}_invalid")
        post_id = row.get("post_id")
        cursor_sha = row.get("cursor_sha256")
        if (
            not isinstance(post_id, str)
            or POST_ID_RE.fullmatch(post_id) is None
            or not isinstance(cursor_sha, str)
            or SHA256_RE.fullmatch(cursor_sha) is None
        ):
            raise CandidateLedgerValidationError(f"{label}_invalid")
        key = f"{post_id}\t{cursor_sha}"
        if key in keys:
            raise CandidateLedgerValidationError(f"{label}_invalid")
        keys.add(key)
        post_ids.add(post_id)
    return keys, post_ids


def _coverage_failure_keys(
    values: object, *, label: str
) -> tuple[set[str], set[str], Counter[str]]:
    if not isinstance(values, list):
        raise CandidateLedgerValidationError(f"{label}_invalid")
    keys: set[str] = set()
    post_ids: set[str] = set()
    reasons: Counter[str] = Counter()
    for row in values:
        if not isinstance(row, dict):
            raise CandidateLedgerValidationError(f"{label}_invalid")
        post_id = row.get("post_id")
        report_sha = row.get("report_sha256")
        reason = row.get("reason")
        if (
            not isinstance(post_id, str)
            or POST_ID_RE.fullmatch(post_id) is None
            or not isinstance(report_sha, str)
            or SHA256_RE.fullmatch(report_sha) is None
            or reason not in COMMENT_REPORT_FAILURE_REASONS
        ):
            raise CandidateLedgerValidationError(f"{label}_invalid")
        key = _sha256_bytes(_canonical_bytes(row))
        if key in keys:
            raise CandidateLedgerValidationError(f"{label}_invalid")
        keys.add(key)
        post_ids.add(post_id)
        reasons[str(reason)] += 1
    return keys, post_ids, reasons


def _expected_candidate_coverage_union(
    raw: dict[str, Any],
    hydration: dict[str, Any],
    *,
    governed_post_ids: set[str],
) -> dict[str, Any]:
    if any(POST_ID_RE.fullmatch(value) is None for value in governed_post_ids):
        raise CandidateLedgerValidationError("coverage_governed_partition_invalid")
    raw_accounting = raw.get("accounting")
    raw_posts = raw.get("posts")
    hydration_work = hydration.get("coverage_work_items")
    if (
        not isinstance(raw_accounting, dict)
        or not isinstance(raw_posts, list)
        or not isinstance(hydration_work, dict)
    ):
        raise CandidateLedgerValidationError("candidate_coverage_union_invalid")
    raw_first = _coverage_post_id_set(
        raw_accounting.get("first_page_missing_post_ids"),
        label="coverage_raw_first_page",
    )
    raw_cursor, raw_cursor_posts = _coverage_cursor_keys(
        raw_accounting.get("cursor_outstanding"), label="coverage_raw_cursor"
    )
    raw_page = _coverage_post_id_set(
        raw_accounting.get("page_pagination_outstanding_post_ids"),
        label="coverage_raw_page",
    )
    raw_failure, raw_failure_posts, _raw_failure_reasons = _coverage_failure_keys(
        raw_accounting.get("failed_reports"), label="coverage_raw_failure"
    )
    hydration_first = _coverage_post_id_set(
        hydration_work.get("first_page_missing_post_ids"),
        label="coverage_hydration_first_page",
    )
    hydration_cursor, hydration_cursor_posts = _coverage_cursor_keys(
        hydration_work.get("cursor_outstanding"),
        label="coverage_hydration_cursor",
    )
    hydration_page = _coverage_post_id_set(
        hydration_work.get("page_pagination_outstanding_post_ids"),
        label="coverage_hydration_page",
    )
    hydration_failure, hydration_failure_posts, hydration_failure_reasons = (
        _coverage_failure_keys(
            hydration_work.get("failed_reports"),
            label="coverage_hydration_failure",
        )
    )
    hydration_partial = _coverage_post_id_set(
        hydration_work.get("partial_post_ids"),
        label="coverage_hydration_partial",
    )
    hydration_not_observed = _coverage_post_id_set(
        hydration_work.get("not_observed_post_ids"),
        label="coverage_hydration_not_observed",
    )
    if hydration_not_observed != hydration_first:
        raise CandidateLedgerValidationError("candidate_coverage_union_invalid")
    raw_partial: set[str] = set()
    raw_post_seen: set[str] = set()
    for row in raw_posts:
        if not isinstance(row, dict):
            raise CandidateLedgerValidationError("coverage_raw_posts_invalid")
        post_id = row.get("post_id")
        if (
            not isinstance(post_id, str)
            or POST_ID_RE.fullmatch(post_id) is None
            or post_id in raw_post_seen
        ):
            raise CandidateLedgerValidationError("coverage_raw_posts_invalid")
        raw_post_seen.add(post_id)
        if row.get("coverage_grade") == "partial":
            raw_partial.add(post_id)
    all_debt_post_ids = (
        raw_first
        | raw_cursor_posts
        | raw_page
        | raw_failure_posts
        | raw_partial
        | hydration_first
        | hydration_cursor_posts
        | hydration_page
        | hydration_failure_posts
        | hydration_partial
        | hydration_not_observed
    )
    if not all_debt_post_ids <= governed_post_ids:
        raise CandidateLedgerValidationError("coverage_governed_partition_invalid")
    first = raw_first | hydration_first
    cursor = raw_cursor | hydration_cursor
    page = raw_page | hydration_page
    failures = raw_failure | hydration_failure
    partial = raw_partial | hydration_partial
    return {
        "first_page_missing": len(first),
        "first_page_missing_lf_sha256": _identity_hash(first),
        "cursor_outstanding": len(cursor),
        "cursor_outstanding_lf_sha256": _identity_hash(cursor),
        "page_pagination_outstanding": len(page),
        "page_pagination_outstanding_lf_sha256": _identity_hash(page),
        "failed_reports": len(failures),
        "failed_reports_lf_sha256": _identity_hash(failures),
        "partial_threads": len(partial),
        "partial_thread_ids_lf_sha256": _identity_hash(partial),
        "not_observed_threads": len(first),
        "not_observed_thread_ids_lf_sha256": _identity_hash(first),
        "source_counts": {
            "v2": {
                "first_page_missing": len(raw_first),
                "cursor_outstanding": len(raw_cursor),
                "page_pagination_outstanding": len(raw_page),
                "failed_reports": len(raw_failure),
            },
            "existing_post_hydration": {
                "first_page_missing": len(hydration_first),
                "cursor_outstanding": len(hydration_cursor),
                "page_pagination_outstanding": len(hydration_page),
                "failed_reports": len(hydration_failure),
                "partial_threads": len(hydration_partial),
                "not_observed_threads": len(hydration_not_observed),
                "failure_reason_counts": dict(
                    sorted(hydration_failure_reasons.items())
                ),
            },
        },
        "key_union_not_numeric_sum": True,
    }


def _validate_candidate_coverage_union(
    candidate_manifest: dict[str, Any],
    raw: dict[str, Any],
    hydration: dict[str, Any],
    *,
    governed_post_ids: set[str],
) -> None:
    fusion = candidate_manifest.get("fusion_accounting")
    if not isinstance(fusion, dict):
        raise CandidateLedgerValidationError("candidate_coverage_union_invalid")
    actual = fusion.get("comment_coverage_debt_union")
    expected = _expected_candidate_coverage_union(
        raw, hydration, governed_post_ids=governed_post_ids
    )
    if actual != expected:
        raise CandidateLedgerValidationError("candidate_coverage_union_invalid")


def validate(
    *,
    builder_code: Path,
    source_freeze_manifest: Path,
    baseline_base_dir: Path,
    candidate_base_dir: Path,
    v2_identity_freeze: Path,
    v2_raw_snapshot: Path,
    existing_post_hydration_snapshot: Path,
    report_root: Path,
    candidate_root: Path,
    expected_governed_external_exclusions: int | None = None,
) -> dict[str, Any]:
    _directory(candidate_root, label="candidate_root", mode=0o700)
    try:
        bundle_members = {path.name for path in candidate_root.iterdir()}
    except OSError as exc:
        raise CandidateLedgerValidationError("candidate_root_unsafe") from exc
    if bundle_members != EXPECTED_BUNDLE_MEMBERS:
        raise CandidateLedgerValidationError("candidate_member_set_invalid")
    for name in EXPECTED_BUNDLE_MEMBERS:
        _regular_file(candidate_root / name, label="candidate_member", mode=0o600)

    source_freeze, source_entries, cutoff = _validated_source_freeze(
        source_freeze_manifest,
        report_root,
    )
    baseline = _validated_base(baseline_base_dir, label="baseline_base")
    candidate = _validated_base(candidate_base_dir, label="candidate_base")
    identity = _load_json(v2_identity_freeze, label="v2_identity_freeze")
    raw = _load_json(v2_raw_snapshot, label="v2_raw_snapshot")
    hydration = _load_json(
        existing_post_hydration_snapshot,
        label="existing_post_hydration_snapshot",
    )
    if identity.get("schema_version") != IDENTITY_SCHEMA:
        raise CandidateLedgerValidationError("v2_identity_schema_invalid")
    if raw.get("schema_version") != RAW_SCHEMA:
        raise CandidateLedgerValidationError("v2_raw_schema_invalid")
    if hydration.get("schema_version") != HYDRATION_SCHEMA:
        raise CandidateLedgerValidationError("hydration_schema_invalid")
    for field, expected in BOUNDARIES.items():
        if hydration.get(field) is not expected:
            raise CandidateLedgerValidationError("hydration_boundary_invalid")

    input_hashes = {
        "source_freeze_manifest_sha256": _file_sha256(source_freeze_manifest),
        "production_baseline_manifest_sha256": baseline["manifest_sha256"],
        "candidate_base_manifest_sha256": candidate["manifest_sha256"],
        "v2_identity_freeze_sha256": _file_sha256(v2_identity_freeze),
        "v2_raw_snapshot_sha256": _file_sha256(v2_raw_snapshot),
        "existing_post_hydration_snapshot_sha256": _file_sha256(
            existing_post_hydration_snapshot
        ),
    }
    input_evidence_sha256 = _sha256_bytes(_canonical_bytes(input_hashes))

    candidate_manifest = candidate["manifest"]
    source_boundaries = candidate_manifest.get("source_boundaries")
    hydration_source = hydration.get("source")
    if not isinstance(source_boundaries, dict) or not isinstance(hydration_source, dict):
        raise CandidateLedgerValidationError("candidate_source_binding_invalid")
    v2_boundary = source_boundaries.get("tencent_v2_search_hydrated")
    hydration_boundary = source_boundaries.get(
        "tencent_existing_post_comment_hydration"
    )
    if (
        not isinstance(v2_boundary, dict)
        or not isinstance(hydration_boundary, dict)
        or v2_boundary.get("snapshot_sha256") != input_hashes["v2_raw_snapshot_sha256"]
        or v2_boundary.get("identity_freeze_sha256")
        != input_hashes["v2_identity_freeze_sha256"]
        or hydration_boundary.get("snapshot_sha256")
        != input_hashes["existing_post_hydration_snapshot_sha256"]
        or hydration_source.get("base_manifest_sha256")
        != input_hashes["production_baseline_manifest_sha256"]
        or hydration_source.get("source_freeze_manifest_sha256")
        != input_hashes["source_freeze_manifest_sha256"]
        or hydration_source.get("discovery_snapshot_sha256")
        != input_hashes["v2_raw_snapshot_sha256"]
        or hydration_source.get("source_cutoff_utc") != cutoff
        or identity.get("freeze_cutoff_utc") != cutoff
    ):
        raise CandidateLedgerValidationError("candidate_source_binding_invalid")

    pending_lineage_ids = _validated_pending_lineage(
        identity=identity,
        identity_sha256=input_hashes["v2_identity_freeze_sha256"],
        raw=raw,
        candidate_manifest=candidate_manifest,
        candidate_post_ids=set(candidate["posts"]),
    )

    manifest_path = candidate_root / MANIFEST_NAME
    manifest = _load_json(manifest_path, label="candidate_ledger_manifest")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateLedgerValidationError("candidate_manifest_inputs_invalid")
    builder_code_sha256 = _validate_builder_code_binding(
        builder_code, inputs.get("builder_code_sha256")
    )
    ledgers = {
        name: _load_jsonl(candidate_root / name, label=name.removesuffix(".jsonl"))
        for name in LEDGER_NAMES
    }

    window = identity.get("target_window_utc")
    raw_accounting = raw.get("accounting")
    if not isinstance(window, dict) or not isinstance(raw_accounting, dict):
        raise CandidateLedgerValidationError("v2_identity_or_raw_invalid")
    external = _external_posts(
        baseline_post_ids=set(candidate["posts"]),
        report_root=report_root,
        window=window,
    )
    if (
        expected_governed_external_exclusions is not None
        and len(external) != expected_governed_external_exclusions
    ):
        raise CandidateLedgerValidationError("external_exclusion_count_unexpected")
    external_post_ids = {str(row["post_id"]) for row in external}
    post_universe = (
        set(candidate["posts"]) | set(pending_lineage_ids) | external_post_ids
    )
    expected_comment_report_count = sum(
        Path(str(row["relative_path"])).name in v2.COMMENT_REPORT_NAMES
        for row in source_entries
        if row["source_namespace"] == "tencent_v2_reports"
    )
    scan, reachable = _full_comment_scan(
        report_root=report_root,
        post_universe=post_universe,
        expected_report_count=expected_comment_report_count,
    )
    invalid_report_sha256s = {
        str(row["report_sha256"]) for row in scan["failures"]
    }
    selected_governed_sha256s = _selected_governed_sha256s(
        candidate_manifest,
        baseline["manifest"],
        str(baseline["manifest_sha256"]),
    )
    expected_occurrences = _expected_occurrences(
        source_entries,
        cutoff=cutoff,
        input_evidence_sha256=input_evidence_sha256,
        invalid_report_sha256s=invalid_report_sha256s,
        selected_governed_sha256s=selected_governed_sha256s,
    )
    expected_posts = _expected_posts(
        baseline["posts"],
        candidate["posts"],
        external,
        pending_lineage_ids,
        cutoff=cutoff,
        input_evidence_sha256=input_evidence_sha256,
    )
    candidate_comment_ids = set(candidate["comments"]) | set(candidate["quarantine"])
    rejected_comment_rows = _rejected_external_comment_rows(
        external_posts=external,
        scan=scan,
        candidate_comment_ids=candidate_comment_ids,
        cutoff=cutoff,
        input_evidence_sha256=input_evidence_sha256,
    )
    baseline_comment_ids = set(baseline["comments"]) | set(
        baseline["quarantine"]
    )
    expected_source_identity_universe = _expected_source_identity_universe(
        raw=raw,
        hydration=hydration,
        pending_lineage_ids=pending_lineage_ids,
        external_post_ids=external_post_ids,
        rejected_comment_rows=rejected_comment_rows,
        baseline_comment_ids=baseline_comment_ids,
        candidate_comment_ids=candidate_comment_ids,
    )
    _validate_source_identity_universe(
        manifest.get("source_identity_universe"),
        expected_source_identity_universe,
    )
    _validate_candidate_coverage_union(
        candidate_manifest,
        raw,
        hydration,
        governed_post_ids=set(candidate["posts"]) | set(pending_lineage_ids),
    )
    expected_candidate_coverage_union = _expected_candidate_coverage_union(
        raw,
        hydration,
        governed_post_ids=set(candidate["posts"]) | set(pending_lineage_ids),
    )
    expected_comments = _expected_comments(
        baseline["comments"],
        baseline["quarantine"],
        candidate["comments"],
        candidate["quarantine"],
        cutoff=cutoff,
        input_evidence_sha256=input_evidence_sha256,
        rejected_rows=rejected_comment_rows,
    )
    expected_coverage = _expected_coverage(
        identity,
        pending_lineage_ids=pending_lineage_ids,
        post_universe=post_universe,
        scan=scan,
        reachable=reachable,
        cutoff=cutoff,
        input_evidence_sha256=input_evidence_sha256,
    )
    expected_by_name = {
        "source-occurrence-ledger.jsonl": expected_occurrences,
        "post-identity-delta-ledger.jsonl": expected_posts,
        "comment-identity-delta-ledger.jsonl": expected_comments,
        "coverage-work-ledger.jsonl": expected_coverage,
    }
    for name, expected in expected_by_name.items():
        if ledgers[name] != expected:
            raise CandidateLedgerValidationError(
                f"{name.removesuffix('.jsonl').replace('-', '_')}_mismatch"
            )

    for rows, key, allowed, label in (
        (expected_occurrences, "occurrence_key", OCCURRENCE_STATUSES, "occurrence"),
        (expected_posts, "post_id", POST_STATUSES, "post"),
        (expected_comments, "comment_id", COMMENT_STATUSES, "comment"),
        (expected_coverage, "work_item_key", COVERAGE_STATUSES, "coverage"),
    ):
        keys = [row.get(key) for row in rows]
        if len(keys) != len(set(keys)) or any(row.get("status") not in allowed for row in rows):
            raise CandidateLedgerValidationError(f"{label}_ledger_nonunique")
        if any(
            row.get("source_cutoff_utc") != cutoff
            or row.get("input_evidence_sha256") != input_evidence_sha256
            or not isinstance(row.get("reason_code"), str)
            or not row.get("reason_code")
            for row in rows
        ):
            raise CandidateLedgerValidationError(f"{label}_ledger_evidence_invalid")

    p0 = set(baseline["posts"])
    l0 = set(baseline["comments"])
    q0 = set(baseline["quarantine"])
    c0 = l0 | q0
    p1 = set(candidate["posts"])
    l1 = set(candidate["comments"])
    q1 = set(candidate["quarantine"])
    c1 = l1 | q1
    identity_sets = {
        "p0": _identity_set(p0),
        "l0": _identity_set(l0),
        "q0": _identity_set(q0),
        "c0": _identity_set(c0),
        "p1": _identity_set(p1),
        "l1": _identity_set(l1),
        "q1": _identity_set(q1),
        "c1": _identity_set(c1),
    }
    occurrence_counts = Counter(str(row["status"]) for row in expected_occurrences)
    post_counts = Counter(str(row["status"]) for row in expected_posts)
    comment_counts = Counter(str(row["status"]) for row in expected_comments)
    coverage_counts = Counter(str(row["status"]) for row in expected_coverage)
    coverage_types = Counter(str(row["work_type"]) for row in expected_coverage)
    net_new_posts = p1 - p0
    net_new_comments = c1 - c0
    expected_accounting = {
        "source_occurrences": {
            "total": len(expected_occurrences),
            "invalid_comment_report_occurrences": occurrence_counts[
                "rejected_invalid"
            ],
            "status_counts": dict(sorted(occurrence_counts.items())),
            "unaccounted": 0,
        },
        "posts": {
            "baseline": len(p0),
            "candidate": len(p1),
            "release_net_new": len(net_new_posts),
            "governed_external_exclusions": len(external),
            "pending_lineage": post_counts["pending_lineage"],
            "status_counts": dict(sorted(post_counts.items())),
            "unaccounted": 0,
        },
        "comments": {
            "baseline": len(c0),
            "candidate": len(c1),
            "release_net_new": len(net_new_comments),
            "rejected_candidates": comment_counts["rejected"],
            "release_net_new_in_voc": sum(
                row["status"] in {"new_linked", "new_quarantined"}
                and row["include_in_voc_metrics"] is True
                for row in expected_comments
            ),
            "release_net_new_excluded_from_voc": sum(
                row["status"] in {"new_linked", "new_quarantined"}
                and row["include_in_voc_metrics"] is False
                for row in expected_comments
            ),
            "status_counts": dict(sorted(comment_counts.items())),
            "unaccounted": 0,
        },
        "coverage": {
            "total": len(expected_coverage),
            "status_counts": dict(sorted(coverage_counts.items())),
            "work_type_counts": dict(sorted(coverage_types.items())),
            "unaccounted": 0,
        },
        "unaccounted_total": 0,
    }
    expected_relations = {
        "p0_subset_p1": p0 <= p1,
        "c0_subset_c1": c0 <= c1,
        "l1_intersection_q1_empty": not (l1 & q1),
        "all_linked_comment_parents_exist": all(
            row.get("post_id") in p1 for row in candidate["comments"].values()
        ),
        "release_net_new_post_ids_lf_sha256": _identity_hash(net_new_posts),
        "release_net_new_comment_ids_lf_sha256": _identity_hash(net_new_comments),
        "pending_lineage_post_ids_lf_sha256": _identity_hash(pending_lineage_ids),
    }
    expected_ledger_meta = {
        name: _ledger_meta(candidate_root / name, ledgers[name]) for name in LEDGER_NAMES
    }
    expected_top_keys = {
        "schema_version",
        "status",
        "source_cutoff_utc",
        "input_evidence_sha256",
        "inputs",
        "identity_sets",
        "source_identity_universe",
        "ledgers",
        "accounting",
        "set_relations",
        "privacy",
        *BOUNDARIES,
    }
    if (
        set(manifest) != expected_top_keys
        or manifest.get("schema_version") != MANIFEST_SCHEMA
        or manifest.get("status") != "a2_identity_closed_with_explicit_coverage_debt"
        or manifest.get("source_cutoff_utc") != cutoff
        or manifest.get("input_evidence_sha256") != input_evidence_sha256
        or not isinstance(inputs, dict)
        or {key: inputs.get(key) for key in input_hashes} != input_hashes
        or set(inputs) != {*input_hashes, "builder_code_sha256"}
        or inputs.get("builder_code_sha256") != builder_code_sha256
        or manifest.get("identity_sets") != identity_sets
        or manifest.get("source_identity_universe")
        != expected_source_identity_universe
        or manifest.get("ledgers") != expected_ledger_meta
        or manifest.get("accounting") != expected_accounting
        or manifest.get("set_relations") != expected_relations
        or manifest.get("privacy")
        != {
            "private_artifact": True,
            "raw_payload_embedded": False,
            "raw_username_embedded": False,
            "post_or_comment_body_in_ledgers": False,
        }
        or any(manifest.get(field) is not expected for field, expected in BOUNDARIES.items())
    ):
        raise CandidateLedgerValidationError("candidate_manifest_contract_invalid")
    if not all(expected_relations.values()):
        raise CandidateLedgerValidationError("identity_set_relation_invalid")
    if any(expected_accounting[key]["unaccounted"] != 0 for key in (
        "source_occurrences",
        "posts",
        "comments",
        "coverage",
    )) or expected_accounting["unaccounted_total"] != 0:
        raise CandidateLedgerValidationError("unaccounted_nonzero")

    validator_code_path = Path(__file__)
    _regular_file(validator_code_path, label="validator_code")
    validator_code_sha256 = _file_sha256(validator_code_path)
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": "passed",
        "evidence_grade": "L2_local_independent_validation",
        "candidate_ledger_manifest_sha256": _file_sha256(manifest_path),
        "builder_code_sha256": builder_code_sha256,
        "validator_code_sha256": validator_code_sha256,
        "source_cutoff_utc": cutoff,
        "input_evidence_sha256": input_evidence_sha256,
        "accounting_rates": {
            "source_occurrences": 1,
            "posts": 1,
            "comments": 1,
            "coverage": 1,
        },
        "counts": {
            "source_occurrences": len(expected_occurrences),
            "post_rows": len(expected_posts),
            "comment_rows": len(expected_comments),
            "coverage_rows": len(expected_coverage),
            "coverage_status_counts": dict(sorted(coverage_counts.items())),
            "coverage_work_type_counts": dict(sorted(coverage_types.items())),
            "governed_external_exclusions": len(external),
            "rejected_comment_candidates": comment_counts["rejected"],
            "invalid_comment_report_occurrences": occurrence_counts[
                "rejected_invalid"
            ],
            "pending_lineage": post_counts["pending_lineage"],
            "pending_lineage_ids_lf_sha256": _identity_hash(
                pending_lineage_ids
            ),
            "existing_post_upgrades": post_counts["existing_upgraded"],
            "release_net_new_posts": len(net_new_posts),
            "release_net_new_comments": len(net_new_comments),
            "unaccounted_total": 0,
        },
        "identity_sets": identity_sets,
        "source_identity_universe": expected_source_identity_universe,
        "candidate_coverage_union_sha256": _sha256_bytes(
            _canonical_bytes(expected_candidate_coverage_union)
        ),
        **BOUNDARIES,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builder-code", type=Path, required=True)
    parser.add_argument("--source-freeze-manifest", type=Path, required=True)
    parser.add_argument("--baseline-base-dir", type=Path, required=True)
    parser.add_argument("--candidate-base-dir", type=Path, required=True)
    parser.add_argument("--v2-identity-freeze", type=Path, required=True)
    parser.add_argument("--v2-raw-snapshot", type=Path, required=True)
    parser.add_argument("--existing-post-hydration-snapshot", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--expected-governed-external-exclusions", type=int)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = validate(
            builder_code=args.builder_code,
            source_freeze_manifest=args.source_freeze_manifest,
            baseline_base_dir=args.baseline_base_dir,
            candidate_base_dir=args.candidate_base_dir,
            v2_identity_freeze=args.v2_identity_freeze,
            v2_raw_snapshot=args.v2_raw_snapshot,
            existing_post_hydration_snapshot=args.existing_post_hydration_snapshot,
            report_root=args.report_root,
            candidate_root=args.candidate_root,
            expected_governed_external_exclusions=(
                args.expected_governed_external_exclusions
            ),
        )
    except CandidateLedgerValidationError as exc:
        print(
            json.dumps(
                {"status": "failed", "reason_code": str(exc)},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    if args.receipt is not None:
        try:
            write_immutable_receipt(args.receipt, receipt)
        except CandidateLedgerValidationError as exc:
            print(
                json.dumps(
                    {"status": "failed", "reason_code": str(exc)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
            return 2
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
