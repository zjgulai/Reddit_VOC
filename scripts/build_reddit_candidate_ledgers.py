#!/usr/bin/env python3
"""Build deterministic private Plan-A candidate identity ledgers.

This is an A2 accounting artifact.  It consumes only frozen local inputs,
compares the current production Base with one already-built candidate Base,
and never controls admission into that Base.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any, Iterable, Sequence

try:
    from scripts import build_reddit_v2_raw_snapshot as v2
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import build_reddit_v2_raw_snapshot as v2  # type: ignore[no-redef]


SCHEMA_VERSION = "reddit_voc_candidate_ledgers_v1"
MANIFEST_SCHEMA_VERSION = "reddit_voc_candidate_ledger_manifest_v2"
SOURCE_FREEZE_SCHEMA = "reddit_voc_candidate_source_freeze_v1"
BASE_SCHEMAS = {
    "reddit_voc_site_snapshot_manifest_v1",
    "reddit_voc_site_snapshot_manifest_v2",
}
IDENTITY_SCHEMA = "reddit_voc_v2_identity_freeze_v1"
RAW_SCHEMA = "reddit_voc_v2_raw_snapshot_v1"
HYDRATION_SCHEMA = "reddit_voc_existing_post_hydration_v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
POST_ID_RE = re.compile(r"^[a-z0-9]{5,10}$")
COMMENT_ID_RE = re.compile(r"^t1_[a-z0-9]+$")
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


class CandidateLedgerError(ValueError):
    """A frozen input or identity/accounting invariant is invalid."""


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


def _identity_hash(values: Iterable[str]) -> str:
    return _sha256_bytes(
        "".join(f"{value}\n" for value in sorted(set(values))).encode("utf-8")
    )


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


def _safe_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CandidateLedgerError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CandidateLedgerError(f"{label}_unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateLedgerError(f"{label}_invalid") from exc
    if not isinstance(value, dict):
        raise CandidateLedgerError(f"{label}_invalid")
    return value


def _safe_json_array(path: Path, *, label: str) -> list[dict[str, Any]]:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CandidateLedgerError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CandidateLedgerError(f"{label}_unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateLedgerError(f"{label}_invalid") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise CandidateLedgerError(f"{label}_invalid")
    return value


def _validated_base(root: Path, *, label: str) -> dict[str, Any]:
    try:
        root_meta = os.lstat(root)
    except OSError as exc:
        raise CandidateLedgerError(f"{label}_missing") from exc
    if stat.S_ISLNK(root_meta.st_mode) or not stat.S_ISDIR(root_meta.st_mode):
        raise CandidateLedgerError(f"{label}_unsafe")
    manifest_path = root / "manifest.json"
    manifest = _safe_json(manifest_path, label=f"{label}_manifest")
    if manifest.get("schema_version") not in BASE_SCHEMAS:
        raise CandidateLedgerError(f"{label}_schema_invalid")
    files = manifest.get("files")
    required_files = {"posts.json", "comments.json", "quarantine.json"}
    if not isinstance(files, dict) or not required_files <= set(files):
        raise CandidateLedgerError(f"{label}_files_invalid")
    loaded: dict[str, list[dict[str, Any]]] = {}
    for name in sorted(required_files):
        row = files.get(name)
        path = root / name
        if (
            not isinstance(row, dict)
            or row.get("sha256") != _file_sha256(path)
            or row.get("bytes") != path.stat().st_size
        ):
            raise CandidateLedgerError(f"{label}_file_binding_invalid")
        loaded[name] = _safe_json_array(path, label=f"{label}_{name}")
    posts = loaded["posts.json"]
    comments = loaded["comments.json"]
    quarantine = loaded["quarantine.json"]
    post_map = _unique_map(posts, "post_id", POST_ID_RE, f"{label}_post")
    comment_map = _unique_map(
        comments, "comment_id", COMMENT_ID_RE, f"{label}_comment"
    )
    quarantine_map = _unique_map(
        quarantine, "comment_id", COMMENT_ID_RE, f"{label}_quarantine"
    )
    if set(comment_map) & set(quarantine_map):
        raise CandidateLedgerError(f"{label}_comment_quarantine_overlap")
    if any(row.get("post_id") not in post_map for row in comments):
        raise CandidateLedgerError(f"{label}_linked_parent_missing")
    counts = manifest.get("canonical_counts")
    if counts != {
        "posts": len(post_map),
        "linked_comments": len(comment_map),
        "quarantined_comments": len(quarantine_map),
        "stored_comments": len(comment_map) + len(quarantine_map),
    }:
        raise CandidateLedgerError(f"{label}_canonical_counts_invalid")
    return {
        "root": root,
        "manifest": manifest,
        "manifest_sha256": _file_sha256(manifest_path),
        "posts": post_map,
        "comments": comment_map,
        "quarantine": quarantine_map,
    }


def _unique_map(
    rows: Sequence[dict[str, Any]],
    field: str,
    pattern: re.Pattern[str],
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(field)
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise CandidateLedgerError(f"{label}_identity_invalid")
        if value in result:
            raise CandidateLedgerError(f"{label}_identity_duplicate")
        result[value] = row
    return result


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CandidateLedgerError("event_time_invalid") from exc
    if parsed.tzinfo is None:
        raise CandidateLedgerError("event_time_invalid")
    return parsed.astimezone(timezone.utc)


def _classify_external_post(
    records: Sequence[tuple[str, str, bool]],
    *,
    start: str,
    end: str,
) -> str:
    window_start = _parse_utc(start)
    window_end = _parse_utc(end)
    if window_start >= window_end:
        raise CandidateLedgerError("event_window_invalid")

    normalized: list[tuple[str, bool, bool]] = []
    for typename, created_at, strict_subreddit in records:
        try:
            in_window = window_start <= _parse_utc(created_at) < window_end
        except CandidateLedgerError:
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
        typename == "ProfilePost"
        for typename, _in_window, _strict in normalized
    ):
        return "window_outside_profile_post"
    return "raw_id_without_strict_search_row"


def _validated_lineage_gap_ids(
    identity: dict[str, Any],
    raw: dict[str, Any],
    v2_boundary: dict[str, Any],
    candidate_post_ids: set[str],
) -> list[str]:
    """Bind pending lineage identities across identity, raw, and Base facts."""

    def identity_set(set_id: str) -> set[str]:
        rows = identity.get("identity_sets")
        if not isinstance(rows, list):
            raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
        matches = [
            row
            for row in rows
            if isinstance(row, dict) and row.get("set_id") == set_id
        ]
        if len(matches) != 1:
            raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
        row = matches[0]
        values = row.get("post_ids")
        if (
            not isinstance(values, list)
            or any(
                not isinstance(value, str)
                or POST_ID_RE.fullmatch(value) is None
                for value in values
            )
        ):
            raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
        result = set(values)
        if (
            len(result) != len(values)
            or row.get("count") != len(result)
            or row.get("lf_sha256") != _identity_hash(result)
        ):
            raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
        return result

    if any(POST_ID_RE.fullmatch(value) is None for value in candidate_post_ids):
        raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
    discovery_ids = identity_set("discovery_only")
    global_ids = identity_set("global_known")
    raw_posts = raw.get("posts")
    raw_target = raw.get("target")
    raw_accounting = raw.get("accounting")
    current_site = identity.get("current_site")
    if (
        not isinstance(raw_posts, list)
        or not isinstance(raw_target, dict)
        or not isinstance(raw_accounting, dict)
        or not isinstance(current_site, dict)
    ):
        raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
    raw_post_values = [
        row.get("post_id") if isinstance(row, dict) else None for row in raw_posts
    ]
    if any(
        not isinstance(value, str) or POST_ID_RE.fullmatch(value) is None
        for value in raw_post_values
    ):
        raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
    raw_post_ids = {str(value) for value in raw_post_values}
    if len(raw_post_ids) != len(raw_post_values):
        raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
    pending_values = raw_accounting.get("lineage_missing_post_ids")
    boundary_values = v2_boundary.get("lineage_gap_post_ids")
    if (
        not isinstance(pending_values, list)
        or not isinstance(boundary_values, list)
        or any(
            not isinstance(value, str) or POST_ID_RE.fullmatch(value) is None
            for value in [*pending_values, *boundary_values]
        )
    ):
        raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
    pending_ids = set(pending_values)
    boundary_ids = set(boundary_values)
    expected_pending = discovery_ids - raw_post_ids
    if (
        len(pending_ids) != len(pending_values)
        or len(boundary_ids) != len(boundary_values)
        or pending_ids != boundary_ids
        or pending_ids != expected_pending
        or discovery_ids != raw_post_ids | pending_ids
        or not raw_post_ids <= candidate_post_ids
        or global_ids != candidate_post_ids | pending_ids
        or candidate_post_ids & pending_ids
        or current_site.get("count") != len(candidate_post_ids)
        or current_site.get("lf_sha256") != _identity_hash(candidate_post_ids)
        or raw_target.get("count") != len(discovery_ids)
        or raw_target.get("post_ids_sha256") != _identity_hash(discovery_ids)
        or v2_boundary.get("target_count") != len(discovery_ids)
        or v2_boundary.get("target_lf_sha256") != _identity_hash(discovery_ids)
        or v2_boundary.get("admitted_posts") != len(raw_post_ids)
        or v2_boundary.get("lineage_gap_count") != len(pending_ids)
        or v2_boundary.get("lineage_gap_lf_sha256")
        != _identity_hash(pending_ids)
    ):
        raise CandidateLedgerError("v2_lineage_gap_binding_mismatch")
    return sorted(pending_ids)


def _post_delta_rows(
    baseline: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
    external_rows: Sequence[dict[str, Any]],
    *,
    pending_post_ids: Iterable[str] = (),
    source_cutoff_utc: str | None = None,
    input_evidence_sha256: str | None = None,
) -> list[dict[str, Any]]:
    if not set(baseline) <= set(candidate):
        raise CandidateLedgerError("baseline_post_missing")
    rows: list[dict[str, Any]] = []
    for post_id in sorted(candidate):
        current = candidate[post_id]
        candidate_sha = _managed_sha256(current, POST_MANAGED_FIELDS)
        previous = baseline.get(post_id)
        if previous is None:
            status = "newly_admitted"
            baseline_sha = None
            reason = "candidate_identity_absent_from_production_baseline"
        else:
            baseline_sha = _managed_sha256(previous, POST_MANAGED_FIELDS)
            status = (
                "existing_unchanged"
                if baseline_sha == candidate_sha
                else "existing_upgraded"
            )
            reason = (
                "managed_fields_equal"
                if status == "existing_unchanged"
                else "managed_fields_changed"
            )
        row = {
                "post_id": post_id,
                "status": status,
                "reason_code": reason,
                "baseline_managed_sha256": baseline_sha,
                "candidate_managed_sha256": candidate_sha,
                "release_net_new": previous is None,
            }
        if source_cutoff_utc is not None:
            row["source_cutoff_utc"] = source_cutoff_utc
        if input_evidence_sha256 is not None:
            row["input_evidence_sha256"] = input_evidence_sha256
        rows.append(row)

    pending_set = set(pending_post_ids)
    if any(
        not isinstance(post_id, str)
        or POST_ID_RE.fullmatch(post_id) is None
        or post_id in candidate
        or post_id in baseline
        for post_id in pending_set
    ):
        raise CandidateLedgerError("pending_post_outcome_invalid")
    for post_id in sorted(pending_set):
        row = {
            "post_id": post_id,
            "status": "pending_lineage",
            "reason_code": "v2_search_identity_lineage_missing",
            "baseline_managed_sha256": None,
            "candidate_managed_sha256": None,
            "release_net_new": False,
        }
        if source_cutoff_utc is not None:
            row["source_cutoff_utc"] = source_cutoff_utc
        if input_evidence_sha256 is not None:
            row["input_evidence_sha256"] = input_evidence_sha256
        rows.append(row)

    seen_external: set[str] = set()
    for external in external_rows:
        post_id = external.get("post_id")
        reason = external.get("reason_code")
        if (
            not isinstance(post_id, str)
            or POST_ID_RE.fullmatch(post_id) is None
            or post_id in candidate
            or post_id in baseline
            or post_id in pending_set
            or post_id in seen_external
            or reason not in EXTERNAL_REJECTION_REASONS
        ):
            raise CandidateLedgerError("external_post_outcome_invalid")
        seen_external.add(post_id)
        row = {
                "post_id": post_id,
                "status": "rejected",
                "reason_code": reason,
                "baseline_managed_sha256": None,
                "candidate_managed_sha256": None,
                "release_net_new": False,
                "comment_report_occurrence_count": external[
                    "comment_report_occurrence_count"
                ],
                "strict_search_occurrence_count": external[
                    "strict_search_occurrence_count"
                ],
            }
        if source_cutoff_utc is not None:
            row["source_cutoff_utc"] = source_cutoff_utc
        if input_evidence_sha256 is not None:
            row["input_evidence_sha256"] = input_evidence_sha256
        rows.append(row)
    rows.sort(key=lambda row: str(row["post_id"]))
    return rows


def _comment_delta_rows(
    baseline_linked: dict[str, dict[str, Any]],
    baseline_quarantine: dict[str, dict[str, Any]],
    candidate_linked: dict[str, dict[str, Any]],
    candidate_quarantine: dict[str, dict[str, Any]],
    *,
    rejected_rows: Sequence[dict[str, Any]] = (),
    source_cutoff_utc: str | None = None,
    input_evidence_sha256: str | None = None,
) -> list[dict[str, Any]]:
    baseline_ids = set(baseline_linked) | set(baseline_quarantine)
    candidate_ids = set(candidate_linked) | set(candidate_quarantine)
    if set(baseline_linked) & set(baseline_quarantine):
        raise CandidateLedgerError("baseline_comment_partition_invalid")
    if set(candidate_linked) & set(candidate_quarantine):
        raise CandidateLedgerError("candidate_comment_partition_invalid")
    if not baseline_ids <= candidate_ids:
        raise CandidateLedgerError("baseline_comment_missing")

    rows: list[dict[str, Any]] = []
    for comment_id in sorted(candidate_ids):
        old_linked = baseline_linked.get(comment_id)
        old_quarantine = baseline_quarantine.get(comment_id)
        new_linked = candidate_linked.get(comment_id)
        new_quarantine = candidate_quarantine.get(comment_id)
        old_location = (
            "linked" if old_linked is not None else "quarantine" if old_quarantine else "absent"
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
                new_quarantine,
                tuple(sorted(new_quarantine)),
            )
        else:  # candidate_ids is the exact linked/quarantine union.
            raise CandidateLedgerError("candidate_comment_location_missing")
        if old_location == "absent":
            status = "new_linked" if new_location == "linked" else "new_quarantined"
            reason = "candidate_identity_absent_from_production_baseline"
        elif old_location == "quarantine" and new_location == "linked":
            status = "existing_quarantine_relinked"
            reason = "existing_identity_parent_link_restored"
        elif old_location == "quarantine" and new_location == "quarantine":
            status = "existing_quarantine_retained"
            reason = "existing_quarantine_identity_retained"
        elif old_location == "linked" and new_location == "quarantine":
            raise CandidateLedgerError("linked_comment_regressed_to_quarantine")
        elif baseline_sha == candidate_sha:
            status = "existing_unchanged"
            reason = "managed_fields_equal"
        else:
            status = "existing_upgraded"
            reason = "managed_fields_changed"
        row = {
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
            }
        if source_cutoff_utc is not None:
            row["source_cutoff_utc"] = source_cutoff_utc
        if input_evidence_sha256 is not None:
            row["input_evidence_sha256"] = input_evidence_sha256
        rows.append(row)
    seen_rejected: set[str] = set()
    for rejected in rejected_rows:
        comment_id = rejected.get("comment_id")
        parent_post_id = rejected.get("parent_post_id")
        reason_code = rejected.get("reason_code")
        source_managed_sha256 = rejected.get("source_managed_sha256")
        if (
            not isinstance(comment_id, str)
            or COMMENT_ID_RE.fullmatch(comment_id) is None
            or comment_id in candidate_ids
            or comment_id in baseline_ids
            or comment_id in seen_rejected
            or not isinstance(parent_post_id, str)
            or POST_ID_RE.fullmatch(parent_post_id) is None
            or not isinstance(reason_code, str)
            or not reason_code.startswith("parent_post_")
            or not isinstance(source_managed_sha256, str)
            or SHA256_RE.fullmatch(source_managed_sha256) is None
        ):
            raise CandidateLedgerError("rejected_comment_outcome_invalid")
        seen_rejected.add(comment_id)
        row = {
            "comment_id": comment_id,
            "status": "rejected",
            "reason_code": reason_code,
            "baseline_location": "absent",
            "candidate_location": "absent",
            "baseline_managed_sha256": None,
            "candidate_managed_sha256": None,
            "source_managed_sha256": source_managed_sha256,
            "release_net_new": False,
            "include_in_voc_metrics": False,
            "deleted_or_removed": rejected.get("deleted_or_removed"),
            "parent_link_status": "parent_post_rejected",
        }
        if source_cutoff_utc is not None:
            row["source_cutoff_utc"] = source_cutoff_utc
        if input_evidence_sha256 is not None:
            row["input_evidence_sha256"] = input_evidence_sha256
        rows.append(row)
    rows.sort(key=lambda row: str(row["comment_id"]))
    return rows


def _coverage_row(
    *,
    work_type: str,
    components: Sequence[str],
    status: str,
    reason_code: str,
    source: str,
    source_cutoff_utc: str | None = None,
    input_evidence_sha256: str | None = None,
    report_sha256: str | None = None,
    report_failure_sha256: str | None = None,
) -> dict[str, Any]:
    if work_type not in {
        "search_lane",
        "lineage_gap",
        "comment_first_page",
        "comment_cursor",
        "comment_page",
    } or not components or status not in {
        "closed_success",
        "closed_no_more",
        "superseded",
        "retryable_failed",
        "nonretryable_rejected",
        "open_carried",
    }:
        raise CandidateLedgerError("coverage_work_item_invalid")
    if work_type == "search_lane":
        try:
            lane_index = int(components[0])
        except (TypeError, ValueError) as exc:
            raise CandidateLedgerError("coverage_work_item_invalid") from exc
        if (
            str(lane_index) != components[0]
            or lane_index < 0
            or len(components) != 2
            or SHA256_RE.fullmatch(components[1]) is None
        ):
            raise CandidateLedgerError("coverage_work_item_invalid")
    elif work_type == "comment_cursor":
        if (
            len(components) != 2
            or POST_ID_RE.fullmatch(components[0]) is None
            or SHA256_RE.fullmatch(components[1]) is None
        ):
            raise CandidateLedgerError("coverage_work_item_invalid")
    elif len(components) != 1 or POST_ID_RE.fullmatch(components[0]) is None:
        raise CandidateLedgerError("coverage_work_item_invalid")
    if report_sha256 is not None and SHA256_RE.fullmatch(report_sha256) is None:
        raise CandidateLedgerError("coverage_work_item_invalid")
    failed_status = status in {"retryable_failed", "nonretryable_rejected"}
    if failed_status != (report_failure_sha256 is not None) or (
        report_failure_sha256 is not None
        and SHA256_RE.fullmatch(report_failure_sha256) is None
    ):
        raise CandidateLedgerError("coverage_work_item_invalid")
    report_backed_type = work_type in {"comment_first_page", "comment_cursor"}
    if (
        status == "closed_success"
        and (not report_backed_type or report_sha256 is None)
    ) or (
        failed_status
        and (not report_backed_type or report_sha256 is None)
    ) or (
        status not in {
            "closed_success",
            "retryable_failed",
            "nonretryable_rejected",
        }
        and report_sha256 is not None
    ):
        raise CandidateLedgerError("coverage_work_item_invalid")
    raw_key = "\t".join((work_type, *components))
    if work_type == "lineage_gap":
        stable_key = f"lineage:{components[0]}"
    elif work_type == "comment_cursor":
        stable_key = f"cursor:{components[0]}:{components[1]}"
    elif work_type == "comment_page":
        stable_key = f"comment_page:{components[0]}"
    elif work_type == "comment_first_page":
        stable_key = f"comment_first_page:{components[0]}"
    elif work_type == "search_lane":
        stable_key = f"search_lane:{components[0]}:{components[1]}"
    else:
        stable_key = _sha256_bytes(raw_key.encode("utf-8"))
    row: dict[str, Any] = {
        "work_item_key": stable_key,
        "work_type": work_type,
        "status": status,
        "reason_code": reason_code,
        "source": source,
    }
    if work_type == "search_lane":
        row["lane_index"] = int(components[0])
        row["term_sha256"] = components[1]
    elif work_type == "comment_cursor":
        row["post_id"] = components[0]
        row["cursor_sha256"] = components[1]
    else:
        row["post_id"] = components[0]
    if report_sha256 is not None:
        row["report_sha256"] = report_sha256
    if report_failure_sha256 is not None:
        row["report_failure_sha256"] = report_failure_sha256
    if source_cutoff_utc is not None:
        row["source_cutoff_utc"] = source_cutoff_utc
    if input_evidence_sha256 is not None:
        row["input_evidence_sha256"] = input_evidence_sha256
    return row


def _validated_source_occurrences(
    manifest_path: Path,
    report_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _safe_json(manifest_path, label="source_freeze_manifest")
    if manifest.get("schema_version") != SOURCE_FREEZE_SCHEMA:
        raise CandidateLedgerError("source_freeze_schema_invalid")
    entries = manifest.get("files")
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise CandidateLedgerError("source_freeze_files_invalid")
    if manifest.get("file_count") != len(entries):
        raise CandidateLedgerError("source_freeze_file_count_invalid")
    source_cutoff = manifest.get("source_cutoff_utc")
    if not isinstance(source_cutoff, str):
        raise CandidateLedgerError("source_freeze_cutoff_invalid")
    _parse_utc(source_cutoff)
    manifest_sha256 = _file_sha256(manifest_path)
    occurrence_rows: list[dict[str, Any]] = []
    stable_keys: set[str] = set()
    seen_content: set[tuple[int, str]] = set()
    expected_reports: dict[str, tuple[int, str]] = {}
    for entry in sorted(
        entries,
        key=lambda row: (
            str(row.get("source_namespace") or ""),
            str(row.get("relative_path") or ""),
            str(row.get("sha256") or ""),
        ),
    ):
        namespace = entry.get("source_namespace")
        source_kind = entry.get("source_kind")
        relative = entry.get("relative_path")
        digest = entry.get("sha256")
        byte_count = entry.get("bytes")
        eligible = entry.get("fusion_eligible")
        if (
            not isinstance(namespace, str)
            or not isinstance(source_kind, str)
            or not isinstance(relative, str)
            or PurePosixPath(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
            or not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
            or not isinstance(eligible, bool)
        ):
            raise CandidateLedgerError("source_freeze_file_row_invalid")
        key_material = {
            "source_namespace": namespace,
            "relative_path": relative,
            "bytes": byte_count,
            "sha256": digest,
            "observed_cutoff": source_cutoff,
        }
        occurrence_key = _sha256_bytes(_canonical_bytes(key_material))
        if occurrence_key in stable_keys:
            raise CandidateLedgerError("source_occurrence_duplicate")
        stable_keys.add(occurrence_key)
        content_key = (byte_count, digest)
        if content_key in seen_content:
            disposition = "accepted_duplicate_occurrence"
            reason_code = "frozen_content_duplicate"
        elif eligible:
            disposition = "accepted_new_occurrence"
            reason_code = "frozen_fusion_eligible_input"
        else:
            disposition = "quarantined_input"
            reason_code = "frozen_plan_or_documentation_non_fusion"
        seen_content.add(content_key)
        occurrence_rows.append(
            {
                "occurrence_key": occurrence_key,
                **key_material,
                "source_kind": source_kind,
                "fusion_eligible": eligible,
                "status": disposition,
                "reason_code": reason_code,
                "source_cutoff_utc": source_cutoff,
                "input_evidence_sha256": manifest_sha256,
            }
        )
        if namespace == "tencent_v2_reports":
            expected_reports[relative] = (byte_count, digest)
    if (
        manifest.get("fusion_eligible_file_count")
        != sum(bool(row["fusion_eligible"]) for row in occurrence_rows)
        or manifest.get("documentation_file_count")
        != sum(row["source_kind"] == "local_external_documentation" for row in occurrence_rows)
    ):
        raise CandidateLedgerError("source_freeze_accounting_invalid")
    actual_reports = {
        path.relative_to(report_root).as_posix(): path
        for path in report_root.rglob("*.json")
        if path.is_file() and not path.is_symlink()
    }
    if set(actual_reports) != set(expected_reports):
        raise CandidateLedgerError("report_root_member_set_invalid")
    for relative, (byte_count, digest) in expected_reports.items():
        path = actual_reports[relative]
        if path.stat().st_size != byte_count or _file_sha256(path) != digest:
            raise CandidateLedgerError("report_root_member_binding_invalid")
    occurrence_rows.sort(key=lambda row: str(row["occurrence_key"]))
    return manifest, occurrence_rows


def _external_post_rows(
    *,
    baseline_post_ids: set[str],
    candidate_post_ids: set[str],
    report_root: Path,
    window_start: str,
    window_end: str,
) -> dict[str, Any]:
    if not baseline_post_ids <= candidate_post_ids:
        raise CandidateLedgerError("candidate_post_set_regressed")
    report_counts: Counter[str] = Counter()
    external_ids: set[str] = set()
    for path in v2._report_paths([report_root], v2.COMMENT_REPORT_NAMES):
        try:
            report, _report_sha = v2._load_report(path)
        except v2.ReportContractError as exc:
            raise CandidateLedgerError("comment_report_envelope_invalid") from exc
        post_id = v2._normalize_post_id(report.get("post_id"))
        if post_id is None or POST_ID_RE.fullmatch(post_id) is None:
            raise CandidateLedgerError("comment_report_post_id_invalid")
        if post_id not in candidate_post_ids:
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
            raise CandidateLedgerError("search_report_invalid") from exc
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
    reason_by_post: dict[str, str] = {}
    for post_id in sorted(external_ids):
        records = search_records.get(post_id, [])
        reason = _classify_external_post(
            records,
            start=window_start,
            end=window_end,
        )
        if reason == "admissible_current_window_subreddit_post":
            raise CandidateLedgerError("admissible_external_post_missing_from_candidate")
        reason_by_post[post_id] = reason
        rows.append(
            {
                "post_id": post_id,
                "reason_code": reason,
                "comment_report_occurrence_count": report_counts[post_id],
                "strict_search_occurrence_count": len(records),
            }
        )
    scanned = v2._scan_comment_reports([report_root], external_ids)
    reachable = v2._reachable_comment_reports(
        tuple(sorted(external_ids)),
        scanned["first_pages"],
        scanned["replies"],
    )
    observed_comments, comment_conflicts = v2._merge_comments(
        reachable["reports"]
    )
    if (
        scanned["conflicts"]
        or comment_conflicts
        or reachable["orphan_replies"]
        or reachable["cursor_cycles"]
    ):
        raise CandidateLedgerError("external_comment_graph_conflict")
    rejected_comments: list[dict[str, Any]] = []
    for comment in observed_comments:
        post_id = str(comment.get("post_id"))
        comment_id = str(comment.get("comment_id"))
        if post_id not in reason_by_post or COMMENT_ID_RE.fullmatch(comment_id) is None:
            raise CandidateLedgerError("external_comment_identity_invalid")
        rejected_comments.append(
            {
                "comment_id": comment_id,
                "parent_post_id": post_id,
                "reason_code": f"parent_post_{reason_by_post[post_id]}",
                "source_managed_sha256": _managed_sha256(
                    comment,
                    (
                        "post_id",
                        "parent_id",
                        "body",
                        "created_at_utc",
                        "deleted_or_removed",
                        "author_hash",
                        "depth",
                    ),
                ),
                "deleted_or_removed": bool(comment.get("deleted_or_removed")),
            }
        )
    rejected_comments.sort(key=lambda row: str(row["comment_id"]))
    invalid_report_sha256s = {
        str(failure["report_sha256"]) for failure in scanned["failures"]
    }
    return {
        "post_rows": rows,
        "rejected_comment_rows": rejected_comments,
        "invalid_report_sha256s": invalid_report_sha256s,
        "coverage": {
            "first_page_missing_post_ids": sorted(reachable["first_page_missing"]),
            "page_pagination_outstanding_post_ids": sorted(
                reachable["page_has_next"]
            ),
            "failed_reports": scanned["failures"],
        },
    }


def _validate_coverage_union_rows(
    rows: Sequence[dict[str, Any]],
    union: dict[str, Any],
    *,
    partial_post_ids: set[str] | None = None,
    expected_source_counts: dict[str, Any] | None = None,
    governed_post_ids: set[str] | None = None,
) -> None:
    governed = [
        row
        for row in rows
        if row.get("work_type")
        in {"comment_first_page", "comment_cursor", "comment_page"}
        and (
            governed_post_ids is None
            or row.get("post_id") in governed_post_ids
        )
    ]
    debt_statuses = {
        "open_carried",
        "retryable_failed",
        "nonretryable_rejected",
    }
    first = {
        str(row["post_id"])
        for row in governed
        if row.get("work_type") == "comment_first_page"
        and row.get("status") in debt_statuses
    }
    cursor = {
        f"{row['post_id']}\t{row['cursor_sha256']}"
        for row in governed
        if row.get("work_type") == "comment_cursor"
        and row.get("status") in {"open_carried", "retryable_failed"}
    }
    pages = {
        str(row["post_id"])
        for row in governed
        if row.get("work_type") == "comment_page"
        and row.get("status") in {"open_carried", "retryable_failed"}
    }
    failures = {
        str(row.get("report_failure_sha256"))
        for row in governed
        if row.get("status") in {"retryable_failed", "nonretryable_rejected"}
    }
    if any(
        (row.get("status") in {"retryable_failed", "nonretryable_rejected"})
        != (row.get("report_failure_sha256") is not None)
        for row in governed
    ) or any(SHA256_RE.fullmatch(value) is None for value in failures):
        raise CandidateLedgerError("coverage_union_binding_mismatch")
    if partial_post_ids is None:
        partial = {
            str(row["post_id"])
            for row in governed
            if row.get("post_id") is not None
            and row.get("work_type")
            in {"comment_first_page", "comment_cursor", "comment_page"}
            and row.get("status") in debt_statuses
        }
    else:
        partial = set(partial_post_ids)
    expected = {
        "first_page_missing": len(first),
        "first_page_missing_lf_sha256": _identity_hash(first),
        "cursor_outstanding": len(cursor),
        "cursor_outstanding_lf_sha256": _identity_hash(cursor),
        "page_pagination_outstanding": len(pages),
        "page_pagination_outstanding_lf_sha256": _identity_hash(pages),
        "failed_reports": len(failures),
        "failed_reports_lf_sha256": _identity_hash(failures),
        "partial_threads": len(partial),
        "partial_thread_ids_lf_sha256": _identity_hash(partial),
        "not_observed_threads": len(first),
        "not_observed_thread_ids_lf_sha256": _identity_hash(first),
    }
    if union.get("key_union_not_numeric_sum") is not True or any(
        union.get(key) != value for key, value in expected.items()
    ) or (
        expected_source_counts is not None
        and union.get("source_counts") != expected_source_counts
    ):
        raise CandidateLedgerError("coverage_union_binding_mismatch")


def _coverage_rows(
    identity: dict[str, Any],
    raw: dict[str, Any],
    hydration: dict[str, Any],
    candidate_manifest: dict[str, Any],
    *,
    report_root: Path,
    candidate_post_ids: set[str],
    pending_lineage_ids: set[str],
    external_post_ids: set[str],
    source_cutoff_utc: str,
    input_evidence_sha256s: dict[str, str],
    external_coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    search = identity.get("coverage_ledger")
    if not isinstance(search, list):
        raise CandidateLedgerError("search_coverage_ledger_invalid")
    for lane in search:
        if not isinstance(lane, dict):
            raise CandidateLedgerError("search_coverage_row_invalid")
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
            raise CandidateLedgerError("search_coverage_row_invalid")
        rows.append(
            _coverage_row(
                work_type="search_lane",
                components=(str(lane_index), term_sha),
                status="closed_no_more" if terminal else "open_carried",
                reason_code="search_lane_terminal" if terminal else "search_lane_has_next",
                source="v2_identity_freeze",
            )
        )

    raw_accounting = raw.get("accounting")
    raw_posts = raw.get("posts")
    if not isinstance(raw_accounting, dict) or not isinstance(raw_posts, list):
        raise CandidateLedgerError("v2_coverage_shape_invalid")
    hydration_work = hydration.get("coverage_work_items")
    if not isinstance(hydration_work, dict):
        raise CandidateLedgerError("hydration_coverage_shape_invalid")
    raw_post_ids = {
        str(row.get("post_id"))
        for row in raw_posts
        if isinstance(row, dict)
    }
    if (
        len(raw_post_ids) != len(raw_posts)
        or not raw_post_ids <= candidate_post_ids
        or candidate_post_ids & pending_lineage_ids
        or candidate_post_ids & external_post_ids
        or pending_lineage_ids & external_post_ids
    ):
        raise CandidateLedgerError("coverage_post_partition_invalid")

    for post_id in sorted(pending_lineage_ids):
        rows.append(
            _coverage_row(
                work_type="lineage_gap",
                components=(post_id,),
                status="open_carried",
                reason_code="post_lineage_missing",
                source="v2",
            )
        )

    post_universe = candidate_post_ids | pending_lineage_ids | external_post_ids
    scanned = v2._scan_comment_reports([report_root], post_universe)
    reachable = v2._reachable_comment_reports(
        tuple(sorted(post_universe)),
        scanned["first_pages"],
        scanned["replies"],
    )
    hydration_failures = hydration_work.get("failed_reports")
    external_failures = external_coverage.get("failed_reports")
    if not isinstance(hydration_failures, list) or not isinstance(
        external_failures, list
    ):
        raise CandidateLedgerError("coverage_failure_shape_invalid")
    expected_failure_keys = {
        _sha256_bytes(_canonical_bytes(failure))
        for failure in [*hydration_failures, *external_failures]
        if isinstance(failure, dict)
    }
    failures = scanned.get("failures")
    if not isinstance(failures, list) or any(
        not isinstance(failure, dict) for failure in failures
    ):
        raise CandidateLedgerError("coverage_failure_shape_invalid")
    actual_failure_keys = {
        _sha256_bytes(_canonical_bytes(failure)) for failure in failures
    }
    if (
        len(expected_failure_keys) != len(hydration_failures)
        + len(external_failures)
        or actual_failure_keys != expected_failure_keys
        or scanned.get("report_file_count")
        != raw_accounting.get("comment_report_file_count")
        or scanned.get("report_file_count")
        != hydration.get("accounting", {}).get("comment_report_file_count")
        or scanned.get("ignored_non_target") != 0
        or scanned.get("conflicts")
        or scanned.get("duplicate_first_pages") != 0
        or scanned.get("duplicate_replies") != 0
        or reachable.get("orphan_replies")
        or reachable.get("cursor_cycles")
    ):
        raise CandidateLedgerError("coverage_strict_scan_mismatch")

    allowed_failure_reasons = {
        "legacy_reply_source_chain_incomplete",
        "legacy_reply_source_predecessor_missing",
        "report_response_validation_failed",
    }
    first_failures: dict[str, dict[str, Any]] = {}
    cursor_failures: dict[tuple[str, str], dict[str, Any]] = {}
    for failure in failures:
        post_id = failure.get("post_id")
        report_kind = failure.get("report_kind")
        report_sha = failure.get("report_sha256")
        reason = failure.get("reason")
        if (
            not isinstance(post_id, str)
            or post_id not in post_universe
            or not isinstance(report_sha, str)
            or SHA256_RE.fullmatch(report_sha) is None
            or reason not in allowed_failure_reasons
        ):
            raise CandidateLedgerError("coverage_failure_binding_invalid")
        if report_kind == "first_page":
            if post_id in first_failures:
                raise CandidateLedgerError("coverage_failure_binding_invalid")
            first_failures[post_id] = failure
        elif report_kind == "reply":
            cursor_sha = failure.get("cursor_sha256")
            if (
                not isinstance(cursor_sha, str)
                or SHA256_RE.fullmatch(cursor_sha) is None
                or (post_id, cursor_sha) in cursor_failures
            ):
                raise CandidateLedgerError("coverage_failure_binding_invalid")
            cursor_failures[(post_id, cursor_sha)] = failure
        else:
            raise CandidateLedgerError("coverage_failure_binding_invalid")

    first_pages = {
        str(post_id): report
        for post_id, report in scanned["first_pages"].items()
    }
    replies = {
        (str(key[0]), str(report.get("cursor_sha256"))): report
        for key, report in scanned["replies"].items()
        if isinstance(key, tuple) and len(key) == 2 and isinstance(report, dict)
    }
    outstanding = {
        (str(row.get("post_id")), str(row.get("cursor_sha256")))
        for row in reachable["cursor_outstanding"]
        if isinstance(row, dict)
    }
    page_post_ids = {str(value) for value in reachable["page_has_next"]}
    missing_first = {str(value) for value in reachable["first_page_missing"]}
    if (
        set(first_pages) | missing_first != post_universe
        or set(first_pages) & missing_first
        or set(first_pages) & set(first_failures)
        or not set(first_failures) <= missing_first
        or set(replies) & set(cursor_failures)
        or set(replies) & outstanding
        or set(cursor_failures) & outstanding
        or not page_post_ids <= post_universe
        or len(replies) != len(scanned["replies"])
        or len(outstanding) != len(reachable["cursor_outstanding"])
    ):
        raise CandidateLedgerError("coverage_work_partition_invalid")

    for post_id in sorted(post_universe):
        report = first_pages.get(post_id)
        failure = first_failures.get(post_id)
        if report is not None:
            rows.append(
                _coverage_row(
                    work_type="comment_first_page",
                    components=(post_id,),
                    status="closed_success",
                    reason_code="first_page_report_validated",
                    source="frozen_comment_reports",
                    report_sha256=str(report["report_sha256"]),
                )
            )
        elif failure is not None:
            rows.append(
                _coverage_row(
                    work_type="comment_first_page",
                    components=(post_id,),
                    status="nonretryable_rejected",
                    reason_code=str(failure["reason"]),
                    source="frozen_comment_reports",
                    report_sha256=str(failure["report_sha256"]),
                    report_failure_sha256=_sha256_bytes(
                        _canonical_bytes(failure)
                    ),
                )
            )
        else:
            rows.append(
                _coverage_row(
                    work_type="comment_first_page",
                    components=(post_id,),
                    status="open_carried",
                    reason_code="first_page_missing",
                    source="candidate_post_universe",
                )
            )

    for (post_id, cursor_sha), report in sorted(replies.items()):
        rows.append(
            _coverage_row(
                work_type="comment_cursor",
                components=(post_id, cursor_sha),
                status="closed_success",
                reason_code="reply_report_validated",
                source="frozen_comment_reports",
                report_sha256=str(report["report_sha256"]),
            )
        )
    for (post_id, cursor_sha), failure in sorted(cursor_failures.items()):
        rows.append(
            _coverage_row(
                work_type="comment_cursor",
                components=(post_id, cursor_sha),
                status="nonretryable_rejected",
                reason_code=str(failure["reason"]),
                source="frozen_comment_reports",
                report_sha256=str(failure["report_sha256"]),
                report_failure_sha256=_sha256_bytes(_canonical_bytes(failure)),
            )
        )
    for post_id, cursor_sha in sorted(outstanding):
        rows.append(
            _coverage_row(
                work_type="comment_cursor",
                components=(post_id, cursor_sha),
                status="open_carried",
                reason_code="cursor_outstanding",
                source="derived_comment_coverage",
            )
        )
    for post_id in sorted(page_post_ids):
        rows.append(
            _coverage_row(
                work_type="comment_page",
                components=(post_id,),
                status="open_carried",
                reason_code="page_pagination_outstanding",
                source="derived_comment_coverage",
            )
        )

    for row in rows:
        source = str(row["source"])
        evidence_sha = input_evidence_sha256s.get(source)
        if evidence_sha is None or SHA256_RE.fullmatch(evidence_sha) is None:
            raise CandidateLedgerError("coverage_input_evidence_invalid")
        row["source_cutoff_utc"] = source_cutoff_utc
        row["input_evidence_sha256"] = evidence_sha

    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["work_item_key"])
        if key in by_key:
            raise CandidateLedgerError("coverage_work_item_conflict")
        by_key[key] = row
    ordered = [by_key[key] for key in sorted(by_key)]

    fusion = candidate_manifest.get("fusion_accounting", {})
    union = fusion.get(
        "comment_coverage_debt_union"
    )
    if (
        not isinstance(union, dict)
        or fusion.get("coverage_debt_is_not_zero_filled") is not True
    ):
        raise CandidateLedgerError("candidate_coverage_union_missing")
    raw_partial = {
        str(row.get("post_id"))
        for row in raw_posts
        if isinstance(row, dict) and row.get("coverage_grade") == "partial"
    }
    hydration_partial = hydration_work.get("partial_post_ids")
    hydration_first = hydration_work.get("first_page_missing_post_ids")
    hydration_cursor = hydration_work.get("cursor_outstanding")
    hydration_page = hydration_work.get("page_pagination_outstanding_post_ids")
    hydration_not_observed = hydration_work.get("not_observed_post_ids")
    if not all(
        isinstance(value, list)
        for value in (
            hydration_partial,
            hydration_first,
            hydration_cursor,
            hydration_page,
            hydration_not_observed,
        )
    ):
        raise CandidateLedgerError("hydration_coverage_shape_invalid")
    assert isinstance(hydration_partial, list)
    assert isinstance(hydration_first, list)
    assert isinstance(hydration_cursor, list)
    assert isinstance(hydration_page, list)
    assert isinstance(hydration_not_observed, list)
    raw_first = raw_accounting.get("first_page_missing_post_ids")
    raw_cursor = raw_accounting.get("cursor_outstanding")
    raw_page = raw_accounting.get("page_pagination_outstanding_post_ids")
    raw_failures = raw_accounting.get("failed_reports")
    if not all(
        isinstance(value, list)
        for value in (raw_first, raw_cursor, raw_page, raw_failures)
    ):
        raise CandidateLedgerError("v2_coverage_shape_invalid")
    assert isinstance(raw_first, list)
    assert isinstance(raw_cursor, list)
    assert isinstance(raw_page, list)
    assert isinstance(raw_failures, list)
    failure_reason_counts = dict(
        sorted(Counter(str(row.get("reason")) for row in hydration_failures).items())
    )
    expected_source_counts = {
        "v2": {
            "first_page_missing": len(raw_first),
            "cursor_outstanding": len(raw_cursor),
            "page_pagination_outstanding": len(raw_page),
            "failed_reports": len(raw_failures),
        },
        "existing_post_hydration": {
            "first_page_missing": len(hydration_first),
            "cursor_outstanding": len(hydration_cursor),
            "page_pagination_outstanding": len(hydration_page),
            "failed_reports": len(hydration_failures),
            "partial_threads": len(hydration_partial),
            "not_observed_threads": len(hydration_not_observed),
            "failure_reason_counts": failure_reason_counts,
        },
    }
    _validate_coverage_union_rows(
        ordered,
        union,
        partial_post_ids=raw_partial | {str(value) for value in hydration_partial},
        expected_source_counts=expected_source_counts,
        governed_post_ids=candidate_post_ids | pending_lineage_ids,
    )
    return ordered


def _render_bundle_member(name: str, value: object) -> bytes:
    if name.endswith(".jsonl"):
        if not isinstance(value, list):
            raise CandidateLedgerError("bundle_jsonl_invalid")
        return b"".join(_canonical_bytes(row) + b"\n" for row in value)
    if name.endswith(".json"):
        return _canonical_bytes(value) + b"\n"
    raise CandidateLedgerError("bundle_member_name_invalid")


def write_bundle(root: Path, bundle: dict[str, object]) -> dict[str, str]:
    if not bundle or any(PurePosixPath(name).name != name for name in bundle):
        raise CandidateLedgerError("bundle_member_name_invalid")
    rendered = {
        name: _render_bundle_member(name, value)
        for name, value in sorted(bundle.items())
    }
    hashes = {name: _sha256_bytes(payload) for name, payload in rendered.items()}
    if root.exists() or root.is_symlink():
        try:
            metadata = os.lstat(root)
        except OSError as exc:  # pragma: no cover
            raise CandidateLedgerError("bundle_collision") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise CandidateLedgerError("bundle_collision")
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            raise CandidateLedgerError("bundle_collision")
        actual = {path.name: path for path in root.iterdir()}
        if set(actual) != set(rendered):
            raise CandidateLedgerError("bundle_collision")
        for name, payload in rendered.items():
            path = actual[name]
            member = os.lstat(path)
            if (
                stat.S_ISLNK(member.st_mode)
                or not stat.S_ISREG(member.st_mode)
                or stat.S_IMODE(member.st_mode) != 0o600
                or path.read_bytes() != payload
            ):
                raise CandidateLedgerError("bundle_collision")
        return hashes

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{root.name}.staging-", dir=root.parent)
    )
    staging.chmod(0o700)
    try:
        for name, payload in rendered.items():
            path = staging / name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
        staging.rename(root)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return hashes


def _ledger_meta(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    payload = b"".join(_canonical_bytes(row) + b"\n" for row in rows)
    return {"rows": len(rows), "bytes": len(payload), "sha256": _sha256_bytes(payload)}


def build(
    *,
    source_freeze_manifest: Path,
    baseline_base_dir: Path,
    candidate_base_dir: Path,
    v2_identity_freeze: Path,
    v2_raw_snapshot: Path,
    existing_post_hydration_snapshot: Path,
    report_root: Path,
) -> dict[str, object]:
    source_freeze, occurrence_rows = _validated_source_occurrences(
        source_freeze_manifest,
        report_root,
    )
    baseline = _validated_base(baseline_base_dir, label="baseline_base")
    candidate = _validated_base(candidate_base_dir, label="candidate_base")
    identity = _safe_json(v2_identity_freeze, label="v2_identity_freeze")
    raw = _safe_json(v2_raw_snapshot, label="v2_raw_snapshot")
    hydration = _safe_json(
        existing_post_hydration_snapshot,
        label="existing_post_hydration_snapshot",
    )
    if identity.get("schema_version") != IDENTITY_SCHEMA:
        raise CandidateLedgerError("v2_identity_schema_invalid")
    if raw.get("schema_version") != RAW_SCHEMA:
        raise CandidateLedgerError("v2_raw_schema_invalid")
    if hydration.get("schema_version") != HYDRATION_SCHEMA:
        raise CandidateLedgerError("hydration_schema_invalid")
    for field, expected in BOUNDARIES.items():
        if hydration.get(field) is not expected:
            raise CandidateLedgerError("hydration_boundary_invalid")

    source_cutoff_utc = source_freeze.get("source_cutoff_utc")
    if not isinstance(source_cutoff_utc, str):
        raise CandidateLedgerError("source_freeze_cutoff_invalid")
    _parse_utc(source_cutoff_utc)
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
    for row in occurrence_rows:
        row["input_evidence_sha256"] = input_evidence_sha256

    candidate_manifest = candidate["manifest"]
    boundaries = candidate_manifest.get("source_boundaries")
    if not isinstance(boundaries, dict):
        raise CandidateLedgerError("candidate_source_boundaries_invalid")
    v2_boundary = boundaries.get("tencent_v2_search_hydrated")
    hydration_boundary = boundaries.get("tencent_existing_post_comment_hydration")
    if (
        not isinstance(v2_boundary, dict)
        or not isinstance(hydration_boundary, dict)
        or v2_boundary.get("snapshot_sha256") != _file_sha256(v2_raw_snapshot)
        or v2_boundary.get("identity_freeze_sha256")
        != _file_sha256(v2_identity_freeze)
        or hydration_boundary.get("snapshot_sha256")
        != _file_sha256(existing_post_hydration_snapshot)
        or hydration.get("source", {}).get("base_manifest_sha256")
        != baseline["manifest_sha256"]
    ):
        raise CandidateLedgerError("candidate_source_binding_invalid")

    window = identity.get("target_window_utc")
    if not isinstance(window, dict):
        raise CandidateLedgerError("identity_window_invalid")
    external_outcomes = _external_post_rows(
        baseline_post_ids=set(baseline["posts"]),
        candidate_post_ids=set(candidate["posts"]),
        report_root=report_root,
        window_start=str(window.get("start")),
        window_end=str(window.get("end")),
    )
    external_rows = external_outcomes["post_rows"]
    hydration_accounting = hydration.get("accounting")
    if not isinstance(hydration_accounting, dict) or not isinstance(
        hydration_accounting.get("failed_reports"), list
    ):
        raise CandidateLedgerError("hydration_failed_report_set_invalid")
    invalid_report_sha256s = set(external_outcomes["invalid_report_sha256s"])
    invalid_report_sha256s.update(
        str(row.get("report_sha256"))
        for row in hydration_accounting["failed_reports"]
        if isinstance(row, dict)
    )
    matched_invalid_occurrences: set[str] = set()
    for row in occurrence_rows:
        if (
            row["source_namespace"] == "tencent_v2_reports"
            and row["sha256"] in invalid_report_sha256s
        ):
            row["status"] = "rejected_invalid"
            row["reason_code"] = "strict_report_or_lineage_validation_failed"
            matched_invalid_occurrences.add(str(row["sha256"]))
    if matched_invalid_occurrences != invalid_report_sha256s:
        raise CandidateLedgerError("invalid_report_occurrence_binding_mismatch")
    baseline_file_shas = {
        str(value.get("sha256"))
        for value in baseline["manifest"].get("files", {}).values()
        if isinstance(value, dict)
    }
    product_resolution = candidate_manifest.get("tagging", {}).get(
        "product_entity_resolution", {}
    )
    consumed_governed_shas = {
        baseline["manifest_sha256"],
        *baseline_file_shas,
        str(boundaries["historical_canonical"].get("database_sha256")),
        str(boundaries["tencent_production_primary"].get("snapshot_sha256")),
        str(boundaries["tencent_isolated_staging"].get("snapshot_sha256")),
        str(candidate_manifest.get("tagging", {}).get("dictionary_sha256")),
        str(
            product_resolution.get("ledger_sha256")
            if isinstance(product_resolution, dict)
            else ""
        ),
    }
    consumed_governed_shas = {
        value
        for value in consumed_governed_shas
        if SHA256_RE.fullmatch(value) is not None
    }
    for row in occurrence_rows:
        if (
            row["source_namespace"] == "governed_inputs"
            and row["fusion_eligible"] is True
            and row["sha256"] not in consumed_governed_shas
            and row["status"] == "accepted_new_occurrence"
        ):
            row["status"] = "superseded_by_precedence"
            row["reason_code"] = "frozen_governed_input_not_selected_by_candidate_load_order"
    raw_accounting = raw.get("accounting")
    if not isinstance(raw_accounting, dict):
        raise CandidateLedgerError("v2_raw_accounting_invalid")
    pending_lineage_ids = _validated_lineage_gap_ids(
        identity,
        raw,
        v2_boundary,
        set(candidate["posts"]),
    )
    post_rows = _post_delta_rows(
        baseline["posts"],
        candidate["posts"],
        external_rows,
        pending_post_ids=pending_lineage_ids,
        source_cutoff_utc=source_cutoff_utc,
        input_evidence_sha256=input_evidence_sha256,
    )
    comment_rows = _comment_delta_rows(
        baseline["comments"],
        baseline["quarantine"],
        candidate["comments"],
        candidate["quarantine"],
        rejected_rows=external_outcomes["rejected_comment_rows"],
        source_cutoff_utc=source_cutoff_utc,
        input_evidence_sha256=input_evidence_sha256,
    )
    coverage_rows = _coverage_rows(
        identity,
        raw,
        hydration,
        candidate_manifest,
        report_root=report_root,
        candidate_post_ids=set(candidate["posts"]),
        pending_lineage_ids=set(pending_lineage_ids),
        external_post_ids={str(row["post_id"]) for row in external_rows},
        source_cutoff_utc=source_cutoff_utc,
        input_evidence_sha256s={
            "v2_identity_freeze": input_evidence_sha256,
            "v2": input_evidence_sha256,
            "existing_post_hydration": input_evidence_sha256,
            "external_rejected": input_evidence_sha256,
            "frozen_comment_reports": input_evidence_sha256,
            "candidate_post_universe": input_evidence_sha256,
            "derived_comment_coverage": input_evidence_sha256,
        },
        external_coverage=external_outcomes["coverage"],
    )

    occurrence_counts = Counter(str(row["status"]) for row in occurrence_rows)
    post_counts = Counter(str(row["status"]) for row in post_rows)
    comment_counts = Counter(str(row["status"]) for row in comment_rows)
    coverage_counts = Counter(str(row["status"]) for row in coverage_rows)
    coverage_types = Counter(str(row["work_type"]) for row in coverage_rows)
    baseline_comment_ids = set(baseline["comments"]) | set(baseline["quarantine"])
    candidate_comment_ids = set(candidate["comments"]) | set(candidate["quarantine"])
    raw_post_ids = {
        str(row.get("post_id"))
        for row in raw.get("posts", [])
        if isinstance(row, dict)
    }
    raw_comment_ids = {
        str(row.get("comment_id"))
        for row in raw.get("comments", [])
        if isinstance(row, dict)
    }
    hydration_comment_ids = {
        str(row.get("comment_id"))
        for row in hydration.get("comments", [])
        if isinstance(row, dict)
    }
    rejected_comment_ids = {
        str(row["comment_id"])
        for row in comment_rows
        if row["status"] == "rejected"
    }
    expected_candidate_comment_ids = (
        baseline_comment_ids | raw_comment_ids | hydration_comment_ids
    )
    if (
        expected_candidate_comment_ids != candidate_comment_ids
        or rejected_comment_ids
        != {
            str(row["comment_id"])
            for row in external_outcomes["rejected_comment_rows"]
        }
        or rejected_comment_ids & candidate_comment_ids
        or not raw_post_ids <= set(candidate["posts"])
    ):
        raise CandidateLedgerError("source_identity_universe_mismatch")
    release_net_new_posts = set(candidate["posts"]) - set(baseline["posts"])
    release_net_new_comments = candidate_comment_ids - baseline_comment_ids
    rejected_external = {
        str(row["post_id"])
        for row in post_rows
        if row["status"] == "rejected"
    }
    pending_lineage = {
        str(row["post_id"])
        for row in post_rows
        if row["status"] == "pending_lineage"
    }
    new_comment_status_count = (
        comment_counts["new_linked"] + comment_counts["new_quarantined"]
    )
    if (
        len(occurrence_rows) != int(source_freeze["file_count"])
        or post_counts["newly_admitted"] != len(release_net_new_posts)
        or new_comment_status_count != len(release_net_new_comments)
        or post_counts["rejected"] != len(rejected_external)
        or pending_lineage != set(pending_lineage_ids)
        or {str(row["post_id"]) for row in post_rows}
        != set(candidate["posts"]) | pending_lineage | rejected_external
        or {str(row["comment_id"]) for row in comment_rows}
        != candidate_comment_ids | rejected_comment_ids
        or any(
            row["reason_code"] == "admissible_current_window_subreddit_post"
            for row in post_rows
        )
    ):
        raise CandidateLedgerError("ledger_accounting_invalid")

    ledgers = {
        "source-occurrence-ledger.jsonl": occurrence_rows,
        "post-identity-delta-ledger.jsonl": post_rows,
        "comment-identity-delta-ledger.jsonl": comment_rows,
        "coverage-work-ledger.jsonl": coverage_rows,
    }
    p0 = set(baseline["posts"])
    l0 = set(baseline["comments"])
    q0 = set(baseline["quarantine"])
    c0 = l0 | q0
    p1 = set(candidate["posts"])
    l1 = set(candidate["comments"])
    q1 = set(candidate["quarantine"])
    c1 = l1 | q1

    def identity_set(values: set[str]) -> dict[str, Any]:
        return {"count": len(values), "ids_lf_sha256": _identity_hash(values)}

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "a2_identity_closed_with_explicit_coverage_debt",
        "source_cutoff_utc": source_cutoff_utc,
        "input_evidence_sha256": input_evidence_sha256,
        "inputs": {
            **input_hashes,
            "builder_code_sha256": _file_sha256(Path(__file__)),
        },
        "identity_sets": {
            "p0": identity_set(p0),
            "l0": identity_set(l0),
            "q0": identity_set(q0),
            "c0": identity_set(c0),
            "p1": identity_set(p1),
            "l1": identity_set(l1),
            "q1": identity_set(q1),
            "c1": identity_set(c1),
        },
        "source_identity_universe": {
            "v2_raw_posts": identity_set(raw_post_ids),
            "v2_lineage_pending_posts": identity_set(pending_lineage),
            "governed_external_rejected_posts": identity_set(rejected_external),
            "v2_raw_comments": identity_set(raw_comment_ids),
            "existing_hydration_comments": identity_set(
                hydration_comment_ids
            ),
            "governed_external_rejected_comments": identity_set(
                rejected_comment_ids
            ),
            "candidate_comment_union_exact": (
                expected_candidate_comment_ids == c1
            ),
        },
        "ledgers": {name: _ledger_meta(rows) for name, rows in ledgers.items()},
        "accounting": {
            "source_occurrences": {
                "total": len(occurrence_rows),
                "invalid_comment_report_occurrences": len(
                    invalid_report_sha256s
                ),
                "status_counts": dict(sorted(occurrence_counts.items())),
                "unaccounted": 0,
            },
            "posts": {
                "baseline": len(baseline["posts"]),
                "candidate": len(candidate["posts"]),
                "release_net_new": len(release_net_new_posts),
                "governed_external_exclusions": len(rejected_external),
                "pending_lineage": len(pending_lineage),
                "status_counts": dict(sorted(post_counts.items())),
                "unaccounted": 0,
            },
            "comments": {
                "baseline": len(baseline_comment_ids),
                "candidate": len(candidate_comment_ids),
                "release_net_new": len(release_net_new_comments),
                "rejected_candidates": len(rejected_comment_ids),
                "release_net_new_in_voc": sum(
                    row["status"] in {"new_linked", "new_quarantined"}
                    and row["include_in_voc_metrics"] is True
                    for row in comment_rows
                ),
                "release_net_new_excluded_from_voc": sum(
                    row["status"] in {"new_linked", "new_quarantined"}
                    and row["include_in_voc_metrics"] is False
                    for row in comment_rows
                ),
                "status_counts": dict(sorted(comment_counts.items())),
                "unaccounted": 0,
            },
            "coverage": {
                "total": len(coverage_rows),
                "status_counts": dict(sorted(coverage_counts.items())),
                "work_type_counts": dict(sorted(coverage_types.items())),
                "unaccounted": 0,
            },
            "unaccounted_total": 0,
        },
        "set_relations": {
            "p0_subset_p1": set(baseline["posts"]) <= set(candidate["posts"]),
            "c0_subset_c1": baseline_comment_ids <= candidate_comment_ids,
            "l1_intersection_q1_empty": not (
                set(candidate["comments"]) & set(candidate["quarantine"])
            ),
            "all_linked_comment_parents_exist": all(
                row.get("post_id") in candidate["posts"]
                for row in candidate["comments"].values()
            ),
            "release_net_new_post_ids_lf_sha256": _identity_hash(
                release_net_new_posts
            ),
            "release_net_new_comment_ids_lf_sha256": _identity_hash(
                release_net_new_comments
            ),
            "pending_lineage_post_ids_lf_sha256": _identity_hash(
                pending_lineage
            ),
        },
        "privacy": {
            "private_artifact": True,
            "raw_payload_embedded": False,
            "raw_username_embedded": False,
            "post_or_comment_body_in_ledgers": False,
        },
        **BOUNDARIES,
    }
    return {**ledgers, "candidate-ledger-manifest.json": manifest}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-freeze-manifest", type=Path, required=True)
    parser.add_argument("--baseline-base-dir", type=Path, required=True)
    parser.add_argument("--candidate-base-dir", type=Path, required=True)
    parser.add_argument("--v2-identity-freeze", type=Path, required=True)
    parser.add_argument("--v2-raw-snapshot", type=Path, required=True)
    parser.add_argument("--existing-post-hydration-snapshot", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    bundle = build(
        source_freeze_manifest=args.source_freeze_manifest,
        baseline_base_dir=args.baseline_base_dir,
        candidate_base_dir=args.candidate_base_dir,
        v2_identity_freeze=args.v2_identity_freeze,
        v2_raw_snapshot=args.v2_raw_snapshot,
        existing_post_hydration_snapshot=args.existing_post_hydration_snapshot,
        report_root=args.report_root,
    )
    hashes = write_bundle(args.output_dir, bundle)
    manifest = bundle["candidate-ledger-manifest.json"]
    assert isinstance(manifest, dict)
    accounting = manifest["accounting"]
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "manifest_sha256": hashes["candidate-ledger-manifest.json"],
                "source_occurrences": accounting["source_occurrences"]["total"],
                "post_rows": manifest["ledgers"]["post-identity-delta-ledger.jsonl"]["rows"],
                "comment_rows": manifest["ledgers"]["comment-identity-delta-ledger.jsonl"]["rows"],
                "coverage_rows": manifest["ledgers"]["coverage-work-ledger.jsonl"]["rows"],
                "release_net_new_posts": accounting["posts"]["release_net_new"],
                "release_net_new_comments": accounting["comments"]["release_net_new"],
                "unaccounted_total": accounting["unaccounted_total"],
                **BOUNDARIES,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
