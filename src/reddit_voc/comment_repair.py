"""Read-only scheduling for terminal comment-coverage debt.

The historical collector must not treat ``unresolved_more`` or
``post_only_coverage`` as a reason to abandon a candidate.  This module only
builds a deterministic repair queue; it does not mutate SQLite or call a
Provider.  A later, separately authorised runner consumes the queue.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


REPAIR_REASONS = ("unresolved_more", "post_only_coverage")
_REASON_PRIORITY = {reason: index for index, reason in enumerate(REPAIR_REASONS)}


def parse_comment_repair_payload(payload: Any, *, expected_post_id: str) -> dict[str, Any]:
    """Validate and summarize one TikHub comment page without writing state."""
    expected = str(expected_post_id).removeprefix("t3_")
    post_info = _find_post_info(payload)
    if not isinstance(post_info, dict):
        raise ValueError("comment_repair_payload_post_missing")
    actual = str(post_info.get("id") or "").removeprefix("t3_")
    if not actual or actual != expected:
        raise ValueError("comment_repair_payload_post_mismatch")
    forest = post_info.get("commentForest")
    if not isinstance(forest, dict) or not isinstance(forest.get("trees"), list):
        raise ValueError("comment_repair_payload_forest_invalid")

    comments: list[dict[str, Any]] = []
    cursors: list[str] = []
    more_node_count = 0

    def visit(tree: Any, fallback_depth: int = 0) -> None:
        nonlocal more_node_count
        if not isinstance(tree, dict):
            return
        more = tree.get("more")
        if more:
            more_node_count += 1
            if isinstance(more, dict):
                cursor = more.get("cursor")
                if isinstance(cursor, str) and cursor and cursor not in cursors:
                    cursors.append(cursor)
        node = tree.get("node") if isinstance(tree.get("node"), dict) else tree
        if isinstance(node, dict) and (node.get("__typename") == "MoreComments" or node.get("type") == "more"):
            more_node_count += 1
            cursor = node.get("cursor")
            if isinstance(cursor, str) and cursor and cursor not in cursors:
                cursors.append(cursor)
        if isinstance(node, dict) and (node.get("__typename") == "Comment" or (node.get("id") is not None and node.get("content") is not None)):
            comment_id = str(node.get("id") or "")
            if comment_id and not comment_id.startswith("t1_"):
                comment_id = "t1_" + comment_id
            if comment_id:
                content = node.get("content")
                if isinstance(content, dict):
                    body = str(content.get("markdown") or content.get("text") or content.get("plainText") or "")
                else:
                    body = "" if content is None else str(content)
                depth = tree.get("depth")
                comments.append({
                    "comment_id": comment_id,
                    "parent_id": tree.get("parentId") or node.get("parentId"),
                    "depth": int(depth) if isinstance(depth, (int, float)) else fallback_depth,
                    "body": body,
                    "created_at": node.get("createdAt") or node.get("created_at") or node.get("created"),
                    "score": node.get("score"),
                })
        for child_key in ("children", "replies", "trees"):
            child_value = tree.get(child_key)
            if child_value is None and isinstance(node, dict):
                child_value = node.get(child_key)
            child_trees = child_value.get("trees") if isinstance(child_value, dict) else child_value
            if isinstance(child_trees, list):
                for child in child_trees:
                    visit(child, fallback_depth + 1)

    for tree in forest["trees"]:
        visit(tree)
    page_info = forest.get("pageInfo")
    if not isinstance(page_info, dict):
        page_info = {}
    return {
        "post_id": actual,
        "reported_comment_count": post_info.get("commentCount"),
        "has_next_page": page_info.get("hasNextPage"),
        "parsed_comment_count": len(comments),
        "more_node_count": more_node_count,
        "more_cursors": tuple(cursors),
        "comments": tuple(comments),
    }


def _find_post_info(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        direct = value.get("postInfoById")
        if isinstance(direct, dict):
            return direct
        for child in value.values():
            found = _find_post_info(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_post_info(child)
            if found is not None:
                return found
    return None


@dataclass(frozen=True)
class CommentRepairCandidate:
    post_id: str
    status_reason: str
    reported_comment_count: int
    parsed_comment_count: int
    more_node_count: int
    coverage_grade: str
    checkpoint_status: str
    checkpoint_stop_reason: str | None
    checkpoint_page_number: int
    first_page_artifact_id: str | None
    first_page_payload_sha256: str | None
    first_page_request_required: bool = True


@dataclass(frozen=True)
class CommentRepairPlan:
    schema_version: str
    run_id: str
    provider_request_ceiling: int
    candidate_count: int
    selected_candidate_count: int
    minimum_first_page_requests: int
    cursor_source: str
    candidates: tuple[CommentRepairCandidate, ...]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["candidates"] = [asdict(item) for item in self.candidates]
        return value

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.as_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def build_comment_repair_plan(
    database: Path | str,
    *,
    run_id: str,
    provider_request_ceiling: int,
) -> CommentRepairPlan:
    """Build a deterministic queue from terminal comment-debt candidates.

    The query is read-only and intentionally excludes cursor values.  The
    browser archive does not prove a TikHub ``more.cursor``; the first-page
    Provider request is therefore an explicit prerequisite for every repair
    candidate.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if type(provider_request_ceiling) is not int or provider_request_ceiling < 1:
        raise ValueError("provider_request_ceiling must be a positive integer")
    path = Path(database)
    with sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT candidate.post_id, candidate.status_reason, "
            "COALESCE(thread.num_comments_reported, 0) AS reported_count, "
            "COALESCE(thread.parsed_comment_count, 0) AS parsed_count, "
            "COALESCE(thread.more_node_count, 0) AS more_count, "
            "COALESCE(thread.coverage_grade, 'post_only') AS coverage_grade, "
            "COALESCE(checkpoint.status, 'missing') AS checkpoint_status, "
            "checkpoint.stop_reason AS checkpoint_stop_reason, "
            "COALESCE(checkpoint.page_number, 0) AS checkpoint_page_number "
            "FROM backfill_candidates AS candidate "
            "LEFT JOIN reddit_threads AS thread "
            "ON thread.run_id = candidate.run_id AND thread.post_id = candidate.post_id "
            "LEFT JOIN backfill_checkpoints AS checkpoint "
            "ON checkpoint.run_id = candidate.run_id "
            "AND checkpoint.lane_type = 'comments' "
            "AND checkpoint.lane_key = candidate.post_id "
            "WHERE candidate.run_id = ? AND candidate.status = 'hydrated' "
            "AND candidate.status_reason IN ('unresolved_more', 'post_only_coverage')",
            (run_id,),
        ).fetchall()
        normalized_rows: list[dict[str, object]] = []
        artifact_table_present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='backfill_raw_artifacts'"
        ).fetchone() is not None
        for row in rows:
            item = dict(row)
            artifact = None
            if artifact_table_present:
                artifact = connection.execute(
                    "SELECT artifact_id, payload_sha256 FROM backfill_raw_artifacts "
                    "WHERE run_id = ? AND lane_type = 'comments' "
                    "AND lane_key_hash = ? AND page_number = 1 "
                    "ORDER BY artifact_id LIMIT 1",
                    (run_id, sha256(str(item["post_id"]).encode()).hexdigest()),
                ).fetchone()
            item["first_page_artifact_id"] = (
                None if artifact is None else str(artifact["artifact_id"])
            )
            item["first_page_payload_sha256"] = (
                None if artifact is None else str(artifact["payload_sha256"])
            )
            normalized_rows.append(item)

    return build_comment_repair_plan_from_rows(
        normalized_rows,
        run_id=run_id,
        provider_request_ceiling=provider_request_ceiling,
    )


def build_comment_repair_plan_from_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    run_id: str,
    provider_request_ceiling: int,
) -> CommentRepairPlan:
    """Build the same plan from an audited remote read-only row snapshot."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if type(provider_request_ceiling) is not int or provider_request_ceiling < 1:
        raise ValueError("provider_request_ceiling must be a positive integer")
    ordered = sorted(
        rows,
        key=lambda row: (
            _REASON_PRIORITY[str(row["status_reason"])],
            -int(row["more_count"]),
            -max(0, int(row["reported_count"]) - int(row["parsed_count"])),
            str(row["post_id"]),
        ),
    )
    candidates = tuple(
        CommentRepairCandidate(
            post_id=str(row["post_id"]),
            status_reason=str(row["status_reason"]),
            reported_comment_count=int(row["reported_count"]),
            parsed_comment_count=int(row["parsed_count"]),
            more_node_count=int(row["more_count"]),
            coverage_grade=str(row["coverage_grade"]),
            checkpoint_status=str(row["checkpoint_status"]),
            checkpoint_stop_reason=(
                None
                if row["checkpoint_stop_reason"] is None
                else str(row["checkpoint_stop_reason"])
            ),
            checkpoint_page_number=int(row["checkpoint_page_number"]),
            first_page_artifact_id=(
                None
                if row.get("first_page_artifact_id") is None
                else str(row["first_page_artifact_id"])
            ),
            first_page_payload_sha256=(
                None
                if row.get("first_page_payload_sha256") is None
                else str(row["first_page_payload_sha256"])
            ),
        )
        for row in ordered
    )
    selected_count = min(provider_request_ceiling, len(candidates))
    return CommentRepairPlan(
        schema_version="reddit_voc_comment_repair_plan_v1",
        run_id=run_id,
        provider_request_ceiling=provider_request_ceiling,
        candidate_count=len(candidates),
        selected_candidate_count=selected_count,
        minimum_first_page_requests=len(candidates),
        cursor_source="fresh_tikhub_comments_page_required",
        candidates=candidates,
    )


def write_comment_repair_plan(plan: CommentRepairPlan, destination: Path | str) -> str:
    """Write a canonical plan with a trailing newline and return its SHA."""
    if not isinstance(plan, CommentRepairPlan):
        raise TypeError("plan must be a CommentRepairPlan")
    path = Path(destination)
    payload = plan.canonical_bytes() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256(payload).hexdigest()
