from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reddit_voc.v3_export_bundle import (
    ARTIFACT_FILES,
    ExportBundleError,
    canonical_json_document,
    canonical_jsonl,
    write_export_bundle_from_files,
)
from reddit_voc.v3_export_materializer import (
    _entity_id_from_reference,
    _iter_large_json_array,
)
from scripts import validate_reddit_voc_export_bundle as validator
from tests.test_reddit_voc_export_bundle import BundleFixture


def _materialization(
    *, row_counts: dict[str, int], source_status_counts: dict[str, int]
) -> dict[str, object]:
    source_labels = {
        "canonical",
        "case_reference",
        "casebook",
        "current_release",
            "governed_signals",
            "integrity",
            "integrity_input",
            "metrics",
        "personas",
        "reports",
        "voc_facts",
    }
    return {
        "bundle_mode": "private_audit",
        "full_scope_filters": {
            "engagement": False,
            "manual_case": False,
            "sentiment": False,
            "severity": False,
        },
        "materialized_row_counts": row_counts,
        "materializer_code_sha256": sha256(
            (
                Path(__file__).resolve().parents[1]
                / "src/reddit_voc/v3_export_materializer.py"
            ).read_bytes()
        ).hexdigest(),
        "private_artifact": True,
        "public_distribution_allowed": False,
        "schema_version": "reddit_voc_export_materialization_v2",
        "source_bindings": {
            label: {
                "manifest_sha256": "a" * 64,
                "validation_receipt_sha256": (
                    None if label == "current_release" else "b" * 64
                ),
            }
            for label in source_labels
        },
        "source_file_contracts_verified": True,
        "source_status_counts": source_status_counts,
        "website_bundle_included": False,
    }


class RedditVocExportMaterializerTests(unittest.TestCase):
    def test_large_named_arrays_are_streamed_without_loading_the_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "periodized.json"
            payload = {
                "brand_health_rows": [{"id": "brand-1"}],
                "rows": [{"id": "metric-1"}, {"id": "metric-2"}],
                "schema_version": "fixture",
            }
            path.write_bytes(canonical_json_document(payload))
            self.assertEqual(
                list(_iter_large_json_array(path, "rows")), payload["rows"]
            )
            self.assertEqual(
                list(_iter_large_json_array(path, "brand_health_rows")),
                payload["brand_health_rows"],
            )

    def test_source_reference_mapping_is_explicit_and_fails_closed(self) -> None:
        entity_ids = {
            "t3_post1",
            "t1_comment1",
            "external_reddit_post:external1",
        }
        self.assertEqual(
            _entity_id_from_reference("post:post1", entity_ids), "t3_post1"
        )
        self.assertEqual(
            _entity_id_from_reference("comment:comment1", entity_ids),
            "t1_comment1",
        )
        self.assertEqual(
            _entity_id_from_reference("external-post:external1", entity_ids),
            "external_reddit_post:external1",
        )
        self.assertEqual(
            _entity_id_from_reference("post:external1", entity_ids),
            "external_reddit_post:external1",
        )
        with self.assertRaisesRegex(ExportBundleError, "unresolved"):
            _entity_id_from_reference("post:missing", entity_ids)

    def test_independent_validator_binds_materialization_counts_and_private_scope(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = BundleFixture(root)
            inputs = root / "inputs"
            inputs.mkdir()
            input_paths = {}
            for name in ARTIFACT_FILES:
                path = inputs / name
                path.write_bytes(canonical_jsonl(fixture.rows[name]))
                input_paths[name] = path
            materialization = _materialization(
                row_counts={
                    "reddit-entities-full.jsonl": 2,
                    "reddit-voc-facts.jsonl": 2,
                    "reddit-metrics-reporting.jsonl": 1,
                    "reddit-governance-casebook.jsonl": 1,
                },
                source_status_counts={
                    "canonical_comment_rows": 1,
                    "canonical_post_rows": 1,
                    "external_reference_rows": 0,
                    "external_snapshot_rows": 0,
                    "linked_comment_rows": 1,
                    "quarantine_rows": 0,
                    "unresolved_parent_comment_rows": 0,
                    "unresolved_parent_exclusion_rows": 0,
                    "voc_exclusion_rows": 0,
                },
            )
            write_export_bundle_from_files(
                fixture.output,
                input_paths,
                fixture.metadata,
                materialization=materialization,
            )
            manifest_path = fixture.output / "manifest.json"
            manifest_payload = manifest_path.read_bytes()
            with mock.patch.object(
                validator,
                "_validate_bound_sources",
                return_value=materialization["source_status_counts"],
            ):
                result = validator.validate_export_bundle(
                    fixture.output,
                    expected_manifest_sha256=sha256(manifest_payload).hexdigest(),
                    candidate_root=root,
                )
            self.assertTrue(result["private_artifact"])
            self.assertEqual(result["status"], "passed")

            manifest = json.loads(manifest_payload.decode("utf-8"))
            manifest["materialization"]["materialized_row_counts"][
                "reddit-entities-full.jsonl"
            ] = 3
            resigned = canonical_json_document(manifest)
            manifest_path.write_bytes(resigned)
            manifest_path.chmod(0o600)
            with mock.patch.object(
                validator,
                "_validate_bound_sources",
                return_value=materialization["source_status_counts"],
            ), self.assertRaisesRegex(
                validator.ExportBundleValidationError, "row counts"
            ):
                validator.validate_export_bundle(
                    fixture.output,
                    expected_manifest_sha256=sha256(resigned).hexdigest(),
                    candidate_root=root,
                )

    def test_signed_bundle_cannot_omit_bound_unresolved_population(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = BundleFixture(root)
            inputs = root / "inputs"
            inputs.mkdir()
            input_paths = {}
            for name in ARTIFACT_FILES:
                path = inputs / name
                path.write_bytes(canonical_jsonl(fixture.rows[name]))
                input_paths[name] = path
            bound_source_counts = {
                "canonical_comment_rows": 2,
                "canonical_post_rows": 1,
                "external_reference_rows": 0,
                "external_snapshot_rows": 0,
                "linked_comment_rows": 1,
                "quarantine_rows": 0,
                "unresolved_parent_comment_rows": 1,
                "unresolved_parent_exclusion_rows": 1,
                "voc_exclusion_rows": 1,
            }
            materialization = _materialization(
                row_counts={
                    "reddit-entities-full.jsonl": 2,
                    "reddit-voc-facts.jsonl": 2,
                    "reddit-metrics-reporting.jsonl": 1,
                    "reddit-governance-casebook.jsonl": 1,
                },
                source_status_counts=bound_source_counts,
            )
            write_export_bundle_from_files(
                fixture.output,
                input_paths,
                fixture.metadata,
                materialization=materialization,
            )
            manifest_payload = (fixture.output / "manifest.json").read_bytes()
            with mock.patch.object(
                validator,
                "_validate_bound_sources",
                return_value=bound_source_counts,
            ), self.assertRaisesRegex(
                validator.ExportBundleValidationError, "status distribution"
            ):
                validator.validate_export_bundle(
                    fixture.output,
                    expected_manifest_sha256=sha256(manifest_payload).hexdigest(),
                    candidate_root=root,
                )


if __name__ == "__main__":
    unittest.main()
