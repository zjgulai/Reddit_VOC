from __future__ import annotations

from contextlib import redirect_stderr
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from scripts.build_reddit_site_snapshot import (
    _append_isolated_staging,
    _append_v2_raw_snapshot,
    _build_parser,
    _fresh_output_directory,
    _generated_at_utc,
    _identity_hash,
    _path_exists,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


class RedditSiteV2FusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.identity_path = self.root / "identity-freeze.json"
        self.raw_path = self.root / "raw-snapshot.json"
        self.target_ids = ["abcde", "fghij"]
        self.missing_ids = ["fghij"]
        self._write_identity()
        self._write_raw()

    def _write_identity(self) -> None:
        _write_json(
            self.identity_path,
            {
                "schema_version": "reddit_voc_v2_identity_freeze_v1",
                "identity_sets": [
                    {
                        "set_id": "discovery_only",
                        "count": len(self.target_ids),
                        "lf_sha256": _identity_hash(self.target_ids),
                        "post_ids": self.target_ids,
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
            },
        )

    def _write_raw(self, *, first_page_missing: list[str] | None = None) -> None:
        identity_sha = sha256(self.identity_path.read_bytes()).hexdigest()
        missing = self.missing_ids if first_page_missing is None else first_page_missing
        _write_json(
            self.raw_path,
            {
                "schema_version": "reddit_voc_v2_raw_snapshot_v1",
                "status": "blocked",
                "target": {
                    "set_id": "discovery_only",
                    "count": len(self.target_ids),
                    "post_ids_sha256": _identity_hash(self.target_ids),
                    "identity_inventory_sha256": identity_sha,
                    "target_window_utc": {
                        "start": "2025-01-01T00:00:00Z",
                        "end": "2026-07-15T16:00:00Z",
                    },
                },
                "accounting": {
                    "canonical_post_count": 1,
                    "canonical_comment_count": 1,
                    "canonical_analysis_count": 2,
                    "target_search_row_rejection_count": 0,
                    "lineage_missing_post_ids": self.missing_ids,
                    "first_page_missing_post_ids": missing,
                    "blockers": {
                        "lineage_missing": 1,
                        "search_post_conflicts": 0,
                        "outside_target_window": 0,
                        "first_page_missing": len(missing),
                        "cursor_outstanding": 1,
                        "cursor_cycles": 0,
                        "page_pagination_outstanding": 1,
                        "orphan_reply_reports": 0,
                        "report_conflicts": 0,
                        "comment_conflicts": 0,
                        "failed_reports": 0,
                    },
                },
                "posts": [
                    {
                        "post_id": "abcde",
                        "title": "fixture title",
                        "selftext": "fixture content",
                        "subreddit": "MomCozy",
                        "source_url": "https://www.reddit.com/r/MomCozy/comments/abcde/fixture/",
                        "created_at_utc": "2026-07-14T00:00:00Z",
                        "score": 3,
                        "num_comments_reported": 2,
                        "parsed_comment_count": 1,
                        "coverage_grade": "partial",
                        "post_content_scope": "search_discovery_only",
                        "author_hash": "a" * 64,
                    }
                ],
                "comments": [
                    {
                        "comment_id": "t1_c1",
                        "post_id": "abcde",
                        "parent_id": "t3_abcde",
                        "body": "fixture comment",
                        "created_at_utc": "2026-07-14T00:01:00Z",
                        "score": 1,
                        "depth": 0,
                        "is_submitter": False,
                        "deleted_or_removed": False,
                        "matched_keywords": [],
                        "author_hash": "b" * 64,
                    }
                ],
                "analyses": [{"analysis_id": "p"}, {"analysis_id": "c"}],
                "privacy": {
                    "raw_payload_embedded": False,
                    "raw_username_embedded": False,
                    "author_identity": "sha256_hash_or_null",
                    "cursor_identity": "sha256_only",
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

    def _admit(
        self,
        posts: dict[str, dict] | None = None,
        comments: dict[str, dict] | None = None,
    ) -> dict:
        return _append_v2_raw_snapshot(
            self.raw_path,
            self.identity_path,
            {} if posts is None else posts,
            {} if comments is None else comments,
        )

    def test_admits_all_hydrated_posts_and_observed_comments_with_explicit_debt(self) -> None:
        posts: dict[str, dict] = {}
        comments: dict[str, dict] = {}

        metadata = self._admit(posts, comments)

        self.assertEqual(set(posts), {"abcde"})
        self.assertEqual(set(comments), {"t1_c1"})
        self.assertEqual(posts["abcde"]["comment_coverage_status"], "observed_first_page")
        self.assertEqual(metadata["admission_status"], "passed_with_partial_comment_coverage")
        self.assertEqual(metadata["identity_set_id"], "discovery_only")
        self.assertEqual(metadata["target_count"], len(self.target_ids))
        self.assertEqual(metadata["target_lf_sha256"], _identity_hash(self.target_ids))
        self.assertEqual(metadata["lineage_gap_count"], 1)
        self.assertEqual(metadata["lineage_gap_post_ids"], self.missing_ids)
        self.assertEqual(
            metadata["lineage_gap_lf_sha256"], _identity_hash(self.missing_ids)
        )
        self.assertEqual(metadata["cursor_outstanding"], 1)
        self.assertEqual(
            metadata["comment_coverage_debt"],
            {
                "cursor_outstanding": 1,
                "page_pagination_outstanding": 1,
                "partial_threads": 1,
            },
        )
        self.assertFalse(metadata["provider_call"])
        self.assertFalse(metadata["database_write"])

    def test_rejects_an_admitted_post_without_first_page(self) -> None:
        self._write_raw(first_page_missing=["abcde", "fghij"])

        with self.assertRaisesRegex(ValueError, "v2_first_page_gap_exceeds_lineage_gap"):
            self._admit()

    def test_rejects_identity_manifest_drift(self) -> None:
        self.identity_path.write_bytes(self.identity_path.read_bytes() + b" ")

        with self.assertRaisesRegex(ValueError, "v2_identity_snapshot_sha256_mismatch"):
            self._admit()

    def test_derives_identity_set_id_from_raw_target(self) -> None:
        identity = json.loads(self.identity_path.read_text(encoding="utf-8"))
        identity["identity_sets"][0]["set_id"] = "task2600_delta"
        _write_json(self.identity_path, identity)
        self._write_raw()
        raw = json.loads(self.raw_path.read_text(encoding="utf-8"))
        raw["target"]["set_id"] = "task2600_delta"
        _write_json(self.raw_path, raw)

        metadata = self._admit()

        self.assertEqual(metadata["identity_set_id"], "task2600_delta")

    def test_rejects_identity_set_self_accounting_drift(self) -> None:
        identity = json.loads(self.identity_path.read_text(encoding="utf-8"))
        identity["identity_sets"][0]["count"] = 3
        _write_json(self.identity_path, identity)
        self._write_raw()

        with self.assertRaisesRegex(
            ValueError, "v2_identity_set_count_or_sha256_mismatch"
        ):
            self._admit()

    def test_dataset_version_is_a_required_cli_argument(self) -> None:
        parser = _build_parser()
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--archive-dir",
                    "archive",
                    "--historical-db",
                    "history.sqlite3",
                    "--production-snapshot",
                    "production.json",
                    "--staging-snapshot",
                    "staging.json",
                    "--v2-raw-snapshot",
                    "v2.json",
                    "--v2-identity-freeze",
                    "identity.json",
                    "--tag-dictionary",
                    "tags.csv",
                    "--product-entity-ledger",
                    "products.json",
                    "--output-dir",
                    "output",
                ]
            )

    def test_generated_at_utc_is_normalized_and_timezone_required(self) -> None:
        self.assertEqual(
            _generated_at_utc("2026-07-15T08:00:00+08:00"),
            "2026-07-15T00:00:00+00:00",
        )
        with self.assertRaisesRegex(ValueError, "generated_at_utc_timezone_missing"):
            _generated_at_utc("2026-07-15T00:00:00")

    def test_fresh_output_is_published_once_and_existing_target_is_rejected(self) -> None:
        output_dir = self.root / "snapshot"
        with _fresh_output_directory(output_dir) as staging_dir:
            self.assertNotEqual(staging_dir, output_dir)
            (staging_dir / "manifest.json").write_text("{}\n", encoding="utf-8")

        self.assertEqual(
            (output_dir / "manifest.json").read_text(encoding="utf-8"), "{}\n"
        )
        self.assertEqual(output_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual(
            (output_dir / "manifest.json").stat().st_mode & 0o777, 0o600
        )
        with self.assertRaisesRegex(FileExistsError, "output_dir_already_exists"):
            with _fresh_output_directory(output_dir):
                self.fail("existing output must not yield a staging directory")

    def test_failed_build_cleans_staging_without_publishing_target(self) -> None:
        output_dir = self.root / "failed-snapshot"
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            with _fresh_output_directory(output_dir) as staging_dir:
                (staging_dir / "partial.json").write_text("{}\n", encoding="utf-8")
                raise RuntimeError("fixture failure")

        self.assertFalse(output_dir.exists())
        self.assertEqual(list(self.root.glob(".failed-snapshot.staging-*")), [])

    def test_publish_race_never_replaces_a_foreign_target(self) -> None:
        output_dir = self.root / "raced-snapshot"

        def hide_only_target(path: Path) -> bool:
            if path == output_dir:
                return False
            return _path_exists(path)

        with mock.patch(
            "scripts.build_reddit_site_snapshot._path_exists",
            side_effect=hide_only_target,
        ), self.assertRaisesRegex(
            FileExistsError, "output_dir_created_during_publish"
        ):
            with _fresh_output_directory(output_dir) as staging_dir:
                (staging_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
                output_dir.mkdir()
                (output_dir / "foreign.txt").write_text(
                    "foreign\n", encoding="utf-8"
                )

        self.assertEqual(
            (output_dir / "foreign.txt").read_text(encoding="utf-8"),
            "foreign\n",
        )
        self.assertEqual(list(self.root.glob(".raced-snapshot.staging-*")), [])


class RedditSiteStagingFusionTests(unittest.TestCase):
    def test_staging_overlay_reports_overlap_and_net_new_counts(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            snapshot_path = Path(temporary_directory) / "staging.json"
            _write_json(
                snapshot_path,
                {
                    "schema_version": "reddit_voc_remote_content_snapshot_v1",
                    "integrity_check": "ok",
                    "quick_check": "ok",
                    "query_only": 1,
                    "identity_snapshot_match": True,
                    "captured_at_utc": "2026-07-15T00:00:00Z",
                    "source": {
                        "environment": "tencent_isolated_staging",
                        "dataset_id": "staging_fixture",
                        "database_sha256": "a" * 64,
                    },
                    "checks": {"fixture_gate": True},
                    "posts": [
                        {
                            "post_id": "abcde",
                            "run_id": "run-1",
                            "title": "same title",
                            "selftext": "longer content",
                            "subreddit": "fixture",
                            "source_url": "https://example.invalid/abcde",
                            "created_at_utc": "2026-07-15T00:00:00Z",
                            "score": 1,
                            "num_comments_reported": 0,
                            "parsed_comment_count": 0,
                            "more_node_count": 0,
                            "coverage_grade": "full",
                            "matched_keywords": [],
                            "media_urls": [],
                            "author_hash": None,
                        },
                        {
                            "post_id": "fghij",
                            "run_id": "run-1",
                            "title": "new title",
                            "selftext": "new content",
                            "subreddit": "fixture",
                            "source_url": "https://example.invalid/fghij",
                            "created_at_utc": "2026-07-15T00:01:00Z",
                            "score": 1,
                            "num_comments_reported": 1,
                            "parsed_comment_count": 1,
                            "more_node_count": 0,
                            "coverage_grade": "full",
                            "matched_keywords": [],
                            "media_urls": [],
                            "author_hash": None,
                        },
                    ],
                    "comments": [
                        {
                            "comment_id": "c1",
                            "post_id": "fghij",
                            "run_id": "run-1",
                            "parent_id": "t3_fghij",
                            "body": "new comment",
                            "created_at_utc": "2026-07-15T00:02:00Z",
                            "score": 1,
                            "depth": 0,
                            "is_submitter": False,
                            "deleted_or_removed": False,
                            "author_hash": None,
                        }
                    ],
                    "analyses": [{"analysis_version": "local_rules_v1"}],
                },
            )
            posts = {
                "abcde": {
                    "title": "same title",
                    "content": "short",
                    "pii_redaction_flags": [],
                    "source_occurrences": [],
                }
            }
            comments: dict[str, dict] = {}

            metadata = _append_isolated_staging(
                snapshot_path,
                posts,
                comments,
            )

            self.assertEqual(metadata["overlap_posts"], 1)
            self.assertEqual(metadata["net_new_posts"], 1)
            self.assertEqual(metadata["net_new_comments"], 1)
            self.assertEqual(metadata["post_content_conflicts"], 1)
            self.assertEqual(metadata["post_content_upgrades"], 1)
            self.assertEqual(posts["abcde"]["content"], "longer content")
            self.assertEqual(set(comments), {"t1_c1"})


if __name__ == "__main__":
    unittest.main()
