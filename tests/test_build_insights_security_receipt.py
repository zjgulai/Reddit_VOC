from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_insights_security_receipt import (
    SecurityReceiptError,
    build_security_receipt,
    canonical_bytes,
)


class InsightsSecurityReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.release_sha = "a" * 64
        self.release_dir = self.root / self.release_sha
        self.release_dir.mkdir()
        release = {
            "schema_version": "reddit_voc_insights_site_release_v2",
            "release_sha256": self.release_sha,
            "target_platform": "linux/amd64",
            "authentication_enabled": False,
            "public_access": True,
            "nginx_base_image": "example.invalid/nginx@sha256:" + "b" * 64,
            "deployment_inputs": [],
        }
        compose_path = self.release_dir / "compose.yaml"
        compose_path.write_text(
            "services:\n  web:\n    read_only: true\n    cap_drop:\n      - ALL\n    security_opt:\n      - no-new-privileges:true\n",
            encoding="utf-8",
        )
        release["deployment_inputs"].append({
            "path": "deploy/insights/compose.yaml",
            "bytes": compose_path.stat().st_size,
            "sha256": sha256(compose_path.read_bytes()).hexdigest(),
        })
        release_manifest_path = self.release_dir / "release-manifest.json"
        release_manifest_path.write_bytes(canonical_bytes(release))
        dist_sums_path = self.release_dir / "dist-SHA256SUMS"
        dist_sums_path.write_text("fixture\n", encoding="utf-8")
        image_tar_path = self.release_dir / f"reddit-voc-insights-{self.release_sha}.tar"
        image_tar_path.write_bytes(b"tar")
        (self.release_dir / "SHA256SUMS").write_text(
            "".join(
                f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                for path in (compose_path, dist_sums_path, release_manifest_path, image_tar_path)
            ),
            encoding="utf-8",
        )
        boundaries = {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        }
        smoke = {
            "schema_version": "reddit_voc_local_insights_container_smoke_receipt_v1",
            "status": "passed_local_isolated_container_smoke",
            "release": {
                "release_sha256": self.release_sha,
                "release_manifest_sha256": sha256(release_manifest_path.read_bytes()).hexdigest(),
                "target_platform": "linux/amd64",
                "dist_sha256sums": {
                    "bytes": dist_sums_path.stat().st_size,
                    "sha256": sha256(dist_sums_path.read_bytes()).hexdigest(),
                },
                "image_tar": {
                    "bytes": image_tar_path.stat().st_size,
                    "sha256": sha256(image_tar_path.read_bytes()).hexdigest(),
                },
            },
            "boundaries": boundaries,
            "runtime_checks": {
                "cap_drop_all": True,
                "container_loopback_http": True,
                "healthy": True,
                "host_port_published": False,
                "isolated_internal_network": True,
                "no_new_privileges": True,
                "read_only_rootfs": True,
                "uid_gid_101": True,
                "zero_mounts": True,
            },
        }
        export = {
            "schema_version": "reddit_voc_insights_export_validation_receipt_v1",
            "status": "passed_local_readonly_export_acceptance",
            "release": {"release_sha256": self.release_sha},
            "checks": {
                "download_count": 4,
                "csv_content_verified": True,
                "docx_structure_and_content_verified": True,
                "pdf_structure_verified": True,
                "pptx_structure_and_content_verified": True,
                "release_and_report_binding_verified": True,
            },
            "boundaries": boundaries,
            "site_scope": "local_loopback",
            "site_url": "http://127.0.0.1:18441",
            "evidence_grade": "L2_local_container_readonly_browser_download_acceptance",
        }
        self.smoke = self.root / "smoke.json"
        self.export = self.root / "export.json"
        self.smoke.write_bytes(canonical_bytes(smoke))
        self.export.write_bytes(canonical_bytes(export))
        self.output = self.root / "security.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build(self):
        return build_security_receipt(
            project_root=self.root,
            release_dir=self.release_dir,
            container_smoke_path=self.smoke,
            export_receipt_path=self.export,
            output_path=self.output,
            generated_at_utc="2026-07-23T00:00:00Z",
        )

    def _rewrite_compose_and_bind(self, value: str) -> None:
        compose_path = self.release_dir / "compose.yaml"
        compose_path.write_text(value, encoding="utf-8")
        release_path = self.release_dir / "release-manifest.json"
        release = json.loads(release_path.read_text())
        release["deployment_inputs"][0] = {
            "path": "deploy/insights/compose.yaml",
            "bytes": compose_path.stat().st_size,
            "sha256": sha256(compose_path.read_bytes()).hexdigest(),
        }
        release_path.write_bytes(canonical_bytes(release))
        smoke = json.loads(self.smoke.read_text())
        smoke["release"]["release_manifest_sha256"] = sha256(
            release_path.read_bytes()
        ).hexdigest()
        self.smoke.write_bytes(canonical_bytes(smoke))
        dist_sums_path = self.release_dir / "dist-SHA256SUMS"
        image_tar_path = self.release_dir / f"reddit-voc-insights-{self.release_sha}.tar"
        (self.release_dir / "SHA256SUMS").write_text(
            "".join(
                f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                for path in (compose_path, dist_sums_path, release_path, image_tar_path)
            ),
            encoding="utf-8",
        )

    def test_builds_canonical_immutable_security_receipt(self) -> None:
        state, digest, receipt = self._build()
        self.assertEqual(state, "created")
        self.assertEqual(digest, sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(all(receipt["checks"].values()))
        self.assertFalse(receipt["boundaries"]["deploy"])
        self.assertEqual(
            receipt["evidence_grade"],
            "L2_local_container_security_and_export_acceptance",
        )
        second_state, second_digest, _ = self._build()
        self.assertEqual((second_state, second_digest), ("no_change", digest))

    def test_rejects_unpinned_base_image(self) -> None:
        path = self.release_dir / "release-manifest.json"
        value = json.loads(path.read_text())
        value["nginx_base_image"] = "nginx:latest"
        path.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(SecurityReceiptError, "release_contract_invalid"):
            self._build()

    def test_rejects_missing_runtime_security(self) -> None:
        value = json.loads(self.smoke.read_text())
        value["runtime_checks"]["read_only_rootfs"] = False
        self.smoke.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(SecurityReceiptError, "container_runtime_security_invalid"):
            self._build()

    def test_rejects_compose_host_volume_section(self) -> None:
        path = self.release_dir / "compose.yaml"
        path.write_text(path.read_text() + "    volumes:\n      - /tmp:/tmp\n", encoding="utf-8")
        with self.assertRaisesRegex(SecurityReceiptError, "compose_contract_mismatch"):
            self._build()

    def test_accepts_v2_exact_read_only_data_mount(self) -> None:
        compose = (
            "services:\n  web:\n    read_only: true\n"
            "    volumes:\n"
            '      - "${REDDIT_VOC_DATA_ROOT:?REDDIT_VOC_DATA_ROOT must be set}'
            ':/srv/reddit-voc-data:ro"\n'
            "    cap_drop:\n      - ALL\n"
            "    security_opt:\n      - no-new-privileges:true\n"
        )
        self._rewrite_compose_and_bind(compose)
        smoke = json.loads(self.smoke.read_text())
        smoke["schema_version"] = "reddit_voc_local_insights_container_smoke_receipt_v2"
        smoke["runtime_checks"].pop("zero_mounts")
        smoke["runtime_checks"].update(
            {
                "one_read_only_data_mount": True,
                "exact_data_mount_contract": True,
                "data_pointer_health": True,
            }
        )
        self.smoke.write_bytes(canonical_bytes(smoke))

        _, _, receipt = self._build()

        self.assertTrue(receipt["checks"]["compose_exact_read_only_data_mount_declared"])
        self.assertNotIn("compose_no_host_mounts_declared", receipt["checks"])

    def test_rejects_v2_writable_data_mount(self) -> None:
        compose = (
            "services:\n  web:\n    read_only: true\n"
            "    volumes:\n"
            '      - "${REDDIT_VOC_DATA_ROOT:?REDDIT_VOC_DATA_ROOT must be set}'
            ':/srv/reddit-voc-data:rw"\n'
            "    cap_drop:\n      - ALL\n"
            "    security_opt:\n      - no-new-privileges:true\n"
        )
        self._rewrite_compose_and_bind(compose)
        smoke = json.loads(self.smoke.read_text())
        smoke["schema_version"] = "reddit_voc_local_insights_container_smoke_receipt_v2"
        smoke["runtime_checks"].pop("zero_mounts")
        smoke["runtime_checks"].update(
            {
                "one_read_only_data_mount": True,
                "exact_data_mount_contract": True,
                "data_pointer_health": True,
            }
        )
        self.smoke.write_bytes(canonical_bytes(smoke))

        with self.assertRaisesRegex(SecurityReceiptError, "compose_security_contract_invalid"):
            self._build()

    def test_rejects_smoke_image_hash_mismatch(self) -> None:
        value = json.loads(self.smoke.read_text())
        value["release"]["image_tar"]["sha256"] = "f" * 64
        self.smoke.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(SecurityReceiptError, "container_smoke_image_tar_contract_mismatch"):
            self._build()

    def test_rejects_release_sums_mismatch(self) -> None:
        path = self.release_dir / "SHA256SUMS"
        path.write_text(path.read_text().replace("a", "b", 1), encoding="utf-8")
        with self.assertRaisesRegex(SecurityReceiptError, "release_sums_contract_mismatch"):
            self._build()

    def test_rejects_mislabeled_loopback_export_grade(self) -> None:
        value = json.loads(self.export.read_text())
        value["evidence_grade"] = "L3_public_readonly_browser_download_acceptance"
        self.export.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(SecurityReceiptError, "export_evidence_grade_invalid"):
            self._build()

    def test_rejects_scope_that_disagrees_with_export_url(self) -> None:
        value = json.loads(self.export.read_text())
        value["site_url"] = "https://reddit.example.test"
        self.export.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(SecurityReceiptError, "export_evidence_grade_invalid"):
            self._build()

    def test_rejects_incomplete_export_content_checks(self) -> None:
        value = json.loads(self.export.read_text())
        value["checks"]["docx_structure_and_content_verified"] = False
        self.export.write_bytes(canonical_bytes(value))
        with self.assertRaisesRegex(SecurityReceiptError, "export_contract_invalid"):
            self._build()


if __name__ == "__main__":
    unittest.main()
