from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.v3_source_manifest import SourceManifestError, load_source_manifest


ROOT = Path(__file__).resolve().parents[1]
SHA256_A = "a" * 64
SHA256_B = "b" * 64
EXPECTED_HEADERS = (
    "舆情ID",
    "舆情链接",
    "舆情分类",
    "标题",
    "内容概要",
    "产品分类",
    "问题类别",
    "内容类型",
    "相关性",
    "浏览量",
    "浏览量环比",
    "转赞评数量",
    "转赞评数量环比",
    "情感描述",
    "舆情等级",
    "来源",
    "国家",
    "作者",
    "粉丝数量",
    "发布时间",
    "处理状态",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(
    root: Path,
    *,
    source_snapshot_id: str,
    relative_path: str,
    selection_class: str,
    query_profile_status: str,
    allowed_metric_families: list[str],
    blocked_uses: list[str],
) -> dict[str, object]:
    path = root / relative_path
    return {
        "source_snapshot_id": source_snapshot_id,
        "relative_path": relative_path,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "workbook": {
            "sheet_name": "0",
            "expected_dimension": "A1:U2",
            "expected_headers": list(EXPECTED_HEADERS),
            "expected_data_rows": 1,
            "expected_entity_counts": {"comments": 0, "posts": 1},
        },
        "source_kind": "workbook_export",
        "selection_class": selection_class,
        "query_profile_status": query_profile_status,
        "source_timezone_status": "unknown",
        "event_time_precision": "day",
        "selection_window": {
            "start_calendar_date": "2025-07-01",
            "end_calendar_date": "2025-07-01",
        },
        "coverage_status": "owner_attested_complete_scope"
        if selection_class == "owner_attested_complete_scope"
        else "outcome_conditioned_negative",
        "allowed_metric_families": allowed_metric_families,
        "blocked_uses": blocked_uses,
        "selection_reason_codes": [selection_class],
    }


def _manifest_value(root: Path) -> dict[str, object]:
    (root / "full.xlsx").write_bytes(b"full-workbook")
    (root / "negative.xlsx").write_bytes(b"negative-workbook")
    base_root = root / "base"
    base_root.mkdir(exist_ok=True)
    public_manifest = base_root / "manifest-public.json"
    public_manifest.write_text(
        json.dumps(
            {
                "dataset_version": "reddit_voc_site_snapshot_20260715_candidate_a2",
                "projection": {"audience": "public_ui"},
                "schema_version": "reddit_voc_site_snapshot_manifest_v2",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    lineage_manifest = base_root / "manifest.json"
    lineage_manifest.write_text(
        json.dumps(
            {
                "dataset_version": "reddit_voc_site_snapshot_20260715_candidate_a2",
                "schema_version": "reddit_voc_site_snapshot_manifest_v2",
                "source_boundaries": {},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    attestation = {
        "attestation_id": "owner-attested-complete-scope-20260716",
        "attested_at_calendar_date": "2026-07-16",
        "statement_cn": "完整范围导出，未按情感、严重度、互动量或人工案例筛选",
        "applies_to_source_snapshot_ids": ["reddit_add_data_full_20260715"],
    }
    return {
        "schema_version": "reddit_voc_source_manifest_v1",
        "dataset_id": "reddit_add_data_20260715_v1",
        "base": {
            "dataset_version": "reddit_voc_site_snapshot_20260715_candidate_a2",
            "lineage_manifest_relative_path": "base/manifest.json",
            "manifest_relative_path": "base/manifest-public.json",
            "public_manifest_sha256": _sha256(public_manifest),
            "lineage_manifest_sha256": _sha256(lineage_manifest),
        },
        "owner_attestation": {
            **attestation,
            "sha256": hashlib.sha256(canonical_json_bytes(attestation)).hexdigest(),
        },
        "sources": [
            _source(
                root,
                source_snapshot_id="reddit_add_data_full_20260715",
                relative_path="full.xlsx",
                selection_class="owner_attested_complete_scope",
                query_profile_status="owner_attested_unknown",
                allowed_metric_families=["momcozy_internal_single_period"],
                blocked_uses=[
                    "cross_brand_visibility",
                    "market_share",
                    "rv_in_05",
                    "sov",
                    "trend",
                ],
            ),
            _source(
                root,
                source_snapshot_id="reddit_add_data_negative_20260715",
                relative_path="negative.xlsx",
                selection_class="outcome_conditioned_negative",
                query_profile_status="not_applicable",
                allowed_metric_families=[],
                blocked_uses=[
                    "brand_health",
                    "cross_brand_visibility",
                    "market_share",
                    "momcozy_internal_single_period",
                    "rv_in_05",
                    "sov",
                    "trend",
                ],
            ),
        ],
        "boundaries": {
            "provider_call": False,
            "database_write": False,
            "remote_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
        },
    }


def _write_manifest(root: Path, value: dict[str, object]) -> Path:
    path = root / "source-manifest.json"
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


class SourceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_owner_attested_unknown_is_single_period_momcozy_only(self) -> None:
        manifest = load_source_manifest(
            _write_manifest(self.root, _manifest_value(self.root)),
            self.root,
        )

        source = manifest.source("reddit_add_data_full_20260715")

        self.assertEqual(source.query_profile_status, "owner_attested_unknown")
        self.assertEqual(
            source.allowed_metric_families,
            ("momcozy_internal_single_period",),
        )
        self.assertEqual(
            source.blocked_uses,
            (
                "cross_brand_visibility",
                "market_share",
                "rv_in_05",
                "sov",
                "trend",
            ),
        )
        self.assertEqual(source.expected_headers, EXPECTED_HEADERS)
        self.assertTrue(manifest.boundaries.production_unchanged)

    def test_negative_selected_source_cannot_enter_business_metrics(self) -> None:
        value = _manifest_value(self.root)
        value["sources"][1]["allowed_metric_families"] = [  # type: ignore[index]
            "momcozy_internal_single_period"
        ]

        with self.assertRaisesRegex(
            SourceManifestError,
            "negative-selected source cannot allow metrics",
        ):
            load_source_manifest(_write_manifest(self.root, value), self.root)

    def test_allowed_and_blocked_metric_families_cannot_overlap(self) -> None:
        value = _manifest_value(self.root)
        blocked = value["sources"][0]["blocked_uses"]  # type: ignore[index]
        blocked.append("momcozy_internal_single_period")
        blocked.sort()

        with self.assertRaisesRegex(
            SourceManifestError,
            "allowed and blocked metric families overlap",
        ):
            load_source_manifest(_write_manifest(self.root, value), self.root)

    def test_owner_attestation_hash_and_scope_are_recomputed(self) -> None:
        value = _manifest_value(self.root)
        value["owner_attestation"]["statement_cn"] = "changed"  # type: ignore[index]

        with self.assertRaisesRegex(
            SourceManifestError,
            "owner attestation sha256 mismatch",
        ):
            load_source_manifest(_write_manifest(self.root, value), self.root)

    def test_source_file_hash_and_relative_path_fail_closed(self) -> None:
        value = _manifest_value(self.root)
        value["sources"][0]["sha256"] = "0" * 64  # type: ignore[index]
        with self.assertRaisesRegex(SourceManifestError, "source sha256 mismatch"):
            load_source_manifest(_write_manifest(self.root, value), self.root)

    def test_base_lineage_manifest_path_is_explicit(self) -> None:
        value = _manifest_value(self.root)

        manifest = load_source_manifest(_write_manifest(self.root, value), self.root)

        self.assertEqual(
            manifest.base.lineage_manifest_relative_path.as_posix(),
            "base/manifest.json",
        )

    def test_base_public_and_lineage_bindings_must_be_distinct(self) -> None:
        value = _manifest_value(self.root)
        base = value["base"]  # type: ignore[assignment]
        base["lineage_manifest_relative_path"] = base["manifest_relative_path"]
        base["lineage_manifest_sha256"] = base["public_manifest_sha256"]

        with self.assertRaisesRegex(
            SourceManifestError,
            "base public and lineage bindings must be distinct",
        ):
            load_source_manifest(_write_manifest(self.root, value), self.root)

        value = _manifest_value(self.root)
        value["sources"][0]["relative_path"] = "../full.xlsx"  # type: ignore[index]
        with self.assertRaisesRegex(SourceManifestError, "unsafe source relative_path"):
            load_source_manifest(_write_manifest(self.root, value), self.root)

    def test_base_manifest_hash_and_role_use_the_same_file_bytes(self) -> None:
        value = _manifest_value(self.root)
        public_path = self.root / "base/manifest-public.json"
        valid_public_text = public_path.read_text(encoding="utf-8")
        invalid_public = {
            "dataset_version": "reddit_voc_site_snapshot_20260715_candidate_a2",
            "projection": {"audience": "private_audit"},
            "schema_version": "reddit_voc_site_snapshot_manifest_v2",
        }
        public_path.write_text(
            json.dumps(
                invalid_public,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        value["base"]["public_manifest_sha256"] = _sha256(public_path)  # type: ignore[index]
        source_manifest_path = _write_manifest(self.root, value)
        original_read_text = Path.read_text

        def swapped_read_text(path: Path, *args, **kwargs):
            if path == public_path:
                return valid_public_text
            return original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", new=swapped_read_text):
            with self.assertRaisesRegex(SourceManifestError, "public manifest role mismatch"):
                load_source_manifest(source_manifest_path, self.root)

    def test_duplicate_source_ids_and_boundary_drift_fail_closed(self) -> None:
        value = _manifest_value(self.root)
        value["sources"][1]["source_snapshot_id"] = (  # type: ignore[index]
            "reddit_add_data_full_20260715"
        )
        with self.assertRaisesRegex(SourceManifestError, "duplicate source_snapshot_id"):
            load_source_manifest(_write_manifest(self.root, value), self.root)

        value = _manifest_value(self.root)
        value["boundaries"]["deploy"] = True  # type: ignore[index]
        with self.assertRaisesRegex(SourceManifestError, "side-effect boundary"):
            load_source_manifest(_write_manifest(self.root, value), self.root)

    def test_manifest_json_must_be_canonical_with_single_trailing_lf(self) -> None:
        value = _manifest_value(self.root)
        path = self.root / "source-manifest.json"
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            SourceManifestError,
            "manifest bytes are not canonical",
        ):
            load_source_manifest(path, self.root)

    def test_manifest_calendar_dates_require_extended_yyyy_mm_dd(self) -> None:
        for calendar_date in ("20250701", "2025-W27-2", "2025-07-01+00:00"):
            with self.subTest(calendar_date=calendar_date):
                value = _manifest_value(self.root)
                window = value["sources"][0]["selection_window"]  # type: ignore[index]
                window["start_calendar_date"] = calendar_date
                window["end_calendar_date"] = calendar_date
                with self.assertRaisesRegex(
                    SourceManifestError,
                    "must be YYYY-MM-DD",
                ):
                    load_source_manifest(_write_manifest(self.root, value), self.root)

    def test_real_source_manifest_binds_both_workbooks_and_base(self) -> None:
        manifest = load_source_manifest(
            ROOT / "config/source_selection/reddit-voc-add-data-20260715-v1.json",
            ROOT,
        )

        self.assertEqual(manifest.source_rows, 13_534)
        self.assertEqual(manifest.base_dataset_version, "reddit_voc_site_snapshot_20260715_candidate_a2")
        self.assertEqual(
            manifest.base_lineage_manifest_sha256,
            "de8b504da8c50588c24b3b2a9a68244864bf8ae4bba20450fcf91c3cd40d6443",
        )
        self.assertEqual(
            [source.expected_data_rows for source in manifest.sources],
            [12_720, 814],
        )
        self.assertEqual(
            [source.workbook.expected_dimension for source in manifest.sources],
            ["A1:U12721", "A1:U815"],
        )
        self.assertEqual(
            [
                (source.workbook.expected_post_rows, source.workbook.expected_comment_rows)
                for source in manifest.sources
            ],
            [(2_094, 10_626), (132, 682)],
        )


if __name__ == "__main__":
    unittest.main()
