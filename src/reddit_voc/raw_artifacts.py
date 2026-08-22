from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

from reddit_voc.models import RawCapture


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_FORMAT_EXTENSIONS = {
    "html": "html",
    "json": "json",
    "text": "txt",
}


class RawArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class PersistedRawArtifact:
    path: Path
    relative_path: PurePosixPath
    sha256: str
    bytes: int
    write_status: str


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise RawArtifactError(f"{label} is invalid")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _private_directory(path: Path, *, label: str) -> None:
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RawArtifactError(f"{label} is unsafe")
        if stat.S_IMODE(metadata.st_mode) != 0o700:
            path.chmod(0o700)
        return
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    _fsync_directory(path.parent)


def persist_raw_artifact(
    root: Path | str,
    capture: RawCapture,
    payload: bytes,
) -> PersistedRawArtifact:
    if not isinstance(payload, bytes):
        raise RawArtifactError("raw payload must be bytes")
    run_id = _safe_id(capture.run_id, "run_id")
    raw_capture_id = _safe_id(capture.raw_capture_id, "raw_capture_id")
    extension = _FORMAT_EXTENSIONS.get(capture.payload_format)
    if extension is None:
        raise RawArtifactError("raw payload format unsupported")
    digest = hashlib.sha256(payload).hexdigest()
    if capture.raw_payload_hash != "sha256:" + digest:
        raise RawArtifactError("raw payload hash mismatch")

    raw_root = Path(root)
    _private_directory(raw_root, label="raw artifact root")
    run_root = raw_root / run_id
    _private_directory(run_root, label="raw artifact run directory")
    relative_path = PurePosixPath(run_id) / f"{raw_capture_id}.{extension}"
    output = run_root / f"{raw_capture_id}.{extension}"

    if output.exists() or output.is_symlink():
        metadata = output.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RawArtifactError("raw artifact immutable collision")
        if output.read_bytes() != payload:
            raise RawArtifactError("raw artifact immutable collision")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            output.chmod(0o600)
        return PersistedRawArtifact(
            path=output,
            relative_path=relative_path,
            sha256=digest,
            bytes=len(payload),
            write_status="no_change",
        )

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(output, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    output.chmod(0o600)
    _fsync_directory(run_root)
    return PersistedRawArtifact(
        path=output,
        relative_path=relative_path,
        sha256=digest,
        bytes=len(payload),
        write_status="created",
    )
