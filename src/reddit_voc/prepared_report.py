from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from .daily_report import (
    DailyReportSource,
    PreparedRenderResult,
    render_prevalidated_daily_report,
    select_visible_daily_report_source,
)
from .prepared_bundle import (
    PreparedReportResult,
    PreparedReportRoots,
    StagedPreparedReport,
    commit_staged_prepared_report,
    freeze_dingtalk_outbox,
    load_verified_prepared_report,
    outbox_sha256,
    write_bundle_index,
)
from .provider_attempt_ledger import ProviderAttemptLedger
from .report_contracts import (
    ReportSchemaAssets,
    TokenUsage,
    canonical_json_bytes,
    load_regular_json,
    load_report_schema_assets,
    sha256_hex,
    validate_schema_instance,
)
from .report_source_state import classify_report_source_state
from .translation_pipeline import (
    PhaseEvidence,
    PostTranslationBundle,
    TranslationPipelineBlocked,
    TranslationPipelineResult,
    TranslationRuntimeAssets,
    TranslationService,
    VerifiedCacheManifest,
    build_post_translation_bundle,
    load_translation_runtime_assets,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VERSION_ID = re.compile(r"^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}$")
_REDDIT_POST_ID = re.compile(r"^[a-z0-9]+$")
_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_REDDIT_MEDIA_HOSTS = frozenset(
    {
        "i.redd.it",
        "v.redd.it",
        "preview.redd.it",
        "external-preview.redd.it",
        "packaged-media.redd.it",
    }
)
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_MAX_VISIBLE_POSTS = 50
_MAX_SOURCE_CHARS_PER_POST = 40_000
_MAX_SOURCE_CHARS_PER_REPORT = 250_000
_ZERO_USAGE = TokenUsage(0, 0, 0, 0, 0)


@dataclass(frozen=True)
class PreparedAttemptContext:
    attempt_id: str
    artifact_version_id: str


@dataclass(frozen=True)
class PreparedPreflight:
    run_id: str
    source: DailyReportSource
    visible_post_ids: tuple[str, ...]
    bundles: tuple[PostTranslationBundle, ...]
    cached_manifests: tuple[VerifiedCacheManifest, ...]
    translation_assets: TranslationRuntimeAssets
    schema_assets: ReportSchemaAssets
    provider_phases_required: tuple[str, ...]
    provider_authorization_id: str | None
    report_static_inputs: Mapping[str, object]


def validate_daily_report_source_state(source: DailyReportSource) -> Mapping[str, object]:
    return classify_report_source_state(
        status=source.run.get("status"),
        post_count=len(source.posts),
        comment_count=sum(len(rows) for rows in source.comments_by_post.values()),
    )


def preflight_daily_report(
    *,
    database: Path,
    run_id: str,
    roots: PreparedReportRoots,
    config_root: Path,
    artifact_base_url: str,
    dingtalk_required_keyword: str,
    dingtalk_max_bytes: int,
    dingtalk_max_parts: int = 2,
) -> PreparedPreflight:
    _require_safe_id(run_id, "run_id")
    artifact_base_url = _require_https_artifact_base_url(artifact_base_url)
    if not isinstance(dingtalk_required_keyword, str) or not dingtalk_required_keyword:
        raise ValueError("dingtalk_required_keyword_invalid")
    if isinstance(dingtalk_max_bytes, bool) or dingtalk_max_bytes <= 0:
        raise ValueError("dingtalk_max_bytes_invalid")
    if isinstance(dingtalk_max_parts, bool) or not 1 <= dingtalk_max_parts <= 2:
        raise ValueError("dingtalk_max_parts_invalid")
    _require_root_directories(roots)
    journal = roots.state_root / "prepared-projection-journal.json"
    if journal.exists():
        raise RuntimeError("projection_recovery_required")

    source = _read_daily_report_snapshot(database=Path(database), run_id=run_id)
    source_state = validate_daily_report_source_state(source)
    visible = select_visible_daily_report_source(source)
    visible = _canonicalize_visible_reddit_source_urls(visible)
    visible_post_ids = tuple(str(post["post_id"]) for post in visible.posts)
    if len(visible_post_ids) > _MAX_VISIBLE_POSTS:
        raise RuntimeError("visible_post_cap_exceeded")
    for post in visible.posts:
        _require_reddit_source_url(post.get("source_url"))
    bundles = tuple(
        build_post_translation_bundle(
            post,
            visible.comments_by_post.get(str(post["post_id"]), ()),
        )
        for post in visible.posts
    )
    source_chars_by_post = tuple(
        sum(len(item.source_text) for item in bundle.items) for bundle in bundles
    )
    if any(
        source_chars > _MAX_SOURCE_CHARS_PER_POST
        for source_chars in source_chars_by_post
    ):
        raise RuntimeError("translation_post_source_cap_exceeded")
    if sum(source_chars_by_post) > _MAX_SOURCE_CHARS_PER_REPORT:
        raise RuntimeError("translation_report_source_cap_exceeded")

    translation_assets = load_translation_runtime_assets(Path(config_root))
    schema_assets = load_report_schema_assets(config_root=Path(config_root))
    cached_manifests = load_verified_cache_manifests(
        roots=roots,
        run_id=run_id,
        schema_assets=schema_assets,
    )
    phases = _provider_phases_required(
        bundles=bundles,
        cached_manifests=cached_manifests,
        assets=translation_assets,
    )
    static_inputs = {
        "schema_version": "prepared-report-static-inputs-v1",
        "source": _source_document(visible),
        "source_state": source_state,
        "visibility_rule_version": "daily-visible-v1",
        "visibility_keyword": "Momcozy",
        "renderer_version": "deepseek-prevalidated-renderer-v1",
        "excerpt_version": "source-excerpt-v1",
        "translation_prompt_version": translation_assets.prompt_version,
        "validator_prompt_version": translation_assets.validator_prompt_version,
        "terms_sha256": translation_assets.terms_sha256,
        "source_signal_rules_sha256": translation_assets.source_signal_rules_sha256,
        "schema_sha256_by_name": dict(schema_assets.sha256_by_name),
        "artifact_base_url": artifact_base_url.rstrip("/"),
        "dingtalk_required_keyword": dingtalk_required_keyword,
        "dingtalk_max_bytes": dingtalk_max_bytes,
        "dingtalk_max_parts": dingtalk_max_parts,
        "hard_caps": {
            "visible_posts": _MAX_VISIBLE_POSTS,
            "source_characters_per_post": _MAX_SOURCE_CHARS_PER_POST,
            "source_characters_per_report": _MAX_SOURCE_CHARS_PER_REPORT,
            "provider_deadline_seconds": 300,
            "provider_attempts": 100,
        },
    }
    return PreparedPreflight(
        run_id=run_id,
        source=visible,
        visible_post_ids=visible_post_ids,
        bundles=bundles,
        cached_manifests=cached_manifests,
        translation_assets=translation_assets,
        schema_assets=schema_assets,
        provider_phases_required=phases,
        provider_authorization_id=None,
        report_static_inputs=static_inputs,
    )


def stage_daily_report(
    preflight: PreparedPreflight,
    *,
    attempt: PreparedAttemptContext,
    translator: TranslationService,
    roots: PreparedReportRoots,
    provider_authorization_id: str | None,
    prepare_action_authorization_id: str,
    provider_attempt_ledger: ProviderAttemptLedger | None = None,
) -> StagedPreparedReport:
    _require_safe_id(preflight.run_id, "run_id")
    _require_safe_id(attempt.attempt_id, "attempt_id")
    _require_version_id(attempt.artifact_version_id)
    _require_safe_id(prepare_action_authorization_id, "prepare_action_authorization_id")
    if provider_authorization_id is not None:
        _require_safe_id(provider_authorization_id, "provider_authorization_id")
    _require_empty_staging_leaf(roots.public_staging_root)
    _require_empty_staging_leaf(roots.private_staging_root)
    final_public = (
        roots.public_root / "prepared" / preflight.run_id / attempt.artifact_version_id
    )
    final_private = (
        roots.private_root / "prepared" / preflight.run_id / attempt.artifact_version_id
    )
    if final_public.exists() or final_private.exists():
        raise RuntimeError("prepared_final_exists")

    pipeline_result = translator.run(
        preflight.bundles,
        cached_manifests=preflight.cached_manifests,
        deadline_seconds=300,
        max_attempts=100,
    )
    effective_provider_authorization_id = (
        provider_authorization_id if pipeline_result.attempts else None
    )
    if pipeline_result.attempts and effective_provider_authorization_id is None:
        raise RuntimeError("provider_authorization_required")

    artifact_version_url = (
        str(preflight.report_static_inputs["artifact_base_url"]).rstrip("/")
        + f"/prepared/{preflight.run_id}/{attempt.artifact_version_id}"
    )
    rendered = render_prevalidated_daily_report(
        preflight.source,
        translations=pipeline_result.translations,
        output_dir=roots.public_staging_root,
        artifact_version_url=artifact_version_url,
        dingtalk_max_bytes=int(preflight.report_static_inputs["dingtalk_max_bytes"]),
        dingtalk_required_keyword=str(
            preflight.report_static_inputs["dingtalk_required_keyword"]
        ),
        dingtalk_max_parts=int(preflight.report_static_inputs["dingtalk_max_parts"]),
    )
    report_input_fingerprint = _report_input_fingerprint(
        preflight=preflight,
        pipeline_result=pipeline_result,
        rendered=rendered,
        artifact_version_id=attempt.artifact_version_id,
    )
    manifest = build_complete_translation_manifest(
        preflight=preflight,
        pipeline_result=pipeline_result,
        report_input_fingerprint=report_input_fingerprint,
        provider_authorization_id=effective_provider_authorization_id,
        provider_attempt_ledger=provider_attempt_ledger,
    )
    manifest_bytes = canonical_json_bytes(manifest)
    _write_new_file(
        roots.private_staging_root / "translation-manifest.json",
        manifest_bytes,
        mode=0o600,
    )
    parts = freeze_dingtalk_outbox(
        rendered=rendered,
        private_staging_dir=roots.private_staging_root,
        dingtalk_required_keyword=str(
            preflight.report_static_inputs["dingtalk_required_keyword"]
        ),
    )
    max_bytes = int(preflight.report_static_inputs["dingtalk_max_bytes"])
    if any(part.byte_count > max_bytes for part in parts):
        raise RuntimeError("dingtalk_body_too_large")
    outbox_digest = outbox_sha256(parts)
    public_paths = tuple(Path(path) for path in rendered.report.artifact_paths())
    expected_public = {
        path.name
        for path in public_paths
    }
    actual_public = {
        path.name
        for path in roots.public_staging_root.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    if actual_public != expected_public:
        raise RuntimeError("rendered_public_file_set_mismatch")
    for path in public_paths:
        path.chmod(0o644)
        _fsync_file(path)
    _fsync_directory(roots.public_staging_root)

    public_artifact_urls = [f"{artifact_version_url}/{path.name}" for path in public_paths]
    validation_report = {
        "schema_version": "prepared-validation-v2",
        "run_id": preflight.run_id,
        "artifact_version_id": attempt.artifact_version_id,
        "report_input_fingerprint": report_input_fingerprint,
        "translation_output_sha256": pipeline_result.translation_output_sha256,
        "validator_output_sha256": pipeline_result.validator_output_sha256,
        "outbox_sha256": outbox_digest,
        "public_artifact_urls": public_artifact_urls,
        "source_state": dict(preflight.report_static_inputs["source_state"]),
    }
    _write_new_file(
        roots.private_staging_root / "validation-report.json",
        canonical_json_bytes(validation_report),
        mode=0o600,
    )
    _, bundle_digest = write_bundle_index(
        public_staging_dir=roots.public_staging_root,
        private_staging_dir=roots.private_staging_root,
        artifact_version_id=attempt.artifact_version_id,
        schema_assets=preflight.schema_assets,
    )

    projections = {
        path.name: (
            f"prepared/{preflight.run_id}/{attempt.artifact_version_id}/{path.name}"
        )
        for path in public_paths
    }
    commit_request = {
        "schema_version": "prepared-commit-request-v1",
        "run_id": preflight.run_id,
        "attempt_id": attempt.attempt_id,
        "artifact_version_id": attempt.artifact_version_id,
        "bundle_sha256": bundle_digest,
        "outbox_sha256": outbox_digest,
        "report_input_fingerprint": report_input_fingerprint,
        "manifest_sha256": sha256_hex(manifest_bytes),
        "provider_authorization_id": effective_provider_authorization_id,
        "prepare_action_authorization_id": prepare_action_authorization_id,
        "staged_public_dir": str(roots.public_staging_root),
        "staged_private_dir": str(roots.private_staging_root),
        "final_public_dir": str(final_public),
        "final_private_dir": str(final_private),
        "projections": projections,
    }
    commit_request_bytes = canonical_json_bytes(commit_request)
    commit_request_path = _write_commit_request(
        roots=roots,
        run_id=preflight.run_id,
        attempt_id=attempt.attempt_id,
        payload=commit_request_bytes,
    )
    return StagedPreparedReport(
        run_id=preflight.run_id,
        attempt_id=attempt.attempt_id,
        artifact_version_id=attempt.artifact_version_id,
        bundle_sha256=bundle_digest,
        report_input_fingerprint=report_input_fingerprint,
        outbox_sha256=outbox_digest,
        provider_authorization_id=effective_provider_authorization_id,
        prepare_action_authorization_id=prepare_action_authorization_id,
        staged_public_dir=roots.public_staging_root,
        staged_private_dir=roots.private_staging_root,
        final_public_dir=final_public,
        final_private_dir=final_private,
        commit_request_path=commit_request_path,
        commit_request_sha256=sha256_hex(commit_request_bytes),
    )


def prepare_daily_report(
    preflight: PreparedPreflight,
    *,
    attempt: PreparedAttemptContext,
    translator: TranslationService,
    roots: PreparedReportRoots,
    provider_authorization_id: str | None,
    prepare_action_authorization_id: str,
    provider_attempt_ledger: ProviderAttemptLedger | None = None,
) -> PreparedReportResult:
    staged = stage_daily_report(
        preflight,
        attempt=attempt,
        translator=translator,
        roots=roots,
        provider_authorization_id=provider_authorization_id,
        prepare_action_authorization_id=prepare_action_authorization_id,
        provider_attempt_ledger=provider_attempt_ledger,
    )
    return commit_staged_prepared_report(
        roots=roots,
        expected_run_id=staged.run_id,
        expected_artifact_version_id=staged.artifact_version_id,
        expected_bundle_sha256=staged.bundle_sha256,
        expected_outbox_sha256=staged.outbox_sha256,
        expected_commit_request_sha256=staged.commit_request_sha256,
        expected_provider_authorization_id=staged.provider_authorization_id,
        expected_prepare_action_authorization_id=staged.prepare_action_authorization_id,
        expected_attempt_id=staged.attempt_id,
        schema_assets=preflight.schema_assets,
    )


def build_complete_translation_manifest(
    *,
    preflight: PreparedPreflight,
    pipeline_result: TranslationPipelineResult,
    report_input_fingerprint: str,
    provider_authorization_id: str | None,
    provider_attempt_ledger: ProviderAttemptLedger | None = None,
) -> Mapping[str, object]:
    _require_sha(report_input_fingerprint, "report_input_fingerprint")
    expected_items = {
        item.stable_id: item for bundle in preflight.bundles for item in bundle.items
    }
    evidence_items = {item.stable_id: item for item in pipeline_result.items}
    if set(expected_items) != set(evidence_items):
        raise RuntimeError("translation_manifest_item_join_mismatch")
    rows: list[dict[str, object]] = []
    for stable_id in sorted(expected_items):
        evidence = evidence_items[stable_id]
        expected = expected_items[stable_id]
        if (
            evidence.input_sha256 != expected.input_sha256
            or evidence.item_type != expected.item_type
            or evidence.post_id != expected.post_id
            or evidence.comment_id != expected.comment_id
            or evidence.zh is None
            or evidence.semantic_verdict is None
            or evidence.status != "accepted"
        ):
            raise RuntimeError("translation_manifest_item_join_mismatch")
        verdict = evidence.semantic_verdict
        rows.append(
            {
                "stable_id": stable_id,
                "item_type": evidence.item_type,
                "post_id": evidence.post_id,
                "comment_id": evidence.comment_id,
                "input_sha256": evidence.input_sha256,
                "zh": evidence.zh,
                "source_signals": {
                    "negation": list(evidence.source_signals.negation),
                    "comparison": list(evidence.source_signals.comparison),
                    "sentiment": list(evidence.source_signals.sentiment),
                },
                "semantic_verdict": {
                    "meaning_preserved": verdict.meaning_preserved,
                    "negation_preserved": verdict.negation_preserved,
                    "comparison_preserved": verdict.comparison_preserved,
                    "sentiment_preserved": verdict.sentiment_preserved,
                    "hallucination_free": verdict.hallucination_free,
                },
                "critical_error_codes": list(verdict.critical_error_codes),
                "entity_status": evidence.entity_status,
                "status": "accepted",
            }
        )
    attempts_made = (
        pipeline_result.translation_phase.attempt_made
        or pipeline_result.semantic_validation_phase.attempt_made
    )
    if attempts_made != (provider_authorization_id is not None):
        raise RuntimeError("provider_authorization_evidence_mismatch")
    translation_phase = pipeline_result.translation_phase
    semantic_phase = pipeline_result.semantic_validation_phase
    parsed_response_attempts = sorted(
        (
            attempt
            for phase in (translation_phase, semantic_phase)
            for attempt in phase.attempts
            if _has_parsed_provider_response(attempt)
        ),
        key=lambda attempt: attempt.sequence,
    )
    responses = [
        _parsed_response_document(attempt) for attempt in parsed_response_attempts
    ]
    counts = {
        "posts": len(preflight.bundles),
        "titles": sum(item.item_type == "title" for item in expected_items.values()),
        "bodies": sum(item.item_type == "body" for item in expected_items.values()),
        "comments": sum(item.item_type == "comment" for item in expected_items.values()),
        "items": len(expected_items),
    }
    manifest_id = (
        f"{preflight.run_id}.{pipeline_result.translation_input_fingerprint}."
        f"{pipeline_result.translation_output_sha256}.{pipeline_result.validator_output_sha256}"
    )
    manifest: Mapping[str, object] = {
        "schema_version": "daily-translation-manifest-v1",
        "manifest_id": manifest_id,
        "run_id": preflight.run_id,
        "provider": "deepseek",
        "requested_model": "deepseek-v4-flash",
        "prompt_version": preflight.translation_assets.prompt_version,
        "validator_prompt_version": preflight.translation_assets.validator_prompt_version,
        "translation_cache_key": pipeline_result.translation_cache_key,
        "validator_cache_key": pipeline_result.validator_cache_key,
        "translation_output_sha256": pipeline_result.translation_output_sha256,
        "validator_output_sha256": pipeline_result.validator_output_sha256,
        "translation_input_fingerprint": pipeline_result.translation_input_fingerprint,
        "report_input_fingerprint": report_input_fingerprint,
        "status": "complete",
        "provider_call": attempts_made,
        "translation_provider_call": attempts_made,
        "translation_provider_attempt_made": attempts_made,
        "translation_phase_attempt_made": translation_phase.attempt_made,
        "semantic_validation_phase_attempt_made": semantic_phase.attempt_made,
        "translation_reused": pipeline_result.translation_reused,
        "semantic_validation_reused": pipeline_result.semantic_validation_reused,
        "request_count": translation_phase.request_count + semantic_phase.request_count,
        "retry_count": translation_phase.retry_count + semantic_phase.retry_count,
        "duration_ms": pipeline_result.duration_ms,
        "usage": _usage_document(pipeline_result.total_usage),
        "responses": responses,
        "counts": counts,
        "items": rows,
        "provider_authorization_id": provider_authorization_id,
    }
    if provider_attempt_ledger is not None:
        manifest = {
            **manifest,
            "provider_attempt_ledger": provider_attempt_ledger.build_manifest_binding(
                status="complete"
            ),
        }
        provider_attempt_ledger.verify_manifest_closure(manifest)
    validate_schema_instance(schema=preflight.schema_assets.manifest_schema, value=manifest)
    return manifest


def build_blocked_translation_attempt(
    *,
    run_id: str,
    attempt_id: str,
    preflight: PreparedPreflight | None,
    pipeline_evidence: TranslationPipelineResult | TranslationPipelineBlocked | None,
    stage: str,
    reason_codes: Sequence[str],
    provider_authorization_id: str | None,
    provider_attempt_ledger: ProviderAttemptLedger | None = None,
) -> Mapping[str, object]:
    _require_safe_id(run_id, "run_id")
    _require_safe_id(attempt_id, "attempt_id")
    _require_reason(stage, "stage")
    reasons = _normalized_reasons(reason_codes)
    if provider_authorization_id is not None:
        _require_safe_id(provider_authorization_id, "provider_authorization_id")
    attempts = tuple(getattr(pipeline_evidence, "attempts", ()))
    if isinstance(pipeline_evidence, TranslationPipelineResult):
        translation_phase = pipeline_evidence.translation_phase
        semantic_phase = pipeline_evidence.semantic_validation_phase
        evidence_items = pipeline_evidence.items
        usage = pipeline_evidence.total_usage
        duration_ms = pipeline_evidence.duration_ms
    elif isinstance(pipeline_evidence, TranslationPipelineBlocked):
        translation_phase = pipeline_evidence.translation_phase
        semantic_phase = pipeline_evidence.semantic_validation_phase
        evidence_items = pipeline_evidence.item_evidence
        usage = _add_usage(translation_phase.usage, semantic_phase.usage)
        duration_ms = translation_phase.duration_ms + semantic_phase.duration_ms
    else:
        translation_phase = _empty_phase("translation")
        semantic_phase = _empty_phase("semantic_validation")
        evidence_items = ()
        usage = _ZERO_USAGE
        duration_ms = 0
    items = []
    has_attributed_item_failure = any(
        item.status == "blocked" for item in evidence_items
    )
    for item in evidence_items:
        status = item.status if item.status in {"pending", "accepted"} else "blocked"
        error_codes = (
            []
            if status == "pending" and has_attributed_item_failure
            else list(reasons)
        )
        for error_code in item.error_codes:
            if _REASON.fullmatch(error_code):
                error_codes.append(error_code)
        if item.error_type and _REASON.fullmatch(item.error_type):
            error_codes.append(item.error_type)
        error_codes = sorted(set(error_codes))
        items.append(
            {
                "stable_id": item.stable_id,
                "input_sha256": item.input_sha256,
                "status": status,
                "error_codes": error_codes,
            }
        )
    if not items and preflight is not None:
        items = [
            {
                "stable_id": item.stable_id,
                "input_sha256": item.input_sha256,
                "status": "pending",
                "error_codes": list(reasons),
            }
            for bundle in preflight.bundles
            for item in bundle.items
        ]
    responses = [_attempt_document(attempt) for attempt in attempts]
    manifest: Mapping[str, object] = {
        "schema_version": "daily-translation-attempt-v1",
        "attempt_id": attempt_id,
        "run_id": run_id,
        "status": "blocked",
        "stage": stage,
        "reason_codes": list(reasons),
        "provider_call": translation_phase.attempt_made
        or semantic_phase.attempt_made,
        "translation_provider_call": translation_phase.attempt_made
        or semantic_phase.attempt_made,
        "translation_provider_attempt_made": translation_phase.attempt_made
        or semantic_phase.attempt_made,
        "translation_phase_attempt_made": translation_phase.attempt_made,
        "semantic_validation_phase_attempt_made": semantic_phase.attempt_made,
        "request_count": translation_phase.request_count
        + semantic_phase.request_count,
        "retry_count": translation_phase.retry_count + semantic_phase.retry_count,
        "duration_ms": duration_ms,
        "usage": _usage_document(usage),
        "responses": responses,
        "counts": {
            "posts": len(preflight.bundles) if preflight is not None else 0,
            "items": len(items),
        },
        "items": items,
        "provider_authorization_id": provider_authorization_id,
    }
    if provider_attempt_ledger is not None:
        ledger_binding = provider_attempt_ledger.build_manifest_binding(
            status="blocked"
        )
        ledger_attempts = ledger_binding["attempts"]
        if not isinstance(ledger_attempts, list):
            raise RuntimeError("provider_attempt_ledger_binding_invalid")
        external_attempted = int(ledger_binding["external_attempt_count"]) > 0
        manifest = {
            **manifest,
            "provider_call": external_attempted,
            "translation_provider_call": external_attempted,
            "translation_provider_attempt_made": external_attempted,
            "translation_phase_attempt_made": any(
                row.get("phase") == "translation"
                and row.get("external_attempt_made") is True
                for row in ledger_attempts
                if isinstance(row, Mapping)
            ),
            "semantic_validation_phase_attempt_made": any(
                row.get("phase") == "semantic_validation"
                and row.get("external_attempt_made") is True
                for row in ledger_attempts
                if isinstance(row, Mapping)
            ),
            "request_count": ledger_binding["external_attempt_count"],
            "retry_count": ledger_binding["retry_count"],
            "usage": ledger_binding["usage"],
            "provider_attempt_ledger": ledger_binding,
        }
        provider_attempt_ledger.verify_manifest_closure(manifest)
    if preflight is not None:
        validate_schema_instance(schema=preflight.schema_assets.attempt_schema, value=manifest)
    return manifest


def write_blocked_attempt(
    *,
    roots: PreparedReportRoots,
    run_id: str,
    attempt_id: str,
    manifest: Mapping[str, object],
) -> Path:
    return _write_blocked_attempt_to_root(
        root=roots.blocked_root,
        run_id=run_id,
        attempt_id=attempt_id,
        manifest=manifest,
        exists_reason="blocked_attempt_exists",
        allow_empty_existing=False,
    )


def stage_blocked_attempt(
    *,
    roots: PreparedReportRoots,
    run_id: str,
    attempt_id: str,
    manifest: Mapping[str, object],
) -> Path:
    return _write_blocked_attempt_to_root(
        root=roots.handoff_root,
        run_id=run_id,
        attempt_id=attempt_id,
        manifest=manifest,
        exists_reason="handoff_attempt_exists",
        allow_empty_existing=True,
    )


def _write_blocked_attempt_to_root(
    *,
    root: Path,
    run_id: str,
    attempt_id: str,
    manifest: Mapping[str, object],
    exists_reason: str,
    allow_empty_existing: bool,
) -> Path:
    _require_safe_id(run_id, "run_id")
    _require_safe_id(attempt_id, "attempt_id")
    if manifest.get("run_id") != run_id or manifest.get("attempt_id") != attempt_id:
        raise RuntimeError("blocked_attempt_identity_mismatch")
    if manifest.get("schema_version") != "daily-translation-attempt-v1":
        raise RuntimeError("blocked_attempt_schema_invalid")
    forbidden = {"source_text", "zh", "api_key", "webhook", "secret"}
    if _contains_forbidden_key(manifest, forbidden):
        raise RuntimeError("blocked_attempt_contains_sensitive_text")
    payload = canonical_json_bytes(manifest)
    _ensure_directory(root, mode=0o700)
    run_root = root / run_id
    if not run_root.exists():
        _make_new_directory(run_root, mode=0o700)
    else:
        _ensure_directory(run_root, mode=0o700)
    target = run_root / attempt_id
    if target.exists() or target.is_symlink():
        _ensure_directory(target, mode=0o700)
        if not allow_empty_existing or any(target.iterdir()):
            raise RuntimeError(exists_reason)
        path = target / "blocked-manifest.json"
        _write_new_file(path, payload, mode=0o600)
        _fsync_directory(target)
    else:
        temporary = run_root / f".{attempt_id}.{secrets.token_hex(8)}.tmp"
        _make_new_directory(temporary, mode=0o700)
        path = temporary / "blocked-manifest.json"
        _write_new_file(path, payload, mode=0o600)
        _fsync_directory(temporary)
        os.rename(temporary, target)
    _fsync_directory(run_root)
    return target / "blocked-manifest.json"


def load_verified_cache_manifests(
    *,
    roots: PreparedReportRoots,
    run_id: str,
    schema_assets: ReportSchemaAssets,
) -> tuple[VerifiedCacheManifest, ...]:
    current_path = roots.state_root / "prepared-current.json"
    if not current_path.exists():
        return ()
    current = load_regular_json(trusted_root=roots.state_root, path=current_path)
    expected_keys = {
        "schema_version",
        "run_id",
        "artifact_version_id",
        "bundle_sha256",
        "report_input_fingerprint",
        "outbox_sha256",
    }
    if not isinstance(current, Mapping) or set(current) != expected_keys:
        raise RuntimeError("prepared_current_invalid")
    if current.get("schema_version") != "prepared-current-v1":
        raise RuntimeError("prepared_current_invalid")
    if current.get("run_id") != run_id:
        return ()
    verified = load_verified_prepared_report(
        roots=roots,
        expected_run_id=run_id,
        expected_artifact_version_id=str(current["artifact_version_id"]),
        expected_bundle_sha256=str(current["bundle_sha256"]),
        expected_outbox_sha256=str(current["outbox_sha256"]),
        schema_assets=schema_assets,
    )
    private_dir = (
        roots.private_root / "prepared" / run_id / verified.artifact_version_id
    )
    manifest = load_regular_json(
        trusted_root=private_dir,
        path=private_dir / "translation-manifest.json",
    )
    if not isinstance(manifest, Mapping):
        raise RuntimeError("translation_manifest_invalid")
    validate_schema_instance(schema=schema_assets.manifest_schema, value=manifest)
    return (
        VerifiedCacheManifest(
            run_id=run_id,
            artifact_version_id=verified.artifact_version_id,
            bundle_sha256=verified.bundle_sha256,
            is_current=True,
            manifest=manifest,
        ),
    )


def _provider_phases_required(
    *,
    bundles: Sequence[PostTranslationBundle],
    cached_manifests: Sequence[VerifiedCacheManifest],
    assets: TranslationRuntimeAssets,
) -> tuple[str, ...]:
    service = TranslationService(client=None, assets=assets)
    try:
        service.run(bundles, cached_manifests=cached_manifests)
    except TranslationPipelineBlocked as exc:
        if "translation_client_required" in exc.reason_codes:
            return ("translation", "semantic_validation")
        if "semantic_validation_client_required" in exc.reason_codes:
            return ("semantic_validation",)
        raise RuntimeError("cache_preflight_blocked") from exc
    return ()


def _read_daily_report_snapshot(*, database: Path, run_id: str) -> DailyReportSource:
    try:
        metadata = database.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError("database_missing") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("database_not_regular")
    uri = database.resolve(strict=True).as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        _validate_database_schema(connection)
        run_row = connection.execute(
            "SELECT run_id,status,window_start_utc,window_end_utc,provider_call,live_send "
            "FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if run_row is None:
            raise RuntimeError("run_not_found")
        post_rows = connection.execute(
            "SELECT post_id,run_id,raw_capture_id,subreddit,title,selftext,source_url,"
            "created_at_utc,score,num_comments_reported,parsed_comment_count,more_node_count,"
            "coverage_grade,matched_keywords,author_hash,media_urls "
            "FROM reddit_threads WHERE run_id=? ORDER BY created_at_utc,post_id",
            (run_id,),
        ).fetchall()
        comment_rows = connection.execute(
            "SELECT comment_id,post_id,run_id,raw_capture_id,parent_id,body,created_at_utc,"
            "score,depth,is_submitter,matched_keywords,author_hash,deleted_or_removed "
            "FROM reddit_comments WHERE run_id=? ORDER BY created_at_utc,comment_id",
            (run_id,),
        ).fetchall()
        analysis_rows = connection.execute(
            "SELECT analysis_id,run_id,source_type,source_id,analysis_version,"
            "sentiment_label,sentiment_score,topic,severity,confidence,pain_points,provider_call "
            "FROM analysis_results WHERE run_id=? ORDER BY source_type,source_id,analysis_id",
            (run_id,),
        ).fetchall()
        recent_rows = connection.execute(
            "SELECT post_id,run_id,raw_capture_id,subreddit,title,selftext,source_url,"
            "created_at_utc,score,num_comments_reported,parsed_comment_count,more_node_count,"
            "coverage_grade,matched_keywords,author_hash,media_urls "
            "FROM reddit_threads ORDER BY created_at_utc DESC,post_id LIMIT 200"
        ).fetchall()
        connection.rollback()
    except RuntimeError:
        raise
    except sqlite3.Error as exc:
        raise RuntimeError("database_schema_invalid") from exc
    finally:
        if "connection" in locals():
            connection.close()

    run = dict(run_row)
    run["provider_call"] = bool(run["provider_call"])
    run["live_send"] = bool(run["live_send"])
    posts = tuple(_thread_row(row) for row in post_rows)
    comments_by_post: dict[str, list[Mapping[str, object]]] = {}
    for row in comment_rows:
        value = dict(row)
        value["is_submitter"] = (
            bool(value["is_submitter"]) if value["is_submitter"] is not None else None
        )
        value["deleted_or_removed"] = bool(value["deleted_or_removed"])
        comments_by_post.setdefault(str(value["post_id"]), []).append(value)
    analysis_by_post: dict[str, Mapping[str, object]] = {}
    for row in analysis_rows:
        value = dict(row)
        value["provider_call"] = bool(value["provider_call"])
        if value["source_type"] == "post":
            source_id = str(value["source_id"])
            if source_id in analysis_by_post:
                raise RuntimeError("analysis_post_duplicate")
            analysis_by_post[source_id] = value
    return DailyReportSource(
        run=run,
        posts=posts,
        comments_by_post={key: tuple(values) for key, values in comments_by_post.items()},
        analysis_by_post=analysis_by_post,
        recent_threads=tuple(_thread_row(row) for row in recent_rows),
    )


def _validate_database_schema(connection: sqlite3.Connection) -> None:
    required = {
        "runs": {"run_id", "status", "window_start_utc", "window_end_utc", "provider_call", "live_send"},
        "reddit_threads": {
            "post_id", "run_id", "raw_capture_id", "subreddit", "title", "selftext",
            "source_url", "created_at_utc", "score", "num_comments_reported",
            "parsed_comment_count", "more_node_count", "coverage_grade", "matched_keywords",
            "author_hash", "media_urls",
        },
        "reddit_comments": {
            "comment_id", "post_id", "run_id", "raw_capture_id", "parent_id", "body",
            "created_at_utc", "score", "depth", "is_submitter", "matched_keywords",
            "author_hash", "deleted_or_removed",
        },
        "analysis_results": {
            "analysis_id", "run_id", "source_type", "source_id", "analysis_version",
            "sentiment_label", "sentiment_score", "topic", "severity", "confidence",
            "pain_points", "provider_call",
        },
        "delivery_previews": {
            "delivery_id", "run_id", "channel", "mode", "status", "message_hash",
            "artifact_paths", "live_send",
        },
    }
    for table, columns in required.items():
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        actual = {str(row[1]) for row in rows}
        if not columns.issubset(actual):
            raise RuntimeError("database_schema_invalid")


def _thread_row(row: sqlite3.Row) -> Mapping[str, object]:
    value = dict(row)
    media = value.get("media_urls")
    try:
        parsed = json.loads(str(media)) if media is not None else []
    except json.JSONDecodeError as exc:
        raise RuntimeError("database_media_urls_invalid") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise RuntimeError("database_media_urls_invalid")
    value["media_urls"] = parsed
    return value


def _source_document(source: DailyReportSource) -> Mapping[str, object]:
    return {
        "run": dict(source.run),
        "posts": [dict(post) for post in source.posts],
        "comments_by_post": {
            post_id: [dict(comment) for comment in comments]
            for post_id, comments in sorted(source.comments_by_post.items())
        },
        "analysis_by_post": {
            post_id: dict(value)
            for post_id, value in sorted(source.analysis_by_post.items())
        },
        "recent_threads": [dict(value) for value in source.recent_threads],
    }


def _report_input_fingerprint(
    *,
    preflight: PreparedPreflight,
    pipeline_result: TranslationPipelineResult,
    rendered: PreparedRenderResult,
    artifact_version_id: str,
) -> str:
    renderer_fingerprint = rendered.report.report_summary.get("report_input_fingerprint")
    _require_sha(renderer_fingerprint, "renderer_report_input_fingerprint")
    return sha256_hex(
        canonical_json_bytes(
            {
                "static_inputs": preflight.report_static_inputs,
                "artifact_version_id": artifact_version_id,
                "translation_input_fingerprint": pipeline_result.translation_input_fingerprint,
                "translation_cache_key": pipeline_result.translation_cache_key,
                "translation_output_sha256": pipeline_result.translation_output_sha256,
                "validator_cache_key": pipeline_result.validator_cache_key,
                "validator_output_sha256": pipeline_result.validator_output_sha256,
                "renderer_report_input_fingerprint": renderer_fingerprint,
            }
        )
    )


def _write_commit_request(
    *, roots: PreparedReportRoots, run_id: str, attempt_id: str, payload: bytes
) -> Path:
    _ensure_directory(roots.handoff_root, mode=0o700)
    run_root = roots.handoff_root / run_id
    if not run_root.exists():
        _make_new_directory(run_root, mode=0o700)
    else:
        _ensure_directory(run_root, mode=0o700)
    attempt_root = run_root / attempt_id
    if attempt_root.exists() or attempt_root.is_symlink():
        _ensure_directory(attempt_root, mode=0o700)
        if any(attempt_root.iterdir()):
            raise RuntimeError("handoff_attempt_not_empty")
    else:
        _make_new_directory(attempt_root, mode=0o700)
    path = attempt_root / "commit-request.json"
    _write_new_file(path, payload, mode=0o600)
    _fsync_directory(attempt_root)
    _fsync_directory(run_root)
    return path


def _has_parsed_provider_response(attempt: object) -> bool:
    return (
        getattr(attempt, "http_status", None) == 200
        and isinstance(getattr(attempt, "response_id", None), str)
        and bool(attempt.response_id)
        and isinstance(getattr(attempt, "actual_model", None), str)
        and bool(attempt.actual_model)
        and isinstance(getattr(attempt, "finish_reason", None), str)
        and bool(attempt.finish_reason)
        and isinstance(getattr(attempt, "usage", None), TokenUsage)
    )


def _parsed_response_document(attempt: object) -> Mapping[str, object]:
    return {
        "phase": attempt.phase,
        "request_id": attempt.response_id,
        "actual_model": attempt.actual_model,
        "system_fingerprint": attempt.system_fingerprint,
        "finish_reason": attempt.finish_reason,
        "usage": _usage_document(attempt.usage),
    }


def _attempt_document(attempt: object) -> Mapping[str, object]:
    usage = getattr(attempt, "usage", None) or _ZERO_USAGE
    return {
        "sequence": int(attempt.sequence),
        "phase": attempt.phase,
        "outcome": str(attempt.outcome),
        "retryable": bool(attempt.retryable),
        "duration_ms": int(attempt.duration_ms),
        "response_id": attempt.response_id,
        "actual_model": attempt.actual_model,
        "system_fingerprint": attempt.system_fingerprint,
        "finish_reason": attempt.finish_reason,
        "usage": _usage_document(usage),
    }


def _usage_document(usage: TokenUsage) -> Mapping[str, int]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "prompt_cache_hit_tokens": usage.prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": usage.prompt_cache_miss_tokens,
        "total_tokens": usage.total_tokens,
    }


def _add_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=left.prompt_tokens + right.prompt_tokens,
        completion_tokens=left.completion_tokens + right.completion_tokens,
        prompt_cache_hit_tokens=left.prompt_cache_hit_tokens + right.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=left.prompt_cache_miss_tokens + right.prompt_cache_miss_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
    )


def _empty_phase(phase: str) -> PhaseEvidence:
    return PhaseEvidence(
        phase=phase,
        request_count=0,
        retry_count=0,
        attempt_made=False,
        duration_ms=0,
        usage=_ZERO_USAGE,
        completions=(),
        attempts=(),
    )


def _require_root_directories(roots: PreparedReportRoots) -> None:
    _ensure_directory(roots.public_root, mode=0o755)
    for path in (
        roots.private_root,
        roots.public_staging_root,
        roots.private_staging_root,
        roots.state_root,
        roots.blocked_root,
        roots.handoff_root,
    ):
        _ensure_directory(path, mode=0o700)


def _require_empty_staging_leaf(path: Path) -> None:
    _ensure_directory(path, mode=0o700)
    if any(path.iterdir()):
        raise RuntimeError("staging_directory_not_empty")


def _ensure_directory(path: Path, *, mode: int) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("directory_invalid")
    if metadata.st_uid != os.getuid():
        raise RuntimeError("directory_owner_invalid")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise RuntimeError("directory_mode_invalid")


def _make_new_directory(path: Path, *, mode: int) -> None:
    path.mkdir(mode=mode)
    path.chmod(mode)
    _fsync_directory(path.parent)


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


def _fsync_file(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def _require_safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{field}_invalid")
    return value


def _require_reddit_source_url(value: object) -> str:
    if not isinstance(value, str) or not value or any(
        character in value for character in ("\r", "\n", "\x00")
    ):
        raise RuntimeError("reddit_source_url_invalid")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("reddit_source_url_invalid") from exc
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or not parsed.path.startswith("/")
        or hostname is None
        or not (
            hostname == "reddit.com"
            or hostname.endswith(".reddit.com")
            or hostname == "redd.it"
        )
    ):
        raise RuntimeError("reddit_source_url_invalid")
    return value


def _canonical_reddit_discussion_url(post: Mapping[str, object]) -> str:
    value = post.get("source_url")
    if not isinstance(value, str) or not value or any(
        character in value for character in ("\r", "\n", "\x00")
    ):
        raise RuntimeError("reddit_source_url_invalid")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("reddit_source_url_invalid") from exc
    is_reddit_gallery = (
        hostname in {"reddit.com", "www.reddit.com"}
        and parsed.path.startswith("/gallery/")
    )
    is_reddit_media = hostname in _REDDIT_MEDIA_HOSTS
    if not is_reddit_gallery and not is_reddit_media:
        return _require_reddit_source_url(value)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise RuntimeError("reddit_source_url_invalid")
    post_id = post.get("post_id")
    subreddit = post.get("subreddit")
    if (
        not isinstance(post_id, str)
        or _REDDIT_POST_ID.fullmatch(post_id) is None
        or not isinstance(subreddit, str)
        or _SUBREDDIT.fullmatch(subreddit) is None
    ):
        raise RuntimeError("reddit_source_url_invalid")
    if is_reddit_gallery and parsed.path != f"/gallery/{post_id}":
        raise RuntimeError("reddit_source_url_invalid")
    return f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/"


def _canonicalize_visible_reddit_source_urls(
    source: DailyReportSource,
) -> DailyReportSource:
    posts: list[Mapping[str, object]] = []
    for post in source.posts:
        normalized = dict(post)
        normalized["source_url"] = _canonical_reddit_discussion_url(post)
        posts.append(normalized)
    return DailyReportSource(
        run=source.run,
        posts=tuple(posts),
        comments_by_post=source.comments_by_post,
        analysis_by_post=source.analysis_by_post,
        recent_threads=source.recent_threads,
    )


def _require_https_artifact_base_url(value: object) -> str:
    canonical = "https://reddit.lute-tlz-dddd.top/artifacts"
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(character in value for character in ("\r", "\n", "\x00", "\\"))
    ):
        raise ValueError("artifact_base_url_invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("artifact_base_url_invalid") from exc
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("artifact_base_url_invalid") from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc != "reddit.lute-tlz-dddd.top"
        or hostname != "reddit.lute-tlz-dddd.top"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is not None
        or value.rstrip("/") != canonical
    ):
        raise ValueError("artifact_base_url_invalid")
    return canonical


def validate_prepared_public_artifact_url(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or any(character in value for character in ("\r", "\n", "\x00", "\\"))
    ):
        raise ValueError("artifact_url_invalid")
    try:
        value.encode("ascii")
        parsed = urlsplit(value)
        port = parsed.port
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("artifact_url_invalid") from exc
    path = parsed.path
    path_match = re.fullmatch(
        r"/artifacts/prepared/"
        r"(?P<run_id>[A-Za-z0-9][A-Za-z0-9._:-]{0,127})/"
        r"(?P<version>[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32})/"
        r"(?P<name>[A-Za-z0-9][A-Za-z0-9._:-]{0,255})",
        path,
    )
    expected_names: set[str] = set()
    if path_match is not None:
        run_id = path_match.group("run_id")
        expected_names = {
            f"{run_id}-insight-report.html",
            f"{run_id}-daily-detail.xlsx",
            f"{run_id}-daily-detail.csv",
            f"{run_id}-insight-report-screenshot.png",
        }
    if (
        parsed.scheme != "https"
        or parsed.netloc != "reddit.lute-tlz-dddd.top"
        or parsed.hostname != "reddit.lute-tlz-dddd.top"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or path_match is None
        or path_match.group("name") not in expected_names
    ):
        raise ValueError("artifact_url_invalid")
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
    if not isinstance(value, str) or _REASON.fullmatch(value) is None:
        raise ValueError(f"{field}_invalid")
    return value


def _normalized_reasons(values: Sequence[str]) -> tuple[str, ...]:
    if not values:
        raise ValueError("reason_codes_empty")
    return tuple(sorted({_require_reason(value, "reason_code") for value in values}))
