from __future__ import annotations

from datetime import datetime
import gzip
from hashlib import sha256
import hmac
from io import BytesIO
import os
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile
import zlib

from .backfill_models import RawArtifactMetadata


_SAFE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ArchiveIntegrityError(RuntimeError):
    pass


class ArchiveReadOnlyError(RuntimeError):
    pass


class PrivateRawArchive:
    def __init__(self, root: Path | str, *, read_only: bool = False) -> None:
        self.read_only = read_only
        if type(read_only) is not bool:
            raise ValueError("read_only must be a bool")
        if read_only:
            raw_root = Path(root)
            try:
                if _path_has_existing_symlink_component(raw_root):
                    raise ValueError
                resolved = raw_root.resolve(strict=True)
            except (FileNotFoundError, OSError, ValueError) as exc:
                raise ValueError(
                    "read-only raw archive root must be an existing directory"
                ) from exc
            if not resolved.is_dir():
                raise ValueError(
                    "read-only raw archive root must be an existing directory"
                )
            self.root = resolved
            return

        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def write(
        self,
        *,
        run_id: str,
        artifact_kind: str,
        lane_type: str,
        lane_key: str,
        identity: str,
        payload: bytes,
        raw_capture_id: str,
        parser_kind: str,
        source_method: str,
        source_url: str,
        source_endpoint: str,
        captured_at_utc: datetime,
        page_number: int | None = None,
        request_cursor: str | None = None,
        response_cursor: str | None = None,
    ) -> RawArtifactMetadata:
        if self.read_only:
            raise ArchiveReadOnlyError("raw archive is read-only")
        run_id = _validated_token("run_id", run_id)
        artifact_kind = _validated_token("artifact_kind", artifact_kind)
        lane_type = _validated_token("lane_type", lane_type)
        if not isinstance(lane_key, str):
            raise ValueError("lane_key must be a string")
        if not isinstance(identity, str):
            raise ValueError("identity must be a string")
        if not isinstance(payload, bytes):
            raise ValueError("payload must be bytes")
        if not isinstance(raw_capture_id, str) or not raw_capture_id.strip():
            raise ValueError("raw_capture_id must be a non-empty string")
        if not isinstance(captured_at_utc, datetime):
            raise ValueError("captured_at_utc must be a datetime")
        if page_number is not None and (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number < 0
        ):
            raise ValueError("page_number must be a non-negative integer or None")

        lane_key_hash = sha256(lane_key.encode()).hexdigest()
        identity_hash = sha256(identity.encode()).hexdigest()
        payload_sha256 = sha256(payload).hexdigest()
        relative = Path(run_id) / artifact_kind / lane_key_hash[:16] / (
            f"page-{page_number or 0:06d}-{identity_hash[:24]}-"
            f"{payload_sha256[:16]}.json.gz"
        )
        destination = self._confined_path(relative)
        self._prepare_parent(destination.parent)
        compressed = _deterministic_gzip(payload)
        self._atomic_replace(destination, compressed)

        relative_path = relative.as_posix()
        artifact_id_hash = sha256(relative_path.encode()).hexdigest()
        return RawArtifactMetadata(
            artifact_id=f"raw_artifact_{artifact_id_hash[:24]}",
            run_id=run_id,
            artifact_kind=artifact_kind,
            lane_type=lane_type,
            lane_key_hash=lane_key_hash,
            identity_hash=identity_hash,
            raw_capture_id=raw_capture_id,
            parser_kind=parser_kind,
            source_method=source_method,
            source_url=source_url,
            source_endpoint=source_endpoint,
            payload_sha256=payload_sha256,
            relative_path=relative_path,
            captured_at_utc=captured_at_utc.isoformat(),
            page_number=page_number,
            request_cursor=request_cursor,
            response_cursor=response_cursor,
        )

    def read_verified(self, artifact: RawArtifactMetadata) -> bytes:
        try:
            if (
                not isinstance(artifact.payload_sha256, str)
                or _SHA256_PATTERN.fullmatch(artifact.payload_sha256) is None
            ):
                raise ArchiveIntegrityError(
                    "raw archive integrity verification failed"
                )
            path = self._confined_path(artifact.relative_path)
            compressed = path.read_bytes()
            payload = gzip.decompress(compressed)
            compressed_matches = hmac.compare_digest(
                compressed, _deterministic_gzip(payload)
            )
            payload_matches = hmac.compare_digest(
                sha256(payload).hexdigest(), artifact.payload_sha256
            )
            if not compressed_matches or not payload_matches:
                raise ArchiveIntegrityError(
                    "raw archive integrity verification failed"
                )
        except (
            ArchiveIntegrityError,
            EOFError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            zlib.error,
        ):
            raise ArchiveIntegrityError(
                "raw archive integrity verification failed"
            ) from None
        return payload

    def _confined_path(self, relative_path: Path | str) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            raise ArchiveIntegrityError("raw archive path escapes root")
        candidate = self.root
        for part in path.parts:
            candidate /= part
            if candidate.is_symlink():
                raise ArchiveIntegrityError("raw archive path escapes root")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise ArchiveIntegrityError("raw archive path escapes root") from None
        return resolved

    def _prepare_parent(self, parent: Path) -> None:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        current = self.root
        current.chmod(0o700)
        for part in parent.relative_to(self.root).parts:
            current /= part
            if current.is_symlink():
                raise ArchiveIntegrityError("raw archive path escapes root")
            current.chmod(0o700)

    @staticmethod
    def _atomic_replace(destination: Path, compressed: bytes) -> None:
        try:
            existing = destination.read_bytes()
        except FileNotFoundError:
            pass
        else:
            if not hmac.compare_digest(existing, compressed):
                raise ArchiveIntegrityError("raw archive path collision")
            destination.chmod(0o600)
            return

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(compressed)
                temporary_file.flush()
                os.fchmod(temporary_file.fileno(), 0o600)
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, destination)
            destination.chmod(0o600)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _validated_token(name: str, value: str) -> str:
    if (
        not isinstance(value, str)
        or value in {".", ".."}
        or Path(value).is_absolute()
        or _SAFE_TOKEN_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"invalid {name}")
    return value


def _path_has_existing_symlink_component(path: Path | str) -> bool:
    lexical = Path(path).expanduser()
    if not lexical.is_absolute():
        lexical = Path.cwd() / lexical
    for component in (lexical, *lexical.parents):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            return True
    return False


def _deterministic_gzip(payload: bytes) -> bytes:
    buffer = BytesIO()
    with gzip.GzipFile(
        filename="", fileobj=buffer, mode="wb", mtime=0
    ) as compressed_file:
        compressed_file.write(payload)
    return buffer.getvalue()
