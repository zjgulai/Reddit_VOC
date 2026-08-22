from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def _boundary_lines(*, passed: bool, reason: str | None = None) -> str:
    lines = [f"runtime_smoke={'passed' if passed else 'blocked'}"]
    if reason is not None:
        lines.append(f"reason={reason}")
    lines.extend(
        [
            "translation_provider_call=false",
            "translation_provider_attempt_made=false",
            "report_live_send=false",
            "live_send=false",
            "database_write=local-test-only",
        ]
    )
    return "\n".join(lines)


def _reason(error: BaseException) -> str:
    candidate = getattr(error, "reason_code", None)
    if isinstance(candidate, str) and candidate.replace("_", "").isalnum():
        return candidate
    message = str(error)
    if message and message.replace("_", "").isalnum():
        return message
    return "runtime_smoke_failed"


def _assert_neutral_imports() -> None:
    project_pythonpath = os.environ.get("PYTHONPATH", "")
    checks = [
        (
            "reddit_voc.prepared_bundle",
            [
                "reddit_voc.prepared_report",
                "reddit_voc.deepseek_client",
                "reddit_voc.translation_pipeline",
                "reddit_voc.daily_report",
            ],
        ),
        (
            "reddit_voc.daily_report_delivery",
            [
                "reddit_voc.prepared_report",
                "reddit_voc.deepseek_client",
                "reddit_voc.translation_pipeline",
                "reddit_voc.daily_report",
            ],
        ),
    ]
    for module, forbidden in checks:
        code = (
            "import importlib,sys;"
            f"importlib.import_module({module!r});"
            f"forbidden={forbidden!r};"
            "assert not [name for name in forbidden if name in sys.modules]"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            env={
                "PYTHONPATH": project_pythonpath,
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("runtime_import_isolation_failed")


def _mkdir700(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)


def run_smoke(*, config_root: Path, work_root: Path) -> None:
    from reddit_voc.prepared_bundle import (
        PreparedReportRoots,
        commit_staged_prepared_report,
        freeze_dingtalk_outbox,
        load_verified_prepared_report,
        outbox_sha256,
        write_bundle_index,
    )
    from reddit_voc.report_contracts import (
        canonical_json_bytes,
        load_report_schema_assets,
        read_regular_utf8,
        sha256_hex,
        validate_schema_instance,
    )

    config_root = config_root.resolve(strict=True)
    schema_assets = load_report_schema_assets(config_root=config_root)
    translation_prompt = read_regular_utf8(
        trusted_root=config_root,
        path=config_root / "prompts" / "deepseek-translation-v1.txt",
    ).encode("utf-8")
    validator_prompt = read_regular_utf8(
        trusted_root=config_root,
        path=config_root / "prompts" / "deepseek-semantic-validator-v1.txt",
    ).encode("utf-8")
    _assert_neutral_imports()
    if work_root.exists() or work_root.is_symlink():
        raise RuntimeError("runtime_work_root_exists")
    _mkdir700(work_root)
    database = work_root / "fixture.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE smoke(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO smoke(value) VALUES('local-test-only')")
    roots_by_name = {
        "public_root": work_root / "public",
        "private_root": work_root / "private",
        "public_staging_root": work_root / "public-staging",
        "private_staging_root": work_root / "private-staging",
        "state_root": work_root / "state",
        "blocked_root": work_root / "blocked",
        "handoff_root": work_root / "handoff",
    }
    for path in roots_by_name.values():
        _mkdir700(path)
    roots = PreparedReportRoots(**roots_by_name)
    run_id = "runtime_smoke_20260713"
    attempt_id = "runtime-smoke-attempt"
    action_id = "runtime-smoke-action"
    version = "20260713T000000000000Z-" + "a" * 32
    empty_digest = sha256_hex(canonical_json_bytes([]))
    report_fingerprint = sha256_hex(
        canonical_json_bytes(
            {
                "runtime_smoke": True,
                "translation_provider_call": False,
                "live_send": False,
            }
        )
    )
    manifest_id = f"{run_id}.{empty_digest}.{empty_digest}.{empty_digest}"
    manifest = {
        "schema_version": "daily-translation-manifest-v1",
        "manifest_id": manifest_id,
        "run_id": run_id,
        "provider": "deepseek",
        "requested_model": "deepseek-v4-flash",
        "prompt_version": sha256_hex(translation_prompt),
        "validator_prompt_version": sha256_hex(validator_prompt),
        "translation_cache_key": sha256_hex(b"runtime-smoke-translation-cache"),
        "validator_cache_key": sha256_hex(b"runtime-smoke-validator-cache"),
        "translation_output_sha256": empty_digest,
        "validator_output_sha256": empty_digest,
        "translation_input_fingerprint": empty_digest,
        "report_input_fingerprint": report_fingerprint,
        "status": "complete",
        "provider_call": False,
        "translation_provider_call": False,
        "translation_provider_attempt_made": False,
        "translation_phase_attempt_made": False,
        "semantic_validation_phase_attempt_made": False,
        "translation_reused": False,
        "semantic_validation_reused": False,
        "request_count": 0,
        "retry_count": 0,
        "duration_ms": 0,
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
            "total_tokens": 0,
        },
        "responses": [],
        "counts": {"posts": 0, "titles": 0, "bodies": 0, "comments": 0, "items": 0},
        "items": [],
        "provider_authorization_id": None,
    }
    validate_schema_instance(schema=schema_assets.manifest_schema, value=manifest)
    manifest_bytes = canonical_json_bytes(manifest)
    _write_new(roots.private_staging_root / "translation-manifest.json", manifest_bytes)
    public_names = [
        f"{run_id}-insight-report.html",
        f"{run_id}-daily-detail.xlsx",
        f"{run_id}-daily-detail.csv",
        f"{run_id}-insight-report-screenshot.png",
    ]
    for name in public_names:
        _write_new(roots.public_staging_root / name, f"runtime-smoke:{name}".encode("utf-8"), mode=0o644)
    artifact_url = f"https://runtime-smoke.invalid/artifacts/prepared/{run_id}/{version}"
    body = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"LL Reddit VOC runtime smoke {run_id}",
            "text": f"# Provider-free runtime smoke\n{artifact_url}",
        },
    }
    parts = freeze_dingtalk_outbox(
        rendered=SimpleNamespace(dingtalk_bodies=(body,)),
        private_staging_dir=roots.private_staging_root,
        dingtalk_required_keyword="LL",
    )
    outbox_digest = outbox_sha256(parts)
    public_urls = [f"{artifact_url}/{name}" for name in public_names]
    validation = {
        "schema_version": "prepared-validation-v2",
        "run_id": run_id,
        "artifact_version_id": version,
        "report_input_fingerprint": report_fingerprint,
        "translation_output_sha256": empty_digest,
        "validator_output_sha256": empty_digest,
        "outbox_sha256": outbox_digest,
        "public_artifact_urls": public_urls,
        "source_state": {
            "schema_version": "daily-report-source-state-v1",
            "status": "empty",
            "mode": "empty_success",
            "post_count": 0,
            "comment_count": 0,
            "business_report_allowed": True,
            "failure_alert_allowed": False,
        },
    }
    _write_new(
        roots.private_staging_root / "validation-report.json",
        canonical_json_bytes(validation),
    )
    _, bundle_digest = write_bundle_index(
        public_staging_dir=roots.public_staging_root,
        private_staging_dir=roots.private_staging_root,
        artifact_version_id=version,
        schema_assets=schema_assets,
    )
    final_public = roots.public_root / "prepared" / run_id / version
    final_private = roots.private_root / "prepared" / run_id / version
    projections = {
        name: f"prepared/{run_id}/{version}/{name}" for name in public_names
    }
    request = {
        "schema_version": "prepared-commit-request-v1",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "artifact_version_id": version,
        "bundle_sha256": bundle_digest,
        "outbox_sha256": outbox_digest,
        "report_input_fingerprint": report_fingerprint,
        "manifest_sha256": sha256_hex(manifest_bytes),
        "provider_authorization_id": None,
        "prepare_action_authorization_id": action_id,
        "staged_public_dir": str(roots.public_staging_root),
        "staged_private_dir": str(roots.private_staging_root),
        "final_public_dir": str(final_public),
        "final_private_dir": str(final_private),
        "projections": projections,
    }
    request_root = roots.handoff_root / run_id / attempt_id
    _mkdir700(request_root)
    request_bytes = canonical_json_bytes(request)
    _write_new(request_root / "commit-request.json", request_bytes)
    result = commit_staged_prepared_report(
        roots=roots,
        expected_run_id=run_id,
        expected_artifact_version_id=version,
        expected_bundle_sha256=bundle_digest,
        expected_outbox_sha256=outbox_digest,
        expected_commit_request_sha256=sha256_hex(request_bytes),
        expected_provider_authorization_id=None,
        expected_prepare_action_authorization_id=action_id,
        expected_attempt_id=attempt_id,
        schema_assets=schema_assets,
    )
    verified = load_verified_prepared_report(
        roots=roots,
        expected_run_id=result.run_id,
        expected_artifact_version_id=result.artifact_version_id,
        expected_bundle_sha256=result.bundle_sha256,
        expected_outbox_sha256=result.outbox_sha256,
        schema_assets=schema_assets,
    )
    if verified.translation_status != "complete" or not verified.parts:
        raise RuntimeError("runtime_smoke_verification_failed")


def _write_new(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, mode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    work_root = args.work_root.absolute()
    try:
        run_smoke(config_root=args.config_root, work_root=work_root)
    except Exception as exc:
        print(_boundary_lines(passed=False, reason=_reason(exc)))
        return 1
    finally:
        if work_root.exists() and not work_root.is_symlink():
            shutil.rmtree(work_root)
    print(_boundary_lines(passed=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
