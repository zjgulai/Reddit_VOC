from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from tests.test_insights_dist_audit import _build_fixture, _build_v3_fixture, _write_json


ROOT = Path(__file__).resolve().parents[1]
BUILDER = (
    ROOT
    / "ref/UI/momcozy-reddit-workbench/deploy/insights/build-release.mjs"
)
DEPLOY_ROOT = BUILDER.parent


def _write_canonical(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_frontend_source_contract(
    root: Path,
    *,
    v3_lineage: dict[str, object] | None = None,
    periodic_publication: dict[str, object] | None = None,
) -> tuple[Path, Path, str]:
    candidate_input = "a" * 64
    inventory = {
        "file_count": 219,
        "inventory_sha256": "b" * 64,
        "total_bytes": 31942539,
    }
    manifest_path = root / "frontend-source-manifest.json"
    receipt_path = root / "candidate-ui-source-validation-receipt.json"
    manifest: dict[str, object] = {
        "frontend_candidate_input_sha256": candidate_input,
        "schema_version": (
            "reddit_voc_frontend_source_manifest_v2"
            if v3_lineage is not None
            else "reddit_voc_frontend_source_manifest_v1"
        ),
        "source": {"inventory": inventory},
        "status": "frontend_source_frozen_local",
    }
    if v3_lineage is not None:
        upstream = {"v3_lineage": v3_lineage}
        if periodic_publication is not None:
            upstream["periodic_report_publication"] = periodic_publication
        manifest["upstream"] = upstream
    _write_canonical(
        manifest_path,
        manifest,
    )
    receipt: dict[str, object] = {
        "frontend_candidate_input_sha256": candidate_input,
        "frontend_source_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "schema_version": (
            "reddit_voc_candidate_ui_source_validation_receipt_v2"
            if v3_lineage is not None
            else "reddit_voc_candidate_ui_source_validation_receipt_v1"
        ),
        "source_inventory": inventory,
        "status": "passed_local_source_validation",
    }
    if v3_lineage is not None:
        receipt["v3_lineage"] = v3_lineage
        receipt["upstream"] = manifest["upstream"]
        if periodic_publication is not None:
            receipt["periodic_report_publication"] = periodic_publication
    _write_canonical(
        receipt_path,
        receipt,
    )
    return manifest_path, receipt_path, candidate_input


class InsightsReleaseBundleTests(unittest.TestCase):
    def _command(
        self,
        dist: Path,
        output: Path,
        versions: dict[str, str],
        collection_status: tuple[str, str] | None = None,
        source_contract: tuple[Path, Path] | None = None,
        frontend_contract: tuple[Path, Path, str] | None = None,
    ) -> list[str]:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")
        command = [
            node,
            str(BUILDER),
            str(dist),
            str(output),
            f"fixture.invalid/nginx@sha256:{'d' * 64}",
            str(DEPLOY_ROOT),
            str(ROOT),
            "v22.0.0-fixture",
            "10.0.0-fixture",
            versions["base"],
            versions["insights"],
            versions["reports"],
            versions["personas"],
            "data/reddit-voc/current-release.json",
        ]
        command.extend(collection_status or ("false", "false"))
        package_lock, dockerignore = source_contract or (
            dist.parent / "package-lock.json",
            dist.parent / ".dockerignore",
        )
        command.extend((str(package_lock), str(dockerignore)))
        manifest, receipt, _candidate_input = frontend_contract or (
            _write_frontend_source_contract(output.parent / "frontend-source")
        )
        command.extend((str(manifest), str(receipt)))
        return command

    def test_release_manifest_binds_dynamic_v2_pointer_and_manifests(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            versions = _build_fixture(dist, generation="v2")
            _write_json(dist.parent / "package-lock.json", {"lockfileVersion": 3})
            (dist.parent / ".dockerignore").write_text("node_modules\n", encoding="utf-8")

            result = subprocess.run(
                self._command(dist, output, versions),
                check=True,
                capture_output=True,
                text=True,
            )
            release_sha = result.stdout.strip()
            manifest = json.loads(
                (output / "release-manifest.json").read_text(encoding="utf-8")
            )
            pointer = dist / "data/reddit-voc/current-release.json"
            self.assertEqual(manifest["release_sha256"], release_sha)
            self.assertEqual(manifest["schema_version"], "reddit_voc_insights_site_release_v2")
            self.assertEqual(
                manifest["build_contract_version"],
                "reddit_voc_insights_container_v6",
            )
            self.assertEqual(
                manifest["data_runtime"],
                {
                    "contract_version": "reddit_voc_data_mount_v1",
                    "mode": "read_only_versioned_mount",
                    "host_root_environment": "REDDIT_VOC_DATA_ROOT",
                    "container_root": "/srv/reddit-voc-data",
                    "current_pointer": "current",
                    "public_alias": (
                        "/srv/reddit-voc-data/current/public/data/reddit-voc/"
                    ),
                    "web_path": "/data/reddit-voc/",
                    "expected_mount_count": 1,
                    "read_only": True,
                    "atomic_pointer_switch_without_container_restart": True,
                },
            )
            self.assertEqual(manifest["dataset_versions"], versions)
            self.assertEqual(
                manifest["current_release"],
                {
                    "path": "data/reddit-voc/current-release.json",
                    "release_id": "reddit_voc_release_fixture_v2",
                    "sha256": sha256(pointer.read_bytes()).hexdigest(),
                },
            )
            self.assertFalse(manifest["authentication_enabled"])
            self.assertFalse(manifest["latest_collection_integrated"])
            self.assertFalse(manifest["latest_collection_fully_hydrated"])
            source_manifest = output.parent / "frontend-source/frontend-source-manifest.json"
            source_receipt = (
                output.parent
                / "frontend-source/candidate-ui-source-validation-receipt.json"
            )
            self.assertEqual(
                manifest["frontend_source"],
                {
                    "frontend_candidate_input_sha256": "a" * 64,
                    "manifest": {
                        "bytes": source_manifest.stat().st_size,
                        "path": "frontend/source/frontend-source-manifest.json",
                        "sha256": sha256(source_manifest.read_bytes()).hexdigest(),
                    },
                    "source_inventory": {
                        "file_count": 219,
                        "inventory_sha256": "b" * 64,
                        "total_bytes": 31942539,
                    },
                    "validation_receipt": {
                        "bytes": source_receipt.stat().st_size,
                        "path": (
                            "frontend/source/"
                            "candidate-ui-source-validation-receipt.json"
                        ),
                        "sha256": sha256(source_receipt.read_bytes()).hexdigest(),
                    },
                },
            )
            self.assertTrue(manifest["boundaries"]["collector_isolation_required"])
            self.assertTrue(manifest["boundaries"]["case_gallery_stock_preserved"])
            self.assertFalse(manifest["boundaries"]["login_required"])

    def test_release_manifest_binds_v3_source_without_legacy_plan_a_lineage(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            versions = _build_v3_fixture(dist)
            _write_json(dist.parent / "package-lock.json", {"lockfileVersion": 3})
            (dist.parent / ".dockerignore").write_text("node_modules\n", encoding="utf-8")
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            lineage = {
                "contract": "reddit_voc_v3_four_dataset_frontend_lineage_v1",
                "source_snapshot_id": "reddit_add_data_20260715_v1",
                "current_release_pointer_sha256": sha256(
                    pointer_path.read_bytes()
                ).hexdigest(),
                "datasets": {
                    key: {
                        "dataset_version": binding["dataset_version"],
                        "lineage_manifest_sha256": binding["lineage_manifest_sha256"],
                        "public_manifest_relative_path": f"public/{binding['manifest_path']}",
                        "public_manifest_sha256": binding["public_manifest_sha256"],
                        "validation_receipt_schema": f"reddit_voc_fixture_{key}_receipt_v1",
                        "validation_receipt_sha256": (
                            {
                                "base": "1",
                                "insights": "2",
                                "reports": "3",
                                "personas": "4",
                            }[key]
                            * 64
                        ),
                    }
                    for key, binding in pointer["datasets"].items()
                },
                "auxiliary_public_manifests": [],
            }
            frontend_contract = _write_frontend_source_contract(
                output.parent / "frontend-source",
                v3_lineage=lineage,
            )

            result = subprocess.run(
                self._command(
                    dist,
                    output,
                    versions,
                    frontend_contract=frontend_contract,
                ),
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(
                (output / "release-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["release_sha256"], result.stdout.strip())
            self.assertEqual(
                manifest["frontend_source"]["contract_schema_version"],
                "reddit_voc_frontend_source_manifest_v2",
            )
            self.assertEqual(manifest["frontend_source"]["v3_lineage"], lineage)
            self.assertNotIn(
                "plan_a", json.dumps(manifest["frontend_source"], sort_keys=True)
            )

    def test_release_manifest_binds_explicit_partial_collection_status(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            versions = _build_fixture(dist, generation="v2")
            _write_json(dist.parent / "package-lock.json", {"lockfileVersion": 3})
            (dist.parent / ".dockerignore").write_text("node_modules\n", encoding="utf-8")

            subprocess.run(
                self._command(
                    dist,
                    output,
                    versions,
                    collection_status=("true", "false"),
                ),
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(
                (output / "release-manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["latest_collection_integrated"])
            self.assertFalse(manifest["latest_collection_fully_hydrated"])

    def test_release_manifest_files_use_code_point_order_for_mixed_case_paths(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            versions = _build_fixture(dist, generation="v2")
            _write_json(dist.parent / "package-lock.json", {"lockfileVersion": 3})
            (dist.parent / ".dockerignore").write_text(
                "node_modules\n", encoding="utf-8"
            )
            assets = dist / "assets"
            assets.mkdir()
            for name in ("Able.js", "Zeta.js", "alpha.js", "zulu.js"):
                (assets / name).write_text(f"// {name}\n", encoding="utf-8")

            subprocess.run(
                self._command(dist, output, versions),
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(
                (output / "release-manifest.json").read_text(encoding="utf-8")
            )
            paths = [row["path"] for row in manifest["files"]]
            self.assertEqual(paths, sorted(paths))

    def test_release_manifest_binds_explicit_reviewed_build_inputs(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            reviewed = workspace / "reviewed"
            reviewed.mkdir()
            package_lock = reviewed / "package-lock.json"
            dockerignore = reviewed / ".dockerignore"
            package_lock.write_text('{"lockfileVersion":3,"reviewed":true}\n', encoding="utf-8")
            dockerignore.write_text("*\n!dist/**\n", encoding="utf-8")
            versions = _build_fixture(dist, generation="v2")

            subprocess.run(
                self._command(
                    dist,
                    output,
                    versions,
                    collection_status=("true", "false"),
                    source_contract=(package_lock, dockerignore),
                ),
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(
                (output / "release-manifest.json").read_text(encoding="utf-8")
            )
            inputs = {entry["path"]: entry for entry in manifest["build_inputs"]}
            self.assertEqual(
                inputs["package-lock.json"]["sha256"],
                sha256(package_lock.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                inputs["ref/UI/momcozy-reddit-workbench/.dockerignore"]["sha256"],
                sha256(dockerignore.read_bytes()).hexdigest(),
            )

    def test_release_builder_rejects_invalid_collection_status(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            versions = _build_fixture(dist, generation="v2")
            _write_json(dist.parent / "package-lock.json", {"lockfileVersion": 3})
            (dist.parent / ".dockerignore").write_text("node_modules\n", encoding="utf-8")

            invalid = subprocess.run(
                self._command(
                    dist,
                    output,
                    versions,
                    collection_status=("yes", "false"),
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("must be true or false", invalid.stderr)

            impossible = subprocess.run(
                self._command(
                    dist,
                    output,
                    versions,
                    collection_status=("false", "true"),
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(impossible.returncode, 0)
            self.assertIn("before it is integrated", impossible.stderr)

    def test_release_builder_rejects_symlinked_explicit_build_input(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            reviewed = workspace / "reviewed"
            reviewed.mkdir()
            real_lock = reviewed / "package-lock.real.json"
            package_lock = reviewed / "package-lock.json"
            dockerignore = reviewed / ".dockerignore"
            real_lock.write_text('{"lockfileVersion":3}\n', encoding="utf-8")
            package_lock.symlink_to(real_lock)
            dockerignore.write_text("*\n!dist/**\n", encoding="utf-8")
            versions = _build_fixture(dist, generation="v2")

            result = subprocess.run(
                self._command(
                    dist,
                    output,
                    versions,
                    collection_status=("true", "false"),
                    source_contract=(package_lock, dockerignore),
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("package lock must be a regular file", result.stderr)

    def test_release_builder_rejects_pointer_manifest_sha_mismatch(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            versions = _build_fixture(dist, generation="v2")
            _write_json(dist.parent / "package-lock.json", {"lockfileVersion": 3})
            (dist.parent / ".dockerignore").write_text("node_modules\n", encoding="utf-8")
            pointer_path = dist / "data/reddit-voc/current-release.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["datasets"]["reports"]["public_manifest_sha256"] = "f" * 64
            _write_json(pointer_path, pointer)

            result = subprocess.run(
                self._command(dist, output, versions),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "reports public manifest SHA-256 mismatch", result.stderr
            )

    def test_release_builder_rejects_frontend_receipt_lineage_mismatch(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            versions = _build_fixture(dist, generation="v2")
            _write_json(dist.parent / "package-lock.json", {"lockfileVersion": 3})
            (dist.parent / ".dockerignore").write_text(
                "node_modules\n", encoding="utf-8"
            )
            frontend_contract = _write_frontend_source_contract(
                workspace / "frontend-source"
            )
            receipt_path = frontend_contract[1]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["frontend_candidate_input_sha256"] = "c" * 64
            _write_canonical(receipt_path, receipt)

            result = subprocess.run(
                self._command(
                    dist,
                    output,
                    versions,
                    frontend_contract=frontend_contract,
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("frontend source lineage mismatch", result.stderr)

    def test_release_builder_rejects_symlinked_frontend_source_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            dist = workspace / "app/dist"
            output = workspace / "release"
            versions = _build_fixture(dist, generation="v2")
            _write_json(dist.parent / "package-lock.json", {"lockfileVersion": 3})
            (dist.parent / ".dockerignore").write_text(
                "node_modules\n", encoding="utf-8"
            )
            manifest, receipt, candidate_input = _write_frontend_source_contract(
                workspace / "frontend-source"
            )
            real_manifest = manifest.with_name("frontend-source-manifest.real.json")
            manifest.rename(real_manifest)
            manifest.symlink_to(real_manifest)

            result = subprocess.run(
                self._command(
                    dist,
                    output,
                    versions,
                    frontend_contract=(manifest, receipt, candidate_input),
                ),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "frontend source manifest must be a regular file", result.stderr
            )


if __name__ == "__main__":
    unittest.main()
