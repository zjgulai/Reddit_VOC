from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest

from scripts.validate_reddit_site_snapshot import validate


DATASET_VERSION = "reddit_voc_site_snapshot_fixture_rc1"
V2_ADMITTED_IDS = [f"p{index:05d}" for index in range(842)]
V2_GAP_IDS = [f"g{index:05d}" for index in range(18)]


def _identity_hash(values: list[str]) -> str:
    return hashlib.sha256(
        "".join(f"{value}\n" for value in sorted(set(values))).encode("utf-8")
    ).hexdigest()


V2_TARGET_SHA256 = _identity_hash([*V2_ADMITTED_IDS, *V2_GAP_IDS])
V2_GAP_SHA256 = _identity_hash(V2_GAP_IDS)
LEDGER_SHA256 = (
    "cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab"
)
ROOT = Path(__file__).resolve().parents[1]


def _analysis() -> dict[str, Any]:
    return {
        "analysis_version": "local_rules_v1",
        "analysis_code_sha256": "a" * 64,
        "sentiment_label": "neutral",
        "sentiment_score": 0,
        "topic": "other",
        "severity": "low",
        "confidence": 1,
        "pain_points": [],
        "provider_call": False,
    }


def _tagging() -> dict[str, Any]:
    return {
        "ambiguous_keyword_matches": [],
        "aspect_tag_ids": [],
        "brand_tag_ids": [],
        "context": {
            "product_line": "未解析",
            "voc_category": "未解析",
            "detected_spu_ids": [],
            "spu_binding_mode": "dictionary_alias_legacy",
        },
        "dictionary_version": "fixture-dictionary-v1",
        "eligible_rule_count": 0,
        "low_specificity_keyword_matches": [],
        "matches": [],
        "negated_keyword_matches": [],
        "semantic_validation_status": "not_run",
        "tag_ids": [],
    }


def _post(index: int) -> dict[str, Any]:
    grade = "partial" if index == 841 else "full"
    return {
        "post_id": f"p{index:05d}",
        "title": "safe title",
        "content": "safe content",
        "author_pseudonym": None,
        "structural_coverage_grade": grade,
        "source_kinds": ["tencent_v2_search_hydrated"],
        "source_occurrences": [
            {
                "source_kind": "tencent_v2_search_hydrated",
                "dataset_id": "fixture-v2",
                "collection_bucket": "v2_discovery",
                "run_id": None,
                "coverage_grade": grade,
            }
        ],
        "analysis": _analysis(),
        "tagging": _tagging(),
    }


def _comment() -> dict[str, Any]:
    return {
        "comment_id": "t1_fixture",
        "post_id": "p00000",
        "body": "safe comment",
        "author_pseudonym": None,
        "include_in_voc_metrics": True,
        "source_occurrences": [
            {
                "source_kind": "tencent_v2_search_hydrated",
                "dataset_id": "fixture-v2",
                "collection_bucket": "v2_discovery",
                "run_id": None,
                "coverage_grade": None,
            }
        ],
        "analysis": _analysis(),
        "tagging": _tagging(),
    }


def _compact_write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_fixture(snapshot_dir: Path) -> dict[str, Any]:
    snapshot_dir.mkdir(parents=True)
    posts = [_post(index) for index in range(len(V2_ADMITTED_IDS))]
    comments = [_comment()]
    quarantine: list[dict[str, Any]] = []
    aggregates = {
        "schema_version": "reddit_voc_site_aggregates_v1",
        "headline": {
            "unique_posts": 842,
            "linked_comments": 1,
            "quarantined_comments": 0,
            "comments_in_voc_metrics": 1,
            "analysis_covered_posts": 842,
            "analysis_covered_comments": 1,
            "posts_with_rule_tags": 0,
            "comments_with_rule_tags_in_voc_metrics": 0,
            "posts_with_aspect_tags": 0,
            "comments_with_aspect_tags": 0,
        },
        "tagging": {
            "posts_with_rule_tags": 0,
            "comments_with_rule_tags": 0,
            "posts_with_aspect_tags": 0,
            "comments_with_aspect_tags": 0,
        },
    }
    tag_dictionary = {
        "schema_version": "reddit_voc_tag_dictionary_v1",
        "dictionary_version": "fixture-dictionary-v1",
        "dictionary_sha256": "d" * 64,
        "profile": {
            "dictionary_version": "fixture-dictionary-v1",
            "row_count": 0,
        },
        "rules": [],
    }
    documents = {
        "posts.json": posts,
        "comments.json": comments,
        "aggregates.json": aggregates,
        "quarantine.json": quarantine,
        "tag-dictionary.json": tag_dictionary,
    }
    for name, value in documents.items():
        _compact_write(snapshot_dir / name, value)

    v2_debt = {
        "cursor_outstanding": 1,
        "page_pagination_outstanding": 1,
        "partial_threads": 1,
    }
    manifest = {
        "schema_version": "reddit_voc_site_snapshot_manifest_v1",
        "dataset_version": DATASET_VERSION,
        "generated_at_utc": "2026-07-15T00:00:00+00:00",
        "delivery_mode": "versioned_static_snapshot",
        "source_boundaries": {
            "imported_archive": {
                "unique_posts": 0,
                "unique_comments": 0,
                "net_new_posts": 0,
                "net_new_comments": 0,
            },
            "historical_canonical": {
                "input_posts": 0,
                "input_comments": 0,
                "overlap_posts": 0,
                "overlap_comments": 0,
                "net_new_posts": 0,
                "net_new_comments": 0,
                "fusion_role": "lineage_occurrence_only_strict_archive_subset",
            },
            "tencent_production_primary": {
                "input_posts": 0,
                "input_comments": 0,
                "overlap_posts": 0,
                "overlap_comments": 0,
                "net_new_posts": 0,
                "net_new_comments": 0,
                "fusion_role": "canonical_primary_disjoint_from_archive",
            },
            "tencent_isolated_staging": {
                "input_posts": 0,
                "input_comments": 0,
                "overlap_posts": 0,
                "overlap_comments": 0,
                "net_new_posts": 0,
                "net_new_comments": 0,
                "fusion_role": "deterministic_overlay_after_production",
            },
            "tencent_v2_search_hydrated": {
                "admission_status": "passed_with_partial_comment_coverage",
                "identity_set_id": "discovery_only",
                "identity_freeze_sha256": "e" * 64,
                "snapshot_sha256": "f" * 64,
                "target_count": 860,
                "admitted_posts": 842,
                "admitted_observed_comments": 1,
                "lineage_gap_count": 18,
                "lineage_gap_lf_sha256": V2_GAP_SHA256,
                "coverage_grade_counts": {"full": 841, "partial": 1},
                "cursor_outstanding": 1,
                "page_pagination_outstanding": 1,
                "comment_coverage_debt": v2_debt,
                "overlap_posts": 0,
                "overlap_comments": 0,
                "net_new_posts": 842,
                "net_new_comments": 1,
                "fusion_role": "disjoint_hydrated_discovery_append",
                "provider_call": False,
                "database_write": False,
                "production_merge": False,
                "live_send": False,
            },
        },
        "fusion_accounting": {
            "load_order": [
                "imported_archive",
                "historical_canonical_lineage_only",
                "tencent_production_primary",
                "tencent_isolated_staging_overlay",
                "tencent_v2_search_hydrated_disjoint_append",
            ],
            "post_identity_key": "post_id",
            "comment_identity_key": "comment_id",
            "expected_from_source_net_new": {"posts": 842, "stored_comments": 1},
            "actual_canonical": {
                "posts": 842,
                "stored_comments": 1,
                "linked_comments": 1,
                "quarantined_comments": 0,
            },
            "v2_comment_coverage_debt": v2_debt,
            "coverage_debt_is_not_zero_filled": True,
        },
        "canonical_counts": {
            "posts": 842,
            "stored_comments": 1,
            "linked_comments": 1,
            "quarantined_comments": 0,
        },
        "analysis": {
            "version": "local_rules_v1",
            "code_sha256": "a" * 64,
            "keyword_rules_sha256": "b" * 64,
            "provider_call": False,
            "recomputed_for_all_public_entities": True,
        },
        "tagging": {
            "dictionary_version": "fixture-dictionary-v1",
            "dictionary_sha256": "d" * 64,
            "dictionary_row_count": 0,
            "entity_context": {
                "product_line": "未解析",
                "voc_category": "未解析",
                "resolution_status": "pending_product_entity_resolver",
            },
            "labels_provisional": True,
            "semantic_validation_run": False,
            "provider_call": False,
        },
        "privacy": {
            "raw_author_fields_present": False,
            "author_display": "stable_pseudonym",
            "html_fields_present": False,
            "contact_patterns_redacted": True,
            "known_archive_bots_excluded_from_voc_metrics": True,
            "raw_archive_public": False,
            "production_private_snapshot_mode": "0600",
        },
        "semantic_boundaries": {
            "collection_bucket_is_brand_ownership": False,
            "brand_metric_label": "sample mention share",
            "market_share_supported": False,
            "roi_supported": False,
            "response_time_supported": False,
            "global_product_category_imputed": False,
            "product_category_resolution_status": "pending_product_entity_resolver",
        },
        "files": {
            name: _file_record(snapshot_dir / name) for name in documents
        },
        "checks": {"builder_checks_passed": True},
        "all_checks_passed": True,
        "production_unchanged": True,
        "provider_call": False,
        "live_send": False,
    }
    (snapshot_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _load_manifest(snapshot_dir: Path) -> dict[str, Any]:
    return json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))


def _promote_to_manifest_v2(snapshot_dir: Path) -> dict[str, Any]:
    manifest = _load_manifest(snapshot_dir)
    posts = json.loads((snapshot_dir / "posts.json").read_text(encoding="utf-8"))
    comments = json.loads(
        (snapshot_dir / "comments.json").read_text(encoding="utf-8")
    )
    aggregates = json.loads(
        (snapshot_dir / "aggregates.json").read_text(encoding="utf-8")
    )

    base_post = _post(0)
    base_post["post_id"] = "base01"
    base_post["source_kinds"] = ["imported_archive"]
    base_post["source_occurrences"] = [
        {
            "source_kind": "imported_archive",
            "dataset_id": "fixture-archive",
            "collection_bucket": "archive",
            "run_id": None,
            "coverage_grade": None,
        }
    ]
    posts.append(base_post)

    hydration_comment = _comment()
    hydration_comment["comment_id"] = "t1_hydration"
    hydration_comment["post_id"] = "base01"
    hydration_comment["source_occurrences"] = [
        {
            "source_kind": "tencent_existing_post_comment_hydration",
            "dataset_id": "fixture-existing-hydration",
            "collection_bucket": "existing_post_hydration",
            "run_id": None,
            "coverage_grade": None,
        }
    ]
    comments.append(hydration_comment)

    aggregates["headline"].update(
        {
            "unique_posts": 843,
            "linked_comments": 2,
            "comments_in_voc_metrics": 2,
            "analysis_covered_posts": 843,
            "analysis_covered_comments": 2,
        }
    )
    for name, value in (
        ("posts.json", posts),
        ("comments.json", comments),
        ("aggregates.json", aggregates),
    ):
        _compact_write(snapshot_dir / name, value)
        manifest["files"][name] = _file_record(snapshot_dir / name)

    manifest["schema_version"] = "reddit_voc_site_snapshot_manifest_v2"
    manifest["source_boundaries"]["tencent_v2_search_hydrated"][
        "lineage_gap_post_ids"
    ] = V2_GAP_IDS
    manifest["source_boundaries"]["tencent_v2_search_hydrated"][
        "target_lf_sha256"
    ] = V2_TARGET_SHA256
    archive = manifest["source_boundaries"]["imported_archive"]
    archive["unique_posts"] = 1
    archive["net_new_posts"] = 1
    hydration_debt = {
        "first_page_missing": 0,
        "cursor_outstanding": 0,
        "page_pagination_outstanding": 1,
        "failed_reports": 0,
        "partial_threads": 1,
        "not_observed_threads": 0,
        "failure_reason_counts": {},
    }
    hydration_work = {
        "first_page_missing_post_ids": [],
        "cursor_outstanding": [],
        "page_pagination_outstanding_post_ids": ["base01"],
        "failed_reports": [],
        "partial_post_ids": ["base01"],
        "not_observed_post_ids": [],
    }
    manifest["source_boundaries"][
        "tencent_existing_post_comment_hydration"
    ] = {
        "admission_status": "passed_with_explicit_comment_coverage_debt",
        "dataset_id": "fixture-existing-hydration",
        "snapshot_sha256": "1" * 64,
        "baseline_post_count": 843,
        "baseline_post_ids_lf_sha256": _identity_hash(
            [*V2_ADMITTED_IDS, "base01"]
        ),
        "baseline_comment_count": 1,
        "baseline_comment_ids_lf_sha256": _identity_hash(["t1_fixture"]),
        "input_posts": 0,
        "input_comments": 1,
        "materialized_comments": 1,
        "release_candidate_comments": 1,
        "preceding_overlap_comments": 0,
        "preceding_body_conflicts": 0,
        "overlap_posts": 0,
        "overlap_comments": 0,
        "net_new_posts": 0,
        "net_new_comments": 1,
        "coverage_grade_counts": {
            "full": 0,
            "partial": 1,
            "not_observed": 0,
        },
        "comment_coverage_debt": hydration_debt,
        "coverage_work_items": hydration_work,
        "fusion_role": "existing_post_comment_delta_after_v2",
        "dedup_key": {"posts": "post_id", "comments": "comment_id"},
        "precedence_policy": "preceding_canonical_wins",
        "provider_call": False,
        "database_write": False,
        "production_merge": False,
        "live_send": False,
    }
    fusion = manifest["fusion_accounting"]
    fusion["load_order"].append(
        "tencent_existing_post_comment_hydration_append"
    )
    fusion["expected_from_source_net_new"] = {
        "posts": 843,
        "stored_comments": 2,
    }
    fusion["actual_canonical"] = {
        "posts": 843,
        "stored_comments": 2,
        "linked_comments": 2,
        "quarantined_comments": 0,
    }
    fusion["existing_post_hydration_coverage_debt"] = hydration_debt
    first_missing_ids = set(V2_GAP_IDS)
    partial_ids = {"p00841", "base01"}
    fusion["comment_coverage_debt_union"] = {
        "first_page_missing": len(first_missing_ids),
        "first_page_missing_lf_sha256": _identity_hash(list(first_missing_ids)),
        "cursor_outstanding": 1,
        "cursor_outstanding_lf_sha256": "2" * 64,
        "page_pagination_outstanding": 2,
        "page_pagination_outstanding_lf_sha256": "3" * 64,
        "failed_reports": 0,
        "failed_reports_lf_sha256": _identity_hash([]),
        "partial_threads": len(partial_ids),
        "partial_thread_ids_lf_sha256": _identity_hash(list(partial_ids)),
        "not_observed_threads": len(first_missing_ids),
        "not_observed_thread_ids_lf_sha256": _identity_hash(
            list(first_missing_ids)
        ),
        "source_counts": {
            "v2": {
                "first_page_missing": 18,
                "cursor_outstanding": 1,
                "page_pagination_outstanding": 1,
                "failed_reports": 0,
            },
            "existing_post_hydration": hydration_debt,
        },
        "key_union_not_numeric_sum": True,
    }
    manifest["canonical_counts"] = fusion["actual_canonical"]
    _write_manifest(snapshot_dir, manifest)
    return manifest


def _write_manifest(snapshot_dir: Path, manifest: dict[str, Any]) -> None:
    (snapshot_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rewrite_document(snapshot_dir: Path, name: str, value: Any) -> None:
    path = snapshot_dir / name
    _compact_write(path, value)
    manifest = _load_manifest(snapshot_dir)
    manifest["files"][name] = _file_record(path)
    _write_manifest(snapshot_dir, manifest)


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bindings = [binding for row in rows for binding in row["product_bindings"]]
    category_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    for binding in bindings:
        category_id = binding["category"]["id"]
        category_counts[category_id] = category_counts.get(category_id, 0) + 1
        family = binding["product_family"]
        if family is not None:
            family_id = family["id"]
            family_counts[family_id] = family_counts.get(family_id, 0) + 1
    return {
        "input_record_count": len(rows),
        "bound_record_count": sum(bool(row["product_bindings"]) for row in rows),
        "unbound_record_count": sum(not row["product_bindings"] for row in rows),
        "multi_binding_record_count": sum(
            len(row["product_bindings"]) > 1 for row in rows
        ),
        "binding_count": len(bindings),
        "exact_spu_binding_count": sum(
            binding["binding_level"] == "spu_exact" for binding in bindings
        ),
        "family_only_binding_count": sum(
            binding["binding_level"] == "product_family" for binding in bindings
        ),
        "category_only_binding_count": sum(
            binding["binding_level"] == "category" for binding in bindings
        ),
        "taxonomy_blocked_binding_count": sum(
            binding["governance_status"] == "taxonomy_blocked"
            for binding in bindings
        ),
        "category_binding_counts": category_counts,
        "family_binding_counts": family_counts,
        "is_conserved": True,
    }


def _promote_to_resolved(snapshot_dir: Path) -> None:
    posts = json.loads((snapshot_dir / "posts.json").read_text(encoding="utf-8"))
    comments = json.loads(
        (snapshot_dir / "comments.json").read_text(encoding="utf-8")
    )
    for row in [*posts, *comments]:
        row["product_bindings"] = []
        row["tagging"]["context"] = {
            "resolution_mode": "governed_product_bindings",
            "contexts": [
                {"product_line": "", "voc_category": "", "spu_ids": []}
            ],
            "detected_spu_ids": [],
            "spu_binding_mode": "governed_explicit",
        }
    posts[0]["product_bindings"] = [
        {
            "brand_id": "momcozy",
            "category": {
                "id": "breast_pump",
                "name_en": "Breast Pump",
                "name_cn": "吸奶器",
            },
            "product_family": None,
            "exact_spu": None,
            "binding_level": "category",
            "match_type": "category_context",
            "matched_alias": "breast pump",
            "governance_status": "category_only",
            "governance_reason": None,
        }
    ]
    posts[0]["tagging"]["context"] = {
        "resolution_mode": "governed_product_bindings",
        "contexts": [
            {
                "product_line": "吸奶器",
                "voc_category": "吸奶器",
                "spu_ids": [],
            }
        ],
        "detected_spu_ids": [],
        "spu_binding_mode": "governed_explicit",
    }
    _rewrite_document(snapshot_dir, "posts.json", posts)
    _rewrite_document(snapshot_dir, "comments.json", comments)

    manifest = _load_manifest(snapshot_dir)
    manifest["source_boundaries"]["tencent_v2_search_hydrated"][
        "target_lf_sha256"
    ] = V2_TARGET_SHA256
    manifest["source_boundaries"]["tencent_v2_search_hydrated"][
        "lineage_gap_post_ids"
    ] = V2_GAP_IDS
    del manifest["tagging"]["entity_context"]
    manifest["tagging"]["product_entity_resolution"] = {
        "status": "resolved",
        "resolver_version": "product-entity-resolver-v1",
        "ledger_version": "momcozy-product-entity-ledger-2026-07-15.v1",
        "ledger_sha256": LEDGER_SHA256,
        "coverage": {
            "posts": _coverage(posts),
            "comments": _coverage(comments),
            "combined": _coverage([*posts, *comments]),
        },
        "observed_tag_contexts": [
            {
                "product_line": "吸奶器",
                "voc_category": "吸奶器",
                "spu_ids": [],
            }
        ],
    }
    manifest["semantic_boundaries"]["product_category_resolution_status"] = (
        "governed_product_entity_resolver_v1"
    )
    manifest["semantic_boundaries"]["product_entity_ledger_sha256"] = (
        LEDGER_SHA256
    )
    manifest["semantic_boundaries"]["product_category_analysis_supported"] = True
    manifest["semantic_boundaries"]["product_family_analysis_supported"] = True
    manifest["semantic_boundaries"][
        "exact_spu_analysis_supported_only_for_approved_bindings"
    ] = True
    _write_manifest(snapshot_dir, manifest)


class RedditSiteSnapshotValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_validates_version_independent_pending_fixture(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)

        receipt = validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

        self.assertEqual(
            receipt["status"], "validated_with_pending_product_resolution"
        )
        self.assertIs(receipt["release_candidate"], False)
        self.assertEqual(receipt["product_entity_resolution"], "pending")
        self.assertEqual(
            receipt["v2_target_hash_binding"],
            "upstream_identity_gate_legacy_manifest",
        )
        self.assertEqual(receipt["counts"]["posts"], 842)
        self.assertEqual(receipt["counts"]["linked_comments"], 1)
        self.assertNotIn("manifest_sha256", receipt)

    def test_validates_dynamic_v2_target_and_gap_counts(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        manifest = _write_fixture(snapshot_dir)
        v2 = manifest["source_boundaries"]["tencent_v2_search_hydrated"]
        v2["target_count"] = 861
        v2["lineage_gap_count"] = 19
        v2["lineage_gap_lf_sha256"] = "1" * 64
        _write_manifest(snapshot_dir, manifest)

        receipt = validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

        self.assertEqual(receipt["counts"]["posts"], 842)
        self.assertEqual(
            receipt["v2_target_hash_binding"],
            "upstream_identity_gate_legacy_manifest",
        )

    def test_validates_manifest_v2_hydration_and_union(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        _promote_to_manifest_v2(snapshot_dir)

        receipt = validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

        self.assertEqual(
            receipt["status"], "validated_with_pending_product_resolution"
        )
        self.assertEqual(receipt["counts"]["posts"], 843)
        self.assertEqual(receipt["counts"]["linked_comments"], 2)
        self.assertEqual(
            receipt["manifest_sha256"],
            hashlib.sha256((snapshot_dir / "manifest.json").read_bytes()).hexdigest(),
        )

    def test_manifest_v2_requires_hydration_source_boundary(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        manifest = _promote_to_manifest_v2(snapshot_dir)
        del manifest["source_boundaries"][
            "tencent_existing_post_comment_hydration"
        ]
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(ValueError, "source boundary set mismatch"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_manifest_v2_rejects_hydration_load_order_tampering(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        manifest = _promote_to_manifest_v2(snapshot_dir)
        manifest["fusion_accounting"]["load_order"][-1] = (
            "tencent_existing_post_comment_hydration_overlay"
        )
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(ValueError, "fusion load order mismatch"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_manifest_v2_rejects_hydration_occurrence_tampering(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        manifest = _promote_to_manifest_v2(snapshot_dir)
        hydration = manifest["source_boundaries"][
            "tencent_existing_post_comment_hydration"
        ]
        hydration["materialized_comments"] = 0
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(
            ValueError,
            "source comment occurrence mismatch: "
            "tencent_existing_post_comment_hydration",
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_manifest_v2_rejects_non_disjoint_hydration_occurrence(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        _promote_to_manifest_v2(snapshot_dir)
        comments = json.loads(
            (snapshot_dir / "comments.json").read_text(encoding="utf-8")
        )
        comments[-1]["source_occurrences"].append(
            {
                "source_kind": "tencent_v2_search_hydrated",
                "dataset_id": "fixture-v2",
                "collection_bucket": "v2_discovery",
                "run_id": None,
                "coverage_grade": None,
            }
        )
        _rewrite_document(snapshot_dir, "comments.json", comments)

        with self.assertRaisesRegex(
            ValueError, "hydration comment is not disjoint from prior sources"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_manifest_v2_rejects_duplicate_hydration_work_item(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        manifest = _promote_to_manifest_v2(snapshot_dir)
        hydration = manifest["source_boundaries"][
            "tencent_existing_post_comment_hydration"
        ]
        hydration["coverage_work_items"]["partial_post_ids"].append("base01")
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(
            ValueError, "hydration coverage work item duplicate"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_manifest_v2_rejects_union_count_tampering(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        manifest = _promote_to_manifest_v2(snapshot_dir)
        manifest["fusion_accounting"]["comment_coverage_debt_union"][
            "first_page_missing"
        ] += 1
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(
            ValueError, "coverage debt union first-page mismatch"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_manifest_v2_rejects_recomputable_union_hash_tampering(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        manifest = _promote_to_manifest_v2(snapshot_dir)
        manifest["fusion_accounting"]["comment_coverage_debt_union"][
            "partial_thread_ids_lf_sha256"
        ] = "0" * 64
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(
            ValueError, "coverage debt union partial-thread mismatch"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_cli_requires_expected_dataset_version(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/validate_reddit_site_snapshot.py"),
                "--snapshot-dir",
                str(snapshot_dir),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--expected-dataset-version", result.stderr)

    def test_rejects_expected_dataset_version_mismatch(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)

        with self.assertRaisesRegex(ValueError, "dataset version mismatch"):
            validate(snapshot_dir, expected_dataset_version="different_version")

    def test_rejects_manifest_schema_mismatch(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        manifest = _write_fixture(snapshot_dir)
        manifest["schema_version"] = "reddit_voc_site_snapshot_manifest_v0"
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(ValueError, "manifest schema mismatch"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_manifest_file_set_mismatch(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        manifest = _write_fixture(snapshot_dir)
        del manifest["files"]["aggregates.json"]
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(ValueError, "manifest file set mismatch"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_file_tampering_before_semantic_checks(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        with (snapshot_dir / "posts.json").open("a", encoding="utf-8") as handle:
            handle.write(" ")

        with self.assertRaisesRegex(ValueError, "byte mismatch: posts.json"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_duplicate_post_ids_after_rehash(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        posts = json.loads(
            (snapshot_dir / "posts.json").read_text(encoding="utf-8")
        )
        posts[1]["post_id"] = posts[0]["post_id"]
        _rewrite_document(snapshot_dir, "posts.json", posts)

        with self.assertRaisesRegex(ValueError, "duplicate post ids"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_orphan_linked_comment_after_rehash(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        comments = json.loads(
            (snapshot_dir / "comments.json").read_text(encoding="utf-8")
        )
        comments[0]["post_id"] = "missing"
        _rewrite_document(snapshot_dir, "comments.json", comments)

        with self.assertRaisesRegex(ValueError, "linked comment missing parent post"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_linked_quarantine_conservation_tampering(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        manifest = _write_fixture(snapshot_dir)
        manifest["canonical_counts"]["stored_comments"] = 2
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(
            ValueError, "linked/quarantine stored comment conservation mismatch"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_fusion_net_new_tampering(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        manifest = _write_fixture(snapshot_dir)
        manifest["source_boundaries"]["tencent_v2_search_hydrated"][
            "net_new_posts"
        ] = 841
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(
            ValueError, "source net-new post conservation mismatch"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_zero_filled_v2_coverage_debt(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        manifest = _write_fixture(snapshot_dir)
        zero_debt = {
            "cursor_outstanding": 0,
            "page_pagination_outstanding": 0,
            "partial_threads": 0,
        }
        v2 = manifest["source_boundaries"]["tencent_v2_search_hydrated"]
        v2["cursor_outstanding"] = 0
        v2["page_pagination_outstanding"] = 0
        v2["comment_coverage_debt"] = zero_debt
        manifest["fusion_accounting"]["v2_comment_coverage_debt"] = zero_debt
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(
            ValueError, "V2 comment coverage debt was zero-filled"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_pending_status_rejects_product_binding_smuggling(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        posts = json.loads(
            (snapshot_dir / "posts.json").read_text(encoding="utf-8")
        )
        posts[0]["product_bindings"] = []
        _rewrite_document(snapshot_dir, "posts.json", posts)

        with self.assertRaisesRegex(
            ValueError, "pending product resolution contains entity bindings"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_resolved_product_contract_recomputes_coverage(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        _promote_to_resolved(snapshot_dir)

        receipt = validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

        self.assertEqual(receipt["status"], "passed_release_candidate")
        self.assertIs(receipt["release_candidate"], True)
        self.assertEqual(receipt["product_entity_resolution"], "resolved")
        self.assertEqual(receipt["v2_target_hash_binding"], "manifest_exact")

    def test_resolved_product_contract_rejects_coverage_tampering(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        _promote_to_resolved(snapshot_dir)
        manifest = _load_manifest(snapshot_dir)
        manifest["tagging"]["product_entity_resolution"]["coverage"]["posts"][
            "bound_record_count"
        ] = 2
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(ValueError, "product coverage mismatch: posts"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_resolved_product_contract_rejects_unapproved_ledger(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        _promote_to_resolved(snapshot_dir)
        manifest = _load_manifest(snapshot_dir)
        manifest["tagging"]["product_entity_resolution"]["ledger_sha256"] = (
            "0" * 64
        )
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(
            ValueError, "product resolver ledger hash mismatch"
        ):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_resolved_release_rejects_wrong_v2_target_identity_hash(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        _promote_to_resolved(snapshot_dir)
        manifest = _load_manifest(snapshot_dir)
        manifest["source_boundaries"]["tencent_v2_search_hydrated"][
            "target_lf_sha256"
        ] = "0" * 64
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(ValueError, "V2 target identity hash mismatch"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_provider_call_even_after_rehash(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        _write_fixture(snapshot_dir)
        comments = json.loads(
            (snapshot_dir / "comments.json").read_text(encoding="utf-8")
        )
        comments[0]["analysis"]["provider_call"] = True
        _rewrite_document(snapshot_dir, "comments.json", comments)

        with self.assertRaisesRegex(ValueError, "provider call found"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)

    def test_rejects_live_send_claim(self) -> None:
        snapshot_dir = self.tmp_path / "snapshot"
        manifest = _write_fixture(snapshot_dir)
        manifest["live_send"] = True
        _write_manifest(snapshot_dir, manifest)

        with self.assertRaisesRegex(ValueError, "manifest live send found"):
            validate(snapshot_dir, expected_dataset_version=DATASET_VERSION)
