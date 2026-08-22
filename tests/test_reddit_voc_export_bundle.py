from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from reddit_voc.v3_export_bundle import (
    ARTIFACT_FILES,
    ExportBundleError,
    ExportBundleMetadata,
    canonical_json_bytes,
    canonical_jsonl,
    sha256_bytes,
    write_export_bundle,
)


class BundleFixture:
    bundle_id = "reddit_voc_export_fixture_a1"
    release_id = "reddit_voc_release_fixture_a1"
    snapshot_id = "reddit_voc_snapshot_fixture_a1"

    def __init__(self, root: Path, *, mode: str = "private_audit") -> None:
        self.root = root
        self.output = root / "bundle"
        self.metadata = ExportBundleMetadata(
            export_bundle_id=self.bundle_id,
            release_id=self.release_id,
            source_snapshot_id=self.snapshot_id,
            source_cutoff_value="2026-07-15",
            source_cutoff_precision="day",
            source_timezone_status="unknown_floating_date",
            dictionary_sha256="1" * 64,
            indicator_registry_sha256="2" * 64,
            eligibility_policy_sha256="3" * 64,
            builder_code_sha256=sha256(
                (
                    Path(__file__).resolve().parents[1]
                    / "scripts/build_reddit_voc_export_bundle.py"
                ).read_bytes()
            ).hexdigest(),
            validator_code_sha256=sha256(
                (
                    Path(__file__).resolve().parents[1]
                    / "scripts/validate_reddit_voc_export_bundle.py"
                ).read_bytes()
            ).hexdigest(),
            candidate_release_sha256="6" * 64,
            bundle_mode=mode,
        )
        common = {
            "export_bundle_id": self.bundle_id,
            "release_id": self.release_id,
            "source_snapshot_id": self.snapshot_id,
        }
        fact_id = "fact:comment1:sentiment"
        metric_payload = {
            "denominator": 2,
            "denominator_member_ids": ["t1_comment1", "t3_post1"],
            "evidence_fact_ids": [fact_id],
            "metric_eligible_member_ids": ["t1_comment1", "t3_post1"],
            "numerator": 1,
            "numerator_member_ids": ["t1_comment1"],
            "policy_version": "fixture.v1",
            "reddit_indicator_id": "fixture.metric",
            "status": "available",
            "value": 1,
        }
        metric_source = "metrics/metrics.json"
        metric_type = "all_history_indicator"
        metric_digest = sha256_bytes(
            canonical_json_bytes(
                {
                    "payload": metric_payload,
                    "record_type": metric_type,
                    "source": metric_source,
                }
            )
        )
        case_payload = {
            "canonical_entity_id": "t3_post1",
            "evidence_ids": [fact_id],
            "review_status": "review_required",
        }
        case_source = "integrity/assessments.jsonl"
        case_type = "integrity_assessment"
        case_digest = sha256_bytes(
            canonical_json_bytes(
                {
                    "payload": case_payload,
                    "record_type": case_type,
                    "source": case_source,
                }
            )
        )
        self.rows = {
            "reddit-entities-full.jsonl": [
                {
                    **common,
                    "entity_id": "t3_post1",
                    "entity_refs": [],
                    "entity_type": "post",
                    "exclusion_reasons": [],
                    "fact_refs": [],
                    "payload": {
                        "canonical_reddit_id": "t3_post1",
                        "entity_type": "post",
                    },
                    "schema_version": "reddit_voc_export_entity_v1",
                    "source_provenance": {
                        "source": "fixture",
                        "source_artifact": "canonical/posts.jsonl",
                    },
                },
                {
                    **common,
                    "entity_id": "t1_comment1",
                    "entity_refs": [],
                    "entity_type": "comment",
                    "exclusion_reasons": [],
                    "fact_refs": [],
                    "payload": {
                        "canonical_reddit_id": "t1_comment1",
                        "comment_state": "linked",
                        "entity_type": "comment",
                    },
                    "schema_version": "reddit_voc_export_entity_v1",
                    "source_provenance": {
                        "source": "fixture",
                        "source_artifact": "canonical/comments.jsonl",
                    },
                },
            ],
            "reddit-voc-facts.jsonl": [
                {
                    **common,
                    "entity_refs": ["t3_post1"],
                    "fact_refs": [],
                    "payload": {
                        "canonical_entity_id": "t3_post1",
                        "voc_id": "post:post1",
                    },
                    "record_id": "voc:post:post1",
                    "record_kind": "voc",
                    "schema_version": "reddit_voc_export_voc_fact_v1",
                    "source_artifact": "voc_facts/vocs.jsonl",
                    "voc_id": "post:post1",
                },
                {
                    **common,
                    "entity_refs": ["t1_comment1"],
                    "fact_id": fact_id,
                    "fact_refs": [],
                    "payload": {
                        "canonical_entity_id": "t1_comment1",
                        "fact_id": fact_id,
                    },
                    "record_id": f"fact:{fact_id}",
                    "record_kind": "fact",
                    "schema_version": "reddit_voc_export_voc_fact_v1",
                    "source_artifact": (
                        "governed_signals/entity-sentiment-facts.jsonl"
                    ),
                },
            ],
            "reddit-metrics-reporting.jsonl": [
                {
                    **common,
                    "denominator": 2,
                    "entity_refs": ["t1_comment1", "t3_post1"],
                    "fact_refs": [fact_id],
                    "formula_version": "fixture.v1",
                    "metric_record_id": (
                        f"metric:{metric_type}:{metric_digest}"
                    ),
                    "numerator": 1,
                    "payload": metric_payload,
                    "record_type": metric_type,
                    "schema_version": "reddit_voc_export_metric_reporting_v1",
                    "source_artifact": metric_source,
                    "status": "available",
                }
            ],
            "reddit-governance-casebook.jsonl": [
                {
                    **common,
                    "case_record_id": f"case:{case_type}:{case_digest}",
                    "entity_refs": ["t3_post1"],
                    "fact_refs": [fact_id],
                    "lifecycle_status": "review_required",
                    "payload": case_payload,
                    "record_type": case_type,
                    "schema_version": "reddit_voc_export_governance_case_v1",
                    "source_artifact": case_source,
                }
            ],
        }

    def build(self) -> str:
        write_export_bundle(self.output, self.rows, self.metadata)
        return sha256_bytes((self.output / "manifest.json").read_bytes())


class RedditVocExportBundleTests(unittest.TestCase):
    def test_builder_writes_exact_atomic_private_member_set_and_safe_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            manifest_sha = fixture.build()
            self.assertEqual(len(manifest_sha), 64)
            self.assertEqual(stat.S_IMODE(fixture.output.stat().st_mode), 0o700)
            self.assertEqual(
                {path.name for path in fixture.output.iterdir()},
                set(ARTIFACT_FILES) | {"manifest.json"},
            )
            for path in fixture.output.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            manifest = json.loads(
                (fixture.output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertFalse(manifest["promotable"])
            self.assertEqual(
                manifest["cross_reference_counts"]["unresolved_entity_references"],
                0,
            )

    def test_builder_rejects_unresolved_entity_and_fact_references(self) -> None:
        for key, value, message in (
            ("entity_refs", ["t3_missing"], "entity"),
            ("fact_refs", ["fact:missing"], "fact"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                fixture = BundleFixture(Path(temporary))
                fixture.rows["reddit-governance-casebook.jsonl"][0][key] = value
                with self.assertRaisesRegex(ExportBundleError, message):
                    fixture.build()

    def test_public_mode_rejects_author_pseudonym_and_internal_review_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary), mode="public")
            fixture.rows["reddit-entities-full.jsonl"][0]["author_pseudonym"] = "private"
            with self.assertRaisesRegex(ExportBundleError, "denied field"):
                fixture.build()

    def test_output_is_immutable_and_input_member_set_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = BundleFixture(Path(temporary))
            fixture.build()
            with self.assertRaisesRegex(ExportBundleError, "already exists"):
                fixture.build()
            incomplete = dict(fixture.rows)
            incomplete.pop("reddit-metrics-reporting.jsonl")
            with self.assertRaisesRegex(ExportBundleError, "member set"):
                write_export_bundle(Path(temporary) / "other", incomplete, fixture.metadata)


if __name__ == "__main__":
    unittest.main()
