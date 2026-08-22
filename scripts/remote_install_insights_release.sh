#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: remote_install_insights_release.sh <archive> <archive-sha256> <release-sha256>" >&2
  exit 1
fi

ARCHIVE="$1"
EXPECTED_ARCHIVE_SHA="$2"
RELEASE_SHA="$3"
DEPLOY_ROOT="/opt/reddit-voc-insights-site"
RELEASE_ROOT="${DEPLOY_ROOT}/releases"
RELEASE_DIR="${RELEASE_ROOT}/${RELEASE_SHA}"
STAGING_DIR="${RELEASE_ROOT}/.staging-${RELEASE_SHA}"
EVIDENCE_ROOT="${DEPLOY_ROOT}/evidence"
PROMOTION_LOCK_FILE="${DEPLOY_ROOT}/.promotion.lock"
DEPLOY_LOCK_FILE="${DEPLOY_ROOT}/.deploy.lock"
COMPOSE_PROJECT="reddit_voc_insights"
CONTAINER_NAME="reddit_voc_insights_web"
BIND_ADDRESS="172.20.0.1"
PORT="18338"
DATA_ROOT="/opt/reddit-voc-insights-data"
DATA_CONTAINER_ROOT="/srv/reddit-voc-data"
DATA_LOCKS_DIR="${DATA_ROOT}/locks"
DATA_LOCK_FILE="${DATA_LOCKS_DIR}/data-release.lock"
RUNTIME_ROOT=""
PREVIOUS_RUNTIME_ROOT=""
COMPOSE_SNAPSHOT=""
COMPOSE_OVERRIDE=""
TARGET_IMAGE_ID="${INSIGHTS_PARENT_TRANSACTION_TARGET_IMAGE_ID:-}"

if [[ ! "${RELEASE_SHA}" =~ ^[a-f0-9]{64}$ ]]; then
  echo "invalid release sha256" >&2
  exit 1
fi
if [[ ! "${EXPECTED_ARCHIVE_SHA}" =~ ^[a-f0-9]{64}$ ]]; then
  echo "invalid archive sha256" >&2
  exit 1
fi
if [[ ! -f "${ARCHIVE}" || -L "${ARCHIVE}" ]]; then
  echo "release archive is missing or is a symlink" >&2
  exit 1
fi

for command in cp curl docker find flock mktemp python3 sha256sum ss tar; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "required command is missing: ${command}" >&2
    exit 1
  fi
done
sudo -n true

read_manifest_identity_and_collection_status() {
  python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
release = manifest.get("release_sha256")
if not isinstance(release, str):
    raise SystemExit("release manifest release_sha256 is invalid")
data_runtime = manifest.get("data_runtime")
expected_runtime = {
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
}
if data_runtime != expected_runtime:
    raise SystemExit("release manifest data runtime contract mismatch")
current_release = manifest.get("current_release")
data_release_id = (
    current_release.get("release_id")
    if isinstance(current_release, dict)
    else None
)
if (
    not isinstance(data_release_id, str)
    or not data_release_id.startswith("reddit_voc_release_")
):
    raise SystemExit("release manifest data release identity is invalid")

def flag(name: str) -> bool:
    value = manifest.get(name, False)
    if type(value) is not bool:
        raise SystemExit(f"release manifest {name} must be boolean")
    return value

integrated = flag("latest_collection_integrated")
fully_hydrated = flag("latest_collection_fully_hydrated")
if fully_hydrated and not integrated:
    raise SystemExit("release manifest collection status is impossible")
print(
    release,
    str(integrated).lower(),
    str(fully_hydrated).lower(),
    data_release_id,
    sep="\t",
)
PY
}

validate_data_root() {
  local expected_release_id="$1"
  python3 - "${DATA_ROOT}" "${expected_release_id}" <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys

root = Path(sys.argv[1])
expected = sys.argv[2]
release_pattern = re.compile(r"^reddit_voc_release_[a-z0-9_-]{3,120}$")
if release_pattern.fullmatch(expected) is None:
    raise SystemExit("expected data release identity is invalid")
if root.is_symlink() or not root.is_dir():
    raise SystemExit("dedicated data root is missing or unsafe")
current = root / "current"
if not current.is_symlink():
    raise SystemExit("dedicated data root current pointer is missing")
target = Path(os.readlink(current))
if (
    target.is_absolute()
    or len(target.parts) != 2
    or target.parts[0] != "releases"
    or target.parts[1] != expected
):
    raise SystemExit("dedicated data root current pointer mismatch")
release = (root / target).resolve(strict=True)
releases = (root / "releases").resolve(strict=True)
try:
    release.relative_to(releases)
except ValueError as exc:
    raise SystemExit("dedicated data release escaped releases root") from exc
public = release / "public"
projection = public / "data/reddit-voc"
pointer_path = projection / "current-release.json"
if not pointer_path.is_file() or pointer_path.is_symlink():
    raise SystemExit("mounted current-release pointer is missing or unsafe")
pointer_bytes = pointer_path.read_bytes()
pointer = json.loads(pointer_bytes.decode("utf-8"))
if (
    pointer.get("schema_version") != "reddit_voc_current_release_v2"
    or pointer.get("release_id") != expected
    or set(pointer.get("datasets", {})) != {
        "base", "insights", "reports", "personas",
        "brand_health", "quarter_insights", "casebook",
    }
):
    raise SystemExit("mounted current-release contract mismatch")
for directory in (root, releases, release, public, public / "data", projection):
    mode = directory.stat().st_mode
    if not directory.is_dir() or mode & 0o005 != 0o005:
        raise SystemExit(f"data directory is not container-readable: {directory}")
for path in projection.rglob("*"):
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise SystemExit(f"public data projection contains a symlink: {path}")
    if path.is_dir():
        if metadata.st_mode & 0o005 != 0o005:
            raise SystemExit(f"public data directory is not container-readable: {path}")
    elif path.is_file():
        if metadata.st_mode & 0o004 != 0o004:
            raise SystemExit(f"public data file is not container-readable: {path}")
    else:
        raise SystemExit(f"public data projection contains an unsafe entry: {path}")
print(sha256(pointer_bytes).hexdigest())
PY
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

assert_candidate_transaction_quiet() {
  local containers listeners
  containers="$(docker ps -a --format '{{.Names}}' | awk '/^reddit_voc_insights_candidate_/{n++} END{print n+0}')"
  listeners="$(ss -H -ltn | awk '$4 ~ /:18339$/{n++} END{print n+0}')"
  if [[ "${containers}" != 0 || "${listeners}" != 0 ]]; then
    echo "site pointer CAS blocked by candidate transaction activity" >&2
    return 1
  fi
}

cas_replace_site_pointer() {
  local expected_target="$1"
  local replacement_target="$2"
  validate_inherited_transaction_locks || return 1
  assert_candidate_transaction_quiet || return 1
  if ! python3 - \
    "${DEPLOY_ROOT}/current" "${expected_target}" "${replacement_target}" \
    "$(id -u)" <<'PY'
import ctypes
import os
import re
import secrets
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected, replacement = sys.argv[2:4]
owner = int(sys.argv[4])
target_pattern = re.compile(r"^releases/[a-f0-9]{64}$")
if (
    not path.is_absolute()
    or target_pattern.fullmatch(expected) is None
    or target_pattern.fullmatch(replacement) is None
    or expected == replacement
):
    raise SystemExit("site pointer CAS arguments are invalid")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("site pointer CAS requires O_NOFOLLOW")
parent = path.parent
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = f".{path.name}.install.{os.getpid()}.{secrets.token_hex(16)}.tmp"
temporary_created = False
replacement_metadata = None

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
        raise SystemExit("site pointer metadata is unsafe")
    return metadata, os.readlink(name, dir_fd=parent_fd)

try:
    parent_before = os.fstat(parent_fd)
    linked_parent = parent.lstat()
    if (
        not stat.S_ISDIR(parent_before.st_mode)
        or (parent_before.st_dev, parent_before.st_ino)
        != (linked_parent.st_dev, linked_parent.st_ino)
        or parent_before.st_uid != owner
        or parent_before.st_mode & 0o022
    ):
        raise SystemExit("site pointer parent directory is unsafe")
    current_before, current_target = linked(path.name)
    if current_target != expected:
        raise SystemExit("site pointer CAS expected target mismatch")
    os.symlink(replacement, temporary, dir_fd=parent_fd)
    temporary_created = True
    replacement_metadata, replacement_value = linked(temporary)
    if replacement_value != replacement:
        raise SystemExit("site pointer CAS temporary target mismatch")
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
            exchange_time, exchange_time_target = linked(temporary)
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
                    != (exchange_time.st_dev, exchange_time.st_ino)
                    or restored_target != exchange_time_target
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
                        "site pointer CAS failed to restore exchange-time destination"
                    )
        finally:
            raise SystemExit("site pointer CAS exchange verification failed")
    os.unlink(temporary, dir_fd=parent_fd)
    temporary_created = False
    final, final_target = linked(path.name)
    if (
        (final.st_dev, final.st_ino)
        != (replacement_metadata.st_dev, replacement_metadata.st_ino)
        or final_target != replacement
    ):
        raise SystemExit("site pointer CAS final verification failed")
    os.fsync(parent_fd)
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
  validate_inherited_transaction_locks || return 1
  assert_candidate_transaction_quiet || return 1
  if [[ ! -L "${DEPLOY_ROOT}/current" || \
        "$(readlink "${DEPLOY_ROOT}/current")" != "${replacement_target}" ]]; then
    echo "site pointer CAS postcondition failed" >&2
    return 1
  fi
}

snapshot_authenticated_archive() {
  local source="$1"
  local expected_sha="$2"
  python3 - "${source}" "${expected_sha}" <<'PY'
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

source = Path(sys.argv[1])
expected_sha = sys.argv[2]
runtime_root = Path("/opt/reddit-voc-insights-site/runtime")
sealed_root = source.parent
if (
    not source.is_absolute()
    or source.name != "release.tgz"
    or sealed_root.parent != runtime_root
    or re.fullmatch(r"\.promotion-[a-f0-9]{12}\.[A-Za-z0-9_-]{6,64}", sealed_root.name)
    is None
):
    raise SystemExit("release archive is not in the sealed promotion bundle")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("sealed archive validation requires O_NOFOLLOW")
runtime_metadata = runtime_root.lstat()
root_before = sealed_root.lstat()
before = source.lstat()
if (
    not stat.S_ISDIR(runtime_metadata.st_mode)
    or runtime_metadata.st_uid != 0
    or runtime_metadata.st_mode & 0o022
    or not stat.S_ISDIR(root_before.st_mode)
    or root_before.st_uid != 0
    or stat.S_IMODE(root_before.st_mode) != 0o555
    or not stat.S_ISREG(before.st_mode)
    or before.st_nlink != 1
    or before.st_uid != 0
    or stat.S_IMODE(before.st_mode) != 0o444
):
    raise SystemExit("sealed release archive identity is unsafe")
source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
try:
    opened = os.fstat(source_fd)
    if (
        (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        or opened.st_nlink != 1
        or opened.st_uid != 0
        or stat.S_IMODE(opened.st_mode) != 0o444
    ):
        raise SystemExit("sealed release archive changed while opening")
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    after = os.fstat(source_fd)
    if (
        (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
        or after.st_size != opened.st_size
        or after.st_mtime_ns != opened.st_mtime_ns
        or total != opened.st_size
        or digest.hexdigest() != expected_sha
    ):
        raise SystemExit("sealed release archive changed or differs from authorization")
finally:
    os.close(source_fd)
root_after = sealed_root.lstat()
if (root_after.st_dev, root_after.st_ino) != (
    root_before.st_dev,
    root_before.st_ino,
):
    raise SystemExit("sealed promotion bundle changed during archive validation")
PY
  ARCHIVE="${source}"
}

expected_image_id_from_archive() {
  local archive_path="$1"
  local image_ref="$2"
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
        raise SystemExit("image archive manifest is ambiguous")
    manifest_member = handle.getmember("manifest.json")
    if not manifest_member.isfile():
        raise SystemExit("image archive manifest is unsafe")
    manifest_stream = handle.extractfile(manifest_member)
    if manifest_stream is None:
        raise SystemExit("image archive manifest is unreadable")
    manifest = json.loads(manifest_stream.read())
    if not isinstance(manifest, list) or len(manifest) != 1:
        raise SystemExit("image archive cardinality mismatch")
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
        raise SystemExit("image archive identity mismatch")
    config_member = handle.getmember(config_name)
    if not config_member.isfile():
        raise SystemExit("image archive config is unsafe")
    config_stream = handle.extractfile(config_member)
    if config_stream is None:
        raise SystemExit("image archive config is unreadable")
    config = config_stream.read()
    digest = hashlib.sha256(config).hexdigest()
    if digest != (config_match.group(1) or config_match.group(2)):
        raise SystemExit("image archive config digest mismatch")
print(f"sha256:{digest}")
PY
}

verify_release_tree() {
  local root="$1"
  local release_sha="${2:-$RELEASE_SHA}"
  python3 - "${root}" "${release_sha}" "$(id -u)" <<'PY'
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

root = Path(sys.argv[1])
release = sys.argv[2]
owner = int(sys.argv[3])
expected_names = {
    "compose.yaml",
    "dist-SHA256SUMS",
    "release-manifest.json",
    f"reddit-voc-insights-{release}.tar",
}

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

root_before = root.lstat()
if (
    not stat.S_ISDIR(root_before.st_mode)
    or not immutable_directory(root_before)
):
    raise SystemExit("release tree root is unsafe")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("release tree validation requires O_NOFOLLOW")

def safe_read(path: Path) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or not immutable_file(before)
    ):
        raise SystemExit(f"release artifact identity is unsafe: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_nlink != 1
            or not immutable_file(opened)
        ):
            raise SystemExit(f"release artifact changed while opening: {path.name}")
        payload = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            payload += chunk
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or len(payload) != opened.st_size
        ):
            raise SystemExit(f"release artifact changed while reading: {path.name}")
        return payload
    finally:
        os.close(descriptor)

actual_entries = {path.name for path in root.iterdir()}
if actual_entries != expected_names | {"SHA256SUMS"}:
    raise SystemExit("release tree exact file inventory mismatch")
sums = safe_read(root / "SHA256SUMS").decode("utf-8")
expected = {}
for line in sums.splitlines():
    match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9._-]+)", line)
    if match is None:
        raise SystemExit("release checksum manifest contains an invalid entry")
    digest, name = match.groups()
    if name in expected:
        raise SystemExit("release checksum manifest contains a duplicate entry")
    expected[name] = digest
if set(expected) != expected_names:
    raise SystemExit("release checksum manifest exact inventory mismatch")
for name, digest in expected.items():
    if hashlib.sha256(safe_read(root / name)).hexdigest() != digest:
        raise SystemExit(f"release artifact digest mismatch: {name}")
root_after = root.lstat()
if (root_after.st_dev, root_after.st_ino) != (root_before.st_dev, root_before.st_ino):
    raise SystemExit("release tree root changed during validation")
PY
}

prepare_runtime_compose_snapshot() {
  local release_root="$1"
  local release_sha="$2"
  local image_id="$3"
  local prefix="$4"
  local runtime_root
  runtime_root="$(mktemp -d "/tmp/reddit-voc-${prefix}-compose.XXXXXX")"
  chmod 0700 "${runtime_root}"
  python3 - "${release_root}" "${runtime_root}" "${release_sha}" "${image_id}" "$(id -u)" <<'PY'
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

source_root = Path(sys.argv[1])
runtime_root = Path(sys.argv[2])
release = sys.argv[3]
image_id = sys.argv[4]
owner = int(sys.argv[5])
if re.fullmatch(r"[a-f0-9]{64}", release) is None or re.fullmatch(
    r"sha256:[a-f0-9]{64}", image_id
) is None:
    raise SystemExit("runtime compose snapshot identity is invalid")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("runtime compose snapshot requires O_NOFOLLOW")

def immutable_source(metadata) -> bool:
    return (
        metadata.st_uid == owner and not metadata.st_mode & 0o022
    ) or (
        metadata.st_uid == 0
        and metadata.st_gid == 0
        and stat.S_IMODE(metadata.st_mode) == 0o444
    )

def read_source(path: Path) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or not immutable_source(before)
    ):
        raise SystemExit(f"runtime compose source is unsafe: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or not immutable_source(opened)
        ):
            raise SystemExit(f"runtime compose source changed while opening: {path.name}")
        payload = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            payload += chunk
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or len(payload) != opened.st_size
        ):
            raise SystemExit(f"runtime compose source changed while reading: {path.name}")
        return payload
    finally:
        os.close(descriptor)

sums_lines = read_source(source_root / "SHA256SUMS").decode("utf-8").splitlines()
matches = [
    match.group(1)
    for line in sums_lines
    if (match := re.fullmatch(r"([a-f0-9]{64})  compose\.yaml", line))
]
if len(matches) != 1:
    raise SystemExit("runtime compose checksum binding is invalid")
source = source_root / "compose.yaml"
before = source.lstat()
if (
    not stat.S_ISREG(before.st_mode)
    or before.st_nlink != 1
    or not immutable_source(before)
):
    raise SystemExit("runtime compose source is unsafe")
payload = read_source(source)
if hashlib.sha256(payload).hexdigest() != matches[0]:
    raise SystemExit("runtime compose source changed or is unauthenticated")
override = (
    "services:\n"
    "  web:\n"
    f"    image: {image_id}\n"
    "    pull_policy: never\n"
).encode("utf-8")
for name, content in (
    ("compose.yaml", payload),
    ("compose-image-id.yaml", override),
    ("compose.sha256", (hashlib.sha256(payload).hexdigest() + "\n").encode()),
):
    descriptor = os.open(
        runtime_root / name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
    )
    try:
        written = 0
        while written < len(content):
            count = os.write(descriptor, content[written:])
            if count <= 0:
                raise SystemExit("runtime compose snapshot write was incomplete")
            written += count
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != owner
            or stat.S_IMODE(metadata.st_mode) != 0o400
        ):
            raise SystemExit("runtime compose snapshot file is unsafe")
    finally:
        os.close(descriptor)
directory_fd = os.open(runtime_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
  sudo chown root:root \
    "${runtime_root}" \
    "${runtime_root}/compose.yaml" \
    "${runtime_root}/compose-image-id.yaml" \
    "${runtime_root}/compose.sha256"
  sudo chmod 0555 "${runtime_root}"
  sudo chmod 0444 \
    "${runtime_root}/compose.yaml" \
    "${runtime_root}/compose-image-id.yaml" \
    "${runtime_root}/compose.sha256"
  printf '%s\n' "${runtime_root}"
}

verify_runtime_compose_snapshot() {
  local runtime_root="$1"
  local release_root="$2"
  local image_id="$3"
  python3 - "${runtime_root}" "${release_root}" "${image_id}" <<'PY'
import hashlib
import os
from pathlib import Path
import re
import stat
import sys

runtime_root = Path(sys.argv[1])
release_root = Path(sys.argv[2])
image_id = sys.argv[3]
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("runtime compose verification requires O_NOFOLLOW")
root_before = runtime_root.lstat()
if (
    not stat.S_ISDIR(root_before.st_mode)
    or root_before.st_uid != 0
    or stat.S_IMODE(root_before.st_mode) != 0o555
    or {path.name for path in runtime_root.iterdir()}
    != {"compose.yaml", "compose-image-id.yaml", "compose.sha256"}
):
    raise SystemExit("runtime compose snapshot root is not sealed")

def safe_read(path: Path, owner: int, mode: int) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != owner
        or stat.S_IMODE(before.st_mode) != mode
    ):
        raise SystemExit(f"runtime compose snapshot file is unsafe: {path.name}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        payload = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            payload += chunk
        after = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or len(payload) != opened.st_size
        ):
            raise SystemExit("runtime compose snapshot changed while reading")
        return payload
    finally:
        os.close(descriptor)

compose = safe_read(runtime_root / "compose.yaml", 0, 0o444)
override = safe_read(runtime_root / "compose-image-id.yaml", 0, 0o444)
compose_sha = safe_read(runtime_root / "compose.sha256", 0, 0o444)
expected_override = (
    "services:\n"
    "  web:\n"
    f"    image: {image_id}\n"
    "    pull_policy: never\n"
).encode()
if override != expected_override:
    raise SystemExit("runtime exact-image override changed")
if compose_sha != (hashlib.sha256(compose).hexdigest() + "\n").encode():
    raise SystemExit("runtime compose snapshot digest changed")
sums = (release_root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
matches = [
    match.group(1)
    for line in sums
    if (match := re.fullmatch(r"([a-f0-9]{64})  compose\.yaml", line))
]
if len(matches) != 1 or hashlib.sha256(compose).hexdigest() != matches[0]:
    raise SystemExit("runtime compose snapshot lost its release checksum binding")
root_after = runtime_root.lstat()
if (root_after.st_dev, root_after.st_ino) != (root_before.st_dev, root_before.st_ino):
    raise SystemExit("runtime compose snapshot root changed")
PY
}

verify_runtime_compose_contract() {
  local compose_path="$1"
  local override_path="$2"
  local release_sha="$3"
  local image_id="$4"
  local release_root="$5"
  local compose_json
  verify_runtime_compose_snapshot \
    "$(dirname "${compose_path}")" "${release_root}" "${image_id}" || return 1
  compose_json="$(
    RELEASE_SHA="${release_sha}" \
    REDDIT_VOC_DATA_ROOT="${DATA_ROOT}" \
    INSIGHTS_BIND_ADDRESS="${BIND_ADDRESS}" \
    INSIGHTS_PORT="${PORT}" \
      docker compose -p "${COMPOSE_PROJECT}" \
        -f "${compose_path}" -f "${override_path}" \
        config --format json
  )" || return 1
  python3 - "${compose_json}" "${release_sha}" "${image_id}" \
    "${DATA_ROOT}" "${DATA_CONTAINER_ROOT}" "${BIND_ADDRESS}" "${PORT}" <<'PY'
import json
import sys

(raw, release, image_id, data_root, data_container_root, bind_address, port) = sys.argv[1:]
value = json.loads(raw)
services = value.get("services") if isinstance(value, dict) else None
networks = value.get("networks") if isinstance(value, dict) else None
if (
    set(value) != {"name", "networks", "services"}
    or value.get("name") != "reddit_voc_insights"
    or not isinstance(services, dict)
    or set(services) != {"web"}
    or not isinstance(networks, dict)
    or set(networks) != {"insights"}
):
    raise SystemExit("installer merged compose topology is invalid")
web = services["web"]
network = networks["insights"]
if not isinstance(web, dict) or not isinstance(network, dict):
    raise SystemExit("installer merged compose shape is invalid")
if set(web) != {
    "cap_drop", "command", "container_name", "cpus", "entrypoint",
    "environment", "healthcheck", "image", "init", "labels", "logging",
    "mem_limit", "networks", "pids_limit", "ports", "pull_policy",
    "read_only", "restart", "security_opt", "tmpfs", "user", "volumes",
}:
    raise SystemExit("installer merged compose service key set changed")
if set(network) != {"driver", "driver_opts", "ipam", "name"}:
    raise SystemExit("installer merged compose network key set changed")

def require(condition, message):
    if not condition:
        raise SystemExit(message)

require(web.get("image") == image_id, "installer compose image is not the authenticated ID")
require(web.get("pull_policy") == "never", "installer compose pull policy changed")
require(web.get("container_name") == "reddit_voc_insights_web", "installer compose container name changed")
require(web.get("command") is None, "installer compose command changed")
require(web.get("entrypoint") is None, "installer compose entrypoint changed")
require(web.get("user") == "101:101", "installer compose user changed")
require(web.get("read_only") is True, "installer compose root filesystem changed")
require(web.get("init") is True, "installer compose init contract changed")
require(web.get("restart") == "unless-stopped", "installer compose restart policy changed")
require(web.get("cap_drop") == ["ALL"], "installer compose capability drop changed")
require(web.get("security_opt") == ["no-new-privileges:true"], "installer compose security options changed")
require(web.get("pids_limit") == 100, "installer compose PID limit changed")
require(web.get("mem_limit") in (268435456, "268435456", "256m"), "installer compose memory limit changed")
require(web.get("cpus") in (0.5, "0.5", "0.50"), "installer compose CPU limit changed")
require(web.get("environment") == {"NGINX_ENTRYPOINT_QUIET_LOGS": "1"}, "installer compose environment changed")
require(web.get("labels") == {
    "com.reddit-voc.component": "insights-site",
    "com.reddit-voc.release": release,
}, "installer compose labels changed")
require(web.get("networks") == {"insights": None}, "installer compose service network changed")
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
}, "installer compose healthcheck changed")
require(web.get("logging") == {
    "driver": "json-file",
    "options": {"max-file": "3", "max-size": "10m"},
}, "installer compose logging changed")
require(
    web.get("tmpfs")
    == ["/tmp:rw,noexec,nosuid,nodev,size=32m,uid=101,gid=101,mode=1777"],
    "installer compose tmpfs changed",
)
volumes = web.get("volumes")
require(isinstance(volumes, list) and len(volumes) == 1, "installer compose volume count changed")
volume = volumes[0]
require(
    isinstance(volume, dict)
    and volume.get("type") == "bind"
    and volume.get("source") == data_root
    and volume.get("target") == data_container_root
    and volume.get("read_only") is True
    and volume.get("bind") in ({}, {"create_host_path": True}),
    "installer compose data mount changed",
)
ports = web.get("ports")
require(isinstance(ports, list) and len(ports) == 1, "installer compose port count changed")
binding = ports[0]
require(
    isinstance(binding, dict)
    and str(binding.get("target")) == "8080"
    and str(binding.get("published")) == port
    and binding.get("host_ip") == bind_address
    and binding.get("mode") == "ingress"
    and binding.get("protocol", "tcp") == "tcp",
    "installer compose port binding changed",
)
require(network.get("name") == "reddit_voc_insights_net", "installer compose network name changed")
require(network.get("driver") == "bridge", "installer compose network driver changed")
require(network.get("ipam") == {}, "installer compose network IPAM changed")
require(network.get("driver_opts") == {
    "com.docker.network.bridge.enable_icc": "false",
    "com.docker.network.bridge.enable_ip_masquerade": "false",
}, "installer compose network isolation options changed")
PY
}

validate_inherited_transaction_locks() {
  python3 - \
    "7:${PROMOTION_LOCK_FILE}" \
    "9:${DEPLOY_LOCK_FILE}" \
    "8:${DATA_LOCK_FILE}" <<'PY'
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
        raise SystemExit(f"inherited transaction lock fd {descriptor} is invalid")
    if not hasattr(os, "O_NOFOLLOW"):
        raise SystemExit("inherited transaction lock validation requires O_NOFOLLOW")
    probe_flags = os.O_RDWR | os.O_NOFOLLOW
    probe = os.open(path, probe_flags)
    try:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
        else:
            fcntl.flock(probe, fcntl.LOCK_UN)
            raise SystemExit(f"inherited transaction lock fd {descriptor} is not locked")
    finally:
        os.close(probe)
PY
}

validate_parent_transaction_invocation() {
  if [[ "${INSIGHTS_PARENT_TRANSACTION_LOCKS:-0}" != 1 || \
        "${INSIGHTS_PARENT_TRANSACTION_MARKER:-}" != reddit_voc_promotion_parent_v1 || \
        "${INSIGHTS_PARENT_TRANSACTION_RELEASE_SHA:-}" != "$RELEASE_SHA" || \
        "${INSIGHTS_PARENT_TRANSACTION_ARCHIVE_SHA:-}" != "$EXPECTED_ARCHIVE_SHA" || \
        ! "${INSIGHTS_PARENT_TRANSACTION_PACKET_SHA:-}" =~ ^[a-f0-9]{64}$ || \
        ! "${INSIGHTS_PARENT_TRANSACTION_DATA_RELEASE_ID:-}" =~ ^reddit_voc_release_[a-z0-9_-]+$ || \
        ! "${INSIGHTS_PARENT_TRANSACTION_EXPECTED_SITE_RELEASE_SHA:-}" =~ ^[a-f0-9]{64}$ || \
        ! "${INSIGHTS_PARENT_TRANSACTION_EXPECTED_DATA_RELEASE_ID:-}" =~ ^reddit_voc_release_[a-z0-9_-]+$ || \
        ! "${INSIGHTS_PARENT_TRANSACTION_TARGET_DATA_POINTER_SHA:-}" =~ ^[a-f0-9]{64}$ || \
        ! "${TARGET_IMAGE_ID}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "standalone installer execution is disabled; use the exact authorized promotion parent transaction" >&2
    return 1
  fi
}

assert_safe_window() {
  local hhmm hhmm_number
  hhmm="$(TZ=Asia/Shanghai date +%H%M)"
  hhmm_number=$((10#${hhmm}))
  if (( hhmm_number >= 630 && hhmm_number <= 830 )); then
    echo "deployment blocked during the 06:30-08:30 collection/report window" >&2
    return 1
  fi
}
assert_safe_window

if [[ -L "${DEPLOY_ROOT}" || -L "${RELEASE_ROOT}" || -L "${EVIDENCE_ROOT}" || -L "${DATA_ROOT}" || -L "${DATA_LOCKS_DIR}" ]]; then
  echo "deployment directories must not be symlinks" >&2
  exit 1
fi
if [[ ! -d "${DEPLOY_ROOT}" || ! -d "${DATA_ROOT}" || -L "${DEPLOY_ROOT}" || -L "${DATA_ROOT}" ]]; then
  echo "initialized Reddit VOC insights site/data roots are missing or unsafe" >&2
  exit 1
fi
if [[ ! -d "${DATA_LOCKS_DIR}" || -L "${DATA_LOCKS_DIR}" ]]; then
  echo "initialized data lock directory is missing or unsafe; use the controlled promotion transaction" >&2
  exit 1
fi
if [[ "$(stat -c '%u|%a' "${DATA_LOCKS_DIR}")" != "$(id -u)|700" ]]; then
  echo "data lock directory contract mismatch" >&2
  exit 1
fi
validate_parent_transaction_invocation
validate_inherited_transaction_locks
if [[ ! -L "${DATA_ROOT}/current" || \
      "$(readlink "${DATA_ROOT}/current")" != "releases/${INSIGHTS_PARENT_TRANSACTION_DATA_RELEASE_ID}" || \
      ! -L "${DATA_ROOT}/previous" || \
      "$(readlink "${DATA_ROOT}/previous")" != "releases/${INSIGHTS_PARENT_TRANSACTION_EXPECTED_DATA_RELEASE_ID}" ]]; then
  echo "parent transaction data current/previous CAS mismatch" >&2
  exit 1
fi
sudo mkdir -p "${RELEASE_ROOT}" "${EVIDENCE_ROOT}"
sudo chown "$(id -u):$(id -g)" "${DEPLOY_ROOT}" "${RELEASE_ROOT}" "${EVIDENCE_ROOT}"

cleanup_private_roots() {
  if [[ -n "${PREVIOUS_RUNTIME_ROOT}" && -d "${PREVIOUS_RUNTIME_ROOT}" ]]; then
    sudo rm -rf "${PREVIOUS_RUNTIME_ROOT}" 2>/dev/null || true
  fi
  if [[ -n "${RUNTIME_ROOT}" && -d "${RUNTIME_ROOT}" ]]; then
    sudo rm -rf "${RUNTIME_ROOT}" 2>/dev/null || true
  fi
}
trap 'cleanup_private_roots' EXIT
snapshot_authenticated_archive "${ARCHIVE}" "${EXPECTED_ARCHIVE_SHA}"

actual_archive_sha="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
if [[ "${actual_archive_sha}" != "${EXPECTED_ARCHIVE_SHA}" ]]; then
  echo "release archive sha256 mismatch" >&2
  exit 1
fi

if tar -tzf "${ARCHIVE}" | awk -v prefix="${RELEASE_SHA}/" '
  /^\// || /(^|\/)\.\.($|\/)/ || index($0, prefix) != 1 { bad=1 }
  END { exit bad ? 0 : 1 }
'; then
  echo "release archive contains an unsafe path" >&2
  exit 1
fi

collector_id="$(docker inspect -f '{{.Id}}' reddit_voc_site_app)"
collector_restart="$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)"
collector_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_site_app)"
translation_id="$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)"
translation_restart="$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)"
translation_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' reddit_voc_libretranslate)"

if [[ "${collector_health}" != "healthy" || "${translation_health}" != "healthy" ]]; then
  echo "deployment blocked because an existing Reddit container is not healthy" >&2
  exit 1
fi
if docker ps --format '{{.Names}}' | grep -q '^reddit_voc_site_app-run-'; then
  echo "deployment blocked because a collector one-shot container is running" >&2
  exit 1
fi

nginx_sha="$(sha256sum /opt/ai-video/deploy/lighthouse/nginx.conf | awk '{print $1}')"
cron_sha="$(sudo sha256sum /etc/cron.d/reddit-voc-site | awk '{print $1}')"
curl -fsS http://127.0.0.1:18337/api/health >/dev/null

database_before="$(stat -c '%Y:%s:%i' /opt/reddit-voc-site/data/reddit_voc_daily.sqlite3)"
report_before="$(stat -c '%Y:%s:%i' /opt/reddit-voc-report/current 2>/dev/null || printf 'absent')"
sleep 5
database_after="$(stat -c '%Y:%s:%i' /opt/reddit-voc-site/data/reddit_voc_daily.sqlite3)"
report_after="$(stat -c '%Y:%s:%i' /opt/reddit-voc-report/current 2>/dev/null || printf 'absent')"
if [[ "${database_before}" != "${database_after}" || "${report_before}" != "${report_after}" ]]; then
  echo "deployment blocked because collector/report state changed during preflight" >&2
  exit 1
fi

previous_release_sha=""
if [[ -L "${DEPLOY_ROOT}/current" ]]; then
  current_target="$(readlink "${DEPLOY_ROOT}/current")"
  if [[ "${current_target}" =~ ^releases/([a-f0-9]{64})$ ]]; then
    previous_release_sha="${BASH_REMATCH[1]}"
  else
    echo "current release symlink has an invalid target" >&2
    exit 1
  fi
  if [[ ! -d "${RELEASE_ROOT}/${previous_release_sha}" || -L "${RELEASE_ROOT}/${previous_release_sha}" ]]; then
    echo "current release directory is missing or unsafe" >&2
    exit 1
  fi
elif [[ -e "${DEPLOY_ROOT}/current" ]]; then
  echo "current release pointer must be a symlink" >&2
  exit 1
fi
if [[ "${previous_release_sha}" != "${INSIGHTS_PARENT_TRANSACTION_EXPECTED_SITE_RELEASE_SHA}" ]]; then
  echo "parent transaction expected-current site CAS mismatch" >&2
  exit 1
fi

if [[ -e "${STAGING_DIR}" ]]; then
  echo "staging directory already exists" >&2
  exit 1
fi

if [[ -e "${RELEASE_DIR}" ]]; then
  if [[ ! -d "${RELEASE_DIR}" || -L "${RELEASE_DIR}" || "${previous_release_sha}" != "${RELEASE_SHA}" ]]; then
    echo "existing release is not the active immutable release" >&2
    exit 1
  fi
  for required in compose.yaml release-manifest.json SHA256SUMS; do
    if [[ ! -f "${RELEASE_DIR}/${required}" ]]; then
      echo "active release is missing ${required}" >&2
      exit 1
    fi
  done
  (
    cd "${RELEASE_DIR}"
    sha256sum --check SHA256SUMS
  )
  verify_release_tree "${RELEASE_DIR}"
  active_archive_image_id="$(expected_image_id_from_archive \
    "${RELEASE_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar" \
    "reddit-voc-insights:${RELEASE_SHA}")"
  if [[ "${active_archive_image_id}" != "${TARGET_IMAGE_ID}" ]]; then
    echo "active release image differs from the parent-authorized target image ID" >&2
    exit 1
  fi
  IFS=$'\t' read -r active_manifest_release active_collection_integrated active_collection_fully_hydrated active_data_release_id \
    < <(read_manifest_identity_and_collection_status "${RELEASE_DIR}/release-manifest.json")
  active_data_pointer_sha="$(validate_data_root "${active_data_release_id}")"
  active_container_release="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
  active_container_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
  active_container_image="$(docker inspect -f '{{.Image}}|{{.Config.Image}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
  active_http_release="$(curl -fsS "http://${BIND_ADDRESS}:${PORT}/release.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["release_sha256"])' 2>/dev/null || true)"
  if [[ "${active_manifest_release}" != "${RELEASE_SHA}" || \
        "${active_container_release}" != "${RELEASE_SHA}" || \
        "${active_container_health}" != "healthy" || \
        "${active_container_image}" != "${TARGET_IMAGE_ID}|${TARGET_IMAGE_ID}" || \
        "${active_http_release}" != "${RELEASE_SHA}" ]]; then
    echo "existing active release failed its idempotency contract" >&2
    exit 1
  fi
  rm -f "${ARCHIVE}" || echo "warning: active-release archive cleanup failed" >&2
  printf '%s\n' \
    "release_sha=${RELEASE_SHA}" \
    "container_health=${active_container_health}" \
    "already_active=true" \
    "data_release_id=${active_data_release_id}" \
    "data_pointer_sha256=${active_data_pointer_sha}" \
    "latest_collection_integrated=${active_collection_integrated}" \
    "latest_collection_fully_hydrated=${active_collection_fully_hydrated}" \
    "backend_health_preserved=true"
  exit 0
fi

existing_container="$(docker ps -a --filter "name=^/${CONTAINER_NAME}$" --format '{{.Names}}')"
if [[ -n "${existing_container}" ]]; then
  component_label="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.component"}}' "${CONTAINER_NAME}")"
  existing_release="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' "${CONTAINER_NAME}")"
  existing_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${CONTAINER_NAME}")"
  if [[ "${component_label}" != "insights-site" || "${existing_release}" != "${previous_release_sha}" || "${existing_health}" != "healthy" ]]; then
    echo "existing insights container does not match the current healthy release" >&2
    exit 1
  fi
elif [[ -n "${previous_release_sha}" ]]; then
  echo "current release exists but its container is missing" >&2
  exit 1
elif ss -H -ltn | awk '{print $4}' | grep -qE "(^|:)${PORT}$"; then
  echo "deployment port ${PORT} is already in use" >&2
  exit 1
fi

mkdir "${STAGING_DIR}"
chmod 0700 "${STAGING_DIR}"
VERIFY_DIR=""
VERIFY_CONTAINER=""
VERIFY_CONTAINER_NAME="reddit_voc_insights_verify_${RELEASE_SHA:0:12}"
CURRENT_TMP="${DEPLOY_ROOT}/.current-${RELEASE_SHA}.$$"
release_committed=0
deployment_succeeded=0
current_switched=0

cleanup_transient() {
  if [[ -n "${VERIFY_CONTAINER}" ]]; then
    docker rm -f "${VERIFY_CONTAINER}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${VERIFY_DIR}" && -d "${VERIFY_DIR}" ]]; then
    rm -rf "${VERIFY_DIR}"
  fi
  if [[ -d "${STAGING_DIR}" ]]; then
    chmod -R u+rwX "${STAGING_DIR}" 2>/dev/null || true
    rm -rf "${STAGING_DIR}"
  fi
  rm -f "${CURRENT_TMP}"
  cleanup_private_roots
}

wait_for_release_health() {
  local expected_release="$1"
  local health=""
  for _ in $(seq 1 60); do
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${CONTAINER_NAME}" 2>/dev/null || printf 'missing')"
    if [[ "${health}" == "healthy" ]] && curl -fsS "http://${BIND_ADDRESS}:${PORT}/healthz" >/dev/null 2>&1; then
      [[ "$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' "${CONTAINER_NAME}")" == "${expected_release}" ]]
      return
    fi
    if [[ "${health}" == "unhealthy" ]]; then
      return 1
    fi
    sleep 2
  done
  return 1
}

rollback_release() {
  local rollback_ok=1
  echo "deployment failed; rolling back the isolated insights container" >&2
  if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    container_release="$(docker inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
    if [[ "${container_release}" == "${RELEASE_SHA}" ]]; then
      RELEASE_SHA="${RELEASE_SHA}" REDDIT_VOC_DATA_ROOT="${DATA_ROOT}" INSIGHTS_BIND_ADDRESS="${BIND_ADDRESS}" INSIGHTS_PORT="${PORT}" \
        docker compose -p "${COMPOSE_PROJECT}" \
          -f "${COMPOSE_SNAPSHOT}" -f "${COMPOSE_OVERRIDE}" \
          down >/dev/null 2>&1 || rollback_ok=0
    fi
  fi

  if [[ -n "${previous_release_sha}" ]]; then
    previous_release_root="${RELEASE_ROOT}/${previous_release_sha}"
    previous_image_ref="reddit-voc-insights:${previous_release_sha}"
    verify_release_tree "${previous_release_root}" "${previous_release_sha}" || rollback_ok=0
    previous_image_id="$(expected_image_id_from_archive \
      "${previous_release_root}/reddit-voc-insights-${previous_release_sha}.tar" \
      "${previous_image_ref}")" || rollback_ok=0
    if [[ "${rollback_ok}" == "1" ]]; then
      docker load --input \
        "${previous_release_root}/reddit-voc-insights-${previous_release_sha}.tar" \
        >/dev/null || rollback_ok=0
    fi
    if [[ "${rollback_ok}" == "1" && \
          "$(docker image inspect -f '{{.Id}}' "${previous_image_id}" 2>/dev/null || true)" != "${previous_image_id}" ]]; then
      rollback_ok=0
    fi
    if [[ "${rollback_ok}" == "1" ]]; then
      PREVIOUS_RUNTIME_ROOT="$(prepare_runtime_compose_snapshot \
        "${previous_release_root}" "${previous_release_sha}" \
        "${previous_image_id}" previous)" || rollback_ok=0
    fi
    if [[ "${rollback_ok}" == "1" ]]; then
      verify_runtime_compose_contract \
        "${PREVIOUS_RUNTIME_ROOT}/compose.yaml" \
        "${PREVIOUS_RUNTIME_ROOT}/compose-image-id.yaml" \
        "${previous_release_sha}" "${previous_image_id}" \
        "${previous_release_root}" || rollback_ok=0
    fi
    if [[ "${rollback_ok}" == "1" ]]; then
      RELEASE_SHA="${previous_release_sha}" REDDIT_VOC_DATA_ROOT="${DATA_ROOT}" INSIGHTS_BIND_ADDRESS="${BIND_ADDRESS}" INSIGHTS_PORT="${PORT}" \
        docker compose -p "${COMPOSE_PROJECT}" \
          -f "${PREVIOUS_RUNTIME_ROOT}/compose.yaml" \
          -f "${PREVIOUS_RUNTIME_ROOT}/compose-image-id.yaml" \
          up -d --no-build --no-deps --pull never web >/dev/null 2>&1 || rollback_ok=0
    fi
    if [[ "${rollback_ok}" == "1" ]]; then
      wait_for_release_health "${previous_release_sha}" || rollback_ok=0
    fi
    if [[ "${current_switched}" == "1" ]]; then
      if cas_replace_site_pointer \
        "releases/${RELEASE_SHA}" "releases/${previous_release_sha}"; then
        current_switched=0
      else
        rollback_ok=0
      fi
    fi
  elif [[ "${current_switched}" == "1" ]]; then
    echo "site pointer rollback cannot target absence under the parent transaction" >&2
    rollback_ok=0
  fi

  if [[ "${rollback_ok}" == "1" && "${release_committed}" == "1" && -d "${RELEASE_DIR}" && ! -L "${RELEASE_DIR}" ]]; then
    rm -rf "${RELEASE_DIR}" && fsync_directory "${RELEASE_ROOT}" || rollback_ok=0
  fi
  [[ "${rollback_ok}" == "1" ]]
}

on_exit() {
  local status="$1"
  trap - EXIT
  set +e
  if [[ "${status}" != "0" && "${release_committed}" == "1" && "${deployment_succeeded}" != "1" ]]; then
    if ! rollback_release; then
      echo "CRITICAL: automatic rollback did not complete; inspect ${DEPLOY_ROOT} before retrying" >&2
    fi
  fi
  cleanup_transient
  exit "${status}"
}
trap 'on_exit $?' EXIT

tar -xzf "${ARCHIVE}" -C "${STAGING_DIR}" --strip-components=1 \
  --no-same-owner --no-same-permissions
if find "${STAGING_DIR}" -type l -print -quit | grep -q . || \
   find "${STAGING_DIR}" ! -type d ! -type f -print -quit | grep -q .; then
  echo "release payload contains an unsafe entry" >&2
  exit 1
fi

for required in compose.yaml dist-SHA256SUMS release-manifest.json SHA256SUMS "reddit-voc-insights-${RELEASE_SHA}.tar"; do
  if [[ ! -f "${STAGING_DIR}/${required}" ]]; then
    echo "release payload is missing ${required}" >&2
    exit 1
  fi
done

(
  cd "${STAGING_DIR}"
  sha256sum --check SHA256SUMS
)
verify_release_tree "${STAGING_DIR}"

IFS=$'\t' read -r manifest_release manifest_collection_integrated manifest_collection_fully_hydrated manifest_data_release_id \
  < <(read_manifest_identity_and_collection_status "${STAGING_DIR}/release-manifest.json")
if [[ "${manifest_release}" != "${RELEASE_SHA}" ]]; then
  echo "release manifest identity mismatch" >&2
  exit 1
fi
if [[ "${manifest_data_release_id}" != "${INSIGHTS_PARENT_TRANSACTION_DATA_RELEASE_ID}" ]]; then
  echo "parent transaction target data release mismatch" >&2
  exit 1
fi
manifest_data_pointer_sha="$(validate_data_root "${manifest_data_release_id}")"
if [[ "${manifest_data_pointer_sha}" != "${INSIGHTS_PARENT_TRANSACTION_TARGET_DATA_POINTER_SHA}" ]]; then
  echo "parent transaction target data pointer mismatch" >&2
  exit 1
fi

image_ref="reddit-voc-insights:${RELEASE_SHA}"
archive_image_id="$(expected_image_id_from_archive \
  "${STAGING_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar" "${image_ref}")"
if [[ "${archive_image_id}" != "${TARGET_IMAGE_ID}" ]]; then
  echo "image archive ID differs from the parent-authorized target image ID" >&2
  exit 1
fi
docker load --input "${STAGING_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar"
image_id="$(docker image inspect -f '{{.Id}}' "${TARGET_IMAGE_ID}")"
tag_image_id="$(docker image inspect -f '{{.Id}}' "${image_ref}")"
image_arch="$(docker image inspect -f '{{.Architecture}}' "${TARGET_IMAGE_ID}")"
image_user="$(docker image inspect -f '{{.Config.User}}' "${TARGET_IMAGE_ID}")"
image_release="$(docker image inspect -f '{{index .Config.Labels "com.reddit-voc.release"}}' "${TARGET_IMAGE_ID}")"
if [[ "${image_id}" != "${TARGET_IMAGE_ID}" || \
      "${tag_image_id}" != "${TARGET_IMAGE_ID}" || \
      "${image_arch}" != "amd64" || "${image_user}" != "101:101" || \
      "${image_release}" != "${RELEASE_SHA}" ]]; then
  echo "loaded image contract mismatch" >&2
  exit 1
fi

VERIFY_DIR="$(mktemp -d "${RELEASE_ROOT}/.verify-${RELEASE_SHA}.XXXXXX")"
mkdir "${VERIFY_DIR}/dist"
if [[ -n "$(docker ps -a --filter "name=^/${VERIFY_CONTAINER_NAME}$" --format '{{.Names}}')" ]]; then
  echo "deterministic image verification container slot is occupied" >&2
  exit 1
fi
docker create --name "${VERIFY_CONTAINER_NAME}" \
  --label com.reddit-voc.component=insights-image-verifier \
  --label "com.reddit-voc.release=${RELEASE_SHA}" \
  --label "com.reddit-voc.promotion-packet=${INSIGHTS_PARENT_TRANSACTION_PACKET_SHA}" \
  "${TARGET_IMAGE_ID}" >/dev/null
VERIFY_CONTAINER="${VERIFY_CONTAINER_NAME}"
docker cp "${VERIFY_CONTAINER}:/usr/share/nginx/html/." "${VERIFY_DIR}/dist/"
docker rm "${VERIFY_CONTAINER}" >/dev/null
VERIFY_CONTAINER=""
(
  cd "${VERIFY_DIR}"
  sha256sum --check "${STAGING_DIR}/dist-SHA256SUMS"
)
marker_release="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release_sha256"])' "${VERIFY_DIR}/dist/release.json")"
if [[ "${marker_release}" != "${RELEASE_SHA}" ]]; then
  echo "image release marker mismatch" >&2
  exit 1
fi
rm -rf "${VERIFY_DIR}"
VERIFY_DIR=""
verify_release_tree "${STAGING_DIR}"

find "${STAGING_DIR}" -depth -type f -exec chmod 0400 {} +
find "${STAGING_DIR}" -depth -type d -exec chmod 0500 {} +
verify_release_tree "${STAGING_DIR}"
RUNTIME_ROOT="$(prepare_runtime_compose_snapshot \
  "${STAGING_DIR}" "${RELEASE_SHA}" "${TARGET_IMAGE_ID}" target)"
COMPOSE_SNAPSHOT="${RUNTIME_ROOT}/compose.yaml"
COMPOSE_OVERRIDE="${RUNTIME_ROOT}/compose-image-id.yaml"
verify_runtime_compose_contract \
  "${COMPOSE_SNAPSHOT}" "${COMPOSE_OVERRIDE}" \
  "${RELEASE_SHA}" "${TARGET_IMAGE_ID}" "${STAGING_DIR}"

assert_safe_window
if docker ps --format '{{.Names}}' | grep -q '^reddit_voc_site_app-run-' || \
   [[ "$(docker inspect -f '{{.Id}}' reddit_voc_site_app)" != "${collector_id}" ]] || \
   [[ "$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)" != "${collector_restart}" ]] || \
   [[ "$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)" != "${translation_id}" ]] || \
   [[ "$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)" != "${translation_restart}" ]] || \
   [[ "$(sha256sum /opt/ai-video/deploy/lighthouse/nginx.conf | awk '{print $1}')" != "${nginx_sha}" ]] || \
   [[ "$(sudo sha256sum /etc/cron.d/reddit-voc-site | awk '{print $1}')" != "${cron_sha}" ]]; then
  echo "production baseline changed before isolated container activation" >&2
  exit 1
fi

mv "${STAGING_DIR}" "${RELEASE_DIR}"
release_committed=1
fsync_directory "${RELEASE_ROOT}"
verify_release_tree "${RELEASE_DIR}"
verify_runtime_compose_contract \
  "${COMPOSE_SNAPSHOT}" "${COMPOSE_OVERRIDE}" \
  "${RELEASE_SHA}" "${TARGET_IMAGE_ID}" "${RELEASE_DIR}"

RELEASE_SHA="${RELEASE_SHA}" \
REDDIT_VOC_DATA_ROOT="${DATA_ROOT}" \
INSIGHTS_BIND_ADDRESS="${BIND_ADDRESS}" \
INSIGHTS_PORT="${PORT}" \
docker compose -p "${COMPOSE_PROJECT}" \
  -f "${COMPOSE_SNAPSHOT}" -f "${COMPOSE_OVERRIDE}" \
  up -d --no-build --no-deps --pull never web

if ! wait_for_release_health "${RELEASE_SHA}"; then
  docker logs --tail 120 "${CONTAINER_NAME}" >&2 || true
  echo "insights container did not become healthy" >&2
  exit 1
fi

container_networks="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "${CONTAINER_NAME}" | xargs)"
container_mounts="$(docker inspect -f '{{len .Mounts}}' "${CONTAINER_NAME}")"
container_data_mount="$(docker inspect -f '{{range .Mounts}}{{.Type}}|{{.Source}}|{{.RW}}|{{.Destination}}|{{.Propagation}}{{end}}' "${CONTAINER_NAME}")"
container_read_only="$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "${CONTAINER_NAME}")"
container_restart="$(docker inspect -f '{{.RestartCount}}' "${CONTAINER_NAME}")"
container_health="$(docker inspect -f '{{.State.Health.Status}}' "${CONTAINER_NAME}")"
network_internal="$(docker network inspect -f '{{.Internal}}' reddit_voc_insights_net)"
network_id="$(docker network inspect -f '{{.Id}}' reddit_voc_insights_net)"
network_masquerade="$(docker network inspect -f '{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}' reddit_voc_insights_net)"
network_icc="$(docker network inspect -f '{{index .Options "com.docker.network.bridge.enable_icc"}}' reddit_voc_insights_net)"
listener_addresses="$(ss -H -ltn | awk -v suffix=":${PORT}" 'index($4, suffix) == length($4) - length(suffix) + 1 {print $4}' | sort -u)"
if [[ "${container_networks}" != "reddit_voc_insights_net" || \
      "${container_mounts}" != "1" || \
      "${container_data_mount}" != "bind|${DATA_ROOT}|false|${DATA_CONTAINER_ROOT}|rprivate" || \
      "${container_read_only}" != "true" || \
      "${container_health}" != "healthy" || \
      "${listener_addresses}" != "${BIND_ADDRESS}:${PORT}" || \
      "${network_internal}" != "false" || \
      "${network_masquerade}" != "false" || \
      "${network_icc}" != "false" ]]; then
  echo "deployed container isolation contract mismatch" >&2
  exit 1
fi
if docker exec "${CONTAINER_NAME}" wget -q -T 3 -O /dev/null "http://${BIND_ADDRESS}:18337/api/health" 2>/dev/null; then
  echo "insights container unexpectedly reached the collector listener" >&2
  exit 1
fi

release_http="$(curl -fsS "http://${BIND_ADDRESS}:${PORT}/release.json")"
if [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["release_sha256"])' "${release_http}")" != "${RELEASE_SHA}" ]]; then
  echo "running release marker mismatch" >&2
  exit 1
fi
container_contract_json="$(docker inspect "${CONTAINER_NAME}")"
python3 - "${container_contract_json}" "${RELEASE_SHA}" "${TARGET_IMAGE_ID}" "${image_id}" "${DATA_ROOT}" "${BIND_ADDRESS}" "${PORT}" "${network_id}" <<'PY'
import json
import sys

raw, release, image_ref, image_id, data_root, bind_address, port, network_id = sys.argv[1:]
values = json.loads(raw)
if len(values) != 1:
    raise SystemExit("deployed container inspect cardinality mismatch")
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
    or config.get("Entrypoint") != ["/docker-entrypoint.sh"]
    or config.get("Cmd") != ["nginx", "-g", "daemon off;"]
    or config.get("WorkingDir") != "/"
    or config.get("OpenStdin") is not False
    or config.get("StdinOnce") is not False
    or config.get("Tty") is not False
    or set(config.get("Env") or []) != {
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "NGINX_VERSION=1.29.4",
        "PKG_RELEASE=1",
        "DYNPKG_RELEASE=1",
        "NJS_VERSION=0.9.4",
        "NJS_RELEASE=1",
        "NGINX_ENTRYPOINT_QUIET_LOGS=1",
    }
    or config.get("Healthcheck") != {
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
    }
    or labels.get("com.reddit-voc.component") != "insights-site"
    or labels.get("com.reddit-voc.release") != release
    or state.get("Running") is not True
    or health.get("Status") != "healthy"
    or host.get("ReadonlyRootfs") is not True
    or host.get("Privileged") is not False
    or host.get("PidMode") != ""
    or host.get("IpcMode") != "private"
    or host.get("UTSMode") != ""
    or host.get("UsernsMode") != ""
    or host.get("Devices") not in (None, [])
    or host.get("DeviceRequests") not in (None, [])
    or host.get("DeviceCgroupRules") not in (None, [])
    or host.get("Sysctls") not in (None, {})
    or host.get("Ulimits") not in (None, [])
    or host.get("Runtime") not in ("", "runc")
    or host.get("CapAdd") not in (None, [])
    or host.get("CapDrop") != ["ALL"]
    or host.get("SecurityOpt") != ["no-new-privileges:true"]
    or host.get("Init") is not True
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
    raise SystemExit("deployed container exact runtime contract mismatch")
mount = mounts[0]
if (
    mount.get("Type") != "bind"
    or mount.get("Source") != data_root
    or mount.get("Destination") != "/srv/reddit-voc-data"
    or mount.get("RW") is not False
    or mount.get("Propagation") != "rprivate"
):
    raise SystemExit("deployed container exact mount contract mismatch")
expected_binding = [{"HostIp": bind_address, "HostPort": port}]
if ports != {"8080/tcp": expected_binding} or bindings != {"8080/tcp": expected_binding}:
    raise SystemExit("deployed container exact port contract mismatch")
PY

if [[ "$(docker inspect -f '{{.Id}}' reddit_voc_site_app)" != "${collector_id}" || \
      "$(docker inspect -f '{{.RestartCount}}' reddit_voc_site_app)" != "${collector_restart}" || \
      "$(docker inspect -f '{{.Id}}' reddit_voc_libretranslate)" != "${translation_id}" || \
      "$(docker inspect -f '{{.RestartCount}}' reddit_voc_libretranslate)" != "${translation_restart}" || \
      "$(sha256sum /opt/ai-video/deploy/lighthouse/nginx.conf | awk '{print $1}')" != "${nginx_sha}" || \
      "$(sudo sha256sum /etc/cron.d/reddit-voc-site | awk '{print $1}')" != "${cron_sha}" ]]; then
  echo "existing production baseline changed during isolated container deployment" >&2
  exit 1
fi

curl -fsS http://127.0.0.1:18337/api/health >/dev/null

evidence_file="${EVIDENCE_ROOT}/container-deploy-$(date -u +%Y%m%dT%H%M%SZ)-${RELEASE_SHA}.txt"
cas_replace_site_pointer \
  "releases/${previous_release_sha}" "releases/${RELEASE_SHA}"
current_switched=1
python3 - "${EVIDENCE_ROOT}" "${evidence_file##*/}" \
  "evidence_grade=L4-authorized-live" \
  "release_sha=${RELEASE_SHA}" \
  "image_id=${image_id}" \
  "container=${CONTAINER_NAME}" \
  "container_health=${container_health}" \
  "container_restart_count=${container_restart}" \
  "container_networks=${container_networks}" \
  "network_internal=${network_internal}" \
  "network_ip_masquerade=${network_masquerade}" \
  "network_icc=${network_icc}" \
  "collector_listener_reachable_from_insights=false" \
  "container_mounts=${container_mounts}" \
  "container_data_mount=${container_data_mount}" \
  "data_release_id=${manifest_data_release_id}" \
  "data_pointer_sha256=${manifest_data_pointer_sha}" \
  "listener=${listener_addresses}" \
  "release_marker_verified=true" \
  "image_dist_checksums_verified=true" \
  "collector_id_unchanged=true" \
  "collector_restart_count=${collector_restart}" \
  "translation_restart_count=${translation_restart}" \
  "nginx_unchanged=true" \
  "cron_unchanged=true" \
  "provider_call=false" \
  "database_write=false" \
  "live_send=false" \
  "webhook_send=false" \
  "latest_collection_integrated=${manifest_collection_integrated}" \
  "latest_collection_fully_hydrated=${manifest_collection_fully_hydrated}" <<'PY'
import os
from pathlib import Path
import ctypes
import errno
import re
import secrets
import stat
import sys

root = Path(sys.argv[1])
name = sys.argv[2]
records = sys.argv[3:]
if re.fullmatch(r"container-deploy-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{64}\.txt", name) is None:
    raise SystemExit("container deployment evidence name is invalid")
if not records or any(
    "\n" in record
    or "\r" in record
    or re.fullmatch(r"[a-z0-9_]+=[^\r\n]*", record) is None
    for record in records
):
    raise SystemExit("container deployment evidence record is invalid")
if len({record.split("=", 1)[0] for record in records}) != len(records):
    raise SystemExit("container deployment evidence keys are not unique")
payload = ("\n".join(records) + "\n").encode("utf-8")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("container deployment evidence requires O_NOFOLLOW")
directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
descriptor = None
temporary_name = f".{name}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
opened = None

def rename_noreplace(source: str, target: str, directory: int) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        result = library.renameat2(
            directory, source_bytes, directory, target_bytes, 1
        )
    elif sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            directory, source_bytes, directory, target_bytes, 0x00000004
        )
    else:
        raise SystemExit("atomic no-replace rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), target)
        raise OSError(error, os.strerror(error), target)

try:
    directory = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != os.getuid()
        or directory.st_mode & 0o022
    ):
        raise SystemExit("container deployment evidence directory is unsafe")
    descriptor = os.open(
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or opened.st_uid != os.getuid()
        or stat.S_IMODE(opened.st_mode) != 0o600
    ):
        raise SystemExit("container deployment evidence file is unsafe")
    written = 0
    while written < len(payload):
        chunk = os.write(descriptor, payload[written:])
        if chunk <= 0:
            raise SystemExit("container deployment evidence write was incomplete")
        written += chunk
    os.fsync(descriptor)
    temporary = os.stat(
        temporary_name, dir_fd=directory_fd, follow_symlinks=False
    )
    if (temporary.st_dev, temporary.st_ino) != (opened.st_dev, opened.st_ino):
        raise SystemExit("container deployment evidence temporary path changed")
    rename_noreplace(temporary_name, name, directory_fd)
    os.fsync(directory_fd)
    published = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if (
        (published.st_dev, published.st_ino) != (opened.st_dev, opened.st_ino)
        or published.st_nlink != 1
        or published.st_uid != os.getuid()
        or stat.S_IMODE(published.st_mode) != 0o600
    ):
        raise SystemExit("container deployment evidence publication changed")
    verification_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        verified = os.fstat(verification_fd)
        verified_payload = b""
        while chunk := os.read(verification_fd, 1024 * 1024):
            verified_payload += chunk
        verified_after = os.fstat(verification_fd)
        if (
            (verified.st_dev, verified.st_ino) != (opened.st_dev, opened.st_ino)
            or verified.st_nlink != 1
            or verified.st_uid != os.getuid()
            or stat.S_IMODE(verified.st_mode) != 0o600
            or verified_payload != payload
            or verified_after.st_size != verified.st_size
            or verified_after.st_mtime_ns != verified.st_mtime_ns
        ):
            raise SystemExit("container deployment evidence final verification failed")
    finally:
        os.close(verification_fd)
except BaseException:
    if opened is not None:
        for candidate in (name, temporary_name):
            try:
                metadata = os.stat(
                    candidate, dir_fd=directory_fd, follow_symlinks=False
                )
                if (metadata.st_dev, metadata.st_ino) == (
                    opened.st_dev,
                    opened.st_ino,
                ):
                    os.unlink(candidate, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
    raise
finally:
    if descriptor is not None:
        os.close(descriptor)
    os.close(directory_fd)
PY
deployment_succeeded=1
trap - EXIT
rm -f "${ARCHIVE}" || echo "warning: committed archive cleanup failed" >&2
cleanup_transient || echo "warning: committed transient cleanup failed" >&2
printf '%s\n' \
  "release_sha=${RELEASE_SHA}" \
  "image_id=${image_id}" \
  "container_health=${container_health}" \
  "latest_collection_integrated=${manifest_collection_integrated}" \
  "latest_collection_fully_hydrated=${manifest_collection_fully_hydrated}" \
  "evidence=${evidence_file}" \
  "backend_health_preserved=true"
