from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.freeze_reddit_incremental_inputs import (
    IncrementalFreezeError,
    build_freeze,
    write_freeze,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value) + b"\n")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _identity_hash(values: list[str]) -> str:
    return sha256(
        "".join(f"{value}\n" for value in sorted(set(values))).encode("utf-8")
    ).hexdigest()


def _identity(ids: list[str]) -> dict:
    return {
        "schema_version": "reddit_voc_v2_identity_freeze_v1",
        "identity_sets": [
            {
                "set_id": "discovery_only",
                "count": len(ids),
                "lf_sha256": _identity_hash(ids),
                "post_ids": ids,
            }
        ],
        "boundaries": {
            "provider_call": False,
            "remote_write": False,
            "database_write": False,
            "production_merge": False,
            "live_send": False,
            "deployment": False,
        },
    }


class IncrementalInputFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.previous_path = self.root / "inputs/previous.json"
        self.candidate_path = self.root / "inputs/candidate.json"
        self.raw_path = self.root / "inputs/raw.json"
        self.config_path = self.root / "config/dictionary.csv"
        self.config_path.parent.mkdir(parents=True)
        self.config_path.write_text("tag_id,keyword\nA,fixture\n", encoding="utf-8")
        self.previous_ids = ["abcde"]
        self.candidate_ids = ["abcde", "fghij"]
        _write(self.previous_path, _identity(self.previous_ids))
        _write(self.candidate_path, _identity(self.candidate_ids))
        self._write_raw()

    def _write_raw(
        self,
        *,
        candidate_ids: list[str] | None = None,
        failed_reports: int = 0,
    ) -> None:
        ids = self.candidate_ids if candidate_ids is None else candidate_ids
        posts = [
            {
                "post_id": post_id,
                "coverage_grade": "full",
            }
            for post_id in ids
        ]
        _write(
            self.raw_path,
            {
                "schema_version": "reddit_voc_v2_raw_snapshot_v1",
                "status": "complete" if not failed_reports else "blocked",
                "target": {
                    "set_id": "discovery_only",
                    "count": len(ids),
                    "post_ids_sha256": _identity_hash(ids),
                    "identity_inventory_sha256": _sha(self.candidate_path),
                },
                "accounting": {
                    "canonical_post_count": len(posts),
                    "canonical_comment_count": 0,
                    "canonical_analysis_count": len(posts),
                    "target_search_row_rejection_count": 0,
                    "lineage_missing_post_ids": [],
                    "first_page_missing_post_ids": [],
                    "blockers": {
                        "lineage_missing": 0,
                        "search_post_conflicts": 0,
                        "outside_target_window": 0,
                        "first_page_missing": 0,
                        "cursor_outstanding": 3,
                        "cursor_cycles": 0,
                        "page_pagination_outstanding": 2,
                        "orphan_reply_reports": 0,
                        "report_conflicts": 0,
                        "comment_conflicts": 0,
                        "failed_reports": failed_reports,
                    },
                },
                "posts": posts,
                "comments": [],
                "analyses": [{"id": post_id} for post_id in ids],
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

    def _build(self) -> dict:
        return build_freeze(
            project_root=self.root,
            freeze_id="reddit_voc_incremental_freeze_20260716_abc123",
            generated_at_utc="2026-07-16T02:03:04Z",
            source_cutoff_utc="2026-07-16T02:00:00+00:00",
            report_anchor_date="2026-07-16",
            identity_set_id="discovery_only",
            previous_identity_path=self.previous_path,
            candidate_identity_path=self.candidate_path,
            raw_snapshot_path=self.raw_path,
            artifacts=[("tag_dictionary", self.config_path)],
        )

    def test_freezes_monotonic_delta_and_explicit_coverage_debt(self) -> None:
        value = self._build()

        self.assertEqual(value["identity"]["previous_count"], 1)
        self.assertEqual(value["identity"]["candidate_count"], 2)
        self.assertEqual(value["identity"]["added_count"], 1)
        self.assertEqual(value["coverage"]["cursor_outstanding"], 3)
        self.assertEqual(value["coverage"]["page_pagination_outstanding"], 2)
        self.assertFalse(value["boundaries"]["deploy"])
        self.assertEqual(
            set(value["artifacts"]),
            {
                "previous_identity_freeze",
                "candidate_identity_freeze",
                "v2_raw_snapshot",
                "tag_dictionary",
            },
        )

    def test_rejects_identity_regression_without_tombstone(self) -> None:
        _write(self.previous_path, _identity(["abcde", "fghij"] ))
        _write(self.candidate_path, _identity(["abcde"]))
        self._write_raw(candidate_ids=["abcde"])

        with self.assertRaisesRegex(
            IncrementalFreezeError, "identity_regression_without_tombstone"
        ):
            self._build()

    def test_rejects_raw_target_not_bound_to_candidate_identity(self) -> None:
        value = json.loads(self.raw_path.read_text(encoding="utf-8"))
        value["target"]["identity_inventory_sha256"] = "0" * 64
        _write(self.raw_path, value)

        with self.assertRaisesRegex(
            IncrementalFreezeError, "raw_snapshot_target_mismatch"
        ):
            self._build()

    def test_rejects_fatal_report_failure(self) -> None:
        self._write_raw(failed_reports=1)

        with self.assertRaisesRegex(
            IncrementalFreezeError, "raw_snapshot_failed_reports_not_admissible"
        ):
            self._build()

    def test_exact_second_write_is_no_change_without_mtime_change(self) -> None:
        destination = self.root / "frozen/input-freeze.json"
        value = self._build()
        self.assertEqual(write_freeze(destination, value), "created")
        first_mtime = destination.stat().st_mtime_ns

        self.assertEqual(write_freeze(destination, value), "no_change")
        self.assertEqual(destination.stat().st_mtime_ns, first_mtime)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
