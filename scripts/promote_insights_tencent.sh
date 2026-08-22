#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: promote_insights_tencent.sh release \
  --artifact-root <path> \
  --execution-contract <path> --execution-contract-sha256 <sha256> \
  --packet <path> --packet-sha256 <sha256> \
  --permit <path> --permit-sha256 <sha256>
EOF
  exit 64
}

[[ "$#" -ge 1 && "$1" == release ]] || usage
shift

ARTIFACT_ROOT=""
EXECUTION_CONTRACT=""
EXECUTION_CONTRACT_SHA=""
PACKET=""
PACKET_SHA=""
PERMIT=""
PERMIT_SHA=""
while [[ "$#" -gt 0 ]]; do
  [[ "$#" -ge 2 ]] || usage
  case "$1" in
    --artifact-root)
      [[ -z "$ARTIFACT_ROOT" ]] || usage
      ARTIFACT_ROOT="$2"
      ;;
    --execution-contract)
      [[ -z "$EXECUTION_CONTRACT" ]] || usage
      EXECUTION_CONTRACT="$2"
      ;;
    --execution-contract-sha256)
      [[ -z "$EXECUTION_CONTRACT_SHA" ]] || usage
      EXECUTION_CONTRACT_SHA="$2"
      ;;
    --packet)
      [[ -z "$PACKET" ]] || usage
      PACKET="$2"
      ;;
    --packet-sha256)
      [[ -z "$PACKET_SHA" ]] || usage
      PACKET_SHA="$2"
      ;;
    --permit)
      [[ -z "$PERMIT" ]] || usage
      PERMIT="$2"
      ;;
    --permit-sha256)
      [[ -z "$PERMIT_SHA" ]] || usage
      PERMIT_SHA="$2"
      ;;
    *) usage ;;
  esac
  shift 2
done
for value in \
  "$ARTIFACT_ROOT" "$EXECUTION_CONTRACT" "$EXECUTION_CONTRACT_SHA" \
  "$PACKET" "$PACKET_SHA" "$PERMIT" "$PERMIT_SHA"; do
  [[ -n "$value" ]] || usage
done

SCRIPT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VALIDATOR="${SCRIPT_ROOT}/scripts/validate_reddit_promotion_execution_bundle.py"
KEY="${SCRIPT_ROOT}/DDDD.pem"
REMOTE="ubuntu@101.34.52.232"
HOST="101.34.52.232"
EXPECTED_HOST_FINGERPRINT="SHA256:LIiSdEy34t6nQCaOxrZ5BI0OlskdFOTrkPsFMd/KgDY"
LOCAL_TEMP=""
KNOWN_HOSTS=""
UPLOAD_ROOT=""
SEALED_ROOT=""
UPLOAD_CREATED=0

for command in date mktemp python3 scp ssh ssh-keygen ssh-keyscan; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "required local command missing: $command" >&2
    exit 69
  }
done

python3 - "$KEY" "$(id -u)" <<'PY'
import os
from pathlib import Path
import stat
import sys

path = Path(sys.argv[1])
owner = int(sys.argv[2])
metadata = path.lstat()
if (
    not path.is_absolute()
    or not stat.S_ISREG(metadata.st_mode)
    or metadata.st_nlink != 1
    or metadata.st_uid != owner
    or stat.S_IMODE(metadata.st_mode) != 0o600
):
    raise SystemExit("SSH private key contract invalid")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("SSH private key validation requires O_NOFOLLOW")
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    opened = os.fstat(descriptor)
    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise SystemExit("SSH private key changed while opening")
finally:
    os.close(descriptor)
PY

cleanup_local() {
  local status="$?"
  trap - EXIT
  if [[ "$UPLOAD_CREATED" == 1 && -n "$UPLOAD_ROOT" ]]; then
    ssh \
      -i "$KEY" -o BatchMode=yes -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KNOWN_HOSTS" \
      -o HostKeyAlgorithms=ssh-ed25519 \
      "$REMOTE" sudo -n python3 - "$UPLOAD_ROOT" "${PACKET_SHA:0:12}" <<'PY' \
      >/dev/null 2>&1 || true
from pathlib import Path
import pwd
import re
import shutil
import stat
import sys

path = Path(sys.argv[1])
prefix = sys.argv[2]
metadata = path.lstat()
if (
    path.parent != Path("/tmp")
    or re.fullmatch(rf"reddit-voc-promotion-upload\.{prefix}\.[A-Za-z0-9]+", path.name)
    is None
    or not stat.S_ISDIR(metadata.st_mode)
    or metadata.st_uid != pwd.getpwnam("ubuntu").pw_uid
):
    raise SystemExit("refusing unsafe promotion upload cleanup")
shutil.rmtree(path)
PY
  fi
  [[ -z "$LOCAL_TEMP" ]] || rm -rf "$LOCAL_TEMP"
  exit "$status"
}
trap cleanup_local EXIT

NOW_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
BUNDLE_JSON="$(
  python3 "$VALIDATOR" \
    --artifact-root "$ARTIFACT_ROOT" \
    --execution-contract "$EXECUTION_CONTRACT" \
    --execution-contract-sha256 "$EXECUTION_CONTRACT_SHA" \
    --packet "$PACKET" --packet-sha256 "$PACKET_SHA" \
    --permit "$PERMIT" --permit-sha256 "$PERMIT_SHA" \
    --now-utc "$NOW_UTC"
)"

BUNDLE_VALUES="$(python3 - "$BUNDLE_JSON" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
if (
    value.get("schema_version")
    != "reddit_voc_live_promotion_bundle_validation_v1"
    or value.get("status") != "passed_local_exact_bundle"
):
    raise SystemExit("local promotion bundle validation result invalid")
sources = value["sources"]
arguments = value["runner_arguments"]
fields = []
for label in ("archive", "packet", "permit", "runner", "installer", "rollback"):
    record = sources[label]
    fields.extend(
        [record["path"], record["sha256"], str(record["bytes"])]
    )
for label in (
    "release_sha256",
    "expected_current_release_sha256",
    "data_release_id",
    "expected_current_data_release_id",
    "expected_current_data_pointer_sha256",
    "target_data_pointer_sha256",
):
    fields.append(arguments[label])
if any(not isinstance(field, str) or not field or "\t" in field or "\n" in field for field in fields):
    raise SystemExit("local promotion bundle contains an unsafe shell field")
print("\t".join(fields))
PY
)"
IFS=$'\t' read -r \
  ARCHIVE_PATH ARCHIVE_SHA ARCHIVE_BYTES \
  PACKET_PATH PACKET_BOUND_SHA PACKET_BYTES \
  PERMIT_PATH PERMIT_BOUND_SHA PERMIT_BYTES \
  RUNNER_PATH RUNNER_SHA RUNNER_BYTES \
  INSTALLER_PATH INSTALLER_SHA INSTALLER_BYTES \
  ROLLBACK_PATH ROLLBACK_SHA ROLLBACK_BYTES \
  RELEASE_SHA EXPECTED_CURRENT DATA_RELEASE_ID \
  EXPECTED_CURRENT_DATA_RELEASE_ID EXPECTED_CURRENT_DATA_POINTER_SHA \
  TARGET_DATA_POINTER_SHA <<<"$BUNDLE_VALUES"
[[ "$PACKET_BOUND_SHA" == "$PACKET_SHA" && "$PERMIT_BOUND_SHA" == "$PERMIT_SHA" ]] || {
  echo "validated authority digests differ from explicit inputs" >&2
  exit 65
}

LOCAL_TEMP="$(mktemp -d "${TMPDIR:-/tmp}/reddit-voc-promotion-transport.XXXXXX")"
chmod 0700 "$LOCAL_TEMP"
KNOWN_HOSTS="$LOCAL_TEMP/known_hosts"
ssh-keyscan -T 10 -t ed25519 "$HOST" >"$KNOWN_HOSTS"
chmod 0600 "$KNOWN_HOSTS"
python3 - "$KNOWN_HOSTS" "$EXPECTED_HOST_FINGERPRINT" <<'PY'
import subprocess
import sys

path, expected = sys.argv[1:]
completed = subprocess.run(
    ["ssh-keygen", "-lf", path, "-E", "sha256"],
    check=True,
    capture_output=True,
    text=True,
)
rows = [row.split() for row in completed.stdout.splitlines() if row.strip()]
fingerprints = [row[1] for row in rows if len(row) >= 4]
if fingerprints != [expected]:
    raise SystemExit("Tencent host ED25519 fingerprint mismatch")
PY

SSH_OPTIONS=(
  -i "$KEY"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=$KNOWN_HOSTS"
  -o HostKeyAlgorithms=ssh-ed25519
)
PACKET_PREFIX="${PACKET_SHA:0:12}"
UPLOAD_ROOT="$(ssh "${SSH_OPTIONS[@]}" "$REMOTE" bash -s -- "$PACKET_PREFIX" <<'REMOTE'
set -euo pipefail
prefix="$1"
[[ "$prefix" =~ ^[a-f0-9]{12}$ ]]
umask 077
mktemp -d "/tmp/reddit-voc-promotion-upload.${prefix}.XXXXXXXX"
REMOTE
)"
[[ "$UPLOAD_ROOT" =~ ^/tmp/reddit-voc-promotion-upload\.${PACKET_PREFIX}\.[A-Za-z0-9]+$ ]] || {
  echo "remote promotion upload root contract invalid" >&2
  exit 65
}
UPLOAD_CREATED=1

SOURCE_PATHS=(
  "$ARCHIVE_PATH" "$PACKET_PATH" "$PERMIT_PATH"
  "$RUNNER_PATH" "$INSTALLER_PATH" "$ROLLBACK_PATH"
)
SEALED_NAMES=(
  release.tgz packet.json permit.json
  remote_promote_insights_v6.sh
  remote_install_insights_release.sh
  remote_rollback_insights.sh
)
for index in 0 1 2 3 4 5; do
  source_path="${SOURCE_PATHS[$index]}"
  sealed_name="${SEALED_NAMES[$index]}"
  scp -q "${SSH_OPTIONS[@]}" -- \
    "$source_path" "$REMOTE:$UPLOAD_ROOT/$sealed_name"
done

SEALED_ROOT="$(ssh "${SSH_OPTIONS[@]}" "$REMOTE" sudo -n python3 - \
  "$UPLOAD_ROOT" "$PACKET_PREFIX" \
  release.tgz "$ARCHIVE_SHA" "$ARCHIVE_BYTES" \
  packet.json "$PACKET_SHA" "$PACKET_BYTES" \
  permit.json "$PERMIT_SHA" "$PERMIT_BYTES" \
  remote_promote_insights_v6.sh "$RUNNER_SHA" "$RUNNER_BYTES" \
  remote_install_insights_release.sh "$INSTALLER_SHA" "$INSTALLER_BYTES" \
  remote_rollback_insights.sh "$ROLLBACK_SHA" "$ROLLBACK_BYTES" <<'PY'
from hashlib import sha256
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import stat
import sys

upload = Path(sys.argv[1])
prefix = sys.argv[2]
raw_specs = sys.argv[3:]
if len(raw_specs) != 18:
    raise SystemExit("promotion sealer specification invalid")
specs = {
    raw_specs[index]: (raw_specs[index + 1], int(raw_specs[index + 2]))
    for index in range(0, len(raw_specs), 3)
}
expected_names = {
    "release.tgz",
    "packet.json",
    "permit.json",
    "remote_promote_insights_v6.sh",
    "remote_install_insights_release.sh",
    "remote_rollback_insights.sh",
}
if set(specs) != expected_names or re.fullmatch(r"[a-f0-9]{12}", prefix) is None:
    raise SystemExit("promotion sealer exact inventory invalid")
ubuntu_uid = pwd.getpwnam("ubuntu").pw_uid
upload_metadata = upload.lstat()
if (
    upload.parent != Path("/tmp")
    or re.fullmatch(rf"reddit-voc-promotion-upload\.{prefix}\.[A-Za-z0-9]+", upload.name)
    is None
    or not stat.S_ISDIR(upload_metadata.st_mode)
    or upload_metadata.st_uid != ubuntu_uid
    or stat.S_IMODE(upload_metadata.st_mode) != 0o700
    or {path.name for path in upload.iterdir()} != expected_names
):
    raise SystemExit("promotion upload root is unsafe")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("promotion sealer requires O_NOFOLLOW")
upload_fd = os.open(upload, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
payloads = {}
try:
    for name in sorted(expected_names):
        before = os.stat(name, dir_fd=upload_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != ubuntu_uid
            or before.st_mode & 0o022
        ):
            raise SystemExit(f"promotion upload is unsafe: {name}")
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=upload_fd)
        try:
            opened = os.fstat(descriptor)
            chunks = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        payload = b"".join(chunks)
        expected_sha, expected_bytes = specs[name]
        if (
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or len(payload) != expected_bytes
            or sha256(payload).hexdigest() != expected_sha
        ):
            raise SystemExit(f"promotion upload changed or is unauthenticated: {name}")
        payloads[name] = payload
finally:
    os.close(upload_fd)

runtime_root = Path("/opt/reddit-voc-insights-site/runtime")
runtime_root.mkdir(mode=0o755, exist_ok=True)
runtime_metadata = runtime_root.lstat()
if (
    not stat.S_ISDIR(runtime_metadata.st_mode)
    or runtime_metadata.st_uid != 0
    or runtime_metadata.st_mode & 0o022
):
    raise SystemExit("promotion runtime root is unsafe")
sealed = runtime_root / f".promotion-{prefix}.{secrets.token_urlsafe(12)}"
if re.fullmatch(rf"\.promotion-{prefix}\.[A-Za-z0-9_-]{{6,64}}", sealed.name) is None:
    raise SystemExit("promotion sealed root name invalid")
sealed.mkdir(mode=0o700)
try:
    sealed_fd = os.open(sealed, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in sorted(expected_names):
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o444,
                dir_fd=sealed_fd,
            )
            try:
                payload = payloads[name]
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise SystemExit("promotion sealed write incomplete")
                    offset += written
                os.fchmod(descriptor, 0o444)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(sealed_fd)
    finally:
        os.close(sealed_fd)
    os.chmod(sealed, 0o555)
    runtime_fd = os.open(runtime_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(runtime_fd)
    finally:
        os.close(runtime_fd)
except BaseException:
    os.chmod(sealed, 0o700)
    shutil.rmtree(sealed)
    raise
print(sealed)
PY
)"
[[ "$SEALED_ROOT" =~ ^/opt/reddit-voc-insights-site/runtime/\.promotion-${PACKET_PREFIX}\.[A-Za-z0-9_-]{6,64}$ ]] || {
  echo "remote sealed promotion root contract invalid" >&2
  exit 65
}

# The root sealer has copied and authenticated all uploaded bytes.  Removing the
# untrusted upload directory now cannot affect the transaction.
ssh "${SSH_OPTIONS[@]}" "$REMOTE" sudo -n python3 - \
  "$UPLOAD_ROOT" "$PACKET_PREFIX" <<'PY'
from pathlib import Path
import pwd
import re
import shutil
import stat
import sys

path = Path(sys.argv[1])
prefix = sys.argv[2]
metadata = path.lstat()
if (
    path.parent != Path("/tmp")
    or re.fullmatch(rf"reddit-voc-promotion-upload\.{prefix}\.[A-Za-z0-9]+", path.name)
    is None
    or not stat.S_ISDIR(metadata.st_mode)
    or metadata.st_uid != pwd.getpwnam("ubuntu").pw_uid
):
    raise SystemExit("refusing unsafe promotion upload cleanup")
shutil.rmtree(path)
PY
UPLOAD_CREATED=0

set +e
ssh "${SSH_OPTIONS[@]}" "$REMOTE" bash -s -- \
  "$SEALED_ROOT" "$ARCHIVE_SHA" "$PACKET_SHA" "$PERMIT_SHA" \
  "$RELEASE_SHA" "$EXPECTED_CURRENT" "$DATA_RELEASE_ID" \
  "$EXPECTED_CURRENT_DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_POINTER_SHA" \
  "$TARGET_DATA_POINTER_SHA" <<'REMOTE'
set -euo pipefail
sealed="$1"
shift
[[ "$sealed" =~ ^/opt/reddit-voc-insights-site/runtime/\.promotion-[a-f0-9]{12}\.[A-Za-z0-9_-]{6,64}$ ]]
exec bash "$sealed/remote_promote_insights_v6.sh" \
  "$sealed/release.tgz" "$1" \
  "$sealed/packet.json" "$2" \
  "$sealed/permit.json" "$3" \
  "$4" "$5" "$6" "$7" "$8" "$9"
REMOTE
PROMOTION_STATUS=$?
set -e
if [[ "$PROMOTION_STATUS" != 0 ]]; then
  echo "promotion failed; root-sealed evidence retained at $SEALED_ROOT" >&2
  exit "$PROMOTION_STATUS"
fi

ssh "${SSH_OPTIONS[@]}" "$REMOTE" sudo -n python3 - \
  "$SEALED_ROOT" "$PACKET_PREFIX" <<'PY'
from pathlib import Path
import re
import shutil
import stat
import sys

path = Path(sys.argv[1])
prefix = sys.argv[2]
runtime_root = Path("/opt/reddit-voc-insights-site/runtime")
metadata = path.lstat()
expected = {
    "release.tgz", "packet.json", "permit.json",
    "remote_promote_insights_v6.sh",
    "remote_install_insights_release.sh",
    "remote_rollback_insights.sh",
}
if (
    path.parent != runtime_root
    or re.fullmatch(rf"\.promotion-{prefix}\.[A-Za-z0-9_-]{{6,64}}", path.name)
    is None
    or not stat.S_ISDIR(metadata.st_mode)
    or metadata.st_uid != 0
    or stat.S_IMODE(metadata.st_mode) != 0o555
    or {item.name for item in path.iterdir()} != expected
):
    raise SystemExit("refusing unsafe sealed promotion cleanup")
os_mode = 0o700
path.chmod(os_mode)
shutil.rmtree(path)
PY
SEALED_ROOT=""
echo "controlled Reddit VOC promotion completed for packet $PACKET_SHA and release $RELEASE_SHA"
