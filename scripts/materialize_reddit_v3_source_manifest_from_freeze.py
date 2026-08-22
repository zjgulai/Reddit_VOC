#!/usr/bin/env python3
"""Bind a V3 source manifest to one immutable local source freeze.

The V3 source-manifest schema intentionally contains only data-source
contracts.  This adapter changes no source metadata: it replaces each
``relative_path`` with the matching byte-for-byte member in a run-scoped source
freeze, re-validates the complete manifest, and writes one immutable V3
manifest under the local candidate artifact root.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v3_source_manifest import (  # noqa: E402
    SourceManifestError,
    load_source_manifest,
)

try:
    from scripts.build_reddit_v3_source_manifest import (  # noqa: E402
        SourceManifestBuildError,
        _prepare_output_parent,
        _write_immutable,
    )
    from scripts.capture_reddit_candidate_sources import (  # noqa: E402
        MANIFEST_SCHEMA_VERSION as FREEZE_SCHEMA_VERSION,
        _canonical_bytes as freeze_canonical_bytes,
    )
except ModuleNotFoundError:  # Direct script execution.
    from build_reddit_v3_source_manifest import (
        SourceManifestBuildError,
        _prepare_output_parent,
        _write_immutable,
    )
    from capture_reddit_candidate_sources import (
        MANIFEST_SCHEMA_VERSION as FREEZE_SCHEMA_VERSION,
        _canonical_bytes as freeze_canonical_bytes,
    )


class SourceFreezeBridgeError(ValueError):
    """A freeze or its requested source mapping is unsafe or incomplete."""


def _project_path(value: Path, *, project_root: Path, label: str) -> Path:
    path = value if value.is_absolute() else project_root / value
    path = Path(path.absolute())
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise SourceFreezeBridgeError(f"{label}_outside_project_root") from exc
    return path


def _canonical_source_manifest(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _load_canonical_object(path: Path, *, label: str, canonical: bytes) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceFreezeBridgeError(f"{label}_invalid") from exc
    if not isinstance(value, dict) or payload != canonical(value):
        raise SourceFreezeBridgeError(f"{label}_noncanonical")
    return value


def _mapping(values: Sequence[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        source_id, separator, namespace = value.partition("=")
        if (
            not separator
            or not source_id
            or not namespace
            or source_id in mapping
            or "/" in namespace
            or "\\" in namespace
        ):
            raise SourceFreezeBridgeError("source_namespace_mapping_invalid")
        mapping[source_id] = namespace
    if not mapping:
        raise SourceFreezeBridgeError("source_namespace_mapping_empty")
    return mapping


def _freeze_members(path: Path, *, project_root: Path) -> dict[tuple[str, str], Mapping[str, Any]]:
    freeze = _load_canonical_object(
        path,
        label="source_freeze_manifest",
        canonical=lambda value: freeze_canonical_bytes(value) + b"\n",
    )
    if freeze.get("schema_version") != FREEZE_SCHEMA_VERSION:
        raise SourceFreezeBridgeError("source_freeze_schema_invalid")
    files = freeze.get("files")
    if not isinstance(files, list) or not files:
        raise SourceFreezeBridgeError("source_freeze_files_invalid")
    members: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in files:
        if not isinstance(row, dict) or set(row) != {
            "source_namespace",
            "source_kind",
            "relative_path",
            "destination_relative_path",
            "bytes",
            "mtime_ns",
            "sha256",
            "fusion_eligible",
        }:
            raise SourceFreezeBridgeError("source_freeze_member_invalid")
        namespace = row["source_namespace"]
        relative = row["relative_path"]
        destination = row["destination_relative_path"]
        if (
            not isinstance(namespace, str)
            or not isinstance(relative, str)
            or not isinstance(destination, str)
            or destination != f"sources/{namespace}/{relative}"
            or not isinstance(row["bytes"], int)
            or row["bytes"] <= 0
            or not isinstance(row["sha256"], str)
            or len(row["sha256"]) != 64
        ):
            raise SourceFreezeBridgeError("source_freeze_member_invalid")
        member_path = path.parent / destination
        try:
            member_project_relative = member_path.relative_to(project_root).as_posix()
        except ValueError as exc:
            raise SourceFreezeBridgeError("source_freeze_outside_project_root") from exc
        try:
            member_payload = member_path.read_bytes()
        except OSError as exc:
            raise SourceFreezeBridgeError("source_freeze_member_missing") from exc
        if (
            len(member_payload) != row["bytes"]
            or sha256(member_payload).hexdigest() != row["sha256"]
        ):
            raise SourceFreezeBridgeError("source_freeze_member_drift")
        key = (namespace, relative)
        if key in members:
            raise SourceFreezeBridgeError("source_freeze_member_duplicate")
        members[key] = {**row, "project_relative_path": member_project_relative}
    return members


def materialize_source_manifest_from_freeze(
    *,
    base_manifest_path: Path,
    source_freeze_manifest_path: Path,
    output_path: Path,
    source_namespaces: Sequence[str],
    project_root: Path,
) -> dict[str, Any]:
    """Create one immutable source manifest whose files all come from a freeze."""

    project_root = Path(project_root).absolute()
    base_manifest_path = _project_path(
        Path(base_manifest_path), project_root=project_root, label="base_source_manifest"
    )
    source_freeze_manifest_path = _project_path(
        Path(source_freeze_manifest_path),
        project_root=project_root,
        label="source_freeze_manifest",
    )
    output_path = _project_path(
        Path(output_path), project_root=project_root, label="output"
    )
    try:
        base = load_source_manifest(base_manifest_path, project_root)
    except SourceManifestError as exc:
        raise SourceFreezeBridgeError(f"base_source_manifest_invalid:{exc}") from exc
    base_value = _load_canonical_object(
        base_manifest_path,
        label="base_source_manifest",
        canonical=_canonical_source_manifest,
    )
    mapping = _mapping(source_namespaces)
    source_ids = {source.source_snapshot_id for source in base.sources}
    if set(mapping) != source_ids:
        raise SourceFreezeBridgeError("source_namespace_mapping_incomplete")
    members = _freeze_members(source_freeze_manifest_path, project_root=project_root)

    rewritten_sources: list[dict[str, Any]] = []
    for source_value, source in zip(base_value["sources"], base.sources, strict=True):
        if not isinstance(source_value, dict):
            raise SourceFreezeBridgeError("base_source_manifest_invalid")
        namespace = mapping[source.source_snapshot_id]
        key = (namespace, source.relative_path.as_posix())
        member = members.get(key)
        if member is None:
            raise SourceFreezeBridgeError(
                f"source_freeze_member_not_found:{source.source_snapshot_id}"
            )
        if member["bytes"] != source.bytes or member["sha256"] != source.sha256:
            raise SourceFreezeBridgeError(
                f"source_freeze_member_identity_mismatch:{source.source_snapshot_id}"
            )
        rewritten = dict(source_value)
        rewritten["relative_path"] = str(member["project_relative_path"])
        rewritten_sources.append(rewritten)

    output_value = dict(base_value)
    output_value["sources"] = rewritten_sources
    payload = _canonical_source_manifest(output_value)
    _prepare_output_parent(output_path, project_root)
    write_status = _write_immutable(output_path, payload)
    try:
        frozen = load_source_manifest(output_path, project_root)
    except SourceManifestError as exc:
        raise SourceFreezeBridgeError(f"frozen_source_manifest_invalid:{exc}") from exc
    return {
        "schema_version": "reddit_voc_source_freeze_bridge_result_v1",
        "status": "passed",
        "write_status": write_status,
        "dataset_id": frozen.dataset_id,
        "source_count": len(frozen.sources),
        "source_rows": frozen.source_rows,
        "base_manifest_sha256": base.manifest_sha256,
        "source_freeze_manifest_sha256": sha256(
            source_freeze_manifest_path.read_bytes()
        ).hexdigest(),
        "source_manifest_sha256": sha256(payload).hexdigest(),
        "output_path": output_path.relative_to(project_root).as_posix(),
        "production_unchanged": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-manifest", required=True, type=Path)
    parser.add_argument("--source-freeze-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--source-namespace",
        action="append",
        default=[],
        metavar="SOURCE_SNAPSHOT_ID=NAMESPACE",
    )
    parser.add_argument("--project-root", default=Path.cwd(), type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = materialize_source_manifest_from_freeze(
            base_manifest_path=args.base_manifest,
            source_freeze_manifest_path=args.source_freeze_manifest,
            output_path=args.output,
            source_namespaces=args.source_namespace,
            project_root=args.project_root,
        )
    except (SourceFreezeBridgeError, SourceManifestBuildError) as exc:
        print(f"source_freeze_bridge_failed:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
