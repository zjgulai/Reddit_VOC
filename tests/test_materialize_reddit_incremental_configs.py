from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.materialize_reddit_incremental_configs import (
    IncrementalConfigError,
    materialize_configs,
    write_configs,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class IncrementalConfigMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base_dir = self.root / "base/reddit_voc_site_snapshot_20260716_abc123"
        self.coverage_template = self.root / "templates/coverage.json"
        self.risk_template = self.root / "templates/risk.json"
        self.persona_template = self.root / "templates/personas.json"
        self.ledger_manifest = self.root / "identity/candidate-ledger-manifest.json"
        self.ledger_receipt = self.root / "identity/candidate-ledger-validation-receipt.json"
        self._write_base()
        self._write_identity_gate()
        _write(
            self.coverage_template,
            {
                "schema_version": "reddit_voc_period_coverage_profile_v1",
                "profile_version": "template",
                "reason_codes": ["event_time_coverage_partial"],
            },
        )
        _write(
            self.risk_template,
            {
                "schema_version": "reddit_voc_risk_theme_gate_policy_v1",
                "policy_version": "template",
                "status": "draft",
            },
        )
        _write(
            self.persona_template,
            {
                "schema_version": "reddit_voc_persona_config_v1",
                "config_version": "template",
                "dataset_version": "template",
                "personas": [],
            },
        )

    def _write_base(
        self,
        *,
        validated: bool = True,
        cursor: int = 7,
        page: int = 8,
        manifest_schema: str = "reddit_voc_site_snapshot_manifest_v1",
        union_cursor: int = 7,
        union_page: int = 8,
    ) -> None:
        v2_debt = {
            "cursor_outstanding": cursor,
            "page_pagination_outstanding": page,
            "partial_threads": 9,
        }
        fusion_accounting: dict[str, object] = {
            "v2_comment_coverage_debt": v2_debt,
            "coverage_debt_is_not_zero_filled": True,
        }
        if manifest_schema == "reddit_voc_site_snapshot_manifest_v2":
            fusion_accounting["comment_coverage_debt_union"] = {
                "first_page_missing": 3,
                "first_page_missing_lf_sha256": "3" * 64,
                "cursor_outstanding": union_cursor,
                "cursor_outstanding_lf_sha256": "4" * 64,
                "page_pagination_outstanding": union_page,
                "page_pagination_outstanding_lf_sha256": "5" * 64,
                "failed_reports": 2,
                "failed_reports_lf_sha256": "6" * 64,
                "partial_threads": 4,
                "partial_thread_ids_lf_sha256": "7" * 64,
                "not_observed_threads": 3,
                "not_observed_thread_ids_lf_sha256": "8" * 64,
                "source_counts": {
                    "v2": {
                        "first_page_missing": 1,
                        "cursor_outstanding": cursor,
                        "page_pagination_outstanding": page,
                        "failed_reports": 1,
                    },
                    "existing_post_hydration": {
                        "first_page_missing": 2,
                        "cursor_outstanding": 0,
                        "page_pagination_outstanding": 0,
                        "failed_reports": 1,
                        "partial_threads": 2,
                        "not_observed_threads": 2,
                        "failure_reason_counts": {
                            "response_validation_failed": 1
                        },
                    },
                },
                "key_union_not_numeric_sum": True,
            }
        _write(
            self.base_dir / "manifest.json",
            {
                "schema_version": manifest_schema,
                "dataset_version": "reddit_voc_site_snapshot_20260716_abc123",
                "all_checks_passed": validated,
                "tagging": {
                    "dictionary_version": "dim_tag_v6.3_final",
                    "dictionary_sha256": "1" * 64,
                },
                "semantic_boundaries": {"product_entity_ledger_sha256": "2" * 64},
                "source_boundaries": {
                    "tencent_v2_search_hydrated": {
                        "comment_coverage_debt": {
                            "cursor_outstanding": cursor,
                            "page_pagination_outstanding": page,
                        }
                    }
                },
                "fusion_accounting": fusion_accounting,
            },
        )
        if hasattr(self, "ledger_manifest"):
            self._write_identity_gate()

    def _base_manifest(self) -> dict[str, object]:
        return json.loads(
            (self.base_dir / "manifest.json").read_text(encoding="utf-8")
        )

    def _write_identity_gate(self) -> None:
        base_sha = __import__("hashlib").sha256(
            (self.base_dir / "manifest.json").read_bytes()
        ).hexdigest()
        _write(
            self.ledger_manifest,
            {
                "schema_version": "reddit_voc_candidate_ledger_manifest_v2",
                "status": "a2_identity_closed_with_explicit_coverage_debt",
                "inputs": {"candidate_base_manifest_sha256": base_sha},
                "accounting": {"unaccounted_total": 0},
                "production_unchanged": True,
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": False,
                "remote_write": False,
                "deployment": False,
                "production_merge": False,
                "live_send": False,
            },
        )
        ledger_sha = __import__("hashlib").sha256(
            self.ledger_manifest.read_bytes()
        ).hexdigest()
        _write(
            self.ledger_receipt,
            {
                "schema_version": "reddit_voc_candidate_ledger_validation_receipt_v1",
                "status": "passed",
                "candidate_ledger_manifest_sha256": ledger_sha,
                "input_evidence_sha256": "e" * 64,
                "counts": {"unaccounted_total": 0},
                "production_unchanged": True,
                "provider_call": False,
                "provider_attempt_made": False,
                "database_write": False,
                "remote_write": False,
                "deployment": False,
                "production_merge": False,
                "live_send": False,
            },
        )

    def _materialize(self) -> dict[str, dict]:
        return materialize_configs(
            base_dir=self.base_dir,
            coverage_template_path=self.coverage_template,
            risk_template_path=self.risk_template,
            persona_template_path=self.persona_template,
            personas_dataset_version="reddit_voc_personas_20260716_abc123",
            candidate_ledger_manifest_path=self.ledger_manifest,
            ledger_validation_receipt_path=self.ledger_receipt,
            expected_ledger_validation_receipt_sha256=__import__("hashlib").sha256(
                self.ledger_receipt.read_bytes()
            ).hexdigest(),
        )

    def test_binds_exact_final_identity_gate(self) -> None:
        values = self._materialize()
        identity = values["identity_gate"]
        self.assertEqual(identity["unaccounted_total"], 0)
        self.assertEqual(
            identity["ledger_validation_receipt_sha256"],
            __import__("hashlib").sha256(self.ledger_receipt.read_bytes()).hexdigest(),
        )

    def test_rejects_preliminary_or_wrong_receipt_sha(self) -> None:
        with self.assertRaisesRegex(
            IncrementalConfigError, "ledger_validation_receipt_sha_mismatch"
        ):
            materialize_configs(
                base_dir=self.base_dir,
                coverage_template_path=self.coverage_template,
                risk_template_path=self.risk_template,
                persona_template_path=self.persona_template,
                personas_dataset_version="reddit_voc_personas_20260716_abc123",
                candidate_ledger_manifest_path=self.ledger_manifest,
                ledger_validation_receipt_path=self.ledger_receipt,
                expected_ledger_validation_receipt_sha256="0" * 64,
            )

    def test_binds_all_configs_to_validated_base_and_keeps_risk_draft(self) -> None:
        values = self._materialize()

        self.assertEqual(
            values["coverage"]["applies_to_base_dataset_version"],
            "reddit_voc_site_snapshot_20260716_abc123",
        )
        self.assertTrue(values["coverage"]["search_has_next_truncates_window"])
        self.assertEqual(values["coverage"]["comment_coverage_status"], "mixed")
        self.assertIn(
            "incremental_candidate_coverage_debt_explicit",
            values["coverage"]["reason_codes"],
        )
        self.assertEqual(values["risk"]["status"], "draft")
        self.assertEqual(
            values["personas"]["dataset_version"],
            "reddit_voc_personas_20260716_abc123",
        )

    def test_manifest_v1_uses_fusion_v2_debt_not_source_boundary(self) -> None:
        self._write_base(cursor=0, page=0)
        manifest = self._base_manifest()
        fusion = manifest["fusion_accounting"]
        assert isinstance(fusion, dict)
        fusion["v2_comment_coverage_debt"] = {
            "cursor_outstanding": 7,
            "page_pagination_outstanding": 8,
            "partial_threads": 9,
        }
        _write(self.base_dir / "manifest.json", manifest)
        self._write_identity_gate()

        values = self._materialize()

        self.assertTrue(values["coverage"]["search_has_next_truncates_window"])
        self.assertEqual(values["coverage"]["comment_coverage_status"], "mixed")

    def test_manifest_v1_rejects_incomplete_fusion_debt(self) -> None:
        manifest = self._base_manifest()
        fusion = manifest["fusion_accounting"]
        assert isinstance(fusion, dict)
        debt = fusion["v2_comment_coverage_debt"]
        assert isinstance(debt, dict)
        debt.pop("partial_threads")
        _write(self.base_dir / "manifest.json", manifest)

        with self.assertRaisesRegex(
            IncrementalConfigError, "base_coverage_debt_invalid"
        ):
            self._materialize()

    def test_manifest_v1_partial_threads_keep_comment_coverage_mixed(self) -> None:
        self._write_base(cursor=0, page=0)

        values = self._materialize()

        self.assertFalse(values["coverage"]["search_has_next_truncates_window"])
        self.assertEqual(values["coverage"]["comment_coverage_status"], "mixed")

    def test_manifest_v2_uses_full_union_without_numeric_reaggregation(self) -> None:
        self._write_base(
            manifest_schema="reddit_voc_site_snapshot_manifest_v2",
            cursor=0,
            page=0,
            union_cursor=0,
            union_page=0,
        )

        values = self._materialize()

        self.assertFalse(values["coverage"]["search_has_next_truncates_window"])
        self.assertEqual(values["coverage"]["comment_coverage_status"], "mixed")

    def test_manifest_v2_never_falls_back_when_union_is_missing(self) -> None:
        self._write_base(manifest_schema="reddit_voc_site_snapshot_manifest_v2")
        manifest = self._base_manifest()
        fusion = manifest["fusion_accounting"]
        assert isinstance(fusion, dict)
        fusion.pop("comment_coverage_debt_union")
        _write(self.base_dir / "manifest.json", manifest)

        with self.assertRaisesRegex(
            IncrementalConfigError, "base_coverage_debt_missing"
        ):
            self._materialize()

    def test_manifest_v2_rejects_incomplete_or_derived_union(self) -> None:
        mutations = {
            "missing_count": lambda debt: debt.pop("not_observed_threads"),
            "missing_hash": lambda debt: debt.pop(
                "partial_thread_ids_lf_sha256"
            ),
            "missing_source_counts": lambda debt: debt.pop("source_counts"),
            "missing_v2_source_count": lambda debt: debt["source_counts"][
                "v2"
            ].pop("failed_reports"),
            "missing_hydration_source_count": lambda debt: debt[
                "source_counts"
            ]["existing_post_hydration"].pop("not_observed_threads"),
            "missing_failure_reason_counts": lambda debt: debt["source_counts"][
                "existing_post_hydration"
            ].pop("failure_reason_counts"),
            "numeric_sum_not_disclaimed": lambda debt: debt.__setitem__(
                "key_union_not_numeric_sum", False
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                self._write_base(
                    manifest_schema="reddit_voc_site_snapshot_manifest_v2"
                )
                manifest = self._base_manifest()
                fusion = manifest["fusion_accounting"]
                assert isinstance(fusion, dict)
                debt = fusion["comment_coverage_debt_union"]
                assert isinstance(debt, dict)
                mutate(debt)
                _write(self.base_dir / "manifest.json", manifest)

                with self.assertRaisesRegex(
                    IncrementalConfigError, "base_coverage_debt_invalid"
                ):
                    self._materialize()

    def test_rejects_missing_no_zero_fill_marker(self) -> None:
        manifest = self._base_manifest()
        fusion = manifest["fusion_accounting"]
        assert isinstance(fusion, dict)
        fusion.pop("coverage_debt_is_not_zero_filled")
        _write(self.base_dir / "manifest.json", manifest)

        with self.assertRaisesRegex(
            IncrementalConfigError, "base_coverage_debt_invalid"
        ):
            self._materialize()

    def test_exact_second_publication_is_no_change_and_preserves_mtime(self) -> None:
        output = self.root / "candidate/config"
        values = self._materialize()
        first = write_configs(output, values)
        first_mtime = (output / "manifest.json").stat().st_mtime_ns

        second = write_configs(output, values)

        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "no_change")
        self.assertEqual((output / "manifest.json").stat().st_mtime_ns, first_mtime)
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertTrue(
            all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())
        )

    def test_existing_output_with_public_file_mode_fails_closed(self) -> None:
        output = self.root / "candidate/config"
        values = self._materialize()
        write_configs(output, values)
        (output / "coverage-profile.json").chmod(0o644)

        with self.assertRaisesRegex(IncrementalConfigError, "output_root_collision"):
            write_configs(output, values)

    def test_existing_different_output_fails_closed(self) -> None:
        output = self.root / "candidate/config"
        values = self._materialize()
        write_configs(output, values)
        (output / "coverage-profile.json").write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(IncrementalConfigError, "output_root_collision"):
            write_configs(output, values)

    def test_existing_output_with_extra_empty_directory_fails_closed(self) -> None:
        output = self.root / "candidate/config"
        values = self._materialize()
        write_configs(output, values)
        (output / "unexpected").mkdir()

        with self.assertRaisesRegex(IncrementalConfigError, "output_root_collision"):
            write_configs(output, values)

    def test_rejects_unvalidated_base(self) -> None:
        self._write_base(validated=False)

        with self.assertRaisesRegex(IncrementalConfigError, "base_not_validated"):
            self._materialize()

    def test_rejects_non_draft_risk_template(self) -> None:
        _write(
            self.risk_template,
            {
                "schema_version": "reddit_voc_risk_theme_gate_policy_v1",
                "policy_version": "template",
                "status": "frozen",
            },
        )

        with self.assertRaisesRegex(
            IncrementalConfigError, "risk_template_must_remain_draft"
        ):
            self._materialize()


if __name__ == "__main__":
    unittest.main()
