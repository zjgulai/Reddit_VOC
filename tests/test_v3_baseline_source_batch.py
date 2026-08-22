from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import load_source_batch
from reddit_voc.v2_center import (
    V2CenterError,
    V2CenterStore,
    build_metric_release,
    register_candidate,
)
from reddit_voc.v3_baseline_source_batch import (
    V3BaselineSourceBatchError,
    build_v3_baseline_bridge_receipt,
    build_v3_baseline_source_batch,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row) + b"\n")


class V3BaselineSourceBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.canonical = self.root / "canonical"
        self.canonical.mkdir()
        post = {
            "canonical_reddit_id": "t3_post1",
            "entity_type": "post",
            "record": {
                "created_at_utc": "2026-06-01T08:00:00Z",
                "post_id": "t3_post1",
                "score": 5,
                "subreddit": "test",
                "title": "Momcozy test",
            },
        }
        linked = {
            "canonical_reddit_id": "t1_linked",
            "comment_state": "linked",
            "entity_type": "comment",
            "post_id": "post1",
            "record": {
                "body": "linked without immediate parent",
                "created_at_utc": "2026-06-02T08:00:00Z",
                "post_id": "post1",
            },
        }
        unresolved = {
            "canonical_reddit_id": "t1_unresolved",
            "comment_state": "unresolved_parent",
            "entity_type": "comment",
            "post_id": "missing1",
            "record": {
                "body": "unresolved",
                "created_at_utc": "2026-06-03T08:00:00Z",
                "post_id": "missing1",
            },
        }
        quarantined = {
            "canonical_reddit_id": "t1_quarantine",
            "entity_type": "comment",
            "record": {"missing_post_id": "missing2"},
        }
        documents = {
            "comments.jsonl": [linked, unresolved],
            "conflict-ledger.jsonl": [],
            "posts.jsonl": [post],
            "provenance-ledger.jsonl": [],
            "quarantine.jsonl": [quarantined],
            "unresolved-parent-ledger.jsonl": [unresolved],
        }
        files = {}
        for name, rows in documents.items():
            path = self.canonical / name
            _jsonl(path, rows)
            files[name] = {
                "bytes": path.stat().st_size,
                "rows": len(rows),
                "sha256": _sha(path),
            }
        counts = {
            "comments_jsonl": 2,
            "linked_comments": 1,
            "posts": 1,
            "quarantined_comments": 1,
            "stored_comments": 3,
            "unresolved_parent_comments": 1,
        }
        manifest = {
            "canonical_counts": counts,
            "dataset_id": "v3-test-dataset",
            "files": files,
            "inputs": {"source_manifest_sha256": "a" * 64},
            "schema_version": "reddit_voc_canonical_snapshot_manifest_v1",
        }
        self.canonical_manifest = self.canonical / "manifest.json"
        _json(self.canonical_manifest, manifest)
        self.canonical_receipt = self.root / "canonical-validation.json"
        _json(
            self.canonical_receipt,
            {
                "bundle_manifest_sha256": _sha(self.canonical_manifest),
                "canonical_counts": counts,
                "schema_version": "reddit_voc_canonical_snapshot_validation_receipt_v1",
                "status": "passed",
            },
        )

    def _build(self):
        return build_v3_baseline_source_batch(
            canonical_root=self.canonical,
            validation_receipt_path=self.canonical_receipt,
            output_root=self.root / "batches",
            batch_id="v3-baseline-test",
        )

    def _source_receipt(self, manifest: Path) -> Path:
        batch = load_source_batch(manifest, require_consumable=True)
        path = self.root / "source-validation.json"
        _json(
            path,
            {
                "batch_id": batch.batch_id,
                "consumable": True,
                "manifest_sha256": batch.manifest_sha256,
                "schema_version": "reddit_voc_source_batch_validation_receipt_v1",
                "status": "passed",
            },
        )
        return path

    def _set_canonical_contract_version(self, version: int) -> None:
        manifest = json.loads(self.canonical_manifest.read_text())
        manifest["schema_version"] = (
            f"reddit_voc_canonical_snapshot_manifest_v{version}"
        )
        _json(self.canonical_manifest, manifest)
        receipt = json.loads(self.canonical_receipt.read_text())
        receipt["schema_version"] = (
            f"reddit_voc_canonical_snapshot_validation_receipt_v{version}"
        )
        receipt["bundle_manifest_sha256"] = _sha(self.canonical_manifest)
        _json(self.canonical_receipt, receipt)

    def test_full_bridge_conserves_structural_states_and_enables_baseline(self) -> None:
        result = self._build()
        batch = load_source_batch(result.manifest_path, require_consumable=True)
        self.assertEqual((batch.counts.posts, batch.counts.comments), (1, 3))
        comments = [
            json.loads(line)
            for line in (result.batch_root / "comments.jsonl").read_bytes().splitlines()
        ]
        linked = next(row for row in comments if row["comment_id"] == "t1_linked")
        self.assertEqual(linked["parent_id"], "t3_post1")
        self.assertIsNone(
            linked["source_record"]["record"].get("parent_id")
        )

        source_receipt = self._source_receipt(result.manifest_path)
        bridge_value = build_v3_baseline_bridge_receipt(
            canonical_root=self.canonical,
            canonical_validation_receipt_path=self.canonical_receipt,
            source_batch_manifest_path=result.manifest_path,
            source_batch_validation_receipt_path=source_receipt,
        )
        bridge_path = self.root / "bridge.json"
        _json(bridge_path, bridge_value)
        store = V2CenterStore(self.root / "center.sqlite3")
        store.consume_source_batch(
            result.manifest_path, validation_receipt_path=source_receipt
        )
        self.assertEqual(store.register_v3_baseline_bridge_receipt(bridge_path), "registered")
        self.assertEqual(store.register_v3_baseline_bridge_receipt(bridge_path), "no_change")
        self.assertEqual(store.count("canonical_posts"), 1)
        self.assertEqual(store.count("canonical_comments"), 3)
        self.assertEqual(store.count("relationship_debt"), 1)
        self.assertEqual(store.count("comment_quarantine"), 1)

        metric = build_metric_release(
            store,
            cutoff_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
            output_path=self.root / "metric.json",
        )
        candidate = register_candidate(
            store, metric_release_path=metric.path, registry_root=self.root / "registry"
        )
        value = json.loads(candidate.path.read_text())
        self.assertTrue(value["baseline_bridge_complete"])
        self.assertNotIn("full_v3_baseline_bridge_incomplete", value["blockers"])
        self.assertIn("full_v3_page_e2e_and_shadow_incomplete", value["blockers"])

    def test_replay_is_no_change(self) -> None:
        first = self._build()
        second = self._build()
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        self.assertEqual(second.write_status, "no_change")

    def test_v2_canonical_contract_is_supported_for_daily_chaining(self) -> None:
        self._set_canonical_contract_version(2)

        result = self._build()

        batch = load_source_batch(result.manifest_path, require_consumable=True)
        self.assertEqual((batch.counts.posts, batch.counts.comments), (1, 3))

    def test_mixed_canonical_contract_versions_fail_closed(self) -> None:
        manifest = json.loads(self.canonical_manifest.read_text())
        manifest["schema_version"] = "reddit_voc_canonical_snapshot_manifest_v2"
        _json(self.canonical_manifest, manifest)
        receipt = json.loads(self.canonical_receipt.read_text())
        receipt["bundle_manifest_sha256"] = _sha(self.canonical_manifest)
        _json(self.canonical_receipt, receipt)

        with self.assertRaisesRegex(
            V3BaselineSourceBatchError,
            "validation receipt is not passed",
        ):
            self._build()

    def test_tampered_canonical_member_fails_closed(self) -> None:
        with (self.canonical / "comments.jsonl").open("ab") as handle:
            handle.write(b"{}\n")
        with self.assertRaisesRegex(
            V3BaselineSourceBatchError, "canonical file binding mismatch"
        ):
            self._build()

    def test_bridge_registration_requires_exact_center_conservation(self) -> None:
        result = self._build()
        source_receipt = self._source_receipt(result.manifest_path)
        value = build_v3_baseline_bridge_receipt(
            canonical_root=self.canonical,
            canonical_validation_receipt_path=self.canonical_receipt,
            source_batch_manifest_path=result.manifest_path,
            source_batch_validation_receipt_path=source_receipt,
        )
        value["counts"]["stored_comments"] = 4
        bridge_path = self.root / "bad-bridge.json"
        _json(bridge_path, value)
        store = V2CenterStore(self.root / "center.sqlite3")
        store.consume_source_batch(
            result.manifest_path, validation_receipt_path=source_receipt
        )
        with self.assertRaises(V2CenterError):
            store.register_v3_baseline_bridge_receipt(bridge_path)


if __name__ == "__main__":
    unittest.main()
