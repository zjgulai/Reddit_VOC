from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any, Iterator, Literal, NoReturn, cast
from zoneinfo import ZoneInfo

from .backfill_archive import (
    ArchiveIntegrityError,
    ArchiveReadOnlyError,
    PrivateRawArchive,
    _path_has_existing_symlink_component,
)
from .backfill_merge import (
    PLAN_KEYS,
    BackfillMergeError,
    MergeCommittedReviewError,
    merge_staging_insert_only,
    plan_insert_only_merge,
)
from .backfill_models import (
    BackfillCheckpoint,
    BackfillManifest,
    CursorContract,
    LaneResult,
    SeedBaseline,
    required_lanes_snapshot,
    required_lanes_sha256,
)
from .backfill_provider import (
    ProviderBudgetExhausted,
    TikHubBackfillDiscoverer,
    TikHubDetailHydrator,
    TikHubProviderError,
    TikHubRequestExecutor,
    TikHubSchemaDrift,
)
from .backfill_profile import BackfillProfileError, load_v2_search_profile
from .backfill_seed import import_seed_directory
from .backfill_storage import (
    BackfillConflictError,
    BackfillSchemaError,
    BackfillStore,
)
from .backfill_validation import (
    ReplayPublicationError,
    operational_snapshot_sha256,
    recover_collection_from_archive,
    reindex_discovery_from_archive,
    replay_from_archive,
    validate_backfill,
)
from .keywords import keyword_rules_sha256
from .search_config import (
    DEFAULT_REVIEWED_SUBREDDITS,
    DEFAULT_TIKHUB_SEARCH_TERMS,
)
from .tikhub import TikHubClient
from .time_window import CollectionWindow


CONTRACT_PROBE_MAX_REQUESTS = 4
CONTRACT_PROBE_MAX_SUCCESS_PAGES = 2
READY_PROBE_STOP_REASONS = frozenset(
    ("probe_page_limit", "cursor_exhausted", "older_than_window")
)
TERMINAL_DISCOVERY_STOP_REASONS = frozenset(
    ("provider_error", "schema_drift", "cursor_loop")
)
SEED_BASELINE_RELATIVE_PATH = (
    "config/backfill/momcozy-seed-baseline-20250101-20260711.json"
)
RELEASE_MANIFEST_RELATIVE_PATH = (
    "config/backfill/momcozy-backfill-release-manifest-20260711.json"
)
COMMENT_CURSOR_RELATIVE_PATH = (
    "config/backfill/momcozy-comment-cursor-contract-20260711.json"
)
STAGING_DATABASE_NAME = "reddit_voc_backfill.sqlite3"
RAW_ARCHIVE_DIRECTORY_NAME = "private-raw"
REPORT_DIRECTORY_NAME = "reports"
CODE_ROOT = Path(__file__).resolve().parents[2]
RELEASE_REVIEWED_PATHS = (
    "pyproject.toml",
    "scripts/run_historical_backfill.sh",
    "scripts/server_historical_backfill.sh",
    "src/reddit_voc/__init__.py",
    "src/reddit_voc/adapters.py",
    "src/reddit_voc/analyzer.py",
    "src/reddit_voc/backfill_archive.py",
    "src/reddit_voc/backfill_archived_recovery.py",
    "src/reddit_voc/backfill_cli.py",
    "src/reddit_voc/backfill_merge.py",
    "src/reddit_voc/backfill_models.py",
    "src/reddit_voc/backfill_provider.py",
    "src/reddit_voc/backfill_seed.py",
    "src/reddit_voc/backfill_storage.py",
    "src/reddit_voc/backfill_validation.py",
    "src/reddit_voc/keywords.py",
    "src/reddit_voc/models.py",
    "src/reddit_voc/search_config.py",
    "src/reddit_voc/storage.py",
    "src/reddit_voc/tikhub.py",
    "src/reddit_voc/time_window.py",
    SEED_BASELINE_RELATIVE_PATH,
    COMMENT_CURSOR_RELATIVE_PATH,
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SAFE_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,95}")
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SEED_NUMERIC_CONTRACT = {
    "files_total": 55,
    "files_imported": 48,
    "files_outside_window": 7,
    "files_excluded": 0,
    "files_duplicate": 0,
    "parse_errors": 0,
    "threads": 48,
    "comments": 1894,
    "analyses": 1942,
    "coverage_full": 45,
    "coverage_partial": 3,
    "coverage_post_only": 0,
}
VALIDATION_RESULT_KEYS = (
    "schema_version",
    "run_id",
    "scope",
    "status",
    "stop_reason",
    "replay_status",
    "full_ready",
    "source_provider_call",
    "provider_attempt_made",
    "live_send",
    "seed_baseline_sha256",
    "known_seed_partial_count",
    "known_seed_partial_post_ids_sha256",
    "run_root_scan",
    "counts",
    "candidate_status_counts",
    "occurrence_disposition_counts",
    "required_lanes",
    "source_fingerprints",
    "replay_fingerprints",
    "operational_metadata",
    "checks",
    "issues",
)
REINDEX_DISCOVERY_RESULT_KEYS = (
    "schema_version",
    "status",
    "stop_reason",
    "provider_attempt_made",
    "live_send",
    "source_db_sha256",
    "raw_inventory_sha256",
    "target_db_sha256",
    "source_max_provider_requests",
    "source_provider_request_count",
    "source_provider_ledger_sha256",
    "target_max_provider_requests",
    "target_provider_request_count",
    "target_provider_ledger_sha256",
    "discovery_artifact_count",
    "discovery_occurrence_count",
    "candidate_count",
)
COLLECTION_RECOVERY_RESULT_KEYS = (
    "schema_version",
    "status",
    "stop_reason",
    "run_id",
    "provider_call",
    "provider_attempt_made",
    "database_write",
    "live_send",
    "source_db_sha256",
    "raw_inventory_sha256",
    "target_db_sha256",
    "source_max_provider_requests",
    "source_provider_request_count",
    "source_provider_ledger_sha256",
    "target_max_provider_requests",
    "target_provider_request_count",
    "target_provider_ledger_sha256",
    "discovery_artifact_count",
    "discovery_occurrence_count",
    "candidate_count",
    "new_candidate_count",
    "recovered_discovery_lane_count",
    "reset_candidate_count",
    "reset_batch_count",
    "reset_comment_checkpoint_count",
    "raw_persisted_batch_count",
    "prepared_batch_count",
    "archived_hydrated_candidate_count",
)
_VALIDATION_COUNT_KEYS = (
    "manifests",
    "runs",
    "seed_files",
    "raw_artifacts",
    "raw_captures",
    "threads",
    "comments",
    "analyses",
    "delivery_previews",
    "provider_attempts",
    "checkpoints",
    "candidates",
    "discovery_occurrences",
    "detail_batches",
    "detail_batch_members",
)
_VALIDATION_CANDIDATE_KEYS = (
    "pending",
    "duplicate_existing_structured",
    "hydrated",
    "excluded",
    "outside_window_detail",
    "failed",
    "budget_deferred",
)
_VALIDATION_OCCURRENCE_KEYS = (
    "new_candidate",
    "duplicate_occurrence",
    "outside_window",
    "duplicate_existing_structured",
    "invalid",
)
_VALIDATION_FINGERPRINT_TABLES = (
    "runs",
    "backfill_raw_artifacts",
    "raw_captures",
    "reddit_threads",
    "reddit_comments",
    "analysis_results",
)
_REQUIRED_ACCEPTANCE_CHECK_CODES = frozenset(
    (
        "seed_baseline_contract",
        "source_database_readable",
        "replay_equivalence",
        "required_schema",
        "required_columns",
        "sqlite_integrity",
        "foreign_key_integrity",
        "manifest_row_count",
        "run_row_count",
        "delivery_rows",
        "manifest_run_identity",
        "manifest_window",
        "live_send_flags",
        "scope_status",
        "reviewed_search_terms",
        "keyword_config",
        "baseline_search_terms",
        "reviewed_subreddits",
        "required_lanes_hash",
        "archive_integrity",
        "seed_artifact_ledger",
        "seed_numeric_contract",
        "seed_inventory",
        "known_seed_partials",
        "entity_analysis_parity",
        "provider_attempt_ledger",
        "operational_accounting",
    )
)

REVIEWED_COMMENT_CURSOR_CONTRACT = CursorContract(
    cursor_path=(
        "data",
        "postInfoById",
        "commentForest",
        "pageInfo",
        "endCursor",
    ),
    schema_sha256=(
        "67c3b44ef86da5d844320d676e6a6e6cc0dccfc1e94b4509b9cb0ce89ff5edc1"
    ),
)
REVIEWED_COMMENT_CURSOR_SCHEMA_SHA256 = (
    REVIEWED_COMMENT_CURSOR_CONTRACT.schema_sha256
)


class BackfillCliError(RuntimeError):
    def __init__(
        self,
        reason: str,
        *,
        status: Literal["blocked", "failed", "rejected"] = "failed",
        provider_call: bool = False,
        production_write: bool = False,
        provider_gate: bool = False,
    ) -> None:
        if _SAFE_REASON_PATTERN.fullmatch(reason) is None:
            reason = "cli_failed"
        self.reason = reason
        self.status: Literal["blocked", "failed", "rejected"] = status
        self.provider_call = provider_call
        self.production_write = production_write
        self.provider_gate = provider_gate
        super().__init__(reason)


class BackfillArgumentError(RuntimeError):
    pass


class _StableArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise BackfillArgumentError


@dataclass(frozen=True)
class LoadedReleaseBundle:
    manifest_sha256: str
    seed_baseline: SeedBaseline
    comment_cursor_contract: CursorContract


@dataclass(frozen=True)
class _PinnedReviewedFile:
    payload: bytes
    device: int
    inode: int
    size: int


def _canonical_json_bytes(value: object, *, newline: bool = False) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise BackfillCliError("noncanonical_json_value") from None
    return payload + (b"\n" if newline else b"")


def _canonical_sha256(value: object) -> str:
    return sha256(_canonical_json_bytes(value)).hexdigest()


def _read_pinned_reviewed_file(path: Path, *, reason: str) -> _PinnedReviewedFile:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino, after.st_size)
            != (before.st_dev, before.st_ino, before.st_size)
        ):
            raise OSError
        path_state = path.lstat()
        if (
            not stat.S_ISREG(path_state.st_mode)
            or path_state.st_nlink != 1
            or (path_state.st_dev, path_state.st_ino, path_state.st_size)
            != (before.st_dev, before.st_ino, before.st_size)
        ):
            raise OSError
        return _PinnedReviewedFile(
            payload=b"".join(chunks),
            device=before.st_dev,
            inode=before.st_ino,
            size=before.st_size,
        )
    except (OSError, ValueError):
        raise BackfillCliError(reason) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _assert_pinned_reviewed_file(
    path: Path, pinned: _PinnedReviewedFile, *, reason: str
) -> None:
    try:
        current = path.lstat()
    except OSError:
        raise BackfillCliError(reason) from None
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or (current.st_dev, current.st_ino, current.st_size)
        != (pinned.device, pinned.inode, pinned.size)
    ):
        raise BackfillCliError(reason)


def _strict_json_bytes(raw: bytes, *, reason: str) -> object:
    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(_: str) -> object:
        raise ValueError("nonfinite number")

    try:
        text = raw.decode("utf-8")
        decoded = json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
        _reject_nonfinite_json(decoded)
        return decoded
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise BackfillCliError(reason) from None


def _reject_nonfinite_json(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite number")
    if isinstance(value, list):
        for item in value:
            _reject_nonfinite_json(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_nonfinite_json(item)


def _exact_dict(value: object, keys: tuple[str, ...], *, reason: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise BackfillCliError(reason)
    if set(value) != set(keys):
        raise BackfillCliError(reason)
    return cast(dict[str, object], value)


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_PATTERN.fullmatch(value) is not None


def _fixed_reviewed_file(
    supplied: Path,
    relative_path: str,
    *,
    path_reason: str,
    unsafe_reason: str = "reviewed_file_unsafe",
) -> Path:
    lexical_root = Path(os.path.abspath(os.fspath(CODE_ROOT)))
    try:
        root = lexical_root.resolve(strict=True)
    except (OSError, ValueError):
        raise BackfillCliError("code_root_invalid") from None
    expected = lexical_root / relative_path
    supplied_absolute = Path(os.path.abspath(os.fspath(supplied)))
    if supplied_absolute != expected:
        raise BackfillCliError(path_reason)
    current = lexical_root
    try:
        for component in PurePosixPath(relative_path).parts:
            if component in {"", ".", ".."} or "\x00" in component:
                raise BackfillCliError(unsafe_reason)
            current = current / component
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise BackfillCliError(unsafe_reason)
        resolved = expected.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise BackfillCliError(unsafe_reason)
    except BackfillCliError:
        raise
    except (OSError, ValueError):
        raise BackfillCliError(unsafe_reason) from None
    return expected


def _safe_map_relative_path(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value or "\n" in value or "\r" in value:
        raise BackfillCliError("release_manifest_file_map_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BackfillCliError("release_manifest_file_map_invalid")
    lowered = value.lower()
    if any(
        token in lowered
        for token in (".env", "secret", "credential", ".pem", "private_key")
    ):
        raise BackfillCliError("release_manifest_file_map_invalid")
    return value


def _load_seed_baseline(raw: bytes) -> SeedBaseline:
    payload = _exact_dict(
        _strict_json_bytes(raw, reason="seed_baseline_invalid"),
        tuple(field.name for field in fields(SeedBaseline)),
        reason="seed_baseline_invalid",
    )
    if payload["schema_version"] != "momcozy_seed_baseline_v1":
        raise BackfillCliError("seed_baseline_invalid")
    for name, expected in _SEED_NUMERIC_CONTRACT.items():
        if type(payload[name]) is not int or payload[name] != expected:
            raise BackfillCliError("seed_baseline_invalid")
    for name in (
        "source_inventory_sha256",
        "known_partial_post_ids_sha256",
        "reviewed_search_terms_sha256",
        "reviewed_subreddits_sha256",
        "baseline_sha256",
    ):
        if not _is_sha256(payload[name]):
            raise BackfillCliError("seed_baseline_invalid")
    subreddits = payload["reviewed_subreddits"]
    if (
        not isinstance(subreddits, list)
        or not subreddits
        or any(type(item) is not str or not item.strip() for item in subreddits)
        or len(set(subreddits)) != len(subreddits)
        or tuple(subreddits) != tuple(DEFAULT_REVIEWED_SUBREDDITS)
    ):
        raise BackfillCliError("seed_baseline_invalid")
    if payload["reviewed_search_terms_sha256"] != _canonical_sha256(
        list(DEFAULT_TIKHUB_SEARCH_TERMS)
    ):
        raise BackfillCliError("seed_baseline_invalid")
    if payload["reviewed_subreddits_sha256"] != _canonical_sha256(subreddits):
        raise BackfillCliError("seed_baseline_invalid")
    canonical_payload = dict(payload)
    baseline_sha256 = canonical_payload.pop("baseline_sha256")
    if baseline_sha256 != _canonical_sha256(canonical_payload):
        raise BackfillCliError("seed_baseline_invalid")
    return SeedBaseline(
        schema_version="momcozy_seed_baseline_v1",
        files_total=cast(int, payload["files_total"]),
        files_imported=cast(int, payload["files_imported"]),
        files_outside_window=cast(int, payload["files_outside_window"]),
        files_excluded=cast(int, payload["files_excluded"]),
        files_duplicate=cast(int, payload["files_duplicate"]),
        parse_errors=cast(int, payload["parse_errors"]),
        threads=cast(int, payload["threads"]),
        comments=cast(int, payload["comments"]),
        analyses=cast(int, payload["analyses"]),
        coverage_full=cast(int, payload["coverage_full"]),
        coverage_partial=cast(int, payload["coverage_partial"]),
        coverage_post_only=cast(int, payload["coverage_post_only"]),
        source_inventory_sha256=cast(str, payload["source_inventory_sha256"]),
        known_partial_post_ids_sha256=cast(
            str, payload["known_partial_post_ids_sha256"]
        ),
        reviewed_search_terms_sha256=cast(
            str, payload["reviewed_search_terms_sha256"]
        ),
        reviewed_subreddits=tuple(cast(list[str], subreddits)),
        reviewed_subreddits_sha256=cast(
            str, payload["reviewed_subreddits_sha256"]
        ),
        baseline_sha256=cast(str, payload["baseline_sha256"]),
    )


def _load_comment_cursor_contract(raw: bytes) -> CursorContract:
    payload = _exact_dict(
        _strict_json_bytes(raw, reason="comment_cursor_contract_invalid"),
        ("schema_version", "cursor_path", "cursor_schema_sha256"),
        reason="comment_cursor_contract_invalid",
    )
    if payload["schema_version"] != "tikhub_comment_cursor_contract_v1":
        raise BackfillCliError("comment_cursor_contract_invalid")
    if payload["cursor_path"] != list(REVIEWED_COMMENT_CURSOR_CONTRACT.cursor_path):
        raise BackfillCliError("comment_cursor_contract_invalid")
    if payload["cursor_schema_sha256"] != REVIEWED_COMMENT_CURSOR_SCHEMA_SHA256:
        raise BackfillCliError("comment_cursor_contract_invalid")
    return REVIEWED_COMMENT_CURSOR_CONTRACT


def load_release_bundle(
    manifest_path: Path,
    *,
    baseline_path: Path,
    comment_cursor_path: Path,
    run_id: str,
    expected_manifest_sha256: str | None = None,
) -> LoadedReleaseBundle:
    manifest_file = _fixed_reviewed_file(
        manifest_path,
        RELEASE_MANIFEST_RELATIVE_PATH,
        path_reason="release_manifest_path_invalid",
    )
    manifest_pin = _read_pinned_reviewed_file(
        manifest_file, reason="release_manifest_unreadable"
    )
    manifest_raw = manifest_pin.payload
    manifest_sha256 = sha256(manifest_raw).hexdigest()
    if expected_manifest_sha256 is not None:
        if not _is_sha256(expected_manifest_sha256) or not hmac.compare_digest(
            manifest_sha256, expected_manifest_sha256
        ):
            raise BackfillCliError("release_manifest_sha256_mismatch")

    manifest = _exact_dict(
        _strict_json_bytes(manifest_raw, reason="release_manifest_invalid"),
        ("schema_version", "run_id", "seed_baseline", "reviewed_files_sha256"),
        reason="release_manifest_invalid",
    )
    if (
        manifest["schema_version"] != "momcozy_backfill_release_manifest_v1"
        or manifest["run_id"] != run_id
    ):
        raise BackfillCliError("release_manifest_invalid")
    nested = _exact_dict(
        manifest["seed_baseline"],
        ("relative_path", "sha256"),
        reason="release_manifest_invalid",
    )
    file_map = manifest["reviewed_files_sha256"]
    if not isinstance(file_map, dict) or any(type(key) is not str for key in file_map):
        raise BackfillCliError("release_manifest_file_map_invalid")
    if set(file_map) != set(RELEASE_REVIEWED_PATHS):
        raise BackfillCliError("release_manifest_file_map_invalid")
    pinned_files: dict[str, tuple[Path, _PinnedReviewedFile]] = {}
    for raw_relative_path, expected_sha256 in file_map.items():
        relative_path = _safe_map_relative_path(raw_relative_path)
        if not _is_sha256(expected_sha256):
            raise BackfillCliError("release_manifest_file_map_invalid")
        reviewed_file = _fixed_reviewed_file(
            CODE_ROOT / relative_path,
            relative_path,
            path_reason="release_manifest_file_map_invalid",
        )
        pinned = _read_pinned_reviewed_file(
            reviewed_file, reason="reviewed_file_unreadable"
        )
        if not hmac.compare_digest(
            sha256(pinned.payload).hexdigest(),
            cast(str, expected_sha256),
        ):
            raise BackfillCliError("reviewed_file_sha256_mismatch")
        pinned_files[relative_path] = (reviewed_file, pinned)

    baseline_file = _fixed_reviewed_file(
        baseline_path,
        SEED_BASELINE_RELATIVE_PATH,
        path_reason="seed_baseline_path_invalid",
    )
    comment_file = _fixed_reviewed_file(
        comment_cursor_path,
        COMMENT_CURSOR_RELATIVE_PATH,
        path_reason="comment_cursor_contract_path_invalid",
    )
    pinned_baseline = pinned_files.get(SEED_BASELINE_RELATIVE_PATH)
    pinned_comment = pinned_files.get(COMMENT_CURSOR_RELATIVE_PATH)
    if pinned_baseline is None or pinned_comment is None:
        raise BackfillCliError("release_manifest_file_map_invalid")
    if pinned_baseline[0] != baseline_file or pinned_comment[0] != comment_file:
        raise BackfillCliError("release_manifest_file_map_invalid")
    baseline_sha256 = sha256(pinned_baseline[1].payload).hexdigest()
    if (
        nested["relative_path"] != SEED_BASELINE_RELATIVE_PATH
        or nested["sha256"] != baseline_sha256
        or file_map.get(SEED_BASELINE_RELATIVE_PATH) != baseline_sha256
    ):
        raise BackfillCliError("seed_baseline_release_binding_invalid")
    loaded = LoadedReleaseBundle(
        manifest_sha256=manifest_sha256,
        seed_baseline=_load_seed_baseline(pinned_baseline[1].payload),
        comment_cursor_contract=_load_comment_cursor_contract(
            pinned_comment[1].payload
        ),
    )
    _assert_pinned_reviewed_file(
        manifest_file, manifest_pin, reason="release_manifest_changed_during_admission"
    )
    for reviewed_file, pinned in pinned_files.values():
        _assert_pinned_reviewed_file(
            reviewed_file,
            pinned,
            reason="reviewed_file_changed_during_admission",
        )
    return loaded


def _publish_json(path: Path, payload: object) -> None:
    data = _canonical_json_bytes(payload, newline=True)
    published = False
    try:
        if _path_has_existing_symlink_component(path.parent):
            raise BackfillCliError("output_path_unsafe")
        path.parent.mkdir(parents=True, exist_ok=True)
        parent = path.parent.resolve(strict=True)
        destination = parent / path.name
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise BackfillCliError("output_path_unsafe")
            try:
                existing = destination.read_bytes()
            except OSError:
                raise BackfillCliError("output_unreadable") from None
            if existing == data:
                return
            raise BackfillCliError("output_exists_needs_review")
        temporary = parent / f".{path.name}.{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, destination)
            published = True
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    except BackfillCliError:
        raise
    except FileExistsError:
        raise BackfillCliError("output_exists_needs_review") from None
    except OSError:
        raise BackfillCliError(
            "output_committed_needs_review" if published else "output_write_failed"
        ) from None


def _publish_or_verify_json(path: Path, payload: object) -> None:
    expected = _canonical_json_bytes(payload, newline=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise BackfillCliError("output_exists_needs_review")
        try:
            actual = path.read_bytes()
        except OSError:
            raise BackfillCliError("output_exists_needs_review") from None
        if actual != expected:
            raise BackfillCliError("output_exists_needs_review")
        return
    _publish_json(path, payload)


def _publish_evidence_snapshot(
    report_dir: Path,
    *,
    run_id: str,
    phase: str,
    payload: object,
    sequence: int,
) -> Path:
    digest = sha256(_canonical_json_bytes(payload, newline=True)).hexdigest()
    path = report_dir / (
        f"{run_id}-{phase}-{sequence:06d}-{digest[:16]}.json"
    )
    _publish_json(path, payload)
    return path


def _emit(payload: object) -> None:
    sys.stdout.write(_canonical_json_bytes(payload, newline=True).decode("utf-8"))
    sys.stdout.flush()


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise BackfillCliError("utc_timestamp_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BackfillCliError("utc_timestamp_invalid")
    return parsed.astimezone(timezone.utc)


def _require_isolated_staging_paths(
    *, database: Path, raw_archive: Path, report_dir: Path, require_existing: bool
) -> None:
    database = Path(os.path.abspath(database))
    raw_archive = Path(os.path.abspath(raw_archive))
    report_dir = Path(os.path.abspath(report_dir))
    run_root = database.parent
    if (
        database.name != STAGING_DATABASE_NAME
        or raw_archive != run_root / RAW_ARCHIVE_DIRECTORY_NAME
        or report_dir != run_root / REPORT_DIRECTORY_NAME
    ):
        raise BackfillCliError("isolated_backfill_layout_invalid")
    for path in (database, raw_archive, report_dir):
        if _path_has_existing_symlink_component(path):
            raise BackfillCliError("isolated_backfill_path_unsafe")
    if database.exists():
        try:
            database_state = database.lstat()
        except OSError:
            raise BackfillCliError("isolated_backfill_path_unsafe") from None
        if (
            not stat.S_ISREG(database_state.st_mode)
            or database_state.st_nlink != 1
        ):
            raise BackfillCliError("staging_database_link_count_invalid")
    if require_existing:
        if not database.is_file() or not raw_archive.is_dir():
            raise BackfillCliError("isolated_backfill_state_missing")
    else:
        if database.exists() and not database.is_file():
            raise BackfillCliError("isolated_backfill_path_unsafe")
        if raw_archive.exists() and not raw_archive.is_dir():
            raise BackfillCliError("isolated_backfill_path_unsafe")
    if report_dir.exists() and not report_dir.is_dir():
        raise BackfillCliError("isolated_backfill_path_unsafe")


def _admit_existing_seed_database(path: Path) -> tuple[int, int]:
    try:
        database_state = path.lstat()
    except FileNotFoundError:
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError:
            raise BackfillCliError("isolated_backfill_path_unsafe") from None
        try:
            database_state = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise BackfillCliError("isolated_backfill_path_unsafe") from None
    if (
        not stat.S_ISREG(database_state.st_mode)
        or database_state.st_nlink != 1
    ):
        raise BackfillCliError("staging_database_link_count_invalid")
    expected_identity = (database_state.st_dev, database_state.st_ino)
    if database_state.st_size == 0:
        return expected_identity
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.resolve(strict=True).as_uri()}?mode=ro", uri=True, timeout=2.0
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    except (OSError, ValueError, sqlite3.DatabaseError):
        raise BackfillCliError("existing_staging_database_invalid") from None
    finally:
        if connection is not None:
            connection.close()
    try:
        admitted_state = path.lstat()
    except OSError:
        raise BackfillCliError("staging_database_link_count_invalid") from None
    if (
        not stat.S_ISREG(admitted_state.st_mode)
        or admitted_state.st_nlink != 1
        or (admitted_state.st_dev, admitted_state.st_ino) != expected_identity
    ):
        raise BackfillCliError("staging_database_link_count_invalid")
    if tables and "backfill_manifests" not in tables:
        raise BackfillCliError("existing_database_is_not_backfill_staging")
    return expected_identity


def _assert_seed_database_identity(
    path: Path,
    expected_identity: tuple[int, int],
    *,
    expected_link_count: int = 1,
) -> None:
    try:
        database_state = path.lstat()
    except OSError:
        raise BackfillCliError("staging_database_link_count_invalid") from None
    if (
        not stat.S_ISREG(database_state.st_mode)
        or database_state.st_nlink != expected_link_count
        or (database_state.st_dev, database_state.st_ino) != expected_identity
    ):
        raise BackfillCliError("staging_database_link_count_invalid")


@contextmanager
def _pinned_seed_database(
    path: Path, expected_identity: tuple[int, int]
) -> Iterator[Path]:
    with TemporaryDirectory(prefix=".seed-database-pin-", dir=path.parent) as directory:
        pin_root = Path(directory)
        try:
            pin_root.chmod(0o700)
            pinned_path = pin_root / path.name
            os.link(path, pinned_path, follow_symlinks=False)
        except OSError:
            raise BackfillCliError("staging_database_link_count_invalid") from None
        _assert_seed_database_identity(
            path, expected_identity, expected_link_count=2
        )
        _assert_seed_database_identity(
            pinned_path, expected_identity, expected_link_count=2
        )
        try:
            yield pinned_path
        finally:
            _assert_seed_database_identity(
                pinned_path, expected_identity, expected_link_count=2
            )
            _assert_seed_database_identity(
                path, expected_identity, expected_link_count=2
            )


def _provider_gate(authorized: bool) -> str:
    if (
        authorized is not True
        or os.environ.get("REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL") != "1"
        or os.environ.get("REDDIT_VOC_ENABLE_TIKHUB") != "1"
    ):
        raise BackfillCliError(
            "provider_call_not_authorized", status="blocked", provider_gate=True
        )
    api_key = os.environ.get("TIKHUB_API_KEY", "")
    if not api_key.strip():
        raise BackfillCliError(
            "missing_tikhub_api_key", status="blocked", provider_gate=True
        )
    return api_key


def _production_gate(authorized: bool) -> None:
    if (
        authorized is not True
        or os.environ.get("REDDIT_VOC_ENABLE_PRODUCTION_MERGE") != "1"
    ):
        raise BackfillCliError(
            "production_merge_not_authorized", status="blocked"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = _StableArgumentParser(prog="reddit-voc-backfill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed = subparsers.add_parser("seed")
    for option in ("run-id", "database", "source-dir", "raw-archive-dir", "report-dir"):
        seed.add_argument(f"--{option}", required=True, type=Path if option != "run-id" else str)
    seed.add_argument("--window-start-utc", required=True)
    seed.add_argument("--requested-window-end-utc", required=True)
    seed.add_argument("--effective-window-end-utc", required=True)

    probe = subparsers.add_parser("probe")
    _provider_common_arguments(probe)
    probe.add_argument("--release-manifest", required=True, type=Path)

    collect = subparsers.add_parser("collect")
    _provider_common_arguments(collect)
    collect.add_argument("--probe-report", required=True, type=Path)
    collect.add_argument("--expected-probe-sha256", required=True)
    collect.add_argument("--release-manifest", required=True, type=Path)
    collect.add_argument("--expected-release-manifest-sha256", required=True)
    collect.add_argument("--comment-cursor-contract", required=True, type=Path)
    collect.add_argument("--max-provider-requests-total", required=True, type=int)
    collect.add_argument("--include-subreddit-sweep", required=True, choices=("0", "1"))
    collect.add_argument("--budget-extension-authorization", type=Path)
    collect.add_argument(
        "--expected-budget-extension-authorization-sha256"
    )
    collect.add_argument("--existing-budget-resume-authorization", type=Path)
    collect.add_argument(
        "--expected-existing-budget-resume-authorization-sha256"
    )

    profile_admission = subparsers.add_parser("profile-admission")
    profile_admission.add_argument("--run-id", required=True)
    profile_admission.add_argument("--profile", required=True, type=Path)
    profile_admission.add_argument("--expected-profile-sha256", required=True)

    v2_seed = subparsers.add_parser("v2-seed")
    for option in ("run-id", "database", "source-dir", "raw-archive-dir", "report-dir"):
        v2_seed.add_argument(
            f"--{option}", required=True, type=Path if option != "run-id" else str
        )
    v2_seed.add_argument("--window-start-utc", required=True)
    v2_seed.add_argument("--requested-window-end-utc", required=True)
    v2_seed.add_argument("--effective-window-end-utc", required=True)
    v2_seed.add_argument("--profile", required=True, type=Path)
    v2_seed.add_argument("--expected-profile-sha256", required=True)
    v2_seed.add_argument("--max-provider-requests", required=True, type=int)

    replay = subparsers.add_parser("replay")
    replay.add_argument("--run-id", required=True)
    replay.add_argument("--source-database", required=True, type=Path)
    replay.add_argument("--raw-archive-dir", required=True, type=Path)
    replay.add_argument("--replay-database", required=True, type=Path)
    replay.add_argument("--report", type=Path)

    reindex = subparsers.add_parser("reindex-discovery")
    reindex.add_argument("--run-id", required=True)
    reindex.add_argument("--source-database", required=True, type=Path)
    reindex.add_argument("--raw-archive-dir", required=True, type=Path)
    reindex.add_argument("--reindexed-database", required=True, type=Path)
    reindex.add_argument("--expected-source-database-sha256", required=True)
    reindex.add_argument("--release-manifest", required=True, type=Path)
    reindex.add_argument(
        "--expected-release-manifest-sha256", required=True
    )
    reindex.add_argument("--report", required=True, type=Path)

    recovery = subparsers.add_parser("recover-collection")
    recovery.add_argument("--run-id", required=True)
    recovery.add_argument("--source-database", required=True, type=Path)
    recovery.add_argument("--raw-archive-dir", required=True, type=Path)
    recovery.add_argument(
        "--recovered-database",
        dest="reindexed_database",
        required=True,
        type=Path,
    )
    recovery.add_argument(
        "--expected-source-database-sha256", required=True
    )
    recovery.add_argument("--recovered-at-utc", required=True)
    recovery.add_argument("--release-manifest", required=True, type=Path)
    recovery.add_argument(
        "--expected-release-manifest-sha256", required=True
    )
    recovery.add_argument("--report", required=True, type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--scope", required=True, choices=("seed", "full"))
    validate.add_argument("--run-id", required=True)
    validate.add_argument("--database", required=True, type=Path)
    validate.add_argument("--raw-archive-dir", required=True, type=Path)
    validate.add_argument("--replay-database", type=Path)
    validate.add_argument("--run-root", type=Path)
    validate.add_argument("--seed-baseline", required=True, type=Path)
    validate.add_argument("--release-manifest", required=True, type=Path)
    validate.add_argument("--expected-release-manifest-sha256")
    validate.add_argument("--report", required=True, type=Path)

    merge_plan = subparsers.add_parser("merge-plan")
    _merge_common_arguments(merge_plan)
    merge_plan.add_argument("--output", required=True, type=Path)

    merge_production = subparsers.add_parser("merge-production")
    _merge_common_arguments(merge_production)
    merge_production.add_argument("--expected-acceptance-report-sha256", required=True)
    merge_production.add_argument("--merge-plan", required=True, type=Path)
    merge_production.add_argument("--expected-merge-plan-sha256", required=True)
    merge_production.add_argument("--backup-database", required=True, type=Path)
    merge_production.add_argument("--expected-production-sha256", required=True)
    merge_production.add_argument("--output", required=True, type=Path)
    merge_production.add_argument("--authorize-production-write", action="store_true")
    return parser


def _provider_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--raw-archive-dir", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--authorize-provider-call", action="store_true")


def _merge_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--staging-database", required=True, type=Path)
    parser.add_argument("--production-database", required=True, type=Path)
    parser.add_argument("--acceptance-report", required=True, type=Path)


def _manifest_row(store: BackfillStore, run_id: str) -> dict[str, object]:
    with store.connect() as connection:
        row = connection.execute(
            "SELECT * FROM backfill_manifests WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None:
        raise BackfillCliError("backfill_manifest_missing")
    return dict(row)


def _decode_manifest_sequence(value: object, *, reason: str) -> tuple[str, ...]:
    if type(value) is not str:
        raise BackfillCliError(reason)
    decoded = _strict_json_bytes(value.encode("utf-8"), reason=reason)
    if (
        not isinstance(decoded, list)
        or not decoded
        or any(type(item) is not str or not item.strip() for item in decoded)
        or len(set(decoded)) != len(decoded)
    ):
        raise BackfillCliError(reason)
    return tuple(decoded)


def _window_from_manifest(row: dict[str, object]) -> CollectionWindow:
    start_utc = _parse_utc(cast(str, row["window_start_utc"]))
    end_utc = _parse_utc(cast(str, row["effective_end_utc"]))
    if end_utc <= start_utc:
        raise BackfillCliError("backfill_window_invalid")
    zone = ZoneInfo("Asia/Shanghai")
    return CollectionWindow(
        timezone_name="Asia/Shanghai",
        run_at_local=end_utc.astimezone(zone),
        start_local=start_utc.astimezone(zone),
        end_local=end_utc.astimezone(zone),
        start_utc=start_utc,
        end_utc=end_utc,
    )


def _assert_seed_manifest_contract(
    row: dict[str, object],
    *,
    run_id: str,
    start_utc: datetime | None = None,
    requested_end_utc: datetime | None = None,
    effective_end_utc: datetime | None = None,
    require_probe_contract: bool = True,
) -> None:
    search_terms = _decode_manifest_sequence(
        row.get("search_terms_json"), reason="search_terms_contract_mismatch"
    )
    subreddits = _decode_manifest_sequence(
        row.get("subreddits_json"), reason="subreddits_contract_mismatch"
    )
    expected_lanes = required_lanes_sha256(
        search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
        subreddits=DEFAULT_REVIEWED_SUBREDDITS,
        include_subreddit_sweep=False,
    )
    checks = [
        row.get("run_id") == run_id,
        search_terms == tuple(DEFAULT_TIKHUB_SEARCH_TERMS),
        subreddits == tuple(DEFAULT_REVIEWED_SUBREDDITS),
        row.get("keyword_config_sha256") == keyword_rules_sha256(),
        row.get("live_send") == 0,
    ]
    if require_probe_contract:
        checks.extend(
            (
                row.get("include_subreddit_sweep") == 0,
                row.get("required_lanes_sha256") == expected_lanes,
                row.get("max_provider_requests") == CONTRACT_PROBE_MAX_REQUESTS,
            )
        )
    if not all(checks):
        raise BackfillCliError("seed_manifest_contract_mismatch")
    for actual, expected in (
        (row.get("window_start_utc"), start_utc),
        (row.get("requested_end_utc"), requested_end_utc),
        (row.get("effective_end_utc"), effective_end_utc),
    ):
        if expected is not None and _parse_utc(cast(str, actual)) != expected:
            raise BackfillCliError("seed_manifest_contract_mismatch")


def run_profile_admission(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    """Admit a reviewed V2 term profile for a distinct, future staging run.

    This command intentionally has no database, archive, or provider parameters.
    It proves only that the reviewed delta is immutable and cannot overwrite the
    frozen legacy run; collection remains a separately authorized operation.
    """

    try:
        profile = load_v2_search_profile(
            cast(Path, args.profile),
            expected_sha256=cast(str, args.expected_profile_sha256),
        )
    except BackfillProfileError as error:
        raise BackfillCliError(str(error), status="blocked") from None
    if args.run_id == profile.legacy_run_id:
        raise BackfillCliError("v2_profile_requires_distinct_run", status="blocked")
    return 0, {
        "schema_version": "backfill_v2_profile_admission_v1",
        "run_id": args.run_id,
        "status": "ready_for_new_isolated_run",
        "profile_sha256": profile.sha256,
        "legacy_run_id": profile.legacy_run_id,
        "candidate_term_count": len(profile.candidate_terms),
        "delta_term_count": len(profile.delta_terms),
        "delta_terms": list(profile.delta_terms),
        "provider_call": False,
        "provider_attempt_made": False,
        "production_merge": False,
        "git_push": False,
        "live_send": False,
    }


def _assert_v2_seed_manifest_contract(
    row: dict[str, object],
    *,
    run_id: str,
    profile_terms: tuple[str, ...],
    profile_sha256: str,
    start_utc: datetime,
    requested_end_utc: datetime,
    effective_end_utc: datetime,
    max_provider_requests: int,
) -> None:
    terms = _decode_manifest_sequence(
        row.get("search_terms_json"), reason="v2_seed_manifest_contract_mismatch"
    )
    subreddits = _decode_manifest_sequence(
        row.get("subreddits_json"), reason="v2_seed_manifest_contract_mismatch"
    )
    checks = (
        row.get("run_id") == run_id,
        terms == profile_terms,
        subreddits == tuple(DEFAULT_REVIEWED_SUBREDDITS),
        row.get("include_subreddit_sweep") == 0,
        row.get("required_lanes_sha256")
        == required_lanes_sha256(
            search_terms=profile_terms,
            subreddits=DEFAULT_REVIEWED_SUBREDDITS,
            include_subreddit_sweep=False,
        ),
        row.get("keyword_config_sha256") == keyword_rules_sha256(),
        row.get("max_provider_requests") == max_provider_requests,
        row.get("provider_request_count") == 0,
        row.get("provider_call") == 0,
        row.get("live_send") == 0,
        row.get("status") in {"prepared", "seed_complete", "failed"},
    )
    if not all(checks):
        raise BackfillCliError("v2_seed_manifest_contract_mismatch")
    for actual, expected in (
        (row.get("window_start_utc"), start_utc),
        (row.get("requested_end_utc"), requested_end_utc),
        (row.get("effective_end_utc"), effective_end_utc),
    ):
        if _parse_utc(cast(str, actual)) != expected:
            raise BackfillCliError("v2_seed_manifest_contract_mismatch")
    if not _is_sha256(profile_sha256):
        raise BackfillCliError("v2_seed_profile_sha256_invalid")


def run_v2_seed(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    start_utc = _parse_utc(args.window_start_utc)
    requested_end_utc = _parse_utc(args.requested_window_end_utc)
    effective_end_utc = _parse_utc(args.effective_window_end_utc)
    if not start_utc < effective_end_utc <= requested_end_utc:
        raise BackfillCliError("backfill_window_invalid")
    if type(args.max_provider_requests) is not int or args.max_provider_requests <= 0:
        raise BackfillCliError("v2_seed_provider_budget_invalid", status="blocked")
    try:
        profile = load_v2_search_profile(
            cast(Path, args.profile),
            expected_sha256=cast(str, args.expected_profile_sha256),
        )
    except BackfillProfileError as error:
        raise BackfillCliError(str(error), status="blocked") from None
    if args.run_id == profile.legacy_run_id:
        raise BackfillCliError("v2_profile_requires_distinct_run", status="blocked")

    database = cast(Path, args.database)
    _require_isolated_staging_paths(
        database=database,
        raw_archive=args.raw_archive_dir,
        report_dir=args.report_dir,
        require_existing=False,
    )
    try:
        source_root = args.source_dir.resolve(strict=True)
        output_root = database.parent.resolve(strict=False)
    except (OSError, ValueError):
        raise BackfillCliError("seed_source_invalid") from None
    if (
        not source_root.is_dir()
        or source_root == output_root
        or source_root.is_relative_to(output_root)
        or output_root.is_relative_to(source_root)
    ):
        raise BackfillCliError("seed_source_overlaps_run_root")
    if not any(
        path.is_file() and path.suffix.lower() == ".json"
        for path in source_root.rglob("*")
    ):
        raise BackfillCliError("v2_seed_source_empty", status="blocked")

    database.parent.mkdir(parents=True, exist_ok=True)
    expected_database_identity = _admit_existing_seed_database(database)
    with _pinned_seed_database(
        database, expected_database_identity
    ) as pinned_database:
        store = BackfillStore(pinned_database)
        store.migrate()
        with store.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM backfill_manifests WHERE run_id = ?", (args.run_id,)
            ).fetchone()
        now = datetime.now(timezone.utc)
        if existing is None:
            store.create_manifest(
                BackfillManifest(
                    run_id=args.run_id,
                    status="prepared",
                    window_start_utc=start_utc.isoformat(),
                    requested_end_utc=requested_end_utc.isoformat(),
                    effective_end_utc=effective_end_utc.isoformat(),
                    search_terms=profile.delta_terms,
                    subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=False,
                    required_lanes_sha256=required_lanes_sha256(
                        search_terms=profile.delta_terms,
                        subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                        include_subreddit_sweep=False,
                    ),
                    keyword_config_sha256=keyword_rules_sha256(),
                    max_provider_requests=args.max_provider_requests,
                    provider_request_count=0,
                    provider_call=False,
                    live_send=False,
                    created_at_utc=now.isoformat(),
                    updated_at_utc=now.isoformat(),
                )
            )
        else:
            _assert_v2_seed_manifest_contract(
                dict(existing),
                run_id=args.run_id,
                profile_terms=profile.delta_terms,
                profile_sha256=profile.sha256,
                start_utc=start_utc,
                requested_end_utc=requested_end_utc,
                effective_end_utc=effective_end_utc,
                max_provider_requests=args.max_provider_requests,
            )
        archive = PrivateRawArchive(args.raw_archive_dir)
        summary = import_seed_directory(
            store,
            archive,
            run_id=args.run_id,
            source_dir=args.source_dir,
            window_start_utc=start_utc,
            effective_end_utc=effective_end_utc,
            captured_at_utc=now,
        )
    _assert_seed_database_identity(database, expected_database_identity)
    _require_isolated_staging_paths(
        database=database,
        raw_archive=args.raw_archive_dir,
        report_dir=args.report_dir,
        require_existing=False,
    )
    payload: dict[str, object] = {
        "schema_version": "backfill_v2_seed_cli_v1",
        "run_id": args.run_id,
        "profile_sha256": profile.sha256,
        "delta_term_count": len(profile.delta_terms),
        "required_lanes_sha256": required_lanes_sha256(
            search_terms=profile.delta_terms,
            subreddits=DEFAULT_REVIEWED_SUBREDDITS,
            include_subreddit_sweep=False,
        ),
        "max_provider_requests": args.max_provider_requests,
        "seed": asdict(summary),
        "provider_call": False,
        "provider_attempt_made": False,
        "production_merge": False,
        "git_push": False,
        "live_send": False,
    }
    report_digest = sha256(_canonical_json_bytes(payload, newline=True)).hexdigest()
    _publish_or_verify_json(
        args.report_dir / f"{args.run_id}-v2-seed-000000-{report_digest[:16]}.json",
        payload,
    )
    return (0 if summary.status == "seed_complete" else 1), payload


def run_seed(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    start_utc = _parse_utc(args.window_start_utc)
    requested_end_utc = _parse_utc(args.requested_window_end_utc)
    effective_end_utc = _parse_utc(args.effective_window_end_utc)
    if not start_utc < effective_end_utc <= requested_end_utc:
        raise BackfillCliError("backfill_window_invalid")
    database = cast(Path, args.database)
    _require_isolated_staging_paths(
        database=database,
        raw_archive=args.raw_archive_dir,
        report_dir=args.report_dir,
        require_existing=False,
    )
    try:
        source_root = args.source_dir.resolve(strict=True)
        output_root = database.parent.resolve(strict=False)
    except (OSError, ValueError):
        raise BackfillCliError("seed_source_invalid") from None
    if (
        not source_root.is_dir()
        or source_root == output_root
        or source_root.is_relative_to(output_root)
        or output_root.is_relative_to(source_root)
    ):
        raise BackfillCliError("seed_source_overlaps_run_root")
    database.parent.mkdir(parents=True, exist_ok=True)
    expected_database_identity = _admit_existing_seed_database(database)
    with _pinned_seed_database(
        database, expected_database_identity
    ) as pinned_database:
        store = BackfillStore(pinned_database)
        store.migrate()
        with store.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM backfill_manifests WHERE run_id = ?",
                (args.run_id,),
            ).fetchone()
        now = datetime.now(timezone.utc)
        if existing is None:
            store.create_manifest(
                BackfillManifest(
                    run_id=args.run_id,
                    status="prepared",
                    window_start_utc=start_utc.isoformat(),
                    requested_end_utc=requested_end_utc.isoformat(),
                    effective_end_utc=effective_end_utc.isoformat(),
                    search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                    subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                    include_subreddit_sweep=False,
                    required_lanes_sha256=required_lanes_sha256(
                        search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
                        subreddits=DEFAULT_REVIEWED_SUBREDDITS,
                        include_subreddit_sweep=False,
                    ),
                    keyword_config_sha256=keyword_rules_sha256(),
                    max_provider_requests=CONTRACT_PROBE_MAX_REQUESTS,
                    provider_request_count=0,
                    provider_call=False,
                    live_send=False,
                    created_at_utc=now.isoformat(),
                    updated_at_utc=now.isoformat(),
                )
            )
        else:
            _assert_seed_manifest_contract(
                dict(existing),
                run_id=args.run_id,
                start_utc=start_utc,
                requested_end_utc=requested_end_utc,
                effective_end_utc=effective_end_utc,
            )
            if (
                existing["status"] not in {"prepared", "seed_complete", "failed"}
                or int(existing["provider_request_count"]) != 0
                or bool(existing["provider_call"])
            ):
                raise BackfillCliError(
                    "seed_resume_after_provider_activity_rejected"
                )
        archive = PrivateRawArchive(args.raw_archive_dir)
        summary = import_seed_directory(
            store,
            archive,
            run_id=args.run_id,
            source_dir=args.source_dir,
            window_start_utc=start_utc,
            effective_end_utc=effective_end_utc,
            captured_at_utc=now,
        )
    _assert_seed_database_identity(database, expected_database_identity)
    _require_isolated_staging_paths(
        database=database,
        raw_archive=args.raw_archive_dir,
        report_dir=args.report_dir,
        require_existing=False,
    )
    payload: dict[str, object] = {
        "schema_version": "backfill_seed_cli_v1",
        "run_id": args.run_id,
        "seed": asdict(summary),
    }
    _publish_json(args.report_dir / f"{args.run_id}-seed.json", payload)
    return (0 if summary.status == "seed_complete" else 1), payload


PROBE_REPORT_KEYS = (
    "schema_version",
    "run_id",
    "status",
    "stop_reason",
    "contract_probe_max_requests",
    "provider_request_count_before",
    "provider_request_count_after",
    "attempts_used",
    "dynamic_search_term_sha256",
    "committed_pages",
    "unique_candidates",
    "cursor_path",
    "cursor_schema_sha256",
    "observed_page_span_seconds",
    "recommended_max_provider_requests",
    "recommended_max_provider_requests_with_subreddit_sweep",
    "cost_uncertainty",
    "release_manifest_sha256",
    "provider_call",
    "live_send",
)
BUDGET_EXTENSION_AUTHORIZATION_KEYS = (
    "schema_version",
    "run_id",
    "release_manifest_sha256",
    "probe_report_sha256",
    "expected_source_database_sha256",
    "expected_provider_request_count",
    "expected_max_provider_requests",
    "new_max_provider_requests_total",
    "discovery_request_ceiling",
    "hydration_request_reserve",
    "include_subreddit_sweep",
    "required_lanes_sha256",
    "lane_page_ceilings_sha256",
    "lane_page_ceilings",
    "live_send",
)
EXISTING_BUDGET_RESUME_AUTHORIZATION_KEYS = (
    "schema_version",
    "run_id",
    "release_manifest_sha256",
    "probe_report_sha256",
    "expected_source_database_sha256",
    "expected_provider_request_count",
    "max_provider_requests_total",
    "discovery_request_ceiling",
    "hydration_request_reserve",
    "include_subreddit_sweep",
    "required_lanes_sha256",
    "lane_page_ceilings_sha256",
    "lane_page_ceilings",
    "candidate_state_sha256",
    "live_send",
)
LANE_PAGE_CEILING_KEYS = (
    "lane_type",
    "lane_key",
    "expected_page_number",
    "absolute_page_ceiling",
)


def _checkpoint_for_probe(store: BackfillStore, run_id: str) -> BackfillCheckpoint | None:
    return store.load_checkpoint(
        run_id=run_id,
        lane_type="dynamic_search",
        lane_key=DEFAULT_TIKHUB_SEARCH_TERMS[0],
    )


def _probe_recommendations(
    *, pages: int, unique_candidates: int
) -> tuple[int, int]:
    per_page = max(1, math.ceil(unique_candidates / max(1, pages)))

    def estimate(lane_count: int) -> int:
        estimated_candidates = per_page * 2 * lane_count
        base = 2 * lane_count + math.ceil(estimated_candidates / 30) + 2 * estimated_candidates
        return max(CONTRACT_PROBE_MAX_REQUESTS, base)

    dynamic = estimate(len(DEFAULT_TIKHUB_SEARCH_TERMS))
    with_subreddits = estimate(
        len(DEFAULT_TIKHUB_SEARCH_TERMS) + len(DEFAULT_REVIEWED_SUBREDDITS)
    )
    return dynamic, with_subreddits


def _probe_payload(
    *,
    run_id: str,
    before: int,
    checkpoint: BackfillCheckpoint | None,
    store: BackfillStore,
    manifest_sha256: str,
    stop_reason: str,
) -> dict[str, object]:
    after = store.provider_request_count(run_id)
    pages = 0 if checkpoint is None else checkpoint.page_number
    unique_candidates = 0 if checkpoint is None else checkpoint.unique_count
    cursor_path: list[str | int] = []
    cursor_schema_sha256 = ""
    if checkpoint is not None and checkpoint.cursor_json_path is not None:
        decoded = _strict_json_bytes(
            checkpoint.cursor_json_path.encode("utf-8"),
            reason="probe_cursor_contract_invalid",
        )
        if not isinstance(decoded, list):
            raise BackfillCliError("probe_cursor_contract_invalid")
        cursor_path = cast(list[str | int], decoded)
        cursor_schema_sha256 = checkpoint.cursor_schema_sha256 or ""
    ready = (
        checkpoint is not None
        and 1 <= pages <= CONTRACT_PROBE_MAX_SUCCESS_PAGES
        and bool(cursor_path)
        and _is_sha256(cursor_schema_sha256)
        and 1 <= after <= CONTRACT_PROBE_MAX_REQUESTS
        and stop_reason in READY_PROBE_STOP_REASONS
    )
    span_seconds: float | None = None
    if (
        checkpoint is not None
        and checkpoint.newest_seen_utc is not None
        and checkpoint.oldest_seen_utc is not None
    ):
        span_seconds = max(
            0.0,
            (
                _parse_utc(checkpoint.newest_seen_utc)
                - _parse_utc(checkpoint.oldest_seen_utc)
            ).total_seconds(),
        )
    recommendation, sweep_recommendation = _probe_recommendations(
        pages=pages, unique_candidates=unique_candidates
    )
    return {
        "schema_version": "backfill_contract_probe_v1",
        "run_id": run_id,
        "status": "ready" if ready else "rejected",
        "stop_reason": stop_reason,
        "contract_probe_max_requests": CONTRACT_PROBE_MAX_REQUESTS,
        "provider_request_count_before": before,
        "provider_request_count_after": after,
        "attempts_used": after - before,
        "dynamic_search_term_sha256": sha256(
            DEFAULT_TIKHUB_SEARCH_TERMS[0].encode("utf-8")
        ).hexdigest(),
        "committed_pages": pages,
        "unique_candidates": unique_candidates,
        "cursor_path": cursor_path,
        "cursor_schema_sha256": cursor_schema_sha256,
        "observed_page_span_seconds": span_seconds,
        "recommended_max_provider_requests": recommendation,
        "recommended_max_provider_requests_with_subreddit_sweep": sweep_recommendation,
        "cost_uncertainty": "high_unbounded_comment_pagination",
        "release_manifest_sha256": manifest_sha256,
        "provider_call": store.provider_call_evidence(run_id),
        "live_send": False,
    }


def _probe_report_is_ready(
    report: dict[str, object],
    *,
    run_id: str,
    release_manifest_sha256: str,
    allow_historical_release_manifest: bool = False,
) -> bool:
    cursor_path = report["cursor_path"]
    before = report["provider_request_count_before"]
    after = report["provider_request_count_after"]
    attempts = report["attempts_used"]
    pages = report["committed_pages"]
    candidates = report["unique_candidates"]
    recommendation = report["recommended_max_provider_requests"]
    sweep_recommendation = report[
        "recommended_max_provider_requests_with_subreddit_sweep"
    ]
    observed_span = report["observed_page_span_seconds"]
    numeric_contract = (
        type(before) is int
        and type(after) is int
        and type(attempts) is int
        and type(pages) is int
        and type(candidates) is int
        and type(recommendation) is int
        and type(sweep_recommendation) is int
    )
    if not numeric_contract:
        return False
    expected_recommendation, expected_sweep_recommendation = _probe_recommendations(
        pages=cast(int, pages), unique_candidates=cast(int, candidates)
    )
    return bool(
        report["schema_version"] == "backfill_contract_probe_v1"
        and report["run_id"] == run_id
        and report["status"] == "ready"
        and report["stop_reason"] in READY_PROBE_STOP_REASONS
        and report["contract_probe_max_requests"] == CONTRACT_PROBE_MAX_REQUESTS
        and 0 <= cast(int, before) <= cast(int, after) <= 4
        and cast(int, attempts) == cast(int, after) - cast(int, before)
        and 0 <= cast(int, attempts) <= 4
        and 1 <= cast(int, pages) <= 2
        and cast(int, candidates) >= 0
        and cast(int, recommendation) == expected_recommendation
        and cast(int, sweep_recommendation) == expected_sweep_recommendation
        and cast(int, sweep_recommendation) >= cast(int, recommendation) >= 4
        and (
            observed_span is None
            or (
                type(observed_span) in {int, float}
                and math.isfinite(cast(float, observed_span))
                and cast(float, observed_span) >= 0
            )
        )
        and isinstance(cursor_path, list)
        and bool(cursor_path)
        and all(
            (type(component) is str and bool(component))
            or (type(component) is int and component >= 0)
            for component in cursor_path
        )
        and _is_sha256(report["cursor_schema_sha256"])
        and report["dynamic_search_term_sha256"]
        == sha256(DEFAULT_TIKHUB_SEARCH_TERMS[0].encode("utf-8")).hexdigest()
        and report["cost_uncertainty"]
        == "high_unbounded_comment_pagination"
        and (
            (
                allow_historical_release_manifest
                and _is_sha256(report["release_manifest_sha256"])
            )
            or report["release_manifest_sha256"] == release_manifest_sha256
        )
        and report["provider_call"] is True
        and report["live_send"] is False
    )


def _load_existing_probe(
    path: Path, *, run_id: str, release_manifest_sha256: str
) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise BackfillCliError("probe_report_unreadable") from None
    report = _exact_dict(
        _strict_json_bytes(raw, reason="probe_report_invalid"),
        PROBE_REPORT_KEYS,
        reason="probe_report_invalid",
    )
    if not _probe_report_is_ready(
        report,
        run_id=run_id,
        release_manifest_sha256=release_manifest_sha256,
    ):
        raise BackfillCliError("probe_report_invalid")
    return report


def run_probe(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    api_key = _provider_gate(args.authorize_provider_call)
    _require_isolated_staging_paths(
        database=args.database,
        raw_archive=args.raw_archive_dir,
        report_dir=args.report_dir,
        require_existing=True,
    )
    bundle = load_release_bundle(
        args.release_manifest,
        baseline_path=CODE_ROOT / SEED_BASELINE_RELATIVE_PATH,
        comment_cursor_path=CODE_ROOT / COMMENT_CURSOR_RELATIVE_PATH,
        run_id=args.run_id,
    )
    store = BackfillStore(args.database)
    row = _manifest_row(store, args.run_id)
    report_path = args.report_dir / f"{args.run_id}-probe.json"
    if report_path.exists() or report_path.is_symlink():
        _assert_seed_manifest_contract(
            row,
            run_id=args.run_id,
            require_probe_contract=row["status"] == "seed_complete",
        )
        existing = _load_existing_probe(
            report_path,
            run_id=args.run_id,
            release_manifest_sha256=bundle.manifest_sha256,
        )
        if row["status"] == "seed_complete":
            _assert_probe_staging_state(
                store, run_id=args.run_id, report=existing
            )
        return 0, existing

    _assert_seed_manifest_contract(row, run_id=args.run_id)
    request_count = row["provider_request_count"]
    if (
        row["status"] != "seed_complete"
        or type(request_count) is not int
        or request_count > CONTRACT_PROBE_MAX_REQUESTS
    ):
        raise BackfillCliError("probe_manifest_state_invalid")
    before = store.provider_request_count(args.run_id)
    checkpoint = _checkpoint_for_probe(store, args.run_id)
    committed_pages = 0 if checkpoint is None else checkpoint.page_number
    if committed_pages > CONTRACT_PROBE_MAX_SUCCESS_PAGES:
        raise BackfillCliError("probe_page_cap_exceeded")
    remaining_pages = CONTRACT_PROBE_MAX_SUCCESS_PAGES - committed_pages
    stop_reason = checkpoint.stop_reason if checkpoint is not None else "probe_not_run"
    if remaining_pages:
        archive = PrivateRawArchive(args.raw_archive_dir)
        client = TikHubClient(
            api_key=api_key,
            base_url=os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.io"),
        )
        executor = TikHubRequestExecutor(
            client,
            store,
            args.run_id,
            sleep=time.sleep,
            now=lambda: datetime.now(timezone.utc),
        )
        result = TikHubBackfillDiscoverer(
            executor,
            store,
            archive,
            args.run_id,
            now=lambda: datetime.now(timezone.utc),
        ).run_dynamic_search(
            DEFAULT_TIKHUB_SEARCH_TERMS[0],
            _window_from_manifest(row),
            max_pages=remaining_pages,
        )
        stop_reason = result.stop_reason
        checkpoint = _checkpoint_for_probe(store, args.run_id)
    payload = _probe_payload(
        run_id=args.run_id,
        before=before,
        checkpoint=checkpoint,
        store=store,
        manifest_sha256=bundle.manifest_sha256,
        stop_reason=stop_reason or "probe_incomplete",
    )
    if payload["status"] == "ready":
        _publish_json(report_path, payload)
    else:
        _publish_evidence_snapshot(
            args.report_dir,
            run_id=args.run_id,
            phase="probe-rejected",
            payload=payload,
            sequence=store.provider_request_count(args.run_id),
        )
    return (0 if payload["status"] == "ready" else 1), payload


def _load_approved_probe(
    path: Path,
    *,
    expected_path: Path,
    expected_sha256: str,
    run_id: str,
    release_manifest_sha256: str,
    allow_historical_release_manifest: bool = False,
) -> dict[str, object]:
    if Path(os.path.abspath(path)) != Path(os.path.abspath(expected_path)):
        raise BackfillCliError("probe_report_path_invalid")
    if not _is_sha256(expected_sha256):
        raise BackfillCliError("probe_report_sha256_mismatch")
    try:
        raw = path.read_bytes()
    except OSError:
        raise BackfillCliError("probe_report_unreadable") from None
    if not hmac.compare_digest(sha256(raw).hexdigest(), expected_sha256):
        raise BackfillCliError("probe_report_sha256_mismatch")
    report = _exact_dict(
        _strict_json_bytes(raw, reason="probe_report_invalid"),
        PROBE_REPORT_KEYS,
        reason="probe_report_invalid",
    )
    if not _probe_report_is_ready(
        report,
        run_id=run_id,
        release_manifest_sha256=release_manifest_sha256,
        allow_historical_release_manifest=allow_historical_release_manifest,
    ):
        raise BackfillCliError("probe_report_invalid")
    return report


def _collection_resume_candidate_state_from_connection(
    connection: sqlite3.Connection, *, run_id: str
) -> str:
    state: dict[str, list[list[object]]] = {}
    queries = {
        "candidates": (
            "SELECT post_id, first_lane_type, first_lane_key, "
            "first_discovered_at_utc, source_url, post_created_at_utc, "
            "raw_artifact_id, status, status_reason, updated_at_utc "
            "FROM backfill_candidates WHERE run_id=? ORDER BY post_id"
        ),
        "detail_batches": (
            "SELECT batch_id, batch_number, status, artifact_id, stop_reason, "
            "created_at_utc, updated_at_utc FROM backfill_detail_batches "
            "WHERE run_id=? ORDER BY batch_number, batch_id"
        ),
        "detail_batch_members": (
            "SELECT batch_id, ordinal, post_id "
            "FROM backfill_detail_batch_members WHERE run_id=? "
            "ORDER BY batch_id, ordinal"
        ),
        "hydration_checkpoints": (
            "SELECT lane_type, lane_key, cursor, previous_cursor, page_number, "
            "newest_seen_utc, oldest_seen_utc, discovered_count, unique_count, "
            "provider_request_count, last_success_utc, last_error, status, "
            "stop_reason, cursor_json_path, cursor_schema_sha256, "
            "consecutive_old_pages FROM backfill_checkpoints WHERE run_id=? "
            "AND lane_type IN ('detail_batch','comments') "
            "ORDER BY lane_type, lane_key"
        ),
    }
    for key, query in queries.items():
        state[key] = [list(row) for row in connection.execute(query, (run_id,))]
    return _canonical_sha256(state)


def _collection_resume_snapshot_connection(
    payload: bytes,
) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", timeout=1.0)
    try:
        connection.deserialize(payload)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except Exception:
        connection.close()
        raise


def _collection_resume_candidate_state_sha256(
    source_database: Path, *, run_id: str
) -> str:
    snapshot = _read_pinned_reviewed_file(
        source_database,
        reason="existing_budget_resume_source_database_invalid",
    )
    connection: sqlite3.Connection | None = None
    try:
        connection = _collection_resume_snapshot_connection(snapshot.payload)
        return _collection_resume_candidate_state_from_connection(
            connection, run_id=run_id
        )
    except sqlite3.DatabaseError:
        raise BackfillCliError(
            "existing_budget_resume_source_database_invalid"
        ) from None
    finally:
        if connection is not None:
            connection.close()


def _existing_budget_resume_state_is_authorized(
    source_payload: bytes,
    *,
    run_id: str,
    authorization_sha256: str,
    packet: dict[str, object],
    expected_lanes: tuple[tuple[str, str], ...],
    initial: bool,
) -> bool:
    connection: sqlite3.Connection | None = None
    try:
        connection = _collection_resume_snapshot_connection(source_payload)
        manifest = connection.execute(
            "SELECT status, max_provider_requests, provider_request_count, "
            "provider_call, live_send, include_subreddit_sweep, "
            "required_lanes_sha256 FROM backfill_manifests WHERE run_id=?",
            (run_id,),
        ).fetchone()
        run = connection.execute(
            "SELECT status, provider_call, live_send FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if manifest is None or run is None:
            return False
        expected_count = cast(int, packet["expected_provider_request_count"])
        maximum = cast(int, packet["max_provider_requests_total"])
        current_count = int(manifest["provider_request_count"])
        attempts = connection.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status IN ('succeeded','failed') THEN 1 ELSE 0 END) "
            "AS terminal, MIN(request_number) AS minimum, "
            "MAX(request_number) AS maximum FROM backfill_provider_attempts "
            "WHERE run_id=?",
            (run_id,),
        ).fetchone()
        common_valid = bool(
            str(manifest["status"])
            in ({"partial"} if initial else {"running", "partial", "success"})
            and str(run["status"]) == str(manifest["status"])
            and int(manifest["max_provider_requests"]) == maximum
            and (
                current_count == expected_count
                if initial
                else expected_count <= current_count <= maximum
            )
            and int(manifest["provider_call"]) == 1
            and int(run["provider_call"]) == 1
            and int(manifest["live_send"]) == 0
            and int(run["live_send"]) == 0
            and int(manifest["include_subreddit_sweep"])
            == int(cast(bool, packet["include_subreddit_sweep"]))
            and str(manifest["required_lanes_sha256"])
            == packet["required_lanes_sha256"]
            and current_count > 0
            and int(attempts["total"] or 0) == current_count
            and int(attempts["terminal"] or 0) == current_count
            and int(attempts["minimum"] or 0) == 1
            and int(attempts["maximum"] or 0) == current_count
        )
        if not common_valid:
            return False
        if initial:
            if (
                _collection_resume_candidate_state_from_connection(
                    connection, run_id=run_id
                )
                != packet["candidate_state_sha256"]
            ):
                return False
        else:
            ledger = connection.execute(
                "SELECT expected_source_database_sha256, "
                "expected_provider_request_count, max_provider_requests, "
                "discovery_request_ceiling, lane_page_ceilings_sha256, "
                "candidate_state_sha256, include_subreddit_sweep, "
                "required_lanes_sha256 FROM backfill_collection_resumes "
                "WHERE run_id=? AND authorization_sha256=?",
                (run_id, authorization_sha256),
            ).fetchone()
            expected_ledger = (
                packet["expected_source_database_sha256"],
                expected_count,
                maximum,
                packet["discovery_request_ceiling"],
                packet["lane_page_ceilings_sha256"],
                packet["candidate_state_sha256"],
                int(cast(bool, packet["include_subreddit_sweep"])),
                packet["required_lanes_sha256"],
            )
            # A fresh continuation authorization is recorded immediately after
            # this loader returns.  Therefore the ledger row may legitimately
            # be absent on first use; if a row already exists, it must still
            # match the packet exactly.
            if ledger is not None and tuple(ledger) != expected_ledger:
                return False
        for value, lane in zip(
            cast(list[dict[str, object]], packet["lane_page_ceilings"]),
            expected_lanes,
            strict=True,
        ):
            checkpoint = connection.execute(
                "SELECT page_number FROM backfill_checkpoints "
                "WHERE run_id=? AND lane_type=? AND lane_key=?",
                (run_id, lane[0], lane[1]),
            ).fetchone()
            current_page = 0 if checkpoint is None else int(checkpoint[0])
            expected_page = cast(int, value["expected_page_number"])
            absolute_ceiling = cast(int, value["absolute_page_ceiling"])
            if (
                current_page != expected_page
                if initial
                else not expected_page <= current_page <= absolute_ceiling
            ):
                return False
        return True
    except (KeyError, TypeError, ValueError, sqlite3.DatabaseError):
        return False
    finally:
        if connection is not None:
            connection.close()


def _budget_extension_forward_state_is_authorized(
    source_database: Path,
    *,
    run_id: str,
    authorization_sha256: str,
    packet: dict[str, object],
) -> bool:
    connection: sqlite3.Connection | None = None
    try:
        database_uri = source_database.resolve(strict=True).as_uri()
        connection = sqlite3.connect(
            f"{database_uri}?mode=ro", uri=True, timeout=1.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        extension = connection.execute(
            "SELECT expected_provider_request_count, "
            "expected_max_provider_requests, new_max_provider_requests, "
            "discovery_request_ceiling, lane_page_ceilings_sha256, "
            "include_subreddit_sweep, required_lanes_sha256 "
            "FROM backfill_budget_extensions "
            "WHERE run_id = ? AND authorization_sha256 = ?",
            (run_id, authorization_sha256),
        ).fetchone()
        manifest = connection.execute(
            "SELECT status, max_provider_requests, provider_request_count, "
            "provider_call, live_send, include_subreddit_sweep, "
            "required_lanes_sha256 FROM backfill_manifests WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        run = connection.execute(
            "SELECT status, provider_call, live_send FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if extension is None or manifest is None or run is None:
            return False

        expected_count = cast(int, packet["expected_provider_request_count"])
        expected_max = cast(int, packet["expected_max_provider_requests"])
        new_max = cast(int, packet["new_max_provider_requests_total"])
        current_count = int(manifest["provider_request_count"])
        expected_extension = (
            expected_count,
            expected_max,
            new_max,
            cast(int, packet["discovery_request_ceiling"]),
            cast(str, packet["lane_page_ceilings_sha256"]),
            int(cast(bool, packet["include_subreddit_sweep"])),
            cast(str, packet["required_lanes_sha256"]),
        )
        actual_extension = (
            int(extension["expected_provider_request_count"]),
            int(extension["expected_max_provider_requests"]),
            int(extension["new_max_provider_requests"]),
            int(extension["discovery_request_ceiling"]),
            str(extension["lane_page_ceilings_sha256"]),
            int(extension["include_subreddit_sweep"]),
            str(extension["required_lanes_sha256"]),
        )
        attempt_counts = connection.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status IN ('succeeded', 'failed') THEN 1 ELSE 0 END) "
            "AS terminal, MIN(request_number) AS minimum, "
            "MAX(request_number) AS maximum "
            "FROM backfill_provider_attempts WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return bool(
            actual_extension == expected_extension
            and str(manifest["status"]) in {"running", "partial", "success"}
            and str(run["status"]) == str(manifest["status"])
            and int(manifest["max_provider_requests"]) == new_max
            and expected_count <= current_count <= new_max
            and int(manifest["provider_call"]) == 1
            and int(run["provider_call"]) == 1
            and int(manifest["live_send"]) == 0
            and int(run["live_send"]) == 0
            and int(manifest["include_subreddit_sweep"])
            == int(cast(bool, packet["include_subreddit_sweep"]))
            and str(manifest["required_lanes_sha256"])
            == packet["required_lanes_sha256"]
            and current_count > 0
            and int(attempt_counts["total"] or 0) == current_count
            and int(attempt_counts["terminal"] or 0) == current_count
            and int(attempt_counts["minimum"] or 0) == 1
            and int(attempt_counts["maximum"] or 0) == current_count
        )
    except (OSError, ValueError, sqlite3.DatabaseError, TypeError, KeyError):
        return False
    finally:
        if connection is not None:
            connection.close()


def _load_budget_extension_authorization(
    path: Path,
    *,
    expected_path: Path,
    expected_sha256: str,
    run_id: str,
    release_manifest_sha256: str,
    probe_report_sha256: str,
    source_database: Path,
    expected_lanes: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    if Path(os.path.abspath(path)) != Path(os.path.abspath(expected_path)):
        raise BackfillCliError("budget_extension_authorization_path_invalid")
    if not _is_sha256(expected_sha256):
        raise BackfillCliError("budget_extension_authorization_sha256_mismatch")
    try:
        raw = path.read_bytes()
    except OSError:
        raise BackfillCliError("budget_extension_authorization_unreadable") from None
    if not hmac.compare_digest(sha256(raw).hexdigest(), expected_sha256):
        raise BackfillCliError("budget_extension_authorization_sha256_mismatch")
    packet = _exact_dict(
        _strict_json_bytes(raw, reason="budget_extension_authorization_invalid"),
        BUDGET_EXTENSION_AUTHORIZATION_KEYS,
        reason="budget_extension_authorization_invalid",
    )
    if raw != _canonical_json_bytes(packet, newline=True):
        raise BackfillCliError("budget_extension_authorization_invalid")

    expected_source = packet["expected_source_database_sha256"]
    try:
        source_snapshot = _read_pinned_reviewed_file(
            source_database,
            reason="budget_extension_source_database_invalid",
        )
    except BackfillCliError:
        raise
    actual_source_sha256 = sha256(source_snapshot.payload).hexdigest()
    expected_scope_sha256 = _canonical_sha256(
        [[lane_type, lane_key] for lane_type, lane_key in expected_lanes]
    )
    include_subreddit_sweep = packet["include_subreddit_sweep"]
    expected_sweep = any(
        lane_type == "subreddit_feed" for lane_type, _ in expected_lanes
    )
    expected_count = packet["expected_provider_request_count"]
    expected_max = packet["expected_max_provider_requests"]
    new_max = packet["new_max_provider_requests_total"]
    discovery_ceiling = packet["discovery_request_ceiling"]
    hydration_reserve = packet["hydration_request_reserve"]
    lane_values = packet["lane_page_ceilings"]
    valid_header = (
        packet["schema_version"]
        == "momcozy_backfill_budget_extension_authorization_v1"
        and packet["run_id"] == run_id
        and _is_sha256(packet["release_manifest_sha256"])
        and hmac.compare_digest(
            cast(str, packet["release_manifest_sha256"]),
            release_manifest_sha256,
        )
        and _is_sha256(packet["probe_report_sha256"])
        and hmac.compare_digest(
            cast(str, packet["probe_report_sha256"]), probe_report_sha256
        )
        and _is_sha256(expected_source)
        and type(expected_count) is int
        and type(expected_max) is int
        and type(new_max) is int
        and type(discovery_ceiling) is int
        and type(hydration_reserve) is int
        and expected_count == expected_max
        and 0 <= expected_count < new_max
        and expected_count <= discovery_ceiling < new_max
        and hydration_reserve == new_max - discovery_ceiling
        and hydration_reserve > 0
        and type(include_subreddit_sweep) is bool
        and include_subreddit_sweep == expected_sweep
        and _is_sha256(packet["required_lanes_sha256"])
        and hmac.compare_digest(
            cast(str, packet["required_lanes_sha256"]),
            expected_scope_sha256,
        )
        and packet["live_send"] is False
        and isinstance(lane_values, list)
        and len(lane_values) == len(expected_lanes)
    )
    if not valid_header:
        raise BackfillCliError("budget_extension_authorization_invalid")

    normalized_lanes: list[dict[str, object]] = []
    for value, expected_lane in zip(lane_values, expected_lanes, strict=True):
        lane = _exact_dict(
            value,
            LANE_PAGE_CEILING_KEYS,
            reason="budget_extension_authorization_invalid",
        )
        expected_page = lane["expected_page_number"]
        absolute_ceiling = lane["absolute_page_ceiling"]
        if (
            (lane["lane_type"], lane["lane_key"]) != expected_lane
            or type(expected_page) is not int
            or type(absolute_ceiling) is not int
            or expected_page < 0
            or absolute_ceiling < expected_page
        ):
            raise BackfillCliError("budget_extension_authorization_invalid")
        normalized_lanes.append(lane)
    if (
        not _is_sha256(packet["lane_page_ceilings_sha256"])
        or not hmac.compare_digest(
            cast(str, packet["lane_page_ceilings_sha256"]),
            _canonical_sha256(normalized_lanes),
        )
    ):
        raise BackfillCliError("budget_extension_authorization_invalid")
    if not hmac.compare_digest(
        cast(str, expected_source), actual_source_sha256
    ) and not _budget_extension_forward_state_is_authorized(
        source_database,
        run_id=run_id,
        authorization_sha256=expected_sha256,
        packet=packet,
    ):
        raise BackfillCliError("budget_extension_authorization_invalid")
    return packet


def _load_existing_budget_resume_authorization(
    path: Path,
    *,
    expected_path: Path,
    expected_sha256: str,
    run_id: str,
    release_manifest_sha256: str,
    probe_report_sha256: str,
    source_database: Path,
    expected_lanes: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    if Path(os.path.abspath(path)) != Path(os.path.abspath(expected_path)):
        raise BackfillCliError(
            "existing_budget_resume_authorization_path_invalid"
        )
    if not _is_sha256(expected_sha256):
        raise BackfillCliError(
            "existing_budget_resume_authorization_sha256_mismatch"
        )
    try:
        raw = path.read_bytes()
    except OSError:
        raise BackfillCliError(
            "existing_budget_resume_authorization_unreadable"
        ) from None
    if not hmac.compare_digest(sha256(raw).hexdigest(), expected_sha256):
        raise BackfillCliError(
            "existing_budget_resume_authorization_sha256_mismatch"
        )
    packet = _exact_dict(
        _strict_json_bytes(
            raw, reason="existing_budget_resume_authorization_invalid"
        ),
        EXISTING_BUDGET_RESUME_AUTHORIZATION_KEYS,
        reason="existing_budget_resume_authorization_invalid",
    )
    if raw != _canonical_json_bytes(packet, newline=True):
        raise BackfillCliError(
            "existing_budget_resume_authorization_invalid"
        )
    source_snapshot = _read_pinned_reviewed_file(
        source_database,
        reason="existing_budget_resume_source_database_invalid",
    )
    actual_source_sha256 = sha256(source_snapshot.payload).hexdigest()
    expected_scope_sha256 = _canonical_sha256(
        [[lane_type, lane_key] for lane_type, lane_key in expected_lanes]
    )
    expected_sweep = any(
        lane_type == "subreddit_feed" for lane_type, _ in expected_lanes
    )
    expected_count = packet["expected_provider_request_count"]
    maximum = packet["max_provider_requests_total"]
    discovery_ceiling = packet["discovery_request_ceiling"]
    hydration_reserve = packet["hydration_request_reserve"]
    lane_values = packet["lane_page_ceilings"]
    valid_header = bool(
        packet["schema_version"]
        == "momcozy_backfill_existing_budget_resume_authorization_v1"
        and packet["run_id"] == run_id
        and _is_sha256(packet["release_manifest_sha256"])
        and hmac.compare_digest(
            cast(str, packet["release_manifest_sha256"]),
            release_manifest_sha256,
        )
        and _is_sha256(packet["probe_report_sha256"])
        and hmac.compare_digest(
            cast(str, packet["probe_report_sha256"]), probe_report_sha256
        )
        and _is_sha256(packet["expected_source_database_sha256"])
        and _is_sha256(packet["candidate_state_sha256"])
        and type(expected_count) is int
        and type(maximum) is int
        and type(discovery_ceiling) is int
        and type(hydration_reserve) is int
        and 0 <= expected_count < maximum
        and expected_count <= discovery_ceiling < maximum
        and hydration_reserve == maximum - discovery_ceiling
        and hydration_reserve > 0
        and type(packet["include_subreddit_sweep"]) is bool
        and packet["include_subreddit_sweep"] == expected_sweep
        and _is_sha256(packet["required_lanes_sha256"])
        and hmac.compare_digest(
            cast(str, packet["required_lanes_sha256"]),
            expected_scope_sha256,
        )
        and packet["live_send"] is False
        and isinstance(lane_values, list)
        and len(lane_values) == len(expected_lanes)
    )
    if not valid_header:
        raise BackfillCliError(
            "existing_budget_resume_authorization_invalid"
        )
    normalized_lanes: list[dict[str, object]] = []
    for value, expected_lane in zip(lane_values, expected_lanes, strict=True):
        lane = _exact_dict(
            value,
            LANE_PAGE_CEILING_KEYS,
            reason="existing_budget_resume_authorization_invalid",
        )
        expected_page = lane["expected_page_number"]
        absolute_ceiling = lane["absolute_page_ceiling"]
        if (
            (lane["lane_type"], lane["lane_key"]) != expected_lane
            or type(expected_page) is not int
            or type(absolute_ceiling) is not int
            or expected_page < 0
            or absolute_ceiling < expected_page
        ):
            raise BackfillCliError(
                "existing_budget_resume_authorization_invalid"
            )
        normalized_lanes.append(lane)
    if (
        not _is_sha256(packet["lane_page_ceilings_sha256"])
        or not hmac.compare_digest(
            cast(str, packet["lane_page_ceilings_sha256"]),
            _canonical_sha256(normalized_lanes),
        )
    ):
        raise BackfillCliError(
            "existing_budget_resume_authorization_invalid"
        )
    exact_source = hmac.compare_digest(
        cast(str, packet["expected_source_database_sha256"]),
        actual_source_sha256,
    )
    if not _existing_budget_resume_state_is_authorized(
        source_snapshot.payload,
        run_id=run_id,
        authorization_sha256=expected_sha256,
        packet=packet,
        expected_lanes=expected_lanes,
        initial=exact_source,
    ):
        raise BackfillCliError(
            "existing_budget_resume_authorization_invalid"
        )
    return packet


def _verify_approved_probe_sha(
    path: Path, *, expected_path: Path, expected_sha256: str
) -> None:
    if Path(os.path.abspath(path)) != Path(os.path.abspath(expected_path)):
        raise BackfillCliError("probe_report_path_invalid")
    if not _is_sha256(expected_sha256):
        raise BackfillCliError("probe_report_sha256_mismatch")
    try:
        actual = sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise BackfillCliError("probe_report_unreadable") from None
    if not hmac.compare_digest(actual, expected_sha256):
        raise BackfillCliError("probe_report_sha256_mismatch")


def _assert_probe_staging_state(
    store: BackfillStore, *, run_id: str, report: dict[str, object]
) -> None:
    checkpoint = _checkpoint_for_probe(store, run_id)
    if (
        checkpoint is None
        or checkpoint.page_number != report["committed_pages"]
        or checkpoint.cursor_schema_sha256 != report["cursor_schema_sha256"]
        or checkpoint.cursor_json_path is None
        or store.provider_request_count(run_id)
        != report["provider_request_count_after"]
    ):
        raise BackfillCliError("probe_staging_state_mismatch")
    cursor_path = _strict_json_bytes(
        checkpoint.cursor_json_path.encode("utf-8"),
        reason="probe_staging_state_mismatch",
    )
    if cursor_path != report["cursor_path"]:
        raise BackfillCliError("probe_staging_state_mismatch")


def _assert_budget_extension_checkpoint_state(
    store: BackfillStore,
    *,
    run_id: str,
    authorization_sha256: str,
    packet: dict[str, object],
    source_database: Path,
) -> None:
    authorization_was_applied = _budget_extension_forward_state_is_authorized(
        source_database,
        run_id=run_id,
        authorization_sha256=authorization_sha256,
        packet=packet,
    )
    for value in cast(list[dict[str, object]], packet["lane_page_ceilings"]):
        lane_type = cast(str, value["lane_type"])
        lane_key = cast(str, value["lane_key"])
        expected_page = cast(int, value["expected_page_number"])
        absolute_ceiling = cast(int, value["absolute_page_ceiling"])
        checkpoint = store.load_checkpoint(
            run_id=run_id,
            lane_type=lane_type,
            lane_key=lane_key,
        )
        current_page = 0 if checkpoint is None else checkpoint.page_number
        state_matches = (
            expected_page <= current_page <= absolute_ceiling
            if authorization_was_applied
            else current_page == expected_page
        )
        completed = checkpoint is not None and checkpoint.status == "complete"
        if not state_matches or (
            absolute_ceiling == expected_page and not completed
        ):
            raise BackfillCliError(
                "budget_extension_checkpoint_state_mismatch"
            )


def _assert_existing_budget_resume_checkpoint_state(
    store: BackfillStore,
    *,
    run_id: str,
    packet: dict[str, object],
) -> None:
    for value in cast(list[dict[str, object]], packet["lane_page_ceilings"]):
        lane_type = cast(str, value["lane_type"])
        lane_key = cast(str, value["lane_key"])
        expected_page = cast(int, value["expected_page_number"])
        absolute_ceiling = cast(int, value["absolute_page_ceiling"])
        checkpoint = store.load_checkpoint(
            run_id=run_id,
            lane_type=lane_type,
            lane_key=lane_key,
        )
        current_page = 0 if checkpoint is None else checkpoint.page_number
        if not expected_page <= current_page <= absolute_ceiling:
            raise BackfillCliError(
                "existing_budget_resume_checkpoint_state_mismatch"
            )
        if checkpoint is not None and (
            checkpoint.status == "failed"
            or (
                checkpoint.status != "complete"
                and checkpoint.stop_reason in TERMINAL_DISCOVERY_STOP_REASONS
            )
        ):
            raise BackfillCliError(
                "existing_budget_resume_checkpoint_state_mismatch"
            )


def _lane_result_snapshot(
    store: BackfillStore,
    *,
    run_id: str,
    lane_type: str,
    lane_key: str,
    stop_reason: str | None = None,
) -> LaneResult:
    checkpoint = store.load_checkpoint(
        run_id=run_id, lane_type=lane_type, lane_key=lane_key
    )
    checkpoint_status = (
        None if checkpoint is None else getattr(checkpoint, "status", None)
    )
    checkpoint_stop_reason = (
        None if checkpoint is None else getattr(checkpoint, "stop_reason", None)
    )
    result_status = (
        checkpoint_status
        if checkpoint_status in {"complete", "failed"}
        else "partial"
    )
    preserve_checkpoint_reason = (
        checkpoint_status in {"complete", "failed"}
        or checkpoint_stop_reason in TERMINAL_DISCOVERY_STOP_REASONS
    )
    result_stop_reason = (
        checkpoint_stop_reason
        if preserve_checkpoint_reason and checkpoint_stop_reason is not None
        else stop_reason or checkpoint_stop_reason or "incomplete"
    )
    return LaneResult(
        run_id=run_id,
        lane_type=cast(Any, lane_type),
        lane_key=lane_key,
        status=cast(Any, result_status),
        stop_reason=result_stop_reason,
        pages=0 if checkpoint is None else checkpoint.page_number,
        discovered_occurrences=(
            0 if checkpoint is None else checkpoint.discovered_count
        ),
        unique_candidates=0 if checkpoint is None else checkpoint.unique_count,
        provider_request_count=store.provider_request_count(run_id),
        provider_call=store.provider_call_evidence(run_id),
        live_send=False,
    )


def _run_discovery_round_robin(
    discoverer: TikHubBackfillDiscoverer,
    store: BackfillStore,
    *,
    run_id: str,
    window: CollectionWindow,
    lane_page_ceilings: list[dict[str, object]]
    | tuple[dict[str, object], ...],
) -> list[LaneResult]:
    lanes = tuple(lane_page_ceilings)
    active = list(range(len(lanes)))
    results: dict[int, LaneResult] = {}
    phase_exhausted = False
    while active and not phase_exhausted:
        next_active: list[int] = []
        for active_offset, lane_index in enumerate(active):
            lane = lanes[lane_index]
            lane_type = cast(str, lane["lane_type"])
            lane_key = cast(str, lane["lane_key"])
            absolute_ceiling = cast(int, lane["absolute_page_ceiling"])
            checkpoint = store.load_checkpoint(
                run_id=run_id,
                lane_type=lane_type,
                lane_key=lane_key,
            )
            checkpoint_status = (
                None
                if checkpoint is None
                else getattr(checkpoint, "status", None)
            )
            checkpoint_stop_reason = (
                None
                if checkpoint is None
                else getattr(checkpoint, "stop_reason", None)
            )
            if checkpoint is not None and (
                checkpoint_status in {"complete", "failed"}
                or checkpoint_stop_reason
                in TERMINAL_DISCOVERY_STOP_REASONS
            ):
                results[lane_index] = _lane_result_snapshot(
                    store,
                    run_id=run_id,
                    lane_type=lane_type,
                    lane_key=lane_key,
                )
                continue
            current_page = 0 if checkpoint is None else checkpoint.page_number
            page_limit_stop_reason = "round_robin_yield"
            if lane_type == "dynamic_search":
                result = discoverer.run_dynamic_search(
                    lane_key,
                    window,
                    max_pages=1,
                    absolute_page_ceiling=absolute_ceiling,
                    page_limit_stop_reason=page_limit_stop_reason,
                )
            elif lane_type == "subreddit_feed":
                result = discoverer.run_subreddit_feed(
                    lane_key,
                    window,
                    max_pages=1,
                    absolute_page_ceiling=absolute_ceiling,
                    page_limit_stop_reason=page_limit_stop_reason,
                )
            else:
                raise BackfillCliError("budget_extension_authorization_invalid")
            results[lane_index] = result
            if result.stop_reason in {
                "discovery_budget_exhausted",
                "budget_exhausted",
            }:
                phase_exhausted = True
                next_active.extend(active[active_offset:])
                break
            if result.stop_reason == "round_robin_yield":
                if result.pages != current_page + 1:
                    raise BackfillCliError("discovery_round_robin_state_invalid")
                next_active.append(lane_index)
        active = next_active

    if phase_exhausted:
        for lane_index in active:
            lane = lanes[lane_index]
            results[lane_index] = _lane_result_snapshot(
                store,
                run_id=run_id,
                lane_type=cast(str, lane["lane_type"]),
                lane_key=cast(str, lane["lane_key"]),
                stop_reason="discovery_budget_exhausted",
            )
    return [results[index] for index in range(len(lanes))]


def _collection_stop_reason(
    lane_results: list[LaneResult], hydration: LaneResult
) -> str:
    if hydration.status != "complete":
        return hydration.stop_reason
    for result in lane_results:
        if result.status != "complete":
            return result.stop_reason
    return "collection_complete"


def run_collect(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    authorization_path = cast(
        Path | None, getattr(args, "budget_extension_authorization", None)
    )
    authorization_sha256 = cast(
        str | None,
        getattr(
            args,
            "expected_budget_extension_authorization_sha256",
            None,
        ),
    )
    if (authorization_path is None) != (authorization_sha256 is None):
        raise BackfillCliError(
            "budget_extension_authorization_pair_required", status="blocked"
        )
    resume_authorization_path = cast(
        Path | None,
        getattr(args, "existing_budget_resume_authorization", None),
    )
    resume_authorization_sha256 = cast(
        str | None,
        getattr(
            args,
            "expected_existing_budget_resume_authorization_sha256",
            None,
        ),
    )
    if (resume_authorization_path is None) != (
        resume_authorization_sha256 is None
    ):
        raise BackfillCliError(
            "existing_budget_resume_authorization_pair_required",
            status="blocked",
        )
    if authorization_path is not None and resume_authorization_path is not None:
        raise BackfillCliError(
            "continuation_authorizations_mutually_exclusive", status="blocked"
        )
    api_key = _provider_gate(args.authorize_provider_call)
    _require_isolated_staging_paths(
        database=args.database,
        raw_archive=args.raw_archive_dir,
        report_dir=args.report_dir,
        require_existing=True,
    )
    _verify_approved_probe_sha(
        args.probe_report,
        expected_path=args.report_dir / f"{args.run_id}-probe.json",
        expected_sha256=args.expected_probe_sha256,
    )
    bundle = load_release_bundle(
        args.release_manifest,
        baseline_path=CODE_ROOT / SEED_BASELINE_RELATIVE_PATH,
        comment_cursor_path=args.comment_cursor_contract,
        run_id=args.run_id,
        expected_manifest_sha256=args.expected_release_manifest_sha256,
    )
    store = BackfillStore(args.database)
    row = _manifest_row(store, args.run_id)
    _assert_seed_manifest_contract(
        row, run_id=args.run_id, require_probe_contract=False
    )
    include_sweep = args.include_subreddit_sweep == "1"
    expected_lanes = required_lanes_snapshot(
        search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
        subreddits=DEFAULT_REVIEWED_SUBREDDITS,
        include_subreddit_sweep=include_sweep,
    )
    lane_sha256 = required_lanes_sha256(
        search_terms=DEFAULT_TIKHUB_SEARCH_TERMS,
        subreddits=DEFAULT_REVIEWED_SUBREDDITS,
        include_subreddit_sweep=include_sweep,
    )
    initial_collection = row["status"] == "seed_complete"
    if initial_collection and (
        authorization_path is not None or resume_authorization_path is not None
    ):
        raise BackfillCliError(
            "budget_extension_authorization_not_applicable", status="blocked"
        )
    if not initial_collection and (
        authorization_path is None and resume_authorization_path is None
    ):
        raise BackfillCliError(
            "budget_extension_authorization_pair_required", status="blocked"
        )

    authorization: dict[str, object] | None = None
    authorization_kind: Literal["budget_extension", "existing_budget_resume"] | None = None
    if authorization_path is not None and authorization_sha256 is not None:
        authorization_kind = "budget_extension"
        authorization = _load_budget_extension_authorization(
            authorization_path,
            expected_path=args.report_dir
            / f"{args.run_id}-budget-extension-authorization.json",
            expected_sha256=authorization_sha256,
            run_id=args.run_id,
            release_manifest_sha256=bundle.manifest_sha256,
            probe_report_sha256=args.expected_probe_sha256,
            source_database=args.database,
            expected_lanes=expected_lanes,
        )
        if (
            args.max_provider_requests_total
            != authorization["new_max_provider_requests_total"]
        ):
            raise BackfillCliError("budget_extension_authorization_invalid")
        _assert_budget_extension_checkpoint_state(
            store,
            run_id=args.run_id,
            authorization_sha256=authorization_sha256,
            packet=authorization,
            source_database=args.database,
        )
    elif (
        resume_authorization_path is not None
        and resume_authorization_sha256 is not None
    ):
        authorization_kind = "existing_budget_resume"
        authorization = _load_existing_budget_resume_authorization(
            resume_authorization_path,
            expected_path=args.report_dir
            / f"{args.run_id}-existing-budget-resume-authorization.json",
            expected_sha256=resume_authorization_sha256,
            run_id=args.run_id,
            release_manifest_sha256=bundle.manifest_sha256,
            probe_report_sha256=args.expected_probe_sha256,
            source_database=args.database,
            expected_lanes=expected_lanes,
        )
        if (
            args.max_provider_requests_total
            != authorization["max_provider_requests_total"]
        ):
            raise BackfillCliError(
                "existing_budget_resume_authorization_invalid"
            )
        _assert_existing_budget_resume_checkpoint_state(
            store,
            run_id=args.run_id,
            packet=authorization,
        )

    report = _load_approved_probe(
        args.probe_report,
        expected_path=args.report_dir / f"{args.run_id}-probe.json",
        expected_sha256=args.expected_probe_sha256,
        run_id=args.run_id,
        release_manifest_sha256=bundle.manifest_sha256,
        allow_historical_release_manifest=not initial_collection,
    )
    if initial_collection:
        _assert_probe_staging_state(store, run_id=args.run_id, report=report)
    else:
        if authorization is None or authorization_kind is None:
            raise AssertionError("continuation authorization invariant")
        store.migrate()
        updated_at_utc = datetime.now(timezone.utc)
        if authorization_kind == "budget_extension":
            if authorization_sha256 is None:
                raise AssertionError("budget extension SHA invariant")
            store.extend_full_collection_budget(
                args.run_id,
                expected_provider_request_count=cast(
                    int, authorization["expected_provider_request_count"]
                ),
                expected_max_provider_requests=cast(
                    int, authorization["expected_max_provider_requests"]
                ),
                new_max_provider_requests_total=cast(
                    int, authorization["new_max_provider_requests_total"]
                ),
                discovery_request_ceiling=cast(
                    int, authorization["discovery_request_ceiling"]
                ),
                lane_page_ceilings_sha256=cast(
                    str, authorization["lane_page_ceilings_sha256"]
                ),
                include_subreddit_sweep=cast(
                    bool, authorization["include_subreddit_sweep"]
                ),
                required_lanes_sha256=cast(
                    str, authorization["required_lanes_sha256"]
                ),
                authorization_sha256=authorization_sha256,
                updated_at_utc=updated_at_utc,
            )
            if not store.hydration_resume_recorded(
                args.run_id, authorization_sha256
            ):
                store.resume_budget_exhausted_hydration(
                    args.run_id,
                    authorization_sha256=authorization_sha256,
                    updated_at_utc=updated_at_utc,
                )
        else:
            if resume_authorization_sha256 is None:
                raise AssertionError("existing budget resume SHA invariant")
            store.record_existing_budget_resume_authorization(
                args.run_id,
                authorization_sha256=resume_authorization_sha256,
                expected_source_database_sha256=cast(
                    str, authorization["expected_source_database_sha256"]
                ),
                expected_provider_request_count=cast(
                    int, authorization["expected_provider_request_count"]
                ),
                max_provider_requests=cast(
                    int, authorization["max_provider_requests_total"]
                ),
                discovery_request_ceiling=cast(
                    int, authorization["discovery_request_ceiling"]
                ),
                lane_page_ceilings_sha256=cast(
                    str, authorization["lane_page_ceilings_sha256"]
                ),
                candidate_state_sha256=cast(
                    str, authorization["candidate_state_sha256"]
                ),
                include_subreddit_sweep=cast(
                    bool, authorization["include_subreddit_sweep"]
                ),
                required_lanes_sha256=cast(
                    str, authorization["required_lanes_sha256"]
                ),
                applied_at_utc=updated_at_utc,
            )

    store.freeze_full_collection_contract(
        args.run_id,
        expected_probe_request_count=cast(
            int, report["provider_request_count_after"]
        ),
        max_provider_requests_total=args.max_provider_requests_total,
        include_subreddit_sweep=include_sweep,
        required_lanes_sha256=lane_sha256,
        updated_at_utc=datetime.now(timezone.utc),
    )
    row = _manifest_row(store, args.run_id)
    window = _window_from_manifest(row)
    archive = PrivateRawArchive(args.raw_archive_dir)
    provider_request_count_before = store.provider_request_count(args.run_id)
    client = TikHubClient(
        api_key=api_key,
        base_url=os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.io"),
    )
    discovery_executor = TikHubRequestExecutor(
        client,
        store,
        args.run_id,
        sleep=time.sleep,
        now=lambda: datetime.now(timezone.utc),
        request_ceiling=(
            None
            if authorization is None
            else cast(int, authorization["discovery_request_ceiling"])
        ),
    )
    discoverer = TikHubBackfillDiscoverer(
        discovery_executor,
        store,
        archive,
        args.run_id,
        now=lambda: datetime.now(timezone.utc),
    )
    if authorization is None:
        lane_results = [
            discoverer.run_dynamic_search(term, window)
            for term in DEFAULT_TIKHUB_SEARCH_TERMS
        ]
        if include_sweep:
            lane_results.extend(
                discoverer.run_subreddit_feed(subreddit, window)
                for subreddit in DEFAULT_REVIEWED_SUBREDDITS
            )
    else:
        lane_results = _run_discovery_round_robin(
            discoverer,
            store,
            run_id=args.run_id,
            window=window,
            lane_page_ceilings=cast(
                list[dict[str, object]], authorization["lane_page_ceilings"]
            ),
        )
    provider_request_count_after_discovery = store.provider_request_count(
        args.run_id
    )
    outcomes = store.load_hydration_outcomes(args.run_id)
    post_ids = tuple(str(outcome["post_id"]) for outcome in outcomes)
    hydration_executor = (
        discovery_executor
        if authorization is None
        else TikHubRequestExecutor(
            client,
            store,
            args.run_id,
            sleep=time.sleep,
            now=lambda: datetime.now(timezone.utc),
        )
    )
    hydration = TikHubDetailHydrator(
        hydration_executor,
        store,
        archive,
        args.run_id,
        now=lambda: datetime.now(timezone.utc),
    ).hydrate(
        post_ids=post_ids,
        window=window,
        comment_cursor_contract=bundle.comment_cursor_contract,
    )
    complete = all(result.status == "complete" for result in lane_results) and (
        hydration.status == "complete"
    )
    status = "success" if complete else "partial"
    store.set_backfill_status(args.run_id, status, datetime.now(timezone.utc))
    provider_request_count = store.provider_request_count(args.run_id)
    payload: dict[str, object] = {
        "schema_version": "backfill_collect_v1",
        "run_id": args.run_id,
        "status": status,
        "stop_reason": _collection_stop_reason(lane_results, hydration),
        "max_provider_requests_total": args.max_provider_requests_total,
        "provider_request_count": provider_request_count,
        "include_subreddit_sweep": include_sweep,
        "required_lanes_sha256": lane_sha256,
        "lane_results": [asdict(result) for result in lane_results],
        "hydration": asdict(hydration),
        "provider_call": store.provider_call_evidence(args.run_id),
        "live_send": False,
    }
    if authorization is not None:
        payload.update(
            {
                "schema_version": "backfill_collect_v2",
                "provider_request_count_before": provider_request_count_before,
                "provider_request_count_after_discovery": (
                    provider_request_count_after_discovery
                ),
                "discovery_provider_requests_used": (
                    provider_request_count_after_discovery
                    - provider_request_count_before
                ),
                "hydration_provider_requests_used": (
                    provider_request_count
                    - provider_request_count_after_discovery
                ),
                "discovery_request_ceiling": authorization[
                    "discovery_request_ceiling"
                ],
                "hydration_request_reserve": authorization[
                    "hydration_request_reserve"
                ],
                "lane_page_ceilings_sha256": authorization[
                    "lane_page_ceilings_sha256"
                ],
            }
        )
        if authorization_kind == "budget_extension":
            payload["budget_extension_authorization_sha256"] = (
                authorization_sha256
            )
        else:
            payload["schema_version"] = "backfill_collect_v3"
            payload["existing_budget_resume_authorization_sha256"] = (
                resume_authorization_sha256
            )
    _publish_evidence_snapshot(
        args.report_dir,
        run_id=args.run_id,
        phase="collect",
        payload=payload,
        sequence=provider_request_count,
    )
    return (0 if complete else 1), payload


@dataclass(frozen=True)
class _PinnedFileDigest:
    sha256: str
    device: int
    inode: int
    size: int


def _pinned_regular_file_digest(
    path: Path, *, reason: str
) -> tuple[Path, _PinnedFileDigest]:
    descriptor: int | None = None
    lexical = Path(os.path.abspath(os.fspath(path)))
    try:
        if _path_has_existing_symlink_component(lexical):
            raise OSError
        descriptor = os.open(
            lexical, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError
        digest = sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        lexical_state = lexical.lstat()
        identity = (before.st_dev, before.st_ino, before.st_size)
        if (
            identity
            != (after.st_dev, after.st_ino, after.st_size)
            or identity
            != (
                lexical_state.st_dev,
                lexical_state.st_ino,
                lexical_state.st_size,
            )
            or not stat.S_ISREG(lexical_state.st_mode)
            or lexical_state.st_nlink != 1
        ):
            raise OSError
        return lexical.resolve(strict=True), _PinnedFileDigest(
            sha256=digest.hexdigest(),
            device=before.st_dev,
            inode=before.st_ino,
            size=before.st_size,
        )
    except (OSError, ValueError):
        raise BackfillCliError(reason) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _canonical_reindex_output_path(path: Path, *, reason: str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(path)))
    try:
        if _path_has_existing_symlink_component(lexical.parent):
            raise OSError
        parent = lexical.parent.resolve(strict=True)
        state = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(state.st_mode):
            raise OSError
        canonical = parent / lexical.name
        if canonical.parent != parent:
            raise OSError
        return canonical
    except (OSError, ValueError):
        raise BackfillCliError(reason) from None


def _sqlite_path_names(path: Path) -> tuple[Path, ...]:
    return tuple(
        Path(str(path) + suffix)
        for suffix in ("", "-wal", "-shm", "-journal")
    )


def _reindex_target_has_residue(path: Path) -> bool:
    try:
        return any(os.path.lexists(value) for value in _sqlite_path_names(path))
    except OSError:
        raise BackfillCliError("reindex_target_state_unreadable") from None


def _sqlite_sidecars_present(path: Path) -> bool:
    try:
        return any(os.path.lexists(value) for value in _sqlite_path_names(path)[1:])
    except OSError:
        raise BackfillCliError("reindex_target_state_unreadable") from None


def _remove_pinned_reindex_report(
    path: Path,
    pinned: _PinnedFileDigest,
    *,
    expected_sha256: str,
) -> None:
    parent_fd: int | None = None
    descriptor: int | None = None
    lexical = Path(os.path.abspath(os.fspath(path)))
    try:
        if _path_has_existing_symlink_component(lexical.parent):
            raise OSError
        parent = lexical.parent.resolve(strict=True)
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptor = os.open(
            lexical.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        expected_identity = (pinned.device, pinned.inode, pinned.size)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (before.st_dev, before.st_ino, before.st_size)
            != expected_identity
        ):
            raise OSError
        digest = sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        entry = os.stat(
            lexical.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            digest.hexdigest() != expected_sha256
            or pinned.sha256 != expected_sha256
            or not stat.S_ISREG(entry.st_mode)
            or entry.st_nlink != 1
            or (entry.st_dev, entry.st_ino, entry.st_size)
            != expected_identity
        ):
            raise OSError
        os.unlink(lexical.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        try:
            os.stat(
                lexical.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        raise OSError
    except (OSError, ValueError):
        raise BackfillCliError("reindex_report_cleanup_failed") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_fd is not None:
            os.close(parent_fd)


def _best_effort_remove_expected_reindex_report(
    path: Path, *, expected_sha256: str
) -> bool:
    try:
        if not os.path.lexists(path):
            return True
        _, pinned = _pinned_regular_file_digest(
            path, reason="reindex_report_cleanup_failed"
        )
        if pinned.sha256 != expected_sha256:
            return False
        _remove_pinned_reindex_report(
            path,
            pinned,
            expected_sha256=expected_sha256,
        )
        return not os.path.lexists(path)
    except (BackfillCliError, OSError):
        return False


def _postlibrary_target_may_have_residue(path: Path) -> bool:
    try:
        return _reindex_target_has_residue(path)
    except BackfillCliError:
        return True


def _admit_reindex_paths(
    args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path, _PinnedFileDigest]:
    if not _is_sha256(args.expected_source_database_sha256):
        raise BackfillCliError(
            "expected_source_database_sha256_invalid", status="blocked"
        )
    source, source_pin = _pinned_regular_file_digest(
        args.source_database, reason="reindex_source_database_invalid"
    )
    if not hmac.compare_digest(
        source_pin.sha256, args.expected_source_database_sha256
    ):
        raise BackfillCliError(
            "reindex_source_database_sha256_mismatch", status="blocked"
        )
    if any(os.path.lexists(path) for path in _sqlite_path_names(source)[1:]):
        raise BackfillCliError(
            "reindex_source_database_sidecar_present", status="blocked"
        )

    raw_lexical = Path(os.path.abspath(os.fspath(args.raw_archive_dir)))
    try:
        if _path_has_existing_symlink_component(raw_lexical):
            raise OSError
        raw_archive = raw_lexical.resolve(strict=True)
        raw_state = os.stat(raw_archive, follow_symlinks=False)
        if not stat.S_ISDIR(raw_state.st_mode):
            raise OSError
    except (OSError, ValueError):
        raise BackfillCliError("reindex_raw_archive_invalid", status="blocked") from None

    target = _canonical_reindex_output_path(
        args.reindexed_database, reason="reindex_target_path_invalid"
    )
    report = _canonical_reindex_output_path(
        args.report, reason="reindex_report_path_invalid"
    )
    if _reindex_target_has_residue(target):
        raise BackfillCliError(
            "reindex_target_exists_needs_review", status="blocked"
        )
    if os.path.lexists(report):
        raise BackfillCliError(
            "reindex_report_exists_needs_review", status="blocked"
        )

    run_root = source.parent
    try:
        raw_archive.relative_to(run_root)
        target.parent.relative_to(run_root)
        report.parent.relative_to(run_root)
    except ValueError:
        raise BackfillCliError("reindex_path_outside_run_root", status="blocked") from None
    if raw_archive == run_root:
        raise BackfillCliError("reindex_paths_overlap", status="blocked")
    try:
        source.relative_to(raw_archive)
    except ValueError:
        pass
    else:
        raise BackfillCliError("reindex_paths_overlap", status="blocked")
    try:
        target.relative_to(raw_archive)
    except ValueError:
        pass
    else:
        raise BackfillCliError("reindex_paths_overlap", status="blocked")
    try:
        report.relative_to(raw_archive)
    except ValueError:
        pass
    else:
        raise BackfillCliError("reindex_paths_overlap", status="blocked")
    source_namespace = set(_sqlite_path_names(source))
    target_namespace = set(_sqlite_path_names(target))
    if (
        source_namespace.intersection(target_namespace)
        or report in source_namespace
        or report in target_namespace
        or len({source, target, report}) != 3
    ):
        raise BackfillCliError("reindex_paths_overlap", status="blocked")
    return source, raw_archive, target, report, source_pin


def _validate_reindex_result(
    result: object,
    *,
    expected_source_sha256: str,
    target: Path,
) -> dict[str, object]:
    payload = _exact_dict(
        result,
        REINDEX_DISCOVERY_RESULT_KEYS,
        reason="reindex_result_contract_invalid",
    )
    stop_reason = payload["stop_reason"]
    source_max = payload["source_max_provider_requests"]
    source_count = payload["source_provider_request_count"]
    count_keys = (
        "discovery_artifact_count",
        "discovery_occurrence_count",
        "candidate_count",
    )
    common_valid = (
        payload["schema_version"] == "backfill_discovery_reindex_v1"
        and payload["provider_attempt_made"] is False
        and payload["live_send"] is False
        and payload["source_db_sha256"] == expected_source_sha256
        and _is_sha256(payload["raw_inventory_sha256"])
        and _is_sha256(payload["source_provider_ledger_sha256"])
        and type(stop_reason) is str
        and _SAFE_REASON_PATTERN.fullmatch(cast(str, stop_reason)) is not None
        and type(source_max) is int
        and cast(int, source_max) >= 0
        and type(source_count) is int
        and 0 <= cast(int, source_count) <= cast(int, source_max)
        and all(
            type(payload[key]) is int and cast(int, payload[key]) >= 0
            for key in count_keys
        )
    )
    if not common_valid:
        raise BackfillCliError("reindex_result_contract_invalid")

    if payload["status"] == "complete":
        if _sqlite_sidecars_present(target):
            raise BackfillCliError("reindex_result_contract_invalid")
        _, target_pin = _pinned_regular_file_digest(
            target, reason="reindex_result_contract_invalid"
        )
        target_max = payload["target_max_provider_requests"]
        target_count = payload["target_provider_request_count"]
        valid = (
            stop_reason == "reindex_complete"
            and _is_sha256(payload["target_db_sha256"])
            and payload["target_db_sha256"] == target_pin.sha256
            and type(target_max) is int
            and type(target_count) is int
            and target_max == source_max
            and target_count == source_count
            and payload["target_provider_ledger_sha256"]
            == payload["source_provider_ledger_sha256"]
        )
    elif payload["status"] == "failed":
        valid = (
            stop_reason != "reindex_complete"
            and payload["target_db_sha256"] is None
            and payload["target_max_provider_requests"] is None
            and payload["target_provider_request_count"] is None
            and payload["target_provider_ledger_sha256"] is None
            and all(payload[key] == 0 for key in count_keys)
            and not _reindex_target_has_residue(target)
        )
    else:
        valid = False
    if not valid:
        raise BackfillCliError("reindex_result_contract_invalid")
    return payload


def run_reindex_discovery(
    args: argparse.Namespace,
) -> tuple[int, dict[str, object]]:
    source, raw_archive, target, report, source_pin = _admit_reindex_paths(args)
    bundle = load_release_bundle(
        args.release_manifest,
        baseline_path=CODE_ROOT / SEED_BASELINE_RELATIVE_PATH,
        comment_cursor_path=CODE_ROOT / COMMENT_CURSOR_RELATIVE_PATH,
        run_id=args.run_id,
        expected_manifest_sha256=args.expected_release_manifest_sha256,
    )
    try:
        result = reindex_discovery_from_archive(
            BackfillStore(source),
            PrivateRawArchive(raw_archive, read_only=True),
            target_db=target,
            run_id=args.run_id,
            expected_source_db_sha256=source_pin.sha256,
        )
    except ReplayPublicationError:
        reason = (
            "reindex_target_committed_needs_review"
            if _postlibrary_target_may_have_residue(target)
            else "reindex_target_exists_needs_review"
        )
        raise BackfillCliError(reason) from None
    except ValueError:
        if _postlibrary_target_may_have_residue(target):
            raise BackfillCliError(
                "reindex_target_committed_needs_review"
            ) from None
        try:
            _, current_source_pin = _pinned_regular_file_digest(
                source, reason="reindex_source_database_changed"
            )
        except BackfillCliError:
            raise
        reason = (
            "reindex_source_database_changed"
            if current_source_pin != source_pin
            else "reindex_inputs_invalid"
        )
        raise BackfillCliError(reason) from None
    except Exception:
        if _postlibrary_target_may_have_residue(target):
            raise BackfillCliError(
                "reindex_target_committed_needs_review"
            ) from None
        raise

    expected_report_sha256: str | None = None
    try:
        checked = _validate_reindex_result(
            result,
            expected_source_sha256=source_pin.sha256,
            target=target,
        )
        target_pin_before_report: _PinnedFileDigest | None = None
        if checked["status"] == "complete":
            _, target_pin_before_report = _pinned_regular_file_digest(
                target, reason="reindex_result_contract_invalid"
            )
            if target_pin_before_report.sha256 != checked["target_db_sha256"]:
                raise BackfillCliError("reindex_result_contract_invalid")
        _, current_source_pin = _pinned_regular_file_digest(
            source, reason="reindex_source_database_changed"
        )
        if current_source_pin != source_pin:
            raise BackfillCliError("reindex_source_database_changed")
        envelope: dict[str, object] = {
            "schema_version": "backfill_discovery_reindex_cli_envelope_v1",
            "run_id": args.run_id,
            "release_manifest_sha256": bundle.manifest_sha256,
            "expected_source_database_sha256": source_pin.sha256,
            "reindex": checked,
        }
        expected_report_sha256 = sha256(
            _canonical_json_bytes(envelope, newline=True)
        ).hexdigest()
        _publish_json(report, envelope)
        _, report_pin = _pinned_regular_file_digest(
            report, reason="reindex_report_state_invalid"
        )
        if report_pin.sha256 != expected_report_sha256:
            raise BackfillCliError("reindex_report_state_invalid")
        _, final_source_pin = _pinned_regular_file_digest(
            source, reason="reindex_source_database_changed"
        )
        if final_source_pin != source_pin:
            raise BackfillCliError("reindex_source_database_changed")
        if checked["status"] == "complete":
            if _sqlite_sidecars_present(target):
                raise BackfillCliError("reindex_result_contract_invalid")
            _, target_pin_after_report = _pinned_regular_file_digest(
                target, reason="reindex_result_contract_invalid"
            )
            if (
                target_pin_before_report is None
                or target_pin_after_report != target_pin_before_report
                or target_pin_after_report.sha256
                != checked["target_db_sha256"]
                or _sqlite_sidecars_present(target)
            ):
                raise BackfillCliError("reindex_result_contract_invalid")
        elif _postlibrary_target_may_have_residue(target):
            raise BackfillCliError("reindex_result_contract_invalid")
    except BackfillCliError:
        if expected_report_sha256 is not None:
            _best_effort_remove_expected_reindex_report(
                report, expected_sha256=expected_report_sha256
            )
        if _postlibrary_target_may_have_residue(target):
            raise BackfillCliError(
                "reindex_target_committed_needs_review"
            ) from None
        raise
    return (0 if checked["status"] == "complete" else 1), envelope


def _validate_collection_recovery_result(
    result: object,
    *,
    run_id: str,
    expected_source_sha256: str,
    target: Path,
) -> dict[str, object]:
    payload = _exact_dict(
        result,
        COLLECTION_RECOVERY_RESULT_KEYS,
        reason="collection_recovery_result_contract_invalid",
    )
    stop_reason = payload["stop_reason"]
    source_max = payload["source_max_provider_requests"]
    source_count = payload["source_provider_request_count"]
    count_keys = (
        "discovery_artifact_count",
        "discovery_occurrence_count",
        "candidate_count",
        "new_candidate_count",
        "recovered_discovery_lane_count",
        "reset_candidate_count",
        "reset_batch_count",
        "reset_comment_checkpoint_count",
        "raw_persisted_batch_count",
        "prepared_batch_count",
        "archived_hydrated_candidate_count",
    )
    common_valid = bool(
        payload["schema_version"] == "backfill_collection_recovery_v1"
        and payload["run_id"] == run_id
        and payload["provider_call"] is False
        and payload["provider_attempt_made"] is False
        and payload["live_send"] is False
        and payload["source_db_sha256"] == expected_source_sha256
        and _is_sha256(payload["raw_inventory_sha256"])
        and _is_sha256(payload["source_provider_ledger_sha256"])
        and type(stop_reason) is str
        and _SAFE_REASON_PATTERN.fullmatch(cast(str, stop_reason)) is not None
        and type(source_max) is int
        and cast(int, source_max) >= 0
        and type(source_count) is int
        and 0 <= cast(int, source_count) <= cast(int, source_max)
        and all(
            type(payload[key]) is int and cast(int, payload[key]) >= 0
            for key in count_keys
        )
    )
    if not common_valid:
        raise BackfillCliError("collection_recovery_result_contract_invalid")

    if payload["status"] == "complete":
        if _sqlite_sidecars_present(target):
            raise BackfillCliError(
                "collection_recovery_result_contract_invalid"
            )
        _, target_pin = _pinned_regular_file_digest(
            target, reason="collection_recovery_result_contract_invalid"
        )
        valid = bool(
            stop_reason == "collection_recovery_complete"
            and payload["database_write"] == "recovery_target_only"
            and _is_sha256(payload["target_db_sha256"])
            and payload["target_db_sha256"] == target_pin.sha256
            and payload["target_max_provider_requests"] == source_max
            and payload["target_provider_request_count"] == source_count
            and payload["target_provider_ledger_sha256"]
            == payload["source_provider_ledger_sha256"]
            and cast(int, payload["recovered_discovery_lane_count"]) > 0
            and cast(int, payload["reset_candidate_count"]) > 0
            and cast(int, payload["reset_batch_count"]) > 0
            and cast(int, payload["reset_comment_checkpoint_count"]) > 0
            and cast(int, payload["archived_hydrated_candidate_count"]) > 0
            and cast(int, payload["candidate_count"])
            >= cast(int, payload["reset_candidate_count"])
            and cast(int, payload["raw_persisted_batch_count"])
            + cast(int, payload["prepared_batch_count"])
            == cast(int, payload["reset_batch_count"])
        )
    elif payload["status"] == "failed":
        valid = bool(
            stop_reason != "collection_recovery_complete"
            and payload["database_write"] is False
            and payload["target_db_sha256"] is None
            and payload["target_max_provider_requests"] is None
            and payload["target_provider_request_count"] is None
            and payload["target_provider_ledger_sha256"] is None
            and all(payload[key] == 0 for key in count_keys)
            and not _reindex_target_has_residue(target)
        )
    else:
        valid = False
    if not valid:
        raise BackfillCliError("collection_recovery_result_contract_invalid")
    return payload


def run_recover_collection(
    args: argparse.Namespace,
) -> tuple[int, dict[str, object]]:
    source, raw_archive, target, report, source_pin = _admit_reindex_paths(args)
    try:
        recovered_at_utc = datetime.fromisoformat(args.recovered_at_utc)
    except (TypeError, ValueError):
        raise BackfillCliError("collection_recovery_timestamp_invalid") from None
    if (
        recovered_at_utc.tzinfo is None
        or recovered_at_utc.utcoffset() is None
    ):
        raise BackfillCliError("collection_recovery_timestamp_invalid")
    bundle = load_release_bundle(
        args.release_manifest,
        baseline_path=CODE_ROOT / SEED_BASELINE_RELATIVE_PATH,
        comment_cursor_path=CODE_ROOT / COMMENT_CURSOR_RELATIVE_PATH,
        run_id=args.run_id,
        expected_manifest_sha256=args.expected_release_manifest_sha256,
    )
    try:
        result = recover_collection_from_archive(
            BackfillStore(source),
            PrivateRawArchive(raw_archive, read_only=True),
            target_db=target,
            run_id=args.run_id,
            expected_source_db_sha256=source_pin.sha256,
            recovered_at_utc=recovered_at_utc,
        )
    except ReplayPublicationError:
        reason = (
            "collection_recovery_target_committed_needs_review"
            if _postlibrary_target_may_have_residue(target)
            else "collection_recovery_target_exists_needs_review"
        )
        raise BackfillCliError(reason) from None
    except ValueError:
        if _postlibrary_target_may_have_residue(target):
            raise BackfillCliError(
                "collection_recovery_target_committed_needs_review"
            ) from None
        raise BackfillCliError("collection_recovery_inputs_invalid") from None

    expected_report_sha256: str | None = None
    try:
        checked = _validate_collection_recovery_result(
            result,
            run_id=args.run_id,
            expected_source_sha256=source_pin.sha256,
            target=target,
        )
        target_pin_before_report: _PinnedFileDigest | None = None
        if checked["status"] == "complete":
            _, target_pin_before_report = _pinned_regular_file_digest(
                target, reason="collection_recovery_result_contract_invalid"
            )
        _, current_source_pin = _pinned_regular_file_digest(
            source, reason="collection_recovery_source_database_changed"
        )
        if current_source_pin != source_pin:
            raise BackfillCliError(
                "collection_recovery_source_database_changed"
            )
        envelope: dict[str, object] = {
            "schema_version": "backfill_collection_recovery_cli_envelope_v1",
            "run_id": args.run_id,
            "release_manifest_sha256": bundle.manifest_sha256,
            "expected_source_database_sha256": source_pin.sha256,
            "recovered_at_utc": recovered_at_utc.isoformat(),
            "recovery": checked,
        }
        expected_report_sha256 = sha256(
            _canonical_json_bytes(envelope, newline=True)
        ).hexdigest()
        _publish_json(report, envelope)
        _, report_pin = _pinned_regular_file_digest(
            report, reason="collection_recovery_report_state_invalid"
        )
        if report_pin.sha256 != expected_report_sha256:
            raise BackfillCliError(
                "collection_recovery_report_state_invalid"
            )
        _, final_source_pin = _pinned_regular_file_digest(
            source, reason="collection_recovery_source_database_changed"
        )
        if final_source_pin != source_pin:
            raise BackfillCliError(
                "collection_recovery_source_database_changed"
            )
        if checked["status"] == "complete":
            if _sqlite_sidecars_present(target):
                raise BackfillCliError(
                    "collection_recovery_result_contract_invalid"
                )
            _, target_pin_after_report = _pinned_regular_file_digest(
                target, reason="collection_recovery_result_contract_invalid"
            )
            if (
                target_pin_before_report is None
                or target_pin_after_report != target_pin_before_report
                or target_pin_after_report.sha256
                != checked["target_db_sha256"]
            ):
                raise BackfillCliError(
                    "collection_recovery_result_contract_invalid"
                )
        elif _postlibrary_target_may_have_residue(target):
            raise BackfillCliError(
                "collection_recovery_result_contract_invalid"
            )
    except BackfillCliError:
        if expected_report_sha256 is not None:
            _best_effort_remove_expected_reindex_report(
                report, expected_sha256=expected_report_sha256
            )
        if _postlibrary_target_may_have_residue(target):
            raise BackfillCliError(
                "collection_recovery_target_committed_needs_review"
            ) from None
        raise
    return (0 if checked["status"] == "complete" else 1), envelope


def run_replay(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if args.source_database.is_symlink() or not args.source_database.is_file():
        raise BackfillCliError("replay_source_unreadable")
    if args.replay_database.exists() or args.replay_database.is_symlink():
        raise BackfillCliError("replay_target_exists_needs_review")
    store = BackfillStore(args.source_database)
    archive = PrivateRawArchive(args.raw_archive_dir, read_only=True)
    result = replay_from_archive(
        store,
        archive,
        target_db=args.replay_database,
        run_id=args.run_id,
    )
    if args.report is not None:
        _publish_json(args.report, result)
    return (0 if result.get("status") == "complete" else 1), result


def run_validate(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    if args.scope == "full" and (
        args.replay_database is None
        or args.run_root is None
        or args.expected_release_manifest_sha256 is None
    ):
        raise BackfillCliError("full_validation_inputs_required")
    if args.database.is_symlink() or not args.database.is_file():
        raise BackfillCliError("validation_source_unreadable")
    if (
        args.scope == "full"
        and (
            args.replay_database.is_symlink()
            or not args.replay_database.is_file()
            or args.run_root.is_symlink()
            or not args.run_root.is_dir()
        )
    ):
        raise BackfillCliError("full_validation_inputs_invalid")
    bundle = load_release_bundle(
        args.release_manifest,
        baseline_path=args.seed_baseline,
        comment_cursor_path=CODE_ROOT / COMMENT_CURSOR_RELATIVE_PATH,
        run_id=args.run_id,
        expected_manifest_sha256=(
            args.expected_release_manifest_sha256 if args.scope == "full" else None
        ),
    )
    store = BackfillStore(args.database)
    archive = PrivateRawArchive(args.raw_archive_dir, read_only=True)
    result = validate_backfill(
        store,
        archive,
        run_id=args.run_id,
        seed_baseline=bundle.seed_baseline,
        scope=args.scope,
        replay_db=args.replay_database,
        run_root=args.run_root,
    )
    if not isinstance(result, dict) or set(result) != set(VALIDATION_RESULT_KEYS):
        raise BackfillCliError("validation_result_contract_invalid")
    if (
        result.get("schema_version") != "backfill_validation_v1"
        or result.get("run_id") != args.run_id
        or result.get("scope") != args.scope
        or result.get("provider_attempt_made") is not False
        or result.get("live_send") is not False
    ):
        raise BackfillCliError("validation_result_contract_invalid")
    envelope: dict[str, object] = {
        "schema_version": "backfill_validation_cli_envelope_v1",
        "run_id": args.run_id,
        "scope": args.scope,
        "release_manifest_sha256": bundle.manifest_sha256,
        "validation": result,
    }
    _publish_json(args.report, envelope)
    return (0 if result.get("status") == "accepted" else 1), envelope


def _load_json_file_with_sha(
    path: Path,
    *,
    reason: str,
    expected_sha256: str | None = None,
) -> tuple[dict[str, object], str]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise BackfillCliError(f"{reason}_unreadable") from None
    actual_sha256 = sha256(raw).hexdigest()
    if expected_sha256 is not None and (
        not _is_sha256(expected_sha256)
        or not hmac.compare_digest(actual_sha256, expected_sha256)
    ):
        raise BackfillCliError(f"{reason}_sha256_mismatch")
    value = _strict_json_bytes(raw, reason=f"{reason}_invalid")
    if not isinstance(value, dict):
        raise BackfillCliError(f"{reason}_invalid")
    return cast(dict[str, object], value), actual_sha256


def _acceptance_counts(
    value: object, keys: tuple[str, ...]
) -> dict[str, int]:
    payload = _exact_dict(
        value, keys, reason="acceptance_report_invalid"
    )
    result: dict[str, int] = {}
    for key in keys:
        count = payload[key]
        if type(count) is not int or count < 0:
            raise BackfillCliError("acceptance_report_invalid")
        result[key] = count
    return result


def _acceptance_fingerprints(value: object) -> dict[str, object]:
    payload = _exact_dict(
        value,
        _VALIDATION_FINGERPRINT_TABLES,
        reason="acceptance_report_invalid",
    )
    result: dict[str, object] = {}
    for table in _VALIDATION_FINGERPRINT_TABLES:
        keys = (
            "row_count",
            "id_set_sha256",
            "canonical_rows_sha256",
        )
        if table in {"backfill_raw_artifacts", "raw_captures"}:
            keys += ("raw_payload_hash_set_sha256",)
        fingerprint = _exact_dict(
            payload[table], keys, reason="acceptance_report_invalid"
        )
        if (
            type(fingerprint["row_count"]) is not int
            or fingerprint["row_count"] < 0
            or any(not _is_sha256(fingerprint[key]) for key in keys[1:])
        ):
            raise BackfillCliError("acceptance_report_invalid")
        result[table] = fingerprint
    return result


def _validate_acceptance_result(validation: dict[str, object]) -> None:
    counts = _acceptance_counts(validation["counts"], _VALIDATION_COUNT_KEYS)
    candidate_counts = _acceptance_counts(
        validation["candidate_status_counts"], _VALIDATION_CANDIDATE_KEYS
    )
    occurrence_counts = _acceptance_counts(
        validation["occurrence_disposition_counts"],
        _VALIDATION_OCCURRENCE_KEYS,
    )
    if (
        counts["manifests"] != 1
        or counts["runs"] != 1
        or counts["seed_files"] != 55
        or counts["threads"] < 48
        or counts["comments"] < 1894
        or counts["analyses"] != counts["threads"] + counts["comments"]
        or counts["delivery_previews"] != 0
        or counts["provider_attempts"] < 1
        or sum(candidate_counts.values()) != counts["candidates"]
        or sum(occurrence_counts.values()) != counts["discovery_occurrences"]
        or occurrence_counts["invalid"] != 0
        or any(
            candidate_counts[key] != 0
            for key in ("pending", "failed", "budget_deferred")
        )
    ):
        raise BackfillCliError("acceptance_report_invalid")

    lanes = validation["required_lanes"]
    if not isinstance(lanes, list) or not lanes:
        raise BackfillCliError("acceptance_report_invalid")
    lane_identities: set[tuple[str, str]] = set()
    for value in lanes:
        lane = _exact_dict(
            value,
            ("lane_type", "lane_key_sha256", "status"),
            reason="acceptance_report_invalid",
        )
        identity = (lane["lane_type"], lane["lane_key_sha256"])
        if (
            type(identity[0]) is not str
            or identity[0] not in {"dynamic_search", "subreddit_feed"}
            or not _is_sha256(identity[1])
            or lane["status"] != "complete"
            or identity in lane_identities
        ):
            raise BackfillCliError("acceptance_report_invalid")
        lane_identities.add(cast(tuple[str, str], identity))
    if counts["checkpoints"] < len(lanes):
        raise BackfillCliError("acceptance_report_invalid")
    dynamic_lanes = [
        (
            "dynamic_search",
            sha256(term.encode("utf-8")).hexdigest(),
        )
        for term in DEFAULT_TIKHUB_SEARCH_TERMS
    ]
    subreddit_lanes = [
        (
            "subreddit_feed",
            sha256(subreddit.encode("utf-8")).hexdigest(),
        )
        for subreddit in DEFAULT_REVIEWED_SUBREDDITS
    ]
    lane_sequence = [
        (
            cast(str, lane["lane_type"]),
            cast(str, lane["lane_key_sha256"]),
        )
        for lane in cast(list[dict[str, object]], lanes)
    ]
    if lane_sequence not in (
        dynamic_lanes,
        dynamic_lanes + subreddit_lanes,
    ):
        raise BackfillCliError("acceptance_report_invalid")

    source_fingerprints = _acceptance_fingerprints(
        validation["source_fingerprints"]
    )
    replay_fingerprints = _acceptance_fingerprints(
        validation["replay_fingerprints"]
    )
    if source_fingerprints != replay_fingerprints:
        raise BackfillCliError("acceptance_report_invalid")
    count_names = {
        "runs": "runs",
        "backfill_raw_artifacts": "raw_artifacts",
        "raw_captures": "raw_captures",
        "reddit_threads": "threads",
        "reddit_comments": "comments",
        "analysis_results": "analyses",
    }
    for table, count_name in count_names.items():
        fingerprint = cast(dict[str, object], source_fingerprints[table])
        if fingerprint["row_count"] != counts[count_name]:
            raise BackfillCliError("acceptance_report_invalid")

    metadata = _exact_dict(
        validation["operational_metadata"],
        (
            "mode",
            "failure_only_metadata",
            "metadata_mirrored_count",
            "provider_attempts",
        ),
        reason="acceptance_report_invalid",
    )
    if metadata != {
        "mode": "constraints_checked",
        "failure_only_metadata": "none",
        "metadata_mirrored_count": 0,
        "provider_attempts": "source_only_not_replayed",
    }:
        raise BackfillCliError("acceptance_report_invalid")

    checks = validation["checks"]
    if not isinstance(checks, list) or not checks:
        raise BackfillCliError("acceptance_report_invalid")
    check_codes: set[str] = set()
    scalar_types = {str, int, bool, type(None)}
    for value in checks:
        check = _exact_dict(
            value,
            ("code", "ok", "actual", "expected"),
            reason="acceptance_report_invalid",
        )
        code = check["code"]
        if (
            type(code) is not str
            or not code
            or code in check_codes
            or check["ok"] is not True
            or type(check["actual"]) not in scalar_types
            or type(check["expected"]) not in scalar_types
        ):
            raise BackfillCliError("acceptance_report_invalid")
        check_codes.add(cast(str, code))
    if not _REQUIRED_ACCEPTANCE_CHECK_CODES.issubset(check_codes):
        raise BackfillCliError("acceptance_report_invalid")
    operational_check = next(
        cast(dict[str, object], value)
        for value in cast(list[dict[str, object]], checks)
        if value["code"] == "operational_accounting"
    )
    if (
        not _is_sha256(operational_check["actual"])
        or operational_check["actual"] != operational_check["expected"]
    ):
        raise BackfillCliError("acceptance_report_invalid")


def _load_acceptance(
    path: Path,
    *,
    run_id: str,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    envelope, _ = _load_json_file_with_sha(
        path, reason="acceptance_report", expected_sha256=expected_sha256
    )
    envelope = _exact_dict(
        envelope,
        (
            "schema_version",
            "run_id",
            "scope",
            "release_manifest_sha256",
            "validation",
        ),
        reason="acceptance_report_invalid",
    )
    validation = _exact_dict(
        envelope["validation"],
        VALIDATION_RESULT_KEYS,
        reason="acceptance_report_invalid",
    )
    valid = (
        envelope["schema_version"] == "backfill_validation_cli_envelope_v1"
        and envelope["run_id"] == run_id
        and envelope["scope"] == "full"
        and _is_sha256(envelope["release_manifest_sha256"])
        and validation["schema_version"] == "backfill_validation_v1"
        and validation["run_id"] == run_id
        and validation["scope"] == "full"
        and validation["status"] == "accepted"
        and validation["stop_reason"] == "full_validation_complete"
        and validation["replay_status"] == "equivalent"
        and validation["full_ready"] is True
        and validation["source_provider_call"] is True
        and validation["provider_attempt_made"] is False
        and validation["live_send"] is False
        and _is_sha256(validation["seed_baseline_sha256"])
        and type(validation["known_seed_partial_count"]) is int
        and validation["known_seed_partial_count"] == 3
        and _is_sha256(validation["known_seed_partial_post_ids_sha256"])
        and validation["run_root_scan"] == "clean"
        and validation["issues"] == []
    )
    if not valid:
        raise BackfillCliError("acceptance_report_invalid")
    _validate_acceptance_result(validation)
    return envelope


def _require_acceptance_matches_plan(
    acceptance: dict[str, object], plan: dict[str, object]
) -> None:
    validation = cast(dict[str, object], acceptance["validation"])
    if validation["source_fingerprints"] != plan.get("staging_fingerprints"):
        raise BackfillCliError(
            "acceptance_report_staging_fingerprint_mismatch"
        )


def _acceptance_check_map(
    validation: dict[str, object]
) -> dict[str, dict[str, object]]:
    return {
        cast(str, check["code"]): cast(dict[str, object], check)
        for check in cast(list[dict[str, object]], validation["checks"])
    }


def _require_acceptance_matches_staging(
    acceptance: dict[str, object],
    plan: dict[str, object],
    staging_database: Path,
    *,
    run_id: str,
) -> None:
    reason = "acceptance_report_staging_evidence_mismatch"
    expected_file_sha256 = plan.get("staging_sha256")
    if not _is_sha256(expected_file_sha256):
        raise BackfillCliError(reason)
    path = Path(staging_database)
    connection: sqlite3.Connection | None = None
    try:
        before = path.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or sha256(path.read_bytes()).hexdigest() != expected_file_sha256
        ):
            raise BackfillCliError(reason)
        identity = (before.st_dev, before.st_ino)
        resolved = path.resolve(strict=True)
        connection = sqlite3.connect(
            f"{resolved.as_uri()}?mode=ro", uri=True, timeout=2.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN")

        count_tables = {
            "manifests": "backfill_manifests",
            "runs": "runs",
            "seed_files": "backfill_seed_files",
            "raw_artifacts": "backfill_raw_artifacts",
            "raw_captures": "raw_captures",
            "threads": "reddit_threads",
            "comments": "reddit_comments",
            "analyses": "analysis_results",
            "delivery_previews": "delivery_previews",
            "provider_attempts": "backfill_provider_attempts",
            "checkpoints": "backfill_checkpoints",
            "candidates": "backfill_candidates",
            "discovery_occurrences": "backfill_discovery_occurrences",
            "detail_batches": "backfill_detail_batches",
            "detail_batch_members": "backfill_detail_batch_members",
        }
        current_counts = {
            name: int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)
                ).fetchone()[0]
            )
            for name, table in count_tables.items()
        }
        validation = cast(dict[str, object], acceptance["validation"])
        if current_counts != validation["counts"]:
            raise BackfillCliError(reason)

        candidate_counts = {
            key: 0 for key in _VALIDATION_CANDIDATE_KEYS
        }
        for row in connection.execute(
            "SELECT status, COUNT(*) AS count FROM backfill_candidates "
            "WHERE run_id=? GROUP BY status",
            (run_id,),
        ).fetchall():
            status_name = str(row["status"])
            if status_name not in candidate_counts:
                raise BackfillCliError(reason)
            candidate_counts[status_name] = int(row["count"])
        if candidate_counts != validation["candidate_status_counts"]:
            raise BackfillCliError(reason)

        occurrence_counts = {
            key: 0 for key in _VALIDATION_OCCURRENCE_KEYS
        }
        for row in connection.execute(
            "SELECT disposition, COUNT(*) AS count "
            "FROM backfill_discovery_occurrences "
            "WHERE run_id=? GROUP BY disposition",
            (run_id,),
        ).fetchall():
            disposition = str(row["disposition"])
            if disposition not in occurrence_counts:
                raise BackfillCliError(reason)
            occurrence_counts[disposition] = int(row["count"])
        if occurrence_counts != validation["occurrence_disposition_counts"]:
            raise BackfillCliError(reason)

        manifest = connection.execute(
            "SELECT search_terms_json, subreddits_json, include_subreddit_sweep, "
            "provider_request_count FROM backfill_manifests WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if manifest is None:
            raise BackfillCliError(reason)
        search_terms = _decode_manifest_sequence(
            manifest["search_terms_json"], reason=reason
        )
        subreddits = _decode_manifest_sequence(
            manifest["subreddits_json"], reason=reason
        )
        configured_lanes = required_lanes_snapshot(
            search_terms=search_terms,
            subreddits=subreddits,
            include_subreddit_sweep=bool(manifest["include_subreddit_sweep"]),
        )
        checkpoint_rows = {
            (str(row["lane_type"]), str(row["lane_key"])): str(row["status"])
            for row in connection.execute(
                "SELECT lane_type, lane_key, status FROM backfill_checkpoints "
                "WHERE run_id=? AND lane_type IN ('dynamic_search','subreddit_feed')",
                (run_id,),
            ).fetchall()
        }
        if set(checkpoint_rows) != set(configured_lanes):
            raise BackfillCliError(reason)
        current_lanes = [
            {
                "lane_type": lane_type,
                "lane_key_sha256": sha256(lane_key.encode("utf-8")).hexdigest(),
                "status": checkpoint_rows[(lane_type, lane_key)],
            }
            for lane_type, lane_key in configured_lanes
        ]
        if current_lanes != validation["required_lanes"]:
            raise BackfillCliError(reason)
        if int(manifest["provider_request_count"]) != current_counts["provider_attempts"]:
            raise BackfillCliError(reason)

        seed_outcomes = {
            outcome: 0
            for outcome in (
                "imported",
                "outside_window",
                "excluded",
                "duplicate",
                "parse_error",
            )
        }
        for row in connection.execute(
            "SELECT outcome, COUNT(*) AS count FROM backfill_seed_files "
            "WHERE run_id=? GROUP BY outcome",
            (run_id,),
        ).fetchall():
            outcome = str(row["outcome"])
            if outcome not in seed_outcomes:
                raise BackfillCliError(reason)
            seed_outcomes[outcome] = int(row["count"])
        if seed_outcomes != {
            "imported": 48,
            "outside_window": 7,
            "excluded": 0,
            "duplicate": 0,
            "parse_error": 0,
        }:
            raise BackfillCliError(reason)

        imported_post_ids = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT post_id FROM backfill_seed_files "
                "WHERE run_id=? AND outcome='imported' ORDER BY post_id",
                (run_id,),
            ).fetchall()
        )
        if len(imported_post_ids) != 48 or len(set(imported_post_ids)) != 48:
            raise BackfillCliError(reason)
        placeholders = ",".join("?" for _ in imported_post_ids)
        parameters: tuple[object, ...] = (run_id, *imported_post_ids)
        seed_threads = connection.execute(
            "SELECT post_id, coverage_grade FROM reddit_threads "
            f"WHERE run_id=? AND post_id IN ({placeholders}) ORDER BY post_id",
            parameters,
        ).fetchall()
        seed_comment_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM reddit_comments "
                f"WHERE run_id=? AND post_id IN ({placeholders})",
                parameters,
            ).fetchone()[0]
        )
        seed_analysis_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM analysis_results WHERE run_id=? AND "
                f"((source_type='post' AND source_id IN ({placeholders})) OR "
                "(source_type='comment' AND source_id IN "
                "(SELECT comment_id FROM reddit_comments "
                f"WHERE run_id=? AND post_id IN ({placeholders}))))",
                (run_id, *imported_post_ids, run_id, *imported_post_ids),
            ).fetchone()[0]
        )
        coverage_counts = {"full": 0, "partial": 0, "post_only": 0}
        for row in seed_threads:
            coverage = str(row["coverage_grade"])
            if coverage not in coverage_counts:
                raise BackfillCliError(reason)
            coverage_counts[coverage] += 1
        partial_ids = sorted(
            str(row["post_id"])
            for row in seed_threads
            if row["coverage_grade"] == "partial"
        )
        if (
            len(seed_threads) != 48
            or seed_comment_count != 1894
            or seed_analysis_count != 1942
            or coverage_counts != {"full": 45, "partial": 3, "post_only": 0}
            or _canonical_sha256(partial_ids)
            != validation["known_seed_partial_post_ids_sha256"]
        ):
            raise BackfillCliError(reason)

        inventory = sorted(
            [str(row["input_path_hash"]), str(row["payload_sha256"])]
            for row in connection.execute(
                "SELECT input_path_hash, payload_sha256 FROM backfill_seed_files "
                "WHERE run_id=?",
                (run_id,),
            ).fetchall()
        )
        actual_numeric = {
            "files_total": 55,
            "files_imported": 48,
            "files_outside_window": 7,
            "files_excluded": 0,
            "files_duplicate": 0,
            "parse_errors": 0,
            "threads": 48,
            "comments": 1894,
            "analyses": 1942,
            "coverage_full": 45,
            "coverage_partial": 3,
            "coverage_post_only": 0,
        }
        checks = _acceptance_check_map(validation)
        operational_snapshot = operational_snapshot_sha256(connection, run_id)
        operational_check = checks["operational_accounting"]
        if (
            operational_check["actual"] != operational_snapshot
            or operational_check["expected"] != operational_snapshot
        ):
            raise BackfillCliError(reason)
        for code, actual in (
            ("seed_numeric_contract", _canonical_sha256(actual_numeric)),
            ("seed_inventory", _canonical_sha256(inventory)),
            ("known_seed_partials", _canonical_sha256(partial_ids)),
        ):
            check = checks[code]
            if check["actual"] != actual or check["expected"] != actual:
                raise BackfillCliError(reason)
    except BackfillCliError:
        raise
    except (OSError, ValueError, TypeError, KeyError, sqlite3.DatabaseError):
        raise BackfillCliError(reason) from None
    finally:
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.DatabaseError:
                pass
            connection.close()
    try:
        after = path.lstat()
        if (
            stat.S_ISLNK(after.st_mode)
            or not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or (after.st_dev, after.st_ino) != identity
            or sha256(path.read_bytes()).hexdigest() != expected_file_sha256
        ):
            raise BackfillCliError(reason)
    except OSError:
        raise BackfillCliError(reason) from None


def run_merge_plan(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    acceptance = _load_acceptance(args.acceptance_report, run_id=args.run_id)
    plan = plan_insert_only_merge(
        args.staging_database,
        args.production_database,
        run_id=args.run_id,
    )
    if tuple(plan) != PLAN_KEYS:
        raise BackfillCliError("merge_plan_contract_invalid")
    _require_acceptance_matches_plan(acceptance, plan)
    _require_acceptance_matches_staging(
        acceptance, plan, args.staging_database, run_id=args.run_id
    )
    _publish_json(args.output, plan)
    return (0 if plan.get("status") == "ready" else 1), plan


def run_merge_production(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    _production_gate(args.authorize_production_write)
    acceptance = _load_acceptance(
        args.acceptance_report,
        run_id=args.run_id,
        expected_sha256=args.expected_acceptance_report_sha256,
    )
    reviewed_plan, _ = _load_json_file_with_sha(
        args.merge_plan,
        reason="merge_plan",
        expected_sha256=args.expected_merge_plan_sha256,
    )
    reviewed_plan = _exact_dict(
        reviewed_plan, PLAN_KEYS, reason="merge_plan_invalid"
    )
    if (
        reviewed_plan["schema_version"] != "backfill_insert_only_merge_plan_v1"
        or reviewed_plan["run_id"] != args.run_id
        or not _is_sha256(reviewed_plan["plan_sha256"])
        or not _is_sha256(args.expected_production_sha256)
        or reviewed_plan["production_sha256"] != args.expected_production_sha256
    ):
        raise BackfillCliError("merge_plan_invalid")
    semantic = dict(reviewed_plan)
    semantic_sha256 = semantic.pop("plan_sha256")
    if semantic_sha256 != _canonical_sha256(semantic):
        raise BackfillCliError("merge_plan_invalid")
    fresh_plan = plan_insert_only_merge(
        args.staging_database,
        args.production_database,
        run_id=args.run_id,
    )
    _require_acceptance_matches_plan(acceptance, fresh_plan)
    _require_acceptance_matches_staging(
        acceptance, fresh_plan, args.staging_database, run_id=args.run_id
    )
    if fresh_plan != reviewed_plan:
        raise BackfillCliError("merge_plan_drift")
    summary = merge_staging_insert_only(
        args.staging_database,
        args.production_database,
        run_id=args.run_id,
        backup_path=args.backup_database,
        expected_production_sha256=args.expected_production_sha256,
        expected_plan_sha256=cast(str, reviewed_plan["plan_sha256"]),
        authorized=True,
    )
    result = asdict(summary)
    try:
        _publish_json(args.output, result)
    except BackfillCliError:
        raise BackfillCliError(
            "merge_result_publication_failed", production_write=True
        ) from None
    return 0, result


def _error_payload(
    *, command: str, run_id: str | None, error: BackfillCliError
) -> dict[str, object]:
    if error.provider_gate:
        return {
            "schema_version": "backfill_provider_gate_v1",
            "command": command,
            "run_id": run_id,
            "status": "blocked",
            "reason": error.reason,
            "provider_call": False,
            "provider_attempt_made": False,
            "live_send": False,
        }
    return {
        "schema_version": "backfill_cli_error_v1",
        "command": command,
        "run_id": run_id,
        "status": error.status,
        "reason": error.reason,
        "provider_call": error.provider_call,
        "production_write": error.production_write,
        "live_send": False,
    }


def _persisted_provider_call(args: argparse.Namespace) -> bool:
    database = getattr(args, "database", None)
    if not isinstance(database, Path) or database.is_symlink() or not database.is_file():
        return False
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{database.resolve(strict=True).as_uri()}?mode=ro", uri=True, timeout=1.0
        )
        row = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM backfill_provider_attempts "
            "WHERE run_id = ? AND sent_at_utc IS NOT NULL)",
            (getattr(args, "run_id", ""),),
        ).fetchone()
        return bool(row and row[0])
    except (OSError, ValueError, sqlite3.DatabaseError):
        return False
    finally:
        if connection is not None:
            connection.close()


def _domain_error_reason(error: Exception) -> str:
    if isinstance(error, BackfillSchemaError):
        return "staging_schema_invalid"
    if isinstance(error, BackfillConflictError):
        return "staging_integrity_conflict"
    if isinstance(error, (ArchiveIntegrityError, ArchiveReadOnlyError)):
        return "raw_archive_integrity_failed"
    if isinstance(error, ReplayPublicationError):
        return "replay_target_exists_needs_review"
    if isinstance(error, ProviderBudgetExhausted):
        return "provider_budget_exhausted"
    if isinstance(error, TikHubSchemaDrift):
        return "provider_schema_drift"
    if isinstance(error, TikHubProviderError):
        return "provider_operation_failed"
    return "cli_internal_error"


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(raw_argv)
    except BackfillArgumentError:
        known_commands = {
            "seed",
            "probe",
            "collect",
            "profile-admission",
            "v2-seed",
            "replay",
            "reindex-discovery",
            "recover-collection",
            "validate",
            "merge-plan",
            "merge-production",
        }
        command = (
            raw_argv[0]
            if raw_argv and raw_argv[0] in known_commands
            else "unknown"
        )
        _emit(
            _error_payload(
                command=command,
                run_id=None,
                error=BackfillCliError(
                    "cli_arguments_invalid", status="blocked"
                ),
            )
        )
        return 1
    command = cast(str, args.command)
    run_id = getattr(args, "run_id", None)
    if type(run_id) is not str or _RUN_ID_PATTERN.fullmatch(run_id) is None:
        error = BackfillCliError("run_id_invalid", status="blocked")
        _emit(
            _error_payload(
                command=command,
                run_id=None,
                error=error,
            )
        )
        return 1
    handlers = {
        "seed": run_seed,
        "probe": run_probe,
        "collect": run_collect,
        "profile-admission": run_profile_admission,
        "v2-seed": run_v2_seed,
        "replay": run_replay,
        "reindex-discovery": run_reindex_discovery,
        "recover-collection": run_recover_collection,
        "validate": run_validate,
        "merge-plan": run_merge_plan,
        "merge-production": run_merge_production,
    }
    try:
        return_code, payload = handlers[command](args)
    except BackfillCliError as error:
        if (
            not error.provider_gate
            and not error.provider_call
            and command in {"probe", "collect"}
            and _persisted_provider_call(args)
        ):
            error = BackfillCliError(
                error.reason,
                status=error.status,
                provider_call=True,
                production_write=error.production_write,
            )
        _emit(_error_payload(command=command, run_id=getattr(args, "run_id", None), error=error))
        return 1
    except BackfillMergeError as error:
        cli_error = BackfillCliError(
            error.reason,
            status="failed",
            production_write=isinstance(error, MergeCommittedReviewError),
        )
        _emit(
            _error_payload(
                command=command,
                run_id=getattr(args, "run_id", None),
                error=cli_error,
            )
        )
        return 1
    except (
        BackfillSchemaError,
        BackfillConflictError,
        ArchiveIntegrityError,
        ArchiveReadOnlyError,
        ReplayPublicationError,
        ProviderBudgetExhausted,
        TikHubSchemaDrift,
        TikHubProviderError,
    ) as domain_error:
        error = BackfillCliError(
            _domain_error_reason(domain_error),
            provider_call=(
                command in {"probe", "collect"} and _persisted_provider_call(args)
            ),
        )
        _emit(
            _error_payload(
                command=command,
                run_id=getattr(args, "run_id", None),
                error=error,
            )
        )
        return 1
    except (OSError, sqlite3.DatabaseError, TypeError, ValueError, KeyError):
        error = BackfillCliError(
            "cli_operation_failed",
            provider_call=(
                command in {"probe", "collect"} and _persisted_provider_call(args)
            ),
        )
        _emit(_error_payload(command=command, run_id=getattr(args, "run_id", None), error=error))
        return 1
    except Exception:
        error = BackfillCliError(
            "cli_internal_error",
            provider_call=(
                command in {"probe", "collect"} and _persisted_provider_call(args)
            ),
        )
        _emit(
            _error_payload(
                command=command,
                run_id=getattr(args, "run_id", None),
                error=error,
            )
        )
        return 1
    _emit(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
