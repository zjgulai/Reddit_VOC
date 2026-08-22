#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage:
  rollback_insights_tencent.sh release \
    --expected-current <site-sha256> --target-release <site-sha256> \
    --expected-current-data-release <id> \
    --expected-current-data-pointer-sha <sha256> \
    --target-data-release <id> --target-data-pointer-sha <sha256> \
    --promotion-receipt <remote-absolute-path> \
    --promotion-receipt-sha <sha256> \
    --authorization-packet <local-absolute-path> \
    --authorization-packet-sha <sha256> \
    --authorization-permit <local-absolute-path> \
    --authorization-permit-sha <sha256> \
    --production-baseline <local-absolute-path> \
    --production-baseline-sha <sha256>

Only an exact, dual-resource site-and-data release rollback is supported.
The historical `disable` and site-only rollback paths are intentionally rejected.
EOF
}

fail() {
  echo "$*" >&2
  exit 1
}

if [[ "$#" -lt 1 ]]; then
  usage
  exit 1
fi

ACTION="$1"
shift
if [[ "${ACTION}" != "release" ]]; then
  fail "only controlled dual-resource release rollback is supported; disable is forbidden"
fi

EXPECTED_CURRENT=""
TARGET_RELEASE=""
EXPECTED_CURRENT_DATA_RELEASE=""
EXPECTED_CURRENT_DATA_POINTER_SHA=""
TARGET_DATA_RELEASE=""
TARGET_DATA_POINTER_SHA=""
PROMOTION_RECEIPT=""
PROMOTION_RECEIPT_SHA=""
AUTHORIZATION_PACKET=""
AUTHORIZATION_PACKET_SHA=""
AUTHORIZATION_PERMIT=""
AUTHORIZATION_PERMIT_SHA=""
PRODUCTION_BASELINE=""
PRODUCTION_BASELINE_SHA=""
SEEN_ARGUMENTS="|"

require_once() {
  local name="$1"
  if [[ "${SEEN_ARGUMENTS}" == *"|${name}|"* ]]; then
    fail "duplicate rollback argument is forbidden: --${name}"
  fi
  SEEN_ARGUMENTS+="${name}|"
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --expected-current)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once expected-current
      EXPECTED_CURRENT="$2"
      shift 2
      ;;
    --target-release)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once target-release
      TARGET_RELEASE="$2"
      shift 2
      ;;
    --expected-current-data-release)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once expected-current-data-release
      EXPECTED_CURRENT_DATA_RELEASE="$2"
      shift 2
      ;;
    --expected-current-data-pointer-sha)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once expected-current-data-pointer-sha
      EXPECTED_CURRENT_DATA_POINTER_SHA="$2"
      shift 2
      ;;
    --target-data-release)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once target-data-release
      TARGET_DATA_RELEASE="$2"
      shift 2
      ;;
    --target-data-pointer-sha)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once target-data-pointer-sha
      TARGET_DATA_POINTER_SHA="$2"
      shift 2
      ;;
    --promotion-receipt)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once promotion-receipt
      PROMOTION_RECEIPT="$2"
      shift 2
      ;;
    --promotion-receipt-sha|--promotion-receipt-sha256)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once promotion-receipt-sha
      PROMOTION_RECEIPT_SHA="$2"
      shift 2
      ;;
    --authorization-packet)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once authorization-packet
      AUTHORIZATION_PACKET="$2"
      shift 2
      ;;
    --authorization-packet-sha|--authorization-packet-sha256)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once authorization-packet-sha
      AUTHORIZATION_PACKET_SHA="$2"
      shift 2
      ;;
    --authorization-permit)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once authorization-permit
      AUTHORIZATION_PERMIT="$2"
      shift 2
      ;;
    --authorization-permit-sha|--authorization-permit-sha256)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once authorization-permit-sha
      AUTHORIZATION_PERMIT_SHA="$2"
      shift 2
      ;;
    --production-baseline)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once production-baseline
      PRODUCTION_BASELINE="$2"
      shift 2
      ;;
    --production-baseline-sha|--production-baseline-sha256)
      [[ "$#" -ge 2 ]] || { usage; exit 1; }
      require_once production-baseline-sha
      PRODUCTION_BASELINE_SHA="$2"
      shift 2
      ;;
    *)
      usage
      exit 1
      ;;
  esac
done

SHA_PATTERN='^[a-f0-9]{64}$'
for binding in \
  "expected current release:${EXPECTED_CURRENT}" \
  "target release:${TARGET_RELEASE}" \
  "expected current data pointer:${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
  "target data pointer:${TARGET_DATA_POINTER_SHA}" \
  "promotion receipt:${PROMOTION_RECEIPT_SHA}" \
  "authorization packet:${AUTHORIZATION_PACKET_SHA}" \
  "authorization permit:${AUTHORIZATION_PERMIT_SHA}" \
  "production baseline:${PRODUCTION_BASELINE_SHA}"; do
  label="${binding%%:*}"
  value="${binding#*:}"
  [[ "${value}" =~ ${SHA_PATTERN} ]] || fail "${label} must be a full lowercase SHA-256"
done
if [[ "${EXPECTED_CURRENT}" == "${TARGET_RELEASE}" ]]; then
  fail "target release must differ from expected current release"
fi
if [[ "${EXPECTED_CURRENT_DATA_POINTER_SHA}" == "${TARGET_DATA_POINTER_SHA}" ]]; then
  fail "target data pointer must differ from expected current data pointer"
fi
if [[ ! "${EXPECTED_CURRENT_DATA_RELEASE}" =~ ^reddit_voc_release_[a-z0-9_-]+$ || \
      ! "${TARGET_DATA_RELEASE}" =~ ^reddit_voc_release_[a-z0-9_-]+$ || \
      "${EXPECTED_CURRENT_DATA_RELEASE}" == "${TARGET_DATA_RELEASE}" ]]; then
  fail "complete, distinct Reddit VOC data release bindings are required"
fi

EVIDENCE_ROOT="/opt/reddit-voc-insights-site/evidence"
if [[ ! "${PROMOTION_RECEIPT}" =~ ^${EVIDENCE_ROOT}/[A-Za-z0-9._-]+\.json$ ]]; then
  fail "promotion receipt must be one exact JSON path under ${EVIDENCE_ROOT}"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_KEY="${SSH_KEY:-${PROJECT_ROOT}/DDDD.pem}"
REMOTE="${REMOTE:-ubuntu@101.34.52.232}"
KNOWN_HOSTS="${KNOWN_HOSTS:-${HOME}/.ssh/known_hosts}"
REMOTE_HOST="101.34.52.232"
REMOTE_RUNNER_SOURCE="${PROJECT_ROOT}/scripts/remote_rollback_insights.sh"
PATCHER_SOURCE="${PROJECT_ROOT}/scripts/patch_insights_nginx.py"
STAGER_SOURCE="${PROJECT_ROOT}/scripts/stage_reddit_rollback_evidence.py"

if [[ "${REMOTE}" != "ubuntu@${REMOTE_HOST}" ]]; then
  fail "rollback target must remain ubuntu@${REMOTE_HOST}"
fi

validate_local_evidence() {
  local path="$1"
  local digest="$2"
  local label="$3"
  python3 "${STAGER_SOURCE}" validate \
    --path "${path}" \
    --expected-sha "${digest}" \
    --label "${label}" >/dev/null
}

validate_local_evidence \
  "${AUTHORIZATION_PACKET}" "${AUTHORIZATION_PACKET_SHA}" authorization_packet
validate_local_evidence \
  "${AUTHORIZATION_PERMIT}" "${AUTHORIZATION_PERMIT_SHA}" authorization_permit
validate_local_evidence \
  "${PRODUCTION_BASELINE}" "${PRODUCTION_BASELINE_SHA}" production_baseline

if [[ "${AUTHORIZATION_PACKET}" == "${AUTHORIZATION_PERMIT}" || \
      "${AUTHORIZATION_PACKET}" == "${PRODUCTION_BASELINE}" || \
      "${AUTHORIZATION_PERMIT}" == "${PRODUCTION_BASELINE}" ]]; then
  fail "packet, permit, and baseline must be three distinct local files"
fi
if [[ "${AUTHORIZATION_PACKET_SHA}" == "${AUTHORIZATION_PERMIT_SHA}" || \
      "${AUTHORIZATION_PACKET_SHA}" == "${PRODUCTION_BASELINE_SHA}" || \
      "${AUTHORIZATION_PERMIT_SHA}" == "${PRODUCTION_BASELINE_SHA}" ]]; then
  fail "packet, permit, and baseline must have distinct content digests"
fi

for local_file in \
  "${SSH_KEY}" "${REMOTE_RUNNER_SOURCE}" "${PATCHER_SOURCE}" "${STAGER_SOURCE}"; do
  if [[ ! -f "${local_file}" || -L "${local_file}" ]]; then
    fail "required local file is missing or is a symlink: ${local_file}"
  fi
done
SSH_KEY_MODE="$(
  python3 - "${SSH_KEY}" <<'PY'
import os
import stat
import sys

metadata = os.lstat(sys.argv[1])
if not stat.S_ISREG(metadata.st_mode):
    raise SystemExit(1)
print(f"{stat.S_IMODE(metadata.st_mode):03o}")
PY
)" || fail "SSH key must have mode 600"
if [[ "${SSH_KEY_MODE}" != "600" ]]; then
  fail "SSH key must have mode 600"
fi
if [[ ! -f "${KNOWN_HOSTS}" || -L "${KNOWN_HOSTS}" ]] || \
   ! ssh-keygen -F "${REMOTE_HOST}" -f "${KNOWN_HOSTS}" >/dev/null; then
  fail "verified SSH host key entry is missing for ${REMOTE_HOST}"
fi

RUNNER_SHA="$(python3 "${STAGER_SOURCE}" hash-runtime --path "${REMOTE_RUNNER_SOURCE}")"
PATCHER_SHA="$(python3 "${STAGER_SOURCE}" hash-runtime --path "${PATCHER_SOURCE}")"
STAGER_SHA="$(python3 "${STAGER_SOURCE}" hash-runtime --path "${STAGER_SOURCE}")"
for digest in "${RUNNER_SHA}" "${PATCHER_SHA}" "${STAGER_SHA}"; do
  [[ "${digest}" =~ ${SHA_PATTERN} ]] || fail "local runtime hashing failed"
done
RUNTIME_BUNDLE_SHA="$(
  python3 "${STAGER_SOURCE}" bundle-id \
    --runner-sha "${RUNNER_SHA}" \
    --patcher-sha "${PATCHER_SHA}" \
    --stager-sha "${STAGER_SHA}"
)"
[[ "${RUNTIME_BUNDLE_SHA}" =~ ${SHA_PATTERN} ]] || \
  fail "local runtime bundle hashing failed"

python3 "${STAGER_SOURCE}" validate-authority-bundle \
  --authorization-packet-source "${AUTHORIZATION_PACKET}" \
  --authorization-packet-sha "${AUTHORIZATION_PACKET_SHA}" \
  --authorization-permit-source "${AUTHORIZATION_PERMIT}" \
  --authorization-permit-sha "${AUTHORIZATION_PERMIT_SHA}" \
  --production-baseline-source "${PRODUCTION_BASELINE}" \
  --production-baseline-sha "${PRODUCTION_BASELINE_SHA}" \
  --expected-current-release "${EXPECTED_CURRENT}" \
  --target-release "${TARGET_RELEASE}" \
  --expected-current-data-release "${EXPECTED_CURRENT_DATA_RELEASE}" \
  --expected-current-data-pointer-sha "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
  --target-data-release "${TARGET_DATA_RELEASE}" \
  --target-data-pointer-sha "${TARGET_DATA_POINTER_SHA}" \
  --runner-sha "${RUNNER_SHA}" >/dev/null

SSH_ARGS=(
  -i "${SSH_KEY}"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${KNOWN_HOSTS}"
)

run_remote() {
  local command=""
  local quoted=""
  local argument
  for argument in "$@"; do
    printf -v quoted '%q' "${argument}"
    command+="${quoted} "
  done
  ssh "${SSH_ARGS[@]}" "${REMOTE}" "${command% }"
}

REMOTE_TMP=""
REMOTE_SEALED=""
cleanup_remote() {
  if [[ -n "${REMOTE_SEALED}" && \
        "${REMOTE_SEALED}" =~ ^/tmp/reddit-voc-insights-rollback-sealed\.[a-f0-9]{64}$ ]]; then
    run_remote sudo -n rm -rf -- "${REMOTE_SEALED}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${REMOTE_TMP}" && \
        "${REMOTE_TMP}" =~ ^/tmp/reddit-voc-insights-rollback\.[A-Za-z0-9]+$ ]]; then
    run_remote rm -rf -- "${REMOTE_TMP}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_remote EXIT

REMOTE_TMP="$(run_remote mktemp -d /tmp/reddit-voc-insights-rollback.XXXXXXXXXX)"
if [[ ! "${REMOTE_TMP}" =~ ^/tmp/reddit-voc-insights-rollback\.[A-Za-z0-9]+$ ]]; then
  fail "remote temporary directory did not match the safety contract"
fi

REMOTE_RUNNER="${REMOTE_TMP}/remote_rollback_insights.sh"
REMOTE_PATCHER="${REMOTE_TMP}/patch_insights_nginx.py"
REMOTE_STAGER="${REMOTE_TMP}/stage_reddit_rollback_evidence.py"
REMOTE_PACKET="${REMOTE_TMP}/authorization-packet.json"
REMOTE_PERMIT="${REMOTE_TMP}/authorization-permit.json"
REMOTE_BASELINE="${REMOTE_TMP}/production-baseline.json"

scp "${SSH_ARGS[@]}" \
  "${REMOTE_RUNNER_SOURCE}" "${REMOTE}:${REMOTE_RUNNER}"
scp "${SSH_ARGS[@]}" \
  "${PATCHER_SOURCE}" "${REMOTE}:${REMOTE_PATCHER}"
scp "${SSH_ARGS[@]}" \
  "${STAGER_SOURCE}" "${REMOTE}:${REMOTE_STAGER}"
scp "${SSH_ARGS[@]}" \
  "${AUTHORIZATION_PACKET}" "${REMOTE}:${REMOTE_PACKET}"
scp "${SSH_ARGS[@]}" \
  "${AUTHORIZATION_PERMIT}" "${REMOTE}:${REMOTE_PERMIT}"
scp "${SSH_ARGS[@]}" \
  "${PRODUCTION_BASELINE}" "${REMOTE}:${REMOTE_BASELINE}"

run_remote chmod 0700 "${REMOTE_RUNNER}" "${REMOTE_PATCHER}" "${REMOTE_STAGER}"
run_remote chmod 0600 "${REMOTE_PACKET}" "${REMOTE_PERMIT}" "${REMOTE_BASELINE}"

REMOTE_SEALED="/tmp/reddit-voc-insights-rollback-sealed.${RUNTIME_BUNDLE_SHA}"
REMOTE_STAGER_BOOTSTRAP="$(cat <<'PY'
import hashlib, os, pathlib, pwd, stat, sys
path = pathlib.Path(sys.argv[1])
expected_sha = sys.argv[2]
expected_uid = pwd.getpwnam(sys.argv[3]).pw_uid
if (
    not path.is_absolute()
    or path.parent.name.split(".")[0] != "reddit-voc-insights-rollback"
    or path.parent.parent != pathlib.Path("/tmp")
    or os.path.realpath(path) != os.fspath(path)
):
    raise SystemExit("remote bootstrap path is unsafe")
parent_link = os.lstat(path.parent)
if (
    not stat.S_ISDIR(parent_link.st_mode)
    or parent_link.st_uid != expected_uid
    or stat.S_IMODE(parent_link.st_mode) != 0o700
):
    raise SystemExit("remote bootstrap parent metadata is unsafe")
flags = os.O_RDONLY | os.O_NOFOLLOW
if hasattr(os, "O_CLOEXEC"):
    flags |= os.O_CLOEXEC
fd = os.open(path, flags)
before = os.fstat(fd)
linked = os.lstat(path)
digest = hashlib.sha256()
while True:
    chunk = os.read(fd, 1024 * 1024)
    if not chunk:
        break
    digest.update(chunk)
after = os.fstat(fd)
current = os.lstat(path)
identity = lambda value: (
    value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
    value.st_ctime_ns, value.st_mode, value.st_uid, value.st_nlink,
)
if (
    not stat.S_ISREG(before.st_mode)
    or before.st_uid != expected_uid
    or before.st_nlink != 1
    or stat.S_IMODE(before.st_mode) != 0o700
    or identity(before) != identity(after)
    or identity(before) != identity(linked)
    or identity(before) != identity(current)
    or digest.hexdigest() != expected_sha
):
    raise SystemExit("remote bootstrap runtime changed or failed authentication")
os.lseek(fd, 0, os.SEEK_SET)
os.set_inheritable(fd, True)
os.execve(
    "/usr/bin/python3",
    ["python3", f"/proc/self/fd/{fd}", *sys.argv[4:]],
    os.environ,
)
PY
)"

SEALED_RESULT="$(
  run_remote sudo -n /usr/bin/python3 -c "${REMOTE_STAGER_BOOTSTRAP}" \
    "${REMOTE_STAGER}" "${STAGER_SHA}" ubuntu \
    seal-runtime \
    --staging-root "${REMOTE_TMP}" \
    --runtime-root "${REMOTE_SEALED}" \
    --source-owner ubuntu \
    --runner-source "${REMOTE_RUNNER}" \
    --runner-sha "${RUNNER_SHA}" \
    --patcher-source "${REMOTE_PATCHER}" \
    --patcher-sha "${PATCHER_SHA}" \
    --stager-source "${REMOTE_STAGER}" \
    --stager-sha "${STAGER_SHA}"
)"
if [[ "${SEALED_RESULT}" != "${REMOTE_SEALED}" ]]; then
  fail "remote sealed runtime publication failed"
fi

SEALED_RUNNER="${REMOTE_SEALED}/remote_rollback_insights.sh"
SEALED_PATCHER="${REMOTE_SEALED}/patch_insights_nginx.py"
SEALED_STAGER="${REMOTE_SEALED}/stage_reddit_rollback_evidence.py"
run_remote "${SEALED_STAGER}" verify-runtime-bundle \
  --runtime-root "${REMOTE_SEALED}" \
  --runner-sha "${RUNNER_SHA}" \
  --patcher-sha "${PATCHER_SHA}" \
  --stager-sha "${STAGER_SHA}" >/dev/null

run_remote "${SEALED_STAGER}" persist \
  --staging-root "${REMOTE_TMP}" \
  --evidence-root "${EVIDENCE_ROOT}" \
  --authorization-packet-source "${REMOTE_PACKET}" \
  --authorization-packet-sha "${AUTHORIZATION_PACKET_SHA}" \
  --authorization-permit-source "${REMOTE_PERMIT}" \
  --authorization-permit-sha "${AUTHORIZATION_PERMIT_SHA}" \
  --production-baseline-source "${REMOTE_BASELINE}" \
  --production-baseline-sha "${PRODUCTION_BASELINE_SHA}" \
  --expected-current-release "${EXPECTED_CURRENT}" \
  --target-release "${TARGET_RELEASE}" \
  --expected-current-data-release "${EXPECTED_CURRENT_DATA_RELEASE}" \
  --expected-current-data-pointer-sha "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
  --target-data-release "${TARGET_DATA_RELEASE}" \
  --target-data-pointer-sha "${TARGET_DATA_POINTER_SHA}" \
  --runner-sha "${RUNNER_SHA}" >/dev/null

PERSISTED_PACKET="${EVIDENCE_ROOT}/authorization-packet-${AUTHORIZATION_PACKET_SHA}.json"
PERSISTED_PERMIT="${EVIDENCE_ROOT}/authorization-permit-${AUTHORIZATION_PERMIT_SHA}.json"
PERSISTED_BASELINE="${EVIDENCE_ROOT}/production-baseline-${PRODUCTION_BASELINE_SHA}.json"

run_remote "${SEALED_RUNNER}" release \
  --expected-current "${EXPECTED_CURRENT}" \
  --target-release "${TARGET_RELEASE}" \
  --expected-current-data-release "${EXPECTED_CURRENT_DATA_RELEASE}" \
  --expected-current-data-pointer-sha "${EXPECTED_CURRENT_DATA_POINTER_SHA}" \
  --target-data-release "${TARGET_DATA_RELEASE}" \
  --target-data-pointer-sha "${TARGET_DATA_POINTER_SHA}" \
  --promotion-receipt "${PROMOTION_RECEIPT}" \
  --promotion-receipt-sha "${PROMOTION_RECEIPT_SHA}" \
  --authorization-packet "${PERSISTED_PACKET}" \
  --authorization-packet-sha "${AUTHORIZATION_PACKET_SHA}" \
  --authorization-permit "${PERSISTED_PERMIT}" \
  --authorization-permit-sha "${AUTHORIZATION_PERMIT_SHA}" \
  --production-baseline "${PERSISTED_BASELINE}" \
  --production-baseline-sha "${PRODUCTION_BASELINE_SHA}" \
  --patch-script "${SEALED_PATCHER}"

cleanup_remote
trap - EXIT
