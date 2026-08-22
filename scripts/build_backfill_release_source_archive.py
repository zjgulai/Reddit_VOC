#!/usr/bin/env python3
"""Build an immutable source archive for a reviewed backfill release manifest."""

from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


class ArchiveBuildError(RuntimeError):
    """Raised when reviewed source bytes cannot be archived exactly."""


def _load_reviewed_files(manifest_path: Path) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "momcozy_backfill_release_manifest_v1":
        raise ArchiveBuildError("release_manifest_schema_invalid")
    reviewed = manifest.get("reviewed_files_sha256")
    if not isinstance(reviewed, dict) or not reviewed:
        raise ArchiveBuildError("reviewed_files_missing")

    normalized: dict[str, str] = {}
    for relative_path, expected_sha256 in reviewed.items():
        if not isinstance(relative_path, str) or not isinstance(expected_sha256, str):
            raise ArchiveBuildError("reviewed_file_entry_invalid")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or ".." in path.parts or str(path) != relative_path:
            raise ArchiveBuildError("reviewed_file_path_invalid")
        if len(expected_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in expected_sha256
        ):
            raise ArchiveBuildError("reviewed_file_sha256_invalid")
        normalized[relative_path] = expected_sha256
    return normalized


def build_archive(*, manifest_path: Path, source_root: Path, output_path: Path) -> dict[str, object]:
    reviewed = _load_reviewed_files(manifest_path)
    source_root = source_root.resolve(strict=True)
    if not source_root.is_dir():
        raise ArchiveBuildError("source_root_not_directory")
    if output_path.exists() or output_path.is_symlink():
        raise ArchiveBuildError("output_exists")

    payloads: dict[str, bytes] = {}
    for relative_path, expected_sha256 in sorted(reviewed.items()):
        source_path = source_root / relative_path
        if source_path.is_symlink() or not source_path.is_file():
            raise ArchiveBuildError(f"reviewed_file_missing:{relative_path}")
        payload = source_path.read_bytes()
        actual_sha256 = sha256(payload).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ArchiveBuildError(f"reviewed_file_sha256_mismatch:{relative_path}")
        payloads[relative_path] = payload

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="xb", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for relative_path, payload in payloads.items():
                        member = tarfile.TarInfo(relative_path)
                        member.size = len(payload)
                        member.mode = 0o755 if relative_path.endswith(".sh") else 0o644
                        member.mtime = 0
                        member.uid = 0
                        member.gid = 0
                        member.uname = ""
                        member.gname = ""
                        archive.addfile(member, io.BytesIO(payload))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, output_path)
        os.chmod(output_path, 0o644)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    archive_sha256 = sha256(output_path.read_bytes()).hexdigest()
    return {
        "archive": str(output_path),
        "archive_sha256": archive_sha256,
        "reviewed_file_count": len(payloads),
        "status": "built",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_archive(
        manifest_path=args.manifest,
        source_root=args.source_root,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
