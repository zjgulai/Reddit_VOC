#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_ROOT="${PROJECT_ROOT}/ref/UI/momcozy-reddit-workbench"
DEPLOY_ROOT="${UI_ROOT}/deploy/insights"
DEFAULT_PUBLIC_ROOT="${UI_ROOT}/public"
DEFAULT_DIST_ROOT="${UI_ROOT}/dist"
DEFAULT_OUTPUT_ROOT="${PROJECT_ROOT}/tmp/insights-release"
PUBLIC_ROOT="${INSIGHTS_PUBLIC_ROOT:-${DEFAULT_PUBLIC_ROOT}}"
SOURCE_UI_ROOT="${INSIGHTS_SOURCE_UI_ROOT:-}"
FRONTEND_SOURCE_MANIFEST="${INSIGHTS_FRONTEND_SOURCE_MANIFEST:-}"
FRONTEND_SOURCE_RECEIPT="${INSIGHTS_FRONTEND_SOURCE_RECEIPT:-}"
RECEIPT_PATH="${INSIGHTS_RECEIPT:-}"
DIST_ROOT="${INSIGHTS_DIST_ROOT:-${DEFAULT_DIST_ROOT}}"
OUTPUT_ROOT="${INSIGHTS_OUTPUT_ROOT:-${DEFAULT_OUTPUT_ROOT}}"
DIST_ONLY="${INSIGHTS_DIST_ONLY:-false}"
CANDIDATE_CONTAINER="${INSIGHTS_CANDIDATE_CONTAINER:-false}"
LATEST_COLLECTION_INTEGRATED="${INSIGHTS_LATEST_COLLECTION_INTEGRATED:-false}"
LATEST_COLLECTION_FULLY_HYDRATED="${INSIGHTS_LATEST_COLLECTION_FULLY_HYDRATED:-false}"
DIST_ROOT_EXPLICIT=false
OUTPUT_ROOT_EXPLICIT=false
COLLECTION_INTEGRATED_EXPLICIT=false
COLLECTION_FULLY_HYDRATED_EXPLICIT=false
if [[ -n "${INSIGHTS_DIST_ROOT+x}" ]]; then
  DIST_ROOT_EXPLICIT=true
fi
if [[ -n "${INSIGHTS_OUTPUT_ROOT+x}" ]]; then
  OUTPUT_ROOT_EXPLICIT=true
fi
if [[ -n "${INSIGHTS_LATEST_COLLECTION_INTEGRATED+x}" ]]; then
  COLLECTION_INTEGRATED_EXPLICIT=true
fi
if [[ -n "${INSIGHTS_LATEST_COLLECTION_FULLY_HYDRATED+x}" ]]; then
  COLLECTION_FULLY_HYDRATED_EXPLICIT=true
fi
CURRENT_RELEASE_RELATIVE_PATH="data/reddit-voc/current-release.json"
NGINX_BASE_IMAGE="${NGINX_BASE_IMAGE:-nginxinc/nginx-unprivileged:1.29.4-alpine@sha256:a6c4f61f456b85b8fdf7ec7ab28cc3e299440e6fb4a9dea520e5fd8fd440025e}"

usage() {
  cat <<'EOF'
Usage: scripts/build_insights_release.sh [options]

Options:
  --public-root PATH  Public-data overlay/root to build (default: UI public/).
  --source-ui-root PATH
                      Manifest-only staged React source root for a candidate.
  --frontend-source-manifest PATH
                      Plan B frontend-source-manifest.json for the staged source.
  --frontend-source-receipt PATH
                      Plan B candidate-ui-source-validation-receipt.json.
  --receipt PATH      Canonical private build receipt (candidate container only).
  --dist-root PATH    Build output directory (required for an alternate public root).
  --output-root PATH  Immutable release/staging root (default: tmp/insights-release).
  --dist-only         Build and audit an isolated dist; do not build Docker/release artifacts.
  --candidate-container
                      Build an immutable candidate container in an isolated tmp context.
  --latest-collection-integrated BOOL
                      Whether the selected latest collection is in this candidate.
  --latest-collection-fully-hydrated BOOL
                      Whether that collection has no remaining hydration debt.
  -h, --help          Show this help.

Equivalent environment variables: INSIGHTS_PUBLIC_ROOT, INSIGHTS_SOURCE_UI_ROOT,
INSIGHTS_FRONTEND_SOURCE_MANIFEST, INSIGHTS_FRONTEND_SOURCE_RECEIPT, INSIGHTS_RECEIPT,
INSIGHTS_DIST_ROOT,
INSIGHTS_OUTPUT_ROOT, INSIGHTS_DIST_ONLY=true, INSIGHTS_CANDIDATE_CONTAINER=true,
INSIGHTS_LATEST_COLLECTION_INTEGRATED and
INSIGHTS_LATEST_COLLECTION_FULLY_HYDRATED.  An alternate public root is
fail-closed unless exactly one of --dist-only/--candidate-container is selected,
an explicit dist root below project tmp/, and both collection-status booleans
are supplied.  Candidate container mode also requires an explicit output root
below project tmp/.  The source UI public/ tree and default dist are never
modified in either mode.  Omitted status booleans default only to false.
EOF
}

while (($#)); do
  case "$1" in
    --public-root)
      [[ $# -ge 2 ]] || { echo "--public-root requires a path" >&2; exit 2; }
      PUBLIC_ROOT="$2"
      shift 2
      ;;
    --source-ui-root)
      [[ $# -ge 2 ]] || { echo "--source-ui-root requires a path" >&2; exit 2; }
      SOURCE_UI_ROOT="$2"
      shift 2
      ;;
    --frontend-source-manifest)
      [[ $# -ge 2 ]] || { echo "--frontend-source-manifest requires a path" >&2; exit 2; }
      FRONTEND_SOURCE_MANIFEST="$2"
      shift 2
      ;;
    --frontend-source-receipt)
      [[ $# -ge 2 ]] || { echo "--frontend-source-receipt requires a path" >&2; exit 2; }
      FRONTEND_SOURCE_RECEIPT="$2"
      shift 2
      ;;
    --receipt)
      [[ $# -ge 2 ]] || { echo "--receipt requires a path" >&2; exit 2; }
      RECEIPT_PATH="$2"
      shift 2
      ;;
    --dist-root)
      [[ $# -ge 2 ]] || { echo "--dist-root requires a path" >&2; exit 2; }
      DIST_ROOT="$2"
      DIST_ROOT_EXPLICIT=true
      shift 2
      ;;
    --output-root)
      [[ $# -ge 2 ]] || { echo "--output-root requires a path" >&2; exit 2; }
      OUTPUT_ROOT="$2"
      OUTPUT_ROOT_EXPLICIT=true
      shift 2
      ;;
    --dist-only)
      DIST_ONLY=true
      shift
      ;;
    --candidate-container)
      CANDIDATE_CONTAINER=true
      shift
      ;;
    --latest-collection-integrated)
      [[ $# -ge 2 ]] || { echo "--latest-collection-integrated requires true or false" >&2; exit 2; }
      LATEST_COLLECTION_INTEGRATED="$2"
      COLLECTION_INTEGRATED_EXPLICIT=true
      shift 2
      ;;
    --latest-collection-fully-hydrated)
      [[ $# -ge 2 ]] || { echo "--latest-collection-fully-hydrated requires true or false" >&2; exit 2; }
      LATEST_COLLECTION_FULLY_HYDRATED="$2"
      COLLECTION_FULLY_HYDRATED_EXPLICIT=true
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

for boolean_name in DIST_ONLY CANDIDATE_CONTAINER LATEST_COLLECTION_INTEGRATED LATEST_COLLECTION_FULLY_HYDRATED; do
  boolean_value="${!boolean_name}"
  case "${boolean_value}" in
    true|false) ;;
    *)
      echo "${boolean_name} must be true or false" >&2
      exit 2
      ;;
  esac
done
if [[ "${DIST_ONLY}" == true && "${CANDIDATE_CONTAINER}" == true ]]; then
  echo "--dist-only and --candidate-container are mutually exclusive" >&2
  exit 2
fi
if [[ "${LATEST_COLLECTION_FULLY_HYDRATED}" == true && "${LATEST_COLLECTION_INTEGRATED}" != true ]]; then
  echo "latest collection cannot be fully hydrated before it is integrated" >&2
  exit 2
fi

for command in node npm npx python3; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "required command is missing: ${command}" >&2
    exit 1
  fi
done

if [[ ! -d "${UI_ROOT}/node_modules" ]]; then
  echo "UI dependencies are missing; install the reviewed lockfile before building" >&2
  exit 1
fi

PUBLIC_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${PUBLIC_ROOT}")"
DIST_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${DIST_ROOT}")"
OUTPUT_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${OUTPUT_ROOT}")"
DEFAULT_PUBLIC_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${DEFAULT_PUBLIC_ROOT}")"
DEFAULT_DIST_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${DEFAULT_DIST_ROOT}")"
CANDIDATE_MODE=false
if [[ "${PUBLIC_ROOT}" != "${DEFAULT_PUBLIC_ROOT}" ]]; then
  CANDIDATE_MODE=true
fi

if [[ ! -d "${PUBLIC_ROOT}" || -L "${PUBLIC_ROOT}" ]]; then
  echo "public root is missing or unsafe: ${PUBLIC_ROOT}" >&2
  exit 1
fi
if [[ -n "$(find "${PUBLIC_ROOT}" -type l -print -quit)" ]]; then
  echo "public root must not contain symlinks: ${PUBLIC_ROOT}" >&2
  exit 1
fi
if [[ -e "${DIST_ROOT}" && -L "${DIST_ROOT}" ]]; then
  echo "dist root must not be a symlink: ${DIST_ROOT}" >&2
  exit 1
fi

if [[ "${DIST_ROOT}" != "${DEFAULT_DIST_ROOT}" && ( "${DIST_ONLY}" == true || "${CANDIDATE_CONTAINER}" == true ) ]]; then
  case "${DIST_ROOT}" in
    "${PROJECT_ROOT}/tmp/"*) ;;
    *)
      echo "isolated dist root must remain below ${PROJECT_ROOT}/tmp" >&2
      exit 1
      ;;
  esac
  if [[ "${DIST_ROOT}" == "${PROJECT_ROOT}" ]]; then
    echo "isolated dist root must not be the project root" >&2
    exit 1
  fi
  for protected_path in "${UI_ROOT}" "${DEFAULT_PUBLIC_ROOT}" "${PUBLIC_ROOT}"; do
    if [[ "${DIST_ROOT}" == "${protected_path}" || "${DIST_ROOT}" == "${protected_path}/"* ]]; then
      echo "isolated dist root overlaps a protected source path: ${protected_path}" >&2
      exit 1
    fi
  done
fi

if [[ "${CANDIDATE_MODE}" == true ]]; then
  if [[ "${DIST_ONLY}" != true && "${CANDIDATE_CONTAINER}" != true ]]; then
    echo "an alternate public root requires --dist-only or --candidate-container" >&2
    exit 1
  fi
  if [[ "${DIST_ROOT_EXPLICIT}" != true || "${DIST_ROOT}" == "${DEFAULT_DIST_ROOT}" ]]; then
    echo "an alternate public root requires an explicit isolated --dist-root" >&2
    exit 1
  fi
  if [[ "${COLLECTION_INTEGRATED_EXPLICIT}" != true || "${COLLECTION_FULLY_HYDRATED_EXPLICIT}" != true ]]; then
    echo "an alternate public root requires both explicit collection-status booleans" >&2
    exit 1
  fi
  if [[ "${CANDIDATE_CONTAINER}" == true && "${OUTPUT_ROOT_EXPLICIT}" != true ]]; then
    echo "candidate container mode requires an explicit --output-root" >&2
    exit 1
  fi
  case "${PUBLIC_ROOT}" in
    "${PROJECT_ROOT}/tmp/"*) ;;
    *)
      echo "candidate public root must remain below ${PROJECT_ROOT}/tmp" >&2
      exit 1
      ;;
  esac
  case "${OUTPUT_ROOT}" in
    "${PROJECT_ROOT}/tmp/"*) ;;
    *)
      echo "candidate output root must remain below ${PROJECT_ROOT}/tmp" >&2
      exit 1
      ;;
  esac
  for protected_path in "${UI_ROOT}" "${DEFAULT_PUBLIC_ROOT}" "${PUBLIC_ROOT}"; do
    if [[ "${OUTPUT_ROOT}" == "${protected_path}" || "${OUTPUT_ROOT}" == "${protected_path}/"* ]]; then
      echo "candidate output root overlaps a protected source path: ${protected_path}" >&2
      exit 1
    fi
  done
  if [[ "${OUTPUT_ROOT}" == "${DIST_ROOT}" || "${OUTPUT_ROOT}" == "${DIST_ROOT}/"* || "${DIST_ROOT}" == "${OUTPUT_ROOT}/"* ]]; then
    echo "candidate output root and dist root must not overlap" >&2
    exit 1
  fi
  if [[ -z "${SOURCE_UI_ROOT}" || -z "${FRONTEND_SOURCE_MANIFEST}" || -z "${FRONTEND_SOURCE_RECEIPT}" ]]; then
    echo "candidate mode requires the complete Plan B source contract or V3 frontend source contract: --source-ui-root, --frontend-source-manifest and --frontend-source-receipt" >&2
    exit 1
  fi
  if [[ "${CANDIDATE_CONTAINER}" == true && -z "${RECEIPT_PATH}" ]]; then
    echo "candidate container mode requires an explicit --receipt" >&2
    exit 1
  fi
elif [[ "${CANDIDATE_CONTAINER}" == true ]]; then
  echo "--candidate-container requires an alternate public root" >&2
  exit 1
elif [[ "${DIST_ROOT}" != "${DEFAULT_DIST_ROOT}" && "${DIST_ONLY}" == false ]]; then
  echo "container mode requires the default UI dist root" >&2
  exit 1
fi
if [[ -n "${RECEIPT_PATH}" && "${CANDIDATE_CONTAINER}" != true ]]; then
  echo "--receipt requires --candidate-container" >&2
  exit 1
fi
if [[ -n "${RECEIPT_PATH}" ]]; then
  RECEIPT_PATH="$(python3 -c 'from pathlib import Path; import os, sys; print(Path(os.path.abspath(sys.argv[1])))' "${RECEIPT_PATH}")"
  case "${RECEIPT_PATH}" in
    "${PROJECT_ROOT}/tmp/"*) ;;
    *)
      echo "build receipt must remain below ${PROJECT_ROOT}/tmp" >&2
      exit 1
      ;;
  esac
  for protected_path in "${UI_ROOT}" "${PUBLIC_ROOT}" "${DIST_ROOT}"; do
    if [[ "${RECEIPT_PATH}" == "${protected_path}" || "${RECEIPT_PATH}" == "${protected_path}/"* ]]; then
      echo "build receipt overlaps a protected source or dist path: ${protected_path}" >&2
      exit 1
    fi
  done
fi

BUILD_UI_ROOT="${UI_ROOT}"
FRONTEND_CANDIDATE_INPUT_SHA=""
FRONTEND_SOURCE_MANIFEST_SHA=""
FRONTEND_SOURCE_RECEIPT_SHA=""
if [[ "${CANDIDATE_MODE}" == true ]]; then
  SOURCE_CONTRACT_TSV="$(python3 - \
    "${PROJECT_ROOT}" \
    "${UI_ROOT}" \
    "${PUBLIC_ROOT}" \
    "${SOURCE_UI_ROOT}" \
    "${FRONTEND_SOURCE_MANIFEST}" \
    "${FRONTEND_SOURCE_RECEIPT}" \
    "${DIST_ROOT}" \
    "${OUTPUT_ROOT}" <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

(
    project_arg,
    reviewed_ui_arg,
    public_arg,
    source_arg,
    manifest_arg,
    receipt_arg,
    dist_arg,
    output_arg,
) = sys.argv[1:]
project = Path(project_arg).resolve(strict=True)
tmp_root = (project / "tmp").resolve(strict=True)
reviewed_ui = Path(reviewed_ui_arg).resolve(strict=True)
reviewed_node_modules = reviewed_ui / "node_modules"
sha_pattern = re.compile(r"^[a-f0-9]{64}$")


def fail(reason: str) -> None:
    raise SystemExit(reason)


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tmp_path(raw: str, *, label: str, kind: str) -> Path:
    path = Path(os.path.abspath(raw))
    try:
        relative = path.relative_to(tmp_root)
    except ValueError:
        fail(f"{label} must remain below {tmp_root}")
    current = tmp_root
    for part in relative.parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except OSError:
            fail(f"{label} is missing")
        if stat.S_ISLNK(metadata.st_mode):
            fail(f"{label} path must not contain symlinks")
    metadata = os.lstat(path)
    if kind == "directory" and not stat.S_ISDIR(metadata.st_mode):
        fail(f"{label} must be a directory")
    if kind == "file" and not stat.S_ISREG(metadata.st_mode):
        fail(f"{label} must be a regular file")
    return path


source_root = tmp_path(source_arg, label="source UI root", kind="directory")
manifest_path = tmp_path(
    manifest_arg, label="frontend source manifest", kind="file"
)
receipt_path = tmp_path(
    receipt_arg, label="frontend source receipt", kind="file"
)
public_root = Path(public_arg).resolve(strict=True)
if public_root != source_root / "public":
    fail("candidate public root must be the staged source public directory")
for label, raw in (("dist root", dist_arg), ("output root", output_arg)):
    candidate = Path(os.path.abspath(raw))
    if candidate == source_root or source_root in candidate.parents:
        fail(f"{label} must not overlap the staged source root")
for label, path in (
    ("frontend source manifest", manifest_path),
    ("frontend source receipt", receipt_path),
):
    if path == source_root or source_root in path.parents:
        fail(f"{label} must remain outside the staged source root")

try:
    reviewed_metadata = os.lstat(reviewed_node_modules)
except OSError:
    fail("reviewed UI node_modules is missing")
if not stat.S_ISDIR(reviewed_metadata.st_mode) or stat.S_ISLNK(
    reviewed_metadata.st_mode
):
    fail("reviewed UI node_modules must be a regular directory")
node_modules = source_root / "node_modules"
try:
    node_metadata = os.lstat(node_modules)
except OSError:
    fail("staged source node_modules link is missing")
if not stat.S_ISLNK(node_metadata.st_mode):
    fail("staged source node_modules must be the reviewed symlink")
if node_modules.resolve(strict=True) != reviewed_node_modules:
    fail("staged source node_modules must target reviewed UI node_modules")


def load_canonical(path: Path, *, label: str) -> tuple[dict[str, object], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"{label} must be canonical UTF-8 JSON")
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    if raw != canonical(value) + b"\n":
        fail(f"{label} must use canonical serialization")
    return value, raw


manifest, manifest_bytes = load_canonical(
    manifest_path, label="frontend source manifest"
)
receipt, receipt_bytes = load_canonical(
    receipt_path, label="frontend source receipt"
)
manifest_schema = manifest.get("schema_version")
if (
    manifest_schema
    not in {
        "reddit_voc_frontend_source_manifest_v1",
        "reddit_voc_frontend_source_manifest_v2",
    }
    or manifest.get("status") != "frontend_source_frozen_local"
):
    fail("frontend source manifest contract is invalid")
candidate_input = manifest.get("frontend_candidate_input_sha256")
if not isinstance(candidate_input, str) or sha_pattern.fullmatch(candidate_input) is None:
    fail("frontend candidate input SHA-256 is invalid")
boundaries = manifest.get("boundaries")
if not isinstance(boundaries, dict) or (
    boundaries.get("production_unchanged") is not True
    or boundaries.get("artifact_build") is not False
    or boundaries.get("deploy") is not False
):
    fail("frontend source manifest boundaries are invalid")
source = manifest.get("source")
inventory = source.get("inventory") if isinstance(source, dict) else None
if not isinstance(inventory, dict):
    fail("frontend source inventory is missing")
files = inventory.get("files")
if not isinstance(files, list) or not 1 <= len(files) <= 50_000:
    fail("frontend source inventory file count is invalid")
expected_rows: list[dict[str, object]] = []
seen: set[str] = set()
for row in files:
    if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
        fail("frontend source file contract is invalid")
    relative_text = row.get("path")
    relative = PurePosixPath(relative_text) if isinstance(relative_text, str) else None
    if (
        relative is None
        or relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative_text in seen
    ):
        fail("frontend source inventory path is unsafe or duplicated")
    size = row.get("bytes")
    digest = row.get("sha256")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(digest, str)
        or sha_pattern.fullmatch(digest) is None
    ):
        fail("frontend source file bytes or SHA-256 is invalid")
    seen.add(relative_text)
    expected_rows.append({"bytes": size, "path": relative_text, "sha256": digest})
if expected_rows != sorted(expected_rows, key=lambda row: row["path"]):
    fail("frontend source inventory must be sorted")
inventory_summary = {
    "file_count": len(expected_rows),
    "inventory_sha256": sha256(canonical(expected_rows)).hexdigest(),
    "total_bytes": sum(int(row["bytes"]) for row in expected_rows),
}
if any(inventory.get(key) != value for key, value in inventory_summary.items()):
    fail("frontend source inventory summary mismatch")

actual_rows: list[dict[str, object]] = []
for parent, directories, file_names in os.walk(source_root, followlinks=False):
    parent_path = Path(parent)
    if parent_path == source_root and "node_modules" in directories:
        directories.remove("node_modules")
    directories.sort()
    file_names.sort()
    for name in directories:
        metadata = os.lstat(parent_path / name)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            fail("staged source contains an unsafe directory")
    for name in file_names:
        path = parent_path / name
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            fail("staged source contains an unsafe file")
        actual_rows.append(
            {
                "bytes": metadata.st_size,
                "path": path.relative_to(source_root).as_posix(),
                "sha256": file_sha(path),
            }
        )
actual_rows.sort(key=lambda row: row["path"])
if actual_rows != expected_rows:
    fail("staged source inventory differs from the Plan B manifest")

toolchain = manifest.get("toolchain")
if not isinstance(toolchain, dict):
    fail("frontend source toolchain contract is missing")
if toolchain.get("package_lock_relative_path") != "package-lock.json":
    fail("frontend source package-lock path is invalid")
package_lock = source_root / "package-lock.json"
if toolchain.get("package_lock_sha256") != file_sha(package_lock):
    fail("frontend source package-lock SHA-256 mismatch")

manifest_sha = sha256(manifest_bytes).hexdigest()
expected_receipt_schema = (
    "reddit_voc_candidate_ui_source_validation_receipt_v2"
    if manifest_schema == "reddit_voc_frontend_source_manifest_v2"
    else "reddit_voc_candidate_ui_source_validation_receipt_v1"
)
if (
    receipt.get("schema_version") != expected_receipt_schema
    or receipt.get("status") != "passed_local_source_validation"
):
    fail("frontend source receipt contract is invalid")
if (
    receipt.get("frontend_candidate_input_sha256") != candidate_input
    or receipt.get("frontend_source_manifest_sha256") != manifest_sha
    or receipt.get("source_inventory") != inventory_summary
):
    fail("frontend source manifest and receipt lineage mismatch")
if manifest_schema == "reddit_voc_frontend_source_manifest_v2":
    upstream = manifest.get("upstream")
    lineage = upstream.get("v3_lineage") if isinstance(upstream, dict) else None
    periodic = (
        upstream.get("periodic_report_publication")
        if isinstance(upstream, dict)
        else None
    )
    datasets = lineage.get("datasets") if isinstance(lineage, dict) else None
    allowed_upstream_keys = {"v3_lineage"}
    if periodic is not None:
        allowed_upstream_keys.add("periodic_report_publication")
    if (
        not isinstance(upstream, dict)
        or set(upstream) != allowed_upstream_keys
        or not isinstance(lineage, dict)
        or lineage.get("contract")
        not in {
            "reddit_voc_v3_four_dataset_frontend_lineage_v1",
            "reddit_voc_v3_seven_dataset_frontend_lineage_v2",
        }
        or not isinstance(datasets, dict)
        or set(datasets) != {"base", "insights", "reports", "personas"}
        or receipt.get("v3_lineage") != lineage
        or receipt.get("upstream") != upstream
    ):
        fail("V3 frontend source coordinated lineage is invalid")
    for name, binding in datasets.items():
        if (
            not isinstance(binding, dict)
            or not sha_pattern.fullmatch(str(binding.get("public_manifest_sha256", "")))
            or not sha_pattern.fullmatch(str(binding.get("lineage_manifest_sha256", "")))
            or not sha_pattern.fullmatch(str(binding.get("validation_receipt_sha256", "")))
        ):
            fail(f"V3 frontend source {name} lineage binding is invalid")
    if periodic is None:
        if "periodic_report_publication" in receipt:
            fail("V3 periodic publication receipt binding is unexpected")
    else:
        assets = periodic.get("assets") if isinstance(periodic, dict) else None
        current_release = manifest.get("current_release")
        if (
            not isinstance(periodic, dict)
            or periodic.get("contract")
            != "reddit_voc_periodic_report_frontend_publication_v1"
            or not isinstance(current_release, dict)
            or periodic.get("data_release_id") != current_release.get("release_id")
            or receipt.get("periodic_report_publication") != periodic
            or not isinstance(assets, list)
            or len(assets) != 3
            or {row.get("grain") for row in assets if isinstance(row, dict)}
            != {"daily", "weekly", "monthly"}
        ):
            fail("V3 periodic publication coordinated lineage is invalid")
        inventory_by_path = {row["path"]: row for row in expected_rows}
        manifest_relative = periodic.get("manifest_relative_path")
        manifest_row = inventory_by_path.get(manifest_relative)
        if (
            not isinstance(manifest_relative, str)
            or not manifest_relative.startswith("public/periodic-report-assets/")
            or not isinstance(manifest_row, dict)
            or manifest_row.get("sha256") != periodic.get("manifest_sha256")
        ):
            fail("V3 periodic publication manifest inventory is invalid")
        for asset in assets:
            relative = asset.get("relative_path") if isinstance(asset, dict) else None
            row = inventory_by_path.get(relative)
            if (
                not isinstance(relative, str)
                or not relative.startswith("public/periodic-report-assets/")
                or not isinstance(row, dict)
                or row.get("sha256") != asset.get("sha256")
                or row.get("bytes") != asset.get("bytes")
            ):
                fail("V3 periodic publication asset inventory is invalid")
receipt_boundaries = receipt.get("boundaries")
checks = receipt.get("checks")
if (
    not isinstance(receipt_boundaries, dict)
    or receipt_boundaries.get("production_unchanged") is not True
    or receipt_boundaries.get("deploy") is not False
    or not isinstance(checks, dict)
    or not checks
    or any(value is not True for value in checks.values())
):
    fail("frontend source receipt validation evidence is incomplete")
print(
    candidate_input,
    manifest_sha,
    sha256(receipt_bytes).hexdigest(),
    sep="\t",
)
PY
)"
  IFS=$'\t' read -r \
    FRONTEND_CANDIDATE_INPUT_SHA \
    FRONTEND_SOURCE_MANIFEST_SHA \
    FRONTEND_SOURCE_RECEIPT_SHA <<< "${SOURCE_CONTRACT_TSV}"
  SOURCE_UI_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=True))' "${SOURCE_UI_ROOT}")"
  FRONTEND_SOURCE_MANIFEST="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=True))' "${FRONTEND_SOURCE_MANIFEST}")"
  FRONTEND_SOURCE_RECEIPT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=True))' "${FRONTEND_SOURCE_RECEIPT}")"
  BUILD_UI_ROOT="${SOURCE_UI_ROOT}"
  echo "manifest_only_source_validation=passed candidate_input=${FRONTEND_CANDIDATE_INPUT_SHA}"
fi

if [[ "${DIST_ONLY}" == false ]]; then
  for command in docker tar; do
    if ! command -v "${command}" >/dev/null 2>&1; then
      echo "required command is missing: ${command}" >&2
      exit 1
    fi
  done
  if ! docker buildx version >/dev/null 2>&1; then
    echo "docker buildx is unavailable" >&2
    exit 1
  fi
  if [[ "${NGINX_BASE_IMAGE}" != *@sha256:* ]]; then
    echo "NGINX_BASE_IMAGE must be pinned by sha256 digest" >&2
    exit 1
  fi
fi

PACKAGE_LOCK_SOURCE="${BUILD_UI_ROOT}/package-lock.json"
DOCKERIGNORE_SOURCE="${UI_ROOT}/.dockerignore"
if [[ "${DIST_ONLY}" == false ]]; then
  for reviewed_source in "${PACKAGE_LOCK_SOURCE}" "${DOCKERIGNORE_SOURCE}" "${DEPLOY_ROOT}/Dockerfile" "${DEPLOY_ROOT}/nginx.conf"; do
    if [[ ! -f "${reviewed_source}" || -L "${reviewed_source}" ]]; then
      echo "reviewed container build input is missing or unsafe: ${reviewed_source}" >&2
      exit 1
    fi
  done
fi

CURRENT_RELEASE_SOURCE="${PUBLIC_ROOT}/${CURRENT_RELEASE_RELATIVE_PATH}"
if [[ ! -f "${CURRENT_RELEASE_SOURCE}" || -L "${CURRENT_RELEASE_SOURCE}" ]]; then
  echo "current-release pointer is missing or unsafe: ${CURRENT_RELEASE_SOURCE}" >&2
  exit 1
fi
VERSIONS_TSV="$(python3 - "${CURRENT_RELEASE_SOURCE}" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
datasets = value.get("datasets")
schema = value.get("schema_version")
expected = {"base", "insights", "reports", "personas"}
if schema == "reddit_voc_current_release_v2":
    expected |= {"brand_health", "quarter_insights", "casebook"}
elif schema not in {None, "reddit_voc_current_release_v1"}:
    raise SystemExit("current-release schema contract is invalid")
if not isinstance(datasets, dict) or set(datasets) != expected:
    raise SystemExit("current-release datasets contract is invalid")
versions = []
for key in ("base", "insights", "reports", "personas"):
    binding = datasets.get(key)
    if not isinstance(binding, dict) or not isinstance(binding.get("dataset_version"), str):
        raise SystemExit(f"current-release dataset binding is invalid: {key}")
    versions.append(binding["dataset_version"])
print("\t".join(versions))
PY
)"
IFS=$'\t' read -r BASE_VERSION INSIGHTS_VERSION REPORTS_VERSION PERSONAS_VERSION <<< "${VERSIONS_TSV}"
if [[ ! "${BASE_VERSION}" =~ ^reddit_voc_site_snapshot_[a-z0-9_-]+$ ]] || \
   [[ ! "${INSIGHTS_VERSION}" =~ ^reddit_voc_insights_[a-z0-9_-]+$ ]] || \
   [[ ! "${REPORTS_VERSION}" =~ ^reddit_voc_reports_[a-z0-9_-]+$ ]] || \
   [[ ! "${PERSONAS_VERSION}" =~ ^reddit_voc_personas_[a-z0-9_-]+$ ]]; then
  echo "current-release contains an unsafe dataset version" >&2
  exit 1
fi

mkdir -p "${OUTPUT_ROOT}"
STAGING_DIR=""
PUBLIC_STAGING_DIR=""
DOCKER_CONTEXT_DIR=""
if [[ "${DIST_ONLY}" == false ]]; then
  STAGING_DIR="$(mktemp -d "${OUTPUT_ROOT}/staging.XXXXXX")"
fi
TEMP_ARCHIVE=""

cleanup() {
  if [[ -n "${TEMP_ARCHIVE}" && -f "${TEMP_ARCHIVE}" ]]; then
    rm -f "${TEMP_ARCHIVE}"
  fi
  if [[ -n "${STAGING_DIR}" && -d "${STAGING_DIR}" ]]; then
    rm -rf "${STAGING_DIR}"
  fi
  if [[ -n "${PUBLIC_STAGING_DIR}" && -d "${PUBLIC_STAGING_DIR}" ]]; then
    rm -rf "${PUBLIC_STAGING_DIR}"
  fi
  if [[ -n "${DOCKER_CONTEXT_DIR}" && -d "${DOCKER_CONTEXT_DIR}" ]]; then
    rm -rf "${DOCKER_CONTEXT_DIR}"
  fi
}
trap cleanup EXIT

BUILD_PUBLIC_ROOT="${DEFAULT_PUBLIC_ROOT}"
if [[ "${CANDIDATE_MODE}" == true ]]; then
  PUBLIC_STAGING_DIR="$(mktemp -d "${OUTPUT_ROOT}/public-staging.XXXXXX")"
  BUILD_PUBLIC_ROOT="${PUBLIC_STAGING_DIR}/public"
  mkdir -p "${BUILD_PUBLIC_ROOT}"
  cp -R "${PUBLIC_ROOT}/." "${BUILD_PUBLIC_ROOT}/"
fi

cd "${BUILD_UI_ROOT}"
PUBLIC_MANIFESTS=(
  "${BUILD_PUBLIC_ROOT}/data/reddit-voc/${BASE_VERSION}/manifest-public.json"
  "${BUILD_PUBLIC_ROOT}/data/reddit-voc/${INSIGHTS_VERSION}/public/manifest.json"
  "${BUILD_PUBLIC_ROOT}/data/reddit-voc/${REPORTS_VERSION}/public/manifest.json"
  "${BUILD_PUBLIC_ROOT}/data/reddit-voc/${PERSONAS_VERSION}/manifest.json"
)
for public_manifest in "${PUBLIC_MANIFESTS[@]}"; do
  if [[ ! -f "${public_manifest}" || -L "${public_manifest}" ]]; then
    echo "selected public projection is missing or unsafe: ${public_manifest}" >&2
    exit 1
  fi
done
export VITE_USE_MOCK=false
export VITE_API_BASE_URL=/api/v1
npm test
npm run lint
npx --no-install tsc -b --pretty false
REDDIT_VOC_BUILD_PUBLIC_DIR="${BUILD_PUBLIC_ROOT}" \
  REDDIT_VOC_BUILD_OUT_DIR="${DIST_ROOT}" \
  npm run build

AUDIT_ARGS=(
  --dist "${DIST_ROOT}"
  --base-version "${BASE_VERSION}"
  --insights-version "${INSIGHTS_VERSION}"
  --reports-version "${REPORTS_VERSION}"
  --personas-version "${PERSONAS_VERSION}"
  --current-release-path "${CURRENT_RELEASE_RELATIVE_PATH}"
)
python3 "${PROJECT_ROOT}/scripts/audit_insights_dist.py" \
  "${AUDIT_ARGS[@]}" --prepare-dist
python3 "${PROJECT_ROOT}/scripts/audit_insights_dist.py" "${AUDIT_ARGS[@]}"

if [[ "${DIST_ONLY}" == true ]]; then
  echo "dist_root=${DIST_ROOT}"
  echo "base_version=${BASE_VERSION}"
  echo "insights_version=${INSIGHTS_VERSION}"
  echo "reports_version=${REPORTS_VERSION}"
  echo "personas_version=${PERSONAS_VERSION}"
  echo "latest_collection_integrated=${LATEST_COLLECTION_INTEGRATED}"
  echo "latest_collection_fully_hydrated=${LATEST_COLLECTION_FULLY_HYDRATED}"
  if [[ "${CANDIDATE_MODE}" == true ]]; then
    echo "frontend_candidate_input_sha256=${FRONTEND_CANDIDATE_INPUT_SHA}"
    echo "frontend_source_manifest_sha256=${FRONTEND_SOURCE_MANIFEST_SHA}"
    echo "frontend_source_receipt_sha256=${FRONTEND_SOURCE_RECEIPT_SHA}"
  fi
  echo "artifact_mode=dist_only"
  echo "container_built=false"
  echo "deploy=false"
  exit 0
fi

RELEASE_DIST_ROOT="${DIST_ROOT}"
DOCKER_BUILD_CONTEXT="${UI_ROOT}"
DOCKERFILE_PATH="${DEPLOY_ROOT}/Dockerfile"
if [[ "${CANDIDATE_CONTAINER}" == true ]]; then
  DOCKER_CONTEXT_DIR="$(mktemp -d "${OUTPUT_ROOT}/docker-context.XXXXXX")"
  mkdir -p "${DOCKER_CONTEXT_DIR}/dist" "${DOCKER_CONTEXT_DIR}/deploy/insights"
  cp -R "${DIST_ROOT}/." "${DOCKER_CONTEXT_DIR}/dist/"
  cp "${DEPLOY_ROOT}/Dockerfile" "${DOCKER_CONTEXT_DIR}/deploy/insights/Dockerfile"
  cp "${DEPLOY_ROOT}/nginx.conf" "${DOCKER_CONTEXT_DIR}/deploy/insights/nginx.conf"
  cp "${DOCKERIGNORE_SOURCE}" "${DOCKER_CONTEXT_DIR}/.dockerignore"
  if [[ -n "$(find "${DOCKER_CONTEXT_DIR}" -type l -print -quit)" ]]; then
    echo "isolated Docker context must not contain symlinks" >&2
    exit 1
  fi
  cmp "${DEPLOY_ROOT}/Dockerfile" "${DOCKER_CONTEXT_DIR}/deploy/insights/Dockerfile"
  cmp "${DEPLOY_ROOT}/nginx.conf" "${DOCKER_CONTEXT_DIR}/deploy/insights/nginx.conf"
  cmp "${DOCKERIGNORE_SOURCE}" "${DOCKER_CONTEXT_DIR}/.dockerignore"
  python3 "${PROJECT_ROOT}/scripts/audit_insights_dist.py" \
    --dist "${DOCKER_CONTEXT_DIR}/dist" \
    --base-version "${BASE_VERSION}" \
    --insights-version "${INSIGHTS_VERSION}" \
    --reports-version "${REPORTS_VERSION}" \
    --personas-version "${PERSONAS_VERSION}" \
    --current-release-path "${CURRENT_RELEASE_RELATIVE_PATH}"
  python3 - "${DIST_ROOT}" "${DOCKER_CONTEXT_DIR}/dist" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

def contracts(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, sha256(path.read_bytes()).hexdigest())
        for path in root.rglob("*")
        if path.is_file()
    }

source = contracts(Path(sys.argv[1]))
isolated = contracts(Path(sys.argv[2]))
if source != isolated:
    raise SystemExit("isolated Docker context dist differs from audited candidate dist")
print(f"isolated_docker_context_dist=passed files={len(isolated)}")
PY
  RELEASE_DIST_ROOT="${DOCKER_CONTEXT_DIR}/dist"
  DOCKER_BUILD_CONTEXT="${DOCKER_CONTEXT_DIR}"
  DOCKERFILE_PATH="${DOCKER_CONTEXT_DIR}/deploy/insights/Dockerfile"
fi

RELEASE_BUILDER_ARGS=(
  "${RELEASE_DIST_ROOT}"
  "${STAGING_DIR}"
  "${NGINX_BASE_IMAGE}"
  "${DEPLOY_ROOT}"
  "${PROJECT_ROOT}"
  "$(node --version)"
  "$(npm --version)"
  "${BASE_VERSION}"
  "${INSIGHTS_VERSION}"
  "${REPORTS_VERSION}"
  "${PERSONAS_VERSION}"
  "${CURRENT_RELEASE_RELATIVE_PATH}"
  "${LATEST_COLLECTION_INTEGRATED}"
  "${LATEST_COLLECTION_FULLY_HYDRATED}"
  "${PACKAGE_LOCK_SOURCE}"
  "${DOCKERIGNORE_SOURCE}"
)
if [[ "${CANDIDATE_MODE}" == true ]]; then
  RELEASE_BUILDER_ARGS+=(
    "${FRONTEND_SOURCE_MANIFEST}"
    "${FRONTEND_SOURCE_RECEIPT}"
  )
fi
RELEASE_SHA="$(node "${DEPLOY_ROOT}/build-release.mjs" "${RELEASE_BUILDER_ARGS[@]}")"
RELEASE_DIR="${OUTPUT_ROOT}/${RELEASE_SHA}"
ARCHIVE="${OUTPUT_ROOT}/reddit-voc-insights-${RELEASE_SHA}.tgz"
BUILD_RECEIPT_STATUS=""
BUILD_RECEIPT_SHA=""

write_build_receipt() {
  local release_dir="$1"
  local archive_path="$2"
  local archive_sha="$3"
  local image_tar_sha="$4"
  local artifact_reused="$5"
  local result
  result="$(python3 - \
    "${PROJECT_ROOT}" \
    "${RECEIPT_PATH}" \
    "${release_dir}" \
    "${archive_path}" \
    "${RELEASE_SHA}" \
    "${archive_sha}" \
    "${image_tar_sha}" \
    "${FRONTEND_CANDIDATE_INPUT_SHA}" \
    "${FRONTEND_SOURCE_MANIFEST_SHA}" \
    "${FRONTEND_SOURCE_RECEIPT_SHA}" \
    "${LATEST_COLLECTION_INTEGRATED}" \
    "${LATEST_COLLECTION_FULLY_HYDRATED}" \
    "${artifact_reused}" <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

(
    project_arg,
    receipt_arg,
    release_dir_arg,
    archive_arg,
    release_sha,
    expected_archive_sha,
    expected_image_sha,
    frontend_candidate_sha,
    frontend_manifest_sha,
    frontend_receipt_sha,
    integrated_arg,
    hydrated_arg,
    reused_arg,
) = sys.argv[1:]
sha_pattern = re.compile(r"^[a-f0-9]{64}$")


def fail(reason: str) -> None:
    raise SystemExit(reason)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def regular(path: Path, label: str) -> bytes:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        fail(f"{label} must be a regular file")
    return path.read_bytes()


project = Path(project_arg).resolve(strict=True)
tmp_root = (project / "tmp").resolve(strict=True)
receipt_path = Path(os.path.abspath(receipt_arg))
try:
    receipt_relative = receipt_path.relative_to(tmp_root)
except ValueError:
    fail("build receipt must remain below project tmp")
if any(ord(character) < 32 for character in str(receipt_path)):
    fail("build receipt path contains control characters")

release_dir = Path(release_dir_arg)
release_manifest_path = release_dir / "release-manifest.json"
release_manifest_bytes = regular(release_manifest_path, "release manifest")
release_manifest = json.loads(release_manifest_bytes.decode("utf-8"))
if (
    release_manifest.get("schema_version") != "reddit_voc_insights_site_release_v2"
    or release_manifest.get("build_contract_version")
    != "reddit_voc_insights_container_v6"
    or release_manifest.get("release_sha256") != release_sha
):
    fail("formal release manifest contract mismatch")

frontend_source = release_manifest.get("frontend_source")
if (
    not isinstance(frontend_source, dict)
    or frontend_source.get("frontend_candidate_input_sha256")
    != frontend_candidate_sha
    or frontend_source.get("manifest", {}).get("sha256")
    != frontend_manifest_sha
    or frontend_source.get("validation_receipt", {}).get("sha256")
    != frontend_receipt_sha
):
    fail("formal release manifest frontend source lineage mismatch")

files = release_manifest.get("files")
if not isinstance(files, list) or release_manifest.get("file_count") != len(files):
    fail("formal release dist inventory mismatch")
for row in files:
    if not isinstance(row, dict) or set(row) != {"bytes", "path", "sha256"}:
        fail("formal release dist file contract mismatch")
    relative = PurePosixPath(row["path"]) if isinstance(row.get("path"), str) else None
    if (
        relative is None
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or not isinstance(row.get("bytes"), int)
        or isinstance(row.get("bytes"), bool)
        or row["bytes"] < 0
        or not isinstance(row.get("sha256"), str)
        or sha_pattern.fullmatch(row["sha256"]) is None
    ):
        fail("formal release dist file contract mismatch")
dist_inventory = {
    "file_count": len(files),
    "inventory_sha256": sha256(canonical(files)).hexdigest(),
    "total_bytes": sum(row["bytes"] for row in files),
}

archive_path = Path(archive_arg)
archive_bytes = regular(archive_path, "release archive")
image_path = release_dir / f"reddit-voc-insights-{release_sha}.tar"
image_bytes = regular(image_path, "image tar")
if sha256(archive_bytes).hexdigest() != expected_archive_sha:
    fail("release archive SHA-256 mismatch")
if sha256(image_bytes).hexdigest() != expected_image_sha:
    fail("image tar SHA-256 mismatch")

collection_status = {
    "latest_collection_fully_hydrated": hydrated_arg == "true",
    "latest_collection_integrated": integrated_arg == "true",
}
if any(
    release_manifest.get(key) != value
    for key, value in collection_status.items()
):
    fail("formal release collection status mismatch")

data_lineage = {
    "current_release": release_manifest.get("current_release"),
    "dataset_manifests": release_manifest.get("dataset_manifests"),
    "dataset_versions": release_manifest.get("dataset_versions"),
}
stable_identity = {
    "build_contract_version": "reddit_voc_insights_container_v6",
    "data_lineage": data_lineage,
    "data_runtime": release_manifest.get("data_runtime"),
    "dist_inventory": dist_inventory,
    "frontend_source": frontend_source,
    "release_sha256": release_sha,
}
receipt = {
    "artifacts": {
        "archive_tgz": {
            "bytes": len(archive_bytes),
            "path": archive_path.name,
            "sha256": expected_archive_sha,
        },
        "image_tar": {
            "bytes": len(image_bytes),
            "path": image_path.name,
            "sha256": expected_image_sha,
        },
    },
    "checks": {
        "dist_audit": True,
        "docker_image_tar_contract": True,
        "immutable_release_checksums": True,
        "manifest_only_source_validation": True,
    },
    "collection_status": collection_status,
    "commands": {
        "build": {"argv": ["npm", "run", "build"], "status": "passed"},
        "lint": {"argv": ["npm", "run", "lint"], "status": "passed"},
        "typecheck": {
            "argv": ["npx", "--no-install", "tsc", "-b", "--pretty", "false"],
            "status": "passed",
        },
        "unit": {"argv": ["npm", "test"], "status": "passed"},
    },
    "data_lineage": data_lineage,
    "dist_inventory": dist_inventory,
    "evidence_grade": "L2_local_build_artifact",
    "frontend_source": frontend_source,
    "release_manifest": {
        "bytes": len(release_manifest_bytes),
        "path": "release-manifest.json",
        "sha256": sha256(release_manifest_bytes).hexdigest(),
    },
    "release_sha256": release_sha,
    "schema_version": "reddit_voc_insights_build_receipt_v1",
    "side_effects": {
        "collector_restart": False,
        "database_write": False,
        "deploy": False,
        "docker_load": False,
        "live_send": False,
        "provider_call": False,
        "remote_write": False,
        "schedule_change": False,
        "webhook_send": False,
    },
    "stable_identity_sha256": sha256(canonical(stable_identity)).hexdigest(),
    "status": "passed_local_build",
}
payload = canonical(receipt) + b"\n"

current = tmp_root
for part in receipt_relative.parent.parts:
    current /= part
    try:
        metadata = os.lstat(current)
    except FileNotFoundError:
        os.mkdir(current, 0o700)
        metadata = os.lstat(current)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        fail("build receipt path has an unsafe ancestor")

try:
    metadata = os.lstat(receipt_path)
except FileNotFoundError:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(receipt_path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(receipt_path, 0o600)
    publication_status = "created"
else:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        fail("existing build receipt is unsafe")
    if receipt_path.read_bytes() != payload:
        fail("build receipt immutable collision")
    publication_status = "no_change"

print(
    publication_status,
    sha256(payload).hexdigest(),
    str(receipt_path),
    reused_arg,
    sep="\t",
)
PY
)"
  IFS=$'\t' read -r \
    BUILD_RECEIPT_STATUS \
    BUILD_RECEIPT_SHA \
    RECEIPT_PATH \
    BUILD_RECEIPT_ARTIFACT_REUSED <<< "${result}"
}

if [[ -e "${RELEASE_DIR}" ]]; then
  if [[ ! -d "${RELEASE_DIR}" || -L "${RELEASE_DIR}" || ! -f "${RELEASE_DIR}/SHA256SUMS" ]]; then
    echo "existing release is incomplete or unsafe: ${RELEASE_DIR}" >&2
    exit 1
  fi
  EXISTING_RELEASE_SHA="$(node -e 'const fs=require("fs"); const p=JSON.parse(fs.readFileSync(process.argv[1], "utf8")); process.stdout.write(p.release_sha256)' "${RELEASE_DIR}/release-manifest.json")"
  if [[ "${EXISTING_RELEASE_SHA}" != "${RELEASE_SHA}" ]]; then
    echo "existing release manifest identity mismatch" >&2
    exit 1
  fi
  (
    cd "${RELEASE_DIR}"
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum --check SHA256SUMS
    else
      shasum -a 256 --check SHA256SUMS
    fi
  )
  if [[ ! -f "${ARCHIVE}" || -L "${ARCHIVE}" ]]; then
    echo "immutable release exists but its archive is missing: ${ARCHIVE}" >&2
    exit 1
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    EXISTING_ARCHIVE_SHA="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
    EXISTING_IMAGE_TAR_SHA="$(sha256sum "${RELEASE_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar" | awk '{print $1}')"
  else
    EXISTING_ARCHIVE_SHA="$(shasum -a 256 "${ARCHIVE}" | awk '{print $1}')"
    EXISTING_IMAGE_TAR_SHA="$(shasum -a 256 "${RELEASE_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar" | awk '{print $1}')"
  fi
  if [[ "${CANDIDATE_CONTAINER}" == true ]]; then
    write_build_receipt \
      "${RELEASE_DIR}" \
      "${ARCHIVE}" \
      "${EXISTING_ARCHIVE_SHA}" \
      "${EXISTING_IMAGE_TAR_SHA}" \
      true
  fi
  echo "release_sha=${RELEASE_SHA}"
  echo "release_dir=${RELEASE_DIR}"
  echo "archive=${ARCHIVE}"
  echo "archive_sha256=${EXISTING_ARCHIVE_SHA}"
  echo "image_tar_sha256=${EXISTING_IMAGE_TAR_SHA}"
  echo "latest_collection_integrated=${LATEST_COLLECTION_INTEGRATED}"
  echo "latest_collection_fully_hydrated=${LATEST_COLLECTION_FULLY_HYDRATED}"
  echo "artifact_reused=true"
  if [[ "${CANDIDATE_CONTAINER}" == true ]]; then
    echo "receipt_path=${RECEIPT_PATH}"
    echo "receipt_sha256=${BUILD_RECEIPT_SHA}"
    echo "receipt_status=${BUILD_RECEIPT_STATUS}"
  fi
  exit 0
fi

if [[ -e "${ARCHIVE}" ]]; then
  echo "archive path exists without its immutable release directory: ${ARCHIVE}" >&2
  exit 1
fi

cp "${DEPLOY_ROOT}/compose.yaml" "${STAGING_DIR}/compose.yaml"

docker buildx build \
  --platform linux/amd64 \
  --build-arg "NGINX_BASE_IMAGE=${NGINX_BASE_IMAGE}" \
  --build-arg "RELEASE_SHA=${RELEASE_SHA}" \
  --file "${DOCKERFILE_PATH}" \
  --tag "reddit-voc-insights:${RELEASE_SHA}" \
  --provenance=false \
  --output "type=docker,dest=${STAGING_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar" \
  "${DOCKER_BUILD_CONTEXT}"

python3 - \
  "${STAGING_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar" \
  "${STAGING_DIR}/dist-SHA256SUMS" \
  "${RELEASE_SHA}" <<'PY'
from hashlib import sha256
from io import BytesIO
import json
from pathlib import PurePosixPath
import sys
import tarfile

image_path, sums_path, expected_release = sys.argv[1:]
with tarfile.open(image_path, mode="r") as image:
    manifest = json.loads(image.extractfile("manifest.json").read())
    if not isinstance(manifest, list) or len(manifest) != 1:
        raise SystemExit("Docker image archive manifest must contain exactly one image")
    image_entry = manifest[0]
    config = json.loads(image.extractfile(image_entry["Config"]).read())
    labels = config.get("config", {}).get("Labels", {})
    if config.get("architecture") != "amd64":
        raise SystemExit("Docker image architecture mismatch")
    if config.get("config", {}).get("User") != "101:101":
        raise SystemExit("Docker image user mismatch")
    if labels.get("com.reddit-voc.component") != "insights-site" or labels.get("com.reddit-voc.release") != expected_release:
        raise SystemExit("Docker image release labels mismatch")

    image_files: dict[str, bytes] = {}
    prefix = PurePosixPath("usr/share/nginx/html")
    for layer_name in image_entry.get("Layers", []):
        layer_bytes = image.extractfile(layer_name).read()
        with tarfile.open(fileobj=BytesIO(layer_bytes), mode="r:*") as layer:
            for member in layer.getmembers():
                name = PurePosixPath(member.name.lstrip("./"))
                try:
                    relative_path = name.relative_to(prefix)
                except ValueError:
                    continue
                basename = relative_path.name
                parent = relative_path.parent.as_posix()
                if basename == ".wh..wh..opq":
                    parent_prefix = "" if parent == "." else f"{parent}/"
                    image_files = {
                        key: value
                        for key, value in image_files.items()
                        if not key.startswith(parent_prefix)
                    }
                    continue
                if basename.startswith(".wh."):
                    target_name = basename.removeprefix(".wh.")
                    target = target_name if parent == "." else f"{parent}/{target_name}"
                    image_files.pop(target, None)
                    continue
                if not member.isfile():
                    continue
                relative = relative_path.as_posix()
                stream = layer.extractfile(member)
                if stream is None:
                    raise SystemExit("Docker image layer file could not be read")
                image_files[relative] = stream.read()

expected_files: dict[str, str] = {}
for line in open(sums_path, encoding="utf-8"):
    digest, release_path = line.rstrip("\n").split("  ", 1)
    if not release_path.startswith("dist/"):
        raise SystemExit("dist checksum path is invalid")
    expected_files[release_path.removeprefix("dist/")] = digest
actual_files = {name: sha256(payload).hexdigest() for name, payload in image_files.items() if name != "release.json"}
if actual_files != expected_files:
    raise SystemExit("Docker image filesystem does not match dist-SHA256SUMS")
release_marker = json.loads(image_files.get("release.json", b"null"))
if release_marker != {"release_sha256": expected_release}:
    raise SystemExit("Docker image release marker mismatch")
print(f"docker_image_tar_contract=passed files={len(expected_files)} release_sha={expected_release}")
PY

(
  cd "${STAGING_DIR}"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum \
      compose.yaml \
      dist-SHA256SUMS \
      release-manifest.json \
      "reddit-voc-insights-${RELEASE_SHA}.tar" > SHA256SUMS
    sha256sum --check SHA256SUMS
  else
    shasum -a 256 \
      compose.yaml \
      dist-SHA256SUMS \
      release-manifest.json \
      "reddit-voc-insights-${RELEASE_SHA}.tar" > SHA256SUMS
    shasum -a 256 --check SHA256SUMS
  fi
)

mv "${STAGING_DIR}" "${RELEASE_DIR}"
TEMP_ARCHIVE="${ARCHIVE}.tmp.$$"
COPYFILE_DISABLE=1 tar -czf "${TEMP_ARCHIVE}" -C "${OUTPUT_ROOT}" "${RELEASE_SHA}"
mv "${TEMP_ARCHIVE}" "${ARCHIVE}"
TEMP_ARCHIVE=""
if command -v sha256sum >/dev/null 2>&1; then
  ARCHIVE_SHA="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
  IMAGE_TAR_SHA="$(sha256sum "${RELEASE_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar" | awk '{print $1}')"
else
  ARCHIVE_SHA="$(shasum -a 256 "${ARCHIVE}" | awk '{print $1}')"
  IMAGE_TAR_SHA="$(shasum -a 256 "${RELEASE_DIR}/reddit-voc-insights-${RELEASE_SHA}.tar" | awk '{print $1}')"
fi
if [[ "${CANDIDATE_CONTAINER}" == true ]]; then
  write_build_receipt \
    "${RELEASE_DIR}" \
    "${ARCHIVE}" \
    "${ARCHIVE_SHA}" \
    "${IMAGE_TAR_SHA}" \
    false
fi
cleanup
trap - EXIT

echo "release_sha=${RELEASE_SHA}"
echo "release_dir=${RELEASE_DIR}"
echo "archive=${ARCHIVE}"
echo "archive_sha256=${ARCHIVE_SHA}"
echo "image_tar_sha256=${IMAGE_TAR_SHA}"
echo "latest_collection_integrated=${LATEST_COLLECTION_INTEGRATED}"
echo "latest_collection_fully_hydrated=${LATEST_COLLECTION_FULLY_HYDRATED}"
echo "artifact_mode=$([[ "${CANDIDATE_CONTAINER}" == true ]] && echo candidate_container || echo container)"
echo "deploy=false"
echo "artifact_reused=false"
if [[ "${CANDIDATE_CONTAINER}" == true ]]; then
  echo "receipt_path=${RECEIPT_PATH}"
  echo "receipt_sha256=${BUILD_RECEIPT_SHA}"
  echo "receipt_status=${BUILD_RECEIPT_STATUS}"
fi
