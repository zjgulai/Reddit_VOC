from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_data_release import (
    DataReleaseContractError,
    build_data_release,
    write_immutable_pointer,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "ref/UI/momcozy-reddit-workbench/public"
CURRENT_POINTER = PUBLIC / "data/reddit-voc/current-release.json"
def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


class DataReleaseBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)
        self.freshness_path = self.temp / "freshness.json"
        self.output = self.temp / "current-release.json"
        current = json.loads(CURRENT_POINTER.read_text(encoding="utf-8"))
        self.auxiliary = {
            key: current["datasets"][key]["dataset_version"]
            for key in ("brand_health", "quarter_insights", "casebook")
        }
        base_manifest = json.loads(
            (
                PUBLIC
                / current["datasets"]["base"]["manifest_path"]
            ).read_text(encoding="utf-8")
        )
        self.core_pointer = self.temp / "core-current-release-v1.json"
        _write(
            self.core_pointer,
            {
                "schema_version": "reddit_voc_current_release_v1",
                "release_id": "reddit_voc_release_fixture_core_v1",
                "generated_at_utc": current["generated_at_utc"],
                "datasets": {
                    key: deepcopy(current["datasets"][key])
                    for key in ("base", "insights", "reports", "personas")
                },
                "cases": deepcopy(current["cases"]),
                "boundaries": deepcopy(current["boundaries"]),
            },
        )
        self.freshness = {
            "schema_version": "reddit_voc_data_freshness_v1",
            "status": "partial",
            "timezone": "Asia/Shanghai",
            "data_as_of_utc": "2026-07-18T23:00:00Z",
            "window_start_utc": "2026-07-17T23:00:00Z",
            "window_end_utc": "2026-07-18T23:00:00Z",
            "collector_run_id": "daily_collect_20260719_0700",
            "source_batch_id": "daily_collect_20260719_0700",
            "center_snapshot_id": base_manifest["source_snapshot_id"],
            "net_new": {
                "posts": 12,
                "comments": 61,
                "updated_historical_posts": 3,
                "repaired_parent_links": 1,
            },
            "coverage": {
                "full_posts": 9,
                "partial_posts": 3,
                "unresolved_continuations": 3,
            },
            "boundaries": {
                "provider_call": False,
                "database_write": False,
                "remote_write": False,
                "live_send": False,
                "deploy": False,
                "production_unchanged": True,
            },
        }
        _write(self.freshness_path, self.freshness)

    def _build(self) -> dict[str, object]:
        return build_data_release(
            public_root=PUBLIC,
            core_pointer_path=self.core_pointer,
            auxiliary_versions=self.auxiliary,
            auxiliary_manifest_sha256s={
                key: _sha(PUBLIC / "data/reddit-voc" / version / "manifest.json")
                for key, version in self.auxiliary.items()
            },
            freshness_path=self.freshness_path,
            release_id="reddit_voc_release_20260719_data_v2",
            generated_at_utc="2026-07-19T00:00:00Z",
        )

    def test_builds_seven_dataset_pointer_with_explicit_freshness(self) -> None:
        pointer = self._build()
        self.assertEqual(pointer["schema_version"], "reddit_voc_current_release_v2")
        self.assertEqual(
            set(pointer["datasets"]),
            {
                "base",
                "insights",
                "reports",
                "personas",
                "brand_health",
                "quarter_insights",
                "casebook",
            },
        )
        self.assertEqual(pointer["freshness"]["status"], "partial")
        self.assertEqual(pointer["freshness"]["net_new"]["posts"], 12)
        self.assertEqual(pointer["freshness"]["center_snapshot_id"], self.freshness["center_snapshot_id"])

    def test_rejects_non_24_hour_or_non_0700_window(self) -> None:
        invalid = deepcopy(self.freshness)
        invalid["window_start_utc"] = "2026-07-18T00:00:00Z"
        _write(self.freshness_path, invalid)
        with self.assertRaisesRegex(DataReleaseContractError, "freshness_window_invalid"):
            self._build()

    def test_rejects_partial_rows_claimed_as_full(self) -> None:
        invalid = deepcopy(self.freshness)
        invalid["status"] = "full"
        _write(self.freshness_path, invalid)
        with self.assertRaisesRegex(DataReleaseContractError, "freshness_partial_status_mismatch"):
            self._build()

    def test_empty_success_requires_and_preserves_zero_delta(self) -> None:
        empty = deepcopy(self.freshness)
        empty["status"] = "empty_success"
        empty["net_new"] = {
            "posts": 0,
            "comments": 0,
            "updated_historical_posts": 0,
            "repaired_parent_links": 0,
        }
        empty["coverage"] = {
            "full_posts": 0,
            "partial_posts": 0,
            "unresolved_continuations": 0,
        }
        _write(self.freshness_path, empty)
        pointer = self._build()
        self.assertEqual(pointer["freshness"]["status"], "empty_success")
        self.assertEqual(sum(pointer["freshness"]["net_new"].values()), 0)

        empty["net_new"]["comments"] = 1
        _write(self.freshness_path, empty)
        with self.assertRaisesRegex(
            DataReleaseContractError, "freshness_empty_success_has_delta"
        ):
            self._build()

    def test_rejects_auxiliary_manifest_hash_drift(self) -> None:
        hashes = {
            key: _sha(PUBLIC / "data/reddit-voc" / version / "manifest.json")
            for key, version in self.auxiliary.items()
        }
        hashes["brand_health"] = "0" * 64
        with self.assertRaisesRegex(DataReleaseContractError, "brand_health_manifest_sha256_mismatch"):
            build_data_release(
                public_root=PUBLIC,
                core_pointer_path=self.core_pointer,
                auxiliary_versions=self.auxiliary,
                auxiliary_manifest_sha256s=hashes,
                freshness_path=self.freshness_path,
                release_id="reddit_voc_release_20260719_data_v2",
                generated_at_utc="2026-07-19T00:00:00Z",
            )

    def test_pointer_write_is_immutable_and_replay_safe(self) -> None:
        pointer = self._build()
        self.assertEqual(write_immutable_pointer(self.output, pointer), "created")
        self.assertEqual(write_immutable_pointer(self.output, pointer), "no_change")
        drifted = deepcopy(pointer)
        drifted["release_id"] = "reddit_voc_release_20260719_data_v2_drift"
        with self.assertRaisesRegex(DataReleaseContractError, "pointer_immutable_collision"):
            write_immutable_pointer(self.output, drifted)


if __name__ == "__main__":
    unittest.main()
