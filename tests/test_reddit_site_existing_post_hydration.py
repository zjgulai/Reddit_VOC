from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_site_snapshot import (
    _append_existing_post_hydration,
    _identity_hash,
)


POST_ID = "abcde"
BASE_COMMENT_ID = "t1_base"
NEW_COMMENT_ID = "t1_new"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _canonical_post() -> dict:
    return {
        "post_id": POST_ID,
        "structural_coverage_grade": "partial",
        "source_occurrences": [],
    }


def _canonical_comment(comment_id: str, body: str) -> dict:
    return {
        "comment_id": comment_id,
        "reddit_id": comment_id,
        "post_id": POST_ID,
        "parent_id": f"t3_{POST_ID}",
        "body": body,
        "created_at_utc": "2026-07-14T00:01:00Z",
        "score": 1,
        "depth": 0,
        "is_submitter": False,
        "deleted_or_removed": False,
        "is_bot": None,
        "bot_detection_status": "fixture",
        "author_pseudonym": None,
        "pii_redaction_flags": [],
        "source_occurrences": [],
    }


def _hydration_snapshot() -> dict:
    empty_hash = _identity_hash([])
    return {
        "schema_version": "reddit_voc_existing_post_hydration_v1",
        "status": "complete",
        "source": {
            "base_manifest_sha256": "a" * 64,
            "source_freeze_manifest_sha256": "b" * 64,
        },
        "target": {
            "base_post_count": 1,
            "base_post_ids_lf_sha256": _identity_hash([POST_ID]),
            "base_comment_count": 1,
            "base_comment_ids_lf_sha256": _identity_hash([BASE_COMMENT_ID]),
            "existing_post_count": 1,
            "existing_post_ids_lf_sha256": _identity_hash([POST_ID]),
        },
        "baseline_identity": {
            "base_post_ids": [POST_ID],
            "base_comment_ids": [BASE_COMMENT_ID],
        },
        "accounting": {
            "comment_report_file_count": 0,
            "report_outcome_counts": {
                "accepted_first_page": 0,
                "accepted_reply": 0,
                "accepted_duplicate": 0,
                "rejected_invalid": 0,
                "excluded_non_target": 0,
            },
            "accounted_report_count": 0,
            "gross_new_comment_count": 1,
            "gross_new_comment_ids_lf_sha256": _identity_hash([NEW_COMMENT_ID]),
            "unaccounted_report_count": 0,
            "observed_identity_conserved": True,
            "baseline_identity_conserved": True,
            "failure_reason_counts": {},
            "first_page_missing_post_ids_lf_sha256": empty_hash,
            "cursor_outstanding_keys_lf_sha256": empty_hash,
            "page_pagination_outstanding_post_ids_lf_sha256": empty_hash,
            "failed_report_keys_lf_sha256": empty_hash,
            "coverage_grade_counts": {
                "full": 1,
                "partial": 0,
                "not_observed": 0,
            },
            "blockers": {
                "first_page_missing": 0,
                "cursor_outstanding": 0,
                "page_pagination_outstanding": 0,
                "orphan_reply_reports": 0,
                "cursor_cycles": 0,
                "report_conflicts": 0,
                "comment_conflicts": 0,
                "failed_reports": 0,
            },
        },
        "coverage_work_items": {
            "first_page_missing_post_ids": [],
            "cursor_outstanding": [],
            "page_pagination_outstanding_post_ids": [],
            "failed_reports": [],
            "partial_post_ids": [],
            "not_observed_post_ids": [],
        },
        "comments": [
            {
                "comment_id": NEW_COMMENT_ID,
                "post_id": POST_ID,
                "parent_id": f"t3_{POST_ID}",
                "body": "new body",
                "created_at_utc": "2026-07-14T00:02:00Z",
                "score": 2,
                "depth": 0,
                "is_submitter": False,
                "deleted_or_removed": False,
                "author_hash": "author_sha256:" + "a" * 16,
                "source_payload_sha256s": ["c" * 64],
            }
        ],
        "post_coverage": [
            {
                "post_id": POST_ID,
                "coverage_grade": "full",
                "observed_comment_count": 2,
                "cursor_outstanding_count": 0,
                "page_has_next": False,
                "failed_report_count": 0,
            }
        ],
        "privacy": {
            "raw_payload_embedded": False,
            "raw_username_embedded": False,
            "private_artifact": True,
        },
        "provider_call": False,
        "provider_attempt_made": False,
        "database_write": False,
        "remote_write": False,
        "production_merge": False,
        "deployment": False,
        "git_push": False,
        "live_send": False,
        "dingtalk": False,
        "production_unchanged": True,
    }


class RedditSiteExistingPostHydrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.snapshot_path = self.root / "hydration.json"
        _write_json(self.snapshot_path, _hydration_snapshot())

    def test_appends_only_new_comment_and_does_not_mutate_post_coverage(self) -> None:
        posts = {POST_ID: _canonical_post()}
        before_posts = deepcopy(posts)
        comments = {
            BASE_COMMENT_ID: _canonical_comment(BASE_COMMENT_ID, "base body")
        }

        metadata = _append_existing_post_hydration(
            self.snapshot_path, posts, comments
        )

        self.assertEqual(posts, before_posts)
        self.assertEqual(set(comments), {BASE_COMMENT_ID, NEW_COMMENT_ID})
        self.assertEqual(metadata["release_candidate_comments"], 1)
        self.assertEqual(metadata["preceding_overlap_comments"], 0)
        self.assertEqual(metadata["net_new_comments"], 1)
        self.assertEqual(
            comments[NEW_COMMENT_ID]["bot_detection_status"],
            "unavailable_in_existing_post_hydration",
        )
        self.assertEqual(
            comments[NEW_COMMENT_ID]["author_pseudonym"],
            "anon_aaaaaaaaaa",
        )

    def test_preceding_canonical_comment_wins_without_duplicate_insert(self) -> None:
        posts = {POST_ID: _canonical_post()}
        comments = {
            BASE_COMMENT_ID: _canonical_comment(BASE_COMMENT_ID, "base body"),
            NEW_COMMENT_ID: _canonical_comment(NEW_COMMENT_ID, "preceding body"),
        }

        metadata = _append_existing_post_hydration(
            self.snapshot_path, posts, comments
        )

        self.assertEqual(comments[NEW_COMMENT_ID]["body"], "preceding body")
        self.assertEqual(metadata["preceding_overlap_comments"], 1)
        self.assertEqual(metadata["net_new_comments"], 0)

    def test_rejects_when_production_baseline_comment_is_missing(self) -> None:
        posts = {POST_ID: _canonical_post()}

        with self.assertRaisesRegex(
            ValueError, "existing_hydration_baseline_comment_missing"
        ):
            _append_existing_post_hydration(self.snapshot_path, posts, {})

    def test_rejects_new_comment_parent_outside_baseline_posts(self) -> None:
        snapshot = _hydration_snapshot()
        snapshot["comments"][0]["post_id"] = "fghij"
        _write_json(self.snapshot_path, snapshot)
        posts = {POST_ID: _canonical_post()}
        comments = {
            BASE_COMMENT_ID: _canonical_comment(BASE_COMMENT_ID, "base body")
        }

        with self.assertRaisesRegex(
            ValueError, "existing_hydration_comment_parent_invalid"
        ):
            _append_existing_post_hydration(
                self.snapshot_path, posts, comments
            )

    def test_rejects_malformed_author_hash_token(self) -> None:
        snapshot = _hydration_snapshot()
        snapshot["comments"][0]["author_hash"] = "a" * 64
        _write_json(self.snapshot_path, snapshot)
        posts = {POST_ID: _canonical_post()}
        comments = {
            BASE_COMMENT_ID: _canonical_comment(BASE_COMMENT_ID, "base body")
        }

        with self.assertRaisesRegex(
            ValueError, "existing_hydration_comment_parent_invalid"
        ):
            _append_existing_post_hydration(
                self.snapshot_path, posts, comments
            )

    def test_rejects_page_work_item_not_present_in_post_coverage(self) -> None:
        snapshot = _hydration_snapshot()
        snapshot["coverage_work_items"][
            "page_pagination_outstanding_post_ids"
        ] = [POST_ID]
        snapshot["accounting"]["blockers"][
            "page_pagination_outstanding"
        ] = 1
        snapshot["accounting"][
            "page_pagination_outstanding_post_ids_lf_sha256"
        ] = _identity_hash([POST_ID])
        snapshot["status"] = "blocked_with_explicit_coverage_debt"
        _write_json(self.snapshot_path, snapshot)
        posts = {POST_ID: _canonical_post()}
        comments = {
            BASE_COMMENT_ID: _canonical_comment(BASE_COMMENT_ID, "base body")
        }

        with self.assertRaisesRegex(
            ValueError, "existing_hydration_coverage_post_set_mismatch"
        ):
            _append_existing_post_hydration(
                self.snapshot_path, posts, comments
            )

    def test_rejects_failed_report_reason_summary_mismatch(self) -> None:
        snapshot = _hydration_snapshot()
        failed_row = {
            "post_id": POST_ID,
            "reason": "legacy_reply_source_chain_incomplete",
            "report_sha256": "d" * 64,
        }
        failed_key = sha256(
            json.dumps(
                failed_row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        snapshot["status"] = "blocked_with_explicit_coverage_debt"
        snapshot["accounting"]["comment_report_file_count"] = 1
        snapshot["accounting"]["accounted_report_count"] = 1
        snapshot["accounting"]["report_outcome_counts"][
            "rejected_invalid"
        ] = 1
        snapshot["accounting"]["failure_reason_counts"] = {
            "report_response_validation_failed": 1
        }
        snapshot["accounting"]["failed_report_keys_lf_sha256"] = (
            _identity_hash([failed_key])
        )
        snapshot["accounting"]["coverage_grade_counts"] = {
            "full": 0,
            "partial": 1,
            "not_observed": 0,
        }
        snapshot["accounting"]["blockers"]["failed_reports"] = 1
        snapshot["coverage_work_items"]["failed_reports"] = [failed_row]
        snapshot["coverage_work_items"]["partial_post_ids"] = [POST_ID]
        snapshot["post_coverage"][0]["coverage_grade"] = "partial"
        snapshot["post_coverage"][0]["failed_report_count"] = 1
        _write_json(self.snapshot_path, snapshot)
        posts = {POST_ID: _canonical_post()}
        comments = {
            BASE_COMMENT_ID: _canonical_comment(BASE_COMMENT_ID, "base body")
        }

        with self.assertRaisesRegex(
            ValueError, "existing_hydration_failed_report_mismatch"
        ):
            _append_existing_post_hydration(
                self.snapshot_path, posts, comments
            )


if __name__ == "__main__":
    unittest.main()
