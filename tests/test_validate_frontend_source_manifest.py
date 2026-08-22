# pyright: reportMissingImports=false
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest

from scripts import build_frontend_source_manifest as builder
from scripts import validate_frontend_source_manifest as validator


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_json(path: Path, value: object, *, mode: int = 0o644) -> str:
    payload = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.chmod(path, mode)
    return sha256(payload).hexdigest()


def _contract(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}


class Fixture:
    plan_a_input = "a" * 64
    node_version = "v22.17.0"
    npm_version = "10.9.2"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "workbench"
        self.output = root / "output"
        self.output.mkdir(mode=0o700)
        self.temporary = root / "temporary"
        self._build_source()
        self._build_upstream()
        self._build_manifest()

    def _build_source(self) -> None:
        self.source.mkdir()
        for relative in validator.ROOT_SOURCE_FILES:
            path = self.source / relative
            if relative == "package-lock.json":
                self.package_lock_sha = _write_json(
                    path, {"name": "fixture", "lockfileVersion": 3, "packages": {}}
                )
            elif relative == "package.json":
                _write_json(path, {"name": "fixture", "scripts": {}})
            elif relative == ".gitignore":
                path.write_text("node_modules\ndist\n*.local\n", encoding="utf-8")
            else:
                path.write_text(f"fixture:{relative}\n", encoding="utf-8")
        (self.source / ".env.local").write_text("VITE_SECRET=excluded\n", encoding="utf-8")
        (self.source / "node_modules").mkdir()
        app = self.source / "src/App.tsx"
        app.parent.mkdir()
        route_rows = "\n".join(
            f"  {{ path: '{route}', kind: 'page', element: <div /> }},"
            for route in validator.EXPECTED_ROUTES
        )
        app.write_text(
            "export const PRODUCTION_ROUTE_DEFINITIONS = [\n"
            f"{route_rows}\n"
            "] satisfies readonly ProductionRouteDefinition[];\n",
            encoding="utf-8",
        )
        (self.source / "src/main.tsx").write_text("export {}\n", encoding="utf-8")
        public = self.source / "public"
        for name in ("favicon.svg", "icons.svg", "robots.txt"):
            path = public / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name}\n", encoding="utf-8")

        child_counts = {"base": 4, "insights": 2, "reports": 7, "personas": 4}
        self.dataset_versions: dict[str, str] = {}
        self.public_manifest_shas: dict[str, str] = {}
        self.private_manifest_shas: dict[str, str] = {}
        projection_paths: list[str] = []
        for name, child_count in child_counts.items():
            version = f"reddit_voc_{name}_fixture_v1"
            self.dataset_versions[name] = version
            directory = public / "data/reddit-voc" / version
            files: dict[str, dict[str, Any]] = {}
            for index in range(child_count):
                relative = f"payload-{index}.json"
                _write_json(directory / relative, {"dataset": name, "index": index})
                files[relative] = _contract(directory / relative)
                projection_paths.append((directory / relative).relative_to(public).as_posix())
            manifest_path = directory / "manifest.json"
            manifest_sha = _write_json(manifest_path, {"dataset": name, "files": files})
            self.public_manifest_shas[name] = manifest_sha
            self.private_manifest_shas[name] = sha256(f"private:{name}".encode()).hexdigest()
            projection_paths.append(manifest_path.relative_to(public).as_posix())

        cases_directory = public / "data/cases"
        self.cases_manifest_sha = _write_json(
            cases_directory / "manifest.v1.json", {"selected": 38, "unverified": 12}
        )
        self.cases_index_sha = _write_json(
            cases_directory / "case-index.v1.json", {"cases": []}
        )
        pointer = {
            "schema_version": validator.CURRENT_RELEASE_SCHEMA,
            "release_id": "reddit_voc_release_fixture",
            "datasets": {
                name: {
                    "dataset_version": version,
                    "manifest_path": f"data/reddit-voc/{version}/manifest.json",
                    "public_manifest_sha256": self.public_manifest_shas[name],
                    "lineage_manifest_sha256": self.private_manifest_shas[name],
                }
                for name, version in self.dataset_versions.items()
            },
            "cases": {
                "dataset_version": "case_catalog_fixture_v1",
                "manifest_path": "data/cases/manifest.v1.json",
                "public_manifest_sha256": self.cases_manifest_sha,
                "index_path": "data/cases/case-index.v1.json",
                "index_sha256": self.cases_index_sha,
                "stock_content_preserved": True,
                "approved_delta_count": 0,
            },
            "boundaries": {"login_required": False},
        }
        self.pointer_relative = "public/data/reddit-voc/current-release.json"
        self.pointer_sha = _write_json(self.source / self.pointer_relative, pointer)
        self.projection_paths = sorted(projection_paths)
        projection_rows = []
        for relative in self.projection_paths:
            row = _contract(public / relative)
            projection_rows.append({"path": relative, **row})
        inventory_text = "".join(
            f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in projection_rows
        )
        self.public_inventory = {
            "file_count": len(projection_rows),
            "total_bytes": sum(row["bytes"] for row in projection_rows),
            "inventory_sha256": sha256(inventory_text.encode()).hexdigest(),
        }
        self.includes = sorted(
            [
                *validator.ROOT_SOURCE_FILES,
                "src",
                *validator.STATIC_PUBLIC_FILES,
                "public/data/cases",
                self.pointer_relative,
                *[
                    f"public/data/reddit-voc/{version}"
                    for version in self.dataset_versions.values()
                ],
            ]
        )

    def _build_upstream(self) -> None:
        self.public_receipt = self.root / "public-validation-receipt.json"
        public_receipt = {
            "schema_version": validator.PUBLIC_RECEIPT_SCHEMA,
            "status": "passed_release_candidate",
            "public_inventory": self.public_inventory,
            "lineage": {
                name: {
                    "dataset_version": self.dataset_versions[name],
                    "private_manifest_sha256": self.private_manifest_shas[name],
                    "public_manifest_sha256": self.public_manifest_shas[name],
                }
                for name in validator.DATASET_KEYS
            },
            "cases": {
                "manifest_sha256": self.cases_manifest_sha,
                "index_sha256": self.cases_index_sha,
                "selected_count": 38,
                "unverified_count": 12,
                "approved_delta_count": 0,
            },
            "provider_call": False,
            "database_write": False,
            "remote_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
        }
        self.public_receipt_sha = _write_json(self.public_receipt, public_receipt)
        self.plan_a_root = self.root / "closure" / self.plan_a_input
        self.plan_a_root.mkdir(parents=True, mode=0o700)
        reconciliation = {
            "schema_version": "reddit_voc_candidate_data_reconciliation_v1",
            "candidate_input_sha256": self.plan_a_input,
            "boundaries": dict(builder.BOUNDARIES),
        }
        self.reconciliation_sha = _write_json(
            self.plan_a_root / "candidate-data-reconciliation-ledger.jsonl",
            reconciliation,
            mode=0o600,
        )
        plan_a_manifest = {
            "schema_version": validator.PLAN_A_MANIFEST_SCHEMA,
            "status": "candidate_data_built_local",
            "candidate_input_sha256": self.plan_a_input,
            "reconciliation": {
                "path": "candidate-data-reconciliation-ledger.jsonl",
                "sha256": self.reconciliation_sha,
            },
            "lineage": {
                "public_validation_receipt_sha256": self.public_receipt_sha,
                "public_inventory_sha256": self.public_inventory["inventory_sha256"],
            },
            "counts": {
                "public_files": self.public_inventory["file_count"],
                "public_bytes": self.public_inventory["total_bytes"],
            },
            "boundaries": dict(builder.BOUNDARIES),
        }
        self.plan_a_manifest_sha = _write_json(
            self.plan_a_root / "candidate-data-manifest.json", plan_a_manifest, mode=0o600
        )
        plan_a_receipt = {
            "schema_version": validator.PLAN_A_RECEIPT_SCHEMA,
            "status": "passed",
            "candidate_input_sha256": self.plan_a_input,
            "candidate_data_manifest_sha256": self.plan_a_manifest_sha,
            "reconciliation_sha256": self.reconciliation_sha,
            "boundaries": dict(builder.BOUNDARIES),
        }
        self.plan_a_receipt_sha = _write_json(
            self.plan_a_root / "candidate-data-validation-receipt.json",
            plan_a_receipt,
            mode=0o600,
        )

    def _build_manifest(self) -> None:
        build_args = argparse.Namespace(
            source_root=str(self.source),
            source_root_label="ref/UI/momcozy-reddit-workbench",
            include=self.includes,
            plan_a_candidate_root=str(self.plan_a_root),
            expected_plan_a_candidate_input_sha256=self.plan_a_input,
            expected_plan_a_candidate_data_manifest_sha256=self.plan_a_manifest_sha,
            expected_plan_a_reconciliation_sha256=self.reconciliation_sha,
            expected_plan_a_independent_validation_receipt_sha256=self.plan_a_receipt_sha,
            public_validation_receipt=str(self.public_receipt),
            expected_public_validation_receipt_sha256=self.public_receipt_sha,
            current_release_relative_path=self.pointer_relative,
            expected_current_release_pointer_sha256=self.pointer_sha,
            package_lock_relative_path="package-lock.json",
            expected_package_lock_sha256=self.package_lock_sha,
            node_version=self.node_version,
            npm_version=self.npm_version,
            output_root=str(self.output),
        )
        result = builder.build_frontend_source_manifest(build_args)
        self.identity = result["frontend_candidate_input_sha256"]
        self.manifest_sha = result["frontend_source_manifest_sha256"]
        self.manifest = self.output / self.identity / "frontend/source/frontend-source-manifest.json"
        self.receipt = self.manifest.parent / "candidate-ui-source-validation-receipt.json"

    def args(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "manifest": str(self.manifest),
            "expected_frontend_source_manifest_sha256": self.manifest_sha,
            "receipt": str(self.receipt),
            "source_root": str(self.source),
            "source_root_label": "ref/UI/momcozy-reddit-workbench",
            "plan_a_candidate_root": str(self.plan_a_root),
            "expected_plan_a_candidate_input_sha256": self.plan_a_input,
            "expected_plan_a_candidate_data_manifest_sha256": self.plan_a_manifest_sha,
            "expected_plan_a_reconciliation_sha256": self.reconciliation_sha,
            "expected_plan_a_independent_validation_receipt_sha256": self.plan_a_receipt_sha,
            "public_validation_receipt": str(self.public_receipt),
            "expected_public_validation_receipt_sha256": self.public_receipt_sha,
            "current_release_relative_path": self.pointer_relative,
            "expected_current_release_sha256": self.pointer_sha,
            "package_lock_relative_path": "package-lock.json",
            "expected_package_lock_sha256": self.package_lock_sha,
            "expected_node_version": self.node_version,
            "expected_npm_version": self.npm_version,
            "temporary_build_root": str(self.temporary),
            "run_commands": True,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def runner(self, *, fail: str | None = None):
        def run(
            argv: list[str],
            *,
            cwd: Path,
            env: dict[str, str],
            capture_output: bool,
            text: bool,
            check: bool,
        ) -> subprocess.CompletedProcess[str]:
            assert capture_output and text and not check
            assert cwd != self.source
            assert not (cwd / ".env.local").exists()
            assert (cwd / "node_modules").resolve(strict=True) == (
                self.source / "node_modules"
            ).resolve(strict=True)
            if argv == ["node", "--version"]:
                return subprocess.CompletedProcess(argv, 0, self.node_version + "\n", "")
            if argv == ["npm", "--version"]:
                return subprocess.CompletedProcess(argv, 0, self.npm_version + "\n", "")
            label = {
                ("npm", "test", "--", "--run"): "unit_tests",
                ("npm", "run", "lint"): "lint",
                ("npx", "tsc", "-b", "--pretty", "false"): "typecheck",
            }.get(tuple(argv), "temporary_build")
            if label == fail:
                return subprocess.CompletedProcess(argv, 1, "", "failed")
            if label == "unit_tests":
                return subprocess.CompletedProcess(
                    argv, 0, "Test Files  26 passed (26)\nTests  166 passed (166)\n", ""
                )
            if label == "lint":
                output = "".join(
                    f"src/file-{index}.tsx: warning react/only-export-components\n"
                    for index in range(5)
                )
                return subprocess.CompletedProcess(argv, 0, output, "")
            if label == "temporary_build":
                build_root = Path(env["REDDIT_VOC_BUILD_OUT_DIR"])
                build_root.mkdir()
                (build_root / "index.html").write_text("built\n", encoding="utf-8")
                staged_public = Path(env["REDDIT_VOC_BUILD_PUBLIC_DIR"])
                staged_paths = {
                    path.relative_to(staged_public).as_posix()
                    for path in staged_public.rglob("*")
                    if path.is_file()
                }
                expected_public = {
                    row["path"].removeprefix("public/")
                    for row in json.loads(self.manifest.read_text())["source"]["inventory"]["files"]
                    if row["path"].startswith("public/")
                }
                assert staged_paths == expected_public
            return subprocess.CompletedProcess(argv, 0, "", "")

        return run


class ValidateFrontendSourceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_validates_isolated_source_then_returns_no_change(self) -> None:
        fixture = self.fixture
        first = validator.validate_frontend_source_manifest(
            fixture.args(), runner=fixture.runner()
        )
        self.assertEqual(first["status"], "created")
        self.assertIs(first["promotable"], False)
        receipt = json.loads(fixture.receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], validator.RECEIPT_STATUS)
        self.assertEqual(receipt["command_evidence"]["unit_tests"]["passed_tests"], 166)
        self.assertEqual(receipt["command_evidence"]["lint"]["warning_count"], 5)
        self.assertIs(receipt["command_evidence"]["temporary_build"]["promotable"], False)
        self.assertEqual(receipt["public_projection_inventory"], fixture.public_inventory)
        self.assertEqual(receipt["boundaries"], validator.BOUNDARIES)
        before = fixture.receipt.stat().st_mtime_ns

        second = validator.validate_frontend_source_manifest(
            fixture.args(), runner=fixture.runner()
        )
        self.assertEqual(second, {**first, "status": "no_change"})
        self.assertEqual(fixture.receipt.stat().st_mtime_ns, before)

    def test_rejects_source_tamper_before_commands(self) -> None:
        fixture = self.fixture
        (fixture.source / "src/main.tsx").write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError,
            "source_inventory_file_contract_invalid",
        ):
            validator.validate_frontend_source_manifest(
                fixture.args(), runner=fixture.runner()
            )
        self.assertFalse(fixture.receipt.exists())

    def test_command_failure_writes_no_receipt(self) -> None:
        fixture = self.fixture
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError, "typecheck_failed"
        ):
            validator.validate_frontend_source_manifest(
                fixture.args(), runner=fixture.runner(fail="typecheck")
            )
        self.assertFalse(fixture.receipt.exists())

    def test_requires_real_command_gate_and_rejects_manifest_collision(self) -> None:
        fixture = self.fixture
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError,
            "frontend_command_execution_required",
        ):
            validator.validate_frontend_source_manifest(
                fixture.args(run_commands=False), runner=fixture.runner()
            )
        validator.validate_frontend_source_manifest(
            fixture.args(), runner=fixture.runner()
        )
        fixture.receipt.write_bytes(fixture.receipt.read_bytes() + b" ")
        with self.assertRaisesRegex(
            validator.FrontendSourceValidationError, "receipt_immutable_collision"
        ):
            validator.validate_frontend_source_manifest(
                fixture.args(), runner=fixture.runner()
            )


if __name__ == "__main__":
    unittest.main()
