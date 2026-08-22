from __future__ import annotations

import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.periodic_report_bundle import (
    PeriodicBundleError,
    build_periodic_report_bundle,
    preflight_periodic_report_bundle,
    verify_periodic_report_bundle,
)
from reddit_voc.report_contracts import canonical_json_bytes, sha256_hex


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POSTER_ROOT = (
    REPOSITORY_ROOT
    / "output/reddit-voc-periodic-report-posters/gate5-local-20260724-r3"
)
RELEASE_ID = "reddit_voc_release_20260723_daily_v2"
DATASET_VERSION = "reddit_voc_reports_20260723_v3_47c49395e785_history2"
DESTINATION = sha256_hex(b"dingtalk-group-primary-v1")


class PeriodicReportBundleTests(unittest.TestCase):
    def build(
        self,
        temporary: str,
        *,
        name: str = "bundle",
        poster_manifest: Path | None = None,
        destination: str = DESTINATION,
        release_id: str = RELEASE_ID,
        artifact_base_url: str = "https://reddit.lute-tlz-dddd.top/data/reddit-voc-delivery",
    ) -> tuple[Path, str, dict[str, object]]:
        root = Path(temporary) / name
        manifest_sha, manifest = build_periodic_report_bundle(
            poster_manifest_path=poster_manifest or POSTER_ROOT / "manifest.json",
            output_root=root,
            artifact_base_url=artifact_base_url,
            dashboard_base_url="https://reddit.lute-tlz-dddd.top",
            destination_fingerprint=destination,
            expected_release_id=release_id,
            expected_dataset_version=DATASET_VERSION,
        )
        return root, manifest_sha, dict(manifest)

    def poster_manifest_with_status(self, temporary: str, status: str) -> Path:
        root = Path(temporary) / f"posters-{status}"
        shutil.copytree(POSTER_ROOT, root)
        path = root / "manifest.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        for capture in value["captures"]:
            capture["source_freshness_status"] = status
        path.write_bytes(canonical_json_bytes(value) + b"\n")
        return path

    def test_builds_three_secret_free_frozen_messages_and_verifies_identity(self) -> None:
        with TemporaryDirectory() as temporary:
            root, manifest_sha, manifest = self.build(temporary)
            verified = verify_periodic_report_bundle(
                root,
                expected_release_id=RELEASE_ID,
                expected_destination_fingerprint=DESTINATION,
            )
            self.assertEqual(
                manifest_sha, sha256_hex((root / "manifest.json").read_bytes())
            )
            self.assertEqual(verified["status"], "shadow_candidate")
            self.assertFalse(verified["delivery"]["eligible"])
            self.assertEqual(
                {row["grain"] for row in manifest["captures"]},
                {"daily", "weekly", "monthly"},
            )
            keys = set()
            for capture in manifest["captures"]:
                grain = capture["grain"]
                self.assertTrue((root / f"public/{grain}/poster.png").is_file())
                body = (root / f"private/outbox/{grain}.json").read_text(
                    encoding="utf-8"
                )
                self.assertIn("https://", body)
                self.assertIn("查看完整报告", body)
                self.assertIn("打开导出入口", body)
                self.assertIn(RELEASE_ID, body)
                self.assertNotIn("webhook", body.lower())
                self.assertNotIn("secret", body.lower())
                keys.add(capture["idempotency_key"])
            self.assertEqual(len(keys), 3)

    def test_same_inputs_produce_byte_identical_manifests(self) -> None:
        with TemporaryDirectory() as temporary:
            first, first_sha, _ = self.build(temporary, name="first")
            second, second_sha, _ = self.build(temporary, name="second")
            self.assertEqual(first_sha, second_sha)
            self.assertEqual(
                (first / "manifest.json").read_bytes(),
                (second / "manifest.json").read_bytes(),
            )

    def test_destination_is_part_of_bundle_and_idempotency_identity(self) -> None:
        with TemporaryDirectory() as temporary:
            _, _, first = self.build(temporary, name="first")
            other = sha256_hex(b"different-destination")
            _, _, second = self.build(temporary, name="second", destination=other)
            self.assertNotEqual(first["bundle_id"], second["bundle_id"])
            self.assertNotEqual(
                [row["idempotency_key"] for row in first["captures"]],
                [row["idempotency_key"] for row in second["captures"]],
            )

    def test_partial_empty_success_and_no_change_have_explicit_business_copy(self) -> None:
        expected = {
            "partial": "部分分页覆盖",
            "empty_success": "没有净新增",
            "no_change": "幂等键阻止重复发送",
        }
        with TemporaryDirectory() as temporary:
            for status, message in expected.items():
                poster_manifest = self.poster_manifest_with_status(temporary, status)
                root, _, _ = self.build(
                    temporary,
                    name=f"bundle-{status}",
                    poster_manifest=poster_manifest,
                )
                body = (root / "private/outbox/daily.json").read_text(
                    encoding="utf-8"
                )
                self.assertIn(message, body)

    def test_failed_or_unknown_source_status_cannot_build_business_bundle(self) -> None:
        with TemporaryDirectory() as temporary:
            failed = self.poster_manifest_with_status(temporary, "failed")
            with self.assertRaisesRegex(
                PeriodicBundleError, "poster_daily_contract_invalid"
            ):
                self.build(temporary, poster_manifest=failed)

    def test_unreviewed_new_image_identity_cannot_build_a_bundle(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "unreviewed-posters"
            shutil.copytree(POSTER_ROOT, root)
            path = root / "manifest.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["golden_evaluation"] = {
                "status": "passed_structural_new_identity",
                "manual_visual_review_required": True,
                "reason": "release_dataset_period_or_validator_changed",
            }
            path.write_bytes(canonical_json_bytes(value) + b"\n")
            with self.assertRaisesRegex(
                PeriodicBundleError, "poster_manifest_contract_invalid"
            ):
                self.build(temporary, poster_manifest=path)

    def test_old_release_or_insecure_url_is_rejected_before_output(self) -> None:
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PeriodicBundleError, "poster_identity_mismatch"):
                self.build(
                    temporary,
                    name="stale",
                    release_id="reddit_voc_release_20260722_stale",
                )
            self.assertFalse((Path(temporary) / "stale").exists())
            with self.assertRaisesRegex(PeriodicBundleError, "artifact_base_url_invalid"):
                self.build(
                    temporary,
                    name="insecure",
                    artifact_base_url="http://example.test/reports",
                )

    def test_tampered_poster_or_outbox_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            root, _, _ = self.build(temporary)
            poster = root / "public/daily/poster.png"
            poster.write_bytes(poster.read_bytes() + b"tampered")
            with self.assertRaisesRegex(PeriodicBundleError, "bundle_poster_mismatch"):
                verify_periodic_report_bundle(
                    root,
                    expected_release_id=RELEASE_ID,
                    expected_destination_fingerprint=DESTINATION,
                )

    def test_preflight_checks_all_nine_urls_without_enabling_send(self) -> None:
        with TemporaryDirectory() as temporary:
            root, _, manifest = self.build(temporary)
            poster_sizes = {
                row["poster"]["public_url"]: row["poster"]["bytes"]
                for row in manifest["captures"]
            }
            seen: list[str] = []

            def head(url: str) -> dict[str, object]:
                seen.append(url)
                return {"status": 200, "content_length": poster_sizes.get(url)}

            result = preflight_periodic_report_bundle(
                root,
                expected_release_id=RELEASE_ID,
                expected_destination_fingerprint=DESTINATION,
                head_checker=head,
            )
            self.assertEqual(result["status"], "passed_shadow_preflight")
            self.assertEqual(len(result["checks"]), 9)
            self.assertEqual(len(seen), 9)
            self.assertFalse(result["delivery_eligible"])
            self.assertFalse(result["boundaries"]["live_send"])

    def test_wrong_remote_poster_length_blocks_preflight(self) -> None:
        with TemporaryDirectory() as temporary:
            root, _, _ = self.build(temporary)

            def head(url: str) -> dict[str, object]:
                return {"status": 200, "content_length": 1}

            with self.assertRaisesRegex(
                PeriodicBundleError, "head_daily_poster_bytes_mismatch"
            ):
                preflight_periodic_report_bundle(
                    root,
                    expected_release_id=RELEASE_ID,
                    expected_destination_fingerprint=DESTINATION,
                    head_checker=head,
                )


if __name__ == "__main__":
    unittest.main()
