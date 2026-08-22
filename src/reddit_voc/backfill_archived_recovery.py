from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from hashlib import sha256
import sqlite3

from .backfill_archive import PrivateRawArchive
from .backfill_storage import BackfillStore
from .time_window import CollectionWindow


class ArchivedRecoveryProviderCallError(RuntimeError):
    pass


class _ForbiddenProviderExecutor:
    def get_json(self, _path: str, _params: dict[str, object]) -> object:
        raise ArchivedRecoveryProviderCallError


def prepare_failed_schema_drift_retry(
    store: BackfillStore,
    *,
    run_id: str,
    post_ids: Sequence[str],
    now: datetime,
) -> dict[str, int]:
    """Reset a reviewed comments-schema-drift subset for archive replay.

    This is a local-only state transition. It reopens only the exact failed
    candidates and their already archived comment pages; it never reserves a
    Provider request or changes the cumulative Provider ledger.
    """
    if not isinstance(store, BackfillStore):
        raise ValueError("store must be a BackfillStore")
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if isinstance(post_ids, (str, bytes)):
        raise ValueError("post_ids must be a sequence of strings")
    normalized = tuple(sorted(set(post_ids)))
    if (
        not normalized
        or any(type(post_id) is not str or not post_id.strip() for post_id in normalized)
    ):
        raise ValueError("post_ids must contain non-empty strings")
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise ValueError("now must be timezone-aware")

    placeholders = ",".join("?" for _ in normalized)
    updated_at = now.isoformat()
    with sqlite3.connect(store.path, timeout=5.0) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        manifest = connection.execute(
            "SELECT status, provider_call, live_send FROM backfill_manifests "
            "WHERE run_id=?",
            (run_id,),
        ).fetchone()
        run = connection.execute(
            "SELECT status, provider_call, live_send FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if (
            manifest is None
            or run is None
            or manifest["status"] != "partial"
            or run["status"] != "partial"
            or manifest["provider_call"] != 1
            or run["provider_call"] != 1
            or manifest["live_send"] != 0
            or run["live_send"] != 0
        ):
            raise ValueError("failed_schema_drift_retry_state_invalid")

        candidates = connection.execute(
            "SELECT post_id, status, status_reason FROM backfill_candidates "
            f"WHERE run_id=? AND post_id IN ({placeholders})",
            (run_id, *normalized),
        ).fetchall()
        if (
            {str(row["post_id"]) for row in candidates} != set(normalized)
            or any(
                row["status"] != "failed"
                or row["status_reason"] != "comments_schema_drift"
                for row in candidates
            )
        ):
            raise ValueError("failed_schema_drift_retry_candidate_mismatch")
        all_failures = {
            str(row[0])
            for row in connection.execute(
                "SELECT post_id FROM backfill_candidates WHERE run_id=? "
                "AND status='failed' AND status_reason='comments_schema_drift'",
                (run_id,),
            ).fetchall()
        }
        if all_failures != set(normalized):
            raise ValueError("failed_schema_drift_retry_candidate_mismatch")

        member_rows = connection.execute(
            "SELECT batch_id, post_id FROM backfill_detail_batch_members "
            f"WHERE run_id=? AND post_id IN ({placeholders}) "
            "ORDER BY batch_id, ordinal",
            (run_id, *normalized),
        ).fetchall()
        if {str(row["post_id"]) for row in member_rows} != set(normalized):
            raise ValueError("failed_schema_drift_retry_batch_mismatch")
        batch_ids = tuple(sorted({str(row["batch_id"]) for row in member_rows}))
        if len(member_rows) != len(normalized):
            raise ValueError("failed_schema_drift_retry_batch_mismatch")

        batch_placeholders = ",".join("?" for _ in batch_ids)
        batches = connection.execute(
            "SELECT batch_id, status, artifact_id, stop_reason "
            "FROM backfill_detail_batches "
            f"WHERE run_id=? AND batch_id IN ({batch_placeholders}) "
            "ORDER BY batch_number",
            (run_id, *batch_ids),
        ).fetchall()
        if len(batches) != len(batch_ids):
            raise ValueError("failed_schema_drift_retry_batch_mismatch")
        for batch in batches:
            if (
                batch["status"] not in {"complete", "failed"}
                or batch["artifact_id"] is None
                or (
                    batch["status"] == "failed"
                    and batch["stop_reason"] != "comments_schema_drift"
                )
                or (
                    batch["status"] == "complete"
                    and batch["stop_reason"] is not None
                )
            ):
                raise ValueError("failed_schema_drift_retry_batch_mismatch")
            artifact = connection.execute(
                "SELECT artifact_kind, lane_type, parser_kind, source_method "
                "FROM backfill_raw_artifacts WHERE run_id=? AND artifact_id=?",
                (run_id, batch["artifact_id"]),
            ).fetchone()
            if artifact is None or tuple(artifact) != (
                "detail",
                "detail_batch",
                "tikhub_detail",
                "tikhub_detail",
            ):
                raise ValueError("failed_schema_drift_retry_batch_mismatch")

        for post_id in normalized:
            membership = connection.execute(
                "SELECT status FROM backfill_candidates AS candidate "
                "JOIN backfill_detail_batch_members AS member "
                "ON member.run_id=candidate.run_id AND member.post_id=candidate.post_id "
                "WHERE member.run_id=? AND member.post_id=?",
                (run_id, post_id),
            ).fetchall()
            if not membership or any(row["status"] == "pending" for row in membership):
                raise ValueError("failed_schema_drift_retry_batch_mismatch")
            artifact_rows = connection.execute(
                "SELECT page_number, request_cursor, response_cursor "
                "FROM backfill_raw_artifacts WHERE run_id=? "
                "AND lane_type='comments' AND lane_key_hash=?",
                (run_id, sha256(post_id.encode()).hexdigest()),
            ).fetchall()
            if len(artifact_rows) != 1 or tuple(artifact_rows[0]) != (1, None, None):
                raise ValueError("failed_schema_drift_retry_comment_mismatch")
            checkpoint = connection.execute(
                "SELECT cursor, previous_cursor, page_number, discovered_count, "
                "unique_count, last_success_utc, last_error, status, stop_reason "
                "FROM backfill_checkpoints WHERE run_id=? AND lane_type='comments' "
                "AND lane_key=?",
                (run_id, post_id),
            ).fetchone()
            if checkpoint is None or tuple(checkpoint) != (
                None,
                None,
                0,
                0,
                0,
                None,
                "TikHubSchemaDrift",
                "partial",
                "comments_schema_drift",
            ):
                raise ValueError("failed_schema_drift_retry_comment_mismatch")
            if connection.execute(
                "SELECT 1 FROM reddit_threads WHERE run_id=? AND post_id=? "
                "UNION ALL SELECT 1 FROM reddit_comments WHERE run_id=? AND post_id=? "
                "LIMIT 1",
                (run_id, post_id, run_id, post_id),
            ).fetchone() is not None:
                raise ValueError("failed_schema_drift_retry_structured_state_present")

        candidate_cursor = connection.execute(
            "UPDATE backfill_candidates SET status='pending', status_reason=NULL, "
            f"updated_at_utc=? WHERE run_id=? AND post_id IN ({placeholders}) "
            "AND status='failed' AND status_reason='comments_schema_drift'",
            (updated_at, run_id, *normalized),
        )
        checkpoint_cursor = connection.execute(
            "UPDATE backfill_checkpoints SET status='prepared', stop_reason=NULL, "
            "last_error=NULL WHERE run_id=? AND lane_type='comments' "
            f"AND lane_key IN ({placeholders}) AND status='partial' "
            "AND stop_reason='comments_schema_drift'",
            (run_id, *normalized),
        )
        for batch in batches:
            cursor = connection.execute(
                "UPDATE backfill_detail_batches SET status='raw_persisted', "
                "stop_reason=NULL, updated_at_utc=? WHERE run_id=? AND batch_id=?",
                (updated_at, run_id, batch["batch_id"]),
            )
            if cursor.rowcount != 1:
                raise ValueError("failed_schema_drift_retry_batch_mismatch")
        if (
            candidate_cursor.rowcount != len(normalized)
            or checkpoint_cursor.rowcount != len(normalized)
            or connection.execute("PRAGMA foreign_key_check").fetchone() is not None
            or [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
            != ["ok"]
        ):
            raise ValueError("failed_schema_drift_retry_write_invalid")
        connection.commit()
        return {
            "reset_candidate_count": len(normalized),
            "reset_batch_count": len(batches),
            "reset_comment_checkpoint_count": len(normalized),
            "raw_persisted_batch_count": len(batches),
            "prepared_batch_count": 0,
        }


def recover_archived_candidates(
    store: BackfillStore,
    archive: PrivateRawArchive,
    *,
    run_id: str,
    window: CollectionWindow,
    now: Callable[[], datetime],
) -> tuple[str, ...]:
    """Use the hydrator's archive-only path without exposing Provider I/O."""
    from .backfill_provider import TikHubDetailHydrator

    return TikHubDetailHydrator(
        _ForbiddenProviderExecutor(),
        store,
        archive,
        run_id,
        now=now,
    ).recover_archived(window=window)
