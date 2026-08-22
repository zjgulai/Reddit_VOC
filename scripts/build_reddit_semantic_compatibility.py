#!/usr/bin/env python3
"""Project an approved semantic audit onto one immutable current Base.

The projection carries governance conclusions, not a claim of new review.  All
population fields are recomputed from the target Base.  The command is local
only and binds the exact final identity-ledger receipt supplied by the caller.
"""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, cast


PROJECTION_SCHEMA = "reddit_voc_semantic_governance_projection_v1"
SOURCE_AUDIT_SCHEMA = "reddit_voc_tag_semantic_audit_v1"
LEDGER_MANIFEST_SCHEMA = "reddit_voc_candidate_ledger_manifest_v2"
LEDGER_MANIFEST_STATUS = "a2_identity_closed_with_explicit_coverage_debt"
LEDGER_RECEIPT_SCHEMA = "reddit_voc_candidate_ledger_validation_receipt_v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LEGACY_FIELDS = ("headline", "signals", "reference_dimensions", "held_tags")


class SemanticCompatibilityError(ValueError):
    """A source audit cannot be carried onto the requested Base."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lf_sha(values: list[str]) -> str:
    return sha256("".join(f"{value}\n" for value in sorted(values)).encode()).hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise SemanticCompatibilityError(f"{label}_unsafe")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise SemanticCompatibilityError(f"{label}_missing") from exc
    if not resolved.is_file():
        raise SemanticCompatibilityError(f"{label}_not_file")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SemanticCompatibilityError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise SemanticCompatibilityError(f"{label}_not_object")
    return cast(dict[str, Any], value)


def _load_rows(path: Path, *, label: str) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise SemanticCompatibilityError(f"{label}_unsafe")
    try:
        value = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SemanticCompatibilityError(f"{label}_invalid_json") from exc
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise SemanticCompatibilityError(f"{label}_not_object_list")
    return cast(list[dict[str, Any]], value)


def _file_contract(path: Path) -> dict[str, int | str]:
    return {"bytes": path.stat().st_size, "sha256": _sha(path)}


def _verify_file_contract(
    root: Path, files: dict[str, Any], name: str, *, label: str
) -> None:
    contract = files.get(name)
    path = root / name
    if (
        not isinstance(contract, dict)
        or path.is_symlink()
        or not path.is_file()
        or contract.get("bytes") != path.stat().st_size
        or contract.get("sha256") != _sha(path)
    ):
        raise SemanticCompatibilityError(f"{label}_{name}_contract_mismatch")


def _string_list(value: object, *, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise SemanticCompatibilityError(f"{label}_invalid")
    return cast(list[str], value)


def _false_side_effects(value: dict[str, Any], *, label: str) -> None:
    if value.get("production_unchanged") is not True:
        raise SemanticCompatibilityError(f"{label}_production_boundary_invalid")
    for field in (
        "provider_call",
        "provider_attempt_made",
        "database_write",
        "remote_write",
        "deployment",
        "production_merge",
        "live_send",
    ):
        if field in value and value[field] is not False:
            raise SemanticCompatibilityError(f"{label}_{field}_invalid")


def _tag_match(row: dict[str, Any], tag_id: str) -> dict[str, Any] | None:
    tagging = row.get("tagging")
    matches = tagging.get("matches") if isinstance(tagging, dict) else None
    if not isinstance(matches, list):
        raise SemanticCompatibilityError("base_tagging_contract_invalid")
    found = [
        match
        for match in matches
        if isinstance(match, dict) and match.get("tag_id") == tag_id
    ]
    if len(found) > 1:
        raise SemanticCompatibilityError("base_duplicate_tag_match")
    return cast(dict[str, Any], found[0]) if found else None


def _population(
    tag_id: str,
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> dict[str, int]:
    post_count = sum(_tag_match(row, tag_id) is not None for row in posts)
    comment_count = sum(
        row.get("include_in_voc_metrics") is True
        and _tag_match(row, tag_id) is not None
        for row in comments
    )
    return {
        "post_entities": post_count,
        "comment_entities": comment_count,
        "total_entities": post_count + comment_count,
    }


def _compatible_sample(
    sample: dict[str, Any],
    *,
    tag_id: str,
    posts_by_id: dict[str, dict[str, Any]],
    comments_by_id: dict[str, dict[str, Any]],
) -> bool:
    entity_type = sample.get("entity_type")
    entity_id = sample.get("entity_id")
    if not isinstance(entity_id, str) or entity_type not in {"post", "comment"}:
        raise SemanticCompatibilityError("source_audit_sample_identity_invalid")
    row = (posts_by_id if entity_type == "post" else comments_by_id).get(entity_id)
    if row is None or (
        entity_type == "comment" and row.get("include_in_voc_metrics") is not True
    ):
        return False
    match = _tag_match(row, tag_id)
    if match is None:
        return False
    source_keywords = _string_list(
        sample.get("evidence_keywords"), label="source_audit_evidence_keywords"
    )
    current_keywords = _string_list(
        match.get("evidence_keywords"), label="base_evidence_keywords"
    )
    return [item.casefold().strip() for item in current_keywords] == [
        item.casefold().strip() for item in source_keywords
    ]


def _evidence_examples(
    tag: dict[str, Any], compatible_ids: set[str], *, limit: int = 4
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    samples = tag.get("samples")
    if not isinstance(samples, list):
        raise SemanticCompatibilityError("source_audit_samples_invalid")
    for sample in samples:
        if not isinstance(sample, dict) or sample.get("audit_id") not in compatible_ids:
            continue
        review = sample.get("review")
        if not isinstance(review, dict) or not (
            review.get("label_verdict") == "correct"
            and review.get("taxonomy_fit") == "fit"
        ):
            continue
        rows.append(
            {
                field: sample[field]
                for field in (
                    "audit_id",
                    "entity_type",
                    "entity_id",
                    "reddit_id",
                    "post_id",
                    "subreddit",
                    "created_at_utc",
                    "evidence_keywords",
                    "context_excerpt",
                )
                if field in sample
            }
            | {
                "review_reason_code": review.get("reason_code"),
                "evidence_source": "source_audit_reviewed_context",
            }
        )
    rows.sort(key=lambda row: (row.get("entity_type") != "post", row["audit_id"]))
    return rows[:limit]


def build_projection(
    *,
    base_dir: Path,
    source_audit_path: Path,
    expected_source_audit_sha256: str,
    candidate_ledger_manifest_path: Path,
    ledger_validation_receipt_path: Path,
    expected_ledger_validation_receipt_sha256: str,
) -> dict[str, Any]:
    for value, label in (
        (expected_source_audit_sha256, "expected_source_audit_sha256"),
        (
            expected_ledger_validation_receipt_sha256,
            "expected_ledger_validation_receipt_sha256",
        ),
    ):
        if SHA256_RE.fullmatch(value) is None:
            raise SemanticCompatibilityError(f"{label}_invalid")

    base_manifest_path = base_dir / "manifest.json"
    base_manifest = _load_object(base_manifest_path, label="base_manifest")
    if base_manifest.get("schema_version") not in {
        "reddit_voc_site_snapshot_manifest_v1",
        "reddit_voc_site_snapshot_manifest_v2",
    } or base_manifest.get("all_checks_passed") is not True:
        raise SemanticCompatibilityError("base_manifest_not_validated")
    files = base_manifest.get("files")
    if not isinstance(files, dict):
        raise SemanticCompatibilityError("base_manifest_files_invalid")
    for name in ("posts.json", "comments.json", "tag-dictionary.json"):
        _verify_file_contract(base_dir, files, name, label="base")
    base_sha = _sha(base_manifest_path)

    source_audit = _load_object(source_audit_path, label="source_audit")
    if _sha(source_audit_path) != expected_source_audit_sha256:
        raise SemanticCompatibilityError("source_audit_sha256_mismatch")
    if source_audit.get("schema_version") != SOURCE_AUDIT_SCHEMA:
        raise SemanticCompatibilityError("source_audit_schema_invalid")

    ledger_manifest = _load_object(
        candidate_ledger_manifest_path, label="candidate_ledger_manifest"
    )
    ledger_manifest_sha = _sha(candidate_ledger_manifest_path)
    if (
        ledger_manifest.get("schema_version") != LEDGER_MANIFEST_SCHEMA
        or ledger_manifest.get("status") != LEDGER_MANIFEST_STATUS
        or not isinstance(ledger_manifest.get("accounting"), dict)
        or ledger_manifest["accounting"].get("unaccounted_total") != 0
        or not isinstance(ledger_manifest.get("inputs"), dict)
        or ledger_manifest["inputs"].get("candidate_base_manifest_sha256")
        != base_sha
    ):
        raise SemanticCompatibilityError("candidate_ledger_manifest_invalid")
    _false_side_effects(ledger_manifest, label="candidate_ledger_manifest")

    receipt = _load_object(
        ledger_validation_receipt_path, label="ledger_validation_receipt"
    )
    receipt_sha = _sha(ledger_validation_receipt_path)
    if receipt_sha != expected_ledger_validation_receipt_sha256:
        raise SemanticCompatibilityError("ledger_validation_receipt_sha256_mismatch")
    if (
        receipt.get("schema_version") != LEDGER_RECEIPT_SCHEMA
        or receipt.get("status") != "passed"
        or receipt.get("candidate_ledger_manifest_sha256") != ledger_manifest_sha
        or not isinstance(receipt.get("counts"), dict)
        or receipt["counts"].get("unaccounted_total") != 0
    ):
        raise SemanticCompatibilityError("ledger_validation_receipt_invalid")
    _false_side_effects(receipt, label="ledger_validation_receipt")

    posts = _load_rows(base_dir / "posts.json", label="base_posts")
    comments = _load_rows(base_dir / "comments.json", label="base_comments")
    dictionary = _load_object(base_dir / "tag-dictionary.json", label="dictionary")
    if (
        source_audit.get("dictionary_version") != dictionary.get("dictionary_version")
        or source_audit.get("dictionary_sha256") != dictionary.get("dictionary_sha256")
    ):
        raise SemanticCompatibilityError("dictionary_lineage_mismatch")
    rules_value = dictionary.get("rules")
    if not isinstance(rules_value, list):
        raise SemanticCompatibilityError("dictionary_rules_invalid")
    rules = {
        row["tag_id"]: row
        for row in rules_value
        if isinstance(row, dict) and isinstance(row.get("tag_id"), str)
    }

    summary = source_audit.get("summary")
    tags_value = source_audit.get("tags")
    if not isinstance(summary, dict) or not isinstance(tags_value, list):
        raise SemanticCompatibilityError("source_audit_contract_invalid")
    promoted = _string_list(
        summary.get("promoted_tag_ids"), label="source_audit_promoted_tag_ids"
    )
    held = _string_list(
        summary.get("held_tag_ids"), label="source_audit_held_tag_ids"
    )
    if set(promoted) & set(held) or set(promoted) | set(held) != {
        tag.get("tag_id") for tag in tags_value if isinstance(tag, dict)
    }:
        raise SemanticCompatibilityError("source_audit_tag_partition_invalid")
    if not set(promoted) | set(held) <= set(rules):
        raise SemanticCompatibilityError("source_audit_tag_outside_dictionary")

    posts_by_id = {str(row.get("post_id")): row for row in posts}
    comments_by_id = {str(row.get("comment_id")): row for row in comments}
    compatible_ids: list[str] = []
    incompatible_ids: list[str] = []
    promoted_source = 0
    promoted_compatible = 0
    tag_compatibility: list[dict[str, Any]] = []
    population_by_tag: dict[str, dict[str, int]] = {}
    tags_by_id: dict[str, dict[str, Any]] = {}

    for value in tags_value:
        if not isinstance(value, dict) or not isinstance(value.get("tag_id"), str):
            raise SemanticCompatibilityError("source_audit_tag_invalid")
        tag = cast(dict[str, Any], value)
        tag_id = cast(str, tag["tag_id"])
        tags_by_id[tag_id] = tag
        samples = tag.get("samples")
        if not isinstance(samples, list):
            raise SemanticCompatibilityError("source_audit_samples_invalid")
        tag_compatible = 0
        for sample_value in samples:
            if not isinstance(sample_value, dict) or not isinstance(
                sample_value.get("audit_id"), str
            ):
                raise SemanticCompatibilityError("source_audit_sample_invalid")
            sample = cast(dict[str, Any], sample_value)
            audit_id = cast(str, sample["audit_id"])
            compatible = _compatible_sample(
                sample,
                tag_id=tag_id,
                posts_by_id=posts_by_id,
                comments_by_id=comments_by_id,
            )
            (compatible_ids if compatible else incompatible_ids).append(audit_id)
            tag_compatible += int(compatible)
        if tag_id in promoted:
            promoted_source += len(samples)
            promoted_compatible += tag_compatible
            if tag_compatible != len(samples):
                raise SemanticCompatibilityError(
                    f"promoted_review_assignment_incompatible:{tag_id}"
                )
        population = _population(tag_id, posts, comments)
        population_by_tag[tag_id] = population
        tag_compatibility.append(
            {
                "tag_id": tag_id,
                "disposition": "promoted" if tag_id in promoted else "held",
                "source_reviewed_assignments": len(samples),
                "compatible_assignments": tag_compatible,
                "current_population": population,
                "source_review_metrics": tag.get("review_metrics"),
                "source_gate_checks": tag.get("gate_checks"),
            }
        )

    source_reviewed = sum(
        row["source_reviewed_assignments"] for row in tag_compatibility
    )
    if source_reviewed != summary.get("reviewed_assignments"):
        raise SemanticCompatibilityError("source_audit_reviewed_count_mismatch")

    promoted_set = set(promoted)
    unique_posts = sum(
        any(_tag_match(row, tag_id) is not None for tag_id in promoted_set)
        for row in posts
    )
    unique_comments = sum(
        row.get("include_in_voc_metrics") is True
        and any(_tag_match(row, tag_id) is not None for tag_id in promoted_set)
        for row in comments
    )
    promoted_assignments = sum(
        population_by_tag[tag_id]["total_entities"] for tag_id in promoted
    )

    reference_fields = (
        "consumer_card",
        "aipl_node",
        "story_lines",
        "intent_type",
        "problem_type",
    )
    reference_dimensions: dict[str, dict[str, int]] = {}
    for field in reference_fields:
        counts: Counter[str] = Counter()
        for tag_id in promoted:
            reference = tags_by_id[tag_id].get("dictionary_reference")
            if not isinstance(reference, dict) or not isinstance(reference.get(field), str):
                raise SemanticCompatibilityError("source_audit_dictionary_reference_invalid")
            counts[reference[field]] += population_by_tag[tag_id]["total_entities"]
        reference_dimensions[field] = dict(counts.most_common())

    compatible_set = set(compatible_ids)
    signals = []
    for tag_id in promoted:
        tag = tags_by_id[tag_id]
        population = population_by_tag[tag_id]
        signals.append(
            {
                "tag_id": tag_id,
                "name_cn": tag.get("name_cn"),
                "name_en": tag.get("name_en"),
                "theme": tag.get("theme"),
                "matched_posts": population["post_entities"],
                "matched_comments": population["comment_entities"],
                "matched_entities": population["total_entities"],
                "review_metrics": tag.get("review_metrics"),
                "dictionary_reference": tag.get("dictionary_reference"),
                "evidence_examples": _evidence_examples(tag, compatible_set),
            }
        )
    held_tags = []
    for tag_id in held:
        tag = tags_by_id[tag_id]
        held_tags.append(
            {
                "tag_id": tag_id,
                "name_cn": tag.get("name_cn"),
                "theme": tag.get("theme"),
                "matched_entities": population_by_tag[tag_id]["total_entities"],
                "review_metrics": tag.get("review_metrics"),
                "governance_review": tag.get("governance_review"),
                "failed_checks": [
                    name
                    for name, passed in cast(
                        dict[str, Any], tag.get("gate_checks", {})
                    ).items()
                    if passed is not True
                ],
            }
        )

    base_version = base_manifest.get("dataset_version")
    governance_version = f"{source_audit.get('audit_version')}__{base_sha[:12]}"
    legacy_insights = {
        "headline": {
            "audited_tags": len(tags_by_id),
            "promoted_tags": len(promoted),
            "held_tags": len(held),
            "reviewed_assignments": None,
            "source_reviewed_assignments": source_reviewed,
            "compatible_source_assignments": len(compatible_ids),
            "promoted_rule_assignments": promoted_assignments,
            "unique_posts_with_promoted_tags": unique_posts,
            "unique_comments_with_promoted_tags": unique_comments,
        },
        "signals": signals,
        "reference_dimensions": reference_dimensions,
        "held_tags": held_tags,
        "interpretation_boundaries": {
            "counts_are_rule_matched_entities_not_users": True,
            "promoted_means_source_sample_gate_passed_not_new_base_review": True,
            "consumer_card_is_reference_not_persona_id": True,
            "persona_tags_generated": False,
            "market_share_supported": False,
            "roi_supported": False,
            "trend_claim_supported": False,
        },
        "boundaries": {
            "scope": "source_governance_current_base_population_projection",
            "independent_human_review": False,
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
        },
        "compatibility_contract": {
            "status": "current_base_recomputed_governance_projection",
            "recomputed_fields": list(LEGACY_FIELDS),
            "source_fields_carried_without_population_counts": [
                "review_metrics",
                "governance_review",
                "failed_checks",
            ],
            "current_base_manifest_sha256": base_sha,
            "source_semantic_audit_sha256": expected_source_audit_sha256,
            "candidate_ledger_manifest_sha256": ledger_manifest_sha,
            "ledger_validation_receipt_sha256": receipt_sha,
            "new_review_performed": False,
        },
    }
    return {
        "schema_version": PROJECTION_SCHEMA,
        "governance_version": governance_version,
        "projection_mode": "governance_projection_no_new_review",
        "promoted_tag_ids": promoted,
        "held_tag_ids": held,
        "source_audit": {
            "source_name": source_audit_path.name,
            "sha256": expected_source_audit_sha256,
            "schema_version": source_audit.get("schema_version"),
            "audit_version": source_audit.get("audit_version"),
            "base_dataset_version": source_audit.get("base_dataset_version"),
            "base_manifest_sha256": source_audit.get("base_manifest_sha256"),
            "sample_sha256": source_audit.get("sample_sha256"),
            "quality_gate": source_audit.get("quality_gate"),
        },
        "target_base": {
            "dataset_version": base_version,
            "manifest_sha256": base_sha,
        },
        "dictionary_version": dictionary.get("dictionary_version"),
        "dictionary_sha256": dictionary.get("dictionary_sha256"),
        "identity_gate": {
            "candidate_ledger_manifest_sha256": ledger_manifest_sha,
            "ledger_validation_receipt_sha256": receipt_sha,
            "input_evidence_sha256": receipt.get("input_evidence_sha256"),
            "unaccounted_total": 0,
        },
        "compatibility_summary": {
            "source_reviewed_assignments": source_reviewed,
            "compatible_source_assignments": len(compatible_ids),
            "incompatible_or_absent_source_assignments": len(incompatible_ids),
            "promoted_source_assignments": promoted_source,
            "promoted_compatible_assignments": promoted_compatible,
            "promoted_retention_gate_passed": promoted_source
            == promoted_compatible,
            "compatible_audit_ids_lf_sha256": _lf_sha(compatible_ids),
            "incompatible_audit_ids_lf_sha256": _lf_sha(incompatible_ids),
            "evidence_match_contract": "entity_identity_tag_assignment_and_evidence_keywords_v1",
        },
        "tag_compatibility": sorted(
            tag_compatibility, key=lambda row: cast(str, row["tag_id"])
        ),
        "legacy_insights": legacy_insights,
        "boundaries": {
            "new_review_performed": False,
            "raw_review_samples_included": False,
            "held_tags_remain_excluded_without_new_review": True,
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "remote_write": False,
            "live_send": False,
            "deploy": False,
        },
    }


def write_projection(path: Path, projection: dict[str, Any]) -> dict[str, Any]:
    payload = _canonical_bytes(projection)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise SemanticCompatibilityError("output_collision")
        status = "no_change"
    else:
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            os.write(handle, payload)
            os.close(handle)
            handle = -1
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if handle >= 0:
                os.close(handle)
            if temporary.exists():
                temporary.unlink()
        status = "created"
    os.chmod(path, 0o600)
    return {
        "status": status,
        "schema_version": PROJECTION_SCHEMA,
        "output": _file_contract(path),
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "remote_write": False,
        "live_send": False,
        "deploy": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--expected-source-audit-sha256", required=True)
    parser.add_argument("--candidate-ledger-manifest", type=Path, required=True)
    parser.add_argument("--ledger-validation-receipt", type=Path, required=True)
    parser.add_argument("--expected-ledger-validation-receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    projection = build_projection(
        base_dir=args.base_dir.resolve(strict=True),
        source_audit_path=args.source_audit,
        expected_source_audit_sha256=args.expected_source_audit_sha256,
        candidate_ledger_manifest_path=args.candidate_ledger_manifest,
        ledger_validation_receipt_path=args.ledger_validation_receipt,
        expected_ledger_validation_receipt_sha256=args.expected_ledger_validation_receipt_sha256,
    )
    print(
        json.dumps(
            write_projection(args.output, projection),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
