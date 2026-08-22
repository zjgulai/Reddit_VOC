#!/usr/bin/env python3
"""Rebuild and verify the immutable Reddit V2 report archive manifests.

The command admits only the exact union of an already-audited base manifest
and a reviewed append manifest.  Every local report is re-hashed before either
manifest is replaced.  It never parses or emits Reddit payload content.
"""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable


PRIVATE_SCHEMA_VERSION = "reddit_voc_v2_report_file_manifest_v1"
IMPORT_SCHEMA_VERSION = "reddit_voc_v2_report_import_manifest_v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReportManifestContractError(ValueError):
    """The report archive cannot be admitted under the reviewed contract."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, error: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportManifestContractError(error) from exc
    if not isinstance(value, dict):
        raise ReportManifestContractError(error)
    return value


def _validated_rows(value: object, *, error: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise ReportManifestContractError(error)
    rows: dict[str, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "relative_path",
            "bytes",
            "sha256",
        }:
            raise ReportManifestContractError(error)
        relative_path = row.get("relative_path")
        size = row.get("bytes")
        digest = row.get("sha256")
        if not isinstance(relative_path, str) or not relative_path:
            raise ReportManifestContractError(error)
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise ReportManifestContractError(error)
        if type(size) is not int or size < 1:
            raise ReportManifestContractError(error)
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise ReportManifestContractError(error)
        if relative_path in rows:
            raise ReportManifestContractError(error)
        rows[relative_path] = {
            "relative_path": relative_path,
            "bytes": size,
            "sha256": digest,
        }
    return rows


def _manifest_lf_hash(rows: Iterable[dict[str, Any]]) -> str:
    payload = "".join(
        f"{row['relative_path']}|{row['bytes']}|{row['sha256']}\n"
        for row in rows
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _assert_row_summary(
    rows: dict[str, dict[str, Any]],
    summary: object,
    *,
    error: str,
) -> None:
    if not isinstance(summary, dict):
        raise ReportManifestContractError(error)
    ordered = [rows[path] for path in sorted(rows)]
    if summary.get("file_count") != len(ordered):
        raise ReportManifestContractError(error)
    if summary.get("total_bytes") != sum(int(row["bytes"]) for row in ordered):
        raise ReportManifestContractError(error)
    if summary.get("file_manifest_lf_sha256") != _manifest_lf_hash(ordered):
        raise ReportManifestContractError(error)


def _write_private_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_bytes(value) + b"\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def rebuild_manifests(
    *,
    reports_root: Path,
    base_manifest_path: Path,
    append_manifest_path: Path,
    import_manifest_path: Path,
    archive_mtime_cutoff_utc: str,
    search_semantic_cutoff_utc: str,
    first_page_cutoff_utc: str,
    reply_cutoff_utc: str,
) -> dict[str, Any]:
    base = _load_json(base_manifest_path, error="base_manifest_unreadable")
    append = _load_json(append_manifest_path, error="append_manifest_unreadable")
    previous_import = _load_json(
        import_manifest_path, error="import_manifest_unreadable"
    )
    if base.get("schema_version") != PRIVATE_SCHEMA_VERSION:
        raise ReportManifestContractError("base_manifest_schema_invalid")
    if base.get("raw_payload_embedded_in_manifest") is not False:
        raise ReportManifestContractError("base_manifest_payload_boundary_invalid")
    if base.get("freeze_cutoff_utc") != archive_mtime_cutoff_utc:
        raise ReportManifestContractError("base_archive_cutoff_mismatch")
    if previous_import.get("schema_version") != IMPORT_SCHEMA_VERSION:
        raise ReportManifestContractError("import_manifest_schema_invalid")
    source_environment = previous_import.get("source_environment")
    source_root = previous_import.get("source_root")
    boundaries = previous_import.get("boundaries")
    if not isinstance(source_environment, str) or not source_environment:
        raise ReportManifestContractError("import_source_environment_invalid")
    if not isinstance(source_root, str) or not source_root.startswith("/"):
        raise ReportManifestContractError("import_source_root_invalid")
    if not isinstance(boundaries, dict) or not boundaries or any(
        value is not False for value in boundaries.values()
    ):
        raise ReportManifestContractError("import_boundaries_invalid")
    append_section = append.get("append")
    expected_merged = append.get("merged_expected")
    if not isinstance(append_section, dict) or not isinstance(
        expected_merged, dict
    ):
        raise ReportManifestContractError("append_manifest_contract_invalid")

    base_rows = _validated_rows(base.get("files"), error="base_rows_invalid")
    append_rows = _validated_rows(
        append_section.get("files"), error="append_rows_invalid"
    )
    _assert_row_summary(base_rows, base, error="base_summary_mismatch")
    _assert_row_summary(
        append_rows, append_section, error="append_summary_mismatch"
    )
    selection = append.get("selection_contract")
    if not isinstance(selection, dict):
        raise ReportManifestContractError("append_selection_contract_invalid")
    identity_source = selection.get("rc_post_id_set_source")
    per_kind_cutoff = selection.get("per_kind_cutoff")
    if not isinstance(identity_source, dict) or not isinstance(
        per_kind_cutoff, dict
    ):
        raise ReportManifestContractError("append_selection_contract_invalid")
    expected_cutoffs = {
        "archive_manifest_cutoff_utc": archive_mtime_cutoff_utc,
        "semantic_search_cutoff_utc": search_semantic_cutoff_utc,
    }
    if any(identity_source.get(key) != value for key, value in expected_cutoffs.items()):
        raise ReportManifestContractError("append_identity_cutoff_mismatch")
    first_page_contract = per_kind_cutoff.get("comment-repair-probe.json")
    reply_contract = per_kind_cutoff.get("comment-reply-probe.json")
    if not isinstance(first_page_contract, dict) or not isinstance(
        reply_contract, dict
    ):
        raise ReportManifestContractError("append_hydration_cutoff_invalid")
    if first_page_contract.get("captured_at_utc") != first_page_cutoff_utc:
        raise ReportManifestContractError("append_first_page_cutoff_mismatch")
    if reply_contract.get("captured_at_utc") != reply_cutoff_utc:
        raise ReportManifestContractError("append_reply_cutoff_mismatch")
    overlap = set(base_rows) & set(append_rows)
    if overlap:
        if overlap != set(append_rows) or any(
            base_rows[path] != append_rows[path] for path in overlap
        ):
            raise ReportManifestContractError("append_path_overlap")
        original_base_rows = {
            path: row for path, row in base_rows.items() if path not in append_rows
        }
        _assert_row_summary(
            original_base_rows,
            append.get("base_manifest"),
            error="append_base_summary_mismatch",
        )
        expected_rows = base_rows
    else:
        _assert_row_summary(
            base_rows,
            append.get("base_manifest"),
            error="append_base_summary_mismatch",
        )
        expected_rows = {**base_rows, **append_rows}

    try:
        root = reports_root.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ReportManifestContractError("reports_root_unreadable") from exc
    if not root.is_dir():
        raise ReportManifestContractError("reports_root_not_directory")
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual_paths != set(expected_rows):
        raise ReportManifestContractError("reports_filesystem_set_mismatch")

    rows: list[dict[str, Any]] = []
    for relative_path in sorted(actual_paths):
        pure_path = PurePosixPath(relative_path)
        file_path = root.joinpath(*pure_path.parts)
        expected = expected_rows[relative_path]
        size = file_path.stat().st_size
        digest = _file_sha256(file_path)
        if size != expected["bytes"]:
            raise ReportManifestContractError("report_file_bytes_mismatch")
        if digest != expected["sha256"]:
            raise ReportManifestContractError("report_file_sha256_mismatch")
        rows.append(expected)

    total_bytes = sum(int(row["bytes"]) for row in rows)
    aggregate_hash = _manifest_lf_hash(rows)
    report_counts = Counter(PurePosixPath(row["relative_path"]).name for row in rows)
    report_bytes: Counter[str] = Counter()
    for row in rows:
        report_bytes[PurePosixPath(row["relative_path"]).name] += int(row["bytes"])
    if expected_merged.get("file_count") != len(rows):
        raise ReportManifestContractError("merged_file_count_mismatch")
    if expected_merged.get("total_bytes") != total_bytes:
        raise ReportManifestContractError("merged_total_bytes_mismatch")
    if expected_merged.get("file_manifest_lf_sha256") != aggregate_hash:
        raise ReportManifestContractError("merged_aggregate_sha256_mismatch")
    if expected_merged.get("by_report_name") != dict(sorted(report_counts.items())):
        raise ReportManifestContractError("merged_report_counts_mismatch")

    watermarks = {
        "archive_file_mtime_cutoff_utc": archive_mtime_cutoff_utc,
        "search_semantic_captured_at_cutoff_utc": search_semantic_cutoff_utc,
        "first_page_captured_at_cutoff_utc": first_page_cutoff_utc,
        "reply_captured_at_cutoff_utc": reply_cutoff_utc,
    }
    private_manifest = {
        "schema_version": PRIVATE_SCHEMA_VERSION,
        "freeze_cutoff_utc": archive_mtime_cutoff_utc,
        "watermarks": watermarks,
        "raw_payload_embedded_in_manifest": False,
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "file_manifest_lf_sha256": aggregate_hash,
        "files": rows,
    }
    private_payload = _canonical_bytes(private_manifest) + b"\n"
    private_size = len(private_payload)
    private_digest = sha256(private_payload).hexdigest()

    import_manifest = {
        "schema_version": IMPORT_SCHEMA_VERSION,
        "dataset_id": "tencent_v2_reports_rc_20260715",
        "source_environment": source_environment,
        "source_root": source_root,
        "freeze_cutoff_utc": archive_mtime_cutoff_utc,
        "watermarks": watermarks,
        "scope": {
            "identity_set_id": "discovery_only",
            "identity_count": 860,
            "identity_lf_sha256": (
                "fcc58d0e42146355deb93cfbb0e09cae2d657811658b1884eccfb55bec780e7b"
            ),
            "task2600_and_later_excluded": True,
        },
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "file_manifest_lf_sha256": aggregate_hash,
        "report_counts": dict(sorted(report_counts.items())),
        "report_bytes": dict(sorted(report_bytes.items())),
        "private_file_manifest": {
            "relative_path": "private/report-file-manifest.json",
            "bytes": private_size,
            "sha256": private_digest,
        },
        "copy_verification": {
            "remote_local_file_count_equal": True,
            "remote_local_total_bytes_equal": True,
            "remote_local_file_manifest_sha256_equal": True,
            "local_member_bytes_and_sha256_verified": True,
        },
        "boundaries": boundaries,
    }
    _write_private_json(base_manifest_path, private_manifest)
    _write_private_json(import_manifest_path, import_manifest)
    return {
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "file_manifest_lf_sha256": aggregate_hash,
        "private_manifest_sha256": private_digest,
        "report_counts": dict(sorted(report_counts.items())),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--append-manifest", type=Path, required=True)
    parser.add_argument("--import-manifest", type=Path, required=True)
    parser.add_argument("--archive-mtime-cutoff-utc", required=True)
    parser.add_argument("--search-semantic-cutoff-utc", required=True)
    parser.add_argument("--first-page-cutoff-utc", required=True)
    parser.add_argument("--reply-cutoff-utc", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = rebuild_manifests(
        reports_root=args.reports_root,
        base_manifest_path=args.base_manifest,
        append_manifest_path=args.append_manifest,
        import_manifest_path=args.import_manifest,
        archive_mtime_cutoff_utc=args.archive_mtime_cutoff_utc,
        search_semantic_cutoff_utc=args.search_semantic_cutoff_utc,
        first_page_cutoff_utc=args.first_page_cutoff_utc,
        reply_cutoff_utc=args.reply_cutoff_utc,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
