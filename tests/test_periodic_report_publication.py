from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.periodic_report_bundle import PeriodicBundleError
from reddit_voc.periodic_report_publication import (
    materialize_periodic_public_projection,
    verify_periodic_public_projection,
)
from reddit_voc.report_contracts import sha256_hex


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = (
    ROOT
    / "output/reddit-voc-periodic-report-bundles/shadow-daily-v3-20260724-r2"
)
RELEASE_ID = "reddit_voc_release_20260723_daily_v3"
DESTINATION = sha256_hex(b"dingtalk-group-primary-v1")
BUNDLE_SHA = "658966e32a39fcff47b91f7ba0d64d7ac7f520b311e505aef3a57e113853d21b"
BUNDLE_ID = "periodic_93d555291be7aa1b71b5ccc965492a73"


class PeriodicReportPublicationTests(unittest.TestCase):
    def materialize(self, temporary: str):
        projection = Path(temporary) / "projection"
        public, receipt = materialize_periodic_public_projection(
            bundle_root=BUNDLE_ROOT,
            projection_root=projection,
            expected_release_id=RELEASE_ID,
            expected_destination_fingerprint=DESTINATION,
            expected_bundle_manifest_sha256=BUNDLE_SHA,
        )
        return projection, public, receipt

    def test_projection_contains_only_three_pngs_and_sanitized_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            projection, public, receipt = self.materialize(temporary)
            files = sorted(
                path.relative_to(projection).as_posix()
                for path in projection.rglob("*")
                if path.is_file()
            )
            self.assertEqual(
                files,
                [
                    f"periodic-report-assets/{BUNDLE_ID}/manifest.json",
                    f"periodic-report-assets/{BUNDLE_ID}/public/daily/poster.png",
                    f"periodic-report-assets/{BUNDLE_ID}/public/monthly/poster.png",
                    f"periodic-report-assets/{BUNDLE_ID}/public/weekly/poster.png",
                ],
            )
            manifest_text = (
                projection / f"periodic-report-assets/{BUNDLE_ID}/manifest.json"
            ).read_text(encoding="utf-8")
            self.assertNotIn('"relative_path":"private/', manifest_text.lower())
            self.assertNotIn(DESTINATION, manifest_text)
            self.assertNotIn("periodic-shadow.invalid", manifest_text.lower())
            self.assertEqual(public["data_release_id"], RELEASE_ID)
            self.assertEqual(receipt["status"], "passed_local_publication_candidate")
            self.assertEqual(receipt["asset_count"], 3)
            self.assertFalse(receipt["boundaries"]["deploy"])

    def test_projection_verifier_fails_on_tampered_or_extra_file(self) -> None:
        with TemporaryDirectory() as temporary:
            projection, _, _ = self.materialize(temporary)
            poster = projection / f"periodic-report-assets/{BUNDLE_ID}/public/daily/poster.png"
            poster.write_bytes(poster.read_bytes() + b"tampered")
            with self.assertRaisesRegex(
                PeriodicBundleError, "periodic_public_asset_mismatch"
            ):
                verify_periodic_public_projection(
                    projection,
                    expected_release_id=RELEASE_ID,
                    expected_bundle_manifest_sha256=BUNDLE_SHA,
                )

        with TemporaryDirectory() as temporary:
            projection, _, _ = self.materialize(temporary)
            extra = projection / "unexpected.txt"
            extra.write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(
                PeriodicBundleError, "periodic_public_projection_file_set_invalid"
            ):
                verify_periodic_public_projection(
                    projection,
                    expected_release_id=RELEASE_ID,
                    expected_bundle_manifest_sha256=BUNDLE_SHA,
                )

    def test_wrong_source_manifest_hash_fails_before_projection(self) -> None:
        with TemporaryDirectory() as temporary:
            projection = Path(temporary) / "projection"
            with self.assertRaisesRegex(
                PeriodicBundleError, "periodic_public_source_manifest_mismatch"
            ):
                materialize_periodic_public_projection(
                    bundle_root=BUNDLE_ROOT,
                    projection_root=projection,
                    expected_release_id=RELEASE_ID,
                    expected_destination_fingerprint=DESTINATION,
                    expected_bundle_manifest_sha256="0" * 64,
                )
            self.assertFalse(projection.exists())


if __name__ == "__main__":
    unittest.main()
