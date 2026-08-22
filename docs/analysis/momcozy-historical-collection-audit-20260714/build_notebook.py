from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import textwrap
import traceback


ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = Path(__file__).resolve().parent
NOTEBOOK_PATH = OUTPUT_DIR / "analysis.ipynb"


def markdown(source: str) -> dict[str, object]:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": textwrap.dedent(source).strip() + "\n",
    }


def code(source: str) -> dict[str, object]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": textwrap.dedent(source).strip() + "\n",
    }


cells = [
    markdown(
        """
        # Momcozy Historical Collection Audit

        Reproducible, read-only analysis of the governed v6.3 tag dictionary,
        the Phase 3 v3.5 internal product-master join, current Reddit search
        terms, historical backfill evidence, imported competitor archive, and
        the refreshed 2026-07-14 production identity snapshot. It also audits
        all 69 V2 delta terms against the 410-post / 4,730-comment potential
        deduplicated union without exporting remote content.

        Boundaries: no Provider request, no production write, no merge, no
        DingTalk/live send. The notebook produces a proposed v2 search profile;
        it does not activate that profile.
        """
    ),
    code(
        """
        from __future__ import annotations

        from collections import Counter, defaultdict
        import csv
        from datetime import datetime, timezone
        from hashlib import sha256
        import json
        from pathlib import Path
        import re
        import sys

        ROOT = Path.cwd().resolve()
        assert (ROOT / "dim_tag_v6.3_final.csv").is_file(), ROOT
        OUT = ROOT / "docs/analysis/momcozy-historical-collection-audit-20260714"
        OUT.mkdir(parents=True, exist_ok=True)
        sys.path.insert(0, str(ROOT / "src"))

        from reddit_voc.keywords import DEFAULT_COMPETITORS, DEFAULT_PRODUCTS
        from reddit_voc.search_config import DEFAULT_TIKHUB_SEARCH_TERMS
        from reddit_voc.tag_dictionary import TagDictionary

        def file_sha(path: Path) -> str:
            return sha256(path.read_bytes()).hexdigest()

        def load_csv(path: Path) -> list[dict[str, str]]:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))

        def load_json(path: Path):
            return json.loads(path.read_text(encoding="utf-8"))

        FINAL_PATH = ROOT / "dim_tag_v6.3_final.csv"
        CANDIDATE_PATH = ROOT / "dim_tag_v6.3_candidate.csv"
        INTERNAL_SPU_PATH = OUT / "internal-spu-master-join.json"
        PRODUCTION_REFRESH_PATH = OUT / "production-identity-refresh.json"
        DELTA_COVERAGE_PATH = OUT / "delta-term-offline-coverage-audit.json"
        DELTA_COVERAGE_VALIDATION_PATH = OUT / "delta-term-offline-coverage-validation.json"
        COMMENT_DEBT_PATH = OUT / "comment-coverage-debt-audit.json"
        COMMENT_DEBT_VALIDATION_PATH = OUT / "comment-coverage-debt-validation.json"
        final_rows = load_csv(FINAL_PATH)
        candidate_rows = load_csv(CANDIDATE_PATH)
        internal_spu_master = load_json(INTERNAL_SPU_PATH)
        production_refresh = load_json(PRODUCTION_REFRESH_PATH)
        delta_coverage = load_json(DELTA_COVERAGE_PATH)
        delta_coverage_validation = load_json(DELTA_COVERAGE_VALIDATION_PATH)
        comment_debt = load_json(COMMENT_DEBT_PATH)
        comment_debt_validation = load_json(COMMENT_DEBT_VALIDATION_PATH)
        columns = list(final_rows[0])
        print({
            "root": ROOT.name,
            "final_rows": len(final_rows),
            "candidate_rows": len(candidate_rows),
            "columns": len(columns),
        })
        """
    ),
    markdown(
        """
        ## Dictionary Data Quality

        The final and candidate files are compared both byte-for-byte and as
        parsed CSV records. Completeness, identity uniqueness, controlled
        vocabularies, and JSON keyword validity are checked independently.
        """
    ),
    code(
        """
        final_by_id = {row["tag_id"]: row for row in final_rows}
        candidate_by_id = {row["tag_id"]: row for row in candidate_rows}
        blank_cells = sum(
            1 for row in final_rows for value in row.values() if not (value or "").strip()
        )
        invalid_keyword_json = []
        keyword_phrase_rows = defaultdict(list)
        for row in final_rows:
            try:
                phrases = json.loads(row["keywords_en"])
            except json.JSONDecodeError:
                invalid_keyword_json.append(row["tag_id"])
                continue
            if not isinstance(phrases, list) or not phrases:
                invalid_keyword_json.append(row["tag_id"])
                continue
            for phrase in phrases:
                keyword_phrase_rows[" ".join(str(phrase).casefold().split())].append(row)

        shared_phrases = {
            phrase: rows for phrase, rows in keyword_phrase_rows.items() if len(rows) > 1
        }
        cross_sentiment_shared = {
            phrase: rows
            for phrase, rows in shared_phrases.items()
            if len({row["sentiment"] for row in rows}) > 1
        }
        final_bytes = FINAL_PATH.read_bytes()
        candidate_bytes = CANDIDATE_PATH.read_bytes()
        dictionary_quality = {
            "final_sha256": file_sha(FINAL_PATH),
            "candidate_sha256": file_sha(CANDIDATE_PATH),
            "binary_equal": final_bytes == candidate_bytes,
            "binary_difference_only_utf8_bom": (
                final_bytes.startswith(bytes((239, 187, 191)))
                and not candidate_bytes.startswith(bytes((239, 187, 191)))
                and final_bytes[3:] == candidate_bytes
            ),
            "semantic_equal": final_rows == candidate_rows,
            "final_rows": len(final_rows),
            "candidate_rows": len(candidate_rows),
            "unique_final_tag_ids": len(final_by_id),
            "unique_candidate_tag_ids": len(candidate_by_id),
            "blank_cells": blank_cells,
            "invalid_keyword_json_rows": len(invalid_keyword_json),
            "scope_distribution": dict(Counter(row["tag_scope"] for row in final_rows)),
            "sentiment_distribution": dict(Counter(row["sentiment"] for row in final_rows)),
            "shared_keyword_phrase_count": len(shared_phrases),
            "cross_sentiment_shared_keyword_count": len(cross_sentiment_shared),
            "final_crlf_count": final_bytes.count(bytes((13, 10))),
            "candidate_crlf_count": candidate_bytes.count(bytes((13, 10))),
            "final_has_utf8_bom": final_bytes.startswith(bytes((239, 187, 191))),
            "candidate_has_utf8_bom": candidate_bytes.startswith(bytes((239, 187, 191))),
        }
        print(json.dumps(dictionary_quality, ensure_ascii=False, indent=2))
        """
    ),
    markdown(
        """
        ## Governed Brands and SPU Coverage

        Governed brand rows are the `L0-BRD-*` records. The dictionary itself has
        no `spu_name` column, but the project-documented Phase 3 v3.5 product
        master joins all 254 dictionary SPU IDs to exact Chinese and English
        names. Missing active/effective-date fields remain a separate limit.
        """
    ),
    code(
        """
        brand_rows = sorted(
            (row for row in final_rows if row["tag_id"].startswith("L0-BRD-")),
            key=lambda row: row["tag_id"],
        )
        governed_brands = [row["name_en"] for row in brand_rows]
        momcozy_brand = next(row for row in brand_rows if row["name_en"] == "Momcozy")
        governed_competitors = [brand for brand in governed_brands if brand != "Momcozy"]
        brand_alias_rows = []
        for row in brand_rows:
            aliases = json.loads(row["keywords_en"])
            brand_alias_rows.append({
                "tag_id": row["tag_id"],
                "brand": row["name_en"],
                "role": "owner" if row["name_en"] == "Momcozy" else "competitor",
                "aliases": " | ".join(aliases),
                "alias_count": len(aliases),
                "present_in_runtime_competitors": row["name_en"] in DEFAULT_COMPETITORS,
            })

        spu_rows = [row for row in final_rows if row["tag_scope"] == "L2-SPU专属"]
        category_to_spus = defaultdict(set)
        category_to_rows = Counter()
        category_to_lines = defaultdict(set)
        for row in spu_rows:
            category_to_spus[row["voc_category"]].add(row["spu_id"])
            category_to_rows[row["voc_category"]] += 1
            category_to_lines[row["voc_category"]].add(row["product_line"])
        spu_category_rows = [
            {
                "voc_category": category,
                "product_lines": " | ".join(sorted(category_to_lines[category])),
                "distinct_spu_ids": len(category_to_spus[category]),
                "tag_rows": category_to_rows[category],
            }
            for category in sorted(category_to_spus)
        ]
        named_model_categories = sorted(
            category
            for category in category_to_spus
            if re.match(r"^(?:[A-Za-z]+[0-9]+|BS[0-9]+)(?:[ ]|$)", category)
        )
        dictionary = TagDictionary.from_csv(FINAL_PATH)
        pump_profile = dictionary.profile(product_line="吸奶器", voc_category="吸奶器")
        spu_profile = {
            "spu_name_column_present": "spu_name" in columns,
            "spu_tag_rows": len(spu_rows),
            "distinct_spu_ids": len({row["spu_id"] for row in spu_rows}),
            "distinct_voc_categories": len(category_to_spus),
            "named_model_voc_categories": named_model_categories,
            "supported_model_spu_aliases": dictionary.model_spu_aliases,
            "pump_base_eligible_rules": pump_profile["base_context"]["eligible_rule_count"],
            "internal_spu_name_join_complete": internal_spu_master["dictionary_join"]["exact_spu_id_matches"] == 254,
            "internal_spu_named_matches": internal_spu_master["dictionary_join"]["named_matches"],
            "internal_spu_english_named_matches": internal_spu_master["dictionary_join"]["english_named_matches"],
            "internal_spu_model_field_present": internal_spu_master["dictionary_join"]["model_field_present"],
            "internal_master_active_status_present": "active_status" in internal_spu_master["product_master_profile"]["headers"],
            "internal_master_effective_date_present": "effective_date" in internal_spu_master["product_master_profile"]["headers"],
            "heuristic_spoken_variants_not_activated": internal_spu_master["search_alias_assessment"]["spoken_keyword_variants_in_join"],
        }
        print(json.dumps({
            "governed_brands": governed_brands,
            "governed_competitor_count": len(governed_competitors),
            "momcozy_aliases": json.loads(momcozy_brand["keywords_en"]),
            "spu_profile": spu_profile,
        }, ensure_ascii=False, indent=2))
        """
    ),
    markdown(
        """
        ## Search-Term Coverage and Proposed Delta

        The legacy 15-term run is immutable. The v2 profile is a separate,
        reviewable delta: missing Momcozy models, official-storefront product
        aliases, all 17 governed competitor brands, and high-signal category
        anchors. The full SPU-name join validates product identities but does
        not promote 772 heuristic spoken variants, so the reviewed profile
        remains 75 terms / 69 delta. It requires a new run ID and a new Provider
        authorization before activation.
        """
    ),
    code(
        """
        def query_key(value: str) -> str:
            return " ".join(value.strip().strip('"').casefold().split())

        def product_key(value: str) -> str:
            return re.sub(r"[^a-z0-9]", "", value.casefold())

        official_catalog_path = OUT / "official-product-catalog-snapshot.json"
        official_catalog = load_json(official_catalog_path)
        assert all(official_catalog["checks"].values())
        official_alias_terms = official_catalog["official_catalog_candidate_terms"]
        official_product_term_bindings = []
        for product in official_catalog["canonical_product_families"]:
            for term in product["candidate_search_terms"]:
                official_product_term_bindings.append({
                    "term": term,
                    "family_id": product["family_id"],
                    "official_title": product["official_title"],
                    "official_catalog_product_id": product["official_catalog_product_id"],
                    "official_url": product["official_url"],
                    "internal_mapping_status": product["internal_mapping_status"],
                })

        canonical_products = []
        seen_products = set()
        for product in DEFAULT_PRODUCTS["Momcozy"]:
            key = product_key(product)
            if key not in seen_products:
                canonical_products.append(product)
                seen_products.add(key)
        if "bs03" not in seen_products:
            canonical_products.append("BS03")

        owner_alias_terms = ['"mcozy"']
        model_terms = [f'"Momcozy {product}"' for product in canonical_products]
        competitor_term_bindings = []
        for row in brand_rows:
            if row["name_en"] == "Momcozy":
                continue
            primary_alias = json.loads(row["keywords_en"])[0]
            competitor_term_bindings.append({
                "brand": row["name_en"],
                "term": f'"{primary_alias}"',
                "basis": row["tag_id"],
            })
        competitor_terms = [row["term"] for row in competitor_term_bindings]
        category_terms = [
            '"breast pump"',
            '"wearable breast pump"',
            '"hands-free breast pump"',
            '"bottle washer sterilizer"',
            '"bottle sterilizer"',
            '"bottle warmer"',
            '"baby food maker"',
            '"baby formula maker"',
            '"baby feeding set"',
            '"breast milk storage bags"',
            '"breast milk chiller"',
            '"breast pump parts"',
            '"colostrum collector"',
            '"lactation massager"',
            '"baby thermometer"',
            '"baby humidifier"',
            '"diaper pail"',
            '"nursing bra"',
            '"pumping bra"',
            '"baby carrier"',
            '"high chair"',
            '"pregnancy pillow"',
            '"nursing pillow"',
            '"baby monitor"',
            '"sound machine"',
            '"white noise machine"',
        ]
        groups = {
            "owner_alias_gap": owner_alias_terms,
            "momcozy_model_gap": model_terms,
            "official_catalog_aliases": official_alias_terms,
            "governed_competitors": competitor_terms,
            "category_anchors": category_terms,
        }
        legacy_terms = list(DEFAULT_TIKHUB_SEARCH_TERMS)
        legacy_keys = {query_key(term) for term in legacy_terms}
        search_rows = []
        for group, terms in groups.items():
            for term in terms:
                search_rows.append({
                    "group": group,
                    "term": term,
                    "normalized_term": query_key(term),
                    "legacy_exact_semantic_coverage": query_key(term) in legacy_keys,
                })
        deduped_search_rows = []
        seen_terms = set()
        for row in search_rows:
            if row["normalized_term"] in seen_terms:
                continue
            seen_terms.add(row["normalized_term"])
            deduped_search_rows.append(row)
        delta_rows = [row for row in deduped_search_rows if not row["legacy_exact_semantic_coverage"]]
        delta_terms = [row["term"] for row in delta_rows]
        group_coverage = []
        for group in groups:
            rows = [row for row in deduped_search_rows if row["group"] == group]
            group_coverage.append({
                "group": group,
                "recommended_terms": len(rows),
                "covered_by_legacy": sum(bool(row["legacy_exact_semantic_coverage"]) for row in rows),
                "delta_terms": sum(not bool(row["legacy_exact_semantic_coverage"]) for row in rows),
            })

        recommended_search_profile = {
            "schema_version": "momcozy_reddit_search_profile_v2_candidate",
            "status": "reviewed_candidate_not_activated",
            "generated_on": "2026-07-14",
            "source_dictionary": {
                "path": "dim_tag_v6.3_final.csv",
                "sha256": file_sha(FINAL_PATH),
                "row_count": len(final_rows),
            },
            "source_official_catalog": {
                "path": "docs/analysis/momcozy-historical-collection-audit-20260714/official-product-catalog-snapshot.json",
                "sha256": file_sha(official_catalog_path),
                "authority": official_catalog["source"]["authority"],
                "captured_at_utc": official_catalog["captured_at_utc"],
                "catalog_product_count": official_catalog["source"]["catalog_product_count"],
                "canonical_product_family_count": len(official_catalog["canonical_product_families"]),
                "full_internal_spu_join_complete": official_catalog["boundary"]["full_internal_spu_join_complete"],
            },
            "legacy_frozen_run": {
                "run_id": "backfill_momcozy_20250101_20260711",
                "terms": legacy_terms,
                "term_count": len(legacy_terms),
                "distinct_semantic_term_count": len(legacy_keys),
                "immutable": True,
            },
            "candidate_groups": groups,
            "competitor_term_bindings": competitor_term_bindings,
            "official_product_term_bindings": official_product_term_bindings,
            "candidate_term_count": len(deduped_search_rows),
            "delta_terms": delta_terms,
            "delta_term_count": len(delta_terms),
            "execution_contract": {
                "new_run_required": True,
                "provider_authorization_required": True,
                "production_merge_authorized": False,
                "git_push_authorized": False,
                "live_send": False,
                "pre_provider_order": [
                    "freeze exact profile SHA",
                    "import and deduplicate existing 136-file archive offline",
                    "run query-only admission",
                    "prepare one-page-per-lane discovery probe packet",
                ],
            },
        }
        print(json.dumps({
            "legacy_term_count": len(legacy_terms),
            "legacy_distinct_semantic_terms": len(legacy_keys),
            "candidate_term_count": len(deduped_search_rows),
            "delta_term_count": len(delta_terms),
            "group_coverage": group_coverage,
        }, ensure_ascii=False, indent=2))
        """
    ),
    markdown(
        """
        ## Offline Delta-Lane Coverage and Probe Priority

        A Unicode-normalized token-phrase scan checks the 69 unexecuted delta
        terms against local content and the unchanged Task 37 staging database.
        Remote matching runs read-only and returns only Reddit IDs and counts;
        no body text or usernames are exported. Existing lexical evidence helps
        prioritize discovery probes, but does not prove search completeness or
        complete any Provider lane.
        """
    ),
    code(
        """
        delta_coverage_rows = delta_coverage["rows"]
        delta_coverage_aggregate = delta_coverage["aggregate"]
        delta_probe_rows = delta_coverage["recommended_probe_order"]
        delta_group_offline_rows = [
            {"group": group, **stats}
            for group, stats in delta_coverage_aggregate["by_group"].items()
        ]
        print(json.dumps({
            "coverage_classes": delta_coverage_aggregate["coverage_classes"],
            "terms_with_post_surface_evidence": delta_coverage_aggregate["terms_with_post_surface_evidence"],
            "terms_with_comment_evidence": delta_coverage_aggregate["terms_with_comment_evidence"],
            "distinct_evidence_parent_post_ids": delta_coverage_aggregate["distinct_evidence_parent_post_ids"],
            "top_probe_candidates": delta_probe_rows[:10],
            "provider_lanes_completed_by_offline_scan": 0,
        }, ensure_ascii=False, indent=2))
        """
    ),
    markdown(
        """
        ## Comment Coverage Debt and Orphan Recovery

        The 96 terminal partial comment candidates are reconciled against the
        local canonical snapshot before any new Provider request is considered.
        The audit compares exact comment IDs, reported counts, More-node counts,
        and checkpoint state without exporting remote bodies or usernames. It
        also distinguishes exact Task 37 orphan-comment duplicates from
        production-only comments that become linkable when their Task 37 parent
        post is inserted.
        """
    ),
    code(
        """
        comment_debt_rows = comment_debt["rows"]
        comment_debt_aggregate = comment_debt["aggregate"]
        comment_debt_budget = comment_debt["provider_budget_floor"]
        orphan_recovery = comment_debt["production_orphan_recovery"]
        print(json.dumps({
            "candidates": comment_debt_aggregate["candidates"],
            "task37_comment_rows": comment_debt_aggregate["task37_comment_rows"],
            "local_only_comment_increment": comment_debt_aggregate["local_only_comment_increment"],
            "remaining_reported_gap": comment_debt_aggregate["reported_gap_after_offline_union"],
            "more_nodes": comment_debt_aggregate["task37_more_nodes"],
            "offline_reconciliation_classes": comment_debt_aggregate["offline_reconciliation_classes"],
            "minimum_first_page_request_floor": comment_debt_budget["minimum_first_comment_page_request_floor"],
            "remaining_task37_budget": comment_debt_budget["task37_remaining_requests"],
            "orphan_recovery": orphan_recovery["aggregate"],
        }, ensure_ascii=False, indent=2))
        """
    ),
    markdown(
        """
        ## Collection Coverage and Completion Matrix

        Evidence is kept in separate layers: local imported archive, remote
        Task 37 staging, and the refreshed production read-only identity
        snapshot. An identity-only reconciliation measures exact overlap without
        exporting post/comment content or usernames; raw layer counts still
        must not be added directly.
        """
    ),
    code(
        """
        source_profile = load_json(ROOT / "data/imports/ai_nlp_voc_reddit_20260714/source-profile.json")
        fusion = load_json(ROOT / "data/imports/ai_nlp_voc_reddit_20260714/fusion-audit.json")
        import_manifest = load_json(ROOT / "data/imports/ai_nlp_voc_reddit_20260714/import-manifest.json")
        snapshot_manifest = load_json(ROOT / "data/processed/reddit_voc_site_snapshot_20260714/manifest.json")
        snapshot_validation = load_json(ROOT / "data/processed/reddit_voc_site_snapshot_20260714/validation-receipt.json")
        posts = load_json(ROOT / "data/processed/reddit_voc_site_snapshot_20260714/posts.json")
        comments = load_json(ROOT / "data/processed/reddit_voc_site_snapshot_20260714/comments.json")
        overlap_audit = load_json(OUT / "cross-source-overlap-audit.json")
        merge_plan = load_json(OUT / "cross-source-readonly-merge-plan.json")
        task37_identity = load_json(OUT / "task37-identity-snapshot.json")
        production_refresh = load_json(OUT / "production-identity-refresh.json")
        task37_text = (ROOT / ".superpowers/sdd/task-37-remote-execution-report.md").read_text(encoding="utf-8")

        requested_post_ids = {
            row["post_id"] for row in posts if row["created_at_utc"] >= "2025-01-01T00:00:00+00:00"
        }
        requested_comments = [row for row in comments if row["post_id"] in requested_post_ids]
        production_posts = [row for row in posts if "tencent_production_primary" in row["source_kinds"]]
        production_comments = [
            row for row in comments
            if any(item.get("source_kind") == "tencent_production_primary" for item in row.get("source_occurrences", []))
        ]
        task37_counts_match = re.search(r"`([0-9]+) / ([0-9]+) / ([0-9]+) / ([0-9]+)`", task37_text)
        assert task37_counts_match
        task37_threads, task37_comments, task37_analyses, task37_candidates = map(int, task37_counts_match.groups())
        task37_statuses = {}
        for label in ("hydrated", "hydrated/unresolved_more", "hydrated/post_only_coverage", "excluded"):
            match = re.search(rf"- `{re.escape(label)}`: `([0-9]+)`", task37_text)
            assert match, label
            task37_statuses[label] = int(match.group(1))

        observed_brand_rows = []
        archive_bucket_brands = set(source_profile["folder_distribution"]) - {"Momcozy", "other"}
        for brand in governed_competitors:
            requested_mentions = sum(brand in row.get("mentioned_brands", []) for row in posts if row["post_id"] in requested_post_ids)
            archive_mentions = sum(
                brand in row.get("mentioned_brands", [])
                for row in posts
                if "imported_archive" in row["source_kinds"] and row["created_at_utc"] >= "2025-01-01T00:00:00+00:00"
            )
            observed_brand_rows.append({
                "brand": brand,
                "dedicated_archive_bucket": brand in archive_bucket_brands,
                "requested_window_mentions_local_union": requested_mentions,
                "requested_window_mentions_imported_archive": archive_mentions,
                "dedicated_historical_search_lane": False,
            })

        collection_evidence = {
            "imported_archive": {
                "files": source_profile["json_files"],
                "posts": source_profile["posts"],
                "comments": source_profile["comments"],
                "post_date_range": source_profile["post_date_range"],
                "coverage_grade": source_profile["coverage_grade"],
                "provider_call": import_manifest["provider_call"],
                "net_new_posts": fusion["archive_net_increment"]["posts"],
                "net_new_comments": fusion["archive_net_increment"]["comments"],
            },
            "local_canonical_union": {
                "posts": len(posts),
                "linked_comments": len(comments),
                "requested_window_posts": len(requested_post_ids),
                "requested_window_linked_comments": len(requested_comments),
                "latest_post_utc": max(row["created_at_utc"] for row in posts),
                "latest_comment_utc": max(row["created_at_utc"] for row in comments),
                "validation_status": snapshot_validation["status"],
            },
            "production_read_only_snapshot": {
                "posts": production_refresh["counts"]["posts"],
                "comments": production_refresh["counts"]["comments"],
                "captured_at_utc": production_refresh["captured_at_utc"],
                "post_min_utc": production_refresh["time_bounds"]["post_min_utc"],
                "post_max_utc": production_refresh["time_bounds"]["post_max_utc"],
                "comment_max_utc": production_refresh["time_bounds"]["comment_max_utc"],
                "new_posts_since_prior_snapshot": len(production_refresh["comparison_to_previous"]["new_post_ids"]),
                "new_comments_since_prior_snapshot": len(production_refresh["comparison_to_previous"]["new_comment_ids"]),
                "database_identity_unchanged_since_prior_snapshot": production_refresh["comparison_to_previous"]["database_identity_unchanged"],
                "production_unchanged": production_refresh["boundaries"]["production_unchanged"],
            },
            "task37_remote_staging": {
                "threads": task37_threads,
                "comments": task37_comments,
                "analyses": task37_analyses,
                "candidates": task37_candidates,
                "candidate_statuses": task37_statuses,
                "unresolved_comment_candidates": task37_statuses["hydrated/unresolved_more"] + task37_statuses["hydrated/post_only_coverage"],
                "unresolved_candidate_comment_rows": comment_debt_aggregate["task37_comment_rows"],
                "offline_local_only_comment_increment": comment_debt_aggregate["local_only_comment_increment"],
                "reported_gap_after_offline_union": comment_debt_aggregate["reported_gap_after_offline_union"],
                "unresolved_more_nodes": comment_debt_aggregate["task37_more_nodes"],
                "minimum_first_comment_page_request_floor": comment_debt_budget["minimum_first_comment_page_request_floor"],
                "remaining_provider_budget": comment_debt_budget["task37_remaining_requests"],
                "provider_request_count": 1199,
                "task37_provider_call": False,
                "historical_coverage_complete": False,
                "production_unchanged": True,
            },
            "cross_source_identity_reconciliation": {
                "window_start_utc": "2025-01-01T00:00:00+00:00",
                "local_task37_overlap_posts": overlap_audit["task37_increment_vs_local_canonical_union"]["overlap"]["posts"],
                "local_task37_overlap_comments": overlap_audit["task37_increment_vs_local_canonical_union"]["overlap"]["linked_comments"],
                "task37_only_posts": overlap_audit["task37_increment_vs_local_canonical_union"]["task37_only"]["posts"],
                "task37_only_comments": overlap_audit["task37_increment_vs_local_canonical_union"]["task37_only"]["linked_comments"],
                "local_only_posts": overlap_audit["task37_increment_vs_local_canonical_union"]["local_only"]["posts"],
                "local_only_comments": overlap_audit["task37_increment_vs_local_canonical_union"]["local_only"]["linked_comments"],
                "deduplicated_union_posts": overlap_audit["task37_increment_vs_local_canonical_union"]["potential_deduplicated_union"]["posts"],
                "deduplicated_union_comments": overlap_audit["task37_increment_vs_local_canonical_union"]["potential_deduplicated_union"]["linked_comments"],
                "production_orphan_comment_ids_exact_in_task37": overlap_audit["production_orphan_recovery_from_task37"]["orphan_comment_ids_present_in_task37"],
                "production_only_orphan_comments_with_task37_parent": overlap_audit["production_orphan_recovery_from_task37"]["production_only_orphan_comment_ids_with_parent_present_in_task37"],
                "production_orphan_comments_structurally_recoverable": overlap_audit["production_orphan_recovery_from_task37"]["structurally_recoverable_after_task37_parent_insert"],
                "production_orphan_comments_remaining": overlap_audit["production_orphan_recovery_from_task37"]["remaining_unlinked_production_comment_ids"],
                "identity_only": overlap_audit["boundaries"]["identity_only"],
                "remote_write": overlap_audit["boundaries"]["remote_write"],
                "merge_plan_status": merge_plan["status"],
                "merge_plan_actions": merge_plan["actions"],
            },
            "v2_delta_offline_coverage": {
                "terms": delta_coverage_aggregate["terms"],
                "coverage_classes": delta_coverage_aggregate["coverage_classes"],
                "terms_with_post_surface_evidence": delta_coverage_aggregate["terms_with_post_surface_evidence"],
                "terms_with_comment_evidence": delta_coverage_aggregate["terms_with_comment_evidence"],
                "distinct_matching_post_ids": delta_coverage_aggregate["distinct_matching_post_ids"],
                "distinct_matching_comment_ids": delta_coverage_aggregate["distinct_matching_comment_ids"],
                "distinct_evidence_parent_post_ids": delta_coverage_aggregate["distinct_evidence_parent_post_ids"],
                "top_probe_term": delta_probe_rows[0]["term"],
                "provider_lanes_completed": 0,
                "remote_content_exported": delta_coverage["boundaries"]["remote_content_exported"],
            },
        }

        completion_matrix = [
            {"workstream": "Governed dictionary quality", "status": "complete", "evidence": "2,346 rows; unique tag IDs; no blanks; candidate and final semantically equal", "next_gate": "none"},
            {"workstream": "Momcozy and competitor extraction", "status": "complete", "evidence": "1 owner brand and 17 governed competitor brands", "next_gate": "none"},
            {"workstream": "SPU name extraction", "status": "complete_name_join", "evidence": "Phase 3 v3.5 product master joins all 254 dictionary SPU IDs to Chinese and English names; BS03=SPU000714 and BM03=SPU000176", "next_gate": "active_status/effective_date remain absent; current-sale status stays with official storefront"},
            {"workstream": "Legacy historical search configuration", "status": "partial", "evidence": "15 frozen terms, only 12 semantic terms; no competitor-only lanes", "next_gate": "keep immutable; do not retrofit"},
            {"workstream": "v2 search profile", "status": "candidate_ready", "evidence": f"{len(delta_terms)} delta terms across owner alias, models, six official aliases, 17 competitors and categories", "next_gate": "review exact JSON SHA and implement new-run loader"},
            {"workstream": "Existing archive ingestion", "status": "complete_local", "evidence": "136/136 JSON parsed; 4,153 comments; 88 posts and 2,259 comments net-new", "next_gate": "do not equate with Provider completeness"},
            {"workstream": "Task 37 remote historical staging", "status": "partial_debt_profiled", "evidence": "301 threads; 3,225 comments; 96 terminal partial candidates contain 752 comments and 148 More nodes; local union adds only 21 comments, leaving a 2,082 reported-count gap", "next_gate": "one remaining request is below the 96-request first-page floor; implement a reviewed reopen/more-child contract before a new authorization"},
            {"workstream": "Cross-source identity reconciliation", "status": "complete_identity_only", "evidence": "local/Task37 overlap 78 posts and 2,023 linked comments; deduplicated union 410 posts and 4,730 linked comments; one recovered parent makes 8 production orphans structurally linkable", "next_gate": "preserve 10 orphans that still lack parent evidence; merge remains unauthorized"},
            {"workstream": "V2 delta offline lexical coverage", "status": "complete_evidence_only", "evidence": "69 terms profiled over the 410-post/4,730-comment potential union: 19 zero-evidence, 4 comment-only, 9 post-only, 37 post-and-comment", "next_gate": "all 69 Provider discovery lanes remain unexecuted; use frozen priority order"},
            {"workstream": "2025-01-01 to 2026-07-11 competitor/SPU lanes", "status": "offline_profile_complete_provider_not_started", "evidence": "46/69 terms have post-surface evidence and 41/69 have comment evidence, but no dedicated Provider lane has been executed", "next_gate": "new run, isolated loader, query-only admission, exact bounded probe authorization"},
            {"workstream": "2026-07-12 to current snapshot", "status": "partial_daily", "evidence": "fresh read-only identity capture still has 85 posts/414 comments and zero increment; latest post is 2026-07-14 06:37 Beijing", "next_gate": "next 07:00 daily snapshot or separately authorized bounded catch-up"},
            {"workstream": "Production merge / live delivery", "status": "not_authorized", "evidence": "production unchanged; live_send=false; git_push=false", "next_gate": "separate owner authorization after validation"},
        ]
        print(json.dumps(collection_evidence, ensure_ascii=False, indent=2))
        """
    ),
    markdown(
        """
        ## Persist Derived Outputs

        The generated summaries contain no credentials, Reddit usernames, post
        bodies, or comment bodies. The Task 37 and production identity snapshots
        contain only public Reddit entity IDs, parent linkage, and UTC timestamps
        needed for exact deduplication. The internal SPU join excludes product
        owner names and retains only product/classification fields.
        """
    ),
    code(
        """
        def write_json(name: str, value) -> Path:
            path = OUT / name
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + chr(10), encoding="utf-8")
            return path

        def write_csv(name: str, rows: list[dict[str, object]]) -> Path:
            path = OUT / name
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=list(rows[0]), lineterminator=chr(10)
                )
                writer.writeheader()
                writer.writerows(rows)
            return path

        summary = {
            "schema_version": "momcozy_historical_collection_audit_v1",
            "as_of_date": "2026-07-14",
            "dictionary_quality": dictionary_quality,
            "governed_brand_count": len(governed_brands),
            "governed_competitor_count": len(governed_competitors),
            "governed_brands": governed_brands,
            "spu_profile": spu_profile,
            "internal_spu_master_profile": {
                "authority_grade": internal_spu_master["source"]["authority_grade"],
                "version": internal_spu_master["source"]["version"],
                "product_master_rows": internal_spu_master["product_master_profile"]["data_rows"],
                "dictionary_spu_matches": internal_spu_master["dictionary_join"]["exact_spu_id_matches"],
                "named_matches": internal_spu_master["dictionary_join"]["named_matches"],
                "english_named_matches": internal_spu_master["dictionary_join"]["english_named_matches"],
                "verified_single_official_family_bindings": len(internal_spu_master["official_family_binding_review"]["verified_single_internal_spu"]),
                "spoken_keyword_variants_not_activated": internal_spu_master["search_alias_assessment"]["spoken_keyword_variants_in_join"],
                "active_status_present": False,
                "effective_date_present": False,
            },
            "official_catalog_profile": {
                "source_authority": official_catalog["source"]["authority"],
                "captured_at_utc": official_catalog["captured_at_utc"],
                "catalog_product_count": official_catalog["source"]["catalog_product_count"],
                "canonical_product_family_count": len(official_catalog["canonical_product_families"]),
                "verified_existing_alias_count": len(official_catalog["verified_existing_aliases"]),
                "official_candidate_term_count": len(official_alias_terms),
                "unresolved_internal_aliases": official_catalog["unresolved_internal_aliases"],
                "full_internal_spu_join_complete": official_catalog["boundary"]["full_internal_spu_join_complete"],
            },
            "search_profile": {
                "legacy_term_count": len(legacy_terms),
                "legacy_distinct_semantic_term_count": len(legacy_keys),
                "candidate_term_count": len(deduped_search_rows),
                "delta_term_count": len(delta_terms),
                "group_coverage": group_coverage,
            },
            "delta_offline_coverage": {
                "terms": delta_coverage_aggregate["terms"],
                "coverage_classes": delta_coverage_aggregate["coverage_classes"],
                "terms_with_post_surface_evidence": delta_coverage_aggregate["terms_with_post_surface_evidence"],
                "terms_with_comment_evidence": delta_coverage_aggregate["terms_with_comment_evidence"],
                "distinct_evidence_parent_post_ids": delta_coverage_aggregate["distinct_evidence_parent_post_ids"],
                "top_probe_candidates": delta_probe_rows[:10],
                "provider_lanes_completed": 0,
                "independent_validation_status": delta_coverage_validation["status"],
            },
            "comment_coverage_debt": {
                "candidates": comment_debt_aggregate["candidates"],
                "task37_comment_rows": comment_debt_aggregate["task37_comment_rows"],
                "local_only_comment_increment": comment_debt_aggregate["local_only_comment_increment"],
                "remaining_reported_gap": comment_debt_aggregate["reported_gap_after_offline_union"],
                "more_nodes": comment_debt_aggregate["task37_more_nodes"],
                "minimum_first_comment_page_request_floor": comment_debt_budget["minimum_first_comment_page_request_floor"],
                "remaining_task37_provider_budget": comment_debt_budget["task37_remaining_requests"],
                "structurally_recoverable_production_orphans": orphan_recovery["aggregate"]["structurally_recoverable_comments"],
                "remaining_unlinked_production_orphans": orphan_recovery["aggregate"]["still_unlinked_comments"],
                "independent_validation_status": comment_debt_validation["status"],
            },
            "collection_evidence": collection_evidence,
            "evidence_gate": {
                "decision": "allowed-with-label",
                "supported_claims": [
                    "dictionary and local source snapshots were analyzed read-only",
                    "the Phase 3 v3.5 internal product master joins all 254 dictionary SPU IDs to exact Chinese and English product names",
                    "the 75-term / 69-delta search profile remains unchanged after rejecting 772 unreviewed heuristic spoken variants",
                    "the official Momcozy storefront catalog was captured read-only for product-name evidence",
                    "competitor archive ingestion is complete for the supplied 136 files",
                    "Task 37 staging remains partial",
                    "Task 37 and the local canonical union were reconciled exactly at Reddit post/comment ID grain",
                    "the identity-only local plus Task 37 union contains 410 posts and 4,730 linked comments in the requested window",
                    "all 69 V2 delta terms were profiled offline: 19 have zero lexical evidence, 4 are comment-only, 9 are post-only, and 37 appear in both post and comment surfaces",
                    "offline lexical evidence prioritizes probes but does not complete any Provider discovery lane",
                    "all 96 Task 37 partial comment candidates were reconciled by exact ID; seven gain 21 local-only comments but all retain a reported-count gap",
                    "the current one-request reserve is below the 96-request first-comment-page floor and is not a closure budget",
                    "one Task 37 parent post makes eight production orphan comments structurally recoverable; ten still lack parent evidence",
                    "the v2 search profile is a non-activated candidate",
                ],
                "forbidden_claims": [
                    "historical competitor/SPU coverage is complete",
                    "official catalog product IDs are internal SPU IDs",
                    "the May internal product-master snapshot proves current active status or effective dates",
                    "BS03 and BM03 are the same model",
                    "Task 37 issued a TikHub request",
                    "one remaining Task 37 request can close the 96 partial comment candidates",
                    "reported comment-count gaps equal guaranteed retrievable comments",
                    "production was merged or accepted",
                    "DingTalk was sent",
                ],
            },
        }
        outputs = [
            write_json("analysis-summary.json", summary),
            write_json("recommended-search-profile.json", recommended_search_profile),
            write_csv("brand-aliases.csv", brand_alias_rows),
            write_csv("spu-category-profile.csv", spu_category_rows),
            write_csv("search-term-coverage.csv", deduped_search_rows),
            write_csv("brand-collection-coverage.csv", observed_brand_rows),
            write_csv("completion-matrix.csv", completion_matrix),
        ]
        print({path.name: {"bytes": path.stat().st_size, "sha256": file_sha(path)} for path in outputs})
        """
    ),
    markdown(
        """
        ## Validation

        Assertions below recheck the decision-driving counts, input hashes,
        Provider/production boundaries, and every generated file. This is an
        analytical validation pass, not a Reddit_VOC product test suite.
        """
    ),
    code(
        """
        config_candidate = ROOT / "config/backfill/momcozy-search-profile-v2-candidate-20260714.json"
        analysis_profile = OUT / "recommended-search-profile.json"
        checks = {
            "dictionary_rows_2346": len(final_rows) == 2346,
            "dictionary_tag_ids_unique": len(final_by_id) == len(final_rows),
            "dictionary_no_blank_cells": blank_cells == 0,
            "dictionary_keyword_json_valid": not invalid_keyword_json,
            "candidate_final_semantically_equal": final_rows == candidate_rows,
            "candidate_final_binary_delta_is_bom_only": dictionary_quality["binary_difference_only_utf8_bom"] is True,
            "governed_owner_present": governed_brands.count("Momcozy") == 1,
            "governed_competitors_17": len(governed_competitors) == 17,
            "dictionary_spu_name_column_absent": "spu_name" not in columns,
            "internal_spu_master_checks_passed": all(internal_spu_master["checks"].values()),
            "internal_spu_exact_join_254": internal_spu_master["dictionary_join"]["exact_spu_id_matches"] == 254,
            "internal_spu_named_join_254": internal_spu_master["dictionary_join"]["named_matches"] == 254,
            "internal_spu_english_named_join_254": internal_spu_master["dictionary_join"]["english_named_matches"] == 254,
            "internal_spu_active_status_not_claimed": "active_status" not in internal_spu_master["product_master_profile"]["headers"],
            "internal_spu_effective_date_not_claimed": "effective_date" not in internal_spu_master["product_master_profile"]["headers"],
            "heuristic_spoken_variants_not_activated": internal_spu_master["search_alias_assessment"]["auto_promoted_terms"] == 0,
            "supported_spu_aliases_exact": dictionary.model_spu_aliases == {"m5": "SPU001001001003016", "m9": "SPU000168"},
            "official_catalog_checks_passed": all(official_catalog["checks"].values()),
            "official_catalog_families_18": len(official_catalog["canonical_product_families"]) == 18,
            "official_existing_aliases_24": len(official_catalog["verified_existing_aliases"]) == 24,
            "official_candidate_terms_6": len(official_alias_terms) == 6,
            "bs03_not_equated_to_bm03": official_catalog["checks"]["bs03_not_equated_to_bm03"] is True,
            "v2_candidate_terms_75": len(deduped_search_rows) == 75,
            "v2_delta_terms_69": len(delta_terms) == 69,
            "delta_offline_coverage_checks_passed": all(delta_coverage["checks"].values()),
            "delta_offline_independent_validation_passed": delta_coverage_validation["status"] == "passed" and all(delta_coverage_validation["checks"].values()),
            "delta_offline_terms_match_profile": {row["term"] for row in delta_coverage_rows} == set(delta_terms),
            "delta_offline_zero_evidence_19": delta_coverage_aggregate["coverage_classes"]["zero_existing_lexical_evidence"] == 19,
            "delta_offline_comment_only_4": delta_coverage_aggregate["coverage_classes"]["comment_only_existing_lexical_evidence"] == 4,
            "delta_offline_post_only_9": delta_coverage_aggregate["coverage_classes"]["post_only_existing_lexical_evidence"] == 9,
            "delta_offline_both_37": delta_coverage_aggregate["coverage_classes"]["post_and_comment_existing_lexical_evidence"] == 37,
            "delta_offline_all_provider_lanes_unexecuted": all(row["provider_discovery_still_required"] for row in delta_coverage_rows),
            "delta_offline_top_probe_bm03": delta_probe_rows[0]["term"] == '"Momcozy BM03"',
            "delta_offline_remote_content_not_exported": delta_coverage["boundaries"]["remote_content_exported"] is False,
            "comment_debt_checks_passed": all(comment_debt["checks"].values()),
            "comment_debt_independent_validation_passed": comment_debt_validation["status"] == "passed" and all(comment_debt_validation["checks"].values()),
            "comment_debt_candidates_96": comment_debt_aggregate["candidates"] == 96,
            "comment_debt_local_increment_21": comment_debt_aggregate["local_only_comment_increment"] == 21,
            "comment_debt_remaining_gap_2082": comment_debt_aggregate["reported_gap_after_offline_union"] == 2082,
            "comment_debt_more_nodes_148": comment_debt_aggregate["task37_more_nodes"] == 148,
            "comment_debt_all_candidates_still_open": all(row["provider_reopen_status"] == "still_required_after_offline_reconciliation" for row in comment_debt_rows),
            "comment_debt_first_page_floor_96": comment_debt_budget["minimum_first_comment_page_request_floor"] == 96,
            "comment_debt_remaining_budget_1": comment_debt_budget["task37_remaining_requests"] == 1,
            "comment_debt_remote_content_not_exported": comment_debt["boundaries"]["remote_content_exported"] is False,
            "archive_fusion_checks_passed": fusion["all_checks_passed"] is True,
            "snapshot_validation_passed": snapshot_validation["status"] == "passed",
            "task37_candidate_accounting": sum(task37_statuses.values()) == task37_candidates,
            "task37_unresolved_96": collection_evidence["task37_remote_staging"]["unresolved_comment_candidates"] == 96,
            "task37_provider_not_retried": collection_evidence["task37_remote_staging"]["task37_provider_call"] is False,
            "task37_identity_snapshot_checks_passed": all(task37_identity["checks"].values()),
            "cross_source_overlap_checks_passed": all(overlap_audit["checks"].values()),
            "cross_source_merge_plan_checks_passed": all(merge_plan["checks"].values()),
            "cross_source_merge_plan_not_executable": merge_plan["boundaries"]["executable"] is False,
            "local_task37_overlap_78_2023": overlap_audit["task37_increment_vs_local_canonical_union"]["overlap"] == {"posts": 78, "linked_comments": 2023},
            "task37_only_223_1202": overlap_audit["task37_increment_vs_local_canonical_union"]["task37_only"] == {"posts": 223, "linked_comments": 1202},
            "local_only_109_1505": overlap_audit["task37_increment_vs_local_canonical_union"]["local_only"] == {"posts": 109, "linked_comments": 1505},
            "deduplicated_union_410_4730": overlap_audit["task37_increment_vs_local_canonical_union"]["potential_deduplicated_union"] == {"posts": 410, "linked_comments": 4730},
            "task37_recovers_six_production_orphans": overlap_audit["production_orphan_recovery_from_task37"]["orphan_comment_ids_present_in_task37"] == 6,
            "task37_parent_recovers_two_additional_production_orphans": overlap_audit["production_orphan_recovery_from_task37"]["production_only_orphan_comment_ids_with_parent_present_in_task37"] == 2,
            "production_orphans_structurally_recoverable_8": overlap_audit["production_orphan_recovery_from_task37"]["structurally_recoverable_after_task37_parent_insert"] == 8,
            "production_orphans_remaining_10": overlap_audit["production_orphan_recovery_from_task37"]["remaining_unlinked_production_comment_ids"] == 10,
            "production_refresh_checks_passed": all(production_refresh["checks"].values()),
            "production_identity_unchanged_since_prior_snapshot": production_refresh["comparison_to_previous"]["database_identity_unchanged"] is True,
            "production_refresh_counts_85_414": production_refresh["counts"]["posts"] == 85 and production_refresh["counts"]["comments"] == 414,
            "production_unchanged": production_refresh["boundaries"]["production_unchanged"] is True,
            "v2_requires_new_run": recommended_search_profile["execution_contract"]["new_run_required"] is True,
            "v2_not_activated": recommended_search_profile["status"] == "reviewed_candidate_not_activated",
            "v2_config_exactly_matches_analysis": (
                config_candidate.is_file()
                and config_candidate.read_bytes() == analysis_profile.read_bytes()
            ),
        }
        core_output_names = [
            "analysis-summary.json",
            "brand-aliases.csv",
            "brand-collection-coverage.csv",
            "build_comment_coverage_debt_audit.py",
            "build_cross_source_overlap_audit.py",
            "build_delta_term_offline_coverage_audit.py",
            "build_notebook.py",
            "build_official_product_catalog.py",
            "capture_production_identity_refresh.py",
            "capture_task37_identity_snapshot.py",
            "completion-matrix.csv",
            "comment-coverage-debt-audit.json",
            "comment-coverage-debt-validation.json",
            "comment-coverage-debt.csv",
            "cross-source-overlap-audit.json",
            "cross-source-overlap-matrix.csv",
            "cross-source-readonly-merge-plan.json",
            "delta-term-offline-coverage-audit.json",
            "delta-term-offline-coverage.csv",
            "delta-term-offline-coverage-validation.json",
            "internal-spu-master-join.json",
            "production-identity-refresh.json",
            "production-orphan-recovery-matrix.csv",
            "recommended-search-profile.json",
            "search-term-coverage.csv",
            "spu-category-profile.csv",
            "spu-master-source-audit.json",
            "task37-identity-snapshot.json",
            "validate_delta_term_offline_coverage.py",
            "validate_comment_coverage_debt.py",
        ]
        generated_files = [OUT / name for name in core_output_names]
        receipt = {
            "schema_version": "momcozy_historical_collection_audit_validation_v1",
            "status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
            "source_sha256": {
                "dim_tag_v6.3_final.csv": file_sha(FINAL_PATH),
                "dim_tag_v6.3_candidate.csv": file_sha(CANDIDATE_PATH),
                ".superpowers/sdd/task-37-remote-execution-report.md": file_sha(ROOT / ".superpowers/sdd/task-37-remote-execution-report.md"),
                "data/imports/ai_nlp_voc_reddit_20260714/fusion-audit.json": file_sha(ROOT / "data/imports/ai_nlp_voc_reddit_20260714/fusion-audit.json"),
                "data/processed/reddit_voc_site_snapshot_20260714/manifest.json": file_sha(ROOT / "data/processed/reddit_voc_site_snapshot_20260714/manifest.json"),
                "docs/analysis/momcozy-historical-collection-audit-20260714/task37-identity-snapshot.json": file_sha(OUT / "task37-identity-snapshot.json"),
                "docs/analysis/momcozy-historical-collection-audit-20260714/cross-source-overlap-audit.json": file_sha(OUT / "cross-source-overlap-audit.json"),
                "docs/analysis/momcozy-historical-collection-audit-20260714/cross-source-readonly-merge-plan.json": file_sha(OUT / "cross-source-readonly-merge-plan.json"),
                "docs/analysis/momcozy-historical-collection-audit-20260714/internal-spu-master-join.json": file_sha(INTERNAL_SPU_PATH),
                "docs/analysis/momcozy-historical-collection-audit-20260714/production-identity-refresh.json": file_sha(PRODUCTION_REFRESH_PATH),
                "docs/analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage-audit.json": file_sha(DELTA_COVERAGE_PATH),
                "docs/analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage.csv": file_sha(OUT / "delta-term-offline-coverage.csv"),
                "docs/analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage-validation.json": file_sha(DELTA_COVERAGE_VALIDATION_PATH),
                "docs/analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt-audit.json": file_sha(COMMENT_DEBT_PATH),
                "docs/analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt.csv": file_sha(OUT / "comment-coverage-debt.csv"),
                "docs/analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt-validation.json": file_sha(COMMENT_DEBT_VALIDATION_PATH),
                "docs/analysis/momcozy-historical-collection-audit-20260714/production-orphan-recovery-matrix.csv": file_sha(OUT / "production-orphan-recovery-matrix.csv"),
                "docs/analysis/momcozy-historical-collection-audit-20260714/official-product-catalog-snapshot.json": file_sha(official_catalog_path),
                "docs/analysis/momcozy-historical-collection-audit-20260714/official-product-name-catalog.csv": file_sha(OUT / "official-product-name-catalog.csv"),
                "config/backfill/momcozy-search-profile-v2-candidate-20260714.json": file_sha(config_candidate),
            },
            "generated_files": {path.name: file_sha(path) for path in generated_files},
            "boundaries": {
                "provider_call": False,
                "provider_attempt_made": False,
                "production_unchanged": True,
                "remote_write": False,
                "database_write": "local-analysis-output-only",
                "live_send": False,
                "git_push": False,
                "local_product_tests_run": False,
            },
        }
        write_json("validation-receipt.json", receipt)
        assert all(checks.values()), [name for name, passed in checks.items() if not passed]
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        """
    ),
]


namespace: dict[str, object] = {"__name__": "__main__"}
execution_count = 0
failure: BaseException | None = None
for cell in cells:
    if cell["cell_type"] != "code":
        continue
    execution_count += 1
    cell["execution_count"] = execution_count
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(compile(str(cell["source"]), f"analysis-cell-{execution_count}", "exec"), namespace, namespace)
    except BaseException as exc:  # preserve the failed notebook for diagnosis
        failure = exc
        cell["outputs"].append(
            {
                "output_type": "error",
                "ename": type(exc).__name__,
                "evalue": str(exc),
                "traceback": traceback.format_exc().splitlines(),
            }
        )
    if stdout.getvalue():
        cell["outputs"].append(
            {"output_type": "stream", "name": "stdout", "text": stdout.getvalue()}
        )
    if stderr.getvalue():
        cell["outputs"].append(
            {"output_type": "stream", "name": "stderr", "text": stderr.getvalue()}
        )
    if failure is not None:
        break

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3.12"},
        "analysis_boundaries": {
            "provider_call": False,
            "production_unchanged": True,
            "live_send": False,
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
NOTEBOOK_PATH.write_text(
    json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
)

if failure is not None:
    raise failure

print(
    json.dumps(
        {
            "notebook": str(NOTEBOOK_PATH.relative_to(ROOT)),
            "executed_code_cells": execution_count,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        sort_keys=True,
    )
)
