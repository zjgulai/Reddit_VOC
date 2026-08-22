#!/usr/bin/env python3
"""Run deterministic local same-dist browser acceptance for Reddit VOC.

The command serves only an already-built final dist on an ephemeral loopback
port.  It never contacts a remote site and pins Playwright CLI to the reviewed
offline package version.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import unquote, urlsplit


SCHEMA_VERSION = "reddit_voc_same_dist_browser_e2e_receipt_v2"
RELEASE_SCHEMA = "reddit_voc_insights_site_release_v2"
POINTER_SCHEMAS = {
    "reddit_voc_current_release_v1",
    "reddit_voc_current_release_v2",
}
PLAYWRIGHT_VERSION = "0.1.17"
DEFAULT_RUNNER = (
    "npm",
    "exec",
    "--offline",
    "--package=@playwright/cli@0.1.17",
    "--",
    "playwright-cli",
)
ROUTES = (
    "/",
    "/dashboard",
    "/dashboard/reports",
    "/dashboard/analytics",
    "/dashboard/insights",
    "/dashboard/search",
    "/dashboard/ugc-showcase",
    "/dashboard/messages",
    "/dashboard/settings",
    "/features",
    "/how-it-works",
    "/faq",
    "/cases",
)
VIEWPORTS = ("desktop", "mobile")
PUBLIC_CASEBOOK_ROOT = "data/reddit-voc/reddit_voc_casebook_20260716_public_a1"
PUBLIC_CASEBOOK_MANIFEST_SHA256 = (
    "8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126"
)
PUBLIC_CASEBOOK_DATA_SHA256 = (
    "5ad81e7af5f9744332baacd0a87ac947f1097894f4ef27c6aab692b0f90b249c"
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"(?:Version\s+)?([0-9]+\.[0-9]+\.[0-9]+)")
Runner = Callable[[Sequence[str], Mapping[str, str], float], subprocess.CompletedProcess[str]]


class InsightsE2EError(ValueError):
    """A same-dist browser acceptance invariant failed."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise InsightsE2EError(f"{label}_sha256_invalid")
    return value


def safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise InsightsE2EError(f"{label}_path_invalid")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise InsightsE2EError(f"{label}_path_invalid")
    return relative.as_posix()


def regular_file(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise InsightsE2EError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise InsightsE2EError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise InsightsE2EError(f"{label}_mode_invalid")
    return metadata


def safe_directory(path: Path, *, label: str, mode: int | None = None) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise InsightsE2EError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise InsightsE2EError(f"{label}_unsafe")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise InsightsE2EError(f"{label}_mode_invalid")
    return metadata


def load_json(path: Path, *, label: str, canonical: bool = False) -> dict[str, Any]:
    regular_file(path, label=label)
    payload = path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InsightsE2EError(f"{label}_json_invalid") from exc
    if not isinstance(value, dict):
        raise InsightsE2EError(f"{label}_object_invalid")
    if canonical and payload != canonical_bytes(value):
        raise InsightsE2EError(f"{label}_noncanonical")
    return value


def tree_inventory(root: Path) -> list[dict[str, Any]]:
    safe_directory(root, label="dist_root")
    rows: list[dict[str, Any]] = []
    for parent, directory_names, file_names in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        for name in directory_names:
            metadata = os.lstat(parent_path / name)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise InsightsE2EError("dist_directory_unsafe")
        for name in file_names:
            path = parent_path / name
            metadata = regular_file(path, label="dist_file")
            relative = path.relative_to(root).as_posix()
            safe_relative(relative, label="dist_file")
            rows.append(
                {"path": relative, "bytes": metadata.st_size, "sha256": file_sha256(path)}
            )
    rows.sort(key=lambda row: row["path"])
    if not rows or not any(row["path"] == "index.html" for row in rows):
        raise InsightsE2EError("dist_inventory_invalid")
    return rows


def inventory_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    return sha256(canonical_bytes(list(rows))).hexdigest()


def _manifest_files(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise InsightsE2EError("release_manifest_files_invalid")
    rows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise InsightsE2EError("release_manifest_file_invalid")
        relative = safe_relative(raw.get("path"), label="release_manifest_file")
        size = raw.get("bytes")
        digest = require_sha(raw.get("sha256"), label="release_manifest_file")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise InsightsE2EError("release_manifest_file_bytes_invalid")
        rows.append({"path": relative, "bytes": size, "sha256": digest})
    if rows != sorted(rows, key=lambda row: row["path"]):
        raise InsightsE2EError("release_manifest_files_not_sorted")
    if len({row["path"] for row in rows}) != len(rows):
        raise InsightsE2EError("release_manifest_files_duplicate")
    return rows


def validate_public_casebook(dist_root: Path) -> dict[str, Any]:
    root = dist_root / PUBLIC_CASEBOOK_ROOT
    safe_directory(root, label="public_casebook_root")
    if {path.name for path in root.iterdir()} != {"manifest.json", "casebook.json"}:
        raise InsightsE2EError("public_casebook_file_set_invalid")
    manifest_path = root / "manifest.json"
    casebook_path = root / "casebook.json"
    if file_sha256(manifest_path) != PUBLIC_CASEBOOK_MANIFEST_SHA256:
        raise InsightsE2EError("public_casebook_manifest_sha256_mismatch")
    if file_sha256(casebook_path) != PUBLIC_CASEBOOK_DATA_SHA256:
        raise InsightsE2EError("public_casebook_data_sha256_mismatch")
    manifest = load_json(manifest_path, label="public_casebook_manifest", canonical=True)
    casebook = load_json(casebook_path, label="public_casebook_data", canonical=True)
    contract = manifest.get("files", {}).get("casebook.json")
    if (
        manifest.get("schema_version")
        != "reddit_voc_governance_casebook_public_manifest_v1"
        or manifest.get("status") != "ready"
        or manifest.get("lifecycle_status") != "review_required"
        or not isinstance(contract, dict)
        or contract.get("bytes") != casebook_path.stat().st_size
        or contract.get("sha256") != PUBLIC_CASEBOOK_DATA_SHA256
        or casebook.get("schema_version")
        != "reddit_voc_governance_casebook_public_v1"
        or casebook.get("projection_id") != manifest.get("projection_id")
    ):
        raise InsightsE2EError("public_casebook_contract_invalid")
    dossiers = casebook.get("dossiers")
    dossier = dossiers[0] if isinstance(dossiers, list) and len(dossiers) == 1 else None
    assessment = dossier.get("assessment") if isinstance(dossier, dict) else None
    stages = dossier.get("stages") if isinstance(dossier, dict) else None
    if (
        not isinstance(dossier, dict)
        or dossier.get("title") != "Momcozy 社区信任与疑似非自然推广治理事件"
        or dossier.get("lifecycle_status") != "review_required"
        or not isinstance(assessment, dict)
        or assessment.get("commercial_relation") != "C2"
        or assessment.get("integrity_level") != "I3"
        or assessment.get("brand_control_confirmed") is not False
        or not isinstance(stages, list)
        or [stage.get("label") for stage in stages if isinstance(stage, dict)]
        != ["洞察", "证据", "行动", "监测", "复盘"]
    ):
        raise InsightsE2EError("public_casebook_semantics_invalid")
    serialized = casebook_path.read_text(encoding="utf-8")
    if "http://" in serialized or "https://" in serialized or '"author"' in serialized:
        raise InsightsE2EError("public_casebook_privacy_boundary_invalid")
    return {
        "relativeRoot": PUBLIC_CASEBOOK_ROOT,
        "manifestSha256": PUBLIC_CASEBOOK_MANIFEST_SHA256,
        "dataSha256": PUBLIC_CASEBOOK_DATA_SHA256,
        "dossierCount": 1,
        "externalNavigation": False,
    }


def validate_release(
    *,
    dist_root: Path,
    release_manifest_path: Path,
    expected_manifest_sha256: str,
    expected_release_sha256: str,
    expected_release_id: str,
) -> dict[str, Any]:
    manifest_sha = require_sha(expected_manifest_sha256, label="release_manifest")
    release_sha = require_sha(expected_release_sha256, label="release")
    regular_file(release_manifest_path, label="release_manifest")
    if file_sha256(release_manifest_path) != manifest_sha:
        raise InsightsE2EError("release_manifest_sha256_mismatch")
    manifest = load_json(release_manifest_path, label="release_manifest")
    if manifest.get("schema_version") != RELEASE_SCHEMA:
        raise InsightsE2EError("release_manifest_schema_invalid")
    if manifest.get("release_sha256") != release_sha:
        raise InsightsE2EError("release_identity_mismatch")
    if manifest.get("authentication_enabled") is not False:
        raise InsightsE2EError("release_authentication_contract_invalid")

    casebook = validate_public_casebook(dist_root)
    rows = tree_inventory(dist_root)
    if _manifest_files(manifest.get("files")) != rows:
        raise InsightsE2EError("release_dist_inventory_mismatch")
    if manifest.get("file_count") != len(rows):
        raise InsightsE2EError("release_dist_file_count_mismatch")

    current = manifest.get("current_release")
    if not isinstance(current, dict):
        raise InsightsE2EError("release_current_pointer_invalid")
    pointer_relative = safe_relative(current.get("path"), label="current_pointer")
    pointer_path = dist_root / pointer_relative
    pointer_sha = require_sha(current.get("sha256"), label="current_pointer")
    if file_sha256(pointer_path) != pointer_sha:
        raise InsightsE2EError("current_pointer_sha256_mismatch")
    pointer = load_json(pointer_path, label="current_pointer")
    if pointer.get("schema_version") not in POINTER_SCHEMAS:
        raise InsightsE2EError("current_pointer_schema_invalid")
    if pointer.get("release_id") != expected_release_id or current.get("release_id") != expected_release_id:
        raise InsightsE2EError("current_release_id_mismatch")
    datasets = pointer.get("datasets")
    versions = manifest.get("dataset_versions")
    if not isinstance(datasets, dict) or not isinstance(versions, dict):
        raise InsightsE2EError("release_dataset_bindings_invalid")
    actual_versions = {
        key: binding.get("dataset_version") if isinstance(binding, dict) else None
        for key, binding in datasets.items()
    }
    expected_keys = {"base", "insights", "reports", "personas"}
    if pointer.get("schema_version") == "reddit_voc_current_release_v2":
        expected_keys.update({"brand_health", "quarter_insights", "casebook"})
    if set(actual_versions) != expected_keys or actual_versions != versions:
        raise InsightsE2EError("release_dataset_versions_mismatch")
    return {
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "release_sha256": release_sha,
        "release_id": expected_release_id,
        "dist_inventory": rows,
        "dist_inventory_sha256": inventory_sha256(rows),
        "pointer": pointer,
        "pointer_relative_path": pointer_relative,
        "pointer_sha256": pointer_sha,
        "dataset_versions": versions,
        "casebook": casebook,
    }


class _StrictSpaHandler(SimpleHTTPRequestHandler):
    server_version = "RedditVOCPlanC/1"

    def __init__(
        self,
        *args: Any,
        directory: str,
        allowed_files: set[str],
        release_marker: bytes,
        **kwargs: Any,
    ):
        self._allowed_files = allowed_files
        self._release_marker = release_marker
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _prepare_path(self) -> bool:
        try:
            path = unquote(urlsplit(self.path).path, errors="strict")
        except UnicodeError:
            self.send_error(400)
            return False
        if path in ROUTES:
            self.path = "/index.html"
            return True
        if path in self._allowed_files:
            self.path = path
            return True
        self.send_error(404)
        return False

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/release.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(self._release_marker)))
            self.end_headers()
            self.wfile.write(self._release_marker)
            return
        if self._prepare_path():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/release.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(self._release_marker)))
            self.end_headers()
            return
        if self._prepare_path():
            super().do_HEAD()


@contextmanager
def serve_dist(
    dist_root: Path,
    inventory: Sequence[Mapping[str, Any]],
    release_sha256: str,
) -> Iterator[str]:
    allowed_files = {f"/{row['path']}" for row in inventory}
    release_marker = canonical_bytes({"release_sha256": release_sha256})

    def handler(*args: Any, **kwargs: Any) -> _StrictSpaHandler:
        return _StrictSpaHandler(
            *args,
            directory=str(dist_root),
            allowed_files=allowed_files,
            release_marker=release_marker,
            **kwargs,
        )

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def default_runner(
    command: Sequence[str], env: Mapping[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def runner_prefix(runner_executable: str | None) -> tuple[str, ...]:
    if runner_executable is None:
        return DEFAULT_RUNNER
    executable = Path(runner_executable)
    regular_file(executable, label="runner_executable")
    if not os.access(executable, os.X_OK):
        raise InsightsE2EError("runner_executable_not_executable")
    return (str(executable),)


def _checked_run(
    runner: Runner,
    command: Sequence[str],
    env: Mapping[str, str],
    *,
    label: str,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = runner(command, env, timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InsightsE2EError(f"{label}_execution_failed") from exc
    if completed.returncode != 0:
        raise InsightsE2EError(f"{label}_failed")
    return completed


def verify_runner_version(
    runner: Runner, prefix: Sequence[str], env: Mapping[str, str]
) -> str:
    completed = _checked_run(
        runner, [*prefix, "--version"], env, label="playwright_version", timeout=30
    )
    match = VERSION_RE.search(completed.stdout.strip())
    if match is None or match.group(1) != PLAYWRIGHT_VERSION:
        raise InsightsE2EError("playwright_version_mismatch")
    return match.group(1)


def _parse_runner_result(stdout: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout.strip())
    except json.JSONDecodeError as exc:
        diagnostic = " ".join(stdout.strip().split())[:4000]
        if diagnostic:
            print(f"playwright_result_raw={diagnostic}", file=sys.stderr)
        raise InsightsE2EError("playwright_result_json_invalid") from exc
    if not isinstance(value, dict):
        raise InsightsE2EError("playwright_result_object_invalid")
    return value


def validate_callback_result(result: Mapping[str, Any], release: Mapping[str, Any]) -> None:
    if result.get("status") != "passed":
        raise InsightsE2EError("playwright_result_status_invalid")
    rows = result.get("routes")
    if not isinstance(rows, list) or len(rows) != len(ROUTES) * len(VIEWPORTS):
        raise InsightsE2EError("playwright_route_count_invalid")
    expected_pairs = {(viewport, route) for viewport in VIEWPORTS for route in ROUTES}
    actual_pairs: set[tuple[object, object]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise InsightsE2EError("playwright_route_row_invalid")
        actual_pairs.add((row.get("viewport"), row.get("route")))
        if (
            row.get("error") is not None
            or row.get("status") != 200
            or row.get("finalPath") != row.get("route")
            or row.get("requiredTextPresent") is not True
            or row.get("horizontalOverflow") is not False
            or row.get("passwordInputs") != 0
            or row.get("loginControls") not in ([], None)
        ):
            raise InsightsE2EError("playwright_route_contract_failed")
    if actual_pairs != expected_pairs:
        raise InsightsE2EError("playwright_route_matrix_invalid")
    for field in ("browserErrors", "sameOriginHttpFailures", "externalRequests"):
        if result.get(field) != []:
            raise InsightsE2EError(f"playwright_{field}_not_empty")
    observed_release = result.get("release")
    if not isinstance(observed_release, dict):
        raise InsightsE2EError("playwright_release_binding_missing")
    if (
        observed_release.get("releaseSha256") != release["release_sha256"]
        or observed_release.get("releaseId") != release["release_id"]
        or observed_release.get("releasePointerSha256") != release["pointer_sha256"]
        or observed_release.get("datasetVersions") != release["dataset_versions"]
        or observed_release.get("noLogin") is not True
        or observed_release.get("collectorIsolation") is not True
    ):
        raise InsightsE2EError("playwright_release_binding_mismatch")
    dashboard = result.get("dashboard")
    if not isinstance(dashboard, dict) or not dashboard or not all(
        value is True for value in dashboard.values()
    ):
        raise InsightsE2EError("playwright_dashboard_contract_failed")
    insights = result.get("insights")
    if not isinstance(insights, dict) or not insights or not all(value is True for value in insights.values()):
        raise InsightsE2EError("playwright_insights_contract_failed")
    reports = result.get("reports")
    if (
        not isinstance(reports, list)
        or len(reports) != 3
        or {row.get("period") for row in reports if isinstance(row, dict)}
        != {"日报", "周报", "月报"}
        or any(
            not isinstance(row, dict)
            or row.get("collection") != "最新完整周期"
            or row.get("legacyTermsAbsent") is not True
            for row in reports
        )
    ):
        raise InsightsE2EError("playwright_reports_contract_failed")
    cases = result.get("cases")
    if (
        not isinstance(cases, dict)
        or cases.get("threeViews") is not True
        or cases.get("referenceDefaultEligible") != 33
        or cases.get("reviewOnly") != 17
        or cases.get("operationsDossiers") != 1
        or cases.get("internalFiveStageDrawer") is not True
    ):
        raise InsightsE2EError("playwright_cases_contract_failed")
    if result.get("casebook") != release["casebook"]:
        raise InsightsE2EError("playwright_casebook_binding_mismatch")


def run_browser_callback(
    *,
    base_url: str,
    script_path: Path,
    release_sha256: str,
    runner: Runner,
    prefix: Sequence[str],
    env: Mapping[str, str],
) -> tuple[dict[str, Any], str]:
    version = verify_runner_version(runner, prefix, env)
    session = f"reddit-voc-{release_sha256[:12]}-{os.getpid()}"
    opened = False
    failure: BaseException | None = None
    result: dict[str, Any] | None = None
    try:
        _checked_run(
            runner,
            [*prefix, f"-s={session}", "open", base_url],
            env,
            label="playwright_open",
            timeout=60,
        )
        opened = True
        completed = _checked_run(
            runner,
            [*prefix, "--raw", f"-s={session}", "run-code", f"--filename={script_path}"],
            env,
            label="playwright_run_code",
            timeout=300,
        )
        result = _parse_runner_result(completed.stdout)
    except BaseException as exc:  # cleanup must run for validation and runtime failures
        failure = exc
    finally:
        if opened:
            try:
                _checked_run(
                    runner,
                    [*prefix, f"-s={session}", "close"],
                    env,
                    label="playwright_close",
                    timeout=30,
                )
            except BaseException as close_exc:
                if failure is None:
                    failure = close_exc
    if failure is not None:
        raise failure
    if result is None:
        raise InsightsE2EError("playwright_result_missing")
    return result, version


def write_immutable(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    payload = canonical_bytes(value)
    digest = sha256(payload).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe_directory(path.parent, label="receipt_parent")
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        regular_file(path, label="receipt", mode=0o600)
        if path.read_bytes() == payload:
            return "no_change", digest
        raise InsightsE2EError("receipt_collision")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".receipt.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return "created", digest


def execute_e2e(
    *,
    dist_root: Path,
    release_manifest_path: Path,
    expected_release_manifest_sha256: str,
    expected_release_sha256: str,
    expected_release_id: str,
    e2e_script_path: Path,
    expected_e2e_script_sha256: str,
    output_receipt_path: Path,
    runner_executable: str | None = None,
    runner: Runner = default_runner,
) -> tuple[str, str, dict[str, Any]]:
    release = validate_release(
        dist_root=dist_root,
        release_manifest_path=release_manifest_path,
        expected_manifest_sha256=expected_release_manifest_sha256,
        expected_release_sha256=expected_release_sha256,
        expected_release_id=expected_release_id,
    )
    script_sha = require_sha(expected_e2e_script_sha256, label="e2e_script")
    regular_file(e2e_script_path, label="e2e_script")
    if file_sha256(e2e_script_path) != script_sha:
        raise InsightsE2EError("e2e_script_sha256_mismatch")
    prefix = runner_prefix(runner_executable)
    with tempfile.TemporaryDirectory(prefix="reddit-voc-e2e-") as temporary:
        env = dict(os.environ)
        env.update(
            {
                "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
                "PWTEST_CLI_GLOBAL_CONFIG": temporary,
            }
        )
        with serve_dist(
            dist_root, release["dist_inventory"], release["release_sha256"]
        ) as base_url:
            callback, runner_version = run_browser_callback(
                base_url=base_url,
                script_path=e2e_script_path,
                release_sha256=release["release_sha256"],
                runner=runner,
                prefix=prefix,
                env=env,
            )
    validate_callback_result(callback, release)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed_local_same_dist_browser_acceptance",
        "evidence_grade": "L2_local_same_dist_browser_acceptance",
        "release": {
            "release_id": release["release_id"],
            "release_sha256": release["release_sha256"],
            "release_manifest_sha256": release["manifest_sha256"],
            "dist_inventory_sha256": release["dist_inventory_sha256"],
            "dist_file_count": len(release["dist_inventory"]),
            "current_release_pointer_sha256": release["pointer_sha256"],
            "dataset_versions": release["dataset_versions"],
            "public_casebook": release["casebook"],
        },
        "runner": {
            "name": "playwright-cli",
            "version": runner_version,
            "command_contract": list(DEFAULT_RUNNER),
            "headless": True,
            "browser_download_allowed": False,
            "origin_class": "ephemeral_loopback",
        },
        "script": {"sha256": script_sha, "role": "frozen_page_callback"},
        "route_matrix": {
            "route_count": len(ROUTES),
            "viewports": list(VIEWPORTS),
            "evaluated_pages": len(ROUTES) * len(VIEWPORTS),
            "routes": list(ROUTES),
        },
        "checks": {
            "all_routes_http_200_and_final_path_exact": True,
            "desktop_and_mobile_no_horizontal_overflow": True,
            "no_login_or_password_controls": True,
            "release_pointer_and_seven_datasets_exact": True,
            "dashboard_ranges_circular_radar_quarter_insights_and_three_reports_exact": True,
            "case_three_views_casebook_and_collector_link_exact": True,
            "browser_console_network_and_external_requests_clean": True,
        },
        "boundaries": {
            "production_unchanged": True,
            "deploy": False,
            "remote_write": False,
            "schedule_change": False,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
            "container_runtime_evaluated": False,
            "production_evaluated": False,
        },
    }
    state, digest = write_immutable(output_receipt_path, receipt)
    return state, digest, receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-root", required=True)
    parser.add_argument("--release-manifest", required=True)
    parser.add_argument("--expected-release-manifest-sha256", required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--e2e-script", required=True)
    parser.add_argument("--expected-e2e-script-sha256", required=True)
    parser.add_argument("--output-receipt", required=True)
    parser.add_argument("--runner-executable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        state, digest, _ = execute_e2e(
            dist_root=Path(args.dist_root),
            release_manifest_path=Path(args.release_manifest),
            expected_release_manifest_sha256=args.expected_release_manifest_sha256,
            expected_release_sha256=args.expected_release_sha256,
            expected_release_id=args.expected_release_id,
            e2e_script_path=Path(args.e2e_script),
            expected_e2e_script_sha256=args.expected_e2e_script_sha256,
            output_receipt_path=Path(args.output_receipt),
            runner_executable=args.runner_executable,
        )
    except InsightsE2EError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"status": state, "receipt_sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
