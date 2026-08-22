#!/usr/bin/env python3
"""Seal local Reddit VOC container security evidence into one receipt.

This builder is local-only. It validates already-produced immutable release,
container-smoke, and export evidence and never starts containers or contacts a
remote host.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


SCHEMA_VERSION = "reddit_voc_insights_security_validation_receipt_v1"
SAFE_BOUNDARIES = {
    "collector_restart": False,
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
    "schedule_change": False,
    "webhook_send": False,
}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class SecurityReceiptError(ValueError):
    """The supplied evidence does not satisfy the security contract."""


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _regular_bytes(path: Path, *, label: str) -> bytes:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise SecurityReceiptError(f"{label}_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SecurityReceiptError(f"{label}_unsafe")
    return path.read_bytes()


def _load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _regular_bytes(path, label=label)
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SecurityReceiptError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise SecurityReceiptError(f"{label}_not_object")
    return value, payload


def _safe_boundaries(value: object, *, label: str) -> None:
    if not isinstance(value, dict):
        raise SecurityReceiptError(f"{label}_boundaries_invalid")
    for key in ("database_write", "deploy", "live_send", "provider_call", "remote_write"):
        if value.get(key) is not False:
            raise SecurityReceiptError(f"{label}_boundary_{key}_invalid")
    if value.get("production_unchanged") is not True:
        raise SecurityReceiptError(f"{label}_boundary_production_unchanged_invalid")


def _artifact(path: Path, payload: bytes, *, project_root: Path) -> dict[str, object]:
    resolved = path.resolve()
    try:
        display_path = resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        display_path = str(resolved)
    return {
        "bytes": len(payload),
        "path": display_path,
        "sha256": sha256(payload).hexdigest(),
    }


def _sha256(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _require_artifact_contract(
    value: object, *, payload: bytes, label: str
) -> None:
    if not isinstance(value, dict):
        raise SecurityReceiptError(f"{label}_contract_invalid")
    if value.get("bytes") != len(payload) or value.get("sha256") != _sha256(payload):
        raise SecurityReceiptError(f"{label}_contract_mismatch")


def _parse_sha256sums(payload: bytes) -> dict[str, str]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise SecurityReceiptError("release_sums_invalid") from exc
    rows: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        if len(parts) != 2 or SHA_RE.fullmatch(parts[0]) is None or not parts[1]:
            raise SecurityReceiptError("release_sums_invalid")
        if parts[1] in rows:
            raise SecurityReceiptError("release_sums_duplicate")
        rows[parts[1]] = parts[0]
    return rows


def _export_scope_for_url(value: object) -> str:
    if not isinstance(value, str):
        raise SecurityReceiptError("export_site_url_invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise SecurityReceiptError("export_site_url_invalid")
    if parsed.hostname in {"127.0.0.1", "localhost"}:
        return "local_loopback"
    if parsed.scheme != "https":
        raise SecurityReceiptError("export_site_url_https_required")
    return "public_https"


def _compose_volume_items(compose: str) -> list[str]:
    """Return service-level volume entries from the reviewed compose shape."""
    match = re.search(
        r"(?ms)^    volumes:\s*\n(?P<body>(?:      .*?(?:\n|$))+)",
        compose,
    )
    if match is None:
        return []
    return [
        value.strip().strip('"').strip("'")
        for value in re.findall(r"(?m)^      -\s+(.+?)\s*$", match.group("body"))
    ]


def _write_immutable(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    payload = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SecurityReceiptError("output_unsafe")
        if path.read_bytes() != payload:
            raise SecurityReceiptError("output_immutable_collision")
        return "no_change", sha256(payload).hexdigest()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)
    return "created", sha256(payload).hexdigest()


def build_security_receipt(
    *,
    project_root: Path,
    release_dir: Path,
    container_smoke_path: Path,
    export_receipt_path: Path,
    output_path: Path,
    generated_at_utc: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    release_manifest_path = release_dir / "release-manifest.json"
    compose_path = release_dir / "compose.yaml"
    dist_sums_path = release_dir / "dist-SHA256SUMS"
    release_sums_path = release_dir / "SHA256SUMS"
    release, release_payload = _load_json(release_manifest_path, label="release_manifest")
    smoke, smoke_payload = _load_json(container_smoke_path, label="container_smoke")
    export, export_payload = _load_json(export_receipt_path, label="export_receipt")
    compose_payload = _regular_bytes(compose_path, label="compose")
    dist_sums_payload = _regular_bytes(dist_sums_path, label="dist_sums")
    release_sums_payload = _regular_bytes(release_sums_path, label="release_sums")

    release_sha = release.get("release_sha256")
    if (
        release.get("schema_version") != "reddit_voc_insights_site_release_v2"
        or not isinstance(release_sha, str)
        or SHA_RE.fullmatch(release_sha) is None
        or release.get("target_platform") != "linux/amd64"
        or release.get("authentication_enabled") is not False
        or release.get("public_access") is not True
        or not isinstance(release.get("nginx_base_image"), str)
        or "@sha256:" not in str(release.get("nginx_base_image"))
    ):
        raise SecurityReceiptError("release_contract_invalid")
    image_tar_path = release_dir / f"reddit-voc-insights-{release_sha}.tar"
    image_tar_payload = _regular_bytes(image_tar_path, label="image_tar")

    deployment_inputs = release.get("deployment_inputs")
    compose_contract = next(
        (
            row
            for row in deployment_inputs
            if isinstance(row, dict) and row.get("path") == "deploy/insights/compose.yaml"
        ),
        None,
    ) if isinstance(deployment_inputs, list) else None
    _require_artifact_contract(compose_contract, payload=compose_payload, label="compose")

    expected_release_sums = {
        "compose.yaml": _sha256(compose_payload),
        "dist-SHA256SUMS": _sha256(dist_sums_payload),
        "release-manifest.json": _sha256(release_payload),
        image_tar_path.name: _sha256(image_tar_payload),
    }
    if _parse_sha256sums(release_sums_payload) != expected_release_sums:
        raise SecurityReceiptError("release_sums_contract_mismatch")

    smoke_schema = smoke.get("schema_version")
    if (
        smoke_schema not in {
            "reddit_voc_local_insights_container_smoke_receipt_v1",
            "reddit_voc_local_insights_container_smoke_receipt_v2",
        }
        or smoke.get("status") != "passed_local_isolated_container_smoke"
        or smoke.get("release", {}).get("release_sha256") != release_sha
        or smoke.get("release", {}).get("release_manifest_sha256") != _sha256(release_payload)
        or smoke.get("release", {}).get("target_platform") != release.get("target_platform")
    ):
        raise SecurityReceiptError("container_smoke_contract_invalid")
    _require_artifact_contract(
        smoke.get("release", {}).get("dist_sha256sums"),
        payload=dist_sums_payload,
        label="container_smoke_dist_sums",
    )
    _require_artifact_contract(
        smoke.get("release", {}).get("image_tar"),
        payload=image_tar_payload,
        label="container_smoke_image_tar",
    )
    _safe_boundaries(smoke.get("boundaries"), label="container_smoke")
    runtime = smoke.get("runtime_checks")
    runtime_keys = {
        "cap_drop_all",
        "container_loopback_http",
        "healthy",
        "host_port_published",
        "isolated_internal_network",
        "no_new_privileges",
        "read_only_rootfs",
        "uid_gid_101",
    }
    if smoke_schema == "reddit_voc_local_insights_container_smoke_receipt_v1":
        runtime_keys.add("zero_mounts")
    else:
        runtime_keys.update(
            {
                "one_read_only_data_mount",
                "exact_data_mount_contract",
                "data_pointer_health",
            }
        )
    if not isinstance(runtime, dict) or any(runtime.get(key) is not True for key in runtime_keys - {"host_port_published"}) or runtime.get("host_port_published") is not False:
        raise SecurityReceiptError("container_runtime_security_invalid")

    export_scope = export.get("site_scope")
    expected_export_status = {
        "local_loopback": "passed_local_readonly_export_acceptance",
        "public_https": "passed_public_readonly_export_acceptance",
    }.get(export_scope)
    required_export_checks = {
        "csv_content_verified",
        "docx_structure_and_content_verified",
        "pdf_structure_verified",
        "pptx_structure_and_content_verified",
        "release_and_report_binding_verified",
    }
    export_checks = export.get("checks")
    if (
        export.get("schema_version") != "reddit_voc_insights_export_validation_receipt_v1"
        or expected_export_status is None
        or export.get("status") != expected_export_status
        or export.get("release", {}).get("release_sha256") != release_sha
        or not isinstance(export_checks, dict)
        or export_checks.get("download_count") != 4
        or any(export_checks.get(key) is not True for key in required_export_checks)
    ):
        raise SecurityReceiptError("export_contract_invalid")
    _safe_boundaries(export.get("boundaries"), label="export_receipt")
    export_grade = export.get("evidence_grade")
    export_contracts = {
        "local_loopback": "L2_local_container_readonly_browser_download_acceptance",
        "public_https": "L3_public_readonly_browser_download_acceptance",
    }
    if (
        export_scope != _export_scope_for_url(export.get("site_url"))
        or export_contracts.get(export_scope) != export_grade
    ):
        raise SecurityReceiptError("export_evidence_grade_invalid")

    compose = compose_payload.decode("utf-8")
    volume_items = _compose_volume_items(compose)
    expected_data_mount = (
        "${REDDIT_VOC_DATA_ROOT:?REDDIT_VOC_DATA_ROOT must be set}"
        ":/srv/reddit-voc-data:ro"
    )
    compose_checks = {
        "compose_cap_drop_all": bool(re.search(r"(?m)^\s*cap_drop:\s*$[\s\S]*?^\s*-\s*ALL\s*$", compose)),
        "compose_no_new_privileges": "no-new-privileges:true" in compose,
        "compose_read_only_rootfs": bool(re.search(r"(?m)^\s*read_only:\s*true\s*$", compose)),
    }
    if smoke_schema == "reddit_voc_local_insights_container_smoke_receipt_v1":
        compose_checks["compose_no_host_mounts_declared"] = not bool(
            re.search(r"(?m)^\s*volumes:\s*$", compose)
        )
    else:
        compose_checks["compose_exact_read_only_data_mount_declared"] = (
            volume_items == [expected_data_mount]
        )
    if not all(compose_checks.values()):
        raise SecurityReceiptError("compose_security_contract_invalid")

    generated = generated_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    artifacts = {
        "compose": _artifact(compose_path, compose_payload, project_root=project_root),
        "container_smoke": _artifact(container_smoke_path, smoke_payload, project_root=project_root),
        "dist_sums": _artifact(dist_sums_path, dist_sums_payload, project_root=project_root),
        "export": _artifact(export_receipt_path, export_payload, project_root=project_root),
        "image_tar": _artifact(image_tar_path, image_tar_payload, project_root=project_root),
        "release_manifest": _artifact(release_manifest_path, release_payload, project_root=project_root),
        "release_sums": _artifact(release_sums_path, release_sums_payload, project_root=project_root),
    }
    receipt = {
        "artifacts": artifacts,
        "boundaries": dict(SAFE_BOUNDARIES),
        "checks": {
            "authentication_disabled_by_contract": True,
            "base_image_digest_pinned": True,
            "compose_bound_to_release_manifest": True,
            **compose_checks,
            "container_smoke_passed": True,
            "export_validation_passed": True,
            "no_provider_or_database_side_effects": True,
            "public_access_enabled_by_contract": True,
            "release_identity_verified": True,
            "release_sha256sums_verified": True,
            "smoke_artifacts_bound_to_release": True,
            "target_platform_linux_amd64": True,
        },
        "evidence_grade": (
            "L2_local_container_security_and_export_acceptance"
            if export_scope == "local_loopback"
            else "L2_local_container_security_contract_with_L3_export_acceptance"
        ),
        "generated_at_utc": generated,
        "release_sha256": release_sha,
        "schema_version": SCHEMA_VERSION,
        "stable_evidence": {
            "compose_sha256": artifacts["compose"]["sha256"],
            "container_smoke_receipt_sha256": artifacts["container_smoke"]["sha256"],
            "export_receipt_sha256": artifacts["export"]["sha256"],
            "release_manifest_sha256": artifacts["release_manifest"]["sha256"],
        },
        "status": "passed",
    }
    state, digest = _write_immutable(output_path, receipt)
    return state, digest, receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--container-smoke", type=Path, required=True)
    parser.add_argument("--export-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-at-utc")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        state, digest, _ = build_security_receipt(
            project_root=args.project_root,
            release_dir=args.release_dir,
            container_smoke_path=args.container_smoke,
            export_receipt_path=args.export_receipt,
            output_path=args.output,
            generated_at_utc=args.generated_at_utc,
        )
    except (OSError, SecurityReceiptError) as exc:
        print(f"status=failed reason={exc}", file=__import__("sys").stderr)
        return 1
    print(f"status={state}")
    print(f"receipt_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
