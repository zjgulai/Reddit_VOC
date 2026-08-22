#!/usr/bin/env bash
set -euo pipefail
umask 077

unset DEEPSEEK_API_KEY DINGTALK_WEBHOOK_URL DINGTALK_WEBHOOK_SECRET

LOCAL_TEST_MODE="${REDDIT_VOC_LOCAL_TEST_MODE:-0}"
[[ "$LOCAL_TEST_MODE" == "0" || "$LOCAL_TEST_MODE" == "1" ]] || exit 1
PRODUCTION_LOCK_FILE="/opt/reddit-voc-daily-report/control/locks/daily-report.lock"
PRODUCTION_CURRENT_LINK="/opt/reddit-voc-daily-report/current"
PRODUCTION_RELEASES_ROOT="/opt/reddit-voc-daily-report/releases"
PRODUCTION_CIDFILE="/home/ubuntu/.reddit-voc/run/daily-report.cid"
PRODUCTION_CYCLE_LEASE_ROOT="/home/ubuntu/.reddit-voc/run/cycle-leases"
REPORT_NETWORK="reddit_voc_report_net"
CONTAINER_NETWORK="$REPORT_NETWORK"
PRODUCTION_OVERRIDE=""
if [[ "$LOCAL_TEST_MODE" == "1" ]]; then
  LOCK_FILE="${REDDIT_VOC_REPORT_LOCK_FILE:-$PRODUCTION_LOCK_FILE}"
  CURRENT_LINK="${REDDIT_VOC_REPORT_CURRENT_LINK:-$PRODUCTION_CURRENT_LINK}"
  RELEASES_ROOT="${REDDIT_VOC_REPORT_RELEASES_ROOT:-$PRODUCTION_RELEASES_ROOT}"
  CIDFILE="${REDDIT_VOC_REPORT_CIDFILE:-$PRODUCTION_CIDFILE}"
  CYCLE_LEASE_ROOT="${REDDIT_VOC_REPORT_CYCLE_LEASE_ROOT:-$(dirname "$LOCK_FILE")}"
  PYTHON_BIN="${REDDIT_VOC_HOST_PYTHON_BIN:-python3}"
  DOCKER_BIN="${REDDIT_VOC_DOCKER_BIN:-docker}"
  REPORT_TIMEOUT_SECONDS="${REDDIT_VOC_REPORT_TIMEOUT_SECONDS:-1800}"
  REPORT_UID="${REDDIT_VOC_REPORT_UID:-$(id -u)}"
  REPORT_GID="${REDDIT_VOC_REPORT_GID:-$(id -g)}"
else
  for variable in \
    REDDIT_VOC_REPORT_LOCK_FILE \
    REDDIT_VOC_REPORT_CURRENT_LINK \
    REDDIT_VOC_REPORT_RELEASES_ROOT \
    REDDIT_VOC_REPORT_CIDFILE \
    REDDIT_VOC_REPORT_CYCLE_LEASE_ROOT \
    REDDIT_VOC_HOST_PYTHON_BIN \
    REDDIT_VOC_DOCKER_BIN \
    REDDIT_VOC_REPORT_TIMEOUT_SECONDS \
    REDDIT_VOC_REPORT_UID \
    REDDIT_VOC_REPORT_GID; do
    if [[ -n "${!variable+x}" ]]; then
      PRODUCTION_OVERRIDE="$variable"
      break
    fi
  done
  for variable in ${!REDDIT_VOC_LOCAL_@}; do
    PRODUCTION_OVERRIDE="$variable"
    break
  done
  LOCK_FILE="$PRODUCTION_LOCK_FILE"
  CURRENT_LINK="$PRODUCTION_CURRENT_LINK"
  RELEASES_ROOT="$PRODUCTION_RELEASES_ROOT"
  CIDFILE="$PRODUCTION_CIDFILE"
  CYCLE_LEASE_ROOT="$PRODUCTION_CYCLE_LEASE_ROOT"
  PYTHON_BIN="/usr/bin/python3"
  DOCKER_BIN="/usr/bin/docker"
  REPORT_TIMEOUT_SECONDS="1800"
  REPORT_UID="1000"
  REPORT_GID="1000"
  PATH="/usr/sbin:/usr/bin:/sbin:/bin"
  export PATH
  unset \
    BASH_ENV ENV CDPATH GLOBIGNORE \
    DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG \
    HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY \
    http_proxy https_proxy all_proxy no_proxy \
    PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONINSPECT PYTHONUSERBASE
fi
unset \
  DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG \
  HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY \
  http_proxy https_proxy all_proxy no_proxy

fail() {
  printf 'status=blocked\nreason=%s\nprovider_call=false\ntranslation_provider_attempt_made=false\nreport_live_send=false\nalert_live_send=false\nlive_send=false\n' "$1" >&2
  exit 1
}

[[ -z "$PRODUCTION_OVERRIDE" ]] || fail "production_environment_override_forbidden"

verify_production_binary() {
  local binary="$1"
  local binary_kind="$2"
  [[ "$LOCAL_TEST_MODE" != "1" ]] || return 0
  [[ "$binary" == /* ]] || fail "host_binary_invalid"
  /usr/bin/python3 - "$binary" "$binary_kind" <<'PY' || fail "host_binary_invalid"
import os
import stat
import sys
from pathlib import Path

def validate_binary_metadata(metadata, *, owner_uid):
    if metadata.st_uid != owner_uid:
        raise ValueError("binary_owner_invalid")
    if stat.S_ISLNK(metadata.st_mode):
        return True
    if (
        stat.S_IMODE(metadata.st_mode) & 0o022
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise ValueError("binary_target_invalid")
    return False


def verify_binary_chain(
    original,
    *,
    owner_uid,
    trusted_root,
    expected_parent,
    expected_name_prefix,
    expected_exact,
):
    original = Path(original)
    trusted_root = Path(trusted_root).resolve(strict=True)
    expected_parent = Path(expected_parent).resolve(strict=True)
    current = original
    seen = set()
    for _ in range(16):
        metadata = current.lstat()
        identity = (metadata.st_dev, metadata.st_ino)
        if identity in seen:
            raise ValueError("binary_identity_invalid")
        seen.add(identity)
        if not validate_binary_metadata(metadata, owner_uid=owner_uid):
            if not os.access(current, os.X_OK):
                raise ValueError("binary_not_executable")
            break
        target = Path(os.readlink(current))
        current = target if target.is_absolute() else current.parent / target
        current = Path(os.path.normpath(current))
    else:
        raise ValueError("binary_symlink_depth_invalid")
    resolved = current.resolve(strict=True)
    if resolved.parent != expected_parent:
        raise ValueError("binary_parent_invalid")
    if expected_exact is not None and resolved != Path(expected_exact):
        raise ValueError("binary_exact_target_invalid")
    if expected_name_prefix is not None and not resolved.name.startswith(
        expected_name_prefix
    ):
        raise ValueError("binary_name_invalid")
    try:
        resolved.relative_to(trusted_root)
    except ValueError as exc:
        raise ValueError("binary_trusted_root_invalid") from exc
    parent = resolved.parent
    while True:
        metadata = parent.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != owner_uid
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ValueError("binary_parent_chain_invalid")
        if parent == trusted_root:
            break
        if trusted_root not in parent.parents:
            raise ValueError("binary_parent_chain_invalid")
        parent = parent.parent
    return resolved


try:
    binary = Path(sys.argv[1])
    kind = sys.argv[2]
    if kind == "python" and binary == Path("/usr/bin/python3"):
        verify_binary_chain(
            binary,
            owner_uid=0,
            trusted_root=Path("/"),
            expected_parent=Path("/usr/bin"),
            expected_name_prefix="python3",
            expected_exact=None,
        )
    elif kind == "docker" and binary == Path("/usr/bin/docker"):
        verify_binary_chain(
            binary,
            owner_uid=0,
            trusted_root=Path("/"),
            expected_parent=Path("/usr/bin"),
            expected_name_prefix=None,
            expected_exact=Path("/usr/bin/docker"),
        )
    else:
        raise ValueError("binary_kind_invalid")
except (OSError, ValueError, IndexError):
    raise SystemExit(1)
PY
}

verify_production_binary "$PYTHON_BIN" python
verify_production_binary "$DOCKER_BIN" docker

if [[ "$PYTHON_BIN" != /* ]]; then
  PYTHON_BIN="$(type -P "$PYTHON_BIN")" || fail "host_python_invalid"
fi
[[ "$PYTHON_BIN" == /* && -x "$PYTHON_BIN" ]] || fail "host_python_invalid"

[[ "$REPORT_UID" =~ ^[0-9]+$ && "$REPORT_GID" =~ ^[0-9]+$ ]] \
  || fail "report_user_invalid"
[[ "$REPORT_TIMEOUT_SECONDS" =~ ^[0-9]+$ \
    && "$REPORT_TIMEOUT_SECONDS" -ge 1 \
    && "$REPORT_TIMEOUT_SECONDS" -le 7200 ]] \
  || fail "report_timeout_invalid"

safe_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]]
}

verify_cycle_lease_root() {
  "$PYTHON_BIN" - "$CYCLE_LEASE_ROOT" "$LOCAL_TEST_MODE" <<'PY'
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
local_mode = sys.argv[2] == "1"
production_root = Path("/home/ubuntu/.reddit-voc/run/cycle-leases")
production_parent = production_root.parent

if not root.is_absolute():
    raise SystemExit(1)
if not local_mode and root != production_root:
    raise SystemExit(1)

expected_uid = os.geteuid() if local_mode else 1000
expected_gid = os.getegid() if local_mode else 1000

def validate_directory(path: Path) -> None:
    before = path.lstat()
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISDIR(before.st_mode)
        or before.st_uid != expected_uid
        or before.st_gid != expected_gid
        or stat.S_IMODE(before.st_mode) != 0o700
    ):
        raise SystemExit(1)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        or not stat.S_ISDIR(opened.st_mode)
        or opened.st_uid != expected_uid
        or opened.st_gid != expected_gid
        or stat.S_IMODE(opened.st_mode) != 0o700
    ):
        raise SystemExit(1)

if not local_mode:
    validate_directory(production_parent)
validate_directory(root)
PY
}

record_lock_busy() {
  local blocked_root="/opt/reddit-voc-daily-report/blocked"
  local local_mode="${REDDIT_VOC_LOCAL_TEST_MODE:-0}"
  if [[ -n "${REDDIT_VOC_LOCAL_BLOCKED_ROOT:-}" ]]; then
    [[ "$local_mode" == "1" ]] || return 1
    blocked_root="$REDDIT_VOC_LOCAL_BLOCKED_ROOT"
  fi
  "$PYTHON_BIN" - "$blocked_root" "${REDDIT_VOC_RUN_ID:-}" "$local_mode" <<'PY' \
    >/dev/null 2>&1
import json
import os
import re
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
run_id = sys.argv[2]
local_mode = sys.argv[3] == "1"
safe = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
if safe.fullmatch(run_id) is None:
    run_id = "lock_busy_unknown"
if not root.is_absolute():
    raise SystemExit(1)
if not root.exists():
    if not local_mode:
        raise SystemExit(1)
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
metadata = root.lstat()
if (
    stat.S_ISLNK(metadata.st_mode)
    or not stat.S_ISDIR(metadata.st_mode)
    or metadata.st_uid != os.getuid()
    or stat.S_IMODE(metadata.st_mode) != 0o700
):
    raise SystemExit(1)
run_root = root / run_id
if run_root.exists():
    metadata = run_root.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise SystemExit(1)
else:
    run_root.mkdir(mode=0o700)
    run_root.chmod(0o700)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
attempt_id = f"lock-busy-{stamp}-{secrets.token_hex(8)}"
attempt_root = run_root / attempt_id
attempt_root.mkdir(mode=0o700)
attempt_root.chmod(0o700)
manifest = {
    "schema_version": "daily-translation-attempt-v1",
    "attempt_id": attempt_id,
    "run_id": run_id,
    "status": "blocked",
    "stage": "lock",
    "reason_codes": ["lock_busy"],
    "provider_call": False,
    "translation_provider_call": False,
    "translation_provider_attempt_made": False,
    "translation_phase_attempt_made": False,
    "semantic_validation_phase_attempt_made": False,
    "request_count": 0,
    "retry_count": 0,
    "duration_ms": 0,
    "usage": {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "total_tokens": 0,
    },
    "responses": [],
    "counts": {"posts": 0, "items": 0},
    "items": [],
    "provider_authorization_id": None,
}
payload = json.dumps(
    manifest,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8") + b"\n"
path = attempt_root / "blocked-manifest.json"
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(path, flags, 0o600)
try:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("blocked_write_failed")
        view = view[written:]
    os.fsync(descriptor)
finally:
    os.close(descriptor)
os.chmod(path, 0o600)
for directory in (attempt_root, run_root, root):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
}

operation="${1:-scheduled-prepare}"
[[ "$operation" =~ ^(prepare|send|smoke|scheduled-prepare|scheduled-cycle)$ ]] \
  || fail "launcher_operation_invalid"
if [[ $# -gt 0 ]]; then
  shift
fi
SCHEDULED_PREPARE=0
SCHEDULED_CYCLE=0
if [[ "$operation" == "scheduled-prepare" || "$operation" == "scheduled-cycle" ]]; then
  SCHEDULED_PREPARE=1
  if [[ "$operation" == "scheduled-cycle" ]]; then
    SCHEDULED_CYCLE=1
  fi
  [[ $# -eq 0 ]] || fail "launcher_argument_invalid"
else
  [[ "${REDDIT_VOC_ENABLE_HOST_LAUNCH:-0}" == "1" ]] \
    || fail "host_launch_not_authorized"
  [[ "${1:-}" == "--authorize-host-launch" ]] \
    || fail "host_launch_not_authorized"
  shift
fi
PREPARE_ACTION_ID=""
PROVIDER_AUTHORIZATION_ID=""
SEND_AUTHORIZATION_ID=""
EXPECTED_ARTIFACT_VERSION_ID=""
EXPECTED_BUNDLE_SHA256=""
EXPECTED_OUTBOX_SHA256=""
SEND_ACTION="initial"
SCHEDULED_CYCLE_ID=""
CYCLE_LEASE_FD=""
AUTHORIZE_RESEND=0
RESEND_PARTS=()
if [[ "$operation" == "prepare" ]]; then
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prepare-action-authorization-id)
        [[ $# -ge 2 ]] || fail "prepare_action_id_missing"
        PREPARE_ACTION_ID="$2"
        shift 2
        ;;
      --provider-authorization-id)
        [[ $# -ge 2 ]] || fail "provider_authorization_id_missing"
        PROVIDER_AUTHORIZATION_ID="$2"
        shift 2
        ;;
      *) fail "launcher_argument_invalid" ;;
    esac
  done
  safe_id "$PREPARE_ACTION_ID" || fail "prepare_action_authorization_id_invalid"
  if [[ -n "$PROVIDER_AUTHORIZATION_ID" ]]; then
    safe_id "$PROVIDER_AUTHORIZATION_ID" || fail "provider_authorization_id_invalid"
  fi
elif [[ "$operation" == "send" ]]; then
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --authorization-id)
        [[ $# -ge 2 ]] || fail "send_authorization_id_missing"
        SEND_AUTHORIZATION_ID="$2"
        shift 2
        ;;
      --expected-artifact-version-id)
        [[ $# -ge 2 ]] || fail "send_tuple_missing"
        EXPECTED_ARTIFACT_VERSION_ID="$2"
        shift 2
        ;;
      --expected-bundle-sha256)
        [[ $# -ge 2 ]] || fail "send_tuple_missing"
        EXPECTED_BUNDLE_SHA256="$2"
        shift 2
        ;;
      --expected-outbox-sha256)
        [[ $# -ge 2 ]] || fail "send_tuple_missing"
        EXPECTED_OUTBOX_SHA256="$2"
        shift 2
        ;;
      --scheduled-cycle-id)
        [[ $# -ge 2 ]] || fail "scheduled_cycle_id_missing"
        SCHEDULED_CYCLE_ID="$2"
        shift 2
        ;;
      --cycle-lease-fd)
        [[ $# -ge 2 ]] || fail "cycle_lease_fd_missing"
        CYCLE_LEASE_FD="$2"
        shift 2
        ;;
      --authorize-resend)
        AUTHORIZE_RESEND=1
        SEND_ACTION="resend"
        shift
        ;;
      --resend-part-index)
        [[ $# -ge 2 && "$2" =~ ^[1-9][0-9]*$ ]] \
          || fail "resend_part_index_invalid"
        RESEND_PARTS+=("$2")
        shift 2
        ;;
      *) fail "launcher_argument_invalid" ;;
    esac
  done
  safe_id "$SEND_AUTHORIZATION_ID" || fail "send_authorization_id_invalid"
  [[ "$EXPECTED_ARTIFACT_VERSION_ID" =~ ^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}$ ]] \
    || fail "artifact_version_id_invalid"
  [[ "$EXPECTED_BUNDLE_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || fail "bundle_sha256_invalid"
  [[ "$EXPECTED_OUTBOX_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || fail "outbox_sha256_invalid"
  if [[ -n "$SCHEDULED_CYCLE_ID" || -n "$CYCLE_LEASE_FD" ]]; then
    safe_id "$SCHEDULED_CYCLE_ID" || fail "scheduled_cycle_id_invalid"
    [[ "$CYCLE_LEASE_FD" =~ ^[0-9]+$ && "$CYCLE_LEASE_FD" -ge 3 ]] \
      || fail "cycle_lease_fd_invalid"
    [[ "$SEND_ACTION" == "initial" ]] || fail "scheduled_cycle_resend_forbidden"
  fi
  if [[ "$AUTHORIZE_RESEND" == "1" ]]; then
    [[ ${#RESEND_PARTS[@]} -gt 0 ]] || fail "resend_part_index_required"
  elif [[ ${#RESEND_PARTS[@]} -gt 0 ]]; then
    fail "resend_not_authorized"
  fi
else
  [[ $# -eq 0 ]] || fail "launcher_argument_invalid"
fi

INHERITED_LOCK_FD="${REDDIT_VOC_INHERITED_LOCK_FD:-}"
STABLE_LOCK_FD="${REDDIT_VOC_DAILY_LOCK_FD:-}"
if [[ -n "$STABLE_LOCK_FD" ]]; then
  [[ -z "$INHERITED_LOCK_FD" \
      && "$operation" == "scheduled-cycle" \
      && "${REDDIT_VOC_G6R1_STABLE_VERIFIED:-0}" == "1" ]] \
    || fail "stable_inherited_lock_invalid"
  INHERITED_LOCK_FD="$STABLE_LOCK_FD"
fi
if [[ -n "$INHERITED_LOCK_FD" ]]; then
  [[ ( "$operation" == "scheduled-cycle" && -n "$STABLE_LOCK_FD" ) \
      || "$operation" == "smoke" \
      || ( "$operation" == "prepare" \
        && "${REDDIT_VOC_ENABLE_HOST_LAUNCH:-0}" == "1" ) \
      || ( "$operation" == "send" \
        && -n "$SCHEDULED_CYCLE_ID" \
        && -n "$CYCLE_LEASE_FD" ) ]] \
    || fail "inherited_lock_forbidden"
  [[ -n "$STABLE_LOCK_FD" \
      || "${REDDIT_VOC_ENABLE_HOST_LAUNCH:-0}" == "1" ]] \
    || fail "host_launch_not_authorized"
  [[ "$INHERITED_LOCK_FD" =~ ^[0-9]+$ && "$INHERITED_LOCK_FD" -ge 3 ]] \
    || fail "inherited_lock_fd_invalid"
fi

LOCK_FD=9
if [[ -n "$INHERITED_LOCK_FD" ]]; then
  LOCK_FD="$INHERITED_LOCK_FD"
  "$PYTHON_BIN" - "$LOCK_FILE" "$LOCK_FD" <<'PY' \
    || fail "inherited_lock_fd_invalid"
import fcntl
import os
import stat
import sys

path = sys.argv[1]
descriptor = int(sys.argv[2])
production = os.environ.get("REDDIT_VOC_LOCAL_TEST_MODE", "0") != "1"
try:
    fd_metadata = os.fstat(descriptor)
    path_metadata = os.lstat(path)
except (OSError, ValueError):
    raise SystemExit(1)
expected = (
    path_metadata.st_uid == 0
    and path_metadata.st_gid == 1000
    and stat.S_IMODE(path_metadata.st_mode) == 0o660
) if production else (
    path_metadata.st_uid == os.getuid()
    and stat.S_IMODE(path_metadata.st_mode) == 0o600
)
if (
    stat.S_ISLNK(path_metadata.st_mode)
    or not stat.S_ISREG(path_metadata.st_mode)
    or not expected
    or fd_metadata.st_dev != path_metadata.st_dev
    or fd_metadata.st_ino != path_metadata.st_ino
    or fd_metadata.st_uid != path_metadata.st_uid
    or fd_metadata.st_gid != path_metadata.st_gid
    or stat.S_IMODE(fd_metadata.st_mode) != stat.S_IMODE(path_metadata.st_mode)
):
    raise SystemExit(1)
if production:
    from pathlib import Path
    for parent in reversed(Path(path).absolute().parents):
        metadata = parent.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or not os.access(parent, os.X_OK)
        ):
            raise SystemExit(1)
flags = os.O_RDWR
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
probe = os.open(path, flags)
try:
    try:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        fcntl.flock(probe, fcntl.LOCK_UN)
        raise SystemExit(1)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(1)
finally:
    os.close(probe)
PY
elif [[ "$LOCAL_TEST_MODE" == "1" \
    && -n "${REDDIT_VOC_LOCAL_INHERITED_LOCK_FD:-}" ]]; then
  LOCK_FD="$REDDIT_VOC_LOCAL_INHERITED_LOCK_FD"
  [[ "$LOCK_FD" =~ ^[0-9]+$ && "$LOCK_FD" -ge 3 ]] \
    || fail "inherited_lock_fd_invalid"
else
  if [[ "$LOCAL_TEST_MODE" == "1" ]]; then
    mkdir -p "$(dirname "$LOCK_FILE")"
    exec 9>"$LOCK_FILE"
  else
    [[ "$LOCK_FILE" == "$PRODUCTION_LOCK_FILE" ]] || fail "lock_path_invalid"
    exec 9<"$LOCK_FILE" || fail "lock_path_invalid"
    "$PYTHON_BIN" - "$LOCK_FILE" 9 <<'PY' \
      || fail "lock_path_invalid"
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
descriptor = int(sys.argv[2])
metadata = path.lstat()
opened = os.fstat(descriptor)
if (
    stat.S_ISLNK(metadata.st_mode)
    or not stat.S_ISREG(metadata.st_mode)
    or metadata.st_uid != 0
    or metadata.st_gid != 1000
    or stat.S_IMODE(metadata.st_mode) != 0o660
    or opened.st_dev != metadata.st_dev
    or opened.st_ino != metadata.st_ino
    or opened.st_uid != 0
    or opened.st_gid != 1000
    or stat.S_IMODE(opened.st_mode) != 0o660
):
    raise SystemExit(1)
for parent in reversed(path.absolute().parents):
    parent_metadata = parent.lstat()
    if (
        stat.S_ISLNK(parent_metadata.st_mode)
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != 0
        or stat.S_IMODE(parent_metadata.st_mode) & 0o022
        or not os.access(parent, os.X_OK)
    ):
        raise SystemExit(1)
PY
  fi
  if ! flock -n 9; then
    record_lock_busy || true
    fail "lock_busy"
  fi
fi

if [[ "$LOCAL_TEST_MODE" == "1" && "$operation" != "smoke" ]]; then
  [[ "$LOCK_FILE" != "$PRODUCTION_LOCK_FILE" \
      && "$CURRENT_LINK" != "$PRODUCTION_CURRENT_LINK" \
      && "$RELEASES_ROOT" != "$PRODUCTION_RELEASES_ROOT" \
      && -n "${REDDIT_VOC_LOCAL_SHADOW_ROOT:-}" ]] \
    || fail "local_test_production_scope_forbidden"
fi

if [[ "$SCHEDULED_PREPARE" == "1" ]]; then
  schedule_now="${REDDIT_VOC_LOCAL_SCHEDULE_NOW:-}"
  if [[ -n "$schedule_now" && "${REDDIT_VOC_LOCAL_TEST_MODE:-0}" != "1" ]]; then
    fail "schedule_time_override_forbidden"
  fi
  RUN_ID="$("$PYTHON_BIN" - "$schedule_now" <<'PY'
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

override = sys.argv[1]
if override:
    try:
        now = datetime.fromisoformat(override)
    except ValueError:
        raise SystemExit(1)
    if now.tzinfo is None:
        raise SystemExit(1)
    now = now.astimezone(ZoneInfo("Asia/Shanghai"))
else:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
print(f"daily_collect_{now:%Y%m%d}_0700")
PY
)" || fail "schedule_run_id_generation_failed"
else
  RUN_ID="${REDDIT_VOC_RUN_ID:-}"
fi
safe_id "$RUN_ID" || fail "run_id_invalid"

if [[ "$SCHEDULED_CYCLE" == "1" ]]; then
  verify_cycle_lease_root || fail "cycle_lease_root_invalid"
fi

if [[ "${REDDIT_VOC_LOCAL_TEST_MODE:-0}" != "1" ]]; then
  [[ "$LOCK_FILE" == "/opt/reddit-voc-daily-report/control/locks/daily-report.lock" ]] || fail "lock_path_invalid"
  [[ "$CURRENT_LINK" == "/opt/reddit-voc-daily-report/current" ]] || fail "release_pointer_path_invalid"
  [[ "$RELEASES_ROOT" == "/opt/reddit-voc-daily-report/releases" ]] || fail "release_root_invalid"
fi
RELEASES_ROOT="$(cd "$RELEASES_ROOT" && pwd -P)" || fail "release_root_invalid"

RELEASE_DIR="$(readlink -f "$CURRENT_LINK")" || fail "release_pointer_invalid"
[[ "$RELEASE_DIR" == "$RELEASES_ROOT"/* ]] || fail "release_path_invalid"
[[ ! -L "$RELEASE_DIR" && -d "$RELEASE_DIR" ]] || fail "release_directory_invalid"
RELEASE_SHA256="$(basename "$RELEASE_DIR")"
[[ "$RELEASE_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "release_sha256_invalid"
release_mode="$(stat -c '%a' "$RELEASE_DIR" 2>/dev/null || stat -f '%Lp' "$RELEASE_DIR" 2>/dev/null)" \
  || fail "release_metadata_invalid"
[[ "$release_mode" == "755" || "$release_mode" == "700" || "$release_mode" == "555" ]] || fail "release_mode_invalid"

export PYTHONNOUSERSITE=1
"$PYTHON_BIN" "$RELEASE_DIR/scripts/build_daily_report_release.py" verify \
  --release-dir "$RELEASE_DIR" >/dev/null || fail "release_verification_failed"
import_verify_args=(
  verify-imports
  --release-dir "$RELEASE_DIR"
  --python-executable "$PYTHON_BIN"
)
launcher_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$launcher_root" != "$RELEASE_DIR" ]]; then
  import_verify_args+=(--forbidden-root "$launcher_root")
fi
"$PYTHON_BIN" "$RELEASE_DIR/scripts/build_daily_report_release.py" \
  "${import_verify_args[@]}" >/dev/null || fail "release_import_verification_failed"
LAUNCHER_SHA256="$("$PYTHON_BIN" - "$RELEASE_DIR/scripts/server_daily_report.sh" <<'PY'
import hashlib
import sys
from pathlib import Path

payload = Path(sys.argv[1]).read_bytes()
if len(payload) > 4 * 1024 * 1024:
    raise SystemExit(1)
print(hashlib.sha256(payload).hexdigest())
PY
)" || fail "launcher_sha256_invalid"
[[ "$LAUNCHER_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "launcher_sha256_invalid"
if [[ "$SCHEDULED_CYCLE" == "1" ]]; then
  cycle_lease_token="$("$PYTHON_BIN" - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)" || fail "cycle_lease_generation_failed"
  [[ "$cycle_lease_token" =~ ^[0-9a-f]{64}$ ]] \
    || fail "cycle_lease_generation_failed"
  cycle_lease_path="$(mktemp "$CYCLE_LEASE_ROOT/.g6r1-cycle-lease.XXXXXX")" \
    || fail "cycle_lease_create_failed"
  chmod 600 "$cycle_lease_path" || fail "cycle_lease_create_failed"
  printf '%s' "$cycle_lease_token" >"$cycle_lease_path" \
    || fail "cycle_lease_create_failed"
  exec {CYCLE_LEASE_FD}<"$cycle_lease_path" \
    || fail "cycle_lease_create_failed"
  rm -f "$cycle_lease_path" || fail "cycle_lease_unlink_failed"
  unset cycle_lease_token cycle_lease_path
fi

IMAGE_ID="$("$PYTHON_BIN" - "$RELEASE_DIR/report-release-manifest.json" <<'PY'
import json
import re
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
image = value.get("image_id")
if not isinstance(image, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None:
    raise SystemExit(1)
print(image)
PY
)" || fail "release_image_invalid"

UPDATER="$RELEASE_DIR/scripts/server_update_daily_report_runtime_env.sh"
ADMIN="$RELEASE_DIR/scripts/server_daily_report_admin.sh"
if [[ -n "${REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR:-}" ]]; then
  [[ "${REDDIT_VOC_LOCAL_TEST_MODE:-0}" == "1" ]] || fail "fake_control_forbidden"
  fake_root="$REDDIT_VOC_LOCAL_FAKE_CONTROL_DIR"
  [[ "$fake_root" == /* && ! -L "$fake_root" && -d "$fake_root" ]] || fail "fake_control_invalid"
  UPDATER="$fake_root/updater"
  ADMIN="$fake_root/admin"
fi
[[ ! -L "$UPDATER" && -f "$UPDATER" && -x "$UPDATER" ]] || fail "runtime_updater_invalid"
[[ ! -L "$ADMIN" && -f "$ADMIN" && -x "$ADMIN" ]] || fail "runtime_admin_invalid"

CONTROL_SCOPE_ARGS=()
SHADOW_ROOT=""
if [[ -n "${REDDIT_VOC_LOCAL_SHADOW_ROOT:-}" ]]; then
  [[ "${REDDIT_VOC_LOCAL_TEST_MODE:-0}" == "1" ]] || fail "shadow_scope_forbidden"
  SHADOW_ROOT="$(cd "$REDDIT_VOC_LOCAL_SHADOW_ROOT" && pwd -P)" || fail "shadow_root_invalid"
  CONTROL_SCOPE_ARGS=(--shadow-root "$SHADOW_ROOT")
fi

SCHEDULE_AUTHORITY_ARGS=()
SCHEDULE_TIME_ARGS=()
if [[ "$SCHEDULED_CYCLE" == "1" || -n "$SCHEDULED_CYCLE_ID" ]]; then
  if [[ "${REDDIT_VOC_LOCAL_TEST_MODE:-0}" == "1" ]]; then
    [[ -n "${REDDIT_VOC_LOCAL_SCHEDULE_NOW:-}" ]] \
      || fail "scheduled_time_invalid"
    SCHEDULE_TIME_ARGS=(--scheduled-at "$REDDIT_VOC_LOCAL_SCHEDULE_NOW")
    schedule_authority_bindings=(
      policy-file REDDIT_VOC_LOCAL_G6R1_POLICY_FILE
      parent-policy-file REDDIT_VOC_LOCAL_G6R1_PARENT_POLICY_FILE
      credential-rotation-receipt-file REDDIT_VOC_LOCAL_G6R1_ROTATION_RECEIPT_FILE
      report-env-install-receipt-file REDDIT_VOC_LOCAL_G6R1_REPORT_ENV_INSTALL_RECEIPT_FILE
      dual-credential-set-receipt-file REDDIT_VOC_LOCAL_G6R1_DUAL_CREDENTIAL_SET_RECEIPT_FILE
      dual-report-env-install-receipt-file REDDIT_VOC_LOCAL_G6R1_DUAL_REPORT_ENV_INSTALL_RECEIPT_FILE
      report-env-file REDDIT_VOC_LOCAL_G6R1_REPORT_ENV_FILE
      owner-policy-permit-file REDDIT_VOC_LOCAL_G6R1_OWNER_POLICY_PERMIT_FILE
      activation-marker-file REDDIT_VOC_LOCAL_G6R1_ACTIVATION_MARKER_FILE
      transactions-root REDDIT_VOC_LOCAL_G6R1_TRANSACTIONS_ROOT
      primary-cron-file REDDIT_VOC_LOCAL_G6R1_PRIMARY_CRON_FILE
      stable-entrypoint-file REDDIT_VOC_LOCAL_G6R1_STABLE_ENTRYPOINT_FILE
      secondary-disposition-file REDDIT_VOC_LOCAL_G6R1_SECONDARY_DISPOSITION_FILE
      user-crontab-snapshot-file REDDIT_VOC_LOCAL_G6R1_USER_CRONTAB_SNAPSHOT_FILE
      process-snapshot-file REDDIT_VOC_LOCAL_G6R1_PROCESS_SNAPSHOT_FILE
    )
    for ((binding_index = 0; binding_index < ${#schedule_authority_bindings[@]}; binding_index += 2)); do
      option="${schedule_authority_bindings[$binding_index]}"
      variable="${schedule_authority_bindings[$((binding_index + 1))]}"
      value="${!variable:-}"
      if [[ -n "$value" ]]; then
        SCHEDULE_AUTHORITY_ARGS+=("--$option" "$value")
      fi
    done
  fi
fi

"$UPDATER" verify-base-env ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} --inherited-lock-fd "$LOCK_FD" \
  >/dev/null || fail "base_runtime_env_invalid"
"$ADMIN" recover-prepared-state \
  ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
  --release-dir "$RELEASE_DIR" \
  --config-root "$RELEASE_DIR/config" \
  --expected-release-sha256 "$RELEASE_SHA256" \
  --inherited-lock-fd "$LOCK_FD" \
  >/dev/null || fail "prepared_state_recovery_failed"

PHASE_MOUNT_ARGS=()
CONTAINER_COMMAND=(
  bash /app/scripts/run_daily_report.sh smoke
  --config-root /app/config
  --work-root /tmp/report-smoke
)
ATTEMPT_ID=""
ARTIFACT_VERSION_ID=""
RUNTIME_ENV_PATH=""
PUBLIC_ROOT=""
PRIVATE_ROOT=""
PUBLIC_STAGING_ROOT=""
PRIVATE_STAGING_ROOT=""
STATE_ROOT=""
BLOCKED_ROOT=""
HANDOFF_ROOT=""
PROVIDER_ATTEMPT_ROOT=""
DATABASE_PATH=""
KEY_PATH=""
container_id=""
container_wait_pid=""
WAIT_RESULT_PATH=""
CONTAINER_GATE_DIR=""
PREPARE_PERMIT_RESERVED=0
PROVIDER_PERMIT_RESERVED=0
SEND_PERMIT_RESERVED=0
SEND_CONTAINER_STARTED=0
SEND_RUNTIME_MODE="single"

cleanup_prepare() {
  local original_status=$?
  trap - EXIT INT TERM
  if [[ -n "$container_id" ]]; then
    "$DOCKER_BIN" rm -f "$container_id" >/dev/null 2>&1 || true
  fi
  if [[ -n "$container_wait_pid" ]]; then
    kill "$container_wait_pid" >/dev/null 2>&1 || true
    wait "$container_wait_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$WAIT_RESULT_PATH" ]]; then
    rm -f "$WAIT_RESULT_PATH" >/dev/null 2>&1 || true
  fi
  if [[ -n "$CONTAINER_GATE_DIR" && -d "$CONTAINER_GATE_DIR" \
      && ! -L "$CONTAINER_GATE_DIR" ]]; then
    rm -f "$CONTAINER_GATE_DIR/permit" >/dev/null 2>&1 || true
    rmdir "$CONTAINER_GATE_DIR" >/dev/null 2>&1 || true
  fi
  rm -f "$CIDFILE" >/dev/null 2>&1 || true
  if [[ -n "$RUNTIME_ENV_PATH" && -e "$RUNTIME_ENV_PATH" ]]; then
    "$UPDATER" remove-runtime-env \
      ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
      --attempt-id "$ATTEMPT_ID" \
      --inherited-lock-fd "$LOCK_FD" >/dev/null 2>&1 || true
  fi
  if [[ "$original_status" != "0" ]]; then
    if [[ "$PROVIDER_PERMIT_RESERVED" == "1" ]]; then
      "$ADMIN" terminalize-permit \
        ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
        --authorization-id "$PROVIDER_AUTHORIZATION_ID" \
        --expected-release-sha256 "$RELEASE_SHA256" \
        --terminal-status blocked \
        --inherited-lock-fd "$LOCK_FD" >/dev/null 2>&1 || true
    fi
    if [[ "$PREPARE_PERMIT_RESERVED" == "1" ]]; then
      "$ADMIN" terminalize-permit \
        ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
        --authorization-id "$PREPARE_ACTION_ID" \
        --expected-release-sha256 "$RELEASE_SHA256" \
        --terminal-status blocked \
        --inherited-lock-fd "$LOCK_FD" >/dev/null 2>&1 || true
      if [[ -n "$SCHEDULED_CYCLE_ID" && -n "$CYCLE_LEASE_FD" ]]; then
        "$ADMIN" terminalize-scheduled-prepare \
          ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
          --cycle-id "$SCHEDULED_CYCLE_ID" \
          --cycle-lease-fd "$CYCLE_LEASE_FD" \
          --prepare-action-authorization-id "$PREPARE_ACTION_ID" \
          --expected-release-sha256 "$RELEASE_SHA256" \
          --run-id "$RUN_ID" \
          --terminal-status blocked \
          --inherited-lock-fd "$LOCK_FD" >/dev/null 2>&1 || true
      fi
    fi
  fi
  exit "$original_status"
}

cleanup_send() {
  local original_status=$?
  trap - EXIT INT TERM
  if [[ -n "$container_id" ]]; then
    "$DOCKER_BIN" rm -f "$container_id" >/dev/null 2>&1 || true
  fi
  if [[ -n "$container_wait_pid" ]]; then
    kill "$container_wait_pid" >/dev/null 2>&1 || true
    wait "$container_wait_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$WAIT_RESULT_PATH" ]]; then
    rm -f "$WAIT_RESULT_PATH" >/dev/null 2>&1 || true
  fi
  if [[ -n "$CONTAINER_GATE_DIR" && -d "$CONTAINER_GATE_DIR" \
      && ! -L "$CONTAINER_GATE_DIR" ]]; then
    rm -f "$CONTAINER_GATE_DIR/permit" >/dev/null 2>&1 || true
    rmdir "$CONTAINER_GATE_DIR" >/dev/null 2>&1 || true
  fi
  rm -f "$CIDFILE" >/dev/null 2>&1 || true
  if [[ -n "$RUNTIME_ENV_PATH" && -e "$RUNTIME_ENV_PATH" ]]; then
    "$UPDATER" remove-runtime-env \
      ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
      --attempt-id "$ATTEMPT_ID" \
      --inherited-lock-fd "$LOCK_FD" >/dev/null 2>&1 || true
  fi
  if [[ "$SEND_PERMIT_RESERVED" == "1" ]]; then
    terminal_status="closed_no_attempt"
    if [[ "$SEND_CONTAINER_STARTED" == "1" ]]; then
      terminal_status="unknown"
    fi
    terminal_args=(
      terminalize-send-permit
      ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"}
      --authorization-id "$SEND_AUTHORIZATION_ID"
      --expected-release-sha256 "$RELEASE_SHA256"
      --run-id "$RUN_ID"
      --expected-artifact-version-id "$EXPECTED_ARTIFACT_VERSION_ID"
      --expected-bundle-sha256 "$EXPECTED_BUNDLE_SHA256"
      --expected-outbox-sha256 "$EXPECTED_OUTBOX_SHA256"
      --action "$SEND_ACTION"
      --terminal-status "$terminal_status"
      --inherited-lock-fd "$LOCK_FD"
    )
    for part in ${RESEND_PARTS[@]+"${RESEND_PARTS[@]}"}; do
      terminal_args+=(--resend-part-index "$part")
    done
    if [[ -n "$SCHEDULED_CYCLE_ID" ]]; then
      terminal_args+=(
        --scheduled-cycle-id "$SCHEDULED_CYCLE_ID"
        --cycle-lease-fd "$CYCLE_LEASE_FD"
      )
    fi
    "$ADMIN" "${terminal_args[@]}" >/dev/null 2>&1 || true
  fi
  exit "$original_status"
}

ensure_mode700_directory() {
  local path="$1"
  if [[ -e "$path" || -L "$path" ]]; then
    [[ ! -L "$path" && -d "$path" ]] || fail "report_directory_invalid"
    directory_mode="$(stat -c '%a' "$path" 2>/dev/null || stat -f '%Lp' "$path" 2>/dev/null)" \
      || fail "report_directory_metadata_invalid"
    [[ "$directory_mode" == "700" ]] || fail "report_directory_mode_invalid"
  else
    mkdir -m 700 "$path" || fail "report_directory_create_failed"
  fi
}

ensure_mode755_public_directory() {
  local path="$1"
  [[ ! -L "$path" && -d "$path" ]] || fail "public_report_directory_invalid"
  local metadata
  metadata="$(stat -c '%u:%g:%a' "$path" 2>/dev/null \
    || stat -f '%u:%g:%Lp' "$path" 2>/dev/null)" \
    || fail "public_report_directory_metadata_invalid"
  [[ "$metadata" == "$REPORT_UID:$REPORT_GID:755" ]] \
    || fail "public_report_directory_mode_invalid"
}

require_empty_mode700_directory() {
  local path="$1"
  ensure_mode700_directory "$path"
  [[ -z "$(find "$path" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
    || fail "report_staging_not_empty"
}

if [[ "$operation" == "send" ]]; then
  send_permit_args=(
    --authorization-id "$SEND_AUTHORIZATION_ID"
    --expected-release-sha256 "$RELEASE_SHA256"
    --run-id "$RUN_ID"
    --expected-artifact-version-id "$EXPECTED_ARTIFACT_VERSION_ID"
    --expected-bundle-sha256 "$EXPECTED_BUNDLE_SHA256"
    --expected-outbox-sha256 "$EXPECTED_OUTBOX_SHA256"
    --action "$SEND_ACTION"
  )
  for part in ${RESEND_PARTS[@]+"${RESEND_PARTS[@]}"}; do
    send_permit_args+=(--resend-part-index "$part")
  done
  if [[ -n "$SCHEDULED_CYCLE_ID" ]]; then
    send_permit_args+=(
      --scheduled-cycle-id "$SCHEDULED_CYCLE_ID"
      --cycle-lease-fd "$CYCLE_LEASE_FD"
    )
  fi
  send_runtime_args=(
    --authorization-id "$SEND_AUTHORIZATION_ID"
    --expected-release-sha256 "$RELEASE_SHA256"
    --run-id "$RUN_ID"
    --artifact-version-id "$EXPECTED_ARTIFACT_VERSION_ID"
    --expected-bundle-sha256 "$EXPECTED_BUNDLE_SHA256"
    --expected-outbox-sha256 "$EXPECTED_OUTBOX_SHA256"
    --action "$SEND_ACTION"
  )
  for part in ${RESEND_PARTS[@]+"${RESEND_PARTS[@]}"}; do
    send_runtime_args+=(--resend-part-index "$part")
  done
  if [[ -n "$SCHEDULED_CYCLE_ID" ]]; then
    send_runtime_args+=(
      --scheduled-cycle-id "$SCHEDULED_CYCLE_ID"
      --cycle-lease-fd "$CYCLE_LEASE_FD"
    )
    send_permit_args+=(
      ${SCHEDULE_TIME_ARGS[@]+"${SCHEDULE_TIME_ARGS[@]}"}
    )
    send_runtime_args+=(
      ${SCHEDULE_TIME_ARGS[@]+"${SCHEDULE_TIME_ARGS[@]}"}
    )
  fi
  "$ADMIN" reserve-send-permit \
    ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
    "${send_permit_args[@]}" \
    --inherited-lock-fd "$LOCK_FD" \
    >/dev/null || fail "send_permit_reserve_failed"
  SEND_PERMIT_RESERVED=1
  ATTEMPT_ID="$SEND_AUTHORIZATION_ID"
  safe_id "$ATTEMPT_ID" || fail "send_attempt_id_invalid"
  ARTIFACT_VERSION_ID="$EXPECTED_ARTIFACT_VERSION_ID"
  trap cleanup_send EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  if [[ -n "$SHADOW_ROOT" ]]; then
    PUBLIC_ROOT="$SHADOW_ROOT/public"
    PRIVATE_ROOT="$SHADOW_ROOT/private"
    STATE_ROOT="$SHADOW_ROOT/state"
    DATABASE_PATH="$SHADOW_ROOT/database/reddit_voc.sqlite3"
  else
    PUBLIC_ROOT="/opt/reddit-voc-site/outputs"
    PRIVATE_ROOT="/opt/reddit-voc-site/private"
    STATE_ROOT="/opt/reddit-voc-daily-report/state"
    DATABASE_PATH="/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3"
  fi
  [[ ! -L "$DATABASE_PATH" && -f "$DATABASE_PATH" ]] \
    || fail "report_database_invalid"
  ensure_mode755_public_directory "$PUBLIC_ROOT"
  for directory in "$PRIVATE_ROOT" "$STATE_ROOT"; do
    ensure_mode700_directory "$directory"
  done
  DELIVERY_LEDGER_ROOT="$STATE_ROOT/delivery"
  DELIVERY_LEDGER_RUN_ROOT="$DELIVERY_LEDGER_ROOT/$RUN_ID"
  ensure_mode700_directory "$DELIVERY_LEDGER_ROOT"
  ensure_mode700_directory "$DELIVERY_LEDGER_RUN_ROOT"
  materialize_result="$("$UPDATER" materialize-send-env \
    ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
    "${send_runtime_args[@]}" \
    --attempt-id "$ATTEMPT_ID" \
    --inherited-lock-fd "$LOCK_FD")" \
    || fail "send_runtime_env_materialize_failed"
  [[ "$(printf '%s\n' "$materialize_result" \
      | grep -c '^destination_mode=')" == "1" ]] \
    || fail "send_runtime_env_materialize_result_invalid"
  SEND_RUNTIME_MODE="$(printf '%s\n' "$materialize_result" \
    | sed -n 's/^destination_mode=//p')"
  [[ "$SEND_RUNTIME_MODE" == "single" || "$SEND_RUNTIME_MODE" == "dual" ]] \
    || fail "send_runtime_env_materialize_result_invalid"
  if [[ -n "$SHADOW_ROOT" ]]; then
    RUNTIME_ENV_PATH="$SHADOW_ROOT/control/runtime-env/$ATTEMPT_ID.env"
  else
    RUNTIME_ENV_PATH="/home/ubuntu/.reddit-voc/report-control/runtime-env/$ATTEMPT_ID.env"
  fi
  [[ ! -L "$RUNTIME_ENV_PATH" && -f "$RUNTIME_ENV_PATH" ]] \
    || fail "send_runtime_env_invalid"
  PHASE_MOUNT_ARGS+=(
    --mount "type=bind,src=$DATABASE_PATH,dst=$DATABASE_PATH"
    --mount "type=bind,src=$PUBLIC_ROOT,dst=$PUBLIC_ROOT,readonly"
    --mount "type=bind,src=$PRIVATE_ROOT,dst=$PRIVATE_ROOT,readonly"
    --mount "type=bind,src=$STATE_ROOT,dst=$STATE_ROOT,readonly"
    --mount "type=bind,src=$DELIVERY_LEDGER_RUN_ROOT,dst=$DELIVERY_LEDGER_RUN_ROOT"
    --mount "type=bind,src=$RUNTIME_ENV_PATH,dst=/run/secrets/reddit_voc_report.env,readonly"
  )
  send_wrapper_phase="send"
  if [[ "$SEND_RUNTIME_MODE" == "dual" ]]; then
    send_wrapper_phase="send-dual"
  fi
  CONTAINER_COMMAND=(
    bash /app/scripts/run_daily_report.sh "$send_wrapper_phase"
    --expected-artifact-version-id "$EXPECTED_ARTIFACT_VERSION_ID"
    --expected-bundle-sha256 "$EXPECTED_BUNDLE_SHA256"
    --expected-outbox-sha256 "$EXPECTED_OUTBOX_SHA256"
    --authorization-id "$SEND_AUTHORIZATION_ID"
  )
  if [[ "$AUTHORIZE_RESEND" == "1" ]]; then
    CONTAINER_COMMAND+=(--authorize-resend)
    for part in ${RESEND_PARTS[@]+"${RESEND_PARTS[@]}"}; do
      CONTAINER_COMMAND+=(--resend-part-index "$part")
    done
  fi
elif [[ "$operation" == "prepare" \
    || "$operation" == "scheduled-prepare" \
    || "$operation" == "scheduled-cycle" ]]; then
  if [[ "$SCHEDULED_PREPARE" == "1" ]]; then
    if [[ "$SCHEDULED_CYCLE" == "1" ]]; then
      schedule_reservation="$("$ADMIN" reserve-scheduled-cycle \
        ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
        ${SCHEDULE_TIME_ARGS[@]+"${SCHEDULE_TIME_ARGS[@]}"} \
        ${SCHEDULE_AUTHORITY_ARGS[@]+"${SCHEDULE_AUTHORITY_ARGS[@]}"} \
        --expected-release-sha256 "$RELEASE_SHA256" \
        --expected-launcher-sha256 "$LAUNCHER_SHA256" \
        --run-id "$RUN_ID" \
        --cycle-lease-fd "$CYCLE_LEASE_FD" \
        --inherited-lock-fd "$LOCK_FD")" \
        || fail "scheduled_cycle_reserve_failed"
      SCHEDULED_CYCLE_ID="$(printf '%s\n' "$schedule_reservation" \
        | sed -n 's/^cycle_id=//p')"
      [[ "$(printf '%s\n' "$schedule_reservation" \
        | grep -c '^cycle_id=')" == "1" ]] \
        || fail "scheduled_cycle_result_invalid"
      safe_id "$SCHEDULED_CYCLE_ID" || fail "scheduled_cycle_result_invalid"
    else
      schedule_reservation="$("$ADMIN" reserve-scheduled-prepare \
        ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
        --expected-release-sha256 "$RELEASE_SHA256" \
        --run-id "$RUN_ID" \
        --inherited-lock-fd "$LOCK_FD")" \
        || fail "schedule_permit_reserve_failed"
    fi
    PREPARE_ACTION_ID="$(printf '%s\n' "$schedule_reservation" \
      | sed -n 's/^authorization_id=//p')"
    [[ "$(printf '%s\n' "$schedule_reservation" \
      | grep -c '^authorization_id=')" == "1" ]] \
      || fail "schedule_permit_result_invalid"
    safe_id "$PREPARE_ACTION_ID" || fail "schedule_permit_result_invalid"
    PROVIDER_AUTHORIZATION_ID="$PREPARE_ACTION_ID"
    operation="prepare"
  else
    "$ADMIN" reserve-permit \
      ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
      --authorization-id "$PREPARE_ACTION_ID" \
      --expected-release-sha256 "$RELEASE_SHA256" \
      --run-id "$RUN_ID" \
      --inherited-lock-fd "$LOCK_FD" \
      >/dev/null || fail "prepare_permit_reserve_failed"
  fi
  PREPARE_PERMIT_RESERVED=1
  trap cleanup_prepare EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  if [[ "${REDDIT_VOC_LOCAL_TEST_MODE:-0}" == "1" \
      && -n "${REDDIT_VOC_LOCAL_ATTEMPT_ID:-}" \
      && -n "${REDDIT_VOC_LOCAL_ARTIFACT_VERSION_ID:-}" ]]; then
    ATTEMPT_ID="$REDDIT_VOC_LOCAL_ATTEMPT_ID"
    ARTIFACT_VERSION_ID="$REDDIT_VOC_LOCAL_ARTIFACT_VERSION_ID"
  else
    generated_identity="$("$PYTHON_BIN" - <<'PY'
from datetime import datetime, timezone
import secrets

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
print(f"attempt-{stamp}-{secrets.token_hex(8)}")
print(f"{stamp}-{secrets.token_hex(16)}")
PY
)" || fail "attempt_identity_generation_failed"
    ATTEMPT_ID="${generated_identity%%$'\n'*}"
    ARTIFACT_VERSION_ID="${generated_identity#*$'\n'}"
  fi
  safe_id "$ATTEMPT_ID" || fail "attempt_id_invalid"
  [[ "$ARTIFACT_VERSION_ID" =~ ^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}$ ]] \
    || fail "artifact_version_id_invalid"

  if [[ -n "$SHADOW_ROOT" ]]; then
    PUBLIC_ROOT="$SHADOW_ROOT/public"
    PRIVATE_ROOT="$SHADOW_ROOT/private"
    PUBLIC_STAGING_ROOT="$SHADOW_ROOT/public-staging"
    PRIVATE_STAGING_ROOT="$SHADOW_ROOT/private-staging"
    STATE_ROOT="$SHADOW_ROOT/state"
    BLOCKED_ROOT="$SHADOW_ROOT/blocked"
    HANDOFF_ROOT="$SHADOW_ROOT/handoff"
    PROVIDER_ATTEMPT_ROOT="$SHADOW_ROOT/provider-attempts"
    DATABASE_PATH="$SHADOW_ROOT/database/reddit_voc.sqlite3"
    KEY_PATH="$SHADOW_ROOT/secrets/deepseek-api-key"
  else
    PUBLIC_ROOT="/opt/reddit-voc-site/outputs"
    PRIVATE_ROOT="/opt/reddit-voc-site/private"
    PUBLIC_STAGING_ROOT="$PUBLIC_ROOT/.report-staging/$ATTEMPT_ID"
    PRIVATE_STAGING_ROOT="$PRIVATE_ROOT/.report-staging/$ATTEMPT_ID"
    STATE_ROOT="/opt/reddit-voc-daily-report/state"
    BLOCKED_ROOT="/opt/reddit-voc-daily-report/blocked"
    HANDOFF_ROOT="/opt/reddit-voc-daily-report/handoff"
    PROVIDER_ATTEMPT_ROOT="/home/ubuntu/.reddit-voc/report-control/provider-attempts"
    DATABASE_PATH="/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3"
    KEY_PATH="/home/ubuntu/.reddit-voc/secrets/deepseek-api-key"
  fi
  [[ ! -L "$DATABASE_PATH" && -f "$DATABASE_PATH" ]] || fail "report_database_invalid"
  ensure_mode755_public_directory "$PUBLIC_ROOT"
  for directory in \
    "$PRIVATE_ROOT" "$STATE_ROOT" "$BLOCKED_ROOT" \
    "$HANDOFF_ROOT" "$PROVIDER_ATTEMPT_ROOT"; do
    ensure_mode700_directory "$directory"
  done
  if [[ -n "$SHADOW_ROOT" ]]; then
    require_empty_mode700_directory "$PUBLIC_STAGING_ROOT"
    require_empty_mode700_directory "$PRIVATE_STAGING_ROOT"
  else
    ensure_mode700_directory "$PUBLIC_ROOT/.report-staging"
    ensure_mode700_directory "$PRIVATE_ROOT/.report-staging"
    [[ ! -e "$PUBLIC_STAGING_ROOT" && ! -L "$PUBLIC_STAGING_ROOT" ]] \
      || fail "public_staging_exists"
    [[ ! -e "$PRIVATE_STAGING_ROOT" && ! -L "$PRIVATE_STAGING_ROOT" ]] \
      || fail "private_staging_exists"
    mkdir -m 700 "$PUBLIC_STAGING_ROOT" || fail "public_staging_create_failed"
    mkdir -m 700 "$PRIVATE_STAGING_ROOT" || fail "private_staging_create_failed"
  fi
  ensure_mode700_directory "$HANDOFF_ROOT/$RUN_ID"
  [[ ! -e "$HANDOFF_ROOT/$RUN_ID/$ATTEMPT_ID" \
      && ! -L "$HANDOFF_ROOT/$RUN_ID/$ATTEMPT_ID" ]] \
    || fail "handoff_attempt_exists"
  mkdir -m 700 "$HANDOFF_ROOT/$RUN_ID/$ATTEMPT_ID" \
    || fail "handoff_attempt_create_failed"

  if [[ -n "$PROVIDER_AUTHORIZATION_ID" ]]; then
    if [[ "$PROVIDER_AUTHORIZATION_ID" != "$PREPARE_ACTION_ID" ]]; then
      "$ADMIN" reserve-permit \
        ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
        --authorization-id "$PROVIDER_AUTHORIZATION_ID" \
        --expected-release-sha256 "$RELEASE_SHA256" \
        --run-id "$RUN_ID" \
        --inherited-lock-fd "$LOCK_FD" \
        >/dev/null || fail "provider_permit_reserve_failed"
      PROVIDER_PERMIT_RESERVED=1
    fi
    "$ADMIN" bind-provider-attempt \
      ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
      --authorization-id "$PROVIDER_AUTHORIZATION_ID" \
      --prepare-action-authorization-id "$PREPARE_ACTION_ID" \
      --expected-release-sha256 "$RELEASE_SHA256" \
      --run-id "$RUN_ID" \
      --attempt-id "$ATTEMPT_ID" \
      --public-staging-root "$PUBLIC_STAGING_ROOT" \
      --private-staging-root "$PRIVATE_STAGING_ROOT" \
      --inherited-lock-fd "$LOCK_FD" \
      >/dev/null || fail "provider_attempt_bind_failed"
    "$UPDATER" check \
      ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
      --authorize-secret-provisioning \
      --check-key \
      --inherited-lock-fd "$LOCK_FD" \
      >/dev/null || fail "provider_key_metadata_invalid"
  fi

  prepare_provider_args=()
  if [[ -n "$PROVIDER_AUTHORIZATION_ID" ]]; then
    prepare_provider_args=(
      --provider-authorization-id "$PROVIDER_AUTHORIZATION_ID"
    )
  fi
  "$UPDATER" materialize-prepare-env \
    ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
    --authorization-id "$PREPARE_ACTION_ID" \
    --expected-release-sha256 "$RELEASE_SHA256" \
    --run-id "$RUN_ID" \
    --attempt-id "$ATTEMPT_ID" \
    --artifact-version-id "$ARTIFACT_VERSION_ID" \
    ${prepare_provider_args[@]+"${prepare_provider_args[@]}"} \
    --inherited-lock-fd "$LOCK_FD" \
    >/dev/null || fail "prepare_runtime_env_materialize_failed"
  if [[ -n "$SHADOW_ROOT" ]]; then
    RUNTIME_ENV_PATH="$SHADOW_ROOT/control/runtime-env/$ATTEMPT_ID.env"
  else
    RUNTIME_ENV_PATH="/home/ubuntu/.reddit-voc/report-control/runtime-env/$ATTEMPT_ID.env"
  fi
  [[ ! -L "$RUNTIME_ENV_PATH" && -f "$RUNTIME_ENV_PATH" ]] \
    || fail "prepare_runtime_env_invalid"

  PHASE_MOUNT_ARGS+=(
    --mount "type=bind,src=$DATABASE_PATH,dst=$DATABASE_PATH,readonly"
    --mount "type=bind,src=$PUBLIC_ROOT,dst=$PUBLIC_ROOT,readonly"
    --mount "type=bind,src=$PRIVATE_ROOT,dst=$PRIVATE_ROOT,readonly"
    --mount "type=bind,src=$STATE_ROOT,dst=$STATE_ROOT,readonly"
    --mount "type=bind,src=$BLOCKED_ROOT,dst=$BLOCKED_ROOT,readonly"
    --mount "type=bind,src=$HANDOFF_ROOT,dst=$HANDOFF_ROOT,readonly"
    --mount "type=bind,src=$PUBLIC_STAGING_ROOT,dst=$PUBLIC_STAGING_ROOT"
    --mount "type=bind,src=$PRIVATE_STAGING_ROOT,dst=$PRIVATE_STAGING_ROOT"
    --mount "type=bind,src=$HANDOFF_ROOT/$RUN_ID/$ATTEMPT_ID,dst=$HANDOFF_ROOT/$RUN_ID/$ATTEMPT_ID"
    --mount "type=bind,src=$PROVIDER_ATTEMPT_ROOT,dst=$PROVIDER_ATTEMPT_ROOT,readonly"
    --mount "type=bind,src=$RUNTIME_ENV_PATH,dst=/run/secrets/reddit_voc_report.env,readonly"
  )
  CONTAINER_COMMAND=(
    bash /app/scripts/run_daily_report.sh prepare
    --prepare-action-authorization-id "$PREPARE_ACTION_ID"
  )
  if [[ -n "$PROVIDER_AUTHORIZATION_ID" ]]; then
    PHASE_MOUNT_ARGS+=(
      --mount "type=bind,src=$PROVIDER_ATTEMPT_ROOT/$PROVIDER_AUTHORIZATION_ID,dst=$PROVIDER_ATTEMPT_ROOT/$PROVIDER_AUTHORIZATION_ID"
      --mount "type=bind,src=$KEY_PATH,dst=/run/secrets/deepseek_api_key,readonly"
    )
    CONTAINER_COMMAND+=(
      --provider-authorization-id "$PROVIDER_AUTHORIZATION_ID"
    )
  fi
fi

runtime_mount_args=()
while IFS= read -r relative; do
  [[ -n "$relative" ]] || fail "runtime_mount_manifest_invalid"
  runtime_mount_args+=(
    --mount "type=bind,src=$RELEASE_DIR/$relative,dst=/app/$relative,readonly"
  )
done < <("$PYTHON_BIN" - "$RELEASE_DIR/report-release-manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for entry in manifest["entries"]:
    if entry["role"] == "runtime":
        print(entry["path"])
PY
)
[[ ${#runtime_mount_args[@]} -gt 0 ]] || fail "runtime_mount_manifest_invalid"

if [[ -n "$SHADOW_ROOT" ]]; then
  CONTAINER_GATE_ROOT="$SHADOW_ROOT/control/container-gates"
elif [[ "${REDDIT_VOC_LOCAL_TEST_MODE:-0}" == "1" ]]; then
  CONTAINER_GATE_ROOT="${REDDIT_VOC_REPORT_CONTAINER_GATE_ROOT:-$(dirname "$CIDFILE")/container-gates}"
else
  CONTAINER_GATE_ROOT="/home/ubuntu/.reddit-voc/run/container-gates"
fi
ensure_mode700_directory "$CONTAINER_GATE_ROOT"
if [[ "$operation" == "prepare" ]]; then
  CONTAINER_GATE_ID="$ATTEMPT_ID"
else
  CONTAINER_GATE_ID="$operation-$RUN_ID"
fi
safe_id "$CONTAINER_GATE_ID" || fail "container_gate_id_invalid"
CONTAINER_GATE_DIR="$CONTAINER_GATE_ROOT/$CONTAINER_GATE_ID"
[[ ! -e "$CONTAINER_GATE_DIR" && ! -L "$CONTAINER_GATE_DIR" ]] \
  || fail "container_gate_exists"
mkdir -m 700 "$CONTAINER_GATE_DIR" || fail "container_gate_create_failed"
PHASE_MOUNT_ARGS+=(
  --mount "type=bind,src=$CONTAINER_GATE_DIR,dst=/run/report-gate,readonly"
)
GATED_CONTAINER_COMMAND=(
  -c
  'while [[ ! -f /run/report-gate/permit ]]; do sleep 0.05; done; exec "$@"'
  report-gate
  "${CONTAINER_COMMAND[@]}"
)
if [[ "$operation" == "smoke" || "$LOCAL_TEST_MODE" == "1" ]]; then
  CONTAINER_NETWORK="none"
fi
if [[ "$operation" == "smoke" ]]; then
  trap cleanup_prepare EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
fi

if [[ "$CONTAINER_NETWORK" != "none" ]]; then
  network_driver="$("$DOCKER_BIN" network inspect "$REPORT_NETWORK" --format '{{.Driver}}')" \
    || fail "report_network_missing"
  [[ "$network_driver" == "bridge" ]] || fail "report_network_invalid"
  network_members="$("$DOCKER_BIN" network inspect "$REPORT_NETWORK" --format '{{len .Containers}}')" \
    || fail "report_network_invalid"
  [[ "$network_members" == "0" ]] || fail "report_network_not_empty"
fi

rm -f "$CIDFILE"
container_id="$("$DOCKER_BIN" run -d --rm --pull=never \
  --cidfile "$CIDFILE" \
  --network "$CONTAINER_NETWORK" \
  --user "$REPORT_UID:$REPORT_GID" \
  --entrypoint /bin/bash \
  --cpus 1.0 \
  --memory 2g \
  --pids-limit 256 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --read-only \
  --tmpfs /tmp:rw,nodev,noexec,nosuid,size=128m \
  "${runtime_mount_args[@]}" \
  ${PHASE_MOUNT_ARGS[@]+"${PHASE_MOUNT_ARGS[@]}"} \
  "$IMAGE_ID" \
  "${GATED_CONTAINER_COMMAND[@]}")" \
  || fail "report_container_start_failed"
if [[ "$operation" == "send" ]]; then
  SEND_CONTAINER_STARTED=1
fi
[[ -n "$container_id" && -s "$CIDFILE" ]] || fail "report_container_identity_missing"
cidfile_id="$(tr -d '\r\n' <"$CIDFILE")" || fail "report_container_identity_missing"
[[ "$cidfile_id" == "$container_id" ]] || fail "report_container_identity_mismatch"
if [[ "${REDDIT_VOC_LOCAL_TEST_MODE:-0}" != "1" ]]; then
  [[ "$container_id" =~ ^[0-9a-f]{64}$ ]] || fail "report_container_identity_invalid"
fi

inspected_image="$("$DOCKER_BIN" inspect "$container_id" --format '{{.Image}}')" \
  || fail "report_container_inspect_failed"
[[ "$inspected_image" == "$IMAGE_ID" ]] || fail "report_container_image_mismatch"
inspected_user="$("$DOCKER_BIN" inspect "$container_id" --format '{{.Config.User}}')" \
  || fail "report_container_inspect_failed"
[[ "$inspected_user" == "$REPORT_UID:$REPORT_GID" ]] \
  || fail "report_container_user_mismatch"
inspected_nano_cpus="$("$DOCKER_BIN" inspect "$container_id" --format '{{.HostConfig.NanoCpus}}')" \
  || fail "report_container_inspect_failed"
inspected_memory="$("$DOCKER_BIN" inspect "$container_id" --format '{{.HostConfig.Memory}}')" \
  || fail "report_container_inspect_failed"
inspected_pids="$("$DOCKER_BIN" inspect "$container_id" --format '{{.HostConfig.PidsLimit}}')" \
  || fail "report_container_inspect_failed"
inspected_read_only="$("$DOCKER_BIN" inspect "$container_id" --format '{{.HostConfig.ReadonlyRootfs}}')" \
  || fail "report_container_inspect_failed"
inspected_network_mode="$("$DOCKER_BIN" inspect "$container_id" --format '{{.HostConfig.NetworkMode}}')" \
  || fail "report_container_inspect_failed"
inspected_cap_drop="$("$DOCKER_BIN" inspect "$container_id" --format '{{json .HostConfig.CapDrop}}')" \
  || fail "report_container_inspect_failed"
inspected_security_opt="$("$DOCKER_BIN" inspect "$container_id" --format '{{json .HostConfig.SecurityOpt}}')" \
  || fail "report_container_inspect_failed"
inspected_tmpfs="$("$DOCKER_BIN" inspect "$container_id" --format '{{json .HostConfig.Tmpfs}}')" \
  || fail "report_container_inspect_failed"
inspected_privileged="$("$DOCKER_BIN" inspect "$container_id" --format '{{.HostConfig.Privileged}}')" \
  || fail "report_container_inspect_failed"
inspected_pid_mode="$("$DOCKER_BIN" inspect "$container_id" --format '{{.HostConfig.PidMode}}')" \
  || fail "report_container_inspect_failed"
[[ "$inspected_nano_cpus" == "1000000000" \
    && "$inspected_memory" == "2147483648" \
    && "$inspected_pids" == "256" \
    && "$inspected_read_only" == "true" \
    && "$inspected_network_mode" == "$CONTAINER_NETWORK" ]] \
  || fail "report_container_limits_mismatch"
{
  printf '%s\0' \
    "$inspected_cap_drop" "$inspected_security_opt" "$inspected_tmpfs" \
    "$inspected_privileged" "$inspected_pid_mode"
} | "$PYTHON_BIN" -c '
import json
import sys

fields = sys.stdin.buffer.read(1024 * 1024 + 1).split(b"\0")
if len(fields) != 6 or fields[-1] or len(b"\0".join(fields)) > 1024 * 1024:
    raise SystemExit(1)
try:
    cap_drop, security_opt, tmpfs = (
        json.loads(value.decode("utf-8")) for value in fields[:3]
    )
    privileged = fields[3].decode("ascii")
    pid_mode = fields[4].decode("ascii")
except (UnicodeError, ValueError):
    raise SystemExit(1)
if cap_drop != ["ALL"] or security_opt != ["no-new-privileges:true"]:
    raise SystemExit(1)
if tmpfs not in (
    {"/tmp": "rw,nodev,noexec,nosuid,size=128m"},
    {"/tmp": "rw,nodev,noexec,nosuid,size=134217728"},
):
    raise SystemExit(1)
if privileged != "false" or pid_mode != "":
    raise SystemExit(1)
' || fail "report_container_security_mismatch"
inspected_mounts="$("$DOCKER_BIN" inspect "$container_id" --format '{{json .Mounts}}')" \
  || fail "report_container_inspect_failed"
inspected_networks="$("$DOCKER_BIN" inspect "$container_id" --format '{{json .NetworkSettings.Networks}}')" \
  || fail "report_container_inspect_failed"
image_env="$("$DOCKER_BIN" image inspect "$IMAGE_ID" --format '{{json .Config.Env}}')" \
  || fail "report_image_inspect_failed"
inspected_env="$("$DOCKER_BIN" inspect "$container_id" --format '{{json .Config.Env}}')" \
  || fail "report_container_inspect_failed"
inspected_entrypoint="$("$DOCKER_BIN" inspect "$container_id" --format '{{json .Config.Entrypoint}}')" \
  || fail "report_container_inspect_failed"
inspected_command="$("$DOCKER_BIN" inspect "$container_id" --format '{{json .Config.Cmd}}')" \
  || fail "report_container_inspect_failed"

expected_mount_specs=()
all_mount_args=(
  "${runtime_mount_args[@]}"
  ${PHASE_MOUNT_ARGS[@]+"${PHASE_MOUNT_ARGS[@]}"}
)
for ((mount_index = 0; mount_index < ${#all_mount_args[@]}; mount_index += 2)); do
  [[ "${all_mount_args[$mount_index]}" == "--mount" \
      && $((mount_index + 1)) -lt ${#all_mount_args[@]} ]] \
    || fail "report_mount_contract_invalid"
  expected_mount_specs+=("${all_mount_args[$((mount_index + 1))]}")
done
"$PYTHON_BIN" - "$inspected_mounts" "${expected_mount_specs[@]}" <<'PY' \
  || fail "report_container_mount_mismatch"
import json
import sys

try:
    actual_raw = json.loads(sys.argv[1])
except (TypeError, ValueError):
    raise SystemExit(1)
if not isinstance(actual_raw, list):
    raise SystemExit(1)
actual = []
for item in actual_raw:
    if not isinstance(item, dict):
        raise SystemExit(1)
    actual.append(
        (
            item.get("Type"),
            item.get("Source"),
            item.get("Destination"),
            item.get("RW"),
        )
    )
expected = []
for specification in sys.argv[2:]:
    values = {}
    readonly = False
    for token in specification.split(","):
        if token == "readonly":
            readonly = True
        elif "=" in token:
            key, value = token.split("=", 1)
            values[key] = value
        else:
            raise SystemExit(1)
    if values.get("type") != "bind" or set(values) != {"type", "src", "dst"}:
        raise SystemExit(1)
    expected.append(("bind", values["src"], values["dst"], not readonly))
if len(actual) != len(expected) or len(set(actual)) != len(actual):
    raise SystemExit(1)
if sorted(actual) != sorted(expected):
    raise SystemExit(1)
PY
{
  printf '%s\0' \
    "$inspected_networks" "$image_env" "$inspected_env" \
    "$inspected_entrypoint" "$inspected_command"
} | "$PYTHON_BIN" -c '
import json
import re
import sys

try:
    payload = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
    if len(payload) > 4 * 1024 * 1024:
        raise ValueError("metadata_too_large")
    fields = payload.split(b"\0")
    if len(fields) != 6 or fields[-1]:
        raise ValueError("metadata_shape")
    networks, image_environment, environment, entrypoint, command = (
        json.loads(field.decode("utf-8")) for field in fields[:-1]
    )
except (TypeError, UnicodeError, ValueError):
    raise SystemExit(1)
if not isinstance(networks, dict):
    raise SystemExit(1)
expected_networks = set() if sys.argv[1] == "none" else {sys.argv[1]}
if set(networks) != expected_networks:
    raise SystemExit(1)
if image_environment is None:
    image_environment = []
if environment is None:
    environment = []
if (
    not isinstance(image_environment, list)
    or not isinstance(environment, list)
    or any(not isinstance(item, str) for item in image_environment)
    or any(not isinstance(item, str) for item in environment)
    or environment != image_environment
):
    raise SystemExit(1)
allowed_baked_reddit_voc_names = {
    "REDDIT_VOC_CHROMIUM_PATH",
    "REDDIT_VOC_WEB_HOST",
    "REDDIT_VOC_WEB_PORT",
    "REDDIT_VOC_SITE_ROOT",
    "REDDIT_VOC_DATA_DIR",
    "REDDIT_VOC_OUTPUT_DIR",
    "REDDIT_VOC_CONFIG_DIR",
    "REDDIT_VOC_DOCS_DIR",
}
for item in environment:
    name = item.split("=", 1)[0].upper()
    if name.startswith(("DEEPSEEK_", "DINGTALK_")):
        raise SystemExit(1)
    if name.startswith("REDDIT_VOC_") and name not in allowed_baked_reddit_voc_names:
        raise SystemExit(1)
if entrypoint != ["/bin/bash"]:
    raise SystemExit(1)
if command != sys.argv[2:]:
    raise SystemExit(1)
' "$CONTAINER_NETWORK" "${GATED_CONTAINER_COMMAND[@]}" \
  || fail "report_container_metadata_mismatch"
if [[ "$CONTAINER_NETWORK" != "none" ]]; then
  during_members="$("$DOCKER_BIN" network inspect "$REPORT_NETWORK" --format '{{json .Containers}}')" \
    || fail "report_network_invalid"
  "$PYTHON_BIN" - "$during_members" "$container_id" <<'PY' \
    || fail "report_network_member_mismatch"
import json
import sys

try:
    members = json.loads(sys.argv[1])
except (TypeError, ValueError):
    raise SystemExit(1)
if not isinstance(members, dict) or set(members) != {sys.argv[2]}:
    raise SystemExit(1)
PY
fi
WAIT_RESULT_PATH="$CIDFILE.$CONTAINER_GATE_ID.wait"
[[ ! -e "$WAIT_RESULT_PATH" && ! -L "$WAIT_RESULT_PATH" ]] \
  || fail "report_container_wait_state_exists"
"$PYTHON_BIN" - \
  "$REPORT_TIMEOUT_SECONDS" "$DOCKER_BIN" "$container_id" <<'PY' \
  >"$WAIT_RESULT_PATH" &
import subprocess
import sys

try:
    completed = subprocess.run(
        [sys.argv[2], "wait", sys.argv[3]],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=int(sys.argv[1]),
        check=False,
    )
except subprocess.TimeoutExpired:
    raise SystemExit(124)
sys.stdout.buffer.write(completed.stdout)
raise SystemExit(completed.returncode)
PY
container_wait_pid=$!
permit_path="$CONTAINER_GATE_DIR/permit"
if [[ "$operation" == "send" && -n "$SCHEDULED_CYCLE_ID" ]]; then
  "$ADMIN" validate-send-permit-use \
    ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
    "${send_permit_args[@]}" \
    --inherited-lock-fd "$LOCK_FD" \
    >/dev/null || fail "scheduled_send_window_expired"
fi
"$PYTHON_BIN" - \
  "$permit_path" "$container_id" "$IMAGE_ID" "$RELEASE_SHA256" <<'PY' \
  || fail "report_container_permit_create_failed"
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.dumps(
    {
        "schema_version": "report-container-permit-v1",
        "container_id": sys.argv[2],
        "image_id": sys.argv[3],
        "release_sha256": sys.argv[4],
    },
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(path, flags, 0o600)
try:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("permit_write_failed")
        view = view[written:]
    os.fsync(descriptor)
finally:
    os.close(descriptor)
os.chmod(path, 0o600)
directory = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY

set +e
container_logs="$("$PYTHON_BIN" - \
  "$REPORT_TIMEOUT_SECONDS" "$DOCKER_BIN" "$container_id" <<'PY'
import subprocess
import sys

try:
    completed = subprocess.run(
        [sys.argv[2], "logs", "-f", sys.argv[3]],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=int(sys.argv[1]),
        check=False,
    )
except subprocess.TimeoutExpired:
    raise SystemExit(124)
if len(completed.stdout) > 4 * 1024 * 1024:
    raise SystemExit(125)
sys.stdout.buffer.write(completed.stdout)
raise SystemExit(completed.returncode)
PY
)"
logs_status=$?
set -e
[[ "$logs_status" != "124" ]] || fail "report_container_timeout"
[[ "$logs_status" != "125" ]] || fail "report_container_log_too_large"
[[ "$logs_status" == "0" ]] || fail "report_container_logs_failed"
set +e
wait "$container_wait_pid"
wait_status=$?
set -e
container_wait_pid=""
[[ "$wait_status" != "124" ]] || fail "report_container_timeout"
[[ "$wait_status" == "0" ]] || fail "report_container_wait_failed"
[[ ! -L "$WAIT_RESULT_PATH" && -f "$WAIT_RESULT_PATH" ]] \
  || fail "report_container_wait_state_invalid"
exit_code="$(tr -d '\r\n' <"$WAIT_RESULT_PATH")" \
  || fail "report_container_wait_state_invalid"
rm -f "$WAIT_RESULT_PATH" || fail "report_container_wait_state_cleanup_failed"
WAIT_RESULT_PATH=""
[[ "$exit_code" =~ ^[0-9]+$ ]] || fail "report_container_exit_code_invalid"
container_id=""
if [[ "$CONTAINER_NETWORK" != "none" ]]; then
  final_members="$("$DOCKER_BIN" network inspect "$REPORT_NETWORK" --format '{{len .Containers}}')" \
    || fail "report_network_invalid"
  [[ "$final_members" == "0" ]] || fail "report_network_cleanup_failed"
fi
rm -f "$permit_path" || fail "report_container_gate_cleanup_failed"
rmdir "$CONTAINER_GATE_DIR" || fail "report_container_gate_cleanup_failed"
CONTAINER_GATE_DIR=""
rm -f "$CIDFILE" || fail "report_container_identity_cleanup_failed"

if [[ "$operation" == "prepare" ]]; then
  parsed_result="$(printf '%s\n' "$container_logs" | "$PYTHON_BIN" -c '
import json
import re
import sys

value = None
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        candidate = json.loads(line)
    except ValueError:
        continue
    if isinstance(candidate, dict) and candidate.get("status") in {"complete", "blocked"}:
        value = candidate
if value is None:
    raise SystemExit(1)
fields = [
    value.get("status"),
    value.get("run_id"),
    value.get("attempt_id"),
    value.get("artifact_version_id") or "-",
    value.get("bundle_sha256") or "-",
    value.get("outbox_sha256") or "-",
    value.get("commit_request_sha256") or "-",
    value.get("provider_authorization_id") or "-",
    value.get("blocked_manifest_sha256") or "-",
]
for name in ("translation_provider_call", "translation_provider_attempt_made"):
    item = value.get(name)
    if not isinstance(item, bool):
        raise SystemExit(1)
    fields.append("true" if item else "false")
if any(not isinstance(item, str) or "\t" in item or "\n" in item for item in fields):
    raise SystemExit(1)
print("\t".join(fields))
')" || fail "prepare_result_invalid"
  IFS=$'\t' read -r \
    PREPARE_STATUS RESULT_RUN_ID RESULT_ATTEMPT_ID RESULT_VERSION \
    RESULT_BUNDLE RESULT_OUTBOX RESULT_COMMIT_REQUEST RESULT_PROVIDER \
    RESULT_BLOCKED_SHA RESULT_PROVIDER_CALL RESULT_PROVIDER_ATTEMPT \
    <<<"$parsed_result"
  [[ "$RESULT_RUN_ID" == "$RUN_ID" && "$RESULT_ATTEMPT_ID" == "$ATTEMPT_ID" ]] \
    || fail "prepare_result_identity_mismatch"

  provider_commit_args=()
  if [[ "$RESULT_PROVIDER" != "-" ]]; then
    [[ "$RESULT_PROVIDER" == "$PROVIDER_AUTHORIZATION_ID" ]] \
      || fail "prepare_result_provider_mismatch"
    provider_commit_args=(--provider-authorization-id "$RESULT_PROVIDER")
  elif [[ -n "$PROVIDER_AUTHORIZATION_ID" ]]; then
    if [[ "$PROVIDER_AUTHORIZATION_ID" != "$PREPARE_ACTION_ID" ]]; then
      "$ADMIN" terminalize-permit \
        ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
        --authorization-id "$PROVIDER_AUTHORIZATION_ID" \
        --expected-release-sha256 "$RELEASE_SHA256" \
        --terminal-status closed_no_attempt \
        --inherited-lock-fd "$LOCK_FD" \
        >/dev/null || fail "provider_permit_terminalize_failed"
      PROVIDER_PERMIT_RESERVED=0
    fi
  fi

  prepared_root_args=(
    --public-root "$PUBLIC_ROOT"
    --private-root "$PRIVATE_ROOT"
    --public-staging-root "$PUBLIC_STAGING_ROOT"
    --private-staging-root "$PRIVATE_STAGING_ROOT"
    --state-root "$STATE_ROOT"
    --blocked-root "$BLOCKED_ROOT"
    --handoff-root "$HANDOFF_ROOT"
  )
  if [[ "$PREPARE_STATUS" == "complete" ]]; then
    [[ "$exit_code" == "0" ]] || fail "prepare_complete_exit_code_invalid"
    [[ "$RESULT_VERSION" == "$ARTIFACT_VERSION_ID" \
        && "$RESULT_BUNDLE" =~ ^[0-9a-f]{64}$ \
        && "$RESULT_OUTBOX" =~ ^[0-9a-f]{64}$ \
        && "$RESULT_COMMIT_REQUEST" =~ ^[0-9a-f]{64}$ ]] \
      || fail "prepare_complete_tuple_invalid"
    scheduled_commit_args=()
    if [[ "$SCHEDULED_CYCLE" == "1" ]]; then
      scheduled_commit_args=(
        --cycle-id "$SCHEDULED_CYCLE_ID"
        --cycle-lease-fd "$CYCLE_LEASE_FD"
      )
    fi
    "$ADMIN" commit-prepared \
      ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
      "${prepared_root_args[@]}" \
      ${provider_commit_args[@]+"${provider_commit_args[@]}"} \
      ${scheduled_commit_args[@]+"${scheduled_commit_args[@]}"} \
      --release-dir "$RELEASE_DIR" \
      --config-root "$RELEASE_DIR/config" \
      --authorization-id "$PREPARE_ACTION_ID" \
      --expected-release-sha256 "$RELEASE_SHA256" \
      --run-id "$RUN_ID" \
      --attempt-id "$ATTEMPT_ID" \
      --expected-artifact-version-id "$ARTIFACT_VERSION_ID" \
      --expected-bundle-sha256 "$RESULT_BUNDLE" \
      --expected-outbox-sha256 "$RESULT_OUTBOX" \
      --expected-commit-request-sha256 "$RESULT_COMMIT_REQUEST" \
      --inherited-lock-fd "$LOCK_FD" \
      >/dev/null || fail "host_prepared_commit_failed"
    if [[ "$SCHEDULED_CYCLE" == "1" ]]; then
      derived_send="$("$ADMIN" derive-scheduled-send-permit \
        ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
        ${SCHEDULE_TIME_ARGS[@]+"${SCHEDULE_TIME_ARGS[@]}"} \
        ${SCHEDULE_AUTHORITY_ARGS[@]+"${SCHEDULE_AUTHORITY_ARGS[@]}"} \
        "${prepared_root_args[@]}" \
        --release-dir "$RELEASE_DIR" \
        --config-root "$RELEASE_DIR/config" \
        --expected-release-sha256 "$RELEASE_SHA256" \
        --expected-launcher-sha256 "$LAUNCHER_SHA256" \
        --run-id "$RUN_ID" \
        --cycle-id "$SCHEDULED_CYCLE_ID" \
        --cycle-lease-fd "$CYCLE_LEASE_FD" \
        --prepare-action-authorization-id "$PREPARE_ACTION_ID" \
        --attempt-id "$ATTEMPT_ID" \
        --expected-artifact-version-id "$ARTIFACT_VERSION_ID" \
        --expected-bundle-sha256 "$RESULT_BUNDLE" \
        --expected-outbox-sha256 "$RESULT_OUTBOX" \
        --expected-commit-request-sha256 "$RESULT_COMMIT_REQUEST" \
        --inherited-lock-fd "$LOCK_FD")" \
        || fail "scheduled_send_permit_derive_failed"
      SEND_AUTHORIZATION_ID="$(printf '%s\n' "$derived_send" \
        | sed -n 's/^authorization_id=//p')"
      [[ "$(printf '%s\n' "$derived_send" \
        | grep -c '^authorization_id=')" == "1" ]] \
        || fail "scheduled_send_permit_result_invalid"
      safe_id "$SEND_AUTHORIZATION_ID" \
        || fail "scheduled_send_permit_result_invalid"
    fi
    PREPARE_PERMIT_RESERVED=0
    PROVIDER_PERMIT_RESERVED=0
    final_status="complete"
  else
    [[ "$exit_code" == "1" ]] || fail "prepare_blocked_exit_code_invalid"
    [[ "$RESULT_BLOCKED_SHA" =~ ^[0-9a-f]{64}$ ]] \
      || fail "prepare_blocked_tuple_invalid"
    "$ADMIN" commit-blocked \
      ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
      "${prepared_root_args[@]}" \
      ${provider_commit_args[@]+"${provider_commit_args[@]}"} \
      --release-dir "$RELEASE_DIR" \
      --config-root "$RELEASE_DIR/config" \
      --authorization-id "$PREPARE_ACTION_ID" \
      --expected-release-sha256 "$RELEASE_SHA256" \
      --run-id "$RUN_ID" \
      --attempt-id "$ATTEMPT_ID" \
      --expected-blocked-manifest-sha256 "$RESULT_BLOCKED_SHA" \
      --inherited-lock-fd "$LOCK_FD" \
      >/dev/null || fail "host_blocked_commit_failed"
    if [[ "$SCHEDULED_CYCLE" == "1" ]]; then
      "$ADMIN" terminalize-scheduled-prepare \
        ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
        --cycle-id "$SCHEDULED_CYCLE_ID" \
        --cycle-lease-fd "$CYCLE_LEASE_FD" \
        --prepare-action-authorization-id "$PREPARE_ACTION_ID" \
        --expected-release-sha256 "$RELEASE_SHA256" \
        --run-id "$RUN_ID" \
        --terminal-status blocked \
        --inherited-lock-fd "$LOCK_FD" \
        >/dev/null || fail "scheduled_prepare_terminalize_failed"
    fi
    PREPARE_PERMIT_RESERVED=0
    PROVIDER_PERMIT_RESERVED=0
    final_status="blocked"
  fi
  "$UPDATER" remove-runtime-env \
    ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
    --attempt-id "$ATTEMPT_ID" \
    --inherited-lock-fd "$LOCK_FD" \
    >/dev/null || fail "prepare_runtime_env_remove_failed"
  RUNTIME_ENV_PATH=""
  trap - EXIT INT TERM
  if [[ "$final_status" == "complete" && "$SCHEDULED_CYCLE" == "1" ]]; then
    exec env \
      REDDIT_VOC_ENABLE_HOST_LAUNCH=1 \
      REDDIT_VOC_INHERITED_LOCK_FD="$LOCK_FD" \
      REDDIT_VOC_RUN_ID="$RUN_ID" \
      "$RELEASE_DIR/scripts/server_daily_report.sh" send \
      --authorize-host-launch \
      --authorization-id "$SEND_AUTHORIZATION_ID" \
      --expected-artifact-version-id "$ARTIFACT_VERSION_ID" \
      --expected-bundle-sha256 "$RESULT_BUNDLE" \
      --expected-outbox-sha256 "$RESULT_OUTBOX" \
      --scheduled-cycle-id "$SCHEDULED_CYCLE_ID" \
      --cycle-lease-fd "$CYCLE_LEASE_FD"
  fi
  printf 'status=%s\nrun_id=%s\nattempt_id=%s\nprovider_call=%s\ntranslation_provider_attempt_made=%s\nreport_live_send=false\nalert_live_send=false\nlive_send=false\n' \
    "$final_status" "$RUN_ID" "$ATTEMPT_ID" \
    "$RESULT_PROVIDER_CALL" "$RESULT_PROVIDER_ATTEMPT"
  if [[ "$final_status" == "blocked" ]]; then
    exit 1
  fi
elif [[ "$operation" == "send" ]]; then
  parsed_result="$(printf '%s\n' "$container_logs" | "$PYTHON_BIN" -c '
import json
import re
import sys

mode = sys.argv[1]
value = None
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        candidate = json.loads(line)
    except ValueError:
        continue
    if isinstance(candidate, dict) and isinstance(candidate.get("status"), str):
        value = candidate
if value is None:
    raise SystemExit(1)
for name in ("report_live_send", "alert_live_send", "live_send"):
    if not isinstance(value.get(name), bool):
        raise SystemExit(1)
status = value["status"]
if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", status):
    raise SystemExit(1)
primary_status = secondary_status = primary_tip = secondary_tip = "-"
attempt_count = 0

def indexes(item, name):
    result = item.get(name)
    if (
        not isinstance(result, list)
        or any(type(part) is not int or part < 1 for part in result)
        or len(result) != len(set(result))
    ):
        raise SystemExit(1)
    return result

if mode == "single":
    attempted = indexes(value, "attempted_part_indexes")
    sent = indexes(value, "sent_part_indexes")
    rejected = indexes(value, "rejected_part_indexes")
    attempt_count = len(attempted)
    if status == "sent" and (
        not attempted
        or attempted != sent
        or rejected
        or not value["report_live_send"]
        or not value["live_send"]
    ):
        raise SystemExit(1)
elif mode == "dual":
    destinations = value.get("destinations")
    if not isinstance(destinations, list) or len(destinations) not in {0, 2}:
        raise SystemExit(1)
    allowed = {
        "sent",
        "partially_sent",
        "partial_unknown_delivery_state",
        "unknown_delivery_state",
        "rejected",
        "blocked",
    }
    if status not in allowed or value["alert_live_send"]:
        raise SystemExit(1)
    if not destinations:
        if status != "blocked" or value["report_live_send"] or value["live_send"]:
            raise SystemExit(1)
    else:
        expected_ids = ("primary", "secondary")
        destination_statuses = []
        destination_tips = []
        any_report_live = False
        for expected_id, item in zip(expected_ids, destinations, strict=True):
            if not isinstance(item, dict) or item.get("destination_id") != expected_id:
                raise SystemExit(1)
            attempted = indexes(item, "attempted_part_indexes")
            indexes(item, "sent_part_indexes")
            indexes(item, "rejected_part_indexes")
            if not isinstance(item.get("report_live_send"), bool):
                raise SystemExit(1)
            destination_status = item.get("status")
            if not isinstance(destination_status, str) or not re.fullmatch(
                r"[a-z][a-z0-9_]{0,127}", destination_status
            ):
                raise SystemExit(1)
            tip = item.get("ledger_tip_after")
            if tip is not None and (
                not isinstance(tip, str)
                or re.fullmatch(r"[0-9a-f]{64}", tip) is None
            ):
                raise SystemExit(1)
            if destination_status in {
                "sent", "already_sent", "rejected", "unknown_delivery_state"
            } and tip is None:
                raise SystemExit(1)
            attempt_count += len(attempted)
            any_report_live = any_report_live or item["report_live_send"]
            destination_statuses.append(destination_status)
            destination_tips.append(tip or "-")
        successful = sum(
            item in {"sent", "already_sent"} for item in destination_statuses
        )
        status_set = set(destination_statuses)
        if successful == 2:
            expected_status = "sent"
        elif "unknown_delivery_state" in status_set and successful:
            expected_status = "partial_unknown_delivery_state"
        elif "unknown_delivery_state" in status_set:
            expected_status = "unknown_delivery_state"
        elif successful:
            expected_status = "partially_sent"
        elif status_set == {"rejected"}:
            expected_status = "rejected"
        else:
            expected_status = "blocked"
        if (
            status != expected_status
            or value["report_live_send"] != any_report_live
            or value["live_send"] != any_report_live
        ):
            raise SystemExit(1)
        primary_status, secondary_status = destination_statuses
        primary_tip, secondary_tip = destination_tips
        if status == "sent" and not value["live_send"]:
            raise SystemExit(1)
else:
    raise SystemExit(1)
fields = [
    status,
    value.get("run_id"),
    value.get("artifact_version_id"),
    value.get("outbox_sha256"),
    str(attempt_count),
    "true" if value["report_live_send"] else "false",
    "true" if value["alert_live_send"] else "false",
    "true" if value["live_send"] else "false",
    primary_status,
    secondary_status,
    primary_tip,
    secondary_tip,
]
if any(not isinstance(item, str) or "\t" in item or "\n" in item for item in fields):
    raise SystemExit(1)
print("\t".join(fields))
' "$SEND_RUNTIME_MODE")" || fail "send_result_invalid"
  IFS=$'\t' read -r \
    SEND_STATUS RESULT_RUN_ID RESULT_VERSION RESULT_OUTBOX \
    RESULT_ATTEMPT_COUNT RESULT_REPORT_LIVE RESULT_ALERT_LIVE RESULT_LIVE \
    PRIMARY_DELIVERY_STATUS SECONDARY_DELIVERY_STATUS \
    PRIMARY_LEDGER_TIP SECONDARY_LEDGER_TIP \
    <<<"$parsed_result"
  [[ "$RESULT_RUN_ID" == "$RUN_ID" \
      && "$RESULT_VERSION" == "$EXPECTED_ARTIFACT_VERSION_ID" \
      && "$RESULT_OUTBOX" == "$EXPECTED_OUTBOX_SHA256" ]] \
    || fail "send_result_identity_mismatch"
  [[ "$exit_code" == "0" || "$exit_code" == "1" ]] \
    || fail "send_exit_code_invalid"
  send_terminal_status="closed_no_attempt"
  if [[ "$SEND_STATUS" == "sent" ]]; then
    [[ "$exit_code" == "0" ]] || fail "send_sent_exit_code_invalid"
    send_terminal_status="consumed"
  elif [[ "$SEND_STATUS" == "partially_sent" ]]; then
    [[ "$SEND_RUNTIME_MODE" == "dual" ]] || fail "send_result_invalid"
    send_terminal_status="partial"
  elif [[ "$SEND_STATUS" == "partial_unknown_delivery_state" \
      || "$SEND_STATUS" == "unknown_delivery_state" ]]; then
    if [[ "$SEND_RUNTIME_MODE" == "single" ]]; then
      [[ "$RESULT_ATTEMPT_COUNT" -gt 0 ]] || fail "send_result_invalid"
    fi
    send_terminal_status="unknown"
  elif [[ "$RESULT_ATTEMPT_COUNT" -gt 0 ]]; then
    send_terminal_status="blocked"
  fi
  "$UPDATER" remove-runtime-env \
    ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"} \
    --attempt-id "$ATTEMPT_ID" \
    --inherited-lock-fd "$LOCK_FD" \
    >/dev/null || fail "send_runtime_env_remove_failed"
  RUNTIME_ENV_PATH=""
  terminal_args=(
    terminalize-send-permit
    ${CONTROL_SCOPE_ARGS[@]+"${CONTROL_SCOPE_ARGS[@]}"}
    "${send_permit_args[@]}"
    --terminal-status "$send_terminal_status"
    --inherited-lock-fd "$LOCK_FD"
  )
  if [[ "$SEND_RUNTIME_MODE" == "dual" \
      && "$PRIMARY_DELIVERY_STATUS" != "-" ]]; then
    terminal_args+=(
      --delivery-status "$SEND_STATUS"
      --primary-delivery-status "$PRIMARY_DELIVERY_STATUS"
      --secondary-delivery-status "$SECONDARY_DELIVERY_STATUS"
    )
    if [[ "$PRIMARY_LEDGER_TIP" != "-" ]]; then
      terminal_args+=(--primary-ledger-tip "$PRIMARY_LEDGER_TIP")
    fi
    if [[ "$SECONDARY_LEDGER_TIP" != "-" ]]; then
      terminal_args+=(--secondary-ledger-tip "$SECONDARY_LEDGER_TIP")
    fi
  fi
  "$ADMIN" "${terminal_args[@]}" \
    >/dev/null || fail "send_permit_terminalize_failed"
  SEND_PERMIT_RESERVED=0
  trap - EXIT INT TERM
  printf 'status=%s\nrun_id=%s\nartifact_version_id=%s\noutbox_sha256=%s\ndestination_mode=%s\nreport_live_send=%s\nalert_live_send=%s\nlive_send=%s\nprovider_call=false\ntranslation_provider_attempt_made=false\n' \
    "$SEND_STATUS" "$RUN_ID" "$EXPECTED_ARTIFACT_VERSION_ID" \
    "$EXPECTED_OUTBOX_SHA256" "$SEND_RUNTIME_MODE" "$RESULT_REPORT_LIVE" \
    "$RESULT_ALERT_LIVE" "$RESULT_LIVE"
  if [[ "$SEND_STATUS" != "sent" ]]; then
    exit 1
  fi
else
  [[ "$exit_code" == "0" ]] || fail "report_container_failed"
  printf 'status=complete\nrun_id=%s\nprovider_call=false\ntranslation_provider_attempt_made=false\nreport_live_send=false\nalert_live_send=false\nlive_send=false\n' "$RUN_ID"
fi
