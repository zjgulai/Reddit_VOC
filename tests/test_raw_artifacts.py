from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from reddit_voc.models import RawCapture
from reddit_voc.raw_artifacts import RawArtifactError, persist_raw_artifact


def _capture(payload: bytes) -> RawCapture:
    digest = hashlib.sha256(payload).hexdigest()
    return RawCapture(
        raw_capture_id="raw-daily-1",
        run_id="daily-20260717-0700",
        source_method="tikhub",
        source_url="https://example.invalid/reddit",
        captured_at_utc=datetime(2026, 7, 17, 0, 0, tzinfo=timezone.utc),
        auth_boundary="provider_api",
        raw_payload_hash="sha256:" + digest,
        payload_format="json",
    )


class RawArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "raw-captures"

    def test_persist_is_private_immutable_and_idempotent(self) -> None:
        payload = b'{"id":"t3_example"}\n'

        first = persist_raw_artifact(self.root, _capture(payload), payload)
        second = persist_raw_artifact(self.root, _capture(payload), payload)

        self.assertEqual(first.write_status, "created")
        self.assertEqual(second.write_status, "no_change")
        self.assertEqual(first.relative_path.as_posix(), "daily-20260717-0700/raw-daily-1.json")
        self.assertEqual(first.path.read_bytes(), payload)
        self.assertEqual(first.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(first.path.parent.stat().st_mode & 0o777, 0o700)

    def test_payload_must_match_capture_hash(self) -> None:
        with self.assertRaisesRegex(RawArtifactError, "raw payload hash mismatch"):
            persist_raw_artifact(self.root, _capture(b"expected"), b"changed")

    def test_existing_different_payload_fails_closed(self) -> None:
        payload = b'{"id":"t3_example"}\n'
        persisted = persist_raw_artifact(self.root, _capture(payload), payload)
        persisted.path.write_bytes(b"drift")

        with self.assertRaisesRegex(RawArtifactError, "raw artifact immutable collision"):
            persist_raw_artifact(self.root, _capture(payload), payload)

    def test_symlink_root_is_rejected(self) -> None:
        target = self.root.parent / "outside"
        target.mkdir()
        self.root.symlink_to(target, target_is_directory=True)

        with self.assertRaisesRegex(RawArtifactError, "raw artifact root is unsafe"):
            persist_raw_artifact(self.root, _capture(b"payload"), b"payload")


if __name__ == "__main__":
    unittest.main()
