from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
from pathlib import Path
import tempfile
import unittest

from scripts import validate_reddit_candidate_ledgers as validator


class RedditCandidateLedgerValidatorTests(unittest.TestCase):
    def test_validator_does_not_import_candidate_ledger_builder(self) -> None:
        source = inspect.getsource(validator)
        self.assertNotIn("build_reddit_candidate_ledgers", source)

    def test_coverage_row_requires_exact_report_evidence(self) -> None:
        report_sha = "a" * 64
        failure_sha = "b" * 64
        success = validator._coverage_row(
            "comment_first_page",
            ("abcde",),
            status="closed_success",
            reason="first_page_report_validated",
            source="frozen_comment_reports",
            cutoff="2026-07-15T00:00:00Z",
            input_evidence_sha256="c" * 64,
            report_sha256=report_sha,
        )
        self.assertEqual(success["report_sha256"], report_sha)
        failure = validator._coverage_row(
            "comment_first_page",
            ("abcde",),
            status="nonretryable_rejected",
            reason="report_response_validation_failed",
            source="frozen_comment_reports",
            cutoff="2026-07-15T00:00:00Z",
            input_evidence_sha256="c" * 64,
            report_sha256=report_sha,
            report_failure_sha256=failure_sha,
        )
        self.assertEqual(failure["report_failure_sha256"], failure_sha)
        with self.assertRaisesRegex(
            validator.CandidateLedgerValidationError,
            "coverage_report_evidence_invalid",
        ):
            validator._coverage_row(
                "comment_first_page",
                ("abcde",),
                status="closed_success",
                reason="first_page_report_validated",
                source="frozen_comment_reports",
                cutoff="2026-07-15T00:00:00Z",
                input_evidence_sha256="c" * 64,
            )
        with self.assertRaisesRegex(
            validator.CandidateLedgerValidationError,
            "coverage_report_evidence_invalid",
        ):
            validator._coverage_row(
                "comment_cursor",
                ("abcde", "d" * 64),
                status="nonretryable_rejected",
                reason="legacy_reply_source_chain_incomplete",
                source="frozen_comment_reports",
                cutoff="2026-07-15T00:00:00Z",
                input_evidence_sha256="c" * 64,
                report_sha256=report_sha,
            )

    def test_coverage_rebuilds_report_and_failure_sha_from_frozen_reports(
        self,
    ) -> None:
        report_a = "a" * 64
        report_b = "b" * 64
        cursor = "1" * 64
        failure = {
            "post_id": "fghij",
            "report_kind": "first_page",
            "report_sha256": report_b,
            "reason": "report_response_validation_failed",
        }
        rows = validator._expected_coverage(
            {
                "coverage_ledger": [
                    {
                        "lane_index": 0,
                        "term_sha256": "f" * 64,
                        "terminal": True,
                        "debt": False,
                    }
                ]
            },
            pending_lineage_ids=[],
            post_universe={"abcde", "fghij"},
            scan={
                "first_pages": {"abcde": {"report_sha256": report_a}},
                "replies": {},
                "failures": [failure],
            },
            reachable={"cursor_outstanding": [], "page_has_next": []},
            cutoff="2026-07-15T00:00:00Z",
            input_evidence_sha256="9" * 64,
        )
        by_key = {row["work_item_key"]: row for row in rows}
        self.assertEqual(
            by_key["comment_first_page:abcde"]["report_sha256"], report_a
        )
        rejected = by_key["comment_first_page:fghij"]
        self.assertEqual(rejected["report_sha256"], report_b)
        self.assertEqual(
            rejected["report_failure_sha256"],
            hashlib.sha256(validator._canonical_bytes(failure)).hexdigest(),
        )
        tampered = deepcopy(failure)
        tampered["reason"] = "not_allowed"
        with self.assertRaisesRegex(
            validator.CandidateLedgerValidationError,
            "comment_report_failure_reason_invalid",
        ):
            validator._expected_coverage(
                {"coverage_ledger": []},
                pending_lineage_ids=[],
                post_universe={"fghij"},
                scan={"first_pages": {}, "replies": {}, "failures": [tampered]},
                reachable={"cursor_outstanding": [], "page_has_next": []},
                cutoff="2026-07-15T00:00:00Z",
                input_evidence_sha256="9" * 64,
            )

    def test_source_identity_universe_is_recomputed_and_tamper_closed(self) -> None:
        expected = validator._expected_source_identity_universe(
            raw={
                "posts": [{"post_id": "abcde"}],
                "comments": [{"comment_id": "t1_raw"}],
            },
            hydration={"comments": [{"comment_id": "t1_hyd"}]},
            pending_lineage_ids=["fghij"],
            external_post_ids={"klmno"},
            rejected_comment_rows=[{"comment_id": "t1_rejected"}],
            baseline_comment_ids={"t1_base"},
            candidate_comment_ids={"t1_base", "t1_raw", "t1_hyd"},
        )
        validator._validate_source_identity_universe(expected, expected)
        for field in (
            "v2_raw_posts",
            "v2_lineage_pending_posts",
            "governed_external_rejected_posts",
            "v2_raw_comments",
            "existing_hydration_comments",
            "governed_external_rejected_comments",
        ):
            for nested in ("count", "ids_lf_sha256"):
                with self.subTest(field=field, nested=nested):
                    tampered = deepcopy(expected)
                    tampered[field][nested] = (
                        999 if nested == "count" else "0" * 64
                    )
                    with self.assertRaisesRegex(
                        validator.CandidateLedgerValidationError,
                        "source_identity_universe_invalid",
                    ):
                        validator._validate_source_identity_universe(
                            tampered, expected
                        )
        tampered = deepcopy(expected)
        tampered["candidate_comment_union_exact"] = False
        with self.assertRaisesRegex(
            validator.CandidateLedgerValidationError,
            "source_identity_universe_invalid",
        ):
            validator._validate_source_identity_universe(tampered, expected)

    def test_candidate_coverage_union_recomputes_all_fields_and_partition(
        self,
    ) -> None:
        failure = {
            "post_id": "fghij",
            "report_kind": "first_page",
            "report_sha256": "e" * 64,
            "reason": "report_response_validation_failed",
        }
        raw = {
            "posts": [{"post_id": "abcde", "coverage_grade": "partial"}],
            "accounting": {
                "first_page_missing_post_ids": ["abcde"],
                "cursor_outstanding": [
                    {"post_id": "abcde", "cursor_sha256": "a" * 64}
                ],
                "page_pagination_outstanding_post_ids": ["abcde"],
                "failed_reports": [],
            },
        }
        hydration = {
            "coverage_work_items": {
                "first_page_missing_post_ids": ["fghij"],
                "cursor_outstanding": [
                    {"post_id": "fghij", "cursor_sha256": "b" * 64}
                ],
                "page_pagination_outstanding_post_ids": ["fghij"],
                "failed_reports": [failure],
                "partial_post_ids": ["fghij"],
                "not_observed_post_ids": ["fghij"],
            }
        }
        expected = validator._expected_candidate_coverage_union(
            raw, hydration, governed_post_ids={"abcde", "fghij"}
        )
        validator._validate_candidate_coverage_union(
            {"fusion_accounting": {"comment_coverage_debt_union": expected}},
            raw,
            hydration,
            governed_post_ids={"abcde", "fghij"},
        )
        for field, value in expected.items():
            with self.subTest(field=field):
                tampered = deepcopy(expected)
                if isinstance(value, bool):
                    tampered[field] = not value
                elif isinstance(value, int):
                    tampered[field] = value + 1
                elif isinstance(value, str):
                    tampered[field] = "0" * 64
                else:
                    tampered[field] = {}
                with self.assertRaisesRegex(
                    validator.CandidateLedgerValidationError,
                    "candidate_coverage_union_invalid",
                ):
                    validator._validate_candidate_coverage_union(
                        {
                            "fusion_accounting": {
                                "comment_coverage_debt_union": tampered
                            }
                        },
                        raw,
                        hydration,
                        governed_post_ids={"abcde", "fghij"},
                    )
        raw_outside = deepcopy(raw)
        raw_outside["accounting"]["first_page_missing_post_ids"] = ["zzzzz"]
        with self.assertRaisesRegex(
            validator.CandidateLedgerValidationError,
            "coverage_governed_partition_invalid",
        ):
            validator._expected_candidate_coverage_union(
                raw_outside,
                hydration,
                governed_post_ids={"abcde", "fghij"},
            )

    def test_builder_code_binding_rejects_hash_tamper_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = root / "builder.py"
            code.write_text("print('ok')\n", encoding="utf-8")
            digest = hashlib.sha256(code.read_bytes()).hexdigest()
            self.assertEqual(
                validator._validate_builder_code_binding(code, digest), digest
            )
            with self.assertRaisesRegex(
                validator.CandidateLedgerValidationError,
                "builder_code_binding_invalid",
            ):
                validator._validate_builder_code_binding(code, "0" * 64)
            link = root / "builder-link.py"
            link.symlink_to(code)
            with self.assertRaisesRegex(
                validator.CandidateLedgerValidationError,
                "builder_code_unsafe",
            ):
                validator._validate_builder_code_binding(link, digest)

    def test_lineage_binding_uses_discovery_global_known_and_current_site(
        self,
    ) -> None:
        candidate = {"abcde", "fghij"}
        raw_ids = {"abcde"}
        pending = {"klmno"}
        discovery = raw_ids | pending
        global_known = candidate | pending
        identity_sha = "a" * 64
        identity = {
            "identity_sets": [
                {
                    "set_id": "discovery_only",
                    "count": len(discovery),
                    "lf_sha256": validator._identity_hash(discovery),
                    "post_ids": sorted(discovery),
                },
                {
                    "set_id": "global_known",
                    "count": len(global_known),
                    "lf_sha256": validator._identity_hash(global_known),
                    "post_ids": sorted(global_known),
                },
            ],
            "current_site": {
                "count": len(candidate),
                "lf_sha256": validator._identity_hash(candidate),
            },
        }
        raw = {
            "posts": [{"post_id": value} for value in sorted(raw_ids)],
            "accounting": {"lineage_missing_post_ids": sorted(pending)},
            "target": {
                "count": len(discovery),
                "identity_inventory_sha256": identity_sha,
                "post_ids_sha256": validator._identity_hash(discovery),
            },
        }
        candidate_manifest = {
            "source_boundaries": {
                "tencent_v2_search_hydrated": {
                    "lineage_gap_post_ids": sorted(pending),
                    "lineage_gap_count": len(pending),
                    "lineage_gap_lf_sha256": validator._identity_hash(pending),
                    "target_count": len(discovery),
                    "target_lf_sha256": validator._identity_hash(discovery),
                    "admitted_posts": len(raw_ids),
                }
            }
        }
        self.assertEqual(
            validator._validated_pending_lineage(
                identity=identity,
                identity_sha256=identity_sha,
                raw=raw,
                candidate_manifest=candidate_manifest,
                candidate_post_ids=candidate,
            ),
            sorted(pending),
        )
        for mutation in ("global_known", "current_site"):
            with self.subTest(mutation=mutation):
                tampered = deepcopy(identity)
                if mutation == "global_known":
                    row = next(
                        value
                        for value in tampered["identity_sets"]
                        if value["set_id"] == "global_known"
                    )
                    row["post_ids"] = sorted(candidate)
                    row["count"] = len(candidate)
                    row["lf_sha256"] = validator._identity_hash(candidate)
                else:
                    tampered["current_site"]["lf_sha256"] = "0" * 64
                with self.assertRaisesRegex(
                    validator.CandidateLedgerValidationError,
                    "pending_lineage_binding_invalid",
                ):
                    validator._validated_pending_lineage(
                        identity=tampered,
                        identity_sha256=identity_sha,
                        raw=raw,
                        candidate_manifest=candidate_manifest,
                        candidate_post_ids=candidate,
                    )

    def test_governed_selection_uses_fixed_fields_only(self) -> None:
        shas = [f"{index:064x}" for index in range(1, 10)]
        candidate_manifest = {
            "source_boundaries": {
                "historical_canonical": {"database_sha256": shas[0]},
                "tencent_production_primary": {"snapshot_sha256": shas[1]},
                "tencent_isolated_staging": {"snapshot_sha256": shas[2]},
            },
            "tagging": {
                "dictionary_sha256": shas[3],
                "product_entity_resolution": {"ledger_sha256": shas[4]},
            },
        }
        baseline_manifest = {
            "files": {
                "posts.json": {"sha256": shas[5]},
                "comments.json": {"sha256": shas[6]},
                "quarantine.json": {"sha256": shas[7]},
            }
        }
        expected = set(shas[:8]) | {shas[8]}
        selected = validator._selected_governed_sha256s(
            candidate_manifest, baseline_manifest, shas[8]
        )
        self.assertEqual(selected, expected)
        tampered = deepcopy(candidate_manifest)
        unrelated = "f" * 64
        tampered["unrelated"] = {"arbitrary_sha256": unrelated}
        self.assertEqual(
            validator._selected_governed_sha256s(
                tampered, baseline_manifest, shas[8]
            ),
            expected,
        )
        self.assertNotIn(unrelated, selected)

    def test_receipt_writer_is_private_immutable_and_rerunnable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private-validation"
            receipt = private / "candidate-ledger-validation-receipt.json"
            value = {"schema_version": "receipt-test", "status": "passed"}
            self.assertEqual(
                validator.write_immutable_receipt(receipt, value), "created"
            )
            self.assertEqual(private.stat().st_mode & 0o777, 0o700)
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                validator.write_immutable_receipt(receipt, value), "no_change"
            )
            with self.assertRaisesRegex(
                validator.CandidateLedgerValidationError,
                "receipt_immutable_collision",
            ):
                validator.write_immutable_receipt(
                    receipt, {"schema_version": "receipt-test", "status": "failed"}
                )



if __name__ == "__main__":
    unittest.main()
