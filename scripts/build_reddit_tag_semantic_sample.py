#!/usr/bin/env python3
"""Build a deterministic, stratified review sample for Reddit VOC rule tags."""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "reddit_voc_tag_semantic_sample_v1"
DEFAULT_TOP_TAGS = 10
DEFAULT_SAMPLES_PER_TAG = 10
DEFAULT_POST_SAMPLES_PER_TAG = 3
SOURCE_PRIORITY = (
    "tencent_production_primary",
    "historical_canonical",
    "imported_archive",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _stable_rank(dataset_version: str, tag_id: str, entity_type: str, entity_id: str) -> str:
    value = f"{dataset_version}|{tag_id}|{entity_type}|{entity_id}".encode()
    return sha256(value).hexdigest()


def _source_stratum(source_kinds: Iterable[str]) -> str:
    values = set(source_kinds)
    for source in SOURCE_PRIORITY:
        if source in values:
            return source
    return "unknown"


def _excerpt(text: str, evidence_keywords: list[str], *, limit: int = 520) -> str:
    normalized = " ".join(text.split())
    lowered = normalized.casefold()
    positions = [
        lowered.find(keyword.casefold())
        for keyword in evidence_keywords
        if keyword and lowered.find(keyword.casefold()) >= 0
    ]
    center = min(positions) if positions else 0
    start = max(0, center - limit // 3)
    end = min(len(normalized), start + limit)
    if end - start < limit:
        start = max(0, end - limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(normalized) else ""
    return f"{prefix}{normalized[start:end]}{suffix}"


def _round_robin_sample(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["source_stratum"]].append(row)
    for values in groups.values():
        values.sort(key=lambda row: row["stable_rank"])

    ordered_strata = [source for source in SOURCE_PRIORITY if groups.get(source)]
    ordered_strata.extend(sorted(set(groups) - set(ordered_strata)))
    selected: list[dict[str, Any]] = []
    while len(selected) < count:
        added = False
        for source in ordered_strata:
            if groups[source]:
                selected.append(groups[source].pop(0))
                added = True
                if len(selected) == count:
                    break
        if not added:
            break
    return selected


def _entity_rows(
    *,
    dataset_version: str,
    tag_id: str,
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entity_type, entities in (("post", posts), ("comment", comments)):
        for entity in entities:
            if entity_type == "comment" and not entity["include_in_voc_metrics"]:
                continue
            matches = [
                match for match in entity["tagging"]["matches"] if match["tag_id"] == tag_id
            ]
            if not matches:
                continue
            match = matches[0]
            entity_id = str(entity["post_id"] if entity_type == "post" else entity["comment_id"])
            source_kinds = (
                entity["source_kinds"]
                if entity_type == "post"
                else [item["source_kind"] for item in entity["source_occurrences"]]
            )
            text = (
                f"{entity['title']}\n{entity['content']}"
                if entity_type == "post"
                else str(entity["body"])
            )
            rows.append(
                {
                    "audit_id": f"{tag_id}:{entity_type}:{entity_id}",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "reddit_id": entity["reddit_id"],
                    "post_id": entity["post_id"],
                    "subreddit": entity.get("subreddit"),
                    "created_at_utc": entity["created_at_utc"],
                    "source_stratum": _source_stratum(source_kinds),
                    "source_kinds": sorted(set(source_kinds)),
                    "evidence_keywords": match["evidence_keywords"],
                    "context_excerpt": _excerpt(text, match["evidence_keywords"]),
                    "stable_rank": _stable_rank(
                        dataset_version, tag_id, entity_type, entity_id
                    ),
                    "review": {
                        "label_verdict": "pending",
                        "taxonomy_fit": "pending",
                        "reason_code": "pending",
                        "note": "",
                    },
                }
            )
    return rows


def build_sample(
    snapshot_dir: Path,
    *,
    top_tag_count: int = DEFAULT_TOP_TAGS,
    samples_per_tag: int = DEFAULT_SAMPLES_PER_TAG,
    post_samples_per_tag: int = DEFAULT_POST_SAMPLES_PER_TAG,
) -> dict[str, Any]:
    manifest = _load(snapshot_dir / "manifest.json")
    aggregates = _load(snapshot_dir / "aggregates.json")
    posts = _load(snapshot_dir / "posts.json")
    comments = _load(snapshot_dir / "comments.json")
    dictionary = _load(snapshot_dir / "tag-dictionary.json")
    rules = {row["tag_id"]: row for row in dictionary["rules"]}

    top_tags = aggregates["tagging"]["top_tags"][:top_tag_count]
    result_tags: list[dict[str, Any]] = []
    for summary in top_tags:
        tag_id = summary["tag_id"]
        population = _entity_rows(
            dataset_version=manifest["dataset_version"],
            tag_id=tag_id,
            posts=posts,
            comments=comments,
        )
        post_rows = [row for row in population if row["entity_type"] == "post"]
        comment_rows = [row for row in population if row["entity_type"] == "comment"]
        selected_posts = _round_robin_sample(
            post_rows, min(post_samples_per_tag, len(post_rows), samples_per_tag)
        )
        selected_comments = _round_robin_sample(
            comment_rows, min(samples_per_tag - len(selected_posts), len(comment_rows))
        )
        selected = [*selected_posts, *selected_comments]
        if len(selected) < samples_per_tag:
            selected_ids = {row["audit_id"] for row in selected}
            remaining = [row for row in population if row["audit_id"] not in selected_ids]
            selected.extend(_round_robin_sample(remaining, samples_per_tag - len(selected)))

        rule = rules[tag_id]
        result_tags.append(
            {
                "tag_id": tag_id,
                "name_cn": rule["name_cn"],
                "name_en": rule["name_en"],
                "theme": rule["theme"],
                "definition": rule["definition"],
                "keywords_en": rule["keywords_en"],
                "dictionary_reference": {
                    "aipl_node": rule["aipl_node"],
                    "consumer_card": rule["consumer_card"],
                    "story_lines": rule["story_lines"],
                    "problem_type": rule["problem_type"],
                    "intent_type": rule["intent_type"],
                    "business_impact": rule["business_impact"],
                    "strategy_package": rule["strategy_package"],
                    "biz_action": rule["biz_action"],
                    "dept_owner": rule["dept_owner"],
                },
                "population": summary,
                "sample_counts": {
                    "total": len(selected),
                    "posts": sum(row["entity_type"] == "post" for row in selected),
                    "comments": sum(row["entity_type"] == "comment" for row in selected),
                    "by_source_stratum": {
                        source: sum(row["source_stratum"] == source for row in selected)
                        for source in SOURCE_PRIORITY
                    },
                },
                "governance_review": {
                    "status": "pending",
                    "reason_code": "pending",
                    "note": "",
                },
                "samples": selected,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "base_dataset_version": manifest["dataset_version"],
        "base_manifest_sha256": sha256(
            (snapshot_dir / "manifest.json").read_bytes()
        ).hexdigest(),
        "dictionary_version": dictionary["dictionary_version"],
        "dictionary_sha256": dictionary["dictionary_sha256"],
        "method": {
            "selection": "top aspect tags by total matched entities",
            "sampling": "deterministic SHA-256 ranking, stratified by entity type and source",
            "top_tag_count": top_tag_count,
            "samples_per_tag": samples_per_tag,
            "post_sample_target_per_tag": post_samples_per_tag,
            "review_unit": "one tag assignment on one post or VOC-eligible comment",
            "label_verdicts": ["correct", "incorrect", "ambiguous"],
            "taxonomy_fit_values": ["fit", "mismatch", "ambiguous"],
            "dictionary_reference_dimensions": [
                "aipl_node",
                "consumer_card",
                "story_lines",
                "problem_type",
                "intent_type",
                "business_impact",
                "strategy_package",
                "biz_action",
                "dept_owner",
            ],
            "persona_boundary": "consumer_card is a tag-to-insight-card reference, not a user-level persona_id; true persona tags require the independent dim_persona pipeline",
        },
        "review_state": {
            "status": "pending",
            "reviewer_type": "codex_context_review",
            "independent_human_review": False,
        },
        "tags": result_tags,
        "boundaries": {
            "production_unchanged": True,
            "provider_call": False,
            "database_write": False,
            "live_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-tags", type=int, default=DEFAULT_TOP_TAGS)
    parser.add_argument("--samples-per-tag", type=int, default=DEFAULT_SAMPLES_PER_TAG)
    parser.add_argument(
        "--post-samples-per-tag", type=int, default=DEFAULT_POST_SAMPLES_PER_TAG
    )
    args = parser.parse_args()
    result = build_sample(
        args.snapshot_dir.resolve(strict=True),
        top_tag_count=args.top_tags,
        samples_per_tag=args.samples_per_tag,
        post_samples_per_tag=args.post_samples_per_tag,
    )
    _write(args.output, result)
    print(
        json.dumps(
            {
                "status": "sample_built",
                "output": str(args.output),
                "tags": len(result["tags"]),
                "samples": sum(len(tag["samples"]) for tag in result["tags"]),
                **result["boundaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
