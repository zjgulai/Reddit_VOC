#!/usr/bin/env python3
"""Freeze a fail-closed, build-only Reddit VOC incremental input contract."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable


SCHEMA_VERSION = "reddit_voc_incremental_input_freeze_v1"
IDENTITY_SCHEMA = "reddit_voc_v2_identity_freeze_v1"
RAW_SCHEMA = "reddit_voc_v2_raw_snapshot_v1"
POST_ID_RE = re.compile(r"^[a-z0-9]{5,10}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
FREEZE_ID_RE = re.compile(r"^reddit_voc_incremental_freeze_[a-z0-9_-]{3,96}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_COVERAGE_BLOCKERS = frozenset(
    {
        "lineage_missing",
        "first_page_missing",
        "cursor_outstanding",
        "page_pagination_outstanding",
    }
)
FATAL_BLOCKERS = frozenset(
    {
        "search_post_conflicts",
        "outside_target_window",
        "cursor_cycles",
        "orphan_reply_reports",
        "report_conflicts",
        "comment_conflicts",
        "failed_reports",
    }
)


class IncrementalFreezeError(ValueError):
    """The proposed candidate cannot be frozen as a build input."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_hash(values: Iterable[str]) -> str:
    return sha256(
        "".join(f"{value}\n" for value in sorted(set(values))).encode("utf-8")
    ).hexdigest()


def _load_object(path: Path, *, error: str) -> dict[str, Any]:
    if path.is_symlink():
        raise IncrementalFreezeError(f"{error}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise IncrementalFreezeError(f"{error}_missing") from exc
    if not resolved.is_file():
        raise IncrementalFreezeError(f"{error}_not_file")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IncrementalFreezeError(f"{error}_invalid_json") from exc
    if not isinstance(value, dict):
        raise IncrementalFreezeError(f"{error}_not_object")
    return value


def _utc(value: str, *, error: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IncrementalFreezeError(error)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise IncrementalFreezeError(error) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise IncrementalFreezeError(error)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _report_anchor(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise IncrementalFreezeError("report_anchor_date_invalid") from exc


def _identity_set(
    value: dict[str, Any], *, set_id: str, label: str
) -> tuple[list[str], str]:
    if value.get("schema_version") != IDENTITY_SCHEMA:
        raise IncrementalFreezeError(f"{label}_schema_invalid")
    boundaries = value.get("boundaries")
    if not isinstance(boundaries, dict) or any(item is not False for item in boundaries.values()):
        raise IncrementalFreezeError(f"{label}_boundary_invalid")
    rows = value.get("identity_sets")
    matches = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("set_id") == set_id
    ] if isinstance(rows, list) else []
    if len(matches) != 1:
        raise IncrementalFreezeError(f"{label}_identity_set_not_unique")
    row = matches[0]
    post_ids = row.get("post_ids")
    if not isinstance(post_ids, list) or any(
        not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None
        for post_id in post_ids
    ):
        raise IncrementalFreezeError(f"{label}_post_ids_invalid")
    if len(set(post_ids)) != len(post_ids):
        raise IncrementalFreezeError(f"{label}_post_ids_duplicate")
    digest = _identity_hash(post_ids)
    if row.get("count") != len(post_ids) or row.get("lf_sha256") != digest:
        raise IncrementalFreezeError(f"{label}_identity_summary_mismatch")
    return sorted(post_ids), digest


def _validate_raw_snapshot(
    *,
    raw: dict[str, Any],
    raw_path: Path,
    candidate_identity_path: Path,
    set_id: str,
    candidate_ids: list[str],
    candidate_hash: str,
) -> dict[str, int | str]:
    if raw.get("schema_version") != RAW_SCHEMA:
        raise IncrementalFreezeError("raw_snapshot_schema_invalid")
    if raw.get("status") not in {"blocked", "complete"}:
        raise IncrementalFreezeError("raw_snapshot_status_invalid")
    for field in (
        "provider_call",
        "provider_attempt_made",
        "database_write",
        "production_merge",
        "live_send",
        "git_push",
        "dingtalk",
    ):
        if raw.get(field) is not False:
            raise IncrementalFreezeError(f"raw_snapshot_{field}_boundary_invalid")
    privacy = raw.get("privacy")
    if (
        not isinstance(privacy, dict)
        or privacy.get("raw_payload_embedded") is not False
        or privacy.get("raw_username_embedded") is not False
    ):
        raise IncrementalFreezeError("raw_snapshot_privacy_invalid")
    target = raw.get("target")
    if not isinstance(target, dict):
        raise IncrementalFreezeError("raw_snapshot_target_invalid")
    if (
        target.get("set_id") != set_id
        or target.get("count") != len(candidate_ids)
        or target.get("post_ids_sha256") != candidate_hash
        or target.get("identity_inventory_sha256")
        != _sha256(candidate_identity_path)
    ):
        raise IncrementalFreezeError("raw_snapshot_target_mismatch")

    accounting = raw.get("accounting")
    blockers = accounting.get("blockers") if isinstance(accounting, dict) else None
    if not isinstance(accounting, dict) or not isinstance(blockers, dict):
        raise IncrementalFreezeError("raw_snapshot_accounting_invalid")
    unknown = set(blockers) - ALLOWED_COVERAGE_BLOCKERS - FATAL_BLOCKERS
    if unknown:
        raise IncrementalFreezeError("raw_snapshot_unknown_blocker")
    for field in FATAL_BLOCKERS:
        if blockers.get(field) != 0:
            raise IncrementalFreezeError(f"raw_snapshot_{field}_not_admissible")
    for field in ALLOWED_COVERAGE_BLOCKERS:
        value = blockers.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise IncrementalFreezeError(f"raw_snapshot_{field}_invalid")
    if accounting.get("target_search_row_rejection_count") != 0:
        raise IncrementalFreezeError("raw_snapshot_target_search_row_rejection")

    lineage_ids = accounting.get("lineage_missing_post_ids")
    first_page_ids = accounting.get("first_page_missing_post_ids")
    if not isinstance(lineage_ids, list) or not isinstance(first_page_ids, list):
        raise IncrementalFreezeError("raw_snapshot_missing_identity_sets_invalid")
    if any(
        not isinstance(post_id, str) or POST_ID_RE.fullmatch(post_id) is None
        for post_id in [*lineage_ids, *first_page_ids]
    ):
        raise IncrementalFreezeError("raw_snapshot_missing_post_id_invalid")
    lineage_set = set(lineage_ids)
    first_page_set = set(first_page_ids)
    candidate_set = set(candidate_ids)
    if (
        len(lineage_set) != len(lineage_ids)
        or len(first_page_set) != len(first_page_ids)
        or not lineage_set <= candidate_set
        or first_page_set != lineage_set
        or blockers["lineage_missing"] != len(lineage_set)
        or blockers["first_page_missing"] != len(first_page_set)
    ):
        raise IncrementalFreezeError("raw_snapshot_missing_identity_relation_invalid")
    posts = raw.get("posts")
    comments = raw.get("comments")
    analyses = raw.get("analyses")
    if not isinstance(posts, list) or not isinstance(comments, list) or not isinstance(analyses, list):
        raise IncrementalFreezeError("raw_snapshot_entities_invalid")
    raw_post_ids = [row.get("post_id") for row in posts if isinstance(row, dict)]
    if (
        len(raw_post_ids) != len(posts)
        or len(set(raw_post_ids)) != len(raw_post_ids)
        or set(raw_post_ids) != candidate_set - lineage_set
    ):
        raise IncrementalFreezeError("raw_snapshot_post_identity_relation_invalid")
    if (
        accounting.get("canonical_post_count") != len(posts)
        or accounting.get("canonical_comment_count") != len(comments)
        or accounting.get("canonical_analysis_count") != len(analyses)
        or len(analyses) != len(posts) + len(comments)
    ):
        raise IncrementalFreezeError("raw_snapshot_entity_count_mismatch")
    return {
        "raw_snapshot_sha256": _sha256(raw_path),
        "admitted_post_count": len(posts),
        "observed_comment_count": len(comments),
        "lineage_gap_count": len(lineage_set),
        "lineage_gap_lf_sha256": _identity_hash(lineage_set),
        "cursor_outstanding": blockers["cursor_outstanding"],
        "page_pagination_outstanding": blockers[
            "page_pagination_outstanding"
        ],
    }


def _artifact_contract(project_root: Path, name: str, path: Path) -> dict[str, Any]:
    if NAME_RE.fullmatch(name) is None:
        raise IncrementalFreezeError("artifact_name_invalid")
    if path.is_symlink():
        raise IncrementalFreezeError(f"artifact_unsafe:{name}")
    try:
        root = project_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise IncrementalFreezeError(f"artifact_outside_project:{name}") from exc
    if not resolved.is_file():
        raise IncrementalFreezeError(f"artifact_not_file:{name}")
    return {
        "repo_relative_path": relative.as_posix(),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def build_freeze(
    *,
    project_root: Path,
    freeze_id: str,
    generated_at_utc: str,
    source_cutoff_utc: str,
    report_anchor_date: str,
    identity_set_id: str,
    previous_identity_path: Path,
    candidate_identity_path: Path,
    raw_snapshot_path: Path,
    artifacts: list[tuple[str, Path]],
) -> dict[str, Any]:
    if FREEZE_ID_RE.fullmatch(freeze_id) is None:
        raise IncrementalFreezeError("freeze_id_invalid")
    generated_at = _utc(generated_at_utc, error="generated_at_utc_invalid")
    source_cutoff = _utc(source_cutoff_utc, error="source_cutoff_utc_invalid")
    anchor = _report_anchor(report_anchor_date)
    previous = _load_object(previous_identity_path, error="previous_identity")
    candidate = _load_object(candidate_identity_path, error="candidate_identity")
    raw = _load_object(raw_snapshot_path, error="raw_snapshot")
    previous_ids, previous_hash = _identity_set(
        previous, set_id=identity_set_id, label="previous"
    )
    candidate_ids, candidate_hash = _identity_set(
        candidate, set_id=identity_set_id, label="candidate"
    )
    previous_set = set(previous_ids)
    candidate_set = set(candidate_ids)
    if not previous_set <= candidate_set:
        raise IncrementalFreezeError("identity_regression_without_tombstone")
    added = sorted(candidate_set - previous_set)
    raw_facts = _validate_raw_snapshot(
        raw=raw,
        raw_path=raw_snapshot_path,
        candidate_identity_path=candidate_identity_path,
        set_id=identity_set_id,
        candidate_ids=candidate_ids,
        candidate_hash=candidate_hash,
    )
    named: dict[str, dict[str, Any]] = {}
    required = [
        ("previous_identity_freeze", previous_identity_path),
        ("candidate_identity_freeze", candidate_identity_path),
        ("v2_raw_snapshot", raw_snapshot_path),
        *artifacts,
    ]
    for name, path in required:
        if name in named:
            raise IncrementalFreezeError(f"artifact_name_duplicate:{name}")
        named[name] = _artifact_contract(project_root, name, path)

    return {
        "schema_version": SCHEMA_VERSION,
        "freeze_id": freeze_id,
        "generated_at_utc": generated_at,
        "source_cutoff_utc": source_cutoff,
        "report_anchor_date": anchor,
        "identity": {
            "set_id": identity_set_id,
            "previous_count": len(previous_ids),
            "previous_lf_sha256": previous_hash,
            "candidate_count": len(candidate_ids),
            "candidate_lf_sha256": candidate_hash,
            "added_count": len(added),
            "added_lf_sha256": _identity_hash(added),
            "monotonic_without_tombstone": True,
        },
        "coverage": raw_facts,
        "artifacts": dict(sorted(named.items())),
        "status": "frozen_build_input",
        "evidence_grade": "L2-local-immutable-input",
        "boundaries": {
            "provider_call": False,
            "provider_attempt_made": False,
            "remote_write": False,
            "database_write": False,
            "production_merge": False,
            "deploy": False,
            "schedule_change": False,
            "live_send": False,
        },
    }


def write_freeze(path: Path, value: dict[str, Any]) -> str:
    payload = _canonical_bytes(value) + b"\n"
    if path.exists():
        if not path.is_file() or path.is_symlink():
            raise IncrementalFreezeError("freeze_destination_unsafe")
        if path.read_bytes() != payload:
            raise IncrementalFreezeError("freeze_immutable_collision")
        return "no_change"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "created"


def _artifact_arg(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not raw_path:
        raise argparse.ArgumentTypeError("artifact must be NAME=PATH")
    return name, Path(raw_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--freeze-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--source-cutoff-utc", required=True)
    parser.add_argument("--report-anchor-date", required=True)
    parser.add_argument("--identity-set-id", default="discovery_only")
    parser.add_argument("--previous-identity-freeze", type=Path, required=True)
    parser.add_argument("--candidate-identity-freeze", type=Path, required=True)
    parser.add_argument("--v2-raw-snapshot", type=Path, required=True)
    parser.add_argument("--artifact", type=_artifact_arg, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    value = build_freeze(
        project_root=args.project_root,
        freeze_id=args.freeze_id,
        generated_at_utc=args.generated_at_utc,
        source_cutoff_utc=args.source_cutoff_utc,
        report_anchor_date=args.report_anchor_date,
        identity_set_id=args.identity_set_id,
        previous_identity_path=args.previous_identity_freeze,
        candidate_identity_path=args.candidate_identity_freeze,
        raw_snapshot_path=args.v2_raw_snapshot,
        artifacts=args.artifact,
    )
    status = write_freeze(args.output, value)
    print(
        json.dumps(
            {
                "schema_version": "reddit_voc_incremental_input_freeze_receipt_v1",
                "status": status,
                "freeze_id": value["freeze_id"],
                "freeze_sha256": _sha256(args.output),
                "added_post_identities": value["identity"]["added_count"],
                "provider_call": False,
                "database_write": False,
                "deploy": False,
                "live_send": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
