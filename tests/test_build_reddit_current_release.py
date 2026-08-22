from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_reddit_current_release import (
    CurrentReleaseContractError,
    build_current_release,
    write_immutable_pointer,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class CurrentReleaseBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.public_root = self.root / "public"
        self.sources = {
            key: self.root / "private" / key
            for key in ("base", "insights", "reports", "personas")
        }
        self.versions = {
            "base": "reddit_voc_site_snapshot_20260716_abc123",
            "insights": "reddit_voc_insights_20260716_def456",
            "reports": "reddit_voc_reports_20260716_def456",
            "personas": "reddit_voc_personas_20260716_ghi789",
        }
        self._write_datasets()
        self._write_cases()

    def _write_datasets(self) -> None:
        base_manifest = {
            "schema_version": "reddit_voc_site_snapshot_manifest_v1",
            "dataset_version": self.versions["base"],
            "all_checks_passed": True,
        }
        _write(self.sources["base"] / "manifest.json", base_manifest)
        base_sha = _sha(self.sources["base"] / "manifest.json")

        insights_manifest = {
            "schema_version": "reddit_voc_insights_manifest_v1",
            "dataset_version": self.versions["insights"],
            "base_dataset_version": self.versions["base"],
            "base_manifest_sha256": base_sha,
        }
        _write(self.sources["insights"] / "manifest.json", insights_manifest)
        insights_sha = _sha(self.sources["insights"] / "manifest.json")

        reports_manifest = {
            "schema_version": "reddit_voc_reports_manifest_v1",
            "dataset_version": self.versions["reports"],
            "base_dataset_version": self.versions["base"],
            "base_manifest_sha256": base_sha,
            "insights_dataset_version": self.versions["insights"],
            "insights_manifest_sha256": insights_sha,
        }
        personas_manifest = {
            "schema_version": "reddit_voc_personas_manifest_v1",
            "dataset_version": self.versions["personas"],
            "base_dataset_version": self.versions["base"],
            "base_manifest_sha256": base_sha,
            "insights_dataset_version": self.versions["insights"],
            "insights_manifest_sha256": insights_sha,
        }
        _write(self.sources["reports"] / "manifest.json", reports_manifest)
        _write(self.sources["personas"] / "manifest.json", personas_manifest)

        public_paths = {
            "base": self.public_root
            / "data/reddit-voc"
            / self.versions["base"]
            / "manifest-public.json",
            "insights": self.public_root
            / "data/reddit-voc"
            / self.versions["insights"]
            / "public/manifest.json",
            "reports": self.public_root
            / "data/reddit-voc"
            / self.versions["reports"]
            / "public/manifest.json",
            "personas": self.public_root
            / "data/reddit-voc"
            / self.versions["personas"]
            / "manifest.json",
        }
        _write(
            public_paths["base"],
            {"dataset_version": self.versions["base"]},
        )
        _write(public_paths["insights"], insights_manifest)
        _write(public_paths["reports"], reports_manifest)
        _write(public_paths["personas"], personas_manifest)

    def _write_cases(self, *, seed_count: int = 38) -> None:
        index_path = self.public_root / "data/cases/case-index.v1.json"
        _write(
            index_path,
            {
                "schemaVersion": 1,
                "datasetVersion": "case_catalog_20260716_v1",
                "approvedDelta": [],
            },
        )
        _write(
            self.public_root / "data/cases/manifest.v1.json",
            {
                "schemaVersion": 1,
                "datasetVersion": "case_catalog_20260716_v1",
                "seed": {"count": seed_count},
                "legacyUnverified": {"count": 12},
                "approvedDelta": {"count": 0},
                "index": {
                    "path": "/data/cases/case-index.v1.json",
                    "sha256": _sha(index_path),
                },
            },
        )

    def _build(self) -> dict:
        return build_current_release(
            public_root=self.public_root,
            base_source_dir=self.sources["base"],
            insights_source_dir=self.sources["insights"],
            reports_source_dir=self.sources["reports"],
            personas_source_dir=self.sources["personas"],
            release_id="reddit_voc_release_20260716_abc123",
            generated_at_utc="2026-07-16T01:02:03+00:00",
        )

    def test_builds_cross_layer_pointer_and_preserves_case_stock(self) -> None:
        pointer = self._build()

        self.assertEqual(pointer["generated_at_utc"], "2026-07-16T01:02:03Z")
        self.assertEqual(set(pointer["datasets"]), set(self.sources))
        self.assertEqual(pointer["cases"]["approved_delta_count"], 0)
        self.assertTrue(pointer["cases"]["stock_content_preserved"])
        self.assertEqual(
            pointer["datasets"]["base"]["lineage_manifest_sha256"],
            _sha(self.sources["base"] / "manifest.json"),
        )
        self.assertEqual(
            pointer["datasets"]["insights"]["manifest_path"],
            "data/reddit-voc/reddit_voc_insights_20260716_def456/public/manifest.json",
        )

    def test_exact_rewrite_is_no_change_and_preserves_mtime(self) -> None:
        destination = self.root / "candidate/current-release.json"
        pointer = self._build()
        self.assertEqual(write_immutable_pointer(destination, pointer), "created")
        first_mtime = destination.stat().st_mtime_ns

        self.assertEqual(write_immutable_pointer(destination, pointer), "no_change")
        self.assertEqual(destination.stat().st_mtime_ns, first_mtime)

    def test_rejects_immutable_collision(self) -> None:
        destination = self.root / "candidate/current-release.json"
        pointer = self._build()
        write_immutable_pointer(destination, pointer)
        changed = dict(pointer)
        changed["release_id"] = "reddit_voc_release_20260716_different"

        with self.assertRaisesRegex(
            CurrentReleaseContractError, "pointer_immutable_collision"
        ):
            write_immutable_pointer(destination, changed)

    def test_rejects_public_lineage_drift(self) -> None:
        path = (
            self.public_root
            / "data/reddit-voc"
            / self.versions["insights"]
            / "public/manifest.json"
        )
        value = json.loads(path.read_text(encoding="utf-8"))
        value["base_manifest_sha256"] = "0" * 64
        _write(path, value)

        with self.assertRaisesRegex(
            CurrentReleaseContractError,
            "insights_public_lineage_projection_mismatch",
        ):
            self._build()

    def test_rejects_case_stock_replacement(self) -> None:
        self._write_cases(seed_count=37)

        with self.assertRaisesRegex(
            CurrentReleaseContractError, "cases_stock_content_changed"
        ):
            self._build()


if __name__ == "__main__":
    unittest.main()
