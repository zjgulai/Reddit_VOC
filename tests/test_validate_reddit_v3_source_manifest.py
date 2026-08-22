from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from openpyxl import Workbook

from scripts import build_reddit_v3_source_manifest as builder
from scripts import validate_reddit_v3_source_manifest as validator
from tests.test_reddit_v3_source_manifest import (
    EXPECTED_HEADERS,
    _manifest_value,
    _write_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
REAL_MANIFEST = (
    ROOT / "config/source_selection/reddit-voc-add-data-20260715-v1.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_workbook(
    path: Path,
    *,
    entity_type: str,
    published_at: str,
    bad_header: bool = False,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "0"
    headers = list(EXPECTED_HEADERS)
    if bad_header:
        headers[0] = "错误舆情ID"
    sheet.append(headers)
    row: list[object | None] = [None] * len(headers)
    row[0] = "source-row-1"
    row[1] = (
        "https://www.reddit.com/r/test/comments/abc123/example/t1_def456/"
        if "reply" in entity_type.casefold()
        else "https://www.reddit.com/r/test/comments/abc123/example/"
    )
    row[3] = "Momcozy sample"
    row[7] = entity_type
    row[19] = published_at
    sheet.append(row)
    workbook.save(path)
    workbook.close()


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.value = _manifest_value(root)
        self.base_manifest = root / "base/manifest-public.json"
        self.base_manifest.parent.mkdir(parents=True, exist_ok=True)
        self.base_manifest.write_text(
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
        self.lineage_manifest = root / "base/manifest.json"
        self.lineage_manifest.write_text(
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
        _write_workbook(
            root / "full.xlsx",
            entity_type="Forum Post",
            published_at="2025-07-01 00:00:00",
        )
        _write_workbook(
            root / "negative.xlsx",
            entity_type="forum post reply",
            published_at="2026-02-15 00:00:00",
        )
        self.value["base"]["public_manifest_sha256"] = _sha256(  # type: ignore[index]
            self.base_manifest
        )
        self.value["base"]["lineage_manifest_sha256"] = _sha256(  # type: ignore[index]
            self.lineage_manifest
        )
        full = self.value["sources"][0]  # type: ignore[index]
        negative = self.value["sources"][1]  # type: ignore[index]
        for source, name in ((full, "full.xlsx"), (negative, "negative.xlsx")):
            source["sha256"] = _sha256(root / name)
            source["bytes"] = (root / name).stat().st_size
        negative["workbook"]["expected_entity_counts"] = {  # type: ignore[index]
            "comments": 1,
            "posts": 0,
        }
        negative["selection_window"] = {
            "end_calendar_date": "2026-02-15",
            "start_calendar_date": "2026-02-15",
        }
        self.manifest = _write_manifest(root, self.value)

    def rewrite_manifest(self) -> None:
        self.manifest = _write_manifest(self.root, self.value)


class SourceManifestValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_validator_does_not_import_builder(self) -> None:
        source = inspect.getsource(validator)
        self.assertNotIn("build_reddit_v3_source_manifest", source)

    def test_validates_fixture_and_real_manifest_totals(self) -> None:
        fixture_summary = validator.validate_source_manifest(
            self.fixture.manifest,
            self.fixture.root,
        )
        self.assertEqual(fixture_summary["status"], "passed")
        self.assertEqual(fixture_summary["source_rows"], 2)
        self.assertEqual(fixture_summary["post_rows"], 1)
        self.assertEqual(fixture_summary["comment_rows"], 1)
        self.assertTrue(fixture_summary["production_unchanged"])

        real_summary = validator.validate_source_manifest(REAL_MANIFEST, ROOT)
        self.assertEqual(real_summary["source_count"], 2)
        self.assertEqual(real_summary["source_rows"], 13_534)
        self.assertEqual(real_summary["post_rows"], 2_226)
        self.assertEqual(real_summary["comment_rows"], 11_308)
        self.assertEqual(
            real_summary["base_dataset_version"],
            "reddit_voc_site_snapshot_20260715_candidate_a2",
        )
        self.assertTrue(real_summary["production_unchanged"])

    def test_base_dataset_version_drift_fails_closed(self) -> None:
        self.fixture.base_manifest.write_text(
            '{"dataset_version":"wrong","schema_version":"reddit_voc_site_snapshot_manifest_v2"}\n',
            encoding="utf-8",
        )
        self.fixture.value["base"]["public_manifest_sha256"] = _sha256(  # type: ignore[index]
            self.fixture.base_manifest
        )
        self.fixture.rewrite_manifest()

        with self.assertRaisesRegex(
            validator.SourceManifestValidationError,
            "base dataset_version mismatch",
        ):
            validator.validate_source_manifest(
                self.fixture.manifest,
                self.fixture.root,
            )

    def test_base_lineage_hash_drift_fails_closed(self) -> None:
        self.fixture.lineage_manifest.write_bytes(
            self.fixture.lineage_manifest.read_bytes() + b" "
        )

        with self.assertRaisesRegex(
            validator.SourceManifestValidationError,
            "base lineage manifest sha256 mismatch",
        ):
            validator.validate_source_manifest(
                self.fixture.manifest,
                self.fixture.root,
            )

    def test_workbook_header_drift_fails_closed_after_rebinding_hash(self) -> None:
        workbook_path = self.fixture.root / "full.xlsx"
        _write_workbook(
            workbook_path,
            entity_type="Forum Post",
            published_at="2025-07-01 00:00:00",
            bad_header=True,
        )
        source = self.fixture.value["sources"][0]  # type: ignore[index]
        source["sha256"] = _sha256(workbook_path)
        source["bytes"] = workbook_path.stat().st_size
        self.fixture.rewrite_manifest()

        with self.assertRaisesRegex(
            validator.SourceManifestValidationError,
            "workbook headers mismatch",
        ):
            validator.validate_source_manifest(
                self.fixture.manifest,
                self.fixture.root,
            )

    def test_day_precision_rejects_invalid_suffix_and_non_midnight_time(self) -> None:
        workbook_path = self.fixture.root / "full.xlsx"
        for published_at in (
            "2025-07-01 invalid",
            "2025-07-01 12:00:00",
            "2025-07-01+00:00",
            "20250701",
            "2025-W27-2",
        ):
            with self.subTest(published_at=published_at):
                _write_workbook(
                    workbook_path,
                    entity_type="Forum Post",
                    published_at=published_at,
                )
                source = self.fixture.value["sources"][0]  # type: ignore[index]
                source["sha256"] = _sha256(workbook_path)
                source["bytes"] = workbook_path.stat().st_size
                self.fixture.rewrite_manifest()

                with self.assertRaisesRegex(
                    validator.SourceManifestValidationError,
                    "workbook published date invalid",
                ):
                    validator.validate_source_manifest(
                        self.fixture.manifest,
                        self.fixture.root,
                    )

    def test_materializer_is_idempotent_and_rejects_drift(self) -> None:
        target = self.fixture.root / "tmp/reddit-voc-v3/frozen/manifest.json"
        first = builder.materialize_source_manifest(
            self.fixture.manifest,
            target,
            self.fixture.root,
        )
        second = builder.materialize_source_manifest(
            self.fixture.manifest,
            target,
            self.fixture.root,
        )
        self.assertEqual(first["write_status"], "created")
        self.assertEqual(second["write_status"], "no_change")
        self.assertEqual(target.read_bytes(), self.fixture.manifest.read_bytes())

        target.write_bytes(target.read_bytes() + b" ")
        with self.assertRaisesRegex(
            builder.SourceManifestBuildError,
            "existing output drift",
        ):
            builder.materialize_source_manifest(
                self.fixture.manifest,
                target,
                self.fixture.root,
            )

    def test_materializer_rejects_public_or_non_v3_output_roots(self) -> None:
        for relative in (
            "ref/UI/momcozy-reddit-workbench/public/data/source-manifest.json",
            "output/source-manifest.json",
            "tmp/source-manifest.json",
            "tmp/reddit-voc-v3",
        ):
            with self.subTest(relative=relative):
                target = self.fixture.root / relative
                with self.assertRaisesRegex(
                    builder.SourceManifestBuildError,
                    "private V3 output root",
                ):
                    builder.materialize_source_manifest(
                        self.fixture.manifest,
                        target,
                        self.fixture.root,
                    )
                self.assertFalse(target.exists())

    def test_materializer_rejects_missing_base_bindings(self) -> None:
        self.fixture.base_manifest.unlink()
        self.fixture.lineage_manifest.unlink()
        target = self.fixture.root / "tmp/reddit-voc-v3/source/manifest.json"

        with self.assertRaisesRegex(
            builder.SourceManifestBuildError,
            "base manifest unavailable",
        ):
            builder.materialize_source_manifest(
                self.fixture.manifest,
                target,
                self.fixture.root,
            )
        self.assertFalse(target.exists())

    def test_materializer_rejects_manifest_check_use_drift(self) -> None:
        target = self.fixture.root / "tmp/reddit-voc-v3/source/manifest.json"
        real_loader = builder.load_source_manifest

        def load_then_mutate(manifest_path: Path, project_root: Path):
            manifest = real_loader(manifest_path, project_root)
            manifest_path.write_text('{"invalid_after_check":true}\n', encoding="utf-8")
            return manifest

        with mock.patch.object(
            builder,
            "load_source_manifest",
            side_effect=load_then_mutate,
        ):
            with self.assertRaisesRegex(
                builder.SourceManifestBuildError,
                "manifest changed after validation",
            ):
                builder.materialize_source_manifest(
                    self.fixture.manifest,
                    target,
                    self.fixture.root,
                )
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
