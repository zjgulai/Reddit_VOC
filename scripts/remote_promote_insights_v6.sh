#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 12 ]]; then
  echo "usage: remote_promote_insights_v6.sh <archive> <archive-sha> <packet> <packet-sha> <permit> <permit-sha> <release-sha> <expected-current-sha> <data-release-id> <expected-current-data-release-id> <expected-current-data-pointer-sha> <target-data-pointer-sha>" >&2
  exit 1
fi

ARCHIVE="$1"
ARCHIVE_SHA="$2"
PACKET="$3"
PACKET_SHA="$4"
PERMIT="$5"
PERMIT_SHA="$6"
RELEASE_SHA="$7"
EXPECTED_CURRENT="$8"
DATA_RELEASE_ID="$9"
EXPECTED_CURRENT_DATA_RELEASE_ID="${10}"
EXPECTED_CURRENT_DATA_POINTER_SHA="${11}"
TARGET_DATA_POINTER_SHA="${12}"

DEPLOY_ROOT=/opt/reddit-voc-insights-site
DATA_ROOT=/opt/reddit-voc-insights-data
BIND_ADDRESS=172.20.0.1
CANDIDATE_PORT=18339
CANDIDATE="reddit_voc_insights_candidate_${RELEASE_SHA:0:12}"
VERIFY_CONTAINER="reddit_voc_insights_verify_${RELEASE_SHA:0:12}"
NETWORK=reddit_voc_insights_net
INSTALLER="$(cd "$(dirname "$0")" && pwd)/remote_install_insights_release.sh"
ROLLBACK="$(cd "$(dirname "$0")" && pwd)/remote_rollback_insights.sh"
RUNNER_SOURCE="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
TEMP_ROOT=""
DATA_STAGE=""
DATA_RELEASE_COMMITTED=0
DATA_PREVIOUS_SWITCHED=0
DATA_CURRENT_SWITCHED=0
DATA_EXTRACT=""
DATA_RELEASE_DIR="${DATA_ROOT}/releases/${DATA_RELEASE_ID}"
DATA_CURRENT_TMP="${DATA_ROOT}/.current-${RELEASE_SHA:0:12}.$$"
DATA_PREVIOUS_TMP="${DATA_ROOT}/.previous-${RELEASE_SHA:0:12}.$$"
SITE_CURRENT_RECOVERY_TMP="${DEPLOY_ROOT}/.current-recovery-${RELEASE_SHA:0:12}.$$"
JOURNAL="${DEPLOY_ROOT}/promotion-transaction.json"
PROMOTION_LOCK="${DEPLOY_ROOT}/.promotion.lock"
DEPLOY_LOCK="${DEPLOY_ROOT}/.deploy.lock"
LOCKS_DIR="${DATA_ROOT}/locks"
DATA_LOCK="${LOCKS_DIR}/data-release.lock"
PREVIOUS_DATA_TARGET=""
ORIGINAL_DATA_PREVIOUS_TARGET="absent"
CANDIDATE_DATA_ROOT="$DATA_ROOT"
CANDIDATE_STARTED=0
SITE_COMMITTED=0
TRANSACTION_ARMED=0
EXPECTED_DATA_POINTER_SHA=""
RECOVERED_PROMOTION=0
RECOVERED_EVIDENCE=""
DATA_INVENTORY_SHA=""
DATA_FILE_COUNT=""
DATA_TOTAL_BYTES=""
OLD_DATA_INVENTORY_SHA=""
OLD_DATA_FILE_COUNT=""
OLD_DATA_TOTAL_BYTES=""
AUTHORIZATION_MODE=""
TRANSACTION_STARTED_AT_UTC=""
COLLECTOR_ID=""
COLLECTOR_RESTART=""
TRANSLATION_ID=""
TRANSLATION_RESTART=""
NGINX_SHA=""
CRON_SHA=""
INVENTORY_SHA=""
EXPECTED_OLD_RELEASE_MANIFEST_SHA=""
EXPECTED_OLD_RELEASE_SHA256SUMS_SHA=""
EXPECTED_OLD_DATA_INVENTORY_SHA=""
EXPECTED_OLD_DATA_FILE_COUNT=""
EXPECTED_OLD_DATA_TOTAL_BYTES=""
PRODUCTION_BASELINE_CAS_SHA=""
AUTHORIZED_COLLECTOR_ID=""
AUTHORIZED_COLLECTOR_RESTART=""
AUTHORIZED_TRANSLATION_ID=""
AUTHORIZED_TRANSLATION_RESTART=""
AUTHORIZED_NGINX_SHA=""
AUTHORIZED_CRON_SHA=""
AUTHORIZED_CONTAINER_INVENTORY_SHA=""
AUTHORIZED_INSIGHTS_IMAGE_ID=""
AUTHORIZED_INSIGHTS_NETWORK_ID=""
TARGET_IMAGE_ID=""
DATABASE_IDENTITY=""
REPORT_POINTER_IDENTITY=""
INVENTORY_COUNT=""

fail() { echo "$1" >&2; exit 1; }
is_sha() { [[ "$1" =~ ^[a-f0-9]{64}$ ]]; }
current_release() {
  [[ -L "${DEPLOY_ROOT}/current" ]] || fail "current release pointer missing"
  local target
  target="$(readlink "${DEPLOY_ROOT}/current")"
  [[ "$target" =~ ^releases/([a-f0-9]{64})$ ]] || fail "current release pointer invalid"
  printf '%s' "${BASH_REMATCH[1]}"
}
inventory_identity() {
  python3 - "$VERIFY_CONTAINER" <<'PY'
import hashlib
import json
import subprocess
import sys

verify_container = "/" + sys.argv[1]

def command(*arguments: str) -> str:
    return subprocess.run(
        arguments, check=True, capture_output=True, text=True
    ).stdout.strip()

output = command("docker", "container", "ls", "-a", "-q", "--no-trunc")
identifiers = sorted(line for line in output.splitlines() if line)
if not identifiers:
    raise SystemExit("protected container inventory is empty")
values = json.loads(command("docker", "inspect", *identifiers))
if not isinstance(values, list) or len(values) != len(identifiers):
    raise SystemExit("protected container inventory inspect is incomplete")
rows = []
for value in values:
    if not isinstance(value, dict):
        raise SystemExit("protected container inventory row is invalid")
    name = value.get("Name")
    if name == "/reddit_voc_insights_web" or (
        isinstance(name, str)
        and name.startswith("/reddit_voc_insights_candidate_")
    ) or name == verify_container:
        continue
    state = value.get("State") or {}
    if not isinstance(state, dict):
        raise SystemExit("protected container inventory state is invalid")
    rows.append(
        json.dumps(
            {
                "container_id": value.get("Id"),
                "finished_at": state.get("FinishedAt"),
                "name": name,
                "restart_count": value.get("RestartCount"),
                "started_at": state.get("StartedAt"),
                "state": state.get("Status"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
rows.sort()
digest = hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()
print(len(rows), digest, sep="\t")
PY
}
candidate_count() {
  docker ps -a --format '{{.Names}}' | awk '/^reddit_voc_insights_candidate_/{n++} END{print n+0}'
}
port_count() {
  ss -H -ltn | awk '$4 ~ /:18339$/{n++} END{print n+0}'
}
fsync_directory() {
  python3 - "$1" <<'PY'
import os
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
}
pointer_state() {
  local path="$1"
  if [[ -L "$path" ]]; then
    readlink "$path"
  elif [[ -e "$path" ]]; then
    printf '%s' unsafe
  else
    printf '%s' absent
  fi
}
live_site_tuple() {
  local pointer container_release container_health http_release
  pointer="$(pointer_state "$DEPLOY_ROOT/current")"
  container_release="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' reddit_voc_insights_web 2>/dev/null || true)"
  container_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_insights_web 2>/dev/null || true)"
  http_release="$(curl -fsS "http://$BIND_ADDRESS:18338/release.json" 2>/dev/null | python3 -c 'import json,sys; value=json.load(sys.stdin); print(value.get("release_sha256", ""))' 2>/dev/null || true)"
  printf '%s\t%s\t%s\t%s\n' "$pointer" "$container_release" "$container_health" "$http_release"
}
replace_data_pointer() {
  local path="$1"
  local expected_target="$2"
  local replacement_target="$3"
  local temporary_hint="$4"
  validate_promotion_transaction_locks || return 1
  if [[ "$(candidate_count)" != 0 || "$(port_count)" != 0 ]]; then
    echo "data pointer CAS blocked by candidate activity" >&2
    return 1
  fi
  if ! python3 - "$path" "$expected_target" "$replacement_target" "$temporary_hint" "$(id -u)" <<'PY'
import ctypes
import os
import re
import secrets
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected, replacement, temporary_hint = sys.argv[2:5]
owner = int(sys.argv[5])
target_pattern = re.compile(
    r"^releases/(?:[a-f0-9]{64}|reddit_voc_release_[a-z0-9_-]+)$"
)
if (
    not path.is_absolute()
    or (expected != "absent" and target_pattern.fullmatch(expected) is None)
    or target_pattern.fullmatch(replacement) is None
    or expected == replacement
    or Path(temporary_hint).parent != path.parent
):
    raise SystemExit("data pointer CAS arguments are invalid")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("data pointer CAS requires O_NOFOLLOW")
parent = path.parent
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = f".{path.name}.promotion.{os.getpid()}.{secrets.token_hex(16)}.tmp"
temporary_created = False
replacement_metadata = None
current_before = None

def rename_noreplace(source: str, destination: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        result = library.renameat2(
            parent_fd, os.fsencode(source),
            parent_fd, os.fsencode(destination), 1,
        )
    elif sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            parent_fd, os.fsencode(source),
            parent_fd, os.fsencode(destination), 0x00000004,
        )
    else:
        raise SystemExit("atomic no-replace rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)

def exchange(source: str, destination: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        result = library.renameat2(
            parent_fd, os.fsencode(source),
            parent_fd, os.fsencode(destination), 2,
        )
    elif sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            parent_fd, os.fsencode(source),
            parent_fd, os.fsencode(destination), 0x00000002,
        )
    else:
        raise SystemExit("atomic exchange rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)

def linked(name: str):
    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != owner:
        raise SystemExit("data pointer metadata is unsafe")
    return metadata, os.readlink(name, dir_fd=parent_fd)

try:
    parent_before = os.fstat(parent_fd)
    path_parent = parent.lstat()
    if (
        not stat.S_ISDIR(parent_before.st_mode)
        or (parent_before.st_dev, parent_before.st_ino)
        != (path_parent.st_dev, path_parent.st_ino)
        or parent_before.st_uid != owner
        or parent_before.st_mode & 0o022
    ):
        raise SystemExit("data pointer parent directory is unsafe")
    if expected == "absent":
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SystemExit("data pointer CAS expected absence")
    else:
        current_before, current_target = linked(path.name)
        if current_target != expected:
            raise SystemExit("data pointer CAS expected target mismatch")
    os.symlink(replacement, temporary, dir_fd=parent_fd)
    temporary_created = True
    replacement_metadata, replacement_target = linked(temporary)
    if replacement_target != replacement:
        raise SystemExit("data pointer CAS temporary target mismatch")
    if expected == "absent":
        rename_noreplace(temporary, path.name)
        temporary_created = False
    else:
        exchange(temporary, path.name)
        displaced, displaced_target = linked(temporary)
        published, published_target = linked(path.name)
        if (
            (displaced.st_dev, displaced.st_ino)
            != (current_before.st_dev, current_before.st_ino)
            or displaced_target != expected
            or (published.st_dev, published.st_ino)
            != (replacement_metadata.st_dev, replacement_metadata.st_ino)
            or published_target != replacement
        ):
            try:
                observed, observed_target = linked(path.name)
                old, old_target = linked(temporary)
                if (
                    (observed.st_dev, observed.st_ino)
                    == (replacement_metadata.st_dev, replacement_metadata.st_ino)
                    and observed_target == replacement
                ):
                    exchange(temporary, path.name)
                    restored, restored_target = linked(path.name)
                    restored_temporary, restored_temporary_target = linked(temporary)
                    if (
                        (restored.st_dev, restored.st_ino)
                        != (old.st_dev, old.st_ino)
                        or restored_target != old_target
                        or (
                            restored_temporary.st_dev,
                            restored_temporary.st_ino,
                        )
                        != (
                            replacement_metadata.st_dev,
                            replacement_metadata.st_ino,
                        )
                        or restored_temporary_target != replacement
                    ):
                        raise SystemExit(
                            "data pointer CAS failed to restore exchange-time destination"
                        )
            finally:
                raise SystemExit("data pointer CAS exchange verification failed")
        os.unlink(temporary, dir_fd=parent_fd)
        temporary_created = False
    final, final_target = linked(path.name)
    if (
        (final.st_dev, final.st_ino)
        != (replacement_metadata.st_dev, replacement_metadata.st_ino)
        or final_target != replacement
    ):
        raise SystemExit("data pointer CAS final verification failed")
    os.fsync(parent_fd)
    parent_after = os.fstat(parent_fd)
    linked_after = parent.lstat()
    if (
        (parent_before.st_dev, parent_before.st_ino)
        != (parent_after.st_dev, parent_after.st_ino)
        or (parent_after.st_dev, parent_after.st_ino)
        != (linked_after.st_dev, linked_after.st_ino)
    ):
        raise SystemExit("data pointer parent changed during CAS")
finally:
    if temporary_created and replacement_metadata is not None:
        try:
            candidate = os.stat(
                temporary, dir_fd=parent_fd, follow_symlinks=False
            )
            if (
                candidate.st_dev,
                candidate.st_ino,
            ) == (
                replacement_metadata.st_dev,
                replacement_metadata.st_ino,
            ):
                os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
    os.close(parent_fd)
PY
  then
    return 1
  fi
  validate_promotion_transaction_locks || return 1
  if [[ "$(candidate_count)" != 0 || "$(port_count)" != 0 ]]; then
    echo "data pointer CAS postcondition blocked by candidate activity" >&2
    return 1
  fi
  if [[ "$(pointer_state "$path")" != "$replacement_target" ]]; then
    echo "data pointer CAS postcondition failed: $path" >&2
    return 1
  fi
}
remove_data_pointer() {
  local path="$1"
  local expected_target="$2"
  local temporary_hint="$3"
  validate_promotion_transaction_locks || return 1
  if [[ "$(candidate_count)" != 0 || "$(port_count)" != 0 ]]; then
    echo "data pointer removal blocked by candidate activity" >&2
    return 1
  fi
  if ! python3 - "$path" "$expected_target" "$temporary_hint" "$(id -u)" <<'PY'
import ctypes
import os
import re
import secrets
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = sys.argv[2]
temporary_hint = Path(sys.argv[3])
owner = int(sys.argv[4])
if (
    not path.is_absolute()
    or re.fullmatch(
        r"releases/(?:[a-f0-9]{64}|reddit_voc_release_[a-z0-9_-]+)",
        expected,
    ) is None
    or temporary_hint.parent != path.parent
):
    raise SystemExit("data pointer removal arguments are invalid")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("data pointer removal requires O_NOFOLLOW")
parent = path.parent
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = f".{path.name}.remove.{os.getpid()}.{secrets.token_hex(16)}.tmp"
moved = False

def rename_noreplace(source: str, destination: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        result = library.renameat2(
            parent_fd, os.fsencode(source),
            parent_fd, os.fsencode(destination), 1,
        )
    elif sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            parent_fd, os.fsencode(source),
            parent_fd, os.fsencode(destination), 0x00000004,
        )
    else:
        raise SystemExit("atomic no-replace rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)

def linked(name: str):
    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != owner:
        raise SystemExit("data pointer removal metadata is unsafe")
    return metadata, os.readlink(name, dir_fd=parent_fd)

try:
    parent_before = os.fstat(parent_fd)
    path_parent = parent.lstat()
    if (
        not stat.S_ISDIR(parent_before.st_mode)
        or (parent_before.st_dev, parent_before.st_ino)
        != (path_parent.st_dev, path_parent.st_ino)
        or parent_before.st_uid != owner
        or parent_before.st_mode & 0o022
    ):
        raise SystemExit("data pointer removal parent is unsafe")
    before, before_target = linked(path.name)
    if before_target != expected:
        raise SystemExit("data pointer removal expected target mismatch")
    rename_noreplace(path.name, temporary)
    moved = True
    displaced, displaced_target = linked(temporary)
    if (
        (displaced.st_dev, displaced.st_ino) != (before.st_dev, before.st_ino)
        or displaced_target != expected
    ):
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            rename_noreplace(temporary, path.name)
            moved = False
        raise SystemExit("data pointer removal CAS verification failed")
    try:
        os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise SystemExit("data pointer removal destination was recreated")
    os.unlink(temporary, dir_fd=parent_fd)
    moved = False
    os.fsync(parent_fd)
finally:
    if moved:
        try:
            candidate, _ = linked(temporary)
            try:
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                if (candidate.st_dev, candidate.st_ino) == (
                    before.st_dev,
                    before.st_ino,
                ):
                    rename_noreplace(temporary, path.name)
                    moved = False
        except FileNotFoundError:
            pass
    os.close(parent_fd)
PY
  then
    return 1
  fi
  validate_promotion_transaction_locks || return 1
  if [[ "$(candidate_count)" != 0 || "$(port_count)" != 0 ]]; then
    echo "data pointer removal postcondition blocked by candidate activity" >&2
    return 1
  fi
  if [[ "$(pointer_state "$path")" != absent ]]; then
    echo "data pointer removal postcondition failed: $path" >&2
    return 1
  fi
}
restore_previous_pointer() {
  local expected_target="$1"
  local original_target="$2"
  local observed
  observed="$(pointer_state "$DATA_ROOT/previous")"
  if [[ "$observed" == "$original_target" ]]; then
    return 0
  fi
  [[ "$observed" == "$expected_target" ]] || fail "data previous pointer CAS mismatch during recovery"
  if [[ "$original_target" == absent ]]; then
    remove_data_pointer "$DATA_ROOT/previous" "$expected_target" "$DATA_PREVIOUS_TMP"
  else
    replace_data_pointer "$DATA_ROOT/previous" "$expected_target" "$original_target" "$DATA_PREVIOUS_TMP"
  fi
}
validate_promotion_transaction_locks() {
  python3 - \
    "7:${PROMOTION_LOCK}" \
    "9:${DEPLOY_LOCK}" \
    "8:${DATA_LOCK}" <<'PY'
import errno
import fcntl
import os
from pathlib import Path
import stat
import sys

for binding in sys.argv[1:]:
    raw_fd, raw_path = binding.split(":", 1)
    descriptor = int(raw_fd)
    path = Path(raw_path)
    path_metadata = path.lstat()
    opened_metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(path_metadata.st_mode)
        or path_metadata.st_nlink != 1
        or path_metadata.st_uid != os.getuid()
        or stat.S_IMODE(path_metadata.st_mode) != 0o600
        or not stat.S_ISREG(opened_metadata.st_mode)
        or opened_metadata.st_nlink != 1
        or opened_metadata.st_uid != os.getuid()
        or stat.S_IMODE(opened_metadata.st_mode) != 0o600
        or (opened_metadata.st_dev, opened_metadata.st_ino)
        != (path_metadata.st_dev, path_metadata.st_ino)
    ):
        raise SystemExit(f"promotion transaction lock fd {descriptor} is invalid")
    if not hasattr(os, "O_NOFOLLOW"):
        raise SystemExit("promotion transaction lock validation requires O_NOFOLLOW")
    probe = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
        else:
            fcntl.flock(probe, fcntl.LOCK_UN)
            raise SystemExit(f"promotion transaction lock fd {descriptor} is not locked")
    finally:
        os.close(probe)
PY
}
bootstrap_promotion_transaction_locks() {
  INSIGHTS_PROMOTION_LOCKS_BOOTSTRAPPED=1 python3 - \
    "$RUNNER_SOURCE" \
    "$ARCHIVE" "$ARCHIVE_SHA" "$PACKET" "$PACKET_SHA" "$PERMIT" "$PERMIT_SHA" \
    "$RELEASE_SHA" "$EXPECTED_CURRENT" "$DATA_RELEASE_ID" \
    "$EXPECTED_CURRENT_DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_POINTER_SHA" "$TARGET_DATA_POINTER_SHA" \
    "7:${PROMOTION_LOCK}" \
    "9:${DEPLOY_LOCK}" \
    "8:${DATA_LOCK}" <<'PY'
import errno
import fcntl
import os
from pathlib import Path
import stat
import sys

script = sys.argv[1]
arguments = sys.argv[2:14]
bindings = sys.argv[14:]
if len(arguments) != 12 or len(bindings) != 3:
    raise SystemExit("promotion lock bootstrap argument contract mismatch")
opened = []
try:
    for binding in bindings:
        raw_fd, raw_path = binding.split(":", 1)
        target_fd = int(raw_fd)
        path = Path(raw_path)
        if not hasattr(os, "O_NOFOLLOW"):
            raise SystemExit("promotion transaction locks require O_NOFOLLOW")
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
        if (
            not stat.S_ISREG(path_metadata.st_mode)
            or path_metadata.st_nlink != 1
            or path_metadata.st_uid != os.getuid()
            or stat.S_IMODE(path_metadata.st_mode) != 0o600
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (metadata.st_dev, metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise SystemExit(f"promotion transaction lock is unsafe: {path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise SystemExit(f"promotion transaction lock is already held: {path}") from exc
            raise
        os.dup2(descriptor, target_fd, inheritable=True)
        if descriptor != target_fd:
            os.close(descriptor)
        os.set_inheritable(target_fd, True)
        opened.append(target_fd)
    environment = dict(os.environ)
    environment["INSIGHTS_PROMOTION_LOCKS_BOOTSTRAPPED"] = "1"
    os.execve("/bin/bash", ["bash", script, *arguments], environment)
finally:
    for descriptor in opened:
        try:
            os.close(descriptor)
        except OSError:
            pass
PY
}
write_journal() {
  local phase="$1"
  local original_previous="$2"
  python3 - "$JOURNAL" "$phase" "$PACKET_SHA" "$PERMIT_SHA" "$RELEASE_SHA" "$TARGET_IMAGE_ID" "$EXPECTED_CURRENT" "$DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_RELEASE_ID" "$TARGET_DATA_POINTER_SHA" "$EXPECTED_CURRENT_DATA_POINTER_SHA" "$original_previous" "$TRANSACTION_STARTED_AT_UTC" "$COLLECTOR_ID" "$COLLECTOR_RESTART" "$TRANSLATION_ID" "$TRANSLATION_RESTART" "$NGINX_SHA" "$CRON_SHA" "$INVENTORY_COUNT" "$INVENTORY_SHA" "$PRODUCTION_BASELINE_CAS_SHA" "$PACKET" "$EXPECTED_OLD_RELEASE_MANIFEST_SHA" "$EXPECTED_OLD_RELEASE_SHA256SUMS_SHA" "$EXPECTED_OLD_DATA_INVENTORY_SHA" "$EXPECTED_OLD_DATA_FILE_COUNT" "$EXPECTED_OLD_DATA_TOTAL_BYTES" <<'PY'
import hashlib
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

(path_value, phase, packet, permit, release, target_image_id, previous_release, data_release,
 previous_data_release, data_pointer, previous_data_pointer,
 original_previous, transaction_started, collector, collector_restart,
 translation, translation_restart, nginx, cron, protected_inventory_count,
 protected_inventory_sha, production_baseline_cas_sha, packet_path,
 old_release_manifest_sha,
 old_release_sha256sums_sha, old_data_inventory_sha, old_data_file_count,
 old_data_total_bytes) = sys.argv[1:]
path = Path(path_value)
if phase not in {"prepared", "data_committed", "site_committed", "complete"}:
    raise SystemExit("promotion journal phase invalid")
packet_raw = Path(packet_path).read_bytes()
packet_value = json.loads(packet_raw)
if packet_raw != json.dumps(
    packet_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode() + b"\n":
    raise SystemExit("promotion packet is noncanonical while writing journal")
production_cas = packet_value.get("production_baseline_cas")
if not isinstance(production_cas, dict):
    raise SystemExit("production baseline CAS is absent while writing journal")
observed_cas_sha = hashlib.sha256(
    json.dumps(
        production_cas, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
).hexdigest()
if observed_cas_sha != production_baseline_cas_sha:
    raise SystemExit("production baseline CAS changed while writing journal")
if (
    collector != production_cas["collector"]["container_id"]
    or int(collector_restart) != production_cas["collector"]["restart_count"]
    or translation != production_cas["translation"]["container_id"]
    or int(translation_restart) != production_cas["translation"]["restart_count"]
    or nginx != production_cas["shared_nginx_sha256"]
    or cron != production_cas["cron_sha256"]
    or int(protected_inventory_count)
    != production_cas["container_inventory"]["protected_count"]
    or protected_inventory_sha
    != production_cas["container_inventory"]["protected_sha256"]
):
    raise SystemExit("transaction baseline differs from owner-authorized CAS")
if path.exists() or path.is_symlink():
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise SystemExit("promotion journal is unsafe")
value = {
    "collector_id": production_cas["collector"]["container_id"],
    "collector_restart_count": production_cas["collector"]["restart_count"],
    "container_inventory_sha256": production_cas["container_inventory"]["sha256"],
    "cron_sha256": production_cas["cron_sha256"],
    "database_identity": production_cas["database_identity"],
    "data_pointer_sha256": data_pointer,
    "data_release_id": data_release,
    "expected_current_data_pointer_sha256": previous_data_pointer,
    "expected_current_data_release_id": previous_data_release,
    "expected_current_release_sha256": previous_release,
    "original_previous_data_target": original_previous,
    "previous_release_manifest_sha256": old_release_manifest_sha,
    "previous_release_sha256s_sha256": old_release_sha256sums_sha,
    "previous_data_inventory_sha256": old_data_inventory_sha,
    "previous_data_file_count": int(old_data_file_count),
    "previous_data_total_bytes": int(old_data_total_bytes),
    "packet_sha256": packet,
    "permit_sha256": permit,
    "phase": phase,
    "production_baseline_cas": production_cas,
    "production_baseline_cas_sha256": production_baseline_cas_sha,
    "release_sha256": release,
    "target_image_id": target_image_id,
    "report_pointer_identity": production_cas["report_pointer_identity"],
    "schema_version": "reddit_voc_promotion_transaction_v3",
    "shared_nginx_sha256": production_cas["shared_nginx_sha256"],
    "transaction_started_at_utc": transaction_started,
    "translation_id": production_cas["translation"]["container_id"],
    "translation_restart_count": production_cas["translation"]["restart_count"],
    "unrelated_container_inventory_count": int(protected_inventory_count),
    "unrelated_container_inventory_sha256": protected_inventory_sha,
}
payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(temporary, flags, 0o600)
try:
    with os.fdopen(descriptor, "wb", closefd=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
finally:
    os.close(descriptor)
os.replace(temporary, path)
directory = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}
remove_journal() {
  python3 - "$JOURNAL" <<'PY'
import os
from pathlib import Path
import stat
import sys

path = Path(sys.argv[1])
if path.exists() or path.is_symlink():
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise SystemExit("promotion journal is unsafe")
    path.unlink()
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
PY
}
find_exact_promotion_receipt() {
  python3 - "${DEPLOY_ROOT}/evidence" "$RELEASE_SHA" "$TARGET_IMAGE_ID" "$EXPECTED_CURRENT" "$PACKET_SHA" "$PERMIT_SHA" "$DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_POINTER_SHA" "$TARGET_DATA_POINTER_SHA" "$DATA_INVENTORY_SHA" "$DATA_FILE_COUNT" "$DATA_TOTAL_BYTES" "$COLLECTOR_ID" "$COLLECTOR_RESTART" "$TRANSLATION_ID" "$TRANSLATION_RESTART" "$NGINX_SHA" "$CRON_SHA" "$(id -u)" <<'PY'
import json
import os
from pathlib import Path
import stat
import sys

(root_value, release, target_image_id, previous, packet, permit, data_release,
 previous_data_release, previous_data_pointer, data_pointer, data_inventory,
 data_file_count, data_total_bytes, collector, collector_restart, translation,
 translation_restart, nginx, cron, owner_value) = sys.argv[1:]
root = Path(root_value)
owner = int(owner_value)
if root.is_symlink() or not root.is_dir():
    raise SystemExit("promotion evidence directory is unsafe")
matches = []
for path in root.glob(f"promotion-*-{release}.json"):
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != owner
        or metadata.st_mode & 0o077
    ):
        raise SystemExit("matching promotion receipt is unsafe")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or opened.st_nlink != 1
            or opened.st_uid != owner
            or opened.st_mode & 0o077
        ):
            raise SystemExit("matching promotion receipt changed while opening")
        raw = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            raw += chunk
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or len(raw) != opened.st_size
        ):
            raise SystemExit("matching promotion receipt changed while reading")
    finally:
        os.close(descriptor)
    value = json.loads(raw)
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if raw != canonical:
        raise SystemExit("matching promotion receipt is noncanonical")
    identity = {
        "schema_version": "reddit_voc_remote_promotion_receipt_v2",
        "release_sha256": release,
        "target_image_id": target_image_id,
        "previous_release_sha256": previous,
        "packet_sha256": packet,
        "permit_sha256": permit,
        "data_release_id": data_release,
        "previous_data_release_id": previous_data_release,
        "previous_data_pointer_sha256": previous_data_pointer,
        "data_pointer_sha256": data_pointer,
        "data_inventory_sha256": data_inventory,
        "data_file_count": int(data_file_count),
        "data_total_bytes": int(data_total_bytes),
        "collector_id": collector,
        "collector_restart_count": int(collector_restart),
        "translation_id": translation,
        "translation_restart_count": int(translation_restart),
        "nginx_sha256": nginx,
        "cron_sha256": cron,
        "candidate_exports_validation_bound": True,
        "status": "promoted_pending_public_acceptance",
        "four_exports_complete": False,
    }
    if all(value.get(key) == expected for key, expected in identity.items()):
        matches.append(path)
    else:
        raise SystemExit("conflicting promotion receipt exists for target release")
if len(matches) > 1:
    raise SystemExit("duplicate exact promotion receipts exist")
if matches:
    print(matches[0])
PY
}
write_promotion_receipt() {
  python3 - "$EVIDENCE" "$RELEASE_SHA" "$TARGET_IMAGE_ID" "$EXPECTED_CURRENT" "$PACKET_SHA" "$PERMIT_SHA" "$DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_POINTER_SHA" "$TARGET_DATA_POINTER_SHA" "$DATA_INVENTORY_SHA" "$DATA_FILE_COUNT" "$DATA_TOTAL_BYTES" "$COLLECTOR_ID" "$COLLECTOR_RESTART" "$TRANSLATION_ID" "$TRANSLATION_RESTART" "$NGINX_SHA" "$CRON_SHA" <<'PY'
import ctypes
import errno
import json
import os
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
(path, release, target_image_id, previous, packet, permit, data_release, previous_data_release,
 previous_data_pointer_sha, data_pointer_sha, data_inventory_sha, data_file_count,
 data_total_bytes, collector, collector_restart,
 translation, translation_restart, nginx, cron) = sys.argv[1:]
value={"candidate_18339_smoke":True,"candidate_exports_validation_bound":True,"collector_id":collector,"collector_restart_count":int(collector_restart),"cron_sha256":cron,"data_file_count":int(data_file_count),"data_inventory_sha256":data_inventory_sha,"data_pointer_sha256":data_pointer_sha,"data_release_id":data_release,"data_total_bytes":int(data_total_bytes),"database_write":False,"evidence_grade":"L4-authorized-live","four_exports_complete":False,"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"live_send":False,"nginx_sha256":nginx,"packet_sha256":packet,"permit_sha256":permit,"previous_data_pointer_sha256":previous_data_pointer_sha,"previous_data_release_id":previous_data_release,"previous_release_sha256":previous,"production_container_smoke":True,"provider_call":False,"release_sha256":release,"schema_version":"reddit_voc_remote_promotion_receipt_v2","shared_nginx_modified":False,"status":"promoted_pending_public_acceptance","target_image_id":target_image_id,"translation_id":translation,"translation_restart_count":int(translation_restart)}
target=Path(path)
payload=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode()+b"\n"
if not hasattr(os,"O_NOFOLLOW"):
    raise SystemExit("promotion receipt requires O_NOFOLLOW")
directory_fd=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
temporary_name=f".{target.name}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
fd=None
opened=None

def rename_noreplace(source, destination, directory):
    library=ctypes.CDLL(None,use_errno=True)
    source_bytes=os.fsencode(source)
    destination_bytes=os.fsencode(destination)
    if sys.platform.startswith("linux") and hasattr(library,"renameat2"):
        result=library.renameat2(directory,source_bytes,directory,destination_bytes,1)
    elif sys.platform == "darwin" and hasattr(library,"renameatx_np"):
        result=library.renameatx_np(directory,source_bytes,directory,destination_bytes,0x00000004)
    else:
        raise SystemExit("atomic no-replace rename is unavailable")
    if result != 0:
        error=ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error,os.strerror(error),destination)
        raise OSError(error,os.strerror(error),destination)

try:
    directory=os.fstat(directory_fd)
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid() or directory.st_mode & 0o022:
        raise SystemExit("promotion receipt directory is unsafe")
    fd=os.open(temporary_name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory_fd)
    opened=os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o600:
        raise SystemExit("promotion receipt temporary file is unsafe")
    with os.fdopen(fd,"wb",closefd=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary=os.stat(temporary_name,dir_fd=directory_fd,follow_symlinks=False)
    if (temporary.st_dev,temporary.st_ino) != (opened.st_dev,opened.st_ino):
        raise SystemExit("promotion receipt temporary path changed")
    rename_noreplace(temporary_name,target.name,directory_fd)
    os.fsync(directory_fd)
    verification_fd=os.open(target.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
    try:
        verified=os.fstat(verification_fd)
        verified_payload=b""
        while chunk := os.read(verification_fd,1024*1024):
            verified_payload += chunk
        verified_after=os.fstat(verification_fd)
        if (
            (verified.st_dev,verified.st_ino) != (opened.st_dev,opened.st_ino)
            or verified.st_nlink != 1
            or verified.st_uid != os.getuid()
            or stat.S_IMODE(verified.st_mode) != 0o600
            or verified_payload != payload
            or verified_after.st_size != verified.st_size
            or verified_after.st_mtime_ns != verified.st_mtime_ns
        ):
            raise SystemExit("promotion receipt final verification failed")
    finally:
        os.close(verification_fd)
except BaseException:
    if opened is not None:
        for candidate in (target.name,temporary_name):
            try:
                metadata=os.stat(candidate,dir_fd=directory_fd,follow_symlinks=False)
                if (metadata.st_dev,metadata.st_ino) == (opened.st_dev,opened.st_ino):
                    os.unlink(candidate,dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
    raise
finally:
    if fd is not None:
        os.close(fd)
    os.close(directory_fd)
print(path)
PY
}
verify_owner_authorized_production_baseline() {
  python3 - "$PACKET" \
    "7:${PROMOTION_LOCK}" \
    "9:${DEPLOY_LOCK}" \
    "8:${DATA_LOCK}" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

packet_path = Path(sys.argv[1])
lock_bindings = sys.argv[2:]

def command(*arguments: str) -> str:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

def container_health(value: dict[str, object]) -> str:
    state = value.get("State")
    if not isinstance(state, dict):
        raise SystemExit("owner-authorized baseline container state is invalid")
    health = state.get("Health")
    if isinstance(health, dict):
        status_value = health.get("Status")
    else:
        status_value = state.get("Status")
    if not isinstance(status_value, str):
        raise SystemExit("owner-authorized baseline container health is invalid")
    return status_value

def container_summary(value: dict[str, object]) -> dict[str, object]:
    container_id = value.get("Id")
    restart_count = value.get("RestartCount")
    if not isinstance(container_id, str) or type(restart_count) is not int:
        raise SystemExit("owner-authorized baseline container identity is invalid")
    return {
        "container_id": container_id,
        "health": container_health(value),
        "restart_count": restart_count,
    }

def file_identity(path: Path) -> str:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return "absent"
    return f"{metadata.st_mtime_ns}:{metadata.st_size}:{metadata.st_ino}"

def container_inventories() -> dict[str, object]:
    output = command("docker", "container", "ls", "-a", "-q", "--no-trunc")
    identifiers = sorted(line for line in output.splitlines() if line)
    if not identifiers:
        raise SystemExit("owner-authorized container inventory is empty")
    inspected = json.loads(command("docker", "inspect", *identifiers))
    if not isinstance(inspected, list) or len(inspected) != len(identifiers):
        raise SystemExit("owner-authorized container inventory is invalid")
    rows: list[str] = []
    protected_rows: list[str] = []
    for value in inspected:
        if not isinstance(value, dict):
            raise SystemExit("owner-authorized container inventory row is invalid")
        state = value.get("State") or {}
        if not isinstance(state, dict):
            raise SystemExit("owner-authorized container inventory state is invalid")
        name = value.get("Name")
        row = json.dumps(
                {
                    "container_id": value.get("Id"),
                    "finished_at": state.get("FinishedAt"),
                    "name": name,
                    "restart_count": value.get("RestartCount"),
                    "started_at": state.get("StartedAt"),
                    "state": state.get("Status"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        rows.append(row)
        if name != "/reddit_voc_insights_web" and not (
            isinstance(name, str)
            and name.startswith("/reddit_voc_insights_candidate_")
        ):
            protected_rows.append(row)
    rows.sort()
    protected_rows.sort()
    return {
        "count": len(rows),
        "protected_count": len(protected_rows),
        "protected_sha256": hashlib.sha256(
            ("\n".join(protected_rows) + "\n").encode()
        ).hexdigest(),
        "sha256": hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
    }

packet = json.loads(packet_path.read_bytes())
expected = packet.get("production_baseline_cas")
if not isinstance(expected, dict):
    raise SystemExit("owner-authorized production baseline CAS is absent")

named_values = json.loads(
    command(
        "docker",
        "inspect",
        "reddit_voc_site_app",
        "reddit_voc_libretranslate",
        "reddit_voc_insights_web",
    )
)
if not isinstance(named_values, list) or len(named_values) != 3:
    raise SystemExit("owner-authorized named container observation is invalid")
containers: dict[str, dict[str, object]] = {}
for value in named_values:
    if not isinstance(value, dict) or not isinstance(value.get("Name"), str):
        raise SystemExit("owner-authorized named container observation is invalid")
    containers[value["Name"].removeprefix("/")] = value
if set(containers) != {
    "reddit_voc_site_app",
    "reddit_voc_libretranslate",
    "reddit_voc_insights_web",
}:
    raise SystemExit("owner-authorized named container set changed")

network_values = json.loads(
    command("docker", "network", "inspect", "reddit_voc_insights_net")
)
if (
    not isinstance(network_values, list)
    or len(network_values) != 1
    or not isinstance(network_values[0], dict)
    or not isinstance(network_values[0].get("Id"), str)
):
    raise SystemExit("owner-authorized insights network observation is invalid")

lock_identities: dict[str, dict[str, object]] = {}
for binding in lock_bindings:
    raw_fd, raw_path = binding.split(":", 1)
    descriptor = int(raw_fd)
    path = Path(raw_path)
    opened = os.fstat(descriptor)
    observed = path.lstat()
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(observed.st_mode)
        or opened.st_nlink != 1
        or observed.st_nlink != 1
        or opened.st_uid != os.getuid()
        or observed.st_uid != os.getuid()
        or stat.S_IMODE(opened.st_mode) != 0o600
        or stat.S_IMODE(observed.st_mode) != 0o600
        or (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino)
    ):
        raise SystemExit(f"owner-authorized lock identity is unsafe: {path}")
    name = {
        ".promotion.lock": "promotion",
        ".deploy.lock": "deploy",
        "data-release.lock": "data_release",
    }.get(path.name)
    if name is None or name in lock_identities:
        raise SystemExit("owner-authorized lock binding set is invalid")
    lock_identities[name] = {
        "device": opened.st_dev,
        "inode": opened.st_ino,
        "mode": "0600",
        "nlink": opened.st_nlink,
        "path": str(path),
        "uid": opened.st_uid,
    }

container_inventory = container_inventories()
insights = containers["reddit_voc_insights_web"]
insights_summary = container_summary(insights)
image_id = insights.get("Image")
if not isinstance(image_id, str):
    raise SystemExit("owner-authorized insights image identity is invalid")
network_settings = insights.get("NetworkSettings")
attachments = (
    network_settings.get("Networks") if isinstance(network_settings, dict) else None
)
if (
    not isinstance(attachments, dict)
    or set(attachments) != {"reddit_voc_insights_net"}
    or not isinstance(attachments["reddit_voc_insights_net"], dict)
    or attachments["reddit_voc_insights_net"].get("NetworkID")
    != network_values[0]["Id"]
):
    raise SystemExit("owner-authorized insights network attachment changed")
actual = {
    "collector": container_summary(containers["reddit_voc_site_app"]),
    "container_inventory": container_inventory,
    "cron_sha256": command(
        "sudo", "-n", "sha256sum", "/etc/cron.d/reddit-voc-site"
    ).split()[0],
    "database_identity": file_identity(
        Path("/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3")
    ),
    "insights": {
        **insights_summary,
        "image_id": image_id,
        "network_id": network_values[0]["Id"],
    },
    "lock_identities": lock_identities,
    # The observation timestamp identifies the authorized snapshot.  Runtime
    # equality applies to every mutable identity, not to wall-clock time.
    "observed_at_utc": expected.get("observed_at_utc"),
    "report_pointer_identity": file_identity(Path("/opt/reddit-voc-report/current")),
    "shared_nginx_sha256": hashlib.sha256(
        Path("/opt/ai-video/deploy/lighthouse/nginx.conf").read_bytes()
    ).hexdigest(),
    "translation": container_summary(containers["reddit_voc_libretranslate"]),
}
if actual != expected:
    changed = sorted(
        key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key)
    )
    raise SystemExit(
        "owner-authorized production baseline CAS mismatch: " + ",".join(changed)
    )
subprocess.run(
    ("curl", "-fsS", "http://127.0.0.1:18337/api/health"),
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
PY
}
verify_control_plane_baseline_unchanged() {
  local file_identities
  validate_promotion_transaction_locks
  [[ "$(docker inspect -f '{{.Id}}' reddit_voc_site_app)" == "$COLLECTOR_ID" && "$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)" == "$COLLECTOR_RESTART" && "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_site_app)" == healthy ]] || fail "collector changed during promotion transaction"
  [[ "$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)" == "$TRANSLATION_ID" && "$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)" == "$TRANSLATION_RESTART" && "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_libretranslate)" == healthy ]] || fail "translation changed during promotion transaction"
  [[ "$(sha256sum /opt/ai-video/deploy/lighthouse/nginx.conf | awk '{print $1}')" == "$NGINX_SHA" ]] || fail "shared nginx changed during promotion transaction"
  [[ "$(sudo sha256sum /etc/cron.d/reddit-voc-site | awk '{print $1}')" == "$CRON_SHA" ]] || fail "cron changed during promotion transaction"
  [[ "$(inventory_identity)" == "$INVENTORY_COUNT"$'\t'"$INVENTORY_SHA" ]] || fail "protected container inventory changed during promotion transaction"
  file_identities="$(python3 - <<'PY'
from pathlib import Path

def identity(path: Path) -> str:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return "absent"
    return f"{metadata.st_mtime_ns}:{metadata.st_size}:{metadata.st_ino}"

print(
    identity(Path("/opt/reddit-voc-site/data/reddit_voc_daily.sqlite3")),
    identity(Path("/opt/reddit-voc-report/current")),
    sep="\t",
)
PY
)" || fail "database/report identity observation failed"
  [[ "$file_identities" == "$DATABASE_IDENTITY"$'\t'"$REPORT_POINTER_IDENTITY" ]] || fail "database or report pointer changed during promotion transaction"
}
verify_committed_site_release_for_recovery() {
  local target_release_path="${1:-$DEPLOY_ROOT/releases/$RELEASE_SHA}"
  python3 - "$TEMP_ROOT" "$target_release_path" "$(id -u)" <<'PY'
import hashlib
import os
from pathlib import Path
import stat
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
owner = int(sys.argv[3])
if source.is_symlink() or not source.is_dir() or target.is_symlink() or not target.is_dir():
    raise SystemExit("interrupted site release roots are unsafe")

def inventory(root: Path, *, require_immutable: bool) -> tuple[set[str], dict[str, tuple[str, int]]]:
    directories = {"."}
    files = {}
    for current, names, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        metadata = current_path.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise SystemExit("interrupted site release contains an unsafe directory")
        if require_immutable and (metadata.st_uid != owner or metadata.st_mode & 0o022):
            raise SystemExit("committed site release directory ownership or mode mismatch")
        for name in names:
            path = current_path / name
            item = path.lstat()
            if not stat.S_ISDIR(item.st_mode):
                raise SystemExit("interrupted site release contains a link or special directory entry")
            directories.add(path.relative_to(root).as_posix())
        for name in filenames:
            path = current_path / name
            before = path.lstat()
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or (require_immutable and (before.st_uid != owner or before.st_mode & 0o022))
            ):
                raise SystemExit("interrupted site release contains an unsafe file")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(descriptor)
                if (
                    (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                    or opened.st_nlink != 1
                ):
                    raise SystemExit("interrupted site release file changed while opening")
                digest = hashlib.sha256()
                size = 0
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                after = os.fstat(descriptor)
                if (
                    after.st_size != opened.st_size
                    or after.st_mtime_ns != opened.st_mtime_ns
                    or size != opened.st_size
                ):
                    raise SystemExit("interrupted site release file changed while hashing")
            finally:
                os.close(descriptor)
            files[path.relative_to(root).as_posix()] = (digest.hexdigest(), size)
    return directories, files

source_inventory = inventory(source, require_immutable=False)
target_inventory = inventory(target, require_immutable=True)
if source_inventory != target_inventory:
    raise SystemExit("committed site release differs from the exact authorized archive")
PY
}
verify_interrupted_site_runtime_contract() {
  local expected_release="${1:-$RELEASE_SHA}" expected_image="${2:-$IMAGE}" required_image_id="${3:-}" required_network_id="${4:-}"
  local image_id image_json container_json listener_addresses network_contract network_id
  image_id="$(docker image inspect -f '{{.Id}}' "$expected_image")" || fail "interrupted site image is missing"
  [[ -z "$required_image_id" || "$image_id" == "$required_image_id" ]] || fail "interrupted site image ID differs from the authorized archive"
  image_json="$(docker image inspect "$expected_image")" || fail "interrupted site image inspect failed"
  python3 - "$expected_release" "$image_json" <<'PY'
import json
import sys

values = json.loads(sys.argv[2])
if len(values) != 1:
    raise SystemExit("interrupted site image inspect cardinality mismatch")
image = values[0]
config = image.get("Config") or {}
labels = config.get("Labels") or {}
if (
    image.get("Architecture") != "amd64"
    or config.get("User") != "101:101"
    or labels.get("com.reddit-voc.release") != sys.argv[1]
):
    raise SystemExit("interrupted site image contract mismatch")
PY
  network_id="$(docker network inspect -f '{{.Id}}' "$NETWORK")" || fail "interrupted site network inspect failed"
  [[ -z "$required_network_id" || "$network_id" == "$required_network_id" ]] || fail "interrupted site network ID differs from the owner-authorized baseline"
  container_json="$(docker inspect reddit_voc_insights_web)" || fail "interrupted site container inspect failed"
  python3 - "$expected_release" "$expected_image" "$image_id" "$DATA_ROOT" "$BIND_ADDRESS" "$network_id" "$container_json" <<'PY'
import json
import sys

release, image_ref, image_id, data_root, bind_address, network_id, raw = sys.argv[1:]
values = json.loads(raw)
if len(values) != 1:
    raise SystemExit("interrupted site container inspect cardinality mismatch")
container = values[0]
config = container.get("Config") or {}
host = container.get("HostConfig") or {}
state = container.get("State") or {}
network = container.get("NetworkSettings") or {}
labels = config.get("Labels") or {}
health = state.get("Health") or {}
mounts = container.get("Mounts") or []
networks = network.get("Networks") or {}
ports = network.get("Ports") or {}
bindings = host.get("PortBindings") or {}
tmpfs = host.get("Tmpfs") or {}
tmpfs_options = set(filter(None, str(tmpfs.get("/tmp", "")).split(",")))
expected_tmpfs = {
    "rw", "noexec", "nosuid", "nodev", "size=32m",
    "uid=101", "gid=101", "mode=1777",
}
if (
    config.get("Image") != image_ref
    or container.get("Image") != image_id
    or config.get("User") != "101:101"
    or labels.get("com.reddit-voc.component") != "insights-site"
    or labels.get("com.reddit-voc.release") != release
    or state.get("Running") is not True
    or health.get("Status") != "healthy"
    or host.get("ReadonlyRootfs") is not True
    or host.get("Privileged") is not False
    or host.get("CapAdd") not in (None, [])
    or host.get("Init") is not True
    or host.get("CapDrop") != ["ALL"]
    or host.get("SecurityOpt") != ["no-new-privileges:true"]
    or host.get("PidsLimit") != 100
    or host.get("Memory") != 268435456
    or host.get("NanoCpus") != 500000000
    or (host.get("RestartPolicy") or {}).get("Name") != "unless-stopped"
    or host.get("NetworkMode") != "reddit_voc_insights_net"
    or set(tmpfs) != {"/tmp"}
    or tmpfs_options != expected_tmpfs
    or set(networks) != {"reddit_voc_insights_net"}
    or (networks.get("reddit_voc_insights_net") or {}).get("NetworkID")
    != network_id
    or len(mounts) != 1
):
    raise SystemExit("interrupted site container runtime contract mismatch")
mount = mounts[0]
if (
    mount.get("Type") != "bind"
    or mount.get("Source") != data_root
    or mount.get("Destination") != "/srv/reddit-voc-data"
    or mount.get("RW") is not False
    or mount.get("Propagation") != "rprivate"
):
    raise SystemExit("interrupted site container data mount mismatch")
expected_binding = [{"HostIp": bind_address, "HostPort": "18338"}]
if ports != {"8080/tcp": expected_binding} or bindings != {"8080/tcp": expected_binding}:
    raise SystemExit("interrupted site container port binding mismatch")
PY
  network_contract="$(docker network inspect -f '{{.Internal}}|{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}|{{index .Options "com.docker.network.bridge.enable_icc"}}' "$NETWORK")"
  [[ "$network_contract" == "false|false|false" ]] || fail "interrupted site network isolation contract mismatch"
  listener_addresses="$(ss -H -ltn | awk -v suffix=":18338" 'index($4, suffix) == length($4) - length(suffix) + 1 {print $4}' | sort -u)"
  [[ "$listener_addresses" == "$BIND_ADDRESS:18338" ]] || fail "interrupted site listener contract mismatch"
  if docker exec reddit_voc_insights_web wget -q -T 3 -O /dev/null "http://$BIND_ADDRESS:18337/api/health" 2>/dev/null; then
    fail "interrupted site container unexpectedly reached the collector listener"
  fi
}
expected_image_id_from_archive() {
  local archive_path="$1" image_ref="$2"
  python3 - "$archive_path" "$image_ref" <<'PY'
import hashlib
import json
import re
import sys
import tarfile

archive, image_ref = sys.argv[1:]
with tarfile.open(archive, "r:") as handle:
    members = handle.getmembers()
    names = [member.name for member in members]
    if len(names) != len(set(names)) or names.count("manifest.json") != 1:
        raise SystemExit("candidate image archive manifest is ambiguous")
    manifest_member = handle.getmember("manifest.json")
    if not manifest_member.isfile():
        raise SystemExit("candidate image archive manifest is unsafe")
    manifest_stream = handle.extractfile(manifest_member)
    if manifest_stream is None:
        raise SystemExit("candidate image archive manifest is unreadable")
    manifest = json.loads(manifest_stream.read())
    if len(manifest) != 1:
        raise SystemExit("candidate image archive cardinality mismatch")
    record = manifest[0]
    config_name = record.get("Config")
    tags = record.get("RepoTags")
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
        or tags != [image_ref]
        or names.count(config_name) != 1
    ):
        raise SystemExit("candidate image archive identity mismatch")
    config_member = handle.getmember(config_name)
    if not config_member.isfile():
        raise SystemExit("candidate image archive config is unsafe")
    config_stream = handle.extractfile(config_member)
    if config_stream is None:
        raise SystemExit("candidate image archive config is unreadable")
    config = config_stream.read()
    digest = hashlib.sha256(config).hexdigest()
    if digest != (config_match.group(1) or config_match.group(2)):
        raise SystemExit("candidate image archive config digest mismatch")
print(f"sha256:{digest}")
PY
}
expected_candidate_image_id_from_archive() {
  expected_image_id_from_archive "$TEMP_ROOT/reddit-voc-insights-${RELEASE_SHA}.tar" "$IMAGE"
}
validate_recovery_candidate_stage() {
  local stage="$1" require_complete="${2:-1}" first second
  python3 - "$stage" "$RELEASE_SHA" "$DATA_RELEASE_ID" "$(id -u)" "$require_complete" <<'PY'
import os
from pathlib import Path
import re
import stat
import sys

raw, release, data_release, owner_value, require_complete_value = sys.argv[1:]
owner = int(owner_value)
require_complete = require_complete_value == "1"
if re.fullmatch(rf"/opt/\.reddit-voc-insights-data-{release[:12]}\.[0-9]+", raw) is None:
    raise SystemExit("candidate recovery data stage path is invalid")
root = Path(raw)
metadata = root.lstat()
if (
    not stat.S_ISDIR(metadata.st_mode)
    or metadata.st_uid != owner
    or metadata.st_mode & 0o022
):
    raise SystemExit("candidate recovery data stage is unsafe")
entries = {path.name: path for path in root.iterdir()}
if "releases" not in entries or not set(entries).issubset({"current", "releases"}):
    raise SystemExit("candidate recovery data stage top-level inventory mismatch")
releases = entries["releases"]
current = entries.get("current")
if current is not None and (
    not current.is_symlink()
    or os.readlink(current) != f"releases/{data_release}"
):
    raise SystemExit("candidate recovery data stage pointer mismatch")
if require_complete and current is None:
    raise SystemExit("candidate recovery complete data stage pointer is missing")
release_metadata = releases.lstat()
if not stat.S_ISDIR(release_metadata.st_mode) or releases.is_symlink():
    raise SystemExit("candidate recovery releases root is unsafe")
release_entries = list(releases.iterdir())
if len(release_entries) != 1 or release_entries[0].name != data_release:
    raise SystemExit("candidate recovery releases inventory mismatch")
target = release_entries[0]
target_metadata = target.lstat()
if not stat.S_ISDIR(target_metadata.st_mode) or target.is_symlink():
    raise SystemExit("candidate recovery target data release is unsafe")
for current_root, directories, files in os.walk(target, followlinks=False):
    current_root_path = Path(current_root)
    current_metadata = current_root_path.lstat()
    if not stat.S_ISDIR(current_metadata.st_mode) or current_metadata.st_uid != owner:
        raise SystemExit("candidate recovery data stage directory is unsafe")
    for name in [*directories, *files]:
        path = current_root_path / name
        item = path.lstat()
        if (
            stat.S_ISLNK(item.st_mode)
            or not (stat.S_ISDIR(item.st_mode) or stat.S_ISREG(item.st_mode))
            or item.st_uid != owner
            or (stat.S_ISREG(item.st_mode) and item.st_nlink != 1)
        ):
            raise SystemExit("candidate recovery data stage contains an unsafe entry")
PY
  if [[ "$require_complete" == 1 ]]; then
    first="$(verify_exact_data_projection "$stage/releases/$DATA_RELEASE_ID/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "candidate recovery data stage inventory mismatch"
    second="$(verify_exact_data_projection "$stage/releases/$DATA_RELEASE_ID/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "candidate recovery data stage TOCTOU validation failed"
    [[ "$first" == "$second" ]] || fail "candidate recovery data stage changed during validation"
  fi
}
cleanup_exact_recovery_candidate_and_stage() {
  local candidate_present extract_present verify_present candidate_json candidate_values expected_image_id candidate_stage="" candidate_running="false" stage_values
  local observed_candidate_count observed_port_count listener_addresses network_contract
  local expected_candidate_count=0
  local -a stages=()
  candidate_present="$(docker ps -a --filter "name=^/${CANDIDATE}$" --format '{{.Names}}')"
  extract_present="$(docker ps -a --filter "name=^/${CANDIDATE}_data_extract$" --format '{{.Names}}')"
  verify_present="$(docker ps -a --filter "name=^/${VERIFY_CONTAINER}$" --format '{{.Names}}')"
  observed_candidate_count="$(candidate_count)"
  observed_port_count="$(port_count)"
  expected_image_id="$(expected_candidate_image_id_from_archive)" || fail "candidate recovery image identity validation failed"
  [[ -z "$candidate_present" ]] || expected_candidate_count=$((expected_candidate_count + 1))
  [[ -z "$extract_present" ]] || expected_candidate_count=$((expected_candidate_count + 1))
  [[ "$observed_candidate_count" == "$expected_candidate_count" ]] || fail "candidate recovery found an unknown candidate container; no recovery write performed"
  if [[ -n "$extract_present" ]]; then
    [[ "$extract_present" == "${CANDIDATE}_data_extract" ]] || fail "candidate recovery data extractor identity mismatch"
    candidate_json="$(docker inspect "$extract_present")" || fail "candidate recovery data extractor inspect failed"
    python3 - "$candidate_json" "$IMAGE" "$expected_image_id" "$RELEASE_SHA" <<'PY'
import json
import sys

raw, image_ref, image_id, release = sys.argv[1:]
values = json.loads(raw)
if len(values) != 1:
    raise SystemExit("candidate recovery data extractor cardinality mismatch")
container = values[0]
config = container.get("Config") or {}
host = container.get("HostConfig") or {}
state = container.get("State") or {}
labels = config.get("Labels") or {}
if (
    config.get("Image") != image_id
    or container.get("Image") != image_id
    or labels.get("com.reddit-voc.release") != release
    or state.get("Status") not in {"created", "exited"}
    or container.get("Mounts") not in (None, [])
    or (host.get("PortBindings") or {})
    or (host.get("RestartPolicy") or {}).get("Name") not in {"", "no"}
):
    raise SystemExit("candidate recovery data extractor contract mismatch")
PY
  fi
  if [[ -n "$verify_present" ]]; then
    [[ "$verify_present" == "$VERIFY_CONTAINER" ]] || fail "image verifier recovery identity mismatch"
    candidate_json="$(docker inspect "$verify_present")" || fail "image verifier recovery inspect failed"
    python3 - "$candidate_json" "$IMAGE" "$expected_image_id" "$RELEASE_SHA" "$PACKET_SHA" <<'PY'
import json
import sys

raw, image_ref, image_id, release, packet = sys.argv[1:]
values = json.loads(raw)
if len(values) != 1:
    raise SystemExit("image verifier recovery cardinality mismatch")
container = values[0]
config = container.get("Config") or {}
host = container.get("HostConfig") or {}
state = container.get("State") or {}
labels = config.get("Labels") or {}
if (
    config.get("Image") != image_id
    or container.get("Image") != image_id
    or labels.get("com.reddit-voc.component") != "insights-image-verifier"
    or labels.get("com.reddit-voc.release") != release
    or labels.get("com.reddit-voc.promotion-packet") != packet
    or state.get("Status") not in {"created", "exited"}
    or container.get("Mounts") not in (None, [])
    or (host.get("PortBindings") or {})
    or (host.get("RestartPolicy") or {}).get("Name") not in {"", "no"}
):
    raise SystemExit("image verifier recovery contract mismatch")
PY
  fi
  if [[ -n "$candidate_present" ]]; then
    [[ "$candidate_present" == "$CANDIDATE" ]] || fail "candidate recovery found an unknown candidate container; no recovery write performed"
    candidate_json="$(docker inspect "$CANDIDATE")" || fail "candidate recovery inspect failed"
    candidate_values="$(python3 - "$candidate_json" "$RELEASE_SHA" "$PACKET_SHA" "$IMAGE" "$expected_image_id" "$DATA_RELEASE_ID" "$BIND_ADDRESS" "$CANDIDATE_PORT" <<'PY'
import json
import sys

(raw, release, packet, image_ref, image_id, data_release,
 bind_address, port) = sys.argv[1:]
values = json.loads(raw)
if len(values) != 1:
    raise SystemExit("candidate recovery inspect cardinality mismatch")
container = values[0]
config = container.get("Config") or {}
host = container.get("HostConfig") or {}
state = container.get("State") or {}
network = container.get("NetworkSettings") or {}
labels = config.get("Labels") or {}
mounts = container.get("Mounts") or []
networks = network.get("Networks") or {}
ports = network.get("Ports") or {}
bindings = host.get("PortBindings") or {}
tmpfs = host.get("Tmpfs") or {}
tmpfs_options = set(filter(None, str(tmpfs.get("/tmp", "")).split(",")))
expected_tmpfs = {
    "rw", "noexec", "nosuid", "nodev", "size=32m",
    "uid=101", "gid=101", "mode=1777",
}
if (
    config.get("Image") != image_id
    or container.get("Image") != image_id
    or config.get("User") != "101:101"
    or labels.get("com.reddit-voc.component") != "insights-site"
    or labels.get("com.reddit-voc.release") != release
    or labels.get("com.reddit-voc.scope") != "remote-candidate-smoke"
    or labels.get("com.reddit-voc.promotion-packet") != packet
    or state.get("Status") not in {"created", "running", "exited"}
    or host.get("ReadonlyRootfs") is not True
    or host.get("Privileged") is not False
    or host.get("CapAdd") not in (None, [])
    or host.get("Init") is not True
    or host.get("CapDrop") != ["ALL"]
    or host.get("SecurityOpt") != ["no-new-privileges:true"]
    or host.get("PidsLimit") != 100
    or host.get("Memory") != 268435456
    or host.get("NanoCpus") != 500000000
    or (host.get("RestartPolicy") or {}).get("Name") not in {"", "no"}
    or tmpfs_options != expected_tmpfs
    or set(networks) != {"reddit_voc_insights_net"}
    or len(mounts) != 1
):
    raise SystemExit("candidate recovery runtime contract mismatch")
mount = mounts[0]
if (
    mount.get("Type") != "bind"
    or mount.get("Destination") != "/srv/reddit-voc-data"
    or mount.get("RW") is not False
    or mount.get("Propagation") != "rprivate"
):
    raise SystemExit("candidate recovery mount contract mismatch")
expected_binding = [{"HostIp": bind_address, "HostPort": port}]
if bindings.get("8080/tcp") != expected_binding:
    raise SystemExit("candidate recovery configured port binding mismatch")
if state.get("Running") is True and ports.get("8080/tcp") != expected_binding:
    raise SystemExit("candidate recovery live port binding mismatch")
print(mount.get("Source", ""), str(state.get("Running") is True).lower(), sep="\t")
PY
)" || fail "candidate recovery runtime validation failed"
    IFS=$'\t' read -r candidate_stage candidate_running <<<"$candidate_values"
    validate_recovery_candidate_stage "$candidate_stage" 1
    network_contract="$(docker network inspect -f '{{.Internal}}|{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}|{{index .Options "com.docker.network.bridge.enable_icc"}}' "$NETWORK")"
    [[ "$network_contract" == "false|false|false" ]] || fail "candidate recovery network contract mismatch"
    listener_addresses="$(ss -H -ltn | awk -v suffix=":$CANDIDATE_PORT" 'index($4, suffix) == length($4) - length(suffix) + 1 {print $4}' | sort -u)"
    if [[ "$candidate_running" == true ]]; then
      [[ "$observed_port_count" == 1 && "$listener_addresses" == "$BIND_ADDRESS:$CANDIDATE_PORT" ]] || fail "candidate recovery live listener mismatch"
    else
      [[ "$observed_port_count" == 0 && -z "$listener_addresses" ]] || fail "candidate recovery stopped listener mismatch"
    fi
  else
    [[ "$observed_port_count" == 0 ]] || fail "candidate recovery found unknown slot occupancy; no recovery write performed"
  fi
  stage_values="$(python3 - "$RELEASE_SHA" "$(id -u)" <<'PY'
from pathlib import Path
import re
import stat
import sys

release, owner_value = sys.argv[1:]
owner = int(owner_value)
pattern = re.compile(rf"\.reddit-voc-insights-data-{release[:12]}\.[0-9]+")
for path in sorted(Path("/opt").iterdir()):
    if pattern.fullmatch(path.name):
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink() or metadata.st_uid != owner:
            raise SystemExit("candidate recovery stage discovery found an unsafe path")
        print(path)
PY
)" || fail "candidate recovery stage discovery failed"
  if [[ -n "$stage_values" ]]; then
    mapfile -t stages <<<"$stage_values"
  fi
  [[ "${#stages[@]}" -le 1 ]] || fail "candidate recovery found multiple data stages; no recovery write performed"
  if [[ "${#stages[@]}" == 1 ]]; then
    [[ -z "$candidate_stage" || "${stages[0]}" == "$candidate_stage" ]] || fail "candidate recovery container/stage identity mismatch; no recovery write performed"
    candidate_stage="${stages[0]}"
    if [[ -n "$candidate_present" ]]; then
      validate_recovery_candidate_stage "$candidate_stage" 1
    else
      validate_recovery_candidate_stage "$candidate_stage" 0
    fi
  elif [[ -n "$candidate_stage" ]]; then
    fail "candidate recovery mounted stage disappeared; no recovery write performed"
  fi
  if [[ -n "$candidate_present" ]]; then
    docker rm -f "$CANDIDATE" >/dev/null
  fi
  if [[ -n "$extract_present" ]]; then
    docker rm -f "$extract_present" >/dev/null
  fi
  if [[ -n "$verify_present" ]]; then
    docker rm -f "$verify_present" >/dev/null
  fi
  for _ in $(seq 1 20); do
    [[ "$(candidate_count)" == 0 && "$(port_count)" == 0 ]] && break
    sleep 1
  done
  [[ "$(candidate_count)" == 0 && "$(port_count)" == 0 ]] || fail "candidate recovery slot did not become empty"
  if [[ -n "$candidate_stage" ]]; then
    sudo rm -rf "$candidate_stage"
    fsync_directory /opt
  fi
}
verify_target_site_transition_runtime_contract() {
  local expected_release="${1:-$RELEASE_SHA}" expected_image="${2:-$IMAGE}" expected_image_id="${3:-}"
  local expected_config_image="${4:-}" image_id container_json transition_values running listener_addresses network_contract network_id
  if [[ -z "$expected_image_id" ]]; then
    expected_image_id="$(expected_candidate_image_id_from_archive)" || fail "site transition image archive validation failed"
  fi
  [[ -n "$expected_config_image" ]] || expected_config_image="$expected_image_id"
  image_id="$(docker image inspect -f '{{.Id}}' "$expected_image_id")" || fail "site transition image is missing"
  [[ "$image_id" == "$expected_image_id" ]] || fail "target transition image ID mismatch"
  [[ "$(docker image inspect -f '{{.Architecture}}|{{.Config.User}}|{{index .Config.Labels "com.reddit-voc.release"}}' "$expected_image_id")" == "amd64|101:101|$expected_release" ]] || fail "site transition image contract mismatch"
  network_id="$(docker network inspect -f '{{.Id}}' "$NETWORK")" || fail "target transition network inspect failed"
  container_json="$(docker inspect reddit_voc_insights_web)" || fail "target transition container inspect failed"
  transition_values="$(python3 - "$container_json" "$expected_release" "$expected_config_image" "$image_id" "$DATA_ROOT" "$BIND_ADDRESS" "$network_id" <<'PY'
import json
import sys

raw, release, image_ref, image_id, data_root, bind_address, network_id = sys.argv[1:]
values = json.loads(raw)
if len(values) != 1:
    raise SystemExit("target transition inspect cardinality mismatch")
container = values[0]
config = container.get("Config") or {}
host = container.get("HostConfig") or {}
state = container.get("State") or {}
network = container.get("NetworkSettings") or {}
labels = config.get("Labels") or {}
mounts = container.get("Mounts") or []
networks = network.get("Networks") or {}
ports = network.get("Ports") or {}
bindings = host.get("PortBindings") or {}
tmpfs = host.get("Tmpfs") or {}
tmpfs_options = set(filter(None, str(tmpfs.get("/tmp", "")).split(",")))
expected_tmpfs = {
    "rw", "noexec", "nosuid", "nodev", "size=32m",
    "uid=101", "gid=101", "mode=1777",
}
if (
    config.get("Image") != image_ref
    or container.get("Image") != image_id
    or config.get("User") != "101:101"
    or labels.get("com.reddit-voc.component") != "insights-site"
    or labels.get("com.reddit-voc.release") != release
    or state.get("Status") not in {"created", "running", "exited"}
    or host.get("ReadonlyRootfs") is not True
    or host.get("Privileged") is not False
    or host.get("CapAdd") not in (None, [])
    or host.get("Init") is not True
    or host.get("CapDrop") != ["ALL"]
    or host.get("SecurityOpt") != ["no-new-privileges:true"]
    or host.get("PidsLimit") != 100
    or host.get("Memory") != 268435456
    or host.get("NanoCpus") != 500000000
    or (host.get("RestartPolicy") or {}).get("Name") != "unless-stopped"
    or host.get("NetworkMode") != "reddit_voc_insights_net"
    or set(tmpfs) != {"/tmp"}
    or tmpfs_options != expected_tmpfs
    or set(networks) != {"reddit_voc_insights_net"}
    or (networks.get("reddit_voc_insights_net") or {}).get("NetworkID")
    != network_id
    or len(mounts) != 1
):
    raise SystemExit("target transition runtime contract mismatch")
mount = mounts[0]
if (
    mount.get("Type") != "bind"
    or mount.get("Source") != data_root
    or mount.get("Destination") != "/srv/reddit-voc-data"
    or mount.get("RW") is not False
    or mount.get("Propagation") != "rprivate"
):
    raise SystemExit("target transition mount contract mismatch")
expected_binding = [{"HostIp": bind_address, "HostPort": "18338"}]
if bindings != {"8080/tcp": expected_binding}:
    raise SystemExit("target transition configured port binding mismatch")
if state.get("Running") is True and ports != {"8080/tcp": expected_binding}:
    raise SystemExit("target transition live port binding mismatch")
if state.get("Running") is not True and ports not in (
    {}, {"8080/tcp": None}, {"8080/tcp": expected_binding}
):
    raise SystemExit("target transition stopped port binding mismatch")
health = (state.get("Health") or {}).get("Status", "missing")
print(health, str(state.get("Running") is True).lower(), sep="\t")
PY
)" || fail "target transition runtime validation failed"
  IFS=$'\t' read -r _ running <<<"$transition_values"
  network_contract="$(docker network inspect -f '{{.Internal}}|{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}|{{index .Options "com.docker.network.bridge.enable_icc"}}' "$NETWORK")"
  [[ "$network_contract" == "false|false|false" ]] || fail "target transition network isolation contract mismatch"
  listener_addresses="$(ss -H -ltn | awk -v suffix=":18338" 'index($4, suffix) == length($4) - length(suffix) + 1 {print $4}' | sort -u)"
  if [[ "$running" == true ]]; then
    [[ "$listener_addresses" == "$BIND_ADDRESS:18338" ]] || fail "target transition listener contract mismatch"
    if docker exec reddit_voc_insights_web wget -q -T 3 -O /dev/null "http://$BIND_ADDRESS:18337/api/health" 2>/dev/null; then
      fail "target transition container unexpectedly reached the collector listener"
    fi
  else
    [[ -z "$listener_addresses" ]] || fail "target transition stopped container retained a listener"
  fi
  printf '%s\n' "${transition_values%%$'\t'*}"
}
verify_old_site_release_for_recovery() {
  local old_release="$DEPLOY_ROOT/releases/$EXPECTED_CURRENT"
  [[ -d "$old_release" && ! -L "$old_release" ]] || fail "old site release is missing or unsafe"
  python3 - "$old_release" "$(id -u)" "$EXPECTED_OLD_RELEASE_MANIFEST_SHA" "$EXPECTED_OLD_RELEASE_SHA256SUMS_SHA" <<'PY'
import hashlib
import os
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1])
owner = int(sys.argv[2])
expected_manifest = sys.argv[3]
expected_sums = sys.argv[4]

def immutable_directory(metadata) -> bool:
    return (
        metadata.st_uid == owner and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o555
    )

def immutable_file(metadata) -> bool:
    return (
        metadata.st_uid == owner and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o444
    )

def authenticated_digest(path: Path, expected: str) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not immutable_file(metadata)
    ):
        raise SystemExit("old site authenticated artifact is unsafe")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or opened.st_nlink != 1
            or not immutable_file(opened)
        ):
            raise SystemExit("old site authenticated artifact changed while opening")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or size != opened.st_size
            or digest.hexdigest() != expected
        ):
            raise SystemExit("old site authenticated artifact digest mismatch")
    finally:
        os.close(descriptor)

authenticated_digest(root / "release-manifest.json", expected_manifest)
authenticated_digest(root / "SHA256SUMS", expected_sums)
for current_root, directories, files in os.walk(root, followlinks=False):
    current = Path(current_root)
    metadata = current.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or not immutable_directory(metadata):
        raise SystemExit("old site release directory is mutable or unsafe")
    for name in [*directories, *files]:
        path = current / name
        item = path.lstat()
        if stat.S_ISLNK(item.st_mode) or not (stat.S_ISDIR(item.st_mode) or stat.S_ISREG(item.st_mode)):
            raise SystemExit("old site release contains an unsafe entry")
        if stat.S_ISDIR(item.st_mode):
            immutable = immutable_directory(item)
        else:
            immutable = immutable_file(item)
        if not immutable:
            raise SystemExit("old site release entry is mutable or has wrong owner")
        if stat.S_ISREG(item.st_mode) and item.st_nlink != 1:
            raise SystemExit("old site release contains a hardlinked file")
PY
  (cd "$old_release" && sha256sum --check SHA256SUMS >/dev/null) || fail "old site release checksum validation failed"
}
restore_old_site_runtime_for_recovery() {
  local old_release="$DEPLOY_ROOT/releases/$EXPECTED_CURRENT" old_image="reddit-voc-insights:$EXPECTED_CURRENT"
  local old_image_id site_pointer container_release container_health http_release
  verify_old_site_release_for_recovery
  old_image_id="$(expected_image_id_from_archive "$old_release/reddit-voc-insights-${EXPECTED_CURRENT}.tar" "$old_image")" || fail "old site image archive validation failed"
  [[ "$(docker image inspect -f '{{.Id}}|{{.Architecture}}|{{.Config.User}}|{{index .Config.Labels "com.reddit-voc.release"}}' "$old_image")" == "$old_image_id|amd64|101:101|$EXPECTED_CURRENT" ]] || fail "old site image contract mismatch"
  verify_control_plane_baseline_unchanged
  validate_promotion_transaction_locks
  RELEASE_SHA="$EXPECTED_CURRENT" REDDIT_VOC_DATA_ROOT="$DATA_ROOT" INSIGHTS_BIND_ADDRESS="$BIND_ADDRESS" INSIGHTS_PORT=18338 \
    docker compose -p reddit_voc_insights -f "$old_release/compose.yaml" up -d --no-build --no-deps web >/dev/null
  for _ in $(seq 1 60); do
    container_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_insights_web 2>/dev/null || true)"
    container_release="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' reddit_voc_insights_web 2>/dev/null || true)"
    http_release="$(curl -fsS "http://$BIND_ADDRESS:18338/release.json" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("release_sha256", ""))' 2>/dev/null || true)"
    [[ "$container_health" == healthy && "$container_release" == "$EXPECTED_CURRENT" && "$http_release" == "$EXPECTED_CURRENT" ]] && break
    sleep 2
  done
  verify_interrupted_site_runtime_contract "$EXPECTED_CURRENT" "$old_image" "$old_image_id"
  IFS=$'\t' read -r site_pointer container_release container_health http_release < <(live_site_tuple)
  [[ "$site_pointer" == "releases/$EXPECTED_CURRENT" && "$container_release" == "$EXPECTED_CURRENT" && "$container_health" == healthy && "$http_release" == "$EXPECTED_CURRENT" ]] || fail "old site runtime recovery failed"
  verify_control_plane_baseline_unchanged
}
reconcile_committed_promotion() {
  local existing_receipt target_inventory_before target_inventory_after
  local site_pointer container_release container_health http_release
  verify_committed_site_release_for_recovery
  verify_interrupted_site_runtime_contract
  target_inventory_before="$(verify_exact_data_projection "$DATA_RELEASE_DIR/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "committed promotion target data validation failed"
  verify_control_plane_baseline_unchanged
  validate_promotion_transaction_locks
  target_inventory_after="$(verify_exact_data_projection "$DATA_RELEASE_DIR/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "committed promotion target data TOCTOU validation failed"
  [[ "$target_inventory_before" == "$target_inventory_after" ]] || fail "committed promotion target data changed during final validation"
  IFS=$'\t' read -r DATA_INVENTORY_SHA DATA_FILE_COUNT DATA_TOTAL_BYTES <<<"$target_inventory_after"
  [[ "$(pointer_state "$DATA_ROOT/current")" == "releases/$DATA_RELEASE_ID" ]] || fail "committed promotion data current pointer changed"
  [[ "$(pointer_state "$DATA_ROOT/previous")" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]] || fail "committed promotion data previous pointer changed"
  [[ "$(sha256sum "$DATA_RELEASE_DIR/public/data/reddit-voc/current-release.json" | awk '{print $1}')" == "$TARGET_DATA_POINTER_SHA" ]] || fail "committed promotion data pointer SHA mismatch"
  IFS=$'\t' read -r site_pointer container_release container_health http_release < <(live_site_tuple)
  [[ "$site_pointer" == "releases/$RELEASE_SHA" && "$container_release" == "$RELEASE_SHA" && "$container_health" == healthy && "$http_release" == "$RELEASE_SHA" ]] || fail "committed promotion site tuple changed during final validation"
  existing_receipt="$(find_exact_promotion_receipt)" || fail "committed promotion receipt validation failed"
  if [[ -n "$existing_receipt" ]]; then
    EVIDENCE="$existing_receipt"
  else
    EVIDENCE="${DEPLOY_ROOT}/evidence/promotion-$(date -u +%Y%m%dT%H%M%SZ)-${RELEASE_SHA}.json"
    write_promotion_receipt >/dev/null
  fi
  write_journal "complete" "$ORIGINAL_DATA_PREVIOUS_TARGET"
  remove_journal
  RECOVERED_EVIDENCE="$EVIDENCE"
  RECOVERED_PROMOTION=1
}
complete_interrupted_site_commit() {
  local new_inventory_before new_inventory_after site_pointer container_release container_health http_release
  verify_committed_site_release_for_recovery
  verify_interrupted_site_runtime_contract
  IFS=$'\t' read -r OLD_DATA_INVENTORY_SHA OLD_DATA_FILE_COUNT OLD_DATA_TOTAL_BYTES \
    < <(verify_old_data_projection_stable)
  new_inventory_before="$(verify_exact_data_projection "$DATA_RELEASE_DIR/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "interrupted site commit new data inventory validation failed"
  new_inventory_after="$(verify_exact_data_projection "$DATA_RELEASE_DIR/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "interrupted site commit new data TOCTOU validation failed"
  [[ "$new_inventory_before" == "$new_inventory_after" ]] || fail "interrupted site commit new data inventory changed between TOCTOU checks"
  verify_control_plane_baseline_unchanged
  validate_promotion_transaction_locks
  [[ "$(pointer_state "$DEPLOY_ROOT/current")" == "releases/$EXPECTED_CURRENT" ]] || fail "interrupted site commit pointer CAS changed"
  [[ "$(pointer_state "$DATA_ROOT/current")" == "releases/$DATA_RELEASE_ID" && "$(pointer_state "$DATA_ROOT/previous")" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]] || fail "interrupted site commit data CAS changed"
  replace_data_pointer \
    "$DEPLOY_ROOT/current" "releases/$EXPECTED_CURRENT" \
    "releases/$RELEASE_SHA" "$SITE_CURRENT_RECOVERY_TMP"
  IFS=$'\t' read -r site_pointer container_release container_health http_release < <(live_site_tuple)
  [[ "$site_pointer" == "releases/$RELEASE_SHA" && "$container_release" == "$RELEASE_SHA" && "$container_health" == healthy && "$http_release" == "$RELEASE_SHA" ]] || fail "interrupted site commit did not reach the exact new site tuple"
  SITE_COMMITTED=1
  write_journal "site_committed" "$ORIGINAL_DATA_PREVIOUS_TARGET"
  reconcile_committed_promotion
}
recover_stale_journal() {
  [[ -e "$JOURNAL" || -L "$JOURNAL" ]] || return 0
  local journal_values phase original_previous site_pointer container_release container_health http_release
  local data_current data_previous old_inventory_after current_target previous_target orphan_site_release=0 orphan_site_stage=0
  local target_inventory_before target_inventory_after
  local transition_health transition_target_before transition_target_after transition_old_inventory
  local local_old_image local_old_image_id
  journal_values="$(python3 - "$JOURNAL" "$PACKET_SHA" "$PERMIT_SHA" "$RELEASE_SHA" "$TARGET_IMAGE_ID" "$EXPECTED_CURRENT" "$DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_RELEASE_ID" "$TARGET_DATA_POINTER_SHA" "$EXPECTED_CURRENT_DATA_POINTER_SHA" "$PRODUCTION_BASELINE_CAS_SHA" "$PACKET" "$EXPECTED_OLD_RELEASE_MANIFEST_SHA" "$EXPECTED_OLD_RELEASE_SHA256SUMS_SHA" "$EXPECTED_OLD_DATA_INVENTORY_SHA" "$EXPECTED_OLD_DATA_FILE_COUNT" "$EXPECTED_OLD_DATA_TOTAL_BYTES" "$(id -u)" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from datetime import datetime

(path_value, packet, permit, release, target_image_id, previous_release, data_release,
 previous_data_release, data_pointer, previous_data_pointer,
 production_baseline_cas_sha, packet_path, old_release_manifest_sha,
 old_release_sha256s_sha, old_data_inventory_sha, old_data_file_count,
 old_data_total_bytes, owner) = sys.argv[1:]
path = Path(path_value)
packet_raw = Path(packet_path).read_bytes()
packet_value = json.loads(packet_raw)
if packet_raw != json.dumps(
    packet_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode() + b"\n":
    raise SystemExit("promotion packet is noncanonical during recovery")
production_cas = packet_value.get("production_baseline_cas")
if not isinstance(production_cas, dict) or hashlib.sha256(
    json.dumps(
        production_cas, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
).hexdigest() != production_baseline_cas_sha:
    raise SystemExit("promotion recovery packet baseline CAS mismatch")
metadata = path.lstat()
if (
    not stat.S_ISREG(metadata.st_mode)
    or metadata.st_nlink != 1
    or str(metadata.st_uid) != owner
    or metadata.st_mode & 0o077
):
    raise SystemExit("promotion journal is unsafe")
descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
try:
    opened = os.fstat(descriptor)
    if (
        (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
        or opened.st_nlink != 1
        or str(opened.st_uid) != owner
        or opened.st_mode & 0o077
    ):
        raise SystemExit("promotion journal changed while opening")
    raw = b""
    while chunk := os.read(descriptor, 1024 * 1024):
        raw += chunk
    after = os.fstat(descriptor)
    if (
        after.st_size != opened.st_size
        or after.st_mtime_ns != opened.st_mtime_ns
        or len(raw) != opened.st_size
    ):
        raise SystemExit("promotion journal changed while reading")
finally:
    os.close(descriptor)
value = json.loads(raw)
canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
if raw != canonical:
    raise SystemExit("promotion journal is noncanonical")
expected = {
    "collector_id": production_cas["collector"]["container_id"],
    "collector_restart_count": production_cas["collector"]["restart_count"],
    "container_inventory_sha256": production_cas["container_inventory"]["sha256"],
    "cron_sha256": production_cas["cron_sha256"],
    "data_pointer_sha256": data_pointer,
    "data_release_id": data_release,
    "database_identity": production_cas["database_identity"],
    "expected_current_data_pointer_sha256": previous_data_pointer,
    "expected_current_data_release_id": previous_data_release,
    "expected_current_release_sha256": previous_release,
    "packet_sha256": packet,
    "permit_sha256": permit,
    "previous_data_file_count": int(old_data_file_count),
    "previous_data_inventory_sha256": old_data_inventory_sha,
    "previous_data_total_bytes": int(old_data_total_bytes),
    "previous_release_manifest_sha256": old_release_manifest_sha,
    "previous_release_sha256s_sha256": old_release_sha256s_sha,
    "production_baseline_cas": production_cas,
    "production_baseline_cas_sha256": production_baseline_cas_sha,
    "release_sha256": release,
    "target_image_id": target_image_id,
    "report_pointer_identity": production_cas["report_pointer_identity"],
    "schema_version": "reddit_voc_promotion_transaction_v3",
    "shared_nginx_sha256": production_cas["shared_nginx_sha256"],
    "translation_id": production_cas["translation"]["container_id"],
    "translation_restart_count": production_cas["translation"]["restart_count"],
    "unrelated_container_inventory_count": production_cas["container_inventory"]["protected_count"],
    "unrelated_container_inventory_sha256": production_cas["container_inventory"]["protected_sha256"],
}
baseline_keys = {
    "transaction_started_at_utc",
}
if (
    set(value) != set(expected) | baseline_keys | {"phase", "original_previous_data_target"}
    or any(value.get(key) != item for key, item in expected.items())
):
    raise SystemExit("promotion journal belongs to a different exact transaction")
if value.get("phase") not in {"prepared", "data_committed", "site_committed", "complete"}:
    raise SystemExit("promotion journal phase invalid")
original_previous = value.get("original_previous_data_target")
if original_previous != "absent" and (
    not isinstance(original_previous, str)
    or re.fullmatch(r"releases/reddit_voc_release_[a-z0-9_-]+", original_previous) is None
):
    raise SystemExit("promotion journal previous pointer invalid")
sha = re.compile(r"^[a-f0-9]{64}$")
if (
    sha.fullmatch(str(value.get("collector_id"))) is None
    or sha.fullmatch(str(value.get("translation_id"))) is None
    or sha.fullmatch(str(value.get("container_inventory_sha256"))) is None
    or sha.fullmatch(str(value.get("cron_sha256"))) is None
    or sha.fullmatch(str(value.get("shared_nginx_sha256"))) is None
    or type(value.get("collector_restart_count")) is not int
    or value["collector_restart_count"] < 0
    or type(value.get("translation_restart_count")) is not int
    or value["translation_restart_count"] < 0
):
    raise SystemExit("promotion journal control-plane baseline invalid")
started = value.get("transaction_started_at_utc")
if not isinstance(started, str) or not started.endswith("Z"):
    raise SystemExit("promotion journal transaction start invalid")
try:
    parsed_started = datetime.fromisoformat(started.replace("Z", "+00:00"))
except ValueError as exc:
    raise SystemExit("promotion journal transaction start invalid") from exc
if parsed_started.tzinfo is None:
    raise SystemExit("promotion journal transaction start invalid")
print(
    value["phase"],
    original_previous,
    started,
    value["collector_id"],
    value["collector_restart_count"],
    value["translation_id"],
    value["translation_restart_count"],
    value["shared_nginx_sha256"],
    value["cron_sha256"],
    value["unrelated_container_inventory_count"],
    value["unrelated_container_inventory_sha256"],
    value["database_identity"],
    value["report_pointer_identity"],
    sep="\t",
)
PY
)" || fail "stale promotion journal validation failed"
  IFS=$'\t' read -r phase original_previous TRANSACTION_STARTED_AT_UTC COLLECTOR_ID COLLECTOR_RESTART TRANSLATION_ID TRANSLATION_RESTART NGINX_SHA CRON_SHA INVENTORY_COUNT INVENTORY_SHA DATABASE_IDENTITY REPORT_POINTER_IDENTITY <<<"$journal_values"
  ORIGINAL_DATA_PREVIOUS_TARGET="$original_previous"
  verify_control_plane_baseline_unchanged
  verify_old_site_release_for_recovery
  IFS=$'\t' read -r site_pointer container_release container_health http_release < <(live_site_tuple)
  data_current="$(pointer_state "$DATA_ROOT/current")"
  data_previous="$(pointer_state "$DATA_ROOT/previous")"

  if [[ "$site_pointer" == "releases/$EXPECTED_CURRENT" && "$phase" == data_committed && "$data_current" == "releases/$DATA_RELEASE_ID" && "$data_previous" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" && ( "$container_release" == "$RELEASE_SHA" || ( "$container_release" == "$EXPECTED_CURRENT" && ( "$container_health" != healthy || "$http_release" != "$EXPECTED_CURRENT" ) ) || ( -z "$container_release" && -z "$container_health" && -z "$http_release" ) ) ]]; then
    [[ "$(candidate_count)" == 0 && "$(port_count)" == 0 ]] || fail "CRITICAL: installer transition has candidate residue; no recovery write performed"
    transition_old_inventory="$(verify_old_data_projection_stable)" || fail "installer transition old data validation failed"
    transition_target_before="$(verify_exact_data_projection "$DATA_RELEASE_DIR/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "installer transition target data validation failed"
    transition_target_after="$(verify_exact_data_projection "$DATA_RELEASE_DIR/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "installer transition target data TOCTOU validation failed"
    [[ "$transition_target_before" == "$transition_target_after" ]] || fail "installer transition target data changed during validation"
    if [[ -e "$DEPLOY_ROOT/releases/$RELEASE_SHA" || -L "$DEPLOY_ROOT/releases/$RELEASE_SHA" ]]; then
      [[ -d "$DEPLOY_ROOT/releases/$RELEASE_SHA" && ! -L "$DEPLOY_ROOT/releases/$RELEASE_SHA" ]] || fail "installer transition target release is unsafe"
      verify_committed_site_release_for_recovery
    elif [[ "$container_release" == "$RELEASE_SHA" ]]; then
      fail "installer transition target runtime lacks its exact release tree"
    fi
    if [[ "$container_release" == "$RELEASE_SHA" ]]; then
      transition_health="$(verify_target_site_transition_runtime_contract)"
      for _ in $(seq 1 15); do
        IFS=$'\t' read -r site_pointer container_release container_health http_release < <(live_site_tuple)
        [[ "$container_release" == "$RELEASE_SHA" && "$container_health" == healthy && "$http_release" == "$RELEASE_SHA" ]] && break
        sleep 2
      done
      if [[ "$container_release" == "$RELEASE_SHA" && "$container_health" == healthy && "$http_release" == "$RELEASE_SHA" ]]; then
        complete_interrupted_site_commit
        return 0
      fi
      [[ "$transition_health" == starting || "$transition_health" == unhealthy || "$transition_health" == missing || "$transition_health" == healthy ]] || fail "installer transition health state is unknown"
    elif [[ "$container_release" == "$EXPECTED_CURRENT" ]]; then
      local_old_image="reddit-voc-insights:$EXPECTED_CURRENT"
      verify_old_site_release_for_recovery
      local_old_image_id="$(expected_image_id_from_archive "$DEPLOY_ROOT/releases/$EXPECTED_CURRENT/reddit-voc-insights-${EXPECTED_CURRENT}.tar" "$local_old_image")" || fail "old-labeled transition image archive validation failed"
      transition_health="$(verify_target_site_transition_runtime_contract "$EXPECTED_CURRENT" "$local_old_image" "$local_old_image_id" "$local_old_image")"
      [[ "$transition_health" == starting || "$transition_health" == unhealthy || "$transition_health" == missing || "$transition_health" == healthy ]] || fail "old-labeled transition health state is unknown"
    else
      docker inspect reddit_voc_insights_web >/dev/null 2>&1 && fail "installer transition container identity is unknown"
      [[ "$(ss -H -ltn | awk '$4 ~ /:18338$/{n++} END{print n+0}')" == 0 ]] || fail "installer transition missing container has an occupied listener"
    fi
    restore_old_site_runtime_for_recovery
    recover_stale_journal
    return 0
  fi

  if [[ "$site_pointer" == "releases/$RELEASE_SHA" && "$container_release" == "$RELEASE_SHA" && "$container_health" == healthy && "$http_release" == "$RELEASE_SHA" ]]; then
    [[ "$(candidate_count)" == 0 && "$(port_count)" == 0 ]] || fail "CRITICAL: committed promotion has candidate residue; no recovery write performed"
    if [[ "$data_current" != "releases/$DATA_RELEASE_ID" || "$data_previous" != "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]]; then
      fail "CRITICAL: stale promotion journal has a mixed new-site/data tuple; no recovery write performed"
    fi
    reconcile_committed_promotion
    return 0
  fi

  if [[ "$site_pointer" == "releases/$EXPECTED_CURRENT" && "$container_release" == "$RELEASE_SHA" && "$container_health" == healthy && "$http_release" == "$RELEASE_SHA" ]]; then
    [[ "$(candidate_count)" == 0 && "$(port_count)" == 0 ]] || fail "CRITICAL: interrupted site activation has candidate residue; no recovery write performed"
    if [[ "$phase" != data_committed || "$data_current" != "releases/$DATA_RELEASE_ID" || "$data_previous" != "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]]; then
      fail "CRITICAL: interrupted site activation has an unexpected journal/data tuple; no recovery write performed"
    fi
    complete_interrupted_site_commit
    return 0
  fi

  if [[ "$site_pointer" != "releases/$EXPECTED_CURRENT" || "$container_release" != "$EXPECTED_CURRENT" || "$container_health" != healthy || "$http_release" != "$EXPECTED_CURRENT" ]]; then
    fail "CRITICAL: stale promotion journal has a later, mixed, or unknown site tuple; no recovery write performed"
  fi
  if [[ "$phase" == site_committed || "$phase" == complete ]]; then
    fail "CRITICAL: stale promotion journal phase is later than the observed old site tuple; no recovery write performed"
  fi
  if [[ "$data_current" == "releases/$DATA_RELEASE_ID" ]]; then
    [[ "$data_previous" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]] || fail "CRITICAL: stale promotion journal has an unknown switched-data tuple; no recovery write performed"
  elif [[ "$data_current" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]]; then
    if [[ "$data_previous" != "$original_previous" && "$data_previous" != "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]]; then
      fail "CRITICAL: stale promotion journal has an unknown previous-only tuple; no recovery write performed"
    fi
  else
    fail "CRITICAL: stale promotion journal has a later or unknown data tuple; no recovery write performed"
  fi
  if [[ -e "$DEPLOY_ROOT/releases/$RELEASE_SHA" || -L "$DEPLOY_ROOT/releases/$RELEASE_SHA" ]]; then
    if [[ "$phase" != data_committed || ! -d "$DEPLOY_ROOT/releases/$RELEASE_SHA" || -L "$DEPLOY_ROOT/releases/$RELEASE_SHA" ]]; then
      fail "CRITICAL: stale target site release is not an exact data-committed orphan; no recovery write performed"
    fi
    verify_committed_site_release_for_recovery
    orphan_site_release=1
  fi
  if [[ -e "$DEPLOY_ROOT/releases/.staging-$RELEASE_SHA" || -L "$DEPLOY_ROOT/releases/.staging-$RELEASE_SHA" ]]; then
    [[ "$phase" == data_committed && ! -e "$DEPLOY_ROOT/releases/$RELEASE_SHA" && ! -L "$DEPLOY_ROOT/releases/$RELEASE_SHA" && -d "$DEPLOY_ROOT/releases/.staging-$RELEASE_SHA" && ! -L "$DEPLOY_ROOT/releases/.staging-$RELEASE_SHA" ]] || fail "CRITICAL: stale target site staging release is not an exact data-committed orphan; no recovery write performed"
    verify_committed_site_release_for_recovery "$DEPLOY_ROOT/releases/.staging-$RELEASE_SHA"
    orphan_site_stage=1
  fi
  if [[ -e "$DATA_RELEASE_DIR" || -L "$DATA_RELEASE_DIR" ]]; then
    [[ -d "$DATA_RELEASE_DIR" && ! -L "$DATA_RELEASE_DIR" ]] || fail "CRITICAL: stale target data release path is unsafe; no recovery write performed"
    target_inventory_before="$(verify_exact_data_projection "$DATA_RELEASE_DIR/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "CRITICAL: stale target data release inventory is unknown; no recovery write performed"
    target_inventory_after="$(verify_exact_data_projection "$DATA_RELEASE_DIR/public" "$TEMP_ROOT/dist-SHA256SUMS")" || fail "CRITICAL: stale target data release inventory TOCTOU validation failed; no recovery write performed"
    [[ "$target_inventory_before" == "$target_inventory_after" ]] || fail "CRITICAL: stale target data release inventory changed; no recovery write performed"
  fi

  cleanup_exact_recovery_candidate_and_stage
  validate_promotion_transaction_locks
  IFS=$'\t' read -r OLD_DATA_INVENTORY_SHA OLD_DATA_FILE_COUNT OLD_DATA_TOTAL_BYTES \
    < <(verify_old_data_projection_stable)
  if [[ "$data_current" == "releases/$DATA_RELEASE_ID" ]]; then
    replace_data_pointer "$DATA_ROOT/current" "releases/$DATA_RELEASE_ID" "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" "$DATA_CURRENT_TMP"
  fi
  restore_previous_pointer "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" "$original_previous"
  [[ "$(pointer_state "$DATA_ROOT/current")" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]] || fail "stale transaction recovery did not restore data current"
  [[ "$(pointer_state "$DATA_ROOT/previous")" == "$original_previous" ]] || fail "stale transaction recovery did not restore original data previous"
  old_inventory_after="$(verify_old_data_projection_stable)" || fail "stale transaction recovery could not reverify old data inventory"
  [[ "$old_inventory_after" == "$OLD_DATA_INVENTORY_SHA"$'\t'"$OLD_DATA_FILE_COUNT"$'\t'"$OLD_DATA_TOTAL_BYTES" ]] || fail "old data inventory changed during stale transaction recovery"
  if [[ "$orphan_site_release" == 1 ]]; then
    IFS=$'\t' read -r site_pointer container_release container_health http_release < <(live_site_tuple)
    [[ "$site_pointer" == "releases/$EXPECTED_CURRENT" && "$container_release" == "$EXPECTED_CURRENT" && "$container_health" == healthy && "$http_release" == "$EXPECTED_CURRENT" ]] || fail "site tuple changed before orphan release cleanup"
    [[ "$(pointer_state "$DEPLOY_ROOT/current")" != "releases/$RELEASE_SHA" ]] || fail "orphan site release became active during recovery"
    rm -rf "$DEPLOY_ROOT/releases/$RELEASE_SHA"
    fsync_directory "$DEPLOY_ROOT/releases"
  fi
  if [[ "$orphan_site_stage" == 1 ]]; then
    rm -rf "$DEPLOY_ROOT/releases/.staging-$RELEASE_SHA"
    fsync_directory "$DEPLOY_ROOT/releases"
  fi
  if [[ -d "$DATA_RELEASE_DIR" && ! -L "$DATA_RELEASE_DIR" ]]; then
    current_target="$(readlink "$DATA_ROOT/current" 2>/dev/null || true)"
    previous_target="$(readlink "$DATA_ROOT/previous" 2>/dev/null || true)"
    if [[ "$current_target" == "releases/$DATA_RELEASE_ID" || "$previous_target" == "releases/$DATA_RELEASE_ID" ]]; then
      fail "stale target data release remains pointer-referenced"
    fi
    sudo rm -rf "$DATA_RELEASE_DIR"
    fsync_directory "$DATA_ROOT/releases"
  fi
  remove_journal
}
cleanup() {
  local status="$1"
  local recovery_ok=1 site_pointer container_release container_health http_release allow_data_restore=0
  local data_current data_previous old_inventory_before old_inventory_after current_target previous_target
  trap - EXIT
  set +e
  [[ "$CANDIDATE_STARTED" != 1 ]] || docker rm -f "$CANDIDATE" >/dev/null 2>&1
  [[ -z "$DATA_EXTRACT" ]] || docker rm -f "$DATA_EXTRACT" >/dev/null 2>&1
  if [[ "$status" != 0 && "$TRANSACTION_ARMED" == 1 ]]; then
    IFS=$'\t' read -r site_pointer container_release container_health http_release < <(live_site_tuple)
    data_current="$(pointer_state "$DATA_ROOT/current")"
    data_previous="$(pointer_state "$DATA_ROOT/previous")"
    if [[ "$site_pointer" == "releases/$RELEASE_SHA" && "$container_release" == "$RELEASE_SHA" && "$container_health" == healthy && "$http_release" == "$RELEASE_SHA" && "$data_current" == "releases/$DATA_RELEASE_ID" && "$data_previous" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]]; then
      SITE_COMMITTED=1
      echo "installer returned non-zero after the new site committed; preserving the new site/data tuple" >&2
    elif [[ "$SITE_COMMITTED" != 1 && "$site_pointer" == "releases/$EXPECTED_CURRENT" && "$container_release" == "$EXPECTED_CURRENT" && "$container_health" == healthy && "$http_release" == "$EXPECTED_CURRENT" ]]; then
      if [[ "$data_current" == "releases/$DATA_RELEASE_ID" && "$data_previous" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]] || \
         [[ "$data_current" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" && ( "$data_previous" == "$ORIGINAL_DATA_PREVIOUS_TARGET" || "$data_previous" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ) ]]; then
        if [[ ( -e "$DATA_RELEASE_DIR" || -L "$DATA_RELEASE_DIR" ) && ( ! -d "$DATA_RELEASE_DIR" || -L "$DATA_RELEASE_DIR" ) ]]; then
          echo "CRITICAL: target data release path is unsafe; no recovery write performed" >&2
          recovery_ok=0
        fi
        [[ "$recovery_ok" != 1 ]] || old_inventory_before="$(verify_old_data_projection_stable)" || recovery_ok=0
        [[ "$recovery_ok" == 1 ]] && allow_data_restore=1
      else
        echo "CRITICAL: data state is later, mixed, or unknown; no recovery write performed" >&2
      fi
    else
      echo "CRITICAL: site/data state is later, mixed, or unknown; preserving both data releases for manual recovery" >&2
    fi
  fi
  if [[ "$status" != 0 && "$SITE_COMMITTED" != 1 && "$allow_data_restore" == 1 ]]; then
    if [[ -n "$PREVIOUS_DATA_TARGET" && "$(pointer_state "$DATA_ROOT/current")" == "releases/$DATA_RELEASE_ID" ]]; then
      if replace_data_pointer \
        "$DATA_ROOT/current" "releases/$DATA_RELEASE_ID" \
        "$PREVIOUS_DATA_TARGET" "$DATA_CURRENT_TMP"; then
        DATA_CURRENT_SWITCHED=0
      else
        recovery_ok=0
      fi
    elif [[ "$(pointer_state "$DATA_ROOT/current")" == "$PREVIOUS_DATA_TARGET" ]]; then
      DATA_CURRENT_SWITCHED=0
    else
      recovery_ok=0
    fi
  fi
  if [[ "$status" != 0 && "$SITE_COMMITTED" != 1 && "$allow_data_restore" == 1 && "$(pointer_state "$DATA_ROOT/previous")" != "$ORIGINAL_DATA_PREVIOUS_TARGET" ]]; then
    if [[ "$(pointer_state "$DATA_ROOT/previous")" != "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]]; then
      recovery_ok=0
    elif [[ "$ORIGINAL_DATA_PREVIOUS_TARGET" == absent ]]; then
      remove_data_pointer \
        "$DATA_ROOT/previous" "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" \
        "$DATA_PREVIOUS_TMP" || recovery_ok=0
    elif [[ -n "$ORIGINAL_DATA_PREVIOUS_TARGET" ]]; then
      replace_data_pointer \
        "$DATA_ROOT/previous" "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" \
        "$ORIGINAL_DATA_PREVIOUS_TARGET" "$DATA_PREVIOUS_TMP" || recovery_ok=0
    fi
    DATA_PREVIOUS_SWITCHED=0
  fi
  rm -f "$DATA_CURRENT_TMP" "$DATA_PREVIOUS_TMP" "$SITE_CURRENT_RECOVERY_TMP"
  if [[ "$status" != 0 && "$allow_data_restore" == 1 && "$DATA_RELEASE_COMMITTED" == 1 && "$SITE_COMMITTED" != 1 && -d "$DATA_RELEASE_DIR" && ! -L "$DATA_RELEASE_DIR" ]]; then
    current_target="$(readlink "$DATA_ROOT/current" 2>/dev/null || true)"
    previous_target="$(readlink "$DATA_ROOT/previous" 2>/dev/null || true)"
    if [[ "$current_target" != "releases/$DATA_RELEASE_ID" && "$previous_target" != "releases/$DATA_RELEASE_ID" ]]; then
      sudo rm -rf "$DATA_RELEASE_DIR" && fsync_directory "$DATA_ROOT/releases" || recovery_ok=0
    else
      echo "candidate data release retained because a pointer still references it" >&2
    fi
  fi
  [[ -z "$TEMP_ROOT" ]] || rm -rf "$TEMP_ROOT"
  [[ -z "$DATA_STAGE" ]] || sudo rm -rf "$DATA_STAGE"
  if [[ "$status" != 0 && "$allow_data_restore" == 1 ]]; then
    if [[ "$(pointer_state "$DATA_ROOT/current")" != "$PREVIOUS_DATA_TARGET" || "$(pointer_state "$DATA_ROOT/previous")" != "$ORIGINAL_DATA_PREVIOUS_TARGET" ]]; then
      recovery_ok=0
    fi
    old_inventory_after="$(verify_old_data_projection_stable)" || recovery_ok=0
    [[ "$old_inventory_after" == "$old_inventory_before" ]] || recovery_ok=0
    if [[ "$recovery_ok" == 1 ]]; then
      remove_journal || recovery_ok=0
    fi
  fi
  if [[ "$recovery_ok" != 1 ]]; then
    echo "CRITICAL: automatic promotion recovery did not reach a verified site/data tuple" >&2
  fi
  exit "$status"
}
trap 'cleanup $?' EXIT

for value in "$ARCHIVE_SHA" "$PACKET_SHA" "$PERMIT_SHA" "$RELEASE_SHA" "$EXPECTED_CURRENT" "$EXPECTED_CURRENT_DATA_POINTER_SHA" "$TARGET_DATA_POINTER_SHA"; do
  is_sha "$value" || fail "invalid sha256 argument"
done
[[ "$DATA_RELEASE_ID" =~ ^reddit_voc_release_[a-z0-9_-]+$ ]] || fail "invalid data release id"
[[ "$EXPECTED_CURRENT_DATA_RELEASE_ID" =~ ^reddit_voc_release_[a-z0-9_-]+$ ]] || fail "invalid expected current data release id"
for command in cp curl docker find flock python3 readlink sha256sum ss stat sudo tar; do
  command -v "$command" >/dev/null 2>&1 || fail "required command missing: $command"
done
sudo -n true
umask 077
python3 - \
  "$ARCHIVE" "$PACKET" "$PERMIT" "$INSTALLER" "$ROLLBACK" \
  "$RUNNER_SOURCE" <<'PY'
import os
from pathlib import Path
import re
import stat
import sys

archive, packet, permit, installer, rollback, runner = map(Path, sys.argv[1:])
runtime_root = Path("/opt/reddit-voc-insights-site/runtime")
sealed_root = runner.parent
expected = {
    "release.tgz": archive,
    "packet.json": packet,
    "permit.json": permit,
    "remote_promote_insights_v6.sh": runner,
    "remote_install_insights_release.sh": installer,
    "remote_rollback_insights.sh": rollback,
}
if (
    not sealed_root.is_absolute()
    or sealed_root.parent != runtime_root
    or re.fullmatch(r"\.promotion-[a-f0-9]{12}\.[A-Za-z0-9_-]{6,64}", sealed_root.name)
    is None
    or any(path != sealed_root / name for name, path in expected.items())
):
    raise SystemExit("promotion inputs are not the exact sealed bundle")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("sealed input validation requires O_NOFOLLOW")
runtime_metadata = runtime_root.lstat()
root_before = sealed_root.lstat()
if (
    not stat.S_ISDIR(runtime_metadata.st_mode)
    or runtime_metadata.st_uid != 0
    or runtime_metadata.st_mode & 0o022
    or not stat.S_ISDIR(root_before.st_mode)
    or root_before.st_uid != 0
    or stat.S_IMODE(root_before.st_mode) != 0o555
    or {path.name for path in sealed_root.iterdir()} != set(expected)
):
    raise SystemExit("promotion sealed root contract invalid")
root_fd = os.open(sealed_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    opened_root = os.fstat(root_fd)
    if (opened_root.st_dev, opened_root.st_ino) != (
        root_before.st_dev,
        root_before.st_ino,
    ):
        raise SystemExit("promotion sealed root changed while opening")
    for name in sorted(expected):
        before = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != 0
            or stat.S_IMODE(before.st_mode) != 0o444
        ):
            raise SystemExit(f"promotion sealed input is unsafe: {name}")
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
            ):
                raise SystemExit(f"promotion sealed input changed while opening: {name}")
        finally:
            os.close(descriptor)
    root_after = sealed_root.lstat()
    if (root_after.st_dev, root_after.st_ino) != (
        opened_root.st_dev,
        opened_root.st_ino,
    ):
        raise SystemExit("promotion sealed root changed during validation")
finally:
    os.close(root_fd)
PY
[[ "$(sha256sum "$ARCHIVE" | awk '{print $1}')" == "$ARCHIVE_SHA" ]] || fail "archive sha mismatch"
[[ "$(sha256sum "$PACKET" | awk '{print $1}')" == "$PACKET_SHA" ]] || fail "packet sha mismatch"
[[ "$(sha256sum "$PERMIT" | awk '{print $1}')" == "$PERMIT_SHA" ]] || fail "permit sha mismatch"
[[ -d "$DEPLOY_ROOT" && ! -L "$DEPLOY_ROOT" ]] || fail "deployment root unsafe"
[[ -d "$DATA_ROOT" && ! -L "$DATA_ROOT" ]] || fail "data root unsafe"
[[ -d "$DATA_ROOT/releases" && ! -L "$DATA_ROOT/releases" ]] || fail "data releases root unsafe"
[[ -d "$LOCKS_DIR" && ! -L "$LOCKS_DIR" && "$(stat -c '%u|%a' "$LOCKS_DIR")" == "$(id -u)|700" ]] || fail "initialized data locks directory contract mismatch"
if [[ "${INSIGHTS_PROMOTION_LOCKS_BOOTSTRAPPED:-0}" == 1 ]]; then
  validate_promotion_transaction_locks
else
  bootstrap_promotion_transaction_locks
  fail "promotion transaction lock bootstrap unexpectedly returned"
fi

RUNNER_SHA="$(sha256sum "$RUNNER_SOURCE" | awk '{print $1}')"
INSTALLER_SHA="$(sha256sum "$INSTALLER" | awk '{print $1}')"
ROLLBACK_SHA="$(sha256sum "$ROLLBACK" | awk '{print $1}')"
ARCHIVE_BYTES="$(stat -c '%s' "$ARCHIVE")"
RUNNER_BYTES="$(stat -c '%s' "$RUNNER_SOURCE")"
INSTALLER_BYTES="$(stat -c '%s' "$INSTALLER")"
ROLLBACK_BYTES="$(stat -c '%s' "$ROLLBACK")"

validate_promotion_transaction_locks

AUTHORIZATION_VALUES="$(python3 - "$PACKET" "$PERMIT" "$PACKET_SHA" "$PERMIT_SHA" "$RELEASE_SHA" "$EXPECTED_CURRENT" "$DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_RELEASE_ID" "$EXPECTED_CURRENT_DATA_POINTER_SHA" "$TARGET_DATA_POINTER_SHA" "$ARCHIVE_SHA" "$ARCHIVE_BYTES" "$RUNNER_SHA" "$RUNNER_BYTES" "$INSTALLER_SHA" "$INSTALLER_BYTES" "$ROLLBACK_SHA" "$ROLLBACK_BYTES" "$JOURNAL" "$(id -u)" <<'PY'
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

(packet_path, permit_path, packet_sha, permit_sha, release, current, data_release,
 expected_data_release, expected_data_pointer_sha, target_data_pointer_sha,
 archive_sha, archive_bytes, runner_sha, runner_bytes, installer_sha,
 installer_bytes, rollback_sha, rollback_bytes, journal_path, owner_value) = sys.argv[1:]
sha_pattern = re.compile(r"^[a-f0-9]{64}$")
def canonical(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    expected = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if raw != expected:
        raise SystemExit(f"noncanonical json: {path}")
    return value
packet, permit = canonical(packet_path), canonical(permit_path)
packet_keys = {
    "artifacts", "authorization", "deferred_debts", "evidence",
    "execution_runtime", "expires_at_utc", "generated_at_utc", "nonce",
    "packet_id", "production_baseline_cas", "rollback", "schema_version",
    "side_effects", "status", "target", "v3_lineage",
}
if set(packet) not in (packet_keys, packet_keys - {"v3_lineage"}):
    raise SystemExit("packet fields invalid")
target = packet.get("target", {})
authorization = packet.get("authorization", {})
binding = permit.get("packet", {})
if packet.get("schema_version") != "reddit_voc_promotion_packet_v4" or packet.get("status") != "ready_for_owner_authorization":
    raise SystemExit("packet contract invalid")
if target != {
    "data_release_id": data_release,
    "expected_current_data_pointer_sha256": expected_data_pointer_sha,
    "expected_current_data_release_id": expected_data_release,
    "expected_current_release_sha256": current,
    "release_sha256": release,
    "site_url": "https://reddit.lute-tlz-dddd.top",
    "target_data_pointer_sha256": target_data_pointer_sha,
}:
    raise SystemExit("packet target mismatch")
if (
    not isinstance(authorization, dict)
    or set(authorization) != {
        "allowed_actions", "consumed", "forbidden_actions", "permit_required",
        "promotion_authorized", "required_owner_confirmation",
    }
    or authorization.get("consumed") is not False
    or authorization.get("permit_required") is not True
    or authorization.get("promotion_authorized") is not False
    or authorization.get("required_owner_confirmation")
    != ["packet_sha256", "release_sha256"]
):
    raise SystemExit("packet authorization contract invalid")
if permit.get("schema_version") != "reddit_voc_promotion_permit_v1" or permit.get("status") != "authorized_unconsumed":
    raise SystemExit("permit contract invalid")
permit_keys = {
    "authorization", "authorization_id", "authorized_actions", "authorized_by",
    "authorized_recorded_at_utc", "consumed", "contract", "expires_at_utc",
    "forbidden_actions", "packet", "packet_id", "packet_sha256",
    "release_sha256", "schema_version", "scope", "side_effects", "status",
}
if set(permit) != permit_keys:
    raise SystemExit("permit fields invalid")
if (
    permit.get("packet_sha256") != packet_sha
    or permit.get("release_sha256") != release
    or permit.get("consumed") is not False
    or permit.get("contract") != "reddit_voc_promotion_permit_exact_binding_v4"
    or permit.get("scope") != "insights_site_and_data_current"
):
    raise SystemExit("permit identity mismatch")
if (
    binding.get("packet_sha256") != packet_sha
    or binding.get("release_sha256") != release
    or binding.get("expected_current_release_sha256") != current
    or binding.get("data_release_id") != data_release
    or binding.get("expected_current_data_release_id") != expected_data_release
    or binding.get("expected_current_data_pointer_sha256") != expected_data_pointer_sha
    or binding.get("target_data_pointer_sha256") != target_data_pointer_sha
    or binding.get("packet_id") != packet.get("packet_id")
    or binding.get("nonce") != packet.get("nonce")
    or binding.get("expires_at_utc") != packet.get("expires_at_utc")
    or binding.get("execution_runtime") != packet.get("execution_runtime")
):
    raise SystemExit("permit binding mismatch")
if permit.get("authorized_actions") != authorization.get("allowed_actions") or permit.get("forbidden_actions") != authorization.get("forbidden_actions"):
    raise SystemExit("permit actions mismatch")
required_actions = [
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
required_forbidden_actions = [
    "modify_collector", "restart_collector", "modify_cron",
    "modify_shared_nginx", "modify_tls", "modify_dns",
    "modify_other_docker_environment", "docker_prune", "provider_call",
    "database_write", "schedule_change", "live_send",
    "enable_candidate_registry_automation", "claim_four_exports_complete",
]
allowed_actions = authorization.get("allowed_actions")
if allowed_actions != required_actions:
    raise SystemExit("packet allowed actions invalid")
forbidden_actions = authorization.get("forbidden_actions")
if forbidden_actions != required_forbidden_actions:
    raise SystemExit("packet forbidden actions invalid")
permit_authorization = permit.get("authorization")
if (
    not isinstance(permit_authorization, dict)
    or set(permit_authorization) != {
        "authorized_actions", "authorized_at_utc", "authorized_by",
        "forbidden_actions", "owner_confirmation",
    }
    or permit_authorization.get("authorized_by") != "owner_explicit_confirmation"
    or permit_authorization.get("owner_confirmation")
    != "authorize_exact_reddit_voc_packet_and_release"
    or permit_authorization.get("authorized_actions") != allowed_actions
    or permit_authorization.get("forbidden_actions")
    != forbidden_actions
    or permit.get("authorized_actions") != allowed_actions
    or permit.get("forbidden_actions") != forbidden_actions
    or permit.get("authorized_by") != "owner_explicit_confirmation"
    or permit.get("authorized_recorded_at_utc")
    != permit_authorization.get("authorized_at_utc")
    or permit.get("packet_id") != packet.get("packet_id")
):
    raise SystemExit("permit authorization invalid")
execution_runtime = packet.get("execution_runtime")
runtime_expected = {
    "remote_promotion_runner": (
        "remote_promote_insights_v6.sh", runner_sha, int(runner_bytes)
    ),
    "remote_installer": (
        "remote_install_insights_release.sh", installer_sha, int(installer_bytes)
    ),
    "remote_rollback": (
        "remote_rollback_insights.sh", rollback_sha, int(rollback_bytes)
    ),
}
if not isinstance(execution_runtime, dict) or set(execution_runtime) != set(runtime_expected):
    raise SystemExit("execution runtime invalid")
for name, (filename, digest, size) in runtime_expected.items():
    record = execution_runtime.get(name)
    if (
        not isinstance(record, dict)
        or set(record) != {"bytes", "path", "sha256"}
        or record.get("sha256") != digest
        or record.get("bytes") != size
        or not isinstance(record.get("path"), str)
        or PurePosixPath(record["path"]).is_absolute()
        or ".." in PurePosixPath(record["path"]).parts
        or PurePosixPath(record["path"]).name != filename
    ):
        raise SystemExit("execution runtime binding mismatch")
artifacts = packet.get("artifacts")
transfer = artifacts.get("transfer_tgz") if isinstance(artifacts, dict) else None
if (
    not isinstance(transfer, dict)
    or set(transfer) != {"bytes", "path", "sha256"}
    or transfer.get("sha256") != archive_sha
    or transfer.get("bytes") != int(archive_bytes)
    or not isinstance(transfer.get("path"), str)
    or PurePosixPath(transfer["path"]).is_absolute()
    or ".." in PurePosixPath(transfer["path"]).parts
    or PurePosixPath(transfer["path"]).name
    != f"reddit-voc-insights-{release}.tgz"
):
    raise SystemExit("release archive is not bound to the authorized packet")
rollback = packet.get("rollback")
old_release_manifest_sha = rollback.get("target_release_manifest_sha256") if isinstance(rollback, dict) else None
old_release_sha256s_sha = rollback.get("target_release_sha256s_sha256") if isinstance(rollback, dict) else None
old_data_inventory_sha = rollback.get("target_data_inventory_sha256") if isinstance(rollback, dict) else None
old_data_file_count = rollback.get("target_data_file_count") if isinstance(rollback, dict) else None
old_data_total_bytes = rollback.get("target_data_total_bytes") if isinstance(rollback, dict) else None
if (
    not isinstance(rollback, dict)
    or set(rollback) != {
        "readiness_mode", "ready", "scope", "shared_nginx_change_allowed",
        "target_data_file_count", "target_data_inventory_sha256",
        "target_data_pointer_sha256", "target_data_release_id",
        "target_data_total_bytes", "target_release_manifest_sha256",
        "target_release_sha256", "target_release_sha256s_sha256",
        "valid_until_utc",
    }
    or rollback.get("readiness_mode") != "immediate_same_baseline_window"
    or rollback.get("ready") is not True
    or rollback.get("scope") != "insights_site_and_data_current"
    or rollback.get("target_release_sha256") != current
    or rollback.get("target_data_release_id") != expected_data_release
    or rollback.get("target_data_pointer_sha256") != expected_data_pointer_sha
    or sha_pattern.fullmatch(str(old_release_manifest_sha)) is None
    or sha_pattern.fullmatch(str(old_release_sha256s_sha)) is None
    or sha_pattern.fullmatch(str(old_data_inventory_sha)) is None
    or type(old_data_file_count) is not int
    or old_data_file_count <= 0
    or type(old_data_total_bytes) is not int
    or old_data_total_bytes <= 0
    or rollback.get("shared_nginx_change_allowed") is not False
    or rollback.get("valid_until_utc") != packet.get("expires_at_utc")
):
    raise SystemExit("packet rollback contract invalid")
def utc(value, label):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SystemExit(f"{label} invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit(f"{label} invalid")
    return parsed
cas = packet.get("production_baseline_cas")
cas_keys = {
    "collector", "container_inventory", "cron_sha256", "database_identity",
    "insights", "lock_identities", "observed_at_utc",
    "report_pointer_identity", "shared_nginx_sha256", "translation",
}
container_keys = {"container_id", "health", "restart_count"}
insights_keys = container_keys | {"image_id", "network_id"}
expected_lock_paths = {
    "promotion": "/opt/reddit-voc-insights-site/.promotion.lock",
    "deploy": "/opt/reddit-voc-insights-site/.deploy.lock",
    "data_release": "/opt/reddit-voc-insights-data/locks/data-release.lock",
}
def valid_container(value, *, insights=False):
    expected_keys = insights_keys if insights else container_keys
    return (
        isinstance(value, dict)
        and set(value) == expected_keys
        and sha_pattern.fullmatch(str(value.get("container_id"))) is not None
        and value.get("health") == "healthy"
        and type(value.get("restart_count")) is int
        and value["restart_count"] >= 0
        and (
            not insights
            or (
                re.fullmatch(r"sha256:[a-f0-9]{64}", str(value.get("image_id")))
                is not None
                and sha_pattern.fullmatch(str(value.get("network_id"))) is not None
            )
        )
    )
def valid_file_identity(value, *, allow_absent=False):
    if allow_absent and value == "absent":
        return True
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+:[0-9]+:[1-9][0-9]*", value) is None:
        return False
    modified, size, inode = (int(item) for item in value.split(":"))
    return modified >= 0 and size >= 0 and inode > 0
locks = cas.get("lock_identities") if isinstance(cas, dict) else None
locks_valid = isinstance(locks, dict) and set(locks) == set(expected_lock_paths)
if locks_valid:
    for name, expected_path in expected_lock_paths.items():
        identity = locks.get(name)
        if (
            not isinstance(identity, dict)
            or set(identity) != {"device", "inode", "mode", "nlink", "path", "uid"}
            or type(identity.get("device")) is not int
            or identity["device"] < 0
            or type(identity.get("inode")) is not int
            or identity["inode"] <= 0
            or identity.get("mode") != "0600"
            or identity.get("nlink") != 1
            or identity.get("path") != expected_path
            or type(identity.get("uid")) is not int
            or identity["uid"] != int(owner_value)
        ):
            locks_valid = False
            break
inventory = cas.get("container_inventory") if isinstance(cas, dict) else None
if (
    not isinstance(cas, dict)
    or set(cas) != cas_keys
    or not valid_container(cas.get("collector"))
    or not valid_container(cas.get("translation"))
    or not valid_container(cas.get("insights"), insights=True)
    or not isinstance(inventory, dict)
    or set(inventory) != {
        "count", "protected_count", "protected_sha256", "sha256"
    }
    or type(inventory.get("count")) is not int
    or inventory["count"] <= 0
    or type(inventory.get("protected_count")) is not int
    or inventory["protected_count"] <= 0
    or inventory["protected_count"] > inventory["count"]
    or sha_pattern.fullmatch(str(inventory.get("protected_sha256"))) is None
    or sha_pattern.fullmatch(str(inventory.get("sha256"))) is None
    or sha_pattern.fullmatch(str(cas.get("cron_sha256"))) is None
    or sha_pattern.fullmatch(str(cas.get("shared_nginx_sha256"))) is None
    or not valid_file_identity(cas.get("database_identity"))
    or not valid_file_identity(
        cas.get("report_pointer_identity"), allow_absent=True
    )
    or not locks_valid
):
    raise SystemExit("packet production baseline CAS invalid")
utc(cas.get("observed_at_utc"), "production baseline observed_at")
cas_sha = hashlib.sha256(
    json.dumps(cas, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
generated = utc(packet.get("generated_at_utc"), "packet generated_at")
packet_expires = utc(packet.get("expires_at_utc"), "packet expires_at")
authorized = utc(permit_authorization.get("authorized_at_utc"), "permit authorized_at")
expires = utc(permit.get("expires_at_utc"), "permit expires_at")
now = datetime.now(timezone.utc)
journal = Path(journal_path)
journal_value = None
if journal.exists() or journal.is_symlink():
    owner = int(owner_value)
    metadata = journal.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != owner
        or metadata.st_mode & 0o077
    ):
        raise SystemExit("promotion recovery journal is unsafe")
    descriptor = os.open(journal, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or opened.st_nlink != 1
            or opened.st_uid != owner
            or opened.st_mode & 0o077
        ):
            raise SystemExit("promotion recovery journal changed while opening")
        raw = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            raw += chunk
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or len(raw) != opened.st_size
        ):
            raise SystemExit("promotion recovery journal changed while reading")
    finally:
        os.close(descriptor)
    journal_value = json.loads(raw)
    canonical_journal = json.dumps(
        journal_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode() + b"\n"
    if raw != canonical_journal:
        raise SystemExit("promotion recovery journal is noncanonical")
    journal_identity = {
        "collector_id": cas["collector"]["container_id"],
        "collector_restart_count": cas["collector"]["restart_count"],
        "container_inventory_sha256": cas["container_inventory"]["sha256"],
        "cron_sha256": cas["cron_sha256"],
        "data_pointer_sha256": target_data_pointer_sha,
        "data_release_id": data_release,
        "database_identity": cas["database_identity"],
        "expected_current_data_pointer_sha256": expected_data_pointer_sha,
        "expected_current_data_release_id": expected_data_release,
        "expected_current_release_sha256": current,
        "packet_sha256": packet_sha,
        "permit_sha256": permit_sha,
        "previous_data_file_count": old_data_file_count,
        "previous_data_inventory_sha256": old_data_inventory_sha,
        "previous_data_total_bytes": old_data_total_bytes,
        "previous_release_manifest_sha256": old_release_manifest_sha,
        "previous_release_sha256s_sha256": old_release_sha256s_sha,
        "production_baseline_cas": cas,
        "production_baseline_cas_sha256": cas_sha,
        "release_sha256": release,
        "target_image_id": journal_value.get("target_image_id"),
        "report_pointer_identity": cas["report_pointer_identity"],
        "schema_version": "reddit_voc_promotion_transaction_v3",
        "shared_nginx_sha256": cas["shared_nginx_sha256"],
        "translation_id": cas["translation"]["container_id"],
        "translation_restart_count": cas["translation"]["restart_count"],
        "unrelated_container_inventory_count": cas["container_inventory"]["protected_count"],
        "unrelated_container_inventory_sha256": cas["container_inventory"]["protected_sha256"],
    }
    baseline_keys = {
        "transaction_started_at_utc",
    }
    if (
        set(journal_value)
        != set(journal_identity)
        | baseline_keys
        | {"phase", "original_previous_data_target"}
        or any(journal_value.get(key) != value for key, value in journal_identity.items())
        or journal_value.get("phase")
        not in {"prepared", "data_committed", "site_committed", "complete"}
        or re.fullmatch(
            r"sha256:[a-f0-9]{64}",
            str(journal_value.get("target_image_id")),
        ) is None
    ):
        raise SystemExit("promotion recovery journal identity mismatch")
    started = utc(
        journal_value.get("transaction_started_at_utc"),
        "promotion transaction started_at",
    )
    if not (generated <= authorized <= started < expires <= packet_expires and started <= now):
        raise SystemExit("promotion recovery journal was not started under a valid permit")
    print(
        "recovery",
        started.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        old_release_manifest_sha,
        old_release_sha256s_sha,
        old_data_inventory_sha,
        old_data_file_count,
        old_data_total_bytes,
        cas_sha,
        cas["collector"]["container_id"],
        cas["collector"]["restart_count"],
        cas["translation"]["container_id"],
        cas["translation"]["restart_count"],
        cas["shared_nginx_sha256"],
        cas["cron_sha256"],
        cas["container_inventory"]["protected_count"],
        cas["container_inventory"]["protected_sha256"],
        cas["insights"]["image_id"],
        cas["insights"]["network_id"],
        cas["database_identity"],
        cas["report_pointer_identity"],
        sep="\t",
    )
elif now >= expires:
    raise SystemExit("promotion permit expired")
elif generated <= authorized <= now < expires <= packet_expires:
    print(
        "fresh",
        now.isoformat().replace("+00:00", "Z"),
        old_release_manifest_sha,
        old_release_sha256s_sha,
        old_data_inventory_sha,
        old_data_file_count,
        old_data_total_bytes,
        cas_sha,
        cas["collector"]["container_id"],
        cas["collector"]["restart_count"],
        cas["translation"]["container_id"],
        cas["translation"]["restart_count"],
        cas["shared_nginx_sha256"],
        cas["cron_sha256"],
        cas["container_inventory"]["protected_count"],
        cas["container_inventory"]["protected_sha256"],
        cas["insights"]["image_id"],
        cas["insights"]["network_id"],
        cas["database_identity"],
        cas["report_pointer_identity"],
        sep="\t",
    )
else:
    raise SystemExit("promotion permit expired")
PY
)" || fail "promotion packet/permit authorization validation failed"
IFS=$'\t' read -r AUTHORIZATION_MODE TRANSACTION_STARTED_AT_UTC EXPECTED_OLD_RELEASE_MANIFEST_SHA EXPECTED_OLD_RELEASE_SHA256SUMS_SHA EXPECTED_OLD_DATA_INVENTORY_SHA EXPECTED_OLD_DATA_FILE_COUNT EXPECTED_OLD_DATA_TOTAL_BYTES PRODUCTION_BASELINE_CAS_SHA AUTHORIZED_COLLECTOR_ID AUTHORIZED_COLLECTOR_RESTART AUTHORIZED_TRANSLATION_ID AUTHORIZED_TRANSLATION_RESTART AUTHORIZED_NGINX_SHA AUTHORIZED_CRON_SHA INVENTORY_COUNT INVENTORY_SHA AUTHORIZED_INSIGHTS_IMAGE_ID AUTHORIZED_INSIGHTS_NETWORK_ID DATABASE_IDENTITY REPORT_POINTER_IDENTITY <<<"$AUTHORIZATION_VALUES"
[[ "$AUTHORIZATION_MODE" == fresh || "$AUTHORIZATION_MODE" == recovery ]] || fail "promotion authorization mode invalid"

if [[ "$AUTHORIZATION_MODE" == fresh ]]; then
  [[ "$(current_release)" == "$EXPECTED_CURRENT" ]] || fail "production current changed"
  verify_owner_authorized_production_baseline
  COLLECTOR_ID="$AUTHORIZED_COLLECTOR_ID"
  COLLECTOR_RESTART="$AUTHORIZED_COLLECTOR_RESTART"
  TRANSLATION_ID="$AUTHORIZED_TRANSLATION_ID"
  TRANSLATION_RESTART="$AUTHORIZED_TRANSLATION_RESTART"
  NGINX_SHA="$AUTHORIZED_NGINX_SHA"
  CRON_SHA="$AUTHORIZED_CRON_SHA"
  verify_control_plane_baseline_unchanged
  verify_interrupted_site_runtime_contract \
    "$EXPECTED_CURRENT" "reddit-voc-insights:$EXPECTED_CURRENT" \
    "$AUTHORIZED_INSIGHTS_IMAGE_ID" "$AUTHORIZED_INSIGHTS_NETWORK_ID"
fi

TEMP_ROOT="$(mktemp -d /tmp/reddit-voc-promote-v6.XXXXXX)"
python3 - "$ARCHIVE" "$RELEASE_SHA" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

archive, release = sys.argv[1:]
seen = set()
with tarfile.open(archive, "r:gz") as handle:
    members = handle.getmembers()
    if not members:
        raise SystemExit("release archive is empty")
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "." in path.parts
            or not path.parts
            or path.parts[0] != release
            or member.name in seen
            or not (member.isfile() or member.isdir())
        ):
            raise SystemExit("release archive contains an unsafe member")
        seen.add(member.name)
PY
tar -xzf "$ARCHIVE" -C "$TEMP_ROOT" --strip-components=1 --no-same-owner --no-same-permissions
if find "$TEMP_ROOT" -type l -print -quit | grep -q . || \
   find "$TEMP_ROOT" ! -type d ! -type f -print -quit | grep -q .; then
  fail "release archive extracted an unsafe entry"
fi
(cd "$TEMP_ROOT" && sha256sum --check SHA256SUMS >/dev/null) || fail "release checksums failed"
python3 - "$PACKET" "$TEMP_ROOT" "$RELEASE_SHA" <<'PY'
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

packet = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = Path(sys.argv[2])
release = sys.argv[3]
expected_files = {
    "release_manifest": "release-manifest.json",
    "release_sha256sums": "SHA256SUMS",
    "dist_sha256sums": "dist-SHA256SUMS",
    "linux_amd64_image_tar": f"reddit-voc-insights-{release}.tar",
}
artifacts = packet.get("artifacts")
if not isinstance(artifacts, dict):
    raise SystemExit("packet artifacts invalid")
for key, filename in expected_files.items():
    record = artifacts.get(key)
    target = root / filename
    if (
        not isinstance(record, dict)
        or set(record) != {"bytes", "path", "sha256"}
        or not isinstance(record.get("path"), str)
        or PurePosixPath(record["path"]).is_absolute()
        or ".." in PurePosixPath(record["path"]).parts
        or PurePosixPath(record["path"]).name != filename
        or not target.is_file()
        or target.is_symlink()
    ):
        raise SystemExit(f"authorized release artifact invalid: {key}")
    payload = target.read_bytes()
    if len(payload) != record.get("bytes") or hashlib.sha256(payload).hexdigest() != record.get("sha256"):
        raise SystemExit(f"authorized release artifact mismatch: {key}")
PY
IMAGE="reddit-voc-insights:${RELEASE_SHA}"
TARGET_IMAGE_ID="$(expected_image_id_from_archive "$TEMP_ROOT/reddit-voc-insights-${RELEASE_SHA}.tar" "$IMAGE")" \
  || fail "authorized target image archive identity validation failed"
[[ "$TARGET_IMAGE_ID" =~ ^sha256:[a-f0-9]{64}$ ]] || fail "authorized target image ID is invalid"
EXPECTED_DATA_POINTER_SHA="$(python3 - "$TEMP_ROOT/release-manifest.json" "$DATA_RELEASE_ID" <<'PY'
import json, re, sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_release_id = sys.argv[2]
current = manifest.get("current_release")
if (
    not isinstance(current, dict)
    or current.get("path") != "data/reddit-voc/current-release.json"
    or current.get("release_id") != expected_release_id
    or re.fullmatch(r"[a-f0-9]{64}", str(current.get("sha256"))) is None
):
    raise SystemExit("release manifest data pointer binding invalid")
print(current["sha256"])
PY
)"
[[ "$EXPECTED_DATA_POINTER_SHA" == "$TARGET_DATA_POINTER_SHA" ]] || fail "target data pointer argument differs from release manifest"

materialize_data_stage() {
  DATA_STAGE="/opt/.reddit-voc-insights-data-${RELEASE_SHA:0:12}.$$"
  [[ ! -e "$DATA_STAGE" && ! -L "$DATA_STAGE" ]] || fail "data stage already exists"
  sudo mkdir -p "$DATA_STAGE/releases/$DATA_RELEASE_ID/public/data"
  sudo chown -R "$(id -u):$(id -g)" "$DATA_STAGE"
  DATA_EXTRACT="${CANDIDATE}_data_extract"
  docker create --name "$DATA_EXTRACT" "$TARGET_IMAGE_ID" >/dev/null
  docker cp "$DATA_EXTRACT:/usr/share/nginx/html/data/." "$DATA_STAGE/releases/$DATA_RELEASE_ID/public/data/"
  docker rm "$DATA_EXTRACT" >/dev/null
  DATA_EXTRACT=""
  sudo chown -R "$(id -u):$(id -g)" "$DATA_STAGE"
  ln -s "releases/$DATA_RELEASE_ID" "$DATA_STAGE/current"
  python3 - "$TEMP_ROOT/dist-SHA256SUMS" "$DATA_STAGE/releases/$DATA_RELEASE_ID/public" <<'PY'
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import sys

sums_path = Path(sys.argv[1])
public_root = Path(sys.argv[2])
expected = {}
for number, line in enumerate(sums_path.read_text(encoding="utf-8").splitlines(), 1):
    match = re.fullmatch(r"([a-f0-9]{64})  (dist/data/.+)", line)
    if match is None:
        if "  dist/data/" in line:
            raise SystemExit(f"invalid data checksum line: {number}")
        continue
    digest, raw_path = match.groups()
    relative = PurePosixPath(raw_path).relative_to("dist")
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise SystemExit("unsafe data checksum path")
    key = relative.as_posix()
    if key in expected:
        raise SystemExit("duplicate data checksum path")
    expected[key] = digest
if not expected:
    raise SystemExit("data checksums missing")

actual = {}
for root, directories, files in os.walk(public_root, followlinks=False):
    root_path = Path(root)
    for name in [*directories, *files]:
        path = root_path / name
        if path.is_symlink():
            raise SystemExit(f"data stage symlink forbidden: {path}")
    for name in files:
        path = root_path / name
        relative = path.relative_to(public_root).as_posix()
        actual[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
if set(actual) != set(expected):
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    raise SystemExit(f"data file inventory mismatch missing={missing[:3]} extra={extra[:3]}")
for relative, digest in expected.items():
    if actual[relative] != digest:
        raise SystemExit(f"data checksum mismatch: {relative}")
PY
  find "$DATA_STAGE/releases" -type d -exec chmod 0555 {} +
  find "$DATA_STAGE/releases" -type f -exec chmod 0444 {} +
  chmod 0755 "$DATA_STAGE"
  POINTER="$DATA_STAGE/current/public/data/reddit-voc/current-release.json"
  [[ "$(sha256sum "$POINTER" | awk '{print $1}')" == "$TARGET_DATA_POINTER_SHA" ]] || fail "data pointer sha mismatch"
  python3 - "$POINTER" "$DATA_RELEASE_ID" <<'PY'
import json, sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
if value.get("schema_version") != "reddit_voc_current_release_v2" or value.get("release_id") != sys.argv[2] or set(value.get("datasets", {})) != {"base","insights","reports","personas","brand_health","quarter_insights","casebook"}:
    raise SystemExit("data pointer contract invalid")
PY
}

verify_exact_data_projection() {
  local public_root="$1"
  local sums_path="${2:-$TEMP_ROOT/dist-SHA256SUMS}"
  python3 - "$sums_path" "$public_root" "$(id -u)" <<'PY'
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

sums_path = Path(sys.argv[1])
public_root = Path(sys.argv[2])
expected_uid = int(sys.argv[3])

def immutable_checksum(metadata) -> bool:
    return (
        metadata.st_uid == expected_uid and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o444
    )

path_metadata = sums_path.lstat()
if (
    not stat.S_ISREG(path_metadata.st_mode)
    or path_metadata.st_nlink != 1
    or not immutable_checksum(path_metadata)
):
    raise SystemExit("data checksum inventory is unsafe")
flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
descriptor = os.open(sums_path, flags)
try:
    opened = os.fstat(descriptor)
    if (
        (opened.st_dev, opened.st_ino) != (path_metadata.st_dev, path_metadata.st_ino)
        or opened.st_nlink != 1
        or not immutable_checksum(opened)
    ):
        raise SystemExit("data checksum inventory changed while opening")
    sums_bytes = b""
    while chunk := os.read(descriptor, 1024 * 1024):
        sums_bytes += chunk
    opened_after = os.fstat(descriptor)
    if (
        opened_after.st_dev != opened.st_dev
        or opened_after.st_ino != opened.st_ino
        or opened_after.st_size != opened.st_size
        or opened_after.st_mtime_ns != opened.st_mtime_ns
        or len(sums_bytes) != opened.st_size
    ):
        raise SystemExit("data checksum inventory changed while reading")
finally:
    os.close(descriptor)
expected = {}
for number, line in enumerate(sums_bytes.decode("utf-8").splitlines(), 1):
    match = re.fullmatch(r"([a-f0-9]{64})  (dist/data/.+)", line)
    if match is None:
        if "  dist/data/" in line:
            raise SystemExit(f"invalid data checksum line: {number}")
        continue
    digest, raw_path = match.groups()
    relative = PurePosixPath(raw_path).relative_to("dist").as_posix()
    if relative in expected:
        raise SystemExit("duplicate data checksum path")
    expected[relative] = digest
if not expected:
    raise SystemExit("data checksum inventory is empty")

actual = {}
total_bytes = 0
for root, directories, files in os.walk(public_root, followlinks=False):
    root_path = Path(root)
    root_stat = root_path.lstat()
    if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != expected_uid or root_stat.st_mode & 0o022:
        raise SystemExit("data directory ownership or immutability mismatch")
    for name in directories:
        metadata = (root_path / name).lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_nlink < 1:
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
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
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
            while chunk := os.read(descriptor, 1024 * 1024):
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
        total_bytes += size
if set(actual) != set(expected):
    raise SystemExit("data projection inventory mismatch")
for relative, expected_digest in expected.items():
    if actual[relative][0] != expected_digest:
        raise SystemExit(f"data projection checksum mismatch: {relative}")
inventory = hashlib.sha256()
for relative in sorted(actual):
    digest, size = actual[relative]
    inventory.update(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\0" + str(size).encode("ascii") + b"\n")
print(inventory.hexdigest(), len(actual), total_bytes, sep="\t")
PY
}

verify_old_data_projection_stable() {
  local old_site_release="$DEPLOY_ROOT/releases/$EXPECTED_CURRENT"
  local old_data_public="$DATA_ROOT/releases/$EXPECTED_CURRENT_DATA_RELEASE_ID/public"
  local old_sums="$old_site_release/dist-SHA256SUMS"
  local first second
  [[ -d "$old_site_release" && ! -L "$old_site_release" ]] || fail "old site release is missing or unsafe"
  [[ -d "$old_data_public" && ! -L "$old_data_public" ]] || fail "old data release is missing or unsafe"
  python3 - "$old_site_release/SHA256SUMS" "$old_sums" "$(id -u)" <<'PY'
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

manifest_path, sums_path = map(Path, sys.argv[1:3])
owner = int(sys.argv[3])

def immutable_file(metadata) -> bool:
    return (
        metadata.st_uid == owner and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o444
    )

def safe_read(path: Path) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or not immutable_file(before)
    ):
        raise SystemExit(f"old release checksum source is unsafe: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or not immutable_file(opened)
        ):
            raise SystemExit(f"old release checksum source changed: {path.name}")
        payload = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            payload += chunk
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or len(payload) != opened.st_size
        ):
            raise SystemExit(f"old release checksum source changed while reading: {path.name}")
        return payload
    finally:
        os.close(descriptor)

manifest = safe_read(manifest_path).decode("utf-8")
sums = safe_read(sums_path)
expected = []
for line in manifest.splitlines():
    match = re.fullmatch(r"([a-f0-9]{64})  dist-SHA256SUMS", line)
    if match:
        expected.append(match.group(1))
if len(expected) != 1 or hashlib.sha256(sums).hexdigest() != expected[0]:
    raise SystemExit("old dist-SHA256SUMS is not bound by the active site release")
PY
  first="$(verify_exact_data_projection "$old_data_public" "$old_sums")" || return 1
  second="$(verify_exact_data_projection "$old_data_public" "$old_sums")" || return 1
  [[ "$first" == "$second" ]] || fail "old data inventory changed between TOCTOU checks"
  [[ "$first" == "$EXPECTED_OLD_DATA_INVENTORY_SHA"$'\t'"$EXPECTED_OLD_DATA_FILE_COUNT"$'\t'"$EXPECTED_OLD_DATA_TOTAL_BYTES" ]] || fail "old data inventory differs from the owner-authenticated baseline"
  [[ "$(sha256sum "$old_data_public/data/reddit-voc/current-release.json" | awk '{print $1}')" == "$EXPECTED_CURRENT_DATA_POINTER_SHA" ]] || fail "old data pointer SHA mismatch during inventory validation"
  printf '%s\n' "$first"
}

[[ "$DATA_RELEASE_ID" != "$EXPECTED_CURRENT_DATA_RELEASE_ID" ]] || fail "target data release must differ from current"
[[ -d "$DATA_ROOT" && ! -L "$DATA_ROOT" ]] || fail "data root unsafe"
[[ -d "$DATA_ROOT/releases" && ! -L "$DATA_ROOT/releases" ]] || fail "data releases root unsafe"
[[ -d "$LOCKS_DIR" && ! -L "$LOCKS_DIR" && "$(stat -c '%u|%a' "$LOCKS_DIR")" == "$(id -u)|700" ]] || fail "data locks directory contract mismatch"
validate_promotion_transaction_locks

recover_stale_journal
if [[ "$AUTHORIZATION_MODE" == recovery ]]; then
  [[ ! -e "$JOURNAL" && ! -L "$JOURNAL" ]] || fail "promotion recovery did not consume the exact journal"
  if [[ "$RECOVERED_PROMOTION" == 1 ]]; then
    printf '%s\n' \
      "release_sha=$RELEASE_SHA" \
      "status=promoted_pending_public_acceptance" \
      "reconciled_from_transaction_journal=true" \
      "evidence=$RECOVERED_EVIDENCE"
  else
    printf '%s\n' \
      "release_sha=$RELEASE_SHA" \
      "status=recovered_to_previous_release" \
      "recovery_only_authorization=true"
  fi
  cleanup 0
fi
verify_old_site_release_for_recovery
[[ "$(candidate_count)" == 0 && "$(port_count)" == 0 ]] || fail "candidate slot is occupied"

[[ -L "$DATA_ROOT/current" ]] || fail "data current pointer missing"
PREVIOUS_DATA_TARGET="$(readlink "$DATA_ROOT/current")"
[[ "$PREVIOUS_DATA_TARGET" == "releases/$EXPECTED_CURRENT_DATA_RELEASE_ID" ]] || fail "data current release CAS mismatch"
[[ -d "$DATA_ROOT/$PREVIOUS_DATA_TARGET" && ! -L "$DATA_ROOT/$PREVIOUS_DATA_TARGET" ]] || fail "active data release missing or unsafe"
CURRENT_DATA_POINTER="$DATA_ROOT/$PREVIOUS_DATA_TARGET/public/data/reddit-voc/current-release.json"
[[ -f "$CURRENT_DATA_POINTER" && ! -L "$CURRENT_DATA_POINTER" ]] || fail "active data pointer artifact unsafe"
[[ "$(sha256sum "$CURRENT_DATA_POINTER" | awk '{print $1}')" == "$EXPECTED_CURRENT_DATA_POINTER_SHA" ]] || fail "data current pointer SHA CAS mismatch"
python3 - "$CURRENT_DATA_POINTER" "$EXPECTED_CURRENT_DATA_RELEASE_ID" <<'PY'
import json, sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
if value.get("schema_version") != "reddit_voc_current_release_v2" or value.get("release_id") != sys.argv[2]:
    raise SystemExit("active data pointer contract invalid")
PY
IFS=$'\t' read -r OLD_DATA_INVENTORY_SHA OLD_DATA_FILE_COUNT OLD_DATA_TOTAL_BYTES \
  < <(verify_old_data_projection_stable)
if [[ -e "$DATA_ROOT/previous" || -L "$DATA_ROOT/previous" ]]; then
  [[ -L "$DATA_ROOT/previous" ]] || fail "data previous pointer unsafe"
  ORIGINAL_DATA_PREVIOUS_TARGET="$(readlink "$DATA_ROOT/previous")"
  [[ "$ORIGINAL_DATA_PREVIOUS_TARGET" =~ ^releases/reddit_voc_release_[a-z0-9_-]+$ ]] || fail "data previous pointer invalid"
  [[ -d "$DATA_ROOT/$ORIGINAL_DATA_PREVIOUS_TARGET" && ! -L "$DATA_ROOT/$ORIGINAL_DATA_PREVIOUS_TARGET" ]] || fail "data previous target missing or unsafe"
fi
[[ ! -e "$DATA_RELEASE_DIR" && ! -L "$DATA_RELEASE_DIR" ]] || fail "target data release already exists"
validate_promotion_transaction_locks
verify_owner_authorized_production_baseline
verify_control_plane_baseline_unchanged
verify_interrupted_site_runtime_contract \
  "$EXPECTED_CURRENT" "reddit-voc-insights:$EXPECTED_CURRENT" \
  "$AUTHORIZED_INSIGHTS_IMAGE_ID" "$AUTHORIZED_INSIGHTS_NETWORK_ID"
TRANSACTION_ARMED=1
write_journal "prepared" "$ORIGINAL_DATA_PREVIOUS_TARGET"
docker load --input "$TEMP_ROOT/reddit-voc-insights-${RELEASE_SHA}.tar" >/dev/null
[[ "$(docker image inspect -f '{{.Id}}|{{.Architecture}}|{{.Config.User}}|{{index .Config.Labels "com.reddit-voc.release"}}' "$TARGET_IMAGE_ID")" == "$TARGET_IMAGE_ID|amd64|101:101|${RELEASE_SHA}" ]] || fail "image contract mismatch"
[[ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" == "$TARGET_IMAGE_ID" ]] || fail "loaded image tag does not bind the authorized target image ID"
materialize_data_stage
CANDIDATE_DATA_ROOT="$DATA_STAGE"
[[ "$(readlink "$CANDIDATE_DATA_ROOT/current")" == "releases/$DATA_RELEASE_ID" ]] || fail "candidate data root current mismatch"
TARGET_POINTER="$CANDIDATE_DATA_ROOT/current/public/data/reddit-voc/current-release.json"
[[ -f "$TARGET_POINTER" && ! -L "$TARGET_POINTER" && "$(sha256sum "$TARGET_POINTER" | awk '{print $1}')" == "$TARGET_DATA_POINTER_SHA" ]] || fail "candidate data pointer identity mismatch"
IFS=$'\t' read -r DATA_INVENTORY_SHA DATA_FILE_COUNT DATA_TOTAL_BYTES \
  < <(verify_exact_data_projection "$DATA_STAGE/releases/$DATA_RELEASE_ID/public")

docker run -d --platform linux/amd64 --name "$CANDIDATE" --network "$NETWORK" \
  --user 101:101 --read-only --init \
  --mount "type=bind,src=$CANDIDATE_DATA_ROOT,dst=/srv/reddit-voc-data,readonly" \
  --tmpfs '/tmp:rw,noexec,nosuid,nodev,size=32m,uid=101,gid=101,mode=1777' \
  --publish "$BIND_ADDRESS:$CANDIDATE_PORT:8080" --cap-drop ALL \
  --security-opt no-new-privileges:true --pids-limit 100 --memory 256m --cpus 0.50 \
  --restart no --label com.reddit-voc.component=insights-site \
  --label "com.reddit-voc.release=$RELEASE_SHA" --label com.reddit-voc.scope=remote-candidate-smoke \
  --label "com.reddit-voc.promotion-packet=$PACKET_SHA" \
  --health-cmd 'wget -q -O /dev/null http://127.0.0.1:8080/healthz && wget -q -O /dev/null http://127.0.0.1:8080/data/reddit-voc/current-release.json' \
  --health-interval 2s --health-timeout 3s --health-retries 30 --health-start-period 2s \
  --env NGINX_ENTRYPOINT_QUIET_LOGS=1 "$TARGET_IMAGE_ID" >/dev/null
CANDIDATE_STARTED=1
for _ in $(seq 1 40); do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$CANDIDATE" 2>/dev/null || true)" == healthy ]] && break
  sleep 2
done
[[ "$(docker inspect -f '{{.State.Health.Status}}' "$CANDIDATE")" == healthy ]] || fail "candidate unhealthy"
MOUNT="$(docker inspect -f '{{len .Mounts}}|{{range .Mounts}}{{.Type}}|{{.Source}}|{{.RW}}|{{.Destination}}|{{.Propagation}}{{end}}' "$CANDIDATE")"
[[ "$MOUNT" == "1|bind|${CANDIDATE_DATA_ROOT}|false|/srv/reddit-voc-data|rprivate" ]] || fail "candidate data mount mismatch"
for route in / /dashboard /dashboard/reports /dashboard/analytics /dashboard/insights /dashboard/search /dashboard/ugc-showcase /dashboard/messages /dashboard/settings /features /how-it-works /faq /cases; do
  [[ "$(curl -sS -o /dev/null -w '%{http_code}' "http://$BIND_ADDRESS:$CANDIDATE_PORT$route")" == 200 ]] || fail "candidate route failed: $route"
done
[[ "$(curl -fsS "http://$BIND_ADDRESS:$CANDIDATE_PORT/release.json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["release_sha256"])')" == "$RELEASE_SHA" ]] || fail "candidate release marker mismatch"
[[ "$(curl -fsS "http://$BIND_ADDRESS:$CANDIDATE_PORT/data/reddit-voc/current-release.json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["release_id"])')" == "$DATA_RELEASE_ID" ]] || fail "candidate data pointer mismatch"
if docker exec "$CANDIDATE" wget -q -T 3 -O /dev/null "http://$BIND_ADDRESS:18337/api/health" 2>/dev/null; then
  fail "candidate reached collector"
fi
docker rm -f "$CANDIDATE" >/dev/null
CANDIDATE_STARTED=0
for _ in $(seq 1 20); do [[ "$(port_count)" == 0 ]] && break; sleep 1; done
[[ "$(port_count)" == 0 ]] || fail "candidate port did not close"

verify_control_plane_baseline_unchanged

if [[ -n "$DATA_STAGE" ]]; then
  [[ "$(current_release)" == "$EXPECTED_CURRENT" ]] || fail "production current changed before data switch"
  [[ -L "$DATA_ROOT/current" && "$(readlink "$DATA_ROOT/current")" == "$PREVIOUS_DATA_TARGET" ]] || fail "data current changed before switch"
  [[ "$(sha256sum "$CURRENT_DATA_POINTER" | awk '{print $1}')" == "$EXPECTED_CURRENT_DATA_POINTER_SHA" ]] || fail "data current pointer SHA changed before switch"
  old_inventory_rechecked="$(verify_old_data_projection_stable)" || fail "old data inventory failed its pre-switch TOCTOU check"
  [[ "$old_inventory_rechecked" == "$OLD_DATA_INVENTORY_SHA"$'\t'"$OLD_DATA_FILE_COUNT"$'\t'"$OLD_DATA_TOTAL_BYTES" ]] || fail "old data inventory changed before switch"
  IFS=$'\t' read -r rechecked_inventory_sha rechecked_file_count rechecked_total_bytes \
    < <(verify_exact_data_projection "$DATA_STAGE/releases/$DATA_RELEASE_ID/public")
  [[ "$rechecked_inventory_sha|$rechecked_file_count|$rechecked_total_bytes" == "$DATA_INVENTORY_SHA|$DATA_FILE_COUNT|$DATA_TOTAL_BYTES" ]] || fail "data stage changed after candidate validation"
  validate_promotion_transaction_locks
  sudo mv "$DATA_STAGE/releases/$DATA_RELEASE_ID" "$DATA_RELEASE_DIR"
  DATA_RELEASE_COMMITTED=1
  fsync_directory "$DATA_ROOT/releases"
  IFS=$'\t' read -r committed_inventory_sha committed_file_count committed_total_bytes \
    < <(verify_exact_data_projection "$DATA_RELEASE_DIR/public")
  [[ "$committed_inventory_sha|$committed_file_count|$committed_total_bytes" == "$DATA_INVENTORY_SHA|$DATA_FILE_COUNT|$DATA_TOTAL_BYTES" ]] || fail "committed data release changed before pointer CAS"
  sudo rm -rf "$DATA_STAGE"
  DATA_STAGE=""
  DATA_PREVIOUS_SWITCHED=1
  replace_data_pointer \
    "$DATA_ROOT/previous" "$ORIGINAL_DATA_PREVIOUS_TARGET" \
    "$PREVIOUS_DATA_TARGET" "$DATA_PREVIOUS_TMP"
  DATA_CURRENT_SWITCHED=1
  replace_data_pointer \
    "$DATA_ROOT/current" "$PREVIOUS_DATA_TARGET" \
    "releases/$DATA_RELEASE_ID" "$DATA_CURRENT_TMP"
  write_journal "data_committed" "$ORIGINAL_DATA_PREVIOUS_TARGET"
fi
[[ "$(readlink "$DATA_ROOT/current")" == "releases/$DATA_RELEASE_ID" ]] || fail "data root current mismatch after switch"
PROMOTED_DATA_POINTER="$DATA_ROOT/current/public/data/reddit-voc/current-release.json"
[[ -f "$PROMOTED_DATA_POINTER" && ! -L "$PROMOTED_DATA_POINTER" && "$(sha256sum "$PROMOTED_DATA_POINTER" | awk '{print $1}')" == "$TARGET_DATA_POINTER_SHA" ]] || fail "promoted data pointer identity mismatch"

INSTALL_STATUS=0
INSIGHTS_PARENT_TRANSACTION_LOCKS=1 \
INSIGHTS_PARENT_TRANSACTION_MARKER=reddit_voc_promotion_parent_v1 \
INSIGHTS_PARENT_TRANSACTION_PACKET_SHA="$PACKET_SHA" \
INSIGHTS_PARENT_TRANSACTION_RELEASE_SHA="$RELEASE_SHA" \
INSIGHTS_PARENT_TRANSACTION_ARCHIVE_SHA="$ARCHIVE_SHA" \
INSIGHTS_PARENT_TRANSACTION_DATA_RELEASE_ID="$DATA_RELEASE_ID" \
INSIGHTS_PARENT_TRANSACTION_EXPECTED_SITE_RELEASE_SHA="$EXPECTED_CURRENT" \
INSIGHTS_PARENT_TRANSACTION_EXPECTED_DATA_RELEASE_ID="$EXPECTED_CURRENT_DATA_RELEASE_ID" \
INSIGHTS_PARENT_TRANSACTION_TARGET_DATA_POINTER_SHA="$TARGET_DATA_POINTER_SHA" \
INSIGHTS_PARENT_TRANSACTION_TARGET_IMAGE_ID="$TARGET_IMAGE_ID" \
bash "$INSTALLER" "$ARCHIVE" "$ARCHIVE_SHA" "$RELEASE_SHA" || INSTALL_STATUS=$?
if [[ "$INSTALL_STATUS" != 0 ]]; then
  installed_pointer="$(readlink "$DEPLOY_ROOT/current" 2>/dev/null || true)"
  installed_release="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' reddit_voc_insights_web 2>/dev/null || true)"
  installed_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_insights_web 2>/dev/null || true)"
  if [[ "$installed_pointer" == "releases/$RELEASE_SHA" && "$installed_release" == "$RELEASE_SHA" && "$installed_health" == "healthy" ]]; then
    echo "installer returned non-zero after an exact healthy site commit; reconciling through the parent transaction" >&2
  elif [[ "$installed_pointer" == "releases/$EXPECTED_CURRENT" && "$installed_release" == "$EXPECTED_CURRENT" && "$installed_health" == "healthy" ]]; then
    fail "installer failed before the site commit"
  else
    fail "CRITICAL: installer failed with a mixed or unknown site state"
  fi
fi
SITE_COMMITTED=1
write_journal "site_committed" "$ORIGINAL_DATA_PREVIOUS_TARGET"
[[ "$(current_release)" == "$RELEASE_SHA" ]] || fail "production pointer mismatch after install"
[[ "$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}|{{.State.Health.Status}}|{{len .Mounts}}' reddit_voc_insights_web)" == "$RELEASE_SHA|healthy|1" ]] || fail "production container mismatch"
[[ "$(curl -fsS "http://$BIND_ADDRESS:18338/release.json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("release_sha256", ""))')" == "$RELEASE_SHA" ]] || fail "production HTTP release marker mismatch"
[[ -L "$DATA_ROOT/current" && "$(readlink "$DATA_ROOT/current")" == "releases/$DATA_RELEASE_ID" && "$(sha256sum "$PROMOTED_DATA_POINTER" | awk '{print $1}')" == "$TARGET_DATA_POINTER_SHA" ]] || fail "production data pointer mismatch after install"
[[ "$(candidate_count)" == 0 && "$(port_count)" == 0 ]] || fail "candidate residue"
verify_control_plane_baseline_unchanged

reconcile_committed_promotion
printf '%s\n' "$RECOVERED_EVIDENCE"
trap - EXIT
cleanup 0
