#!/usr/bin/env python3
"""Stage a local-only frontend preview with a validated translation Base.

The source release stage is copied to a new immutable directory.  Only the
copied current-release pointer is rebound to the translated Base.  This command
never deploys, writes remotely, or changes the source stage or production.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, Mapping


RECEIPT_SCHEMA = "reddit_voc_translation_preview_stage_receipt_v1"
VALIDATION_RECEIPT_SCHEMA = "reddit_voc_translation_candidate_validation_receipt_v1"


class TranslationPreviewStageError(ValueError):
    pass


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TranslationPreviewStageError(f"unsafe_or_missing_json:{path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TranslationPreviewStageError(f"invalid_json:{path.name}") from exc
    if not isinstance(value, dict):
        raise TranslationPreviewStageError(f"invalid_json_shape:{path.name}")
    return value


def _write(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise TranslationPreviewStageError(f"output_collision:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _safe_identifier(value: object, *, prefix: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(prefix)
        or not 3 <= len(value) <= 128
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in value)
    ):
        raise TranslationPreviewStageError(f"invalid_{label}")
    return value


def _require_false_boundaries(value: object, *, label: str) -> None:
    if not isinstance(value, Mapping) or not (
        value.get("database_write") is False
        and value.get("remote_write") is False
        and value.get("deploy") is False
        and value.get("live_send") is False
        and value.get("production_unchanged") is True
    ):
        raise TranslationPreviewStageError(f"{label}_boundaries_invalid")


def stage_preview(
    *,
    source_stage_root: Path,
    candidate_root: Path,
    validation_receipt_path: Path,
    output_stage_root: Path,
    release_id: str,
    generated_at_utc: str,
) -> dict[str, object]:
    if source_stage_root.is_symlink() or not source_stage_root.is_dir():
        raise TranslationPreviewStageError("source_stage_root_unsafe")
    if candidate_root.is_symlink() or not candidate_root.is_dir():
        raise TranslationPreviewStageError("candidate_root_unsafe")
    if output_stage_root.exists() or output_stage_root.is_symlink():
        raise TranslationPreviewStageError("output_stage_root_must_not_exist")
    source_resolved = source_stage_root.resolve()
    output_resolved = output_stage_root.resolve(strict=False)
    if source_resolved == output_resolved or source_resolved in output_resolved.parents:
        raise TranslationPreviewStageError("output_stage_root_must_be_outside_source_stage")
    release_id = _safe_identifier(
        release_id,
        prefix="reddit_voc_release_",
        label="release_id",
    )
    try:
        parsed = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TranslationPreviewStageError("generated_at_utc_invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TranslationPreviewStageError("generated_at_utc_not_utc")

    candidate_manifest_path = candidate_root / "manifest-public.json"
    candidate_manifest = _load(candidate_manifest_path)
    validation = _load(validation_receipt_path)
    candidate_version = _safe_identifier(
        candidate_manifest.get("dataset_version"),
        prefix="reddit_voc_site_snapshot_",
        label="candidate_dataset_version",
    )
    translations = candidate_manifest.get("translations")
    if not isinstance(translations, dict):
        raise TranslationPreviewStageError("candidate_translation_manifest_missing")
    _require_false_boundaries(candidate_manifest.get("boundaries"), label="candidate")
    if not (
        candidate_manifest.get("status") == "validated_local_translation_candidate"
        and candidate_manifest.get("promotable") is False
        and candidate_manifest.get("provider_call") is True
        and translations.get("provider_call") is True
        and translations.get("independent_human_review") is False
        and translations.get("semantic_validation") == "not_run"
    ):
        raise TranslationPreviewStageError("candidate_contract_invalid")
    checks = validation.get("checks")
    quality_boundaries = validation.get("quality_boundaries")
    coverage = translations.get("coverage")
    partial_comments = (
        isinstance(coverage, dict)
        and coverage.get("comments_status") == "partial"
        and coverage.get("comments_unavailable_reason")
        == "provider_http_402_balance_blocked"
        and isinstance(coverage.get("comments"), int)
        and isinstance(coverage.get("comments_total"), int)
        and coverage["comments"] < coverage["comments_total"]
    )
    required_true_checks = {
        "source_files_byte_identical",
        "sidecar_integrity_passed",
        "source_hash_binding_passed",
        "checkpoint_binding_passed",
        "prompt_and_terms_binding_passed",
        "provider_attempt_ledger_passed",
        "deterministic_translation_gate_passed",
        "complete_post_coverage",
        "partial_comments_reason_evidence_bound",
    }
    _require_false_boundaries(validation.get("side_effect_boundaries"), label="validation")
    if not (
        validation.get("schema_version") == VALIDATION_RECEIPT_SCHEMA
        and validation.get("status") == "passed_local_candidate_only"
        and validation.get("candidate_dataset_version") == candidate_version
        and validation.get("candidate_public_manifest_sha256")
        == _sha(candidate_manifest_path)
        and validation.get("source_dataset_version")
        == translations.get("source_dataset_version")
        and validation.get("source_public_manifest_sha256")
        == translations.get("source_public_manifest_sha256")
        and isinstance(checks, dict)
        and all(checks.get(name) is True for name in required_true_checks)
        and checks.get("complete_comment_coverage") is (not partial_comments)
        and isinstance(quality_boundaries, dict)
        and quality_boundaries.get("promotable") is False
        and quality_boundaries.get("semantic_validation") == "not_run"
        and quality_boundaries.get("independent_human_review") is False
    ):
        raise TranslationPreviewStageError("validation_receipt_binding_invalid")

    source_public_root = source_stage_root / "public"
    source_pointer_path = source_public_root / "data/reddit-voc/current-release.json"
    pointer = _load(source_pointer_path)
    datasets = pointer.get("datasets")
    if not isinstance(datasets, dict) or not isinstance(datasets.get("base"), dict):
        raise TranslationPreviewStageError("source_pointer_base_binding_missing")
    base_binding = datasets["base"]
    if not (
        base_binding.get("dataset_version") == translations.get("source_dataset_version")
        and base_binding.get("public_manifest_sha256")
        == translations.get("source_public_manifest_sha256")
    ):
        raise TranslationPreviewStageError("source_pointer_base_binding_mismatch")
    source_candidate_destination = (
        source_public_root / "data/reddit-voc" / candidate_version
    )
    if source_candidate_destination.exists() or source_candidate_destination.is_symlink():
        raise TranslationPreviewStageError("candidate_destination_collision")

    shutil.copytree(source_stage_root, output_stage_root, symlinks=False)
    public_root = output_stage_root / "public"
    pointer_path = public_root / "data/reddit-voc/current-release.json"
    destination = public_root / "data/reddit-voc" / candidate_version
    shutil.copytree(candidate_root, destination, symlinks=False)
    base_binding["dataset_version"] = candidate_version
    base_binding["manifest_path"] = (
        f"data/reddit-voc/{candidate_version}/manifest-public.json"
    )
    base_binding["public_manifest_sha256"] = _sha(candidate_manifest_path)
    pointer["release_id"] = release_id
    pointer["generated_at_utc"] = generated_at_utc
    pointer_path.unlink()
    _write(pointer_path, pointer)

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "staged_local_preview_only",
        "release_id": release_id,
        "generated_at_utc": generated_at_utc,
        "source_stage_root": source_stage_root.as_posix(),
        "source_dataset_version": translations["source_dataset_version"],
        "candidate_dataset_version": candidate_version,
        "candidate_public_manifest_sha256": _sha(candidate_manifest_path),
        "comments_translated": coverage.get("comments") if isinstance(coverage, dict) else None,
        "comments_total": coverage.get("comments_total") if isinstance(coverage, dict) else None,
        "comments_status": coverage.get("comments_status") if isinstance(coverage, dict) else None,
        "comments_unavailable_reason": (
            coverage.get("comments_unavailable_reason")
            if isinstance(coverage, dict)
            else None
        ),
        "translation_validation_receipt_sha256": _sha(validation_receipt_path),
        "current_release_path": pointer_path.as_posix(),
        "current_release_sha256": _sha(pointer_path),
        "quality_boundaries": {
            "semantic_validation": "not_run",
            "independent_human_review": False,
            "promotable": False,
        },
        "side_effect_boundaries": {
            "provider_call": False,
            "database_write": False,
            "remote_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
        },
    }
    _write(output_stage_root / "translation-preview-stage-receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-stage-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--validation-receipt", type=Path, required=True)
    parser.add_argument("--output-stage-root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--generated-at-utc", required=True)
    args = parser.parse_args()
    receipt = stage_preview(
        source_stage_root=args.source_stage_root,
        candidate_root=args.candidate_root,
        validation_receipt_path=args.validation_receipt,
        output_stage_root=args.output_stage_root,
        release_id=args.release_id,
        generated_at_utc=args.generated_at_utc,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
