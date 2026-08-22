from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import VocStore


_CONTROL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_no_sidecars(database: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise RuntimeError(f"schema_migration_active_sidecar:{sidecar.name}")


def _require_fresh_target(path: Path, label: str) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"schema_migration_{label}_exists")
    if not path.parent.is_dir():
        raise RuntimeError(f"schema_migration_{label}_parent_missing")


def _exclusive_copy(source: Path, target: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    try:
        with source.open("rb") as source_handle, os.fdopen(descriptor, "wb") as target_handle:
            descriptor = -1
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    shutil.copystat(source, target, follow_symlinks=False)
    _fsync_file(target)
    _fsync_directory(target.parent)


def _apply_source_metadata(path: Path, source_metadata: os.stat_result) -> None:
    os.chmod(path, stat.S_IMODE(source_metadata.st_mode))
    if os.geteuid() == 0:
        os.chown(path, source_metadata.st_uid, source_metadata.st_gid)
    elif source_metadata.st_uid != os.geteuid() or source_metadata.st_gid != os.getegid():
        raise RuntimeError("schema_migration_source_ownership_requires_root")


def _sqlite_inventory(path: Path) -> dict[str, Any]:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        integrity = [str(row[0]) for row in conn.execute("PRAGMA integrity_check").fetchall()]
        if integrity != ["ok"]:
            raise RuntimeError("schema_migration_integrity_check_failed")
        tables = [
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for table in tables:
            quoted = table.replace('"', '""')
            counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0])
        schema_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT type, name, tbl_name, sql
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
            ).fetchall()
        ]
    finally:
        conn.close()
    schema_payload = json.dumps(schema_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "counts": counts,
        "integrity_check": "ok",
        "schema_sha256": hashlib.sha256(schema_payload.encode("utf-8")).hexdigest(),
    }


def _copy_to_candidate(source: Path, source_metadata: os.stat_result) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{source.name}.migration-", dir=source.parent)
    os.close(descriptor)
    candidate = Path(name)
    shutil.copy2(source, candidate)
    _apply_source_metadata(candidate, source_metadata)
    _fsync_file(candidate)
    return candidate


def _verify_candidate(path: Path, expected_counts: dict[str, int]) -> dict[str, Any]:
    VocStore(path, read_only=True).require_daily_source_batch_schema()
    inventory = _sqlite_inventory(path)
    if inventory["counts"] != expected_counts:
        raise RuntimeError("schema_migration_row_counts_changed")
    return inventory


def _verify_post_swap(path: Path, expected_counts: dict[str, int]) -> dict[str, Any]:
    return _verify_candidate(path, expected_counts)


def _restore_database(
    database: Path,
    rollback_path: Path,
    source_metadata: os.stat_result,
    expected_sha256: str,
) -> None:
    restore = _copy_to_candidate(rollback_path, source_metadata)
    try:
        os.replace(restore, database)
        _fsync_directory(database.parent)
    finally:
        if restore.exists():
            restore.unlink()
    if sha256_file(database) != expected_sha256:
        raise RuntimeError("schema_migration_rollback_sha_mismatch")


def migrate_database_schema(
    *,
    database_path: Path | str,
    expected_database_sha256: str,
    backup_path: Path | str,
    rollback_path: Path | str,
    authorization_id: str,
) -> dict[str, Any]:
    database = Path(database_path)
    backup = Path(backup_path)
    rollback = Path(rollback_path)
    expected_sha = expected_database_sha256.strip().lower()

    if not _CONTROL_ID.fullmatch(authorization_id):
        raise RuntimeError("schema_migration_authorization_id_invalid")
    if not _SHA256.fullmatch(expected_sha):
        raise RuntimeError("schema_migration_expected_sha256_invalid")
    try:
        source_metadata = database.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("schema_migration_database_missing") from exc
    if not stat.S_ISREG(source_metadata.st_mode):
        raise RuntimeError("schema_migration_database_not_regular")

    resolved_paths = {
        str(database.resolve()),
        str(backup.resolve(strict=False)),
        str(rollback.resolve(strict=False)),
    }
    if len(resolved_paths) != 3:
        raise RuntimeError("schema_migration_paths_not_distinct")
    _require_fresh_target(backup, "backup")
    _require_fresh_target(rollback, "rollback")
    _assert_no_sidecars(database)

    before_sha = sha256_file(database)
    if before_sha != expected_sha:
        raise RuntimeError("schema_migration_source_sha_mismatch")
    before_inventory = _sqlite_inventory(database)

    _exclusive_copy(database, backup)
    if sha256_file(backup) != before_sha:
        raise RuntimeError("schema_migration_backup_sha_mismatch")
    _exclusive_copy(database, rollback)
    if sha256_file(rollback) != before_sha:
        raise RuntimeError("schema_migration_rollback_sha_mismatch")

    candidate = _copy_to_candidate(database, source_metadata)
    swapped = False
    try:
        VocStore(candidate).migrate()
        _apply_source_metadata(candidate, source_metadata)
        _fsync_file(candidate)
        candidate_inventory = _verify_candidate(candidate, before_inventory["counts"])
        candidate_sha = sha256_file(candidate)

        if candidate_inventory["schema_sha256"] == before_inventory["schema_sha256"]:
            return {
                "schema_version": "reddit-voc-explicit-schema-migration-v1",
                "authorization_id": authorization_id,
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "write_status": "no_change",
                "database_write": False,
                "database_sha256_before": before_sha,
                "database_sha256_after": before_sha,
                "backup_sha256": sha256_file(backup),
                "rollback_sha256": sha256_file(rollback),
                "schema_sha256_before": before_inventory["schema_sha256"],
                "schema_sha256_after": candidate_inventory["schema_sha256"],
                "counts_before": before_inventory["counts"],
                "counts_after": candidate_inventory["counts"],
                "integrity_check": "ok",
                "provider_call": False,
                "live_send": False,
                "deploy": False,
            }

        _assert_no_sidecars(database)
        if sha256_file(database) != before_sha:
            raise RuntimeError("schema_migration_source_changed_before_swap")
        os.replace(candidate, database)
        swapped = True
        _fsync_directory(database.parent)
        try:
            after_inventory = _verify_post_swap(database, before_inventory["counts"])
            after_sha = sha256_file(database)
            if after_sha != candidate_sha:
                raise RuntimeError("schema_migration_post_swap_sha_mismatch")
        except Exception as exc:
            _restore_database(database, rollback, source_metadata, before_sha)
            swapped = False
            raise RuntimeError("schema_migration_rolled_back") from exc

        return {
            "schema_version": "reddit-voc-explicit-schema-migration-v1",
            "authorization_id": authorization_id,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "write_status": "migrated",
            "database_write": True,
            "database_sha256_before": before_sha,
            "database_sha256_after": after_sha,
            "backup_sha256": sha256_file(backup),
            "rollback_sha256": sha256_file(rollback),
            "schema_sha256_before": before_inventory["schema_sha256"],
            "schema_sha256_after": after_inventory["schema_sha256"],
            "counts_before": before_inventory["counts"],
            "counts_after": after_inventory["counts"],
            "integrity_check": "ok",
            "provider_call": False,
            "live_send": False,
            "deploy": False,
        }
    finally:
        if not swapped and candidate.exists():
            candidate.unlink()
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(candidate) + suffix)
            if sidecar.exists():
                sidecar.unlink()
