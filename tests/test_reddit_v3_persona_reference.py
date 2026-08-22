from __future__ import annotations

from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = ROOT / "data/reference/reddit-voc-v3"
MANIFEST_PATH = REFERENCE_ROOT / "manifest.json"
PERSONA_PATH = REFERENCE_ROOT / "dim_persona_v1.csv"
COHORT_CONFIG_PATH = ROOT / "config/personas/reddit-voc-persona-cohorts-v3.json"

EXPECTED_FILES = {
    "dim_persona_v1.csv": {
        "bytes": 35_755,
        "header": [
            "persona_id",
            "persona_name",
            "dimension",
            "sub_dimension",
            "definition",
            "keywords",
            "semantic_pattern",
            "confidence_rules",
            "aip_likelihood",
            "lifecycle_stage",
            "hit_rate_tier",
        ],
        "logical_name": "persona_atomic_dictionary",
        "media_type": "text/csv",
        "original_path_label": (
            "ai_nlp_voc/system_data/main_dim/output/dictionaries/"
            "dim_persona_v1.csv"
        ),
        "row_count": 82,
        "row_count_semantics": "csv_data_rows",
        "sha256": (
            "279b313509141eb0f7432040818e261178fd9f75ec67a947a0cb9e6211799b1e"
        ),
    },
    "indicator_tag_mapping.csv": {
        "bytes": 1_065_524,
        "header": [
            "indicator_code",
            "indicator_name",
            "tag_id",
            "tag_name_cn",
            "tag_scope",
            "aipl_node",
            "theme",
            "sentiment",
            "priority",
            "risk_level",
            "dept_owner",
            "proxy_nps_role",
        ],
        "logical_name": "legacy_indicator_tag_mapping",
        "media_type": "text/csv",
        "original_path_label": (
            "ai_nlp_voc/system_data/main_dim/output/reports/"
            "indicator_tag_mapping.csv"
        ),
        "row_count": 8_854,
        "row_count_semantics": "csv_data_rows",
        "sha256": (
            "ebb6ee922e7fc190484d23808566c8a68241d493631ec7e16cb5d7d3f09a9270"
        ),
    },
    "voc-indicator-registry-stable.csv": {
        "bytes": 4_657,
        "header": [
            "canonical_indicator_id",
            "indicator_name",
            "aliases",
            "registry_role",
            "tag_mapping_code",
            "storyline_code",
            "production_code",
            "superset_dataset",
            "requires_external_data",
            "status",
            "notes",
        ],
        "logical_name": "legacy_indicator_registry",
        "media_type": "text/csv",
        "original_path_label": (
            "ai_nlp_voc/configs/auto-labeling/"
            "voc-indicator-registry-stable.csv"
        ),
        "row_count": 43,
        "row_count_semantics": "csv_data_rows",
        "sha256": (
            "7a8b0fef91f9668ab9457b1ee22e4b1289d84772aabd214feb4243bb12734bac"
        ),
    },
    "indicator_storyline_matrix.csv": {
        "bytes": 4_320,
        "header": [
            "indicator_code",
            "indicator_name",
            "threshold_op",
            "threshold_value",
            "storyline_trigger",
            "trigger_priority",
            "auto_notify_dept",
            "trigger_description",
            "sla_hours",
            "escalation_storyline",
        ],
        "logical_name": "legacy_indicator_storyline_matrix",
        "media_type": "text/csv",
        "original_path_label": (
            "ai_nlp_voc/system_data/main_dim/governance/"
            "indicator_storyline_matrix.csv"
        ),
        "row_count": 43,
        "row_count_semantics": "csv_data_rows",
        "sha256": (
            "c017e7f3e4c7ace7c10cb65890078a32e02b944fe5417167a5f1cef23d33eac5"
        ),
    },
    "13_voc_insight_storylines.md": {
        "bytes": 100_234,
        "header": [
            "name",
            "description",
            "created",
            "updated",
            "status",
            "depends",
        ],
        "logical_name": "legacy_six_part_storyline_reference",
        "media_type": "text/markdown",
        "original_path_label": (
            "ai_nlp_voc/system_data/main_dim/governance/"
            "13_voc_insight_storylines.md"
        ),
        "row_count": 1_958,
        "row_count_semantics": "physical_lines",
        "sha256": (
            "0c7702a4987529eb65ab75e6811d7aad4bdbbbe85a3f5a8dfd5d296ca1962fd2"
        ),
    },
}

EXPECTED_DIMENSIONS = {
    "EMOTION": 13,
    "HOW": 16,
    "TECH": 3,
    "WHAT": 13,
    "WHEN": 12,
    "WHO": 12,
    "WHY": 13,
}
EXPECTED_UNBRIDGED = {"PER-EMOTION-003", "PER-WHY-010", "PER-WHY-011"}


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _range(dimension: str, start: int, end: int) -> list[str]:
    return [f"PER-{dimension}-{index:03d}" for index in range(start, end + 1)]


def _expected_bridge() -> dict[str, list[str]]:
    values = {
        "purchase_decision": [
            "PER-WHO-003",
            *_range("WHAT", 10, 13),
            "PER-WHEN-009",
            "PER-HOW-005",
            "PER-HOW-006",
            *_range("HOW", 8, 16),
            *_range("EMOTION", 11, 13),
        ],
        "product_evaluator": [
            *_range("WHO", 5, 7),
            *_range("WHAT", 1, 9),
            "PER-WHAT-011",
            "PER-WHAT-012",
            *_range("HOW", 2, 5),
            "PER-HOW-010",
            "PER-HOW-012",
            "PER-EMOTION-005",
            "PER-EMOTION-008",
            *_range("TECH", 1, 3),
        ],
        "competitor_comparer": [
            "PER-WHO-002",
            "PER-WHO-006",
            "PER-HOW-004",
            "PER-HOW-005",
            "PER-HOW-016",
            "PER-EMOTION-013",
        ],
        "operations_troubleshooter": [
            "PER-WHO-001",
            "PER-WHO-005",
            *_range("WHY", 1, 6),
            "PER-WHY-012",
            "PER-WHY-013",
            "PER-WHAT-002",
            "PER-WHAT-004",
            "PER-WHEN-010",
            "PER-EMOTION-002",
            "PER-TECH-002",
            "PER-TECH-003",
        ],
        "fit_output_optimizer": [
            "PER-WHO-008",
            "PER-WHO-009",
            "PER-WHO-011",
            "PER-WHO-012",
            "PER-WHY-001",
            "PER-WHY-004",
            "PER-WHY-007",
            "PER-WHY-008",
            "PER-WHY-012",
            "PER-WHY-013",
            "PER-WHAT-003",
            "PER-WHAT-004",
            *_range("WHAT", 6, 9),
            "PER-EMOTION-001",
            "PER-EMOTION-005",
            "PER-EMOTION-006",
            "PER-EMOTION-008",
        ],
        "scenario_adapter": [
            "PER-WHO-003",
            "PER-WHO-004",
            *_range("WHO", 8, 12),
            "PER-WHY-002",
            "PER-WHY-003",
            "PER-WHY-005",
            "PER-WHY-009",
            "PER-WHAT-002",
            "PER-WHAT-004",
            "PER-WHAT-005",
            *_range("WHEN", 1, 12),
            "PER-HOW-001",
            "PER-HOW-002",
            "PER-HOW-004",
            "PER-EMOTION-001",
            "PER-EMOTION-007",
            "PER-EMOTION-009",
        ],
        "service_support_seeker": [
            "PER-WHO-001",
            "PER-WHO-004",
            "PER-WHO-005",
            "PER-WHY-001",
            "PER-WHY-004",
            "PER-WHY-006",
            "PER-WHY-012",
            "PER-WHY-013",
            "PER-WHEN-010",
            "PER-WHEN-011",
            "PER-EMOTION-002",
            "PER-EMOTION-004",
            "PER-TECH-002",
            "PER-TECH-003",
        ],
        "recommendation_expression": [
            "PER-HOW-006",
            "PER-HOW-007",
            "PER-HOW-009",
            "PER-HOW-010",
            "PER-HOW-011",
            "PER-EMOTION-001",
            "PER-EMOTION-008",
            "PER-EMOTION-010",
        ],
    }
    return {key: sorted(value) for key, value in values.items()}


class PersonaReferenceContractTests(unittest.TestCase):
    def test_reference_manifest_is_canonical_and_exact(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(MANIFEST_PATH.read_bytes(), _canonical_json(manifest))
        self.assertEqual(
            manifest["schema_version"], "reddit_voc_v3_reference_manifest_v1"
        )
        self.assertEqual(manifest["manifest_version"], "reddit_voc_v3_20260716_v1")
        self.assertEqual(manifest["source_project_label"], "ai_nlp_voc")
        self.assertEqual(manifest["boundaries"], {
            "copied_by_exact_bytes": True,
            "runtime_absolute_paths": False,
            "runtime_symlinks": False,
            "legacy_metrics_are_reference_only": True,
            "legacy_storyline_thresholds_inherited": False,
            "provider_call": False,
            "production_unchanged": True,
        })

        files = {row["path"]: row for row in manifest["files"]}
        self.assertEqual(set(files), set(EXPECTED_FILES))
        for relative, expected in EXPECTED_FILES.items():
            self.assertEqual(files[relative], {"path": relative, **expected})
            path = REFERENCE_ROOT / relative
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.stat().st_size, expected["bytes"])
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected["sha256"])
            self.assertFalse(PurePosixPath(relative).is_absolute())
            if expected["media_type"] == "text/csv":
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    rows = list(reader)
                self.assertEqual(reader.fieldnames, expected["header"])
                self.assertEqual(len(rows), expected["row_count"])
            else:
                self.assertEqual(
                    len(path.read_text(encoding="utf-8").splitlines()),
                    expected["row_count"],
                )

    def test_persona_dictionary_contract(self) -> None:
        with PERSONA_PATH.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        ids = [row["persona_id"] for row in rows]
        self.assertEqual(len(rows), 82)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(
            re.fullmatch(
                r"PER-(WHO|WHY|WHAT|WHEN|HOW|EMOTION|TECH)-\d{3}", value
            )
            for value in ids
        ))
        self.assertEqual(dict(sorted(Counter(row["dimension"] for row in rows).items())), EXPECTED_DIMENSIONS)

        keyword_owners: defaultdict[str, set[str]] = defaultdict(set)
        keyword_instances = 0
        template_instances = 0
        for row in rows:
            keywords = json.loads(row["keywords"])
            self.assertIsInstance(keywords, list)
            self.assertTrue(keywords)
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in keywords))
            self.assertEqual(
                json.loads(row["confidence_rules"]),
                {"直接陈述": "A", "行为暗示": "B"},
            )
            self.assertEqual(
                set(json.loads(row["aip_likelihood"])),
                {"A", "I", "P1", "P2", "L1", "L2", "L3"},
            )
            for keyword in keywords:
                normalized = unicodedata.normalize("NFKC", keyword).casefold().strip()
                keyword_owners[normalized].add(row["persona_id"])
                keyword_instances += 1
                if "[brand]" in keyword or "[platform]" in keyword:
                    template_instances += 1

        self.assertEqual(keyword_instances, 454)
        self.assertEqual(len(keyword_owners), 425)
        self.assertEqual(
            sum(len(owners) > 1 for owners in keyword_owners.values()), 28
        )
        self.assertEqual(template_instances, 5)

    def test_cohort_bridge_is_exact_and_avatar_paths_are_local(self) -> None:
        config = json.loads(COHORT_CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(COHORT_CONFIG_PATH.read_bytes(), _canonical_json(config))
        self.assertEqual(
            config["schema_version"], "reddit_voc_persona_cohort_config_v1"
        )
        self.assertEqual(config["bridge_version"], "persona_cohort_bridge_v1")
        self.assertEqual(config["bridge_summary"], {
            "bridge_edge_count": 141,
            "bridged_persona_tag_count": 79,
            "cohort_count": 8,
            "unbridged_persona_tag_count": 3,
        })
        self.assertEqual(config["availability_thresholds"], {
            "directional_sample_min": 10,
            "stable_sample_min": 30,
            "unavailable_below": 10,
        })
        self.assertEqual(config["dictionary_binding"], {
            "asset_path": "data/reference/reddit-voc-v3/dim_persona_v1.csv",
            "bytes": 35_755,
            "row_count": 82,
            "sha256": (
                "279b313509141eb0f7432040818e261178fd9f75ec67a947a0cb9e6211799b1e"
            ),
        })
        self.assertEqual(
            config["assignment_id_formula"],
            "sha256(canonical_json_v1({voc_id,cohort_id,cohort_config_sha256,"
            "snapshot_id,scope,source_stratum,persona_fact_ids,"
            "governed_signal_fact_ids,signal_evidence_refs,evidence_scope,"
            "voc_tag_ids}))",
        )
        expected_bridge = _expected_bridge()
        actual_bridge = {
            row["cohort_id"]: row["persona_tag_ids"] for row in config["cohorts"]
        }
        self.assertEqual(actual_bridge, expected_bridge)
        self.assertEqual(len(config["cohorts"]), 8)
        self.assertEqual(sum(len(values) for values in actual_bridge.values()), 141)
        bridged = set().union(*(set(values) for values in actual_bridge.values()))
        self.assertEqual(len(bridged), 79)
        self.assertEqual(set(config["unbridged_persona_tag_ids"]), EXPECTED_UNBRIDGED)

        with PERSONA_PATH.open(encoding="utf-8", newline="") as handle:
            dictionary_ids = {row["persona_id"] for row in csv.DictReader(handle)}
        self.assertEqual(bridged | EXPECTED_UNBRIDGED, dictionary_ids)
        self.assertFalse(bridged & EXPECTED_UNBRIDGED)

        primary_paths: set[str] = set()
        fallback_paths: set[str] = set()
        for row in config["cohorts"]:
            self.assertEqual(row["persona_tag_ids"], sorted(set(row["persona_tag_ids"])))
            avatar = row["avatar"]
            for key in (
                "source_asset_path",
                "public_asset_path",
                "fallback_source_asset_path",
                "fallback_public_asset_path",
            ):
                value = avatar[key]
                self.assertNotIn("://", value)
                self.assertFalse(PurePosixPath(value).is_absolute())
                self.assertNotIn("..", PurePosixPath(value).parts)
                self.assertEqual(PurePosixPath(value).suffix, ".svg")
            self.assertTrue(avatar["alt_text"].endswith("非真实用户"))
            self.assertIs(avatar["synthetic"], True)
            self.assertIs(avatar["real_user_image"], False)
            self.assertIs(avatar["derived_from_reddit_media"], False)
            self.assertIs(avatar["identity_claim"], False)
            primary_paths.add(avatar["source_asset_path"])
            fallback_paths.add(avatar["fallback_source_asset_path"])
        self.assertEqual(len(primary_paths), 8)
        self.assertEqual(len(fallback_paths), 1)
        reused_existing_paths = {
            (
                "docs/superpowers/assets/reddit-voc-evidence-personas/"
                "persona-explicit-advocate.svg"
            ),
            (
                "docs/superpowers/assets/reddit-voc-evidence-personas/"
                "persona-work-scenario.svg"
            ),
        }
        self.assertTrue(reused_existing_paths <= primary_paths)
        self.assertTrue(all((ROOT / path).is_file() for path in reused_existing_paths))


if __name__ == "__main__":
    unittest.main()
