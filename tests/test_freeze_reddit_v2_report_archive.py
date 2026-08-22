from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.freeze_reddit_v2_report_archive import (
    ReportArchiveFreezeError,
    freeze_archive,
    write_manifest,
)


class ReportArchiveFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.reports = self.root / "reports"
        first = self.reports / "task-a/run/reports/search-lane-probe.json"
        second = self.reports / "task-b/run/reports/comment-repair-probe.json"
        first.parent.mkdir(parents=True)
        second.parent.mkdir(parents=True)
        first.write_text('{"fixture":1}\n', encoding="utf-8")
        second.write_text('{"fixture":2}\n', encoding="utf-8")

    def test_freezes_sorted_members_with_integer_mtime_evidence(self) -> None:
        value = freeze_archive(
            self.reports, freeze_cutoff_utc="2026-07-15T06:10:07Z"
        )

        self.assertEqual(value["file_count"], 2)
        self.assertEqual(
            [row["relative_path"] for row in value["files"]],
            sorted(row["relative_path"] for row in value["files"]),
        )
        self.assertEqual(
            value["report_counts"],
            {"comment-repair-probe.json": 1, "search-lane-probe.json": 1},
        )
        self.assertTrue(
            value["quiescence_evidence"]["mtime_compared_as_integer_ns"]
        )
        self.assertIsInstance(
            value["quiescence_evidence"]["max_member_mtime_ns"], int
        )

    def test_exact_second_write_is_no_change(self) -> None:
        destination = self.root / "private/report-file-manifest.json"
        value = freeze_archive(
            self.reports, freeze_cutoff_utc="2026-07-15T06:10:07+00:00"
        )
        self.assertEqual(write_manifest(destination, value), "created")
        first_mtime = destination.stat().st_mtime_ns

        self.assertEqual(write_manifest(destination, value), "no_change")
        self.assertEqual(destination.stat().st_mtime_ns, first_mtime)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_rejects_unreviewed_filename(self) -> None:
        path = self.reports / "task-c/run/reports/secret.env"
        path.parent.mkdir(parents=True)
        path.write_text("not-a-report\n", encoding="utf-8")

        with self.assertRaisesRegex(
            ReportArchiveFreezeError, "report_archive_filename_invalid"
        ):
            freeze_archive(
                self.reports, freeze_cutoff_utc="2026-07-15T06:10:07Z"
            )

    def test_rejects_symlink_member(self) -> None:
        target = self.root / "outside.json"
        target.write_text("{}\n", encoding="utf-8")
        link = self.reports / "task-c/run/reports/comment-reply-probe.json"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)

        with self.assertRaisesRegex(
            ReportArchiveFreezeError, "report_archive_member_unsafe"
        ):
            freeze_archive(
                self.reports, freeze_cutoff_utc="2026-07-15T06:10:07Z"
            )


if __name__ == "__main__":
    unittest.main()
