#!/usr/bin/env python3
"""Build a deterministic, review-gated Reddit semantic tag repair snapshot."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Iterable

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
DEVELOPMENT_EVIDENCE_SCHEMA = "reddit_voc_tag_repair_development_evidence_v1"
SOURCE_PRIORITY = (
    "tencent_production_primary",
    "historical_canonical",
    "imported_archive",
)
FILE_NAMES = (
    "assignments.json",
    "regression-audit.json",
    "review-sample.json",
    "challenge-cases.json",
    "semantic-audit.json",
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
    prior_manifest_path = prior_repair_dir / "manifest.json"
    prior_assignments_path = prior_repair_dir / "assignments.json"
    prior_review_path = prior_repair_dir / "review-sample.json"
    prior_challenges_path = prior_repair_dir / "challenge-cases.json"
    prior_manifest = _load(prior_manifest_path)
    evidence = _load(development_evidence_path)

    if evidence.get("schema_version") != DEVELOPMENT_EVIDENCE_SCHEMA:
        raise ValueError("development evidence schema mismatch")
    if evidence.get("base_manifest_sha256") != base_manifest_sha256:
        raise ValueError("development evidence base manifest mismatch")
    prior_manifest_sha256 = _sha256(prior_manifest_path)
    if evidence.get("prior_repair_manifest_sha256") != prior_manifest_sha256:
        raise ValueError("development evidence prior manifest mismatch")
    if evidence.get("prior_repair_dataset_version") != prior_manifest.get(
        "dataset_version"
    ):
        raise ValueError("development evidence prior dataset mismatch")

    bound_files = {
        "assignments.json": (
            prior_assignments_path,
            "prior_assignments_sha256",
        ),
        "review-sample.json": (
            prior_review_path,
            "prior_review_sample_sha256",
        ),
        "challenge-cases.json": (
            prior_challenges_path,
            "prior_challenge_cases_sha256",
        ),
    }
    for filename, (path, evidence_field) in bound_files.items():
        actual_sha256 = _sha256(path)
        if prior_manifest.get("files", {}).get(filename, {}).get(
            "sha256"
        ) != actual_sha256:
            raise ValueError(f"prior repair file manifest mismatch: {filename}")
        if evidence.get(evidence_field) != actual_sha256:
            raise ValueError(f"development evidence file hash mismatch: {filename}")

    reviewed_filter = evidence.get("reviewed_assignment_filter", {})
    if set(reviewed_filter.get("target_tag_ids", ())) != TARGET_TAG_IDS:
        raise ValueError("development evidence target tag set mismatch")
    statuses = set(reviewed_filter.get("predicate_statuses", ()))
    if not statuses or statuses - ALLOWED_STATUSES:
        raise ValueError("development evidence predicate status mismatch")
    predicate_version = reviewed_filter.get("predicate_version")
    assignments = _load(prior_assignments_path).get("assignments", [])
    reviewed_ids = {
        row["audit_id"]
        for row in assignments
        if row.get("tag_id") in TARGET_TAG_IDS
        and row.get("predicate_status") in statuses
        and row.get("predicate_version") == predicate_version
    }
    if len(reviewed_ids) != evidence.get("reviewed_assignment_count"):
        raise ValueError("development evidence reviewed count mismatch")
    if evidence.get("reviewer", {}).get("independent_human_review") is not False:
        raise ValueError("development evidence human-review boundary mismatch")

    prior_review_ids = {
        row["audit_id"]
        for tag in _load(prior_review_path).get("tags", [])
        for row in tag.get("samples", [])
    }
    prior_challenge_ids = {
        row["audit_id"]
        for tag in _load(prior_challenges_path).get("tags", [])
        for row in tag.get("cases", [])
    }
    excluded_ids = reviewed_ids | prior_review_ids | prior_challenge_ids
    return excluded_ids, {
        "prior_repair_manifest_sha256": prior_manifest_sha256,
        "development_evidence_sha256": _sha256(development_evidence_path),
        "reviewed_assignment_count": len(reviewed_ids),
        "prior_review_sample_count": len(prior_review_ids),
        "prior_challenge_count": len(prior_challenge_ids),
        "unique_development_exclusion_count": len(excluded_ids),
    }


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


def _source_stratum(source_kinds: Iterable[str]) -> str:
    values = set(source_kinds)
    for source in SOURCE_PRIORITY:
        if source in values:
            return source
    return "unknown"


def _stable_rank(
    policy_version: str, tag_id: str, entity_type: str, entity_id: str
) -> str:
    return sha256(
        f"{policy_version}|{tag_id}|{entity_type}|{entity_id}".encode("utf-8")
    ).hexdigest()


def _excerpt(text: str, evidence_keywords: list[str], *, limit: int = 760) -> str:
    normalized = " ".join(text.split())
    folded = normalized.casefold()
    positions = [
        folded.find(keyword.casefold())
        for keyword in evidence_keywords
        if keyword and folded.find(keyword.casefold()) >= 0
    ]
    center = min(positions) if positions else 0
    start = max(0, center - limit // 3)
    end = min(len(normalized), start + limit)
    if end - start < limit:
        start = max(0, end - limit)
    return (
        ("…" if start else "")
        + normalized[start:end]
        + ("…" if end < len(normalized) else "")
    )


def _round_robin(
    rows: list[dict[str, Any]], count: int, *, group_fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(str(row[field]) for field in group_fields)
        groups[key].append(row)
    for values in groups.values():
        values.sort(key=lambda row: row["stable_rank"])
    keys = sorted(groups)
    selected: list[dict[str, Any]] = []
    while len(selected) < count:
        added = False
        for key in keys:
            if groups[key]:
                selected.append(groups[key].pop(0))
                added = True
                if len(selected) == count:
                    break
        if not added:
            break
    return selected


def _expanded_legacy_decision(
    tag_review: dict[str, Any], audit_id: str
) -> dict[str, str]:
    result = dict(tag_review["default_decision"])
    result.update(tag_review.get("overrides", {}).get(audit_id, {}))
    return result


def _legacy_held_tag_ids(
    legacy_sample: dict[str, Any], legacy_decisions: dict[str, Any]
) -> set[str]:
    gate = legacy_decisions["quality_gate"]
    held: set[str] = set()
    for tag in legacy_sample["tags"]:
        review = legacy_decisions["tag_reviews"][tag["tag_id"]]
        decisions = [
            _expanded_legacy_decision(review, sample["audit_id"])
            for sample in tag["samples"]
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
            taxonomy["fit"] / len(decisions) >= gate["minimum_taxonomy_fit_rate"],
            verdicts["ambiguous"] / len(decisions) <= gate["maximum_ambiguous_rate"],
            review["governance_review"]["status"]
            == gate["governance_status_required"],
        )
        if not all(checks):
            held.add(tag["tag_id"])
    return held


def _assignment_rows(
    snapshot_dir: Path,
    policy: PredicatePolicy,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    posts = _load(snapshot_dir / "posts.json")
    comments = _load(snapshot_dir / "comments.json")
    post_by_id = {row["post_id"]: row for row in posts}
    entity_context: dict[str, dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    for entity_type, entities in (("post", posts), ("comment", comments)):
        for entity in entities:
            if entity_type == "comment" and not entity["include_in_voc_metrics"]:
                continue
            entity_id = str(
                entity["post_id"] if entity_type == "post" else entity["comment_id"]
            )
            text = (
                f"{entity['title']}\n{entity['content']}"
                if entity_type == "post"
                else str(entity["body"])
            )
            source_kinds = (
                entity["source_kinds"]
                if entity_type == "post"
                else [item["source_kind"] for item in entity["source_occurrences"]]
            )
            parent = entity if entity_type == "post" else post_by_id[entity["post_id"]]
            parent_text = f"{parent['title']}\n{parent['content']}"
            for lexical_match in entity["tagging"]["matches"]:
                tag_id = lexical_match["tag_id"]
                if tag_id not in TARGET_TAG_IDS:
                    continue
                decision = evaluate_assignment(
                    tag_id=tag_id,
                    text=text,
                    evidence_keywords=lexical_match["evidence_keywords"],
                    policy=policy,
                    brand_tag_ids=entity["tagging"]["brand_tag_ids"],
                    detected_spu_ids=entity["tagging"]["context"]["detected_spu_ids"],
                    parent_text=(parent_text if entity_type == "comment" else None),
                )
                audit_id = f"{tag_id}:{entity_type}:{entity_id}"
                row = {
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
                    "lexical_evidence_keywords": list(decision.evidence_keywords),
                    "predicate_status": decision.status,
                    "reason_code": decision.reason_code,
                    "sentence_indexes": list(decision.sentence_indexes),
                    "evidence_sentences": list(decision.evidence_sentences),
                    "predicate_version": decision.predicate_version,
                    "stable_rank": _stable_rank(
                        policy.policy_version, tag_id, entity_type, entity_id
                    ),
                }
                result.append(row)
                entity_context[audit_id] = {
                    "context_excerpt": _excerpt(
                        text, list(decision.evidence_keywords)
                    ),
                    "parent_context_excerpt": (
                        None
                        if entity_type == "post"
                        else _excerpt(parent_text, [], limit=560)
                    ),
                    "text_sha256": sha256(text.encode("utf-8")).hexdigest(),
                }
    result.sort(
        key=lambda row: (
            row["tag_id"],
            row["predicate_status"],
            row["entity_type"],
            row["entity_id"],
        )
    )
    return result, entity_context, {"posts": posts, "comments": comments}


def _assignments_artifact(
    *,
    rows: list[dict[str, Any]],
    base_manifest: dict[str, Any],
    base_manifest_sha256: str,
    policy: PredicatePolicy,
    policy_sha256: str,
) -> dict[str, Any]:
    by_status = Counter(row["predicate_status"] for row in rows)
    by_tag: dict[str, dict[str, int]] = {}
    for tag_id in policy.target_tag_ids:
        tag_rows = [row for row in rows if row["tag_id"] == tag_id]
        counts = Counter(row["predicate_status"] for row in tag_rows)
        by_tag[tag_id] = {
            "lexical_candidates": len(tag_rows),
            **{status: counts[status] for status in sorted(ALLOWED_STATUSES)},
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
                status: by_status[status] for status in sorted(ALLOWED_STATUSES)
            },
            "by_tag": by_tag,
        },
        "assignments": rows,
        "boundaries": dict(policy.boundaries),
    }


def _regression_artifact(
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
    for tag in legacy_sample["tags"]:
        tag_id = tag["tag_id"]
        if tag_id not in held_tag_ids:
            continue
        tag_review = legacy_decisions["tag_reviews"][tag_id]
        for sample in tag["samples"]:
            previous = _expanded_legacy_decision(tag_review, sample["audit_id"])
            in_scope = tag_id in TARGET_TAG_IDS
            repaired = assignment_by_id.get(sample["audit_id"])
            if in_scope and repaired is None:
                raise ValueError(f"legacy repair sample lacks lexical assignment: {sample['audit_id']}")
            status = repaired["predicate_status"] if repaired else "not_in_scope"
            if not in_scope:
                regression_pass = True
                expectation = "not_in_repair_scope_observed_only"
            elif previous["label_verdict"] == "incorrect":
                regression_pass = status != "confirmed"
                expectation = "must_not_confirm"
            elif previous["label_verdict"] == "ambiguous":
                regression_pass = status == "needs_review"
                expectation = "must_remain_needs_review"
            else:
                regression_pass = True
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
                        repaired["reason_code"] if repaired else "tag_not_in_repair_scope"
                    ),
                    "expectation": expectation,
                    "regression_pass": regression_pass,
                }
            )
    rows.sort(key=lambda row: row["audit_id"])
    by_tag = {}
    for tag_id in policy.target_tag_ids:
        values = [row for row in rows if row["tag_id"] == tag_id]
        by_tag[tag_id] = {
            "samples": len(values),
            "failures": sum(not row["regression_pass"] for row in values),
            "known_incorrect_confirmed": sum(
                row["previous_label_verdict"] == "incorrect"
                and row["predicate_status"] == "confirmed"
                for row in values
            ),
            "known_ambiguous_not_needs_review": sum(
                row["previous_label_verdict"] == "ambiguous"
                and row["predicate_status"] != "needs_review"
                for row in values
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
            "regression_failures": sum(not row["regression_pass"] for row in rows),
            "by_tag": by_tag,
        },
        "samples": rows,
        "boundaries": dict(policy.boundaries),
    }


def _review_row(
    row: dict[str, Any], entity_context: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    context = entity_context[row["audit_id"]]
    return {
        **row,
        **context,
        "review": {
            "label_verdict": "pending",
            "taxonomy_fit": "pending",
            "reason_code": "pending",
            "note": "",
        },
    }


def _review_sample_artifact(
    *,
    assignment_rows: list[dict[str, Any]],
    entity_context: dict[str, dict[str, Any]],
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
    tags = []
    for tag_id in policy.target_tag_ids:
        confirmed = [
            row
            for row in assignment_rows
            if row["tag_id"] == tag_id
            and row["predicate_status"] == "confirmed"
            and row["audit_id"] not in excluded_ids
        ]
        planned = min(30, len(confirmed))
        selected = _round_robin(
            confirmed,
            planned,
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
                    name: rule[name]
                    for name in (
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
                "fresh_confirmed_candidates": len(confirmed),
                "planned_sample_count": planned,
                "sample_count": len(selected),
                "sample_mode": "fixed_30" if len(confirmed) >= 30 else "full_fresh_population",
                "samples": [_review_row(row, entity_context) for row in selected],
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


def _challenge_artifact(
    *,
    assignment_rows: list[dict[str, Any]],
    entity_context: dict[str, dict[str, Any]],
    base_manifest_sha256: str,
    policy: PredicatePolicy,
    policy_sha256: str,
    development_excluded_ids: set[str] | None = None,
) -> dict[str, Any]:
    development_excluded_ids = development_excluded_ids or set()
    tags = []
    for tag_id in policy.target_tag_ids:
        candidates = [
            row
            for row in assignment_rows
            if row["tag_id"] == tag_id
            and row["predicate_status"] in {"rejected", "needs_review"}
            and row["audit_id"] not in development_excluded_ids
        ]
        selected = _round_robin(
            candidates,
            min(20, len(candidates)),
            group_fields=("predicate_status", "reason_code", "source_stratum"),
        )
        tags.append(
            {
                "tag_id": tag_id,
                "available_nonconfirmed_candidates": len(candidates),
                "challenge_target": 20,
                "challenge_count": len(selected),
                "target_met": len(selected) >= 20,
                "cases": [
                    {
                        **row,
                        **entity_context[row["audit_id"]],
                    }
                    for row in selected
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


def _expanded_repair_decision(
    tag_review: dict[str, Any], audit_id: str
) -> dict[str, str]:
    result = dict(tag_review["default_decision"])
    result.update(tag_review.get("overrides", {}).get(audit_id, {}))
    if result.get("label_verdict") not in {"correct", "incorrect", "ambiguous"}:
        raise ValueError(f"invalid repair review label verdict: {audit_id}")
    if result.get("taxonomy_fit") not in {"fit", "mismatch", "ambiguous"}:
        raise ValueError(f"invalid repair review taxonomy fit: {audit_id}")
    if not result.get("reason_code") or not result.get("note"):
        raise ValueError(f"incomplete repair review decision: {audit_id}")
    return result


def _semantic_audit(
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
    if review_decisions is not None:
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
    else:
        reviewer = {
            "type": "codex_context_review",
            "version": "pending",
            "independent_human_review": False,
            "review_policy": "Pending full-context review of zero-overlap confirmed candidates.",
        }

    regression_by_tag = regression["summary"]["by_tag"]
    challenge_by_tag = {tag["tag_id"]: tag for tag in challenges["tags"]}
    assignment_by_tag = assignments["summary"]["by_tag"]
    audited_tags = []
    for tag in review_sample["tags"]:
        tag_id = tag["tag_id"]
        reviewed_samples = []
        if review_decisions is not None:
            tag_review = review_decisions["tag_reviews"][tag_id]
            governance = tag_review["governance_review"]
            explicit_overrides = tag_review.get("overrides", {})
            missing_overrides = sorted(
                sample["audit_id"]
                for sample in tag["samples"]
                if sample["audit_id"] not in explicit_overrides
            )
            if missing_overrides:
                raise ValueError(
                    "repair review decisions missing explicit overrides: "
                    + ", ".join(missing_overrides)
                )
            for sample in tag["samples"]:
                reviewed = dict(sample)
                reviewed["review"] = _expanded_repair_decision(
                    tag_review, sample["audit_id"]
                )
                reviewed_samples.append(reviewed)
        else:
            governance = {
                "status": "pending",
                "reason_code": "review_pending",
                "note": "Zero-overlap candidate review has not been completed.",
            }
            reviewed_samples = list(tag["samples"])
        verdicts = Counter(
            sample["review"]["label_verdict"] for sample in reviewed_samples
        )
        taxonomy = Counter(
            sample["review"]["taxonomy_fit"] for sample in reviewed_samples
        )
        decidable = verdicts["correct"] + verdicts["incorrect"]
        precision = verdicts["correct"] / decidable if decidable else 0.0
        taxonomy_fit = (
            taxonomy["fit"] / len(reviewed_samples) if reviewed_samples else 0.0
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
            == tag["planned_sample_count"]
            and tag["planned_sample_count"] > 0,
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
                "name_cn": tag["name_cn"],
                "name_en": tag["name_en"],
                "theme": tag["theme"],
                "definition": tag["definition"],
                "dictionary_reference": tag["dictionary_reference"],
                "predicate_counts": assignment_by_tag[tag_id],
                "fresh_confirmed_candidates": tag["fresh_confirmed_candidates"],
                "sample_mode": tag["sample_mode"],
                "review_metrics": {
                    "reviewed": len(reviewed_samples),
                    "correct": verdicts["correct"],
                    "incorrect": verdicts["incorrect"],
                    "ambiguous": verdicts["ambiguous"],
                    "label_precision": round(precision, 6),
                    "wilson_lower_bound_95": round(
                        _wilson_lower_bound(verdicts["correct"], decidable), 6
                    ),
                    "taxonomy_fit_rate": round(taxonomy_fit, 6),
                    "ambiguous_rate": round(ambiguous_rate, 6),
                },
                "governance_review": governance,
                "regression_summary": regression_by_tag[tag_id],
                "challenge_summary": {
                    key: challenge_by_tag[tag_id][key]
                    for key in (
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
    review_status = "complete" if review_decisions is not None else "pending"
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
        "review_status": review_status,
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


def build(
    snapshot_dir: Path,
    policy_path: Path,
    legacy_sample_path: Path,
    legacy_decisions_path: Path,
    *,
    review_decisions_path: Path | None,
    prior_repair_dir: Path | None = None,
    development_evidence_path: Path | None = None,
) -> dict[str, Any]:
    snapshot_dir = snapshot_dir.resolve(strict=True)
    policy_path = policy_path.resolve(strict=True)
    legacy_sample_path = legacy_sample_path.resolve(strict=True)
    legacy_decisions_path = legacy_decisions_path.resolve(strict=True)
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
    assignment_rows, entity_context, _ = _assignment_rows(snapshot_dir, policy)
    assignments = _assignments_artifact(
        rows=assignment_rows,
        base_manifest=base_manifest,
        base_manifest_sha256=base_manifest_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
    )
    regression = _regression_artifact(
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
        for tag in legacy_sample["tags"]
        if tag["tag_id"] in held_tag_ids
        for sample in tag["samples"]
    }
    rules_by_tag = {
        rule["tag_id"]: rule for rule in dictionary["rules"] if rule["tag_id"] in TARGET_TAG_IDS
    }
    review_sample = _review_sample_artifact(
        assignment_rows=assignment_rows,
        entity_context=entity_context,
        legacy_ids=legacy_ids,
        rules_by_tag=rules_by_tag,
        base_manifest=base_manifest,
        base_manifest_sha256=base_manifest_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        development_excluded_ids=development_excluded_ids,
        exclusion_metadata=exclusion_metadata,
    )
    challenges = _challenge_artifact(
        assignment_rows=assignment_rows,
        entity_context=entity_context,
        base_manifest_sha256=base_manifest_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        development_excluded_ids=development_excluded_ids,
    )
    if review_decisions_path is not None:
        review_decisions_path = review_decisions_path.resolve(strict=True)
        review_decisions = _load(review_decisions_path)
        review_decisions_sha256 = _sha256(review_decisions_path)
    else:
        review_decisions = None
        review_decisions_sha256 = None
    audit = _semantic_audit(
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


def write_snapshot(output_dir: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stem in (
        "assignments",
        "regression-audit",
        "review-sample",
        "challenge-cases",
        "semantic-audit",
    ):
        _write(output_dir / f"{stem}.json", artifacts[stem])
    manifest = dict(artifacts["manifest"])
    manifest["files"] = {
        name: {
            "bytes": (output_dir / name).stat().st_size,
            "sha256": _sha256(output_dir / name),
        }
        for name in FILE_NAMES
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--legacy-sample", type=Path, required=True)
    parser.add_argument("--legacy-decisions", type=Path, required=True)
    parser.add_argument("--review-decisions", type=Path)
    parser.add_argument("--prior-repair-dir", type=Path)
    parser.add_argument("--development-evidence", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    artifacts = build(
        args.snapshot_dir,
        args.policy,
        args.legacy_sample,
        args.legacy_decisions,
        review_decisions_path=args.review_decisions,
        prior_repair_dir=args.prior_repair_dir,
        development_evidence_path=args.development_evidence,
    )
    manifest = write_snapshot(args.output_dir, artifacts)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "dataset_version": manifest["dataset_version"],
                **manifest["audit_summary"],
                "production_unchanged": True,
                "provider_call": False,
                "database_write": False,
                "live_send": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
