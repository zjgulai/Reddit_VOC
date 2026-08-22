from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from scripts import validate_reddit_v3_canonical_snapshot as validator
from scripts.validate_reddit_v3_canonical_snapshot import (
    CanonicalSnapshotValidationError,
    validate_canonical_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = ROOT / "tmp/reddit-voc-v3"
INPUTS = {
    "base_lineage_manifest_sha256": "1" * 64,
    "base_public_manifest_sha256": "2" * 64,
    "source_manifest_sha256": "3" * 64,
    "workbook_import_manifest_sha256": "4" * 64,
    "workbook_import_validation_receipt_sha256": "5" * 64,
}
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(_canonical(row) + b"\n" for row in rows)


def _write_private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _occurrence(
    key: str, post_id: str, comment_id: str | None = None
) -> dict[str, object]:
    value: dict[str, object] = {
        "occurrence_key": key,
        "post_id": post_id,
        "source_snapshot_id": "fixture",
        "source_text_sha256": _sha(key.encode("utf-8")),
        "source_url": (
            f"https://www.reddit.com/r/test/comments/{post_id}/comment/{comment_id}"
            if comment_id is not None
            else f"https://www.reddit.com/r/test/comments/{post_id}"
        ),
    }
    value["occurrence_sha256"] = _sha(_canonical(value))
    return value


def _base_provenance(canonical_id: str, entity_type: str, record: dict[str, object]) -> dict[str, object]:
    payload_sha = _sha(_canonical(record))
    occurrences = record.get("source_occurrences", record.get("source_kinds", []))
    return {
        "canonical_reddit_id": canonical_id,
        "entity_type": entity_type,
        "provenance_id": _sha(_canonical([canonical_id, "governed_base_entity", payload_sha])),
        "schema_version": "reddit_voc_canonical_provenance_v1",
        "source_occurrence_count": len(occurrences) if isinstance(occurrences, list) else 0,
        "source_payload_sha256": payload_sha,
        "source_role": "governed_base_entity",
    }


def _workbook_provenance(
    canonical_id: str,
    entity_type: str,
    occurrence: dict[str, object],
    outcome: str,
) -> dict[str, object]:
    payload_sha = _sha(_canonical(occurrence))
    key = str(occurrence["occurrence_key"])
    return {
        "canonical_reddit_id": canonical_id,
        "entity_type": entity_type,
        "occurrence_key": key,
        "provenance_id": _sha(_canonical([canonical_id, "workbook_occurrence", key, payload_sha])),
        "schema_version": "reddit_voc_canonical_provenance_v1",
        "source_occurrence": occurrence,
        "source_payload_sha256": payload_sha,
        "source_role": "workbook_occurrence",
        "source_row_terminal_outcome": outcome,
    }


class CanonicalFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.root.chmod(0o700)
        self.bundle = root / "candidate"
        self.bundle.mkdir(mode=0o700)

        p1_record = {
            "post_id": "p1",
            "reddit_id": "t3_p1",
            "title": "governed",
            "source_occurrences": [{"source_kind": "fixture"}],
        }
        p2_occurrence = _occurrence("fixture:p2", "p2")
        p2_record = {
            "canonical_reddit_id": "t3_p2",
            "comment_id": None,
            "entity_type": "post",
            "post_id": "p2",
            "schema_version": "reddit_voc_workbook_entity_v1",
            "source_occurrences": [p2_occurrence],
            "terminal_outcome": "net_new_text_ready",
        }
        self.posts = [
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": "t3_p1",
                "entity_type": "post",
                "post_id": "p1",
                "record": p1_record,
                "record_authority": "governed_base",
                "schema_version": "reddit_voc_canonical_post_v1",
            },
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": "t3_p2",
                "entity_type": "post",
                "post_id": "p2",
                "record": p2_record,
                "record_authority": "workbook_net_new",
                "schema_version": "reddit_voc_canonical_post_v1",
            },
        ]

        c1_record = {
            "body": "root",
            "comment_id": "t1_c1",
            "parent_id": "t3_p1",
            "post_id": "p1",
            "reddit_id": "t1_c1",
            "source_occurrences": [{"source_kind": "fixture"}],
        }
        c2_record = {
            "body": "nested",
            "comment_id": "t1_c2",
            "parent_id": "t1_c1",
            "post_id": "p1",
            "reddit_id": "t1_c2",
            "source_occurrences": [{"source_kind": "fixture"}],
        }
        c3_occurrence = _occurrence("fixture:c3", "p2", "c3")
        c3_record = {
            "canonical_reddit_id": "t1_c3",
            "comment_id": "t1_c3",
            "entity_type": "comment",
            "post_id": "p2",
            "schema_version": "reddit_voc_workbook_entity_v1",
            "source_occurrences": [c3_occurrence],
            "terminal_outcome": "net_new_text_ready",
        }
        c4_occurrence = _occurrence("fixture:c4", "missing", "c4")
        c4_record = {
            "canonical_reddit_id": "t1_c4",
            "comment_id": "t1_c4",
            "entity_type": "comment",
            "post_id": "missing",
            "schema_version": "reddit_voc_workbook_entity_v1",
            "source_occurrences": [c4_occurrence],
            "terminal_outcome": "unresolved_parent",
        }
        self.comments = [
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": "t1_c1",
                "comment_state": "linked",
                "entity_type": "comment",
                "immediate_parent_resolution": "resolved_root_parent",
                "post_id": "p1",
                "record": c1_record,
                "record_authority": "governed_base",
                "schema_version": "reddit_voc_canonical_comment_v1",
            },
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": "t1_c2",
                "comment_state": "linked",
                "entity_type": "comment",
                "immediate_parent_resolution": "resolved_nested_parent",
                "post_id": "p1",
                "record": c2_record,
                "record_authority": "governed_base",
                "schema_version": "reddit_voc_canonical_comment_v1",
            },
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": "t1_c3",
                "comment_state": "linked",
                "entity_type": "comment",
                "post_id": "p2",
                "record": c3_record,
                "record_authority": "workbook_net_new",
                "schema_version": "reddit_voc_canonical_comment_v1",
            },
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": "t1_c4",
                "comment_state": "unresolved_parent",
                "entity_type": "comment",
                "post_id": "missing",
                "record": c4_record,
                "record_authority": "workbook_net_new",
                "schema_version": "reddit_voc_canonical_comment_v1",
            },
        ]
        q1_record = {
            "comment_id": "t1_q1",
            "missing_post_id": "qmissing",
            "reason": "post_attach_orphan",
            "source_kinds": ["fixture"],
        }
        self.quarantine = [
            {
                "canonical_identity_state": "canonical_identity",
                "canonical_reddit_id": "t1_q1",
                "comment_state": "quarantined",
                "entity_type": "comment",
                "record": q1_record,
                "record_authority": "governed_base",
                "schema_version": "reddit_voc_canonical_quarantine_v1",
            }
        ]
        self.unresolved = [
            {
                "canonical_reddit_id": "t1_c4",
                "comment_state": "unresolved_parent",
                "post_id": "missing",
                "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
                "source_parent_link": {
                    "candidate_post_ids": ["missing"],
                    "comment_id": "t1_c4",
                    "context_available": False,
                    "parent_link_status": "unresolved_parent",
                    "post_id": "missing",
                    "schema_version": "reddit_voc_workbook_parent_link_v1",
                    "terminal_outcome": "unresolved_parent",
                },
                "source_terminal_outcome": "unresolved_parent",
            }
        ]

        overlap_occurrence = _occurrence("fixture:p1-overlap", "p1")
        self.provenance = [
            _base_provenance("t1_c1", "comment", c1_record),
            _base_provenance("t1_c2", "comment", c2_record),
            _workbook_provenance("t1_c3", "comment", c3_occurrence, "net_new_text_ready"),
            _workbook_provenance("t1_c4", "comment", c4_occurrence, "unresolved_parent"),
            _base_provenance("t1_q1", "comment", q1_record),
            _base_provenance("t3_p1", "post", p1_record),
            _workbook_provenance("t3_p1", "post", overlap_occurrence, "exact_base_overlap"),
            _workbook_provenance("t3_p2", "post", p2_occurrence, "net_new_text_ready"),
        ]
        self.provenance.sort(key=lambda row: (str(row["canonical_reddit_id"]), str(row["provenance_id"])))

        source_conflict = {
            "canonical_reddit_id": "t3_p1",
            "conflict_type": "source_text_differs_from_governed_base",
            "entity_type": "post",
            "resolution": "governed_base_wins",
            "schema_version": "reddit_voc_workbook_conflict_v1",
            "source_occurrences": [overlap_occurrence],
        }
        conflict_sha = _sha(_canonical(source_conflict))
        self.conflicts = [
            {
                "canonical_reddit_id": "t3_p1",
                "conflict_type": source_conflict["conflict_type"],
                "entity_type": "post",
                "resolution": source_conflict["resolution"],
                "schema_version": "reddit_voc_canonical_conflict_v1",
                "source_conflict_record": source_conflict,
                "source_conflict_sha256": conflict_sha,
                "source_role": "workbook_import_conflict",
            }
        ]
        self.documents = {
            "comments.jsonl": self.comments,
            "conflict-ledger.jsonl": self.conflicts,
            "posts.jsonl": self.posts,
            "provenance-ledger.jsonl": self.provenance,
            "quarantine.jsonl": self.quarantine,
            "unresolved-parent-ledger.jsonl": self.unresolved,
        }
        for name, rows in self.documents.items():
            _write_private(self.bundle / name, _jsonl(rows))
        self._write_manifest()

    def _manifest_value(self) -> dict[str, object]:
        files: dict[str, dict[str, object]] = {}
        for name in sorted(self.documents):
            payload = (self.bundle / name).read_bytes()
            files[name] = {
                "bytes": len(payload),
                "rows": payload.count(b"\n"),
                "sha256": _sha(payload),
            }
        return {
            "boundaries": BOUNDARIES,
            "canonical_counts": {
                "comments_jsonl": 4,
                "linked_comments": 3,
                "posts": 2,
                "quarantined_comments": 1,
                "stored_comments": 5,
                "unresolved_parent_comments": 1,
            },
            "consumption_status": "blocked_pending_independent_validation",
            "dataset_id": "fixture_canonical_v1",
            "files": files,
            "governed_base_parent_lineage_debt": {
                "linked_definition": "post_id_resolves_to_canonical_post_not_complete_immediate_parent_chain",
                "missing_immediate_parent_id": 0,
                "missing_parent_comment_entity": 0,
                "nested_links_whose_parent_record_lacks_immediate_parent_id": 0,
                "workbook_unresolved_parent_separate": True,
            },
            "independent_validation_status": "pending",
            "inputs": INPUTS,
            "promotable": False,
            "schema_version": "reddit_voc_canonical_snapshot_manifest_v1",
            "source_row_accounting": {
                "layer_separation": "source_row_terminal_disposition_is_not_canonical_entity_state",
                "source_rows": 4,
                "terminal_outcomes": {
                    "duplicate": 0,
                    "exact_base_overlap": 1,
                    "identity_conflict": 0,
                    "incomplete_text": 0,
                    "net_new_text_ready": 2,
                    "unresolved_parent": 1,
                },
            },
            "state_contract": {
                "canonical_identity": True,
                "comment_states": ["linked", "unresolved_parent", "quarantined"],
                "states_mutually_exclusive": True,
            },
            "status": "candidate_built",
            "validation_receipt_sha256": None,
        }

    def _write_manifest(self, mutate=None) -> None:
        value = self._manifest_value()
        if mutate is not None:
            mutate(value)
        _write_private(self.bundle / "manifest.json", _canonical(value) + b"\n")

    def rebind_document(self, name: str, rows: list[dict[str, object]]) -> None:
        self.documents[name] = rows
        _write_private(self.bundle / name, _jsonl(rows))
        self._write_manifest()

    @property
    def manifest_sha256(self) -> str:
        return _sha((self.bundle / "manifest.json").read_bytes())

    def validate(self, **overrides):
        arguments = {
            "expected_manifest_sha256": self.manifest_sha256,
            "expected_source_manifest_sha256": INPUTS["source_manifest_sha256"],
            "expected_base_public_manifest_sha256": INPUTS["base_public_manifest_sha256"],
            "expected_base_lineage_manifest_sha256": INPUTS["base_lineage_manifest_sha256"],
            "expected_workbook_import_manifest_sha256": INPUTS["workbook_import_manifest_sha256"],
            "expected_workbook_import_validation_receipt_sha256": INPUTS[
                "workbook_import_validation_receipt_sha256"
            ],
        }
        return validate_canonical_snapshot(
            self.bundle,
            ROOT,
            **{**arguments, **overrides},
        )


class StrictJsonTests(unittest.TestCase):
    def test_duplicate_keys_nonfinite_and_noncanonical_json_fail_closed(self) -> None:
        for payload in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}'):
            with self.subTest(payload=payload):
                with self.assertRaises(CanonicalSnapshotValidationError):
                    validator._decode(payload, "fixture")
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "canonical"):
            validator._jsonl(b'{"b": 1}\n', "fixture")

    def test_percent_encoded_reddit_identity_segments_fail_closed(self) -> None:
        cases = (
            ("https://www.reddit.com/r/test/comments/%70%31", "post"),
            ("https://www.reddit.com/r/test/comments/p1/comment/%63%31", "comment"),
            ("https://www.reddit.com/r/test/comments/p1%2Fcomment%2Fc1", "comment"),
        )
        for url, entity_type in cases:
            with self.subTest(url=url):
                with self.assertRaises(CanonicalSnapshotValidationError):
                    validator._reddit_identity_from_url(url, entity_type, "fixture")


class CanonicalSnapshotValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
        PRIVATE_ROOT.chmod(0o700)
        self._temporary = tempfile.TemporaryDirectory(prefix="canonical-validator-", dir=PRIVATE_ROOT)
        self.root = Path(self._temporary.name)
        self.root.chmod(0o700)
        self.fixture = CanonicalFixture(self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_valid_bundle_conserves_three_states_and_remains_blocked(self) -> None:
        before = {path.name: path.read_bytes() for path in self.fixture.bundle.iterdir()}
        result = self.fixture.validate()
        after = {path.name: path.read_bytes() for path in self.fixture.bundle.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(
            result.canonical_counts,
            {
                "comments_jsonl": 4,
                "linked_comments": 3,
                "posts": 2,
                "quarantined_comments": 1,
                "stored_comments": 5,
                "unresolved_parent_comments": 1,
            },
        )
        self.assertEqual(result.canonical_counts["stored_comments"], 3 + 1 + 1)
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.consumption_status, "blocked_pending_voc_facts")
        self.assertFalse(result.promotable)
        self.assertEqual(result.boundaries, BOUNDARIES)
        self.assertEqual(
            result.source_row_accounting["terminal_outcomes"]["identity_conflict"],
            0,
        )

    def test_inventory_and_private_modes_are_strict(self) -> None:
        extra = self.fixture.bundle / "extra.json"
        _write_private(extra, b"{}\n")
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "inventory"):
            self.fixture.validate()
        extra.unlink()
        (self.fixture.bundle / "posts.jsonl").chmod(0o644)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "0600"):
            self.fixture.validate()

    def test_changed_bytes_fail_manifest_file_binding(self) -> None:
        path = self.fixture.bundle / "posts.jsonl"
        payload = path.read_bytes()
        _write_private(path, payload[:-2] + b"0\n")
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "file binding"):
            self.fixture.validate()

    def test_rebound_foreign_key_and_state_tamper_fail_semantics(self) -> None:
        changed = json.loads(json.dumps(self.fixture.comments))
        changed[2]["post_id"] = "missing2"
        changed[2]["record"]["post_id"] = "missing2"
        self.fixture.rebind_document("comments.jsonl", changed)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "foreign key"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "state")
        changed = json.loads(json.dumps(self.fixture.comments))
        changed[2]["comment_state"] = "unresolved_parent"
        self.fixture.rebind_document("comments.jsonl", changed)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "foreign key"):
            self.fixture.validate()

    def test_rebound_unresolved_and_provenance_tamper_fail_exact_ledgers(self) -> None:
        changed = json.loads(json.dumps(self.fixture.unresolved))
        changed[0]["post_id"] = "other"
        changed[0]["source_parent_link"]["post_id"] = "other"
        self.fixture.rebind_document("unresolved-parent-ledger.jsonl", changed)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "post mismatch"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "provenance")
        changed = json.loads(json.dumps(self.fixture.provenance))
        workbook = next(row for row in changed if row["source_role"] == "workbook_occurrence")
        workbook["source_row_terminal_outcome"] = "wrong"
        self.fixture.rebind_document("provenance-ledger.jsonl", changed)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "terminal outcome"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "provenance-coverage")
        changed = json.loads(json.dumps(self.fixture.provenance))
        changed = [
            row
            for row in changed
            if not (
                row["canonical_reddit_id"] == "t1_c3"
                and row["source_role"] == "workbook_occurrence"
            )
        ]
        self.fixture.rebind_document("provenance-ledger.jsonl", changed)
        self.fixture._write_manifest(
            lambda manifest: manifest["source_row_accounting"].update(
                {
                    "source_rows": 3,
                    "terminal_outcomes": {
                        "duplicate": 0,
                        "exact_base_overlap": 1,
                        "identity_conflict": 0,
                        "incomplete_text": 0,
                        "net_new_text_ready": 1,
                        "unresolved_parent": 1,
                    },
                }
            )
        )
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "provenance is incomplete|coverage"):
            self.fixture.validate()

    def test_rebound_conflict_and_parent_cycle_fail_semantics(self) -> None:
        changed = json.loads(json.dumps(self.fixture.conflicts))
        changed[0]["resolution"] = "incoming_wins"
        self.fixture.rebind_document("conflict-ledger.jsonl", changed)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "derivation"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "cycle")
        changed = json.loads(json.dumps(self.fixture.comments))
        changed[0]["record"]["parent_id"] = "t1_c2"
        changed[0]["immediate_parent_resolution"] = "resolved_nested_parent"
        self.fixture.rebind_document("comments.jsonl", changed)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "cycle"):
            self.fixture.validate()

    def test_manifest_counts_hash_inputs_and_lifecycle_are_strict(self) -> None:
        self.fixture._write_manifest(lambda manifest: manifest["canonical_counts"].update({"stored_comments": 6}))
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "count conservation"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "bool-count")
        self.fixture._write_manifest(
            lambda manifest: manifest["canonical_counts"].update({"stored_comments": False})
        )
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "nonnegative integer"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "hash")
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "manifest hash"):
            self.fixture.validate(expected_manifest_sha256="0" * 64)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "input SHA"):
            self.fixture.validate(expected_source_manifest_sha256="0" * 64)

        self.fixture._write_manifest(lambda manifest: manifest.update({"promotable": True}))
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "lifecycle"):
            self.fixture.validate()

    def test_ascii_identity_and_state_exclusivity_are_fail_closed(self) -> None:
        changed = json.loads(json.dumps(self.fixture.posts))
        changed[0]["canonical_reddit_id"] = "t3_K"
        changed[0]["post_id"] = "K"
        changed[0]["record"]["post_id"] = "K"
        changed[0]["record"]["reddit_id"] = "t3_K"
        self.fixture.rebind_document("posts.jsonl", changed)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "ASCII"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "exclusive")
        changed = json.loads(json.dumps(self.fixture.quarantine))
        changed[0]["canonical_reddit_id"] = "t1_c1"
        changed[0]["record"]["comment_id"] = "t1_c1"
        self.fixture.rebind_document("quarantine.jsonl", changed)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "mutually exclusive"):
            self.fixture.validate()

    def test_symlink_member_and_symlink_parent_are_rejected(self) -> None:
        target = self.fixture.bundle / "posts-real.jsonl"
        os.replace(self.fixture.bundle / "posts.jsonl", target)
        (self.fixture.bundle / "posts.jsonl").symlink_to(target.name)
        with self.assertRaises(CanonicalSnapshotValidationError):
            self.fixture.validate()

        real = self.root / "real"
        fixture = CanonicalFixture(real)
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(CanonicalSnapshotValidationError):
            validate_canonical_snapshot(
                alias / "candidate",
                ROOT,
                expected_manifest_sha256=fixture.manifest_sha256,
                expected_source_manifest_sha256=INPUTS["source_manifest_sha256"],
                expected_base_public_manifest_sha256=INPUTS["base_public_manifest_sha256"],
                expected_base_lineage_manifest_sha256=INPUTS["base_lineage_manifest_sha256"],
                expected_workbook_import_manifest_sha256=INPUTS["workbook_import_manifest_sha256"],
                expected_workbook_import_validation_receipt_sha256=INPUTS[
                    "workbook_import_validation_receipt_sha256"
                ],
            )

    def test_receipt_is_canonical_private_immutable_and_outside_bundle(self) -> None:
        receipt_path = self.root / "validation/receipt.json"
        result = self.fixture.validate(receipt_path=receipt_path)
        payload = receipt_path.read_bytes()
        value = json.loads(payload)
        self.assertEqual(payload, _canonical(value) + b"\n")
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(receipt_path.parent.stat().st_mode), 0o700)
        self.assertEqual(value["bundle_manifest_sha256"], self.fixture.manifest_sha256)
        self.assertEqual(value["inputs"], INPUTS)
        self.assertEqual(value["status"], result.status)
        self.assertEqual(set(value), validator.RECEIPT_KEYS)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "already exists"):
            self.fixture.validate(receipt_path=receipt_path)
        self.assertEqual(receipt_path.read_bytes(), payload)
        members = list(receipt_path.parent.iterdir())
        self.assertEqual({path.name for path in members if not path.name.startswith(".")}, {"receipt.json"})
        stages = [path for path in members if path.name.startswith(".receipt.json.stage-")]
        self.assertEqual(len(stages), 1)
        self.assertEqual(stat.S_IMODE(stages[0].stat().st_mode), 0o600)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "outside"):
            self.fixture.validate(receipt_path=self.fixture.bundle / "receipt.json")

    def test_receipt_symlink_parent_and_foreign_replacement_fail_closed(self) -> None:
        real_parent = self.root / "real-receipt"
        real_parent.mkdir(mode=0o700)
        alias = self.root / "receipt-alias"
        alias.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaises(CanonicalSnapshotValidationError):
            self.fixture.validate(receipt_path=alias / "receipt.json")
        self.assertEqual(list(real_parent.iterdir()), [])

        receipt_parent = self.root / "foreign-replacement"
        receipt_path = receipt_parent / "receipt.json"
        real_fsync = validator.os.fsync
        replaced = False

        def replace_target_on_publish_fsync(descriptor: int) -> None:
            nonlocal replaced
            if receipt_path.exists() and not replaced:
                receipt_path.unlink()
                _write_private(receipt_path, b"foreign\n")
                replaced = True
            real_fsync(descriptor)

        with mock.patch.object(
            validator.os,
            "fsync",
            side_effect=replace_target_on_publish_fsync,
        ):
            with self.assertRaisesRegex(CanonicalSnapshotValidationError, "ownership"):
                self.fixture.validate(receipt_path=receipt_path)
        self.assertEqual(receipt_path.read_bytes(), b"foreign\n")
        self.assertEqual([path.name for path in receipt_parent.iterdir()], ["receipt.json"])

        fsync_parent = self.root / "fsync-failure"
        fsync_receipt = fsync_parent / "receipt.json"

        def fail_publish_parent_fsync(descriptor: int) -> None:
            if fsync_receipt.exists() and stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("forced receipt parent fsync failure")
            real_fsync(descriptor)

        with mock.patch.object(
            validator.os,
            "fsync",
            side_effect=fail_publish_parent_fsync,
        ):
            with self.assertRaisesRegex(CanonicalSnapshotValidationError, "atomic publish"):
                self.fixture.validate(receipt_path=fsync_receipt)
        self.assertTrue(fsync_receipt.is_file())
        self.assertEqual(stat.S_IMODE(fsync_receipt.stat().st_mode), 0o000)
        self.assertEqual(fsync_receipt.stat().st_size, 0)
        self.assertEqual([path.name for path in fsync_parent.iterdir()], ["receipt.json"])

    def test_project_tmp_symlink_is_rejected_without_outside_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            (project / "tmp").symlink_to(outside, target_is_directory=True)
            private = outside / "reddit-voc-v3"
            private.mkdir(mode=0o700)
            receipt = project / "tmp/reddit-voc-v3/new-parent/receipt.json"
            with self.assertRaises(CanonicalSnapshotValidationError):
                validator._open_or_create_receipt_parent(receipt, project)
            self.assertFalse((private / "new-parent").exists())
            with self.assertRaises(CanonicalSnapshotValidationError):
                validator._open_private_directory(
                    project / "tmp/reddit-voc-v3/candidate",
                    project,
                    "fixture bundle",
                )

    def test_workbook_occurrence_identity_terminal_and_fixed_outcomes_are_strict(self) -> None:
        changed_comments = json.loads(json.dumps(self.fixture.comments))
        changed_provenance = json.loads(json.dumps(self.fixture.provenance))
        comment = next(
            row for row in changed_comments if row["canonical_reddit_id"] == "t1_c3"
        )
        provenance = next(
            row
            for row in changed_provenance
            if row["canonical_reddit_id"] == "t1_c3"
            and row["source_role"] == "workbook_occurrence"
        )
        occurrence = provenance["source_occurrence"]
        occurrence["source_url"] = "https://www.reddit.com/r/test/comments/p2/comment/wrong"
        occurrence_without_sha = dict(occurrence)
        occurrence_without_sha.pop("occurrence_sha256")
        occurrence["occurrence_sha256"] = _sha(_canonical(occurrence_without_sha))
        comment["record"]["source_occurrences"] = [occurrence]
        provenance["source_payload_sha256"] = _sha(_canonical(occurrence))
        provenance["provenance_id"] = _sha(
            _canonical(
                [
                    "t1_c3",
                    "workbook_occurrence",
                    occurrence["occurrence_key"],
                    provenance["source_payload_sha256"],
                ]
            )
        )
        changed_provenance.sort(
            key=lambda row: (str(row["canonical_reddit_id"]), str(row["provenance_id"]))
        )
        self.fixture.rebind_document("comments.jsonl", changed_comments)
        self.fixture.rebind_document("provenance-ledger.jsonl", changed_provenance)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "URL comment identity"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "terminal-occurrence")
        changed_comments = json.loads(json.dumps(self.fixture.comments))
        changed_provenance = json.loads(json.dumps(self.fixture.provenance))
        comment = next(
            row for row in changed_comments if row["canonical_reddit_id"] == "t1_c3"
        )
        provenance = next(
            row
            for row in changed_provenance
            if row["canonical_reddit_id"] == "t1_c3"
            and row["source_role"] == "workbook_occurrence"
        )
        occurrence = provenance["source_occurrence"]
        occurrence["terminal_outcome"] = "duplicate"
        occurrence_without_sha = dict(occurrence)
        occurrence_without_sha.pop("occurrence_sha256")
        occurrence["occurrence_sha256"] = _sha(_canonical(occurrence_without_sha))
        comment["record"]["source_occurrences"] = [occurrence]
        provenance["source_payload_sha256"] = _sha(_canonical(occurrence))
        provenance["provenance_id"] = _sha(
            _canonical(
                [
                    "t1_c3",
                    "workbook_occurrence",
                    occurrence["occurrence_key"],
                    provenance["source_payload_sha256"],
                ]
            )
        )
        changed_provenance.sort(
            key=lambda row: (str(row["canonical_reddit_id"]), str(row["provenance_id"]))
        )
        self.fixture.rebind_document("comments.jsonl", changed_comments)
        self.fixture.rebind_document("provenance-ledger.jsonl", changed_provenance)
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "occurrence terminal outcome"):
            self.fixture.validate()

        self.fixture = CanonicalFixture(self.root / "outcome-keys")
        self.fixture._write_manifest(
            lambda manifest: manifest["source_row_accounting"]["terminal_outcomes"].pop(
                "duplicate"
            )
        )
        with self.assertRaisesRegex(CanonicalSnapshotValidationError, "key set"):
            self.fixture.validate()


class IndependenceTests(unittest.TestCase):
    def test_validator_imports_neither_builder_nor_identity_module(self) -> None:
        source = (ROOT / "scripts/validate_reddit_v3_canonical_snapshot.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("v3_canonical_fusion", source)
        self.assertNotIn("v3_canonical_identity", source)


if __name__ == "__main__":
    unittest.main()
