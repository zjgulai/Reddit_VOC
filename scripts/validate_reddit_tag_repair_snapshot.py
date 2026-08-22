#!/usr/bin/env python3
"""Independently validate a versioned Reddit semantic tag repair snapshot."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from itertools import zip_longest
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from reddit_voc.reddit_semantic_predicates import (
    ALLOWED_STATUSES,
    DEFAULT_REPAIR_DATASET_VERSION,
    TARGET_TAG_IDS,
    PredicatePolicy,
    evaluate_assignment,
    load_policy,
)


DATASET_VERSION = DEFAULT_REPAIR_DATASET_VERSION
MANIFEST_SCHEMA = "reddit_voc_tag_repair_manifest_v1"
ASSIGNMENTS_SCHEMA = "reddit_voc_tag_repair_assignments_v1"
REGRESSION_SCHEMA = "reddit_voc_tag_repair_regression_audit_v1"
SAMPLE_SCHEMA = "reddit_voc_tag_repair_review_sample_v1"
CHALLENGE_SCHEMA = "reddit_voc_tag_repair_challenge_cases_v1"
AUDIT_SCHEMA = "reddit_voc_tag_repair_semantic_audit_v1"
DECISIONS_SCHEMA = "reddit_voc_tag_repair_review_decisions_v1"
RECEIPT_SCHEMA = "reddit_voc_tag_repair_validation_receipt_v1"
DEVELOPMENT_EVIDENCE_SCHEMA = "reddit_voc_tag_repair_development_evidence_v1"
FILE_NAMES = (
    "assignments.json",
    "regression-audit.json",
    "review-sample.json",
    "challenge-cases.json",
    "semantic-audit.json",
)
SOURCE_PRIORITY = (
    "tencent_production_primary",
    "historical_canonical",
    "imported_archive",
)
QUALITY_GATE = {
    "sample_plan": "30_fresh_confirmed_or_full_fresh_confirmed_population",
    "minimum_label_precision": 0.9,
    "minimum_wilson_lower_bound_95": 0.75,
    "minimum_taxonomy_fit_rate": 0.9,
    "maximum_ambiguous_rate": 0.1,
    "minimum_challenge_cases": 20,
    "governance_status_required": "fit",
}
ARTIFACT_KEYS = {
    "assignments.json": "assignments",
    "regression-audit.json": "regression-audit",
    "review-sample.json": "review-sample",
    "challenge-cases.json": "challenge-cases",
    "semantic-audit.json": "semantic-audit",
}
EXPECTED_SCHEMAS = {
    "assignments.json": ASSIGNMENTS_SCHEMA,
    "regression-audit.json": REGRESSION_SCHEMA,
    "review-sample.json": SAMPLE_SCHEMA,
    "challenge-cases.json": CHALLENGE_SCHEMA,
    "semantic-audit.json": AUDIT_SCHEMA,
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_encoded(value))


def _wilson_lower_bound(
    successes: int, total: int, *, z: float = 1.959963984540054
) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    center = proportion + z * z / (2 * total)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    )
    return (center - margin) / denominator


def _object_sha256(value: Any) -> str:
    return sha256(_encoded(value)).hexdigest()


def _dataset_version(policy: PredicatePolicy) -> str:
    return policy.repair_dataset_version


def _development_exclusion(
    *,
    prior_repair_dir: Path | None,
    development_evidence_path: Path | None,
    base_manifest_sha256: str,
) -> tuple[set[str], dict[str, Any] | None]:
    if (prior_repair_dir is None) != (development_evidence_path is None):
        raise ValueError(
            "prior repair directory and development evidence must be provided together"
        )
    if prior_repair_dir is None or development_evidence_path is None:
        return set(), None

    prior_repair_dir = prior_repair_dir.resolve(strict=True)
    development_evidence_path = development_evidence_path.resolve(strict=True)
    manifest_path = prior_repair_dir / "manifest.json"
    assignments_path = prior_repair_dir / "assignments.json"
    review_path = prior_repair_dir / "review-sample.json"
    challenges_path = prior_repair_dir / "challenge-cases.json"
    prior_manifest = _load(manifest_path)
    evidence = _load(development_evidence_path)

    if evidence.get("schema_version") != DEVELOPMENT_EVIDENCE_SCHEMA:
        raise ValueError("development evidence schema mismatch")
    if evidence.get("base_manifest_sha256") != base_manifest_sha256:
        raise ValueError("development evidence base manifest mismatch")
    manifest_sha256 = _sha256(manifest_path)
    if evidence.get("prior_repair_manifest_sha256") != manifest_sha256:
        raise ValueError("development evidence prior manifest mismatch")
    if evidence.get("prior_repair_dataset_version") != prior_manifest.get(
        "dataset_version"
    ):
        raise ValueError("development evidence prior dataset mismatch")

    files = (
        ("assignments.json", assignments_path, "prior_assignments_sha256"),
        ("review-sample.json", review_path, "prior_review_sample_sha256"),
        (
            "challenge-cases.json",
            challenges_path,
            "prior_challenge_cases_sha256",
        ),
    )
    for filename, path, evidence_key in files:
        file_sha256 = _sha256(path)
        if prior_manifest.get("files", {}).get(filename, {}).get(
            "sha256"
        ) != file_sha256:
            raise ValueError(f"prior repair file manifest mismatch: {filename}")
        if evidence.get(evidence_key) != file_sha256:
            raise ValueError(f"development evidence file hash mismatch: {filename}")

    filter_spec = evidence.get("reviewed_assignment_filter", {})
    if set(filter_spec.get("target_tag_ids", ())) != TARGET_TAG_IDS:
        raise ValueError("development evidence target tag set mismatch")
    statuses = set(filter_spec.get("predicate_statuses", ()))
    if not statuses or statuses - ALLOWED_STATUSES:
        raise ValueError("development evidence predicate status mismatch")
    predicate_version = filter_spec.get("predicate_version")
    reviewed_ids = {
        row["audit_id"]
        for row in _load(assignments_path).get("assignments", [])
        if row.get("tag_id") in TARGET_TAG_IDS
        and row.get("predicate_status") in statuses
        and row.get("predicate_version") == predicate_version
    }
    if len(reviewed_ids) != evidence.get("reviewed_assignment_count"):
        raise ValueError("development evidence reviewed count mismatch")
    if evidence.get("reviewer", {}).get("independent_human_review") is not False:
        raise ValueError("development evidence human-review boundary mismatch")

    review_ids = {
        row["audit_id"]
        for tag in _load(review_path).get("tags", [])
        for row in tag.get("samples", [])
    }
    challenge_ids = {
        row["audit_id"]
        for tag in _load(challenges_path).get("tags", [])
        for row in tag.get("cases", [])
    }
    excluded_ids = reviewed_ids | review_ids | challenge_ids
    return excluded_ids, {
        "prior_repair_manifest_sha256": manifest_sha256,
        "development_evidence_sha256": _sha256(development_evidence_path),
        "reviewed_assignment_count": len(reviewed_ids),
        "prior_review_sample_count": len(review_ids),
        "prior_challenge_count": len(challenge_ids),
        "unique_development_exclusion_count": len(excluded_ids),
    }


def _source_stratum(source_kinds: list[str]) -> str:
    available = set(source_kinds)
    return next(
        (source for source in SOURCE_PRIORITY if source in available),
        "unknown",
    )


def _stable_rank(
    policy_version: str, tag_id: str, entity_type: str, entity_id: str
) -> str:
    payload = f"{policy_version}|{tag_id}|{entity_type}|{entity_id}"
    return sha256(payload.encode("utf-8")).hexdigest()


def _excerpt(text: str, keywords: list[str], *, limit: int = 760) -> str:
    normalized = " ".join(text.split())
    folded = normalized.casefold()
    offsets = [
        folded.find(keyword.casefold())
        for keyword in keywords
        if keyword and folded.find(keyword.casefold()) >= 0
    ]
    focus = min(offsets) if offsets else 0
    start = max(0, focus - limit // 3)
    end = min(len(normalized), start + limit)
    if end - start < limit:
        start = max(0, end - limit)
    return (
        ("…" if start else "")
        + normalized[start:end]
        + ("…" if end < len(normalized) else "")
    )


def _recompute_assignment_rows(
    snapshot_dir: Path,
    policy: PredicatePolicy,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    posts = _load(snapshot_dir / "posts.json")
    comments = _load(snapshot_dir / "comments.json")
    post_by_id = {post["post_id"]: post for post in posts}
    rows: list[dict[str, Any]] = []
    contexts: dict[str, dict[str, Any]] = {}

    for entity_type, entities in (("post", posts), ("comment", comments)):
        for entity in entities:
            if entity_type == "comment" and not entity["include_in_voc_metrics"]:
                continue
            entity_id = str(
                entity["post_id"]
                if entity_type == "post"
                else entity["comment_id"]
            )
            entity_text = (
                f"{entity['title']}\n{entity['content']}"
                if entity_type == "post"
                else str(entity["body"])
            )
            source_kinds = (
                list(entity["source_kinds"])
                if entity_type == "post"
                else [
                    occurrence["source_kind"]
                    for occurrence in entity["source_occurrences"]
                ]
            )
            parent = entity if entity_type == "post" else post_by_id[entity["post_id"]]
            parent_text = f"{parent['title']}\n{parent['content']}"
            for lexical_match in entity["tagging"]["matches"]:
                tag_id = lexical_match["tag_id"]
                if tag_id not in TARGET_TAG_IDS:
                    continue
                predicate = evaluate_assignment(
                    tag_id=tag_id,
                    text=entity_text,
                    evidence_keywords=lexical_match["evidence_keywords"],
                    policy=policy,
                    brand_tag_ids=entity["tagging"]["brand_tag_ids"],
                    detected_spu_ids=entity["tagging"]["context"][
                        "detected_spu_ids"
                    ],
                    parent_text=(parent_text if entity_type == "comment" else None),
                )
                audit_id = f"{tag_id}:{entity_type}:{entity_id}"
                rows.append(
                    {
                        "audit_id": audit_id,
                        "tag_id": tag_id,
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "reddit_id": entity["reddit_id"],
                        "post_id": entity["post_id"],
                        "subreddit": parent.get("subreddit"),
                        "created_at_utc": entity["created_at_utc"],
                        "source_stratum": _source_stratum(source_kinds),
                        "source_kinds": sorted(set(source_kinds)),
                        "lexical_evidence_keywords": list(
                            predicate.evidence_keywords
                        ),
                        "predicate_status": predicate.status,
                        "reason_code": predicate.reason_code,
                        "sentence_indexes": list(predicate.sentence_indexes),
                        "evidence_sentences": list(
                            predicate.evidence_sentences
                        ),
                        "predicate_version": predicate.predicate_version,
                        "stable_rank": _stable_rank(
                            policy.policy_version,
                            tag_id,
                            entity_type,
                            entity_id,
                        ),
                    }
                )
                contexts[audit_id] = {
                    "context_excerpt": _excerpt(
                        entity_text, list(predicate.evidence_keywords)
                    ),
                    "parent_context_excerpt": (
                        None
                        if entity_type == "post"
                        else _excerpt(parent_text, [], limit=560)
                    ),
                    "text_sha256": sha256(
                        entity_text.encode("utf-8")
                    ).hexdigest(),
                }
    rows.sort(
        key=lambda row: (
            row["tag_id"],
            row["predicate_status"],
            row["entity_type"],
            row["entity_id"],
        )
    )
    return rows, contexts


def _recompute_assignments(
    rows: list[dict[str, Any]],
    *,
    base_manifest: dict[str, Any],
    base_manifest_sha256: str,
    policy: PredicatePolicy,
    policy_sha256: str,
) -> dict[str, Any]:
    overall = Counter(row["predicate_status"] for row in rows)
    by_tag: dict[str, dict[str, int]] = {}
    for tag_id in policy.target_tag_ids:
        tag_rows = [row for row in rows if row["tag_id"] == tag_id]
        counts = Counter(row["predicate_status"] for row in tag_rows)
        by_tag[tag_id] = {
            "lexical_candidates": len(tag_rows),
            **{
                status: counts[status]
                for status in sorted(ALLOWED_STATUSES)
            },
        }
    return {
        "schema_version": ASSIGNMENTS_SCHEMA,
        "dataset_version": _dataset_version(policy),
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": base_manifest_sha256,
        "dictionary_version": policy.dictionary_version,
        "dictionary_sha256": policy.dictionary_sha256,
        "predicate_policy_version": policy.policy_version,
        "predicate_policy_sha256": policy_sha256,
        "summary": {
            "lexical_candidates": len(rows),
            "by_status": {
                status: overall[status]
                for status in sorted(ALLOWED_STATUSES)
            },
            "by_tag": by_tag,
        },
        "assignments": rows,
        "boundaries": dict(policy.boundaries),
    }


def _expanded_decision(
    tag_review: dict[str, Any], audit_id: str
) -> dict[str, str]:
    decision = dict(tag_review["default_decision"])
    decision.update(tag_review.get("overrides", {}).get(audit_id, {}))
    return decision


def _legacy_held_tag_ids(
    legacy_sample: dict[str, Any], legacy_decisions: dict[str, Any]
) -> set[str]:
    gate = legacy_decisions["quality_gate"]
    held: set[str] = set()
    for sampled_tag in legacy_sample["tags"]:
        tag_id = sampled_tag["tag_id"]
        tag_review = legacy_decisions["tag_reviews"][tag_id]
        decisions = [
            _expanded_decision(tag_review, sample["audit_id"])
            for sample in sampled_tag["samples"]
        ]
        verdicts = Counter(item["label_verdict"] for item in decisions)
        taxonomy = Counter(item["taxonomy_fit"] for item in decisions)
        decidable = verdicts["correct"] + verdicts["incorrect"]
        precision = verdicts["correct"] / decidable if decidable else 0.0
        checks = (
            len(decisions) >= gate["required_samples_per_tag"],
            precision >= gate["minimum_label_precision"],
            _wilson_lower_bound(verdicts["correct"], decidable)
            >= gate["minimum_wilson_lower_bound_95"],
            taxonomy["fit"] / len(decisions)
            >= gate["minimum_taxonomy_fit_rate"],
            verdicts["ambiguous"] / len(decisions)
            <= gate["maximum_ambiguous_rate"],
            tag_review["governance_review"]["status"]
            == gate["governance_status_required"],
        )
        if not all(checks):
            held.add(tag_id)
    return held


def _recompute_regression(
    *,
    legacy_sample: dict[str, Any],
    legacy_decisions: dict[str, Any],
    assignment_rows: list[dict[str, Any]],
    held_tag_ids: set[str],
    policy: PredicatePolicy,
    base_manifest_sha256: str,
    policy_sha256: str,
) -> dict[str, Any]:
    assignment_by_id = {row["audit_id"]: row for row in assignment_rows}
    rows: list[dict[str, Any]] = []
    for sampled_tag in legacy_sample["tags"]:
        tag_id = sampled_tag["tag_id"]
        if tag_id not in held_tag_ids:
            continue
        tag_review = legacy_decisions["tag_reviews"][tag_id]
        for sample in sampled_tag["samples"]:
            previous = _expanded_decision(tag_review, sample["audit_id"])
            in_scope = tag_id in TARGET_TAG_IDS
            repaired = assignment_by_id.get(sample["audit_id"])
            if in_scope and repaired is None:
                raise ValueError(
                    f"legacy repair sample lacks lexical assignment: {sample['audit_id']}"
                )
            status = repaired["predicate_status"] if repaired else "not_in_scope"
            if not in_scope:
                passed = True
                expectation = "not_in_repair_scope_observed_only"
            elif previous["label_verdict"] == "incorrect":
                passed = status != "confirmed"
                expectation = "must_not_confirm"
            elif previous["label_verdict"] == "ambiguous":
                passed = status == "needs_review"
                expectation = "must_remain_needs_review"
            else:
                passed = True
                expectation = "retention_observed_not_release_gate"
            rows.append(
                {
                    "audit_id": sample["audit_id"],
                    "tag_id": tag_id,
                    "in_repair_scope": in_scope,
                    "previous_label_verdict": previous["label_verdict"],
                    "previous_taxonomy_fit": previous["taxonomy_fit"],
                    "previous_reason_code": previous["reason_code"],
                    "predicate_status": status,
                    "predicate_reason_code": (
                        repaired["reason_code"]
                        if repaired
                        else "tag_not_in_repair_scope"
                    ),
                    "expectation": expectation,
                    "regression_pass": passed,
                }
            )
    rows.sort(key=lambda row: row["audit_id"])
    by_tag: dict[str, dict[str, int]] = {}
    for tag_id in policy.target_tag_ids:
        tag_rows = [row for row in rows if row["tag_id"] == tag_id]
        by_tag[tag_id] = {
            "samples": len(tag_rows),
            "failures": sum(not row["regression_pass"] for row in tag_rows),
            "known_incorrect_confirmed": sum(
                row["previous_label_verdict"] == "incorrect"
                and row["predicate_status"] == "confirmed"
                for row in tag_rows
            ),
            "known_ambiguous_not_needs_review": sum(
                row["previous_label_verdict"] == "ambiguous"
                and row["predicate_status"] != "needs_review"
                for row in tag_rows
            ),
        }
    return {
        "schema_version": REGRESSION_SCHEMA,
        "dataset_version": _dataset_version(policy),
        "base_manifest_sha256": base_manifest_sha256,
        "predicate_policy_version": policy.policy_version,
        "predicate_policy_sha256": policy_sha256,
        "legacy_sample_sha256": legacy_decisions["sample_sha256"],
        "summary": {
            "legacy_held_samples": len(rows),
            "in_scope_samples": sum(row["in_repair_scope"] for row in rows),
            "out_of_scope_samples": sum(
                not row["in_repair_scope"] for row in rows
            ),
            "regression_failures": sum(
                not row["regression_pass"] for row in rows
            ),
            "by_tag": by_tag,
        },
        "samples": rows,
        "boundaries": dict(policy.boundaries),
    }


def _round_robin_select(
    rows: list[dict[str, Any]],
    count: int,
    *,
    group_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(str(row[field]) for field in group_fields)].append(row)
    ordered_groups = []
    for key in sorted(grouped):
        ordered_groups.append(
            sorted(grouped[key], key=lambda row: row["stable_rank"])
        )
    flattened = [
        item
        for layer in zip_longest(*ordered_groups)
        for item in layer
        if item is not None
    ] if ordered_groups else []
    return flattened[:count]


def _sample_row(
    row: dict[str, Any], contexts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    return {
        **row,
        **contexts[row["audit_id"]],
        "review": {
            "label_verdict": "pending",
            "taxonomy_fit": "pending",
            "reason_code": "pending",
            "note": "",
        },
    }


def _recompute_review_sample(
    *,
    assignment_rows: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    legacy_ids: set[str],
    rules_by_tag: dict[str, dict[str, Any]],
    base_manifest: dict[str, Any],
    base_manifest_sha256: str,
    policy: PredicatePolicy,
    policy_sha256: str,
    development_excluded_ids: set[str] | None = None,
    exclusion_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    development_excluded_ids = development_excluded_ids or set()
    excluded_ids = legacy_ids | development_excluded_ids
    tags: list[dict[str, Any]] = []
    for tag_id in policy.target_tag_ids:
        population = [
            row
            for row in assignment_rows
            if row["tag_id"] == tag_id
            and row["predicate_status"] == "confirmed"
            and row["audit_id"] not in excluded_ids
        ]
        sample_count = min(30, len(population))
        selected = _round_robin_select(
            population,
            sample_count,
            group_fields=("entity_type", "source_stratum", "reason_code"),
        )
        rule = rules_by_tag[tag_id]
        tags.append(
            {
                "tag_id": tag_id,
                "name_cn": rule["name_cn"],
                "name_en": rule["name_en"],
                "theme": rule["theme"],
                "definition": rule["definition"],
                "dictionary_reference": {
                    field: rule[field]
                    for field in (
                        "aipl_node",
                        "consumer_card",
                        "story_lines",
                        "problem_type",
                        "intent_type",
                        "business_impact",
                        "strategy_package",
                        "biz_action",
                        "dept_owner",
                    )
                },
                "fresh_confirmed_candidates": len(population),
                "planned_sample_count": sample_count,
                "sample_count": len(selected),
                "sample_mode": (
                    "fixed_30"
                    if len(population) >= 30
                    else "full_fresh_population"
                ),
                "samples": [
                    _sample_row(row, contexts) for row in selected
                ],
            }
        )
    method: dict[str, Any] = {
        "selection": "predicate_confirmed_assignments_only",
        "legacy_sample_overlap_allowed": False,
        "sampling": "deterministic SHA-256 round robin by entity type, source and reason",
        "candidate_at_least_30": "sample_30",
        "candidate_below_30": "review_full_fresh_population",
    }
    if exclusion_metadata is not None:
        method.update(
            {
                "development_evidence_overlap_allowed": False,
                "prior_review_sample_overlap_allowed": False,
                "prior_challenge_overlap_allowed": False,
                "exclusion": exclusion_metadata,
            }
        )
    return {
        "schema_version": SAMPLE_SCHEMA,
        "dataset_version": _dataset_version(policy),
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": base_manifest_sha256,
        "dictionary_version": policy.dictionary_version,
        "dictionary_sha256": policy.dictionary_sha256,
        "predicate_policy_version": policy.policy_version,
        "predicate_policy_sha256": policy_sha256,
        "method": method,
        "tags": tags,
        "boundaries": dict(policy.boundaries),
    }


def _recompute_challenges(
    *,
    assignment_rows: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    base_manifest_sha256: str,
    policy: PredicatePolicy,
    policy_sha256: str,
    development_excluded_ids: set[str] | None = None,
) -> dict[str, Any]:
    development_excluded_ids = development_excluded_ids or set()
    tags: list[dict[str, Any]] = []
    for tag_id in policy.target_tag_ids:
        population = [
            row
            for row in assignment_rows
            if row["tag_id"] == tag_id
            and row["predicate_status"] in {"rejected", "needs_review"}
            and row["audit_id"] not in development_excluded_ids
        ]
        selected = _round_robin_select(
            population,
            min(20, len(population)),
            group_fields=("predicate_status", "reason_code", "source_stratum"),
        )
        tags.append(
            {
                "tag_id": tag_id,
                "available_nonconfirmed_candidates": len(population),
                "challenge_target": 20,
                "challenge_count": len(selected),
                "target_met": len(selected) >= 20,
                "cases": [
                    {**row, **contexts[row["audit_id"]]} for row in selected
                ],
            }
        )
    method = {
        "selection": "deterministic_nonconfirmed_relation_challenges",
        "minimum_per_tag": 20,
        "legacy_overlap_allowed": True,
        "synthetic_cases_added": False,
    }
    if development_excluded_ids:
        method["development_evidence_overlap_allowed"] = False
    return {
        "schema_version": CHALLENGE_SCHEMA,
        "dataset_version": _dataset_version(policy),
        "base_manifest_sha256": base_manifest_sha256,
        "predicate_policy_version": policy.policy_version,
        "predicate_policy_sha256": policy_sha256,
        "method": method,
        "tags": tags,
        "boundaries": dict(policy.boundaries),
    }


def _recompute_semantic_audit(
    *,
    review_sample: dict[str, Any],
    regression: dict[str, Any],
    challenges: dict[str, Any],
    assignments: dict[str, Any],
    policy: PredicatePolicy,
    policy_sha256: str,
    review_decisions: dict[str, Any] | None,
    review_decisions_sha256: str | None,
) -> dict[str, Any]:
    sample_sha256 = _object_sha256(review_sample)
    if review_decisions is None:
        reviewer = {
            "type": "codex_context_review",
            "version": "pending",
            "independent_human_review": False,
            "review_policy": "Pending full-context review of zero-overlap confirmed candidates.",
        }
    else:
        if review_decisions.get("schema_version") != DECISIONS_SCHEMA:
            raise ValueError("repair review decisions schema mismatch")
        if review_decisions.get("sample_sha256") != sample_sha256:
            raise ValueError("repair review decisions are not bound to current sample")
        if review_decisions.get("predicate_policy_sha256") != policy_sha256:
            raise ValueError("repair review decisions policy hash mismatch")
        if set(review_decisions.get("tag_reviews", {})) != TARGET_TAG_IDS:
            raise ValueError("repair review decision tag set mismatch")
        if review_decisions.get("quality_gate") != QUALITY_GATE:
            raise ValueError("repair review quality gate mismatch")
        reviewer = review_decisions["reviewer"]
        if reviewer.get("independent_human_review") is not False:
            raise ValueError("repair review human-review boundary mismatch")

    regression_by_tag = regression["summary"]["by_tag"]
    challenge_by_tag = {
        tag["tag_id"]: tag for tag in challenges["tags"]
    }
    assignment_by_tag = assignments["summary"]["by_tag"]
    audited_tags: list[dict[str, Any]] = []
    for sampled_tag in review_sample["tags"]:
        tag_id = sampled_tag["tag_id"]
        reviewed_samples: list[dict[str, Any]] = []
        if review_decisions is None:
            governance = {
                "status": "pending",
                "reason_code": "review_pending",
                "note": "Zero-overlap candidate review has not been completed.",
            }
            reviewed_samples = list(sampled_tag["samples"])
        else:
            tag_review = review_decisions["tag_reviews"][tag_id]
            governance = tag_review["governance_review"]
            explicit_overrides = tag_review.get("overrides", {})
            missing_overrides = sorted(
                sample["audit_id"]
                for sample in sampled_tag["samples"]
                if sample["audit_id"] not in explicit_overrides
            )
            if missing_overrides:
                raise ValueError(
                    "repair review decisions missing explicit overrides: "
                    + ", ".join(missing_overrides)
                )
            for sample in sampled_tag["samples"]:
                reviewed = dict(sample)
                decision = _expanded_decision(tag_review, sample["audit_id"])
                if decision.get("label_verdict") not in {
                    "correct",
                    "incorrect",
                    "ambiguous",
                }:
                    raise ValueError(
                        f"invalid repair review label verdict: {sample['audit_id']}"
                    )
                if decision.get("taxonomy_fit") not in {
                    "fit",
                    "mismatch",
                    "ambiguous",
                }:
                    raise ValueError(
                        f"invalid repair review taxonomy fit: {sample['audit_id']}"
                    )
                if not decision.get("reason_code") or not decision.get("note"):
                    raise ValueError(
                        f"incomplete repair review decision: {sample['audit_id']}"
                    )
                reviewed["review"] = decision
                reviewed_samples.append(reviewed)

        verdicts = Counter(
            sample["review"]["label_verdict"]
            for sample in reviewed_samples
        )
        taxonomy = Counter(
            sample["review"]["taxonomy_fit"]
            for sample in reviewed_samples
        )
        decidable = verdicts["correct"] + verdicts["incorrect"]
        precision = verdicts["correct"] / decidable if decidable else 0.0
        taxonomy_fit = (
            taxonomy["fit"] / len(reviewed_samples)
            if reviewed_samples
            else 0.0
        )
        ambiguous_rate = (
            verdicts["ambiguous"] / len(reviewed_samples)
            if reviewed_samples
            else 0.0
        )
        checks = {
            "review_complete": review_decisions is not None
            and all(
                sample["review"]["label_verdict"] != "pending"
                for sample in reviewed_samples
            ),
            "sample_plan_complete": len(reviewed_samples)
            == sampled_tag["planned_sample_count"]
            and sampled_tag["planned_sample_count"] > 0,
            "label_precision": precision
            >= QUALITY_GATE["minimum_label_precision"],
            "wilson_lower_bound_95": _wilson_lower_bound(
                verdicts["correct"], decidable
            )
            >= QUALITY_GATE["minimum_wilson_lower_bound_95"],
            "taxonomy_fit_rate": taxonomy_fit
            >= QUALITY_GATE["minimum_taxonomy_fit_rate"],
            "ambiguous_rate": ambiguous_rate
            <= QUALITY_GATE["maximum_ambiguous_rate"],
            "governance_fit": governance["status"]
            == QUALITY_GATE["governance_status_required"],
            "legacy_known_errors_blocked": regression_by_tag[tag_id][
                "known_incorrect_confirmed"
            ]
            == 0,
            "legacy_ambiguities_preserved": regression_by_tag[tag_id][
                "known_ambiguous_not_needs_review"
            ]
            == 0,
            "challenge_count": challenge_by_tag[tag_id]["challenge_count"]
            >= QUALITY_GATE["minimum_challenge_cases"],
        }
        audited_tags.append(
            {
                "tag_id": tag_id,
                "name_cn": sampled_tag["name_cn"],
                "name_en": sampled_tag["name_en"],
                "theme": sampled_tag["theme"],
                "definition": sampled_tag["definition"],
                "dictionary_reference": sampled_tag["dictionary_reference"],
                "predicate_counts": assignment_by_tag[tag_id],
                "fresh_confirmed_candidates": sampled_tag[
                    "fresh_confirmed_candidates"
                ],
                "sample_mode": sampled_tag["sample_mode"],
                "review_metrics": {
                    "reviewed": len(reviewed_samples),
                    "correct": verdicts["correct"],
                    "incorrect": verdicts["incorrect"],
                    "ambiguous": verdicts["ambiguous"],
                    "label_precision": round(precision, 6),
                    "wilson_lower_bound_95": round(
                        _wilson_lower_bound(verdicts["correct"], decidable),
                        6,
                    ),
                    "taxonomy_fit_rate": round(taxonomy_fit, 6),
                    "ambiguous_rate": round(ambiguous_rate, 6),
                },
                "governance_review": governance,
                "regression_summary": regression_by_tag[tag_id],
                "challenge_summary": {
                    field: challenge_by_tag[tag_id][field]
                    for field in (
                        "available_nonconfirmed_candidates",
                        "challenge_target",
                        "challenge_count",
                        "target_met",
                    )
                },
                "gate_checks": checks,
                "promotion_status": (
                    "promoted_after_repair"
                    if all(checks.values())
                    else "held_after_repair"
                ),
                "samples": reviewed_samples,
            }
        )

    promoted = [
        tag["tag_id"]
        for tag in audited_tags
        if tag["promotion_status"] == "promoted_after_repair"
    ]
    held = [
        tag["tag_id"]
        for tag in audited_tags
        if tag["promotion_status"] == "held_after_repair"
    ]
    return {
        "schema_version": AUDIT_SCHEMA,
        "dataset_version": _dataset_version(policy),
        "base_dataset_version": review_sample["base_dataset_version"],
        "base_manifest_sha256": review_sample["base_manifest_sha256"],
        "dictionary_version": policy.dictionary_version,
        "dictionary_sha256": policy.dictionary_sha256,
        "predicate_policy_version": policy.policy_version,
        "predicate_policy_sha256": policy_sha256,
        "review_sample_sha256": sample_sha256,
        "review_decisions_sha256": review_decisions_sha256,
        "reviewer": reviewer,
        "quality_gate": QUALITY_GATE,
        "review_status": (
            "complete" if review_decisions is not None else "pending"
        ),
        "summary": {
            "target_tags": len(audited_tags),
            "reviewed_assignments": sum(
                tag["review_metrics"]["reviewed"] for tag in audited_tags
            ),
            "promoted_after_repair": len(promoted),
            "held_after_repair": len(held),
            "promoted_tag_ids": promoted,
            "held_tag_ids": held,
            "status": (
                "review_pending"
                if review_decisions is None
                else (
                    "completed_with_promotions"
                    if promoted
                    else "completed_no_new_promotions"
                )
            ),
        },
        "tags": audited_tags,
        "boundaries": dict(policy.boundaries),
    }


def _independently_recompute(
    snapshot_dir: Path,
    policy_path: Path,
    legacy_sample_path: Path,
    legacy_decisions_path: Path,
    review_decisions_path: Path | None,
    prior_repair_dir: Path | None,
    development_evidence_path: Path | None,
) -> dict[str, Any]:
    base_manifest_path = snapshot_dir / "manifest.json"
    base_manifest = _load(base_manifest_path)
    base_manifest_sha256 = _sha256(base_manifest_path)
    dictionary = _load(snapshot_dir / "tag-dictionary.json")
    policy = load_policy(
        policy_path,
        expected_base_manifest_sha256=base_manifest_sha256,
        expected_dictionary_sha256=dictionary["dictionary_sha256"],
    )
    if policy.base_dataset_version != base_manifest["dataset_version"]:
        raise ValueError("predicate policy base dataset version mismatch")
    if policy.dictionary_version != dictionary["dictionary_version"]:
        raise ValueError("predicate policy dictionary version mismatch")
    if (
        policy.repair_dataset_version != DEFAULT_REPAIR_DATASET_VERSION
        and (prior_repair_dir is None or development_evidence_path is None)
    ):
        raise ValueError("v2 repair requires frozen development evidence")
    development_excluded_ids, exclusion_metadata = _development_exclusion(
        prior_repair_dir=prior_repair_dir,
        development_evidence_path=development_evidence_path,
        base_manifest_sha256=base_manifest_sha256,
    )
    policy_sha256 = _sha256(policy_path)
    legacy_sample = _load(legacy_sample_path)
    legacy_decisions = _load(legacy_decisions_path)
    if _sha256(legacy_sample_path) != legacy_decisions["sample_sha256"]:
        raise ValueError("legacy decisions are not bound to legacy sample")
    held_tag_ids = _legacy_held_tag_ids(legacy_sample, legacy_decisions)
    if len(held_tag_ids) != 8:
        raise ValueError("legacy held tag count mismatch")

    assignment_rows, contexts = _recompute_assignment_rows(
        snapshot_dir, policy
    )
    assignments = _recompute_assignments(
        assignment_rows,
        base_manifest=base_manifest,
        base_manifest_sha256=base_manifest_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
    )
    regression = _recompute_regression(
        legacy_sample=legacy_sample,
        legacy_decisions=legacy_decisions,
        assignment_rows=assignment_rows,
        held_tag_ids=held_tag_ids,
        policy=policy,
        base_manifest_sha256=base_manifest_sha256,
        policy_sha256=policy_sha256,
    )
    legacy_ids = {
        sample["audit_id"]
        for sampled_tag in legacy_sample["tags"]
        if sampled_tag["tag_id"] in held_tag_ids
        for sample in sampled_tag["samples"]
    }
    rules_by_tag = {
        rule["tag_id"]: rule
        for rule in dictionary["rules"]
        if rule["tag_id"] in TARGET_TAG_IDS
    }
    review_sample = _recompute_review_sample(
        assignment_rows=assignment_rows,
        contexts=contexts,
        legacy_ids=legacy_ids,
        rules_by_tag=rules_by_tag,
        base_manifest=base_manifest,
        base_manifest_sha256=base_manifest_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        development_excluded_ids=development_excluded_ids,
        exclusion_metadata=exclusion_metadata,
    )
    challenges = _recompute_challenges(
        assignment_rows=assignment_rows,
        contexts=contexts,
        base_manifest_sha256=base_manifest_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        development_excluded_ids=development_excluded_ids,
    )
    review_decisions = (
        _load(review_decisions_path)
        if review_decisions_path is not None
        else None
    )
    review_decisions_sha256 = (
        _sha256(review_decisions_path)
        if review_decisions_path is not None
        else None
    )
    audit = _recompute_semantic_audit(
        review_sample=review_sample,
        regression=regression,
        challenges=challenges,
        assignments=assignments,
        policy=policy,
        policy_sha256=policy_sha256,
        review_decisions=review_decisions,
        review_decisions_sha256=review_decisions_sha256,
    )
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "dataset_version": _dataset_version(policy),
        "delivery_mode": "versioned_static_tag_repair_audit",
        "generated_at_utc": base_manifest["generated_at_utc"],
        "base_dataset_version": base_manifest["dataset_version"],
        "base_manifest_sha256": base_manifest_sha256,
        "dictionary_version": policy.dictionary_version,
        "dictionary_sha256": policy.dictionary_sha256,
        "predicate_policy_version": policy.policy_version,
        "predicate_policy_sha256": policy_sha256,
        "legacy_sample_sha256": _sha256(legacy_sample_path),
        "legacy_decisions_sha256": _sha256(legacy_decisions_path),
        "review_sample_sha256": _object_sha256(review_sample),
        "review_decisions_sha256": review_decisions_sha256,
        "status": audit["summary"]["status"],
        "audit_summary": audit["summary"],
        "files": {},
        "boundaries": dict(policy.boundaries),
    }
    if exclusion_metadata is not None:
        manifest.update(
            {
                "prior_repair_manifest_sha256": exclusion_metadata[
                    "prior_repair_manifest_sha256"
                ],
                "development_evidence_sha256": exclusion_metadata[
                    "development_evidence_sha256"
                ],
            }
        )
    return {
        "assignments": assignments,
        "regression-audit": regression,
        "review-sample": review_sample,
        "challenge-cases": challenges,
        "semantic-audit": audit,
        "manifest": manifest,
    }


def _assert_boundaries(boundaries: dict[str, Any], *, label: str) -> None:
    expected = {
        "dictionary_mutated": False,
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "independent_human_review": False,
    }
    for key, expected_value in expected.items():
        if boundaries.get(key) is not expected_value:
            raise ValueError(f"{label} boundary mismatch: {key}")


def _validate_manifest_and_files(
    repair_dir: Path,
    manifest: dict[str, Any],
    expected_dataset_version: str,
) -> dict[str, Any]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("repair manifest schema mismatch")
    if manifest.get("dataset_version") != expected_dataset_version:
        raise ValueError("repair dataset version mismatch")
    if set(manifest.get("files", {})) != set(FILE_NAMES):
        raise ValueError("repair manifest file set mismatch")
    allowed = {"manifest.json", "validation-receipt.json", *FILE_NAMES}
    actual = {path.name for path in repair_dir.iterdir() if path.is_file()}
    if not {"manifest.json", *FILE_NAMES}.issubset(actual):
        raise ValueError("repair snapshot file set incomplete")
    unexpected = actual - allowed
    if unexpected:
        raise ValueError(f"repair snapshot contains unexpected files: {sorted(unexpected)}")

    artifacts: dict[str, Any] = {}
    for filename in FILE_NAMES:
        path = repair_dir / filename
        metadata = manifest["files"][filename]
        if path.stat().st_size != metadata.get("bytes"):
            raise ValueError(f"repair file byte count mismatch: {filename}")
        if _sha256(path) != metadata.get("sha256"):
            raise ValueError(f"repair file sha256 mismatch: {filename}")
        value = _load(path)
        if value.get("schema_version") != EXPECTED_SCHEMAS[filename]:
            raise ValueError(f"repair artifact schema mismatch: {filename}")
        artifacts[ARTIFACT_KEYS[filename]] = value
    return artifacts


def _validate_assignments(
    assignments: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    rows = assignments.get("assignments", [])
    if assignments.get("dataset_version") != manifest.get("dataset_version"):
        raise ValueError("assignment dataset version mismatch")
    if len(rows) != 243:
        raise ValueError("assignment candidate count mismatch")
    if len({row.get("audit_id") for row in rows}) != len(rows):
        raise ValueError("duplicate assignment audit id")
    if {row.get("tag_id") for row in rows} != TARGET_TAG_IDS:
        raise ValueError("assignment target tag set mismatch")
    if {row.get("predicate_status") for row in rows} - ALLOWED_STATUSES:
        raise ValueError("invalid assignment predicate status")
    for row in rows:
        if not row.get("reason_code") or not row.get("predicate_version"):
            raise ValueError(f"incomplete assignment evidence: {row.get('audit_id')}")
        if not isinstance(row.get("sentence_indexes"), list):
            raise ValueError(f"invalid assignment sentence indexes: {row.get('audit_id')}")
        if len(row["sentence_indexes"]) != len(row.get("evidence_sentences", [])):
            raise ValueError(f"assignment sentence evidence mismatch: {row['audit_id']}")

    counts = Counter(row["predicate_status"] for row in rows)
    expected_counts = {
        status: counts[status] for status in sorted(ALLOWED_STATUSES)
    }
    if assignments.get("summary", {}).get("by_status") != expected_counts:
        raise ValueError("assignment status summary mismatch")
    if assignments["summary"].get("lexical_candidates") != len(rows):
        raise ValueError("assignment total summary mismatch")
    if assignments.get("base_manifest_sha256") != manifest.get("base_manifest_sha256"):
        raise ValueError("assignment base binding mismatch")
    _assert_boundaries(assignments.get("boundaries", {}), label="assignment")
    return {row["audit_id"]: row for row in rows}


def _validate_regression(
    regression: dict[str, Any],
    assignment_by_id: dict[str, dict[str, Any]],
) -> None:
    summary = regression.get("summary", {})
    rows = regression.get("samples", [])
    if len(rows) != 80 or summary.get("legacy_held_samples") != 80:
        raise ValueError("legacy regression sample count mismatch")
    if summary.get("in_scope_samples") != 40 or summary.get("out_of_scope_samples") != 40:
        raise ValueError("legacy regression scope count mismatch")
    if summary.get("regression_failures") != 0:
        raise ValueError("legacy regression contains failures")
    for row in rows:
        if not row.get("regression_pass"):
            raise ValueError(f"legacy regression failed: {row.get('audit_id')}")
        if row.get("in_repair_scope"):
            assignment = assignment_by_id.get(row["audit_id"])
            if assignment is None:
                raise ValueError(f"legacy regression assignment missing: {row['audit_id']}")
            if row.get("predicate_status") != assignment.get("predicate_status"):
                raise ValueError(f"legacy regression status mismatch: {row['audit_id']}")
    for tag_id in TARGET_TAG_IDS:
        tag_summary = summary.get("by_tag", {}).get(tag_id, {})
        if tag_summary.get("samples") != 10:
            raise ValueError(f"legacy regression tag sample count mismatch: {tag_id}")
        if tag_summary.get("failures") != 0:
            raise ValueError(f"legacy regression tag failure: {tag_id}")
        if tag_summary.get("known_incorrect_confirmed") != 0:
            raise ValueError(f"legacy known error confirmed: {tag_id}")
        if tag_summary.get("known_ambiguous_not_needs_review") != 0:
            raise ValueError(f"legacy ambiguity not preserved: {tag_id}")
    _assert_boundaries(regression.get("boundaries", {}), label="regression")


def _legacy_ids(legacy_sample_path: Path) -> set[str]:
    legacy = _load(legacy_sample_path)
    return {
        sample["audit_id"]
        for tag in legacy.get("tags", [])
        for sample in tag.get("samples", [])
    }


def _validate_review_sample(
    sample: dict[str, Any],
    assignment_by_id: dict[str, dict[str, Any]],
    legacy_ids: set[str],
    development_excluded_ids: set[str] | None = None,
) -> None:
    development_excluded_ids = development_excluded_ids or set()
    tags = sample.get("tags", [])
    if {tag.get("tag_id") for tag in tags} != TARGET_TAG_IDS:
        raise ValueError("repair review sample tag set mismatch")
    all_ids: list[str] = []
    for tag in tags:
        samples = tag.get("samples", [])
        expected_count = min(30, tag.get("fresh_confirmed_candidates", -1))
        if tag.get("planned_sample_count") != expected_count:
            raise ValueError(f"repair review sample plan mismatch: {tag['tag_id']}")
        if tag.get("sample_count") != expected_count or len(samples) != expected_count:
            raise ValueError(f"repair review sample count mismatch: {tag['tag_id']}")
        expected_mode = (
            "fixed_30"
            if tag["fresh_confirmed_candidates"] >= 30
            else "full_fresh_population"
        )
        if tag.get("sample_mode") != expected_mode:
            raise ValueError(f"repair review sample mode mismatch: {tag['tag_id']}")
        for row in samples:
            audit_id = row.get("audit_id")
            if audit_id in legacy_ids:
                raise ValueError(f"repair review sample overlaps legacy audit: {audit_id}")
            if audit_id in development_excluded_ids:
                raise ValueError(
                    f"repair review sample overlaps development evidence: {audit_id}"
                )
            assignment = assignment_by_id.get(audit_id)
            if assignment is None or assignment.get("predicate_status") != "confirmed":
                raise ValueError(f"repair review sample is not confirmed: {audit_id}")
            if row.get("tag_id") != tag.get("tag_id"):
                raise ValueError(f"repair review sample tag mismatch: {audit_id}")
            if not row.get("context_excerpt"):
                raise ValueError(f"repair review sample context missing: {audit_id}")
            all_ids.append(audit_id)
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("duplicate repair review sample audit id")
    if development_excluded_ids:
        method = sample.get("method", {})
        for field in (
            "development_evidence_overlap_allowed",
            "prior_review_sample_overlap_allowed",
            "prior_challenge_overlap_allowed",
        ):
            if method.get(field) is not False:
                raise ValueError(f"repair review sample exclusion flag mismatch: {field}")
    _assert_boundaries(sample.get("boundaries", {}), label="review sample")


def _validate_challenges(
    challenges: dict[str, Any],
    assignment_by_id: dict[str, dict[str, Any]],
    development_excluded_ids: set[str] | None = None,
) -> None:
    development_excluded_ids = development_excluded_ids or set()
    tags = challenges.get("tags", [])
    if {tag.get("tag_id") for tag in tags} != TARGET_TAG_IDS:
        raise ValueError("challenge tag set mismatch")
    for tag in tags:
        cases = tag.get("cases", [])
        if tag.get("challenge_target") != QUALITY_GATE["minimum_challenge_cases"]:
            raise ValueError(f"challenge target mismatch: {tag['tag_id']}")
        if tag.get("challenge_count") != len(cases) or len(cases) > 20:
            raise ValueError(f"challenge count mismatch: {tag['tag_id']}")
        if tag.get("target_met") != (len(cases) >= 20):
            raise ValueError(f"challenge target flag failed: {tag['tag_id']}")
        if len({row.get("audit_id") for row in cases}) != len(cases):
            raise ValueError(f"duplicate challenge audit id: {tag['tag_id']}")
        for row in cases:
            if row.get("audit_id") in development_excluded_ids:
                raise ValueError(
                    f"challenge overlaps development evidence: {row['audit_id']}"
                )
            assignment = assignment_by_id.get(row.get("audit_id"))
            if assignment is None:
                raise ValueError(f"challenge assignment missing: {row.get('audit_id')}")
            if assignment.get("predicate_status") not in {"rejected", "needs_review"}:
                raise ValueError(f"confirmed assignment in challenges: {row['audit_id']}")
            if row.get("predicate_status") != assignment.get("predicate_status"):
                raise ValueError(f"challenge status mismatch: {row['audit_id']}")
    if development_excluded_ids and challenges.get("method", {}).get(
        "development_evidence_overlap_allowed"
    ) is not False:
        raise ValueError("challenge development evidence exclusion flag mismatch")
    _assert_boundaries(challenges.get("boundaries", {}), label="challenge")


def _validate_semantic_audit(
    audit: dict[str, Any],
    sample: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    tags = audit.get("tags", [])
    if {tag.get("tag_id") for tag in tags} != TARGET_TAG_IDS:
        raise ValueError("semantic audit tag set mismatch")
    if audit.get("quality_gate") != QUALITY_GATE:
        raise ValueError("semantic audit quality gate mismatch")
    if audit.get("review_sample_sha256") != manifest.get("review_sample_sha256"):
        raise ValueError("semantic audit sample binding mismatch")
    if audit.get("review_decisions_sha256") != manifest.get("review_decisions_sha256"):
        raise ValueError("semantic audit review decision binding mismatch")
    _assert_boundaries(audit.get("boundaries", {}), label="semantic audit")

    review_status = audit.get("review_status")
    if review_status not in {"pending", "complete"}:
        raise ValueError("semantic audit review status invalid")
    expected_total = sum(tag.get("sample_count", 0) for tag in sample.get("tags", []))
    if audit.get("summary", {}).get("reviewed_assignments") != expected_total:
        raise ValueError("semantic audit reviewed assignment count mismatch")

    promoted: list[str] = []
    held: list[str] = []
    for tag in tags:
        reviews = [row.get("review", {}) for row in tag.get("samples", [])]
        verdicts = Counter(review.get("label_verdict") for review in reviews)
        taxonomy = Counter(review.get("taxonomy_fit") for review in reviews)
        if review_status == "pending":
            if any(review.get("label_verdict") != "pending" for review in reviews):
                raise ValueError(f"partially reviewed pending audit: {tag['tag_id']}")
        else:
            allowed_verdicts = {"correct", "incorrect", "ambiguous"}
            allowed_taxonomy = {"fit", "mismatch", "ambiguous"}
            if any(review.get("label_verdict") not in allowed_verdicts for review in reviews):
                raise ValueError(f"incomplete semantic review: {tag['tag_id']}")
            if any(review.get("taxonomy_fit") not in allowed_taxonomy for review in reviews):
                raise ValueError(f"incomplete taxonomy review: {tag['tag_id']}")
            if any(not review.get("reason_code") or not review.get("note") for review in reviews):
                raise ValueError(f"incomplete semantic review rationale: {tag['tag_id']}")

        decidable = verdicts["correct"] + verdicts["incorrect"]
        precision = verdicts["correct"] / decidable if decidable else 0.0
        taxonomy_fit = taxonomy["fit"] / len(reviews) if reviews else 0.0
        ambiguous_rate = verdicts["ambiguous"] / len(reviews) if reviews else 0.0
        expected_metrics = {
            "reviewed": len(reviews),
            "correct": verdicts["correct"],
            "incorrect": verdicts["incorrect"],
            "ambiguous": verdicts["ambiguous"],
            "label_precision": round(precision, 6),
            "wilson_lower_bound_95": round(
                _wilson_lower_bound(verdicts["correct"], decidable), 6
            ),
            "taxonomy_fit_rate": round(taxonomy_fit, 6),
            "ambiguous_rate": round(ambiguous_rate, 6),
        }
        if tag.get("review_metrics") != expected_metrics:
            raise ValueError(f"semantic review metric mismatch: {tag['tag_id']}")
        checks = tag.get("gate_checks", {})
        if set(checks) != {
            "review_complete",
            "sample_plan_complete",
            "label_precision",
            "wilson_lower_bound_95",
            "taxonomy_fit_rate",
            "ambiguous_rate",
            "governance_fit",
            "legacy_known_errors_blocked",
            "legacy_ambiguities_preserved",
            "challenge_count",
        }:
            raise ValueError(f"semantic gate check set mismatch: {tag['tag_id']}")
        expected_promotion = (
            "promoted_after_repair"
            if all(checks.values())
            else "held_after_repair"
        )
        if tag.get("promotion_status") != expected_promotion:
            raise ValueError(f"semantic promotion mismatch: {tag['tag_id']}")
        (promoted if expected_promotion == "promoted_after_repair" else held).append(
            tag["tag_id"]
        )

    summary = audit.get("summary", {})
    if summary.get("promoted_tag_ids") != promoted or summary.get("held_tag_ids") != held:
        raise ValueError("semantic audit tag summary mismatch")
    if summary.get("promoted_after_repair") != len(promoted):
        raise ValueError("semantic audit promotion count mismatch")
    if summary.get("held_after_repair") != len(held):
        raise ValueError("semantic audit held count mismatch")

    if review_status == "pending":
        if manifest.get("status") != "review_pending" or summary.get("status") != "review_pending":
            raise ValueError("pending repair status mismatch")
        if audit.get("reviewer", {}).get("independent_human_review") is not False:
            raise ValueError("pending reviewer boundary mismatch")
        return "passed_review_pending"

    if manifest.get("status") == "review_pending" or summary.get("status") == "review_pending":
        raise ValueError("completed repair remains pending")
    reviewer = audit.get("reviewer", {})
    if reviewer.get("independent_human_review") is not False:
        raise ValueError("semantic reviewer human-review boundary mismatch")
    if not reviewer.get("type") or not reviewer.get("version") or not reviewer.get("review_policy"):
        raise ValueError("semantic reviewer metadata incomplete")
    return "passed"


def validate(
    repair_dir: Path,
    snapshot_dir: Path,
    policy_path: Path,
    legacy_sample_path: Path,
    legacy_decisions_path: Path,
    review_decisions_path: Path | None = None,
    *,
    receipt_path: Path | None = None,
    prior_repair_dir: Path | None = None,
    development_evidence_path: Path | None = None,
) -> dict[str, Any]:
    repair_dir = repair_dir.resolve(strict=True)
    snapshot_dir = snapshot_dir.resolve(strict=True)
    policy_path = policy_path.resolve(strict=True)
    legacy_sample_path = legacy_sample_path.resolve(strict=True)
    legacy_decisions_path = legacy_decisions_path.resolve(strict=True)
    if review_decisions_path is not None:
        review_decisions_path = review_decisions_path.resolve(strict=True)

    base_manifest_path = snapshot_dir / "manifest.json"
    base_manifest_sha256 = _sha256(base_manifest_path)
    dictionary = _load(snapshot_dir / "tag-dictionary.json")
    policy = load_policy(
        policy_path,
        expected_base_manifest_sha256=base_manifest_sha256,
        expected_dictionary_sha256=dictionary["dictionary_sha256"],
    )
    if (
        policy.repair_dataset_version != DEFAULT_REPAIR_DATASET_VERSION
        and (prior_repair_dir is None or development_evidence_path is None)
    ):
        raise ValueError("v2 repair requires frozen development evidence")
    development_excluded_ids, exclusion_metadata = _development_exclusion(
        prior_repair_dir=prior_repair_dir,
        development_evidence_path=development_evidence_path,
        base_manifest_sha256=base_manifest_sha256,
    )

    manifest_path = repair_dir / "manifest.json"
    manifest = _load(manifest_path)
    artifacts = _validate_manifest_and_files(
        repair_dir,
        manifest,
        policy.repair_dataset_version,
    )

    expected = _independently_recompute(
        snapshot_dir,
        policy_path,
        legacy_sample_path,
        legacy_decisions_path,
        review_decisions_path,
        prior_repair_dir,
        development_evidence_path,
    )
    for filename, artifact_key in ARTIFACT_KEYS.items():
        if artifacts[artifact_key] != expected[artifact_key]:
            label = "assignment" if filename == "assignments.json" else filename
            raise ValueError(f"{label} recomputation mismatch")
    for key, value in expected["manifest"].items():
        if key == "files":
            continue
        if manifest.get(key) != value:
            raise ValueError(f"repair manifest recomputation mismatch: {key}")

    if manifest.get("base_manifest_sha256") != _sha256(base_manifest_path):
        raise ValueError("repair base manifest hash mismatch")
    if manifest.get("predicate_policy_sha256") != _sha256(policy_path):
        raise ValueError("repair predicate policy hash mismatch")
    if manifest.get("legacy_sample_sha256") != _sha256(legacy_sample_path):
        raise ValueError("repair legacy sample hash mismatch")
    if manifest.get("legacy_decisions_sha256") != _sha256(legacy_decisions_path):
        raise ValueError("repair legacy decisions hash mismatch")
    if review_decisions_path is None:
        if manifest.get("review_decisions_sha256") is not None:
            raise ValueError("pending repair unexpectedly binds review decisions")
    elif manifest.get("review_decisions_sha256") != _sha256(review_decisions_path):
        raise ValueError("repair review decisions hash mismatch")
    if manifest.get("review_sample_sha256") != _sha256(repair_dir / "review-sample.json"):
        raise ValueError("repair review sample hash mismatch")
    if exclusion_metadata is not None:
        if manifest.get("prior_repair_manifest_sha256") != exclusion_metadata[
            "prior_repair_manifest_sha256"
        ]:
            raise ValueError("repair prior manifest hash mismatch")
        if manifest.get("development_evidence_sha256") != exclusion_metadata[
            "development_evidence_sha256"
        ]:
            raise ValueError("repair development evidence hash mismatch")
    _assert_boundaries(manifest.get("boundaries", {}), label="manifest")

    assignment_by_id = _validate_assignments(artifacts["assignments"], manifest)
    _validate_regression(artifacts["regression-audit"], assignment_by_id)
    _validate_review_sample(
        artifacts["review-sample"],
        assignment_by_id,
        _legacy_ids(legacy_sample_path),
        development_excluded_ids,
    )
    _validate_challenges(
        artifacts["challenge-cases"],
        assignment_by_id,
        development_excluded_ids,
    )
    status = _validate_semantic_audit(
        artifacts["semantic-audit"], artifacts["review-sample"], manifest
    )

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "dataset_version": manifest["dataset_version"],
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "manifest_sha256": _sha256(manifest_path),
        "base_manifest_sha256": manifest["base_manifest_sha256"],
        "predicate_policy_sha256": manifest["predicate_policy_sha256"],
        "review_status": artifacts["semantic-audit"]["review_status"],
        "audit_summary": artifacts["semantic-audit"]["summary"],
        "checks": {
            "manifest_and_file_hashes": True,
            "independent_recomputation": True,
            "assignment_state_machine": True,
            "legacy_regression": True,
            "zero_overlap_review_sample": True,
            "challenge_cases": True,
            "semantic_gate_calculation": True,
            "side_effect_boundaries": True,
        },
        "production_unchanged": True,
        "provider_call": False,
        "database_write": False,
        "live_send": False,
        "independent_human_review": False,
    }
    if exclusion_metadata is not None:
        receipt["checks"]["development_evidence_zero_overlap"] = True
        receipt["prior_repair_manifest_sha256"] = exclusion_metadata[
            "prior_repair_manifest_sha256"
        ]
        receipt["development_evidence_sha256"] = exclusion_metadata[
            "development_evidence_sha256"
        ]
    if receipt_path is not None:
        _write(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair-dir", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--legacy-sample", type=Path, required=True)
    parser.add_argument("--legacy-decisions", type=Path, required=True)
    parser.add_argument("--review-decisions", type=Path)
    parser.add_argument("--prior-repair-dir", type=Path)
    parser.add_argument("--development-evidence", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = validate(
        args.repair_dir,
        args.snapshot_dir,
        args.policy,
        args.legacy_sample,
        args.legacy_decisions,
        args.review_decisions,
        receipt_path=args.receipt,
        prior_repair_dir=args.prior_repair_dir,
        development_evidence_path=args.development_evidence,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
