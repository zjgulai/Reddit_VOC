#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE_DIR=""
OUTPUT_PATH=""

usage() {
  cat <<'EOF'
Usage: scripts/smoke_local_insights_container.sh --release-dir PATH --output PATH

Loads and validates one exact Reddit VOC insights image tar in an isolated
local candidate only container. It never contacts a remote host, deploys,
prunes Docker, or changes any existing container or network.

Options:
  --release-dir PATH  Immutable container-release/<release_sha> directory.
  --output PATH       Canonical local smoke receipt below project tmp/.
  -h, --help          Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --release-dir)
      [[ $# -ge 2 ]] || { echo "--release-dir requires a path" >&2; exit 2; }
      RELEASE_DIR="$2"
      shift 2
      ;;
    --output)
      [[ $# -ge 2 ]] || { echo "--output requires a path" >&2; exit 2; }
      OUTPUT_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "${RELEASE_DIR}" ]] || { echo "--release-dir is required" >&2; exit 2; }
[[ -n "${OUTPUT_PATH}" ]] || { echo "--output is required" >&2; exit 2; }

for command in docker python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "required command is missing: ${command}" >&2
    exit 1
  }
done

RELEASE_DIR="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${RELEASE_DIR}")"
OUTPUT_PATH="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${OUTPUT_PATH}")"
case "${RELEASE_DIR}" in
  "${PROJECT_ROOT}/tmp/"*) ;;
  *) echo "release directory must remain below ${PROJECT_ROOT}/tmp" >&2; exit 1 ;;
esac
case "${OUTPUT_PATH}" in
  "${PROJECT_ROOT}/tmp/"*) ;;
  *) echo "output path must remain below ${PROJECT_ROOT}/tmp" >&2; exit 1 ;;
esac
if [[ ! -d "${RELEASE_DIR}" || -L "${RELEASE_DIR}" ]]; then
  echo "release directory is missing or unsafe" >&2
  exit 1
fi
if [[ -n "$(find "${RELEASE_DIR}" -type l -print -quit)" ]]; then
  echo "release directory must not contain symlinks" >&2
  exit 1
fi

MANIFEST_PATH="${RELEASE_DIR}/release-manifest.json"
SUMS_PATH="${RELEASE_DIR}/SHA256SUMS"
DIST_SUMS_PATH="${RELEASE_DIR}/dist-SHA256SUMS"
for required in "${MANIFEST_PATH}" "${SUMS_PATH}" "${DIST_SUMS_PATH}"; do
  if [[ ! -f "${required}" || -L "${required}" ]]; then
    echo "required release file is missing or unsafe: ${required}" >&2
    exit 1
  fi
done

CONTRACT_TSV="$(python3 - "${MANIFEST_PATH}" "${RELEASE_DIR}" <<'PY'
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import sys

manifest_path = Path(sys.argv[1])
release_dir = Path(sys.argv[2])
raw = manifest_path.read_bytes()
value = json.loads(raw.decode("utf-8"))
sha_pattern = re.compile(r"^[a-f0-9]{64}$")
if value.get("schema_version") != "reddit_voc_insights_site_release_v2":
    raise SystemExit("release manifest schema mismatch")
release_sha = value.get("release_sha256")
if not isinstance(release_sha, str) or sha_pattern.fullmatch(release_sha) is None:
    raise SystemExit("release SHA is invalid")
if release_dir.name != release_sha:
    raise SystemExit("release directory identity mismatch")
if value.get("target_platform") != "linux/amd64":
    raise SystemExit("release target platform mismatch")
current = value.get("current_release")
versions = value.get("dataset_versions")
manifests = value.get("dataset_manifests")
if not isinstance(current, dict) or not isinstance(versions, dict) or not isinstance(manifests, dict):
    raise SystemExit("release data binding is incomplete")
data_runtime = value.get("data_runtime")
if data_runtime != {
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
    raise SystemExit("release data runtime contract mismatch")
core_keys = ("base", "insights", "reports", "personas")
auxiliary_keys = ("brand_health", "quarter_insights", "casebook")
required_keys = core_keys if set(versions) == set(core_keys) else core_keys + auxiliary_keys
if set(versions) != set(required_keys) or set(manifests) != set(required_keys):
    raise SystemExit("release dataset binding mismatch")

def safe_path(raw_path: object, label: str) -> str:
    if not isinstance(raw_path, str):
        raise SystemExit(f"{label} path missing")
    path = PurePosixPath(raw_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SystemExit(f"{label} path unsafe")
    return path.as_posix()

current_path = safe_path(current.get("path"), "current release")
data_release_id = current.get("release_id")
if (
    not isinstance(data_release_id, str)
    or not data_release_id.startswith("reddit_voc_release_")
):
    raise SystemExit("release data identity is invalid")
manifest_paths = {
    key: safe_path(manifests[key].get("manifest_path"), f"{key} manifest")
    for key in required_keys
}
image_name = f"reddit-voc-insights-{release_sha}.tar"
image_path = release_dir / image_name
if not image_path.is_file() or image_path.is_symlink():
    raise SystemExit("release image tar is missing or unsafe")
print("\t".join((
    release_sha,
    image_name,
    current_path,
    data_release_id,
    versions["base"],
    versions["insights"],
    versions["reports"],
    versions["personas"],
    *(versions.get(key, "-") for key in auxiliary_keys),
    *(manifest_paths[key] for key in core_keys),
    *(manifest_paths.get(key, "-") for key in auxiliary_keys),
    sha256(raw).hexdigest(),
)))
PY
)"
IFS=$'\t' read -r \
  RELEASE_SHA IMAGE_TAR_NAME CURRENT_RELEASE_PATH \
  DATA_RELEASE_ID \
  BASE_VERSION INSIGHTS_VERSION REPORTS_VERSION PERSONAS_VERSION \
  BRAND_HEALTH_VERSION QUARTER_INSIGHTS_VERSION CASEBOOK_VERSION \
  BASE_MANIFEST_PATH INSIGHTS_MANIFEST_PATH REPORTS_MANIFEST_PATH PERSONAS_MANIFEST_PATH \
  BRAND_HEALTH_MANIFEST_PATH QUARTER_INSIGHTS_MANIFEST_PATH CASEBOOK_MANIFEST_PATH \
  RELEASE_MANIFEST_SHA <<< "${CONTRACT_TSV}"
IMAGE_TAR_PATH="${RELEASE_DIR}/${IMAGE_TAR_NAME}"

(
  cd "${RELEASE_DIR}"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check SHA256SUMS
  else
    shasum -a 256 --check SHA256SUMS
  fi
)

OUTPUT_PARENT="$(dirname "${OUTPUT_PATH}")"
mkdir -p "${OUTPUT_PARENT}"
chmod 0700 "${OUTPUT_PARENT}"
if [[ -e "${OUTPUT_PATH}" && ( ! -f "${OUTPUT_PATH}" || -L "${OUTPUT_PATH}" ) ]]; then
  echo "output path is unsafe" >&2
  exit 1
fi

SHORT_SHA="${RELEASE_SHA:0:12}"
CONTAINER_NAME="reddit_voc_insights_smoke_${SHORT_SHA}"
NETWORK_NAME="reddit_voc_insights_smoke_${SHORT_SHA}"
IMAGE_TAG="reddit-voc-insights:${RELEASE_SHA}"

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  echo "local smoke container name collision" >&2
  exit 1
fi
if docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  echo "local smoke network name collision" >&2
  exit 1
fi
if docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
  echo "local smoke image tag collision" >&2
  exit 1
fi

WORK_ROOT="$(mktemp -d "${OUTPUT_PARENT}/container-smoke.XXXXXX")"
chmod 0700 "${WORK_ROOT}"
CONTAINER_CREATED=false
NETWORK_CREATED=false
IMAGE_LOADED=false
CLEANUP_FAILED=false
DATA_EXTRACT_CONTAINER=""

snapshot_containers() {
  local destination="$1"
  : > "${destination}"
  docker container ls -aq --no-trunc | LC_ALL=C sort > "${destination}.ids"
  while IFS= read -r container_id; do
    [[ -n "${container_id}" ]] || continue
    docker container inspect --format '{{.Id}}\t{{.State.Status}}\t{{.RestartCount}}' "${container_id}"
  done < "${destination}.ids" | LC_ALL=C sort > "${destination}"
  rm -f "${destination}.ids"
}

cleanup_resources() {
  if [[ -n "${DATA_EXTRACT_CONTAINER}" ]]; then
    if docker rm -f "${DATA_EXTRACT_CONTAINER}" >/dev/null 2>&1; then
      DATA_EXTRACT_CONTAINER=""
    else
      CLEANUP_FAILED=true
    fi
  fi
  if [[ "${CONTAINER_CREATED}" == true ]]; then
    if docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1; then
      CONTAINER_CREATED=false
    else
      CLEANUP_FAILED=true
    fi
  fi
  if [[ "${NETWORK_CREATED}" == true ]]; then
    if docker network rm "${NETWORK_NAME}" >/dev/null 2>&1; then
      NETWORK_CREATED=false
    else
      CLEANUP_FAILED=true
    fi
  fi
  if [[ "${IMAGE_LOADED}" == true ]]; then
    if docker image rm "${IMAGE_TAG}" >/dev/null 2>&1; then
      IMAGE_LOADED=false
    else
      CLEANUP_FAILED=true
    fi
  fi
}

on_exit() {
  local status=$?
  trap - EXIT
  set +e
  cleanup_resources
  rm -rf "${WORK_ROOT}"
  if [[ "${CLEANUP_FAILED}" == true ]]; then
    echo "local smoke cleanup failed" >&2
    status=1
  fi
  exit "${status}"
}
trap on_exit EXIT

snapshot_containers "${WORK_ROOT}/containers-before.tsv"
EXISTING_CONTAINER_COUNT="$(wc -l < "${WORK_ROOT}/containers-before.tsv" | tr -d ' ')"

docker load --input "${IMAGE_TAR_PATH}" >/dev/null
IMAGE_LOADED=true
docker image inspect "${IMAGE_TAG}" > "${WORK_ROOT}/image-inspect.json"
python3 - "${WORK_ROOT}/image-inspect.json" "${RELEASE_SHA}" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(value, list) or len(value) != 1:
    raise SystemExit("loaded image inspect contract mismatch")
image = value[0]
labels = image.get("Config", {}).get("Labels", {})
if image.get("Architecture") != "amd64" or image.get("Os") != "linux":
    raise SystemExit("loaded image platform mismatch")
if image.get("Config", {}).get("User") != "101:101":
    raise SystemExit("loaded image user mismatch")
if labels.get("com.reddit-voc.component") != "insights-site":
    raise SystemExit("loaded image component label mismatch")
if labels.get("com.reddit-voc.release") != sys.argv[2]:
    raise SystemExit("loaded image release label mismatch")
PY

DATA_ROOT="${WORK_ROOT}/data-root"
DATA_RELEASE_ROOT="${DATA_ROOT}/releases/${DATA_RELEASE_ID}"
mkdir -p "${DATA_RELEASE_ROOT}/public/data"
DATA_EXTRACT_CONTAINER="${CONTAINER_NAME}_data_extract"
docker create --name "${DATA_EXTRACT_CONTAINER}" "${IMAGE_TAG}" >/dev/null
docker cp \
  "${DATA_EXTRACT_CONTAINER}:/usr/share/nginx/html/data/." \
  "${DATA_RELEASE_ROOT}/public/data/"
docker rm "${DATA_EXTRACT_CONTAINER}" >/dev/null
DATA_EXTRACT_CONTAINER=""
ln -s "releases/${DATA_RELEASE_ID}" "${DATA_ROOT}/current"
find "${DATA_ROOT}/releases" -type d -exec chmod 0755 {} +
find "${DATA_ROOT}/releases" -type f -exec chmod 0444 {} +
chmod 0755 "${DATA_ROOT}"
python3 "${PROJECT_ROOT}/scripts/reddit_data_release_control.py" validate \
  --root "${DATA_ROOT}" \
  --release-id "${DATA_RELEASE_ID}" >/dev/null

docker network create \
  --internal \
  --label "com.reddit-voc.scope=local-candidate-smoke" \
  --label "com.reddit-voc.release=${RELEASE_SHA}" \
  "${NETWORK_NAME}" >/dev/null
NETWORK_CREATED=true

docker run -d \
  --platform linux/amd64 \
  --name "${CONTAINER_NAME}" \
  --network "${NETWORK_NAME}" \
  --user 101:101 \
  --read-only \
  --mount "type=bind,src=${DATA_ROOT},dst=/srv/reddit-voc-data,readonly" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --restart no \
  --health-cmd 'wget -q -O /dev/null http://127.0.0.1:8080/healthz && wget -q -O /dev/null http://127.0.0.1:8080/data/reddit-voc/current-release.json' \
  --health-interval 2s \
  --health-timeout 3s \
  --health-retries 15 \
  --health-start-period 1s \
  --pids-limit 128 \
  --memory 128m \
  --cpus 1.0 \
  --label "com.reddit-voc.scope=local-candidate-smoke" \
  "${IMAGE_TAG}" >/dev/null
CONTAINER_CREATED=true

for _attempt in $(seq 1 30); do
  HEALTH_STATUS="$(docker container inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${CONTAINER_NAME}")"
  if [[ "${HEALTH_STATUS}" == healthy ]]; then
    break
  fi
  if [[ "$(docker container inspect --format '{{.State.Running}}' "${CONTAINER_NAME}")" != true ]]; then
    echo "local smoke container stopped before becoming healthy" >&2
    exit 1
  fi
  sleep 1
done
if [[ "${HEALTH_STATUS:-missing}" != healthy ]]; then
  docker container inspect --format '{{json .State.Health}}' "${CONTAINER_NAME}" >&2 || true
  docker logs --tail 50 "${CONTAINER_NAME}" >&2 || true
  echo "local smoke container did not become healthy" >&2
  exit 1
fi

docker container inspect "${CONTAINER_NAME}" > "${WORK_ROOT}/container-inspect.json"
python3 - "${WORK_ROOT}/container-inspect.json" "${NETWORK_NAME}" "${RELEASE_SHA}" "${DATA_ROOT}" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(value, list) or len(value) != 1:
    raise SystemExit("container inspect contract mismatch")
container = value[0]
config = container.get("Config", {})
host = container.get("HostConfig", {})
state = container.get("State", {})
labels = config.get("Labels", {})
if config.get("User") != "101:101":
    raise SystemExit("runtime configured user mismatch")
if labels.get("com.reddit-voc.release") != sys.argv[3]:
    raise SystemExit("runtime release label mismatch")
if host.get("ReadonlyRootfs") is not True or host.get("Privileged") is not False:
    raise SystemExit("runtime read-only or privilege contract mismatch")
mounts = container.get("Mounts") or []
if len(mounts) != 1:
    raise SystemExit("runtime must have exactly one mount")
mount = mounts[0]
if (
    mount.get("Type") != "bind"
    or mount.get("Source") != sys.argv[4]
    or mount.get("Destination") != "/srv/reddit-voc-data"
    or mount.get("RW") is not False
    or mount.get("Propagation") != "rprivate"
):
    raise SystemExit("runtime data mount contract mismatch")
if set(host.get("CapDrop") or []) != {"ALL"} or host.get("CapAdd") not in (None, []):
    raise SystemExit("runtime capability contract mismatch")
if "no-new-privileges" not in " ".join(host.get("SecurityOpt") or []):
    raise SystemExit("runtime no-new-privileges contract mismatch")
if host.get("RestartPolicy", {}).get("Name") != "no":
    raise SystemExit("runtime restart policy mismatch")
if set(container.get("NetworkSettings", {}).get("Networks", {})) != {sys.argv[2]}:
    raise SystemExit("runtime network isolation mismatch")
if state.get("Running") is not True or state.get("Health", {}).get("Status") != "healthy":
    raise SystemExit("runtime health contract mismatch")
if (host.get("PortBindings") or {}) != {}:
    raise SystemExit("runtime must not publish a host port")
PY

PROC_STATUS="$(docker exec "${CONTAINER_NAME}" sh -c 'grep -E "^(Uid|Gid):" /proc/1/status')"
python3 - "${PROC_STATUS}" <<'PY'
import sys

rows = {}
for line in sys.argv[1].splitlines():
    key, values = line.split(":", 1)
    rows[key] = values.split()
if rows.get("Uid") != ["101"] * 4 or rows.get("Gid") != ["101"] * 4:
    raise SystemExit("runtime process UID/GID mismatch")
PY

CONTAINER_BASE_URL="http://127.0.0.1:8080"
container_http_status() {
  local probe_path="$1"
  local body_path="$2"
  local headers_path="${WORK_ROOT}/probe-headers.txt"
  if docker exec "${CONTAINER_NAME}" wget -S -O - \
    "${CONTAINER_BASE_URL}${probe_path}" > "${body_path}" 2> "${headers_path}"; then
    if grep -Eq 'HTTP/1\.1 200 ' "${headers_path}"; then
      printf '200'
      return 0
    fi
  elif grep -Eq 'HTTP/1\.1 404 ' "${headers_path}"; then
    printf '404'
    return 0
  fi
  cat "${headers_path}" >&2
  printf '000'
}

STATUS="$(container_http_status /healthz "${WORK_ROOT}/healthz.txt")"
[[ "${STATUS}" == 200 && "$(cat "${WORK_ROOT}/healthz.txt")" == ok ]] || {
  echo "local container health endpoint contract failed" >&2
  exit 1
}
STATUS="$(container_http_status /release.json "${WORK_ROOT}/release.json")"
[[ "${STATUS}" == 200 ]] || { echo "release marker endpoint failed" >&2; exit 1; }
python3 - "${WORK_ROOT}/release.json" "${RELEASE_SHA}" <<'PY'
import json
import sys
if json.load(open(sys.argv[1], encoding="utf-8")) != {"release_sha256": sys.argv[2]}:
    raise SystemExit("runtime release marker mismatch")
PY

PUBLIC_PATHS=(
  "/${CURRENT_RELEASE_PATH}"
  "/${BASE_MANIFEST_PATH}"
  "/${INSIGHTS_MANIFEST_PATH}"
  "/${REPORTS_MANIFEST_PATH}"
  "/${PERSONAS_MANIFEST_PATH}"
  "/data/cases/manifest.v1.json"
  "/data/cases/case-index.v1.json"
)
for manifest_path in \
  "${BRAND_HEALTH_MANIFEST_PATH}" \
  "${QUARTER_INSIGHTS_MANIFEST_PATH}" \
  "${CASEBOOK_MANIFEST_PATH}"; do
  if [[ "${manifest_path}" != "-" ]]; then
    PUBLIC_PATHS+=("/${manifest_path}")
  fi
done
for path in "${PUBLIC_PATHS[@]}"; do
  [[ "$(container_http_status "${path}" "${WORK_ROOT}/public-body")" == 200 ]] || {
    echo "required public path failed: ${path}" >&2
    exit 1
  }
done

ROUTES=(
  /
  /dashboard
  /dashboard/reports
  /dashboard/analytics
  /dashboard/insights
  /dashboard/search
  /dashboard/ugc-showcase
  /dashboard/messages
  /dashboard/settings
  /features
  /how-it-works
  /faq
  /cases
)
for route in "${ROUTES[@]}"; do
  [[ "$(container_http_status "${route}" "${WORK_ROOT}/route-body")" == 200 ]] || {
    echo "SPA route failed: ${route}" >&2
    exit 1
  }
done

FORBIDDEN_PATHS=(
  /.env
  /.env.local
  /frontend-source-manifest.json
  /candidate-ui-source-validation-receipt.json
  /candidate-ui-validation-receipt.json
  /release-manifest.json
  "/data/reddit-voc/${BASE_VERSION}/manifest.json"
  "/data/reddit-voc/${BASE_VERSION}/aggregates.json"
  "/data/reddit-voc/${BASE_VERSION}/posts.json"
  "/data/reddit-voc/${BASE_VERSION}/comments.json"
  "/data/reddit-voc/${BASE_VERSION}/quarantine.json"
  "/data/reddit-voc/${BASE_VERSION}/tag-dictionary.json"
  "/data/reddit-voc/${INSIGHTS_VERSION}/manifest.json"
  "/data/reddit-voc/${INSIGHTS_VERSION}/insights.json"
  "/data/reddit-voc/${INSIGHTS_VERSION}/semantic-audit.json"
  "/data/reddit-voc/${REPORTS_VERSION}/manifest.json"
  "/data/reddit-voc/${REPORTS_VERSION}/report-index.json"
  "/data/reddit-voc/${REPORTS_VERSION}/current/daily.json"
  "/data/reddit-voc/${REPORTS_VERSION}/archive/daily.json"
  "/data/reddit-voc/${PERSONAS_VERSION}/imports/private.json"
)
for path in "${FORBIDDEN_PATHS[@]}"; do
  [[ "$(container_http_status "${path}" "${WORK_ROOT}/forbidden-body")" == 404 ]] || {
    echo "forbidden path did not return 404: ${path}" >&2
    exit 1
  }
done

cleanup_resources
if [[ "${CLEANUP_FAILED}" == true ]]; then
  echo "local smoke resource cleanup failed" >&2
  exit 1
fi
snapshot_containers "${WORK_ROOT}/containers-after.tsv"
cmp "${WORK_ROOT}/containers-before.tsv" "${WORK_ROOT}/containers-after.tsv" || {
  echo "pre-existing local containers changed during smoke" >&2
  exit 1
}
if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1 \
  || docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1 \
  || docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
  echo "local smoke resources remain after cleanup" >&2
  exit 1
fi

WRITE_STATUS="$(python3 - \
  "${OUTPUT_PATH}" \
  "${RELEASE_SHA}" \
  "${RELEASE_MANIFEST_SHA}" \
  "${IMAGE_TAR_PATH}" \
  "${DIST_SUMS_PATH}" \
  "${EXISTING_CONTAINER_COUNT}" \
  "${#ROUTES[@]}" \
  "${#FORBIDDEN_PATHS[@]}" <<'PY'
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

(
    output_raw,
    release_sha,
    release_manifest_sha,
    image_raw,
    dist_sums_raw,
    container_count_raw,
    route_count_raw,
    forbidden_count_raw,
) = sys.argv[1:]
output = Path(output_raw)
image = Path(image_raw)
dist_sums = Path(dist_sums_raw)

def file_contract(path: Path) -> dict[str, object]:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("receipt input is unsafe")
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}

receipt = {
    "schema_version": "reddit_voc_local_insights_container_smoke_receipt_v2",
    "status": "passed_local_isolated_container_smoke",
    "evidence_grade": "L2_local_isolated_container_smoke",
    "release": {
        "release_sha256": release_sha,
        "release_manifest_sha256": release_manifest_sha,
        "image_tar": file_contract(image),
        "dist_sha256sums": file_contract(dist_sums),
        "target_platform": "linux/amd64",
    },
    "runtime_checks": {
        "uid_gid_101": True,
        "read_only_rootfs": True,
        "one_read_only_data_mount": True,
        "exact_data_mount_contract": True,
        "data_pointer_health": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "isolated_internal_network": True,
        "container_loopback_http": True,
        "host_port_published": False,
        "healthy": True,
        "route_count": int(route_count_raw),
        "security_404_count": int(forbidden_count_raw),
    },
    "non_interference": {
        "pre_existing_container_count": int(container_count_raw),
        "pre_existing_containers_unchanged": True,
        "smoke_container_removed": True,
        "smoke_network_removed": True,
        "loaded_image_tag_removed": True,
    },
    "boundaries": {
        "production_unchanged": True,
        "deploy": False,
        "remote_write": False,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
    },
}
payload = json.dumps(
    receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8") + b"\n"
if output.exists():
    metadata = os.lstat(output)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("smoke receipt output is unsafe")
    if output.read_bytes() != payload:
        raise SystemExit("smoke receipt immutable collision")
    print("no_change")
    raise SystemExit(0)
output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(output.parent, 0o700)
descriptor, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if output.exists():
        raise SystemExit("smoke receipt immutable collision")
    os.replace(temporary, output)
    directory_fd = os.open(output.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print("created")
PY
)"

echo "status=${WRITE_STATUS}"
echo "release_sha=${RELEASE_SHA}"
echo "receipt=${OUTPUT_PATH}"
echo "production_unchanged=true"
echo "deploy=false"
echo "remote_write=false"
