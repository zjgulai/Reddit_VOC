#!/usr/bin/env python3
"""Independently reopen and validate the V3 source manifest and source files."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Sequence
import warnings

from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v3_source_manifest import (  # noqa: E402
    SourceContract,
    SourceManifestError,
    load_source_manifest,
)


POST_TYPE = "forum post"
COMMENT_TYPE = "forum post reply"
STRICT_CALENDAR_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
STRICT_MIDNIGHT_DATE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T| )00:00:00$"
)


class SourceManifestValidationError(ValueError):
    """A source-manifest binding or physical workbook invariant failed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_relative_file(
    project_root: Path,
    relative_path: PurePosixPath,
    *,
    label: str,
) -> Path:
    root = Path(os.path.abspath(os.fspath(project_root)))
    current = root
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise SourceManifestValidationError(f"{label} unavailable") from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise SourceManifestValidationError("project_root is unsafe")
    for part in relative_path.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise SourceManifestValidationError(f"{label} unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise SourceManifestValidationError(f"{label} must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise SourceManifestValidationError(f"{label} must be a regular file")
    return current


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceManifestValidationError(f"duplicate json key:{key}")
        result[key] = value
    return result


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceManifestValidationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise SourceManifestValidationError(f"{label} must be a JSON object")
    return value


def _calendar_date(value: object, *, source_id: str, row_number: int) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None and value.time().isoformat() == "00:00:00":
            return value.date().isoformat()
    elif isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if STRICT_CALENDAR_DATE.fullmatch(text):
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError:
                pass
        elif STRICT_MIDNIGHT_DATE.fullmatch(text):
            try:
                return datetime.fromisoformat(text).date().isoformat()
            except ValueError:
                pass
    raise SourceManifestValidationError(
        f"workbook published date invalid:{source_id}:row={row_number}"
    )


def _validate_base(manifest: Any, project_root: Path) -> dict[str, str]:
    public_path = _regular_relative_file(
        project_root,
        manifest.base.manifest_relative_path,
        label="base manifest",
    )
    public_digest = _sha256(public_path)
    if public_digest != manifest.base.public_manifest_sha256:
        raise SourceManifestValidationError("base public manifest sha256 mismatch")
    public_value = _json_object(public_path, label="base manifest")
    if public_value.get("dataset_version") != manifest.base.dataset_version:
        raise SourceManifestValidationError("base dataset_version mismatch")
    if public_value.get("schema_version") not in {
        "reddit_voc_site_snapshot_manifest_v1",
        "reddit_voc_site_snapshot_manifest_v2",
    }:
        raise SourceManifestValidationError("base schema_version unsupported")
    projection = public_value.get("projection")
    if not isinstance(projection, dict) or projection.get("audience") != "public_ui":
        raise SourceManifestValidationError("base public manifest role mismatch")

    lineage_path = _regular_relative_file(
        project_root,
        manifest.base.lineage_manifest_relative_path,
        label="base lineage manifest",
    )
    lineage_digest = _sha256(lineage_path)
    if lineage_digest != manifest.base.lineage_manifest_sha256:
        raise SourceManifestValidationError("base lineage manifest sha256 mismatch")
    lineage_value = _json_object(lineage_path, label="base lineage manifest")
    if lineage_value.get("dataset_version") != manifest.base.dataset_version:
        raise SourceManifestValidationError("base lineage dataset_version mismatch")
    if lineage_value.get("schema_version") not in {
        "reddit_voc_site_snapshot_manifest_v1",
        "reddit_voc_site_snapshot_manifest_v2",
    }:
        raise SourceManifestValidationError("base lineage schema_version unsupported")
    if not isinstance(lineage_value.get("source_boundaries"), dict):
        raise SourceManifestValidationError("base lineage manifest role mismatch")
    return {
        "dataset_version": manifest.base.dataset_version,
        "lineage_manifest_sha256": lineage_digest,
        "public_manifest_sha256": public_digest,
    }


def _validate_workbook(source: SourceContract, project_root: Path) -> dict[str, Any]:
    path = _regular_relative_file(
        project_root,
        source.relative_path,
        label=f"workbook:{source.source_snapshot_id}",
    )
    if _sha256(path) != source.sha256 or path.stat().st_size != source.bytes:
        raise SourceManifestValidationError(
            f"workbook physical binding mismatch:{source.source_snapshot_id}"
        )

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style, apply openpyxl's default",
            category=UserWarning,
        )
        workbook = load_workbook(path, read_only=False, data_only=True)
    try:
        if source.workbook.sheet_name not in workbook.sheetnames:
            raise SourceManifestValidationError(
                f"workbook sheet missing:{source.source_snapshot_id}"
            )
        sheet = workbook[source.workbook.sheet_name]
        dimension = sheet.calculate_dimension()
        if dimension != source.workbook.expected_dimension:
            raise SourceManifestValidationError(
                f"workbook dimension mismatch:{source.source_snapshot_id}"
            )
        headers = tuple(sheet.cell(row=1, column=index).value for index in range(1, 22))
        if headers != source.workbook.expected_headers:
            raise SourceManifestValidationError(
                f"workbook headers mismatch:{source.source_snapshot_id}"
            )

        counts: Counter[str] = Counter()
        observed_dates: list[str] = []
        data_rows = 0
        for row_number, row in enumerate(
            sheet.iter_rows(min_row=2, max_col=21, values_only=True),
            start=2,
        ):
            if not any(value is not None and str(value).strip() for value in row):
                raise SourceManifestValidationError(
                    f"workbook empty data row:{source.source_snapshot_id}:row={row_number}"
                )
            data_rows += 1
            entity_type = str(row[7] or "").strip().casefold()
            if entity_type == POST_TYPE:
                counts["posts"] += 1
            elif entity_type == COMMENT_TYPE:
                counts["comments"] += 1
            else:
                raise SourceManifestValidationError(
                    f"workbook entity type invalid:{source.source_snapshot_id}:row={row_number}"
                )
            observed_dates.append(
                _calendar_date(
                    row[19],
                    source_id=source.source_snapshot_id,
                    row_number=row_number,
                )
            )
    finally:
        workbook.close()

    if data_rows != source.workbook.expected_data_rows:
        raise SourceManifestValidationError(
            f"workbook data rows mismatch:{source.source_snapshot_id}"
        )
    if counts["posts"] != source.workbook.expected_post_rows:
        raise SourceManifestValidationError(
            f"workbook post rows mismatch:{source.source_snapshot_id}"
        )
    if counts["comments"] != source.workbook.expected_comment_rows:
        raise SourceManifestValidationError(
            f"workbook comment rows mismatch:{source.source_snapshot_id}"
        )
    if min(observed_dates) != source.selection_window.start_calendar_date:
        raise SourceManifestValidationError(
            f"workbook start date mismatch:{source.source_snapshot_id}"
        )
    if max(observed_dates) != source.selection_window.end_calendar_date:
        raise SourceManifestValidationError(
            f"workbook end date mismatch:{source.source_snapshot_id}"
        )
    return {
        "comment_rows": counts["comments"],
        "data_rows": data_rows,
        "dimension": dimension,
        "end_calendar_date": max(observed_dates),
        "post_rows": counts["posts"],
        "sha256": source.sha256,
        "source_snapshot_id": source.source_snapshot_id,
        "start_calendar_date": min(observed_dates),
    }


def validate_source_manifest(
    manifest_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Reopen every physical input and return a deterministic read-only summary."""

    try:
        manifest = load_source_manifest(Path(manifest_path), Path(project_root))
    except SourceManifestError as exc:
        raise SourceManifestValidationError(str(exc)) from exc
    base = _validate_base(manifest, Path(project_root))
    sources = [
        _validate_workbook(source, Path(project_root)) for source in manifest.sources
    ]
    return {
        "base_dataset_version": base["dataset_version"],
        "base_lineage_manifest_sha256": base["lineage_manifest_sha256"],
        "base_public_manifest_sha256": base["public_manifest_sha256"],
        "comment_rows": sum(item["comment_rows"] for item in sources),
        "dataset_id": manifest.dataset_id,
        "manifest_sha256": manifest.manifest_sha256,
        "post_rows": sum(item["post_rows"] for item in sources),
        "production_unchanged": manifest.boundaries.production_unchanged,
        "source_count": len(sources),
        "source_rows": sum(item["data_rows"] for item in sources),
        "sources": sources,
        "status": "passed",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--project-root", default=Path.cwd(), type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        summary = validate_source_manifest(arguments.manifest, arguments.project_root)
    except SourceManifestValidationError as exc:
        print(f"source_manifest_validation_failed:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
