from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.capture_reddit_candidate_sources import CapturedMember, materialize_source_freeze
from scripts.materialize_reddit_v3_source_manifest_from_freeze import (
    SourceFreezeBridgeError,
    materialize_source_manifest_from_freeze,
)
from tests.test_reddit_v3_source_manifest import _manifest_value, _write_manifest


class SourceFreezeBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = _write_manifest(self.root, _manifest_value(self.root))
        members = []
        for filename in ("full.xlsx", "negative.xlsx"):
            payload = (self.root / filename).read_bytes()
            members.append(
                CapturedMember(
                    source_namespace="reddit_exports",
                    source_kind="local_workbook",
                    relative_path=filename,
                    byte_count=len(payload),
                    mtime_ns=1,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    content=payload,
                    fusion_eligible=True,
                )
            )
        self.freeze_root = self.root / "tmp/reddit-voc-candidate-automation/source-freezes/run-a1"
        self.freeze_root.parent.mkdir(parents=True, mode=0o700)
        materialize_source_freeze(
            self.freeze_root,
            source_cutoff_utc="2026-07-18T00:00:00Z",
            members=members,
        )
        self.output = self.root / "tmp/reddit-voc-v3/candidate-orchestration/run-a1/source-manifest.json"

    def test_binds_every_source_to_matching_freeze_member_idempotently(self) -> None:
        args = {
            "base_manifest_path": self.manifest,
            "source_freeze_manifest_path": self.freeze_root / "source-freeze-manifest.json",
            "output_path": self.output,
            "source_namespaces": [
                "reddit_add_data_full_20260715=reddit_exports",
                "reddit_add_data_negative_20260715=reddit_exports",
            ],
            "project_root": self.root,
        }
        first = materialize_source_manifest_from_freeze(**args)
        second = materialize_source_manifest_from_freeze(**args)

        self.assertEqual(first["write_status"], "created")
        self.assertEqual(second["write_status"], "no_change")
        value = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(
            [row["relative_path"] for row in value["sources"]],
            [
                "tmp/reddit-voc-candidate-automation/source-freezes/run-a1/sources/reddit_exports/full.xlsx",
                "tmp/reddit-voc-candidate-automation/source-freezes/run-a1/sources/reddit_exports/negative.xlsx",
            ],
        )
        self.assertTrue(first["production_unchanged"])

    def test_rejects_missing_or_identity_drifted_freeze_members(self) -> None:
        with self.assertRaisesRegex(SourceFreezeBridgeError, "source_freeze_member_not_found"):
            materialize_source_manifest_from_freeze(
                base_manifest_path=self.manifest,
                source_freeze_manifest_path=self.freeze_root / "source-freeze-manifest.json",
                output_path=self.output,
                source_namespaces=[
                    "reddit_add_data_full_20260715=other",
                    "reddit_add_data_negative_20260715=reddit_exports",
                ],
                project_root=self.root,
            )
