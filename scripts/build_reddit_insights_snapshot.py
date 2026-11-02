#!/usr/bin/env python3
"""Build a versioned Reddit VOC insights overlay from reviewed tag samples."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any


MANIFEST_SCHEMA = "reddit_voc_insights_manifest_v1"
AUDIT_SCHEMA = "reddit_voc_tag_semantic_audit_v1"
INSIGHTS_SCHEMA = "reddit_voc_insights_v1"
DATASET_VERSION = "reddit_voc_insights_20260714_v1"
ALLOWED_LABEL_VERDICTS = {"correct", "incorrect", "ambiguous"}
ALLOWED_TAXONOMY_FIT = {"fit", "mismatch", "ambiguous"}

V3_INSIGHTS_SCHEMA = "reddit_voc_insights_v3"
V3_INSIGHTS_MANIFEST_SCHEMA = "reddit_voc_insights_manifest_v3"
V3_PUBLIC_INSIGHTS_SCHEMA = "reddit_voc_insights_public_v3"
V3_PUBLIC_INSIGHTS_MANIFEST_SCHEMA = "reddit_voc_insights_public_manifest_v3"
V3_EVIDENCE_REGISTRY_SCHEMA = "reddit_voc_evidence_registry_v3"
V3_REPORT_MANIFEST_SCHEMA = "reddit_voc_reports_manifest_v3"
V3_REPORT_PATHS = {
    f"{role}/{grain}.json"
    for role in ("current", "archive")
    for grain in ("daily", "weekly", "monthly")
}
V3_BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


class V3InsightsBuildError(ValueError):
    """A V3 evidence-bound insights fixture violates its governed contract."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _wilson_lower_bound(successes: int, total: int, *, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    center = proportion + z * z / (2 * total)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    )
    return (center - margin) / denominator


def _expanded_decision(
    tag_review: dict[str, Any], audit_id: str
) -> dict[str, str]:
    value = dict(tag_review["default_decision"])
    value.update(tag_review.get("overrides", {}).get(audit_id, {}))
    if value.get("label_verdict") not in ALLOWED_LABEL_VERDICTS:
        raise ValueError(f"invalid label verdict: {audit_id}")
    if value.get("taxonomy_fit") not in ALLOWED_TAXONOMY_FIT:
        raise ValueError(f"invalid taxonomy fit: {audit_id}")
    if not value.get("reason_code") or not value.get("note"):
        raise ValueError(f"incomplete review decision: {audit_id}")
    return value


def _evaluate_tag(
    tag: dict[str, Any],
    tag_review: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    reviewed_samples = []
    for sample in tag["samples"]:
        reviewed = dict(sample)
        reviewed["review"] = _expanded_decision(tag_review, sample["audit_id"])
        reviewed_samples.append(reviewed)

    verdict_counts = Counter(row["review"]["label_verdict"] for row in reviewed_samples)
    taxonomy_counts = Counter(row["review"]["taxonomy_fit"] for row in reviewed_samples)
    decidable = verdict_counts["correct"] + verdict_counts["incorrect"]
    precision = verdict_counts["correct"] / decidable if decidable else 0.0
    ambiguous_rate = verdict_counts["ambiguous"] / len(reviewed_samples)
    taxonomy_fit_rate = taxonomy_counts["fit"] / len(reviewed_samples)
    wilson_lower = _wilson_lower_bound(verdict_counts["correct"], decidable)
    governance = tag_review["governance_review"]

    checks = {
        "sample_count": len(reviewed_samples) >= gate["required_samples_per_tag"],
        "label_precision": precision >= gate["minimum_label_precision"],
        "wilson_lower_bound_95": wilson_lower
        >= gate["minimum_wilson_lower_bound_95"],
        "taxonomy_fit_rate": taxonomy_fit_rate >= gate["minimum_taxonomy_fit_rate"],
        "ambiguous_rate": ambiguous_rate <= gate["maximum_ambiguous_rate"],
        "governance_fit": governance["status"]
        == gate["governance_status_required"],
    }
    return {
        "tag_id": tag["tag_id"],
        "name_cn": tag["name_cn"],
        "name_en": tag["name_en"],
        "theme": tag["theme"],
        "definition": tag["definition"],
        "dictionary_reference": tag["dictionary_reference"],
        "population": tag["population"],
        "sample_counts": tag["sample_counts"],
        "governance_review": governance,
        "review_metrics": {
            "reviewed": len(reviewed_samples),
            "correct": verdict_counts["correct"],
            "incorrect": verdict_counts["incorrect"],
            "ambiguous": verdict_counts["ambiguous"],
            "label_precision": round(precision, 6),
            "wilson_lower_bound_95": round(wilson_lower, 6),
            "taxonomy_fit_rate": round(taxonomy_fit_rate, 6),
            "ambiguous_rate": round(ambiguous_rate, 6),
        },
        "gate_checks": checks,
        "promotion_status": "promoted" if all(checks.values()) else "held",
        "samples": reviewed_samples,
    }


def _evidence_examples(tag: dict[str, Any], *, limit: int = 4) -> list[dict[str, Any]]:
    correct = [
        sample
        for sample in tag["samples"]
        if sample["review"]["label_verdict"] == "correct"
        and sample["review"]["taxonomy_fit"] == "fit"
    ]
    correct.sort(
        key=lambda row: (
            row["entity_type"] != "post",
            row["source_stratum"],
            row["stable_rank"],
        )
    )
    return [
        {
            "audit_id": row["audit_id"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "reddit_id": row["reddit_id"],
            "post_id": row["post_id"],
            "subreddit": row["subreddit"],
            "created_at_utc": row["created_at_utc"],
            "source_stratum": row["source_stratum"],
            "evidence_keywords": row["evidence_keywords"],
            "context_excerpt": row["context_excerpt"],
            "review_reason_code": row["review"]["reason_code"],
        }
        for row in correct[:limit]
    ]


def _unique_promoted_entities(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    promoted_ids: set[str],
) -> tuple[int, int]:
    post_count = sum(
        bool(set(row["tagging"]["aspect_tag_ids"]) & promoted_ids) for row in posts
    )
    comment_count = sum(
        row["include_in_voc_metrics"]
        and bool(set(row["tagging"]["aspect_tag_ids"]) & promoted_ids)
        for row in comments
    )
    return post_count, comment_count


def build(
    snapshot_dir: Path,
    sample_path: Path,
    decisions_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base_manifest_path = snapshot_dir / "manifest.json"
    base_manifest = _load(base_manifest_path)
    posts = _load(snapshot_dir / "posts.json")
    comments = _load(snapshot_dir / "comments.json")
    sample = _load(sample_path)
    decisions = _load(decisions_path)

    if _sha256(sample_path) != decisions["sample_sha256"]:
        raise ValueError("review decisions are not bound to the current sample")
    if sample["base_dataset_version"] != base_manifest["dataset_version"]:
        raise ValueError("sample/base dataset version mismatch")
    if sample["base_manifest_sha256"] != _sha256(base_manifest_path):
        raise ValueError("sample/base manifest hash mismatch")
    if set(decisions["tag_reviews"]) != {tag["tag_id"] for tag in sample["tags"]}:
        raise ValueError("decision tag set does not match review sample")

    gate = decisions["quality_gate"]
    audited_tags = [
        _evaluate_tag(tag, decisions["tag_reviews"][tag["tag_id"]], gate)
        for tag in sample["tags"]
    ]
    promoted = [tag for tag in audited_tags if tag["promotion_status"] == "promoted"]
    held = [tag for tag in audited_tags if tag["promotion_status"] == "held"]
    promoted_ids = {tag["tag_id"] for tag in promoted}
    unique_posts, unique_comments = _unique_promoted_entities(
        posts, comments, promoted_ids
    )

    audit = {
        "schema_version": AUDIT_SCHEMA,
        "audit_version": DATASET_VERSION,
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": _sha256(base_manifest_path),
        "dictionary_version": sample["dictionary_version"],
        "dictionary_sha256": sample["dictionary_sha256"],
        "sample_sha256": decisions["sample_sha256"],
        "reviewer": decisions["reviewer"],
        "quality_gate": gate,
        "summary": {
            "audited_tags": len(audited_tags),
            "reviewed_assignments": sum(
                tag["review_metrics"]["reviewed"] for tag in audited_tags
            ),
            "promoted_tags": len(promoted),
            "held_tags": len(held),
            "promoted_tag_ids": [tag["tag_id"] for tag in promoted],
            "held_tag_ids": [tag["tag_id"] for tag in held],
            "status": "passed_with_scope_limits" if promoted else "failed_closed",
        },
        "tags": audited_tags,
        "boundaries": {
            "scope": "top_10_aspect_tags_stratified_assignment_review",
            "labels_outside_promoted_set_provisional": True,
            "independent_human_review": False,
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
        },
    }

    reference_fields = (
        "consumer_card",
        "aipl_node",
        "story_lines",
        "intent_type",
        "problem_type",
    )
    reference_dimensions: dict[str, dict[str, int]] = {}
    for field in reference_fields:
        counter: Counter[str] = Counter()
        for tag in promoted:
            counter[tag["dictionary_reference"][field]] += tag["population"][
                "total_entities"
            ]
        reference_dimensions[field] = dict(counter.most_common())

    signals = [
        {
            "tag_id": tag["tag_id"],
            "name_cn": tag["name_cn"],
            "name_en": tag["name_en"],
            "theme": tag["theme"],
            "matched_posts": tag["population"]["post_entities"],
            "matched_comments": tag["population"]["comment_entities"],
            "matched_entities": tag["population"]["total_entities"],
            "review_metrics": tag["review_metrics"],
            "dictionary_reference": tag["dictionary_reference"],
            "evidence_examples": _evidence_examples(tag),
        }
        for tag in promoted
    ]
    insights = {
        "schema_version": INSIGHTS_SCHEMA,
        "dataset_version": DATASET_VERSION,
        "base_dataset_version": base_manifest["dataset_version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "headline": {
            "audited_tags": len(audited_tags),
            "promoted_tags": len(promoted),
            "held_tags": len(held),
            "reviewed_assignments": audit["summary"]["reviewed_assignments"],
            "promoted_rule_assignments": sum(
                tag["population"]["total_entities"] for tag in promoted
            ),
            "unique_posts_with_promoted_tags": unique_posts,
            "unique_comments_with_promoted_tags": unique_comments,
        },
        "signals": signals,
        "reference_dimensions": reference_dimensions,
        "held_tags": [
            {
                "tag_id": tag["tag_id"],
                "name_cn": tag["name_cn"],
                "theme": tag["theme"],
                "matched_entities": tag["population"]["total_entities"],
                "review_metrics": tag["review_metrics"],
                "governance_review": tag["governance_review"],
                "failed_checks": [
                    name for name, passed in tag["gate_checks"].items() if not passed
                ],
            }
            for tag in held
        ],
        "interpretation_boundaries": {
            "counts_are_rule_matched_entities_not_users": True,
            "promoted_means_sample_gate_passed_not_full_population_human_review": True,
            "consumer_card_is_reference_not_persona_id": True,
            "persona_tags_generated": False,
            "persona_note": "consumer_card is a governed tag-to-insight-card mapping. User-level persona requires the independent dim_persona_v1 dual-track pipeline and was not inferred here.",
            "market_share_supported": False,
            "roi_supported": False,
            "trend_claim_supported": False,
        },
        "boundaries": audit["boundaries"],
    }

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "dataset_version": DATASET_VERSION,
        "delivery_mode": "versioned_static_insights_overlay",
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": _sha256(base_manifest_path),
        "dictionary_version": sample["dictionary_version"],
        "dictionary_sha256": sample["dictionary_sha256"],
        "status": audit["summary"]["status"],
        "audit_summary": audit["summary"],
        "files": {},
        "boundaries": audit["boundaries"],
    }
    return audit, insights, manifest


def write_snapshot(
    output_dir: Path,
    audit: dict[str, Any],
    insights: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / "semantic-audit.json"
    insights_path = output_dir / "insights.json"
    _write(audit_path, audit)
    _write(insights_path, insights)
    manifest["files"] = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in (audit_path, insights_path)
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest


def _v3_canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise V3InsightsBuildError(
            "V3 insights document is not canonical-JSON serializable"
        ) from exc


def _v3_validate_report_inputs(
    metrics_binding: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    report_index: dict[str, Any],
    report_manifest: dict[str, Any],
) -> str:
    from scripts.build_reddit_reports_snapshot import _v3_validate_binding

    try:
        _v3_validate_binding(metrics_binding)
    except ValueError as exc:
        raise V3InsightsBuildError(str(exc)) from exc
    if set(reports) != V3_REPORT_PATHS:
        raise V3InsightsBuildError("V3 reports input set is invalid")
    if (
        report_manifest.get("schema_version") != V3_REPORT_MANIFEST_SCHEMA
        or report_manifest.get("artifact_stage") != "fixture_reports"
        or report_manifest.get("fixture_only") is not True
        or report_manifest.get("promotable") is not False
        or report_manifest.get("boundaries") != V3_BOUNDARIES
        or report_manifest.get("metrics_manifest_sha256")
        != metrics_binding["manifest_sha256"]
        or report_manifest.get("metrics_validation_receipt_sha256")
        != metrics_binding["receipt_sha256"]
        or report_manifest.get("source_snapshot_id")
        != metrics_binding["source_snapshot_id"]
    ):
        raise V3InsightsBuildError("V3 reports manifest binding is invalid")
    expected_documents = {"report-index.json": report_index, **reports}
    files = report_manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(expected_documents):
        raise V3InsightsBuildError("V3 reports manifest file set is invalid")
    for name, document in expected_documents.items():
        payload = _v3_canonical_bytes(document)
        if files[name] != {
            "bytes": len(payload),
            "sha256": sha256(payload).hexdigest(),
        }:
            raise V3InsightsBuildError(f"V3 reports in-memory hash mismatch: {name}")
    if (
        report_index.get("business_entry_count") != 3
        or set(report_index.get("reports", {})) != {"daily", "weekly", "monthly"}
        or "current" in report_index
        or "archive" in report_index
    ):
        raise V3InsightsBuildError("V3 report index exposes invalid business entries")
    return sha256(_v3_canonical_bytes(report_manifest)).hexdigest()


def _v3_evidence_facts(
    evidence_registry: dict[str, Any], source_snapshot_id: str
) -> dict[str, dict[str, Any]]:
    if not isinstance(evidence_registry, dict) or set(evidence_registry) != {
        "facts",
        "schema_version",
        "source_snapshot_id",
    }:
        raise V3InsightsBuildError("V3 evidence registry fields are invalid")
    if (
        evidence_registry.get("schema_version") != V3_EVIDENCE_REGISTRY_SCHEMA
        or evidence_registry.get("source_snapshot_id") != source_snapshot_id
        or not isinstance(evidence_registry.get("facts"), dict)
    ):
        raise V3InsightsBuildError("V3 evidence registry binding is invalid")
    facts = evidence_registry["facts"]
    for fact_id, fact in facts.items():
        if (
            not isinstance(fact_id, str)
            or not fact_id
            or not isinstance(fact, dict)
            or fact.get("snapshot_id") != source_snapshot_id
        ):
            raise V3InsightsBuildError("V3 evidence fact is invalid")
    return facts


def build_v3_insights_snapshot(
    metrics_binding: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    report_index: dict[str, Any],
    report_manifest: dict[str, Any],
    evidence_registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build evidence-bound six-section V3 storylines from fixture reports."""

    from reddit_voc.v3_storylines import StorylineError, build_storyline

    report_manifest_sha = _v3_validate_report_inputs(
        metrics_binding, reports, report_index, report_manifest
    )
    source_snapshot_id = metrics_binding["source_snapshot_id"]
    evidence_facts = _v3_evidence_facts(evidence_registry, source_snapshot_id)
    storylines: list[dict[str, Any]] = []
    for grain in ("daily", "weekly", "monthly"):
        report = reports[f"current/{grain}.json"]
        if report.get("artifact_role") != "latest_complete_calendar_period":
            raise V3InsightsBuildError("V3 current report role is invalid")
        period = report.get("period", {})
        review_date = period.get("end")
        if not isinstance(review_date, str) or not review_date:
            raise V3InsightsBuildError("V3 monitoring review date is invalid")
        for card in report.get("indicators", []):
            current = card.get("current")
            comparison = card.get("comparisons", {}).get("period_over_period")
            if not isinstance(current, dict) or not isinstance(comparison, dict):
                raise V3InsightsBuildError("V3 report metric card is invalid")
            status = current.get("status")
            narrative_comparison = comparison
            if current.get("comparison_contract_proven") is not True:
                narrative_comparison = {
                    **comparison,
                    "direction": None,
                    "display": "—",
                    "line_color": "gray",
                    "reason_codes": sorted(
                        set(comparison.get("reason_codes", []))
                        | {"observed_comparison_not_a_formal_insight_claim"}
                    ),
                    "status": "unavailable",
                    "value": None,
                }
            direction = (
                comparison.get("direction")
                if status != "unavailable" and comparison.get("status") == "available"
                else None
            )
            try:
                storyline = build_storyline(
                    metric=current,
                    direction=direction,
                    root_cause_evidence_ids=current.get("evidence_ids", []),
                    evidence_registry=evidence_facts,
                    snapshot_id=source_snapshot_id,
                    comparison=narrative_comparison,
                    impact="该指标仅描述当前受治理观察样本，用于确定后续人工核查与运营优先级。",
                    action={
                        "approval_status": "proposed",
                        "owner_role": "VOC Insights",
                        "priority": "P1" if direction == "up" else "P2",
                    },
                    monitoring={
                        "cadence": grain,
                        "metric_id": current["metric_id"],
                        "review_date": review_date,
                    },
                )
            except StorylineError as exc:
                raise V3InsightsBuildError(str(exc)) from exc
            storylines.append({"grain": grain, **storyline})
    insights = {
        "boundaries": dict(V3_BOUNDARIES),
        "fixture_only": True,
        "interpretation_boundaries": {
            "direction_requires_comparable_complete_periods": True,
            "root_cause_requires_same_snapshot_evidence": True,
            "sales_causality_supported": False,
            "unavailable_metric_direction_supported": False,
        },
        "schema_version": V3_INSIGHTS_SCHEMA,
        "source": {
            "metrics_manifest_sha256": metrics_binding["manifest_sha256"],
            "metrics_validation_receipt_sha256": metrics_binding["receipt_sha256"],
            "report_manifest_sha256": report_manifest_sha,
            "source_snapshot_id": source_snapshot_id,
        },
        "storyline_count": len(storylines),
        "storylines": storylines,
    }
    insights_payload = _v3_canonical_bytes(insights)
    manifest = {
        "artifact_stage": "fixture_insights",
        "boundaries": dict(V3_BOUNDARIES),
        "files": {
            "insights.json": {
                "bytes": len(insights_payload),
                "sha256": sha256(insights_payload).hexdigest(),
            }
        },
        "fixture_only": True,
        "metrics_manifest_sha256": metrics_binding["manifest_sha256"],
        "metrics_validation_receipt_sha256": metrics_binding["receipt_sha256"],
        "promotable": False,
        "report_manifest_sha256": report_manifest_sha,
        "schema_version": V3_INSIGHTS_MANIFEST_SCHEMA,
        "source_snapshot_id": source_snapshot_id,
        "status": "fixture_only_waiting_for_periodized_metrics",
        "storyline_count": len(storylines),
    }
    return insights, manifest


def _v3_write_exact(path: Path, value: Any) -> None:
    payload = _v3_canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V3InsightsBuildError(f"V3 insights output collision: {path}")
        return
    path.write_bytes(payload)


def write_v3_insights_snapshot(
    output_dir: Path,
    insights: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise V3InsightsBuildError("V3 insights output root is invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    if {path.name for path in output_dir.iterdir()} - {"insights.json", "manifest.json"}:
        raise V3InsightsBuildError("V3 insights output root contains undeclared entries")
    _v3_write_exact(output_dir / "insights.json", insights)
    _v3_write_exact(output_dir / "manifest.json", manifest)
    return manifest


def build_v3_formal_insights_snapshot(
    formal_binding: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    report_index: dict[str, Any],
    report_manifest: dict[str, Any],
    report_validation_receipt: dict[str, Any],
    *,
    report_validation_receipt_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build formal six-section storylines from an independently validated report."""

    from scripts.build_reddit_reports_snapshot import (
        V3_REPORT_MANIFEST_SCHEMA,
        _v3_validate_formal_binding,
    )
    from reddit_voc.v3_storylines import StorylineError, build_storyline

    try:
        _v3_validate_formal_binding(formal_binding)
    except ValueError as exc:
        raise V3InsightsBuildError(str(exc)) from exc
    report_receipt_sha = report_validation_receipt_sha256
    periodized = formal_binding["periodized_metrics"]
    comparison_contract_proven = bool(
        periodized["comparison_contract_proven"]
    )
    comparison_contract_basis = periodized["comparison_contract_basis"]
    completeness_percent = 100 if comparison_contract_proven else None
    comparison_unavailable_reason_codes = list(
        periodized["comparison_unavailable_reason_codes"]
    )
    latest_daily_period = periodized["latest_complete_period_ids"]["daily"]
    try:
        latest_daily_start = latest_daily_period.split(":", 2)[1]
        coverage_end_token = datetime.fromisoformat(
            latest_daily_start
        ).date().strftime("%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise V3InsightsBuildError(
            "formal latest daily period is invalid"
        ) from exc
    if (
        not isinstance(report_receipt_sha, str)
        or len(report_receipt_sha) != 64
        or sha256(_v3_canonical_bytes(report_validation_receipt)).hexdigest()
        != report_receipt_sha
    ):
        raise V3InsightsBuildError("formal reports validation receipt SHA mismatch")
    report_manifest_sha = sha256(_v3_canonical_bytes(report_manifest)).hexdigest()
    dataset_version = (
        f"reddit_voc_insights_{coverage_end_token}_v3_"
        + formal_binding["candidate_manifest_sha256"][:12]
        + "_r"
        + report_manifest_sha[:12]
    )
    if (
        report_manifest.get("schema_version") != V3_REPORT_MANIFEST_SCHEMA
        or report_manifest.get("artifact_stage") != "reports_candidate"
        or report_manifest.get("status") != "candidate_built"
        or report_manifest.get("comparison_contract_proven")
        is not comparison_contract_proven
        or report_manifest.get("comparison_contract_basis")
        != comparison_contract_basis
        or report_manifest.get("completeness_percent")
        != completeness_percent
        or report_manifest.get("data_owner_coverage_attestation_sha256")
        != formal_binding["data_owner_coverage_attestation_sha256"]
        or report_validation_receipt.get("schema_version")
        != "reddit_voc_reports_validation_receipt_v3"
        or report_validation_receipt.get("status") != "passed_candidate_only"
        or report_validation_receipt.get("promotable") is not True
        or report_validation_receipt.get("bundle_manifest_sha256")
        != report_manifest_sha
        or report_validation_receipt.get(
            "data_owner_coverage_attestation_sha256"
        )
        != formal_binding["data_owner_coverage_attestation_sha256"]
    ):
        raise V3InsightsBuildError("formal reports validation binding is invalid")
    expected_documents = {"report-index.json": report_index, **reports}
    report_manifest_files = report_manifest.get("files", {})
    if (
        set(reports) != V3_REPORT_PATHS
        or not isinstance(report_manifest_files, dict)
        or not set(expected_documents).issubset(report_manifest_files)
    ):
        raise V3InsightsBuildError("formal reports file set is invalid")
    for name, document in expected_documents.items():
        payload = _v3_canonical_bytes(document)
        if report_manifest["files"][name] != {
            "bytes": len(payload),
            "sha256": sha256(payload).hexdigest(),
        }:
            raise V3InsightsBuildError(f"formal reports hash mismatch: {name}")
    evidence_ids = {
        evidence_id
        for grain in ("daily", "weekly", "monthly")
        for card in reports[f"current/{grain}.json"]["indicators"]
        for evidence_id in card["current"].get("evidence_ids", [])
    }
    evidence_registry = {
        evidence_id: {"snapshot_id": formal_binding["source_snapshot_id"]}
        for evidence_id in evidence_ids
    }
    storylines: list[dict[str, Any]] = []
    for grain in ("daily", "weekly", "monthly"):
        report = reports[f"current/{grain}.json"]
        for card in report["indicators"]:
            current = card["current"]
            comparison = card["comparisons"]["period_over_period"]
            narrative_comparison = comparison
            if not comparison_contract_proven:
                narrative_comparison = {
                    **comparison,
                    "direction": None,
                    "display": "—",
                    "line_color": "gray",
                    "reason_codes": sorted(
                        set(comparison.get("reason_codes", []))
                        | {"observed_comparison_not_a_formal_insight_claim"}
                    ),
                    "status": "unavailable",
                    "value": None,
                }
            direction = (
                comparison["direction"]
                if current["status"] != "unavailable"
                and comparison["status"] != "unavailable"
                and comparison_contract_proven
                else None
            )
            try:
                storyline = build_storyline(
                    metric=current,
                    direction=direction,
                    root_cause_evidence_ids=current.get("evidence_ids", []),
                    evidence_registry=evidence_registry,
                    snapshot_id=formal_binding["source_snapshot_id"],
                    comparison=narrative_comparison,
                    impact=(
                        "该指标描述已声明完整范围内的 Reddit 观察样本，用于 Momcozy 运营核查与竞品对照优先级。"
                        if comparison_contract_proven
                        else "该指标仅描述当前已观测 Reddit 样本；历史覆盖未获数据所有者证明，不支持环比、同比或趋势结论。"
                    ),
                    action={
                        "approval_status": "proposed",
                        "owner_role": "VOC Insights",
                        "priority": "P1" if direction == "up" else "P2",
                    },
                    monitoring={
                        "cadence": grain,
                        "metric_id": current["metric_id"],
                        "review_date": report["period"]["end"],
                    },
                )
            except StorylineError as exc:
                raise V3InsightsBuildError(str(exc)) from exc
            storylines.append(
                {
                    "analysis_frame": deepcopy(report["analysis_frame"]),
                    "comparison_side": card["metric_definition"]["comparison_side"],
                    "grain": grain,
                    **storyline,
                }
            )
    direction_supported = sum(
        row["direction_claim_supported"] is True for row in storylines
    )
    brand_health = {
        grain: deepcopy(reports[f"current/{grain}.json"]["brand_health"])
        for grain in ("daily", "weekly", "monthly")
    }
    source = {
        "coverage_attestation_sha256": formal_binding[
            "data_owner_coverage_attestation_sha256"
        ],
        "metrics_candidate_manifest_sha256": formal_binding[
            "candidate_manifest_sha256"
        ],
        "metrics_input_manifest_sha256": formal_binding["input_manifest_sha256"],
        "metrics_validation_receipt_sha256": formal_binding["receipt_sha256"],
        "report_manifest_sha256": report_manifest_sha,
        "report_validation_receipt_sha256": report_receipt_sha,
        "source_snapshot_id": formal_binding["source_snapshot_id"],
    }
    insights = {
        "analysis_frame": {
            "comparison_brand_role": "competitor_union",
            "comparison_metric_ids": ["RV-BR-05", "RV-PS-04"],
            "primary_brand": "Momcozy",
        },
        "boundaries": dict(V3_BOUNDARIES),
        "brand_health": brand_health,
        "comparison_contract_basis": comparison_contract_basis,
        "comparison_contract_proven": comparison_contract_proven,
        "comparison_unavailable_reason_codes": deepcopy(
            comparison_unavailable_reason_codes
        ),
        "completeness_percent": completeness_percent,
        "coverage_attestation": deepcopy(formal_binding["coverage_attestation"]),
        "data_owner_coverage_attestation_sha256": formal_binding[
            "data_owner_coverage_attestation_sha256"
        ],
        "dataset_version": dataset_version,
        "fixture_only": False,
        "interpretation_boundaries": {
            "brand_health_null_when_classification_coverage_insufficient": True,
            "direction_requires_precomputed_comparable_complete_periods": True,
            "front_end_recomputation_supported": False,
            "root_cause_requires_same_snapshot_evidence": True,
            "sales_causality_supported": False,
            "unavailable_metric_direction_supported": False,
        },
        "schema_version": V3_INSIGHTS_SCHEMA,
        "source": source,
        "storyline_count": len(storylines),
        "storyline_summary": {
            "direction_supported": direction_supported,
            "direction_unavailable": len(storylines) - direction_supported,
            "total": len(storylines),
        },
        "storylines": storylines,
    }
    insights_payload = _v3_canonical_bytes(insights)
    manifest = {
        "artifact_stage": "insights_candidate",
        "boundaries": dict(V3_BOUNDARIES),
        "comparison_contract_basis": comparison_contract_basis,
        "comparison_contract_proven": comparison_contract_proven,
        "comparison_unavailable_reason_codes": comparison_unavailable_reason_codes,
        "completeness_percent": completeness_percent,
        "consumption_status": "blocked_pending_independent_validation",
        "coverage_attestation": deepcopy(formal_binding["coverage_attestation"]),
        "data_owner_coverage_attestation_sha256": formal_binding[
            "data_owner_coverage_attestation_sha256"
        ],
        "dataset_version": dataset_version,
        "files": {
            "insights.json": {
                "bytes": len(insights_payload),
                "sha256": sha256(insights_payload).hexdigest(),
            }
        },
        "fixture_only": False,
        "independent_validation_status": "pending",
        "metrics_candidate_manifest_sha256": formal_binding[
            "candidate_manifest_sha256"
        ],
        "metrics_input_manifest_sha256": formal_binding["input_manifest_sha256"],
        "metrics_validation_receipt_sha256": formal_binding["receipt_sha256"],
        "promotable": False,
        "report_manifest_sha256": report_manifest_sha,
        "report_validation_receipt_sha256": report_receipt_sha,
        "schema_version": V3_INSIGHTS_MANIFEST_SCHEMA,
        "source_snapshot_id": formal_binding["source_snapshot_id"],
        "status": "candidate_built",
        "storyline_count": len(storylines),
        "storyline_summary": insights["storyline_summary"],
    }
    return insights, manifest


def _v3_assert_public_insights_safe(value: Any, path: str = "root") -> None:
    prohibited_keys = {
        "author",
        "body",
        "comment_id",
        "content",
        "entity_id",
        "entity_ids",
        "evidence_ids",
        "member_id",
        "member_ids",
        "permalink",
        "post_id",
        "raw_text",
        "selftext",
        "snapshot_id",
        "storyline_id",
        "title",
        "url",
        "username",
    }
    if isinstance(value, dict):
        overlap = prohibited_keys & set(value)
        if overlap:
            raise V3InsightsBuildError(
                f"public insights contain prohibited fields at {path}: {sorted(overlap)}"
            )
        for key, child in value.items():
            _v3_assert_public_insights_safe(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _v3_assert_public_insights_safe(child, f"{path}[{index}]")
    elif isinstance(value, str) and re.search(r"https?://|reddit\.com/|(?:^|\s)u/\w+", value):
        raise V3InsightsBuildError(f"public insights contain an external link at {path}")


def _v3_public_storyline(storyline: dict[str, Any]) -> dict[str, Any]:
    sections = storyline.get("sections")
    if not isinstance(sections, dict) or set(sections) != {
        "signal",
        "root_cause",
        "counter_intuitive",
        "impact",
        "action",
        "monitoring",
    }:
        raise V3InsightsBuildError("formal storyline section set is invalid")
    root_cause = sections["root_cause"]
    evidence_ids = root_cause.get("evidence_ids")
    if not isinstance(evidence_ids, list):
        raise V3InsightsBuildError("formal storyline evidence IDs are invalid")
    public_storyline = {
        "analysis_frame": deepcopy(storyline["analysis_frame"]),
        "comparison_side": storyline["comparison_side"],
        "direction_claim_supported": storyline["direction_claim_supported"],
        "grain": storyline["grain"],
        "metric_id": storyline["metric_id"],
        "period_id": storyline["period_id"],
        "schema_version": "reddit_voc_storyline_public_v3",
        "sections": {
            "signal": {
                key: deepcopy(sections["signal"][key])
                for key in (
                    "direction",
                    "metric_id",
                    "period_id",
                    "scope",
                    "status",
                    "unit",
                    "value",
                    "voc_type",
                )
            },
            "root_cause": {
                "evidence_count": len(evidence_ids),
                "statement": root_cause["statement"],
                "supported": root_cause["supported"],
            },
            "counter_intuitive": {
                key: deepcopy(sections["counter_intuitive"][key])
                for key in ("reason_codes", "statement", "supported")
            },
            "impact": {
                key: deepcopy(sections["impact"][key])
                for key in ("sales_causality_supported", "statement")
            },
            "action": {
                key: deepcopy(sections["action"][key])
                for key in ("approval_status", "owner_role", "priority")
            },
            "monitoring": {
                key: deepcopy(sections["monitoring"][key])
                for key in ("cadence", "metric_id", "review_date")
            },
        },
    }
    _v3_assert_public_insights_safe(public_storyline, "storyline")
    return public_storyline


def build_v3_public_insights_wrapper(
    candidate_dir: Path,
    validation_receipt_path: Path,
    *,
    expected_candidate_manifest_sha256: str,
    expected_validation_receipt_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create a validated, privacy-safe aggregate-only insights projection."""

    candidate_sha = expected_candidate_manifest_sha256
    receipt_sha = expected_validation_receipt_sha256
    if (
        not isinstance(candidate_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", candidate_sha) is None
        or not isinstance(receipt_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", receipt_sha) is None
    ):
        raise V3InsightsBuildError("public insights SHA binding is invalid")
    candidate_dir = Path(candidate_dir)
    receipt_path = Path(validation_receipt_path)
    if candidate_dir.is_symlink() or not candidate_dir.is_dir():
        raise V3InsightsBuildError("candidate insights root is invalid")
    candidate_manifest_path = candidate_dir / "manifest.json"
    if _sha256(candidate_manifest_path) != candidate_sha:
        raise V3InsightsBuildError("candidate insights manifest SHA mismatch")
    if (
        receipt_path.is_symlink()
        or not receipt_path.is_file()
        or _sha256(receipt_path) != receipt_sha
    ):
        raise V3InsightsBuildError("insights validation receipt SHA mismatch")
    candidate_manifest = json.loads(
        candidate_manifest_path.read_text(encoding="utf-8")
    )
    validation_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        candidate_manifest_path.read_bytes() != _v3_canonical_bytes(candidate_manifest)
        or receipt_path.read_bytes() != _v3_canonical_bytes(validation_receipt)
    ):
        raise V3InsightsBuildError("insights lineage inputs are not canonical JSON")
    if (
        candidate_manifest.get("schema_version") != V3_INSIGHTS_MANIFEST_SCHEMA
        or candidate_manifest.get("artifact_stage") != "insights_candidate"
        or candidate_manifest.get("status") != "candidate_built"
        or candidate_manifest.get("promotable") is not False
        or candidate_manifest.get("fixture_only") is not False
        or validation_receipt.get("schema_version")
        != "reddit_voc_insights_validation_receipt_v3"
        or validation_receipt.get("status") != "passed_candidate_only"
        or validation_receipt.get("promotable") is not True
        or validation_receipt.get("bundle_manifest_sha256") != candidate_sha
        or validation_receipt.get("storyline_count")
        != candidate_manifest.get("storyline_count")
        or validation_receipt.get("data_owner_coverage_attestation_sha256")
        != candidate_manifest.get("data_owner_coverage_attestation_sha256")
    ):
        raise V3InsightsBuildError("validated insights lifecycle binding is invalid")
    files = candidate_manifest.get("files")
    insights_path = candidate_dir / "insights.json"
    if not isinstance(files, dict) or set(files) != {"insights.json"}:
        raise V3InsightsBuildError("candidate insights file set is invalid")
    record = files["insights.json"]
    if (
        insights_path.is_symlink()
        or not insights_path.is_file()
        or not isinstance(record, dict)
        or set(record) != {"bytes", "sha256"}
        or record.get("bytes") != insights_path.stat().st_size
        or record.get("sha256") != _sha256(insights_path)
    ):
        raise V3InsightsBuildError("candidate insights file integrity mismatch")
    candidate = json.loads(insights_path.read_text(encoding="utf-8"))
    if insights_path.read_bytes() != _v3_canonical_bytes(candidate):
        raise V3InsightsBuildError("candidate insights are not canonical JSON")
    public_storylines = [
        _v3_public_storyline(storyline) for storyline in candidate["storylines"]
    ]
    public_insights = {
        "analysis_frame": deepcopy(candidate["analysis_frame"]),
        "boundaries": deepcopy(candidate["boundaries"]),
        "brand_health": deepcopy(candidate["brand_health"]),
        "comparison_contract_basis": candidate["comparison_contract_basis"],
        "comparison_contract_proven": candidate["comparison_contract_proven"],
        "comparison_unavailable_reason_codes": deepcopy(
            candidate["comparison_unavailable_reason_codes"]
        ),
        "completeness_percent": candidate["completeness_percent"],
        "coverage_attestation": deepcopy(candidate["coverage_attestation"]),
        "data_owner_coverage_attestation_sha256": candidate[
            "data_owner_coverage_attestation_sha256"
        ],
        "dataset_version": candidate["dataset_version"],
        "fixture_only": False,
        "interpretation_boundaries": deepcopy(
            candidate["interpretation_boundaries"]
        ),
        "lineage_schema_version": candidate["schema_version"],
        "privacy_safe_projection": True,
        "schema_version": V3_PUBLIC_INSIGHTS_SCHEMA,
        "source": deepcopy(candidate["source"]),
        "storyline_count": len(public_storylines),
        "storyline_summary": deepcopy(candidate["storyline_summary"]),
        "storylines": public_storylines,
    }
    _v3_assert_public_insights_safe(public_insights)
    public_payload = _v3_canonical_bytes(public_insights)
    receipt_payload = _v3_canonical_bytes(validation_receipt)
    public_manifest = {
        "artifact_stage": "insights_public_candidate",
        "boundaries": deepcopy(candidate_manifest["boundaries"]),
        "comparison_contract_basis": candidate_manifest[
            "comparison_contract_basis"
        ],
        "comparison_contract_proven": candidate_manifest[
            "comparison_contract_proven"
        ],
        "comparison_unavailable_reason_codes": deepcopy(
            candidate_manifest["comparison_unavailable_reason_codes"]
        ),
        "completeness_percent": candidate_manifest["completeness_percent"],
        "consumption_status": "eligible_for_frontend_candidate_consumption",
        "coverage_attestation": deepcopy(candidate_manifest["coverage_attestation"]),
        "data_owner_coverage_attestation_sha256": candidate_manifest[
            "data_owner_coverage_attestation_sha256"
        ],
        "dataset_version": candidate_manifest["dataset_version"],
        "files": {
            "insights.json": {
                "bytes": len(public_payload),
                "sha256": sha256(public_payload).hexdigest(),
            },
            "validation-receipt.json": {
                "bytes": len(receipt_payload),
                "sha256": receipt_sha,
            },
        },
        "fixture_only": False,
        "independent_validation_status": "passed",
        "lineage_manifest_sha256": candidate_sha,
        "privacy_safe_projection": True,
        "promotable": True,
        "schema_version": V3_PUBLIC_INSIGHTS_MANIFEST_SCHEMA,
        "source_snapshot_id": candidate_manifest["source_snapshot_id"],
        "status": "validated_candidate",
        "storyline_count": candidate_manifest["storyline_count"],
        "storyline_summary": deepcopy(candidate_manifest["storyline_summary"]),
        "validation_receipt_sha256": receipt_sha,
    }
    return public_insights, validation_receipt, public_manifest


def write_v3_public_insights_wrapper(
    output_dir: Path,
    insights: dict[str, Any],
    validation_receipt: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise V3InsightsBuildError("public insights output root is invalid")
    output_dir.mkdir(parents=True, exist_ok=True)
    if {path.name for path in output_dir.iterdir()} - {
        "insights.json",
        "manifest.json",
        "validation-receipt.json",
        "build.json",
    }:
        raise V3InsightsBuildError("public insights output contains undeclared entries")
    _v3_write_exact(output_dir / "insights.json", insights)
    _v3_write_exact(output_dir / "validation-receipt.json", validation_receipt)
    _v3_write_exact(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit, insights, manifest = build(
        args.snapshot_dir.resolve(strict=True),
        args.sample.resolve(strict=True),
        args.decisions.resolve(strict=True),
    )
    written = write_snapshot(args.output_dir, audit, insights, manifest)
    print(
        json.dumps(
            {
                "status": written["status"],
                "dataset_version": written["dataset_version"],
                **written["audit_summary"],
                **written["boundaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
