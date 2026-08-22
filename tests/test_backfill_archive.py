from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from reddit_voc.backfill_archive import (
    ArchiveIntegrityError,
    ArchiveReadOnlyError,
    PrivateRawArchive,
)


FIXED_NOW = datetime(2026, 7, 11, 4, 17, 9, tzinfo=timezone.utc)
PAYLOAD = b'{"ok":true}'
TEST_TEMP_PARENT = Path(__file__).resolve().parents[1] / ".superpowers" / "sdd"


class PrivateRawArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory(dir=TEST_TEMP_PARENT)
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "private-raw"
        self.archive = PrivateRawArchive(self.root)

    def write_artifact(self, **overrides):
        arguments = {
            "run_id": "backfill_test",
            "artifact_kind": "seed",
            "lane_type": "seed",
            "lane_key": "existing_json",
            "identity": "../../author-title",
            "payload": PAYLOAD,
            "raw_capture_id": "raw_backfill_test",
            "parser_kind": "seed_browser_thread",
            "source_method": "historical_seed",
            "source_url": "seed://fixture.json",
            "source_endpoint": "seed_file",
            "captured_at_utc": FIXED_NOW,
            "page_number": 0,
        }
        arguments.update(overrides)
        return self.archive.write(**arguments)

    def test_write_uses_hash_only_path_and_read_verified_round_trips(self):
        artifact = self.write_artifact()
        lane_hash = sha256(b"existing_json").hexdigest()
        identity_hash = sha256(b"../../author-title").hexdigest()
        payload_hash = sha256(PAYLOAD).hexdigest()

        self.assertEqual(artifact.lane_key_hash, lane_hash)
        self.assertEqual(artifact.identity_hash, identity_hash)
        self.assertEqual(artifact.payload_sha256, payload_hash)
        self.assertEqual(
            Path(artifact.relative_path).parts,
            (
                "backfill_test",
                "seed",
                lane_hash[:16],
                f"page-000000-{identity_hash[:24]}-{payload_hash[:16]}.json.gz",
            ),
        )
        for sensitive_value in ("existing_json", "author-title", "fixture.json"):
            self.assertNotIn(sensitive_value, artifact.relative_path)
        self.assertEqual(self.archive.read_verified(artifact), PAYLOAD)

    def test_repeated_write_produces_identical_metadata_and_gzip_bytes(self):
        first = self.write_artifact()
        path = self.archive.root / first.relative_path
        first_bytes = path.read_bytes()
        first_inode = path.stat().st_ino
        path.chmod(0o644)

        second = self.write_artifact()
        second_bytes = path.read_bytes()

        self.assertEqual(second, first)
        self.assertEqual(second_bytes, first_bytes)
        self.assertEqual(path.stat().st_ino, first_inode)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(first_bytes[:3], b"\x1f\x8b\x08")
        self.assertEqual(first_bytes[3] & 0x08, 0, "gzip filename flag must be absent")
        self.assertEqual(first_bytes[4:8], b"\x00\x00\x00\x00")

    def test_archive_directories_and_file_are_private(self):
        artifact = self.write_artifact()
        path = self.archive.root / artifact.relative_path
        directories = [self.archive.root]
        current = self.archive.root
        for part in Path(artifact.relative_path).parent.parts:
            current /= part
            directories.append(current)

        for directory in directories:
            with self.subTest(directory=directory):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_write_rejects_unsafe_run_artifact_and_lane_tokens(self):
        unsafe_values = (".", "..", "../escape", "/absolute", "bad/name", "bad\\name", "bad\nname")
        for field in ("run_id", "artifact_kind", "lane_type"):
            for value in unsafe_values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.write_artifact(**{field: value})

    def test_write_rejects_empty_or_non_string_raw_capture_id(self):
        for value in ("", "   ", None, b"raw"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.write_artifact(raw_capture_id=value)

    def test_read_verified_unifies_corrupt_gzip_and_payload_hash_tamper(self):
        artifact = self.write_artifact()
        path = self.archive.root / artifact.relative_path
        original = path.read_bytes()
        path.write_bytes(original + b"x")
        with self.assertRaises(ArchiveIntegrityError):
            self.archive.read_verified(artifact)

        path.write_bytes(gzip.compress(b'{"ok":false}', mtime=0))
        with self.assertRaises(ArchiveIntegrityError):
            self.archive.read_verified(artifact)

    def test_read_verified_rejects_gzip_header_and_trailing_padding_tamper(self):
        artifact = self.write_artifact()
        path = self.archive.root / artifact.relative_path
        original = path.read_bytes()
        changed_mtime = bytearray(original)
        changed_mtime[4] = 1
        tampered_variants = {
            "mtime": bytes(changed_mtime),
            "trailing_nul": original + b"\x00",
        }

        for tamper_kind, tampered in tampered_variants.items():
            with self.subTest(tamper_kind=tamper_kind):
                self.assertEqual(gzip.decompress(tampered), PAYLOAD)
                path.write_bytes(tampered)
                with self.assertRaises(ArchiveIntegrityError):
                    self.archive.read_verified(artifact)

    def test_write_rejects_existing_different_valid_gzip_without_overwrite(self):
        artifact = self.write_artifact()
        path = self.archive.root / artifact.relative_path
        existing = gzip.compress(b'{"different":true}', mtime=0)
        self.assertEqual(gzip.decompress(existing), b'{"different":true}')
        path.write_bytes(existing)

        with self.assertRaises(ArchiveIntegrityError):
            self.write_artifact()

        self.assertEqual(path.read_bytes(), existing)

    def test_read_verified_rejects_malformed_payload_sha256_as_integrity_error(self):
        artifact = self.write_artifact()
        malformed_values = (
            None,
            b"0" * 64,
            "",
            "a" * 63,
            "a" * 65,
            "A" * 64,
            "g" * 64,
            "é" * 64,
        )

        for malformed in malformed_values:
            with self.subTest(malformed=malformed):
                with self.assertRaises(ArchiveIntegrityError):
                    self.archive.read_verified(
                        replace(artifact, payload_sha256=malformed)
                    )

    def test_read_verified_rejects_resolved_paths_outside_root(self):
        artifact = self.write_artifact()
        outside = Path(self.temporary_directory.name) / "outside.json.gz"
        outside.write_bytes(gzip.compress(PAYLOAD, mtime=0))

        for relative_path in ("../outside.json.gz", str(outside), "bad\x00path"):
            with self.subTest(relative_path=relative_path):
                with self.assertRaises(ArchiveIntegrityError):
                    self.archive.read_verified(
                        replace(artifact, relative_path=relative_path)
                    )

        symlink = self.archive.root / "outside-link.json.gz"
        symlink.symlink_to(outside)
        with self.assertRaises(ArchiveIntegrityError):
            self.archive.read_verified(
                replace(artifact, relative_path=symlink.name)
            )

    def test_read_only_construction_and_write_failure_do_not_mutate_metadata(self):
        artifact = self.write_artifact()
        path = self.archive.root / artifact.relative_path
        self.archive.root.chmod(0o750)
        path.chmod(0o640)
        before_root = self.archive.root.stat()
        before_file = path.stat()
        before_entries = tuple(
            sorted(item.relative_to(self.archive.root).as_posix() for item in self.archive.root.rglob("*"))
        )

        reader = PrivateRawArchive(self.archive.root, read_only=True)
        self.assertTrue(reader.read_only)
        self.assertEqual(reader.read_verified(artifact), PAYLOAD)
        with self.assertRaisesRegex(ArchiveReadOnlyError, "raw archive is read-only"):
            reader.write(
                run_id="different_run",
                artifact_kind="seed",
                lane_type="seed",
                lane_key="new_lane",
                identity="new_identity",
                payload=b"new payload",
                raw_capture_id="new_capture",
                parser_kind="seed_browser_thread",
                source_method="historical_seed",
                source_url="seed://new",
                source_endpoint="seed_file",
                captured_at_utc=FIXED_NOW,
                page_number=0,
            )

        after_root = self.archive.root.stat()
        after_file = path.stat()
        after_entries = tuple(
            sorted(item.relative_to(self.archive.root).as_posix() for item in self.archive.root.rglob("*"))
        )
        self.assertEqual(stat.S_IMODE(after_root.st_mode), stat.S_IMODE(before_root.st_mode))
        self.assertEqual(after_root.st_mtime_ns, before_root.st_mtime_ns)
        self.assertEqual(stat.S_IMODE(after_file.st_mode), stat.S_IMODE(before_file.st_mode))
        self.assertEqual(after_file.st_mtime_ns, before_file.st_mtime_ns)
        self.assertEqual(after_entries, before_entries)

    def test_read_only_requires_an_existing_real_directory(self):
        missing = Path(self.temporary_directory.name) / "missing-archive"
        regular_file = Path(self.temporary_directory.name) / "archive-file"
        symlink_root = Path(self.temporary_directory.name) / "archive-link"
        linked_parent = Path(self.temporary_directory.name) / "linked-parent"
        regular_file.write_bytes(b"not a directory")
        symlink_root.symlink_to(self.archive.root, target_is_directory=True)
        linked_parent.symlink_to(
            Path(self.temporary_directory.name), target_is_directory=True
        )
        linked_archive = linked_parent / self.archive.root.name

        for root in (missing, regular_file, symlink_root, linked_archive):
            with self.subTest(root=root.name):
                with self.assertRaisesRegex(
                    ValueError, "read-only raw archive root must be an existing directory"
                ):
                    PrivateRawArchive(root, read_only=True)
        self.assertFalse(missing.exists())

        writable_root = linked_parent / "writable-compatible"
        writable = PrivateRawArchive(writable_root)
        self.assertEqual(
            writable.root,
            (Path(self.temporary_directory.name) / "writable-compatible").resolve(),
        )
        self.assertTrue(writable.root.is_dir())

    def test_read_verified_rejects_symlink_components_even_when_target_stays_inside_root(self):
        artifact = self.write_artifact()
        artifact_path = self.archive.root / artifact.relative_path
        target = self.archive.root / "same-bytes-target.json.gz"
        artifact_path.replace(target)
        artifact_path.symlink_to(target)

        reader = PrivateRawArchive(self.archive.root, read_only=True)
        with self.assertRaisesRegex(
            ArchiveIntegrityError, "raw archive integrity verification failed"
        ):
            reader.read_verified(artifact)

    def test_read_verified_rejects_intermediate_directory_symlink_component(self):
        artifact = self.write_artifact()
        artifact_path = self.archive.root / artifact.relative_path
        lane_directory = artifact_path.parent
        relocated = self.archive.root / "relocated-lane-directory"
        lane_directory.replace(relocated)
        lane_directory.symlink_to(relocated, target_is_directory=True)

        reader = PrivateRawArchive(self.archive.root, read_only=True)
        with self.assertRaisesRegex(
            ArchiveIntegrityError, "raw archive integrity verification failed"
        ):
            reader.read_verified(artifact)


if __name__ == "__main__":
    unittest.main()
