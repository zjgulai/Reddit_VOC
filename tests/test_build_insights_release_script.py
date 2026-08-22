from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_insights_release.sh"
REMOTE_INSTALL = ROOT / "scripts/remote_install_insights_release.sh"
REMOTE_ROLLBACK = ROOT / "scripts/remote_rollback_insights.sh"
NGINX_CONFIG = (
    ROOT / "ref/UI/momcozy-reddit-workbench/deploy/insights/nginx.conf"
)
REVIEWED_NODE_MODULES = (
    ROOT / "ref/UI/momcozy-reddit-workbench/node_modules"
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_plan_b_source_fixture(
    workspace: Path,
) -> tuple[Path, Path, Path]:
    source_root = workspace / "source-ui"
    evidence_root = workspace / "plan-b-evidence"
    source_root.mkdir()
    evidence_root.mkdir()
    (source_root / "public/data/reddit-voc").mkdir(parents=True)
    (source_root / "src").mkdir()
    (source_root / "package-lock.json").write_text(
        '{"lockfileVersion":3}\n', encoding="utf-8"
    )
    (source_root / "public/data/reddit-voc/current-release.json").write_text(
        '{"datasets":{}}\n', encoding="utf-8"
    )
    for index in range(217):
        (source_root / "src" / f"fixture-{index:03d}.txt").write_text(
            f"fixture-{index}\n", encoding="utf-8"
        )
    (source_root / "node_modules").symlink_to(
        REVIEWED_NODE_MODULES, target_is_directory=True
    )

    rows = []
    for path in sorted(
        (path for path in source_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source_root).as_posix(),
    ):
        rows.append(
            {
                "bytes": path.stat().st_size,
                "path": path.relative_to(source_root).as_posix(),
                "sha256": _sha(path),
            }
        )
    assert len(rows) == 219
    inventory_sha = sha256(_canonical_bytes(rows)[:-1]).hexdigest()
    candidate_input = "a" * 64
    package_lock_sha = _sha(source_root / "package-lock.json")
    manifest = {
        "boundaries": {
            "artifact_build": False,
            "database_write": False,
            "deploy": False,
            "deployment": False,
            "live_send": False,
            "production_unchanged": True,
            "promotable_dist_included": False,
            "provider_call": False,
            "remote_write": False,
        },
        "frontend_candidate_input_sha256": candidate_input,
        "schema_version": "reddit_voc_frontend_source_manifest_v1",
        "source": {
            "inventory": {
                "file_count": len(rows),
                "files": rows,
                "inventory_sha256": inventory_sha,
                "total_bytes": sum(row["bytes"] for row in rows),
            }
        },
        "status": "frontend_source_frozen_local",
        "toolchain": {
            "package_lock_relative_path": "package-lock.json",
            "package_lock_sha256": package_lock_sha,
        },
    }
    manifest_path = evidence_root / "frontend-source-manifest.json"
    manifest_path.write_bytes(_canonical_bytes(manifest))
    inventory_summary = {
        "file_count": len(rows),
        "inventory_sha256": inventory_sha,
        "total_bytes": sum(row["bytes"] for row in rows),
    }
    receipt = {
        "boundaries": {
            "artifact_build": False,
            "database_write": False,
            "deploy": False,
            "deployment": False,
            "live_send": False,
            "production_unchanged": True,
            "promotable_dist_included": False,
            "provider_call": False,
            "remote_write": False,
        },
        "checks": {"isolated_manifest_only_source_stage": True},
        "frontend_candidate_input_sha256": candidate_input,
        "frontend_source_manifest_sha256": _sha(manifest_path),
        "schema_version": (
            "reddit_voc_candidate_ui_source_validation_receipt_v1"
        ),
        "source_inventory": inventory_summary,
        "status": "passed_local_source_validation",
    }
    receipt_path = evidence_root / "candidate-ui-source-validation-receipt.json"
    receipt_path.write_bytes(_canonical_bytes(receipt))
    return source_root, manifest_path, receipt_path


class BuildInsightsReleaseScriptTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_help_documents_isolated_candidate_contract(self) -> None:
        result = self._run("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--public-root PATH", result.stdout)
        self.assertIn("--source-ui-root PATH", result.stdout)
        self.assertIn("--frontend-source-manifest PATH", result.stdout)
        self.assertIn("--frontend-source-receipt PATH", result.stdout)
        self.assertIn("--receipt PATH", result.stdout)
        self.assertIn("--dist-root PATH", result.stdout)
        self.assertIn("--dist-only", result.stdout)
        self.assertIn("--candidate-container", result.stdout)
        self.assertIn("--latest-collection-integrated BOOL", result.stdout)
        self.assertIn("--latest-collection-fully-hydrated BOOL", result.stdout)
        self.assertIn("default only to false", result.stdout)
        self.assertIn("modified in either mode", result.stdout)

    def test_alternate_public_root_requires_explicit_dist_root(self) -> None:
        with TemporaryDirectory() as temporary:
            result = self._run("--public-root", temporary, "--dist-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit isolated --dist-root", result.stderr)

    def test_isolated_dist_must_remain_below_project_tmp(self) -> None:
        with TemporaryDirectory() as temporary:
            public_root = Path(temporary) / "public"
            dist_root = Path(temporary) / "dist"
            public_root.mkdir()
            result = self._run(
                "--public-root",
                str(public_root),
                "--dist-root",
                str(dist_root),
                "--dist-only",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("isolated dist root must remain below", result.stderr)

    def test_candidate_requires_both_explicit_collection_statuses(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        with TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            public_root = Path(temporary) / "public"
            dist_root = Path(temporary) / "dist"
            public_root.mkdir()
            result = self._run(
                "--public-root",
                str(public_root),
                "--dist-root",
                str(dist_root),
                "--dist-only",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("both explicit collection-status booleans", result.stderr)

    def test_collection_status_rejects_non_boolean_and_impossible_state(self) -> None:
        invalid = self._run("--latest-collection-integrated", "yes")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("must be true or false", invalid.stderr)

        impossible = self._run(
            "--latest-collection-integrated",
            "false",
            "--latest-collection-fully-hydrated",
            "true",
        )
        self.assertNotEqual(impossible.returncode, 0)
        self.assertIn("before it is integrated", impossible.stderr)

    def test_candidate_container_mode_is_explicit_and_fail_closed(self) -> None:
        mutually_exclusive = self._run("--dist-only", "--candidate-container")
        self.assertNotEqual(mutually_exclusive.returncode, 0)
        self.assertIn("mutually exclusive", mutually_exclusive.stderr)

        default_public = self._run("--candidate-container")
        self.assertNotEqual(default_public.returncode, 0)
        self.assertIn("requires an alternate public root", default_public.stderr)

        (ROOT / "tmp").mkdir(exist_ok=True)
        with TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            public_root = Path(temporary) / "public"
            dist_root = Path(temporary) / "dist"
            public_root.mkdir()
            missing_output = self._run(
                "--public-root",
                str(public_root),
                "--dist-root",
                str(dist_root),
                "--candidate-container",
                "--latest-collection-integrated",
                "true",
                "--latest-collection-fully-hydrated",
                "false",
            )
        self.assertNotEqual(missing_output.returncode, 0)
        self.assertIn("requires an explicit --output-root", missing_output.stderr)

        with TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            public_root = Path(temporary) / "public"
            dist_root = Path(temporary) / "dist"
            public_root.mkdir()
            overlapping_output = self._run(
                "--public-root",
                str(public_root),
                "--dist-root",
                str(dist_root),
                "--output-root",
                str(dist_root / "release"),
                "--candidate-container",
                "--latest-collection-integrated",
                "true",
                "--latest-collection-fully-hydrated",
                "false",
            )
        self.assertNotEqual(overlapping_output.returncode, 0)
        self.assertIn("must not overlap", overlapping_output.stderr)

    def test_candidate_public_stage_reads_only_the_explicit_public_root(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('cp -R "${PUBLIC_ROOT}/." "${BUILD_PUBLIC_ROOT}/"', script)
        self.assertNotIn('find "${DEFAULT_PUBLIC_ROOT}"', script)
        self.assertNotIn('cp -R "${source_asset}" "${BUILD_PUBLIC_ROOT}/"', script)

    def test_candidate_requires_complete_plan_b_source_contract(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        with TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            workspace = Path(temporary)
            public_root = workspace / "public"
            dist_root = workspace / "dist"
            public_root.mkdir()
            result = self._run(
                "--public-root",
                str(public_root),
                "--dist-root",
                str(dist_root),
                "--dist-only",
                "--latest-collection-integrated",
                "true",
                "--latest-collection-fully-hydrated",
                "false",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires the complete Plan B source contract", result.stderr)

    def test_candidate_container_requires_explicit_build_receipt(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        with TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            workspace = Path(temporary)
            source_root, manifest, receipt = _write_plan_b_source_fixture(workspace)
            result = self._run(
                "--public-root",
                str(source_root / "public"),
                "--source-ui-root",
                str(source_root),
                "--frontend-source-manifest",
                str(manifest),
                "--frontend-source-receipt",
                str(receipt),
                "--dist-root",
                str(workspace / "dist"),
                "--output-root",
                str(workspace / "release"),
                "--candidate-container",
                "--latest-collection-integrated",
                "true",
                "--latest-collection-fully-hydrated",
                "false",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an explicit --receipt", result.stderr)

    def test_build_receipt_contract_is_private_and_machine_readable(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "reddit_voc_insights_build_receipt_v1",
            '"status": "passed_local_build"',
            '"dist_inventory"',
            '"release_manifest"',
            '"image_tar"',
            '"archive_tgz"',
            '"side_effects"',
            "0o600",
            "receipt_status=",
            "receipt_sha256=",
        ):
            self.assertIn(marker, script)

    def test_manifest_only_source_inventory_passes_before_pointer_gate(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        with TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            workspace = Path(temporary)
            source_root, manifest, receipt = _write_plan_b_source_fixture(workspace)
            result = self._run(
                "--public-root",
                str(source_root / "public"),
                "--source-ui-root",
                str(source_root),
                "--frontend-source-manifest",
                str(manifest),
                "--frontend-source-receipt",
                str(receipt),
                "--dist-root",
                str(workspace / "dist"),
                "--output-root",
                str(workspace / "release"),
                "--dist-only",
                "--latest-collection-integrated",
                "true",
                "--latest-collection-fully-hydrated",
                "false",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manifest_only_source_validation=passed", result.stdout)
        self.assertIn("current-release datasets contract is invalid", result.stderr)

    def test_manifest_only_source_rejects_unlisted_file(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        with TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            workspace = Path(temporary)
            source_root, manifest, receipt = _write_plan_b_source_fixture(workspace)
            (source_root / "unlisted.txt").write_text("drift\n", encoding="utf-8")
            result = self._run(
                "--public-root",
                str(source_root / "public"),
                "--source-ui-root",
                str(source_root),
                "--frontend-source-manifest",
                str(manifest),
                "--frontend-source-receipt",
                str(receipt),
                "--dist-root",
                str(workspace / "dist"),
                "--output-root",
                str(workspace / "release"),
                "--dist-only",
                "--latest-collection-integrated",
                "true",
                "--latest-collection-fully-hydrated",
                "false",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("staged source inventory differs", result.stderr)

    def test_nginx_blocks_governance_evidence_probes_without_version_literals(self) -> None:
        config = NGINX_CONFIG.read_text(encoding="utf-8")
        for path in (
            "/.env",
            "/frontend-source-manifest.json",
            "/candidate-ui-source-validation-receipt.json",
            "/candidate-ui-validation-receipt.json",
            "/release-manifest.json",
            "/frontend/source/frontend-source-manifest.json",
            "/frontend/source/candidate-ui-source-validation-receipt.json",
            "/frontend/final/candidate-ui-validation-receipt.json",
        ):
            self.assertIn(f"location = {path}", config)
        self.assertNotIn("reddit_voc_site_snapshot_20260714_v1", config)
        self.assertNotIn("reddit_voc_insights_20260714_v1", config)
        self.assertNotIn("reddit_voc_reports_20260714_v1", config)

    def test_runtime_uses_one_fail_closed_read_only_data_mount(self) -> None:
        deploy_root = NGINX_CONFIG.parent
        compose = (deploy_root / "compose.yaml").read_text(encoding="utf-8")
        config = NGINX_CONFIG.read_text(encoding="utf-8")
        builder = (deploy_root / "build-release.mjs").read_text(encoding="utf-8")

        self.assertIn(
            "${REDDIT_VOC_DATA_ROOT:?REDDIT_VOC_DATA_ROOT must be set}"
            ":/srv/reddit-voc-data:ro",
            compose,
        )
        self.assertIn(
            "http://127.0.0.1:8080/data/reddit-voc/current-release.json",
            compose,
        )
        self.assertIn(
            "alias /srv/reddit-voc-data/current/public/data/reddit-voc/;",
            config,
        )
        self.assertIn("location = /data/reddit-voc", config)
        self.assertIn("reddit_voc_insights_container_v6", builder)
        self.assertIn("reddit_voc_data_mount_v1", builder)
        self.assertIn("atomic_pointer_switch_without_container_restart", builder)

    def test_remote_operational_scripts_propagate_manifest_collection_status(self) -> None:
        for script in (REMOTE_INSTALL, REMOTE_ROLLBACK):
            syntax = subprocess.run(
                ["bash", "-n", str(script)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)

        install = REMOTE_INSTALL.read_text(encoding="utf-8")
        self.assertIn(
            "latest_collection_integrated=${manifest_collection_integrated}",
            install,
        )
        self.assertIn(
            "latest_collection_fully_hydrated=${manifest_collection_fully_hydrated}",
            install,
        )
        rollback = REMOTE_ROLLBACK.read_text(encoding="utf-8")
        self.assertIn(
            "latest_collection_integrated=${target_collection_integrated}",
            rollback,
        )
        self.assertIn(
            "latest_collection_fully_hydrated=${target_collection_fully_hydrated}",
            rollback,
        )


if __name__ == "__main__":
    unittest.main()
