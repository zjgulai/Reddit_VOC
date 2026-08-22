from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.reddit_data_release_control import (
    DataReleaseControlError,
    rollback_release,
    shadow_validate_release,
    switch_release,
    validate_release,
)


DATASET_KEYS = (
    "base",
    "insights",
    "reports",
    "personas",
    "brand_health",
    "quarter_insights",
    "casebook",
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class DataReleaseControlTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "releases").mkdir()
        self.first = "reddit_voc_release_20260723_data_a1"
        self.second = "reddit_voc_release_20260724_data_a1"
        self._release(self.first, "2026-07-22T23:00:00Z")
        self._release(self.second, "2026-07-23T23:00:00Z")

    def _release(self, release_id: str, data_as_of: str) -> None:
        public = self.root / "releases" / release_id / "public"
        datasets = {}
        for key in DATASET_KEYS:
            version = (
                f"reddit_voc_site_snapshot_{release_id.removeprefix('reddit_voc_release_')}"
                if key == "base"
                else f"reddit_voc_{key}_{release_id.removeprefix('reddit_voc_release_')}"
            )
            manifest = public / "data/reddit-voc" / version / "manifest.json"
            _write(manifest, {"dataset_version": version, "status": "ready"})
            datasets[key] = {
                "dataset_version": version,
                "manifest_path": manifest.relative_to(public).as_posix(),
                "public_manifest_sha256": _sha(manifest),
                "lineage_manifest_sha256": _sha(manifest),
            }
        case_manifest = public / "data/cases/manifest.v1.json"
        case_index = public / "data/cases/case-index.v1.json"
        _write(case_index, {"datasetVersion": "case_catalog_fixture", "approvedDelta": []})
        _write(case_manifest, {"datasetVersion": "case_catalog_fixture"})
        end = data_as_of
        end_date = end[:10]
        start_date = "2026-07-21" if end_date == "2026-07-22" else "2026-07-22"
        pointer = {
            "schema_version": "reddit_voc_current_release_v2",
            "release_id": release_id,
            "generated_at_utc": data_as_of,
            "datasets": datasets,
            "freshness": {
                "status": "full",
                "timezone": "Asia/Shanghai",
                "data_as_of_utc": data_as_of,
                "window_start_utc": f"{start_date}T23:00:00Z",
                "window_end_utc": data_as_of,
                "collector_run_id": "daily_collect_fixture",
                "source_batch_id": "daily_collect_fixture",
                "center_snapshot_id": "reddit_voc_center_fixture",
                "net_new": {
                    "posts": 1,
                    "comments": 2,
                    "updated_historical_posts": 0,
                    "repaired_parent_links": 0,
                },
                "coverage": {
                    "full_posts": 1,
                    "partial_posts": 0,
                    "unresolved_continuations": 0,
                },
            },
            "cases": {
                "dataset_version": "case_catalog_fixture",
                "manifest_path": "data/cases/manifest.v1.json",
                "public_manifest_sha256": _sha(case_manifest),
                "index_path": "data/cases/case-index.v1.json",
                "index_sha256": _sha(case_index),
                "stock_content_preserved": True,
                "approved_delta_count": 0,
            },
            "boundaries": {
                "case_gallery_stock_preserved": True,
                "collector_isolation_required": True,
                "login_required": False,
            },
        }
        _write(public / "data/reddit-voc/current-release.json", pointer)

    def test_validates_exact_release_tree(self) -> None:
        result = validate_release(self.root, self.first)
        self.assertEqual(result["release_id"], self.first)
        self.assertEqual(result["freshness_status"], "full")
        self.assertEqual(set(result["manifest_sha256s"]), set(DATASET_KEYS))

    def test_switch_is_cas_guarded_and_replay_safe(self) -> None:
        first = switch_release(
            root=self.root,
            release_id=self.first,
            expected_current_release_id=None,
            authorize_switch=True,
        )
        self.assertEqual(first["status"], "switched")
        self.assertEqual(os.readlink(self.root / "current"), f"releases/{self.first}")
        second = switch_release(
            root=self.root,
            release_id=self.second,
            expected_current_release_id=self.first,
            authorize_switch=True,
        )
        self.assertEqual(second["status"], "switched")
        self.assertEqual(os.readlink(self.root / "current"), f"releases/{self.second}")
        self.assertEqual(os.readlink(self.root / "previous"), f"releases/{self.first}")
        replay = switch_release(
            root=self.root,
            release_id=self.second,
            expected_current_release_id=self.second,
            authorize_switch=True,
        )
        self.assertEqual(replay["status"], "no_change")

    def test_switch_requires_explicit_authorization_and_expected_current(self) -> None:
        with self.assertRaisesRegex(DataReleaseControlError, "switch_not_authorized"):
            switch_release(
                root=self.root,
                release_id=self.first,
                expected_current_release_id=None,
                authorize_switch=False,
            )
        switch_release(
            root=self.root,
            release_id=self.first,
            expected_current_release_id=None,
            authorize_switch=True,
        )
        with self.assertRaisesRegex(DataReleaseControlError, "current_release_cas_mismatch"):
            switch_release(
                root=self.root,
                release_id=self.second,
                expected_current_release_id="reddit_voc_release_wrong",
                authorize_switch=True,
            )

    def test_shadow_validation_writes_receipt_without_switching_pointers(self) -> None:
        switch_release(
            root=self.root,
            release_id=self.first,
            expected_current_release_id=None,
            authorize_switch=True,
        )
        current_before = os.readlink(self.root / "current")
        self.assertFalse((self.root / "previous").exists())

        result = shadow_validate_release(
            root=self.root,
            release_id=self.second,
        )

        self.assertEqual(result["status"], "shadow_validated")
        self.assertEqual(result["candidate_release_id"], self.second)
        self.assertEqual(result["current_release_id"], self.first)
        self.assertIsNone(result["previous_release_id"])
        self.assertTrue(result["pointer_unchanged"])
        self.assertEqual(os.readlink(self.root / "current"), current_before)
        self.assertFalse((self.root / "previous").exists())
        receipt = Path(result["receipt_path"])
        self.assertTrue(receipt.is_file())
        self.assertEqual(_sha(receipt), result["receipt_sha256"])
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertFalse(payload["boundaries"]["production_switch"])
        self.assertFalse(payload["boundaries"]["remote_write"])
        self.assertFalse(payload["boundaries"]["schedule_change"])
        self.assertFalse(payload["boundaries"]["live_send"])

    def test_rolls_back_by_swapping_current_and_previous(self) -> None:
        switch_release(
            root=self.root,
            release_id=self.first,
            expected_current_release_id=None,
            authorize_switch=True,
        )
        switch_release(
            root=self.root,
            release_id=self.second,
            expected_current_release_id=self.first,
            authorize_switch=True,
        )
        result = rollback_release(
            root=self.root,
            expected_current_release_id=self.second,
            authorize_switch=True,
        )
        self.assertEqual(
            result["schema_version"],
            "reddit_voc_data_release_rollback_receipt_v1",
        )
        self.assertEqual(result["to_release_id"], self.first)
        self.assertTrue(Path(result["receipt_path"]).is_file())
        self.assertEqual(os.readlink(self.root / "current"), f"releases/{self.first}")
        self.assertEqual(os.readlink(self.root / "previous"), f"releases/{self.second}")

    def test_rejects_manifest_tampering_before_switch(self) -> None:
        pointer = _load = json.loads(
            (
                self.root
                / "releases"
                / self.second
                / "public/data/reddit-voc/current-release.json"
            ).read_text(encoding="utf-8")
        )
        manifest = (
            self.root
            / "releases"
            / self.second
            / "public"
            / pointer["datasets"]["base"]["manifest_path"]
        )
        manifest.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(DataReleaseControlError, "base_manifest_sha256_mismatch"):
            validate_release(self.root, self.second)


if __name__ == "__main__":
    unittest.main()
