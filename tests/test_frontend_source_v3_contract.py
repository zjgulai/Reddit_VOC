from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts import build_frontend_source_manifest as builder
from scripts import materialize_frontend_source_stage as materializer
from scripts import validate_frontend_source_manifest as validator
from scripts.build_reddit_v3_current_release import write_immutable_pointer
from tests.test_build_reddit_v3_current_release import (
    V3CurrentReleaseBuilderTests,
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class V3FrontendSourceFixture:
    node_version = "v22.17.0"
    npm_version = "10.9.2"

    def __init__(self, owner: unittest.TestCase) -> None:
        upstream = V3CurrentReleaseBuilderTests(methodName="runTest")
        upstream.setUp()
        owner.addCleanup(upstream.doCleanups)
        self.upstream = upstream
        self.root = upstream.root
        self.source = self.root / "ui"
        shutil.copytree(upstream.public_root, self.source / "public")
        pointer = upstream._build()
        self.pointer_relative = "public/data/reddit-voc/current-release.json"
        self.pointer_path = self.source / self.pointer_relative
        write_immutable_pointer(self.pointer_path, pointer)
        self.pointer_sha = _sha(self.pointer_path)

        public_validation_sidecar = (
            self.source
            / "public/data/reddit-voc"
            / upstream.versions["insights"]
            / "public/public-validation-receipt.json"
        )
        shutil.copyfile(upstream.receipts["insights"], public_validation_sidecar)
        reports_validation_sidecar = (
            self.source
            / "public/data/reddit-voc"
            / upstream.versions["reports"]
            / "public/public-validation-receipt.json"
        )
        shutil.copyfile(upstream.receipts["reports"], reports_validation_sidecar)
        self._write_source_files()
        self.output = self.root / "source-freeze"
        self.output.mkdir(mode=0o700)
        self.temporary = self.root / "validation-tmp"
        self.temporary.mkdir(mode=0o700)
        self.includes = sorted(
            [
                *validator.ROOT_SOURCE_FILES,
                "src",
                *validator.V3_STATIC_PUBLIC_FILES,
                "public/data/cases",
                self.pointer_relative,
                *[
                    f"public/data/reddit-voc/{version}"
                    for version in upstream.versions.values()
                ],
            ]
        )
        self.build_result = builder.build_frontend_source_manifest(
            self.build_args()
        )
        self.identity = self.build_result["frontend_candidate_input_sha256"]
        self.manifest = (
            self.output
            / self.identity
            / "frontend/source/frontend-source-manifest.json"
        )
        self.receipt = (
            self.manifest.parent / "candidate-ui-source-validation-receipt.json"
        )

    def _write_source_files(self) -> None:
        for relative in validator.ROOT_SOURCE_FILES:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == "package-lock.json":
                path.write_text('{"lockfileVersion":3}\n', encoding="utf-8")
            else:
                path.write_text("fixture\n", encoding="utf-8")
        app = self.source / "src/App.tsx"
        app.parent.mkdir(parents=True, exist_ok=True)
        routes = "\n".join(
            f"  {{ path: '{route}' }}," for route in validator.EXPECTED_ROUTES
        )
        app.write_text(
            "export const PRODUCTION_ROUTE_DEFINITIONS = [\n"
            f"{routes}\n"
            "] satisfies readonly ProductionRouteDefinition[];\n",
            encoding="utf-8",
        )
        for relative in validator.V3_STATIC_PUBLIC_FILES:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")
        (self.source / "node_modules").mkdir()

    def _receipt_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for name, path in self.upstream.receipts.items():
            values[f"{name}_validation_receipt"] = str(path)
            values[f"expected_{name}_validation_receipt_sha256"] = _sha(path)
        return values

    def build_args(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "source_root": str(self.source),
            "source_root_label": "tmp/v3-ui-source",
            "include": self.includes,
            "v3_lineage": True,
            "v3_auxiliary_public_manifest": [],
            "current_release_relative_path": self.pointer_relative,
            "expected_current_release_pointer_sha256": self.pointer_sha,
            "package_lock_relative_path": "package-lock.json",
            "expected_package_lock_sha256": _sha(
                self.source / "package-lock.json"
            ),
            "node_version": self.node_version,
            "npm_version": self.npm_version,
            "output_root": str(self.output),
            **self._receipt_values(),
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def validation_args(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "manifest": str(self.manifest),
            "expected_frontend_source_manifest_sha256": self.build_result[
                "frontend_source_manifest_sha256"
            ],
            "receipt": str(self.receipt),
            "source_root": str(self.source),
            "source_root_label": "tmp/v3-ui-source",
            "current_release_relative_path": self.pointer_relative,
            "expected_current_release_sha256": self.pointer_sha,
            "package_lock_relative_path": "package-lock.json",
            "expected_package_lock_sha256": _sha(
                self.source / "package-lock.json"
            ),
            "expected_node_version": self.node_version,
            "expected_npm_version": self.npm_version,
            "temporary_build_root": str(self.temporary),
            "run_commands": True,
            "v3_auxiliary_public_manifest": [],
            **self._receipt_values(),
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def runner(self):
        def run(
            argv: list[str],
            *,
            cwd: Path,
            env: dict[str, str],
            capture_output: bool,
            text: bool,
            check: bool,
        ) -> subprocess.CompletedProcess[str]:
            del capture_output, text, check
            if argv == ["node", "--version"]:
                return subprocess.CompletedProcess(argv, 0, self.node_version + "\n", "")
            if argv == ["npm", "--version"]:
                return subprocess.CompletedProcess(argv, 0, self.npm_version + "\n", "")
            if argv == ["npm", "test", "--", "--run"]:
                return subprocess.CompletedProcess(
                    argv, 0, "Test Files  1 passed (1)\nTests  1 passed (1)\n", ""
                )
            if argv == ["npm", "run", "lint"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[:3] == ["npm", "run", "build"]:
                build_root = Path(env["REDDIT_VOC_BUILD_OUT_DIR"])
                build_root.mkdir()
                (build_root / "index.html").write_text("built\n", encoding="utf-8")
            self.assert_stage(cwd)
            return subprocess.CompletedProcess(argv, 0, "", "")

        return run

    def assert_stage(self, cwd: Path) -> None:
        if not (cwd / "public/data/reddit-voc/current-release.json").is_file():
            raise AssertionError("manifest-only V3 source stage is incomplete")

    def write_quarter_auxiliary_projection(self) -> tuple[str, str, str]:
        dataset_version = "reddit_voc_quarter_insights_20260719_center_refresh_003"
        relative_root = f"public/data/reddit-voc/{dataset_version}"
        root = self.source / relative_root
        root.mkdir(parents=True)
        child = root / "quarter-insights.json"
        child.write_text(
            json.dumps(
                {
                    "dataset_version": dataset_version,
                    "period": {
                        "anchor_date": "2026-07-15",
                        "start_date": "2026-04-17",
                        "end_date": "2026-07-15",
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "reddit_voc_quarter_insights_public_manifest_v1",
                    "status": "validated_candidate",
                    "dataset_version": dataset_version,
                    "files": {
                        "quarter-insights.json": {
                            "bytes": child.stat().st_size,
                            "media_type": "application/json",
                            "sha256": _sha(child),
                        }
                    },
                    "boundaries": {
                        "production_unchanged": True,
                        "provider_call": False,
                        "database_write": False,
                        "remote_write": False,
                        "deploy": False,
                        "live_send": False,
                        "counts_are_content_entities_not_users": True,
                        "market_share_supported": False,
                        "brand_bot_attribution_confirmed": False,
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return relative_root, f"{relative_root}/manifest.json", _sha(manifest)

    def write_periodic_publication(self) -> tuple[str, str, str]:
        bundle_id = "periodic_fixture_bundle"
        relative_root = f"public/periodic-report-assets/{bundle_id}"
        root = self.source / relative_root
        assets = []
        for grain in ("daily", "weekly", "monthly"):
            poster = root / "public" / grain / "poster.png"
            poster.parent.mkdir(parents=True, exist_ok=True)
            poster.write_bytes(b"\x89PNG\r\n\x1a\n" + grain.encode("ascii"))
            public_relative = (
                f"periodic-report-assets/{bundle_id}/public/{grain}/poster.png"
            )
            assets.append(
                {
                    "grain": grain,
                    "period_id": f"fixture-{grain}",
                    "data_as_of": "2026-07-23",
                    "source_freshness_status": "fresh",
                    "relative_path": public_relative,
                    "public_url": f"https://example.test/{public_relative}",
                    "bytes": poster.stat().st_size,
                    "sha256": _sha(poster),
                    "width": 100,
                    "height": 100,
                }
            )
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": (
                        "reddit-voc-periodic-report-public-manifest-v1"
                    ),
                    "status": "publication_candidate_not_deployed",
                    "bundle_id": bundle_id,
                    "data_release_id": json.loads(
                        self.pointer_path.read_text(encoding="utf-8")
                    )["release_id"],
                    "dataset_version": "fixture-periodic-dataset",
                    "data_as_of": "2026-07-23",
                    "assets": assets,
                    "source_bundle_manifest_sha256": "1" * 64,
                    "boundaries": {
                        "public_png_only": True,
                        "private_outbox_excluded": True,
                        "destination_fingerprint_excluded": True,
                        "credential_material_excluded": True,
                        "production_unchanged": True,
                        "deploy": False,
                        "remote_write": False,
                        "live_send": False,
                        "webhook_send": False,
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        return relative_root, f"{relative_root}/manifest.json", _sha(manifest)


class V3FrontendSourceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = V3FrontendSourceFixture(self)

    def test_v3_source_manifest_and_independent_receipt_bind_four_datasets(self) -> None:
        manifest = json.loads(self.fixture.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], builder.V3_SCHEMA_VERSION)
        self.assertNotIn("plan_a", json.dumps(manifest, sort_keys=True))
        lineage = manifest["upstream"]["v3_lineage"]
        self.assertEqual(lineage["contract"], builder.V3_LINEAGE_CONTRACT)
        self.assertEqual(set(lineage["datasets"]), set(validator.DATASET_KEYS))
        self.assertNotIn(
            "public/assets/momcozy-brand-mission-v1.png",
            manifest["source"]["allowlist"],
        )

        result = validator.validate_frontend_source_manifest(
            self.fixture.validation_args(), runner=self.fixture.runner()
        )
        self.assertEqual(result["status"], "created")
        receipt = json.loads(self.fixture.receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], validator.V3_RECEIPT_SCHEMA)
        self.assertEqual(receipt["v3_lineage"], lineage)
        self.assertTrue(
            receipt["checks"]["current_release_four_datasets_and_cases_exact"]
        )
        self.assertTrue(
            receipt["checks"]["v3_four_dataset_manifest_receipt_lineage_exact"]
        )
        self.assertTrue(receipt["checks"]["v3_no_legacy_plan_a_lineage"])

    def test_v3_source_builder_rejects_receipt_substitution(self) -> None:
        with self.assertRaisesRegex(
            builder.FrontendSourceManifestError,
            "v3_base_validation_receipt_sha256_mismatch",
        ):
            builder.build_frontend_source_manifest(
                self.fixture.build_args(
                    expected_base_validation_receipt_sha256="0" * 64,
                    output_root=str(self.fixture.root / "rejected-source-freeze"),
                )
            )

    def test_v3_reports_public_validation_sidecar_is_required(self) -> None:
        sidecar = (
            self.fixture.source
            / "public/data/reddit-voc"
            / self.fixture.upstream.versions["reports"]
            / "public/public-validation-receipt.json"
        )
        sidecar.unlink()
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError,
            "v3_reports_public_receipt_sidecar_missing",
        ):
            validator.validate_frontend_source_manifest(
                self.fixture.validation_args(), runner=self.fixture.runner()
            )

    def test_builder_and_independent_validator_reject_future_generation_time(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(days=1)
        value = future.isoformat().replace("+00:00", "Z")
        with self.assertRaisesRegex(
            builder.FrontendSourceManifestError,
            "v3_current_release_generated_at_utc_future",
        ):
            builder._require_not_future_utc(
                value,
                label="v3_current_release_generated_at_utc",
            )
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError,
            "v3_current_release_generated_at_utc_future",
        ):
            validator._require_not_future_utc(
                value,
                label="v3_current_release_generated_at_utc",
            )

    def test_v3_source_manifest_materializes_without_schema_downgrade(self) -> None:
        stage = self.fixture.root / "materialized-v3-source"
        stage_receipt = self.fixture.root / "materialized-v3-source-receipt.json"
        result = materializer.materialize_source_stage(
            source_root=self.fixture.source,
            manifest_path=self.fixture.manifest,
            expected_manifest_sha256=self.fixture.build_result[
                "frontend_source_manifest_sha256"
            ],
            expected_candidate_input_sha256=self.fixture.identity,
            destination=stage,
            receipt_path=stage_receipt,
        )
        self.assertEqual(result["status"], "created")
        receipt = json.loads(stage_receipt.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["frontend_source_manifest_schema"], builder.V3_SCHEMA_VERSION
        )

    def test_quarter_auxiliary_projection_is_bound_validated_and_materialized(self) -> None:
        quarter_root, quarter_manifest, quarter_manifest_sha = (
            self.fixture.write_quarter_auxiliary_projection()
        )
        auxiliary_argument = f"{quarter_manifest}={quarter_manifest_sha}"
        build_result = builder.build_frontend_source_manifest(
            self.fixture.build_args(
                include=sorted([*self.fixture.includes, quarter_root]),
                v3_auxiliary_public_manifest=[auxiliary_argument],
            )
        )
        manifest = (
            self.fixture.output
            / build_result["frontend_candidate_input_sha256"]
            / "frontend/source/frontend-source-manifest.json"
        )
        receipt = manifest.parent / "candidate-ui-source-validation-receipt.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        lineage = payload["upstream"]["v3_lineage"]
        self.assertEqual(set(lineage["datasets"]), set(validator.DATASET_KEYS))
        self.assertEqual(
            lineage["auxiliary_public_manifests"],
            [{"relative_path": quarter_manifest, "sha256": quarter_manifest_sha}],
        )
        inventory_paths = {
            row["path"] for row in payload["source"]["inventory"]["files"]
        }
        self.assertIn(quarter_manifest, inventory_paths)
        self.assertIn(f"{quarter_root}/quarter-insights.json", inventory_paths)

        result = validator.validate_frontend_source_manifest(
            self.fixture.validation_args(
                manifest=str(manifest),
                receipt=str(receipt),
                expected_frontend_source_manifest_sha256=build_result[
                    "frontend_source_manifest_sha256"
                ],
                v3_auxiliary_public_manifest=[auxiliary_argument],
            ),
            runner=self.fixture.runner(),
        )
        self.assertEqual(result["status"], "created")

        stage = self.fixture.root / "materialized-quarter-source"
        materializer.materialize_source_stage(
            source_root=self.fixture.source,
            manifest_path=manifest,
            expected_manifest_sha256=build_result[
                "frontend_source_manifest_sha256"
            ],
            expected_candidate_input_sha256=build_result[
                "frontend_candidate_input_sha256"
            ],
            destination=stage,
            receipt_path=self.fixture.root
            / "materialized-quarter-source-receipt.json",
        )
        self.assertTrue((stage / quarter_manifest).is_file())
        self.assertTrue((stage / quarter_root / "quarter-insights.json").is_file())

    def test_quarter_auxiliary_projection_rejects_manifest_or_child_tampering(self) -> None:
        quarter_root, quarter_manifest, quarter_manifest_sha = (
            self.fixture.write_quarter_auxiliary_projection()
        )
        auxiliary_argument = f"{quarter_manifest}={quarter_manifest_sha}"
        build_result = builder.build_frontend_source_manifest(
            self.fixture.build_args(
                include=sorted([*self.fixture.includes, quarter_root]),
                v3_auxiliary_public_manifest=[auxiliary_argument],
            )
        )
        manifest = (
            self.fixture.output
            / build_result["frontend_candidate_input_sha256"]
            / "frontend/source/frontend-source-manifest.json"
        )
        receipt = manifest.parent / "candidate-ui-source-validation-receipt.json"
        validation_args = self.fixture.validation_args(
            manifest=str(manifest),
            receipt=str(receipt),
            expected_frontend_source_manifest_sha256=build_result[
                "frontend_source_manifest_sha256"
            ],
            v3_auxiliary_public_manifest=[auxiliary_argument],
        )

        quarter_child = self.fixture.source / quarter_root / "quarter-insights.json"
        original_child = quarter_child.read_bytes()
        quarter_child.write_bytes(original_child + b"tampered\n")
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError,
            "v3_auxiliary_file_contract_mismatch",
        ):
            validator.validate_frontend_source_manifest(
                validation_args, runner=self.fixture.runner()
            )
        with self.assertRaisesRegex(
            materializer.SourceStageError, "source_member_contract_mismatch"
        ):
            materializer.materialize_source_stage(
                source_root=self.fixture.source,
                manifest_path=manifest,
                expected_manifest_sha256=build_result[
                    "frontend_source_manifest_sha256"
                ],
                expected_candidate_input_sha256=build_result[
                    "frontend_candidate_input_sha256"
                ],
                destination=self.fixture.root / "rejected-quarter-stage",
                receipt_path=self.fixture.root / "rejected-quarter-stage-receipt.json",
            )

        quarter_child.write_bytes(original_child)
        quarter_manifest_path = self.fixture.source / quarter_manifest
        quarter_manifest_path.write_bytes(
            quarter_manifest_path.read_bytes() + b"\n"
        )
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError,
            "v3_auxiliary_manifest_sha256_mismatch",
        ):
            validator.validate_frontend_source_manifest(
                validation_args, runner=self.fixture.runner()
            )

    def test_quarter_auxiliary_projection_rejects_missing_child_include(self) -> None:
        _, quarter_manifest, quarter_manifest_sha = (
            self.fixture.write_quarter_auxiliary_projection()
        )
        auxiliary_argument = f"{quarter_manifest}={quarter_manifest_sha}"
        build_result = builder.build_frontend_source_manifest(
            self.fixture.build_args(
                include=sorted([*self.fixture.includes, quarter_manifest]),
                v3_auxiliary_public_manifest=[auxiliary_argument],
            )
        )
        manifest = (
            self.fixture.output
            / build_result["frontend_candidate_input_sha256"]
            / "frontend/source/frontend-source-manifest.json"
        )
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError,
            "source_allowlist_inventory_scope_invalid",
        ):
            validator.validate_frontend_source_manifest(
                self.fixture.validation_args(
                    manifest=str(manifest),
                    receipt=str(
                        manifest.parent
                        / "candidate-ui-source-validation-receipt.json"
                    ),
                    expected_frontend_source_manifest_sha256=build_result[
                        "frontend_source_manifest_sha256"
                    ],
                    v3_auxiliary_public_manifest=[auxiliary_argument],
                ),
                runner=self.fixture.runner(),
            )

    def test_periodic_publication_is_bound_validated_and_materialized(self) -> None:
        periodic_root, periodic_manifest, periodic_sha = (
            self.fixture.write_periodic_publication()
        )
        build_result = builder.build_frontend_source_manifest(
            self.fixture.build_args(
                include=sorted([*self.fixture.includes, periodic_root]),
                periodic_publication_manifest=periodic_manifest,
                expected_periodic_publication_manifest_sha256=periodic_sha,
            )
        )
        manifest = (
            self.fixture.output
            / build_result["frontend_candidate_input_sha256"]
            / "frontend/source/frontend-source-manifest.json"
        )
        receipt = manifest.parent / "candidate-ui-source-validation-receipt.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        binding = payload["upstream"]["periodic_report_publication"]
        self.assertEqual(binding["manifest_relative_path"], periodic_manifest)
        self.assertEqual(
            {asset["grain"] for asset in binding["assets"]},
            {"daily", "weekly", "monthly"},
        )

        result = validator.validate_frontend_source_manifest(
            self.fixture.validation_args(
                manifest=str(manifest),
                receipt=str(receipt),
                expected_frontend_source_manifest_sha256=build_result[
                    "frontend_source_manifest_sha256"
                ],
                periodic_publication_manifest=periodic_manifest,
                expected_periodic_publication_manifest_sha256=periodic_sha,
            ),
            runner=self.fixture.runner(),
        )
        self.assertEqual(result["status"], "created")
        receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt_payload["periodic_report_publication"], binding)
        self.assertTrue(
            receipt_payload["checks"][
                "periodic_publication_manifest_and_assets_exact"
            ]
        )

        stage = self.fixture.root / "materialized-periodic-source"
        materializer.materialize_source_stage(
            source_root=self.fixture.source,
            manifest_path=manifest,
            expected_manifest_sha256=build_result[
                "frontend_source_manifest_sha256"
            ],
            expected_candidate_input_sha256=build_result[
                "frontend_candidate_input_sha256"
            ],
            destination=stage,
            receipt_path=self.fixture.root
            / "materialized-periodic-source-receipt.json",
        )
        for grain in ("daily", "weekly", "monthly"):
            self.assertTrue(
                (
                    stage
                    / periodic_root
                    / "public"
                    / grain
                    / "poster.png"
                ).is_file()
            )

    def test_periodic_publication_rejects_asset_tampering(self) -> None:
        periodic_root, periodic_manifest, periodic_sha = (
            self.fixture.write_periodic_publication()
        )
        poster = self.fixture.source / periodic_root / "public/daily/poster.png"
        poster.write_bytes(poster.read_bytes() + b"tampered")
        with self.assertRaisesRegex(
            builder.FrontendSourceManifestError,
            "periodic_publication_asset_invalid",
        ):
            builder.build_frontend_source_manifest(
                self.fixture.build_args(
                    include=sorted([*self.fixture.includes, periodic_root]),
                    periodic_publication_manifest=periodic_manifest,
                    expected_periodic_publication_manifest_sha256=periodic_sha,
                    output_root=str(self.fixture.root / "rejected-periodic-freeze"),
                )
            )


if __name__ == "__main__":
    unittest.main()
