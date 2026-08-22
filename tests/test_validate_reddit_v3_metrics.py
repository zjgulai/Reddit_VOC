from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest


from reddit_voc.v3_indicators import canonical_json_bytes, load_indicator_registry
from reddit_voc.v3_periodized_metrics import build_periodized_metrics_input
from scripts.build_reddit_v3_metrics import build_metrics_documents, write_metrics_candidate
from scripts.validate_reddit_v3_metrics import (
    MetricsValidationError,
    _validate_upstream_binding,
    validate_metrics_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config/analytics/reddit-voc-indicator-registry-v1.json"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class MetricsValidatorTests(unittest.TestCase):
    @staticmethod
    def _formal_upstream() -> tuple[dict[str, object], dict[str, object]]:
        boundaries = {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        }
        manifest = {
            "boundaries": boundaries,
            "consumption_status": "blocked_pending_independent_validation",
            "independent_validation_status": "pending",
            "promotable": False,
            "schema_version": "reddit_voc_governed_signal_snapshot_v1",
            "snapshot_id": "governed-fixture",
            "source_snapshot_id": "source-fixture",
            "status": "candidate_built",
        }
        receipt = {
            "boundaries": boundaries,
            "consumption_status": "eligible_for_downstream_consumption",
            "promotable": True,
            "schema_version": "reddit_voc_governed_signal_validation_receipt_v1",
            "snapshot_manifest_sha256": "a" * 64,
            "snapshot_id": "governed-fixture",
            "source_snapshot_id": "source-fixture",
            "status": "passed",
            "unaccounted_facts": 0,
            "unaccounted_vocs": 0,
            "validated_tables": 8,
        }
        return manifest, receipt

    def test_independent_recompute_and_semantic_tamper_rejection(self) -> None:
        registry = load_indicator_registry(REGISTRY_PATH)
        observations = [
            {
                "brand": "momcozy",
                "brand_eligible": True,
                "event_created_at_utc": None,
                "event_time_precision": "day",
                "metric_eligible": True,
                "metric_member_id": "t3_fixture",
                "product_bound": False,
                "product_problem_facts": [],
                "recommendation": "none",
                "recommendation_classification_status": "complete",
                "sentiment": None,
                "sentiment_classification_status": "unprocessed",
                "source_calendar_date": "2026-07-15",
                "voc_type": "post_voc",
            }
        ]
        periodized = build_periodized_metrics_input(
            observations=observations,
            input_bindings={
                "canonical_manifest_sha256": "c" * 64,
                "canonical_receipt_sha256": "d" * 64,
                "facts_manifest_sha256": "a" * 64,
                "governed_manifest_sha256": "a" * 64,
                "governed_receipt_sha256": "b" * 64,
                "metric_eligibility_sha256": "e" * 64,
                "vocs_sha256": "f" * 64,
            },
            dataset_id="fixture-snapshot",
            metric_policy_version=registry.registry_version,
            scope="momcozy",
            source_snapshot_id="fixture-snapshot",
        )
        input_document = {
            "atomic_facts": [],
            "context": {},
            "eligibility_rows": [],
            "observations": observations,
            "period": "2026-06",
            "periodized_metrics_input": periodized,
            "schema_version": "reddit_voc_metrics_input_v1",
            "scope": "momcozy",
            "source_facts_manifest_sha256": "a" * 64,
            "source_snapshot_id": "fixture-snapshot",
        }
        documents = build_metrics_documents(input_document, registry=registry)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate"
            write_metrics_candidate(
                output,
                documents=documents,
                input_sha256=sha256(canonical_json_bytes(input_document) + b"\n").hexdigest(),
                registry_sha256=_sha(REGISTRY_PATH),
                source_facts_validation_receipt_sha256="b" * 64,
            )
            result = validate_metrics_candidate(
                output,
                input_document=input_document,
                registry=registry,
                expected_input_sha256=sha256(
                    canonical_json_bytes(input_document) + b"\n"
                ).hexdigest(),
                expected_registry_sha256=_sha(REGISTRY_PATH),
                expected_source_facts_validation_receipt_sha256="b" * 64,
            )
            self.assertEqual(result["status"], "passed_fixture_only")
            self.assertEqual(result["indicator_count"], 26)

            metrics_path = output / "metrics.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            tampered = deepcopy(metrics)
            tampered["indicators"][0]["numerator"] = "999"
            metrics_path.write_bytes(canonical_json_bytes(tampered) + b"\n")
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["metrics.json"] = {
                "bytes": metrics_path.stat().st_size,
                "sha256": _sha(metrics_path),
            }
            manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
            with self.assertRaisesRegex(MetricsValidationError, "independent recompute"):
                validate_metrics_candidate(
                    output,
                    input_document=input_document,
                    registry=registry,
                    expected_input_sha256=sha256(
                        canonical_json_bytes(input_document) + b"\n"
                    ).hexdigest(),
                    expected_registry_sha256=_sha(REGISTRY_PATH),
                    expected_source_facts_validation_receipt_sha256="b" * 64,
                )

    def test_formal_upstream_binding_requires_consumable_receipt(self) -> None:
        from scripts.build_reddit_v3_metrics import MetricsBuildError, validate_upstream_binding

        manifest, receipt = self._formal_upstream()
        validate_upstream_binding(
            source_manifest=manifest,
            source_manifest_sha256="a" * 64,
            source_receipt=receipt,
        )
        _validate_upstream_binding(manifest, "a" * 64, receipt)

        alias_receipt = deepcopy(receipt)
        alias_receipt["consumption_status"] = "consumption_ready"
        with self.assertRaisesRegex(MetricsBuildError, "blocked upstream"):
            validate_upstream_binding(
                source_manifest=manifest,
                source_manifest_sha256="a" * 64,
                source_receipt=alias_receipt,
            )

        bool_receipt = deepcopy(receipt)
        bool_receipt["unaccounted_facts"] = False
        with self.assertRaisesRegex(MetricsValidationError, "blocked upstream"):
            _validate_upstream_binding(manifest, "a" * 64, bool_receipt)

        bad_manifest = deepcopy(manifest)
        bad_manifest["promotable"] = True
        with self.assertRaisesRegex(MetricsBuildError, "lifecycle"):
            validate_upstream_binding(
                source_manifest=bad_manifest,
                source_manifest_sha256="a" * 64,
                source_receipt=receipt,
            )


if __name__ == "__main__":
    unittest.main()
