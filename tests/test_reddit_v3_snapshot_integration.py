from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_reddit_insights_snapshot import (
    _v3_assert_public_insights_safe,
    _v3_public_storyline,
    build_v3_insights_snapshot,
    write_v3_insights_snapshot,
)
from scripts.build_reddit_reports_snapshot import (
    V3ReportsBuildError,
    _v3_assert_privacy_safe,
    build_v3_reports_snapshot,
    load_v3_metrics_binding,
    write_v3_reports_snapshot,
)
from scripts.validate_reddit_insights_snapshot import (
    V3InsightsValidationError,
    validate_v3_insights_snapshot,
)
from scripts.validate_reddit_reports_snapshot import (
    V3ReportsValidationError,
    validate_v3_reports_snapshot,
)
from reddit_voc.v3_reporting_periods import complete_period_windows


BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}
INDICATOR_IDS = tuple(
    [f"RV-DH-{index:02d}" for index in range(1, 6)]
    + [f"RV-BR-{index:02d}" for index in range(1, 6)]
    + [f"RV-PS-{index:02d}" for index in range(1, 5)]
    + [f"RV-IN-{index:02d}" for index in range(1, 6)]
    + [f"RV-CI-{index:02d}" for index in range(1, 8)]
)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _metrics_fixture(root: Path) -> tuple[Path, Path, dict, str, str]:
    metrics_root = root / "metrics"
    metrics_root.mkdir()
    source_snapshot_id = "fixture-v3-periodized-contract"
    lineage = {
        "source_facts_manifest_sha256": "4" * 64,
        "source_snapshot_id": source_snapshot_id,
    }
    metrics = {
        "boundaries": BOUNDARIES,
        "core_indicator_count": 19,
        "indicator_count": 26,
        "indicators": [
            {"reddit_indicator_id": metric_id} for metric_id in INDICATOR_IDS
        ],
        "integrity_indicator_count": 7,
        "lineage": lineage,
        "period": "all_observed_history",
        "registry_version": "fixture-registry",
        "schema_version": "reddit_voc_metrics_snapshot_v1",
        "scope": "canonical_observation_pool",
    }
    brand_health = {
        "boundaries": BOUNDARIES,
        "lineage": lineage,
        "period": "all_observed_history",
        "schema_version": "reddit_voc_brand_health_index_v2",
        "scope": "momcozy",
    }
    _write(metrics_root / "metrics.json", metrics)
    _write(metrics_root / "brand-health.json", brand_health)
    manifest = {
        "artifact_stage": "metrics_candidate",
        "boundaries": BOUNDARIES,
        "consumption_status": "candidate_pending_independent_validation",
        "core_indicator_count": 19,
        "files": {
            name: {
                "bytes": (metrics_root / name).stat().st_size,
                "sha256": _hash(metrics_root / name),
            }
            for name in ("brand-health.json", "metrics.json")
        },
        "indicator_count": 26,
        "input_sha256": "1" * 64,
        "integrity_indicator_count": 7,
        "promotable": False,
        "registry_sha256": "2" * 64,
        "schema_version": "reddit_voc_metrics_candidate_manifest_v1",
        "source_facts_validation_receipt_sha256": "3" * 64,
    }
    _write(metrics_root / "manifest.json", manifest)
    manifest_sha = _hash(metrics_root / "manifest.json")
    receipt = {
        "boundaries": BOUNDARIES,
        "brand_health_recomputed": True,
        "bundle_manifest_sha256": manifest_sha,
        "deterministic_full_byte_replay": True,
        "indicator_count": 26,
        "input_sha256": "1" * 64,
        "promotable": False,
        "registry_sha256": "2" * 64,
        "schema_version": "reddit_voc_metrics_validation_receipt_v1",
        "source_facts_validation_receipt_sha256": "3" * 64,
        "status": "passed_fixture_only",
    }
    receipt_path = root / "metrics-receipt.json"
    _write(receipt_path, receipt)
    receipt_sha = _hash(receipt_path)
    binding = load_v3_metrics_binding(
        metrics_root,
        receipt_path,
        expected_manifest_sha256=manifest_sha,
        expected_receipt_sha256=receipt_sha,
    )
    return metrics_root, receipt_path, binding, manifest_sha, receipt_sha


def _shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def _period(grain: str, start: date) -> tuple[str, date]:
    if grain == "daily":
        end = start + timedelta(days=1)
    elif grain == "weekly":
        end = start + timedelta(days=7)
    else:
        end = _shift_month(start, 1)
    return f"{grain}:{start.isoformat()}:{end.isoformat()}", start


def _row(
    grain: str,
    period_id: str,
    start: date,
    *,
    metric_id: str,
    value: str | None,
    status: str,
    evidence_ids: list[str] | None = None,
    profile: str = "a" * 64,
) -> dict:
    return {
        "comparison_contract_proven": False,
        "coverage_profile_hash": profile,
        "evidence_ids": evidence_ids or [],
        "grain": grain,
        "metric_id": metric_id,
        "metric_policy_version": "reddit-voc-metrics-v3",
        "name_cn": "产品风险信号" if metric_id == "RV-PS-02" else "覆盖完整度",
        "period_id": period_id,
        "retrieval_contract_hash": "b" * 64,
        "scope": "momcozy",
        "source_calendar_date": (
            start.strftime("%Y-%m") if grain == "monthly" else start.isoformat()
        ),
        "source_selection_profile_hash": "c" * 64,
        "status": status,
        "time_precision": {"daily": "day", "weekly": "week", "monthly": "month"}[
            grain
        ],
        "unavailable_reason_codes": (
            [] if status != "unavailable" else ["metric_unavailable_in_fixture"]
        ),
        "unit": "count",
        "value": value,
        "voc_type": "post_voc",
    }


def _period_series(binding: dict, *, profile_mismatch: bool = False) -> dict:
    windows = complete_period_windows(date(2026, 7, 16))
    rows = []
    for grain, comparison in windows.items():
        if grain == "daily":
            older_start = comparison.current.start - timedelta(days=2)
        elif grain == "weekly":
            older_start = comparison.current.start - timedelta(days=14)
        else:
            older_start = _shift_month(comparison.current.start, -2)
        older_id, older_start = _period(grain, older_start)
        rows.extend(
            [
                _row(
                    grain,
                    older_id,
                    older_start,
                    metric_id="RV-PS-02",
                    value="80",
                    status="available",
                ),
                _row(
                    grain,
                    comparison.previous.period_id,
                    comparison.previous.start,
                    metric_id="RV-PS-02",
                    value="100",
                    status="available",
                    profile="d" * 64 if profile_mismatch else "a" * 64,
                ),
                _row(
                    grain,
                    comparison.current.period_id,
                    comparison.current.start,
                    metric_id="RV-PS-02",
                    value="120",
                    status="available",
                    evidence_ids=[f"fact-{grain}"],
                ),
                _row(
                    grain,
                    comparison.current.period_id,
                    comparison.current.start,
                    metric_id="RV-DH-01",
                    value=None,
                    status="unavailable",
                ),
            ]
        )
        if comparison.year_over_year is not None:
            rows.append(
                _row(
                    grain,
                    comparison.year_over_year.period_id,
                    comparison.year_over_year.start,
                    metric_id="RV-PS-02",
                    value="60",
                    status="available",
                )
            )
    return {
        "as_of_date": "2026-07-16",
        "fixture_only": True,
        "metrics_manifest_sha256": binding["manifest_sha256"],
        "metrics_validation_receipt_sha256": binding["receipt_sha256"],
        "rows": rows,
        "schema_version": "reddit_voc_reporting_metric_series_v3",
        "source_snapshot_id": binding["source_snapshot_id"],
    }


def _evidence_registry(binding: dict) -> dict:
    return {
        "facts": {
            f"fact-{grain}": {
                "snapshot_id": binding["source_snapshot_id"],
                "text": f"fixture evidence {grain}",
            }
            for grain in ("daily", "weekly", "monthly")
        },
        "schema_version": "reddit_voc_evidence_registry_v3",
        "source_snapshot_id": binding["source_snapshot_id"],
    }


def _rehash_file(manifest_path: Path, relative_path: str) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = manifest_path.parent / relative_path
    manifest["files"][relative_path] = {
        "bytes": target.stat().st_size,
        "sha256": _hash(target),
    }
    _write(manifest_path, manifest)


class V3ReportsIntegrationTests(unittest.TestCase):
    def test_public_projection_rejects_raw_identity_or_content_fields(self) -> None:
        _v3_assert_privacy_safe({"metric_id": "RV-BR-01", "value": "12"})
        with self.assertRaisesRegex(V3ReportsBuildError, "prohibited fields"):
            _v3_assert_privacy_safe(
                {"metric_id": "RV-BR-01", "evidence": {"author": "someone"}}
            )

    def test_fixture_reports_expose_labeled_observed_comparisons_without_completeness_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metrics_root, receipt_path, binding, manifest_sha, receipt_sha = (
                _metrics_fixture(root)
            )
            series = _period_series(binding)
            reports, index, manifest = build_v3_reports_snapshot(binding, series)

            self.assertEqual(
                set(reports),
                {
                    f"{role}/{grain}.json"
                    for role in ("current", "archive")
                    for grain in ("daily", "weekly", "monthly")
                },
            )
            self.assertEqual(set(index["reports"]), {"daily", "weekly", "monthly"})
            self.assertNotIn("current", index)
            self.assertNotIn("archive", index)
            self.assertTrue(
                all(
                    descriptor["entry_label"] == "最新完整周期"
                    for descriptor in index["reports"].values()
                )
            )
            self.assertNotIn("当前闭合期", json.dumps(index, ensure_ascii=False))
            self.assertNotIn("闭合归档", json.dumps(index, ensure_ascii=False))
            self.assertEqual(
                reports["current/daily.json"]["period"]["start"], "2026-07-15"
            )
            available = next(
                card
                for card in reports["current/daily.json"]["indicators"]
                if card["metric_id"] == "RV-PS-02"
            )
            self.assertEqual(available["current"]["display"], "120")
            self.assertIsNone(available["direction"])
            self.assertEqual(available["line_color"], "gray")
            for comparison in available["comparisons"].values():
                self.assertNotEqual(comparison["display"], "—")
                self.assertEqual(comparison["status"], "provisional")
                self.assertEqual(comparison["line_color"], "blue")
                self.assertIn(
                    "owner_attestation_missing_observed_same_profile",
                    comparison["reason_codes"],
                )
                self.assertEqual(
                    set(comparison["profile_hashes"]), {"current", "baseline"}
                )
            self.assertEqual(available["sparkline"]["status"], "provisional")
            self.assertEqual(available["sparkline"]["line_color"], "blue")
            self.assertEqual(available["sparkline"]["direction"], "up")
            self.assertFalse(available["sparkline"]["trend_claim_supported"])
            unavailable = next(
                card
                for card in reports["current/daily.json"]["indicators"]
                if card["metric_id"] == "RV-DH-01"
            )
            self.assertEqual(unavailable["current"]["display"], "—")
            self.assertIsNone(unavailable["direction"])

            reports_dir = root / "reports"
            write_v3_reports_snapshot(reports_dir, reports, index, manifest)
            validation = validate_v3_reports_snapshot(
                reports_dir,
                metrics_root,
                receipt_path,
                series,
                expected_metrics_manifest_sha256=manifest_sha,
                expected_metrics_receipt_sha256=receipt_sha,
            )
            self.assertEqual(validation["status"], "passed_fixture_only")
            self.assertTrue(validation["deterministic_full_byte_replay"])
            self.assertFalse(validation["promotable"])

    def test_daily_exact_yoy_falls_back_to_labeled_seven_day_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, binding, _, _ = _metrics_fixture(root)
            series = _period_series(binding)
            windows = complete_period_windows(date(2026, 7, 16))
            daily_yoy_period = windows["daily"].year_over_year.period_id
            for row in series["rows"]:
                if (
                    row["grain"] == "daily"
                    and row["period_id"] == daily_yoy_period
                    and row["metric_id"] == "RV-PS-02"
                ):
                    row["status"] = "unavailable"
                    row["value"] = None
                    row["unavailable_reason_codes"] = ["zero_denominator"]
            reports, _, _ = build_v3_reports_snapshot(binding, series)
            card = next(
                row
                for row in reports["current/daily.json"]["indicators"]
                if row["metric_id"] == "RV-PS-02"
            )
            yoy = card["comparisons"]["year_over_year"]
            self.assertEqual(yoy["comparison_basis"], "seven_day_proxy")
            self.assertEqual(yoy["display_label"], "同比（7日替代窗口）")
            self.assertEqual(yoy["status"], "provisional")
            self.assertEqual(yoy["line_color"], "blue")
            self.assertIn(
                "exact_daily_yoy_unavailable_used_seven_day_proxy",
                yoy["reason_codes"],
            )

    def test_profile_mismatch_is_explained_without_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, binding, _, _ = _metrics_fixture(root)
            reports, _, _ = build_v3_reports_snapshot(
                binding, _period_series(binding, profile_mismatch=True)
            )
            card = next(
                row
                for row in reports["current/daily.json"]["indicators"]
                if row["metric_id"] == "RV-PS-02"
            )
            comparison = card["comparisons"]["period_over_period"]
            self.assertEqual(comparison["display"], "—")
            self.assertIn("coverage_profile_hash_mismatch", comparison["reason_codes"])
            self.assertEqual(
                comparison["profile_hashes"]["current"]["coverage_profile_hash"],
                "a" * 64,
            )
            self.assertEqual(
                comparison["profile_hashes"]["baseline"]["coverage_profile_hash"],
                "d" * 64,
            )

    def test_rehashed_report_tamper_fails_deterministic_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metrics_root, receipt_path, binding, manifest_sha, receipt_sha = (
                _metrics_fixture(root)
            )
            series = _period_series(binding)
            reports, index, manifest = build_v3_reports_snapshot(binding, series)
            reports_dir = root / "reports"
            write_v3_reports_snapshot(reports_dir, reports, index, manifest)
            path = reports_dir / "current/daily.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["indicators"][0]["name_cn"] = "tampered"
            _write(path, document)
            _rehash_file(reports_dir / "manifest.json", "current/daily.json")

            with self.assertRaisesRegex(
                V3ReportsValidationError, "deterministic replay mismatch"
            ):
                validate_v3_reports_snapshot(
                    reports_dir,
                    metrics_root,
                    receipt_path,
                    series,
                    expected_metrics_manifest_sha256=manifest_sha,
                    expected_metrics_receipt_sha256=receipt_sha,
                )

    def test_metrics_receipt_semantic_tamper_is_rejected_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metrics_root, receipt_path, _, manifest_sha, _ = _metrics_fixture(root)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["indicator_count"] = 25
            _write(receipt_path, receipt)
            with self.assertRaisesRegex(
                V3ReportsBuildError, "receipt state is invalid"
            ):
                load_v3_metrics_binding(
                    metrics_root,
                    receipt_path,
                    expected_manifest_sha256=manifest_sha,
                    expected_receipt_sha256=_hash(receipt_path),
                )


class V3InsightsIntegrationTests(unittest.TestCase):
    def test_public_storyline_keeps_aggregate_sections_and_drops_evidence_ids(self) -> None:
        formal = {
            "analysis_frame": {"primary_brand": "Momcozy"},
            "comparison_side": "momcozy",
            "direction_claim_supported": False,
            "grain": "daily",
            "metric_id": "RV-PS-02",
            "period_id": "daily:2026-07-15:2026-07-16",
            "schema_version": "reddit_voc_storyline_v3",
            "snapshot_id": "private-snapshot",
            "storyline_id": "private-storyline",
            "sections": {
                "signal": {
                    "direction": None,
                    "metric_id": "RV-PS-02",
                    "period_id": "daily:2026-07-15:2026-07-16",
                    "scope": "momcozy",
                    "status": "unavailable",
                    "unit": "percent",
                    "value": None,
                    "voc_type": "post_voc+comment_context_voc",
                },
                "root_cause": {
                    "evidence_ids": ["private-entity-1", "private-entity-2"],
                    "statement": "由 2 条受治理内容证据支持",
                    "supported": True,
                },
                "counter_intuitive": {
                    "reason_codes": ["sample_below_minimum"],
                    "statement": "基期不可比",
                    "supported": False,
                },
                "impact": {
                    "sales_causality_supported": False,
                    "statement": "仅描述聚合样本。",
                },
                "action": {
                    "approval_status": "proposed",
                    "owner_role": "VOC Insights",
                    "priority": "P2",
                },
                "monitoring": {
                    "cadence": "daily",
                    "metric_id": "RV-PS-02",
                    "review_date": "2026-07-16",
                },
            },
        }
        public = _v3_public_storyline(formal)
        self.assertNotIn("snapshot_id", public)
        self.assertNotIn("storyline_id", public)
        root_cause = public["sections"]["root_cause"]
        self.assertNotIn("evidence_ids", root_cause)
        self.assertEqual(root_cause["evidence_count"], 2)
        _v3_assert_public_insights_safe(public)

    def test_builds_and_validates_six_part_fail_closed_storylines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metrics_root, receipt_path, binding, manifest_sha, receipt_sha = (
                _metrics_fixture(root)
            )
            series = _period_series(binding)
            reports, index, reports_manifest = build_v3_reports_snapshot(
                binding, series
            )
            reports_dir = root / "reports"
            write_v3_reports_snapshot(
                reports_dir, reports, index, reports_manifest
            )
            registry = _evidence_registry(binding)
            insights, manifest = build_v3_insights_snapshot(
                binding, reports, index, reports_manifest, registry
            )
            self.assertEqual(insights["storyline_count"], 6)
            self.assertTrue(
                all(
                    set(storyline["sections"])
                    == {
                        "signal",
                        "root_cause",
                        "counter_intuitive",
                        "impact",
                        "action",
                        "monitoring",
                    }
                    for storyline in insights["storylines"]
                )
            )
            self.assertTrue(
                all(
                    storyline["direction_claim_supported"] is False
                    and storyline["sections"]["signal"]["direction"] is None
                    for storyline in insights["storylines"]
                )
            )
            available = next(
                row
                for row in insights["storylines"]
                if row["grain"] == "daily" and row["metric_id"] == "RV-PS-02"
            )
            self.assertEqual(
                available["sections"]["root_cause"]["evidence_ids"],
                ["fact-daily"],
            )
            self.assertFalse(
                available["sections"]["counter_intuitive"]["supported"]
            )
            self.assertIn(
                "observed_comparison_not_a_formal_insight_claim",
                available["sections"]["counter_intuitive"]["reason_codes"],
            )

            insights_dir = root / "insights"
            write_v3_insights_snapshot(insights_dir, insights, manifest)
            validation = validate_v3_insights_snapshot(
                insights_dir,
                reports_dir,
                metrics_root,
                receipt_path,
                series,
                registry,
                expected_metrics_manifest_sha256=manifest_sha,
                expected_metrics_receipt_sha256=receipt_sha,
            )
            self.assertEqual(validation["status"], "passed_fixture_only")
            self.assertEqual(validation["storyline_count"], 6)
            self.assertFalse(validation["promotable"])

    def test_rehashed_storyline_tamper_fails_deterministic_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metrics_root, receipt_path, binding, manifest_sha, receipt_sha = (
                _metrics_fixture(root)
            )
            series = _period_series(binding)
            reports, index, reports_manifest = build_v3_reports_snapshot(
                binding, series
            )
            reports_dir = root / "reports"
            write_v3_reports_snapshot(
                reports_dir, reports, index, reports_manifest
            )
            registry = _evidence_registry(binding)
            insights, manifest = build_v3_insights_snapshot(
                binding, reports, index, reports_manifest, registry
            )
            insights_dir = root / "insights"
            write_v3_insights_snapshot(insights_dir, insights, manifest)
            path = insights_dir / "insights.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["storylines"][0]["sections"]["impact"]["statement"] = (
                "tampered"
            )
            _write(path, document)
            _rehash_file(insights_dir / "manifest.json", "insights.json")

            with self.assertRaisesRegex(
                V3InsightsValidationError, "deterministic replay mismatch"
            ):
                validate_v3_insights_snapshot(
                    insights_dir,
                    reports_dir,
                    metrics_root,
                    receipt_path,
                    series,
                    registry,
                    expected_metrics_manifest_sha256=manifest_sha,
                    expected_metrics_receipt_sha256=receipt_sha,
                )


if __name__ == "__main__":
    unittest.main()
