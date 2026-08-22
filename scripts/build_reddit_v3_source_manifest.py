#!/usr/bin/env python3
"""Materialize one already-validated V3 source manifest into a private bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.v3_source_manifest import (  # noqa: E402
    SourceManifestError,
    load_source_manifest,
)


class SourceManifestBuildError(ValueError):
    """The requested immutable materialization is unsafe or has drifted."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _inside_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _prepare_output_parent(output_path: Path, project_root: Path) -> None:
    root = Path(os.path.abspath(os.fspath(project_root)))
    output = Path(os.path.abspath(os.fspath(output_path)))
    private_root = root / "tmp/reddit-voc-v3"
    if output == private_root or not _inside_root(output, private_root):
        raise SourceManifestBuildError(
            "output must stay inside private V3 output root:tmp/reddit-voc-v3"
        )

    current = root
    for part in output.relative_to(root).parent.parts:
        current = current / part
        if current.exists():
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise SourceManifestBuildError("unsafe output parent")
            continue
        current.mkdir(mode=0o700)


def _write_immutable(path: Path, payload: bytes) -> str:
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SourceManifestBuildError("unsafe existing output")
        if path.read_bytes() != payload:
            raise SourceManifestBuildError("existing output drift")
        return "no_change"

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "created"


def materialize_source_manifest(
    manifest_path: Path,
    output_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Validate all manifest bindings, then create an immutable byte-for-byte copy."""

    manifest_path = Path(manifest_path)
    output_path = Path(output_path)
    project_root = Path(project_root)
    try:
        manifest = load_source_manifest(manifest_path, project_root)
    except SourceManifestError as exc:
        raise SourceManifestBuildError(str(exc)) from exc

    try:
        payload = manifest_path.read_bytes()
    except OSError as exc:
        raise SourceManifestBuildError("manifest changed after validation") from exc
    if _sha256(payload) != manifest.manifest_sha256:
        raise SourceManifestBuildError("manifest changed after validation")
    _prepare_output_parent(output_path, project_root)
    write_status = _write_immutable(output_path, payload)
    return {
        "dataset_id": manifest.dataset_id,
        "manifest_sha256": _sha256(payload),
        "output_path": output_path.relative_to(project_root).as_posix(),
        "production_unchanged": manifest.boundaries.production_unchanged,
        "source_count": len(manifest.sources),
        "source_rows": manifest.source_rows,
        "status": "passed",
        "write_status": write_status,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--project-root", default=Path.cwd(), type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        summary = materialize_source_manifest(
            arguments.manifest,
            arguments.output,
            arguments.project_root,
        )
    except SourceManifestBuildError as exc:
        print(f"source_manifest_build_failed:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
