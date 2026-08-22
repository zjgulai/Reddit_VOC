from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .report_contracts import (
    ReportSchemaAssets,
    canonical_json_bytes,
    load_regular_json,
    sha256_hex,
    validate_schema_instance,
)
from .report_source_state import validate_frozen_report_source_state


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VERSION_ID = re.compile(r"^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}$")
_ZERO_USAGE = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 0,
    "total_tokens": 0,
}


@dataclass(frozen=True)
class PreparedReportRoots:
    public_root: Path
    private_root: Path
    public_staging_root: Path
    private_staging_root: Path
    state_root: Path
    blocked_root: Path
    handoff_root: Path


@dataclass(frozen=True)
class PreparedReportResult:
    run_id: str
    attempt_id: str
    artifact_version_id: str
    bundle_sha256: str
    report_input_fingerprint: str
    outbox_sha256: str
    provider_authorization_id: str | None
    prepare_action_authorization_id: str
    public_dir: Path
    private_dir: Path


@dataclass(frozen=True)
class StagedPreparedReport:
    run_id: str
    attempt_id: str
    artifact_version_id: str
    bundle_sha256: str
    report_input_fingerprint: str
    outbox_sha256: str
    provider_authorization_id: str | None
    prepare_action_authorization_id: str
    staged_public_dir: Path
    staged_private_dir: Path
    final_public_dir: Path
    final_private_dir: Path
    commit_request_path: Path
    commit_request_sha256: str


@dataclass(frozen=True)
class PreparedOutboxPart:
    index: int
    total: int
    path: Path
    body_bytes: bytes
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class VerifiedPreparedReport:
    run_id: str
    artifact_version_id: str
    bundle_sha256: str
    report_input_fingerprint: str
    translation_input_fingerprint: str
    translation_output_sha256: str
    validator_output_sha256: str
    translation_status: str
    outbox_sha256: str
    parts: tuple[PreparedOutboxPart, ...]
    public_artifact_urls: tuple[str, ...]
    source_state: Mapping[str, object]


def generate_artifact_version_id(
    *,
    now_utc: datetime,
    random_hex: Callable[[int], str] = secrets.token_hex,
) -> str:
    if now_utc.tzinfo is None:
        raise ValueError("artifact_version_time_not_aware")
    timestamp = now_utc.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    entropy = random_hex(16)
    value = f"{timestamp}-{entropy}"
    if _VERSION_ID.fullmatch(value) is None:
        raise ValueError("artifact_version_id_invalid")
    return value


def freeze_dingtalk_outbox(
    *,
    rendered: object,
    private_staging_dir: Path,
    dingtalk_required_keyword: str,
) -> tuple[PreparedOutboxPart, ...]:
    bodies = getattr(rendered, "dingtalk_bodies", None)
    if not isinstance(bodies, tuple) or not 1 <= len(bodies) <= 2:
        raise RuntimeError("dingtalk_outbox_part_count_invalid")
    if not isinstance(dingtalk_required_keyword, str) or not dingtalk_required_keyword:
        raise ValueError("dingtalk_required_keyword_invalid")
    outbox_dir = private_staging_dir / "outbox"
    _make_new_directory(outbox_dir, mode=0o700)
    parts: list[PreparedOutboxPart] = []
    total = len(bodies)
    for index, body in enumerate(bodies, start=1):
        if not isinstance(body, Mapping) or set(body) != {"msgtype", "markdown"}:
            raise RuntimeError("dingtalk_body_shape_invalid")
        markdown = body.get("markdown")
        if body.get("msgtype") != "markdown" or not isinstance(markdown, Mapping):
            raise RuntimeError("dingtalk_body_shape_invalid")
        if set(markdown) != {"title", "text"}:
            raise RuntimeError("dingtalk_body_shape_invalid")
        title = markdown.get("title")
        text = markdown.get("text")
        if not isinstance(title, str) or not isinstance(text, str):
            raise RuntimeError("dingtalk_body_shape_invalid")
        if dingtalk_required_keyword not in title and dingtalk_required_keyword not in text:
            raise RuntimeError("dingtalk_required_keyword_missing")
        payload = canonical_json_bytes(body)
        path = outbox_dir / f"part-{index:04d}.json"
        _write_new_file(path, payload, mode=0o600)
        parts.append(
            PreparedOutboxPart(
                index=index,
                total=total,
                path=path,
                body_bytes=payload,
                sha256=sha256_hex(payload),
                byte_count=len(payload),
            )
        )
    _fsync_directory(outbox_dir)
    return tuple(parts)


def outbox_sha256(parts: Sequence[PreparedOutboxPart]) -> str:
    records = [
        {"index": part.index, "sha256": part.sha256, "byte_count": part.byte_count}
        for part in parts
    ]
    if [record["index"] for record in records] != list(range(1, len(records) + 1)):
        raise ValueError("outbox_parts_not_ordered")
    return sha256_hex(canonical_json_bytes(records))


def write_bundle_index(
    *,
    public_staging_dir: Path,
    private_staging_dir: Path,
    artifact_version_id: str,
    schema_assets: ReportSchemaAssets,
) -> tuple[Mapping[str, object], str]:
    _require_version_id(artifact_version_id)
    entries: list[dict[str, object]] = []
    for scope, root in (("private", private_staging_dir), ("public", public_staging_dir)):
        for path in _regular_tree_files(root):
            relative_path = path.relative_to(root).as_posix()
            if scope == "private" and relative_path == "bundle-index.json":
                continue
            payload = _read_regular_bytes(path, trusted_root=root)
            if b'"bundle_sha256"' in payload:
                raise RuntimeError("bundle_payload_embeds_bundle_sha256")
            entries.append(
                {
                    "scope": scope,
                    "relative_path": relative_path,
                    "byte_size": len(payload),
                    "sha256": sha256_hex(payload),
                }
            )
    entries.sort(key=lambda item: (str(item["scope"]), str(item["relative_path"])))
    index: Mapping[str, object] = {
        "schema_version": "daily-prepared-bundle-index-v1",
        "artifact_version_id": artifact_version_id,
        "entries": entries,
    }
    validate_schema_instance(schema=schema_assets.bundle_index_schema, value=index)
    payload = canonical_json_bytes(index)
    _write_new_file(private_staging_dir / "bundle-index.json", payload, mode=0o600)
    _fsync_directory(private_staging_dir)
    return index, sha256_hex(payload)


def commit_staged_prepared_report(
    *,
    roots: PreparedReportRoots,
    expected_run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    expected_commit_request_sha256: str,
    expected_provider_authorization_id: str | None,
    expected_prepare_action_authorization_id: str,
    expected_attempt_id: str,
    schema_assets: ReportSchemaAssets,
) -> PreparedReportResult:
    _require_safe_id(expected_run_id, "run_id")
    _require_safe_id(expected_attempt_id, "attempt_id")
    _require_safe_id(expected_prepare_action_authorization_id, "prepare_action_authorization_id")
    if expected_provider_authorization_id is not None:
        _require_safe_id(expected_provider_authorization_id, "provider_authorization_id")
    _require_version_id(expected_artifact_version_id)
    _require_sha(expected_bundle_sha256, "bundle_sha256")
    _require_sha(expected_outbox_sha256, "outbox_sha256")
    _require_sha(expected_commit_request_sha256, "commit_request_sha256")

    request_path = (
        roots.handoff_root
        / expected_run_id
        / expected_attempt_id
        / "commit-request.json"
    )
    request_bytes = _read_regular_bytes(request_path, trusted_root=roots.handoff_root)
    if sha256_hex(request_bytes) != expected_commit_request_sha256:
        raise RuntimeError("commit_request_mismatch")
    request = _decode_json_object(request_bytes, "commit_request_invalid")
    expected_keys = {
        "schema_version",
        "run_id",
        "attempt_id",
        "artifact_version_id",
        "bundle_sha256",
        "outbox_sha256",
        "report_input_fingerprint",
        "manifest_sha256",
        "provider_authorization_id",
        "prepare_action_authorization_id",
        "staged_public_dir",
        "staged_private_dir",
        "final_public_dir",
        "final_private_dir",
        "projections",
    }
    if set(request) != expected_keys or request.get("schema_version") != "prepared-commit-request-v1":
        raise RuntimeError("commit_request_invalid")
    comparisons = {
        "run_id": expected_run_id,
        "attempt_id": expected_attempt_id,
        "artifact_version_id": expected_artifact_version_id,
        "bundle_sha256": expected_bundle_sha256,
        "outbox_sha256": expected_outbox_sha256,
        "provider_authorization_id": expected_provider_authorization_id,
        "prepare_action_authorization_id": expected_prepare_action_authorization_id,
        "staged_public_dir": str(roots.public_staging_root),
        "staged_private_dir": str(roots.private_staging_root),
        "final_public_dir": str(
            roots.public_root / "prepared" / expected_run_id / expected_artifact_version_id
        ),
        "final_private_dir": str(
            roots.private_root / "prepared" / expected_run_id / expected_artifact_version_id
        ),
    }
    if any(request.get(key) != value for key, value in comparisons.items()):
        raise RuntimeError("commit_request_mismatch")
    report_fingerprint = request.get("report_input_fingerprint")
    manifest_sha256 = request.get("manifest_sha256")
    _require_sha(report_fingerprint, "report_input_fingerprint")
    _require_sha(manifest_sha256, "manifest_sha256")

    _require_exact_staging_directory(roots.public_staging_root)
    _require_exact_staging_directory(roots.private_staging_root)
    verified_index = _verify_bundle_tree(
        public_dir=roots.public_staging_root,
        private_dir=roots.private_staging_root,
        expected_artifact_version_id=expected_artifact_version_id,
        expected_bundle_sha256=expected_bundle_sha256,
        schema_assets=schema_assets,
    )
    manifest_bytes = _read_regular_bytes(
        roots.private_staging_root / "translation-manifest.json",
        trusted_root=roots.private_staging_root,
    )
    if sha256_hex(manifest_bytes) != manifest_sha256:
        raise RuntimeError("commit_request_mismatch")
    manifest = _decode_json_object(manifest_bytes, "translation_manifest_invalid")
    validate_schema_instance(schema=schema_assets.manifest_schema, value=manifest)
    if manifest.get("run_id") != expected_run_id:
        raise RuntimeError("translation_manifest_run_mismatch")
    if manifest.get("report_input_fingerprint") != report_fingerprint:
        raise RuntimeError("commit_request_mismatch")
    if manifest.get("provider_authorization_id") != expected_provider_authorization_id:
        raise RuntimeError("commit_request_mismatch")
    _verify_outbox_from_index(
        private_dir=roots.private_staging_root,
        index=verified_index,
        expected_outbox_sha256=expected_outbox_sha256,
    )

    final_public = roots.public_root / "prepared" / expected_run_id / expected_artifact_version_id
    final_private = roots.private_root / "prepared" / expected_run_id / expected_artifact_version_id
    _prepare_final_parent(roots.public_root, final_public.parent)
    _prepare_final_parent(roots.private_root, final_private.parent)
    if final_public.exists() or final_private.exists():
        raise RuntimeError("prepared_final_exists")
    if os.stat(roots.public_staging_root).st_dev != os.stat(final_public.parent).st_dev:
        raise RuntimeError("public_staging_cross_device")
    if os.stat(roots.private_staging_root).st_dev != os.stat(final_private.parent).st_dev:
        raise RuntimeError("private_staging_cross_device")

    os.rename(roots.public_staging_root, final_public)
    _fsync_directory(final_public.parent)
    os.rename(roots.private_staging_root, final_private)
    _fsync_directory(final_private.parent)

    current = {
        "schema_version": "prepared-current-v1",
        "run_id": expected_run_id,
        "artifact_version_id": expected_artifact_version_id,
        "bundle_sha256": expected_bundle_sha256,
        "report_input_fingerprint": report_fingerprint,
        "outbox_sha256": expected_outbox_sha256,
    }
    _ensure_mode_directory(roots.state_root, mode=0o700)
    _atomic_replace_file(
        roots.state_root / "prepared-current.json",
        canonical_json_bytes(current),
        mode=0o600,
    )
    _apply_projections(
        roots=roots,
        projections=request.get("projections"),
        final_public_dir=final_public,
    )
    _append_registry_entry(
        roots=roots,
        run_id=expected_run_id,
        artifact_version_id=expected_artifact_version_id,
        bundle_sha256=expected_bundle_sha256,
        manifest=manifest,
    )
    return PreparedReportResult(
        run_id=expected_run_id,
        attempt_id=expected_attempt_id,
        artifact_version_id=expected_artifact_version_id,
        bundle_sha256=expected_bundle_sha256,
        report_input_fingerprint=str(report_fingerprint),
        outbox_sha256=expected_outbox_sha256,
        provider_authorization_id=expected_provider_authorization_id,
        prepare_action_authorization_id=expected_prepare_action_authorization_id,
        public_dir=final_public,
        private_dir=final_private,
    )


def commit_staged_blocked_attempt(
    *,
    roots: PreparedReportRoots,
    expected_run_id: str,
    expected_attempt_id: str,
    expected_manifest_sha256: str,
    expected_provider_authorization_id: str | None,
    schema_assets: ReportSchemaAssets,
) -> Path:
    _require_safe_id(expected_run_id, "run_id")
    _require_safe_id(expected_attempt_id, "attempt_id")
    _require_sha(expected_manifest_sha256, "manifest_sha256")
    if expected_provider_authorization_id is not None:
        _require_safe_id(
            expected_provider_authorization_id, "provider_authorization_id"
        )
    attempt_root = (
        roots.handoff_root / expected_run_id / expected_attempt_id
    )
    _ensure_mode_directory(attempt_root, mode=0o700)
    entries = tuple(attempt_root.iterdir())
    if [path.name for path in entries] != ["blocked-manifest.json"]:
        raise RuntimeError("blocked_handoff_file_set_invalid")
    manifest_path = entries[0]
    metadata = manifest_path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise RuntimeError("blocked_handoff_invalid")
    payload = _read_regular_bytes(manifest_path, trusted_root=roots.handoff_root)
    if sha256_hex(payload) != expected_manifest_sha256:
        raise RuntimeError("blocked_handoff_mismatch")
    manifest = _decode_json_object(payload, "blocked_handoff_invalid")
    validate_schema_instance(schema=schema_assets.attempt_schema, value=manifest)
    if (
        manifest.get("schema_version") != "daily-translation-attempt-v1"
        or manifest.get("status") != "blocked"
        or manifest.get("run_id") != expected_run_id
        or manifest.get("attempt_id") != expected_attempt_id
        or manifest.get("provider_authorization_id")
        != expected_provider_authorization_id
    ):
        raise RuntimeError("blocked_handoff_mismatch")
    if _contains_forbidden_key(
        manifest, {"source_text", "zh", "api_key", "webhook", "secret"}
    ):
        raise RuntimeError("blocked_handoff_sensitive")
    if not roots.blocked_root.exists():
        _make_new_directory(roots.blocked_root, mode=0o700)
    else:
        _ensure_mode_directory(roots.blocked_root, mode=0o700)
    run_root = roots.blocked_root / expected_run_id
    if not run_root.exists():
        _make_new_directory(run_root, mode=0o700)
    else:
        _ensure_mode_directory(run_root, mode=0o700)
    target = run_root / expected_attempt_id
    if target.exists() or target.is_symlink():
        raise RuntimeError("blocked_attempt_exists")
    if os.stat(attempt_root).st_dev != os.stat(run_root).st_dev:
        raise RuntimeError("blocked_handoff_cross_device")
    os.rename(attempt_root, target)
    _fsync_directory(run_root)
    return target / "blocked-manifest.json"


def load_verified_prepared_report(
    *,
    roots: PreparedReportRoots,
    expected_run_id: str,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    expected_outbox_sha256: str,
    schema_assets: ReportSchemaAssets,
) -> VerifiedPreparedReport:
    _require_safe_id(expected_run_id, "run_id")
    _require_version_id(expected_artifact_version_id)
    public_dir = roots.public_root / "prepared" / expected_run_id / expected_artifact_version_id
    private_dir = roots.private_root / "prepared" / expected_run_id / expected_artifact_version_id
    index = _verify_bundle_tree(
        public_dir=public_dir,
        private_dir=private_dir,
        expected_artifact_version_id=expected_artifact_version_id,
        expected_bundle_sha256=expected_bundle_sha256,
        schema_assets=schema_assets,
    )
    manifest_bytes = _read_regular_bytes(
        private_dir / "translation-manifest.json", trusted_root=private_dir
    )
    manifest = _decode_json_object(manifest_bytes, "translation_manifest_invalid")
    validate_schema_instance(schema=schema_assets.manifest_schema, value=manifest)
    if manifest.get("run_id") != expected_run_id or manifest.get("status") != "complete":
        raise RuntimeError("translation_manifest_mismatch")
    parts = _verify_outbox_from_index(
        private_dir=private_dir,
        index=index,
        expected_outbox_sha256=expected_outbox_sha256,
    )
    validation_bytes = _read_regular_bytes(
        private_dir / "validation-report.json", trusted_root=private_dir
    )
    validation = _decode_json_object(validation_bytes, "validation_report_invalid")
    allowed_validation = {
        "schema_version",
        "run_id",
        "artifact_version_id",
        "report_input_fingerprint",
        "translation_output_sha256",
        "validator_output_sha256",
        "outbox_sha256",
        "public_artifact_urls",
        "source_state",
    }
    if set(validation) != allowed_validation or validation.get("schema_version") != "prepared-validation-v2":
        raise RuntimeError("validation_report_invalid")
    source_state = validate_frozen_report_source_state(validation.get("source_state"))
    urls = validation.get("public_artifact_urls")
    if not isinstance(urls, list) or any(
        not isinstance(url, str) or not url.startswith(("http://", "https://")) for url in urls
    ):
        raise RuntimeError("validation_report_invalid")
    expected_values = {
        "run_id": expected_run_id,
        "artifact_version_id": expected_artifact_version_id,
        "report_input_fingerprint": manifest.get("report_input_fingerprint"),
        "translation_output_sha256": manifest.get("translation_output_sha256"),
        "validator_output_sha256": manifest.get("validator_output_sha256"),
        "outbox_sha256": expected_outbox_sha256,
    }
    if any(validation.get(key) != value for key, value in expected_values.items()):
        raise RuntimeError("validation_report_mismatch")
    return VerifiedPreparedReport(
        run_id=expected_run_id,
        artifact_version_id=expected_artifact_version_id,
        bundle_sha256=expected_bundle_sha256,
        report_input_fingerprint=str(manifest["report_input_fingerprint"]),
        translation_input_fingerprint=str(manifest["translation_input_fingerprint"]),
        translation_output_sha256=str(manifest["translation_output_sha256"]),
        validator_output_sha256=str(manifest["validator_output_sha256"]),
        translation_status=str(manifest["status"]),
        outbox_sha256=expected_outbox_sha256,
        parts=parts,
        public_artifact_urls=tuple(urls),
        source_state=dict(source_state),
    )


def build_commit_blocked_attempt_from_complete_manifest(
    *,
    verified_complete_manifest: Mapping[str, object],
    attempt_id: str,
    stage: str,
    reason_codes: Sequence[str],
) -> Mapping[str, object]:
    _require_safe_id(attempt_id, "attempt_id")
    _require_reason(stage, "stage")
    reasons = _normalized_reasons(reason_codes)
    items_value = verified_complete_manifest.get("items")
    items: list[dict[str, object]] = []
    if isinstance(items_value, list):
        for row in items_value:
            if not isinstance(row, Mapping):
                continue
            stable_id = row.get("stable_id")
            input_sha = row.get("input_sha256")
            if isinstance(stable_id, str) and isinstance(input_sha, str):
                items.append(
                    {
                        "stable_id": stable_id,
                        "input_sha256": input_sha,
                        "status": "accepted",
                        "error_codes": list(reasons),
                    }
                )
    usage = verified_complete_manifest.get("usage")
    if not isinstance(usage, Mapping) or set(usage) != set(_ZERO_USAGE):
        usage = dict(_ZERO_USAGE)
    counts_value = verified_complete_manifest.get("counts")
    posts = counts_value.get("posts", 0) if isinstance(counts_value, Mapping) else 0
    blocked: dict[str, object] = {
        "schema_version": "daily-translation-attempt-v1",
        "attempt_id": attempt_id,
        "run_id": str(verified_complete_manifest.get("run_id") or ""),
        "status": "blocked",
        "stage": stage,
        "reason_codes": list(reasons),
        "provider_call": bool(verified_complete_manifest.get("provider_call")),
        "translation_provider_call": bool(
            verified_complete_manifest.get("translation_provider_call")
        ),
        "translation_provider_attempt_made": bool(
            verified_complete_manifest.get("translation_provider_attempt_made")
        ),
        "translation_phase_attempt_made": bool(
            verified_complete_manifest.get("translation_phase_attempt_made")
        ),
        "semantic_validation_phase_attempt_made": bool(
            verified_complete_manifest.get("semantic_validation_phase_attempt_made")
        ),
        "request_count": int(verified_complete_manifest.get("request_count") or 0),
        "retry_count": int(verified_complete_manifest.get("retry_count") or 0),
        "duration_ms": int(verified_complete_manifest.get("duration_ms") or 0),
        "usage": dict(usage),
        "responses": [],
        "counts": {"posts": int(posts), "items": len(items)},
        "items": items,
        "provider_authorization_id": verified_complete_manifest.get(
            "provider_authorization_id"
        ),
    }
    from .provider_attempt_ledger import (
        derive_blocked_binding_from_verified_complete_manifest,
    )

    ledger_binding = derive_blocked_binding_from_verified_complete_manifest(
        manifest=verified_complete_manifest,
        attempt_id=attempt_id,
    )
    if ledger_binding is not None:
        blocked["provider_attempt_ledger"] = ledger_binding
    return blocked


def recover_projection_journal(*, roots: PreparedReportRoots) -> None:
    journal = roots.state_root / "prepared-projection-journal.json"
    if not journal.exists():
        return
    value = load_regular_json(trusted_root=roots.state_root, path=journal)
    if not isinstance(value, Mapping) or value.get("schema_version") != "prepared-projection-journal-v1":
        raise RuntimeError("projection_journal_invalid")
    current_path = roots.state_root / "prepared-current.json"
    if not current_path.exists():
        raise RuntimeError("projection_recovery_without_current")
    projections = value.get("projections")
    final_dir_text = value.get("final_public_dir")
    if not isinstance(final_dir_text, str):
        raise RuntimeError("projection_journal_invalid")
    _apply_projections(
        roots=roots,
        projections=projections,
        final_public_dir=Path(final_dir_text),
        journal_already_written=True,
    )


def _verify_bundle_tree(
    *,
    public_dir: Path,
    private_dir: Path,
    expected_artifact_version_id: str,
    expected_bundle_sha256: str,
    schema_assets: ReportSchemaAssets,
) -> Mapping[str, object]:
    _ensure_mode_directory(public_dir, mode=None)
    _ensure_mode_directory(private_dir, mode=None)
    index_bytes = _read_regular_bytes(private_dir / "bundle-index.json", trusted_root=private_dir)
    if sha256_hex(index_bytes) != expected_bundle_sha256:
        raise RuntimeError("bundle_sha256_mismatch")
    index = _decode_json_object(index_bytes, "bundle_index_invalid")
    validate_schema_instance(schema=schema_assets.bundle_index_schema, value=index)
    if index.get("artifact_version_id") != expected_artifact_version_id:
        raise RuntimeError("bundle_version_mismatch")
    entries = index.get("entries")
    assert isinstance(entries, list)
    expected_paths: dict[str, set[str]] = {"public": set(), "private": set()}
    for entry in entries:
        assert isinstance(entry, Mapping)
        scope = str(entry["scope"])
        relative = str(entry["relative_path"])
        root = public_dir if scope == "public" else private_dir
        path = root / relative
        payload = _read_regular_bytes(path, trusted_root=root)
        if len(payload) != entry["byte_size"] or sha256_hex(payload) != entry["sha256"]:
            raise RuntimeError("bundle_entry_mismatch")
        if b'"bundle_sha256"' in payload:
            raise RuntimeError("bundle_payload_embeds_bundle_sha256")
        expected_paths[scope].add(relative)
    actual_public = {path.relative_to(public_dir).as_posix() for path in _regular_tree_files(public_dir)}
    actual_private = {
        path.relative_to(private_dir).as_posix()
        for path in _regular_tree_files(private_dir)
        if path.name != "bundle-index.json"
    }
    if actual_public != expected_paths["public"] or actual_private != expected_paths["private"]:
        raise RuntimeError("bundle_file_set_mismatch")
    return index


def _verify_outbox_from_index(
    *, private_dir: Path, index: Mapping[str, object], expected_outbox_sha256: str
) -> tuple[PreparedOutboxPart, ...]:
    entries = index.get("entries")
    assert isinstance(entries, list)
    names = sorted(
        str(entry["relative_path"])
        for entry in entries
        if isinstance(entry, Mapping)
        and entry.get("scope") == "private"
        and re.fullmatch(r"outbox/part-[0-9]{4}\.json", str(entry.get("relative_path")))
    )
    if not 1 <= len(names) <= 2 or names != [f"outbox/part-{index:04d}.json" for index in range(1, len(names) + 1)]:
        raise RuntimeError("outbox_file_set_invalid")
    parts: list[PreparedOutboxPart] = []
    for index, name in enumerate(names, start=1):
        path = private_dir / name
        payload = _read_regular_bytes(path, trusted_root=private_dir)
        body = _decode_json_object(payload, "outbox_body_invalid")
        if body.get("msgtype") != "markdown" or not isinstance(body.get("markdown"), Mapping):
            raise RuntimeError("outbox_body_invalid")
        parts.append(
            PreparedOutboxPart(
                index=index,
                total=len(names),
                path=path,
                body_bytes=payload,
                sha256=sha256_hex(payload),
                byte_count=len(payload),
            )
        )
    result = tuple(parts)
    if outbox_sha256(result) != expected_outbox_sha256:
        raise RuntimeError("outbox_sha256_mismatch")
    return result


def _apply_projections(
    *,
    roots: PreparedReportRoots,
    projections: object,
    final_public_dir: Path,
    journal_already_written: bool = False,
) -> None:
    if not isinstance(projections, Mapping) or not projections:
        raise RuntimeError("projection_mapping_invalid")
    checked: dict[str, str] = {}
    for name, target in projections.items():
        if not isinstance(name, str) or Path(name).name != name or not isinstance(target, str):
            raise RuntimeError("projection_mapping_invalid")
        target_path = roots.public_root / target
        try:
            target_path.relative_to(roots.public_root)
            target_path.relative_to(final_public_dir)
        except ValueError as exc:
            raise RuntimeError("projection_target_outside_public_root") from exc
        if not target_path.is_file() or target_path.is_symlink():
            raise RuntimeError("projection_target_invalid")
        checked[name] = target
    journal_path = roots.state_root / "prepared-projection-journal.json"
    if not journal_already_written:
        _atomic_replace_file(
            journal_path,
            canonical_json_bytes(
                {
                    "schema_version": "prepared-projection-journal-v1",
                    "final_public_dir": str(final_public_dir),
                    "projections": checked,
                }
            ),
            mode=0o600,
        )
    ordered = sorted(checked, key=lambda name: (name.endswith("-daily-detail.csv"), name))
    for name in ordered:
        link_path = roots.public_root / name
        temporary = roots.public_root / f".{name}.{secrets.token_hex(8)}.tmp"
        relative_target = os.path.relpath(roots.public_root / checked[name], roots.public_root)
        os.symlink(relative_target, temporary)
        os.replace(temporary, link_path)
    _fsync_directory(roots.public_root)
    journal_path.unlink(missing_ok=False)
    _fsync_directory(roots.state_root)


def _append_registry_entry(
    *,
    roots: PreparedReportRoots,
    run_id: str,
    artifact_version_id: str,
    bundle_sha256: str,
    manifest: Mapping[str, object],
) -> None:
    commits_root = roots.state_root / "prepared-commits"
    if not commits_root.exists():
        _make_new_directory(commits_root, mode=0o700)
    run_root = commits_root / run_id
    if not run_root.exists():
        _make_new_directory(run_root, mode=0o700)
    registry = run_root / "registry.jsonl"
    entries: list[Mapping[str, object]] = []
    if registry.exists():
        metadata = registry.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("commit_registry_invalid")
        for raw_line in registry.read_bytes().splitlines():
            if not raw_line:
                raise RuntimeError("commit_registry_invalid")
            entries.append(_decode_json_object(raw_line, "commit_registry_invalid"))
        _validate_registry_chain(entries, run_id=run_id)
    for entry in entries:
        if entry.get("artifact_version_id") == artifact_version_id:
            if entry.get("bundle_sha256") == bundle_sha256:
                return
            raise RuntimeError("commit_registry_conflict")
    base = {
        "schema_version": "prepared-commit-registry-v1",
        "sequence": len(entries) + 1,
        "previous_entry_sha256": entries[-1]["entry_sha256"] if entries else "0" * 64,
        "run_id": run_id,
        "artifact_version_id": artifact_version_id,
        "bundle_sha256": bundle_sha256,
        "manifest_id": manifest.get("manifest_id"),
        "translation_cache_key": manifest.get("translation_cache_key"),
        "validator_cache_key": manifest.get("validator_cache_key"),
        "translation_output_sha256": manifest.get("translation_output_sha256"),
        "validator_output_sha256": manifest.get("validator_output_sha256"),
    }
    entry = {**base, "entry_sha256": sha256_hex(canonical_json_bytes(base))}
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(registry, flags, 0o600)
    try:
        os.write(descriptor, canonical_json_bytes(entry) + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(registry, 0o600)
    _fsync_directory(run_root)


def _validate_registry_chain(entries: Sequence[Mapping[str, object]], *, run_id: str) -> None:
    previous = "0" * 64
    versions: set[str] = set()
    for sequence, entry in enumerate(entries, start=1):
        required = {
            "schema_version",
            "sequence",
            "previous_entry_sha256",
            "run_id",
            "artifact_version_id",
            "bundle_sha256",
            "manifest_id",
            "translation_cache_key",
            "validator_cache_key",
            "translation_output_sha256",
            "validator_output_sha256",
            "entry_sha256",
        }
        if set(entry) != required:
            raise RuntimeError("commit_registry_invalid")
        base = {key: entry[key] for key in required if key != "entry_sha256"}
        if (
            entry.get("schema_version") != "prepared-commit-registry-v1"
            or entry.get("sequence") != sequence
            or entry.get("previous_entry_sha256") != previous
            or entry.get("run_id") != run_id
            or entry.get("entry_sha256") != sha256_hex(canonical_json_bytes(base))
            or entry.get("artifact_version_id") in versions
        ):
            raise RuntimeError("commit_registry_invalid")
        versions.add(str(entry["artifact_version_id"]))
        previous = str(entry["entry_sha256"])


def _regular_tree_files(root: Path) -> tuple[Path, ...]:
    _ensure_mode_directory(root, mode=None)
    files: list[Path] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directory_names:
            path = current_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("bundle_tree_invalid")
        for name in file_names:
            path = current_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("bundle_tree_invalid")
            files.append(path)
    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


def _read_regular_bytes(path: Path, *, trusted_root: Path) -> bytes:
    root = Path(os.path.abspath(os.fspath(trusted_root)))
    candidate = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("path_outside_trusted_root") from exc
    if not relative.parts:
        raise RuntimeError("not_regular_file")
    current = root
    for part in relative.parts:
        current = current / part
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError("not_regular_file")
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("not_regular_file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(candidate, flags)
    try:
        payload = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > 64 * 1024 * 1024:
                raise RuntimeError("prepared_file_too_large")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _write_new_file(path: Path, payload: bytes, *, mode: int) -> None:
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


def _atomic_replace_file(path: Path, payload: bytes, *, mode: int) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    _write_new_file(temporary, payload, mode=mode)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _make_new_directory(path: Path, *, mode: int) -> None:
    path.mkdir(mode=mode)
    path.chmod(mode)
    _fsync_directory(path.parent)


def _prepare_final_parent(root: Path, final_parent: Path) -> None:
    _ensure_mode_directory(root, mode=None)
    prepared = root / "prepared"
    run_parent = final_parent
    if not prepared.exists():
        _make_new_directory(prepared, mode=0o700)
    else:
        _ensure_mode_directory(prepared, mode=None)
    if not run_parent.exists():
        _make_new_directory(run_parent, mode=0o700)
    else:
        _ensure_mode_directory(run_parent, mode=None)


def _ensure_mode_directory(path: Path, *, mode: int | None) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("directory_invalid")
    if metadata.st_uid != os.getuid():
        raise RuntimeError("directory_owner_invalid")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise RuntimeError("directory_mode_invalid")


def _require_exact_staging_directory(path: Path) -> None:
    _ensure_mode_directory(path, mode=0o700)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _decode_json_object(payload: bytes, reason: str) -> Mapping[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(reason) from exc
    if not isinstance(value, Mapping):
        raise RuntimeError(reason)
    return value


def _require_safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{field}_invalid")
    return value


def _require_version_id(value: object) -> str:
    if not isinstance(value, str) or _VERSION_ID.fullmatch(value) is None:
        raise ValueError("artifact_version_id_invalid")
    return value


def _require_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field}_invalid")
    return value


def _require_reason(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", value) is None:
        raise ValueError(f"{field}_invalid")
    return value


def _normalized_reasons(values: Sequence[str]) -> tuple[str, ...]:
    if not values:
        raise ValueError("reason_codes_empty")
    return tuple(sorted({_require_reason(value, "reason_code") for value in values}))


def _contains_forbidden_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in forbidden
            or _contains_forbidden_key(child, forbidden)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(child, forbidden) for child in value)
    return False
