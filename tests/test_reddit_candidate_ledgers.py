from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_candidate_ledgers import (
    CandidateLedgerError,
    _classify_external_post,
    _comment_delta_rows,
    _coverage_row,
    _identity_hash,
    _managed_sha256,
    _post_delta_rows,
    _validated_lineage_gap_ids,
    _validate_coverage_union_rows,
    write_bundle,
)


class RedditCandidateLedgerTests(unittest.TestCase):
    def test_managed_sha_is_order_and_whitespace_stable(self) -> None:
        first = {"title": "Momcozy  pump", "content": "line one\nline two"}
        second = {"content": "line one line two", "title": "Momcozy pump"}

        self.assertEqual(
            _managed_sha256(first, ("title", "content")),
            _managed_sha256(second, ("content", "title")),
        )
        changed = deepcopy(second)
        changed["content"] = "different"
        self.assertNotEqual(
            _managed_sha256(first, ("title", "content")),
            _managed_sha256(changed, ("title", "content")),
        )

    def test_external_post_classification_is_fail_closed(self) -> None:
        start = "2025-01-01T00:00:00Z"
        end = "2026-01-01T00:00:00Z"
        self.assertEqual(
            _classify_external_post(
                [("SubredditPost", "2024-12-31T23:59:59Z", True)],
                start=start,
                end=end,
            ),
            "window_outside_subreddit_post",
        )
        self.assertEqual(
            _classify_external_post(
                [("ProfilePost", "2025-06-01T00:00:00Z", False)],
                start=start,
                end=end,
            ),
            "window_inside_profile_post",
        )
        self.assertEqual(
            _classify_external_post([], start=start, end=end),
            "raw_id_without_strict_search_row",
        )
        self.assertEqual(
            _classify_external_post(
                [("SubredditPost", "2025-06-01T00:00:00Z", True)],
                start=start,
                end=end,
            ),
            "admissible_current_window_subreddit_post",
        )

    def test_post_delta_is_append_only_and_reports_upgrades(self) -> None:
        baseline = {
            "abcde": {
                "post_id": "abcde",
                "title": "same",
                "content": "body",
                "subreddit": "x",
                "permalink": "/r/x/abcde",
                "created_at_utc": "2025-01-01T00:00:00Z",
                "author_pseudonym": None,
            }
        }
        candidate = deepcopy(baseline)
        rows = _post_delta_rows(baseline, candidate, [])
        self.assertEqual(rows[0]["status"], "existing_unchanged")

        candidate["abcde"]["title"] = "upgraded"
        rows = _post_delta_rows(baseline, candidate, [])
        self.assertEqual(rows[0]["status"], "existing_upgraded")

        with self.assertRaisesRegex(CandidateLedgerError, "baseline_post_missing"):
            _post_delta_rows(baseline, {}, [])

        rows = _post_delta_rows(
            baseline,
            candidate,
            [],
            pending_post_ids=["fghij"],
        )
        self.assertEqual(
            {row["post_id"]: row["status"] for row in rows}["fghij"],
            "pending_lineage",
        )

    def test_comment_delta_distinguishes_new_relink_and_retained(self) -> None:
        linked = {
            "t1_linked": {
                "comment_id": "t1_linked",
                "post_id": "abcde",
                "parent_id": "t3_abcde",
                "body": "same",
                "created_at_utc": "2025-01-01T00:00:00Z",
                "deleted_or_removed": False,
                "author_pseudonym": None,
                "include_in_voc_metrics": True,
                "parent_link_status": "linked",
            }
        }
        quarantine = {
            "t1_quarantine": {
                "comment_id": "t1_quarantine",
                "missing_post_id": "missing",
                "reason": "post_attach_orphan",
            }
        }
        candidate_linked = deepcopy(linked)
        candidate_linked["t1_quarantine"] = {
            "comment_id": "t1_quarantine",
            "post_id": "abcde",
            "parent_id": "t3_abcde",
            "body": "restored",
            "created_at_utc": "2025-01-02T00:00:00Z",
            "deleted_or_removed": False,
            "author_pseudonym": None,
            "include_in_voc_metrics": True,
            "parent_link_status": "linked",
        }
        candidate_linked["t1_new"] = {
            **candidate_linked["t1_quarantine"],
            "comment_id": "t1_new",
        }

        rows = _comment_delta_rows(
            linked,
            quarantine,
            candidate_linked,
            {},
        )
        by_id = {row["comment_id"]: row for row in rows}
        self.assertEqual(by_id["t1_linked"]["status"], "existing_unchanged")
        self.assertEqual(
            by_id["t1_quarantine"]["status"],
            "existing_quarantine_relinked",
        )
        self.assertEqual(by_id["t1_new"]["status"], "new_linked")

    def test_coverage_keys_isolate_work_item_types(self) -> None:
        first = _coverage_row(
            work_type="comment_first_page",
            components=("abcde",),
            status="open_carried",
            reason_code="first_page_missing",
            source="v2",
        )
        cursor = _coverage_row(
            work_type="comment_cursor",
            components=("abcde", "a" * 64),
            status="open_carried",
            reason_code="cursor_outstanding",
            source="v2",
        )
        self.assertNotEqual(first["work_item_key"], cursor["work_item_key"])
        self.assertEqual(cursor["cursor_sha256"], "a" * 64)
        with self.assertRaisesRegex(CandidateLedgerError, "coverage_work_item_invalid"):
            _coverage_row(
                work_type="comment_cursor",
                components=("abcde", "not-a-hash"),
                status="open_carried",
                reason_code="cursor_outstanding",
                source="v2",
            )

    def test_coverage_union_recomputes_counts_and_hashes(self) -> None:
        rows = [
            _coverage_row(
                work_type="comment_first_page",
                components=("abcde",),
                status="open_carried",
                reason_code="first_page_missing",
                source="v2",
            )
        ]
        empty_hash = _identity_hash([])
        first_hash = _identity_hash(["abcde"])
        union = {
            "first_page_missing": 1,
            "first_page_missing_lf_sha256": first_hash,
            "cursor_outstanding": 0,
            "cursor_outstanding_lf_sha256": empty_hash,
            "page_pagination_outstanding": 0,
            "page_pagination_outstanding_lf_sha256": empty_hash,
            "failed_reports": 0,
            "failed_reports_lf_sha256": empty_hash,
            "partial_threads": 1,
            "partial_thread_ids_lf_sha256": first_hash,
            "not_observed_threads": 1,
            "not_observed_thread_ids_lf_sha256": first_hash,
            "key_union_not_numeric_sum": True,
        }
        _validate_coverage_union_rows(rows, union)
        union["first_page_missing_lf_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            CandidateLedgerError, "coverage_union_binding_mismatch"
        ):
            _validate_coverage_union_rows(rows, union)

    def test_coverage_union_uses_work_status_and_failure_evidence(self) -> None:
        failure_sha = "f" * 64
        rows = [
            _coverage_row(
                work_type="comment_first_page",
                components=("abcde",),
                status="closed_success",
                reason_code="first_page_report_validated",
                source="frozen_comment_reports",
                report_sha256="a" * 64,
            ),
            _coverage_row(
                work_type="comment_first_page",
                components=("fghij",),
                status="nonretryable_rejected",
                reason_code="report_response_validation_failed",
                source="frozen_comment_reports",
                report_sha256="b" * 64,
                report_failure_sha256=failure_sha,
            ),
        ]
        empty_hash = _identity_hash([])
        missing_hash = _identity_hash(["fghij"])
        union = {
            "first_page_missing": 1,
            "first_page_missing_lf_sha256": missing_hash,
            "cursor_outstanding": 0,
            "cursor_outstanding_lf_sha256": empty_hash,
            "page_pagination_outstanding": 0,
            "page_pagination_outstanding_lf_sha256": empty_hash,
            "failed_reports": 1,
            "failed_reports_lf_sha256": _identity_hash([failure_sha]),
            "partial_threads": 1,
            "partial_thread_ids_lf_sha256": missing_hash,
            "not_observed_threads": 1,
            "not_observed_thread_ids_lf_sha256": missing_hash,
            "key_union_not_numeric_sum": True,
        }
        _validate_coverage_union_rows(
            rows,
            union,
            partial_post_ids={"fghij"},
        )

    def test_coverage_union_excludes_governed_external_post_work(self) -> None:
        rows = [
            _coverage_row(
                work_type="comment_first_page",
                components=(post_id,),
                status="open_carried",
                reason_code="first_page_missing",
                source="candidate_post_universe",
            )
            for post_id in ("abcde", "fghij")
        ]
        empty_hash = _identity_hash([])
        governed_hash = _identity_hash(["abcde"])
        union = {
            "first_page_missing": 1,
            "first_page_missing_lf_sha256": governed_hash,
            "cursor_outstanding": 0,
            "cursor_outstanding_lf_sha256": empty_hash,
            "page_pagination_outstanding": 0,
            "page_pagination_outstanding_lf_sha256": empty_hash,
            "failed_reports": 0,
            "failed_reports_lf_sha256": empty_hash,
            "partial_threads": 1,
            "partial_thread_ids_lf_sha256": governed_hash,
            "not_observed_threads": 1,
            "not_observed_thread_ids_lf_sha256": governed_hash,
            "key_union_not_numeric_sum": True,
        }
        _validate_coverage_union_rows(
            rows,
            union,
            partial_post_ids={"abcde"},
            governed_post_ids={"abcde"},
        )

    def test_coverage_rejects_derived_duplicate_work_types(self) -> None:
        for work_type, components in (
            ("partial_thread", ("abcde",)),
            ("failed_report", ("f" * 64,)),
        ):
            with self.subTest(work_type=work_type):
                with self.assertRaisesRegex(
                    CandidateLedgerError,
                    "coverage_work_item_invalid",
                ):
                    _coverage_row(
                        work_type=work_type,
                        components=components,
                        status="open_carried",
                        reason_code="derived_duplicate",
                        source="v2",
                    )

    def test_coverage_report_evidence_matches_work_status(self) -> None:
        with self.assertRaisesRegex(
            CandidateLedgerError,
            "coverage_work_item_invalid",
        ):
            _coverage_row(
                work_type="comment_first_page",
                components=("abcde",),
                status="closed_success",
                reason_code="first_page_report_validated",
                source="frozen_comment_reports",
            )
        with self.assertRaisesRegex(
            CandidateLedgerError,
            "coverage_work_item_invalid",
        ):
            _coverage_row(
                work_type="comment_cursor",
                components=("abcde", "a" * 64),
                status="open_carried",
                reason_code="cursor_outstanding",
                source="derived_comment_coverage",
                report_sha256="b" * 64,
            )

    def test_lineage_gap_binding_is_exact_across_identity_raw_and_base(self) -> None:
        candidate_ids = {"abcde", "fghij"}
        raw_post_ids = {"abcde"}
        pending_ids = {"klmno"}
        global_ids = candidate_ids | pending_ids
        discovery_ids = raw_post_ids | pending_ids
        identity = {
            "identity_sets": [
                {
                    "set_id": "discovery_only",
                    "count": len(discovery_ids),
                    "lf_sha256": _identity_hash(discovery_ids),
                    "post_ids": sorted(discovery_ids),
                },
                {
                    "set_id": "global_known",
                    "count": len(global_ids),
                    "lf_sha256": _identity_hash(global_ids),
                    "post_ids": sorted(global_ids),
                }
            ],
            "current_site": {
                "count": len(candidate_ids),
                "lf_sha256": _identity_hash(candidate_ids),
            },
        }
        raw = {
            "target": {
                "count": len(discovery_ids),
                "post_ids_sha256": _identity_hash(discovery_ids),
            },
            "posts": [{"post_id": value} for value in sorted(raw_post_ids)],
            "accounting": {
                "lineage_missing_post_ids": sorted(pending_ids),
            },
        }
        v2_boundary = {
            "target_count": len(discovery_ids),
            "target_lf_sha256": _identity_hash(discovery_ids),
            "admitted_posts": len(raw_post_ids),
            "lineage_gap_count": len(pending_ids),
            "lineage_gap_lf_sha256": _identity_hash(pending_ids),
            "lineage_gap_post_ids": sorted(pending_ids),
        }
        self.assertEqual(
            _validated_lineage_gap_ids(
                identity,
                raw,
                v2_boundary,
                candidate_ids,
            ),
            sorted(pending_ids),
        )

        tampered = deepcopy(raw)
        tampered["accounting"]["lineage_missing_post_ids"] = ["pqrst"]
        with self.assertRaisesRegex(
            CandidateLedgerError,
            "v2_lineage_gap_binding_mismatch",
        ):
            _validated_lineage_gap_ids(
                identity,
                tampered,
                v2_boundary,
                candidate_ids,
            )

    def test_bundle_write_is_private_immutable_and_collision_safe(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "candidate"
            bundle = {
                "source-occurrence-ledger.jsonl": [{"row": 1}],
                "candidate-ledger-manifest.json": {"status": "passed"},
            }
            first = write_bundle(root, bundle)
            before = {
                path.name: (path.stat().st_mtime_ns, path.stat().st_ctime_ns)
                for path in root.iterdir()
            }
            second = write_bundle(root, bundle)
            after = {
                path.name: (path.stat().st_mtime_ns, path.stat().st_ctime_ns)
                for path in root.iterdir()
            }

            self.assertEqual(first, second)
            self.assertEqual(before, after)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertTrue(
                all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
            )
            changed = deepcopy(bundle)
            changed["candidate-ledger-manifest.json"]["status"] = "changed"
            with self.assertRaisesRegex(CandidateLedgerError, "bundle_collision"):
                write_bundle(root, changed)


if __name__ == "__main__":
    unittest.main()
