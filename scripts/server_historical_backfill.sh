#!/usr/bin/env bash
set -euo pipefail

PHASE="${REDDIT_VOC_BACKFILL_PHASE:-}"
RELEASE_MANIFEST_RELATIVE_PATH="config/backfill/momcozy-backfill-release-manifest-20260711.json"

fail() {
  printf 'backfill_server_wrapper_error=%s\n' "$1" >&2
  exit 64
}

require_env() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "missing_required_value:${name}"
}

forward_required() {
  local name="$1"
  require_env "$name"
  docker_args+=(--env "$name")
}

forward_if_set() {
  local name="$1"
  if [[ -n "${!name:-}" ]]; then
    docker_args+=(--env "$name")
  fi
}

validate_host_mount() {
  local path="$1"
  [[ "$path" == /* ]] || fail "host_mount_not_absolute"
  [[ "$path" != *:* && "$path" != *[[:cntrl:]]* ]] || fail "host_mount_invalid"
  [[ -d "$path" ]] || fail "host_mount_not_directory"
}

reject_host_mount_symlinks() {
  local path="$1"
  local component
  local current=""
  local -a components=()
  IFS='/' read -r -a components <<< "$path"
  for component in "${components[@]}"; do
    [[ -n "$component" ]] || continue
    current="$current/$component"
    [[ ! -L "$current" ]] || fail "host_mount_symlink"
  done
}

validate_container_mount() {
  local path="$1"
  [[ "$path" == /* && "$path" != "/" ]] || fail "container_mount_invalid"
  [[ "$path" != *:* && "$path" != *[[:cntrl:]]* ]] || fail "container_mount_invalid"
  [[ "$path" != */../* && "$path" != */.. ]] || fail "container_mount_invalid"
  [[ "$path" != */./* && "$path" != */. ]] || fail "container_mount_invalid"
}

paths_overlap() {
  local first="$1"
  local second="$2"
  [[ "$first" == "$second" || "$first/" == "$second/"* || "$second/" == "$first/"* ]]
}

host_path_for_run_path() {
  local path="$1"
  validate_container_mount "$path"
  case "$path" in
    "$CONTAINER_RUN_ROOT"/*) ;;
    *) fail "reindex_path_outside_run_root" ;;
  esac
  printf '%s/%s\n' "$HOST_RUN_ROOT" "${path#"$CONTAINER_RUN_ROOT"/}"
}

validate_reindex_existing_file() {
  local container_path="$1"
  local host_path
  host_path="$(host_path_for_run_path "$container_path")"
  reject_host_mount_symlinks "$host_path"
  [[ -f "$host_path" && ! -L "$host_path" ]] || \
    fail "reindex_source_database_invalid"
}

validate_reindex_existing_directory() {
  local container_path="$1"
  local host_path
  host_path="$(host_path_for_run_path "$container_path")"
  reject_host_mount_symlinks "$host_path"
  [[ -d "$host_path" && ! -L "$host_path" ]] || \
    fail "reindex_raw_archive_invalid"
}

validate_reindex_output_path() {
  local container_path="$1"
  local output_kind="$2"
  local host_path
  local host_parent
  host_path="$(host_path_for_run_path "$container_path")"
  host_parent="${host_path%/*}"
  reject_host_mount_symlinks "$host_path"
  [[ -d "$host_parent" && ! -L "$host_parent" ]] || \
    fail "reindex_output_parent_invalid"
  if [[ "$output_kind" == "database" ]]; then
    [[ ! -e "$host_path" && ! -L "$host_path" ]] || \
      fail "reindexed_database_exists"
    [[ ! -e "$host_path-wal" && ! -L "$host_path-wal" ]] || \
      fail "reindexed_database_sidecar_exists"
    [[ ! -e "$host_path-shm" && ! -L "$host_path-shm" ]] || \
      fail "reindexed_database_sidecar_exists"
    [[ ! -e "$host_path-journal" && ! -L "$host_path-journal" ]] || \
      fail "reindexed_database_sidecar_exists"
  elif [[ -e "$host_path" && ! -f "$host_path" ]]; then
    fail "reindex_report_path_invalid"
  fi
}

case "$PHASE" in
  probe|collect|replay|reindex-discovery|recover-collection|validate) ;;
  *) fail "unsupported_phase" ;;
esac

require_env REDDIT_VOC_BACKFILL_CONTAINER_IMAGE
require_env REDDIT_VOC_BACKFILL_CODE_ROOT
require_env REDDIT_VOC_BACKFILL_HOST_RUN_ROOT
require_env REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT
require_env REDDIT_VOC_BACKFILL_RUN_ROOT
require_env REDDIT_VOC_BACKFILL_RUN_ID

IMAGE="$REDDIT_VOC_BACKFILL_CONTAINER_IMAGE"
HOST_CODE_ROOT="$REDDIT_VOC_BACKFILL_CODE_ROOT"
HOST_RUN_ROOT="$REDDIT_VOC_BACKFILL_HOST_RUN_ROOT"
CONTAINER_CODE_ROOT="$REDDIT_VOC_BACKFILL_CONTAINER_CODE_ROOT"
CONTAINER_RUN_ROOT="$REDDIT_VOC_BACKFILL_RUN_ROOT"
RUN_ID="$REDDIT_VOC_BACKFILL_RUN_ID"

[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || fail "run_id_invalid"
IMAGE_PATTERN='^[a-z0-9]+([._-][a-z0-9]+)*(:[0-9]{1,5})?(/[a-z0-9]+([._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$'
[[ "$IMAGE" =~ $IMAGE_PATTERN ]] || fail "container_image_not_reviewed_digest"

validate_host_mount "$HOST_CODE_ROOT"
validate_host_mount "$HOST_RUN_ROOT"
reject_host_mount_symlinks "$HOST_CODE_ROOT"
reject_host_mount_symlinks "$HOST_RUN_ROOT"
validate_container_mount "$CONTAINER_CODE_ROOT"
validate_container_mount "$CONTAINER_RUN_ROOT"

HOST_CODE_ROOT="$(cd -- "$HOST_CODE_ROOT" && pwd -P)"
HOST_RUN_ROOT="$(cd -- "$HOST_RUN_ROOT" && pwd -P)"
case "$HOST_CODE_ROOT" in
  /|/Applications|/Library|/System|/Users|/Volumes|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/media|/mnt|/opt|/private|/private/var|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var)
    fail "host_code_root_too_broad"
    ;;
esac
if [[ "$HOST_CODE_ROOT" =~ ^/(Users|home)/[^/]+$ ]]; then
  fail "host_code_root_too_broad"
fi
[[ "${HOST_RUN_ROOT##*/}" == "$RUN_ID" ]] || fail "host_run_root_not_run_leaf"
if paths_overlap "$HOST_CODE_ROOT" "$HOST_RUN_ROOT"; then
  fail "host_mount_roots_overlap"
fi
if paths_overlap "$CONTAINER_CODE_ROOT" "$CONTAINER_RUN_ROOT"; then
  fail "container_mount_roots_overlap"
fi

require_env REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
EXPECTED_RELEASE_MANIFEST_SHA256="$REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256"
FIXED_CONTAINER_RELEASE_MANIFEST="$CONTAINER_CODE_ROOT/$RELEASE_MANIFEST_RELATIVE_PATH"
case "$PHASE" in
  probe|collect|reindex-discovery|recover-collection)
    require_env REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    [[ "$REDDIT_VOC_BACKFILL_RELEASE_MANIFEST" == "$FIXED_CONTAINER_RELEASE_MANIFEST" ]] || \
      fail "release_manifest_path_not_fixed"
    ;;
  validate)
    require_env REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    [[ "$REDDIT_VOC_BACKFILL_RELEASE_MANIFEST" == "$FIXED_CONTAINER_RELEASE_MANIFEST" ]] || \
      fail "release_manifest_path_not_fixed"
    ;;
esac

if [[ "$PHASE" == "reindex-discovery" || "$PHASE" == "recover-collection" ]]; then
  require_env REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH
  require_env REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
  if [[ "$PHASE" == "reindex-discovery" ]]; then
    require_env REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH
    REINDEX_OUTPUT_PATH="$REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH"
  else
    require_env REDDIT_VOC_BACKFILL_RECOVERED_DATABASE_PATH
    require_env REDDIT_VOC_BACKFILL_RECOVERED_AT_UTC
    REINDEX_OUTPUT_PATH="$REDDIT_VOC_BACKFILL_RECOVERED_DATABASE_PATH"
  fi
  require_env REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256
  require_env REDDIT_VOC_BACKFILL_REPORT
  [[ "$REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256" =~ ^[0-9a-f]{64}$ ]] || \
    fail "expected_source_database_sha256_invalid"
  validate_reindex_existing_file "$REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH"
  validate_reindex_existing_directory "$REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR"
  validate_reindex_output_path "$REINDEX_OUTPUT_PATH" database
  validate_reindex_output_path "$REDDIT_VOC_BACKFILL_REPORT" report
fi

IFS= read -r -d '' BUNDLE_VERIFIER_SOURCE <<'PY' || true
import hashlib
import hmac
import json
import os
from pathlib import PurePosixPath
import re
import secrets
import stat
import sys

try:
    ROOT, RUN_ID, EXPECTED_MANIFEST_SHA256, MODE, *MODE_ARGS = sys.argv[1:]
except ValueError:
    raise SystemExit(1) from None
MANIFEST_RELATIVE_PATH = (
    "config/backfill/momcozy-backfill-release-manifest-20260711.json"
)
BASELINE_RELATIVE_PATH = (
    "config/backfill/momcozy-seed-baseline-20250101-20260711.json"
)
REVIEWED_PATHS = (
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
    BASELINE_RELATIVE_PATH,
    "config/backfill/momcozy-comment-cursor-contract-20260711.json",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def reject():
    raise SystemExit(1)


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            reject()
        result[key] = value
    return result


def open_absolute_directory(path_value):
    path = PurePosixPath(path_value)
    if (
        not path.is_absolute()
        or path == PurePosixPath("/")
        or "\\" in path_value
        or "\x00" in path_value
        or "\n" in path_value
        or "\r" in path_value
        or any(part in ("", ".", "..") for part in path.parts[1:])
    ):
        reject()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open("/", directory_flags)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(
                component,
                directory_flags | nofollow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        metadata = os.fstat(directory_fd)
        if not stat.S_ISDIR(metadata.st_mode):
            reject()
        return directory_fd
    except (OSError, ValueError):
        os.close(directory_fd)
        reject()


def create_mount_identity(run_root):
    directory_fd = open_absolute_directory(run_root)
    directory_metadata = os.fstat(directory_fd)
    marker_name = ".backfill-mount-identity." + secrets.token_hex(16)
    payload = secrets.token_bytes(32)
    file_fd = None
    try:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        file_fd = os.open(marker_name, flags, 0o600, dir_fd=directory_fd)
        view = memoryview(payload)
        while view:
            written = os.write(file_fd, view)
            if written <= 0:
                reject()
            view = view[written:]
        os.fsync(file_fd)
        metadata = os.fstat(file_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size != len(payload)
        ):
            reject()
    except (OSError, ValueError):
        reject()
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)
    print(
        marker_name,
        hashlib.sha256(payload).hexdigest(),
        directory_metadata.st_dev,
        directory_metadata.st_ino,
    )


def consume_mount_identity(
    run_root,
    marker_name,
    expected_sha256,
    expected_device,
    expected_inode,
):
    if (
        re.fullmatch(r"\.backfill-mount-identity\.[0-9a-f]{32}", marker_name)
        is None
        or SHA256_PATTERN.fullmatch(expected_sha256) is None
        or re.fullmatch(r"[0-9]+", expected_device) is None
        or re.fullmatch(r"[0-9]+", expected_inode) is None
    ):
        reject()
    directory_fd = open_absolute_directory(run_root)
    file_fd = None
    try:
        directory_metadata = os.fstat(directory_fd)
        if (
            str(directory_metadata.st_dev) != expected_device
            or str(directory_metadata.st_ino) != expected_inode
        ):
            reject()
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        file_fd = os.open(marker_name, flags, dir_fd=directory_fd)
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size != 32
        ):
            reject()
        payload = os.read(file_fd, 33)
        after = os.fstat(file_fd)
        if (
            len(payload) != 32
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or not hmac.compare_digest(
                hashlib.sha256(payload).hexdigest(), expected_sha256
            )
        ):
            reject()
        os.close(file_fd)
        file_fd = None
        os.unlink(marker_name, dir_fd=directory_fd)
    except (OSError, ValueError):
        reject()
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def read_regular(relative_path):
    path = PurePosixPath(relative_path)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") for part in path.parts)
        or "\\" in relative_path
        or "\x00" in relative_path
        or "\n" in relative_path
        or "\r" in relative_path
    ):
        reject()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(ROOT, directory_flags | nofollow)
    try:
        for component in path.parts[:-1]:
            next_fd = os.open(
                component,
                directory_flags | nofollow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            path.parts[-1],
            flags | nofollow,
            dir_fd=directory_fd,
        )
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                reject()
            chunks = []
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(file_fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                reject()
            return b"".join(chunks)
        finally:
            os.close(file_fd)
    except (OSError, ValueError):
        reject()
    finally:
        os.close(directory_fd)


def inventory_regular_files():
    found = set()
    pending = [(ROOT, "")]
    while pending:
        directory, prefix = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            reject()
        for entry in entries:
            relative_path = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                reject()
            if stat.S_ISLNK(metadata.st_mode):
                reject()
            if stat.S_ISDIR(metadata.st_mode):
                pending.append((entry.path, relative_path))
            elif stat.S_ISREG(metadata.st_mode):
                found.add(relative_path)
            else:
                reject()
    return found


if MODE == "create-marker" and len(MODE_ARGS) == 1:
    create_mount_identity(MODE_ARGS[0])
    raise SystemExit(0)
if MODE == "cleanup-marker" and len(MODE_ARGS) == 5:
    consume_mount_identity(*MODE_ARGS)
    raise SystemExit(0)
if MODE not in {"verify", "exec"}:
    reject()
if MODE == "verify" and MODE_ARGS:
    reject()
if MODE == "exec" and len(MODE_ARGS) != 5:
    reject()


try:
    root_metadata = os.lstat(ROOT)
except OSError:
    reject()
if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
    reject()
if SHA256_PATTERN.fullmatch(EXPECTED_MANIFEST_SHA256) is None:
    reject()

manifest_raw = read_regular(MANIFEST_RELATIVE_PATH)
manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
if not hmac.compare_digest(manifest_sha256, EXPECTED_MANIFEST_SHA256):
    reject()
try:
    manifest = json.loads(
        manifest_raw.decode("utf-8"),
        object_pairs_hook=strict_object,
        parse_constant=lambda _value: reject(),
    )
except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
    reject()
if not isinstance(manifest, dict) or set(manifest) != {
    "schema_version",
    "run_id",
    "seed_baseline",
    "reviewed_files_sha256",
}:
    reject()
if (
    manifest["schema_version"] != "momcozy_backfill_release_manifest_v1"
    or manifest["run_id"] != RUN_ID
):
    reject()
baseline = manifest["seed_baseline"]
file_map = manifest["reviewed_files_sha256"]
if not isinstance(baseline, dict) or set(baseline) != {"relative_path", "sha256"}:
    reject()
if not isinstance(file_map, dict) or set(file_map) != set(REVIEWED_PATHS):
    reject()
if any(
    type(path) is not str
    or type(expected_sha256) is not str
    or SHA256_PATTERN.fullmatch(expected_sha256) is None
    for path, expected_sha256 in file_map.items()
):
    reject()
if (
    baseline["relative_path"] != BASELINE_RELATIVE_PATH
    or baseline["sha256"] != file_map[BASELINE_RELATIVE_PATH]
):
    reject()
if inventory_regular_files() != set(REVIEWED_PATHS) | {MANIFEST_RELATIVE_PATH}:
    reject()
for relative_path in REVIEWED_PATHS:
    actual_sha256 = hashlib.sha256(read_regular(relative_path)).hexdigest()
    if not hmac.compare_digest(actual_sha256, file_map[relative_path]):
        reject()
if inventory_regular_files() != set(REVIEWED_PATHS) | {MANIFEST_RELATIVE_PATH}:
    reject()
if MODE == "exec":
    consume_mount_identity(*MODE_ARGS)
    os.execv(
        "/bin/bash",
        ("bash", f"{ROOT}/scripts/run_historical_backfill.sh"),
    )
PY

if ! python3 -c "$BUNDLE_VERIFIER_SOURCE" \
  "$HOST_CODE_ROOT" "$RUN_ID" "$EXPECTED_RELEASE_MANIFEST_SHA256" verify
then
  fail "reviewed_bundle_verification_failed"
fi

MOUNT_IDENTITY="$({
  python3 -c "$BUNDLE_VERIFIER_SOURCE" \
    "$HOST_CODE_ROOT" "$RUN_ID" "$EXPECTED_RELEASE_MANIFEST_SHA256" \
    create-marker "$HOST_RUN_ROOT"
} 2>/dev/null)" || fail "run_root_identity_creation_failed"
IFS=' ' read -r MOUNT_IDENTITY_NAME MOUNT_IDENTITY_SHA256 \
  MOUNT_IDENTITY_DEVICE MOUNT_IDENTITY_INODE MOUNT_IDENTITY_EXTRA \
  <<< "$MOUNT_IDENTITY"
if [[ ! "$MOUNT_IDENTITY_NAME" =~ ^\.backfill-mount-identity\.[0-9a-f]{32}$ ]] \
  || [[ ! "$MOUNT_IDENTITY_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || [[ ! "$MOUNT_IDENTITY_DEVICE" =~ ^[0-9]+$ ]] \
  || [[ ! "$MOUNT_IDENTITY_INODE" =~ ^[0-9]+$ ]] \
  || [[ -n "$MOUNT_IDENTITY_EXTRA" ]]
then
  fail "run_root_identity_creation_failed"
fi

cleanup_mount_identity() {
  python3 -c "$BUNDLE_VERIFIER_SOURCE" \
    "$HOST_CODE_ROOT" "$RUN_ID" "$EXPECTED_RELEASE_MANIFEST_SHA256" \
    cleanup-marker "$HOST_RUN_ROOT" "$MOUNT_IDENTITY_NAME" \
    "$MOUNT_IDENTITY_SHA256" "$MOUNT_IDENTITY_DEVICE" \
    "$MOUNT_IDENTITY_INODE" >/dev/null 2>&1 || true
}
trap cleanup_mount_identity EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

docker_args=(run --rm)
if [[ "$PHASE" == "replay" || "$PHASE" == "reindex-discovery" \
  || "$PHASE" == "recover-collection" \
  || "$PHASE" == "validate" ]]; then
  docker_args+=(--network none)
fi
docker_args+=(
  --volume "$HOST_CODE_ROOT:$CONTAINER_CODE_ROOT:ro"
  --volume "$HOST_RUN_ROOT:$CONTAINER_RUN_ROOT:rw"
  --workdir "$CONTAINER_CODE_ROOT"
  --entrypoint /bin/bash
  --env "PYTHONPATH=$CONTAINER_CODE_ROOT/src"
)

forward_required REDDIT_VOC_BACKFILL_PHASE
forward_required REDDIT_VOC_BACKFILL_RUN_ID

case "$PHASE" in
  probe)
    forward_required REDDIT_VOC_BACKFILL_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    forward_required REDDIT_VOC_BACKFILL_REPORT_DIR
    forward_required REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    forward_if_set REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL
    forward_if_set REDDIT_VOC_ENABLE_TIKHUB
    forward_if_set TIKHUB_BASE_URL
    forward_if_set TIKHUB_API_KEY
    ;;
  collect)
    forward_required REDDIT_VOC_BACKFILL_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    forward_required REDDIT_VOC_BACKFILL_REPORT_DIR
    forward_required REDDIT_VOC_BACKFILL_PROBE_REPORT
    forward_required REDDIT_VOC_BACKFILL_EXPECTED_PROBE_SHA256
    forward_required REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    forward_required REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
    forward_required REDDIT_VOC_BACKFILL_COMMENT_CURSOR_CONTRACT
    forward_required REDDIT_VOC_BACKFILL_MAX_PROVIDER_REQUESTS_TOTAL
    forward_required REDDIT_VOC_BACKFILL_INCLUDE_SUBREDDIT_SWEEP
    if [[ -n "${REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION:-}" \
      || -n "${REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256:-}" ]]; then
      forward_required REDDIT_VOC_BACKFILL_BUDGET_EXTENSION_AUTHORIZATION
      forward_required REDDIT_VOC_BACKFILL_EXPECTED_BUDGET_EXTENSION_AUTHORIZATION_SHA256
    fi
    if [[ -n "${REDDIT_VOC_BACKFILL_EXISTING_BUDGET_RESUME_AUTHORIZATION:-}" \
      || -n "${REDDIT_VOC_BACKFILL_EXPECTED_EXISTING_BUDGET_RESUME_AUTHORIZATION_SHA256:-}" ]]; then
      forward_required REDDIT_VOC_BACKFILL_EXISTING_BUDGET_RESUME_AUTHORIZATION
      forward_required REDDIT_VOC_BACKFILL_EXPECTED_EXISTING_BUDGET_RESUME_AUTHORIZATION_SHA256
    fi
    forward_if_set REDDIT_VOC_BACKFILL_AUTHORIZE_PROVIDER_CALL
    forward_if_set REDDIT_VOC_ENABLE_TIKHUB
    forward_if_set TIKHUB_BASE_URL
    forward_if_set TIKHUB_API_KEY
    ;;
  replay)
    forward_required REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    ;;
  reindex-discovery)
    forward_required REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    forward_required REDDIT_VOC_BACKFILL_REINDEXED_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256
    forward_required REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    forward_required REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
    forward_required REDDIT_VOC_BACKFILL_REPORT
    ;;
  recover-collection)
    forward_required REDDIT_VOC_BACKFILL_SOURCE_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    forward_required REDDIT_VOC_BACKFILL_RECOVERED_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_EXPECTED_SOURCE_DATABASE_SHA256
    forward_required REDDIT_VOC_BACKFILL_RECOVERED_AT_UTC
    forward_required REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    forward_required REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
    forward_required REDDIT_VOC_BACKFILL_REPORT
    ;;
  validate)
    forward_required REDDIT_VOC_BACKFILL_SCOPE
    forward_required REDDIT_VOC_BACKFILL_DATABASE_PATH
    forward_required REDDIT_VOC_BACKFILL_RAW_ARCHIVE_DIR
    forward_required REDDIT_VOC_BACKFILL_SEED_BASELINE
    forward_required REDDIT_VOC_BACKFILL_RELEASE_MANIFEST
    forward_required REDDIT_VOC_BACKFILL_REPORT
    case "$REDDIT_VOC_BACKFILL_SCOPE" in
      seed) ;;
      full)
        forward_required REDDIT_VOC_BACKFILL_REPLAY_DATABASE_PATH
        forward_required REDDIT_VOC_BACKFILL_RUN_ROOT
        forward_required REDDIT_VOC_BACKFILL_EXPECTED_RELEASE_MANIFEST_SHA256
        ;;
      *) fail "invalid_validation_scope" ;;
    esac
    ;;
esac

docker_args+=(
  "$IMAGE"
  -c 'exec python3 -c "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}"'
  backfill-mount-verifier
  "$BUNDLE_VERIFIER_SOURCE"
  "$CONTAINER_CODE_ROOT"
  "$RUN_ID"
  "$EXPECTED_RELEASE_MANIFEST_SHA256"
  exec
  "$CONTAINER_RUN_ROOT"
  "$MOUNT_IDENTITY_NAME"
  "$MOUNT_IDENTITY_SHA256"
  "$MOUNT_IDENTITY_DEVICE"
  "$MOUNT_IDENTITY_INODE"
)

docker "${docker_args[@]}"
