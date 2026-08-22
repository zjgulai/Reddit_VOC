from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_existing_post_hydration import (
    HydrationContractError,
    build,
    write_snapshot,
)
from scripts.build_reddit_v2_raw_snapshot import canonical_bytes
from tests.test_reddit_v2_raw_snapshot import (
    OTHER_POST_ID,
    POST_ID,
    _comment_node,
    _comment_payload,
    _comment_report,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _metadata(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}


class RedditExistingPostHydrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.base = self.root / "base"
        self.freeze = self.root / "freeze"
        self.reports = self.freeze / "sources" / "tencent_v2_reports"
        self.discovery = self.root / "discovery.json"
        self.source_manifest = self.freeze / "source-freeze-manifest.json"
        self._write_base()
        self._write_discovery()
        self._write_reports()

    def _write_base(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        _write_json(
            self.base / "posts.json",
            [{"post_id": POST_ID}, {"post_id": OTHER_POST_ID}],
        )
        _write_json(
            self.base / "comments.json",
            [{"comment_id": "t1_c1", "post_id": POST_ID}],
        )
        _write_json(self.base / "quarantine.json", [])
        files = {
            name: _metadata(self.base / name)
            for name in ("posts.json", "comments.json", "quarantine.json")
        }
        _write_json(
            self.base / "manifest.json",
            {
                "schema_version": "reddit_voc_site_snapshot_manifest_v1",
                "dataset_version": "fixture_base",
                "all_checks_passed": True,
                "production_unchanged": True,
                "provider_call": False,
                "live_send": False,
                "canonical_counts": {
                    "posts": 2,
                    "linked_comments": 1,
                    "quarantined_comments": 0,
                    "stored_comments": 1,
                },
                "files": files,
            },
        )

    def _write_discovery(self) -> None:
        _write_json(
            self.discovery,
            {
                "schema_version": "reddit_voc_v2_raw_snapshot_v1",
                "status": "blocked",
                "target": {"set_id": "discovery_only"},
                "posts": [{"post_id": OTHER_POST_ID}],
                "comments": [],
                "privacy": {
                    "raw_payload_embedded": False,
                    "raw_username_embedded": False,
                },
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": False,
                "production_merge": False,
                "live_send": False,
                "git_push": False,
                "dingtalk": False,
            },
        )

    def _write_reports(self) -> None:
        report = _comment_report(
            _comment_payload(
                comments=[
                    _comment_node("c1", "baseline"),
                    _comment_node("c2", "new"),
                ]
            )
        )
        path = self.reports / "task" / "reports" / "comment-repair-probe.json"
        _write_json(path, report)
        relative = path.relative_to(self.freeze).as_posix()
        _write_json(
            self.source_manifest,
            {
                "schema_version": "reddit_voc_candidate_source_freeze_v1",
                "source_cutoff_utc": "2026-07-15T00:00:00Z",
                "boundaries": {
                    "provider_call": False,
                    "provider_attempt_made": False,
                    "database_write": False,
                    "remote_write": False,
                    "deploy": False,
                    "live_send": False,
                },
                "files": [
                    {
                        "destination_relative_path": relative,
                        **_metadata(path),
                    }
                ],
            },
        )

    def _build(self) -> dict:
        return build(
            base_dir=self.base,
            discovery_snapshot=self.discovery,
            source_freeze_manifest=self.source_manifest,
            comment_report_root=self.reports,
        )

    def test_builds_disjoint_existing_post_delta(self) -> None:
        snapshot = self._build()

        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["target"]["base_post_count"], 2)
        self.assertEqual(snapshot["target"]["discovery_post_count"], 1)
        self.assertEqual(snapshot["target"]["existing_post_count"], 1)
        self.assertEqual(
            snapshot["accounting"]["canonical_observed_comment_count"], 2
        )
        self.assertEqual(
            snapshot["accounting"]["baseline_overlap_comment_count"], 1
        )
        self.assertEqual(snapshot["accounting"]["gross_new_comment_count"], 1)
        self.assertEqual(
            [row["comment_id"] for row in snapshot["comments"]], ["t1_c2"]
        )
        self.assertEqual(
            snapshot["post_coverage"],
            [
                {
                    "post_id": POST_ID,
                    "coverage_grade": "full",
                    "observed_comment_count": 2,
                    "cursor_outstanding_count": 0,
                    "page_has_next": False,
                    "failed_report_count": 0,
                }
            ],
        )
        self.assertFalse(snapshot["provider_call"])
        self.assertFalse(snapshot["database_write"])

    def test_rejects_report_member_tamper(self) -> None:
        path = self.reports / "task" / "reports" / "comment-repair-probe.json"
        path.write_bytes(path.read_bytes() + b" ")

        with self.assertRaisesRegex(
            HydrationContractError, "comment_report_freeze_member_mismatch"
        ):
            self._build()

    def test_rejects_base_file_tamper(self) -> None:
        path = self.base / "posts.json"
        path.write_bytes(path.read_bytes() + b" ")

        with self.assertRaisesRegex(
            HydrationContractError, "base_manifest_file_mismatch"
        ):
            self._build()

    def test_rejects_discovery_post_outside_base(self) -> None:
        discovery = json.loads(self.discovery.read_text(encoding="utf-8"))
        discovery["posts"].append({"post_id": "outside"})
        _write_json(self.discovery, discovery)

        with self.assertRaisesRegex(
            HydrationContractError, "discovery_snapshot_partition_invalid"
        ):
            self._build()

    def test_write_is_immutable_and_private(self) -> None:
        snapshot = self._build()
        destination = self.root / "private" / "hydration.json"

        first_sha = write_snapshot(snapshot, destination)
        before = destination.stat()
        second_sha = write_snapshot(snapshot, destination)
        after = destination.stat()

        self.assertEqual(first_sha, second_sha)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertEqual(before.st_ctime_ns, after.st_ctime_ns)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)
        with self.assertRaisesRegex(
            HydrationContractError, "snapshot_destination_conflict"
        ):
            write_snapshot({**snapshot, "status": "changed"}, destination)


if __name__ == "__main__":
    unittest.main()
