from hashlib import sha256
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest

from scripts.build_backfill_release_source_archive import (
    ArchiveBuildError,
    build_archive,
)


class BackfillReleaseSourceArchiveTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, bytes]:
        source_root = root / "source"
        source_path = source_root / "src/reddit_voc/example.py"
        source_path.parent.mkdir(parents=True)
        payload = b"VALUE = 1\n"
        source_path.write_bytes(payload)
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "momcozy_backfill_release_manifest_v1",
                    "reviewed_files_sha256": {
                        "src/reddit_voc/example.py": sha256(payload).hexdigest()
                    },
                }
            ),
            encoding="utf-8",
        )
        return manifest_path, source_root, payload

    def test_build_is_deterministic_and_contains_only_reviewed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, source_root, payload = self._fixture(root)
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"

            first_result = build_archive(
                manifest_path=manifest_path,
                source_root=source_root,
                output_path=first,
            )
            second_result = build_archive(
                manifest_path=manifest_path,
                source_root=source_root,
                output_path=second,
            )

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_result["archive_sha256"], second_result["archive_sha256"])
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o644)
            with tarfile.open(first, mode="r:gz") as archive:
                self.assertEqual(archive.getnames(), ["src/reddit_voc/example.py"])
                extracted = archive.extractfile("src/reddit_voc/example.py")
                self.assertIsNotNone(extracted)
                self.assertEqual(extracted.read(), payload)

    def test_hash_mismatch_fails_before_output_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, source_root, _ = self._fixture(root)
            (source_root / "src/reddit_voc/example.py").write_bytes(b"tampered\n")
            output = root / "release.tar.gz"

            with self.assertRaisesRegex(
                ArchiveBuildError,
                r"reviewed_file_sha256_mismatch:src/reddit_voc/example\.py",
            ):
                build_archive(
                    manifest_path=manifest_path,
                    source_root=source_root,
                    output_path=output,
                )

            self.assertFalse(output.exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, source_root, _ = self._fixture(root)
            output = root / "release.tar.gz"
            output.write_bytes(b"existing")

            with self.assertRaisesRegex(ArchiveBuildError, r"\Aoutput_exists\Z"):
                build_archive(
                    manifest_path=manifest_path,
                    source_root=source_root,
                    output_path=output,
                )

            self.assertEqual(output.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
