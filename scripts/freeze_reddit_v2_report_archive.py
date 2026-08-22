#!/usr/bin/env python3
"""Hash one quiescent V2 report directory into an immutable private manifest."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "reddit_voc_v2_report_file_manifest_v1"
REPORT_NAMES = frozenset(
    {
        "search-lane-probe.json",
        "search-continuation-probe.json",
        "comment-repair-probe.json",
        "comment-reply-probe.json",
    }
)


class ReportArchiveFreezeError(ValueError):
    """The report archive is unsafe, changing, or collides with a freeze."""


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ReportArchiveFreezeError("freeze_cutoff_utc_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReportArchiveFreezeError("freeze_cutoff_utc_invalid")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _scan(root: Path) -> dict[str, tuple[int, int, Path]]:
    result: dict[str, tuple[int, int, Path]] = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directory_names:
            path = base / name
            if path.is_symlink():
                raise ReportArchiveFreezeError("report_archive_symlink_found")
        for name in file_names:
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise ReportArchiveFreezeError("report_archive_member_unsafe")
            if name not in REPORT_NAMES:
                raise ReportArchiveFreezeError("report_archive_filename_invalid")
            relative = path.relative_to(root).as_posix()
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts or relative in result:
                raise ReportArchiveFreezeError("report_archive_path_invalid")
            stat = path.stat()
            if stat.st_size < 1:
                raise ReportArchiveFreezeError("report_archive_empty_member")
            result[relative] = (stat.st_size, stat.st_mtime_ns, path)
    if not result:
        raise ReportArchiveFreezeError("report_archive_empty")
    return result


def freeze_archive(reports_root: Path, *, freeze_cutoff_utc: str) -> dict[str, Any]:
    if reports_root.is_symlink():
        raise ReportArchiveFreezeError("reports_root_unsafe")
    try:
        root = reports_root.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ReportArchiveFreezeError("reports_root_missing") from exc
    if not root.is_dir():
        raise ReportArchiveFreezeError("reports_root_not_directory")
    before = _scan(root)
    rows: list[dict[str, Any]] = []
    for relative in sorted(before):
        size, mtime_ns, path = before[relative]
        digest = _sha256(path)
        stat = path.stat()
        if stat.st_size != size or stat.st_mtime_ns != mtime_ns:
            raise ReportArchiveFreezeError("report_archive_changed_during_hash")
        rows.append(
            {"relative_path": relative, "bytes": size, "sha256": digest}
        )
    after = _scan(root)
    if {
        key: value[:2] for key, value in before.items()
    } != {key: value[:2] for key, value in after.items()}:
        raise ReportArchiveFreezeError("report_archive_changed_during_scan")
    aggregate_payload = "".join(
        f"{row['relative_path']}|{row['bytes']}|{row['sha256']}\n" for row in rows
    ).encode("utf-8")
    counts = Counter(PurePosixPath(row["relative_path"]).name for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "freeze_cutoff_utc": _utc(freeze_cutoff_utc),
        "raw_payload_embedded_in_manifest": False,
        "quiescence_evidence": {
            "member_set_and_stat_stable_during_hash": True,
            "mtime_compared_as_integer_ns": True,
            "max_member_mtime_ns": max(value[1] for value in before.values()),
        },
        "file_count": len(rows),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
        "file_manifest_lf_sha256": sha256(aggregate_payload).hexdigest(),
        "report_counts": dict(sorted(counts.items())),
        "files": rows,
    }


def write_manifest(path: Path, value: dict[str, Any]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if path.exists():
        if not path.is_file() or path.is_symlink():
            raise ReportArchiveFreezeError("manifest_destination_unsafe")
        if path.read_bytes() != payload:
            raise ReportArchiveFreezeError("manifest_immutable_collision")
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--freeze-cutoff-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = freeze_archive(
        args.reports_root, freeze_cutoff_utc=args.freeze_cutoff_utc
    )
    status = write_manifest(args.output, manifest)
    print(
        json.dumps(
            {
                "schema_version": "reddit_voc_v2_report_archive_freeze_receipt_v1",
                "status": status,
                "manifest_sha256": _sha256(args.output),
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
                "file_manifest_lf_sha256": manifest[
                    "file_manifest_lf_sha256"
                ],
                "provider_call": False,
                "remote_write": False,
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
