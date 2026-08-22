from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read_json(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def read_csv(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


summary = read_json("analysis-summary.json")
overlap_audit = read_json("cross-source-overlap-audit.json")
merge_plan = read_json("cross-source-readonly-merge-plan.json")
internal_spu_master = read_json("internal-spu-master-join.json")
production_refresh = read_json("production-identity-refresh.json")
delta_coverage = read_json("delta-term-offline-coverage-audit.json")
delta_coverage_validation = read_json("delta-term-offline-coverage-validation.json")
comment_debt = read_json("comment-coverage-debt-audit.json")
comment_debt_validation = read_json("comment-coverage-debt-validation.json")
if not all(delta_coverage["checks"].values()) or delta_coverage_validation["status"] != "passed":
    raise RuntimeError("delta coverage evidence is not validated")
if not all(comment_debt["checks"].values()) or comment_debt_validation["status"] != "passed":
    raise RuntimeError("comment debt evidence is not validated")
completion = read_csv("completion-matrix.csv")
competitors = read_csv("brand-collection-coverage.csv")
spu_categories = read_csv("spu-category-profile.csv")
official_products = read_csv("official-product-name-catalog.csv")
generated_at = datetime.now(timezone.utc).isoformat()

group_labels = {
    "owner_alias_gap": "品牌别名",
    "momcozy_model_gap": "Momcozy 型号",
    "official_catalog_aliases": "官网产品别名",
    "governed_competitors": "治理竞品",
    "category_anchors": "品类锚点",
}
search_groups = []
search_coverage = []
for row in summary["search_profile"]["group_coverage"]:
    group = group_labels[row["group"]]
    normalized = {
        "group": group,
        "recommended_terms": row["recommended_terms"],
        "covered_by_legacy": row["covered_by_legacy"],
        "delta_terms": row["delta_terms"],
    }
    search_groups.append(normalized)
    search_coverage.extend(
        [
            {
                "group": group,
                "coverage_status": "旧运行已覆盖",
                "terms": row["covered_by_legacy"],
            },
            {
                "group": group,
                "coverage_status": "V2 delta 未执行",
                "terms": row["delta_terms"],
            },
        ]
    )

delta_class_labels = {
    "zero_existing_lexical_evidence": "零命中",
    "comment_only_existing_lexical_evidence": "仅评论命中",
    "post_only_existing_lexical_evidence": "仅帖子命中",
    "post_and_comment_existing_lexical_evidence": "帖子与评论均命中",
}
delta_class_order = list(delta_class_labels)
delta_coverage_class_rows = [
    {
        "coverage_class": delta_class_labels[coverage_class],
        "terms": delta_coverage["aggregate"]["coverage_classes"][coverage_class],
        "share_of_69": round(
            delta_coverage["aggregate"]["coverage_classes"][coverage_class] / 69,
            6,
        ),
        "priority_tier": f"P{index}",
        "provider_lanes_completed": 0,
        "interpretation": (
            "highest discovery priority"
            if index == 0
            else "existing lexical evidence only; discovery remains unexecuted"
        ),
    }
    for index, coverage_class in enumerate(delta_class_order)
]
delta_group_rows = [
    {
        "group": group_labels[group],
        "delta_terms": stats["terms"],
        "zero_evidence_terms": stats["zero_existing_lexical_evidence"],
        "comment_only_terms": stats["comment_only_existing_lexical_evidence"],
        "post_surface_covered_terms": stats["post_surface_covered_terms"],
        "comment_covered_terms": stats["comment_covered_terms"],
        "provider_lanes_completed": 0,
    }
    for group, stats in delta_coverage["aggregate"]["by_group"].items()
]
delta_probe_rows = [
    {
        "priority_rank": row["priority_rank"],
        "priority_tier": row["priority_tier"],
        "group": group_labels[row["group"]],
        "term": row["term"],
        "coverage_class": delta_class_labels[row["coverage_class"]],
        "post_surface_matches": row["deduplicated_union"]["post_surface_matches"],
        "comment_matches": row["deduplicated_union"]["comment_matches"],
        "evidence_parent_posts": row["deduplicated_union"]["evidence_parent_posts"],
        "provider_lane_status": row["provider_lane_status"],
    }
    for row in delta_coverage["rows"]
]

comment_gap_bucket_order = ["1-4", "5-9", "10-24", "25-99", "100+"]
comment_gap_bucket_rows = []
for bucket_order, gap_bucket in enumerate(comment_gap_bucket_order, start=1):
    bucket = comment_debt["aggregate"]["remaining_gap_buckets"][gap_bucket]
    comment_gap_bucket_rows.append(
        {
            "gap_bucket": gap_bucket,
            "bucket_order": bucket_order,
            "candidates": bucket["candidates"],
            "remaining_reported_gap": bucket["remaining_reported_gap"],
            "share_of_total_gap": round(
                bucket["remaining_reported_gap"]
                / comment_debt["aggregate"]["reported_gap_after_offline_union"],
                6,
            ),
            "remaining_gap_total": comment_debt["aggregate"][
                "reported_gap_after_offline_union"
            ],
            "definition": "max(reported comments - exact union comment IDs, 0)",
        }
    )
comment_debt_row_by_post = {row["post_id"]: row for row in comment_debt["rows"]}
comment_debt_priority_rows = []
for priority in comment_debt["priority_queue"]:
    row = comment_debt_row_by_post[priority["post_id"]]
    comment_debt_priority_rows.append(
        {
            "priority_rank": priority["priority_rank"],
            "priority_tier": priority["priority_tier"],
            "post_id": priority["post_id"],
            "status_reason": priority["status_reason"],
            "first_lane": f'{row["first_lane_type"]}:{row["first_lane_key"]}',
            "reported_comments": row["reported_comment_count"],
            "task37_comments": row["task37_distinct_comment_ids"],
            "local_only_increment": row["local_only_comment_increment"],
            "union_comments": row["deduplicated_union_comment_count"],
            "remaining_reported_gap": priority["remaining_reported_gap"],
            "more_nodes": priority["more_nodes"],
            "reopen_status": priority["provider_reopen_status"],
        }
    )
orphan_recovery_rows = [
    {
        "missing_parent_post_id": row["missing_parent_post_id"],
        "orphan_comments": row["orphan_comments"],
        "parent_in_task37": row["parent_in_task37"],
        "exact_comment_ids_in_task37": row["exact_comment_ids_in_task37"],
        "production_only_with_task37_parent": row[
            "production_only_comments_with_task37_parent"
        ],
        "structurally_recoverable": row["structurally_recoverable_comments"],
        "still_unlinked": row["still_unlinked_comments"],
        "private_content_rows_available": row["private_content_rows_available"],
    }
    for row in comment_debt["production_orphan_recovery"]["parent_groups"]
]

task37 = summary["collection_evidence"]["task37_remote_staging"]
task37_status = [
    {"status": "完整 hydrated", "candidates": task37["candidate_statuses"]["hydrated"], "terminal": True},
    {"status": "unresolved_more", "candidates": task37["candidate_statuses"]["hydrated/unresolved_more"], "terminal": False},
    {"status": "post_only", "candidates": task37["candidate_statuses"]["hydrated/post_only_coverage"], "terminal": False},
    {"status": "excluded", "candidates": task37["candidate_statuses"]["excluded"], "terminal": True},
]

overlap = overlap_audit["task37_increment_vs_local_canonical_union"]
overlap_rows = [
    {
        "component": "Local canonical union",
        "posts": overlap["local_canonical_union"]["posts"],
        "linked_comments": overlap["local_canonical_union"]["linked_comments"],
        "meaning": "Requested-window local baseline",
    },
    {
        "component": "Task 37 staging",
        "posts": overlap["task37_remote_staging"]["posts"],
        "linked_comments": overlap["task37_remote_staging"]["linked_comments"],
        "meaning": "Hash-pinned remote identity snapshot",
    },
    {
        "component": "Exact overlap",
        "posts": overlap["overlap"]["posts"],
        "linked_comments": overlap["overlap"]["linked_comments"],
        "meaning": "Same Reddit primary IDs in both sources",
    },
    {
        "component": "Task 37 only",
        "posts": overlap["task37_only"]["posts"],
        "linked_comments": overlap["task37_only"]["linked_comments"],
        "meaning": "Eligible for an isolated local merge after implementation gate",
    },
    {
        "component": "Local only",
        "posts": overlap["local_only"]["posts"],
        "linked_comments": overlap["local_only"]["linked_comments"],
        "meaning": "Must be preserved by any future merge",
    },
    {
        "component": "Deduplicated identity union",
        "posts": overlap["potential_deduplicated_union"]["posts"],
        "linked_comments": overlap["potential_deduplicated_union"]["linked_comments"],
        "meaning": "Potential union only; not yet materialized",
    },
]

merge_action_labels = {
    "insert_task37_only_posts": "Insert Task 37-only posts",
    "insert_comments_with_new_parent_posts": "Insert comments with new parent posts",
    "attach_new_comments_to_existing_local_posts": "Attach new comments to existing local posts",
    "preserve_local_only_posts": "Preserve local-only posts",
    "preserve_local_only_comments": "Preserve local-only comments",
    "recoverable_production_orphan_comments": "Recoverable production orphan comments",
    "recoverable_by_exact_task37_comment_id": "Recoverable by exact Task 37 comment ID",
    "recoverable_by_task37_parent_only": "Production-only comments recoverable by Task 37 parent",
    "remaining_unlinked_production_comments": "Remaining unlinked production comments",
}
merge_action_rows = [
    {
        "action": label,
        "entities": merge_plan["actions"][key],
        "state": "identity plan only; not executed",
    }
    for key, label in merge_action_labels.items()
]

competitor_rows = []
for row in competitors:
    mentions = int(row["requested_window_mentions_local_union"])
    archive_mentions = int(row["requested_window_mentions_imported_archive"])
    has_bucket = row["dedicated_archive_bucket"] == "True"
    if has_bucket:
        state = "已有归档 bucket，无历史 search lane"
    elif mentions:
        state = "仅偶发提及，无历史 search lane"
    else:
        state = "本地窗口未观察且无历史 search lane"
    competitor_rows.append(
        {
            "brand": row["brand"],
            "local_window_mentions": mentions,
            "archive_window_mentions": archive_mentions,
            "archive_bucket": "yes" if has_bucket else "no",
            "dedicated_historical_search_lane": "no",
            "coverage_state": state,
        }
    )

spu_rows = [
    {
        "voc_category": row["voc_category"],
        "product_lines": row["product_lines"],
        "distinct_spu_ids": int(row["distinct_spu_ids"]),
        "tag_rows": int(row["tag_rows"]),
        "name_boundary": (
            "explicit dictionary model/category label; exact SPU names joined"
            if row["voc_category"] in {"M5 吸奶器", "M9 吸奶器", "BS03 全自动清洗消毒器"}
            else "broad dictionary category; exact SPU names joined separately"
        ),
    }
    for row in spu_categories
]

internal_spu_rows = [
    {
        "spu_id": row["spu_id"],
        "spu_name": row["spu_name"],
        "product_name_en": row["product_name_en"],
        "product_model": row["product_model"] or "not separated",
        "product_type": row["product_type"],
        "master_product_line": row["master_product_line"],
        "master_voc_line": row["master_voc_line"],
        "dictionary_voc_categories": " | ".join(row["dictionary_voc_categories"]),
        "dictionary_tag_rows": row["dictionary_tag_rows"],
    }
    for row in internal_spu_master["rows"]
]

verified_internal_bindings = {
    row["family_id"]: row
    for row in internal_spu_master["official_family_binding_review"]["verified_single_internal_spu"]
}
reviewed_internal_boundaries = {
    row["family_id"]: row
    for row in internal_spu_master["official_family_binding_review"]["ambiguous_or_missing"]
}

official_product_rows = []
for row in official_products:
    verified = verified_internal_bindings.get(row["family_id"])
    boundary = reviewed_internal_boundaries.get(row["family_id"])
    if verified:
        internal_spu_join = verified["spu_id"]
        mapping_status = verified["mapping_status"]
    elif boundary:
        internal_spu_join = " | ".join(boundary["candidate_spu_ids"]) or "not present in 2026-05 internal snapshot"
        mapping_status = boundary["status"]
    else:
        internal_spu_join = row["internal_spu_ids"] or "not joined"
        mapping_status = row["internal_mapping_status"]
    official_product_rows.append(
        {
            "family_id": row["family_id"],
            "official_title": row["official_title"],
            "product_type": row["product_type"],
            "search_aliases": row["dictionary_runtime_aliases"],
            "internal_spu_join": internal_spu_join,
            "mapping_status": mapping_status,
            "new_search_terms": row["candidate_search_terms"] or "none",
            "official_url": row["official_url"],
        }
    )

collection = summary["collection_evidence"]
evidence_layers = [
    {
        "layer": "Imported archive",
        "posts": collection["imported_archive"]["posts"],
        "comments": collection["imported_archive"]["comments"],
        "status": "complete for supplied 136 files",
        "evidence_grade": "L2 local immutable import",
        "additive_rule": "overlaps 48 historical posts; do not add raw counts",
    },
    {
        "layer": "Local canonical union",
        "posts": collection["local_canonical_union"]["posts"],
        "comments": collection["local_canonical_union"]["linked_comments"],
        "status": "validated snapshot",
        "evidence_grade": "L2 validated local artifact",
        "additive_rule": "187 posts / 3,528 comments are in requested window",
    },
    {
        "layer": "Production daily snapshot",
        "posts": collection["production_read_only_snapshot"]["posts"],
        "comments": collection["production_read_only_snapshot"]["comments"],
        "status": "fresh identity capture; zero increment; through 2026-07-14 06:37 BJT for posts",
        "evidence_grade": "L3 production read-only",
        "additive_rule": "included in local canonical union; production unchanged",
    },
    {
        "layer": "Task 37 remote staging",
        "posts": task37["threads"],
        "comments": task37["comments"],
        "status": "partial; 96 comment candidates unresolved",
        "evidence_grade": "L4 authorized staging write, no Task 37 Provider call",
        "additive_rule": "identity overlap reconciled; use 410 / 4,730 union, never raw addition",
    },
]

completion_rows = [
    {
        "workstream": row["workstream"],
        "status": row["status"],
        "evidence": row["evidence"],
        "next_gate": row["next_gate"],
    }
    for row in completion
]

recommendations = [
    {
        "priority": 1,
        "action": "Govern active status and heuristic SPU aliases",
        "why": "The 254/254 name join is complete, but the May snapshot has no active/effective dates and its 772 spoken variants are not safe for automatic Reddit activation.",
        "gate": "internal lifecycle source plus manual alias review",
    },
    {
        "priority": 2,
        "action": "Implement a new-run V2 profile loader",
        "why": "The old run is hash-frozen; mutating its 15 terms would invalidate replay and release evidence.",
        "gate": "local RED/GREEN tests; no Provider",
    },
    {
        "priority": 3,
        "action": "Materialize the exact merge plan in isolated staging",
        "why": "Identity reconciliation is complete: preserve 109 local-only posts and add 223 Task 37-only posts without double-counting the 78-post overlap.",
        "gate": "lift local no-test boundary, then RED/GREEN tests",
    },
    {
        "priority": 4,
        "action": "Reconcile 21 local-only comments, then implement a comment-specific reopen contract",
        "why": "Seven candidates gain 21 exact-ID comments offline, but all 96 retain a reported-count gap. The remaining one-request reserve is below the 96-request first-page floor, and unresolved More nodes may require a different endpoint contract.",
        "gate": "lift local no-test boundary; RED/GREEN and a separate comment-repair packet",
    },
    {
        "priority": 5,
        "action": "Run a bounded one-page-per-lane probe",
        "why": "Offline evidence prioritizes 19 zero-hit terms first; the first reviewed candidate is Momcozy BM03, followed by DeepClean and S12 Pro Quick. A real probe is still needed before estimating discovery and hydration budget.",
        "gate": "new exact TikHub authorization",
    },
    {
        "priority": 6,
        "action": "Freeze historical-to-daily cutover",
        "why": "The current production snapshot proves posts only through 2026-07-14 06:37 Beijing, not the full current day.",
        "gate": "next daily snapshot or bounded catch-up",
    },
]

headline = [{
    "governed_competitors": summary["governed_competitor_count"],
    "official_product_families": summary["official_catalog_profile"]["canonical_product_family_count"],
    "internal_spu_named_matches": summary["internal_spu_master_profile"]["named_matches"],
    "delta_search_terms": summary["search_profile"]["delta_term_count"],
    "zero_evidence_delta_terms": delta_coverage["aggregate"]["coverage_classes"]["zero_existing_lexical_evidence"],
    "task37_unresolved": task37["unresolved_comment_candidates"],
    "comment_gap_after_offline_union": comment_debt["aggregate"]["reported_gap_after_offline_union"],
    "comment_first_page_request_floor": comment_debt["provider_budget_floor"]["minimum_first_comment_page_request_floor"],
    "task37_remaining_provider_budget": comment_debt["provider_budget_floor"]["task37_remaining_requests"],
    "structurally_recoverable_orphans": comment_debt["production_orphan_recovery"]["aggregate"]["structurally_recoverable_comments"],
    "remaining_unlinked_orphans": comment_debt["production_orphan_recovery"]["aggregate"]["still_unlinked_comments"],
    "deduplicated_union_posts": overlap["potential_deduplicated_union"]["posts"],
    "deduplicated_union_comments": overlap["potential_deduplicated_union"]["linked_comments"],
    "archive_files": collection["imported_archive"]["files"],
    "archive_comments": collection["imported_archive"]["comments"],
}]

dictionary_gates = [
    {"gate": "Rows", "observed": summary["dictionary_quality"]["final_rows"], "status": "pass", "interpretation": "Governed final dictionary rows."},
    {"gate": "Unique tag IDs", "observed": summary["dictionary_quality"]["unique_final_tag_ids"], "status": "pass", "interpretation": "No tag_id collision."},
    {"gate": "Blank cells", "observed": summary["dictionary_quality"]["blank_cells"], "status": "pass", "interpretation": "All governed fields populated."},
    {"gate": "Candidate/final semantic equality", "observed": "yes", "status": "pass", "interpretation": "Byte delta is UTF-8 BOM only."},
    {"gate": "SPU IDs", "observed": summary["spu_profile"]["distinct_spu_ids"], "status": "pass", "interpretation": "All 254 IDs join to Phase 3 v3.5 Chinese and English names."},
    {"gate": "SPU-level categories", "observed": summary["spu_profile"]["distinct_voc_categories"], "status": "bounded", "interpretation": "Only M5, M9, and BS03 are explicit named model/category labels."},
    {"gate": "Official product families", "observed": summary["official_catalog_profile"]["canonical_product_family_count"], "status": "bounded", "interpretation": "Official catalog proves current products; six families have verified single internal SPU bindings."},
]

source_docs = [
    {
        "id": "tag_dictionary",
        "label": "Governed v6.3 tag dictionary",
        "path": "dim_tag_v6.3_final.csv",
        "query": {
            "engine": "python3/csv-readonly",
            "description": "Profiles row integrity, governed brands, SPU IDs, category labels, keyword collisions and candidate/final equivalence.",
            "tables_used": ["dim_tag_v6.3_final.csv", "dim_tag_v6.3_candidate.csv"],
            "filters": ["L0-BRD-* for governed brand rows", "L2-SPU专属 for SPU rows"],
            "metric_definitions": {
                "Governed competitor": "An L0-BRD-* brand row other than Momcozy.",
                "SPU category": "voc_category on an L2-SPU专属 row; not an authoritative product name.",
            },
            "executed_at": generated_at,
        },
    },
    {
        "id": "internal_spu_master",
        "label": "Phase 3 v3.5 internal product-master join",
        "path": "docs/analysis/momcozy-historical-collection-audit-20260714/internal-spu-master-join.json",
        "query": {
            "engine": "artifact-tool/xlsx-readonly-plus-exact-id-join",
            "description": "Reads the project-documented Phase 3 v3.5 product-master workbook and joins exact SPU编码 to all governed dictionary SPU IDs.",
            "tables_used": ["产品主数据_VOC维度关联_v3.5.xlsx!Sheet1!A1:AD432", "dim_tag_v6.3_final.csv"],
            "filters": ["Exact SPU ID equality", "Product owner fields excluded", "772 heuristic spoken variants not activated"],
            "metric_definitions": {
                "Named SPU match": "A dictionary SPU ID with exactly one v3.5 product-master row and nonblank Chinese and English names.",
                "Current sale boundary": "Not derivable because active_status and effective_date are absent; use the official storefront snapshot instead.",
            },
            "executed_at": internal_spu_master["generated_at_utc"],
        },
    },
    {
        "id": "analysis_validation",
        "label": "Reproducible collection audit",
        "path": "docs/analysis/momcozy-historical-collection-audit-20260714/validation-receipt.json",
        "query": {
            "engine": "python3/notebook-readonly",
            "description": "Executes the analysis top-to-bottom and checks dictionary, archive, snapshot, Task 37, and V2 profile bindings.",
            "tables_used": ["analysis-summary.json", "completion-matrix.csv", "recommended-search-profile.json"],
            "filters": ["No raw post/comment text or user identifiers in report datasets"],
            "metric_definitions": {"Delta term": "A V2 candidate query not semantically exact-matched by the immutable legacy 15-term profile."},
            "executed_at": generated_at,
        },
    },
    {
        "id": "official_product_catalog",
        "label": "Momcozy official storefront product catalog",
        "path": "docs/analysis/momcozy-historical-collection-audit-20260714/official-product-catalog-snapshot.json",
        "url": "https://momcozy.com/agents.md",
        "query": {
            "engine": "https/json-readonly",
            "description": "Reads the official Shopify catalog endpoints documented by Momcozy and selects 18 current primary product families by exact handle.",
            "tables_used": [
                "https://momcozy.com/collections/all/products.json?limit=250&page=1",
                "https://momcozy.com/collections/all/products.json?limit=250&page=2",
            ],
            "filters": ["Exact reviewed primary product handles", "Bundles and accessories are not treated as separate product families"],
            "metric_definitions": {
                "Official product family": "A reviewed primary storefront product used to consolidate aliases; it is not an internal SPU ID.",
            },
            "executed_at": summary["official_catalog_profile"]["captured_at_utc"],
        },
    },
    {
        "id": "task37",
        "label": "Task 37 remote staging execution",
        "path": ".superpowers/sdd/task-37-remote-execution-report.md",
        "query": {
            "engine": "report/aggregate-readonly",
            "description": "Reads exact postflight counts, candidate states, provider ledger delta, and production boundary.",
            "tables_used": ["backfill_candidates", "backfill_provider_attempts", "reddit_threads", "reddit_comments", "analysis_results"],
            "filters": ["Task 37 exact packet only", "No raw content included"],
            "metric_definitions": {"Task 37 Provider call": "True only if the provider ledger increased beyond 1199 during Task 37."},
            "executed_at": generated_at,
        },
    },
    {
        "id": "cross_source_overlap",
        "label": "Cross-source Reddit identity reconciliation",
        "path": "docs/analysis/momcozy-historical-collection-audit-20260714/cross-source-overlap-audit.json",
        "query": {
            "engine": "python3/sqlite-json-identity-readonly",
            "description": "Intersects exact Reddit post and comment primary IDs across the local canonical union, imported archive, production snapshot, and hash-pinned Task 37 staging snapshot.",
            "tables_used": ["post_id", "comment_id", "comment parent post_id", "created_at_utc"],
            "filters": ["Post window starts 2025-01-01T00:00:00Z", "Comments must link to an in-window post", "18 production orphan comments assessed separately"],
            "metric_definitions": {
                "Exact overlap": "Identical Reddit primary IDs present in both Task 37 and the requested-window local canonical union.",
                "Deduplicated identity union": "Local IDs union Task 37 IDs after exact primary-ID deduplication; it is not a materialized corpus.",
            },
            "executed_at": overlap_audit["generated_at_utc"],
        },
    },
    {
        "id": "merge_plan",
        "label": "Read-only cross-source merge plan",
        "path": "docs/analysis/momcozy-historical-collection-audit-20260714/cross-source-readonly-merge-plan.json",
        "query": {
            "engine": "python3/set-difference-readonly",
            "description": "Freezes insert, preserve, and orphan-recovery counts from exact identity set differences without creating a staging database or writing production.",
            "tables_used": ["Task 37-only post IDs", "Task 37-only comment IDs", "local-only IDs", "production orphan comment IDs"],
            "filters": ["Identity fields only", "executable=false", "local_isolated_staging_created=false"],
            "metric_definitions": {
                "Merge action": "A bounded identity-count instruction that still requires a separately tested loader and isolated staging execution.",
            },
            "executed_at": merge_plan["generated_at_utc"],
        },
    },
    {
        "id": "fusion_audit",
        "label": "Imported archive and three-source fusion audit",
        "path": "data/imports/ai_nlp_voc_reddit_20260714/fusion-audit.json",
        "query": {
            "engine": "python3/sqlite-readonly",
            "description": "Reconciles local history, imported archive, and production primary IDs without adding overlapping counts.",
            "tables_used": ["reddit_threads", "reddit_comments", "analysis_results", "136 imported JSON files"],
            "filters": ["Primary production database only", "18 orphan comments quarantined"],
            "metric_definitions": {"Archive net new": "Imported archive IDs minus local historical and production IDs."},
            "executed_at": generated_at,
        },
    },
    {
        "id": "production_snapshot",
        "label": "Production read-only and sanitized union snapshot",
        "path": "data/processed/reddit_voc_site_snapshot_20260714/manifest.json",
        "query": {
            "engine": "python3/json-readonly",
            "description": "Provides source counts, requested-window bounds and production unchanged proof.",
            "tables_used": ["posts.json", "comments.json", "manifest.json"],
            "filters": ["Sanitized fields only", "No raw usernames or HTML"],
            "metric_definitions": {"Requested window": "Post created_at_utc on or after 2025-01-01T00:00:00Z in the local canonical union."},
            "executed_at": generated_at,
        },
    },
    {
        "id": "production_refresh",
        "label": "Fresh production identity-only refresh",
        "path": "docs/analysis/momcozy-historical-collection-audit-20260714/production-identity-refresh.json",
        "query": {
            "engine": "ssh/docker/sqlite-query-only",
            "description": "Refreshes production post/comment identities and UTC timestamps in a read-only SQLite transaction without content or usernames.",
            "tables_used": ["reddit_threads", "reddit_comments", "analysis_results", "runs", "raw_captures"],
            "filters": ["Identity fields only", "PRAGMA query_only=ON", "remote_write=false"],
            "metric_definitions": {
                "Daily increment": "New Reddit primary IDs compared with the earlier 2026-07-14 production identity snapshot.",
            },
            "executed_at": production_refresh["captured_at_utc"],
        },
    },
    {
        "id": "v2_profile",
        "label": "V2 search profile candidate",
        "path": "config/backfill/momcozy-search-profile-v2-candidate-20260714.json",
        "query": {
            "engine": "python3/json-readonly",
            "description": "Binds 75 candidate terms and 69 legacy-uncovered delta terms to the governed dictionary and official storefront catalog.",
            "tables_used": ["candidate_groups", "competitor_term_bindings", "official_product_term_bindings", "delta_terms"],
            "filters": ["Status reviewed_candidate_not_activated", "Legacy run remains immutable"],
            "metric_definitions": {"Candidate term": "A reviewed query string proposed for a separate V2 run; it is not an executed lane."},
            "executed_at": generated_at,
        },
    },
    {
        "id": "delta_offline_coverage",
        "label": "V2 delta offline lexical coverage audit",
        "path": "docs/analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage-audit.json",
        "query": {
            "engine": "python3/ssh-sqlite-query-only-plus-local-json",
            "description": "Matches all 69 V2 delta phrases against the requested-window local corpus and the unchanged Task 37 staging database, then deduplicates matched Reddit IDs without exporting remote content.",
            "tables_used": [
                "data/processed/reddit_voc_site_snapshot_20260714/posts.json",
                "data/processed/reddit_voc_site_snapshot_20260714/comments.json",
                "Task 37 staging reddit_threads",
                "Task 37 staging reddit_comments",
                "delta-term-offline-coverage-validation.json",
            ],
            "filters": [
                "Post created_at_utc >= 2025-01-01T00:00:00Z",
                "Unicode NFKC casefold token-phrase matching",
                "Remote database mode=ro immutable query_only",
                "Only Reddit IDs and counts returned from remote",
            ],
            "metric_definitions": {
                "Zero lexical evidence": "No normalized phrase match in any post title/body or linked comment body across the potential local plus Task 37 identity union.",
                "Provider lane completed": "Always zero in this audit; existing lexical evidence cannot prove exhaustive search discovery.",
            },
            "executed_at": delta_coverage["generated_at_utc"],
        },
    },
    {
        "id": "comment_coverage_debt",
        "label": "Task 37 comment coverage debt audit",
        "path": "docs/analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt-audit.json",
        "query": {
            "engine": "python3/ssh-sqlite-query-only-plus-local-identity-union",
            "description": "Reconciles all 96 terminal partial Task 37 candidates with exact local comment IDs, profiles remaining reported-count gaps and More nodes, and validates production orphan-parent recovery without exporting remote bodies or usernames.",
            "tables_used": [
                "Task 37 staging backfill_candidates",
                "Task 37 staging backfill_checkpoints",
                "Task 37 staging reddit_threads",
                "Task 37 staging reddit_comments",
                "data/processed/reddit_voc_site_snapshot_20260714/comments.json",
                "production-identity-snapshot.json",
                "comment-coverage-debt-validation.json",
            ],
            "filters": [
                "candidate status_reason in unresolved_more or post_only_coverage",
                "Remote database mode=ro immutable query_only",
                "Only Reddit IDs, structural states, timestamps, and counts returned from remote",
                "No runtime state transition or Provider request",
            ],
            "metric_definitions": {
                "Remaining reported gap": "max(num_comments_reported minus exact Task 37/local union comment IDs, zero); a priority measure, not a guaranteed retrievable count.",
                "Minimum first-page request floor": "One FETCH_POST_COMMENTS first-page request per still-open candidate under the current endpoint contract; not a closure estimate.",
                "Structurally recoverable orphan": "A production orphan comment whose missing parent post exists in Task 37; the comment may be an exact Task 37 duplicate or a production-only row.",
            },
            "executed_at": comment_debt["generated_at_utc"],
        },
    },
]


raw_datasets = {
    "headline": headline,
    "dictionary_gates": dictionary_gates,
    "search_coverage": search_coverage,
    "search_groups": search_groups,
    "delta_coverage_classes": delta_coverage_class_rows,
    "delta_group_coverage": delta_group_rows,
    "delta_probe_priority": delta_probe_rows,
    "comment_gap_buckets": comment_gap_bucket_rows,
    "comment_debt_priority": comment_debt_priority_rows,
    "orphan_recovery": orphan_recovery_rows,
    "task37_status": task37_status,
    "overlap_reconciliation": overlap_rows,
    "merge_actions": merge_action_rows,
    "competitor_coverage": competitor_rows,
    "spu_categories": spu_rows,
    "internal_spu_names": internal_spu_rows,
    "official_products": official_product_rows,
    "evidence_layers": evidence_layers,
    "completion_matrix": completion_rows,
    "recommendations": recommendations,
}

dataset_provenance = {
    "headline": ("docs/analysis/momcozy-historical-collection-audit-20260714/validation-receipt.json", "Headline audit metrics"),
    "dictionary_gates": ("dim_tag_v6.3_final.csv", "Dictionary quality gates"),
    "search_coverage": ("config/backfill/momcozy-search-profile-v2-candidate-20260714.json", "Search-term coverage chart data"),
    "search_groups": ("config/backfill/momcozy-search-profile-v2-candidate-20260714.json", "Search profile group totals"),
    "delta_coverage_classes": ("docs/analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage-audit.json", "V2 delta lexical evidence classes"),
    "delta_group_coverage": ("docs/analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage-audit.json", "V2 delta lexical coverage by group"),
    "delta_probe_priority": ("docs/analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage.csv", "Frozen V2 delta probe priority"),
    "comment_gap_buckets": ("docs/analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt-audit.json", "Remaining comment-gap distribution"),
    "comment_debt_priority": ("docs/analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt.csv", "Task 37 comment-repair priority"),
    "orphan_recovery": ("docs/analysis/momcozy-historical-collection-audit-20260714/production-orphan-recovery-matrix.csv", "Production orphan-parent recovery matrix"),
    "task37_status": (".superpowers/sdd/task-37-remote-execution-report.md", "Task 37 candidate states"),
    "overlap_reconciliation": ("docs/analysis/momcozy-historical-collection-audit-20260714/cross-source-overlap-audit.json", "Exact cross-source identity overlap"),
    "merge_actions": ("docs/analysis/momcozy-historical-collection-audit-20260714/cross-source-readonly-merge-plan.json", "Read-only identity merge actions"),
    "competitor_coverage": ("docs/analysis/momcozy-historical-collection-audit-20260714/brand-collection-coverage.csv", "Governed competitor observation coverage"),
    "spu_categories": ("docs/analysis/momcozy-historical-collection-audit-20260714/spu-category-profile.csv", "SPU-level category profile"),
    "internal_spu_names": ("docs/analysis/momcozy-historical-collection-audit-20260714/internal-spu-master-join.json", "Exact internal SPU name join"),
    "official_products": ("docs/analysis/momcozy-historical-collection-audit-20260714/internal-spu-master-join.json", "Official product-family and internal-SPU reconciliation"),
    "evidence_layers": ("docs/analysis/momcozy-historical-collection-audit-20260714/analysis-summary.json", "Collection evidence layers"),
    "completion_matrix": ("docs/analysis/momcozy-historical-collection-audit-20260714/completion-matrix.csv", "Historical completion matrix"),
    "recommendations": ("docs/workflows/momcozy-reddit-history-coverage-v2.md", "Recommended execution order"),
}


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def materialize_with_sql(dataset_id: str, rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], str]:
    columns = list(rows[0])
    column_sql = ", ".join(f'"{column}"' for column in columns)
    values_sql = ",\n    ".join(
        "(" + ", ".join([str(index), *(sql_literal(row[column]) for column in columns)]) + ")"
        for index, row in enumerate(rows)
    )
    sql = (
        f'WITH source("_row_order", {column_sql}) AS (VALUES\n    {values_sql}\n)\n'
        f'SELECT {column_sql} FROM source ORDER BY "_row_order";'
    )
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        materialized = [dict(row) for row in connection.execute(sql)]
    if len(materialized) != len(rows):
        raise RuntimeError(f"dataset materialization mismatch: {dataset_id}")
    return materialized, sql


datasets: dict[str, list[dict[str, object]]] = {}
dataset_sources = []
for dataset_id, rows in raw_datasets.items():
    materialized, sql = materialize_with_sql(dataset_id, rows)
    datasets[dataset_id] = materialized
    source_path, source_label = dataset_provenance[dataset_id]
    dataset_sources.append(
        {
            "id": f"dataset_{dataset_id}",
            "label": source_label,
            "path": source_path,
            "query": {
                "engine": "sqlite3/bounded-values",
                "sql": sql,
                "description": f"Exact SQL used to re-materialize the validated bounded {dataset_id} snapshot rows.",
                "tables_used": [source_path],
                "filters": ["No raw post/comment text, usernames, credentials, or direct identifiers"],
                "metric_definitions": ["Values are bounded audit aggregates; overlapping collection layers are not additive."],
                "executed_at": generated_at,
            },
        }
    )

sources = [*source_docs, *dataset_sources]

manifest = {
    "version": 1,
    "surface": "report",
    "title": "Momcozy Historical Collection Audit",
    "description": "Governed tag dictionary, exact 254-SPU product-name join, official current products, 69-term offline lexical coverage, 96-candidate comment debt, cross-source identity overlap, and Reddit historical collection completion audit as of 2026-07-14.",
    "generatedAt": generated_at,
    "blocks": [
        {"id": "title", "type": "markdown", "layout": "full", "body": "# Momcozy Historical Collection Audit"},
        {"id": "executive_summary", "type": "markdown", "layout": "full", "body": "## Executive Summary\n\n**SPU 名称 join 已补齐，查询集合保持克制。** Phase 3 v3.5 内部产品主数据把字典中的 254/254 个 SPU ID 全部连接到中文和英文名称；BS03=SPU000714，BM03=SPU000176。772 个内部口语变体因包含大量 SKU/配件与启发式品牌组合而没有自动启用，V2 仍为 75 个候选词 / 69 个未执行 delta。\n\n**69 个 delta 已完成离线证据分层，但没有完成任何 Provider lane。** 19 个词在 410 帖 / 4,730 评论潜在 union 中零命中，4 个仅评论命中，9 个仅帖子命中，37 个两侧均命中；首个零证据官网词是 Momcozy BM03。\n\n**96 个评论债务已精确量化，现有一次余额远远不够。** 本地 union 只给 7 个候选补入 21 条 Task 37 未有的评论，96 个候选仍全部保留缺口：剩余 reported-count gap 为 2,082，另有 148 个 More nodes。当前 endpoint 的首页面请求下限是 96 次，而旧 run 只余 1 次；这个下限仍不是完整闭环预算。\n\n**历史采集仍未闭环。** 潜在去重 union 为 410 帖 / 4,730 条 linked comments，但尚未物化。一个 Task 37 父帖可使 8 条 production orphan comments 结构性恢复，其中 2 条是 production-only；仍有 10 条缺少父帖证据。另有 69 个未执行 V2 Provider lane，且本轮没有 TikHub 请求。"},
        {"id": "headline_metrics", "type": "metric-strip", "layout": "full", "cardIds": ["competitor_count", "internal_spu_named_matches", "official_product_families", "delta_terms", "zero_evidence_terms", "unresolved_comments", "comment_gap_after_offline_union", "comment_first_page_request_floor", "orphan_recovery", "deduplicated_union_posts", "deduplicated_union_comments", "archive_scale"]},
        {"id": "dictionary_section", "type": "markdown", "layout": "full", "sourceId": "tag_dictionary", "body": "## Dictionary Findings\n\n`final` 与 `candidate` 解析后逐字段一致，字节差异仅是 UTF-8 BOM。字典自身的 1,225 个 SPU 级标签只有 `spu_id` 与 `voc_category`，但 Phase 3 v3.5 产品主数据已经按 ID 精确补齐全部 254 个 SPU 的中文/英文名称；不能再把宽泛品类名冒充单品名。"},
        {"id": "dictionary_table", "type": "table", "layout": "full", "tableId": "dictionary_gates"},
        {"id": "search_section", "type": "markdown", "layout": "full", "sourceId": "v2_profile", "body": "## Search Configuration Gap\n\n旧 run 必须保持 hash-frozen。V2 采用新 run ID 和独立 profile/checkpoint：1 个品牌别名、20 个未覆盖 Momcozy 型号、6 个官网产品别名、17 个治理竞品和 25 个未覆盖品类锚点，共 69 个 delta。完整 SPU 名称 join 没有自动扩张查询：772 个启发式口语变体仅保留为待审证据。"},
        {"id": "search_chart", "type": "chart", "layout": "full", "chartId": "search_coverage"},
        {"id": "search_table", "type": "table", "layout": "full", "tableId": "search_groups"},
        {"id": "delta_offline_section", "type": "markdown", "layout": "full", "sourceId": "delta_offline_coverage", "body": "## Existing Evidence Prioritizes the 69 Unexecuted Lanes\n\n对 410 帖 / 4,730 条评论潜在 union 的只读正文匹配显示：19 个 delta 完全零命中，4 个只在评论出现，9 个只在帖子出现，37 个在帖子和评论两侧都出现。69 个词合计关联到 299 个父帖子，但这只是现有语料中的 lexical evidence，不能证明对应搜索已经穷尽；完成的 Provider lane 仍为 0。P0 首批应从 Momcozy BM03、DeepClean、S12 Pro Quick 等零证据官网/型号词开始。"},
        {"id": "delta_coverage_chart_block", "type": "chart", "layout": "full", "chartId": "delta_coverage_classes"},
        {"id": "delta_group_table_block", "type": "table", "layout": "full", "tableId": "delta_group_coverage"},
        {"id": "delta_probe_table_block", "type": "table", "layout": "full", "tableId": "delta_probe_priority"},
        {"id": "brand_spu_section", "type": "markdown", "layout": "full", "sourceId": "tag_dictionary", "body": "## Brand and SPU Coverage\n\n本地窗口内出现过某品牌只代表样本提及，不等于该品牌有独立历史检索。17 个竞品均无 dedicated historical search lane；其中只有 Elvie、Lansinoh、Medela、Spectra、Willow 有专门 imported archive bucket。"},
        {"id": "competitor_table", "type": "table", "layout": "full", "tableId": "competitor_coverage"},
        {"id": "spu_table", "type": "table", "layout": "full", "tableId": "spu_categories"},
        {"id": "internal_spu_section", "type": "markdown", "layout": "full", "sourceId": "internal_spu_master", "body": "## Exact Internal SPU Name Join\n\nPhase 3 v3.5 产品主数据包含 431 个唯一 SPU；字典使用的 254 个 ID 全部精确命中且中文/英文名称非空。162 个 SPU 另有 772 个启发式口语变体，但没有任何变体被自动激活为 Reddit lane。该快照缺少 active_status/effective_date，不能证明当前在售。"},
        {"id": "internal_spu_table", "type": "table", "layout": "full", "tableId": "internal_spu_names"},
        {"id": "official_product_section", "type": "markdown", "layout": "full", "sourceId": "official_product_catalog", "body": "## Official Product-Name Reconciliation\n\n官网 406 个当前商品按主商品 handle 归并出 18 个相关产品族。与内部主数据交叉后，M6、M9、V2 Pro、Air 1、KleanPal Pro/BS03 和 BM03 六个当前产品族有单一内部 SPU 绑定；其他产品存在版本歧义或晚于 2026-05 内部快照。官网商品 ID 仍不是内部 SPU ID。"},
        {"id": "official_product_table", "type": "table", "layout": "full", "tableId": "official_products"},
        {"id": "collection_section", "type": "markdown", "layout": "full", "sourceId": "comment_coverage_debt", "body": "## Comment Debt Is a Separate Collection Lane\n\nTask 37 修正了执行准入，但当前 hydrator 把 `unresolved_more` 与 `post_only_coverage` 当成终态，因此没有消费剩余的一次 Provider 额度。评论债务必须先做离线 ID reconciliation，再通过独立、受测的 reopen/More-child 合同执行；V2 discovery 仍使用另一套预算和 one-shot guard。"},
        {"id": "task37_chart", "type": "chart", "layout": "full", "chartId": "task37_candidate_status"},
        {"id": "comment_debt_section", "type": "markdown", "layout": "full", "sourceId": "comment_coverage_debt", "body": "## One Remaining Request Cannot Close the Comment Debt\n\n96 个终态 partial 候选当前只有 752 条精确评论 ID；本地 canonical union 对其中 7 个帖子增加 21 条不重复评论，但没有任何候选达到 captured reported count。离线 union 后仍有 2,082 的 reported-count gap 和 148 个 More nodes。按当前每个候选页面一次 `FETCH_POST_COMMENTS` 的合同，仅首页面就至少需要 96 次请求；剩余 1 次额度不足 95 次，而且重复首页面不保证解析 More children。reported count 可能包含删除、移除或晚到评论，因此 gap 只用于优先级，不是保证可取回行数。"},
        {"id": "comment_gap_chart_block", "type": "chart", "layout": "full", "chartId": "comment_gap_buckets"},
        {"id": "comment_debt_priority_table_block", "type": "table", "layout": "full", "tableId": "comment_debt_priority"},
        {"id": "overlap_section", "type": "markdown", "layout": "full", "sourceId": "cross_source_overlap", "body": "## Exact Cross-Source Identity Reconciliation\n\nTask 37 与本地 requested-window canonical union 已按 Reddit post/comment 主键精确核对。78 帖 / 2,023 条 linked comments 重叠，223 / 1,202 仅存在于 Task 37，109 / 1,505 仅存在于本地。潜在去重 union 为 410 帖 / 4,730 条 linked comments；该数字是 identity plan，不是已物化或已验收的新数据库。"},
        {"id": "overlap_table", "type": "table", "layout": "full", "tableId": "overlap_reconciliation"},
        {"id": "merge_plan_section", "type": "markdown", "layout": "full", "sourceId": "merge_plan", "body": "## Read-Only Merge Plan\n\n精确 set difference 已冻结为非可执行计划：未来 isolated staging 应插入 223 个 Task 37-only posts 和 1,202 条 Task 37-only comments，其中 34 条连接到现有本地 posts；同时保留全部 local-only IDs。18 条 production orphan comments 中，6 条与 Task 37 comment ID 精确重叠，另 2 条虽为 production-only 但父帖已在 Task 37，因此结构性可恢复 8 条；仍有 10 条跨 3 个父帖缺少证据。"},
        {"id": "merge_actions_table", "type": "table", "layout": "full", "tableId": "merge_actions"},
        {"id": "orphan_recovery_table_block", "type": "table", "layout": "full", "tableId": "orphan_recovery"},
        {"id": "evidence_table", "type": "table", "layout": "full", "tableId": "evidence_layers"},
        {"id": "completion_section", "type": "markdown", "layout": "full", "sourceId": "analysis_validation", "body": "## Completion Matrix\n\n完成声明必须同时闭合字典主数据、V2 search lanes、旧评论债务、跨源去重与 daily cutover；任何单一 staging 或 snapshot 都不足以证明 2025-01-01 至今完整。"},
        {"id": "completion_table", "type": "table", "layout": "full", "tableId": "completion_matrix"},
        {"id": "recommendations_section", "type": "markdown", "layout": "full", "sourceId": "analysis_validation", "body": "## Recommendations\n\nSPU 名称 join、离线 lane 排序和 identity dedupe 已完成。解除本地 no-test 边界后，先在 isolated staging 物化 merge plan，并把 21 条 local-only candidate comments 与 8 条结构性可恢复 orphan comments 纳入 RED/GREEN；随后分别实现 comment reopen/More-child 合同与 V2 new-run loader。只有 query-only admission 冻结实际请求面后，才为评论补采和 V2 discovery 分别生成新的精确 Provider packet。"},
        {"id": "recommendations_table", "type": "table", "layout": "full", "tableId": "recommendations"},
        {"id": "questions_section", "type": "markdown", "layout": "full", "body": "## Further Questions\n\n1. 内部产品主数据的 active_status/effective_date 权威来源在哪里？\n2. S9 Pro、S12 Pro Quick 与 V1 Pro 的多个内部版本 SPU 应如何绑定当前官网产品？\n3. 772 个内部口语变体中，哪些经过主产品、品牌和 Reddit 信号治理后值得进入下一版 profile？\n4. 解除本地测试门禁并完成 loader 后，新的 exact Provider packet 是否应从 P0 rank 1 的 Momcozy BM03 单页开始？\n5. daily cutover 应等待下一次 07:00 快照，还是另做当前日 catch-up？"},
        {"id": "caveats_section", "type": "markdown", "layout": "full", "body": "## Caveats and Assumptions\n\n- 本报告不包含原帖、评论正文、Reddit 用户名、产品负责人或 secrets；远端正文只在 query-only 进程内匹配，输出仅保留 Reddit IDs 与计数。\n- 410 帖 / 4,730 条 linked comments 是潜在 identity union，不是已物化 corpus、已执行 merge 或历史完整性证明。\n- 离线 lexical evidence 只用于排序；即使已有命中，也不能证明搜索 lane 完整。69 个 Provider lane 全部仍未执行。\n- `voc_category` 仍只是标签上下文；精确 `spu_name` 来自 Phase 3 v3.5 ID join。官网商品 ID 不是内部 `spu_id`。\n- 内部主数据缺少 active_status/effective_date，且早于 7 月官网快照；不能单独证明当前在售。\n- 772 个口语变体是启发式证据，不是已批准查询。\n- production 最新只读刷新仍停在北京时间 2026-07-14 06:37，不代表 7 月 14 日全天。\n- V2 profile 为 `reviewed_candidate_not_activated`；`provider_call=false`、`production unchanged`、`live_send=false`。"},
        {"id": "sources_section", "type": "markdown", "layout": "full", "body": "## Sources\n\n结论来自 governed CSV、Phase 3 v3.5 内部产品主数据及其项目审计、Momcozy 官方只读商品目录、可复现 notebook validation、69-term offline lexical audit、96-candidate comment-debt audit 与各自独立校验、Task 37 postflight 与身份快照、exact cross-source overlap audit、read-only merge plan、import/fusion audit、最新 production identity refresh 与 V2 candidate profile。"},
    ],
    "cards": [
        {"id": "competitor_count", "dataset": "headline", "metrics": [{"label": "Governed competitors", "field": "governed_competitors", "format": "number"}], "description": "L0-BRD-* rows excluding Momcozy.", "sourceId": "dataset_headline"},
        {"id": "internal_spu_named_matches", "dataset": "headline", "metrics": [{"label": "Named internal SPUs", "field": "internal_spu_named_matches", "format": "number"}], "description": "Exact Phase 3 v3.5 ID join with Chinese and English names.", "sourceId": "dataset_headline"},
        {"id": "official_product_families", "dataset": "headline", "metrics": [{"label": "Official product families", "field": "official_product_families", "format": "number"}], "description": "Current primary storefront products consolidated by reviewed handle; not internal SPUs.", "sourceId": "dataset_headline"},
        {"id": "delta_terms", "dataset": "headline", "metrics": [{"label": "Unexecuted V2 delta terms", "field": "delta_search_terms", "format": "number"}], "description": "Candidate queries not exact-covered by the immutable legacy profile.", "sourceId": "dataset_headline"},
        {"id": "zero_evidence_terms", "dataset": "headline", "metrics": [{"label": "Delta terms with zero evidence", "field": "zero_evidence_delta_terms", "format": "number"}], "description": "No normalized lexical hit in the 410-post / 4,730-comment potential union; highest discovery priority.", "sourceId": "dataset_headline"},
        {"id": "unresolved_comments", "dataset": "headline", "metrics": [{"label": "Task 37 unresolved candidates", "field": "task37_unresolved", "format": "number"}], "description": "95 unresolved_more plus one post_only candidate.", "sourceId": "dataset_headline"},
        {"id": "comment_gap_after_offline_union", "dataset": "headline", "metrics": [{"label": "Remaining reported comment gap", "field": "comment_gap_after_offline_union", "format": "number"}], "description": "After exact Task 37/local comment-ID union; a prioritization measure, not guaranteed retrievable rows.", "sourceId": "dataset_headline"},
        {"id": "comment_first_page_request_floor", "dataset": "headline", "metrics": [{"label": "First-page request floor", "field": "comment_first_page_request_floor", "format": "number"}, {"label": "Task 37 requests remaining", "field": "task37_remaining_provider_budget", "format": "number"}], "description": "Current endpoint requires at least one first-page request per open candidate; this is not a closure estimate.", "sourceId": "dataset_headline"},
        {"id": "orphan_recovery", "dataset": "headline", "metrics": [{"label": "Structurally recoverable orphans", "field": "structurally_recoverable_orphans", "format": "number"}, {"label": "Still unlinked", "field": "remaining_unlinked_orphans", "format": "number"}], "description": "Recovery is possible only where the missing production parent post exists in Task 37.", "sourceId": "dataset_headline"},
        {"id": "deduplicated_union_posts", "dataset": "headline", "metrics": [{"label": "Potential deduplicated posts", "field": "deduplicated_union_posts", "format": "number"}], "description": "Exact primary-ID union; not yet materialized.", "sourceId": "dataset_headline"},
        {"id": "deduplicated_union_comments", "dataset": "headline", "metrics": [{"label": "Potential linked comments", "field": "deduplicated_union_comments", "format": "number"}], "description": "Exact linked-comment ID union; not a completeness claim.", "sourceId": "dataset_headline"},
        {"id": "archive_scale", "dataset": "headline", "metrics": [{"label": "Imported archive files", "field": "archive_files", "format": "number"}, {"label": "Imported comments", "field": "archive_comments", "format": "number"}], "description": "Complete only for the supplied immutable archive.", "sourceId": "dataset_headline"},
    ],
    "charts": [
        {"id": "search_coverage", "title": "Search terms by configuration group", "description": "Most governed competitors, models, and category anchors have not run as historical lanes.", "type": "bar", "dataset": "search_coverage", "encodings": {"x": {"field": "group", "type": "nominal", "label": "Group"}, "y": {"field": "terms", "type": "quantitative", "label": "Terms"}, "color": {"field": "coverage_status", "type": "nominal", "label": "Coverage status"}}, "sourceId": "dataset_search_coverage"},
        {"id": "task37_candidate_status", "title": "Task 37 candidate status", "description": "Ninety-six candidates still lack closed comment coverage.", "type": "bar", "dataset": "task37_status", "encodings": {"x": {"field": "status", "type": "nominal", "label": "Candidate status"}, "y": {"field": "candidates", "type": "quantitative", "label": "Candidates"}, "color": {"field": "terminal", "type": "nominal", "label": "Coverage closed"}}, "sourceId": "dataset_task37_status"},
        {"id": "delta_coverage_classes", "title": "Offline lexical evidence across V2 delta terms", "description": "All 69 terms remain unexecuted Provider lanes; 19 have no lexical hit in the potential union.", "type": "bar", "dataset": "delta_coverage_classes", "encodings": {"x": {"field": "coverage_class", "type": "nominal", "label": "Existing evidence class"}, "y": {"field": "terms", "type": "quantitative", "label": "Delta terms"}}, "sourceId": "dataset_delta_coverage_classes"},
        {"id": "comment_gap_buckets", "title": "Remaining reported comment gap by candidate band", "description": "All 96 partial candidates remain open after exact local/Task 37 comment-ID union; the total reported-count gap is 2,082.", "type": "bar", "dataset": "comment_gap_buckets", "encodings": {"x": {"field": "gap_bucket", "type": "nominal", "label": "Remaining gap per candidate"}, "y": {"field": "remaining_reported_gap", "type": "quantitative", "label": "Remaining reported gap"}}, "sourceId": "dataset_comment_gap_buckets"},
    ],
    "tables": [
        {"id": "dictionary_gates", "title": "Dictionary quality and SPU naming boundaries", "dataset": "dictionary_gates", "columns": [{"field": "gate", "label": "Gate"}, {"field": "observed", "label": "Observed"}, {"field": "status", "label": "Status"}, {"field": "interpretation", "label": "Interpretation"}], "defaultSort": {"field": "gate", "direction": "asc"}, "sourceId": "dataset_dictionary_gates"},
        {"id": "search_groups", "title": "Search profile coverage by group", "dataset": "search_groups", "columns": [{"field": "group", "label": "Group"}, {"field": "recommended_terms", "label": "Candidate terms", "format": "number"}, {"field": "covered_by_legacy", "label": "Legacy covered", "format": "number"}, {"field": "delta_terms", "label": "Delta", "format": "number"}], "defaultSort": {"field": "delta_terms", "direction": "desc"}, "sourceId": "dataset_search_groups"},
        {"id": "delta_group_coverage", "title": "Offline evidence by V2 delta group", "dataset": "delta_group_coverage", "columns": [{"field": "group", "label": "Group"}, {"field": "delta_terms", "label": "Delta terms", "format": "number"}, {"field": "zero_evidence_terms", "label": "Zero evidence", "format": "number"}, {"field": "comment_only_terms", "label": "Comment only", "format": "number"}, {"field": "post_surface_covered_terms", "label": "Post evidence", "format": "number"}, {"field": "comment_covered_terms", "label": "Comment evidence", "format": "number"}, {"field": "provider_lanes_completed", "label": "Provider lanes completed", "format": "number"}], "defaultSort": {"field": "zero_evidence_terms", "direction": "desc"}, "sourceId": "dataset_delta_group_coverage"},
        {"id": "delta_probe_priority", "title": "Frozen V2 delta discovery priority", "dataset": "delta_probe_priority", "columns": [{"field": "priority_rank", "label": "Rank", "format": "number"}, {"field": "priority_tier", "label": "Tier"}, {"field": "group", "label": "Group"}, {"field": "term", "label": "Query term"}, {"field": "coverage_class", "label": "Existing evidence"}, {"field": "post_surface_matches", "label": "Post matches", "format": "number"}, {"field": "comment_matches", "label": "Comment matches", "format": "number"}, {"field": "evidence_parent_posts", "label": "Evidence parent posts", "format": "number"}, {"field": "provider_lane_status", "label": "Provider status"}], "defaultSort": {"field": "priority_rank", "direction": "asc"}, "sourceId": "dataset_delta_probe_priority"},
        {"id": "competitor_coverage", "title": "Governed competitor observation and lane coverage", "dataset": "competitor_coverage", "columns": [{"field": "brand", "label": "Brand"}, {"field": "local_window_mentions", "label": "Local-window mentions", "format": "number"}, {"field": "archive_window_mentions", "label": "Archive mentions", "format": "number"}, {"field": "archive_bucket", "label": "Archive bucket"}, {"field": "dedicated_historical_search_lane", "label": "Historical lane"}, {"field": "coverage_state", "label": "Coverage state"}], "defaultSort": {"field": "local_window_mentions", "direction": "desc"}, "sourceId": "dataset_competitor_coverage"},
        {"id": "spu_categories", "title": "SPU-level dictionary categories", "dataset": "spu_categories", "columns": [{"field": "voc_category", "label": "voc_category"}, {"field": "product_lines", "label": "Product line"}, {"field": "distinct_spu_ids", "label": "SPU IDs", "format": "number"}, {"field": "tag_rows", "label": "Tag rows", "format": "number"}, {"field": "name_boundary", "label": "Naming boundary"}], "defaultSort": {"field": "distinct_spu_ids", "direction": "desc"}, "sourceId": "dataset_spu_categories"},
        {"id": "internal_spu_names", "title": "Exact internal SPU name join", "dataset": "internal_spu_names", "columns": [{"field": "spu_id", "label": "SPU ID"}, {"field": "spu_name", "label": "SPU name"}, {"field": "product_name_en", "label": "English product name"}, {"field": "product_model", "label": "Model"}, {"field": "product_type", "label": "Product type"}, {"field": "master_product_line", "label": "Master product line"}, {"field": "master_voc_line", "label": "Master VOC line"}, {"field": "dictionary_voc_categories", "label": "Dictionary VOC categories"}, {"field": "dictionary_tag_rows", "label": "Tag rows", "format": "number"}], "defaultSort": {"field": "spu_id", "direction": "asc"}, "sourceId": "dataset_internal_spu_names"},
        {"id": "official_products", "title": "Official product families and internal-SPU boundary", "dataset": "official_products", "columns": [{"field": "family_id", "label": "Family"}, {"field": "official_title", "label": "Official product title"}, {"field": "product_type", "label": "Product type"}, {"field": "search_aliases", "label": "Existing aliases"}, {"field": "internal_spu_join", "label": "Internal SPU join"}, {"field": "mapping_status", "label": "Mapping status"}, {"field": "new_search_terms", "label": "Added search term"}, {"field": "official_url", "label": "Official URL"}], "defaultSort": {"field": "family_id", "direction": "asc"}, "sourceId": "dataset_official_products"},
        {"id": "comment_debt_priority", "title": "Task 37 comment-repair priority", "dataset": "comment_debt_priority", "columns": [{"field": "priority_rank", "label": "Rank", "format": "number"}, {"field": "priority_tier", "label": "Tier"}, {"field": "post_id", "label": "Post ID"}, {"field": "status_reason", "label": "Status reason"}, {"field": "first_lane", "label": "First lane"}, {"field": "reported_comments", "label": "Reported", "format": "number"}, {"field": "task37_comments", "label": "Task 37", "format": "number"}, {"field": "local_only_increment", "label": "Local-only increment", "format": "number"}, {"field": "union_comments", "label": "Exact union", "format": "number"}, {"field": "remaining_reported_gap", "label": "Remaining gap", "format": "number"}, {"field": "more_nodes", "label": "More nodes", "format": "number"}, {"field": "reopen_status", "label": "Reopen status"}], "defaultSort": {"field": "priority_rank", "direction": "asc"}, "sourceId": "dataset_comment_debt_priority"},
        {"id": "overlap_reconciliation", "title": "Exact Task 37 and local identity reconciliation", "dataset": "overlap_reconciliation", "columns": [{"field": "component", "label": "Component"}, {"field": "posts", "label": "Posts", "format": "number"}, {"field": "linked_comments", "label": "Linked comments", "format": "number"}, {"field": "meaning", "label": "Meaning"}], "defaultSort": {"field": "posts", "direction": "desc"}, "sourceId": "dataset_overlap_reconciliation"},
        {"id": "merge_actions", "title": "Read-only identity merge actions", "dataset": "merge_actions", "columns": [{"field": "action", "label": "Action"}, {"field": "entities", "label": "Entities", "format": "number"}, {"field": "state", "label": "State"}], "defaultSort": {"field": "entities", "direction": "desc"}, "sourceId": "dataset_merge_actions"},
        {"id": "orphan_recovery", "title": "Production orphan-parent recovery matrix", "dataset": "orphan_recovery", "columns": [{"field": "missing_parent_post_id", "label": "Missing parent post ID"}, {"field": "orphan_comments", "label": "Orphan comments", "format": "number"}, {"field": "parent_in_task37", "label": "Parent in Task 37"}, {"field": "exact_comment_ids_in_task37", "label": "Exact Task 37 IDs", "format": "number"}, {"field": "production_only_with_task37_parent", "label": "Production-only with parent", "format": "number"}, {"field": "structurally_recoverable", "label": "Structurally recoverable", "format": "number"}, {"field": "still_unlinked", "label": "Still unlinked", "format": "number"}, {"field": "private_content_rows_available", "label": "Local content rows available", "format": "number"}], "defaultSort": {"field": "orphan_comments", "direction": "desc"}, "sourceId": "dataset_orphan_recovery"},
        {"id": "evidence_layers", "title": "Collection evidence layers", "dataset": "evidence_layers", "columns": [{"field": "layer", "label": "Layer"}, {"field": "posts", "label": "Posts", "format": "number"}, {"field": "comments", "label": "Comments", "format": "number"}, {"field": "status", "label": "Status"}, {"field": "evidence_grade", "label": "Evidence grade"}, {"field": "additive_rule", "label": "Additive boundary"}], "defaultSort": {"field": "posts", "direction": "desc"}, "sourceId": "dataset_evidence_layers"},
        {"id": "completion_matrix", "title": "Historical collection completion matrix", "dataset": "completion_matrix", "columns": [{"field": "workstream", "label": "Workstream"}, {"field": "status", "label": "Status"}, {"field": "evidence", "label": "Evidence"}, {"field": "next_gate", "label": "Next gate"}], "defaultSort": {"field": "workstream", "direction": "asc"}, "sourceId": "dataset_completion_matrix"},
        {"id": "recommendations", "title": "Recommended execution order", "dataset": "recommendations", "columns": [{"field": "priority", "label": "Priority", "format": "number"}, {"field": "action", "label": "Action"}, {"field": "why", "label": "Why"}, {"field": "gate", "label": "Gate"}], "defaultSort": {"field": "priority", "direction": "asc"}, "sourceId": "dataset_recommendations"},
    ],
    "sources": sources,
}

snapshot = {
    "version": 1,
    "status": "ready",
    "generatedAt": generated_at,
    "datasets": datasets,
}

artifact = {
    "surface": "report",
    "manifest": manifest,
    "snapshot": snapshot,
    "sources": sources,
    "package_info": {"report_id": "momcozy-historical-collection-audit-20260714"},
}

(OUT / "artifact.json").write_text(
    json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps({"artifact": "artifact.json", "datasets": {key: len(value) for key, value in snapshot["datasets"].items()}}, sort_keys=True))
