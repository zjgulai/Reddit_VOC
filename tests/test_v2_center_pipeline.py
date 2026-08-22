from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reddit_voc.report_contracts import canonical_json_bytes
from reddit_voc.comment_refresh import build_comment_refresh_source_batch
from reddit_voc.v2_center import (
    V2CenterError,
    V2CenterStore,
    build_metric_release,
    register_candidate,
)


ROLES = (
    "checkpoints",
    "comment_occurrences",
    "comments",
    "issues",
    "post_occurrences",
    "posts",
    "raw_index",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row) + b"\n")


def _batch(
    root: Path,
    *,
    batch_id: str,
    start: str,
    end: str,
    post_created: str,
    comments: list[dict[str, object]],
    query_sha: str = "a" * 64,
    status: str = "success",
) -> Path:
    root.mkdir(parents=True)
    raw = root / "raw" / f"{batch_id}.json"
    raw.parent.mkdir()
    raw.write_bytes(canonical_json_bytes({"batch_id": batch_id}) + b"\n")
    post = {
        "created_at_utc": post_created,
        "num_comments_reported": len(comments),
        "post_id": "t3_post1",
        "score": 7,
        "selftext": "Momcozy pump body",
        "source_url": "https://reddit.com/r/test/comments/post1/x/",
        "subreddit": "test",
        "title": "Momcozy pump",
    }
    raw_id = f"raw-{batch_id}"
    documents = {
        "checkpoints": [],
        "comment_occurrences": [
            {
                "comment_id": row["comment_id"],
                "occurrence_id": f"occ-{batch_id}-{row['comment_id']}",
                "raw_object_id": raw_id,
            }
            for row in comments
        ],
        "comments": comments,
        "issues": [],
        "post_occurrences": [
            {
                "occurrence_id": f"occ-{batch_id}-post1",
                "post_id": "t3_post1",
                "raw_object_id": raw_id,
            }
        ],
        "posts": [post],
        "raw_index": [
            {
                "bytes": raw.stat().st_size,
                "raw_object_id": raw_id,
                "relative_path": f"raw/{raw.name}",
                "sha256": _sha(raw),
                "terminal_disposition": "entity_observed",
            }
        ],
    }
    members = []
    for role in ROLES:
        path = root / f"{role}.jsonl"
        _jsonl(path, documents[role])
        members.append(
            {
                "bytes": path.stat().st_size,
                "relative_path": path.name,
                "role": role,
                "rows": len(documents[role]),
                "sha256": _sha(path),
            }
        )
    manifest = {
        "active_thread_policy": {
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
        },
        "batch_id": batch_id,
        "boundaries": {
            "database_write": False,
            "deploy": False,
            "live_send": False,
            "production_unchanged": True,
            "provider_call": False,
            "remote_write": False,
        },
        "counts": {
            "comment_occurrences": len(comments),
            "comments": len(comments),
            "issues": 0,
            "post_occurrences": 1,
            "posts": 1,
            "raw_objects": 1,
            "unresolved_continuations": 0,
        },
        "members": members,
        "producer_type": "daily_incremental",
        "profiles": {
            "coverage_profile_sha256": "b" * 64,
            "coverage_profile_version": "coverage-v2",
            "query_profile_sha256": query_sha,
            "query_profile_version": "query-v2",
        },
        "schema_version": "reddit_voc_source_batch_v2",
        "status": status,
        "window": {
            "metric_end_utc": end,
            "metric_start_utc": start,
            "new_post_discovery_end_utc": end,
            "new_post_discovery_start_utc": start,
            "timezone": "Asia/Shanghai",
        },
    }
    path = root / "source-batch-manifest.json"
    path.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return path


def _comment(comment_id: str, created_at: str, body: str = "comment") -> dict[str, object]:
    return {
        "body": body,
        "comment_id": comment_id,
        "created_at_utc": created_at,
        "deleted_or_removed": False,
        "parent_id": "t3_post1",
        "post_id": "t3_post1",
        "score": 2,
    }


def _receipt(manifest: Path) -> Path:
    value = json.loads(manifest.read_text())
    receipt = {
        "batch_id": value["batch_id"],
        "consumable": True,
        "manifest_sha256": _sha(manifest),
        "schema_version": "reddit_voc_source_batch_validation_receipt_v1",
        "status": "passed",
    }
    path = manifest.parent / "validation-receipt.json"
    path.write_bytes(canonical_json_bytes(receipt) + b"\n")
    return path


class V2CenterPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = V2CenterStore(self.root / "center.sqlite3")
        self.first = _batch(
            self.root / "batch-1",
            batch_id="daily-20260716",
            start="2026-07-15T23:00:00Z",
            end="2026-07-16T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[_comment("t1_comment1", "2026-07-16T08:00:00Z")],
        )

    def test_consumption_is_single_writer_and_replay_is_no_change(self) -> None:
        first = self.store.consume_source_batch(self.first)
        second = self.store.consume_source_batch(self.first)

        self.assertEqual(first.write_status, "consumed")
        self.assertEqual(second.write_status, "no_change")
        self.assertEqual(self.store.count("source_batches"), 1)
        self.assertEqual(self.store.count("canonical_posts"), 1)
        self.assertEqual(self.store.count("canonical_comments"), 1)
        self.assertEqual(self.store.count("entity_occurrences"), 2)

    def test_late_daily_comment_is_added_once_and_versioned(self) -> None:
        self.store.consume_source_batch(self.first)
        second = _batch(
            self.root / "batch-2",
            batch_id="daily-20260717",
            start="2026-07-16T23:00:00Z",
            end="2026-07-17T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[
                _comment("t1_comment1", "2026-07-16T08:00:00Z"),
                _comment("t1_comment2", "2026-07-17T08:00:00Z", "new comment"),
            ],
        )

        result = self.store.consume_source_batch(second)

        self.assertEqual(result.new_comments, 1)
        self.assertEqual(self.store.count("canonical_comments"), 2)
        self.assertEqual(self.store.count("source_batches"), 2)
        self.assertGreaterEqual(self.store.count("engagement_snapshots"), 4)

    def test_active_thread_registry_applies_normal_and_priority_lifecycles(self) -> None:
        self.store.consume_source_batch(self.first)
        at_20_days = datetime(2026, 7, 30, tzinfo=timezone.utc)
        at_35_days = datetime(2026, 8, 14, tzinfo=timezone.utc)

        self.assertEqual([row.post_id for row in self.store.active_threads(at_20_days)], ["t3_post1"])
        self.assertEqual(self.store.active_threads(at_35_days), ())
        self.store.set_priority_reasons("t3_post1", ("manual_case",))
        self.assertEqual([row.post_id for row in self.store.active_threads(at_35_days)], ["t3_post1"])

    def test_stable_identity_conflict_fails_without_partial_consumption(self) -> None:
        self.store.consume_source_batch(self.first)
        conflict = _batch(
            self.root / "batch-conflict",
            batch_id="daily-20260717-conflict",
            start="2026-07-16T23:00:00Z",
            end="2026-07-17T23:00:00Z",
            post_created="2026-07-11T08:00:00Z",
            comments=[_comment("t1_comment1", "2026-07-16T08:00:00Z")],
        )

        with self.assertRaisesRegex(V2CenterError, "stable post identity conflict"):
            self.store.consume_source_batch(conflict)

        self.assertEqual(self.store.count("source_batches"), 1)

    def test_metric_release_and_candidate_bind_every_product_surface(self) -> None:
        self.store.consume_source_batch(
            self.first, validation_receipt_path=_receipt(self.first)
        )
        metric = build_metric_release(
            self.store,
            cutoff_utc=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
            output_path=self.root / "metric-release.json",
        )
        candidate = register_candidate(
            self.store,
            metric_release_path=metric.path,
            registry_root=self.root / "candidate-registry",
        )
        repeated = register_candidate(
            self.store,
            metric_release_path=metric.path,
            registry_root=self.root / "candidate-registry",
        )
        value = json.loads(metric.path.read_text())

        self.assertEqual(set(value["surface_bindings"]), {"cases", "insights", "overview", "personas", "reports"})
        self.assertEqual(
            {binding["metric_release_id"] for binding in value["surface_bindings"].values()},
            {value["metric_release_id"]},
        )
        self.assertEqual(set(value["periods"]), {"daily", "monthly", "weekly"})
        self.assertEqual(candidate.write_status, "created")
        self.assertEqual(repeated.write_status, "no_change")
        self.assertTrue(candidate.production_unchanged)

    def test_profile_comparison_recovers_after_drift_leaves_comparison_window(self) -> None:
        self.store.consume_source_batch(
            self.first, validation_receipt_path=_receipt(self.first)
        )
        drift = _batch(
            self.root / "batch-drift",
            batch_id="daily-20260717-drift",
            start="2026-07-16T23:00:00Z",
            end="2026-07-17T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[_comment("t1_comment1", "2026-07-16T08:00:00Z")],
            query_sha="c" * 64,
        )
        self.store.consume_source_batch(drift, validation_receipt_path=_receipt(drift))
        during = build_metric_release(
            self.store,
            cutoff_utc=datetime(2026, 7, 18, 23, tzinfo=timezone.utc),
            output_path=self.root / "during-drift" / "metric.json",
        )
        self.assertFalse(json.loads(during.path.read_text())["profile_comparable"])

        coverage_start = datetime(2026, 8, 17, 23, tzinfo=timezone.utc)
        source_batch_evidence = []
        for day in range(60):
            start = coverage_start + timedelta(days=day)
            end = start + timedelta(days=1)
            recovered = _batch(
                self.root / f"batch-recovered-{day:02d}",
                batch_id=f"daily-recovered-{day:02d}",
                start=start.isoformat().replace("+00:00", "Z"),
                end=end.isoformat().replace("+00:00", "Z"),
                post_created="2026-07-10T08:00:00Z",
                comments=[_comment("t1_comment1", "2026-07-16T08:00:00Z")],
                query_sha="c" * 64,
            )
            receipt = _receipt(recovered)
            self.store.consume_source_batch(
                recovered, validation_receipt_path=receipt
            )
            source_batch_evidence.append(
                {
                    "manifest_sha256": _sha(recovered),
                    "validation_receipt_sha256": _sha(receipt),
                }
            )
        before_closure = build_metric_release(
            self.store,
            cutoff_utc=datetime(2026, 10, 16, 23, tzinfo=timezone.utc),
            output_path=self.root / "before-closure" / "metric.json",
        )
        self.assertFalse(json.loads(before_closure.path.read_text())["profile_comparable"])
        closure = {
            "coverage_end_utc": "2026-10-16T23:00:00Z",
            "coverage_start_utc": "2026-08-17T23:00:00Z",
            "from_coverage_profile_sha256": "b" * 64,
            "from_query_profile_sha256": "a" * 64,
            "schema_version": "reddit_voc_profile_delta_closure_receipt_v2",
            "source_batch_evidence": source_batch_evidence,
            "status": "passed",
            "to_coverage_profile_sha256": "b" * 64,
            "to_query_profile_sha256": "c" * 64,
        }
        forged = {**closure, "source_batch_evidence": source_batch_evidence[:1]}
        forged_path = self.root / "forged-profile-delta-closure.json"
        forged_path.write_bytes(canonical_json_bytes(forged) + b"\n")
        with self.assertRaisesRegex(V2CenterError, "does not cover window"):
            self.store.register_profile_delta_closure(forged_path)
        closure_path = self.root / "profile-delta-closure.json"
        closure_path.write_bytes(canonical_json_bytes(closure) + b"\n")
        self.store.register_profile_delta_closure(closure_path)
        after = build_metric_release(
            self.store,
            cutoff_utc=datetime(2026, 10, 16, 23, tzinfo=timezone.utc),
            output_path=self.root / "after-closure" / "metric.json",
        )
        self.assertTrue(json.loads(after.path.read_text())["profile_comparable"])

    def test_success_batch_gap_keeps_comparison_closed(self) -> None:
        self.store.consume_source_batch(
            self.first, validation_receipt_path=_receipt(self.first)
        )
        metric = build_metric_release(
            self.store,
            cutoff_utc=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
            output_path=self.root / "gap-metric.json",
        )
        for period in json.loads(metric.path.read_text())["periods"].values():
            self.assertFalse(period["comparison_available"])
            self.assertIn("coverage_incomplete", period["comparison_blockers"])

    def test_metric_release_rejects_unvalidated_source_batch(self) -> None:
        self.store.consume_source_batch(self.first)
        with self.assertRaisesRegex(V2CenterError, "candidate-ineligible"):
            build_metric_release(
                self.store,
                cutoff_utc=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
                output_path=self.root / "invalid-metric.json",
            )

    def test_partial_coverage_never_opens_period_comparison(self) -> None:
        partial = _batch(
            self.root / "partial-batch",
            batch_id="historical-partial",
            start="2026-07-16T23:00:00Z",
            end="2026-07-17T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[_comment("t1_comment1", "2026-07-16T08:00:00Z")],
            status="partial",
        )
        self.store.consume_source_batch(
            partial, validation_receipt_path=_receipt(partial)
        )
        metric = build_metric_release(
            self.store,
            cutoff_utc=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
            output_path=self.root / "partial-metric.json",
        )
        value = json.loads(metric.path.read_text())
        self.assertFalse(value["profile_comparable"])
        for period in value["periods"].values():
            self.assertFalse(period["comparison_available"])
            self.assertIsNone(period["voc_change"])
            self.assertIn("coverage_incomplete", period["comparison_blockers"])

    def test_active_thread_refresh_captures_late_comment_and_fuses_it_once(self) -> None:
        class Client:
            calls = 0

            @classmethod
            def get_json(cls, path, params):
                cls.calls += 1
                return {
                    "data": {
                        "postInfoById": {
                            "commentForest": {
                                "trees": [
                                    {
                                        "node": {
                                            "__typename": "Comment",
                                            "content": {"markdown": "comment"},
                                            "createdAt": "2026-07-16T08:00:00+0000",
                                            "id": "t1_comment1",
                                            "score": 2,
                                        },
                                        "parentId": "t3_post1",
                                    },
                                    {
                                        "node": {
                                            "__typename": "Comment",
                                            "content": {"markdown": "new active-thread comment"},
                                            "createdAt": "2026-07-17T08:00:00+0000",
                                            "id": "t1_comment2",
                                            "score": 3,
                                        },
                                        "parentId": "t3_post1",
                                    },
                                ]
                            },
                            "id": "t3_post1",
                        }
                    }
                }

        self.store.consume_source_batch(self.first)
        project_root = Path(__file__).resolve().parents[1]
        refresh = build_comment_refresh_source_batch(
            self.store,
            client=Client(),
            run_id="refresh-20260717",
            window_start_utc=datetime(2026, 7, 16, 23, tzinfo=timezone.utc),
            window_end_utc=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
            query_profile_path=project_root / "config/source-batch/momcozy-query-v2.json",
            coverage_profile_path=project_root / "config/source-batch/momcozy-coverage-v2.json",
            output_root=self.root / "refresh-batches",
        )
        fused = self.store.consume_source_batch(refresh.manifest_path)
        replay = build_comment_refresh_source_batch(
            self.store,
            client=Client(),
            run_id="refresh-20260717",
            window_start_utc=datetime(2026, 7, 16, 23, tzinfo=timezone.utc),
            window_end_utc=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
            query_profile_path=project_root / "config/source-batch/momcozy-query-v2.json",
            coverage_profile_path=project_root / "config/source-batch/momcozy-coverage-v2.json",
            output_root=self.root / "refresh-batches",
        )

        self.assertEqual(refresh.new_comment_ids, ("t1_comment2",))
        self.assertEqual(refresh.observed_comments, 2)
        self.assertEqual(fused.new_comments, 1)
        self.assertEqual(self.store.count("canonical_comments"), 2)
        self.assertEqual(replay.write_status, "no_change")
        self.assertEqual(Client.calls, 1)

    def test_missing_parent_comment_is_recorded_as_relationship_debt(self) -> None:
        comment = _comment("t1_orphan", "2026-07-16T08:00:00Z")
        comment["parent_id"] = "t1_missing"
        manifest = _batch(
            self.root / "orphan-batch",
            batch_id="daily-orphan",
            start="2026-07-15T23:00:00Z",
            end="2026-07-16T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[comment],
        )
        self.store.consume_source_batch(manifest)

        self.assertEqual(self.store.count("relationship_debt"), 1)
        with self.store.connect() as connection:
            edge = connection.execute(
                "SELECT relationship_status,reason_code FROM comment_parent_edges WHERE comment_id='t1_orphan'"
            ).fetchone()
        self.assertEqual(tuple(edge), ("unresolved", "parent_comment_missing"))

    def test_explicit_top_level_comment_without_parent_id_links_to_root_post(self) -> None:
        comment = _comment("t1_toplevel", "2026-07-16T08:00:00Z")
        comment["parent_id"] = None
        comment["depth"] = 0
        manifest = _batch(
            self.root / "top-level-parent-omitted",
            batch_id="daily-top-level-parent-omitted",
            start="2026-07-15T23:00:00Z",
            end="2026-07-16T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[comment],
        )

        self.store.consume_source_batch(manifest)

        self.assertEqual(self.store.count("relationship_debt"), 0)
        with self.store.connect() as connection:
            edge = connection.execute(
                "SELECT parent_id,relationship_status,reason_code "
                "FROM comment_parent_edges WHERE comment_id='t1_toplevel'"
            ).fetchone()
            persisted = json.loads(
                connection.execute(
                    "SELECT payload_json FROM canonical_comments "
                    "WHERE comment_id='t1_toplevel'"
                ).fetchone()[0]
            )
        self.assertEqual(tuple(edge), ("t3_post1", "linked", None))
        self.assertEqual(persisted["parent_id"], "t3_post1")

    def test_nested_comment_without_parent_id_remains_relationship_debt(self) -> None:
        comment = _comment("t1_nestedunknown", "2026-07-16T08:00:00Z")
        comment["parent_id"] = None
        comment["depth"] = 1
        manifest = _batch(
            self.root / "nested-parent-omitted",
            batch_id="daily-nested-parent-omitted",
            start="2026-07-15T23:00:00Z",
            end="2026-07-16T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[comment],
        )

        self.store.consume_source_batch(manifest)

        self.assertEqual(self.store.count("relationship_debt"), 1)
        with self.store.connect() as connection:
            edge = connection.execute(
                "SELECT parent_id,relationship_status,reason_code "
                "FROM comment_parent_edges WHERE comment_id='t1_nestedunknown'"
            ).fetchone()
        self.assertEqual(tuple(edge), (None, "unresolved", "parent_id_missing"))

    def test_nested_comment_is_unresolved_when_root_post_is_missing(self) -> None:
        parent = _comment("t1_parent", "2026-07-16T08:00:00Z")
        child = _comment("t1_child", "2026-07-16T08:01:00Z")
        child["parent_id"] = "t1_parent"
        manifest = _batch(
            self.root / "nested-missing-root",
            batch_id="daily-nested-missing-root",
            start="2026-07-15T23:00:00Z",
            end="2026-07-16T23:00:00Z",
            post_created="2026-07-10T08:00:00Z",
            comments=[parent, child],
        )
        self.store.consume_source_batch(manifest)
        with self.store.connect() as connection:
            connection.execute("DELETE FROM canonical_posts WHERE post_id='t3_post1'")
            self.store._reconcile_comment_relationships(connection, "c" * 64)
            edge = connection.execute(
                "SELECT relationship_status,reason_code FROM comment_parent_edges WHERE comment_id='t1_child'"
            ).fetchone()

        self.assertEqual(tuple(edge), ("unresolved", "parent_post_missing"))
        self.assertEqual(self.store.count("relationship_debt"), 2)

    def test_refresh_limit_rotates_previously_attempted_threads(self) -> None:
        self.store.consume_source_batch(self.first)
        with self.store.connect() as connection:
            base = connection.execute(
                "SELECT * FROM canonical_posts WHERE post_id='t3_post1'"
            ).fetchone()
            for index in range(2, 5):
                post_id = f"t3_post{index}"
                payload = json.loads(base["payload_json"])
                payload["post_id"] = post_id
                connection.execute(
                    "INSERT INTO canonical_posts VALUES(?,?,?,?,?,?,?,?)",
                    (post_id, json.dumps(payload, sort_keys=True, separators=(",", ":")), base["content_sha256"], base["created_at_utc"], base["first_observed_at_utc"], base["last_observed_at_utc"], base["first_batch_sha256"], base["last_batch_sha256"]),
                )
                connection.execute(
                    "INSERT INTO active_threads(post_id,post_created_at_utc,last_activity_at_utc,priority_reason_codes_json,last_batch_sha256,last_refreshed_at_utc) VALUES(?,?,?,?,?,NULL)",
                    (post_id, base["created_at_utc"], base["created_at_utc"], "[]", base["last_batch_sha256"]),
                )
        as_of = datetime(2026, 7, 17, 23, tzinfo=timezone.utc)
        first_ids = [item.post_id for item in self.store.active_threads(as_of, limit=2)]
        self.store.mark_threads_refreshed(first_ids, as_of)
        second_ids = [item.post_id for item in self.store.active_threads(as_of, limit=2)]
        self.assertTrue(set(first_ids).isdisjoint(second_ids))


if __name__ == "__main__":
    unittest.main()
