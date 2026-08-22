from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.source_batch import SourceBatchError, load_source_batch


SHA_A = "a" * 64
SHA_B = "b" * 64


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row) + b"\n")


def _member(root: Path, role: str, relative_path: str) -> dict[str, object]:
    path = root / relative_path
    rows = sum(1 for line in path.read_bytes().splitlines() if line)
    return {
        "bytes": path.stat().st_size,
        "relative_path": relative_path,
        "role": role,
        "rows": rows,
        "sha256": _sha256(path),
    }


def _build_batch(root: Path, *, producer_type: str = "daily_incremental") -> Path:
    raw_path = root / "raw/post-1.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(b'{"id":"post-1"}\n')

    _write_jsonl(
        root / "raw-index.jsonl",
        [
            {
                "bytes": raw_path.stat().st_size,
                "raw_object_id": "raw-post-1",
                "relative_path": "raw/post-1.json",
                "sha256": _sha256(raw_path),
                "terminal_disposition": "entity_observed",
            }
        ],
    )
    _write_jsonl(root / "posts.jsonl", [{"post_id": "t3_post1"}])
    _write_jsonl(root / "comments.jsonl", [{"comment_id": "t1_comment1", "post_id": "t3_post1"}])
    _write_jsonl(root / "post-occurrences.jsonl", [{"occurrence_id": "occ-post-1", "post_id": "t3_post1", "raw_object_id": "raw-post-1"}])
    _write_jsonl(root / "comment-occurrences.jsonl", [{"comment_id": "t1_comment1", "occurrence_id": "occ-comment-1", "raw_object_id": "raw-post-1"}])
    _write_jsonl(root / "checkpoints.jsonl", [])
    _write_jsonl(root / "issues.jsonl", [])

    roles = [
        ("checkpoints", "checkpoints.jsonl"),
        ("comment_occurrences", "comment-occurrences.jsonl"),
        ("comments", "comments.jsonl"),
        ("issues", "issues.jsonl"),
        ("post_occurrences", "post-occurrences.jsonl"),
        ("posts", "posts.jsonl"),
        ("raw_index", "raw-index.jsonl"),
    ]
    active_thread_policy: dict[str, object] | None = {
        "normal_max_age_days": 30,
        "normal_quiet_days": 7,
        "priority_max_age_days": 90,
        "priority_quiet_days": 30,
        "priority_reason_codes": [
            "admin_exposure",
            "brand_intervention",
            "content_compliance",
            "high_risk",
            "manual_case",
        ],
    }
    if producer_type == "historical_backfill":
        active_thread_policy = None
    value = {
        "active_thread_policy": active_thread_policy,
        "batch_id": "daily-20260717-0700" if producer_type != "historical_backfill" else "history-2025-01",
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": True,
            "remote_write": False,
        },
        "counts": {
            "comment_occurrences": 1,
            "comments": 1,
            "issues": 0,
            "post_occurrences": 1,
            "posts": 1,
            "raw_objects": 1,
            "unresolved_continuations": 0,
        },
        "members": [_member(root, role, path) for role, path in roles],
        "producer_type": producer_type,
        "profiles": {
            "coverage_profile_sha256": SHA_B,
            "coverage_profile_version": "momcozy-coverage-v1",
            "query_profile_sha256": SHA_A,
            "query_profile_version": "momcozy-query-v2",
        },
        "schema_version": "reddit_voc_source_batch_v2",
        "status": "success",
        "window": {
            "metric_end_utc": "2026-07-17T23:00:00Z",
            "metric_start_utc": "2026-07-16T23:00:00Z",
            "new_post_discovery_end_utc": "2026-07-17T23:00:00Z",
            "new_post_discovery_start_utc": "2026-07-16T21:00:00Z",
            "timezone": "Asia/Shanghai",
        },
    }
    manifest = root / "source-batch-manifest.json"
    manifest.write_bytes(canonical_json_bytes(value) + b"\n")
    return manifest


class SourceBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_daily_batch_binds_all_members_and_raw_objects(self) -> None:
        batch = load_source_batch(_build_batch(self.root), self.root, require_consumable=True)

        self.assertTrue(batch.is_consumable)
        self.assertEqual(batch.producer_type, "daily_incremental")
        self.assertEqual(batch.counts.posts, 1)
        self.assertEqual(batch.active_thread_policy.normal_max_age_days, 30)
        self.assertEqual(len(batch.manifest_sha256), 64)

    def test_historical_batch_uses_the_same_contract_without_active_thread_policy(self) -> None:
        batch = load_source_batch(
            _build_batch(self.root, producer_type="historical_backfill"),
            self.root,
            require_consumable=True,
        )

        self.assertEqual(batch.producer_type, "historical_backfill")
        self.assertIsNone(batch.active_thread_policy)

    def test_daily_metric_window_must_be_exactly_24_hours(self) -> None:
        manifest = _build_batch(self.root)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["window"]["metric_start_utc"] = "2026-07-16T22:00:00Z"
        manifest.write_bytes(canonical_json_bytes(value) + b"\n")

        with self.assertRaisesRegex(SourceBatchError, "daily metric window must be exactly 24 hours"):
            load_source_batch(manifest, self.root)

    def test_daily_batch_requires_the_governed_active_thread_policy(self) -> None:
        manifest = _build_batch(self.root)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["active_thread_policy"] = None
        manifest.write_bytes(canonical_json_bytes(value) + b"\n")

        with self.assertRaisesRegex(SourceBatchError, "active_thread_policy is required"):
            load_source_batch(manifest, self.root)

    def test_member_hash_drift_is_rejected(self) -> None:
        manifest = _build_batch(self.root)
        (self.root / "posts.jsonl").write_text('{"post_id":"changed"}\n', encoding="utf-8")

        with self.assertRaisesRegex(SourceBatchError, "member physical binding mismatch:posts"):
            load_source_batch(manifest, self.root)

    def test_raw_object_hash_drift_is_rejected(self) -> None:
        manifest = _build_batch(self.root)
        (self.root / "raw/post-1.json").write_text('{"id":"changed"}\n', encoding="utf-8")

        with self.assertRaisesRegex(SourceBatchError, "raw object physical binding mismatch:raw-post-1"):
            load_source_batch(manifest, self.root)

    def test_occurrence_must_reference_a_bound_raw_object(self) -> None:
        manifest = _build_batch(self.root)
        _write_jsonl(
            self.root / "post-occurrences.jsonl",
            [{"occurrence_id": "occ-post-1", "post_id": "t3_post1", "raw_object_id": "raw-missing"}],
        )
        value = json.loads(manifest.read_text(encoding="utf-8"))
        for member in value["members"]:
            if member["role"] == "post_occurrences":
                member.update(_member(self.root, "post_occurrences", "post-occurrences.jsonl"))
        manifest.write_bytes(canonical_json_bytes(value) + b"\n")

        with self.assertRaisesRegex(SourceBatchError, "post occurrence references unknown raw object"):
            load_source_batch(manifest, self.root)

    def test_every_canonical_entity_requires_an_occurrence(self) -> None:
        manifest = _build_batch(self.root)
        _write_jsonl(self.root / "post-occurrences.jsonl", [])
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["counts"]["post_occurrences"] = 0
        for member in value["members"]:
            if member["role"] == "post_occurrences":
                member.update(_member(self.root, "post_occurrences", "post-occurrences.jsonl"))
        manifest.write_bytes(canonical_json_bytes(value) + b"\n")

        with self.assertRaisesRegex(SourceBatchError, "post occurrence conservation failed"):
            load_source_batch(manifest, self.root, require_consumable=True)

    def test_canonical_entity_rows_must_have_unique_reddit_fullnames(self) -> None:
        manifest = _build_batch(self.root)
        _write_jsonl(
            self.root / "posts.jsonl",
            [{"post_id": "post1"}],
        )
        value = json.loads(manifest.read_text(encoding="utf-8"))
        for member in value["members"]:
            if member["role"] == "posts":
                member.update(_member(self.root, "posts", "posts.jsonl"))
        manifest.write_bytes(canonical_json_bytes(value) + b"\n")

        with self.assertRaisesRegex(SourceBatchError, "posts.post_id must be a t3 fullname"):
            load_source_batch(manifest, self.root)

    def test_symlink_member_is_rejected(self) -> None:
        manifest = _build_batch(self.root)
        posts = self.root / "posts.jsonl"
        target = self.root / "posts-target.jsonl"
        posts.rename(target)
        posts.symlink_to(target.name)

        with self.assertRaisesRegex(SourceBatchError, "member:posts must not be a symlink"):
            load_source_batch(manifest, self.root)

    def test_failed_batch_is_auditable_but_not_consumable(self) -> None:
        manifest = _build_batch(self.root)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["status"] = "failed"
        manifest.write_bytes(canonical_json_bytes(value) + b"\n")

        batch = load_source_batch(manifest, self.root)
        self.assertFalse(batch.is_consumable)
        with self.assertRaisesRegex(SourceBatchError, "source batch is not consumable:failed"):
            load_source_batch(manifest, self.root, require_consumable=True)


if __name__ == "__main__":
    unittest.main()
