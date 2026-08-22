#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 || ( "$1" != "http" && "$1" != "https" ) ]]; then
  echo "usage: configure_insights_edge_tencent.sh <http|https>" >&2
  exit 1
fi

MODE="$1"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_KEY="${SSH_KEY:-${PROJECT_ROOT}/DDDD.pem}"
REMOTE="${REMOTE:-ubuntu@101.34.52.232}"
KNOWN_HOSTS="${KNOWN_HOSTS:-${HOME}/.ssh/known_hosts}"

if [[ ! -f "${SSH_KEY}" || -L "${SSH_KEY}" ]]; then
  echo "SSH key is missing or is a symlink: ${SSH_KEY}" >&2
  exit 1
fi
if [[ "$(stat -f '%Lp' "${SSH_KEY}" 2>/dev/null || stat -c '%a' "${SSH_KEY}")" != "600" ]]; then
  echo "SSH key must have mode 600" >&2
  exit 1
fi
if [[ ! -f "${KNOWN_HOSTS}" || -L "${KNOWN_HOSTS}" ]] || ! ssh-keygen -F 101.34.52.232 -f "${KNOWN_HOSTS}" >/dev/null; then
  echo "verified SSH host key entry is missing for 101.34.52.232" >&2
  exit 1
fi

SSH_ARGS=(-i "${SSH_KEY}" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${KNOWN_HOSTS}")
REMOTE_TMP="$(ssh "${SSH_ARGS[@]}" "${REMOTE}" mktemp -d /tmp/reddit-voc-insights-edge.XXXXXX)"
if [[ ! "${REMOTE_TMP}" =~ ^/tmp/reddit-voc-insights-edge\.[A-Za-z0-9]+$ ]]; then
  echo "remote temporary directory did not match the safety contract" >&2
  exit 1
fi
REMOTE_RUNNER="${REMOTE_TMP}/remote_configure_insights_edge.sh"
REMOTE_PATCHER="${REMOTE_TMP}/patch_insights_nginx.py"

cleanup_remote() {
  ssh "${SSH_ARGS[@]}" "${REMOTE}" rm -rf "${REMOTE_TMP}" >/dev/null 2>&1 || true
}
trap cleanup_remote EXIT

scp "${SSH_ARGS[@]}" "${PROJECT_ROOT}/scripts/remote_configure_insights_edge.sh" "${REMOTE}:${REMOTE_RUNNER}"
scp "${SSH_ARGS[@]}" "${PROJECT_ROOT}/scripts/patch_insights_nginx.py" "${REMOTE}:${REMOTE_PATCHER}"
ssh "${SSH_ARGS[@]}" "${REMOTE}" chmod 0700 "${REMOTE_RUNNER}" "${REMOTE_PATCHER}"
ssh "${SSH_ARGS[@]}" "${REMOTE}" "${REMOTE_RUNNER}" "${MODE}" "${REMOTE_PATCHER}"
cleanup_remote
trap - EXIT
