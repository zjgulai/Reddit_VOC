#!/usr/bin/env python3
"""Build a private, deterministic hydration delta for existing Base posts."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Sequence

try:
    from build_reddit_v2_raw_snapshot import (
        COMMENT_REPORT_NAMES,
        COMMENT_ID_RE,
        POST_ID_RE,
        _merge_comments,
        _reachable_comment_reports,
        _scan_comment_reports,
        canonical_bytes,
        identity_hash,
    )
except ModuleNotFoundError:  # Imported as scripts.build_reddit_existing_post_hydration.
    from scripts.build_reddit_v2_raw_snapshot import (
        COMMENT_REPORT_NAMES,
        COMMENT_ID_RE,
        POST_ID_RE,
        _merge_comments,
        _reachable_comment_reports,
        _scan_comment_reports,
        canonical_bytes,
        identity_hash,
    )


SCHEMA_VERSION = "reddit_voc_existing_post_hydration_v1"
ALLOWED_COVERAGE_FAILURE_REASONS = frozenset(
    {
        "legacy_reply_source_chain_incomplete",
        "legacy_reply_source_predecessor_missing",
        "report_response_validation_failed",
    }
)


class HydrationContractError(ValueError):
    """One immutable input or output violates the hydration contract."""


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, reason: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HydrationContractError(reason) from exc


def _validated_base(
    base_dir: Path,
) -> tuple[dict[str, Any], tuple[str, ...], set[str]]:
    if base_dir.is_symlink():
        raise HydrationContractError("base_dir_symlink_rejected")
    try:
        root = base_dir.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise HydrationContractError("base_dir_unreadable") from exc
    if not root.is_dir():
        raise HydrationContractError("base_dir_not_directory")
    manifest_path = root / "manifest.json"
    manifest = _load_json(manifest_path, reason="base_manifest_invalid")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version")
        != "reddit_voc_site_snapshot_manifest_v1"
        or manifest.get("all_checks_passed") is not True
        or manifest.get("production_unchanged") is not True
        or manifest.get("provider_call") is not False
        or manifest.get("live_send") is not False
    ):
        raise HydrationContractError("base_manifest_contract_invalid")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise HydrationContractError("base_manifest_files_invalid")
    for name, metadata in files.items():
        if not isinstance(name, str) or not isinstance(metadata, dict):
            raise HydrationContractError("base_manifest_file_entry_invalid")
        path = root / name
        if (
            path.parent != root
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != metadata.get("bytes")
            or _file_sha256(path) != metadata.get("sha256")
        ):
            raise HydrationContractError("base_manifest_file_mismatch")

    posts = _load_json(root / "posts.json", reason="base_posts_invalid")
    linked = _load_json(root / "comments.json", reason="base_comments_invalid")
    quarantine = _load_json(
        root / "quarantine.json", reason="base_quarantine_invalid"
    )
    if not all(isinstance(value, list) for value in (posts, linked, quarantine)):
        raise HydrationContractError("base_entity_arrays_invalid")
    post_ids = [
        row.get("post_id") for row in posts if isinstance(row, dict)
    ]
    if len(post_ids) != len(posts) or any(
        not isinstance(value, str) or POST_ID_RE.fullmatch(value) is None
        for value in post_ids
    ):
        raise HydrationContractError("base_post_ids_invalid")
    if len(set(post_ids)) != len(post_ids):
        raise HydrationContractError("base_post_ids_duplicate")

    linked_ids = [
        row.get("comment_id") for row in linked if isinstance(row, dict)
    ]
    quarantine_ids = [
        row.get("comment_id") for row in quarantine if isinstance(row, dict)
    ]
    comment_ids = [*linked_ids, *quarantine_ids]
    if len(linked_ids) != len(linked) or len(quarantine_ids) != len(quarantine):
        raise HydrationContractError("base_comment_rows_invalid")
    if any(
        not isinstance(value, str) or COMMENT_ID_RE.fullmatch(value) is None
        for value in comment_ids
    ):
        raise HydrationContractError("base_comment_ids_invalid")
    if len(set(comment_ids)) != len(comment_ids):
        raise HydrationContractError("base_comment_ids_duplicate")
    counts = manifest.get("canonical_counts")
    if (
        not isinstance(counts, dict)
        or counts.get("posts") != len(post_ids)
        or counts.get("linked_comments") != len(linked_ids)
        or counts.get("quarantined_comments") != len(quarantine_ids)
        or counts.get("stored_comments") != len(comment_ids)
    ):
        raise HydrationContractError("base_canonical_counts_mismatch")
    return manifest, tuple(sorted(post_ids)), set(comment_ids)


def _validated_discovery_partition(
    snapshot_path: Path, base_post_ids: set[str]
) -> tuple[dict[str, Any], set[str]]:
    if snapshot_path.is_symlink() or not snapshot_path.is_file():
        raise HydrationContractError("discovery_snapshot_invalid")
    snapshot = _load_json(
        snapshot_path, reason="discovery_snapshot_json_invalid"
    )
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema_version") != "reddit_voc_v2_raw_snapshot_v1"
        or snapshot.get("status") not in {"blocked", "complete"}
    ):
        raise HydrationContractError("discovery_snapshot_contract_invalid")
    for field in (
        "provider_call",
        "provider_attempt_made",
        "database_write",
        "production_merge",
        "live_send",
        "git_push",
        "dingtalk",
    ):
        if snapshot.get(field) is not False:
            raise HydrationContractError(
                f"discovery_snapshot_{field}_boundary_invalid"
            )
    posts = snapshot.get("posts")
    if not isinstance(posts, list):
        raise HydrationContractError("discovery_snapshot_posts_invalid")
    post_ids = [
        row.get("post_id") for row in posts if isinstance(row, dict)
    ]
    if len(post_ids) != len(posts) or any(
        not isinstance(value, str) or POST_ID_RE.fullmatch(value) is None
        for value in post_ids
    ):
        raise HydrationContractError("discovery_snapshot_post_ids_invalid")
    discovered = set(post_ids)
    if len(discovered) != len(post_ids) or not discovered <= base_post_ids:
        raise HydrationContractError("discovery_snapshot_partition_invalid")
    return snapshot, discovered


def _validated_report_freeze(
    source_freeze_manifest_path: Path, comment_report_root: Path
) -> tuple[dict[str, Any], int, int, str]:
    if source_freeze_manifest_path.is_symlink():
        raise HydrationContractError("source_freeze_manifest_symlink_rejected")
    manifest = _load_json(
        source_freeze_manifest_path, reason="source_freeze_manifest_invalid"
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version")
        != "reddit_voc_candidate_source_freeze_v1"
    ):
        raise HydrationContractError("source_freeze_contract_invalid")
    boundaries = manifest.get("boundaries")
    if not isinstance(boundaries, dict) or any(
        boundaries.get(field) is not False
        for field in (
            "provider_call",
            "provider_attempt_made",
            "database_write",
            "remote_write",
            "deploy",
            "live_send",
        )
    ):
        raise HydrationContractError("source_freeze_boundary_invalid")
    freeze_root = source_freeze_manifest_path.resolve(strict=True).parent
    report_root = comment_report_root.resolve(strict=True)
    if comment_report_root.is_symlink() or not report_root.is_dir():
        raise HydrationContractError("comment_report_root_invalid")
    try:
        report_prefix = report_root.relative_to(freeze_root).as_posix() + "/"
    except ValueError as exc:
        raise HydrationContractError("comment_report_root_outside_freeze") from exc
    if report_prefix != "sources/tencent_v2_reports/":
        raise HydrationContractError("comment_report_root_namespace_invalid")

    files = manifest.get("files")
    if not isinstance(files, list):
        raise HydrationContractError("source_freeze_files_invalid")
    expected: dict[str, tuple[int, str]] = {}
    for row in files:
        if not isinstance(row, dict):
            raise HydrationContractError("source_freeze_file_entry_invalid")
        relative = row.get("destination_relative_path")
        if (
            isinstance(relative, str)
            and relative.startswith(report_prefix)
            and Path(relative).name in COMMENT_REPORT_NAMES
        ):
            member = relative[len(report_prefix) :]
            size = row.get("bytes")
            digest = row.get("sha256")
            if (
                member in expected
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                raise HydrationContractError(
                    "source_freeze_comment_member_invalid"
                )
            expected[member] = (size, digest)
    actual_paths = sorted(
        (
            path
            for path in report_root.rglob("*.json")
            if path.name in COMMENT_REPORT_NAMES
        ),
        key=lambda path: path.relative_to(report_root).as_posix(),
    )
    actual = {path.relative_to(report_root).as_posix(): path for path in actual_paths}
    if set(actual) != set(expected):
        raise HydrationContractError("comment_report_freeze_member_set_mismatch")
    lines: list[str] = []
    total_bytes = 0
    for relative in sorted(expected):
        path = actual[relative]
        size, digest = expected[relative]
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != size
            or _file_sha256(path) != digest
        ):
            raise HydrationContractError("comment_report_freeze_member_mismatch")
        total_bytes += size
        lines.append(f"{relative}\t{size}\t{digest}\n")
    aggregate = sha256("".join(lines).encode("utf-8")).hexdigest()
    return manifest, len(expected), total_bytes, aggregate


def build(
    *,
    base_dir: Path | str,
    discovery_snapshot: Path | str,
    source_freeze_manifest: Path | str,
    comment_report_root: Path | str,
) -> dict[str, Any]:
    base_path = Path(base_dir)
    discovery_path = Path(discovery_snapshot)
    freeze_path = Path(source_freeze_manifest)
    report_root = Path(comment_report_root)
    base_manifest, base_post_ids, base_comment_ids = _validated_base(base_path)
    discovery, discovery_post_ids = _validated_discovery_partition(
        discovery_path, set(base_post_ids)
    )
    freeze, report_file_count, report_bytes, report_lf_sha256 = (
        _validated_report_freeze(freeze_path, report_root)
    )
    target_ids = tuple(sorted(set(base_post_ids) - discovery_post_ids))
    if not target_ids or set(target_ids) & discovery_post_ids:
        raise HydrationContractError("existing_post_partition_invalid")
    if set(target_ids) | discovery_post_ids != set(base_post_ids):
        raise HydrationContractError("base_post_partition_incomplete")

    scanned = _scan_comment_reports([report_root], set(target_ids))
    reachable = _reachable_comment_reports(
        target_ids,
        scanned["first_pages"],
        scanned["replies"],
    )
    observed_comments, comment_conflicts = _merge_comments(reachable["reports"])
    if (
        scanned["conflicts"]
        or comment_conflicts
        or reachable["orphan_replies"]
        or reachable["cursor_cycles"]
    ):
        raise HydrationContractError("hydration_fatal_graph_conflict")
    failure_reason_counts = Counter(
        str(row["reason"]) for row in scanned["failures"]
    )
    if not set(failure_reason_counts) <= ALLOWED_COVERAGE_FAILURE_REASONS:
        raise HydrationContractError("hydration_failure_reason_not_allowed")
    report_outcome_counts = {
        "accepted_first_page": len(scanned["first_pages"]),
        "accepted_reply": len(scanned["replies"]),
        "accepted_duplicate": int(scanned["duplicate_first_pages"])
        + int(scanned["duplicate_replies"]),
        "rejected_invalid": len(scanned["failures"]),
        "excluded_non_target": int(scanned["ignored_non_target"]),
    }
    accounted_report_count = sum(report_outcome_counts.values())
    unaccounted_report_count = int(scanned["report_file_count"]) - accounted_report_count
    if (
        scanned["report_file_count"] != report_file_count
        or unaccounted_report_count != 0
    ):
        raise HydrationContractError("hydration_report_accounting_mismatch")
    observed_ids = {str(row["comment_id"]) for row in observed_comments}
    gross_new_comments = [
        row
        for row in observed_comments
        if str(row["comment_id"]) not in base_comment_ids
    ]
    gross_new_ids = {str(row["comment_id"]) for row in gross_new_comments}
    overlap_ids = observed_ids & base_comment_ids
    retained_ids = base_comment_ids - observed_ids
    if gross_new_ids & base_comment_ids or len(gross_new_ids) != len(
        gross_new_comments
    ):
        raise HydrationContractError("gross_new_comment_identity_invalid")
    if any(str(row["post_id"]) not in set(target_ids) for row in gross_new_comments):
        raise HydrationContractError("gross_new_comment_parent_invalid")

    first_page_missing = set(reachable["first_page_missing"])
    cursor_debt = Counter(
        str(row["post_id"]) for row in reachable["cursor_outstanding"]
    )
    page_debt = set(str(value) for value in reachable["page_has_next"])
    failure_debt = Counter(
        str(row["post_id"])
        for row in scanned["failures"]
        if isinstance(row.get("post_id"), str)
    )
    observed_by_post = Counter(str(row["post_id"]) for row in observed_comments)
    post_coverage: list[dict[str, Any]] = []
    for post_id in target_ids:
        if post_id in first_page_missing:
            grade = "not_observed"
        elif cursor_debt[post_id] or post_id in page_debt or failure_debt[post_id]:
            grade = "partial"
        else:
            grade = "full"
        post_coverage.append(
            {
                "post_id": post_id,
                "coverage_grade": grade,
                "observed_comment_count": observed_by_post[post_id],
                "cursor_outstanding_count": cursor_debt[post_id],
                "page_has_next": post_id in page_debt,
                "failed_report_count": failure_debt[post_id],
            }
        )
    coverage_counts = Counter(row["coverage_grade"] for row in post_coverage)
    blockers = {
        "first_page_missing": len(first_page_missing),
        "cursor_outstanding": len(reachable["cursor_outstanding"]),
        "page_pagination_outstanding": len(page_debt),
        "orphan_reply_reports": len(reachable["orphan_replies"]),
        "cursor_cycles": len(reachable["cursor_cycles"]),
        "report_conflicts": len(scanned["conflicts"]),
        "comment_conflicts": len(comment_conflicts),
        "failed_reports": len(scanned["failures"]),
    }
    status = (
        "complete"
        if not any(blockers.values())
        else "blocked_with_explicit_coverage_debt"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source": {
            "base_dataset_version": base_manifest["dataset_version"],
            "base_manifest_sha256": _file_sha256(base_path / "manifest.json"),
            "discovery_snapshot_sha256": _file_sha256(discovery_path),
            "discovery_target_set_id": discovery["target"]["set_id"],
            "source_freeze_manifest_sha256": _file_sha256(freeze_path),
            "source_cutoff_utc": freeze["source_cutoff_utc"],
            "comment_report_file_count": report_file_count,
            "comment_report_total_bytes": report_bytes,
            "comment_report_manifest_lf_sha256": report_lf_sha256,
            "parser_code_sha256": _file_sha256(
                Path(__file__).with_name("build_reddit_v2_raw_snapshot.py")
            ),
            "builder_code_sha256": _file_sha256(Path(__file__)),
        },
        "target": {
            "base_post_count": len(base_post_ids),
            "base_post_ids_lf_sha256": identity_hash(base_post_ids),
            "discovery_post_count": len(discovery_post_ids),
            "discovery_post_ids_lf_sha256": identity_hash(discovery_post_ids),
            "existing_post_count": len(target_ids),
            "existing_post_ids_lf_sha256": identity_hash(target_ids),
            "base_comment_count": len(base_comment_ids),
            "base_comment_ids_lf_sha256": identity_hash(base_comment_ids),
        },
        "baseline_identity": {
            "base_post_ids": list(base_post_ids),
            "base_comment_ids": sorted(base_comment_ids),
        },
        "accounting": {
            "comment_report_file_count": scanned["report_file_count"],
            "report_outcome_counts": report_outcome_counts,
            "accounted_report_count": accounted_report_count,
            "unaccounted_report_count": unaccounted_report_count,
            "ignored_non_target_comment_report_count": scanned[
                "ignored_non_target"
            ],
            "first_page_report_count": len(scanned["first_pages"]),
            "accepted_reply_report_count": len(scanned["replies"]),
            "reachable_report_count": len(reachable["reports"]),
            "canonical_observed_comment_count": len(observed_comments),
            "canonical_observed_comment_ids_lf_sha256": identity_hash(
                observed_ids
            ),
            "baseline_overlap_comment_count": len(overlap_ids),
            "baseline_overlap_comment_ids_lf_sha256": identity_hash(
                overlap_ids
            ),
            "gross_new_comment_count": len(gross_new_ids),
            "gross_new_comment_ids_lf_sha256": identity_hash(gross_new_ids),
            "baseline_retained_not_reobserved_count": len(retained_ids),
            "baseline_retained_not_reobserved_ids_lf_sha256": identity_hash(
                retained_ids
            ),
            "observed_identity_conserved": len(observed_ids)
            == len(overlap_ids) + len(gross_new_ids),
            "baseline_identity_conserved": len(base_comment_ids)
            == len(overlap_ids) + len(retained_ids),
            "gross_new_parent_post_count": len(
                {str(row["post_id"]) for row in gross_new_comments}
            ),
            "gross_new_deleted_or_removed_count": sum(
                bool(row.get("deleted_or_removed"))
                for row in gross_new_comments
            ),
            "gross_new_author_hash_null_count": sum(
                row.get("author_hash") is None for row in gross_new_comments
            ),
            "reply_source_resolution": scanned["reply_source_resolution"],
            "coverage_grade_counts": {
                "full": coverage_counts["full"],
                "partial": coverage_counts["partial"],
                "not_observed": coverage_counts["not_observed"],
            },
            "blockers": blockers,
            "failure_reason_counts": dict(sorted(failure_reason_counts.items())),
            "first_page_missing_post_ids_lf_sha256": identity_hash(
                first_page_missing
            ),
            "cursor_outstanding_keys_lf_sha256": identity_hash(
                f"{row['post_id']}\t{row['cursor_sha256']}"
                for row in reachable["cursor_outstanding"]
            ),
            "page_pagination_outstanding_post_ids_lf_sha256": identity_hash(
                page_debt
            ),
            "failed_report_keys_lf_sha256": identity_hash(
                sha256(canonical_bytes(row)).hexdigest()
                for row in scanned["failures"]
            ),
            "failed_reports": scanned["failures"],
            "report_conflicts": scanned["conflicts"],
            "comment_conflicts": comment_conflicts,
        },
        "coverage_work_items": {
            "first_page_missing_post_ids": sorted(first_page_missing),
            "cursor_outstanding": reachable["cursor_outstanding"],
            "page_pagination_outstanding_post_ids": sorted(page_debt),
            "failed_reports": scanned["failures"],
            "partial_post_ids": sorted(
                row["post_id"]
                for row in post_coverage
                if row["coverage_grade"] == "partial"
            ),
            "not_observed_post_ids": sorted(first_page_missing),
        },
        "comments": sorted(
            gross_new_comments, key=lambda row: str(row["comment_id"])
        ),
        "post_coverage": post_coverage,
        "source_reports": sorted(
            scanned["source_reports"],
            key=lambda row: (
                str(row["report_kind"]),
                str(row.get("post_id") or ""),
                str(row.get("cursor_sha256") or ""),
                str(row["report_sha256"]),
            ),
        ),
        "privacy": {
            "raw_payload_embedded": False,
            "raw_username_embedded": False,
            "author_identity": "sha256_hash_or_null",
            "cursor_identity": "sha256_only",
            "private_artifact": True,
        },
        "provider_call": False,
        "provider_attempt_made": False,
        "database_write": False,
        "remote_write": False,
        "production_merge": False,
        "deployment": False,
        "git_push": False,
        "live_send": False,
        "dingtalk": False,
        "production_unchanged": True,
    }


def write_snapshot(snapshot: dict[str, Any], destination: Path | str) -> str:
    path = Path(destination)
    payload = canonical_bytes(snapshot) + b"\n"
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise HydrationContractError("snapshot_destination_conflict")
        if (
            path.stat().st_mode & 0o777 != 0o600
            or path.parent.stat().st_mode & 0o777 != 0o700
        ):
            raise HydrationContractError("snapshot_destination_mode_mismatch")
    else:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(payload)
        path.parent.chmod(0o700)
        path.chmod(0o600)
    return sha256(payload).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--discovery-snapshot", type=Path, required=True)
    parser.add_argument("--source-freeze-manifest", type=Path, required=True)
    parser.add_argument("--comment-report-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshot = build(
        base_dir=args.base_dir,
        discovery_snapshot=args.discovery_snapshot,
        source_freeze_manifest=args.source_freeze_manifest,
        comment_report_root=args.comment_report_root,
    )
    digest = write_snapshot(snapshot, args.output)
    print(
        json.dumps(
            {
                "schema_version": "reddit_voc_existing_post_hydration_receipt_v1",
                "status": snapshot["status"],
                "snapshot_sha256": digest,
                "existing_post_count": snapshot["target"][
                    "existing_post_count"
                ],
                "gross_new_comment_count": snapshot["accounting"][
                    "gross_new_comment_count"
                ],
                "provider_call": False,
                "database_write": False,
                "remote_write": False,
                "production_unchanged": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if snapshot["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
