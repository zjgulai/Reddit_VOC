from __future__ import annotations

import argparse
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from scripts import build_reddit_candidate as candidate


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _write(path: Path, value: object, *, mode: int = 0o600) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))
    path.chmod(mode)
    return sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.automation = root / "tmp/reddit-voc-candidate-automation"
        self.registry = root / "output/reddit-voc-candidate-registry"
        self.plan_a_input = "a" * 64
        self.plan_b_input = "b" * 64

        self.plan_a = root / "plan-a" / self.plan_a_input
        self.plan_a.mkdir(parents=True, mode=0o700)
        self.reconciliation_sha = "c" * 64
        plan_a_manifest = {
            "schema_version": "reddit_voc_candidate_data_manifest_v1",
            "status": "candidate_data_closed",
            "candidate_input_sha256": self.plan_a_input,
            "reconciliation": {
                "path": "candidate-data-reconciliation-ledger.jsonl",
                "bytes": 1,
                "rows": 1,
                "sha256": self.reconciliation_sha,
            },
            "boundaries": dict(candidate.SAFE_BOUNDARIES),
        }
        self.plan_a_manifest = self.plan_a / "candidate-data-manifest.json"
        self.plan_a_manifest_sha = _write(self.plan_a_manifest, plan_a_manifest)
        plan_a_receipt = {
            "schema_version": "reddit_voc_candidate_data_validation_receipt_v1",
            "status": "passed",
            "candidate_input_sha256": self.plan_a_input,
            "candidate_data_manifest_sha256": self.plan_a_manifest_sha,
            "reconciliation_sha256": self.reconciliation_sha,
            "boundaries": dict(candidate.SAFE_BOUNDARIES),
        }
        self.plan_a_receipt = self.plan_a / "candidate-data-validation-receipt.json"
        self.plan_a_receipt_sha = _write(self.plan_a_receipt, plan_a_receipt)

        self.plan_b = root / "plan-b/frontend/source"
        self.plan_b.mkdir(parents=True, mode=0o700)
        upstream = {
            "plan_a_candidate_input_sha256": self.plan_a_input,
            "plan_a_candidate_data_manifest_sha256": self.plan_a_manifest_sha,
            "plan_a_independent_validation_receipt_sha256": self.plan_a_receipt_sha,
            "plan_a_reconciliation_sha256": self.reconciliation_sha,
        }
        source_manifest = {
            "schema_version": "reddit_voc_frontend_source_manifest_v1",
            "status": "frontend_source_frozen_local",
            "frontend_candidate_input_sha256": self.plan_b_input,
            "upstream": upstream,
            "boundaries": dict(candidate.SAFE_BOUNDARIES),
        }
        self.source_manifest = self.plan_b / "frontend-source-manifest.json"
        self.source_manifest_sha = _write(self.source_manifest, source_manifest)
        source_receipt = {
            "schema_version": "reddit_voc_candidate_ui_source_validation_receipt_v1",
            "status": "passed_local_source_validation",
            "frontend_candidate_input_sha256": self.plan_b_input,
            "frontend_source_manifest_sha256": self.source_manifest_sha,
            "upstream": upstream,
            "boundaries": dict(candidate.SAFE_BOUNDARIES),
        }
        self.source_receipt = self.plan_b / "candidate-ui-source-validation-receipt.json"
        self.source_receipt_sha = _write(self.source_receipt, source_receipt)

        self.build_contract = root / "build-contract.json"
        self.build_contract_sha = _write(
            self.build_contract,
            {
                "schema_version": "reddit_voc_candidate_build_contract_v1",
                "status": "frozen",
            },
            mode=0o644,
        )
        self.final_receipt = root / "final/candidate-ui-validation-receipt.json"
        self.final_value = self._final_receipt()
        self.final_receipt_sha = _write(self.final_receipt, self.final_value)

    def _final_receipt(self, *, generated_at: str = "2026-07-15T12:00:00Z") -> dict:
        return {
            "schema_version": "reddit_voc_candidate_ui_validation_receipt_v1",
            "status": "passed_local_candidate_validation",
            "generated_at_utc": generated_at,
            "expires_at_utc": "2026-07-22T12:00:00Z",
            "lineage": {
                "plan_a_candidate_input_sha256": self.plan_a_input,
                "plan_a_candidate_data_manifest_sha256": self.plan_a_manifest_sha,
                "plan_a_validation_receipt_sha256": self.plan_a_receipt_sha,
                "frontend_candidate_input_sha256": self.plan_b_input,
                "frontend_source_manifest_sha256": self.source_manifest_sha,
                "frontend_source_validation_receipt_sha256": self.source_receipt_sha,
                "build_contract_sha256": self.build_contract_sha,
            },
            "release": {
                "release_sha256": "d" * 64,
                "dist_manifest_sha256": "e" * 64,
                "release_manifest_sha256": "f" * 64,
                "release_manifest_evidence_sha256": "6" * 64,
            },
            "deliverables": {
                "image_tar_sha256": "7" * 64,
                "transfer_tgz_sha256": "8" * 64,
            },
            "evidence": {
                "browser_e2e_evidence_sha256": "1" * 64,
                "container_evidence_sha256": "2" * 64,
                "export_evidence_sha256": "3" * 64,
                "security_evidence_sha256": "4" * 64,
                "ui_validation_evidence_sha256": "5" * 64,
            },
            "boundaries": dict(candidate.SAFE_BOUNDARIES),
        }

    def args(self, *, run_id: str = "run-001") -> argparse.Namespace:
        return argparse.Namespace(
            run_id=run_id,
            plan_a_root=self.plan_a,
            expected_plan_a_input_sha256=self.plan_a_input,
            expected_plan_a_manifest_sha256=self.plan_a_manifest_sha,
            expected_plan_a_receipt_sha256=self.plan_a_receipt_sha,
            plan_b_source_manifest=self.source_manifest,
            expected_plan_b_source_manifest_sha256=self.source_manifest_sha,
            plan_b_source_receipt=self.source_receipt,
            expected_plan_b_source_receipt_sha256=self.source_receipt_sha,
            expected_plan_b_input_sha256=self.plan_b_input,
            build_contract=self.build_contract,
            expected_build_contract_sha256=self.build_contract_sha,
            final_receipt=self.final_receipt,
            expected_final_receipt_sha256=self.final_receipt_sha,
        )


class NativeV3Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.automation = root / "tmp/reddit-voc-candidate-automation"
        self.registry = root / "output/reddit-voc-candidate-registry"
        self.workspace = root / "native-v3"
        self.release_id = "reddit_voc_release_fixture_a1"
        self.source_snapshot_id = "reddit_add_data_fixture_v1"
        self.release_sha = "d" * 64
        self.frontend_input = "b" * 64
        self.current_release_pointer_sha = "c" * 64
        self.dataset_versions = {
            "base": "reddit_voc_base_fixture_v1",
            "insights": "reddit_voc_insights_fixture_v1",
            "reports": "reddit_voc_reports_fixture_v1",
            "personas": "reddit_voc_personas_fixture_v1",
        }
        self.dataset_manifests: dict[str, Path] = {}
        self.dataset_manifest_shas: dict[str, str] = {}
        self.dataset_receipts: dict[str, Path] = {}
        self.dataset_receipt_shas: dict[str, str] = {}
        self.dataset_lineage_shas: dict[str, str] = {}

        for name, schema in candidate.V3_DATASET_MANIFEST_SCHEMAS.items():
            manifest_path = self.workspace / f"{name}-manifest.json"
            if name == "personas":
                manifest = {
                    "schema_version": schema,
                    "status": "personas_public_manifest_materialized",
                    "snapshot_id": self.dataset_versions[name],
                    "governed_signal_source_snapshot_id": self.source_snapshot_id,
                    "promotable": True,
                    "boundaries": dict(candidate.PERSONA_BOUNDARIES),
                }
            else:
                self.dataset_lineage_shas[name] = {"base": "1", "insights": "2", "reports": "3"}[name] * 64
                manifest = {
                    "schema_version": schema,
                    "status": "public_manifest_materialized",
                    "dataset_version": self.dataset_versions[name],
                    "source_snapshot_id": self.source_snapshot_id,
                    "lineage_manifest_sha256": self.dataset_lineage_shas[name],
                    "promotable": True,
                    "boundaries": dict(candidate.SAFE_BOUNDARIES),
                }
            manifest_sha = _write(manifest_path, manifest)
            receipt_path = self.workspace / f"{name}-receipt.json"
            if name == "personas":
                self.dataset_lineage_shas[name] = manifest_sha
                receipt = {
                    "schema_version": candidate.V3_DATASET_RECEIPT_SCHEMAS[name],
                    "status": "passed",
                    "promotable": True,
                    "manifest_sha256": manifest_sha,
                    **dict(candidate.PERSONA_BOUNDARIES),
                }
            else:
                receipt = {
                    "schema_version": candidate.V3_DATASET_RECEIPT_SCHEMAS[name],
                    "status": "passed_candidate_only",
                    "promotable": True,
                    "bundle_manifest_sha256": manifest_sha,
                    "boundaries": dict(candidate.SAFE_BOUNDARIES),
                }
            receipt_sha = _write(receipt_path, receipt)
            self.dataset_manifests[name] = manifest_path
            self.dataset_manifest_shas[name] = manifest_sha
            self.dataset_receipts[name] = receipt_path
            self.dataset_receipt_shas[name] = receipt_sha

        datasets = {}
        for name in ("base", "insights", "reports", "personas"):
            public_path = f"public/data/reddit-voc/{name}/manifest.json"
            datasets[name] = {
                "dataset_version": self.dataset_versions[name],
                "public_manifest_relative_path": public_path,
                "public_manifest_sha256": self.dataset_manifest_shas[name],
                "validation_receipt_sha256": self.dataset_receipt_shas[name],
                "validation_receipt_schema": candidate.V3_DATASET_RECEIPT_SCHEMAS[name],
                "lineage_manifest_sha256": self.dataset_lineage_shas[name],
            }
        self.v3_lineage = {
            "contract": candidate.V3_FRONTEND_LINEAGE_CONTRACT,
            "source_snapshot_id": self.source_snapshot_id,
            "current_release_pointer_sha256": self.current_release_pointer_sha,
            "auxiliary_public_manifests": [],
            "datasets": datasets,
        }
        self.source_manifest = self.workspace / "frontend-source-manifest.json"
        self.source_manifest_sha = _write(
            self.source_manifest,
            {
                "schema_version": candidate.V3_FRONTEND_SOURCE_SCHEMA,
                "status": "frontend_source_frozen_local",
                "frontend_candidate_input_sha256": self.frontend_input,
                "upstream": {"v3_lineage": self.v3_lineage},
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            },
        )
        self.source_receipt = self.workspace / "frontend-source-receipt.json"
        self.source_receipt_sha = _write(
            self.source_receipt,
            {
                "schema_version": candidate.V3_FRONTEND_RECEIPT_SCHEMA,
                "status": "passed_local_source_validation",
                "frontend_candidate_input_sha256": self.frontend_input,
                "frontend_source_manifest_sha256": self.source_manifest_sha,
                "v3_lineage": self.v3_lineage,
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            },
        )
        self.stage_receipt = self.workspace / "frontend-source-stage-receipt.json"
        self.stage_receipt_sha = _write(
            self.stage_receipt,
            {
                "schema_version": candidate.V3_FRONTEND_STAGE_RECEIPT_SCHEMA,
                "status": "source_stage_materialized_local",
                "frontend_candidate_input_sha256": self.frontend_input,
                "frontend_source_manifest_sha256": self.source_manifest_sha,
                "frontend_source_manifest_schema": candidate.V3_FRONTEND_SOURCE_SCHEMA,
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            },
        )
        self.release_dataset_manifests = {
            name: {
                "manifest_path": datasets[name]["public_manifest_relative_path"].removeprefix("public/"),
                "public_manifest_sha256": datasets[name]["public_manifest_sha256"],
                "lineage_manifest_sha256": datasets[name]["lineage_manifest_sha256"],
            }
            for name in ("base", "insights", "reports", "personas")
        }
        self.frontend_source = {
            "contract_schema_version": candidate.V3_FRONTEND_SOURCE_SCHEMA,
            "frontend_candidate_input_sha256": self.frontend_input,
            "manifest": {
                "path": "frontend-source-manifest.json",
                "sha256": self.source_manifest_sha,
            },
            "validation_receipt": {
                "path": "frontend-source-receipt.json",
                "sha256": self.source_receipt_sha,
            },
            "v3_lineage": self.v3_lineage,
        }
        self.release_manifest = self.workspace / "release-manifest.json"
        self.release_manifest_sha = _write(
            self.release_manifest,
            {
                "schema_version": "reddit_voc_insights_site_release_v2",
                "release_sha256": self.release_sha,
                "current_release": {
                    "release_id": self.release_id,
                    "sha256": self.current_release_pointer_sha,
                    "path": "data/reddit-voc/current-release.json",
                },
                "dataset_versions": self.dataset_versions,
                "dataset_manifests": self.release_dataset_manifests,
                "frontend_source": self.frontend_source,
                "files": [],
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            },
            mode=0o644,
        )
        self.build_contract = self.workspace / "build-receipt.json"
        self.build_contract_sha = _write(
            self.build_contract,
            {
                "schema_version": "reddit_voc_insights_build_receipt_v1",
                "status": "passed_local_build",
                "release_sha256": self.release_sha,
                "frontend_source": self.frontend_source,
                "data_lineage": {
                    "current_release": {
                        "release_id": self.release_id,
                        "sha256": self.current_release_pointer_sha,
                        "path": "data/reddit-voc/current-release.json",
                    },
                    "dataset_manifests": self.release_dataset_manifests,
                    "dataset_versions": self.dataset_versions,
                },
                "boundaries": dict(candidate.SAFE_BOUNDARIES),
            },
            mode=0o644,
        )
        self.dist_sums = self.workspace / "dist-SHA256SUMS"
        self.dist_sums.write_text(f"{'0' * 64}  index.html\n", encoding="utf-8")
        self.dist_sums.chmod(0o644)
        self.image_tar = self.workspace / "image.tar"
        self.image_tar.write_bytes(b"native-v3-image")
        self.transfer_tgz = self.workspace / "release.tgz"
        self.transfer_tgz.write_bytes(b"native-v3-tgz")
        self.receipts: dict[str, tuple[Path, str]] = {}
        for key, schema in {
            "browser_e2e": "reddit_voc_same_dist_browser_e2e_receipt_v2",
            "export": "reddit_voc_insights_export_validation_receipt_v1",
            "container_smoke": "reddit_voc_local_insights_container_smoke_receipt_v1",
            "security": "reddit_voc_insights_security_validation_receipt_v1",
        }.items():
            status = {
                "browser_e2e": "passed_local_same_dist_browser_acceptance",
                "export": "passed_public_readonly_export_acceptance",
                "container_smoke": "passed_local_isolated_container_smoke",
                "security": "passed",
            }[key]
            path = self.workspace / f"{key}.json"
            digest = _write(
                path,
                {
                    "schema_version": schema,
                    "status": status,
                    "generated_at_utc": "2026-07-15T12:30:00Z",
                    "stable_evidence": {"check": key, "passed": True},
                    "boundaries": dict(candidate.SAFE_BOUNDARIES),
                },
            )
            self.receipts[key] = (path, digest)
        self.native_artifact_paths = {
            "v3_frontend_source_manifest": self.source_manifest,
            "v3_frontend_source_receipt": self.source_receipt,
            "v3_frontend_source_stage_receipt": self.stage_receipt,
            "v3_base_manifest": self.dataset_manifests["base"],
            "v3_base_receipt": self.dataset_receipts["base"],
            "v3_insights_manifest": self.dataset_manifests["insights"],
            "v3_insights_receipt": self.dataset_receipts["insights"],
            "v3_reports_manifest": self.dataset_manifests["reports"],
            "v3_reports_receipt": self.dataset_receipts["reports"],
            "v3_personas_manifest": self.dataset_manifests["personas"],
            "v3_personas_receipt": self.dataset_receipts["personas"],
        }
        self.native_artifact_shas = {
            "v3_frontend_source_manifest": self.source_manifest_sha,
            "v3_frontend_source_receipt": self.source_receipt_sha,
            "v3_frontend_source_stage_receipt": self.stage_receipt_sha,
            "v3_base_manifest": self.dataset_manifest_shas["base"],
            "v3_base_receipt": self.dataset_receipt_shas["base"],
            "v3_insights_manifest": self.dataset_manifest_shas["insights"],
            "v3_insights_receipt": self.dataset_receipt_shas["insights"],
            "v3_reports_manifest": self.dataset_manifest_shas["reports"],
            "v3_reports_receipt": self.dataset_receipt_shas["reports"],
            "v3_personas_manifest": self.dataset_manifest_shas["personas"],
            "v3_personas_receipt": self.dataset_receipt_shas["personas"],
        }
        self.final_receipt = self.workspace / "final/candidate-ui-validation-receipt.json"
        build_result = candidate.build_final_ui_receipt(self.finalize_args())
        self.final_receipt_sha = str(build_result["final_receipt_sha256"])

    def finalize_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            native_v3=True,
            v3_release_id=self.release_id,
            v3_source_snapshot_id=self.source_snapshot_id,
            v3_native_artifact_paths=self.native_artifact_paths,
            expected_v3_native_artifact_sha256s=self.native_artifact_shas,
            build_contract=self.build_contract,
            expected_build_contract_sha256=self.build_contract_sha,
            generated_at_utc="2026-07-15T13:00:00Z",
            expires_at_utc="2026-07-22T13:00:00Z",
            release_manifest=self.release_manifest,
            expected_release_manifest_sha256=self.release_manifest_sha,
            dist_sums=self.dist_sums,
            expected_dist_sums_sha256=sha256(self.dist_sums.read_bytes()).hexdigest(),
            image_tar=self.image_tar,
            expected_image_tar_sha256=sha256(self.image_tar.read_bytes()).hexdigest(),
            transfer_tgz=self.transfer_tgz,
            expected_transfer_tgz_sha256=sha256(self.transfer_tgz.read_bytes()).hexdigest(),
            browser_e2e_receipt=self.receipts["browser_e2e"][0],
            expected_browser_e2e_receipt_sha256=self.receipts["browser_e2e"][1],
            export_receipt=self.receipts["export"][0],
            expected_export_receipt_sha256=self.receipts["export"][1],
            container_smoke_receipt=self.receipts["container_smoke"][0],
            expected_container_smoke_receipt_sha256=self.receipts["container_smoke"][1],
            security_receipt=self.receipts["security"][0],
            expected_security_receipt_sha256=self.receipts["security"][1],
            output=self.final_receipt,
        )

    def args(self, *, run_id: str = "native-v3-run-001") -> argparse.Namespace:
        return argparse.Namespace(
            run_id=run_id,
            native_v3=True,
            v3_release_id=self.release_id,
            v3_source_snapshot_id=self.source_snapshot_id,
            v3_native_artifact_paths=self.native_artifact_paths,
            expected_v3_native_artifact_sha256s=self.native_artifact_shas,
            build_contract=self.build_contract,
            expected_build_contract_sha256=self.build_contract_sha,
            release_manifest=self.release_manifest,
            expected_release_manifest_sha256=self.release_manifest_sha,
            final_receipt=self.final_receipt,
            expected_final_receipt_sha256=self.final_receipt_sha,
        )


class BuildRedditCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_registers_exact_external_final_candidate_then_no_change(self) -> None:
        first = candidate.register_candidate(
            self.fixture.args(),
            automation_root=self.fixture.automation,
            registry_root=self.fixture.registry,
        )
        self.assertEqual(first["status"], "created")
        self.assertEqual(first["phase"], "register_only_external_final_artifacts")
        self.assertFalse(first["artifact_build_performed"])
        entry = self.fixture.registry / "entries" / f"{first['candidate_id']}.json"
        event = self.fixture.registry / "events" / f"{first['candidate_id']}.registered.json"
        run = self.fixture.registry / "runs/run-001.json"
        for path in (entry, event, run):
            self.assertTrue(path.is_file())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

        second = candidate.register_candidate(
            self.fixture.args(run_id="run-002"),
            automation_root=self.fixture.automation,
            registry_root=self.fixture.registry,
        )
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(second["candidate_id"], first["candidate_id"])

    def test_lock_is_stable_inode_nonblocking_and_never_unlinked(self) -> None:
        with candidate.candidate_lock(self.fixture.automation) as descriptor:
            lock = self.fixture.automation / "candidate-build.lock"
            before = os.fstat(descriptor)
            self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(candidate.CandidateBuildBusy):
                with candidate.candidate_lock(self.fixture.automation):
                    pass
            after = lock.stat()
            self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        self.assertTrue(lock.exists())

    def test_timestamps_do_not_enter_candidate_identity_but_evidence_does(self) -> None:
        contract = candidate.validate_registration_inputs(self.fixture.args())
        first = candidate.candidate_id(contract)
        changed_time = dict(contract)
        changed_time["generated_at_utc"] = "2030-01-01T00:00:00Z"
        self.assertEqual(candidate.candidate_id(changed_time), first)
        changed_evidence = json.loads(json.dumps(contract))
        changed_evidence["evidence"]["browser_e2e_evidence_sha256"] = "9" * 64
        self.assertNotEqual(candidate.candidate_id(changed_evidence), first)

    def test_invalid_final_boundary_writes_failed_run_only(self) -> None:
        value = self.fixture._final_receipt()
        value["boundaries"]["deploy"] = True
        self.fixture.final_receipt_sha = _write(self.fixture.final_receipt, value)
        with self.assertRaisesRegex(candidate.CandidateRegistrationError, "boundaries_invalid"):
            candidate.register_candidate(
                self.fixture.args(run_id="run-failed"),
                automation_root=self.fixture.automation,
                registry_root=self.fixture.registry,
            )
        self.assertFalse((self.fixture.registry / "entries").exists())
        self.assertFalse((self.fixture.registry / "events").exists())
        run = json.loads((self.fixture.registry / "runs/run-failed.json").read_text())
        self.assertEqual(run["status"], "failed")
        self.assertFalse(run["entry_written"])

    def test_explicit_paths_reject_symlink_and_upstream_drift(self) -> None:
        actual = self.fixture.source_manifest
        linked = actual.with_name("linked-source-manifest.json")
        linked.symlink_to(actual)
        args = self.fixture.args()
        args.plan_b_source_manifest = linked
        with self.assertRaisesRegex(candidate.CandidateRegistrationError, "unsafe"):
            candidate.validate_registration_inputs(args)

        args = self.fixture.args()
        args.expected_plan_a_manifest_sha256 = "0" * 64
        with self.assertRaisesRegex(candidate.CandidateRegistrationError, "sha256_mismatch"):
            candidate.validate_registration_inputs(args)

    def test_builds_final_receipt_from_explicit_artifacts_created_then_no_change(self) -> None:
        workspace = self.fixture.root / "finalize-inputs"
        release_manifest = workspace / "release-manifest.json"
        release_sha = "d" * 64
        release_manifest_sha = _write(
            release_manifest,
            {
                "schema_version": "reddit_voc_insights_site_release_v2",
                "release_sha256": release_sha,
                "generated_at_utc": "2026-07-15T11:00:00Z",
                "boundaries": {
                    "provider_call": False,
                    "database_write": False,
                    "live_send": False,
                    "schedule_change": False,
                    "collector_restart": False,
                    "collector_isolation_required": True,
                    "case_gallery_stock_preserved": True,
                    "login_required": False,
                },
            },
            mode=0o644,
        )
        dist_sums = workspace / "dist-SHA256SUMS"
        dist_sums.parent.mkdir(parents=True, exist_ok=True)
        dist_sums.write_text(f"{'0' * 64}  dist/index.html\n", encoding="utf-8")
        dist_sums.chmod(0o644)
        image_tar = workspace / "image.tar"
        image_tar.write_bytes(b"image-fixture")
        transfer_tgz = workspace / "release.tgz"
        transfer_tgz.write_bytes(b"tgz-fixture")

        receipts = {}
        for key, schema in {
            "browser_e2e": "reddit_voc_insights_browser_e2e_receipt_v1",
            "export": "reddit_voc_insights_export_validation_receipt_v1",
            "container_smoke": "reddit_voc_insights_container_smoke_receipt_v1",
            "security": "reddit_voc_insights_security_validation_receipt_v1",
        }.items():
            status = "passed_public_readonly_export_acceptance" if key == "export" else "passed"
            receipt = workspace / f"{key}.json"
            digest = _write(
                receipt,
                {
                    "schema_version": schema,
                    "status": status,
                    "generated_at_utc": "2026-07-15T11:30:00Z",
                    "stable_evidence": {"check": key, "passed": True},
                    "boundaries": dict(candidate.SAFE_BOUNDARIES),
                },
            )
            receipts[key] = (receipt, digest)

        output = self.fixture.root / "finalized/candidate-ui-validation-receipt.json"
        args = argparse.Namespace(
            generated_at_utc="2026-07-15T12:00:00Z",
            expires_at_utc="2026-07-22T12:00:00Z",
            expected_plan_a_input_sha256=self.fixture.plan_a_input,
            expected_plan_a_manifest_sha256=self.fixture.plan_a_manifest_sha,
            expected_plan_a_receipt_sha256=self.fixture.plan_a_receipt_sha,
            expected_plan_b_input_sha256=self.fixture.plan_b_input,
            expected_plan_b_source_manifest_sha256=self.fixture.source_manifest_sha,
            expected_plan_b_source_receipt_sha256=self.fixture.source_receipt_sha,
            expected_build_contract_sha256=self.fixture.build_contract_sha,
            release_manifest=release_manifest,
            expected_release_manifest_sha256=release_manifest_sha,
            dist_sums=dist_sums,
            expected_dist_sums_sha256=sha256(dist_sums.read_bytes()).hexdigest(),
            image_tar=image_tar,
            expected_image_tar_sha256=sha256(image_tar.read_bytes()).hexdigest(),
            transfer_tgz=transfer_tgz,
            expected_transfer_tgz_sha256=sha256(transfer_tgz.read_bytes()).hexdigest(),
            browser_e2e_receipt=receipts["browser_e2e"][0],
            expected_browser_e2e_receipt_sha256=receipts["browser_e2e"][1],
            export_receipt=receipts["export"][0],
            expected_export_receipt_sha256=receipts["export"][1],
            container_smoke_receipt=receipts["container_smoke"][0],
            expected_container_smoke_receipt_sha256=receipts["container_smoke"][1],
            security_receipt=receipts["security"][0],
            expected_security_receipt_sha256=receipts["security"][1],
            output=output,
        )
        first = candidate.build_final_ui_receipt(args)
        self.assertEqual(first["status"], "created")
        value = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(value["status"], "passed_local_candidate_validation")
        self.assertEqual(value["release"]["release_sha256"], release_sha)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(candidate.build_final_ui_receipt(args)["status"], "no_change")

    def test_native_v3_builds_final_receipt_and_registers_without_legacy_plan_a(self) -> None:
        fixture = NativeV3Fixture(self.fixture.root / "native")
        value = json.loads(fixture.final_receipt.read_text(encoding="utf-8"))
        self.assertEqual(
            value["schema_version"], "reddit_voc_candidate_ui_validation_receipt_v2"
        )
        expected_v3_lineage = {
            "artifact_sha256s": fixture.native_artifact_shas,
            "candidate_release_sha256": fixture.release_sha,
            "release_id": fixture.release_id,
            "source_snapshot_id": fixture.source_snapshot_id,
        }
        self.assertEqual(value["v3_lineage"], expected_v3_lineage)
        self.assertNotIn("plan_a_candidate_input_sha256", value["lineage"])

        first = candidate.register_candidate(
            fixture.args(),
            automation_root=fixture.automation,
            registry_root=fixture.registry,
        )
        self.assertEqual(first["status"], "created")
        entry = json.loads(
            (
                fixture.registry / "entries" / f"{first['candidate_id']}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            entry["schema_version"], "reddit_voc_candidate_registry_entry_v2"
        )
        self.assertEqual(entry["v3_lineage"], expected_v3_lineage)
        self.assertIn("v3_frontend_source_stage_receipt", entry["artifacts"])
        self.assertNotIn("plan_a_candidate_data_manifest", entry["artifacts"])

        second = candidate.register_candidate(
            fixture.args(run_id="native-v3-run-002"),
            automation_root=fixture.automation,
            registry_root=fixture.registry,
        )
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(second["candidate_id"], first["candidate_id"])


if __name__ == "__main__":
    unittest.main()
