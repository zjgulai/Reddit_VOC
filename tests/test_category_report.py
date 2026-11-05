"""Category report builder tests (Wave 1 T12, cap72 skeleton).

The report is static + provisional by design (plan §1 11-16 diff column):
26 indicators render as 4 available + 22 explicitly unavailable, conclusions
cite their inputs, and a conclusion citing an input the release does not
contain must fail the build — never render an untraceable claim.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "build_category_report", ROOT / "scripts" / "build_category_report.py"
)
bcr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bcr)

FIXTURE_REPORTS_VERSION = "reddit_voc_reports_test_v1"


def _fake_pointer() -> dict:
    return {
        "release_id": "reddit_voc_release_test",
        "freshness": {"data_as_of_utc": "2026-11-04T23:00:00Z"},
        "datasets": {
            "reports": {
                "dataset_version": FIXTURE_REPORTS_VERSION,
                "public_manifest_sha256": "a" * 64,
            }
        },
    }


def _fake_daily() -> dict:
    def ind(mid, name, status, value):
        return {"metric_id": mid, "name_cn": name, "current": {"status": status, "value": value}}

    return {
        "indicators": [
            ind("RV-BR-01", "观察量", "available", 54.0),
            ind("RV-BR-02", "负向率", "available", 3.7),
            ind("RV-BR-04", "推荐表达率", "available", 22.22),
            ind("RV-BR-05", "竞品语境占比", "available", 100.0),
            ind("RV-BR-03", "净情感", "unavailable", None),
        ]
        + [ind(f"RV-CI-0{n}", f"占位{n}", "unavailable", None) for n in range(1, 8)]
        + [ind(f"RV-DH-0{n}", f"占位{n}", "unavailable", None) for n in range(1, 6)]
        + [ind(f"RV-IN-0{n}", f"占位{n}", "unavailable", None) for n in range(1, 6)]
        + [ind(f"RV-PS-0{n}", f"占位{n}", "unavailable", None) for n in range(1, 5)]
    }


class CategoryReportTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.mkdtemp()
        self.out = Path(self._dir) / "report"
        # Minimal synthetic index satisfying the conclusions' query-index refs.
        import sqlite3

        self.index = Path(self._dir) / "index.sqlite3"
        conn = sqlite3.connect(self.index)
        conn.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE post_bindings (post_id TEXT, binding_level TEXT, product_family_id TEXT, exact_spu_id TEXT);"
            "CREATE TABLE comments (comment_id TEXT PRIMARY KEY, post_id TEXT, sentiment_label TEXT);"
        )
        conn.executemany("INSERT INTO meta VALUES (?,?)", [
            ("data_as_of_utc", "2026-11-04T23:00:00Z"),
            ("release_token", "t:t"),
            ("release_id", "reddit_voc_release_test"),
        ])
        conn.execute("INSERT INTO post_bindings VALUES ('p1','spu_exact','m9-mobile-flow','SPU000168')")
        conn.execute("INSERT INTO post_bindings VALUES ('p2','product_family','m5-smart',NULL)")
        conn.executemany("INSERT INTO comments VALUES (?,?,?)", [
            ("c1", "p2", "negative"), ("c2", "p2", "positive"),
        ])
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._dir, ignore_errors=True)

    def _build(self) -> dict:
        with patch.object(bcr, "_fetch_json", side_effect=[_fake_pointer(), _fake_daily()]):
            return bcr.build(self.out, index_path=self.index)

    def test_builds_with_availability_split(self) -> None:
        receipt = self._build()
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["indicators_available"], 4)
        self.assertEqual(receipt["indicators_unavailable"], 22)
        self.assertEqual(receipt["conclusions"], len(bcr.CONCLUSIONS))
        html_text = Path(receipt["output"]).read_text(encoding="utf-8")
        self.assertIn("provisional v1", html_text)
        self.assertIn("RV-BR-01", html_text)
        self.assertIn("unavailable", html_text)
        # Unavailable rows must not render a bare 0.
        self.assertNotIn("<td class='num'>0.0</td>", html_text)

    def test_report_receipt_is_written(self) -> None:
        receipt = self._build()
        saved = json.loads((self.out / "build-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["report_token"], receipt["report_token"])

    def test_conclusion_citing_unknown_indicator_fails_build(self) -> None:
        broken = (
            {
                "id": "CR-BAD",
                "text": "引用不存在的指标。",
                "inputs": ["reports:RV-XX-99"],
                "confidence": "provisional",
            },
        )
        with patch.object(bcr, "_fetch_json", side_effect=[_fake_pointer(), _fake_daily()]):
            with patch.object(bcr, "CONCLUSIONS", broken):
                with self.assertRaises(SystemExit) as ctx:
                    bcr.build(self.out, index_path=Path(self._dir) / "no-index.sqlite3")
        self.assertIn("RV-XX-99", str(ctx.exception))

    def test_conclusion_citing_index_fact_requires_index(self) -> None:
        # Without an index, query-index-cited conclusions cannot trace their
        # inputs — the build must fail rather than render the claim.
        with patch.object(bcr, "_fetch_json", side_effect=[_fake_pointer(), _fake_daily()]):
            with self.assertRaises(SystemExit):
                bcr.build(self.out, index_path=Path(self._dir) / "no-index.sqlite3")

    def test_index_missing_cited_family_fails_build(self) -> None:
        # An index whose facts don't cover a cited family (m5-smart absent)
        # must fail the assertion gate instead of rendering.
        import sqlite3

        partial = Path(self._dir) / "partial.sqlite3"
        conn = sqlite3.connect(partial)
        conn.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE post_bindings (post_id TEXT, binding_level TEXT, product_family_id TEXT, exact_spu_id TEXT);"
            "CREATE TABLE comments (comment_id TEXT PRIMARY KEY, post_id TEXT, sentiment_label TEXT);"
        )
        conn.executemany("INSERT INTO meta VALUES (?,?)", [
            ("data_as_of_utc", "2026-11-04T23:00:00Z"),
            ("release_token", "t:t"),
            ("release_id", "reddit_voc_release_test"),
        ])
        conn.commit()
        conn.close()
        with patch.object(bcr, "_fetch_json", side_effect=[_fake_pointer(), _fake_daily()]):
            with self.assertRaises(SystemExit):
                bcr.build(self.out, index_path=partial)


if __name__ == "__main__":
    unittest.main()
