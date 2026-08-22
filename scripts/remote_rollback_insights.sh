#!/usr/bin/env bash
set -euo pipefail
ORIGINAL_ARGUMENTS=("$@")

usage() {
  cat >&2 <<'EOF'
usage:
  remote_rollback_insights.sh release --expected-current <sha256> --target-release <sha256> \
    --expected-current-data-release <id> --expected-current-data-pointer-sha <sha256> \
    --target-data-release <id> --target-data-pointer-sha <sha256> \
    --promotion-receipt <path> --promotion-receipt-sha <sha256> \
    --authorization-packet <path> --authorization-packet-sha <sha256> \
    --authorization-permit <path> --authorization-permit-sha <sha256> \
    --production-baseline <path> --production-baseline-sha <sha256> --patch-script <path>
EOF
}

if [[ "$#" -lt 1 ]]; then
  usage
  exit 1
fi

ACTION="$1"
shift
EXPECTED_CURRENT=""
TARGET_RELEASE=""
PATCH_SCRIPT=""
EXPECTED_CURRENT_DATA_RELEASE=""
EXPECTED_CURRENT_DATA_POINTER_SHA=""
TARGET_DATA_RELEASE=""
TARGET_DATA_POINTER_SHA=""
PROMOTION_RECEIPT_INPUT=""
PROMOTION_RECEIPT_SHA_INPUT=""
AUTHORIZATION_PACKET_INPUT=""
AUTHORIZATION_PACKET_SHA_INPUT=""
AUTHORIZATION_PERMIT_INPUT=""
AUTHORIZATION_PERMIT_SHA_INPUT=""
PRODUCTION_BASELINE_INPUT=""
PRODUCTION_BASELINE_SHA_INPUT=""

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --expected-current)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      EXPECTED_CURRENT="$2"
      shift 2
      ;;
    --target-release)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      TARGET_RELEASE="$2"
      shift 2
      ;;
    --patch-script)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      PATCH_SCRIPT="$2"
      shift 2
      ;;
    --expected-current-data-release)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      EXPECTED_CURRENT_DATA_RELEASE="$2"
      shift 2
      ;;
    --expected-current-data-pointer-sha)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      EXPECTED_CURRENT_DATA_POINTER_SHA="$2"
      shift 2
      ;;
    --target-data-release)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      TARGET_DATA_RELEASE="$2"
      shift 2
      ;;
    --target-data-pointer-sha)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      TARGET_DATA_POINTER_SHA="$2"
      shift 2
      ;;
    --promotion-receipt)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      PROMOTION_RECEIPT_INPUT="$2"
      shift 2
      ;;
    --promotion-receipt-sha|--promotion-receipt-sha256)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      PROMOTION_RECEIPT_SHA_INPUT="$2"
      shift 2
      ;;
    --authorization-packet)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      AUTHORIZATION_PACKET_INPUT="$2"
      shift 2
      ;;
    --authorization-packet-sha|--authorization-packet-sha256)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      AUTHORIZATION_PACKET_SHA_INPUT="$2"
      shift 2
      ;;
    --authorization-permit)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      AUTHORIZATION_PERMIT_INPUT="$2"
      shift 2
      ;;
    --authorization-permit-sha|--authorization-permit-sha256)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      AUTHORIZATION_PERMIT_SHA_INPUT="$2"
      shift 2
      ;;
    --production-baseline)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      PRODUCTION_BASELINE_INPUT="$2"
      shift 2
      ;;
    --production-baseline-sha|--production-baseline-sha256)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      PRODUCTION_BASELINE_SHA_INPUT="$2"
      shift 2
      ;;
    *)
      usage
      exit 1
      ;;
  esac
done

if [[ "${ACTION}" != "release" ]]; then
  echo "only exact dual-resource release rollback is supported" >&2
  usage
  exit 1
fi
if [[ ! "${EXPECTED_CURRENT}" =~ ^[a-f0-9]{64}$ ]]; then
  echo "expected current release must be a full lowercase sha256" >&2
  exit 1
fi
if [[ ! "${TARGET_RELEASE}" =~ ^[a-f0-9]{64}$ ]]; then
  echo "target release must be a full lowercase sha256" >&2
  exit 1
fi
if [[ "${TARGET_RELEASE}" == "${EXPECTED_CURRENT}" ]]; then
  echo "target release must differ from expected current release" >&2
  exit 1
fi
DATA_ARGUMENT_COUNT=0
for value in \
  "${EXPECTED_CURRENT_DATA_RELEASE}" \
  "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
  "${TARGET_DATA_RELEASE}" \
  "${TARGET_DATA_POINTER_SHA}"; do
  [[ -z "${value}" ]] || DATA_ARGUMENT_COUNT=$((DATA_ARGUMENT_COUNT + 1))
done
if [[ "${DATA_ARGUMENT_COUNT}" != "4" ]]; then
  echo "exact rollback requires all four data bindings" >&2
  exit 1
fi
EVIDENCE_ARGUMENT_COUNT=0
for value in "${PROMOTION_RECEIPT_INPUT}" "${PROMOTION_RECEIPT_SHA_INPUT}"; do
  [[ -z "${value}" ]] || EVIDENCE_ARGUMENT_COUNT=$((EVIDENCE_ARGUMENT_COUNT + 1))
done
if [[ "${EVIDENCE_ARGUMENT_COUNT}" != "2" ]]; then
  echo "release rollback requires an explicit promotion receipt path and SHA-256" >&2
  exit 1
fi
DUAL_DATA_ROLLBACK=1
if [[ ! "${EXPECTED_CURRENT_DATA_RELEASE}" =~ ^reddit_voc_release_[a-z0-9_-]+$ || \
      ! "${TARGET_DATA_RELEASE}" =~ ^reddit_voc_release_[a-z0-9_-]+$ || \
      "${EXPECTED_CURRENT_DATA_RELEASE}" == "${TARGET_DATA_RELEASE}" ]]; then
  echo "data release rollback bindings are invalid" >&2
  exit 1
fi
if [[ ! "${EXPECTED_CURRENT_DATA_POINTER_SHA}" =~ ^[a-f0-9]{64}$ || \
      ! "${TARGET_DATA_POINTER_SHA}" =~ ^[a-f0-9]{64}$ || \
      "${EXPECTED_CURRENT_DATA_POINTER_SHA}" == "${TARGET_DATA_POINTER_SHA}" ]]; then
  echo "data pointer rollback bindings are invalid" >&2
  exit 1
fi
AUTHORIZATION_ARGUMENT_COUNT=0
for value in \
  "${AUTHORIZATION_PACKET_INPUT}" "${AUTHORIZATION_PACKET_SHA_INPUT}" \
  "${AUTHORIZATION_PERMIT_INPUT}" "${AUTHORIZATION_PERMIT_SHA_INPUT}" \
  "${PRODUCTION_BASELINE_INPUT}" "${PRODUCTION_BASELINE_SHA_INPUT}"; do
  [[ -z "${value}" ]] || AUTHORIZATION_ARGUMENT_COUNT=$((AUTHORIZATION_ARGUMENT_COUNT + 1))
done
if [[ "${AUTHORIZATION_ARGUMENT_COUNT}" != "6" ]]; then
  echo "dual-resource rollback requires exact packet, permit, and baseline paths and SHA-256 bindings" >&2
  exit 1
fi
for digest in \
  "${PROMOTION_RECEIPT_SHA_INPUT}" "${AUTHORIZATION_PACKET_SHA_INPUT}" \
  "${AUTHORIZATION_PERMIT_SHA_INPUT}" "${PRODUCTION_BASELINE_SHA_INPUT}"; do
  [[ -z "${digest}" || "${digest}" =~ ^[a-f0-9]{64}$ ]] || {
    echo "rollback evidence SHA-256 bindings must be full lowercase digests" >&2
    exit 1
  }
done
if [[ ! -f "${PATCH_SCRIPT}" || -L "${PATCH_SCRIPT}" ]]; then
  echo "Nginx patch script is missing or is a symlink" >&2
  exit 1
fi

DEPLOY_ROOT="/opt/reddit-voc-insights-site"
RELEASE_ROOT="${DEPLOY_ROOT}/releases"
EVIDENCE_ROOT="${DEPLOY_ROOT}/evidence"
LOCK_FILE="${DEPLOY_ROOT}/.deploy.lock"
PROMOTION_LOCK="${DEPLOY_ROOT}/.promotion.lock"
COMPOSE_PROJECT="reddit_voc_insights"
CONTAINER_NAME="reddit_voc_insights_web"
BIND_ADDRESS="172.20.0.1"
PORT="18338"
DATA_ROOT="/opt/reddit-voc-insights-data"
DATA_CONTAINER_ROOT="/srv/reddit-voc-data"
ROLLBACK_JOURNAL="${DEPLOY_ROOT}/.dual-resource-rollback-journal.json"
ROLLBACK_JOURNAL_SCHEMA="reddit_voc_dual_resource_rollback_journal_v1"
ROLLBACK_RECEIPT_SCHEMA="reddit_voc_dual_resource_rollback_receipt_v1"
FROM_DATA_INVENTORY_SHA=""
FROM_DATA_FILE_COUNT=""
FROM_DATA_TOTAL_BYTES=""
TO_DATA_INVENTORY_SHA=""
TO_DATA_FILE_COUNT=""
TO_DATA_TOTAL_BYTES=""
TARGET_DEPLOYMENT_EVIDENCE_SHA=""
DOMAIN="reddit.lute-tlz-dddd.top"
NGINX_CONTAINER="ai_video_nginx"
NGINX_CONF="/opt/ai-video/deploy/lighthouse/nginx.conf"
CRON_FILE="/etc/cron.d/reddit-voc-site"
COLLECTOR_PUBLIC_URL="https://reddit.brand.lute-tlz-dddd.top/api/health"
MARKER_START="# BEGIN reddit-voc-insights-site"
MARKER_END="# END reddit-voc-insights-site"
ROLLBACK_VERIFIER_TRANSACTION_SHA="$(
  printf '%s\n' \
    "${ACTION}" "${EXPECTED_CURRENT}" "${TARGET_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${TARGET_DATA_RELEASE}" "${TARGET_DATA_POINTER_SHA}" \
    "${PROMOTION_RECEIPT_SHA_INPUT}" "${AUTHORIZATION_PACKET_SHA_INPUT}" | \
    sha256sum | awk '{print $1}'
)" || exit 1
if [[ ! "${ROLLBACK_VERIFIER_TRANSACTION_SHA}" =~ ^[a-f0-9]{64}$ ]]; then
  echo "rollback verifier transaction identity is invalid" >&2
  exit 1
fi
ROLLBACK_VERIFIER_NAME="reddit_voc_insights_rollback_verify_${ROLLBACK_VERIFIER_TRANSACTION_SHA:0:24}"

for command in curl docker flock grep mktemp python3 sha256sum ss stat; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "required command is missing: ${command}" >&2
    exit 1
  fi
done
sudo -n true

assert_safe_window() {
  local hhmm hhmm_number
  hhmm="$(TZ=Asia/Shanghai date +%H%M)"
  hhmm_number=$((10#${hhmm}))
  if (( hhmm_number >= 630 && hhmm_number <= 830 )); then
    echo "rollback blocked during the 06:30-08:30 collection/report window" >&2
    return 1
  fi
}

assert_safe_window
for directory in "${DEPLOY_ROOT}" "${RELEASE_ROOT}" "${EVIDENCE_ROOT}"; do
  if [[ ! -d "${directory}" || -L "${directory}" ]]; then
    echo "required deployment directory is missing or unsafe: ${directory}" >&2
    exit 1
  fi
done
if [[ ! -f "${NGINX_CONF}" || -L "${NGINX_CONF}" ]]; then
  echo "shared Nginx config is missing or unsafe" >&2
  exit 1
fi
if ! sudo test -f "${CRON_FILE}" || sudo test -L "${CRON_FILE}"; then
  echo "collector cron file is missing or unsafe" >&2
  exit 1
fi
if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
  DATA_RELEASE_ROOT="${DATA_ROOT}/releases"
  DATA_LOCKS_DIR="${DATA_ROOT}/locks"
  DATA_LOCK_FILE="${DATA_LOCKS_DIR}/data-release.lock"
  for directory in "${DATA_ROOT}" "${DATA_RELEASE_ROOT}" "${DATA_LOCKS_DIR}"; do
    if [[ ! -d "${directory}" || -L "${directory}" ]]; then
      echo "required data rollback directory is missing or unsafe: ${directory}" >&2
      exit 1
    fi
  done
else
  DATA_LOCK_FILE=""
fi

revalidate_rollback_locks() {
  python3 - \
    "${PROMOTION_LOCK}" "${LOCK_FILE}" "${DATA_LOCK_FILE}" \
    "${DUAL_DATA_ROLLBACK}" "${REDDIT_VOC_ROLLBACK_LOCK_FDS:-}" \
    "${ROLLBACK_AUTHORIZED_LOCK_IDENTITIES_B64:-absent}" <<'PY'
import base64
import fcntl
import json
import os
import stat
import sys

promotion, deploy, data, dual_raw, fd_raw, expected_raw = sys.argv[1:]
paths = [promotion, deploy] + ([data] if dual_raw == "1" else [])
names = ["promotion", "deploy"] + (["data_release"] if dual_raw == "1" else [])
try:
    descriptors = [int(item) for item in fd_raw.split(",") if item]
except ValueError:
    raise SystemExit("rollback lock descriptor contract is invalid")
if len(descriptors) != len(paths):
    raise SystemExit("rollback lock descriptor count is invalid")
actual = {}
for name, path, descriptor in zip(names, paths, descriptors, strict=True):
    opened = os.fstat(descriptor)
    linked = os.lstat(path)
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(linked.st_mode)
        or opened.st_dev != linked.st_dev
        or opened.st_ino != linked.st_ino
        or opened.st_nlink != 1
        or linked.st_nlink != 1
        or opened.st_uid != os.getuid()
        or linked.st_uid != os.getuid()
        or stat.S_IMODE(opened.st_mode) != 0o600
        or stat.S_IMODE(linked.st_mode) != 0o600
    ):
        raise SystemExit(f"rollback lock fd/path identity is unsafe: {path}")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"rollback lock is no longer held: {path}")
    actual[name] = {
        "device": opened.st_dev,
        "inode": opened.st_ino,
        "mode": f"{stat.S_IMODE(opened.st_mode):04o}",
        "nlink": opened.st_nlink,
        "path": path,
        "uid": opened.st_uid,
    }
if expected_raw != "absent":
    try:
        expected = json.loads(base64.urlsafe_b64decode(expected_raw).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("authorized rollback lock identities are invalid") from exc
    if actual != expected:
        raise SystemExit("rollback lock identities differ from the authorized baseline")
PY
}

if [[ "${REDDIT_VOC_ROLLBACK_LOCKS_HELD:-}" != "1" ]]; then
  python3 - \
    "$0" "${DUAL_DATA_ROLLBACK}" "${PROMOTION_LOCK}" "${LOCK_FILE}" \
    "${DATA_LOCK_FILE}" "${ORIGINAL_ARGUMENTS[@]}" <<'PY'
import fcntl
import os
import stat
import sys

script, dual_raw, promotion, deploy, data, *arguments = sys.argv[1:]
paths = [promotion, deploy] + ([data] if dual_raw == "1" else [])
descriptors = []
targets = [200, 201, 202]

def revalidate(path, descriptor):
    opened = os.fstat(descriptor)
    linked = os.lstat(path)
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(linked.st_mode)
        or opened.st_dev != linked.st_dev
        or opened.st_ino != linked.st_ino
        or opened.st_nlink != 1
        or linked.st_nlink != 1
        or opened.st_uid != os.getuid()
        or linked.st_uid != os.getuid()
        or stat.S_IMODE(opened.st_mode) != 0o600
        or stat.S_IMODE(linked.st_mode) != 0o600
    ):
        raise SystemExit(f"rollback lock fd/path identity is unsafe: {path}")

for index, path in enumerate(paths):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    opened = os.fstat(descriptor)
    linked = os.lstat(path)
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(linked.st_mode)
        or opened.st_dev != linked.st_dev
        or opened.st_ino != linked.st_ino
        or opened.st_nlink != 1
        or linked.st_nlink != 1
        or opened.st_uid != os.getuid()
        or linked.st_uid != os.getuid()
        or stat.S_IMODE(opened.st_mode) != 0o600
        or stat.S_IMODE(linked.st_mode) != 0o600
    ):
        raise SystemExit(f"rollback lock bootstrap is unsafe: {path}")
    revalidate(path, descriptor)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"rollback lock is busy: {path}")
    revalidate(path, descriptor)
    target = targets[index]
    if descriptor != target:
        os.dup2(descriptor, target, inheritable=True)
        os.close(descriptor)
        descriptor = target
    else:
        os.set_inheritable(descriptor, True)
    descriptors.append(descriptor)

for path, descriptor in zip(paths, descriptors, strict=True):
    revalidate(path, descriptor)
environment = dict(os.environ)
environment["REDDIT_VOC_ROLLBACK_LOCKS_HELD"] = "1"
environment["REDDIT_VOC_ROLLBACK_LOCK_FDS"] = ",".join(map(str, descriptors))
os.execve("/bin/bash", ["bash", script, *arguments], environment)
PY
  exit 1
fi

revalidate_rollback_locks

IFS=$'\t' read -r ROLLBACK_RUNNER_SHA ROLLBACK_RUNNER_BYTES < <(
  python3 - "$0" <<'PY'
import ctypes
import errno
import hashlib
import os
import stat
import sys

path = sys.argv[1]
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    opened = os.fstat(descriptor)
    linked = os.lstat(path)
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(linked.st_mode)
        or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
        or opened.st_nlink != 1
        or linked.st_nlink != 1
        or opened.st_uid != os.getuid()
        or linked.st_uid != os.getuid()
        or opened.st_mode & 0o022
        or linked.st_mode & 0o022
    ):
        raise SystemExit("rollback runner identity is unsafe")
    digest = hashlib.sha256()
    length = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        length += len(chunk)
    after = os.fstat(descriptor)
    if (
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        or length != opened.st_size
    ):
        raise SystemExit("rollback runner changed while hashing")
finally:
    os.close(descriptor)
print(digest.hexdigest(), length, sep="\t")
PY
)
if [[ ! "${ROLLBACK_RUNNER_SHA}" =~ ^[a-f0-9]{64}$ || ! "${ROLLBACK_RUNNER_BYTES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "rollback runner identity binding failed" >&2
  exit 1
fi

if [[ -e "${ROLLBACK_JOURNAL}" || -L "${ROLLBACK_JOURNAL}" ]]; then
  if [[ -L "${ROLLBACK_JOURNAL}" || ! -f "${ROLLBACK_JOURNAL}" || \
        "$(stat -c '%h|%u|%a' "${ROLLBACK_JOURNAL}")" != "1|$(id -u)|600" ]]; then
    echo "dual-resource rollback journal is unsafe" >&2
    exit 1
  fi
  if [[ "${DUAL_DATA_ROLLBACK}" != "1" ]]; then
    echo "an unfinished dual-resource rollback journal blocks site-only actions" >&2
    exit 1
  fi
fi

release_dir() {
  printf '%s/%s' "${RELEASE_ROOT}" "$1"
}

fsync_directory_path() {
  python3 - "$1" <<'PY'
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
}

safe_file_sha256() {
  python3 - "$1" "$(id -u)" <<'PY'
import hashlib
import os
import stat
import sys

path = sys.argv[1]
expected_uid = int(sys.argv[2])
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != expected_uid
        or before.st_mode & 0o022
    ):
        raise SystemExit("immutable evidence/file metadata is unsafe")
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    after = os.fstat(descriptor)
    if (
        after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or size != before.st_size
    ):
        raise SystemExit("immutable evidence/file changed while hashing")
finally:
    os.close(descriptor)
print(digest.hexdigest())
PY
}

assert_site_only_release_compatible() {
  local release_sha="$1"
  python3 - "$(release_dir "${release_sha}")/release-manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
runtime = manifest.get("data_runtime")
has_mounted_runtime = isinstance(runtime, dict) and runtime.get("mode") == "read_only_versioned_mount"
has_data_binding = manifest.get("current_release") is not None
if has_mounted_runtime or has_data_binding:
    raise SystemExit(
        "site-only release rollback is forbidden for a mounted/data-bound release; "
        "supply all four data bindings"
    )
PY
}

read_release_collection_status() {
  local release_sha="$1"
  python3 - "$(release_dir "${release_sha}")/release-manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

def flag(name: str) -> bool:
    value = manifest.get(name, False)
    if type(value) is not bool:
        raise SystemExit(f"release manifest {name} must be boolean")
    return value

integrated = flag("latest_collection_integrated")
fully_hydrated = flag("latest_collection_fully_hydrated")
if fully_hydrated and not integrated:
    raise SystemExit("release manifest collection status is impossible")
print(str(integrated).lower(), str(fully_hydrated).lower(), sep="\t")
PY
}

assert_expected_current_pointer() {
  local expected_target="releases/${EXPECTED_CURRENT}"
  if [[ ! -L "${DEPLOY_ROOT}/current" ]]; then
    echo "current release pointer is missing or is not a symlink" >&2
    return 1
  fi
  if [[ "$(readlink "${DEPLOY_ROOT}/current")" != "${expected_target}" ]]; then
    echo "current release does not match --expected-current" >&2
    return 1
  fi
}

cas_replace_symlink() {
  local pointer="$1"
  local expected_target="$2"
  local replacement_target="$3"
  local label="$4"
  revalidate_rollback_locks || return 1
  assert_candidate_transaction_quiet || return 1
  python3 - \
    "${pointer}" "${expected_target}" "${replacement_target}" \
    "${label}" "$(id -u)" <<'PY' || return 1
import ctypes
import errno
import os
import re
import secrets
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected, replacement, label = sys.argv[2:5]
expected_uid = int(sys.argv[5])
target_re = re.compile(
    r"^releases/(?:[a-f0-9]{64}|reddit_voc_release_[a-z0-9_-]+)$"
)
if (
    not path.is_absolute()
    or not path.name
    or "/" in path.name
    or (expected != "absent" and target_re.fullmatch(expected) is None)
    or target_re.fullmatch(replacement) is None
    or expected == replacement
    or not re.fullmatch(r"[a-z0-9_-]+", label)
):
    raise SystemExit("pointer CAS arguments are invalid")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("pointer CAS requires O_NOFOLLOW")
parent = path.parent
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = f".{path.name}.{label}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
temporary_created = False
temporary_before = None

def rename_noreplace(source, target):
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        result = library.renameat2(
            parent_fd,
            os.fsencode(source),
            parent_fd,
            os.fsencode(target),
            1,
        )
    elif sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            parent_fd,
            os.fsencode(source),
            parent_fd,
            os.fsencode(target),
            0x00000004,
        )
    else:
        raise SystemExit("atomic no-replace rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)

def rename_exchange(source, target):
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        result = library.renameat2(
            parent_fd,
            os.fsencode(source),
            parent_fd,
            os.fsencode(target),
            2,
        )
    elif sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            parent_fd,
            os.fsencode(source),
            parent_fd,
            os.fsencode(target),
            0x00000002,
        )
    else:
        raise SystemExit("atomic exchange rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)

def linked(name):
    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != expected_uid:
        raise SystemExit(f"{label} pointer metadata is unsafe")
    return metadata, os.readlink(name, dir_fd=parent_fd)

try:
    parent_before = os.fstat(parent_fd)
    linked_parent = parent.lstat()
    if (
        not stat.S_ISDIR(parent_before.st_mode)
        or (parent_before.st_dev, parent_before.st_ino)
        != (linked_parent.st_dev, linked_parent.st_ino)
        or parent_before.st_uid != expected_uid
        or parent_before.st_mode & 0o022
    ):
        raise SystemExit(f"{label} pointer parent directory is unsafe")
    if expected == "absent":
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SystemExit(f"{label} pointer CAS expected absence")
    else:
        current_before, current_target = linked(path.name)
        if current_target != expected:
            raise SystemExit(f"{label} pointer CAS expected target mismatch")
    os.symlink(replacement, temporary, dir_fd=parent_fd)
    temporary_created = True
    temporary_before, temporary_target = linked(temporary)
    if temporary_target != replacement:
        raise SystemExit(f"{label} pointer temporary target mismatch")
    if expected == "absent":
        rename_noreplace(temporary, path.name)
        temporary_created = False
    else:
        rename_exchange(temporary, path.name)
        displaced, displaced_target = linked(temporary)
        published, published_target = linked(path.name)
        if (
            (displaced.st_dev, displaced.st_ino)
            != (current_before.st_dev, current_before.st_ino)
            or displaced_target != expected
            or (published.st_dev, published.st_ino)
            != (temporary_before.st_dev, temporary_before.st_ino)
            or published_target != replacement
        ):
            try:
                observed, observed_target = linked(path.name)
                old, old_target = linked(temporary)
                if (
                    (observed.st_dev, observed.st_ino)
                    == (temporary_before.st_dev, temporary_before.st_ino)
                    and observed_target == replacement
                ):
                    rename_exchange(temporary, path.name)
                    restored, restored_target = linked(path.name)
                    restored_temporary, restored_temporary_target = linked(
                        temporary
                    )
                    if (
                        (restored.st_dev, restored.st_ino)
                        != (old.st_dev, old.st_ino)
                        or restored_target != old_target
                        or (
                            restored_temporary.st_dev,
                            restored_temporary.st_ino,
                        )
                        != (
                            temporary_before.st_dev,
                            temporary_before.st_ino,
                        )
                        or restored_temporary_target != replacement
                    ):
                        raise SystemExit(
                            f"{label} pointer CAS failed to restore the "
                            "exchange-time destination"
                        )
            finally:
                raise SystemExit(f"{label} pointer CAS exchange verification failed")
        os.unlink(temporary, dir_fd=parent_fd)
        temporary_created = False
    final, final_target = linked(path.name)
    if (
        (final.st_dev, final.st_ino)
        != (temporary_before.st_dev, temporary_before.st_ino)
        or final_target != replacement
    ):
        raise SystemExit(f"{label} pointer CAS final verification failed")
    os.fsync(parent_fd)
    parent_after = os.fstat(parent_fd)
    linked_after = parent.lstat()
    if (
        (parent_before.st_dev, parent_before.st_ino)
        != (parent_after.st_dev, parent_after.st_ino)
        or (parent_after.st_dev, parent_after.st_ino)
        != (linked_after.st_dev, linked_after.st_ino)
    ):
        raise SystemExit(f"{label} pointer parent changed during CAS")
finally:
    if temporary_created:
        try:
            candidate = os.stat(
                temporary, dir_fd=parent_fd, follow_symlinks=False
            )
            if (
                temporary_before is not None
                and (candidate.st_dev, candidate.st_ino)
                == (temporary_before.st_dev, temporary_before.st_ino)
            ):
                os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
    os.close(parent_fd)
PY
  revalidate_rollback_locks || return 1
  assert_candidate_transaction_quiet || return 1
  if [[ ! -L "${pointer}" || "$(readlink "${pointer}")" != "${replacement_target}" ]]; then
    echo "${label} pointer CAS postcondition failed" >&2
    return 1
  fi
}

cas_remove_symlink() {
  local pointer="$1"
  local expected_target="$2"
  local label="$3"
  revalidate_rollback_locks || return 1
  assert_candidate_transaction_quiet || return 1
  python3 - \
    "${pointer}" "${expected_target}" "${label}" "$(id -u)" <<'PY' || return 1
import ctypes
import os
import re
import secrets
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected, label = sys.argv[2:4]
expected_uid = int(sys.argv[4])
target_re = re.compile(
    r"^releases/(?:[a-f0-9]{64}|reddit_voc_release_[a-z0-9_-]+)$"
)
if (
    not path.is_absolute()
    or target_re.fullmatch(expected) is None
    or not re.fullmatch(r"[a-z0-9_-]+", label)
):
    raise SystemExit("pointer removal CAS arguments are invalid")
parent = path.parent
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = f".{path.name}.{label}.{os.getpid()}.{secrets.token_hex(16)}.old"
moved = False

def rename_noreplace(source, target):
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        result = library.renameat2(
            parent_fd, os.fsencode(source), parent_fd, os.fsencode(target), 1
        )
    elif sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            parent_fd,
            os.fsencode(source),
            parent_fd,
            os.fsencode(target),
            0x00000004,
        )
    else:
        raise SystemExit("atomic no-replace rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)

try:
    parent_before = os.fstat(parent_fd)
    linked_parent = parent.lstat()
    if (
        not stat.S_ISDIR(parent_before.st_mode)
        or (parent_before.st_dev, parent_before.st_ino)
        != (linked_parent.st_dev, linked_parent.st_ino)
        or parent_before.st_uid != expected_uid
        or parent_before.st_mode & 0o022
    ):
        raise SystemExit(f"{label} pointer parent directory is unsafe")
    before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISLNK(before.st_mode)
        or before.st_uid != expected_uid
        or os.readlink(path.name, dir_fd=parent_fd) != expected
    ):
        raise SystemExit(f"{label} pointer removal CAS expected target mismatch")
    rename_noreplace(path.name, temporary)
    moved = True
    displaced = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISLNK(displaced.st_mode)
        or (displaced.st_dev, displaced.st_ino) != (before.st_dev, before.st_ino)
        or os.readlink(temporary, dir_fd=parent_fd) != expected
    ):
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            rename_noreplace(temporary, path.name)
            moved = False
        raise SystemExit(f"{label} pointer removal CAS verification failed")
    os.unlink(temporary, dir_fd=parent_fd)
    moved = False
    os.fsync(parent_fd)
    try:
        os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise SystemExit(f"{label} pointer removal CAS final state is not absent")
finally:
    if moved:
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            try:
                rename_noreplace(temporary, path.name)
            except OSError:
                pass
    os.close(parent_fd)
PY
  revalidate_rollback_locks || return 1
  assert_candidate_transaction_quiet || return 1
  if [[ -e "${pointer}" || -L "${pointer}" ]]; then
    echo "${label} pointer removal CAS postcondition failed" >&2
    return 1
  fi
}

validate_release_payload() {
  local release_sha="$1"
  local directory
  directory="$(release_dir "${release_sha}")" || return 1
  if [[ ! -d "${directory}" || -L "${directory}" ]]; then
    echo "release directory is missing or unsafe: ${release_sha}" >&2
    return 1
  fi
  local required
  for required in compose.yaml dist-SHA256SUMS release-manifest.json SHA256SUMS "reddit-voc-insights-${release_sha}.tar"; do
    if [[ ! -f "${directory}/${required}" || -L "${directory}/${required}" ]]; then
      echo "release ${release_sha} is missing safe ${required}" >&2
      return 1
    fi
  done
  python3 - "${directory}/SHA256SUMS" "${release_sha}" <<'PY' || return 1
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
release = sys.argv[2]
expected = {
    "compose.yaml",
    "dist-SHA256SUMS",
    "release-manifest.json",
    f"reddit-voc-insights-{release}.tar",
}
actual = []
for line in path.read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9._-]+)", line)
    if match is None:
        raise SystemExit("release SHA256SUMS contains an unsafe entry")
    actual.append(match.group(2))
if len(actual) != len(expected) or len(set(actual)) != len(actual) or set(actual) != expected:
    raise SystemExit("release SHA256SUMS does not match the immutable release contract")
PY
  (
    cd "${directory}"
    sha256sum --check SHA256SUMS
  ) || return 1
  local manifest_release manifest_schema
  manifest_release="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["release_sha256"])' "${directory}/release-manifest.json")" || return 1
  manifest_schema="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["schema_version"])' "${directory}/release-manifest.json")" || return 1
  if [[ "${manifest_release}" != "${release_sha}" || "${manifest_schema}" != "reddit_voc_insights_site_release_v2" ]]; then
    echo "release manifest identity or schema mismatch: ${release_sha}" >&2
    return 1
  fi
  read_release_collection_status "${release_sha}" >/dev/null || return 1
}

validate_release_data_binding() {
  local release_sha="$1"
  local data_release_id="$2"
  local data_pointer_sha="$3"
  python3 - "$(release_dir "${release_sha}")/release-manifest.json" "${data_release_id}" "${data_pointer_sha}" <<'PY' || return 1
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
current = manifest.get("current_release")
if (
    not isinstance(current, dict)
    or current.get("path") != "data/reddit-voc/current-release.json"
    or current.get("release_id") != sys.argv[2]
    or current.get("sha256") != sys.argv[3]
):
    raise SystemExit("release manifest data binding mismatch")
PY
}

data_release_dir() {
  printf '%s/releases/%s' "${DATA_ROOT}" "$1"
}

validate_data_release_payload() {
  local data_release_id="$1"
  local expected_pointer_sha="$2"
  local site_release_sha="$3"
  local directory pointer dist_sums
  directory="$(data_release_dir "${data_release_id}")" || return 1
  pointer="${directory}/public/data/reddit-voc/current-release.json"
  dist_sums="$(release_dir "${site_release_sha}")/dist-SHA256SUMS" || return 1
  if [[ ! -d "${directory}" || -L "${directory}" || ! -f "${pointer}" || -L "${pointer}" ]]; then
    echo "data release payload is missing or unsafe: ${data_release_id}" >&2
    return 1
  fi
  if [[ ! -f "${dist_sums}" || -L "${dist_sums}" ]]; then
    echo "site release data checksum inventory is missing or unsafe: ${site_release_sha}" >&2
    return 1
  fi
  if find "${directory}" -type l -print -quit | grep -q . || \
     find "${directory}" \( -type d -o -type f \) -perm /022 -print -quit | grep -q .; then
    echo "data release payload is mutable or contains symlinks: ${data_release_id}" >&2
    return 1
  fi
  if [[ "$(sha256sum "${pointer}" | awk '{print $1}')" != "${expected_pointer_sha}" ]]; then
    echo "data release pointer checksum mismatch: ${data_release_id}" >&2
    return 1
  fi
  python3 - "${directory}/public" "${data_release_id}" <<'PY' || return 1
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

public_root = Path(sys.argv[1])
release_id = sys.argv[2]
pointer = public_root / "data/reddit-voc/current-release.json"
value = json.loads(pointer.read_text(encoding="utf-8"))
datasets = value.get("datasets")
if (
    value.get("schema_version") != "reddit_voc_current_release_v2"
    or value.get("release_id") != release_id
    or not isinstance(datasets, dict)
    or set(datasets) != {
        "base", "insights", "reports", "personas", "brand_health",
        "quarter_insights", "casebook",
    }
):
    raise SystemExit("data release pointer contract mismatch")

def verify_manifest(row, *, path_key, sha_key):
    if not isinstance(row, dict):
        raise SystemExit("data release manifest binding is not an object")
    raw_path = row.get(path_key)
    expected_sha = row.get(sha_key)
    if not isinstance(raw_path, str) or not isinstance(expected_sha, str):
        raise SystemExit("data release manifest binding is incomplete")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise SystemExit("data release manifest path is unsafe")
    target = public_root.joinpath(*relative.parts)
    if not target.is_file() or target.is_symlink():
        raise SystemExit("data release manifest is missing or unsafe")
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha:
        raise SystemExit("data release manifest checksum mismatch")

for row in datasets.values():
    verify_manifest(row, path_key="manifest_path", sha_key="public_manifest_sha256")
cases = value.get("cases")
if cases is not None:
    verify_manifest(cases, path_key="manifest_path", sha_key="public_manifest_sha256")
PY
  python3 - "${dist_sums}" "${directory}/public" "$(id -u)" <<'PY'
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

sums_path = Path(sys.argv[1])
public_root = Path(sys.argv[2])
expected_uid = int(sys.argv[3])

sums_fd = os.open(sums_path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    sums_stat = os.fstat(sums_fd)
    if (
        not stat.S_ISREG(sums_stat.st_mode)
        or sums_stat.st_nlink != 1
        or sums_stat.st_mode & 0o022
    ):
        raise SystemExit("site data checksum inventory metadata is unsafe")
    sums_raw = b""
    while True:
        chunk = os.read(sums_fd, 1024 * 1024)
        if not chunk:
            break
        sums_raw += chunk
    sums_after = os.fstat(sums_fd)
    if (
        sums_after.st_dev != sums_stat.st_dev
        or sums_after.st_ino != sums_stat.st_ino
        or sums_after.st_size != sums_stat.st_size
        or sums_after.st_mtime_ns != sums_stat.st_mtime_ns
        or len(sums_raw) != sums_stat.st_size
    ):
        raise SystemExit("site data checksum inventory changed while reading")
finally:
    os.close(sums_fd)
try:
    sums_lines = sums_raw.decode("utf-8").splitlines()
except UnicodeDecodeError:
    raise SystemExit("site data checksum inventory is not UTF-8")

expected = {}
for number, line in enumerate(sums_lines, 1):
    match = re.fullmatch(r"([a-f0-9]{64})  (dist/data/.+)", line)
    if match is None:
        if "  dist/data/" in line:
            raise SystemExit(f"invalid data checksum line: {number}")
        continue
    digest, raw_path = match.groups()
    relative = PurePosixPath(raw_path).relative_to("dist")
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise SystemExit("unsafe data checksum path")
    key = relative.as_posix()
    if key in expected:
        raise SystemExit("duplicate data checksum path")
    expected[key] = digest
if not expected:
    raise SystemExit("data checksum inventory is empty")

actual = {}
for root, directories, files in os.walk(public_root, followlinks=False):
    root_path = Path(root)
    root_stat = root_path.lstat()
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or root_stat.st_uid != expected_uid
        or root_stat.st_mode & 0o022
    ):
        raise SystemExit("data directory ownership or immutability mismatch")
    for name in directories:
        metadata = (root_path / name).lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != expected_uid or metadata.st_mode & 0o022:
            raise SystemExit("data projection contains an unsafe directory")
    for name in files:
        path = root_path / name
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != expected_uid
            or metadata.st_mode & 0o022
        ):
            raise SystemExit("data projection contains an unsafe file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
                or opened.st_nlink != 1
                or opened.st_uid != expected_uid
                or opened.st_mode & 0o022
            ):
                raise SystemExit("data projection file changed while validating")
            digest_value = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest_value.update(chunk)
                size += len(chunk)
            opened_after = os.fstat(descriptor)
            if (
                opened_after.st_dev != opened.st_dev
                or opened_after.st_ino != opened.st_ino
                or opened_after.st_size != opened.st_size
                or opened_after.st_mtime_ns != opened.st_mtime_ns
                or size != opened.st_size
            ):
                raise SystemExit("data projection file changed while hashing")
        finally:
            os.close(descriptor)
        relative = path.relative_to(public_root).as_posix()
        actual[relative] = (digest_value.hexdigest(), size)
if set(actual) != set(expected):
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    raise SystemExit(
        f"data projection inventory mismatch missing={missing[:3]} extra={extra[:3]}"
    )
for relative, expected_digest in expected.items():
    if actual[relative][0] != expected_digest:
        raise SystemExit(f"data projection checksum mismatch: {relative}")
inventory = hashlib.sha256()
total_bytes = 0
for relative in sorted(actual):
    digest, size = actual[relative]
    inventory.update(
        relative.encode("utf-8")
        + b"\0"
        + digest.encode("ascii")
        + b"\0"
        + str(size).encode("ascii")
        + b"\n"
    )
    total_bytes += size
print(inventory.hexdigest(), len(actual), total_bytes, sep="\t")
PY
}

validate_and_bind_data_inventory() {
  local role="$1"
  local data_release_id="$2"
  local pointer_sha="$3"
  local site_release_sha="$4"
  local inventory_output inventory_sha file_count total_bytes
  inventory_output="$(validate_data_release_payload \
    "${data_release_id}" "${pointer_sha}" "${site_release_sha}")" || return 1
  IFS=$'\t' read -r inventory_sha file_count total_bytes <<< "${inventory_output}"
  if [[ ! "${inventory_sha}" =~ ^[a-f0-9]{64}$ || \
        ! "${file_count}" =~ ^[1-9][0-9]*$ || \
        ! "${total_bytes}" =~ ^[1-9][0-9]*$ ]]; then
    echo "data inventory statistics are invalid: ${role}" >&2
    return 1
  fi
  case "${role}" in
    from)
      if [[ -z "${FROM_DATA_INVENTORY_SHA}" ]]; then
        FROM_DATA_INVENTORY_SHA="${inventory_sha}"
        FROM_DATA_FILE_COUNT="${file_count}"
        FROM_DATA_TOTAL_BYTES="${total_bytes}"
      elif [[ "${FROM_DATA_INVENTORY_SHA}|${FROM_DATA_FILE_COUNT}|${FROM_DATA_TOTAL_BYTES}" != \
              "${inventory_sha}|${file_count}|${total_bytes}" ]]; then
        echo "source data inventory changed during rollback" >&2
        return 1
      fi
      ;;
    to)
      if [[ -z "${TO_DATA_INVENTORY_SHA}" ]]; then
        TO_DATA_INVENTORY_SHA="${inventory_sha}"
        TO_DATA_FILE_COUNT="${file_count}"
        TO_DATA_TOTAL_BYTES="${total_bytes}"
      elif [[ "${TO_DATA_INVENTORY_SHA}|${TO_DATA_FILE_COUNT}|${TO_DATA_TOTAL_BYTES}" != \
              "${inventory_sha}|${file_count}|${total_bytes}" ]]; then
        echo "target data inventory changed during rollback" >&2
        return 1
      fi
      ;;
    *)
      echo "unknown data inventory role" >&2
      return 1
      ;;
  esac
}

assert_expected_data_pointer() {
  [[ "${DUAL_DATA_ROLLBACK}" == "1" ]] || return 0
  if [[ ! -L "${DATA_ROOT}/current" || \
        "$(readlink "${DATA_ROOT}/current")" != "releases/${EXPECTED_CURRENT_DATA_RELEASE}" ]]; then
    echo "current data release does not match the expected rollback source" >&2
    return 1
  fi
  validate_and_bind_data_inventory from \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${EXPECTED_CURRENT}"
}

assert_original_data_previous_pointer() {
  [[ "${DUAL_DATA_ROLLBACK}" == "1" ]] || return 0
  if [[ "${ORIGINAL_DATA_PREVIOUS_TARGET}" == "absent" ]]; then
    if [[ -e "${DATA_ROOT}/previous" || -L "${DATA_ROOT}/previous" ]]; then
      echo "data previous pointer was not restored to absent" >&2
      return 1
    fi
  elif [[ ! -L "${DATA_ROOT}/previous" || \
          "$(readlink "${DATA_ROOT}/previous")" != "${ORIGINAL_DATA_PREVIOUS_TARGET}" ]]; then
    echo "data previous pointer was not restored to its original target" >&2
    return 1
  fi
}

TARGET_DEPLOYMENT_EVIDENCE=""
ROLLBACK_EVIDENCE_MODE=""
ROLLBACK_ACCEPTANCE_EVIDENCE="absent"
ROLLBACK_ACCEPTANCE_EVIDENCE_SHA="absent"
ROLLBACK_AUTHORIZATION_PACKET="absent"
ROLLBACK_AUTHORIZATION_PACKET_SHA="absent"
ROLLBACK_AUTHORIZATION_PERMIT="absent"
ROLLBACK_AUTHORIZATION_PERMIT_SHA="absent"
ROLLBACK_PRODUCTION_BASELINE="absent"
ROLLBACK_PRODUCTION_BASELINE_SHA="absent"
FROM_RELEASE_MANIFEST_SHA256="absent"
FROM_RELEASE_SHA256SUMS_SHA256="absent"
TO_RELEASE_MANIFEST_SHA256="absent"
TO_RELEASE_SHA256SUMS_SHA256="absent"
ROLLBACK_PROTECTED_CONTAINER_COUNT="absent"
ROLLBACK_PROTECTED_CONTAINER_SHA256="absent"
ROLLBACK_AUTHORIZED_CRON_SHA256="absent"
ROLLBACK_AUTHORIZED_DATABASE_IDENTITY="absent"
ROLLBACK_AUTHORIZED_REPORT_IDENTITY="absent"
ROLLBACK_AUTHORIZED_NGINX_SHA256="absent"
ROLLBACK_AUTHORIZED_LOCK_IDENTITIES_B64="absent"
CURRENT_RUNTIME_SNAPSHOT=""
CURRENT_EXPECTED_IMAGE_ID=""
TARGET_RUNTIME_SNAPSHOT=""
TARGET_EXPECTED_IMAGE_ID=""
validate_target_deployment_evidence() {
  local evidence_output
  revalidate_rollback_locks || return 1
  # Historical lookup shape `promotion-*-${release_sha}.json` is intentionally
  # not evaluated: callers must supply one exact path and digest.
  evidence_output="$(python3 - \
    "${EVIDENCE_ROOT}" "${DUAL_DATA_ROLLBACK}" \
    "${EXPECTED_CURRENT}" "${TARGET_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${FROM_DATA_INVENTORY_SHA}" "${FROM_DATA_FILE_COUNT}" "${FROM_DATA_TOTAL_BYTES}" \
    "${TARGET_DATA_RELEASE}" "${TARGET_DATA_POINTER_SHA}" \
    "${TO_DATA_INVENTORY_SHA}" "${TO_DATA_FILE_COUNT}" "${TO_DATA_TOTAL_BYTES}" \
    "${PROMOTION_RECEIPT_INPUT}" "${PROMOTION_RECEIPT_SHA_INPUT}" \
    "${AUTHORIZATION_PACKET_INPUT}" "${AUTHORIZATION_PACKET_SHA_INPUT}" \
    "${AUTHORIZATION_PERMIT_INPUT}" "${AUTHORIZATION_PERMIT_SHA_INPUT}" \
    "${PRODUCTION_BASELINE_INPUT}" "${PRODUCTION_BASELINE_SHA_INPUT}" \
    "${ROLLBACK_RUNNER_SHA}" "${ROLLBACK_RUNNER_BYTES}" <<'PY'
import base64
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

(
    root_raw, dual_raw, from_site, to_site, from_data_id, from_data_pointer,
    from_inventory, from_count_raw, from_bytes_raw, to_data_id, to_data_pointer,
    to_inventory, to_count_raw, to_bytes_raw, promotion_raw, promotion_expected_sha,
    packet_raw, packet_expected_sha, permit_raw, permit_expected_sha,
    baseline_raw, baseline_expected_sha, runner_sha, runner_bytes_raw,
) = sys.argv[1:]
root = Path(root_raw)
dual = dual_raw == "1"
from_count = int(from_count_raw) if from_count_raw else None
from_bytes = int(from_bytes_raw) if from_bytes_raw else None
to_count = int(to_count_raw) if to_count_raw else None
to_bytes = int(to_bytes_raw) if to_bytes_raw else None
runner_bytes = int(runner_bytes_raw)
sha_re = re.compile(r"^[a-f0-9]{64}$")
v1_allowlist = {
    "0a672425654533326bf183e2cf9ab86d19957450d659d62f0d30ff34b988e819": "e0d57e921ffb54662f883635fb4f20a89ffde898d95293dd1e304178dace6240",
    "4460f75aff7e7979c491a3c59b4419bbf8d886dec0ad62c6a4b6998be54c3cfd": "e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b",
    "6f8d263ca21d7779ffd1344c76f64710f052b1637f083c7d0f72cf44a190e969": "130e228cdf7e9d936a862b5a992533e21ae2d3df01b90889d1b5a0b9ec8571ad",
    "c4e7d2f01b186bfb2313cf5176e388c0c5e6d8ba795e4fcaf15709ffdf6e597a": "9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5",
    "dbab71ee93144b48b88d8c2afedc2d8af02ac0ad3b13be815be9e665524f6373": "6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2",
    "f34148b00c16d24a1a7e364f3f6469474a6dbf82c651fe57d89db7427035c49c": "ebaa5443906628145f9fbe05777d4218b1ec6d53b78e9d7f4f86fa8fbe9df313",
}

def safe_json(path, expected_sha, label):
    if path.parent != root or not path.is_absolute():
        raise ValueError(f"{label} path escaped the evidence root")
    if sha_re.fullmatch(expected_sha or "") is None:
        raise ValueError(f"{label} explicit SHA-256 binding is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        linked = os.lstat(path)
        if (
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(linked.st_mode)
            or before.st_dev != linked.st_dev
            or before.st_ino != linked.st_ino
            or before.st_nlink != 1
            or linked.st_nlink != 1
            or before.st_uid != os.getuid()
            or linked.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or stat.S_IMODE(linked.st_mode) != 0o600
        ):
            raise ValueError(f"{label} metadata is unsafe")
        raw = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            raw += chunk
        after = os.fstat(descriptor)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or len(raw) != before.st_size
        ):
            raise ValueError(f"{label} changed while reading")
    finally:
        os.close(descriptor)
    value = json.loads(raw)
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if raw != canonical:
        raise ValueError(f"{label} is not canonical JSON")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha:
        raise ValueError(f"{label} SHA-256 mismatch")
    return digest, value

def valid_sha(value):
    return isinstance(value, str) and sha_re.fullmatch(value) is not None

def artifact_digest(artifacts, key):
    record = artifacts.get(key) if isinstance(artifacts, dict) else None
    if (
        not isinstance(record, dict)
        or set(record) != {"bytes", "path", "sha256"}
        or type(record.get("bytes")) is not int
        or record["bytes"] <= 0
        or not isinstance(record.get("path"), str)
        or not record["path"]
        or not valid_sha(record.get("sha256"))
    ):
        raise ValueError(f"packet {key} artifact binding is invalid")
    relative = PurePosixPath(record["path"])
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        raise ValueError(f"packet {key} artifact path is unsafe")
    return record["sha256"]

def validate_remote(path, expected_digest, expected_release, require_v2):
    digest, value = safe_json(path, expected_digest, "promotion receipt")
    schema = value.get("schema_version")
    required_shas = (
        "collector_id", "cron_sha256", "nginx_sha256", "packet_sha256",
        "permit_sha256", "previous_release_sha256", "release_sha256",
        "translation_id",
    )
    if (
        schema not in {
            "reddit_voc_remote_promotion_receipt_v1",
            "reddit_voc_remote_promotion_receipt_v2",
        }
        or (require_v2 and schema != "reddit_voc_remote_promotion_receipt_v2")
        or value.get("status") != "promoted_pending_public_acceptance"
        or value.get("evidence_grade") != "L4-authorized-live"
        or value.get("release_sha256") != expected_release
        or value.get("previous_release_sha256") == expected_release
        or any(not valid_sha(value.get(name)) for name in required_shas)
        or value.get("candidate_18339_smoke") is not True
        or value.get("production_container_smoke") is not True
        or value.get("collector_restart_count") != 0
        or value.get("translation_restart_count") != 0
        or value.get("database_write") is not False
        or value.get("live_send") is not False
        or value.get("provider_call") is not False
        or value.get("shared_nginx_modified") is not False
    ):
        raise ValueError("remote promotion contract invalid")
    if schema == "reddit_voc_remote_promotion_receipt_v1":
        if v1_allowlist.get(digest) != expected_release:
            raise ValueError("remote v1 receipt is not exactly allowlisted")
        return digest, value
    if (
        not valid_sha(value.get("data_pointer_sha256"))
        or not valid_sha(value.get("previous_data_pointer_sha256"))
        or not valid_sha(value.get("data_inventory_sha256"))
        or not isinstance(value.get("data_release_id"), str)
        or not value["data_release_id"].startswith("reddit_voc_release_")
        or not isinstance(value.get("previous_data_release_id"), str)
        or not value["previous_data_release_id"].startswith("reddit_voc_release_")
        or value["data_release_id"] == value["previous_data_release_id"]
        or value["data_pointer_sha256"] == value["previous_data_pointer_sha256"]
        or type(value.get("data_file_count")) is not int
        or value["data_file_count"] <= 0
        or type(value.get("data_total_bytes")) is not int
        or value["data_total_bytes"] <= 0
        or value.get("four_exports_complete") is not False
        or value.get("candidate_exports_validation_bound") is not True
    ):
        raise ValueError("remote promotion v2 data contract invalid")
    return digest, value

def parse_utc(value, label):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} timestamp is invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} timestamp is invalid") from exc

def validate_forward_authorization(remote):
    packet_path = Path(packet_raw)
    permit_path = Path(permit_raw)
    baseline_path = Path(baseline_raw)
    packet_sha, packet = safe_json(
        packet_path, packet_expected_sha, "authorization packet"
    )
    permit_sha, permit = safe_json(
        permit_path, permit_expected_sha, "authorization permit"
    )
    baseline_sha, baseline = safe_json(
        baseline_path, baseline_expected_sha, "production baseline"
    )
    if remote.get("packet_sha256") != packet_sha or remote.get("permit_sha256") != permit_sha:
        raise ValueError("forward receipt is not bound to the explicit packet and permit")

    target = packet.get("target")
    rollback = packet.get("rollback")
    authorization = packet.get("authorization")
    evidence = packet.get("evidence")
    artifacts = packet.get("artifacts")
    packet_baseline_cas = packet.get("production_baseline_cas")
    execution_runtime = packet.get("execution_runtime")
    rollback_runtime = (
        execution_runtime.get("remote_rollback")
        if isinstance(execution_runtime, dict) else None
    )
    baseline_record = (
        artifacts.get("production_baseline_receipt")
        if isinstance(artifacts, dict) else None
    )
    from_release_manifest_sha = artifact_digest(artifacts, "release_manifest")
    from_release_sha256sums_sha = artifact_digest(
        artifacts, "release_sha256sums"
    )
    expected_allowed_actions = [
        "read_only_remote_preflight",
        "upload_exact_release_artifacts_to_isolated_directory",
        "verify_exact_remote_artifact_hashes",
        "stage_exact_insights_data_release",
        "load_exact_linux_amd64_image",
        "start_only_reddit_voc_insights_candidate_18339",
        "run_candidate_runtime_smoke",
        "compare_and_swap_only_insights_current",
        "compare_and_swap_only_insights_data_current",
        "run_public_production_acceptance",
        "persist_exact_rollback_authority_evidence",
        "rollback_only_insights_current",
        "rollback_only_insights_data_current",
    ]
    expected_forbidden_actions = [
        "modify_collector",
        "restart_collector",
        "modify_cron",
        "modify_shared_nginx",
        "modify_tls",
        "modify_dns",
        "modify_other_docker_environment",
        "docker_prune",
        "provider_call",
        "database_write",
        "schedule_change",
        "live_send",
        "enable_candidate_registry_automation",
        "claim_four_exports_complete",
    ]
    rollback_keys = {
        "readiness_mode",
        "ready",
        "scope",
        "shared_nginx_change_allowed",
        "target_data_file_count",
        "target_data_inventory_sha256",
        "target_data_pointer_sha256",
        "target_data_release_id",
        "target_data_total_bytes",
        "target_release_manifest_sha256",
        "target_release_sha256",
        "target_release_sha256s_sha256",
        "valid_until_utc",
    }
    if (
        packet.get("schema_version") != "reddit_voc_promotion_packet_v4"
        or packet.get("status") != "ready_for_owner_authorization"
        or not isinstance(target, dict)
        or target.get("release_sha256") != from_site
        or target.get("expected_current_release_sha256") != to_site
        or target.get("data_release_id") != from_data_id
        or target.get("target_data_pointer_sha256") != from_data_pointer
        or target.get("expected_current_data_release_id") != to_data_id
        or target.get("expected_current_data_pointer_sha256") != to_data_pointer
        or not isinstance(rollback, dict)
        or set(rollback) != rollback_keys
        or rollback.get("readiness_mode") != "immediate_same_baseline_window"
        or rollback.get("ready") is not True
        or rollback.get("scope") != "insights_site_and_data_current"
        or rollback.get("shared_nginx_change_allowed") is not False
        or rollback.get("target_release_sha256") != to_site
        or rollback.get("target_data_release_id") != to_data_id
        or rollback.get("target_data_pointer_sha256") != to_data_pointer
        or rollback.get("target_data_inventory_sha256") != to_inventory
        or rollback.get("target_data_file_count") != to_count
        or rollback.get("target_data_total_bytes") != to_bytes
        or not valid_sha(rollback.get("target_release_manifest_sha256"))
        or not valid_sha(rollback.get("target_release_sha256s_sha256"))
        or rollback.get("valid_until_utc") != packet.get("expires_at_utc")
        or not isinstance(authorization, dict)
        or authorization.get("permit_required") is not True
        or authorization.get("consumed") is not False
        or authorization.get("promotion_authorized") is not False
        or authorization.get("allowed_actions") != expected_allowed_actions
        or authorization.get("forbidden_actions") != expected_forbidden_actions
        or not isinstance(evidence, dict)
        or not isinstance(packet_baseline_cas, dict)
        or evidence.get("all_artifacts_reopened") is not True
        or type(evidence.get("baseline_max_age_seconds")) is not int
        or evidence["baseline_max_age_seconds"] <= 0
        or not isinstance(baseline_record, dict)
        or baseline_record.get("sha256") != baseline_sha
        or not isinstance(rollback_runtime, dict)
        or rollback_runtime.get("sha256") != runner_sha
        or rollback_runtime.get("bytes") != runner_bytes
        or Path(str(rollback_runtime.get("path", ""))).name
        != "remote_rollback_insights.sh"
    ):
        raise ValueError("packet does not bind the exact forward and rollback tuples")

    binding = permit.get("packet")
    permit_authorization = permit.get("authorization")
    if (
        permit.get("schema_version") != "reddit_voc_promotion_permit_v1"
        or permit.get("status") != "authorized_unconsumed"
        or permit.get("consumed") is not False
        or permit.get("packet_sha256") != packet_sha
        or permit.get("release_sha256") != from_site
        or permit.get("contract") != "reddit_voc_promotion_permit_exact_binding_v4"
        or permit.get("scope") != "insights_site_and_data_current"
        or not isinstance(binding, dict)
        or binding.get("packet_sha256") != packet_sha
        or binding.get("release_sha256") != from_site
        or binding.get("expected_current_release_sha256") != to_site
        or binding.get("data_release_id") != from_data_id
        or binding.get("target_data_pointer_sha256") != from_data_pointer
        or binding.get("expected_current_data_release_id") != to_data_id
        or binding.get("expected_current_data_pointer_sha256") != to_data_pointer
        or binding.get("packet_id") != packet.get("packet_id")
        or binding.get("nonce") != packet.get("nonce")
        or binding.get("execution_runtime") != execution_runtime
        or not isinstance(permit_authorization, dict)
        or permit_authorization.get("authorized_by") != "owner_explicit_confirmation"
        or permit_authorization.get("owner_confirmation")
        != "authorize_exact_reddit_voc_packet_and_release"
        or permit.get("authorized_actions") != expected_allowed_actions
        or permit.get("forbidden_actions") != expected_forbidden_actions
        or permit_authorization.get("authorized_actions")
        != expected_allowed_actions
        or permit_authorization.get("forbidden_actions")
        != expected_forbidden_actions
    ):
        raise ValueError("permit does not authenticate the exact forward transaction")

    observations = baseline.get("observations")
    insights = observations.get("insights") if isinstance(observations, dict) else None
    collector = (
        observations.get("collector") if isinstance(observations, dict) else None
    )
    translation = (
        observations.get("libretranslate")
        if isinstance(observations, dict) else None
    )
    containers = (
        observations.get("running_containers")
        if isinstance(observations, dict) else None
    )
    cron = observations.get("cron") if isinstance(observations, dict) else None
    database = (
        observations.get("database") if isinstance(observations, dict) else None
    )
    report_pointer = (
        observations.get("report_pointer")
        if isinstance(observations, dict) else None
    )
    shared_nginx = (
        observations.get("shared_nginx")
        if isinstance(observations, dict) else None
    )
    runtime_contract = (
        insights.get("runtime_contract") if isinstance(insights, dict) else None
    )
    runtime_network = (
        runtime_contract.get("network")
        if isinstance(runtime_contract, dict) else None
    )
    site_tuple = (
        observations.get("site_data_tuple") if isinstance(observations, dict) else None
    )
    release_sums = (
        observations.get("release_sha256s")
        if isinstance(observations, dict) else None
    )
    site_manifest = (
        observations.get("site_release_manifest")
        if isinstance(observations, dict) else None
    )
    locks = observations.get("locks") if isinstance(observations, dict) else None
    identities = locks.get("identities") if isinstance(locks, dict) else None
    expected_locks = {
        "data_release": "/opt/reddit-voc-insights-data/locks/data-release.lock",
        "deploy": "/opt/reddit-voc-insights-site/.deploy.lock",
        "promotion": "/opt/reddit-voc-insights-site/.promotion.lock",
    }

    def zero_integer(value):
        return type(value) is int and value == 0

    def positive_integer(value):
        return type(value) is int and value > 0

    def pristine_container(value):
        return (
            isinstance(value, dict)
            and valid_sha(value.get("container_id"))
            and value.get("health") == "healthy"
            and zero_integer(value.get("restart_count"))
        )

    def stable_identity(value, *, allow_absent=False):
        return (
            isinstance(value, dict)
            and value.get("stable") is True
            and isinstance(value.get("before"), str)
            and (
                (allow_absent and value["before"] == "absent")
                or re.fullmatch(r"[0-9]+:[0-9]+:[0-9]+", value["before"])
                is not None
            )
            and value.get("after") == value["before"]
        )

    locks_valid = isinstance(identities, dict) and set(identities) == set(expected_locks)
    if locks_valid:
        for name, expected_path in expected_locks.items():
            item = identities.get(name)
            if (
                not isinstance(item, dict)
                or set(item) != {
                    "device", "inode", "mode", "nlink", "path", "uid"
                }
                or item.get("path") != expected_path
                or item.get("mode") != "0600"
                or item.get("nlink") != 1
                or type(item.get("device")) is not int
                or item["device"] <= 0
                or type(item.get("inode")) is not int
                or item["inode"] <= 0
                or type(item.get("uid")) is not int
                or item["uid"] < 0
            ):
                locks_valid = False
                break
    if (
        baseline.get("schema_version") != "reddit_voc_production_baseline_receipt_v1"
        or baseline.get("status") != "passed"
        or baseline.get("evidence_grade") != "L3-production-read-only"
        or baseline.get("current_release_sha256") != to_site
        or baseline.get("production_unchanged") is not True
        or baseline.get("remote_write") is not False
        or not isinstance(observations, dict)
        or observations.get("quiet_counts_stable") is not True
        or not pristine_container(collector)
        or not pristine_container(translation)
        or not isinstance(insights, dict)
        or not valid_sha(insights.get("container_id"))
        or insights.get("health") != "healthy"
        or insights.get("restart_count") != 0
        or insights.get("release_label") != to_site
        or insights.get("internal_release_sha256") != to_site
        or insights.get("current_symlink") != f"releases/{to_site}"
        or insights.get("internal_pointer") != to_data_id
        or insights.get("internal_pointer_sha256") != to_data_pointer
        or insights.get("internal_pointer_symlink") != f"releases/{to_data_id}"
        or insights.get("data_inventory_sha256") != to_inventory
        or insights.get("data_file_count") != to_count
        or insights.get("data_total_bytes") != to_bytes
        or not isinstance(runtime_contract, dict)
        or re.fullmatch(
            r"sha256:[a-f0-9]{64}", str(runtime_contract.get("image_id"))
        ) is None
        or not isinstance(runtime_network, dict)
        or not valid_sha(runtime_network.get("id"))
        or not isinstance(containers, dict)
        or not positive_integer(containers.get("count"))
        or not valid_sha(containers.get("inventory_sha256"))
        or not positive_integer(containers.get("protected_count"))
        or not valid_sha(containers.get("protected_inventory_sha256"))
        or containers.get("protected_scope")
        != "docker_ps_a_excluding_insights_transaction"
        or containers.get("stable") is not True
        or not isinstance(cron, dict)
        or cron.get("stable") is not True
        or not valid_sha(cron.get("sha256"))
        or observations.get("cron_sha256") != cron.get("sha256")
        or not stable_identity(database)
        or not stable_identity(report_pointer, allow_absent=True)
        or not isinstance(shared_nginx, dict)
        or shared_nginx.get("stable") is not True
        or not valid_sha(shared_nginx.get("sha256"))
        or observations.get("shared_nginx_sha256")
        != shared_nginx.get("sha256")
        or not isinstance(site_tuple, dict)
        or site_tuple.get("stable") is not True
        or site_tuple.get("site_release_sha256") != to_site
        or site_tuple.get("data_release_id") != to_data_id
        or site_tuple.get("pointer_sha256") != to_data_pointer
        or site_tuple.get("data_inventory_sha256") != to_inventory
        or site_tuple.get("data_file_count") != to_count
        or site_tuple.get("data_total_bytes") != to_bytes
        or not isinstance(release_sums, dict)
        or release_sums.get("verified_before") is not True
        or release_sums.get("verified_after") is not True
        or release_sums.get("stable") is not True
        or not valid_sha(release_sums.get("sha256"))
        or observations.get("release_sha256sums_verified") is not True
        or not isinstance(site_manifest, dict)
        or site_manifest.get("stable") is not True
        or site_manifest.get("served_exact") is not True
        or site_manifest.get("release_sha256") != to_site
        or site_manifest.get("data_release_id") != to_data_id
        or site_manifest.get("pointer_sha256") != to_data_pointer
        or not valid_sha(site_manifest.get("manifest_sha256"))
        or site_manifest.get("manifest_sha256")
        != site_tuple.get("site_manifest_sha256")
        or rollback.get("target_release_manifest_sha256")
        != site_manifest.get("manifest_sha256")
        or rollback.get("target_release_sha256s_sha256")
        != release_sums.get("sha256")
        or not isinstance(locks, dict)
        or locks.get("stable") is not True
        or not locks_valid
    ):
        raise ValueError("baseline does not prove the exact previous site/data tuple")

    derived_baseline_cas = {
        "collector": {
            "container_id": collector["container_id"],
            "health": collector["health"],
            "restart_count": collector["restart_count"],
        },
        "container_inventory": {
            "count": containers["count"],
            "protected_count": containers["protected_count"],
            "protected_sha256": containers["protected_inventory_sha256"],
            "sha256": containers["inventory_sha256"],
        },
        "cron_sha256": cron["sha256"],
        "database_identity": database["before"],
        "insights": {
            "container_id": insights["container_id"],
            "health": insights["health"],
            "image_id": runtime_contract["image_id"],
            "network_id": runtime_network["id"],
            "restart_count": insights["restart_count"],
        },
        "lock_identities": identities,
        "observed_at_utc": baseline.get("observed_at_utc"),
        "report_pointer_identity": report_pointer["before"],
        "shared_nginx_sha256": shared_nginx["sha256"],
        "translation": {
            "container_id": translation["container_id"],
            "health": translation["health"],
            "restart_count": translation["restart_count"],
        },
    }
    if packet_baseline_cas != derived_baseline_cas:
        raise ValueError("packet production baseline CAS does not match explicit baseline")
    lock_identities_b64 = base64.urlsafe_b64encode(
        json.dumps(
            identities, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).decode("ascii")

    baseline_at = parse_utc(baseline.get("observed_at_utc"), "baseline observed")
    packet_at = parse_utc(packet.get("generated_at_utc"), "packet generated")
    packet_expires = parse_utc(packet.get("expires_at_utc"), "packet expiry")
    authorized_at = parse_utc(
        permit.get("authorized_recorded_at_utc"), "permit authorization"
    )
    permit_expires = parse_utc(permit.get("expires_at_utc"), "permit expiry")
    promoted_at = parse_utc(remote.get("generated_at_utc"), "promotion receipt")
    baseline_age = (packet_at - baseline_at).total_seconds()
    if (
        baseline_age < 0
        or baseline_age > evidence["baseline_max_age_seconds"]
        or not (packet_at <= authorized_at <= promoted_at)
        or promoted_at >= packet_expires
        or promoted_at >= permit_expires
    ):
        raise ValueError("transaction time ordering or baseline freshness is invalid")
    return (
        packet_path, packet_sha, permit_path, permit_sha, baseline_path, baseline_sha,
        from_release_manifest_sha, from_release_sha256sums_sha,
        site_manifest["manifest_sha256"], release_sums["sha256"],
        containers["protected_count"], containers["protected_inventory_sha256"],
        cron["sha256"], database["before"], report_pointer["before"],
        shared_nginx["sha256"], lock_identities_b64,
    )

if dual:
    for path in [Path(promotion_raw)]:
        try:
            digest, remote = validate_remote(
                path, promotion_expected_sha, from_site, True
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(str(exc)) from exc
        if (
            remote.get("previous_release_sha256") == to_site
            and remote.get("data_release_id") == from_data_id
            and remote.get("data_pointer_sha256") == from_data_pointer
            and remote.get("data_inventory_sha256") == from_inventory
            and remote.get("data_file_count") == from_count
            and remote.get("data_total_bytes") == from_bytes
            and remote.get("previous_data_release_id") == to_data_id
            and remote.get("previous_data_pointer_sha256") == to_data_pointer
        ):
            (
                packet_path, packet_sha, permit_path, permit_sha,
                baseline_path, baseline_sha, from_release_manifest_sha,
                from_release_sha256sums_sha, to_release_manifest_sha,
                to_release_sha256sums_sha, protected_container_count,
                protected_container_sha, authorized_cron_sha,
                authorized_database_identity, authorized_report_identity,
                authorized_nginx_sha, authorized_lock_identities_b64,
            ) = validate_forward_authorization(remote)
            print(
                "forward_previous_authorized", path, digest, "absent", "absent",
                packet_path, packet_sha, permit_path, permit_sha,
                baseline_path, baseline_sha, from_release_manifest_sha,
                from_release_sha256sums_sha, to_release_manifest_sha,
                to_release_sha256sums_sha, protected_container_count,
                protected_container_sha, authorized_cron_sha,
                authorized_database_identity, authorized_report_identity,
                authorized_nginx_sha, authorized_lock_identities_b64, sep="\t",
            )
            raise SystemExit(0)

    raise SystemExit(
        "dual rollback only supports the exact previous tuple of the supplied forward receipt"
    )

else:
    for path in [Path(promotion_raw)]:
        try:
            digest, remote = validate_remote(
                path, promotion_expected_sha, to_site, False
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if remote.get("schema_version") == "reddit_voc_remote_promotion_receipt_v1":
            print(
                "allowlisted_v1_target", path, digest, "absent", "absent",
                "absent", "absent", "absent", "absent", "absent", "absent",
                "absent", "absent", "absent", "absent", "absent", "absent",
                "absent", "absent", "absent", "absent", "absent",
                sep="\t",
            )
            raise SystemExit(0)

raise SystemExit(
    "no exact rollback evidence: plaintext allowlist is empty and pending target receipts are forbidden"
)
PY
)" || return 1
  IFS=$'\t' read -r ROLLBACK_EVIDENCE_MODE TARGET_DEPLOYMENT_EVIDENCE \
    TARGET_DEPLOYMENT_EVIDENCE_SHA ROLLBACK_ACCEPTANCE_EVIDENCE \
    ROLLBACK_ACCEPTANCE_EVIDENCE_SHA ROLLBACK_AUTHORIZATION_PACKET \
    ROLLBACK_AUTHORIZATION_PACKET_SHA ROLLBACK_AUTHORIZATION_PERMIT \
    ROLLBACK_AUTHORIZATION_PERMIT_SHA ROLLBACK_PRODUCTION_BASELINE \
    ROLLBACK_PRODUCTION_BASELINE_SHA FROM_RELEASE_MANIFEST_SHA256 \
    FROM_RELEASE_SHA256SUMS_SHA256 TO_RELEASE_MANIFEST_SHA256 \
    TO_RELEASE_SHA256SUMS_SHA256 ROLLBACK_PROTECTED_CONTAINER_COUNT \
    ROLLBACK_PROTECTED_CONTAINER_SHA256 ROLLBACK_AUTHORIZED_CRON_SHA256 \
    ROLLBACK_AUTHORIZED_DATABASE_IDENTITY ROLLBACK_AUTHORIZED_REPORT_IDENTITY \
    ROLLBACK_AUTHORIZED_NGINX_SHA256 ROLLBACK_AUTHORIZED_LOCK_IDENTITIES_B64 \
    <<< "${evidence_output}"
  if [[ -z "${ROLLBACK_EVIDENCE_MODE}" || -z "${TARGET_DEPLOYMENT_EVIDENCE_SHA}" ]]; then
    echo "rollback evidence selection returned an incomplete binding" >&2
    return 1
  fi
  if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
    if [[ ! "${ROLLBACK_PROTECTED_CONTAINER_COUNT}" =~ ^[1-9][0-9]*$ || \
          ! "${ROLLBACK_PROTECTED_CONTAINER_SHA256}" =~ ^[a-f0-9]{64}$ || \
          ! "${ROLLBACK_AUTHORIZED_CRON_SHA256}" =~ ^[a-f0-9]{64}$ || \
          ! "${ROLLBACK_AUTHORIZED_NGINX_SHA256}" =~ ^[a-f0-9]{64}$ || \
          ! "${ROLLBACK_AUTHORIZED_DATABASE_IDENTITY}" =~ ^[0-9]+:[0-9]+:[0-9]+$ || \
          ! "${ROLLBACK_AUTHORIZED_REPORT_IDENTITY}" =~ ^[0-9]+:[0-9]+:[0-9]+$ || \
          -z "${ROLLBACK_AUTHORIZED_LOCK_IDENTITIES_B64}" ]]; then
      echo "rollback evidence selected an invalid authorized control-plane baseline" >&2
      return 1
    fi
    revalidate_rollback_locks || return 1
    assert_authorized_protected_container_baseline || return 1
    assert_authorized_control_plane_baseline || return 1
  fi
}

reverify_bound_release_artifacts() {
  [[ "${DUAL_DATA_ROLLBACK}" == "1" ]] || return 0
  revalidate_rollback_locks || return 1
  python3 - \
    "${RELEASE_ROOT}" "${EXPECTED_CURRENT}" "${TARGET_RELEASE}" \
    "${FROM_RELEASE_MANIFEST_SHA256}" "${FROM_RELEASE_SHA256SUMS_SHA256}" \
    "${TO_RELEASE_MANIFEST_SHA256}" "${TO_RELEASE_SHA256SUMS_SHA256}" <<'PY'
import hashlib
import os
import re
import stat
import sys

(
    root,
    from_release,
    to_release,
    from_manifest_sha,
    from_sums_sha,
    to_manifest_sha,
    to_sums_sha,
) = sys.argv[1:]
sha_re = re.compile(r"^[a-f0-9]{64}$")
if (
    sha_re.fullmatch(from_release) is None
    or sha_re.fullmatch(to_release) is None
    or any(
        sha_re.fullmatch(value) is None
        for value in (
            from_manifest_sha,
            from_sums_sha,
            to_manifest_sha,
            to_sums_sha,
        )
    )
):
    raise SystemExit("bound release artifact identity is invalid")

def same_identity(opened, linked):
    return (opened.st_dev, opened.st_ino) == (linked.st_dev, linked.st_ino)

def immutable_directory(metadata):
    return (
        metadata.st_uid == os.getuid() and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o555
    )

def immutable_file(metadata):
    return (
        metadata.st_uid == os.getuid() and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o444
    )

def safe_directory(opened, linked, label):
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(linked.st_mode)
        or not same_identity(opened, linked)
        or not immutable_directory(opened)
        or not immutable_directory(linked)
    ):
        raise SystemExit(f"{label} directory identity is unsafe")

root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    root_opened = os.fstat(root_fd)
    root_linked = os.lstat(root)
    safe_directory(root_opened, root_linked, "release root")

    def verify_release(release, manifest_sha, sums_sha, label):
        directory_fd = os.open(
            release,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        try:
            directory_before = os.fstat(directory_fd)
            directory_linked = os.stat(
                release, dir_fd=root_fd, follow_symlinks=False
            )
            safe_directory(directory_before, directory_linked, label)

            def file_sha256(name):
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd
                )
                try:
                    before = os.fstat(descriptor)
                    linked = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or not stat.S_ISREG(linked.st_mode)
                        or not same_identity(before, linked)
                        or before.st_nlink != 1
                        or linked.st_nlink != 1
                        or not immutable_file(before)
                        or not immutable_file(linked)
                        or before.st_size <= 0
                    ):
                        raise SystemExit(f"{label} {name} metadata is unsafe")
                    digest = hashlib.sha256()
                    size = 0
                    while True:
                        chunk = os.read(descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                    after = os.fstat(descriptor)
                    linked_after = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    if (
                        (
                            after.st_dev,
                            after.st_ino,
                            after.st_size,
                            after.st_mtime_ns,
                        )
                        != (
                            before.st_dev,
                            before.st_ino,
                            before.st_size,
                            before.st_mtime_ns,
                        )
                        or not same_identity(after, linked_after)
                        or linked_after.st_nlink != 1
                        or size != before.st_size
                    ):
                        raise SystemExit(f"{label} {name} changed while hashing")
                    return digest.hexdigest()
                finally:
                    os.close(descriptor)

            if file_sha256("release-manifest.json") != manifest_sha:
                raise SystemExit(f"{label} release-manifest.json digest mismatch")
            if file_sha256("SHA256SUMS") != sums_sha:
                raise SystemExit(f"{label} SHA256SUMS digest mismatch")

            directory_after = os.fstat(directory_fd)
            directory_linked_after = os.stat(
                release, dir_fd=root_fd, follow_symlinks=False
            )
            if (
                (directory_after.st_dev, directory_after.st_ino)
                != (directory_before.st_dev, directory_before.st_ino)
                or not same_identity(directory_after, directory_linked_after)
            ):
                raise SystemExit(f"{label} release directory changed while hashing")
        finally:
            os.close(directory_fd)

    verify_release(
        from_release,
        from_manifest_sha,
        from_sums_sha,
        "current/from release",
    )
    verify_release(
        to_release,
        to_manifest_sha,
        to_sums_sha,
        "target/to release",
    )
    root_after = os.fstat(root_fd)
    root_linked_after = os.lstat(root)
    if (
        (root_after.st_dev, root_after.st_ino)
        != (root_opened.st_dev, root_opened.st_ino)
        or not same_identity(root_after, root_linked_after)
    ):
        raise SystemExit("release root changed while hashing")
finally:
    os.close(root_fd)
PY
}

revalidate_bound_rollback_evidence() {
  local expected_binding observed_binding
  expected_binding="${ROLLBACK_EVIDENCE_MODE}|${TARGET_DEPLOYMENT_EVIDENCE}|${TARGET_DEPLOYMENT_EVIDENCE_SHA}|${ROLLBACK_ACCEPTANCE_EVIDENCE}|${ROLLBACK_ACCEPTANCE_EVIDENCE_SHA}|${ROLLBACK_AUTHORIZATION_PACKET}|${ROLLBACK_AUTHORIZATION_PACKET_SHA}|${ROLLBACK_AUTHORIZATION_PERMIT}|${ROLLBACK_AUTHORIZATION_PERMIT_SHA}|${ROLLBACK_PRODUCTION_BASELINE}|${ROLLBACK_PRODUCTION_BASELINE_SHA}|${FROM_RELEASE_MANIFEST_SHA256}|${FROM_RELEASE_SHA256SUMS_SHA256}|${TO_RELEASE_MANIFEST_SHA256}|${TO_RELEASE_SHA256SUMS_SHA256}|${ROLLBACK_PROTECTED_CONTAINER_COUNT}|${ROLLBACK_PROTECTED_CONTAINER_SHA256}|${ROLLBACK_AUTHORIZED_CRON_SHA256}|${ROLLBACK_AUTHORIZED_DATABASE_IDENTITY}|${ROLLBACK_AUTHORIZED_REPORT_IDENTITY}|${ROLLBACK_AUTHORIZED_NGINX_SHA256}|${ROLLBACK_AUTHORIZED_LOCK_IDENTITIES_B64}"
  validate_target_deployment_evidence "${TARGET_RELEASE}"
  observed_binding="${ROLLBACK_EVIDENCE_MODE}|${TARGET_DEPLOYMENT_EVIDENCE}|${TARGET_DEPLOYMENT_EVIDENCE_SHA}|${ROLLBACK_ACCEPTANCE_EVIDENCE}|${ROLLBACK_ACCEPTANCE_EVIDENCE_SHA}|${ROLLBACK_AUTHORIZATION_PACKET}|${ROLLBACK_AUTHORIZATION_PACKET_SHA}|${ROLLBACK_AUTHORIZATION_PERMIT}|${ROLLBACK_AUTHORIZATION_PERMIT_SHA}|${ROLLBACK_PRODUCTION_BASELINE}|${ROLLBACK_PRODUCTION_BASELINE_SHA}|${FROM_RELEASE_MANIFEST_SHA256}|${FROM_RELEASE_SHA256SUMS_SHA256}|${TO_RELEASE_MANIFEST_SHA256}|${TO_RELEASE_SHA256SUMS_SHA256}|${ROLLBACK_PROTECTED_CONTAINER_COUNT}|${ROLLBACK_PROTECTED_CONTAINER_SHA256}|${ROLLBACK_AUTHORIZED_CRON_SHA256}|${ROLLBACK_AUTHORIZED_DATABASE_IDENTITY}|${ROLLBACK_AUTHORIZED_REPORT_IDENTITY}|${ROLLBACK_AUTHORIZED_NGINX_SHA256}|${ROLLBACK_AUTHORIZED_LOCK_IDENTITIES_B64}"
  if [[ "${observed_binding}" != "${expected_binding}" ]]; then
    echo "rollback transaction evidence binding changed" >&2
    return 1
  fi
  reverify_bound_release_artifacts || return 1
}

runtime_snapshot_directory() {
  local release_sha="$1"
  if [[ "${release_sha}" == "${EXPECTED_CURRENT}" && \
        -n "${CURRENT_RUNTIME_SNAPSHOT}" ]]; then
    printf '%s\n' "${CURRENT_RUNTIME_SNAPSHOT}"
  elif [[ "${release_sha}" == "${TARGET_RELEASE}" && \
          -n "${TARGET_RUNTIME_SNAPSHOT}" ]]; then
    printf '%s\n' "${TARGET_RUNTIME_SNAPSHOT}"
  else
    echo "release runtime snapshot is not prepared: ${release_sha}" >&2
    return 1
  fi
}

runtime_expected_image_id() {
  local release_sha="$1"
  if [[ "${release_sha}" == "${EXPECTED_CURRENT}" && \
        -n "${CURRENT_EXPECTED_IMAGE_ID}" ]]; then
    printf '%s\n' "${CURRENT_EXPECTED_IMAGE_ID}"
  elif [[ "${release_sha}" == "${TARGET_RELEASE}" && \
          -n "${TARGET_EXPECTED_IMAGE_ID}" ]]; then
    printf '%s\n' "${TARGET_EXPECTED_IMAGE_ID}"
  else
    echo "release expected image ID is not prepared: ${release_sha}" >&2
    return 1
  fi
}

prepare_release_runtime_snapshot() {
  local release_sha="$1"
  local source_dir snapshot_dir expected_manifest_sha expected_sums_sha
  local expected_image_id
  if [[ "${release_sha}" == "${EXPECTED_CURRENT}" && \
        -n "${CURRENT_RUNTIME_SNAPSHOT}" ]]; then
    return 0
  fi
  if [[ "${release_sha}" == "${TARGET_RELEASE}" && \
        -n "${TARGET_RUNTIME_SNAPSHOT}" ]]; then
    return 0
  fi
  if [[ "${release_sha}" == "${EXPECTED_CURRENT}" ]]; then
    expected_manifest_sha="${FROM_RELEASE_MANIFEST_SHA256}"
    expected_sums_sha="${FROM_RELEASE_SHA256SUMS_SHA256}"
  elif [[ "${release_sha}" == "${TARGET_RELEASE}" ]]; then
    expected_manifest_sha="${TO_RELEASE_MANIFEST_SHA256}"
    expected_sums_sha="${TO_RELEASE_SHA256SUMS_SHA256}"
  else
    echo "runtime snapshot release is outside the rollback tuple" >&2
    return 1
  fi
  reverify_bound_release_artifacts || return 1
  source_dir="$(release_dir "${release_sha}")" || return 1
  snapshot_dir="$(
    mktemp -d "${RELEASE_ROOT}/.rollback-runtime-${release_sha}.XXXXXX"
  )" || return 1
  chmod 0700 "${snapshot_dir}" || {
    rm -rf -- "${snapshot_dir}"
    return 1
  }
  expected_image_id="$(
    python3 - \
      "${source_dir}" "${snapshot_dir}" "${release_sha}" \
      "${expected_manifest_sha}" "${expected_sums_sha}" <<'PY'
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath

source = Path(sys.argv[1])
target = Path(sys.argv[2])
release, expected_manifest_sha, expected_sums_sha = sys.argv[3:]
sha_re = re.compile(r"^[a-f0-9]{64}$")
image_name = f"reddit-voc-insights-{release}.tar"
payload_names = {
    "compose.yaml",
    "dist-SHA256SUMS",
    "release-manifest.json",
    image_name,
}
required_names = payload_names | {"SHA256SUMS"}

def immutable_directory(metadata):
    return (
        metadata.st_uid == os.getuid() and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o555
    )

def immutable_file(metadata):
    return (
        metadata.st_uid == os.getuid() and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o444
    )

if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("runtime snapshot requires O_NOFOLLOW")
source_link = source.lstat()
target_link = target.lstat()
if (
    not stat.S_ISDIR(source_link.st_mode)
    or not immutable_directory(source_link)
    or not stat.S_ISDIR(target_link.st_mode)
    or target_link.st_uid != os.getuid()
    or stat.S_IMODE(target_link.st_mode) != 0o700
):
    raise SystemExit("runtime snapshot directory metadata is unsafe")
source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
target_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

def stable_read(name: str) -> bytes:
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_fd
        )
    except OSError as exc:
        raise SystemExit(
            f"runtime source file metadata is unsafe: {name}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        linked_before = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(linked_before.st_mode)
            or (before.st_dev, before.st_ino)
            != (linked_before.st_dev, linked_before.st_ino)
            or before.st_nlink != 1
            or linked_before.st_nlink != 1
            or not immutable_file(before)
            or not immutable_file(linked_before)
        ):
            raise SystemExit(f"runtime source file metadata is unsafe: {name}")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        linked_after = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        payload = b"".join(chunks)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            or (after.st_dev, after.st_ino)
            != (linked_after.st_dev, linked_after.st_ino)
            or linked_after.st_nlink != 1
            or len(payload) != before.st_size
        ):
            raise SystemExit(f"runtime source file changed while reading: {name}")
        return payload
    finally:
        os.close(descriptor)

def publish(name: str, payload: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
        dir_fd=target_fd,
    )
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o400
        ):
            raise SystemExit(f"runtime snapshot file metadata is unsafe: {name}")
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise SystemExit(f"runtime snapshot write was incomplete: {name}")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    verification = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=target_fd)
    try:
        metadata = os.fstat(verification)
        observed = bytearray()
        while chunk := os.read(verification, 1024 * 1024):
            observed.extend(chunk)
        after = os.fstat(verification)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or bytes(observed) != payload
            or (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
        ):
            raise SystemExit(f"runtime snapshot verification failed: {name}")
    finally:
        os.close(verification)

try:
    source_before = os.fstat(source_fd)
    sums_payload = stable_read("SHA256SUMS")
    observed_sums_sha = hashlib.sha256(sums_payload).hexdigest()
    if (
        expected_sums_sha != "absent"
        and (
            sha_re.fullmatch(expected_sums_sha) is None
            or observed_sums_sha != expected_sums_sha
        )
    ):
        raise SystemExit("runtime SHA256SUMS differs from the authorized digest")
    entries = {}
    for raw_line in sums_payload.decode("utf-8").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([^\x00-\x1f]+)", raw_line)
        if match is None:
            raise SystemExit("runtime SHA256SUMS contains an invalid entry")
        digest, name = match.groups()
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or len(path.parts) != 1
            or name in entries
            or "\\" in name
        ):
            raise SystemExit("runtime SHA256SUMS contains an unsafe entry")
        entries[name] = digest
    if set(entries) != payload_names:
        raise SystemExit("runtime SHA256SUMS file set is not exact")
    payloads = {"SHA256SUMS": sums_payload}
    for name in sorted(payload_names):
        payload = stable_read(name)
        if hashlib.sha256(payload).hexdigest() != entries[name]:
            raise SystemExit(f"runtime source digest mismatch: {name}")
        payloads[name] = payload
    observed_manifest_sha = hashlib.sha256(
        payloads["release-manifest.json"]
    ).hexdigest()
    if (
        expected_manifest_sha != "absent"
        and (
            sha_re.fullmatch(expected_manifest_sha) is None
            or observed_manifest_sha != expected_manifest_sha
        )
    ):
        raise SystemExit("runtime manifest differs from the authorized digest")
    manifest = json.loads(payloads["release-manifest.json"])
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version")
        != "reddit_voc_insights_site_release_v2"
        or manifest.get("release_sha256") != release
    ):
        raise SystemExit("runtime release manifest identity is invalid")
    for name in sorted(required_names):
        publish(name, payloads[name])
    os.fsync(target_fd)
    source_after = os.fstat(source_fd)
    source_link_after = source.lstat()
    if (
        (source_before.st_dev, source_before.st_ino)
        != (source_after.st_dev, source_after.st_ino)
        or (source_after.st_dev, source_after.st_ino)
        != (source_link_after.st_dev, source_link_after.st_ino)
    ):
        raise SystemExit("runtime source directory changed during snapshot")
    with tarfile.open(
        fileobj=io.BytesIO(payloads[image_name]), mode="r:"
    ) as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or names.count("manifest.json") != 1:
            raise SystemExit("runtime image archive manifest is ambiguous")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise SystemExit("runtime image archive contains an unsafe path")
        manifest_member = archive.getmember("manifest.json")
        if not manifest_member.isfile():
            raise SystemExit("runtime image archive manifest is unsafe")
        manifest_stream = archive.extractfile(manifest_member)
        if manifest_stream is None:
            raise SystemExit("runtime image archive manifest is unreadable")
        image_manifest = json.loads(manifest_stream.read())
        if not isinstance(image_manifest, list) or len(image_manifest) != 1:
            raise SystemExit("runtime image archive cardinality mismatch")
        record = image_manifest[0]
        if not isinstance(record, dict):
            raise SystemExit("runtime image archive identity is invalid")
        config_name = record.get("Config")
        config_match = (
            re.fullmatch(
                r"(?:([a-f0-9]{64})\.json|blobs/sha256/([a-f0-9]{64}))",
                config_name,
            )
            if isinstance(config_name, str)
            else None
        )
        if (
            config_match is None
            or record.get("RepoTags") != [f"reddit-voc-insights:{release}"]
            or names.count(config_name) != 1
        ):
            raise SystemExit("runtime image archive identity mismatch")
        config_member = archive.getmember(config_name)
        if not config_member.isfile():
            raise SystemExit("runtime image archive config is unsafe")
        config_stream = archive.extractfile(config_member)
        if config_stream is None:
            raise SystemExit("runtime image archive config is unreadable")
        config_payload = config_stream.read()
    config_digest = hashlib.sha256(config_payload).hexdigest()
    if config_digest != (config_match.group(1) or config_match.group(2)):
        raise SystemExit("runtime image archive config digest mismatch")
    expected_image_id = f"sha256:{config_digest}"
    override_payload = (
        "services:\n"
        "  web:\n"
        f"    image: {expected_image_id}\n"
    ).encode("utf-8")
    publish("compose-image-id.yaml", override_payload)
    os.fsync(target_fd)
    os.chmod(target, 0o500)
    os.fsync(target_fd)
    print(expected_image_id)
finally:
    os.close(target_fd)
    os.close(source_fd)
PY
  )" || {
    chmod 0700 "${snapshot_dir}" >/dev/null 2>&1 || true
    rm -rf -- "${snapshot_dir}"
    return 1
  }
  if [[ ! "${expected_image_id}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "runtime snapshot returned an invalid image ID" >&2
    chmod 0700 "${snapshot_dir}" >/dev/null 2>&1 || true
    rm -rf -- "${snapshot_dir}"
    return 1
  fi
  if [[ "${release_sha}" == "${EXPECTED_CURRENT}" ]]; then
    CURRENT_RUNTIME_SNAPSHOT="${snapshot_dir}"
    CURRENT_EXPECTED_IMAGE_ID="${expected_image_id}"
  else
    TARGET_RUNTIME_SNAPSHOT="${snapshot_dir}"
    TARGET_EXPECTED_IMAGE_ID="${expected_image_id}"
  fi
}

verify_runtime_snapshot() {
  local release_sha="$1"
  local snapshot_dir expected_image_id expected_manifest_sha expected_sums_sha
  if [[ "${release_sha}" == "${EXPECTED_CURRENT}" ]]; then
    expected_manifest_sha="${FROM_RELEASE_MANIFEST_SHA256}"
    expected_sums_sha="${FROM_RELEASE_SHA256SUMS_SHA256}"
  elif [[ "${release_sha}" == "${TARGET_RELEASE}" ]]; then
    expected_manifest_sha="${TO_RELEASE_MANIFEST_SHA256}"
    expected_sums_sha="${TO_RELEASE_SHA256SUMS_SHA256}"
  else
    echo "runtime snapshot verification release is outside the rollback tuple" >&2
    return 1
  fi
  snapshot_dir="$(runtime_snapshot_directory "${release_sha}")" || return 1
  expected_image_id="$(runtime_expected_image_id "${release_sha}")" || return 1
  python3 - \
    "${snapshot_dir}" "${release_sha}" "${expected_image_id}" \
    "${expected_manifest_sha}" "${expected_sums_sha}" <<'PY' || return 1
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import PurePosixPath

(
    root,
    release,
    expected_image_id,
    expected_manifest_sha,
    expected_sums_sha,
) = sys.argv[1:]
image_name = f"reddit-voc-insights-{release}.tar"
payload_names = {
    "compose.yaml",
    "dist-SHA256SUMS",
    "release-manifest.json",
    image_name,
}
required_names = payload_names | {"SHA256SUMS", "compose-image-id.yaml"}
if re.fullmatch(r"sha256:[a-f0-9]{64}", expected_image_id) is None:
    raise SystemExit("runtime snapshot expected image ID is invalid")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("runtime snapshot verification requires O_NOFOLLOW")
root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

def read_file(name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    try:
        before = os.fstat(descriptor)
        linked = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(linked.st_mode)
            or (before.st_dev, before.st_ino) != (linked.st_dev, linked.st_ino)
            or before.st_nlink != 1
            or linked.st_nlink != 1
            or before.st_uid != os.getuid()
            or linked.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o400
            or stat.S_IMODE(linked.st_mode) != 0o400
        ):
            raise SystemExit(f"runtime snapshot file metadata changed: {name}")
        payload = bytearray()
        while chunk := os.read(descriptor, 1024 * 1024):
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            or len(payload) != before.st_size
        ):
            raise SystemExit(f"runtime snapshot file changed while reading: {name}")
        return bytes(payload)
    finally:
        os.close(descriptor)

try:
    root_before = os.fstat(root_fd)
    linked_root = os.lstat(root)
    if (
        not stat.S_ISDIR(root_before.st_mode)
        or (root_before.st_dev, root_before.st_ino)
        != (linked_root.st_dev, linked_root.st_ino)
        or root_before.st_uid != os.getuid()
        or stat.S_IMODE(root_before.st_mode) != 0o500
    ):
        raise SystemExit("runtime snapshot directory changed")
    observed_names = set(os.listdir(root_fd))
    if observed_names != required_names:
        raise SystemExit("runtime snapshot file set changed")
    sums_payload = read_file("SHA256SUMS")
    if (
        expected_sums_sha != "absent"
        and hashlib.sha256(sums_payload).hexdigest() != expected_sums_sha
    ):
        raise SystemExit(
            "runtime snapshot SHA256SUMS differs from the authorized digest"
        )
    sums = sums_payload.decode("utf-8").splitlines()
    entries = {}
    for line in sums:
        match = re.fullmatch(r"([a-f0-9]{64})  ([^\x00-\x1f]+)", line)
        if match is None:
            raise SystemExit("runtime snapshot SHA256SUMS is invalid")
        digest, name = match.groups()
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or len(path.parts) != 1
            or name in entries
            or "\\" in name
        ):
            raise SystemExit("runtime snapshot SHA256SUMS path is unsafe")
        entries[name] = digest
    if set(entries) != payload_names:
        raise SystemExit("runtime snapshot SHA256SUMS file set changed")
    for name, expected_digest in entries.items():
        if hashlib.sha256(read_file(name)).hexdigest() != expected_digest:
            raise SystemExit(f"runtime snapshot digest changed: {name}")
    manifest_payload = read_file("release-manifest.json")
    if (
        expected_manifest_sha != "absent"
        and hashlib.sha256(manifest_payload).hexdigest()
        != expected_manifest_sha
    ):
        raise SystemExit(
            "runtime snapshot manifest differs from the authorized digest"
        )
    manifest = json.loads(manifest_payload)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version")
        != "reddit_voc_insights_site_release_v2"
        or manifest.get("release_sha256") != release
    ):
        raise SystemExit("runtime snapshot manifest identity changed")
    image_payload = read_file(image_name)
    with tarfile.open(fileobj=io.BytesIO(image_payload), mode="r:") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or names.count("manifest.json") != 1:
            raise SystemExit("runtime snapshot image manifest is ambiguous")
        manifest_member = archive.getmember("manifest.json")
        manifest_stream = archive.extractfile(manifest_member)
        if not manifest_member.isfile() or manifest_stream is None:
            raise SystemExit("runtime snapshot image manifest is unsafe")
        image_manifest = json.loads(manifest_stream.read())
        if not isinstance(image_manifest, list) or len(image_manifest) != 1:
            raise SystemExit("runtime snapshot image cardinality changed")
        record = image_manifest[0]
        config_name = record.get("Config") if isinstance(record, dict) else None
        if (
            not isinstance(config_name, str)
            or re.fullmatch(r"[a-f0-9]{64}\.json", config_name) is None
            or record.get("RepoTags") != [f"reddit-voc-insights:{release}"]
            or names.count(config_name) != 1
        ):
            raise SystemExit("runtime snapshot image identity changed")
        config_member = archive.getmember(config_name)
        config_stream = archive.extractfile(config_member)
        if not config_member.isfile() or config_stream is None:
            raise SystemExit("runtime snapshot image config is unsafe")
        config_digest = hashlib.sha256(config_stream.read()).hexdigest()
    if expected_image_id != f"sha256:{config_digest}":
        raise SystemExit("runtime snapshot image ID changed")
    expected_override = (
        "services:\n"
        "  web:\n"
        f"    image: {expected_image_id}\n"
    ).encode("utf-8")
    if read_file("compose-image-id.yaml") != expected_override:
        raise SystemExit("runtime snapshot image override changed")
    root_after = os.fstat(root_fd)
    linked_after = os.lstat(root)
    if (
        (root_before.st_dev, root_before.st_ino)
        != (root_after.st_dev, root_after.st_ino)
        or (root_after.st_dev, root_after.st_ino)
        != (linked_after.st_dev, linked_after.st_ino)
    ):
        raise SystemExit("runtime snapshot directory changed during verification")
finally:
    os.close(root_fd)
PY
}

verify_runtime_compose_contract() {
  local release_sha="$1"
  local snapshot_dir expected_image_id compose_json
  verify_runtime_snapshot "${release_sha}" || return 1
  snapshot_dir="$(runtime_snapshot_directory "${release_sha}")" || return 1
  expected_image_id="$(runtime_expected_image_id "${release_sha}")" || return 1
  compose_json="$(
    RELEASE_SHA="${release_sha}" \
    REDDIT_VOC_DATA_ROOT="${DATA_ROOT}" \
    INSIGHTS_BIND_ADDRESS="${BIND_ADDRESS}" \
    INSIGHTS_PORT="${PORT}" \
      docker compose -p "${COMPOSE_PROJECT}" \
        -f "${snapshot_dir}/compose.yaml" \
        -f "${snapshot_dir}/compose-image-id.yaml" \
        config --format json
  )" || return 1
  python3 - \
    "${compose_json}" "${release_sha}" "${expected_image_id}" \
    "${DATA_ROOT}" "${DATA_CONTAINER_ROOT}" "${BIND_ADDRESS}" \
    "${PORT}" <<'PY' || return 1
import json
import sys

(
    raw,
    release,
    expected_image_id,
    data_root,
    data_container_root,
    bind_address,
    port,
) = sys.argv[1:]
value = json.loads(raw)
services = value.get("services") if isinstance(value, dict) else None
networks = value.get("networks") if isinstance(value, dict) else None
if (
    not isinstance(services, dict)
    or set(value) != {"name", "networks", "services"}
    or value.get("name") != "reddit_voc_insights"
    or set(services) != {"web"}
    or not isinstance(networks, dict)
    or set(networks) != {"insights"}
):
    raise SystemExit("runtime merged compose topology is invalid")
web = services["web"]
network = networks["insights"]
if not isinstance(web, dict) or not isinstance(network, dict):
    raise SystemExit("runtime merged compose shape is invalid")
if set(web) != {
    "cap_drop",
    "command",
    "container_name",
    "cpus",
    "entrypoint",
    "environment",
    "healthcheck",
    "image",
    "init",
    "labels",
    "logging",
    "mem_limit",
    "networks",
    "pids_limit",
    "ports",
    "pull_policy",
    "read_only",
    "restart",
    "security_opt",
    "tmpfs",
    "user",
    "volumes",
}:
    raise SystemExit("runtime merged compose service key set changed")
if set(network) != {"driver", "driver_opts", "ipam", "name"}:
    raise SystemExit("runtime merged compose network key set changed")

def require(condition, message):
    if not condition:
        raise SystemExit(message)

require(web.get("image") == expected_image_id, "runtime compose image is not the authenticated ID")
require(web.get("pull_policy") == "never", "runtime compose pull policy changed")
require(web.get("container_name") == "reddit_voc_insights_web", "runtime compose container name changed")
require(web.get("command") is None, "runtime compose command changed")
require(web.get("entrypoint") is None, "runtime compose entrypoint changed")
require(web.get("user") == "101:101", "runtime compose user changed")
require(web.get("read_only") is True, "runtime compose root filesystem changed")
require(web.get("init") is True, "runtime compose init contract changed")
require(web.get("restart") == "unless-stopped", "runtime compose restart policy changed")
require(web.get("privileged") in (None, False), "runtime compose became privileged")
require(web.get("cap_drop") == ["ALL"], "runtime compose capability drop changed")
require(web.get("cap_add") in (None, []), "runtime compose added capabilities")
require(web.get("security_opt") == ["no-new-privileges:true"], "runtime compose security options changed")
require(web.get("pids_limit") == 100, "runtime compose PID limit changed")
require(web.get("mem_limit") in (268435456, "268435456", "256m"), "runtime compose memory limit changed")
require(web.get("cpus") in (0.5, "0.5", "0.50"), "runtime compose CPU limit changed")
require(web.get("environment") == {"NGINX_ENTRYPOINT_QUIET_LOGS": "1"}, "runtime compose environment changed")
require(web.get("labels") == {
    "com.reddit-voc.component": "insights-site",
    "com.reddit-voc.release": release,
}, "runtime compose labels changed")
require(web.get("networks") == {"insights": None}, "runtime compose service network changed")
require(web.get("healthcheck") == {
    "test": [
        "CMD-SHELL",
        "wget -q -O /dev/null http://127.0.0.1:8080/healthz && "
        "wget -q -O /dev/null "
        "http://127.0.0.1:8080/data/reddit-voc/current-release.json",
    ],
    "timeout": "3s",
    "interval": "10s",
    "retries": 6,
    "start_period": "5s",
}, "runtime compose healthcheck changed")
require(web.get("logging") == {
    "driver": "json-file",
    "options": {"max-file": "3", "max-size": "10m"},
}, "runtime compose logging changed")
tmpfs = web.get("tmpfs")
require(
    tmpfs == ["/tmp:rw,noexec,nosuid,nodev,size=32m,uid=101,gid=101,mode=1777"],
    "runtime compose tmpfs changed",
)
volumes = web.get("volumes")
require(isinstance(volumes, list) and len(volumes) == 1, "runtime compose volume count changed")
volume = volumes[0]
require(
    isinstance(volume, dict)
    and volume.get("type") == "bind"
    and volume.get("source") == data_root
    and volume.get("target") == data_container_root
    and volume.get("read_only") is True
    and volume.get("bind") == {},
    "runtime compose data mount changed",
)
ports = web.get("ports")
require(isinstance(ports, list) and len(ports) == 1, "runtime compose port count changed")
binding = ports[0]
require(
    isinstance(binding, dict)
    and str(binding.get("target")) == "8080"
    and str(binding.get("published")) == port
    and binding.get("host_ip") == bind_address
    and binding.get("mode") == "ingress"
    and binding.get("protocol", "tcp") == "tcp",
    "runtime compose port binding changed",
)
require(network.get("name") == "reddit_voc_insights_net", "runtime compose network name changed")
require(network.get("driver") == "bridge", "runtime compose network driver changed")
require(network.get("ipam") == {}, "runtime compose network IPAM changed")
require(network.get("driver_opts") == {
    "com.docker.network.bridge.enable_icc": "false",
    "com.docker.network.bridge.enable_ip_masquerade": "false",
}, "runtime compose network isolation options changed")
PY
}

ensure_image_contract() {
  local release_sha="$1"
  local directory image_ref expected_image_id actual_image_id
  reverify_bound_release_artifacts || return 1
  prepare_release_runtime_snapshot "${release_sha}" || return 1
  verify_runtime_snapshot "${release_sha}" || return 1
  directory="$(runtime_snapshot_directory "${release_sha}")" || return 1
  expected_image_id="$(runtime_expected_image_id "${release_sha}")" || return 1
  image_ref="reddit-voc-insights:${release_sha}"
  docker load --input "${directory}/reddit-voc-insights-${release_sha}.tar" || return 1
  actual_image_id="$(docker image inspect -f '{{.Id}}' "${image_ref}")" || return 1
  if [[ "${actual_image_id}" != "${expected_image_id}" ]]; then
    echo "rollback loaded image ID differs from the authenticated archive" >&2
    return 1
  fi
  docker image inspect "${image_ref}" | python3 -c '
import json
import sys

release = sys.argv[1]
expected_image_id = sys.argv[2]
image = json.load(sys.stdin)[0]
config = image.get("Config") or {}
labels = config.get("Labels") or {}
if image.get("Id") != expected_image_id:
    raise SystemExit("rollback image ID contract mismatch")
if image.get("Architecture") != "amd64":
    raise SystemExit("rollback image architecture contract mismatch")
if config.get("User") != "101:101":
    raise SystemExit("rollback image user contract mismatch")
if labels.get("com.reddit-voc.component") != "insights-site":
    raise SystemExit("rollback image component label mismatch")
if labels.get("com.reddit-voc.release") != release:
    raise SystemExit("rollback image release label mismatch")
' "${release_sha}" "${expected_image_id}" || return 1
}

assert_rollback_verifier_contract() {
  local expected_release="${1:-}"
  local inspect_json expected_image_id=""
  if [[ -n "${expected_release}" ]]; then
    expected_image_id="$(
      runtime_expected_image_id "${expected_release}"
    )" || return 1
  fi
  inspect_json="$(docker inspect "${ROLLBACK_VERIFIER_NAME}")" || return 1
  python3 - \
    "${inspect_json}" "${ROLLBACK_VERIFIER_NAME}" \
    "${ROLLBACK_VERIFIER_TRANSACTION_SHA}" "${EXPECTED_CURRENT}" \
    "${TARGET_RELEASE}" "${expected_release}" "${expected_image_id}" \
    "${CURRENT_EXPECTED_IMAGE_ID}" "${TARGET_EXPECTED_IMAGE_ID}" <<'PY' || return 1
import json
import re
import sys

(
    raw,
    verifier_name,
    transaction_sha,
    current_release,
    target_release,
    expected,
    expected_image,
    current_image,
    target_image,
) = sys.argv[1:]
values = json.loads(raw)
if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
    raise SystemExit("rollback verifier inspect cardinality mismatch")
value = values[0]
config = value.get("Config") or {}
host = value.get("HostConfig") or {}
state = value.get("State") or {}
labels = config.get("Labels") or {}
mounts = value.get("Mounts") or []
allowed_releases = {current_release}
if target_release:
    allowed_releases.add(target_release)
release = labels.get("com.reddit-voc.release")
allowed_images = {f"reddit-voc-insights:{release}"}
for candidate in (current_image, target_image):
    if re.fullmatch(r"sha256:[a-f0-9]{64}", candidate or "") is not None:
        allowed_images.add(candidate)
if (
    not isinstance(config, dict)
    or not isinstance(host, dict)
    or not isinstance(state, dict)
    or not isinstance(labels, dict)
    or not isinstance(mounts, list)
    or re.fullmatch(r"[a-f0-9]{64}", str(value.get("Id"))) is None
    or value.get("Name") != f"/{verifier_name}"
    or labels.get("com.reddit-voc.component") != "insights-rollback-verifier"
    or labels.get("com.reddit-voc.rollback-transaction") != transaction_sha
    or release not in allowed_releases
    or (expected and release != expected)
    or config.get("Image") not in allowed_images
    or (expected and config.get("Image") != expected_image)
    or config.get("Entrypoint") != ["/bin/true"]
    or state.get("Running") is not False
    or state.get("Status") != "created"
    or value.get("RestartCount") != 0
    or host.get("NetworkMode") != "none"
    or (host.get("RestartPolicy") or {}).get("Name") != "no"
    or host.get("AutoRemove") is not False
    or host.get("PortBindings") not in (None, {})
    or host.get("Binds") not in (None, [])
    or mounts != []
):
    raise SystemExit("rollback verifier ownership or isolation contract mismatch")
print(value["Id"])
PY
}

cleanup_rollback_verifier_residue() {
  local matching_ids verified_id remaining_ids
  matching_ids="$(
    docker container ls -a -q --no-trunc \
      --filter "name=^/${ROLLBACK_VERIFIER_NAME}$"
  )" || return 1
  if [[ -z "${matching_ids}" ]]; then
    return 0
  fi
  if [[ ! "${matching_ids}" =~ ^[a-f0-9]{64}$ ]]; then
    echo "rollback verifier name resolves to an ambiguous container set" >&2
    return 1
  fi
  verified_id="$(assert_rollback_verifier_contract)" || return 1
  if [[ "${verified_id}" != "${matching_ids}" ]]; then
    echo "rollback verifier name and inspected identity disagree" >&2
    return 1
  fi
  docker rm "${verified_id}" >/dev/null || return 1
  remaining_ids="$(
    docker container ls -a -q --no-trunc \
      --filter "name=^/${ROLLBACK_VERIFIER_NAME}$"
  )" || return 1
  if [[ -n "${remaining_ids}" ]]; then
    echo "rollback verifier residue cleanup did not complete" >&2
    return 1
  fi
}

verify_image_dist_contract() {
  local release_sha="$1"
  local directory expected_image_id verify_dir verify_container verify_ok cleanup_ok
  reverify_bound_release_artifacts || return 1
  prepare_release_runtime_snapshot "${release_sha}" || return 1
  verify_runtime_snapshot "${release_sha}" || return 1
  cleanup_rollback_verifier_residue || return 1
  directory="$(runtime_snapshot_directory "${release_sha}")" || return 1
  expected_image_id="$(runtime_expected_image_id "${release_sha}")" || return 1
  python3 - "${directory}/dist-SHA256SUMS" <<'PY' || return 1
import re
import sys
from pathlib import PurePosixPath

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
if not lines:
    raise SystemExit("dist checksum manifest is empty")
seen = set()
for line in lines:
    match = re.fullmatch(r"([a-f0-9]{64})  ([^\x00-\x1f]+)", line)
    if match is None:
        raise SystemExit("dist checksum manifest contains an invalid entry")
    name = match.group(2)
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in name or name in seen:
        raise SystemExit("dist checksum manifest contains an unsafe or duplicate path")
    seen.add(name)
PY
  verify_dir="$(mktemp -d "${RELEASE_ROOT}/.rollback-verify-${release_sha}.XXXXXX")" || return 1
  verify_container="$(
    docker create \
      --name "${ROLLBACK_VERIFIER_NAME}" \
      --network none \
      --restart no \
      --label "com.reddit-voc.component=insights-rollback-verifier" \
      --label "com.reddit-voc.rollback-transaction=${ROLLBACK_VERIFIER_TRANSACTION_SHA}" \
      --label "com.reddit-voc.release=${release_sha}" \
      --entrypoint /bin/true \
      "${expected_image_id}"
  )" || {
    rm -rf "${verify_dir}"
    return 1
  }
  if [[ "$(assert_rollback_verifier_contract "${release_sha}")" != \
        "${verify_container}" ]]; then
    echo "created rollback verifier does not match its exact transaction contract" >&2
    rm -rf "${verify_dir}"
    return 1
  fi
  verify_ok=0
  cleanup_ok=1
  if ! mkdir "${verify_dir}/dist"; then
    verify_ok=0
  elif docker cp "${ROLLBACK_VERIFIER_NAME}:/usr/share/nginx/html/." "${verify_dir}/dist/" && \
     (cd "${verify_dir}" && sha256sum --check "${directory}/dist-SHA256SUMS") && \
     [[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["release_sha256"])' "${verify_dir}/dist/release.json")" == "${release_sha}" ]]; then
    verify_ok=1
  fi
  verify_runtime_snapshot "${release_sha}" || verify_ok=0
  cleanup_rollback_verifier_residue || cleanup_ok=0
  rm -rf "${verify_dir}" || cleanup_ok=0
  if [[ "${verify_ok}" != "1" || "${cleanup_ok}" != "1" ]]; then
    echo "image dist checksum or release marker contract mismatch: ${release_sha}" >&2
    return 1
  fi
}

wait_for_release_health() {
  local expected_release="$1"
  local health release_label http_release
  for _ in $(seq 1 60); do
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${CONTAINER_NAME}" 2>/dev/null || printf 'missing')"
    release_label="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
    http_release="$(curl -fsS "http://${BIND_ADDRESS}:${PORT}/release.json" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["release_sha256"])' 2>/dev/null || true)"
    if [[ "${health}" == "healthy" && "${release_label}" == "${expected_release}" && "${http_release}" == "${expected_release}" ]]; then
      return 0
    fi
    if [[ "${health}" == "unhealthy" ]]; then
      return 1
    fi
    sleep 2
  done
  return 1
}

protected_container_inventory() {
  local identifier_output inspect_json
  local -a identifiers=()
  identifier_output="$(docker container ls -a -q --no-trunc)" || return 1
  while IFS= read -r identifier; do
    [[ -z "${identifier}" ]] || identifiers+=("${identifier}")
  done <<< "${identifier_output}"
  if [[ "${#identifiers[@]}" -eq 0 ]]; then
    echo "protected container inventory is empty" >&2
    return 1
  fi
  inspect_json="$(docker inspect "${identifiers[@]}")" || return 1
  python3 - \
    "${#identifiers[@]}" "${inspect_json}" "${ROLLBACK_VERIFIER_NAME}" \
    "${ROLLBACK_VERIFIER_TRANSACTION_SHA}" "${EXPECTED_CURRENT}" \
    "${TARGET_RELEASE}" "${CURRENT_EXPECTED_IMAGE_ID}" \
    "${TARGET_EXPECTED_IMAGE_ID}" <<'PY' || return 1
import hashlib
import json
import re
import sys

expected_count = int(sys.argv[1])
values = json.loads(sys.argv[2])
(
    verifier_name,
    transaction_sha,
    current_release,
    target_release,
    current_image,
    target_image,
) = sys.argv[3:]
if not isinstance(values, list) or len(values) != expected_count:
    raise SystemExit("protected container inspect cardinality mismatch")
rows = []
seen = set()
for value in values:
    if not isinstance(value, dict):
        raise SystemExit("protected container inspect row is invalid")
    container_id = value.get("Id")
    name = value.get("Name")
    state = value.get("State")
    restart_count = value.get("RestartCount")
    if (
        not isinstance(container_id, str)
        or re.fullmatch(r"[a-f0-9]{64}", container_id) is None
        or container_id in seen
        or not isinstance(name, str)
        or not name.startswith("/")
        or not isinstance(state, dict)
        or type(restart_count) is not int
        or restart_count < 0
        or not isinstance(state.get("StartedAt"), str)
        or not isinstance(state.get("FinishedAt"), str)
        or not isinstance(state.get("Status"), str)
    ):
        raise SystemExit("protected container inspect contract is invalid")
    seen.add(container_id)
    if name == "/reddit_voc_insights_web" or name.startswith(
        "/reddit_voc_insights_candidate_"
    ):
        continue
    if name == f"/{verifier_name}":
        config = value.get("Config") or {}
        labels = config.get("Labels") or {}
        host = value.get("HostConfig") or {}
        allowed_releases = {current_release}
        if target_release:
            allowed_releases.add(target_release)
        release = labels.get("com.reddit-voc.release")
        allowed_images = {f"reddit-voc-insights:{release}"}
        for candidate in (current_image, target_image):
            if re.fullmatch(r"sha256:[a-f0-9]{64}", candidate or "") is not None:
                allowed_images.add(candidate)
        if (
            not isinstance(config, dict)
            or not isinstance(labels, dict)
            or not isinstance(host, dict)
            or labels.get("com.reddit-voc.component")
            != "insights-rollback-verifier"
            or labels.get("com.reddit-voc.rollback-transaction")
            != transaction_sha
            or release not in allowed_releases
            or config.get("Image") not in allowed_images
            or config.get("Entrypoint") != ["/bin/true"]
            or state.get("Running") is not False
            or state.get("Status") != "created"
            or restart_count != 0
            or host.get("NetworkMode") != "none"
            or (host.get("RestartPolicy") or {}).get("Name") != "no"
            or host.get("AutoRemove") is not False
            or host.get("PortBindings") not in (None, {})
            or host.get("Binds") not in (None, [])
            or (value.get("Mounts") or []) != []
        ):
            raise SystemExit("rollback verifier residue contract is invalid")
        continue
    rows.append(
        json.dumps(
            {
                "container_id": container_id,
                "finished_at": state["FinishedAt"],
                "name": name,
                "restart_count": restart_count,
                "started_at": state["StartedAt"],
                "state": state["Status"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
rows.sort()
if not rows:
    raise SystemExit("protected container inventory is empty")
digest = hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()
print(len(rows), digest, sep="\t")
PY
}

candidate_transaction_quiet_counts() {
  local candidate_count listener_count
  candidate_count="$(
    docker container ls -a --format '{{.Names}}' | \
      awk '/^reddit_voc_insights_candidate_/{count++} END{print count+0}'
  )" || return 1
  listener_count="$(
    ss -H -ltn | awk '
      {
        address=$4
        if (address ~ /:18339$/) {
          count++
        }
      }
      END {print count+0}
    '
  )" || return 1
  if [[ ! "${candidate_count}" =~ ^[0-9]+$ || \
        ! "${listener_count}" =~ ^[0-9]+$ ]]; then
    echo "candidate transaction quiet-state count is invalid" >&2
    return 1
  fi
  printf '%s\t%s\n' "${candidate_count}" "${listener_count}"
}

assert_candidate_transaction_quiet() {
  local quiet_counts candidate_count listener_count
  quiet_counts="$(candidate_transaction_quiet_counts)" || return 1
  IFS=$'\t' read -r candidate_count listener_count <<< "${quiet_counts}"
  if [[ "${candidate_count}" != "0" || "${listener_count}" != "0" ]]; then
    echo "rollback blocked because the candidate transaction slot is occupied" >&2
    return 1
  fi
}

assert_runtime_collector_isolation() {
  if docker exec "${CONTAINER_NAME}" wget -q -T 3 -O /dev/null \
      "http://${BIND_ADDRESS}:18337/api/health" 2>/dev/null; then
    echo "runtime unexpectedly reached the collector listener" >&2
    return 1
  fi
}

verify_runtime_contract() {
  local release_sha="$1"
  local data_runtime_mode image_ref image_id expected_image_id
  local container_json network_json snapshot_dir
  prepare_release_runtime_snapshot "${release_sha}" || return 1
  snapshot_dir="$(runtime_snapshot_directory "${release_sha}")" || return 1
  expected_image_id="$(runtime_expected_image_id "${release_sha}")" || return 1
  data_runtime_mode="$(python3 - "${snapshot_dir}/release-manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
runtime = manifest.get("data_runtime")
if runtime is None:
    print("legacy_bundled")
elif runtime == {
    "contract_version": "reddit_voc_data_mount_v1",
    "mode": "read_only_versioned_mount",
    "host_root_environment": "REDDIT_VOC_DATA_ROOT",
    "container_root": "/srv/reddit-voc-data",
    "current_pointer": "current",
    "public_alias": "/srv/reddit-voc-data/current/public/data/reddit-voc/",
    "web_path": "/data/reddit-voc/",
    "expected_mount_count": 1,
    "read_only": True,
    "atomic_pointer_switch_without_container_restart": True,
}:
    print("read_only_versioned_mount")
else:
    raise SystemExit("rollback target data runtime contract mismatch")
PY
)" || return 1
  verify_runtime_snapshot "${release_sha}" || return 1
  image_ref="${expected_image_id}"
  image_id="$(docker image inspect -f '{{.Id}}' "${image_ref}")" || return 1
  if [[ "${image_id}" != "${expected_image_id}" ]]; then
    echo "runtime image ID differs from the authenticated archive" >&2
    return 1
  fi
  container_json="$(docker inspect "${CONTAINER_NAME}")" || return 1
  network_json="$(docker network inspect reddit_voc_insights_net)" || return 1
  python3 - \
    "${container_json}" "${network_json}" "${release_sha}" \
    "${image_ref}" "${image_id}" "${BIND_ADDRESS}" "${PORT}" \
    "${data_runtime_mode}" "${DATA_ROOT}" "${DATA_CONTAINER_ROOT}" <<'PY' || return 1
import json
import re
import sys

(
    container_raw,
    network_raw,
    release,
    image_ref,
    image_id,
    bind_address,
    port,
    data_runtime_mode,
    data_root,
    container_data_root,
) = sys.argv[1:]
containers = json.loads(container_raw)
network_values = json.loads(network_raw)
if (
    not isinstance(containers, list)
    or not isinstance(network_values, list)
    or len(containers) != 1
    or len(network_values) != 1
    or not isinstance(containers[0], dict)
    or not isinstance(network_values[0], dict)
):
    raise SystemExit("runtime inspect cardinality mismatch")
container = containers[0]
network_contract = network_values[0]
config = container.get("Config") or {}
host = container.get("HostConfig") or {}
state = container.get("State") or {}
network_settings = container.get("NetworkSettings") or {}
labels = config.get("Labels") or {}
health = state.get("Health") or {}
networks = network_settings.get("Networks") or {}
ports = network_settings.get("Ports") or {}
bindings = host.get("PortBindings") or {}
tmpfs = host.get("Tmpfs") or {}
network_options = network_contract.get("Options") or {}
mounts = container.get("Mounts") or []
if not all(
    isinstance(value, dict)
    for value in (
        config,
        host,
        state,
        network_settings,
        labels,
        health,
        networks,
        ports,
        bindings,
        tmpfs,
        network_contract,
        network_options,
    )
) or not isinstance(mounts, list):
    raise SystemExit("runtime inspect shape mismatch")

def require(condition, message):
    if not condition:
        raise SystemExit(message)

require(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id) is not None, "runtime loaded image ID is invalid")
require(config.get("Image") == image_ref, "runtime image reference mismatch")
require(container.get("Image") == image_id, "runtime container image ID mismatch")
require(config.get("User") == "101:101", "runtime user contract mismatch")
require(config.get("Entrypoint") == ["/docker-entrypoint.sh"], "runtime entrypoint changed")
require(config.get("Cmd") == ["nginx", "-g", "daemon off;"], "runtime command changed")
require(config.get("WorkingDir") == "/", "runtime working directory changed")
require(config.get("OpenStdin") is False, "runtime stdin contract changed")
require(config.get("StdinOnce") is False, "runtime stdin-once contract changed")
require(config.get("Tty") is False, "runtime TTY contract changed")
require(set(config.get("Env") or []) == {
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "NGINX_VERSION=1.29.4",
    "PKG_RELEASE=1",
    "DYNPKG_RELEASE=1",
    "NJS_VERSION=0.9.4",
    "NJS_RELEASE=1",
    "NGINX_ENTRYPOINT_QUIET_LOGS=1",
}, "runtime environment changed")
require(config.get("Healthcheck") == {
    "Test": [
        "CMD-SHELL",
        "wget -q -O /dev/null http://127.0.0.1:8080/healthz && "
        "wget -q -O /dev/null "
        "http://127.0.0.1:8080/data/reddit-voc/current-release.json",
    ],
    "Interval": 10_000_000_000,
    "Timeout": 3_000_000_000,
    "Retries": 6,
    "StartPeriod": 5_000_000_000,
}, "runtime healthcheck changed")
require(labels.get("com.reddit-voc.component") == "insights-site", "runtime component label mismatch")
require(labels.get("com.reddit-voc.release") == release, "runtime release label mismatch")
require(state.get("Running") is True, "runtime running-state contract mismatch")
require(health.get("Status") == "healthy", "runtime health contract mismatch")
require(host.get("ReadonlyRootfs") is True, "runtime root filesystem is not read-only")
require(host.get("Privileged") is False, "runtime must not be privileged")
require(host.get("PidMode") == "", "runtime PID namespace changed")
require(host.get("IpcMode") == "private", "runtime IPC namespace changed")
require(host.get("UTSMode") == "", "runtime UTS namespace changed")
require(host.get("UsernsMode") == "", "runtime user namespace changed")
require(host.get("Devices") in (None, []), "runtime device access changed")
require(host.get("DeviceRequests") in (None, []), "runtime device requests changed")
require(host.get("DeviceCgroupRules") in (None, []), "runtime device cgroup rules changed")
require(host.get("Sysctls") in (None, {}), "runtime sysctls changed")
require(host.get("Ulimits") in (None, []), "runtime ulimits changed")
require(host.get("Runtime") in ("", "runc"), "runtime implementation changed")
if data_runtime_mode == "legacy_bundled":
    require(mounts == [], "legacy runtime must not have host/data mounts")
else:
    require(len(mounts) == 1, "mounted runtime must have exactly one mount")
    mount = mounts[0]
    require(mount.get("Type") == "bind", "data mount must be a bind mount")
    require(mount.get("Source") == data_root, "data mount source mismatch")
    require(mount.get("Destination") == container_data_root, "data mount destination mismatch")
    require(mount.get("RW") is False, "data mount must be read-only")
    require(mount.get("Propagation") == "rprivate", "data mount propagation mismatch")
network_id = network_contract.get("Id")
require(host.get("NetworkMode") == "reddit_voc_insights_net", "runtime network mode mismatch")
require(set(networks) == {"reddit_voc_insights_net"}, "runtime network isolation mismatch")
require(isinstance(networks.get("reddit_voc_insights_net"), dict), "runtime network attachment is invalid")
require(re.fullmatch(r"[a-f0-9]{64}", str(network_id)) is not None, "runtime network ID is invalid")
require(networks["reddit_voc_insights_net"].get("NetworkID") == network_id, "runtime network attachment ID mismatch")
require(network_contract.get("Name") == "reddit_voc_insights_net", "runtime network name mismatch")
require(network_contract.get("Driver") == "bridge", "runtime network driver mismatch")
require(network_contract.get("Internal") is False, "runtime network internal-mode mismatch")
require(network_options.get("com.docker.network.bridge.enable_ip_masquerade") == "false", "runtime network masquerade mismatch")
require(network_options.get("com.docker.network.bridge.enable_icc") == "false", "runtime network ICC mismatch")
require(host.get("CapDrop") == ["ALL"], "runtime capability drop contract mismatch")
require(host.get("CapAdd") in (None, []), "runtime must not add capabilities")
require(host.get("SecurityOpt") == ["no-new-privileges:true"], "runtime security options mismatch")
require(host.get("Init") is True, "runtime init contract mismatch")
require(host.get("PidsLimit") == 100, "runtime PID limit mismatch")
require(host.get("Memory") == 256 * 1024 * 1024, "runtime memory limit mismatch")
require(host.get("NanoCpus") == 500_000_000, "runtime CPU limit mismatch")
require((host.get("RestartPolicy") or {}).get("Name") == "unless-stopped", "runtime restart policy mismatch")
require(set(tmpfs) == {"/tmp"}, "runtime tmpfs contract mismatch")
tmpfs_options = set(filter(None, str(tmpfs["/tmp"]).split(",")))
expected_tmpfs = {
    "rw", "noexec", "nosuid", "nodev", "size=32m",
    "uid=101", "gid=101", "mode=1777",
}
require(tmpfs_options == expected_tmpfs, "runtime tmpfs exact contract mismatch")
expected_binding = [{"HostIp": bind_address, "HostPort": port}]
require(bindings == {"8080/tcp": expected_binding}, "runtime host port binding mismatch")
require(ports == {"8080/tcp": expected_binding}, "runtime live port binding mismatch")
PY
  local listeners
  listeners="$(ss -H -ltn | awk -v suffix=":${PORT}" 'index($4, suffix) == length($4) - length(suffix) + 1 {print $4}' | sort -u)" || return 1
  if [[ "${listeners}" != "${BIND_ADDRESS}:${PORT}" ]]; then
    echo "runtime listener isolation mismatch" >&2
    return 1
  fi
  local network_internal network_masquerade network_icc
  network_internal="$(docker network inspect -f '{{.Internal}}' reddit_voc_insights_net)" || return 1
  network_masquerade="$(docker network inspect -f '{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}' reddit_voc_insights_net)" || return 1
  network_icc="$(docker network inspect -f '{{index .Options "com.docker.network.bridge.enable_icc"}}' reddit_voc_insights_net)" || return 1
  if [[ "${network_internal}" != "false" || "${network_masquerade}" != "false" || "${network_icc}" != "false" ]]; then
    echo "runtime network egress-isolation contract mismatch" >&2
    return 1
  fi
  assert_runtime_collector_isolation || return 1
  curl -fsS "http://${BIND_ADDRESS}:${PORT}/healthz" >/dev/null || return 1
  local http_release
  http_release="$(curl -fsS "http://${BIND_ADDRESS}:${PORT}/release.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["release_sha256"])')" || return 1
  if [[ "${http_release}" != "${release_sha}" ]]; then
    echo "runtime release marker mismatch" >&2
    return 1
  fi
}

file_identity_ns() {
  python3 - "$1" <<'PY' || return 1
import os
import sys

try:
    value = os.stat(sys.argv[1])
except FileNotFoundError:
    print("absent")
else:
    print(f"{value.st_mtime_ns}:{value.st_size}:{value.st_ino}")
PY
}

collector_id="$(docker inspect -f '{{.Id}}' reddit_voc_site_app)"
collector_restart="$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)"
collector_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_site_app)"
translation_id="$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)"
translation_restart="$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)"
translation_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_libretranslate)"
nginx_id="$(docker inspect -f '{{.Id}}' "${NGINX_CONTAINER}")"
nginx_restart="$(docker inspect -f '{{.RestartCount}}' "${NGINX_CONTAINER}")"
nginx_before_sha="$(sha256sum "${NGINX_CONF}" | awk '{print $1}')"
nginx_before_inode="$(stat -c '%i' "${NGINX_CONF}")"
cron_sha="$(sudo sha256sum "${CRON_FILE}" | awk '{print $1}')"

if [[ "${collector_health}" != "healthy" || "${translation_health}" != "healthy" ]]; then
  echo "rollback blocked because an existing Reddit container is not healthy" >&2
  exit 1
fi
if docker ps --format '{{.Names}}' | grep -q '^reddit_voc_site_app-run-'; then
  echo "rollback blocked because a collector one-shot container is running" >&2
  exit 1
fi
assert_candidate_transaction_quiet

nginx_conf_mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/nginx/nginx.conf"}}{{.Type}}|{{.Source}}{{end}}{{end}}' "${NGINX_CONTAINER}")"
if [[ "${nginx_conf_mount}" != "bind|${NGINX_CONF}" ]]; then
  echo "shared Nginx config is not the expected single-file bind mount" >&2
  exit 1
fi
nginx_container_sha="$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')"
if [[ "${nginx_container_sha}" != "${nginx_before_sha}" ]]; then
  echo "host and container Nginx configurations are not aligned" >&2
  exit 1
fi
docker exec "${NGINX_CONTAINER}" nginx -t >/dev/null
curl -fsS "${COLLECTOR_PUBLIC_URL}" >/dev/null
curl -fsS http://127.0.0.1:18337/api/health >/dev/null

database_before="$(file_identity_ns /opt/reddit-voc-site/data/reddit_voc_daily.sqlite3)"
report_before="$(file_identity_ns /opt/reddit-voc-report/current)"
sleep 5
database_after="$(file_identity_ns /opt/reddit-voc-site/data/reddit_voc_daily.sqlite3)"
report_after="$(file_identity_ns /opt/reddit-voc-report/current)"
if [[ "${database_before}" != "${database_after}" || "${report_before}" != "${report_after}" ]]; then
  echo "rollback blocked because collector/report state changed during preflight" >&2
  exit 1
fi
cleanup_rollback_verifier_residue || exit 1
shared_container_inventory_tuple="$(protected_container_inventory)" || exit 1
IFS=$'\t' read -r shared_container_inventory_count shared_container_inventory_sha \
  <<< "${shared_container_inventory_tuple}"
if [[ ! "${shared_container_inventory_count}" =~ ^[1-9][0-9]*$ || \
      ! "${shared_container_inventory_sha}" =~ ^[a-f0-9]{64}$ ]]; then
  echo "shared container inventory baseline is invalid" >&2
  exit 1
fi

assert_shared_nginx_digest_baseline() {
  local host_nginx_sha="$1"
  local container_nginx_sha="$2"
  if [[ "${host_nginx_sha}" != "${nginx_before_sha}" || \
        "${container_nginx_sha}" != "${nginx_before_sha}" ]]; then
    echo "host or container Nginx content changed from the rollback baseline" >&2
    return 1
  fi
}

assert_authorized_protected_container_baseline() {
  [[ "${DUAL_DATA_ROLLBACK}" == "1" ]] || return 0
  if [[ "${shared_container_inventory_count}" != \
          "${ROLLBACK_PROTECTED_CONTAINER_COUNT}" || \
        "${shared_container_inventory_sha}" != \
          "${ROLLBACK_PROTECTED_CONTAINER_SHA256}" ]]; then
    echo "protected container inventory does not match the authorized baseline" >&2
    return 1
  fi
}

assert_authorized_control_plane_baseline() {
  [[ "${DUAL_DATA_ROLLBACK}" == "1" ]] || return 0
  revalidate_rollback_locks || return 1
  if [[ "${nginx_before_sha}" != "${ROLLBACK_AUTHORIZED_NGINX_SHA256}" || \
        "${nginx_container_sha}" != "${ROLLBACK_AUTHORIZED_NGINX_SHA256}" || \
        "${cron_sha}" != "${ROLLBACK_AUTHORIZED_CRON_SHA256}" || \
        "${database_before}" != "${ROLLBACK_AUTHORIZED_DATABASE_IDENTITY}" || \
        "${report_before}" != "${ROLLBACK_AUTHORIZED_REPORT_IDENTITY}" ]]; then
    echo "live control-plane state differs from the authorized production baseline" >&2
    return 1
  fi
}

assert_shared_service_baseline() {
  if docker ps --format '{{.Names}}' | grep -q '^reddit_voc_site_app-run-'; then
    echo "collector one-shot container appeared during rollback" >&2
    return 1
  fi
  assert_candidate_transaction_quiet || return 1
  local observed_container_inventory_count observed_container_inventory_sha
  local observed_container_inventory_tuple
  observed_container_inventory_tuple="$(protected_container_inventory)" || return 1
  IFS=$'\t' read -r observed_container_inventory_count \
    observed_container_inventory_sha <<< "${observed_container_inventory_tuple}"
  if [[ "${observed_container_inventory_count}" != \
          "${shared_container_inventory_count}" || \
        "${observed_container_inventory_sha}" != \
          "${shared_container_inventory_sha}" || \
        "$(docker inspect -f '{{.Id}}' reddit_voc_site_app)" != "${collector_id}" || \
        "$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)" != "${collector_restart}" || \
        "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_site_app)" != "healthy" || \
        "$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)" != "${translation_id}" || \
        "$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)" != "${translation_restart}" || \
        "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_libretranslate)" != "healthy" || \
        "$(docker inspect -f '{{.Id}}' "${NGINX_CONTAINER}")" != "${nginx_id}" || \
        "$(docker inspect -f '{{.RestartCount}}' "${NGINX_CONTAINER}")" != "${nginx_restart}" || \
        "$(stat -c '%i' "${NGINX_CONF}")" != "${nginx_before_inode}" || \
        "$(sudo sha256sum "${CRON_FILE}" | awk '{print $1}')" != "${cron_sha}" || \
        "$(file_identity_ns /opt/reddit-voc-site/data/reddit_voc_daily.sqlite3)" != "${database_before}" || \
        "$(file_identity_ns /opt/reddit-voc-report/current)" != "${report_before}" ]]; then
    echo "collector, translation, Nginx, or cron baseline changed" >&2
    return 1
  fi
  local host_nginx_sha container_nginx_sha
  host_nginx_sha="$(sha256sum "${NGINX_CONF}" | awk '{print $1}')" || return 1
  container_nginx_sha="$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')" || return 1
  assert_shared_nginx_digest_baseline \
    "${host_nginx_sha}" "${container_nginx_sha}" || return 1
  assert_authorized_protected_container_baseline || return 1
  assert_authorized_control_plane_baseline || return 1
  docker exec "${NGINX_CONTAINER}" nginx -t >/dev/null || return 1
  curl -fsS "${COLLECTOR_PUBLIC_URL}" >/dev/null || return 1
  curl -fsS http://127.0.0.1:18337/api/health >/dev/null || return 1
}

CURRENT_TMP="${DEPLOY_ROOT}/.current-rollback.$$"
EVIDENCE_TMP=""
EVIDENCE_FILE=""
BACKUP_DIR=""
ACTION_STARTED=0
ACTION_SUCCEEDED=0
JOURNAL_ACTIVE=0
ROLLBACK_STARTED_AT_UTC=""
ROLLBACK_RECEIPT_FILE=""
ROLLBACK_RECEIPT_SHA=""
CURRENT_CHANGED=0
DATA_CURRENT_CHANGED=0
DATA_PREVIOUS_CHANGED=0
DATA_CURRENT_TMP="${DATA_ROOT}/.current-rollback.$$"
DATA_PREVIOUS_TMP="${DATA_ROOT}/.previous-rollback.$$"
ORIGINAL_DATA_PREVIOUS_TARGET="absent"
ORIGINAL_DATA_PREVIOUS_SHA="absent"
VHOST_WAS_PRESENT=0
VHOST_REMOVED=0

write_rollback_journal_phase() {
  local phase="$1"
  local receipt_sha="${2:-}"
  revalidate_rollback_locks
  python3 - \
    "${ROLLBACK_JOURNAL}" \
    "${ROLLBACK_JOURNAL_SCHEMA}" \
    "${phase}" \
    "${ROLLBACK_STARTED_AT_UTC}" \
    "${ROLLBACK_RECEIPT_FILE}" \
    "${receipt_sha}" \
    "${EXPECTED_CURRENT}" \
    "${TARGET_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" \
    "${ORIGINAL_DATA_PREVIOUS_TARGET}" \
    "${ORIGINAL_DATA_PREVIOUS_SHA}" \
    "${ROLLBACK_EVIDENCE_MODE}" \
    "${TARGET_DEPLOYMENT_EVIDENCE}" \
    "${TARGET_DEPLOYMENT_EVIDENCE_SHA}" \
    "${ROLLBACK_ACCEPTANCE_EVIDENCE}" \
    "${ROLLBACK_ACCEPTANCE_EVIDENCE_SHA}" \
    "${ROLLBACK_AUTHORIZATION_PACKET}" \
    "${ROLLBACK_AUTHORIZATION_PACKET_SHA}" \
    "${ROLLBACK_AUTHORIZATION_PERMIT}" \
    "${ROLLBACK_AUTHORIZATION_PERMIT_SHA}" \
    "${ROLLBACK_PRODUCTION_BASELINE}" \
    "${ROLLBACK_PRODUCTION_BASELINE_SHA}" \
    "${FROM_RELEASE_MANIFEST_SHA256}" \
    "${FROM_RELEASE_SHA256SUMS_SHA256}" \
    "${TO_RELEASE_MANIFEST_SHA256}" \
    "${TO_RELEASE_SHA256SUMS_SHA256}" \
    "${ROLLBACK_RUNNER_SHA}" \
    "${ROLLBACK_RUNNER_BYTES}" \
    "${collector_id}" "${collector_restart}" \
    "${translation_id}" "${translation_restart}" \
    "${nginx_id}" "${nginx_restart}" "${nginx_before_sha}" \
    "${nginx_before_inode}" "${cron_sha}" "${database_before}" \
    "${report_before}" "${shared_container_inventory_sha}" <<'PY'
import datetime as dt
import json
import os
import stat
import sys
from pathlib import Path

(
    journal_raw,
    schema,
    phase,
    started_at,
    receipt_path,
    receipt_sha,
    from_site,
    to_site,
    from_data_id,
    from_data_sha,
    to_data_id,
    to_data_sha,
    original_previous,
    original_previous_sha,
    evidence_mode,
    target_evidence,
    target_evidence_sha,
    acceptance_evidence,
    acceptance_evidence_sha,
    authorization_packet,
    authorization_packet_sha,
    authorization_permit,
    authorization_permit_sha,
    production_baseline,
    production_baseline_sha,
    from_release_manifest_sha,
    from_release_sha256sums_sha,
    to_release_manifest_sha,
    to_release_sha256sums_sha,
    rollback_runner_sha,
    rollback_runner_bytes,
    collector_id,
    collector_restart,
    translation_id,
    translation_restart,
    nginx_id,
    nginx_restart,
    nginx_sha,
    nginx_inode,
    cron_sha,
    database_identity,
    report_identity,
    shared_container_inventory_sha,
) = sys.argv[1:]
journal = Path(journal_raw)
phases = ["prepared", "data_switched", "site_switched", "complete"]
if phase not in phases:
    raise SystemExit("invalid dual-resource rollback journal phase")
if not started_at or not receipt_path:
    raise SystemExit("dual-resource rollback journal identity is incomplete")

site = {
    "acceptance_receipt_path": acceptance_evidence,
    "acceptance_receipt_sha256": acceptance_evidence_sha,
    "authorization_packet_path": authorization_packet,
    "authorization_packet_sha256": authorization_packet_sha,
    "authorization_permit_path": authorization_permit,
    "authorization_permit_sha256": authorization_permit_sha,
    "evidence_mode": evidence_mode,
    "from_release_manifest_sha256": from_release_manifest_sha,
    "from_release_sha256sums_sha256": from_release_sha256sums_sha,
    "from_release_sha256": from_site,
    "production_baseline_path": production_baseline,
    "production_baseline_sha256": production_baseline_sha,
    "promotion_receipt_path": target_evidence,
    "promotion_receipt_sha256": target_evidence_sha,
    "rollback_runner_bytes": int(rollback_runner_bytes),
    "rollback_runner_sha256": rollback_runner_sha,
    "to_release_manifest_sha256": to_release_manifest_sha,
    "to_release_sha256sums_sha256": to_release_sha256sums_sha,
    "to_release_sha256": to_site,
}
data = {
    "from_pointer_sha256": from_data_sha,
    "from_release_id": from_data_id,
    "original_previous_target": original_previous,
    "original_previous_pointer_sha256": original_previous_sha,
    "to_pointer_sha256": to_data_sha,
    "to_release_id": to_data_id,
}
control_plane_baseline = {
    "collector_id": collector_id,
    "collector_restart_count": int(collector_restart),
    "cron_sha256": cron_sha,
    "database_identity": database_identity,
    "nginx_id": nginx_id,
    "nginx_inode": int(nginx_inode),
    "nginx_restart_count": int(nginx_restart),
    "nginx_sha256": nginx_sha,
    "report_identity": report_identity,
    "shared_container_inventory_sha256": shared_container_inventory_sha,
    "translation_id": translation_id,
    "translation_restart_count": int(translation_restart),
}
history = []
if journal.exists() or journal.is_symlink():
    fd = os.open(journal, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise SystemExit("dual-resource rollback journal metadata is unsafe")
        raw = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(fd)
    try:
        existing = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise SystemExit("dual-resource rollback journal is invalid")
    canonical = json.dumps(
        existing, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if raw != canonical:
        raise SystemExit("dual-resource rollback journal is not canonical JSON")
    if (
        existing.get("schema_version") != schema
        or existing.get("operation") != "dual_resource_release_rollback"
        or existing.get("site") != site
        or existing.get("data") != data
        or existing.get("control_plane_baseline") != control_plane_baseline
        or existing.get("started_at") != started_at
        or existing.get("receipt_path") != receipt_path
    ):
        raise SystemExit("dual-resource rollback journal tuple mismatch")
    previous_phase = existing.get("phase")
    if previous_phase not in phases:
        raise SystemExit("dual-resource rollback journal phase is invalid")
    history = existing.get("phase_history")
    if not isinstance(history, list) or history != phases[: phases.index(previous_phase) + 1]:
        raise SystemExit("dual-resource rollback journal phase history is invalid")
    if phase != previous_phase and phases.index(phase) != phases.index(previous_phase) + 1:
        raise SystemExit("illegal dual-resource rollback journal transition")
else:
    if phase != "prepared":
        raise SystemExit("dual-resource rollback journal must start at prepared")

if not history or history[-1] != phase:
    history = [*history, phase]
value = {
    "control_plane_baseline": control_plane_baseline,
    "data": data,
    "operation": "dual_resource_release_rollback",
    "phase": phase,
    "phase_history": history,
    "receipt_path": receipt_path,
    "receipt_sha256": receipt_sha or None,
    "schema_version": schema,
    "site": site,
    "started_at": started_at,
    "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
payload = json.dumps(
    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8") + b"\n"
temporary = Path(f"{journal}.tmp.{os.getpid()}")
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
fd = os.open(temporary, flags, 0o600)
try:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        view = view[written:]
    os.fsync(fd)
finally:
    os.close(fd)
try:
    os.replace(temporary, journal)
    directory_fd = os.open(journal.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    if temporary.exists():
        temporary.unlink()
PY
  JOURNAL_ACTIVE=1
  JOURNAL_PHASE="${phase}"
}

read_and_validate_rollback_journal() {
  local journal_output
  journal_output="$(python3 - \
    "${ROLLBACK_JOURNAL}" \
    "${ROLLBACK_JOURNAL_SCHEMA}" \
    "${EXPECTED_CURRENT}" \
    "${TARGET_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" \
    "${ROLLBACK_RUNNER_SHA}" \
    "${ROLLBACK_RUNNER_BYTES}" \
    "${collector_id}" "${collector_restart}" \
    "${translation_id}" "${translation_restart}" \
    "${nginx_id}" "${nginx_restart}" "${nginx_before_sha}" \
    "${nginx_before_inode}" "${cron_sha}" "${database_before}" \
    "${report_before}" "${shared_container_inventory_sha}" <<'PY'
import json
import os
import re
import stat
import sys
from pathlib import Path

journal = Path(sys.argv[1])
fd = os.open(journal, os.O_RDONLY | os.O_NOFOLLOW)
try:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SystemExit("dual-resource rollback journal metadata is unsafe")
    raw = b""
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        raw += chunk
finally:
    os.close(fd)
try:
    value = json.loads(raw)
except (UnicodeError, json.JSONDecodeError):
    raise SystemExit("dual-resource rollback journal is invalid")
canonical = json.dumps(
    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8") + b"\n"
if raw != canonical:
    raise SystemExit("dual-resource rollback journal is not canonical JSON")

phase = value.get("phase")
phases = ["prepared", "data_switched", "site_switched", "complete"]
site = value.get("site")
data = value.get("data")
expected_site = {
    "from_release_sha256": sys.argv[3],
    "to_release_sha256": sys.argv[4],
}
expected_data = {
    "from_pointer_sha256": sys.argv[6],
    "from_release_id": sys.argv[5],
    "to_pointer_sha256": sys.argv[8],
    "to_release_id": sys.argv[7],
}
expected_baseline = {
    "collector_id": sys.argv[11],
    "collector_restart_count": int(sys.argv[12]),
    "translation_id": sys.argv[13],
    "translation_restart_count": int(sys.argv[14]),
    "nginx_id": sys.argv[15],
    "nginx_restart_count": int(sys.argv[16]),
    "nginx_sha256": sys.argv[17],
    "nginx_inode": int(sys.argv[18]),
    "cron_sha256": sys.argv[19],
    "database_identity": sys.argv[20],
    "report_identity": sys.argv[21],
    "shared_container_inventory_sha256": sys.argv[22],
}
if (
    set(value) != {
        "control_plane_baseline", "data", "operation", "phase", "phase_history", "receipt_path",
        "receipt_sha256", "schema_version", "site", "started_at", "updated_at",
    }
    or
    value.get("schema_version") != sys.argv[2]
    or value.get("operation") != "dual_resource_release_rollback"
    or value.get("control_plane_baseline") != expected_baseline
    or not isinstance(site, dict)
    or set(site) != {
        "acceptance_receipt_path", "acceptance_receipt_sha256",
        "authorization_packet_path", "authorization_packet_sha256",
        "authorization_permit_path", "authorization_permit_sha256",
        "evidence_mode", "from_release_manifest_sha256",
        "from_release_sha256sums_sha256", "from_release_sha256",
        "production_baseline_path",
        "production_baseline_sha256", "promotion_receipt_path",
        "promotion_receipt_sha256", "rollback_runner_bytes",
        "rollback_runner_sha256", "to_release_manifest_sha256",
        "to_release_sha256sums_sha256", "to_release_sha256",
    }
    or any(site.get(key) != item for key, item in expected_site.items())
    or site.get("rollback_runner_sha256") != sys.argv[9]
    or site.get("rollback_runner_bytes") != int(sys.argv[10])
    or not isinstance(data, dict)
    or set(data) != {
        "from_pointer_sha256", "from_release_id",
        "original_previous_pointer_sha256", "original_previous_target",
        "to_pointer_sha256", "to_release_id",
    }
    or any(data.get(key) != item for key, item in expected_data.items())
    or phase not in phases
    or value.get("phase_history") != phases[: phases.index(phase) + 1]
):
    raise SystemExit("journal does not match the exact requested site/data tuple")
original_previous = data.get("original_previous_target")
original_previous_sha = data.get("original_previous_pointer_sha256")
if original_previous != "absent" and re.fullmatch(
    r"releases/reddit_voc_release_[a-z0-9_-]+", original_previous or ""
) is None:
    raise SystemExit("journal original data previous target is invalid")
if (
    (original_previous == "absent" and original_previous_sha != "absent")
    or (
        original_previous != "absent"
        and re.fullmatch(r"[a-f0-9]{64}", original_previous_sha or "") is None
    )
):
    raise SystemExit("journal original data previous pointer checksum is invalid")
receipt_path = value.get("receipt_path")
expected_parent = journal.parent / "evidence"
if (
    not isinstance(receipt_path, str)
    or Path(receipt_path).parent != expected_parent
    or re.fullmatch(r"rollback-release-[A-Za-z0-9._-]+\.json", Path(receipt_path).name) is None
):
    raise SystemExit("journal receipt path is invalid")
evidence_mode = site.get("evidence_mode")
target_evidence = site.get("promotion_receipt_path")
target_evidence_sha = site.get("promotion_receipt_sha256")
acceptance_evidence = site.get("acceptance_receipt_path")
acceptance_evidence_sha = site.get("acceptance_receipt_sha256")
authorization_packet = site.get("authorization_packet_path")
authorization_packet_sha = site.get("authorization_packet_sha256")
authorization_permit = site.get("authorization_permit_path")
authorization_permit_sha = site.get("authorization_permit_sha256")
production_baseline = site.get("production_baseline_path")
production_baseline_sha = site.get("production_baseline_sha256")
from_release_manifest_sha = site.get("from_release_manifest_sha256")
from_release_sha256sums_sha = site.get("from_release_sha256sums_sha256")
to_release_manifest_sha = site.get("to_release_manifest_sha256")
to_release_sha256sums_sha = site.get("to_release_sha256sums_sha256")
if (
    evidence_mode != "forward_previous_authorized"
    or not isinstance(target_evidence, str)
    or Path(target_evidence).parent != expected_parent
    or not Path(target_evidence).name
    or re.fullmatch(r"[a-f0-9]{64}", target_evidence_sha or "") is None
    or acceptance_evidence != "absent"
    or acceptance_evidence_sha != "absent"
    or any(
        not isinstance(path, str) or Path(path).parent != expected_parent
        for path in (authorization_packet, authorization_permit, production_baseline)
    )
    or any(
        re.fullmatch(r"[a-f0-9]{64}", digest or "") is None
        for digest in (
            authorization_packet_sha, authorization_permit_sha,
            production_baseline_sha, from_release_manifest_sha,
            from_release_sha256sums_sha, to_release_manifest_sha,
            to_release_sha256sums_sha,
        )
    )
):
    raise SystemExit("journal rollback transaction evidence binding is invalid")
started_at = value.get("started_at")
receipt_sha = value.get("receipt_sha256")
if not isinstance(started_at, str) or re.fullmatch(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", started_at
) is None:
    raise SystemExit("journal start time is invalid")
if receipt_sha is not None and re.fullmatch(r"[a-f0-9]{64}", receipt_sha) is None:
    raise SystemExit("journal receipt checksum is invalid")
print(
    phase, original_previous, original_previous_sha, receipt_path,
    receipt_sha or "", started_at, evidence_mode, target_evidence,
    target_evidence_sha, acceptance_evidence, acceptance_evidence_sha,
    authorization_packet, authorization_packet_sha, authorization_permit,
    authorization_permit_sha, production_baseline, production_baseline_sha,
    from_release_manifest_sha, from_release_sha256sums_sha,
    to_release_manifest_sha, to_release_sha256sums_sha,
    sep="\t",
)
PY
)"
  IFS=$'\t' read -r JOURNAL_PHASE ORIGINAL_DATA_PREVIOUS_TARGET \
    ORIGINAL_DATA_PREVIOUS_SHA \
    ROLLBACK_RECEIPT_FILE ROLLBACK_RECEIPT_SHA ROLLBACK_STARTED_AT_UTC \
    ROLLBACK_EVIDENCE_MODE TARGET_DEPLOYMENT_EVIDENCE \
    TARGET_DEPLOYMENT_EVIDENCE_SHA ROLLBACK_ACCEPTANCE_EVIDENCE \
    ROLLBACK_ACCEPTANCE_EVIDENCE_SHA ROLLBACK_AUTHORIZATION_PACKET \
    ROLLBACK_AUTHORIZATION_PACKET_SHA ROLLBACK_AUTHORIZATION_PERMIT \
    ROLLBACK_AUTHORIZATION_PERMIT_SHA ROLLBACK_PRODUCTION_BASELINE \
    ROLLBACK_PRODUCTION_BASELINE_SHA FROM_RELEASE_MANIFEST_SHA256 \
    FROM_RELEASE_SHA256SUMS_SHA256 TO_RELEASE_MANIFEST_SHA256 \
    TO_RELEASE_SHA256SUMS_SHA256 \
    <<< "${journal_output}"
  JOURNAL_ACTIVE=1
}

clear_rollback_journal() {
  revalidate_rollback_locks
  python3 - "${ROLLBACK_JOURNAL}" <<'PY'
import os
import stat
import sys
from pathlib import Path

journal = Path(sys.argv[1])
fd = os.open(journal, os.O_RDONLY | os.O_NOFOLLOW)
try:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SystemExit("refusing to clear unsafe dual-resource rollback journal")
finally:
    os.close(fd)
os.unlink(journal)
directory_fd = os.open(journal.parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
  JOURNAL_ACTIVE=0
}

write_dual_rollback_receipt() {
  local completed_at
  revalidate_rollback_locks
  completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python3 - \
    "${ROLLBACK_RECEIPT_FILE}" \
    "${ROLLBACK_RECEIPT_SCHEMA}" \
    "${completed_at}" \
    "${EXPECTED_CURRENT}" \
    "${TARGET_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" \
    "${ROLLBACK_EVIDENCE_MODE}" \
    "${TARGET_DEPLOYMENT_EVIDENCE}" \
    "${TARGET_DEPLOYMENT_EVIDENCE_SHA}" \
    "${ROLLBACK_ACCEPTANCE_EVIDENCE}" \
    "${ROLLBACK_ACCEPTANCE_EVIDENCE_SHA}" \
    "${ROLLBACK_AUTHORIZATION_PACKET}" \
    "${ROLLBACK_AUTHORIZATION_PACKET_SHA}" \
    "${ROLLBACK_AUTHORIZATION_PERMIT}" \
    "${ROLLBACK_AUTHORIZATION_PERMIT_SHA}" \
    "${ROLLBACK_PRODUCTION_BASELINE}" \
    "${ROLLBACK_PRODUCTION_BASELINE_SHA}" \
    "${FROM_RELEASE_MANIFEST_SHA256}" \
    "${FROM_RELEASE_SHA256SUMS_SHA256}" \
    "${TO_RELEASE_MANIFEST_SHA256}" \
    "${TO_RELEASE_SHA256SUMS_SHA256}" \
    "${ROLLBACK_RUNNER_SHA}" \
    "${ROLLBACK_RUNNER_BYTES}" \
    "${collector_id}" "${collector_restart}" \
    "${translation_id}" "${translation_restart}" \
    "${nginx_id}" "${nginx_restart}" "${nginx_before_sha}" \
    "${nginx_before_inode}" "${cron_sha}" "${database_before}" \
    "${report_before}" "${shared_container_inventory_sha}" \
    "${FROM_DATA_INVENTORY_SHA}" \
    "${FROM_DATA_FILE_COUNT}" \
    "${FROM_DATA_TOTAL_BYTES}" \
    "${TO_DATA_INVENTORY_SHA}" \
    "${TO_DATA_FILE_COUNT}" \
    "${TO_DATA_TOTAL_BYTES}" \
    "${collector_restart}" \
    "${translation_restart}" \
    "${nginx_restart}" \
    "${nginx_before_sha}" \
    "${target_collection_integrated}" \
    "${target_collection_fully_hydrated}" \
    "${ROLLBACK_JOURNAL_SCHEMA}" <<'PY'
import ctypes
import errno
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

(
    receipt_raw,
    schema,
    completed_at,
    from_site,
    to_site,
    from_data_id,
    from_data_sha,
    to_data_id,
    to_data_sha,
    evidence_mode,
    target_evidence,
    target_evidence_sha,
    acceptance_evidence,
    acceptance_evidence_sha,
    authorization_packet,
    authorization_packet_sha,
    authorization_permit,
    authorization_permit_sha,
    production_baseline,
    production_baseline_sha,
    from_release_manifest_sha,
    from_release_sha256sums_sha,
    to_release_manifest_sha,
    to_release_sha256sums_sha,
    rollback_runner_sha,
    rollback_runner_bytes,
    collector_id,
    baseline_collector_restart,
    translation_id,
    baseline_translation_restart,
    nginx_id,
    baseline_nginx_restart,
    baseline_nginx_sha,
    nginx_inode,
    cron_sha,
    database_identity,
    report_identity,
    shared_container_inventory_sha,
    from_inventory_sha,
    from_file_count,
    from_total_bytes,
    to_inventory_sha,
    to_file_count,
    to_total_bytes,
    collector_restart,
    translation_restart,
    nginx_restart,
    nginx_sha,
    integrated,
    hydrated,
    journal_schema,
) = sys.argv[1:]
receipt = Path(receipt_raw)
if receipt.exists() or receipt.is_symlink():
    raise SystemExit("dual-resource rollback receipt path already exists")
value = {
    "action": "release",
    "completed_at": completed_at,
    "control_plane_baseline": {
        "collector_id": collector_id,
        "collector_restart_count": int(baseline_collector_restart),
        "cron_sha256": cron_sha,
        "database_identity": database_identity,
        "nginx_id": nginx_id,
        "nginx_inode": int(nginx_inode),
        "nginx_restart_count": int(baseline_nginx_restart),
        "nginx_sha256": baseline_nginx_sha,
        "report_identity": report_identity,
        "shared_container_inventory_sha256": shared_container_inventory_sha,
        "translation_id": translation_id,
        "translation_restart_count": int(baseline_translation_restart),
    },
    "data": {
        "from_pointer_sha256": from_data_sha,
        "from_release_id": from_data_id,
        "from_inventory_sha256": from_inventory_sha,
        "from_file_count": int(from_file_count),
        "from_total_bytes": int(from_total_bytes),
        "to_pointer_sha256": to_data_sha,
        "to_release_id": to_data_id,
        "to_inventory_sha256": to_inventory_sha,
        "to_file_count": int(to_file_count),
        "to_total_bytes": int(to_total_bytes),
        "verified_current_target": f"releases/{to_data_id}",
        "verified_previous_target": f"releases/{from_data_id}",
    },
    "evidence_grade": "L4-authorized-live",
    "invariants": {
        "automatic_failure_recovery_armed": True,
        "collector_id_unchanged": True,
        "collector_restart_count": int(collector_restart),
        "cron_unchanged": True,
        "database_write": False,
        "live_send": False,
        "nginx_id_unchanged": True,
        "nginx_restart_count": int(nginx_restart),
        "nginx_sha256": nginx_sha,
        "nginx_unchanged": True,
        "provider_call": False,
        "shared_service_baseline_verified": True,
        "translation_id_unchanged": True,
        "translation_restart_count": int(translation_restart),
        "webhook_send": False,
    },
    "journal": {
        "phase_history": ["prepared", "data_switched", "site_switched", "complete"],
        "schema_version": journal_schema,
    },
    "latest_collection_fully_hydrated": hydrated == "true",
    "latest_collection_integrated": integrated == "true",
    "schema_version": schema,
    "site": {
        "acceptance_receipt_path": acceptance_evidence,
        "acceptance_receipt_sha256": acceptance_evidence_sha,
        "authorization_packet_path": authorization_packet,
        "authorization_packet_sha256": authorization_packet_sha,
        "authorization_permit_path": authorization_permit,
        "authorization_permit_sha256": authorization_permit_sha,
        "evidence_mode": evidence_mode,
        "from_release_manifest_sha256": from_release_manifest_sha,
        "from_release_sha256sums_sha256": from_release_sha256sums_sha,
        "from_release_sha256": from_site,
        "production_baseline_path": production_baseline,
        "production_baseline_sha256": production_baseline_sha,
        "promotion_receipt_path": target_evidence,
        "promotion_receipt_sha256": target_evidence_sha,
        "rollback_runner_bytes": int(rollback_runner_bytes),
        "rollback_runner_sha256": rollback_runner_sha,
        "runtime_release_sha256": to_site,
        "to_release_manifest_sha256": to_release_manifest_sha,
        "to_release_sha256sums_sha256": to_release_sha256sums_sha,
        "to_release_sha256": to_site,
        "verified_current_target": f"releases/{to_site}",
    },
    "status": "dual_resource_rollback_complete",
}
payload = json.dumps(
    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8") + b"\n"
temporary = Path(f"{receipt}.tmp.{os.getpid()}")
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
fd = os.open(temporary, flags, 0o600)
try:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        view = view[written:]
    os.fsync(fd)
finally:
    os.close(fd)
try:
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(temporary)
    destination = os.fsencode(receipt)
    if hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, source, -100, destination, 1)
    elif hasattr(libc, "renamex_np"):
        result = libc.renamex_np(source, destination, 4)
    else:
        raise SystemExit("atomic no-replace rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise SystemExit("dual-resource rollback receipt path already exists")
        raise OSError(error, os.strerror(error), str(receipt))
    directory_fd = os.open(receipt.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    if temporary.exists():
        temporary.unlink()
info = receipt.lstat()
if (
    not stat.S_ISREG(info.st_mode)
    or info.st_nlink != 1
    or info.st_uid != os.getuid()
    or stat.S_IMODE(info.st_mode) != 0o600
):
    raise SystemExit("published dual-resource rollback receipt is unsafe")
print(hashlib.sha256(payload).hexdigest())
PY
}

validate_dual_rollback_receipt() {
  local expected_receipt_sha="${1:-}"
  revalidate_rollback_locks
  reverify_bound_release_artifacts || return 1
  python3 - \
    "${ROLLBACK_RECEIPT_FILE}" \
    "${ROLLBACK_RECEIPT_SCHEMA}" \
    "${expected_receipt_sha}" \
    "${EXPECTED_CURRENT}" \
    "${TARGET_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" \
    "${ROLLBACK_JOURNAL_SCHEMA}" \
    "${ROLLBACK_EVIDENCE_MODE}" \
    "${TARGET_DEPLOYMENT_EVIDENCE}" \
    "${TARGET_DEPLOYMENT_EVIDENCE_SHA}" \
    "${ROLLBACK_ACCEPTANCE_EVIDENCE}" \
    "${ROLLBACK_ACCEPTANCE_EVIDENCE_SHA}" \
    "${ROLLBACK_AUTHORIZATION_PACKET}" \
    "${ROLLBACK_AUTHORIZATION_PACKET_SHA}" \
    "${ROLLBACK_AUTHORIZATION_PERMIT}" \
    "${ROLLBACK_AUTHORIZATION_PERMIT_SHA}" \
    "${ROLLBACK_PRODUCTION_BASELINE}" \
    "${ROLLBACK_PRODUCTION_BASELINE_SHA}" \
    "${FROM_RELEASE_MANIFEST_SHA256}" \
    "${FROM_RELEASE_SHA256SUMS_SHA256}" \
    "${TO_RELEASE_MANIFEST_SHA256}" \
    "${TO_RELEASE_SHA256SUMS_SHA256}" \
    "${ROLLBACK_RUNNER_SHA}" \
    "${ROLLBACK_RUNNER_BYTES}" \
    "${collector_id}" "${collector_restart}" \
    "${translation_id}" "${translation_restart}" \
    "${nginx_id}" "${nginx_restart}" "${nginx_before_sha}" \
    "${nginx_before_inode}" "${cron_sha}" "${database_before}" \
    "${report_before}" "${shared_container_inventory_sha}" \
    "${FROM_DATA_INVENTORY_SHA}" \
    "${FROM_DATA_FILE_COUNT}" \
    "${FROM_DATA_TOTAL_BYTES}" \
    "${TO_DATA_INVENTORY_SHA}" \
    "${TO_DATA_FILE_COUNT}" \
    "${TO_DATA_TOTAL_BYTES}" <<'PY'
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

receipt = Path(sys.argv[1])
fd = os.open(receipt, os.O_RDONLY | os.O_NOFOLLOW)
try:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SystemExit("dual-resource rollback receipt metadata is unsafe")
    raw = b""
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        raw += chunk
finally:
    os.close(fd)
try:
    value = json.loads(raw)
except (UnicodeError, json.JSONDecodeError):
    raise SystemExit("dual-resource rollback receipt is invalid")
canonical = json.dumps(
    value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8") + b"\n"
if raw != canonical:
    raise SystemExit("dual-resource rollback receipt is not canonical JSON")
actual_sha = hashlib.sha256(raw).hexdigest()
if sys.argv[3] and actual_sha != sys.argv[3]:
    raise SystemExit("dual-resource rollback receipt checksum mismatch")
site = value.get("site")
data = value.get("data")
control_plane_baseline = value.get("control_plane_baseline")
invariants = value.get("invariants")
journal = value.get("journal")
if (
    set(value) != {
        "action", "completed_at", "control_plane_baseline", "data", "evidence_grade", "invariants",
        "journal", "latest_collection_fully_hydrated",
        "latest_collection_integrated", "schema_version", "site", "status",
    }
    or value.get("schema_version") != sys.argv[2]
    or value.get("status") != "dual_resource_rollback_complete"
    or value.get("action") != "release"
    or value.get("evidence_grade") != "L4-authorized-live"
    or control_plane_baseline != {
        "collector_id": sys.argv[28],
        "collector_restart_count": int(sys.argv[29]),
        "translation_id": sys.argv[30],
        "translation_restart_count": int(sys.argv[31]),
        "nginx_id": sys.argv[32],
        "nginx_restart_count": int(sys.argv[33]),
        "nginx_sha256": sys.argv[34],
        "nginx_inode": int(sys.argv[35]),
        "cron_sha256": sys.argv[36],
        "database_identity": sys.argv[37],
        "report_identity": sys.argv[38],
        "shared_container_inventory_sha256": sys.argv[39],
    }
    or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value.get("completed_at", "")) is None
    or site != {
        "acceptance_receipt_path": sys.argv[14],
        "acceptance_receipt_sha256": sys.argv[15],
        "authorization_packet_path": sys.argv[16],
        "authorization_packet_sha256": sys.argv[17],
        "authorization_permit_path": sys.argv[18],
        "authorization_permit_sha256": sys.argv[19],
        "evidence_mode": sys.argv[11],
        "from_release_manifest_sha256": sys.argv[22],
        "from_release_sha256sums_sha256": sys.argv[23],
        "from_release_sha256": sys.argv[4],
        "production_baseline_path": sys.argv[20],
        "production_baseline_sha256": sys.argv[21],
        "promotion_receipt_path": sys.argv[12],
        "promotion_receipt_sha256": sys.argv[13],
        "rollback_runner_bytes": int(sys.argv[27]),
        "rollback_runner_sha256": sys.argv[26],
        "runtime_release_sha256": sys.argv[5],
        "to_release_manifest_sha256": sys.argv[24],
        "to_release_sha256sums_sha256": sys.argv[25],
        "to_release_sha256": sys.argv[5],
        "verified_current_target": f"releases/{sys.argv[5]}",
    }
    or data != {
        "from_pointer_sha256": sys.argv[7],
        "from_release_id": sys.argv[6],
        "from_inventory_sha256": sys.argv[40],
        "from_file_count": int(sys.argv[41]),
        "from_total_bytes": int(sys.argv[42]),
        "to_pointer_sha256": sys.argv[9],
        "to_release_id": sys.argv[8],
        "to_inventory_sha256": sys.argv[43],
        "to_file_count": int(sys.argv[44]),
        "to_total_bytes": int(sys.argv[45]),
        "verified_current_target": f"releases/{sys.argv[8]}",
        "verified_previous_target": f"releases/{sys.argv[6]}",
    }
    or journal != {
        "phase_history": ["prepared", "data_switched", "site_switched", "complete"],
        "schema_version": sys.argv[10],
    }
    or not isinstance(invariants, dict)
    or set(invariants) != {
        "automatic_failure_recovery_armed", "collector_id_unchanged",
        "collector_restart_count", "cron_unchanged", "database_write",
        "live_send", "nginx_id_unchanged", "nginx_restart_count",
        "nginx_sha256", "nginx_unchanged", "provider_call",
        "shared_service_baseline_verified", "translation_id_unchanged",
        "translation_restart_count", "webhook_send",
    }
    or invariants.get("automatic_failure_recovery_armed") is not True
    or invariants.get("shared_service_baseline_verified") is not True
    or invariants.get("collector_id_unchanged") is not True
    or invariants.get("translation_id_unchanged") is not True
    or invariants.get("nginx_id_unchanged") is not True
    or invariants.get("nginx_unchanged") is not True
    or invariants.get("cron_unchanged") is not True
    or invariants.get("database_write") is not False
    or invariants.get("live_send") is not False
    or invariants.get("provider_call") is not False
    or invariants.get("webhook_send") is not False
    or any(
        type(invariants.get(name)) is not int or invariants[name] < 0
        for name in (
            "collector_restart_count", "translation_restart_count",
            "nginx_restart_count",
        )
    )
    or re.fullmatch(r"[a-f0-9]{64}", invariants.get("nginx_sha256", "")) is None
    or type(value.get("latest_collection_integrated")) is not bool
    or type(value.get("latest_collection_fully_hydrated")) is not bool
):
    raise SystemExit("dual-resource rollback receipt contract mismatch")
if sys.argv[11] != "forward_previous_authorized" or sys.argv[14:16] != ["absent", "absent"]:
    raise SystemExit("dual-resource rollback evidence mode is invalid")
for label, path_raw, expected_sha in (
    ("promotion", sys.argv[12], sys.argv[13]),
    ("packet", sys.argv[16], sys.argv[17]),
    ("permit", sys.argv[18], sys.argv[19]),
    ("baseline", sys.argv[20], sys.argv[21]),
):
    evidence_path = Path(path_raw)
    if evidence_path.parent != receipt.parent:
        raise SystemExit(f"dual-resource rollback {label} evidence path is unsafe")
    evidence_fd = os.open(evidence_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        evidence_info = os.fstat(evidence_fd)
        linked_info = os.lstat(evidence_path)
        if (
            not stat.S_ISREG(evidence_info.st_mode)
            or not stat.S_ISREG(linked_info.st_mode)
            or (evidence_info.st_dev, evidence_info.st_ino)
            != (linked_info.st_dev, linked_info.st_ino)
            or evidence_info.st_nlink != 1
            or linked_info.st_nlink != 1
            or evidence_info.st_uid != os.getuid()
            or linked_info.st_uid != os.getuid()
            or stat.S_IMODE(evidence_info.st_mode) != 0o600
            or stat.S_IMODE(linked_info.st_mode) != 0o600
        ):
            raise SystemExit(f"dual-resource rollback {label} evidence metadata is unsafe")
        evidence_digest = hashlib.sha256()
        while True:
            chunk = os.read(evidence_fd, 1024 * 1024)
            if not chunk:
                break
            evidence_digest.update(chunk)
    finally:
        os.close(evidence_fd)
    if evidence_digest.hexdigest() != expected_sha:
        raise SystemExit(f"dual-resource rollback {label} evidence checksum mismatch")
print(actual_sha)
PY
}

cleanup_transient() {
  if ! cleanup_rollback_verifier_residue; then
    echo "CRITICAL: transaction-owned rollback verifier residue was not cleaned" >&2
  fi
  local snapshot
  for snapshot in "${CURRENT_RUNTIME_SNAPSHOT}" "${TARGET_RUNTIME_SNAPSHOT}"; do
    if [[ -n "${snapshot}" ]]; then
      case "${snapshot}" in
        "${RELEASE_ROOT}"/.rollback-runtime-[a-f0-9]*.[A-Za-z0-9]*)
          if [[ -d "${snapshot}" && ! -L "${snapshot}" ]]; then
            chmod 0700 "${snapshot}" >/dev/null 2>&1 || true
            rm -rf -- "${snapshot}"
          else
            echo "CRITICAL: runtime snapshot cleanup path is unsafe" >&2
          fi
          ;;
        *)
          echo "CRITICAL: runtime snapshot cleanup escaped the release root" >&2
          ;;
      esac
    fi
  done
  CURRENT_RUNTIME_SNAPSHOT=""
  CURRENT_EXPECTED_IMAGE_ID=""
  TARGET_RUNTIME_SNAPSHOT=""
  TARGET_EXPECTED_IMAGE_ID=""
  rm -f "${CURRENT_TMP}"
  rm -f "${DATA_CURRENT_TMP}" "${DATA_PREVIOUS_TMP}"
  if [[ -n "${EVIDENCE_TMP}" ]]; then
    rm -f "${EVIDENCE_TMP}"
  fi
  if [[ "${ACTION_SUCCEEDED}" != "1" && -n "${EVIDENCE_FILE}" ]]; then
    if [[ "${DUAL_DATA_ROLLBACK}" != "1" || "${EVIDENCE_FILE}" != "${ROLLBACK_RECEIPT_FILE}" ]]; then
      rm -f "${EVIDENCE_FILE}"
    fi
  fi
}

restore_current_pointer() {
  reverify_bound_release_artifacts || return 1
  if [[ -L "${DEPLOY_ROOT}/current" && \
        "$(readlink "${DEPLOY_ROOT}/current")" == \
          "releases/${EXPECTED_CURRENT}" ]]; then
    CURRENT_CHANGED=0
    return 0
  fi
  cas_replace_symlink \
    "${DEPLOY_ROOT}/current" \
    "releases/${TARGET_RELEASE}" \
    "releases/${EXPECTED_CURRENT}" \
    "restore-site-current" || return 1
  CURRENT_CHANGED=0
}

restore_original_release() {
  local compose_path compose_override
  reverify_bound_release_artifacts || return 1
  prepare_release_runtime_snapshot "${EXPECTED_CURRENT}" || return 1
  verify_runtime_compose_contract "${EXPECTED_CURRENT}" || return 1
  compose_path="$(runtime_snapshot_directory "${EXPECTED_CURRENT}")/compose.yaml" || return 1
  compose_override="$(
    runtime_snapshot_directory "${EXPECTED_CURRENT}"
  )/compose-image-id.yaml" || return 1
  RELEASE_SHA="${EXPECTED_CURRENT}" \
  INSIGHTS_BIND_ADDRESS="${BIND_ADDRESS}" \
  INSIGHTS_PORT="${PORT}" \
    REDDIT_VOC_DATA_ROOT="${DATA_ROOT}" \
      docker compose -p "${COMPOSE_PROJECT}" \
        -f "${compose_path}" -f "${compose_override}" \
        up -d --pull never --no-build --no-deps web || return 1
  wait_for_release_health "${EXPECTED_CURRENT}" || return 1
  verify_runtime_contract "${EXPECTED_CURRENT}" || return 1
  restore_current_pointer || return 1
}

restore_original_data() {
  [[ "${DUAL_DATA_ROLLBACK}" == "1" ]] || return 0
  local recovery_ok=1
  reverify_bound_release_artifacts || return 1
  rm -f "${DATA_CURRENT_TMP}" "${DATA_PREVIOUS_TMP}" || return 1
  if [[ "${DATA_CURRENT_CHANGED}" == "1" ]]; then
    if [[ -L "${DATA_ROOT}/current" && \
          "$(readlink "${DATA_ROOT}/current")" == \
            "releases/${EXPECTED_CURRENT_DATA_RELEASE}" ]]; then
      DATA_CURRENT_CHANGED=0
    elif cas_replace_symlink \
      "${DATA_ROOT}/current" \
      "releases/${TARGET_DATA_RELEASE}" \
      "releases/${EXPECTED_CURRENT_DATA_RELEASE}" \
      "restore-data-current"; then
      DATA_CURRENT_CHANGED=0
    else
      recovery_ok=0
    fi
  fi
  if [[ "${DATA_PREVIOUS_CHANGED}" == "1" ]]; then
    reverify_bound_release_artifacts || return 1
    if [[ "${ORIGINAL_DATA_PREVIOUS_TARGET}" == "absent" ]]; then
      if [[ ! -e "${DATA_ROOT}/previous" && ! -L "${DATA_ROOT}/previous" ]]; then
        :
      elif cas_remove_symlink \
        "${DATA_ROOT}/previous" \
        "releases/${EXPECTED_CURRENT_DATA_RELEASE}" \
        "restore-data-previous"; then
        :
      else
        recovery_ok=0
      fi
    elif [[ -L "${DATA_ROOT}/previous" && \
            "$(readlink "${DATA_ROOT}/previous")" == \
              "${ORIGINAL_DATA_PREVIOUS_TARGET}" ]]; then
      :
    elif cas_replace_symlink \
      "${DATA_ROOT}/previous" \
      "releases/${EXPECTED_CURRENT_DATA_RELEASE}" \
      "${ORIGINAL_DATA_PREVIOUS_TARGET}" \
      "restore-data-previous"; then
      :
    else
      recovery_ok=0
    fi
    DATA_PREVIOUS_CHANGED=0
  fi
  if ! assert_expected_data_pointer; then
    recovery_ok=0
  fi
  if ! assert_original_data_previous_pointer; then
    recovery_ok=0
  fi
  [[ "${recovery_ok}" == "1" ]]
}

restore_original_nginx() {
  if [[ "${VHOST_WAS_PRESENT}" != "1" || -z "${BACKUP_DIR}" ]]; then
    return 0
  fi
  sudo cp "${BACKUP_DIR}/nginx.conf" "${NGINX_CONF}" || return 1
  local restored_inode restored_host_sha restored_container_sha
  restored_inode="$(stat -c '%i' "${NGINX_CONF}")" || return 1
  restored_host_sha="$(sha256sum "${NGINX_CONF}" | awk '{print $1}')" || return 1
  restored_container_sha="$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')" || return 1
  if [[ "${restored_inode}" != "${nginx_before_inode}" || "${restored_host_sha}" != "${nginx_before_sha}" || "${restored_container_sha}" != "${nginx_before_sha}" ]]; then
    echo "CRITICAL: Nginx rollback content or inode verification failed" >&2
    return 1
  fi
  docker exec "${NGINX_CONTAINER}" nginx -t >/dev/null || return 1
  docker exec "${NGINX_CONTAINER}" nginx -s reload || return 1
  curl -fsS "${COLLECTOR_PUBLIC_URL}" >/dev/null || return 1
  VHOST_REMOVED=0
}

assert_dual_recovery_phase_cas() {
  [[ "${DUAL_DATA_ROLLBACK}" == "1" && "${JOURNAL_ACTIVE}" == "1" ]] || return 0
  if [[ ! "${JOURNAL_PHASE:-}" =~ ^(prepared|data_switched|site_switched|complete)$ ]]; then
    echo "dual-resource recovery phase is missing or invalid" >&2
    return 1
  fi

  validate_release_payload "${EXPECTED_CURRENT}" || return 1
  validate_release_data_binding \
    "${EXPECTED_CURRENT}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" || return 1
  validate_and_bind_data_inventory from \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${EXPECTED_CURRENT}" || return 1
  validate_release_payload "${TARGET_RELEASE}" || return 1
  validate_release_data_binding \
    "${TARGET_RELEASE}" \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" || return 1
  validate_and_bind_data_inventory to \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" \
    "${TARGET_RELEASE}" || return 1
  reverify_bound_release_artifacts || return 1

  local observed_site observed_data_current observed_data_current_sha
  local observed_data_previous observed_data_previous_sha
  local runtime_release runtime_health http_release pointer_file
  if [[ -L "${DEPLOY_ROOT}/current" ]]; then
    observed_site="$(readlink "${DEPLOY_ROOT}/current")"
  else
    observed_site="unsafe"
  fi
  if [[ -L "${DATA_ROOT}/current" ]]; then
    observed_data_current="$(readlink "${DATA_ROOT}/current")"
  else
    observed_data_current="unsafe"
  fi
  case "${observed_data_current}" in
    "releases/${EXPECTED_CURRENT_DATA_RELEASE}"|"releases/${TARGET_DATA_RELEASE}")
      pointer_file="${DATA_ROOT}/${observed_data_current}/public/data/reddit-voc/current-release.json"
      observed_data_current_sha="$(safe_file_sha256 "${pointer_file}")"
      ;;
    *)
      observed_data_current_sha="unsafe"
      ;;
  esac
  if [[ ! -e "${DATA_ROOT}/previous" && ! -L "${DATA_ROOT}/previous" ]]; then
    observed_data_previous="absent"
    observed_data_previous_sha="absent"
  elif [[ -L "${DATA_ROOT}/previous" ]]; then
    observed_data_previous="$(readlink "${DATA_ROOT}/previous")"
    if [[ "${observed_data_previous}" == "releases/${EXPECTED_CURRENT_DATA_RELEASE}" || \
          "${observed_data_previous}" == "${ORIGINAL_DATA_PREVIOUS_TARGET}" ]]; then
      pointer_file="${DATA_ROOT}/${observed_data_previous}/public/data/reddit-voc/current-release.json"
      observed_data_previous_sha="$(safe_file_sha256 "${pointer_file}")"
    else
      observed_data_previous_sha="unsafe"
    fi
  else
    observed_data_previous="unsafe"
    observed_data_previous_sha="unsafe"
  fi
  runtime_release="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' "${CONTAINER_NAME}" 2>/dev/null || printf 'missing')"
  runtime_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${CONTAINER_NAME}" 2>/dev/null || printf 'missing')"
  http_release="$(curl -fsS "http://${BIND_ADDRESS}:${PORT}/release.json" 2>/dev/null | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["release_sha256"])' 2>/dev/null || printf 'missing')"

  python3 - \
    "${JOURNAL_PHASE}" \
    "${observed_site}" \
    "${runtime_release}" \
    "${runtime_health}" \
    "${http_release}" \
    "${observed_data_current}" \
    "${observed_data_current_sha}" \
    "${observed_data_previous}" \
    "${observed_data_previous_sha}" \
    "${EXPECTED_CURRENT}" \
    "${TARGET_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" \
    "${ORIGINAL_DATA_PREVIOUS_TARGET}" \
    "${ORIGINAL_DATA_PREVIOUS_SHA}" <<'PY'
import sys

(
    phase,
    site_pointer,
    runtime_release,
    runtime_health,
    http_release,
    data_current,
    data_current_sha,
    data_previous,
    data_previous_sha,
    from_site,
    to_site,
    from_data_id,
    from_data_sha,
    to_data_id,
    to_data_sha,
    original_previous,
    original_previous_sha,
) = sys.argv[1:]

site_from = f"releases/{from_site}"
site_to = f"releases/{to_site}"
data_from = f"releases/{from_data_id}"
data_to = f"releases/{to_data_id}"
if original_previous == "absent":
    original_pair = ("absent", "absent")
else:
    original_pair = (original_previous, original_previous_sha)
old_data = (data_from, from_data_sha)
new_data = (data_to, to_data_sha)
allowed_site_runtime = {
    "prepared": {(site_from, from_site)},
    "data_switched": {
        (site_from, from_site),
        (site_from, "missing"),
        (site_from, to_site),
        (site_to, to_site),
    },
    "site_switched": {(site_to, to_site)},
    "complete": {(site_to, to_site)},
}
allowed_data_pairs = {
    "prepared": {
        (*old_data, *original_pair),
        (*old_data, *old_data),
        (*new_data, *old_data),
    },
    "data_switched": {(*new_data, *old_data)},
    "site_switched": {(*new_data, *old_data)},
    "complete": {(*new_data, *old_data)},
}

if (site_pointer, runtime_release) not in allowed_site_runtime[phase]:
    raise SystemExit("recovery CAS rejected site/runtime tuple outside the journal phase")
if runtime_release == "missing":
    if runtime_health != "missing" or http_release != "missing":
        raise SystemExit("recovery CAS rejected incomplete missing-runtime tuple")
elif runtime_health not in {"healthy", "starting", "unhealthy"}:
    raise SystemExit("recovery CAS rejected unknown runtime health")
elif runtime_health == "healthy" and http_release != runtime_release:
    raise SystemExit("recovery CAS rejected runtime/HTTP release mismatch")
elif runtime_health != "healthy" and http_release not in {"missing", runtime_release}:
    raise SystemExit("recovery CAS rejected later HTTP release marker")
observed_data_pair = (
    data_current, data_current_sha, data_previous, data_previous_sha,
)
if observed_data_pair not in allowed_data_pairs[phase]:
    raise SystemExit("recovery CAS rejected mixed data tuple outside the journal phase")
PY
}

recover_failed_action() {
  local recovery_ok=1
  revalidate_rollback_locks || return 1
  cleanup_rollback_verifier_residue || return 1
  if ! assert_dual_recovery_phase_cas; then
    echo "CRITICAL: recovery CAS failed; no site/data pointer was changed and the journal is retained" >&2
    return 1
  fi
  if ! ensure_image_contract "${EXPECTED_CURRENT}" || \
     ! verify_image_dist_contract "${EXPECTED_CURRENT}"; then
    echo "CRITICAL: original release artifacts cannot be verified for recovery" >&2
    return 1
  fi
  echo "rollback action failed; restoring the pre-action insights state" >&2
  restore_original_data || recovery_ok=0
  restore_original_release || recovery_ok=0
  if [[ "${ACTION}" == "disable" && "${VHOST_REMOVED}" == "1" ]]; then
    restore_original_nginx || recovery_ok=0
  fi
  assert_shared_service_baseline || recovery_ok=0
  assert_expected_current_pointer || recovery_ok=0
  assert_expected_data_pointer || recovery_ok=0
  assert_original_data_previous_pointer || recovery_ok=0
  [[ "${recovery_ok}" == "1" ]]
}

assert_target_site_data_tuple() {
  if [[ ! -L "${DEPLOY_ROOT}/current" || \
        "$(readlink "${DEPLOY_ROOT}/current")" != "releases/${TARGET_RELEASE}" ]]; then
    echo "committed rollback site pointer does not match the target tuple" >&2
    return 1
  fi
  if [[ ! -L "${DATA_ROOT}/current" || \
        "$(readlink "${DATA_ROOT}/current")" != "releases/${TARGET_DATA_RELEASE}" ]]; then
    echo "committed rollback data pointer does not match the target tuple" >&2
    return 1
  fi
  if [[ ! -L "${DATA_ROOT}/previous" || \
        "$(readlink "${DATA_ROOT}/previous")" != "releases/${EXPECTED_CURRENT_DATA_RELEASE}" ]]; then
    echo "committed rollback data previous pointer does not match the source tuple" >&2
    return 1
  fi
  validate_release_payload "${TARGET_RELEASE}" || return 1
  validate_release_data_binding \
    "${TARGET_RELEASE}" \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" || return 1
  validate_and_bind_data_inventory to \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" \
    "${TARGET_RELEASE}" || return 1
  reverify_bound_release_artifacts || return 1
  ensure_image_contract "${TARGET_RELEASE}" || return 1
  verify_image_dist_contract "${TARGET_RELEASE}" || return 1
  wait_for_release_health "${TARGET_RELEASE}" || return 1
  verify_runtime_contract "${TARGET_RELEASE}" || return 1
  assert_shared_service_baseline || return 1
}

recover_persistent_rollback_journal_on_startup() {
  [[ "${DUAL_DATA_ROLLBACK}" == "1" ]] || return 0
  [[ -e "${ROLLBACK_JOURNAL}" || -L "${ROLLBACK_JOURNAL}" ]] || return 0

  read_and_validate_rollback_journal
  if [[ "${ORIGINAL_DATA_PREVIOUS_TARGET}" != "absent" && \
        ( ! -d "${DATA_ROOT}/${ORIGINAL_DATA_PREVIOUS_TARGET}" || \
          -L "${DATA_ROOT}/${ORIGINAL_DATA_PREVIOUS_TARGET}" ) ]]; then
    echo "journal original data previous target is missing or unsafe" >&2
    return 1
  fi
  if [[ "${ORIGINAL_DATA_PREVIOUS_TARGET}" != "absent" && \
        "$(safe_file_sha256 "${DATA_ROOT}/${ORIGINAL_DATA_PREVIOUS_TARGET}/public/data/reddit-voc/current-release.json")" != \
          "${ORIGINAL_DATA_PREVIOUS_SHA}" ]]; then
    echo "journal original data previous pointer checksum changed" >&2
    return 1
  fi

  journal_target_evidence="${TARGET_DEPLOYMENT_EVIDENCE}"
  journal_target_evidence_sha="${TARGET_DEPLOYMENT_EVIDENCE_SHA}"
  journal_evidence_mode="${ROLLBACK_EVIDENCE_MODE}"
  journal_acceptance_evidence="${ROLLBACK_ACCEPTANCE_EVIDENCE}"
  journal_acceptance_evidence_sha="${ROLLBACK_ACCEPTANCE_EVIDENCE_SHA}"
  journal_authorization_packet="${ROLLBACK_AUTHORIZATION_PACKET}"
  journal_authorization_packet_sha="${ROLLBACK_AUTHORIZATION_PACKET_SHA}"
  journal_authorization_permit="${ROLLBACK_AUTHORIZATION_PERMIT}"
  journal_authorization_permit_sha="${ROLLBACK_AUTHORIZATION_PERMIT_SHA}"
  journal_production_baseline="${ROLLBACK_PRODUCTION_BASELINE}"
  journal_production_baseline_sha="${ROLLBACK_PRODUCTION_BASELINE_SHA}"
  journal_from_release_manifest_sha="${FROM_RELEASE_MANIFEST_SHA256}"
  journal_from_release_sha256sums_sha="${FROM_RELEASE_SHA256SUMS_SHA256}"
  journal_to_release_manifest_sha="${TO_RELEASE_MANIFEST_SHA256}"
  journal_to_release_sha256sums_sha="${TO_RELEASE_SHA256SUMS_SHA256}"
  validate_release_payload "${EXPECTED_CURRENT}"
  validate_release_data_binding \
    "${EXPECTED_CURRENT}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}"
  validate_and_bind_data_inventory from \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${EXPECTED_CURRENT}"
  validate_release_payload "${TARGET_RELEASE}"
  validate_release_data_binding \
    "${TARGET_RELEASE}" \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}"
  validate_and_bind_data_inventory to \
    "${TARGET_DATA_RELEASE}" \
    "${TARGET_DATA_POINTER_SHA}" \
    "${TARGET_RELEASE}"
  validate_target_deployment_evidence "${TARGET_RELEASE}"
  if [[ "${ROLLBACK_EVIDENCE_MODE}|${TARGET_DEPLOYMENT_EVIDENCE}|${TARGET_DEPLOYMENT_EVIDENCE_SHA}|${ROLLBACK_ACCEPTANCE_EVIDENCE}|${ROLLBACK_ACCEPTANCE_EVIDENCE_SHA}|${ROLLBACK_AUTHORIZATION_PACKET}|${ROLLBACK_AUTHORIZATION_PACKET_SHA}|${ROLLBACK_AUTHORIZATION_PERMIT}|${ROLLBACK_AUTHORIZATION_PERMIT_SHA}|${ROLLBACK_PRODUCTION_BASELINE}|${ROLLBACK_PRODUCTION_BASELINE_SHA}|${FROM_RELEASE_MANIFEST_SHA256}|${FROM_RELEASE_SHA256SUMS_SHA256}|${TO_RELEASE_MANIFEST_SHA256}|${TO_RELEASE_SHA256SUMS_SHA256}" != \
        "${journal_evidence_mode}|${journal_target_evidence}|${journal_target_evidence_sha}|${journal_acceptance_evidence}|${journal_acceptance_evidence_sha}|${journal_authorization_packet}|${journal_authorization_packet_sha}|${journal_authorization_permit}|${journal_authorization_permit_sha}|${journal_production_baseline}|${journal_production_baseline_sha}|${journal_from_release_manifest_sha}|${journal_from_release_sha256sums_sha}|${journal_to_release_manifest_sha}|${journal_to_release_sha256sums_sha}" ]]; then
    echo "journal rollback transaction evidence binding changed" >&2
    return 1
  fi
  reverify_bound_release_artifacts || return 1

  if [[ -e "${ROLLBACK_RECEIPT_FILE}" || -L "${ROLLBACK_RECEIPT_FILE}" ]]; then
    if [[ "${JOURNAL_PHASE}" != "site_switched" && "${JOURNAL_PHASE}" != "complete" ]]; then
      echo "rollback receipt exists before the journal commit phase; refusing recovery" >&2
      return 1
    fi
    if ! assert_dual_recovery_phase_cas; then
      echo "committed journal recovery CAS failed before receipt verification" >&2
      return 1
    fi
    ROLLBACK_RECEIPT_SHA="$(validate_dual_rollback_receipt "${ROLLBACK_RECEIPT_SHA}")"
    assert_target_site_data_tuple
    if [[ "${JOURNAL_PHASE}" != "complete" ]]; then
      write_rollback_journal_phase complete "${ROLLBACK_RECEIPT_SHA}"
    fi
    clear_rollback_journal
    ACTION_STARTED=0
    ACTION_SUCCEEDED=1
    trap - EXIT
    cleanup_transient
    printf '%s\n' \
      "action=release" \
      "recovered_committed_journal=true" \
      "release_sha=${TARGET_RELEASE}" \
      "data_release=${TARGET_DATA_RELEASE}" \
      "evidence=${ROLLBACK_RECEIPT_FILE}" \
      "backend_health_preserved=true"
    exit 0
  fi

  if [[ "${JOURNAL_PHASE}" == "complete" ]]; then
    echo "complete rollback journal has no immutable receipt; refusing ambiguous recovery" >&2
    return 1
  fi

  validate_release_payload "${EXPECTED_CURRENT}"
  validate_release_data_binding \
    "${EXPECTED_CURRENT}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}"
  validate_and_bind_data_inventory from \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
    "${EXPECTED_CURRENT}"
  ACTION_STARTED=1
  CURRENT_CHANGED=1
  DATA_CURRENT_CHANGED=1
  DATA_PREVIOUS_CHANGED=1
  if ! recover_failed_action; then
    echo "CRITICAL: persistent journal recovery did not restore the old site/data tuple" >&2
    return 1
  fi
  clear_rollback_journal
  ACTION_STARTED=0
  echo "recovered incomplete dual-resource rollback to the exact old site/data tuple; retry explicitly" >&2
  exit 75
}

on_exit() {
  local status="$1"
  local receipt_commit_sha=""
  local receipt_state="absent"
  trap - EXIT
  set +e
  if [[ "${status}" != "0" && "${ACTION_STARTED}" == "1" && "${ACTION_SUCCEEDED}" != "1" ]]; then
    if [[ "${DUAL_DATA_ROLLBACK}" == "1" && -n "${ROLLBACK_RECEIPT_FILE}" && \
          ( -e "${ROLLBACK_RECEIPT_FILE}" || -L "${ROLLBACK_RECEIPT_FILE}" ) ]]; then
      receipt_state="ambiguous"
      if assert_dual_recovery_phase_cas && \
         receipt_commit_sha="$(validate_dual_rollback_receipt "${ROLLBACK_RECEIPT_SHA}")" && \
         assert_target_site_data_tuple; then
        receipt_state="committed"
        ACTION_SUCCEEDED=1
        ROLLBACK_RECEIPT_SHA="${receipt_commit_sha}"
        if [[ "${JOURNAL_PHASE:-}" == "site_switched" ]]; then
          write_rollback_journal_phase complete "${ROLLBACK_RECEIPT_SHA}" || \
            echo "CRITICAL: receipt is committed but the complete journal phase could not be persisted" >&2
        fi
        echo "dual-resource rollback receipt is committed; preserving the verified target site/data tuple" >&2
      else
        echo "CRITICAL: rollback receipt exists but its target tuple cannot be verified; refusing automatic mutation" >&2
      fi
    fi
    if [[ "${receipt_state}" == "absent" ]] && recover_failed_action; then
      if [[ "${JOURNAL_ACTIVE}" == "1" ]] && ! clear_rollback_journal; then
        echo "CRITICAL: recovered old site/data tuple but could not clear the rollback journal" >&2
      fi
    elif [[ "${receipt_state}" == "absent" ]]; then
      echo "CRITICAL: automatic recovery did not complete; inspect ${DEPLOY_ROOT} and shared Nginx before retrying" >&2
    fi
  fi
  cleanup_transient
  exit "${status}"
}
trap 'on_exit $?' EXIT

recover_persistent_rollback_journal_on_startup

assert_expected_current_pointer
validate_release_payload "${EXPECTED_CURRENT}"
if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
  validate_release_data_binding \
    "${EXPECTED_CURRENT}" \
    "${EXPECTED_CURRENT_DATA_RELEASE}" \
    "${EXPECTED_CURRENT_DATA_POINTER_SHA}"
  assert_expected_data_pointer
elif [[ "${ACTION}" == "release" ]]; then
  assert_site_only_release_compatible "${EXPECTED_CURRENT}"
fi
IFS=$'\t' read -r current_collection_integrated current_collection_fully_hydrated \
  < <(read_release_collection_status "${EXPECTED_CURRENT}")
if [[ "${DUAL_DATA_ROLLBACK}" != "1" ]]; then
  ensure_image_contract "${EXPECTED_CURRENT}"
  verify_image_dist_contract "${EXPECTED_CURRENT}"
  wait_for_release_health "${EXPECTED_CURRENT}"
  verify_runtime_contract "${EXPECTED_CURRENT}"
fi

if [[ "${ACTION}" == "release" ]]; then
  validate_release_payload "${TARGET_RELEASE}"
  if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
    validate_release_data_binding \
      "${TARGET_RELEASE}" \
      "${TARGET_DATA_RELEASE}" \
      "${TARGET_DATA_POINTER_SHA}"
    validate_and_bind_data_inventory to \
      "${TARGET_DATA_RELEASE}" \
      "${TARGET_DATA_POINTER_SHA}" \
      "${TARGET_RELEASE}"
    if [[ -e "${DATA_ROOT}/previous" || -L "${DATA_ROOT}/previous" ]]; then
      if [[ ! -L "${DATA_ROOT}/previous" ]]; then
        echo "data previous pointer is unsafe" >&2
        exit 1
      fi
      ORIGINAL_DATA_PREVIOUS_TARGET="$(readlink "${DATA_ROOT}/previous")"
      if [[ ! "${ORIGINAL_DATA_PREVIOUS_TARGET}" =~ ^releases/reddit_voc_release_[a-z0-9_-]+$ || \
            ! -d "${DATA_ROOT}/${ORIGINAL_DATA_PREVIOUS_TARGET}" || \
            -L "${DATA_ROOT}/${ORIGINAL_DATA_PREVIOUS_TARGET}" ]]; then
        echo "data previous pointer target is invalid" >&2
        exit 1
      fi
      original_previous_pointer="${DATA_ROOT}/${ORIGINAL_DATA_PREVIOUS_TARGET}/public/data/reddit-voc/current-release.json"
      if [[ ! -f "${original_previous_pointer}" || -L "${original_previous_pointer}" ]]; then
        echo "data previous release pointer is missing or unsafe" >&2
        exit 1
      fi
      ORIGINAL_DATA_PREVIOUS_SHA="$(safe_file_sha256 "${original_previous_pointer}")"
    fi
  else
    assert_site_only_release_compatible "${TARGET_RELEASE}"
  fi
  IFS=$'\t' read -r target_collection_integrated target_collection_fully_hydrated \
    < <(read_release_collection_status "${TARGET_RELEASE}")
  validate_target_deployment_evidence "${TARGET_RELEASE}"
  if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
    reverify_bound_release_artifacts
    ensure_image_contract "${EXPECTED_CURRENT}"
    verify_image_dist_contract "${EXPECTED_CURRENT}"
    wait_for_release_health "${EXPECTED_CURRENT}"
    verify_runtime_contract "${EXPECTED_CURRENT}"
    reverify_bound_release_artifacts
  fi
  ensure_image_contract "${TARGET_RELEASE}"
  verify_image_dist_contract "${TARGET_RELEASE}"

  assert_safe_window
  assert_expected_current_pointer
  assert_expected_data_pointer
  assert_shared_service_baseline
  if [[ "$(sha256sum "${NGINX_CONF}" | awk '{print $1}')" != "${nginx_before_sha}" ]]; then
    echo "shared Nginx content changed before release rollback" >&2
    exit 1
  fi

  if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
    ROLLBACK_STARTED_AT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    receipt_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    ROLLBACK_RECEIPT_FILE="${EVIDENCE_ROOT}/rollback-release-${receipt_stamp}-${EXPECTED_CURRENT}-to-${TARGET_RELEASE}.json"
    if [[ -e "${ROLLBACK_RECEIPT_FILE}" || -L "${ROLLBACK_RECEIPT_FILE}" ]]; then
      echo "dual-resource rollback receipt path already exists" >&2
      exit 1
    fi
    write_rollback_journal_phase prepared
    reverify_bound_release_artifacts
  fi

  ACTION_STARTED=1
  if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
    reverify_bound_release_artifacts
    if [[ "${ORIGINAL_DATA_PREVIOUS_TARGET}" != \
          "releases/${EXPECTED_CURRENT_DATA_RELEASE}" ]]; then
      cas_replace_symlink \
        "${DATA_ROOT}/previous" \
        "${ORIGINAL_DATA_PREVIOUS_TARGET}" \
        "releases/${EXPECTED_CURRENT_DATA_RELEASE}" \
        "switch-data-previous"
      DATA_PREVIOUS_CHANGED=1
    fi
    reverify_bound_release_artifacts
    cas_replace_symlink \
      "${DATA_ROOT}/current" \
      "releases/${EXPECTED_CURRENT_DATA_RELEASE}" \
      "releases/${TARGET_DATA_RELEASE}" \
      "switch-data-current"
    DATA_CURRENT_CHANGED=1
    if [[ "$(readlink "${DATA_ROOT}/current")" != "releases/${TARGET_DATA_RELEASE}" ]]; then
      echo "target data current pointer switch failed" >&2
      exit 1
    fi
    validate_and_bind_data_inventory to \
      "${TARGET_DATA_RELEASE}" \
      "${TARGET_DATA_POINTER_SHA}" \
      "${TARGET_RELEASE}"
    if [[ ! -L "${DATA_ROOT}/previous" || \
          "$(readlink "${DATA_ROOT}/previous")" != "releases/${EXPECTED_CURRENT_DATA_RELEASE}" ]]; then
      echo "data previous pointer switch failed" >&2
      exit 1
    fi
    write_rollback_journal_phase data_switched
    reverify_bound_release_artifacts
  fi
  prepare_release_runtime_snapshot "${TARGET_RELEASE}"
  verify_runtime_compose_contract "${TARGET_RELEASE}"
  target_snapshot_dir="$(runtime_snapshot_directory "${TARGET_RELEASE}")"
  target_compose_path="${target_snapshot_dir}/compose.yaml"
  target_compose_override="${target_snapshot_dir}/compose-image-id.yaml"
  RELEASE_SHA="${TARGET_RELEASE}" \
  INSIGHTS_BIND_ADDRESS="${BIND_ADDRESS}" \
  INSIGHTS_PORT="${PORT}" \
    REDDIT_VOC_DATA_ROOT="${DATA_ROOT}" \
      docker compose -p "${COMPOSE_PROJECT}" \
        -f "${target_compose_path}" -f "${target_compose_override}" \
        up -d --pull never --no-build --no-deps web
  if ! wait_for_release_health "${TARGET_RELEASE}"; then
    docker logs --tail 120 "${CONTAINER_NAME}" >&2 || true
    echo "target release did not become healthy" >&2
    exit 1
  fi
  verify_runtime_contract "${TARGET_RELEASE}"
  if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
    [[ "$(readlink "${DATA_ROOT}/current")" == "releases/${TARGET_DATA_RELEASE}" ]] || {
      echo "data current pointer changed during release rollback" >&2
      exit 1
    }
    validate_and_bind_data_inventory to \
      "${TARGET_DATA_RELEASE}" \
      "${TARGET_DATA_POINTER_SHA}" \
      "${TARGET_RELEASE}"
  fi

  reverify_bound_release_artifacts
  cas_replace_symlink \
    "${DEPLOY_ROOT}/current" \
    "releases/${EXPECTED_CURRENT}" \
    "releases/${TARGET_RELEASE}" \
    "switch-site-current"
  CURRENT_CHANGED=1

  assert_shared_service_baseline
  if [[ "$(sha256sum "${NGINX_CONF}" | awk '{print $1}')" != "${nginx_before_sha}" ]]; then
    echo "shared Nginx content changed during release rollback" >&2
    exit 1
  fi
  verify_runtime_contract "${TARGET_RELEASE}"

  if [[ "${DUAL_DATA_ROLLBACK}" == "1" ]]; then
    assert_target_site_data_tuple
    revalidate_rollback_locks
    assert_candidate_transaction_quiet
    verify_runtime_snapshot "${TARGET_RELEASE}"
    write_rollback_journal_phase site_switched
    revalidate_bound_rollback_evidence
    assert_shared_service_baseline
    assert_candidate_transaction_quiet
    EVIDENCE_FILE="${ROLLBACK_RECEIPT_FILE}"
    ROLLBACK_RECEIPT_SHA="$(write_dual_rollback_receipt)"
    validated_receipt_sha="$(validate_dual_rollback_receipt "${ROLLBACK_RECEIPT_SHA}")"
    if [[ "${validated_receipt_sha}" != "${ROLLBACK_RECEIPT_SHA}" ]]; then
      echo "dual-resource rollback receipt terminal validation changed" >&2
      exit 1
    fi
    revalidate_rollback_locks
    assert_candidate_transaction_quiet
    assert_target_site_data_tuple
    write_rollback_journal_phase complete "${ROLLBACK_RECEIPT_SHA}"
    revalidate_rollback_locks
    assert_candidate_transaction_quiet
    clear_rollback_journal
    ACTION_SUCCEEDED=1
    evidence_file="${ROLLBACK_RECEIPT_FILE}"
  else
    evidence_file="${EVIDENCE_ROOT}/rollback-release-$(date -u +%Y%m%dT%H%M%SZ)-${EXPECTED_CURRENT}-to-${TARGET_RELEASE}.txt"
    if [[ -e "${evidence_file}" || -L "${evidence_file}" ]]; then
      echo "rollback evidence path already exists" >&2
      exit 1
    fi
    EVIDENCE_FILE="${evidence_file}"
    EVIDENCE_TMP="${evidence_file}.tmp.$$"
    {
      echo "evidence_grade=L4-authorized-live"
      echo "action=release"
      echo "expected_current=${EXPECTED_CURRENT}"
      echo "target_release=${TARGET_RELEASE}"
      echo "target_deployment_evidence=${TARGET_DEPLOYMENT_EVIDENCE}"
      echo "target_payload_checksums_verified=true"
      echo "target_image_contract_verified=true"
      echo "target_runtime_contract_verified=true"
      echo "target_release_marker_verified=true"
      echo "current_pointer_atomic=true"
      echo "current_pointer=releases/${TARGET_RELEASE}"
      echo "data_rollback=false"
      echo "automatic_failure_recovery_armed=true"
      echo "collector_id_unchanged=true"
      echo "collector_restart_count=${collector_restart}"
      echo "translation_id_unchanged=true"
      echo "translation_restart_count=${translation_restart}"
      echo "nginx_id_unchanged=true"
      echo "nginx_restart_count=${nginx_restart}"
      echo "nginx_sha=${nginx_before_sha}"
      echo "nginx_unchanged=true"
      echo "cron_unchanged=true"
      echo "provider_call=false"
      echo "database_write=false"
      echo "live_send=false"
      echo "webhook_send=false"
      echo "latest_collection_integrated=${target_collection_integrated}"
      echo "latest_collection_fully_hydrated=${target_collection_fully_hydrated}"
    } > "${EVIDENCE_TMP}"
    mv "${EVIDENCE_TMP}" "${evidence_file}"
    EVIDENCE_TMP=""
    ACTION_SUCCEEDED=1
  fi
  trap - EXIT
  cleanup_transient
  printf '%s\n' \
    "action=release" \
    "previous_release=${EXPECTED_CURRENT}" \
    "release_sha=${TARGET_RELEASE}" \
    "data_rollback=$([[ "${DUAL_DATA_ROLLBACK}" == "1" ]] && echo true || echo false)" \
    "data_release=${TARGET_DATA_RELEASE:-unchanged}" \
    "latest_collection_integrated=${target_collection_integrated}" \
    "latest_collection_fully_hydrated=${target_collection_fully_hydrated}" \
    "evidence=${evidence_file}" \
    "backend_health_preserved=true"
  exit 0
fi

has_marker_start=0
has_marker_end=0
grep -Fq "${MARKER_START}" "${NGINX_CONF}" && has_marker_start=1
grep -Fq "${MARKER_END}" "${NGINX_CONF}" && has_marker_end=1
if [[ "${has_marker_start}" != "${has_marker_end}" ]]; then
  echo "managed Nginx marker is incomplete" >&2
  exit 1
fi
if [[ "${has_marker_start}" == "1" ]]; then
  VHOST_WAS_PRESENT=1
  BACKUP_DIR="/opt/ai-video-backups/reddit-voc-insights-disable-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  if [[ -e "${BACKUP_DIR}" || -L "${BACKUP_DIR}" ]]; then
    echo "Nginx backup path already exists" >&2
    exit 1
  fi
  sudo mkdir "${BACKUP_DIR}"
  sudo cp "${NGINX_CONF}" "${BACKUP_DIR}/nginx.conf"
  backup_sha="$(sudo sha256sum "${BACKUP_DIR}/nginx.conf" | awk '{print $1}')"
  if [[ "${backup_sha}" != "${nginx_before_sha}" ]]; then
    echo "shared Nginx backup checksum mismatch" >&2
    exit 1
  fi
else
  backup_sha="not_required"
fi

assert_safe_window
assert_expected_current_pointer
assert_shared_service_baseline
if [[ "$(sha256sum "${NGINX_CONF}" | awk '{print $1}')" != "${nginx_before_sha}" ]]; then
  echo "shared Nginx content changed before disable" >&2
  exit 1
fi

ACTION_STARTED=1
if [[ "${VHOST_WAS_PRESENT}" == "1" ]]; then
  VHOST_REMOVED=1
  sudo python3 "${PATCH_SCRIPT}" \
    --conf "${NGINX_CONF}" \
    --mode remove \
    --domain "${DOMAIN}" \
    --upstream "${BIND_ADDRESS}:${PORT}"
  if grep -Fq "${MARKER_START}" "${NGINX_CONF}" || grep -Fq "${MARKER_END}" "${NGINX_CONF}"; then
    echo "managed insights vhost was not fully removed" >&2
    exit 1
  fi
  nginx_after_remove_sha="$(sha256sum "${NGINX_CONF}" | awk '{print $1}')"
  nginx_container_after_remove_sha="$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')"
  if [[ "$(stat -c '%i' "${NGINX_CONF}")" != "${nginx_before_inode}" || "${nginx_after_remove_sha}" != "${nginx_container_after_remove_sha}" || "${nginx_after_remove_sha}" == "${nginx_before_sha}" ]]; then
    echo "Nginx vhost removal did not satisfy the bind-mount mutation contract" >&2
    exit 1
  fi
  docker exec "${NGINX_CONTAINER}" nginx -t >/dev/null
  docker exec "${NGINX_CONTAINER}" nginx -s reload
else
  nginx_after_remove_sha="${nginx_before_sha}"
fi

curl -fsS "${COLLECTOR_PUBLIC_URL}" >/dev/null
curl -fsS http://127.0.0.1:18337/api/health >/dev/null
if [[ "$(docker inspect -f '{{.Id}}' "${NGINX_CONTAINER}")" != "${nginx_id}" || \
      "$(docker inspect -f '{{.RestartCount}}' "${NGINX_CONTAINER}")" != "${nginx_restart}" ]]; then
  echo "shared Nginx container changed during vhost removal" >&2
  exit 1
fi

assert_safe_window
assert_expected_current_pointer
if docker ps --format '{{.Names}}' | grep -q '^reddit_voc_site_app-run-' || \
   [[ "$(docker inspect -f '{{.Id}}' reddit_voc_site_app)" != "${collector_id}" ]] || \
   [[ "$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)" != "${collector_restart}" ]] || \
   [[ "$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)" != "${translation_id}" ]] || \
   [[ "$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)" != "${translation_restart}" ]] || \
   [[ "$(sudo sha256sum "${CRON_FILE}" | awk '{print $1}')" != "${cron_sha}" ]]; then
  echo "production baseline changed before isolated container disable" >&2
  exit 1
fi

verify_runtime_compose_contract "${EXPECTED_CURRENT}"
RELEASE_SHA="${EXPECTED_CURRENT}" \
INSIGHTS_BIND_ADDRESS="${BIND_ADDRESS}" \
INSIGHTS_PORT="${PORT}" \
  REDDIT_VOC_DATA_ROOT="${DATA_ROOT}" \
    docker compose -p "${COMPOSE_PROJECT}" \
      -f "$(runtime_snapshot_directory "${EXPECTED_CURRENT}")/compose.yaml" \
      -f "$(runtime_snapshot_directory "${EXPECTED_CURRENT}")/compose-image-id.yaml" \
      down

if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  echo "insights container still exists after disable" >&2
  exit 1
fi
if ss -H -ltn | awk '{print $4}' | grep -qE "(^|:)${PORT}$"; then
  echo "insights listener still exists after disable" >&2
  exit 1
fi

host_nginx_after_sha="$(sha256sum "${NGINX_CONF}" | awk '{print $1}')"
container_nginx_after_sha="$(docker exec "${NGINX_CONTAINER}" sha256sum /etc/nginx/nginx.conf | awk '{print $1}')"
if [[ "${host_nginx_after_sha}" != "${nginx_after_remove_sha}" || "${container_nginx_after_sha}" != "${nginx_after_remove_sha}" || \
      "$(stat -c '%i' "${NGINX_CONF}")" != "${nginx_before_inode}" ]]; then
  echo "shared Nginx configuration changed unexpectedly after container disable" >&2
  exit 1
fi
assert_shared_service_baseline

evidence_file="${EVIDENCE_ROOT}/rollback-disable-$(date -u +%Y%m%dT%H%M%SZ)-${EXPECTED_CURRENT}.txt"
if [[ -e "${evidence_file}" || -L "${evidence_file}" ]]; then
  echo "disable evidence path already exists" >&2
  exit 1
fi
EVIDENCE_FILE="${evidence_file}"
EVIDENCE_TMP="${evidence_file}.tmp.$$"
{
  echo "evidence_grade=L4-authorized-live"
  echo "action=disable"
  echo "expected_current=${EXPECTED_CURRENT}"
  echo "vhost_was_present=$([[ "${VHOST_WAS_PRESENT}" == "1" ]] && echo true || echo false)"
  echo "vhost_removed_before_container=true"
  echo "container_absent=true"
  echo "listener_absent=true"
  echo "current_pointer=absent"
  echo "current_pointer_change_atomic=true"
  echo "automatic_failure_recovery_armed=true"
  echo "nginx_before_sha=${nginx_before_sha}"
  echo "nginx_after_sha=${nginx_after_remove_sha}"
  echo "nginx_backup_dir=${BACKUP_DIR:-not_required}"
  echo "nginx_backup_sha=${backup_sha}"
  echo "nginx_inode_preserved=true"
  echo "nginx_container_sha_aligned=true"
  echo "nginx_reload=$([[ "${VHOST_WAS_PRESENT}" == "1" ]] && echo true || echo false)"
  echo "collector_id_unchanged=true"
  echo "collector_restart_count=${collector_restart}"
  echo "translation_id_unchanged=true"
  echo "translation_restart_count=${translation_restart}"
  echo "nginx_id_unchanged=true"
  echo "nginx_restart_count=${nginx_restart}"
  echo "cron_unchanged=true"
  echo "provider_call=false"
  echo "database_write=false"
  echo "live_send=false"
  echo "webhook_send=false"
  echo "latest_collection_integrated=false"
  echo "latest_collection_fully_hydrated=false"
  echo "disabled_release_latest_collection_integrated=${current_collection_integrated}"
  echo "disabled_release_latest_collection_fully_hydrated=${current_collection_fully_hydrated}"
} > "${EVIDENCE_TMP}"

assert_expected_current_pointer
cas_remove_symlink \
  "${DEPLOY_ROOT}/current" \
  "releases/${EXPECTED_CURRENT}" \
  "disable-site-current"
CURRENT_CHANGED=1
mv "${EVIDENCE_TMP}" "${evidence_file}"
EVIDENCE_TMP=""
ACTION_SUCCEEDED=1
trap - EXIT
cleanup_transient
printf '%s\n' \
  "action=disable" \
  "disabled_release=${EXPECTED_CURRENT}" \
  "disabled_release_latest_collection_integrated=${current_collection_integrated}" \
  "disabled_release_latest_collection_fully_hydrated=${current_collection_fully_hydrated}" \
  "evidence=${evidence_file}" \
  "backend_health_preserved=true"
