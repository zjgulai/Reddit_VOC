from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import unittest
from unittest import mock

import reddit_voc.v3_workbook_import as workbook_import
from reddit_voc.v3_source_manifest import load_source_manifest
from reddit_voc.v3_workbook_import import (
    RedditIdentity,
    WorkbookImportError,
    _classify_rows,
    _base_maps,
    _json_list,
    _json_object,
    _load_base,
    _load_source_rows,
    _private_output,
    _write_bundle,
    build_workbook_import,
    normalize_workbook_row,
    parse_reddit_identity,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = (
    ROOT / "config/source_selection/reddit-voc-add-data-20260715-v1.json"
)
EXPECTED_FILES = {
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "manifest.json",
    "parent-link-ledger.jsonl",
    "posts.jsonl",
    "row-outcomes.jsonl",
}


def _write_json(path: Path, value: object) -> bytes:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    path.write_bytes(payload)
    return payload


def _base_fixture_manifest(
    fake_project: Path,
    manifest,
    *,
    public_posts: list[dict[str, object]],
    public_comments: list[dict[str, object]],
    private_posts: list[dict[str, object]],
    private_comments: list[dict[str, object]],
    quarantine: list[dict[str, object]],
):
    public_root = fake_project / "public-base"
    private_root = fake_project / "private-base"
    public_root.mkdir()
    private_root.mkdir()
    public_members = {
        "posts-public.json": public_posts,
        "comments-public.json": public_comments,
    }
    private_members = {
        "posts.json": private_posts,
        "comments.json": private_comments,
        "quarantine.json": quarantine,
    }
    public_files = {}
    for name, value in public_members.items():
        payload = _write_json(public_root / name, value)
        public_files[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    private_files = {}
    for name, value in private_members.items():
        payload = _write_json(private_root / name, value)
        private_files[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    counts = {
        "linked_comments": len(private_comments),
        "posts": len(private_posts),
        "quarantined_comments": len(quarantine),
        "stored_comments": len(private_comments) + len(quarantine),
    }
    public_manifest_payload = _write_json(
        public_root / "manifest-public.json",
        {
            "canonical_counts": counts,
            "dataset_version": "fixture_base",
            "files": public_files,
            "projection": {"audience": "public_ui"},
            "schema_version": "reddit_voc_site_snapshot_manifest_v2",
        },
    )
    private_manifest_payload = _write_json(
        private_root / "manifest.json",
        {
            "canonical_counts": counts,
            "dataset_version": "fixture_base",
            "files": private_files,
            "schema_version": "reddit_voc_site_snapshot_manifest_v2",
            "source_boundaries": {},
        },
    )
    return replace(
        manifest,
        base=replace(
            manifest.base,
            dataset_version="fixture_base",
            manifest_relative_path=PurePosixPath("public-base/manifest-public.json"),
            lineage_manifest_relative_path=PurePosixPath("private-base/manifest.json"),
            public_manifest_sha256=hashlib.sha256(public_manifest_payload).hexdigest(),
            lineage_manifest_sha256=hashlib.sha256(private_manifest_payload).hexdigest(),
        ),
    )


class RedditIdentityTests(unittest.TestCase):
    def test_parses_supported_post_and_comment_url_shapes(self) -> None:
        cases = (
            (
                "https://reddit.com/r/x/comments/abc123",
                "post",
                RedditIdentity(post_id="abc123", comment_id=None),
            ),
            (
                "https://www.reddit.com/r/x/comments/abc123/a-unicode-%E6%A0%87%E9%A2%98/",
                "post",
                RedditIdentity(post_id="abc123", comment_id=None),
            ),
            (
                "https://www.reddit.com/r/x/comments/abc123/comment/def456?context=3#x",
                "comment",
                RedditIdentity(post_id="abc123", comment_id="def456"),
            ),
            (
                "https://old.reddit.com/r/x/comments/abc123/title/def456/",
                "comment",
                RedditIdentity(post_id="abc123", comment_id="def456"),
            ),
        )
        for url, entity_type, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(parse_reddit_identity(url, entity_type), expected)

    def test_rejects_non_reddit_or_entity_path_mismatch(self) -> None:
        cases = (
            ("https://example.com/r/x/comments/abc123", "post"),
            ("http://reddit.com/r/x/comments/abc123", "post"),
            ("https://reddit.com/r/x/comments/abc123/title", "comment"),
            ("https://reddit.com/r/x/comments/abc123/comment/def456", "post"),
            ("https://reddit.com/foo/comments/abc123/title/def456", "comment"),
            ("https://reddit.com/r/x/junk/comments/abc123/title/def456", "comment"),
            ("https://reddit.com/r/x/comments/abc123/%2e%2e/def456", "comment"),
            ("https://reddit.com/r/x/comments/abc123/title/t1_def456", "comment"),
            ("https://evil@reddit.com/r/x/comments/abc123", "post"),
            ("https://reddit.com:444/r/x/comments/abc123", "post"),
        )
        for url, entity_type in cases:
            with self.subTest(url=url, entity_type=entity_type):
                with self.assertRaises(WorkbookImportError):
                    parse_reddit_identity(url, entity_type)


class WorkbookRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        cls.source = cls.manifest.source("reddit_add_data_full_20260715")

    def test_normalizes_casefold_type_and_floating_day_without_author_or_utc(self) -> None:
        row = normalize_workbook_row(
            {
                "舆情ID": "source-row-1",
                "舆情链接": "https://www.reddit.com/r/x/comments/abc123/comment/def456",
                "标题": "  Momcozy\r\ncomment  ",
                "内容概要": "derived summary",
                "内容类型": "  FORUM POST REPLY ",
                "作者": "must-not-be-copied",
                "发布时间": "2025-07-28 00:00:00",
            },
            source=self.source,
            row_ordinal=2,
        )

        value = row.as_dict()
        self.assertEqual(row.entity_type, "comment")
        self.assertEqual(row.identity, RedditIdentity("abc123", "def456"))
        self.assertEqual(row.source_text, "Momcozy\ncomment")
        self.assertEqual(row.source_calendar_date, "2025-07-28")
        self.assertEqual(row.event_time_precision, "day")
        self.assertEqual(row.source_timezone_status, "unknown")
        self.assertNotIn("author", json.dumps(value, ensure_ascii=False).casefold())
        self.assertFalse(any("utc" in key.casefold() for key in value))

    def test_rejects_non_midnight_or_offset_day_values(self) -> None:
        for published_at in (
            "2025-07-28 12:00:00",
            "2025-07-28+00:00",
            "20250728",
        ):
            with self.subTest(published_at=published_at):
                with self.assertRaisesRegex(WorkbookImportError, "floating calendar date"):
                    normalize_workbook_row(
                        {
                            "舆情ID": "source-row-1",
                            "舆情链接": "https://reddit.com/r/x/comments/abc123",
                            "标题": "text",
                            "内容类型": "Forum Post",
                            "发布时间": published_at,
                        },
                        source=self.source,
                        row_ordinal=2,
                    )

    def test_rejects_nonfinite_source_annotations(self) -> None:
        with self.assertRaisesRegex(WorkbookImportError, "non-finite"):
            normalize_workbook_row(
                {
                    "舆情ID": "source-row-1",
                    "舆情链接": "https://reddit.com/r/x/comments/abc123",
                    "标题": "text",
                    "内容类型": "Forum Post",
                    "发布时间": "2025-07-28",
                    "浏览量": float("nan"),
                },
                source=self.source,
                row_ordinal=2,
            )


class WorkbookClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        cls.source = cls.manifest.source("reddit_add_data_full_20260715")

    def _comment(
        self,
        *,
        post_id: str,
        comment_id: str = "def456",
        row_ordinal: int = 2,
        text: str = "source comment",
        view_count: int | None = None,
    ):
        return normalize_workbook_row(
            {
                "舆情ID": f"source-{row_ordinal}",
                "舆情链接": (
                    f"https://reddit.com/r/x/comments/{post_id}/comment/{comment_id}"
                ),
                "标题": text,
                "内容类型": "Forum Post Reply",
                "发布时间": "2025-07-28",
                "浏览量": view_count,
            },
            source=self.source,
            row_ordinal=row_ordinal,
        )

    def test_base_comment_parent_mismatch_is_held_not_overlap(self) -> None:
        result = _classify_rows(
            [self._comment(post_id="abc123")],
            [
                {"post_id": "t3_abc123", "title": "source parent"},
                {"post_id": "t3_zzz789", "title": "governed parent"},
            ],
            [
                {
                    "body": "governed comment",
                    "comment_id": "t1_def456",
                    "post_id": "t3_zzz789",
                    "reddit_id": "t1_def456",
                }
            ],
        )

        self.assertEqual(result.terminal_outcomes["identity_conflict"], 1)
        self.assertEqual(result.terminal_outcomes["exact_base_overlap"], 0)
        self.assertEqual(result.comments[0]["terminal_outcome"], "identity_conflict")
        self.assertTrue(result.comments[0]["base_overlap"])
        self.assertIn("base_anchor", result.comments[0])
        self.assertEqual(result.counts["base_overlap_comments"], 1)
        self.assertEqual(result.counts["net_new_comments"], 0)
        self.assertNotEqual(result.comments[0]["analysis_status"], "ready")
        self.assertTrue(
            any(
                item["conflict_type"] == "comment_parent_identity_conflict"
                for item in result.conflicts
            )
        )

    def test_cross_workbook_parent_conflict_holds_entire_identity(self) -> None:
        result = _classify_rows(
            [
                self._comment(post_id="abc123", row_ordinal=2),
                self._comment(post_id="zzz789", row_ordinal=3),
            ],
            [
                {"post_id": "t3_abc123", "title": "parent one"},
                {"post_id": "t3_zzz789", "title": "parent two"},
            ],
            [],
        )

        self.assertEqual(result.terminal_outcomes["identity_conflict"], 2)
        self.assertEqual(result.terminal_outcomes["net_new_text_ready"], 0)
        self.assertEqual(result.comments[0]["terminal_outcome"], "identity_conflict")
        self.assertNotEqual(result.comments[0]["analysis_status"], "ready")
        self.assertEqual(len(result.parent_links), 1)
        self.assertEqual(result.parent_links[0]["parent_link_status"], "identity_conflict")

    def test_same_new_identity_different_text_is_held_with_hash_conflict(self) -> None:
        result = _classify_rows(
            [
                self._comment(post_id="abc123", row_ordinal=2, text="first text"),
                self._comment(post_id="abc123", row_ordinal=3, text="second text"),
            ],
            [{"post_id": "t3_abc123", "title": "parent"}],
            [],
        )

        self.assertEqual(result.terminal_outcomes["identity_conflict"], 2)
        conflicts = [
            item
            for item in result.conflicts
            if item["conflict_type"] == "source_text_conflict_without_governed_base"
        ]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(len(conflicts[0]["source_text_sha256s"]), 2)
        self.assertFalse(any("first text" in json.dumps(item) for item in conflicts))

    def test_classification_is_stable_after_input_order_shuffle(self) -> None:
        rows = [
            self._comment(post_id="abc123", comment_id="def456", row_ordinal=2),
            self._comment(post_id="abc123", comment_id="ghi789", row_ordinal=3),
        ]
        base_posts = [{"post_id": "t3_abc123", "title": "parent"}]
        first = _classify_rows(rows, base_posts, [])
        second = _classify_rows(list(reversed(rows)), base_posts, [])
        self.assertEqual(first, second)

    def test_occurrences_preserve_annotation_values_and_hashes(self) -> None:
        result = _classify_rows(
            [
                self._comment(post_id="abc123", row_ordinal=2, view_count=1),
                self._comment(post_id="abc123", row_ordinal=3, view_count=999),
            ],
            [{"post_id": "t3_abc123", "title": "parent"}],
            [],
        )
        source_occurrences = result.comments[0]["source_occurrences"]
        self.assertEqual(
            [item["source_annotations"]["view_count"] for item in source_occurrences],
            [1, 999],
        )
        self.assertEqual(
            len({item["source_annotations_sha256"] for item in source_occurrences}),
            2,
        )

    def test_private_quarantine_overlap_is_not_net_new(self) -> None:
        result = _classify_rows(
            [self._comment(post_id="abc123")],
            [],
            [],
            [
                {
                    "comment_id": "t1_def456",
                    "missing_post_id": "abc123",
                    "reason": "post_attach_orphan",
                }
            ],
        )

        self.assertEqual(result.terminal_outcomes["exact_base_overlap"], 1)
        self.assertEqual(result.comments[0]["analysis_status"], "governed_base_quarantine")
        self.assertEqual(
            result.parent_links[0]["parent_link_status"],
            "quarantined_governed_base_comment",
        )
        self.assertFalse(result.parent_links[0]["context_available"])
        self.assertEqual(result.comments[0]["metric_eligibility_basis"], "held_quarantine")
        self.assertEqual(result.comments[0]["effective_allowed_metric_families"], [])

    def test_unresolved_overlap_can_relink_to_a_base_post(self) -> None:
        result = _classify_rows(
            [self._comment(post_id="abc123")],
            [
                {
                    "content": "base parent content",
                    "post_id": "abc123",
                    "title": "base parent",
                }
            ],
            [],
            base_unresolved=[
                {
                    "canonical_reddit_id": "t1_def456",
                    "comment_state": "unresolved_parent",
                    "post_id": "missing1",
                    "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
                    "source_terminal_outcome": "unresolved_parent",
                }
            ],
        )

        self.assertEqual(result.terminal_outcomes["exact_base_overlap"], 1)
        self.assertTrue(result.comments[0]["base_overlap"])
        self.assertEqual(
            result.comments[0]["base_anchor"]["canonical_state"],
            "unresolved_comment",
        )
        self.assertEqual(
            result.parent_links[0]["parent_link_status"],
            "linked_base_post",
        )
        self.assertEqual(result.parent_links[0]["post_id"], "abc123")

    def test_quarantine_parent_mismatch_is_held_but_still_base_overlap(self) -> None:
        result = _classify_rows(
            [self._comment(post_id="abc123")],
            [],
            [],
            [
                {
                    "comment_id": "t1_def456",
                    "missing_post_id": "zzz789",
                    "reason": "post_attach_orphan",
                }
            ],
        )
        self.assertEqual(result.comments[0]["terminal_outcome"], "identity_conflict")
        self.assertTrue(result.comments[0]["base_overlap"])
        self.assertEqual(result.counts["base_overlap_comments"], 1)
        self.assertEqual(result.counts["net_new_comments"], 0)
        self.assertEqual(result.comments[0]["effective_allowed_metric_families"], [])

    def test_redundant_base_identity_disagreement_fails_closed(self) -> None:
        with self.assertRaisesRegex(WorkbookImportError, "redundant identity"):
            _base_maps(
                [
                    {
                        "post_id": "t3_abc123",
                        "reddit_id": "t3_zzz789",
                    }
                ],
                [],
            )
        with self.assertRaisesRegex(WorkbookImportError, "root parent disagreement"):
            _base_maps(
                [
                    {"post_id": "t3_abc123"},
                    {"post_id": "t3_zzz789"},
                ],
                [
                    {
                        "comment_id": "t1_def456",
                        "parent_id": "t3_zzz789",
                        "post_id": "t3_abc123",
                    }
                ],
            )


class WorkbookImportBoundaryTests(unittest.TestCase):
    def test_output_must_be_below_project_private_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            disguised_public = (
                fake_project / "public/tmp/reddit-voc-v3/candidate"
            )
            with self.assertRaisesRegex(WorkbookImportError, "project private"):
                _private_output(disguised_public, fake_project)

    def test_symlinked_output_ancestor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            private_root = fake_project / "tmp/reddit-voc-v3"
            private_root.mkdir(parents=True)
            os.chmod(private_root, 0o700)
            outside = fake_project / "outside"
            outside.mkdir()
            (private_root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(WorkbookImportError, "symlink"):
                _private_output(private_root / "escape/candidate", fake_project)

    def test_failed_bundle_write_leaves_no_partial_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            private_root = fake_project / "tmp/reddit-voc-v3"
            private_root.mkdir(parents=True)
            os.chmod(private_root, 0o700)
            candidate = private_root / "candidate"
            with self.assertRaisesRegex(WorkbookImportError, "payload inventory"):
                _write_bundle(candidate, {}, b"{}\n", project_root=fake_project)
            self.assertFalse(candidate.exists())
            self.assertEqual(list(private_root.iterdir()), [])

    def test_interrupted_file_write_leaves_no_staging_residue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            private_root = fake_project / "tmp/reddit-voc-v3"
            private_root.mkdir(parents=True)
            os.chmod(private_root, 0o700)
            candidate = private_root / "candidate"
            payloads = {name: b"payload\n" for name in EXPECTED_FILES if name != "manifest.json"}
            with mock.patch(
                "reddit_voc.v3_workbook_import.os.write",
                side_effect=OSError("simulated write failure"),
            ):
                with self.assertRaisesRegex(WorkbookImportError, "bundle write failed"):
                    _write_bundle(
                        candidate,
                        payloads,
                        b"{}\n",
                        project_root=fake_project,
                    )
            self.assertFalse(candidate.exists())
            self.assertEqual(list(private_root.iterdir()), [])

    def test_parent_fsync_failure_removes_published_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            private_root = fake_project / "tmp/reddit-voc-v3"
            private_root.mkdir(parents=True)
            os.chmod(private_root, 0o700)
            candidate = private_root / "candidate"
            payloads = {name: b"payload\n" for name in EXPECTED_FILES if name != "manifest.json"}
            parent_inode = private_root.stat().st_ino
            original_fsync = os.fsync

            def fail_parent_fsync(descriptor: int):
                if os.fstat(descriptor).st_ino == parent_inode:
                    raise OSError("simulated parent fsync failure")
                return original_fsync(descriptor)

            with mock.patch(
                "reddit_voc.v3_workbook_import.os.fsync",
                side_effect=fail_parent_fsync,
            ):
                with self.assertRaisesRegex(WorkbookImportError, "bundle write failed"):
                    _write_bundle(
                        candidate,
                        payloads,
                        b"{}\n",
                        project_root=fake_project,
                    )
            self.assertFalse(candidate.exists())
            self.assertEqual(list(private_root.iterdir()), [])

    def test_existing_build_reservation_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            private_root = fake_project / "tmp/reddit-voc-v3"
            private_root.mkdir(parents=True)
            os.chmod(private_root, 0o700)
            candidate = private_root / "candidate"
            reservation = private_root / ".candidate.build-lock"
            reservation.write_bytes(b"owned-by-other-builder")
            os.chmod(reservation, 0o600)
            payloads = {name: b"payload\n" for name in EXPECTED_FILES if name != "manifest.json"}
            with self.assertRaisesRegex(WorkbookImportError, "already in progress"):
                _write_bundle(
                    candidate,
                    payloads,
                    b"{}\n",
                    project_root=fake_project,
                )
            self.assertEqual(reservation.read_bytes(), b"owned-by-other-builder")
            self.assertFalse(candidate.exists())

    def test_atomic_publish_never_replaces_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            (parent / "source").mkdir()
            (parent / "target").mkdir()
            descriptor = os.open(
                parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            self.addCleanup(os.close, descriptor)
            with self.assertRaisesRegex(WorkbookImportError, "immutable output"):
                workbook_import._rename_noreplace(
                    descriptor,
                    "source",
                    descriptor,
                    "target",
                )
            self.assertTrue((parent / "source").is_dir())
            self.assertTrue((parent / "target").is_dir())

    def test_builder_never_creates_or_unlinks_a_reservation_path(self) -> None:
        real_rename = getattr(workbook_import, "_rename_noreplace", None)
        self.assertIsNotNone(real_rename)
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            private_root = fake_project / "tmp/reddit-voc-v3"
            private_root.mkdir(parents=True)
            os.chmod(private_root, 0o700)
            candidate = private_root / "candidate"
            reservation_name = ".candidate.build-lock"
            payloads = {name: b"payload\n" for name in EXPECTED_FILES if name != "manifest.json"}

            def rename_then_add_foreign_reservation(
                source_fd: int,
                source_name: str,
                target_fd: int,
                target_name: str,
            ) -> None:
                with self.assertRaises(FileNotFoundError):
                    os.stat(
                        reservation_name,
                        dir_fd=target_fd,
                        follow_symlinks=False,
                    )
                real_rename(source_fd, source_name, target_fd, target_name)
                descriptor = os.open(
                    reservation_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=target_fd,
                )
                try:
                    os.write(descriptor, b"foreign-reservation")
                finally:
                    os.close(descriptor)

            with mock.patch.object(
                workbook_import,
                "_rename_noreplace",
                side_effect=rename_then_add_foreign_reservation,
            ):
                _write_bundle(
                    candidate,
                    payloads,
                    b"{}\n",
                    project_root=fake_project,
                )
            reservation = private_root / reservation_name
            self.assertEqual(reservation.read_bytes(), b"foreign-reservation")
            self.assertTrue(candidate.is_dir())

    def test_duplicate_json_keys_and_nonfinite_numbers_fail_closed(self) -> None:
        with self.assertRaisesRegex(WorkbookImportError, "duplicate JSON key"):
            _json_object(b'{"files":{},"files":{"evil":true}}', "fixture")
        with self.assertRaisesRegex(WorkbookImportError, "duplicate JSON key"):
            _json_list(
                b'[{"post_id":"abc123","post_id":"def456"}]',
                "fixture",
            )
        with self.assertRaisesRegex(WorkbookImportError, "non-finite"):
            _json_object(b'{"value":NaN}', "fixture")
        for payload in (b'{"value":1e999}', b'{"value":-1e999}'):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(WorkbookImportError, "non-finite"):
                    _json_object(payload, "fixture")

    def test_public_private_base_identity_drift_fails_closed(self) -> None:
        manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            fixture_manifest = _base_fixture_manifest(
                fake_project,
                manifest,
                public_posts=[{"post_id": "t3_abc123", "reddit_id": "t3_abc123"}],
                public_comments=[],
                private_posts=[{"post_id": "t3_zzz789", "reddit_id": "t3_zzz789"}],
                private_comments=[],
                quarantine=[],
            )

            with self.assertRaisesRegex(WorkbookImportError, "post identity drift"):
                _load_base(fixture_manifest, fake_project)

    def test_public_private_comment_parent_drift_fails_closed(self) -> None:
        manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        posts = [
            {"post_id": "t3_abc123", "reddit_id": "t3_abc123"},
            {"post_id": "t3_zzz789", "reddit_id": "t3_zzz789"},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            fixture_manifest = _base_fixture_manifest(
                fake_project,
                manifest,
                public_posts=posts,
                public_comments=[
                    {
                        "comment_id": "t1_def456",
                        "post_id": "t3_abc123",
                        "reddit_id": "t1_def456",
                    }
                ],
                private_posts=posts,
                private_comments=[
                    {
                        "comment_id": "t1_def456",
                        "post_id": "t3_zzz789",
                        "reddit_id": "t1_def456",
                    }
                ],
                quarantine=[],
            )
            with self.assertRaisesRegex(WorkbookImportError, "comment parent drift"):
                _load_base(fixture_manifest, fake_project)

    def test_public_private_comment_parent_id_drift_fails_closed(self) -> None:
        manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        posts = [{"post_id": "t3_abc123", "reddit_id": "t3_abc123"}]
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            fixture_manifest = _base_fixture_manifest(
                fake_project,
                manifest,
                public_posts=posts,
                public_comments=[
                    {
                        "comment_id": "t1_def456",
                        "parent_id": "t1_aaaaa",
                        "post_id": "t3_abc123",
                        "reddit_id": "t1_def456",
                    }
                ],
                private_posts=posts,
                private_comments=[
                    {
                        "comment_id": "t1_def456",
                        "parent_id": "t1_bbbbb",
                        "post_id": "t3_abc123",
                        "reddit_id": "t1_def456",
                    }
                ],
                quarantine=[],
            )
            with self.assertRaisesRegex(WorkbookImportError, "parent_id drift"):
                _load_base(fixture_manifest, fake_project)

    def test_public_private_permalink_conflict_sets_must_match(self) -> None:
        manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            fixture_manifest = _base_fixture_manifest(
                fake_project,
                manifest,
                public_posts=[
                    {
                        "permalink": "/r/x/comments/zzz789/other-post/",
                        "post_id": "t3_abc123",
                        "reddit_id": "t3_abc123",
                    }
                ],
                public_comments=[],
                private_posts=[
                    {"post_id": "t3_abc123", "reddit_id": "t3_abc123"}
                ],
                private_comments=[],
                quarantine=[],
            )
            with self.assertRaisesRegex(WorkbookImportError, "conflict identity drift"):
                _load_base(fixture_manifest, fake_project)

    def test_quarantine_parent_must_be_absent_from_private_posts(self) -> None:
        manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        posts = [{"post_id": "t3_abc123", "reddit_id": "t3_abc123"}]
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            fixture_manifest = _base_fixture_manifest(
                fake_project,
                manifest,
                public_posts=posts,
                public_comments=[],
                private_posts=posts,
                private_comments=[],
                quarantine=[
                    {
                        "comment_id": "t1_def456",
                        "missing_post_id": "abc123",
                        "reason": "post_attach_orphan",
                    }
                ],
            )
            with self.assertRaisesRegex(
                WorkbookImportError,
                "quarantined parent unexpectedly exists",
            ):
                _load_base(fixture_manifest, fake_project)

    def test_invalid_workbook_is_wrapped_and_no_output_is_created(self) -> None:
        manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            fake_project = Path(temporary)
            payload = b"not-an-xlsx"
            (fake_project / "broken.xlsx").write_bytes(payload)
            source = replace(
                manifest.sources[0],
                relative_path=PurePosixPath("broken.xlsx"),
                sha256=hashlib.sha256(payload).hexdigest(),
                bytes=len(payload),
            )
            fixture_manifest = replace(manifest, sources=(source,))
            with self.assertRaisesRegex(WorkbookImportError, "workbook unreadable"):
                _load_source_rows(fixture_manifest, fake_project)


class RealWorkbookImportTests(unittest.TestCase):
    def test_builds_exact_private_bundle_and_is_byte_deterministic(self) -> None:
        manifest = load_source_manifest(SOURCE_MANIFEST, ROOT)
        private_test_root = ROOT / "tmp/reddit-voc-v3"
        private_test_root.mkdir(parents=True, exist_ok=True)
        os.chmod(private_test_root, 0o700)
        temporary = tempfile.TemporaryDirectory(
            prefix="workbook-import-test-",
            dir=private_test_root,
        )
        self.addCleanup(temporary.cleanup)
        output_a = Path(temporary.name) / "import-a"
        output_b = Path(temporary.name) / "import-b"

        first = build_workbook_import(
            manifest,
            output_a,
            project_root=ROOT,
        )
        second = build_workbook_import(
            manifest,
            output_b,
            project_root=ROOT,
        )

        self.assertEqual(first.source_rows, 13_534)
        self.assertEqual(first.distinct_posts, 2_226)
        self.assertEqual(first.distinct_comments, 11_305)
        self.assertEqual(first.duplicate_rows, 3)
        self.assertEqual(first.base_overlap_posts, 54)
        self.assertEqual(first.base_overlap_comments, 738)
        self.assertEqual(first.net_new_posts, 2_172)
        self.assertEqual(first.net_new_comments, 10_567)
        self.assertEqual(
            first.terminal_outcomes,
            {
                "duplicate": 3,
                "exact_base_overlap": 792,
                "identity_conflict": 0,
                "incomplete_text": 109,
                "net_new_text_ready": 5_687,
                "unresolved_parent": 6_943,
            },
        )
        self.assertEqual(sum(first.terminal_outcomes.values()), first.source_rows)
        self.assertEqual({path.name for path in output_a.iterdir()}, EXPECTED_FILES)
        self.assertTrue(first.production_unchanged)
        self.assertEqual(first.as_dict()["status"], "candidate_built")
        self.assertEqual(
            first.as_dict()["independent_validation_status"],
            "pending",
        )

        for name in sorted(EXPECTED_FILES):
            self.assertEqual(
                (output_a / name).read_bytes(),
                (output_b / name).read_bytes(),
                name,
            )
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)

        manifest_value = json.loads((output_a / "manifest.json").read_text())
        self.assertEqual(manifest_value["status"], "candidate_built")
        self.assertEqual(
            manifest_value["independent_validation_status"],
            "pending",
        )
        self.assertEqual(
            manifest_value["consumption_status"],
            "blocked_pending_independent_validation",
        )
        self.assertFalse(manifest_value["promotable"])
        self.assertIsNone(manifest_value["validation_receipt_sha256"])
        self.assertIn("public_manifest_relative_path", manifest_value["base"])
        self.assertIn("lineage_manifest_relative_path", manifest_value["base"])
        self.assertEqual(manifest_value["files"]["parent-link-ledger.jsonl"]["rows"], 11_305)
        self.assertEqual(
            manifest_value["base"]["identity_reconciliation"]["redundant_identity_conflicts"],
            4,
        )
        self.assertEqual(
            manifest_value["base"]["identity_reconciliation"]["held_identity_conflicts"],
            4,
        )

        negative_overlap = None
        for line in (output_a / "comments.jsonl").read_text().splitlines():
            item = json.loads(line)
            if (
                item["terminal_outcome"] == "exact_base_overlap"
                and item["selection_class"] == "outcome_conditioned_negative"
            ):
                negative_overlap = item
                break
        self.assertIsNotNone(negative_overlap)
        self.assertEqual(
            negative_overlap["metric_eligibility_basis"],
            "governed_base_anchor",
        )
        self.assertEqual(
            negative_overlap["base_anchor"]["dataset_version"],
            manifest.base.dataset_version,
        )
        self.assertIn("entity_sha256", negative_overlap["base_anchor"])
        self.assertTrue(
            negative_overlap["workbook_metric_eligibility_ignored_for_overlap"]
        )

        entity_occurrence_keys: list[str] = []
        for name in ("posts.jsonl", "comments.jsonl"):
            for line in (output_a / name).read_text().splitlines():
                item = json.loads(line)
                entity_occurrence_keys.extend(
                    occurrence["occurrence_key"]
                    for occurrence in item["source_occurrences"]
                )
        row_outcome_keys = [
            json.loads(line)["occurrence_key"]
            for line in (output_a / "row-outcomes.jsonl").read_text().splitlines()
        ]
        self.assertEqual(len(entity_occurrence_keys), 13_534)
        self.assertEqual(len(set(entity_occurrence_keys)), 13_534)
        self.assertEqual(sorted(entity_occurrence_keys), sorted(row_outcome_keys))

        base_conflicts = [
            json.loads(line)
            for line in (output_a / "conflict-ledger.jsonl").read_text().splitlines()
            if json.loads(line)["conflict_type"]
            == "base_permalink_identity_disagreement"
        ]
        self.assertEqual(len(base_conflicts), 4)
        self.assertEqual(
            {item["resolution"] for item in base_conflicts},
            {"held_identity_conflict"},
        )

        conflicted_parent_comment = next(
            json.loads(line)
            for line in (output_a / "comments.jsonl").read_text().splitlines()
            if json.loads(line)["canonical_reddit_id"] == "t1_ovpacbr"
        )
        self.assertTrue(conflicted_parent_comment["base_overlap"])
        self.assertEqual(
            conflicted_parent_comment["analysis_status"],
            "governed_base_anchor_held_identity_conflict",
        )
        self.assertEqual(
            conflicted_parent_comment["metric_eligibility_basis"],
            "held_identity_conflict",
        )
        self.assertEqual(conflicted_parent_comment["effective_allowed_metric_families"], [])

        def keys(value: object):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from keys(item)
            elif isinstance(value, list):
                for item in value:
                    yield from keys(item)

        for name in EXPECTED_FILES:
            if name == "manifest.json":
                values = [json.loads((output_a / name).read_text())]
            else:
                values = [
                    json.loads(line)
                    for line in (output_a / name).read_text().splitlines()
                ]
            self.assertNotIn("author", {key.casefold() for value in values for key in keys(value)})
            self.assertNotIn(
                "author_pseudonym",
                {key.casefold() for value in values for key in keys(value)},
            )

        for path in output_a.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(output_a.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
