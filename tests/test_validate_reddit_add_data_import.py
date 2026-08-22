from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
import uuid
from unittest import mock

from scripts import validate_reddit_add_data_import as validator
from scripts.validate_reddit_add_data_import import (
    ImportValidationError,
    _decode_json_document,
    _write_private_receipt,
    validate_workbook_import,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "config/source_selection/reddit-voc-add-data-20260715-v1.json"
CANDIDATE = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1/workbook-import-candidate-a1"
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _copy_candidate(destination: Path) -> None:
    shutil.copytree(CANDIDATE, destination, copy_function=shutil.copy2)


def _replace_file(path: Path, payload: bytes) -> None:
    path.unlink()
    path.write_bytes(payload)
    path.chmod(0o600)


def _rebind_file(bundle: Path, name: str, payload: bytes) -> None:
    _replace_file(bundle / name, payload)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][name] = {
        "bytes": len(payload),
        "rows": payload.count(b"\n"),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    _replace_file(bundle / "manifest.json", _canonical_bytes(manifest) + b"\n")


class StrictJsonTests(unittest.TestCase):
    def test_duplicate_keys_and_nonfinite_numbers_fail_closed(self) -> None:
        cases = (
            b'{"a":1,"a":2}\n',
            b'{"a":NaN}\n',
            b'{"a":Infinity}\n',
            b'{"a":1e999}\n',
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ImportValidationError):
                    _decode_json_document(payload, "fixture")


class IdentityBoundaryTests(unittest.TestCase):
    def test_unicode_homoglyphs_never_fold_into_reddit_identity(self) -> None:
        for value in ("t3_K", "t1_ſ", "K", "ſ"):
            with self.subTest(value=value):
                with self.assertRaises(ImportValidationError):
                    validator._bare_id(value, "t3_", "fixture")
        for encoded in ("%E2%84%AA", "%C5%BF"):
            with self.subTest(encoded=encoded):
                with self.assertRaises(ImportValidationError):
                    validator._parse_reddit_url(
                        f"https://www.reddit.com/r/test/comments/{encoded}/title/abc123",
                        "comment",
                    )


class ReceiptBoundaryTests(unittest.TestCase):
    def _private_project(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name)
        private_root = project / "tmp/reddit-voc-v3"
        private_root.mkdir(parents=True)
        private_root.chmod(0o700)
        return temporary, project

    def test_parent_fsync_failure_leaves_no_receipt_or_stage(self) -> None:
        temporary, project = self._private_project()
        self.addCleanup(temporary.cleanup)
        target = project / "tmp/reddit-voc-v3/receipt.json"
        calls = 0

        def fail_second_fsync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("parent fsync failed")

        with mock.patch.object(validator.os, "fsync", side_effect=fail_second_fsync):
            with self.assertRaisesRegex(ImportValidationError, "atomic publish"):
                _write_private_receipt(target, {"status": "passed"}, project)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.iterdir()), [])

    def test_foreign_replacement_during_publish_is_never_accepted(self) -> None:
        temporary, project = self._private_project()
        self.addCleanup(temporary.cleanup)
        target = project / "tmp/reddit-voc-v3/receipt.json"
        real_fsync = validator.os.fsync
        calls = 0

        def replace_target_on_parent_fsync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                target.unlink()
                target.write_bytes(b"foreign\n")
                target.chmod(0o600)
            real_fsync(descriptor)

        with mock.patch.object(
            validator.os,
            "fsync",
            side_effect=replace_target_on_parent_fsync,
        ):
            with self.assertRaisesRegex(ImportValidationError, "ownership"):
                _write_private_receipt(target, {"status": "passed"}, project)
        self.assertEqual(target.read_bytes(), b"foreign\n")
        self.assertEqual(
            [path.name for path in target.parent.iterdir()],
            ["receipt.json"],
        )

    def test_failed_publish_never_unlinks_foreign_replacement(self) -> None:
        temporary, project = self._private_project()
        self.addCleanup(temporary.cleanup)
        target = project / "tmp/reddit-voc-v3/receipt.json"
        calls = 0

        def replace_target_then_fail(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                target.unlink()
                target.write_bytes(b"foreign\n")
                target.chmod(0o600)
                raise OSError("parent fsync failed after replacement")

        with mock.patch.object(
            validator.os,
            "fsync",
            side_effect=replace_target_then_fail,
        ):
            with self.assertRaisesRegex(ImportValidationError, "atomic publish"):
                _write_private_receipt(target, {"status": "passed"}, project)
        self.assertEqual(target.read_bytes(), b"foreign\n")
        self.assertEqual(
            [path.name for path in target.parent.iterdir()],
            ["receipt.json"],
        )

    def test_private_root_mode_is_checked_even_without_child_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            private_root = project / "tmp/reddit-voc-v3"
            private_root.mkdir(parents=True)
            private_root.chmod(0o755)
            with self.assertRaisesRegex(ImportValidationError, "private"):
                _write_private_receipt(
                    private_root / "receipt.json",
                    {"status": "passed"},
                    project,
                )

    def test_symlinked_receipt_parent_is_rejected(self) -> None:
        temporary, project = self._private_project()
        self.addCleanup(temporary.cleanup)
        private_root = project / "tmp/reddit-voc-v3"
        real_parent = private_root / "real"
        real_parent.mkdir(mode=0o700)
        (private_root / "alias").symlink_to(real_parent, target_is_directory=True)
        with self.assertRaises(ImportValidationError):
            _write_private_receipt(
                private_root / "alias/receipt.json",
                {"status": "passed"},
                project,
            )
        self.assertFalse((real_parent / "receipt.json").exists())


class RealCandidateValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not CANDIDATE.is_dir():
            raise AssertionError(
                "Task 2 real candidate is required before Task 3 validation tests"
            )
        private_tmp = ROOT / "tmp/reddit-voc-v3"
        private_tmp.mkdir(parents=True, exist_ok=True)
        cls._receipt_directory = tempfile.TemporaryDirectory(
            prefix="validator-receipt-", dir=private_tmp
        )
        cls.receipt_path = Path(cls._receipt_directory.name) / "receipt.json"
        before = (CANDIDATE / "manifest.json").read_bytes()
        cls.result = validate_workbook_import(
            CANDIDATE,
            SOURCE_MANIFEST,
            ROOT,
            receipt_path=cls.receipt_path,
        )
        cls.bundle_manifest_before = before
        cls.bundle_manifest_after = (CANDIDATE / "manifest.json").read_bytes()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._receipt_directory.cleanup()

    def test_real_candidate_conserves_source_rows_and_identities(self) -> None:
        self.assertEqual(self.result.schema_version, "reddit_voc_workbook_import_validation_receipt_v1")
        self.assertEqual(self.result.status, "passed")
        self.assertEqual(self.result.counts["source_rows"], 13_534)
        self.assertEqual(self.result.counts["distinct_posts"], 2_226)
        self.assertEqual(self.result.counts["distinct_comments"], 11_305)
        self.assertEqual(self.result.counts["base_overlap_posts"], 54)
        self.assertEqual(self.result.counts["base_overlap_comments"], 738)
        self.assertEqual(self.result.counts["net_new_posts"], 2_172)
        self.assertEqual(self.result.counts["net_new_comments"], 10_567)
        self.assertEqual(
            self.result.counts["terminal_outcomes"],
            {
                "duplicate": 3,
                "exact_base_overlap": 792,
                "identity_conflict": 0,
                "incomplete_text": 109,
                "net_new_text_ready": 5_687,
                "unresolved_parent": 6_943,
            },
        )
        self.assertEqual(self.result.unaccounted_source_rows, 0)
        self.assertEqual(self.result.unaccounted_import_identities, 0)

    def test_validation_never_mutates_or_admits_the_candidate(self) -> None:
        self.assertEqual(self.bundle_manifest_before, self.bundle_manifest_after)
        manifest = json.loads(self.bundle_manifest_after)
        self.assertEqual(manifest["status"], "candidate_built")
        self.assertEqual(manifest["independent_validation_status"], "pending")
        self.assertEqual(
            manifest["consumption_status"],
            "blocked_pending_independent_validation",
        )
        self.assertFalse(manifest["promotable"])
        self.assertIsNone(manifest["validation_receipt_sha256"])

    def test_receipt_is_private_canonical_and_no_overwrite(self) -> None:
        payload = self.receipt_path.read_bytes()
        value = json.loads(payload)
        self.assertEqual(payload, _canonical_bytes(value) + b"\n")
        self.assertEqual(stat.S_IMODE(self.receipt_path.stat().st_mode), 0o600)
        self.assertEqual(value["status"], "passed")
        self.assertEqual(value["consumption_status"], "blocked_pending_canonical_snapshot")
        self.assertFalse(value["promotable"])
        with self.assertRaisesRegex(ImportValidationError, "already exists"):
            _write_private_receipt(self.receipt_path, value, ROOT)

    def test_boundaries_remain_local_and_production_unchanged(self) -> None:
        self.assertEqual(
            self.result.boundaries,
            {
                "database_write": False,
                "deploy": False,
                "live_send": False,
                "production_unchanged": True,
                "provider_call": False,
                "remote_write": False,
            },
        )


class TamperValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        private_tmp = ROOT / "tmp/reddit-voc-v3"
        private_tmp.mkdir(parents=True, exist_ok=True)
        self._directory = tempfile.TemporaryDirectory(
            prefix=f"validator-tamper-{uuid.uuid4().hex}-", dir=private_tmp
        )
        self.bundle = Path(self._directory.name) / "candidate"
        _copy_candidate(self.bundle)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_changed_file_bytes_fail_manifest_binding(self) -> None:
        target = self.bundle / "row-outcomes.jsonl"
        payload = target.read_bytes()
        _replace_file(target, payload[:-2] + b"0\n")
        with self.assertRaisesRegex(ImportValidationError, "file binding"):
            validate_workbook_import(self.bundle, SOURCE_MANIFEST, ROOT)

    def test_unknown_member_and_broad_member_mode_fail_closed(self) -> None:
        unexpected = self.bundle / "unexpected.json"
        unexpected.write_bytes(b"{}\n")
        unexpected.chmod(0o600)
        with self.assertRaisesRegex(ImportValidationError, "inventory"):
            validate_workbook_import(self.bundle, SOURCE_MANIFEST, ROOT)
        unexpected.unlink()

        member = self.bundle / "posts.jsonl"
        member.chmod(0o644)
        with self.assertRaisesRegex(ImportValidationError, "private mode"):
            validate_workbook_import(self.bundle, SOURCE_MANIFEST, ROOT)

    def test_rebound_row_outcome_still_fails_independent_recomputation(self) -> None:
        path = self.bundle / "row-outcomes.jsonl"
        lines = path.read_bytes().splitlines()
        first = json.loads(lines[0])
        first["terminal_outcome"] = "unresolved_parent"
        payload = b"\n".join([_canonical_bytes(first), *lines[1:]]) + b"\n"
        _rebind_file(self.bundle, "row-outcomes.jsonl", payload)
        with self.assertRaisesRegex(ImportValidationError, "row outcome"):
            validate_workbook_import(self.bundle, SOURCE_MANIFEST, ROOT)

    def test_rebound_occurrence_hash_still_fails_source_recomputation(self) -> None:
        path = self.bundle / "posts.jsonl"
        lines = path.read_bytes().splitlines()
        first = json.loads(lines[0])
        first["source_occurrences"][0]["source_text_sha256"] = "0" * 64
        occurrence = dict(first["source_occurrences"][0])
        occurrence.pop("occurrence_sha256")
        first["source_occurrences"][0]["occurrence_sha256"] = hashlib.sha256(
            _canonical_bytes(occurrence)
        ).hexdigest()
        payload = b"\n".join([_canonical_bytes(first), *lines[1:]]) + b"\n"
        _rebind_file(self.bundle, "posts.jsonl", payload)
        with self.assertRaisesRegex(ImportValidationError, "source occurrence"):
            validate_workbook_import(self.bundle, SOURCE_MANIFEST, ROOT)

    def test_rebound_parent_and_conflict_ledgers_fail_exact_recomputation(self) -> None:
        parent_path = self.bundle / "parent-link-ledger.jsonl"
        parent_lines = parent_path.read_bytes().splitlines()
        parent = json.loads(parent_lines[0])
        parent["context_available"] = not parent["context_available"]
        parent_payload = b"\n".join(
            [_canonical_bytes(parent), *parent_lines[1:]]
        ) + b"\n"
        _rebind_file(self.bundle, "parent-link-ledger.jsonl", parent_payload)
        with self.assertRaisesRegex(ImportValidationError, "parent-link ledger"):
            validate_workbook_import(self.bundle, SOURCE_MANIFEST, ROOT)

        self._directory.cleanup()
        private_tmp = ROOT / "tmp/reddit-voc-v3"
        self._directory = tempfile.TemporaryDirectory(
            prefix=f"validator-tamper-{uuid.uuid4().hex}-", dir=private_tmp
        )
        self.bundle = Path(self._directory.name) / "candidate"
        _copy_candidate(self.bundle)
        conflict_path = self.bundle / "conflict-ledger.jsonl"
        conflict_lines = conflict_path.read_bytes().splitlines()
        conflict = json.loads(conflict_lines[0])
        conflict["resolution"] = "tampered"
        conflict_payload = b"\n".join(
            [_canonical_bytes(conflict), *conflict_lines[1:]]
        ) + b"\n"
        _rebind_file(self.bundle, "conflict-ledger.jsonl", conflict_payload)
        with self.assertRaisesRegex(ImportValidationError, "conflict ledger"):
            validate_workbook_import(self.bundle, SOURCE_MANIFEST, ROOT)

    def test_receipt_cannot_be_written_inside_validated_bundle(self) -> None:
        receipt = self.bundle / "formal-receipt.json"
        with self.assertRaisesRegex(ImportValidationError, "outside input bundle"):
            validate_workbook_import(
                self.bundle,
                SOURCE_MANIFEST,
                ROOT,
                receipt_path=receipt,
            )
        self.assertFalse(receipt.exists())


class IndependenceTests(unittest.TestCase):
    def test_validator_does_not_import_workbook_builder(self) -> None:
        source = (
            ROOT / "scripts/validate_reddit_add_data_import.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("v3_workbook_import", source)
        self.assertNotIn("build_workbook_import", source)


if __name__ == "__main__":
    unittest.main()
