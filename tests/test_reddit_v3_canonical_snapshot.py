from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import reddit_voc.v3_canonical_fusion as canonical_fusion
from reddit_voc.v3_canonical_fusion import (
    CanonicalFusionError,
    build_canonical_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
BOUNDARIES = {
    "database_write": False,
    "deploy": False,
    "live_send": False,
    "production_unchanged": True,
    "provider_call": False,
    "remote_write": False,
}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: object) -> dict[str, object]:
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    path.chmod(0o600)
    return {"bytes": len(payload), "sha256": _sha(payload)}


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    payload = b"".join(_canonical_bytes(row) for row in rows)
    path.write_bytes(payload)
    path.chmod(0o600)
    return {"bytes": len(payload), "rows": len(rows), "sha256": _sha(payload)}


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _occurrence(key: str, post_id: str) -> dict[str, object]:
    return {
        "occurrence_key": key,
        "post_id": post_id,
        "source_file_sha256": "a" * 64,
        "source_snapshot_id": "fixture-source",
        "source_text_sha256": _sha(key.encode("utf-8")),
    }


def _entity(
    entity_type: str,
    bare_id: str,
    post_id: str,
    outcome: str,
    *,
    overlap: bool = False,
    occurrences: list[dict[str, object]] | None = None,
    source_text: str | None = None,
) -> dict[str, object]:
    prefix = "t3" if entity_type == "post" else "t1"
    return {
        "analysis_status": "ready",
        "base_overlap": overlap,
        "canonical_reddit_id": f"{prefix}_{bare_id}",
        "comment_id": None if entity_type == "post" else f"t1_{bare_id}",
        "entity_type": entity_type,
        "post_id": post_id,
        "schema_version": "reddit_voc_workbook_entity_v1",
        "source_occurrences": occurrences or [_occurrence(f"fixture-source:{bare_id}", post_id)],
        "source_text": source_text if source_text is not None else f"workbook-{bare_id}",
        "terminal_outcome": outcome,
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.base = root / "base"
        self.public = root / "public"
        self.import_bundle = root / "workbook-import"
        self.base.mkdir(parents=True)
        self.public.mkdir()
        self.import_bundle.mkdir()

        self.base_posts = [
            {
                "post_id": "p1",
                "reddit_id": "t3_p1",
                "title": "governed title",
                "content": "governed body",
                "permalink": "https://www.reddit.com/r/test/comments/p1/title/",
                "source_occurrences": [{"dataset_id": "base", "source_kind": "fixture"}],
            },
            {
                "post_id": "p2",
                "reddit_id": "t3_p2",
                "title": "second",
                "content": "second body",
                "permalink": "https://www.reddit.com/r/test/comments/p2/title/",
                "source_occurrences": [{"dataset_id": "base", "source_kind": "fixture"}],
            },
        ]
        self.base_comments = [
            {
                "comment_id": "t1_c1",
                "reddit_id": "t1_c1",
                "post_id": "p1",
                "parent_id": "t3_p1",
                "body": "governed comment",
                "source_occurrences": [{"dataset_id": "base", "source_kind": "fixture"}],
            },
            {
                "comment_id": "t1_c2",
                "reddit_id": "t1_c2",
                "post_id": "p2",
                "parent_id": "t3_p2",
                "body": "second comment",
                "source_occurrences": [{"dataset_id": "base", "source_kind": "fixture"}],
            },
        ]
        self.base_quarantine = [
            {
                "comment_id": "t1_q1",
                "missing_post_id": "p9",
                "reason": "post_attach_orphan",
                "source_kinds": ["fixture"],
            }
        ]
        self.base_public_comments = [
            {key: row[key] for key in ("comment_id", "reddit_id", "post_id", "parent_id", "body")}
            for row in self.base_comments
        ]
        self.base_unresolved: list[dict[str, object]] = []
        private_files = {
            "posts.json": _write_json(self.base / "posts.json", self.base_posts),
            "comments.json": _write_json(self.base / "comments.json", self.base_comments),
            "quarantine.json": _write_json(self.base / "quarantine.json", self.base_quarantine),
        }
        private_manifest = {
            "all_checks_passed": True,
            "canonical_counts": {
                "linked_comments": 2,
                "posts": 2,
                "quarantined_comments": 1,
                "stored_comments": 3,
            },
            "dataset_version": "fixture-base-v1",
            "files": private_files,
            "schema_version": "reddit_voc_site_snapshot_manifest_v2",
        }
        self.base_manifest = self.base / "manifest.json"
        private_binding = _write_json(self.base_manifest, private_manifest)

        public_posts = [
            {key: row[key] for key in ("post_id", "reddit_id", "title", "content", "permalink")}
            for row in self.base_posts
        ]
        public_files = {
            "posts-public.json": _write_json(self.public / "posts-public.json", public_posts),
            "comments-public.json": _write_json(
                self.public / "comments-public.json", self.base_public_comments
            ),
        }
        public_manifest = {
            "all_checks_passed": True,
            "canonical_counts": private_manifest["canonical_counts"],
            "dataset_version": "fixture-base-v1",
            "files": public_files,
            "schema_version": "reddit_voc_site_snapshot_manifest_v2",
        }
        self.public_manifest = self.public / "manifest-public.json"
        public_binding = _write_json(self.public_manifest, public_manifest)

        self.source_manifest = root / "source-manifest.json"
        source_value = {
            "base": {
                "dataset_version": "fixture-base-v1",
                "lineage_manifest_relative_path": self.base_manifest.relative_to(ROOT).as_posix(),
                "lineage_manifest_sha256": private_binding["sha256"],
                "manifest_relative_path": self.public_manifest.relative_to(ROOT).as_posix(),
                "public_manifest_sha256": public_binding["sha256"],
            },
            "boundaries": BOUNDARIES,
            "dataset_id": "fixture-add-data",
            "schema_version": "reddit_voc_source_manifest_v1",
        }
        source_binding = _write_json(self.source_manifest, source_value)
        self.source_manifest_sha256 = str(source_binding["sha256"])
        self.base_public_manifest_sha256 = str(public_binding["sha256"])
        self.base_lineage_manifest_sha256 = str(private_binding["sha256"])

        posts = [
            _entity("post", "p1", "p1", "exact_base_overlap", overlap=True, source_text="incoming overwrite"),
            _entity("post", "p3", "p3", "net_new_text_ready"),
            _entity("post", "p4", "p4", "net_new_text_ready"),
            _entity("post", "p5", "p5", "net_new_text_ready"),
        ]
        self.import_posts = posts
        c3_occurrences = [_occurrence("fixture-source:c3-a", "p3"), _occurrence("fixture-source:c3-b", "p3")]
        comments = [
            _entity("comment", "c1", "p1", "exact_base_overlap", overlap=True),
            _entity("comment", "c3", "p3", "net_new_text_ready", occurrences=c3_occurrences),
            _entity("comment", "c4", "p2", "incomplete_text"),
            _entity("comment", "c5", "missing1", "unresolved_parent"),
            _entity("comment", "c6", "missing2", "unresolved_parent"),
        ]
        self.import_comments = comments
        parent_links = [
            {"comment_id": "t1_c1", "parent_link_status": "linked_governed_base_comment", "post_id": "p1"},
            {"comment_id": "t1_c3", "parent_link_status": "linked_workbook_post", "post_id": "p3"},
            {"comment_id": "t1_c4", "parent_link_status": "linked_base_post", "post_id": "p2"},
            {"comment_id": "t1_c5", "parent_link_status": "unresolved_parent", "post_id": "missing1"},
            {"comment_id": "t1_c6", "parent_link_status": "unresolved_parent", "post_id": "missing2"},
        ]
        self.import_parent_links = parent_links
        conflicts = [
            {
                "canonical_reddit_id": "t3_p1",
                "conflict_type": "source_text_differs_from_governed_base",
                "entity_type": "post",
                "resolution": "governed_base_wins",
            }
        ]
        row_outcomes = [
            {"canonical_reddit_id": "t3_p1", "occurrence_key": "fixture-source:p1", "terminal_outcome": "exact_base_overlap"},
            {"canonical_reddit_id": "t3_p3", "occurrence_key": "fixture-source:p3", "terminal_outcome": "net_new_text_ready"},
            {"canonical_reddit_id": "t3_p4", "occurrence_key": "fixture-source:p4", "terminal_outcome": "net_new_text_ready"},
            {"canonical_reddit_id": "t3_p5", "occurrence_key": "fixture-source:p5", "terminal_outcome": "net_new_text_ready"},
            {"canonical_reddit_id": "t1_c1", "occurrence_key": "fixture-source:c1", "terminal_outcome": "exact_base_overlap"},
            {"canonical_reddit_id": "t1_c3", "occurrence_key": "fixture-source:c3-a", "terminal_outcome": "net_new_text_ready"},
            {"canonical_reddit_id": "t1_c3", "occurrence_key": "fixture-source:c3-b", "terminal_outcome": "duplicate"},
            {"canonical_reddit_id": "t1_c4", "occurrence_key": "fixture-source:c4", "terminal_outcome": "incomplete_text"},
            {"canonical_reddit_id": "t1_c5", "occurrence_key": "fixture-source:c5", "terminal_outcome": "unresolved_parent"},
            {"canonical_reddit_id": "t1_c6", "occurrence_key": "fixture-source:c6", "terminal_outcome": "unresolved_parent"},
        ]
        self.import_row_outcomes = row_outcomes
        import_files = {
            "comments.jsonl": _write_jsonl(self.import_bundle / "comments.jsonl", comments),
            "conflict-ledger.jsonl": _write_jsonl(self.import_bundle / "conflict-ledger.jsonl", conflicts),
            "parent-link-ledger.jsonl": _write_jsonl(self.import_bundle / "parent-link-ledger.jsonl", parent_links),
            "posts.jsonl": _write_jsonl(self.import_bundle / "posts.jsonl", posts),
            "row-outcomes.jsonl": _write_jsonl(self.import_bundle / "row-outcomes.jsonl", row_outcomes),
        }
        terminal = {
            "duplicate": 1,
            "exact_base_overlap": 2,
            "identity_conflict": 0,
            "incomplete_text": 1,
            "net_new_text_ready": 4,
            "unresolved_parent": 2,
        }
        import_manifest = {
            "base": {
                "dataset_version": "fixture-base-v1",
                "lineage_manifest_sha256": self.base_lineage_manifest_sha256,
                "public_manifest_sha256": self.base_public_manifest_sha256,
            },
            "boundaries": BOUNDARIES,
            "consumption_status": "blocked_pending_independent_validation",
            "counts": {
                "base_overlap_comments": 1,
                "base_overlap_posts": 1,
                "distinct_comments": 5,
                "distinct_posts": 4,
                "duplicate_rows": 1,
                "net_new_comments": 4,
                "net_new_posts": 3,
                "source_rows": 10,
                "terminal_outcomes": terminal,
            },
            "dataset_id": "fixture-add-data",
            "files": import_files,
            "independent_validation_status": "pending",
            "promotable": False,
            "schema_version": "reddit_voc_workbook_import_manifest_v1",
            "source_manifest_sha256": self.source_manifest_sha256,
            "status": "candidate_built",
            "validation_receipt_sha256": None,
        }
        self.import_manifest = self.import_bundle / "manifest.json"
        import_binding = _write_json(self.import_manifest, import_manifest)
        self.import_bundle_manifest_sha256 = str(import_binding["sha256"])

        self.import_receipt = root / "import-validation-receipt.json"
        receipt_value = {
            "base_lineage_manifest_sha256": self.base_lineage_manifest_sha256,
            "base_public_manifest_sha256": self.base_public_manifest_sha256,
            "boundaries": BOUNDARIES,
            "bundle_manifest_sha256": self.import_bundle_manifest_sha256,
            "consumption_status": "blocked_pending_canonical_snapshot",
            "counts": import_manifest["counts"],
            "promotable": False,
            "schema_version": "reddit_voc_workbook_import_validation_receipt_v1",
            "source_manifest_sha256": self.source_manifest_sha256,
            "status": "passed",
            "unaccounted_import_identities": 0,
            "unaccounted_source_rows": 0,
        }
        receipt_binding = _write_json(self.import_receipt, receipt_value)
        self.import_validation_receipt_sha256 = str(receipt_binding["sha256"])

    def build(self, output_root: Path):
        return build_canonical_snapshot(
            import_bundle_root=self.import_bundle,
            import_bundle_manifest_sha256=self.import_bundle_manifest_sha256,
            import_validation_receipt_path=self.import_receipt,
            import_validation_receipt_sha256=self.import_validation_receipt_sha256,
            source_manifest_path=self.source_manifest,
            base_public_manifest_sha256=self.base_public_manifest_sha256,
            base_lineage_manifest_sha256=self.base_lineage_manifest_sha256,
            output_root=output_root,
            project_root=ROOT,
        )

    def rebind_base_comments(
        self,
        private_comments: list[dict[str, object]],
        public_comments: list[dict[str, object]],
    ) -> None:
        self.base_comments = private_comments
        self.base_public_comments = public_comments
        private_file = _write_json(self.base / "comments.json", private_comments)
        public_file = _write_json(self.public / "comments-public.json", public_comments)
        private_manifest = json.loads(self.base_manifest.read_text(encoding="utf-8"))
        public_manifest = json.loads(self.public_manifest.read_text(encoding="utf-8"))
        private_manifest["files"]["comments.json"] = private_file
        public_manifest["files"]["comments-public.json"] = public_file
        _write_json(self.base_manifest, private_manifest)
        _write_json(self.public_manifest, public_manifest)
        self._sync_base_bindings()

    def rebind_base_unresolved(self, unresolved_rows: list[dict[str, object]]) -> None:
        self.base_unresolved = unresolved_rows
        private_manifest = json.loads(self.base_manifest.read_text(encoding="utf-8"))
        if unresolved_rows:
            private_manifest["files"]["unresolved-parent-ledger.jsonl"] = _write_jsonl(
                self.base / "unresolved-parent-ledger.jsonl", unresolved_rows
            )
        else:
            private_manifest["files"].pop("unresolved-parent-ledger.jsonl", None)
        _write_json(self.base_manifest, private_manifest)
        self._sync_base_bindings()

    def _sync_base_bindings(self) -> None:
        private_manifest = json.loads(self.base_manifest.read_text(encoding="utf-8"))
        public_manifest = json.loads(self.public_manifest.read_text(encoding="utf-8"))
        private_binding = _write_json(self.base_manifest, private_manifest)
        public_binding = _write_json(self.public_manifest, public_manifest)
        self.base_lineage_manifest_sha256 = str(private_binding["sha256"])
        self.base_public_manifest_sha256 = str(public_binding["sha256"])

        source = json.loads(self.source_manifest.read_text(encoding="utf-8"))
        source["base"]["lineage_manifest_sha256"] = self.base_lineage_manifest_sha256
        source["base"]["public_manifest_sha256"] = self.base_public_manifest_sha256
        source_binding = _write_json(self.source_manifest, source)
        self.source_manifest_sha256 = str(source_binding["sha256"])

        import_manifest = json.loads(self.import_manifest.read_text(encoding="utf-8"))
        import_manifest["base"]["lineage_manifest_sha256"] = self.base_lineage_manifest_sha256
        import_manifest["base"]["public_manifest_sha256"] = self.base_public_manifest_sha256
        import_manifest["source_manifest_sha256"] = self.source_manifest_sha256
        import_binding = _write_json(self.import_manifest, import_manifest)
        self.import_bundle_manifest_sha256 = str(import_binding["sha256"])

        receipt = json.loads(self.import_receipt.read_text(encoding="utf-8"))
        receipt["base_lineage_manifest_sha256"] = self.base_lineage_manifest_sha256
        receipt["base_public_manifest_sha256"] = self.base_public_manifest_sha256
        receipt["bundle_manifest_sha256"] = self.import_bundle_manifest_sha256
        receipt["source_manifest_sha256"] = self.source_manifest_sha256
        receipt_binding = _write_json(self.import_receipt, receipt)
        self.import_validation_receipt_sha256 = str(receipt_binding["sha256"])

    def _rebind_import_counts(
        self,
        import_posts: list[dict[str, object]],
        import_comments: list[dict[str, object]],
        import_row_outcomes: list[dict[str, object]],
    ) -> dict[str, object]:
        base_overlap_posts = sum(1 for row in import_posts if row.get("base_overlap") is True)
        base_overlap_comments = sum(1 for row in import_comments if row.get("base_overlap") is True)
        outcome_counts = Counter(
            row.get("terminal_outcome")
            for row in import_row_outcomes
            if isinstance(row.get("terminal_outcome"), str)
        )
        return {
            "base_overlap_comments": base_overlap_comments,
            "base_overlap_posts": base_overlap_posts,
            "distinct_comments": len(import_comments),
            "distinct_posts": len(import_posts),
            "duplicate_rows": outcome_counts["duplicate"],
            "net_new_comments": len(import_comments) - base_overlap_comments,
            "net_new_posts": len(import_posts) - base_overlap_posts,
            "source_rows": len(import_row_outcomes),
            "terminal_outcomes": dict(outcome_counts),
        }

    def rebind_import_bundle(
        self,
        comments: list[dict[str, object]],
        parent_links: list[dict[str, object]],
        row_outcomes: list[dict[str, object]],
    ) -> None:
        self.import_comments = comments
        self.import_parent_links = parent_links
        self.import_row_outcomes = row_outcomes
        import_manifest = json.loads(self.import_manifest.read_text(encoding="utf-8"))
        import_manifest["files"]["comments.jsonl"] = _write_jsonl(
            self.import_bundle / "comments.jsonl", comments
        )
        import_manifest["files"]["parent-link-ledger.jsonl"] = _write_jsonl(
            self.import_bundle / "parent-link-ledger.jsonl", parent_links
        )
        import_manifest["files"]["row-outcomes.jsonl"] = _write_jsonl(
            self.import_bundle / "row-outcomes.jsonl", row_outcomes
        )
        import_manifest["counts"] = self._rebind_import_counts(
            import_posts=self.import_posts,
            import_comments=comments,
            import_row_outcomes=row_outcomes,
        )
        import_binding = _write_json(self.import_manifest, import_manifest)
        self.import_bundle_manifest_sha256 = str(import_binding["sha256"])
        receipt = json.loads(self.import_receipt.read_text(encoding="utf-8"))
        receipt["counts"] = import_manifest["counts"]
        receipt["bundle_manifest_sha256"] = self.import_bundle_manifest_sha256
        _write_json(self.import_receipt, receipt)
        self._sync_base_bindings()


class CanonicalSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        private_tmp = ROOT / "tmp/reddit-voc-v3"
        private_tmp.mkdir(parents=True, exist_ok=True)
        self._tmp = tempfile.TemporaryDirectory(prefix="canonical-fixture-", dir=private_tmp)
        self.fixture = Fixture(Path(self._tmp.name))
        self.output = Path(self._tmp.name) / "canonical-candidate"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_comment_states_are_mutually_exclusive_and_conserved(self) -> None:
        result = self.fixture.build(self.output)
        self.assertEqual(result.posts, 5)
        self.assertEqual(result.stored_comments, 7)
        self.assertEqual(result.linked_comments, 4)
        self.assertEqual(result.unresolved_parent_comments, 2)
        self.assertEqual(result.quarantined_comments, 1)
        self.assertEqual(
            result.linked_comments + result.unresolved_parent_comments + result.quarantined_comments,
            result.stored_comments,
        )
        comments = _read_jsonl(self.output / "comments.jsonl")
        states = {str(row["canonical_reddit_id"]): str(row["comment_state"]) for row in comments}
        self.assertEqual(states["t1_c4"], "linked")
        self.assertEqual(states["t1_c5"], "unresolved_parent")
        self.assertNotIn("t1_q1", states)
        self.assertEqual(len(_read_jsonl(self.output / "quarantine.jsonl")), 1)
        self.assertEqual(len(_read_jsonl(self.output / "unresolved-parent-ledger.jsonl")), 2)

    def test_base_unresolved_overlap_can_transition_to_linked(self) -> None:
        self.fixture.rebind_base_unresolved(
            [
                {
                    "canonical_reddit_id": "t1_c5",
                    "comment_state": "unresolved_parent",
                    "post_id": "missing1",
                    "schema_version": "reddit_voc_canonical_unresolved_parent_v1",
                    "source_terminal_outcome": "unresolved_parent",
                }
            ]
        )
        comments = _read_jsonl(self.fixture.import_bundle / "comments.jsonl")
        for row in comments:
            if row["canonical_reddit_id"] == "t1_c5":
                row["base_overlap"] = True
                row["terminal_outcome"] = "exact_base_overlap"
        parent_links = _read_jsonl(
            self.fixture.import_bundle / "parent-link-ledger.jsonl"
        )
        for row in parent_links:
            if row["comment_id"] == "t1_c5":
                row["parent_link_status"] = "linked_base_post"
        row_outcomes = _read_jsonl(
            self.fixture.import_bundle / "row-outcomes.jsonl"
        )
        for row in row_outcomes:
            if row["canonical_reddit_id"] == "t1_c5":
                row["terminal_outcome"] = "exact_base_overlap"

        self.fixture.rebind_import_bundle(comments, parent_links, row_outcomes)
        result = self.fixture.build(self.output)
        self.assertEqual(result.linked_comments, 5)
        self.assertEqual(result.unresolved_parent_comments, 1)
        self.assertEqual(result.quarantined_comments, 1)
        output_comments = {
            row["canonical_reddit_id"]: row for row in _read_jsonl(self.output / "comments.jsonl")
        }
        self.assertEqual(output_comments["t1_c5"]["comment_state"], "linked")
        unresolved = _read_jsonl(self.output / "unresolved-parent-ledger.jsonl")
        self.assertEqual(len(unresolved), 1)
        self.assertNotIn("t1_c5", {row["canonical_reddit_id"] for row in unresolved})

    def test_governed_base_fields_win_and_workbook_overlap_only_appends_lineage(self) -> None:
        self.fixture.build(self.output)
        posts = {row["canonical_reddit_id"]: row for row in _read_jsonl(self.output / "posts.jsonl")}
        overlap = posts["t3_p1"]
        self.assertEqual(overlap["record_authority"], "governed_base")
        self.assertEqual(overlap["record"], self.fixture.base_posts[0])
        self.assertNotIn("incoming overwrite", json.dumps(overlap["record"]))
        provenance = _read_jsonl(self.output / "provenance-ledger.jsonl")
        workbook_rows = [
            row
            for row in provenance
            if row["canonical_reddit_id"] == "t3_p1" and row["source_role"] == "workbook_occurrence"
        ]
        self.assertEqual(len(workbook_rows), 1)
        conflicts = _read_jsonl(self.output / "conflict-ledger.jsonl")
        self.assertTrue(any(row["canonical_reddit_id"] == "t3_p1" for row in conflicts))

    def test_source_row_terminal_outcomes_remain_separate_from_canonical_state(self) -> None:
        self.fixture.build(self.output)
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_row_accounting"]["terminal_outcomes"]["duplicate"], 1)
        self.assertEqual(manifest["canonical_counts"]["stored_comments"], 7)
        self.assertEqual(manifest["canonical_counts"]["linked_comments"], 4)

    def test_receipt_status_and_boundary_are_strict(self) -> None:
        receipt = json.loads(self.fixture.import_receipt.read_text(encoding="utf-8"))
        for key, value in (("status", "failed"), ("consumption_status", "ready")):
            with self.subTest(key=key):
                changed = dict(receipt)
                changed[key] = value
                binding = _write_json(self.fixture.import_receipt, changed)
                with self.assertRaisesRegex(CanonicalFusionError, "validation receipt"):
                    build_canonical_snapshot(
                        import_bundle_root=self.fixture.import_bundle,
                        import_bundle_manifest_sha256=self.fixture.import_bundle_manifest_sha256,
                        import_validation_receipt_path=self.fixture.import_receipt,
                        import_validation_receipt_sha256=str(binding["sha256"]),
                        source_manifest_path=self.fixture.source_manifest,
                        base_public_manifest_sha256=self.fixture.base_public_manifest_sha256,
                        base_lineage_manifest_sha256=self.fixture.base_lineage_manifest_sha256,
                        output_root=self.output,
                        project_root=ROOT,
                    )
                _write_json(self.fixture.import_receipt, receipt)

        changed = dict(receipt)
        changed["boundaries"] = {**BOUNDARIES, "remote_write": True}
        binding = _write_json(self.fixture.import_receipt, changed)
        with self.assertRaisesRegex(CanonicalFusionError, "validation receipt boundaries"):
            build_canonical_snapshot(
                import_bundle_root=self.fixture.import_bundle,
                import_bundle_manifest_sha256=self.fixture.import_bundle_manifest_sha256,
                import_validation_receipt_path=self.fixture.import_receipt,
                import_validation_receipt_sha256=str(binding["sha256"]),
                source_manifest_path=self.fixture.source_manifest,
                base_public_manifest_sha256=self.fixture.base_public_manifest_sha256,
                base_lineage_manifest_sha256=self.fixture.base_lineage_manifest_sha256,
                output_root=self.output,
                project_root=ROOT,
            )

    def test_receipt_unaccounted_fields_require_integer_zero(self) -> None:
        original = json.loads(self.fixture.import_receipt.read_text(encoding="utf-8"))
        for field in ("unaccounted_source_rows", "unaccounted_import_identities"):
            with self.subTest(field=field):
                output = self.output.parent / f"{self.output.name}-{field}"
                changed = dict(original)
                changed[field] = False
                binding = _write_json(self.fixture.import_receipt, changed)
                with self.assertRaisesRegex(CanonicalFusionError, "unaccounted"):
                    build_canonical_snapshot(
                        import_bundle_root=self.fixture.import_bundle,
                        import_bundle_manifest_sha256=self.fixture.import_bundle_manifest_sha256,
                        import_validation_receipt_path=self.fixture.import_receipt,
                        import_validation_receipt_sha256=str(binding["sha256"]),
                        source_manifest_path=self.fixture.source_manifest,
                        base_public_manifest_sha256=self.fixture.base_public_manifest_sha256,
                        base_lineage_manifest_sha256=self.fixture.base_lineage_manifest_sha256,
                        output_root=output,
                        project_root=ROOT,
                    )
                _write_json(self.fixture.import_receipt, original)

    def test_output_parent_symlink_has_no_outside_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            private_root = project / "tmp/reddit-voc-v3"
            private_root.mkdir(parents=True)
            private_root.chmod(0o700)
            outside = project / "outside"
            outside.mkdir()
            (private_root / "alias").symlink_to(outside, target_is_directory=True)
            output = private_root / "alias/created-parent/candidate"
            with self.assertRaises(CanonicalFusionError):
                canonical_fusion._write_bundle(
                    output,
                    {"manifest.json": b"{}\n"},
                    project_root=project,
                )
            self.assertEqual(list(outside.iterdir()), [])

    def test_publish_replacement_is_not_accepted_or_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            output = project / "tmp/reddit-voc-v3/candidate"
            real_fsync = canonical_fusion.os.fsync
            replaced = False

            def replace_published_target(descriptor: int) -> None:
                nonlocal replaced
                if output.is_dir() and not replaced:
                    for member in output.iterdir():
                        member.unlink()
                    output.rmdir()
                    output.mkdir(mode=0o700)
                    (output / "foreign.txt").write_bytes(b"foreign\n")
                    replaced = True
                real_fsync(descriptor)

            with mock.patch.object(
                canonical_fusion.os,
                "fsync",
                side_effect=replace_published_target,
            ):
                with self.assertRaisesRegex(CanonicalFusionError, "ownership"):
                    canonical_fusion._write_bundle(
                        output,
                        {"manifest.json": b"{}\n"},
                        project_root=project,
                    )
            self.assertEqual((output / "foreign.txt").read_bytes(), b"foreign\n")

    def test_zero_progress_write_retains_only_non_candidate_failure_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            output = project / "tmp/reddit-voc-v3/candidate"
            with mock.patch.object(canonical_fusion.os, "write", return_value=0):
                with self.assertRaisesRegex(CanonicalFusionError, "publish canonical bundle"):
                    canonical_fusion._write_bundle(
                        output,
                        {"manifest.json": b"{}\n"},
                        project_root=project,
                    )
            parent = project / "tmp/reddit-voc-v3"
            shells = list(parent.iterdir())
            self.assertEqual(len(shells), 1)
            self.assertIn("staging", shells[0].name)
            self.assertEqual(
                [path.name for path in shells[0].iterdir()],
                [".publish-failed"],
            )

    def test_staging_fchmod_failure_retains_only_non_candidate_failure_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            output = project / "tmp/reddit-voc-v3/candidate"
            real_fchmod = canonical_fusion.os.fchmod
            failed = False

            def fail_first_directory_fchmod(descriptor: int, mode: int) -> None:
                nonlocal failed
                if stat.S_ISDIR(os.fstat(descriptor).st_mode) and not failed:
                    failed = True
                    raise OSError("forced staging fchmod failure")
                real_fchmod(descriptor, mode)

            with mock.patch.object(
                canonical_fusion.os,
                "fchmod",
                side_effect=fail_first_directory_fchmod,
            ):
                with self.assertRaisesRegex(CanonicalFusionError, "publish canonical bundle"):
                    canonical_fusion._write_bundle(
                        output,
                        {"manifest.json": b"{}\n"},
                        project_root=project,
                    )
            parent = project / "tmp/reddit-voc-v3"
            shells = list(parent.iterdir())
            self.assertEqual(len(shells), 1)
            self.assertIn("staging", shells[0].name)
            self.assertEqual(
                [path.name for path in shells[0].iterdir()],
                [".publish-failed"],
            )

    def test_all_input_hashes_are_explicitly_bound(self) -> None:
        cases = (
            {"import_bundle_manifest_sha256": "0" * 64},
            {"import_validation_receipt_sha256": "0" * 64},
            {"base_public_manifest_sha256": "0" * 64},
            {"base_lineage_manifest_sha256": "0" * 64},
        )
        common = {
            "import_bundle_root": self.fixture.import_bundle,
            "import_bundle_manifest_sha256": self.fixture.import_bundle_manifest_sha256,
            "import_validation_receipt_path": self.fixture.import_receipt,
            "import_validation_receipt_sha256": self.fixture.import_validation_receipt_sha256,
            "source_manifest_path": self.fixture.source_manifest,
            "base_public_manifest_sha256": self.fixture.base_public_manifest_sha256,
            "base_lineage_manifest_sha256": self.fixture.base_lineage_manifest_sha256,
            "output_root": self.output,
            "project_root": ROOT,
        }
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaisesRegex(CanonicalFusionError, "SHA-256|hash|binding"):
                    build_canonical_snapshot(**{**common, **override})

    def test_output_is_private_immutable_and_deterministic(self) -> None:
        result = self.fixture.build(self.output)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        for path in self.output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        first = {path.name: path.read_bytes() for path in self.output.iterdir()}
        with self.assertRaisesRegex(CanonicalFusionError, "already exists"):
            self.fixture.build(self.output)

        other = Path(self._tmp.name) / "canonical-candidate-2"
        second_result = self.fixture.build(other)
        second = {path.name: path.read_bytes() for path in other.iterdir()}
        self.assertEqual(first, second)
        self.assertEqual(result.manifest_sha256, second_result.manifest_sha256)

    def test_parent_fsync_failure_retains_only_non_candidate_failure_shell(self) -> None:
        real_fsync = os.fsync
        parent_inode = self.output.parent.stat().st_ino

        def fail_parent_fsync(descriptor: int) -> None:
            if os.fstat(descriptor).st_ino == parent_inode:
                raise OSError("forced parent fsync failure")
            real_fsync(descriptor)

        with mock.patch("reddit_voc.v3_canonical_fusion.os.fsync", side_effect=fail_parent_fsync):
            with self.assertRaisesRegex(CanonicalFusionError, "publish canonical bundle"):
                self.fixture.build(self.output)
        self.assertTrue(self.output.is_dir())
        self.assertEqual(
            [path.name for path in self.output.iterdir()],
            [".publish-failed"],
        )
        self.assertFalse(any("staging" in path.name for path in self.output.parent.iterdir()))

    def test_public_private_base_identity_mismatch_fails_closed(self) -> None:
        public_posts = json.loads((self.fixture.public / "posts-public.json").read_text(encoding="utf-8"))
        public_posts.pop()
        file_binding = _write_json(self.fixture.public / "posts-public.json", public_posts)
        manifest = json.loads(self.fixture.public_manifest.read_text(encoding="utf-8"))
        manifest["files"]["posts-public.json"] = file_binding
        manifest_binding = _write_json(self.fixture.public_manifest, manifest)
        source = json.loads(self.fixture.source_manifest.read_text(encoding="utf-8"))
        source["base"]["public_manifest_sha256"] = manifest_binding["sha256"]
        source_binding = _write_json(self.fixture.source_manifest, source)
        import_manifest = json.loads(self.fixture.import_manifest.read_text(encoding="utf-8"))
        import_manifest["source_manifest_sha256"] = source_binding["sha256"]
        import_manifest["base"]["public_manifest_sha256"] = manifest_binding["sha256"]
        import_binding = _write_json(self.fixture.import_manifest, import_manifest)
        receipt = json.loads(self.fixture.import_receipt.read_text(encoding="utf-8"))
        receipt["base_public_manifest_sha256"] = manifest_binding["sha256"]
        receipt["bundle_manifest_sha256"] = import_binding["sha256"]
        receipt["source_manifest_sha256"] = source_binding["sha256"]
        receipt_binding = _write_json(self.fixture.import_receipt, receipt)
        with self.assertRaisesRegex(CanonicalFusionError, "identity sets"):
            build_canonical_snapshot(
                import_bundle_root=self.fixture.import_bundle,
                import_bundle_manifest_sha256=str(import_binding["sha256"]),
                import_validation_receipt_path=self.fixture.import_receipt,
                import_validation_receipt_sha256=str(receipt_binding["sha256"]),
                source_manifest_path=self.fixture.source_manifest,
                base_public_manifest_sha256=str(manifest_binding["sha256"]),
                base_lineage_manifest_sha256=self.fixture.base_lineage_manifest_sha256,
                output_root=self.output,
                project_root=ROOT,
            )

    def test_base_nested_comment_must_stay_in_thread_and_acyclic(self) -> None:
        cases = (
            ("t1_c2", "crosses threads"),
            ("t1_c1", "cycle"),
        )
        for parent_id, expected_error in cases:
            with self.subTest(parent_id=parent_id):
                private_comments = json.loads(
                    (self.fixture.base / "comments.json").read_text(encoding="utf-8")
                )
                public_comments = json.loads(
                    (self.fixture.public / "comments-public.json").read_text(encoding="utf-8")
                )
                private_comments[0]["parent_id"] = parent_id
                public_comments[0]["parent_id"] = parent_id
                private_file = _write_json(self.fixture.base / "comments.json", private_comments)
                public_file = _write_json(self.fixture.public / "comments-public.json", public_comments)
                private_manifest = json.loads(self.fixture.base_manifest.read_text(encoding="utf-8"))
                public_manifest = json.loads(self.fixture.public_manifest.read_text(encoding="utf-8"))
                private_manifest["files"]["comments.json"] = private_file
                public_manifest["files"]["comments-public.json"] = public_file
                private_binding = _write_json(self.fixture.base_manifest, private_manifest)
                public_binding = _write_json(self.fixture.public_manifest, public_manifest)
                source = json.loads(self.fixture.source_manifest.read_text(encoding="utf-8"))
                source["base"]["lineage_manifest_sha256"] = private_binding["sha256"]
                source["base"]["public_manifest_sha256"] = public_binding["sha256"]
                source_binding = _write_json(self.fixture.source_manifest, source)
                import_manifest = json.loads(self.fixture.import_manifest.read_text(encoding="utf-8"))
                import_manifest["base"]["lineage_manifest_sha256"] = private_binding["sha256"]
                import_manifest["base"]["public_manifest_sha256"] = public_binding["sha256"]
                import_manifest["source_manifest_sha256"] = source_binding["sha256"]
                import_binding = _write_json(self.fixture.import_manifest, import_manifest)
                receipt = json.loads(self.fixture.import_receipt.read_text(encoding="utf-8"))
                receipt["base_lineage_manifest_sha256"] = private_binding["sha256"]
                receipt["base_public_manifest_sha256"] = public_binding["sha256"]
                receipt["bundle_manifest_sha256"] = import_binding["sha256"]
                receipt["source_manifest_sha256"] = source_binding["sha256"]
                receipt_binding = _write_json(self.fixture.import_receipt, receipt)
                with self.assertRaisesRegex(CanonicalFusionError, expected_error):
                    build_canonical_snapshot(
                        import_bundle_root=self.fixture.import_bundle,
                        import_bundle_manifest_sha256=str(import_binding["sha256"]),
                        import_validation_receipt_path=self.fixture.import_receipt,
                        import_validation_receipt_sha256=str(receipt_binding["sha256"]),
                        source_manifest_path=self.fixture.source_manifest,
                        base_public_manifest_sha256=str(public_binding["sha256"]),
                        base_lineage_manifest_sha256=str(private_binding["sha256"]),
                        output_root=self.output,
                        project_root=ROOT,
                    )
                self.fixture = Fixture(Path(self._tmp.name) / f"reset-{parent_id}")
                self.output = Path(self._tmp.name) / f"candidate-{parent_id}"

    def test_governed_missing_immediate_parent_is_separate_lineage_debt(self) -> None:
        private_comments = json.loads(
            (self.fixture.base / "comments.json").read_text(encoding="utf-8")
        )
        public_comments = json.loads(
            (self.fixture.public / "comments-public.json").read_text(encoding="utf-8")
        )
        private_comments[0]["parent_id"] = None
        public_comments[0]["parent_id"] = None
        private_comments[1]["parent_id"] = "t1_missing"
        public_comments[1]["parent_id"] = "t1_missing"
        self.fixture.rebind_base_comments(private_comments, public_comments)
        self.fixture.build(self.output)
        comments = _read_jsonl(self.output / "comments.jsonl")
        governed = {
            row["canonical_reddit_id"]: row
            for row in comments
            if row["record_authority"] == "governed_base"
        }
        self.assertEqual(governed["t1_c1"]["comment_state"], "linked")
        self.assertEqual(
            governed["t1_c1"]["immediate_parent_resolution"],
            "missing_immediate_parent_id",
        )
        self.assertEqual(governed["t1_c2"]["comment_state"], "linked")
        self.assertEqual(
            governed["t1_c2"]["immediate_parent_resolution"],
            "missing_parent_comment_entity",
        )
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        debt = manifest["governed_base_parent_lineage_debt"]
        self.assertEqual(debt["missing_immediate_parent_id"], 1)
        self.assertEqual(debt["missing_parent_comment_entity"], 1)
        self.assertTrue(debt["workbook_unresolved_parent_separate"])


if __name__ == "__main__":
    unittest.main()
