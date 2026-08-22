from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from scripts import build_frontend_source_manifest as builder


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> str:
    payload = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256(payload).hexdigest()


class Fixture:
    plan_a_input = "a" * 64

    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "workbench"
        self.output = root / "output"
        self.output.mkdir(mode=0o700)
        self._build_source()
        self._build_upstream()

    def _build_source(self) -> None:
        (self.source / "src/nested").mkdir(parents=True)
        (self.source / "src/main.tsx").write_text("export {}\n", encoding="utf-8")
        (self.source / "src/nested/view.tsx").write_text(
            "export const view = 1\n", encoding="utf-8"
        )
        (self.source / ".env.local").write_text("SECRET=not-selected\n", encoding="utf-8")
        (self.source / "package.json").write_text('{}\n', encoding="utf-8")
        self.package_lock_sha = _write_json(
            self.source / "package-lock.json",
            {"name": "fixture", "lockfileVersion": 3, "packages": {}},
        )
        public = self.source / "public"
        contracts: dict[str, str] = {}
        for name in ("base", "insights", "reports", "personas"):
            path = public / f"data/reddit-voc/{name}/manifest.json"
            contracts[name] = _write_json(path, {"dataset": name})
        cases_manifest = public / "data/cases/manifest.v1.json"
        cases_index = public / "data/cases/case-index.v1.json"
        cases_manifest_sha = _write_json(cases_manifest, {"cases": 38})
        cases_index_sha = _write_json(cases_index, {"cases": []})
        pointer = {
            "schema_version": "reddit_voc_current_release_v1",
            "release_id": "reddit_voc_release_fixture",
            "datasets": {
                name: {
                    "dataset_version": f"{name}-v1",
                    "manifest_path": f"data/reddit-voc/{name}/manifest.json",
                    "public_manifest_sha256": digest,
                    "lineage_manifest_sha256": "f" * 64,
                }
                for name, digest in contracts.items()
            },
            "cases": {
                "manifest_path": "data/cases/manifest.v1.json",
                "manifest_sha256": cases_manifest_sha,
                "public_manifest_sha256": cases_manifest_sha,
                "index_path": "data/cases/case-index.v1.json",
                "index_sha256": cases_index_sha,
            },
            "boundaries": {"login_required": False},
        }
        self.pointer_sha = _write_json(
            public / "data/reddit-voc/current-release.json", pointer
        )
        self.includes = [
            "package.json",
            "package-lock.json",
            "src",
            "public/data/cases",
            "public/data/reddit-voc/current-release.json",
            *[f"public/data/reddit-voc/{name}" for name in contracts],
        ]

    def _build_upstream(self) -> None:
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
        )
        manifest = {
            "schema_version": "reddit_voc_candidate_data_manifest_v1",
            "status": "candidate_data_built_local",
            "candidate_input_sha256": self.plan_a_input,
            "reconciliation": {
                "path": "candidate-data-reconciliation-ledger.jsonl",
                "sha256": self.reconciliation_sha,
            },
            "boundaries": dict(builder.BOUNDARIES),
        }
        self.plan_a_manifest_sha = _write_json(
            self.plan_a_root / "candidate-data-manifest.json", manifest
        )
        receipt = {
            "schema_version": "reddit_voc_candidate_data_validation_receipt_v1",
            "status": "passed",
            "candidate_input_sha256": self.plan_a_input,
            "candidate_data_manifest_sha256": self.plan_a_manifest_sha,
            "reconciliation_sha256": self.reconciliation_sha,
            "boundaries": dict(builder.BOUNDARIES),
        }
        self.plan_a_receipt_sha = _write_json(
            self.plan_a_root / "candidate-data-validation-receipt.json", receipt
        )
        self.public_receipt = self.root / "public-validation-receipt.json"
        self.public_receipt_sha = _write_json(
            self.public_receipt,
            {
                "schema_version": "reddit_voc_public_projection_validation_v1",
                "status": "passed_release_candidate",
                "provider_call": False,
                "database_write": False,
                "remote_write": False,
                "deploy": False,
                "live_send": False,
                "production_unchanged": True,
            },
        )

    def args(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "source_root": str(self.source),
            "source_root_label": "ref/UI/momcozy-reddit-workbench",
            "include": list(self.includes),
            "plan_a_candidate_root": str(self.plan_a_root),
            "expected_plan_a_candidate_input_sha256": self.plan_a_input,
            "expected_plan_a_candidate_data_manifest_sha256": self.plan_a_manifest_sha,
            "expected_plan_a_reconciliation_sha256": self.reconciliation_sha,
            "expected_plan_a_independent_validation_receipt_sha256": self.plan_a_receipt_sha,
            "public_validation_receipt": str(self.public_receipt),
            "expected_public_validation_receipt_sha256": self.public_receipt_sha,
            "current_release_relative_path": "public/data/reddit-voc/current-release.json",
            "expected_current_release_pointer_sha256": self.pointer_sha,
            "package_lock_relative_path": "package-lock.json",
            "expected_package_lock_sha256": self.package_lock_sha,
            "node_version": "v22.17.0",
            "npm_version": "10.9.2",
            "output_root": str(self.output),
        }
        values.update(overrides)
        return argparse.Namespace(**values)


class BuildFrontendSourceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_builds_recursive_explicit_inventory_then_returns_no_change(self) -> None:
        first = builder.build_frontend_source_manifest(self.fixture.args())
        self.assertEqual(first["status"], "created")
        candidate = self.fixture.output / first["frontend_candidate_input_sha256"]
        manifest_path = candidate / "frontend/source/frontend-source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = [row["path"] for row in manifest["source"]["inventory"]["files"]]
        self.assertIn("src/nested/view.tsx", paths)
        self.assertNotIn(".env.local", paths)
        self.assertEqual(manifest["source"]["allowlist"], sorted(self.fixture.includes))
        self.assertEqual(manifest["boundaries"], builder.BOUNDARIES)
        self.assertEqual(candidate.stat().st_mode & 0o777, 0o700)
        self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o600)
        before = manifest_path.stat().st_mtime_ns

        second = builder.build_frontend_source_manifest(self.fixture.args())
        self.assertEqual(second, {**first, "status": "no_change"})
        self.assertEqual(manifest_path.stat().st_mtime_ns, before)

    def test_rejects_traversal_duplicate_overlap_symlink_and_special(self) -> None:
        with self.assertRaisesRegex(builder.FrontendSourceManifestError, "path_invalid"):
            builder.build_frontend_source_manifest(
                self.fixture.args(include=["../package.json"])
            )
        with self.assertRaisesRegex(builder.FrontendSourceManifestError, "allowlist_duplicate"):
            builder.build_frontend_source_manifest(
                self.fixture.args(include=["package.json", "package.json"])
            )
        with self.assertRaisesRegex(builder.FrontendSourceManifestError, "allowlist_overlap"):
            builder.build_frontend_source_manifest(
                self.fixture.args(include=["src", "src/main.tsx"])
            )

        outside = self.fixture.root / "outside.tsx"
        outside.write_text("secret\n", encoding="utf-8")
        (self.fixture.source / "src/link.tsx").symlink_to(outside)
        with self.assertRaisesRegex(builder.FrontendSourceManifestError, "member_unsafe"):
            builder.build_frontend_source_manifest(self.fixture.args())
        (self.fixture.source / "src/link.tsx").unlink()

        fifo = self.fixture.source / "src/pipe.tsx"
        os.mkfifo(fifo)
        self.addCleanup(lambda: fifo.exists() and fifo.unlink())
        self.assertTrue(stat.S_ISFIFO(os.lstat(fifo).st_mode))
        with self.assertRaisesRegex(builder.FrontendSourceManifestError, "member_unsafe"):
            builder.build_frontend_source_manifest(self.fixture.args())

    def test_requires_exact_upstream_pointer_lock_and_selected_pointer_targets(self) -> None:
        with self.assertRaisesRegex(builder.FrontendSourceManifestError, "sha256_mismatch"):
            builder.build_frontend_source_manifest(
                self.fixture.args(expected_package_lock_sha256="0" * 64)
            )
        with self.assertRaisesRegex(builder.FrontendSourceManifestError, "sha256_mismatch"):
            builder.build_frontend_source_manifest(
                self.fixture.args(expected_plan_a_candidate_data_manifest_sha256="0" * 64)
            )
        includes = [
            item
            for item in self.fixture.includes
            if item != "public/data/reddit-voc/reports"
        ]
        with self.assertRaisesRegex(
            builder.FrontendSourceManifestError, "current_release_target_missing"
        ):
            builder.build_frontend_source_manifest(self.fixture.args(include=includes))

    def test_existing_identity_with_different_manifest_is_collision(self) -> None:
        result = builder.build_frontend_source_manifest(self.fixture.args())
        path = (
            self.fixture.output
            / result["frontend_candidate_input_sha256"]
            / "frontend/source/frontend-source-manifest.json"
        )
        path.write_text("{}\n", encoding="utf-8")
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(
            builder.FrontendSourceManifestError, "immutable_collision"
        ):
            builder.build_frontend_source_manifest(self.fixture.args())


if __name__ == "__main__":
    unittest.main()
