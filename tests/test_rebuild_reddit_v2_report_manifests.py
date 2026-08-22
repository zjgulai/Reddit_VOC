from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.rebuild_reddit_v2_report_manifests import (
    ReportManifestContractError,
    rebuild_manifests,
)


ARCHIVE_CUTOFF = "2026-07-15T04:15:20.212680Z"
SEARCH_CUTOFF = "2026-07-15T04:15:20.214394Z"
FIRST_PAGE_CUTOFF = "2026-07-15T04:19:56.303367Z"
REPLY_CUTOFF = "2026-07-15T04:28:28.244835Z"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _row(path: str, payload: bytes) -> dict[str, object]:
    return {
        "relative_path": path,
        "bytes": len(payload),
        "sha256": sha256(payload).hexdigest(),
    }


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(rows, key=lambda row: str(row["relative_path"]))
    payload = "".join(
        f"{row['relative_path']}|{row['bytes']}|{row['sha256']}\n"
        for row in ordered
    ).encode()
    return {
        "file_count": len(ordered),
        "total_bytes": sum(int(str(row["bytes"])) for row in ordered),
        "file_manifest_lf_sha256": sha256(payload).hexdigest(),
    }


class RebuildRedditV2ReportManifestsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.reports_root = self.root / "private/reports"
        base_payload = b"base-report\n"
        append_payload = b"append-report\n"
        self.base_row = _row("run/search-lane-probe.json", base_payload)
        self.append_row = _row("run/comment-repair-probe.json", append_payload)
        for row, payload in (
            (self.base_row, base_payload),
            (self.append_row, append_payload),
        ):
            path = self.reports_root / str(row["relative_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

        self.private_manifest = self.root / "private/report-file-manifest.json"
        self.append_manifest = self.root / "append-manifest.json"
        self.import_manifest = self.root / "import-manifest.json"
        base_summary = _summary([self.base_row])
        append_summary = _summary([self.append_row])
        merged_summary = _summary([self.base_row, self.append_row])
        _write_json(
            self.private_manifest,
            {
                "schema_version": "reddit_voc_v2_report_file_manifest_v1",
                "freeze_cutoff_utc": ARCHIVE_CUTOFF,
                "raw_payload_embedded_in_manifest": False,
                **base_summary,
                "files": [self.base_row],
            },
        )
        _write_json(
            self.append_manifest,
            {
                "base_manifest": {**base_summary, "path": "fixture"},
                "append": {
                    **append_summary,
                    "by_report_name": {"comment-repair-probe.json": 1},
                    "files": [self.append_row],
                },
                "merged_expected": {
                    **merged_summary,
                    "by_report_name": {
                        "comment-repair-probe.json": 1,
                        "search-lane-probe.json": 1,
                    },
                },
                "selection_contract": {
                    "rc_post_id_set_source": {
                        "archive_manifest_cutoff_utc": ARCHIVE_CUTOFF,
                        "semantic_search_cutoff_utc": SEARCH_CUTOFF,
                    },
                    "per_kind_cutoff": {
                        "comment-repair-probe.json": {
                            "captured_at_utc": FIRST_PAGE_CUTOFF
                        },
                        "comment-reply-probe.json": {
                            "captured_at_utc": REPLY_CUTOFF
                        },
                    },
                },
            },
        )
        _write_json(
            self.import_manifest,
            {
                "schema_version": "reddit_voc_v2_report_import_manifest_v1",
                "source_environment": "tencent_isolated_staging",
                "source_root": "/opt/reddit-voc-staging",
                "boundaries": {
                    "provider_call": False,
                    "database_write": False,
                    "remote_write": False,
                },
            },
        )

    def _rebuild(self, *, search_cutoff: str = SEARCH_CUTOFF) -> dict[str, object]:
        return rebuild_manifests(
            reports_root=self.reports_root,
            base_manifest_path=self.private_manifest,
            append_manifest_path=self.append_manifest,
            import_manifest_path=self.import_manifest,
            archive_mtime_cutoff_utc=ARCHIVE_CUTOFF,
            search_semantic_cutoff_utc=search_cutoff,
            first_page_cutoff_utc=FIRST_PAGE_CUTOFF,
            reply_cutoff_utc=REPLY_CUTOFF,
        )

    def test_rebuild_is_exact_private_and_idempotent(self) -> None:
        first = self._rebuild()
        first_private = self.private_manifest.read_bytes()
        first_import = self.import_manifest.read_bytes()
        second = self._rebuild()

        self.assertEqual(first, second)
        self.assertEqual(first_private, self.private_manifest.read_bytes())
        self.assertEqual(first_import, self.import_manifest.read_bytes())
        private = json.loads(first_private)
        imported = json.loads(first_import)
        self.assertEqual(private["file_count"], 2)
        self.assertEqual(
            private["watermarks"]["reply_captured_at_cutoff_utc"],
            REPLY_CUTOFF,
        )
        self.assertTrue(imported["scope"]["task2600_and_later_excluded"])
        self.assertEqual(os.stat(self.private_manifest).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.import_manifest).st_mode & 0o777, 0o600)

    def test_cutoff_mismatch_fails_before_writing(self) -> None:
        before_private = self.private_manifest.read_bytes()
        before_import = self.import_manifest.read_bytes()
        with self.assertRaisesRegex(
            ReportManifestContractError, "append_identity_cutoff_mismatch"
        ):
            self._rebuild(search_cutoff="2026-07-15T04:15:21Z")
        self.assertEqual(self.private_manifest.read_bytes(), before_private)
        self.assertEqual(self.import_manifest.read_bytes(), before_import)


if __name__ == "__main__":
    unittest.main()
