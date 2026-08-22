from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any
import unittest

from scripts.build_reddit_v3_current_release import (
    V3CurrentReleaseContractError,
    build_v3_current_release,
    write_immutable_pointer,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class V3CurrentReleaseBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.public_root = self.root / "public"
        self.snapshot_id = "reddit_add_data_20260715_v1"
        self.versions = {
            "base": "reddit_voc_site_snapshot_20260716_v3_abc123",
            "insights": "reddit_voc_insights_20260716_v3_def456",
            "reports": "reddit_voc_reports_20260716_v3_def456",
            "personas": "reddit_voc_personas_20260716_candidate_a4",
        }
        self.receipts: dict[str, Path] = {}
        self._write_datasets()
        self._write_cases()

    def _manifest_path(self, key: str) -> Path:
        version = self.versions[key]
        suffix = "manifest-public.json" if key == "base" else "manifest.json"
        if key in {"insights", "reports"}:
            return self.public_root / "data/reddit-voc" / version / "public" / suffix
        return self.public_root / "data/reddit-voc" / version / suffix

    def _write_data_file(self, key: str, relative_path: str, value: object) -> dict[str, object]:
        manifest_path = self._manifest_path(key)
        path = manifest_path.parent / relative_path
        _write(path, value)
        return {"bytes": path.stat().st_size, "sha256": _sha(path)}

    def _write_receipt(self, key: str, manifest_path: Path) -> None:
        receipt = self.root / "receipts" / f"{key}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        boundaries = {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        }
        if key == "base":
            value: dict[str, object] = {
                "schema_version": "reddit_voc_base_public_validation_receipt_v1",
                "status": "passed_candidate_only",
                "promotable": True,
                "privacy_safe_projection": True,
                "bundle_manifest_sha256": _sha(manifest_path),
                "public_manifest_sha256": _sha(manifest_path),
                "dataset_version": manifest["dataset_version"],
                "source_snapshot_id": self.snapshot_id,
                "canonical_manifest_sha256": manifest["lineage_manifest_sha256"],
                "canonical_validation_receipt_sha256": manifest["inputs"]["canonical_validation_receipt_sha256"],
                "checks": {"deterministic_full_byte_replay": True},
                "all_checks_passed": True,
                "boundaries": boundaries,
                "comparison_contract_proven": manifest["comparison_contract_proven"],
                "comparison_contract_basis": manifest["comparison_contract_basis"],
                "completeness_percent": manifest["completeness_percent"],
                "coverage_attestation": manifest["coverage_attestation"],
                "data_owner_coverage_attestation_sha256": manifest[
                    "data_owner_coverage_attestation_sha256"
                ],
            }
        elif key in {"insights", "reports"}:
            value = {
                "schema_version": f"reddit_voc_{key}_public_validation_receipt_v3",
                "status": "passed_candidate_only",
                "promotable": True,
                "privacy_safe_projection": True,
                "bundle_manifest_sha256": _sha(manifest_path),
                "lineage_manifest_sha256": manifest["lineage_manifest_sha256"],
                "validation_receipt_sha256": manifest["validation_receipt_sha256"],
                "deterministic_full_byte_replay": True,
                "boundaries": boundaries,
                "comparison_contract_proven": manifest["comparison_contract_proven"],
                "comparison_contract_basis": manifest["comparison_contract_basis"],
                "completeness_percent": manifest["completeness_percent"],
                "data_owner_coverage_attestation_sha256": manifest[
                    "data_owner_coverage_attestation_sha256"
                ],
            }
            if key == "reports":
                value.update(
                    {
                        "report_count": manifest["report_count"],
                        "history_report_count": manifest["history_report_count"],
                        "business_entry_count": manifest["business_entry_count"],
                    }
                )
        else:
            value = {
                "schema_version": "reddit_voc_personas_validation_v3",
                "status": "passed",
                "promotable": True,
                "manifest_sha256": _sha(manifest_path),
                "snapshot_id": manifest["snapshot_id"],
                "consumption_status": "eligible_for_downstream_consumption",
                "checks": {"deterministic_full_byte_replay": True},
                **boundaries,
            }
        _write(receipt, value)
        self.receipts[key] = receipt
        if key == "insights":
            _write(
                self._manifest_path(key).parent / "public-validation-receipt.json",
                value,
            )

    def _write_datasets(self) -> None:
        lineage = "a" * 64
        boundaries = {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        }
        base_files = {
            path: self._write_data_file("base", path, {"rows": []})
            for path in (
                "aggregates-public.json",
                "posts-public.json",
                "comments-public.json",
                "tag-dictionary-public.json",
            )
        }
        base = {
            "schema_version": "reddit_voc_site_snapshot_manifest_v3",
            "dataset_version": self.versions["base"],
            "source_snapshot_id": self.snapshot_id,
            "status": "validated_candidate",
            "promotable": True,
            "privacy_safe_projection": True,
            "completeness_percent": 100,
            "completeness_basis": "data_owner_declaration",
            "comparison_contract_proven": True,
            "comparison_contract_basis": "owner_attested_dataset_scope_window",
            "comparison_unavailable_reason_codes": [],
            "coverage_attestation": {
                "attestation_basis": "data_owner_declaration",
                "completeness_percent": 100,
                "evidence_class": "owner_attested_not_crawler_proof",
                "source_snapshot_id": self.snapshot_id,
            },
            "data_owner_coverage_attestation_sha256": "e" * 64,
            "consumption_status": "eligible_for_current_release_candidate_binding",
            "lineage_manifest_sha256": lineage,
            "inputs": {
                "canonical_dataset_id": "reddit_add_data_20260715_v1_canonical_v1",
                "canonical_manifest_sha256": lineage,
                "canonical_validation_receipt_sha256": "d" * 64,
                "tag_dictionary_sha256": "f" * 64,
            },
            "files": base_files,
            "boundaries": boundaries,
        }
        _write(self._manifest_path("base"), base)
        self._write_receipt("base", self._manifest_path("base"))

        for key in ("insights", "reports"):
            data_names = (
                ("insights.json",)
                if key == "insights"
                else (
                    "report-index.json",
                    "current/daily.json",
                    "current/weekly.json",
                    "current/monthly.json",
                    "archive/daily.json",
                    "archive/weekly.json",
                    "archive/monthly.json",
                )
            )
            files = {
                name: self._write_data_file(key, name, {"schema_version": f"fixture_{key}"})
                for name in data_names
            }
            if key == "reports":
                history_reports: dict[str, list[dict[str, object]]] = {
                    "daily": [],
                    "weekly": [],
                    "monthly": [],
                }
                for grain, count in {"daily": 14, "weekly": 12, "monthly": 12}.items():
                    for position in range(count):
                        relative_path = f"history/{grain}/{position:02d}.json"
                        integrity = self._write_data_file(
                            key,
                            relative_path,
                            {"schema_version": "fixture_reports", "position": position},
                        )
                        files[relative_path] = integrity
                        history_reports[grain].append(
                            {
                                "artifact_path": relative_path,
                                "artifact_sha256": integrity["sha256"],
                            }
                        )
                history_index = {
                    "schema_version": "reddit_voc_business_history_index_v1",
                    "dataset_version": self.versions["reports"],
                    "limits": {"daily": 14, "weekly": 12, "monthly": 12},
                    "history_entry_count": 38,
                    "total_business_entry_count": 41,
                    "reports": history_reports,
                }
                files["business-history-index.json"] = self._write_data_file(
                    key,
                    "business-history-index.json",
                    history_index,
                )
            embedded = self._write_data_file(key, "validation-receipt.json", {"status": "passed_candidate_only"})
            files["validation-receipt.json"] = embedded
            manifest = {
                "schema_version": f"reddit_voc_{key}_public_manifest_v3",
                "dataset_version": self.versions[key],
                "source_snapshot_id": self.snapshot_id,
                "status": "validated_candidate",
                "promotable": True,
                "privacy_safe_projection": True,
                "consumption_status": "eligible_for_frontend_candidate_consumption",
                "fixture_only": False,
                "independent_validation_status": "passed",
                "comparison_contract_proven": True,
                "comparison_contract_basis": "owner_attested_dataset_scope_window",
                "comparison_unavailable_reason_codes": [],
                "completeness_percent": 100,
                "coverage_attestation": {
                    "attestation_basis": "data_owner_declaration",
                    "completeness_percent": 100,
                    "evidence_class": "owner_attested_not_crawler_proof",
                    "source_snapshot_id": self.snapshot_id,
                },
                "data_owner_coverage_attestation_sha256": "e" * 64,
                "lineage_manifest_sha256": ("b" if key == "insights" else "c") * 64,
                "validation_receipt_sha256": embedded["sha256"],
                "files": files,
                "boundaries": boundaries,
            }
            if key == "reports":
                manifest.update(
                    {
                        "report_count": 44,
                        "history_report_count": 38,
                        "business_entry_count": 41,
                    }
                )
            _write(self._manifest_path(key), manifest)
            self._write_receipt(key, self._manifest_path(key))

        persona_paths = (
            "personas.json",
            "persona-tags.json",
            "persona-atomic-catalog.json",
            "persona-atomic-facts.jsonl",
            "persona-cohort-bridge.json",
            "assets/persona-competitor-comparer.svg",
            "assets/persona-explicit-advocate.svg",
            "assets/persona-fallback-neutral.svg",
            "assets/persona-fit-output-optimizer.svg",
            "assets/persona-operations-troubleshooter.svg",
            "assets/persona-product-evaluator.svg",
            "assets/persona-purchase-decision.svg",
            "assets/persona-service-support-seeker.svg",
            "assets/persona-work-scenario.svg",
        )
        persona_files = {
            path: self._write_data_file("personas", path, {"fixture": path})
            for path in persona_paths
        }
        personas = {
            "schema_version": "reddit_voc_personas_manifest_v3",
            "snapshot_id": self.versions["personas"],
            "governed_signal_source_snapshot_id": self.snapshot_id,
            "status": "candidate_built",
            "consumption_status": "eligible_for_downstream_consumption",
            "promotable": True,
            "upstream": {
                "consumption_status": "eligible_for_downstream_consumption",
                "promotable": True,
            },
            "files": persona_files,
            "boundaries": {
                **boundaries,
                "counts_are_content_entities_not_users": True,
                "author_level_personas": False,
                "real_user_images": False,
            },
        }
        _write(self._manifest_path("personas"), personas)
        self._write_receipt("personas", self._manifest_path("personas"))

    def _write_cases(self, *, seed: int = 38, legacy: int = 12) -> None:
        index = self.public_root / "data/cases/case-index.v1.json"
        _write(index, {"datasetVersion": "case_catalog_20260716_v1", "approvedDelta": []})
        _write(
            self.public_root / "data/cases/manifest.v1.json",
            {
                "datasetVersion": "case_catalog_20260716_v1",
                "seed": {"count": seed},
                "legacyUnverified": {"count": legacy},
                "approvedDelta": {"count": 0},
                "index": {"path": "/data/cases/case-index.v1.json", "sha256": _sha(index)},
            },
        )

    def _set_unattested_contract(self, *keys: str) -> None:
        reason = [
            "historical_collection_coverage_not_owner_attested_complete"
        ]
        for key in keys:
            path = self._manifest_path(key)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest.update(
                {
                    "comparison_contract_proven": False,
                    "comparison_contract_basis": "not_owner_attested",
                    "comparison_unavailable_reason_codes": reason,
                    "completeness_percent": None,
                    "coverage_attestation": None,
                    "data_owner_coverage_attestation_sha256": None,
                }
            )
            if key == "base":
                manifest["completeness_basis"] = "not_owner_attested"
            if key == "reports":
                reports_root = path.parent
                history_root = reports_root / "history"
                shutil.rmtree(history_root)
                for relative in list(manifest["files"]):
                    if relative.startswith("history/"):
                        del manifest["files"][relative]
                history_index_path = reports_root / "business-history-index.json"
                history_index = json.loads(
                    history_index_path.read_text(encoding="utf-8")
                )
                history_index.update(
                    {
                        "history_entry_count": 0,
                        "total_business_entry_count": 3,
                        "reports": {
                            "daily": [],
                            "weekly": [],
                            "monthly": [],
                        },
                    }
                )
                _write(history_index_path, history_index)
                manifest["files"]["business-history-index.json"] = {
                    "bytes": history_index_path.stat().st_size,
                    "sha256": _sha(history_index_path),
                }
                manifest.update(
                    {
                        "report_count": 6,
                        "history_report_count": 0,
                        "business_entry_count": 3,
                    }
                )
            _write(path, manifest)
            self._write_receipt(key, path)

    def _build(self) -> dict[str, Any]:
        return build_v3_current_release(
            public_root=self.public_root,
            base_validation_receipt=self.receipts["base"],
            insights_validation_receipt=self.receipts["insights"],
            reports_validation_receipt=self.receipts["reports"],
            personas_validation_receipt=self.receipts["personas"],
            release_id="reddit_voc_release_20260716_v3_abc123",
            generated_at_utc="2026-07-16T08:00:00Z",
            versions=self.versions,
        )

    def test_builds_v1_pointer_from_one_complete_v3_snapshot(self) -> None:
        base_manifest = json.loads(self._manifest_path("base").read_text(encoding="utf-8"))
        self.assertNotIn("validation_receipt_sha256", base_manifest)
        self.assertEqual(
            base_manifest["inputs"]["canonical_validation_receipt_sha256"],
            "d" * 64,
        )
        pointer = self._build()
        self.assertEqual(pointer["schema_version"], "reddit_voc_current_release_v1")
        self.assertEqual(pointer["datasets"]["personas"]["dataset_version"], self.versions["personas"])
        self.assertEqual(pointer["cases"]["approved_delta_count"], 0)
        self.assertEqual(
            set(pointer),
            {"schema_version", "release_id", "generated_at_utc", "datasets", "cases", "boundaries"},
        )
        self.assertEqual(set(pointer["datasets"]), {"base", "insights", "reports", "personas"})
        for key, binding in pointer["datasets"].items():
            self.assertEqual(
                set(binding),
                {"dataset_version", "manifest_path", "public_manifest_sha256", "lineage_manifest_sha256"},
                key,
            )
        self.assertEqual(
            set(pointer["cases"]),
            {
                "dataset_version",
                "manifest_path",
                "public_manifest_sha256",
                "index_path",
                "index_sha256",
                "stock_content_preserved",
                "approved_delta_count",
            },
        )
        self.assertEqual(
            set(pointer["boundaries"]),
            {"case_gallery_stock_preserved", "collector_isolation_required", "login_required"},
        )
        self.assertFalse((self.public_root / "data/reddit-voc/current-release.json").exists())

    def test_builds_v1_pointer_for_coordinated_unattested_snapshot(self) -> None:
        self._set_unattested_contract("base", "insights", "reports")
        pointer = self._build()
        self.assertEqual(pointer["schema_version"], "reddit_voc_current_release_v1")

    def test_rejects_mixed_attested_and_unattested_snapshot(self) -> None:
        self._set_unattested_contract("insights", "reports")
        with self.assertRaisesRegex(
            V3CurrentReleaseContractError,
            "coordinated_coverage_contract_mismatch",
        ):
            self._build()

    def test_rejects_source_snapshot_drift(self) -> None:
        path = self._manifest_path("reports")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["source_snapshot_id"] = "different_snapshot"
        value["coverage_attestation"]["source_snapshot_id"] = "different_snapshot"
        _write(path, value)
        self._write_receipt("reports", path)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "source_snapshot_mismatch"):
            self._build()

    def test_rejects_completeness_below_owner_attested_100(self) -> None:
        path = self._manifest_path("insights")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["completeness_percent"] = 99
        _write(path, value)
        self._write_receipt("insights", path)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "insights_comparison_contract_invalid"):
            self._build()

    def test_rejects_receipt_bound_to_other_manifest(self) -> None:
        receipt = json.loads(self.receipts["personas"].read_text(encoding="utf-8"))
        receipt["manifest_sha256"] = "0" * 64
        _write(self.receipts["personas"], receipt)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "personas_validation_receipt_manifest_mismatch"):
            self._build()

    def test_rejects_case_stock_change(self) -> None:
        self._write_cases(seed=37)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "cases_stock_content_changed"):
            self._build()

    def test_rejects_legacy_case_stock_change(self) -> None:
        self._write_cases(legacy=11)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "cases_stock_content_changed"):
            self._build()

    def test_rejects_blocked_frontend_consumption_status(self) -> None:
        path = self._manifest_path("reports")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["consumption_status"] = "blocked_pending_independent_validation"
        _write(path, value)
        self._write_receipt("reports", path)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "reports_consumption_status_invalid"):
            self._build()

    def test_rejects_external_receipt_lineage_drift(self) -> None:
        receipt_path = self.receipts["insights"]
        value = json.loads(receipt_path.read_text(encoding="utf-8"))
        value["lineage_manifest_sha256"] = "0" * 64
        _write(receipt_path, value)
        _write(
            self._manifest_path("insights").parent
            / "public-validation-receipt.json",
            value,
        )
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "insights_validation_receipt_lineage_invalid"):
            self._build()

    def test_rejects_missing_insights_public_validation_sidecar(self) -> None:
        (
            self._manifest_path("insights").parent
            / "public-validation-receipt.json"
        ).unlink()
        with self.assertRaisesRegex(
            V3CurrentReleaseContractError,
            "insights_validation_sidecar_mismatch",
        ):
            self._build()

    def test_rejects_embedded_receipt_binding_drift(self) -> None:
        path = self._manifest_path("insights")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["validation_receipt_sha256"] = "0" * 64
        _write(path, value)
        self._write_receipt("insights", path)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "insights_embedded_receipt_binding_invalid"):
            self._build()

    def test_rejects_static_side_effect_overclaim(self) -> None:
        path = self._manifest_path("base")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["boundaries"]["provider_call"] = True
        _write(path, value)
        self._write_receipt("base", path)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "base_provider_call_boundary_invalid"):
            self._build()

    def test_rejects_undeclared_nested_report_file(self) -> None:
        reports_root = self._manifest_path("reports").parent
        _write(reports_root / "history/daily/undeclared.json", {"private": True})

        with self.assertRaisesRegex(
            V3CurrentReleaseContractError,
            "reports_directory_inventory_mismatch",
        ):
            self._build()

    def test_rejects_declared_files_below_symlink_parent(self) -> None:
        reports_root = self._manifest_path("reports").parent
        daily = reports_root / "history/daily"
        outside = self.root / "outside-history-daily"
        shutil.copytree(daily, outside)
        shutil.rmtree(daily)
        daily.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(
            V3CurrentReleaseContractError,
            "reports_(?:file|directory_inventory)_unsafe",
        ):
            self._build()

    def test_rejects_persona_upstream_not_promotable(self) -> None:
        path = self._manifest_path("personas")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["upstream"]["promotable"] = False
        _write(path, value)
        self._write_receipt("personas", path)
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "personas_validation_receipt_lineage_invalid"):
            self._build()

    def test_pointer_write_is_immutable_and_idempotent(self) -> None:
        output = self.root / "candidate/current-release.json"
        value = self._build()
        self.assertEqual(write_immutable_pointer(output, value), "created")
        self.assertEqual(write_immutable_pointer(output, value), "no_change")
        changed = dict(value)
        changed["release_id"] = "reddit_voc_release_20260716_v3_changed"
        with self.assertRaisesRegex(V3CurrentReleaseContractError, "pointer_immutable_collision"):
            write_immutable_pointer(output, changed)


if __name__ == "__main__":
    unittest.main()
