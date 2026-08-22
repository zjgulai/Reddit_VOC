#!/usr/bin/env python3
"""Build a deterministic, private snapshot from archived Reddit V2 reports.

The builder is deliberately offline.  It validates immutable identity and raw
report contracts, reuses the reviewed TikHub parsers, and never opens SQLite or
calls a Provider.  Raw payloads and raw author names are not copied to the
snapshot; payload hashes preserve the evidence lineage.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Sequence

from reddit_voc.analyzer import analyze_text
from reddit_voc.comment_repair import parse_comment_repair_payload
from reddit_voc.tikhub import (
    FETCH_COMMENT_REPLIES,
    FETCH_DYNAMIC_SEARCH,
    FETCH_POST_COMMENTS,
    _STRICT_DISCOVERY_CONTENT_TYPENAMES,
    _discovery_post_from_row,
    _parse_strict_tikhub_comment_payload,
    _strict_dynamic_search_post_records,
)


SCHEMA_VERSION = "reddit_voc_v2_raw_snapshot_v1"
SEARCH_REPORT_NAMES = frozenset(
    {"search-lane-probe.json", "search-continuation-probe.json"}
)
COMMENT_REPORT_NAMES = frozenset(
    {"comment-repair-probe.json", "comment-reply-probe.json"}
)
SEARCH_SCHEMAS = frozenset(
    {
        "reddit_voc_search_lane_probe_v1",
        "reddit_voc_search_continuation_probe_v1",
    }
)
COMMENT_SCHEMAS = {
    "comment-repair-probe.json": "reddit_voc_comment_repair_probe_v1",
    "comment-reply-probe.json": "reddit_voc_comment_reply_probe_v1",
}
ENDPOINTS = {
    "search": FETCH_DYNAMIC_SEARCH,
    "first_page": FETCH_POST_COMMENTS,
    "reply": FETCH_COMMENT_REPLIES,
}
POST_ID_RE = re.compile(r"^[a-z0-9]{5,10}$")
COMMENT_ID_RE = re.compile(r"^t1_[a-z0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PERMALINK_RE = re.compile(r"/comments/([a-z0-9]{5,10})(?:/|$)", re.I)


class SnapshotContractError(ValueError):
    """An immutable input contract is invalid, so no snapshot may be trusted."""


class ReportContractError(ValueError):
    """One archived report cannot be admitted as raw evidence."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def identity_hash(values: Iterable[str]) -> str:
    ordered = sorted(set(values))
    payload = ("\n".join(ordered) + ("\n" if ordered else "")).encode("utf-8")
    return sha256(payload).hexdigest()


def _normalize_post_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized.startswith("t3_"):
        normalized = normalized[3:]
    return normalized or None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().replace("Z", "+00:00")
    candidate = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", candidate)
    candidate = re.sub(r"(\.\d{6})\d+(?=[+-]\d\d:\d\d$)", r"\1", candidate)
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _cursor_sha256(cursor: str) -> str:
    return sha256(cursor.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_target_set(
    inventory_path: Path,
    *,
    set_id: str,
    expected_count: int,
    expected_sha256: str,
) -> tuple[tuple[str, ...], dict[str, str] | None, str]:
    if type(expected_count) is not int or expected_count < 1:
        raise SnapshotContractError("expected_target_count_invalid")
    if not SHA256_RE.fullmatch(expected_sha256):
        raise SnapshotContractError("expected_target_sha256_invalid")
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotContractError("identity_inventory_unreadable") from exc
    if not isinstance(inventory, dict):
        raise SnapshotContractError("identity_inventory_invalid")
    sets = inventory.get("identity_sets")
    if not isinstance(sets, list):
        raise SnapshotContractError("identity_sets_missing")
    matches = [row for row in sets if isinstance(row, dict) and row.get("set_id") == set_id]
    if len(matches) != 1:
        raise SnapshotContractError("identity_set_not_unique")
    selected = matches[0]
    raw_ids = selected.get("post_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise SnapshotContractError("identity_set_post_ids_invalid")
    normalized: list[str] = []
    for value in raw_ids:
        post_id = _normalize_post_id(value)
        if post_id is None or POST_ID_RE.fullmatch(post_id) is None:
            raise SnapshotContractError("identity_set_post_id_invalid")
        normalized.append(post_id)
    if len(normalized) != len(set(normalized)):
        raise SnapshotContractError("identity_set_post_ids_duplicate")
    ordered = tuple(sorted(normalized))
    computed_sha256 = identity_hash(ordered)
    declared_hashes = [
        selected[field]
        for field in ("sha256", "lf_sha256")
        if field in selected
    ]
    if len(declared_hashes) != 1:
        raise SnapshotContractError("identity_set_sha256_field_invalid")
    if (
        selected.get("count") != len(ordered)
        or declared_hashes[0] != computed_sha256
        or len(ordered) != expected_count
        or computed_sha256 != expected_sha256
    ):
        raise SnapshotContractError("identity_set_count_or_sha256_mismatch")

    target_window = inventory.get("target_window_utc")
    normalized_window: dict[str, str] | None = None
    if target_window is not None:
        if not isinstance(target_window, dict):
            raise SnapshotContractError("identity_target_window_invalid")
        start = _parse_datetime(target_window.get("start"))
        end = _parse_datetime(target_window.get("end"))
        if start is None or end is None or start > end:
            raise SnapshotContractError("identity_target_window_invalid")
        normalized_window = {"start": _iso_utc(start), "end": _iso_utc(end)}
    return ordered, normalized_window, _file_sha256(inventory_path)


def _report_paths(roots: Sequence[Path], names: frozenset[str]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise SnapshotContractError("report_root_unreadable") from exc
        if not resolved.is_dir():
            raise SnapshotContractError("report_root_not_directory")
        paths.extend(
            path
            for path in resolved.rglob("*.json")
            if path.is_file() and path.name in names
        )
    return sorted(set(paths), key=lambda path: path.as_posix())


def _load_report(path: Path) -> tuple[dict[str, Any], str]:
    report_sha256 = _file_sha256(path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportContractError("report_json_invalid") from exc
    if not isinstance(report, dict):
        raise ReportContractError("report_root_invalid")
    return report, report_sha256


def _validated_report_payload(
    report: dict[str, Any],
    *,
    schemas: frozenset[str],
    endpoint: str,
) -> tuple[Any, str]:
    if report.get("schema_version") not in schemas:
        raise ReportContractError("report_schema_invalid")
    if report.get("endpoint") != endpoint:
        raise ReportContractError("report_endpoint_invalid")
    if type(report.get("http_status")) is not int or report["http_status"] != 200:
        raise ReportContractError("report_http_status_invalid")
    if report.get("response_validation") != "passed":
        raise ReportContractError("report_response_validation_failed")
    if report.get("provider_attempt_made") is not True:
        raise ReportContractError("report_provider_attempt_missing")
    for field in ("live_send", "production_merge", "git_push", "dingtalk"):
        if report.get(field) is not False:
            raise ReportContractError(f"report_{field}_boundary_invalid")
    payload = report.get("payload")
    if not isinstance(payload, (dict, list)):
        raise ReportContractError("report_payload_missing")
    payload_sha256 = report.get("payload_sha256")
    if not isinstance(payload_sha256, str) or SHA256_RE.fullmatch(payload_sha256) is None:
        raise ReportContractError("report_payload_sha256_invalid")
    if sha256(canonical_bytes(payload)).hexdigest() != payload_sha256:
        raise ReportContractError("report_payload_sha256_mismatch")
    return payload, payload_sha256


def _failure(
    kind: str,
    report_sha256: str,
    reason: str,
    *,
    post_id: str | None = None,
    cursor: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "report_kind": kind,
        "report_sha256": report_sha256,
        "reason": reason,
    }
    if post_id is not None:
        result["post_id"] = post_id
    if cursor is not None:
        result["cursor_sha256"] = _cursor_sha256(cursor)
    return result


def _semantic_primary_post(
    wrapper_typename: str, row: dict[str, Any]
) -> dict[str, Any]:
    if wrapper_typename not in _STRICT_DISCOVERY_CONTENT_TYPENAMES:
        raise ReportContractError("search_primary_wrapper_typename_invalid")
    if row.get("__typename") != "SubredditPost":
        raise ReportContractError("search_primary_typename_invalid")
    post_id = _normalize_post_id(row.get("id"))
    if post_id is None or POST_ID_RE.fullmatch(post_id) is None:
        raise ReportContractError("search_primary_post_id_invalid")
    permalink = row.get("permalink")
    match = PERMALINK_RE.search(permalink) if isinstance(permalink, str) else None
    if match is None or _normalize_post_id(match.group(1)) != post_id:
        raise ReportContractError("search_primary_permalink_mismatch")
    post = _discovery_post_from_row(row, "tikhub_dynamic_search")
    if (
        post.post_id != post_id
        or post.created_at_utc is None
        or not post.title.strip()
        or not post.source_url
    ):
        raise ReportContractError("search_primary_values_invalid")
    return {
        "post_id": post_id,
        "subreddit": post.subreddit,
        "title": post.title,
        "selftext": "",
        "source_url": post.source_url,
        "created_at_utc": _iso_utc(post.created_at_utc),
        "score": post.score,
        "num_comments_reported": post.num_comments_reported,
    }


def _is_reviewed_dynamic_search_terminal_empty(payload: Any) -> bool:
    """Recognize the exact archived Reddit no-results terminal component."""
    try:
        main = payload["data"]["search"]["dynamic"]["components"]["main"]
    except (KeyError, TypeError):
        return False
    if not isinstance(main, dict) or set(main) != {"edges", "pageInfo"}:
        return False
    page_info = main.get("pageInfo")
    edges = main.get("edges")
    if (
        not isinstance(page_info, dict)
        or set(page_info)
        != {"endCursor", "hasNextPage", "hasPreviousPage", "startCursor"}
        or page_info.get("hasNextPage") is not False
        or page_info.get("hasPreviousPage") is not False
        or not isinstance(page_info.get("endCursor"), str)
        or not page_info["endCursor"]
        or page_info.get("startCursor") != ""
        or not isinstance(edges, list)
        or not edges
    ):
        return False

    for edge in edges:
        if (
            not isinstance(edge, dict)
            or set(edge) != {"cursor", "node"}
            or edge.get("cursor") != ""
        ):
            return False
        node = edge.get("node")
        if (
            not isinstance(node, dict)
            or set(node) != {
                "__typename",
                "behaviors",
                "presentation",
                "telemetry",
            }
            or node.get("__typename") != "SearchErrorMessage"
            or not isinstance(node.get("behaviors"), dict)
            or not isinstance(node.get("telemetry"), dict)
        ):
            return False
        presentation = node.get("presentation")
        if (
            not isinstance(presentation, dict)
            or set(presentation)
            != {
                "__typename",
                "ctaButtonText",
                "explanation",
                "icon",
                "message",
            }
            or presentation.get("__typename")
            != "SearchErrorMessageDefaultPresentation"
            or presentation.get("ctaButtonText") != "调整你的搜索"
            or presentation.get("explanation")
            != "请仔细检查拼写或尝试不同的关键词"
            or presentation.get("icon") != "EMPTY"
            or not isinstance(presentation.get("message"), str)
            or not presentation["message"].startswith("嗯...我们找不到")
            or not presentation["message"].endswith("的任何结果")
        ):
            return False
    return True


def _strict_search_records(
    payload: Any,
) -> tuple[list[tuple[str, dict[str, Any]]], bool]:
    try:
        return _strict_dynamic_search_post_records(payload), False
    except ValueError:
        if _is_reviewed_dynamic_search_terminal_empty(payload):
            return [], True
        raise


def _search_row_rejection(
    *,
    record_index: int,
    wrapper_typename: str,
    row: dict[str, Any],
    target_ids: set[str],
    report_sha256: str,
    payload_sha256: str,
    reason: str,
) -> dict[str, Any]:
    post_id = _normalize_post_id(row.get("id"))
    is_target = bool(post_id is not None and post_id in target_ids)
    rejection: dict[str, Any] = {
        "report_kind": "search_row",
        "report_sha256": report_sha256,
        "payload_sha256": payload_sha256,
        "record_index": record_index,
        "wrapper_typename": wrapper_typename,
        "reason": reason,
        "is_target": is_target,
    }
    if is_target:
        rejection["post_id"] = post_id
    return rejection


def _stable_post_fields(post: dict[str, Any]) -> dict[str, Any]:
    return {
        field: post[field]
        for field in (
            "post_id",
            "subreddit",
            "title",
            "selftext",
            "source_url",
            "created_at_utc",
        )
    }


def _scan_search_reports(
    roots: Sequence[Path],
    target_ids: set[str],
) -> dict[str, Any]:
    posts: dict[str, dict[str, Any]] = {}
    conflicted: set[str] = set()
    conflicts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    row_rejections: list[dict[str, Any]] = []
    source_reports: dict[tuple[object, ...], dict[str, Any]] = {}
    duplicate_occurrences = 0
    semantic_occurrences = 0
    candidate_occurrences = 0
    terminal_empty_reports = 0
    report_file_count = 0

    for path in _report_paths(roots, SEARCH_REPORT_NAMES):
        report_file_count += 1
        report_sha256 = _file_sha256(path)
        try:
            report, report_sha256 = _load_report(path)
            payload, payload_sha256 = _validated_report_payload(
                report, schemas=SEARCH_SCHEMAS, endpoint=ENDPOINTS["search"]
            )
            records, terminal_empty = _strict_search_records(payload)
        except (ReportContractError, ValueError) as exc:
            failures.append(_failure("search", report_sha256, str(exc)))
            continue

        source_key = (
            "search",
            report_sha256,
            payload_sha256,
            report.get("run_id"),
            report.get("lane_index"),
            report.get("continuation_depth"),
        )
        source_reports[source_key] = {
            "report_kind": "search",
            "report_sha256": report_sha256,
            "payload_sha256": payload_sha256,
            "run_id": report.get("run_id"),
            "lane_index": report.get("lane_index"),
            "continuation_depth": report.get("continuation_depth"),
            "terminal_empty": terminal_empty,
        }
        if terminal_empty:
            terminal_empty_reports += 1

        candidate_occurrences += len(records)
        for record_index, (wrapper_typename, row) in enumerate(records):
            try:
                post = _semantic_primary_post(wrapper_typename, row)
            except ReportContractError as exc:
                row_rejections.append(
                    _search_row_rejection(
                        record_index=record_index,
                        wrapper_typename=wrapper_typename,
                        row=row,
                        target_ids=target_ids,
                        report_sha256=report_sha256,
                        payload_sha256=payload_sha256,
                        reason=str(exc),
                    )
                )
                continue
            semantic_occurrences += 1
            post_id = str(post["post_id"])
            if post_id not in target_ids:
                continue
            if post_id in conflicted:
                duplicate_occurrences += 1
                continue
            existing = posts.get(post_id)
            if existing is None:
                posts[post_id] = {
                    **_stable_post_fields(post),
                    "score_values": set()
                    if post["score"] is None
                    else {int(post["score"])},
                    "reported_values": set()
                    if post["num_comments_reported"] is None
                    else {int(post["num_comments_reported"])},
                    "source_payload_sha256s": {payload_sha256},
                }
                continue
            duplicate_occurrences += 1
            differing = sorted(
                field
                for field, value in _stable_post_fields(post).items()
                if existing[field] != value
            )
            if differing:
                conflicts.append({"post_id": post_id, "differing_fields": differing})
                conflicted.add(post_id)
                del posts[post_id]
                continue
            if post["score"] is not None:
                cast_scores = existing["score_values"]
                assert isinstance(cast_scores, set)
                cast_scores.add(int(post["score"]))
            if post["num_comments_reported"] is not None:
                cast_reported = existing["reported_values"]
                assert isinstance(cast_reported, set)
                cast_reported.add(int(post["num_comments_reported"]))
            cast_sources = existing["source_payload_sha256s"]
            assert isinstance(cast_sources, set)
            cast_sources.add(payload_sha256)

    canonical_posts: dict[str, dict[str, Any]] = {}
    for post_id, internal in posts.items():
        scores = internal.pop("score_values")
        reported = internal.pop("reported_values")
        sources = internal.pop("source_payload_sha256s")
        assert isinstance(scores, set)
        assert isinstance(reported, set)
        assert isinstance(sources, set)
        canonical_posts[post_id] = {
            **internal,
            "score": max(scores) if scores else None,
            "num_comments_reported": max(reported) if reported else None,
            "source_payload_sha256s": sorted(sources),
        }
    return {
        "posts": canonical_posts,
        "conflicts": conflicts,
        "failures": failures,
        "row_rejections": sorted(
            {canonical_bytes(row): row for row in row_rejections}.values(),
            key=lambda row: (
                str(row["report_sha256"]),
                int(row["record_index"]),
                str(row["wrapper_typename"]),
                str(row["reason"]),
            ),
        ),
        "source_reports": list(source_reports.values()),
        "duplicate_occurrences": duplicate_occurrences,
        "semantic_occurrences": semantic_occurrences,
        "candidate_occurrences": candidate_occurrences,
        "terminal_empty_reports": terminal_empty_reports,
        "report_file_count": report_file_count,
    }


def _normalized_comment(comment: Any) -> dict[str, Any]:
    if COMMENT_ID_RE.fullmatch(comment.comment_id) is None:
        raise ReportContractError("comment_id_invalid")
    return {
        "comment_id": comment.comment_id,
        "post_id": comment.post_id,
        "body": comment.body,
        "created_at_utc": _iso_utc(comment.created_at_utc),
        "parent_id": comment.parent_id,
        "score": comment.score,
        "depth": comment.depth,
        "is_submitter": comment.is_submitter,
        "matched_keywords": sorted(set(comment.matched_keywords)),
        "author_hash": comment.author_hash,
        "deleted_or_removed": comment.deleted_or_removed,
    }


def _parse_comment_report(
    report: dict[str, Any],
    *,
    path_name: str,
    report_sha256: str,
    expected_post_id: str,
) -> dict[str, Any]:
    kind = "first_page" if path_name == "comment-repair-probe.json" else "reply"
    payload, payload_sha256 = _validated_report_payload(
        report,
        schemas=frozenset({COMMENT_SCHEMAS[path_name]}),
        endpoint=ENDPOINTS[kind],
    )
    request_params = report.get("request_params")
    if not isinstance(request_params, dict):
        raise ReportContractError("comment_request_params_invalid")
    requested_post_id = _normalize_post_id(request_params.get("post_id"))
    if requested_post_id != expected_post_id:
        raise ReportContractError("comment_request_post_id_mismatch")

    cursor: str | None = None
    source_payload_sha256: str | None = None
    source_binding_mode = "not_applicable"
    if kind == "first_page":
        if request_params.get("after") != "":
            raise ReportContractError("comment_first_page_after_invalid")
    else:
        cursor_value = report.get("cursor")
        if not isinstance(cursor_value, str) or not cursor_value:
            raise ReportContractError("comment_reply_cursor_invalid")
        if request_params.get("cursor") != cursor_value:
            raise ReportContractError("comment_reply_cursor_mismatch")
        cursor = cursor_value
        if "source_first_page_payload_sha256" not in report:
            raise ReportContractError("comment_reply_source_sha256_invalid")
        source_value = report.get("source_first_page_payload_sha256")
        if source_value is None:
            source_binding_mode = "legacy_null_pending"
        elif isinstance(source_value, str) and SHA256_RE.fullmatch(source_value):
            source_payload_sha256 = source_value
            source_binding_mode = "explicit_pending"
        else:
            raise ReportContractError("comment_reply_source_sha256_invalid")

    try:
        summary = parse_comment_repair_payload(
            payload, expected_post_id=expected_post_id
        )
        comments, _more_count = _parse_strict_tikhub_comment_payload(
            payload,
            post_id=expected_post_id,
            run_id=str(report.get("run_id") or "v2-raw-snapshot"),
            raw_capture_id="raw_v2_" + payload_sha256[:24],
            submitter_name="",
        )
    except ValueError as exc:
        raise ReportContractError(str(exc)) from None
    normalized_comments = [_normalized_comment(comment) for comment in comments]
    summary_ids = sorted(str(row["comment_id"]) for row in summary["comments"])
    parsed_ids = sorted(str(row["comment_id"]) for row in normalized_comments)
    if summary_ids != parsed_ids:
        raise ReportContractError("comment_parser_identity_mismatch")
    expected_metadata = {
        "parsed_comment_count": summary["parsed_comment_count"],
        "more_node_count": summary["more_node_count"],
        "more_cursor_count": len(summary["more_cursors"]),
    }
    if kind == "first_page":
        expected_metadata["reported_comment_count"] = summary[
            "reported_comment_count"
        ]
        expected_metadata["has_next_page"] = summary["has_next_page"]
    for field, expected in expected_metadata.items():
        if report.get(field) != expected:
            raise ReportContractError(f"comment_report_{field}_mismatch")
    return {
        "kind": kind,
        "post_id": expected_post_id,
        "cursor": cursor,
        "cursor_sha256": None if cursor is None else _cursor_sha256(cursor),
        "source_payload_sha256": source_payload_sha256,
        "source_binding_mode": source_binding_mode,
        "payload_sha256": payload_sha256,
        "report_sha256": report_sha256,
        "run_id": report.get("run_id"),
        "comments": normalized_comments,
        "more_cursors": tuple(str(value) for value in summary["more_cursors"]),
        "has_next_page": summary["has_next_page"],
    }


def _consolidate_comment_reports(
    reports: dict[object, list[dict[str, Any]]],
    *,
    kind: str,
) -> tuple[dict[object, dict[str, Any]], list[dict[str, Any]], int]:
    accepted: dict[object, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    duplicate_count = 0
    for key, values in reports.items():
        by_payload: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for value in values:
            by_payload[str(value["payload_sha256"])].append(value)
        duplicate_count += sum(len(group) - 1 for group in by_payload.values())
        if len(by_payload) != 1:
            first = values[0]
            conflict = {
                "report_kind": kind,
                "post_id": first["post_id"],
                "payload_sha256s": sorted(by_payload),
            }
            if first.get("cursor_sha256") is not None:
                conflict["cursor_sha256"] = first["cursor_sha256"]
            conflicts.append(conflict)
            continue
        payload_sha256 = next(iter(by_payload))
        accepted[key] = min(
            by_payload[payload_sha256], key=lambda row: str(row["report_sha256"])
        )
    return accepted, conflicts, duplicate_count


def _bind_replies_to_rooted_parents(
    first_pages: dict[object, dict[str, Any]],
    replies: dict[object, dict[str, Any]],
) -> tuple[
    dict[object, dict[str, Any]],
    list[dict[str, object]],
    dict[str, int],
    set[tuple[str, str]],
]:
    """Resolve direct reply parents without letting orphan chains self-attest."""
    parent_reports: dict[tuple[str, str, str], dict[str, Any]] = {}
    parent_nodes_by_child: dict[
        tuple[str, str], set[tuple[str, str, str]]
    ] = defaultdict(set)
    first_nodes: set[tuple[str, str, str]] = set()
    reply_nodes: dict[tuple[str, str], tuple[str, str, str]] = {}

    for post_key, report in first_pages.items():
        post_id = str(post_key)
        node = ("first_page", post_id, "")
        parent_reports[node] = report
        first_nodes.add(node)
    for raw_key, report in replies.items():
        if not isinstance(raw_key, tuple) or len(raw_key) != 2:
            raise AssertionError("reply key invariant")
        post_id, cursor = str(raw_key[0]), str(raw_key[1])
        node = ("reply", post_id, cursor)
        parent_reports[node] = report
        reply_nodes[(post_id, cursor)] = node

    for node, report in parent_reports.items():
        post_id = node[1]
        for child_cursor in set(str(value) for value in report["more_cursors"]):
            parent_nodes_by_child[(post_id, child_cursor)].add(node)

    structural_parent: dict[
        tuple[str, str], tuple[str, str, str]
    ] = {}
    derived_sources: dict[tuple[str, str], str] = {}
    failures: list[dict[str, object]] = []
    invalid_keys: set[tuple[str, str]] = set()
    stats = {
        "legacy_null_reply_report_count": 0,
        "legacy_structural_source_derived_count": 0,
        "legacy_source_predecessor_missing_count": 0,
        "legacy_source_predecessor_ambiguous_count": 0,
        "legacy_source_chain_incomplete_count": 0,
        "native_direct_source_verified_count": 0,
        "native_source_predecessor_missing_count": 0,
        "native_source_predecessor_ambiguous_count": 0,
        "native_source_mismatch_count": 0,
        "native_source_chain_incomplete_count": 0,
    }

    for key in sorted(reply_nodes):
        report = replies[key]
        legacy_null = report["source_binding_mode"] == "legacy_null_pending"
        if legacy_null:
            stats["legacy_null_reply_report_count"] += 1
        parents = sorted(parent_nodes_by_child.get(key, set()))
        if len(parents) != 1:
            if legacy_null:
                reason = (
                    "legacy_reply_source_predecessor_missing"
                    if not parents
                    else "legacy_reply_source_predecessor_ambiguous"
                )
                counter = (
                    "legacy_source_predecessor_missing_count"
                    if not parents
                    else "legacy_source_predecessor_ambiguous_count"
                )
            else:
                reason = (
                    "comment_reply_source_payload_missing"
                    if not parents
                    else "comment_reply_source_payload_ambiguous"
                )
                counter = (
                    "native_source_predecessor_missing_count"
                    if not parents
                    else "native_source_predecessor_ambiguous_count"
                )
            stats[counter] += 1
            failures.append(
                _failure(
                    "reply",
                    str(report["report_sha256"]),
                    reason,
                    post_id=key[0],
                    cursor=key[1],
                )
            )
            invalid_keys.add(key)
            continue

        parent_node = parents[0]
        parent_payload_sha256 = str(parent_reports[parent_node]["payload_sha256"])
        declared_source = report.get("source_payload_sha256")
        if not legacy_null and declared_source != parent_payload_sha256:
            stats["native_source_mismatch_count"] += 1
            failures.append(
                _failure(
                    "reply",
                    str(report["report_sha256"]),
                    "comment_reply_source_payload_mismatch",
                    post_id=key[0],
                    cursor=key[1],
                )
            )
            invalid_keys.add(key)
            continue
        structural_parent[key] = parent_node
        if legacy_null:
            derived_sources[key] = parent_payload_sha256

    rooted_nodes = set(first_nodes)
    changed = True
    while changed:
        changed = False
        for key in sorted(structural_parent):
            node = reply_nodes[key]
            if node in rooted_nodes or key in invalid_keys:
                continue
            if structural_parent[key] in rooted_nodes:
                rooted_nodes.add(node)
                changed = True

    for key in sorted(structural_parent):
        if key in invalid_keys:
            continue
        report = replies[key]
        node = reply_nodes[key]
        legacy_null = report["source_binding_mode"] == "legacy_null_pending"
        if node not in rooted_nodes:
            if legacy_null:
                reason = "legacy_reply_source_chain_incomplete"
                stats["legacy_source_chain_incomplete_count"] += 1
            else:
                reason = "comment_reply_source_chain_incomplete"
                stats["native_source_chain_incomplete_count"] += 1
            failures.append(
                _failure(
                    "reply",
                    str(report["report_sha256"]),
                    reason,
                    post_id=key[0],
                    cursor=key[1],
                )
            )
            invalid_keys.add(key)
            continue
        if legacy_null:
            report["source_payload_sha256"] = derived_sources[key]
            report["source_binding_mode"] = "legacy_structural_source_derived"
            stats["legacy_structural_source_derived_count"] += 1
        else:
            report["source_binding_mode"] = "explicit_direct_parent_verified"
            stats["native_direct_source_verified_count"] += 1

    valid_replies = {
        raw_key: report
        for raw_key, report in replies.items()
        if (str(raw_key[0]), str(raw_key[1])) not in invalid_keys
    }
    return valid_replies, failures, stats, invalid_keys


def _scan_comment_reports(
    roots: Sequence[Path],
    target_ids: set[str],
) -> dict[str, Any]:
    first_candidates: dict[object, list[dict[str, Any]]] = defaultdict(list)
    reply_candidates: dict[object, list[dict[str, Any]]] = defaultdict(list)
    failures: list[dict[str, Any]] = []
    source_reports: dict[tuple[object, ...], dict[str, Any]] = {}
    ignored_non_target = 0
    report_file_count = 0

    for path in _report_paths(roots, COMMENT_REPORT_NAMES):
        report_file_count += 1
        report_sha256 = _file_sha256(path)
        try:
            report, report_sha256 = _load_report(path)
        except ReportContractError as exc:
            failures.append(_failure("comment_unknown", report_sha256, str(exc)))
            continue
        post_id = _normalize_post_id(report.get("post_id"))
        kind = "first_page" if path.name == "comment-repair-probe.json" else "reply"
        cursor = report.get("cursor") if kind == "reply" else None
        if post_id is None or POST_ID_RE.fullmatch(post_id) is None:
            failures.append(_failure(kind, report_sha256, "comment_report_post_id_invalid"))
            continue
        if post_id not in target_ids:
            ignored_non_target += 1
            continue
        try:
            parsed = _parse_comment_report(
                report,
                path_name=path.name,
                report_sha256=report_sha256,
                expected_post_id=post_id,
            )
        except ReportContractError as exc:
            failures.append(
                _failure(
                    kind,
                    report_sha256,
                    str(exc),
                    post_id=post_id,
                    cursor=cursor if isinstance(cursor, str) and cursor else None,
                )
            )
            continue
        if kind == "first_page":
            first_candidates[post_id].append(parsed)
        else:
            reply_candidates[(post_id, str(parsed["cursor"]))].append(parsed)
        if kind == "first_page" or parsed["source_binding_mode"] != "legacy_null_pending":
            source_key = (
                kind,
                report_sha256,
                parsed["payload_sha256"],
                post_id,
                parsed.get("cursor_sha256"),
            )
            source_reports[source_key] = {
                "report_kind": kind,
                "report_sha256": report_sha256,
                "payload_sha256": parsed["payload_sha256"],
                "run_id": parsed["run_id"],
                "post_id": post_id,
                "cursor_sha256": parsed.get("cursor_sha256"),
                "source_payload_sha256": parsed.get("source_payload_sha256"),
            }

    first_pages, first_conflicts, duplicate_first = _consolidate_comment_reports(
        first_candidates, kind="first_page"
    )
    replies, reply_conflicts, duplicate_replies = _consolidate_comment_reports(
        reply_candidates, kind="reply"
    )
    replies, binding_failures, binding_stats, invalid_reply_keys = (
        _bind_replies_to_rooted_parents(first_pages, replies)
    )
    failures.extend(binding_failures)
    for post_id, cursor in invalid_reply_keys:
        cursor_sha256 = _cursor_sha256(cursor)
        for source_key in list(source_reports):
            if (
                source_key[0] == "reply"
                and source_key[3] == post_id
                and source_key[4] == cursor_sha256
            ):
                del source_reports[source_key]
    for report in replies.values():
        if report["source_binding_mode"] != "legacy_structural_source_derived":
            continue
        source_key = (
            "reply",
            report["report_sha256"],
            report["payload_sha256"],
            report["post_id"],
            report["cursor_sha256"],
        )
        source_reports[source_key] = {
            "report_kind": "reply",
            "report_sha256": report["report_sha256"],
            "payload_sha256": report["payload_sha256"],
            "run_id": report["run_id"],
            "post_id": report["post_id"],
            "cursor_sha256": report["cursor_sha256"],
            "source_payload_sha256": report["source_payload_sha256"],
            "source_binding_mode": "legacy_structural_source_derived",
        }

    return {
        "first_pages": first_pages,
        "replies": replies,
        "conflicts": [*first_conflicts, *reply_conflicts],
        "failures": failures,
        "source_reports": list(source_reports.values()),
        "duplicate_first_pages": duplicate_first,
        "duplicate_replies": duplicate_replies,
        "reply_source_resolution": binding_stats,
        "ignored_non_target": ignored_non_target,
        "report_file_count": report_file_count,
    }


def _reachable_comment_reports(
    target_ids: tuple[str, ...],
    first_pages: dict[object, dict[str, Any]],
    replies: dict[object, dict[str, Any]],
) -> dict[str, Any]:
    reachable_reports: list[dict[str, Any]] = []
    first_page_missing: list[str] = []
    outstanding: list[dict[str, str]] = []
    orphan_replies: list[dict[str, str]] = []
    cursor_cycles: list[dict[str, Any]] = []
    page_has_next: set[str] = set()
    reachable_by_post: dict[str, set[str]] = defaultdict(set)

    for post_id in target_ids:
        first = first_pages.get(post_id)
        if first is None:
            first_page_missing.append(post_id)
            continue
        reachable_reports.append(first)
        if first["has_next_page"] is True:
            page_has_next.add(post_id)
        roots = set(str(value) for value in first["more_cursors"])
        graph: dict[str, set[str]] = {}
        stack = list(sorted(roots, reverse=True))
        while stack:
            cursor = stack.pop()
            if cursor in reachable_by_post[post_id]:
                continue
            reachable_by_post[post_id].add(cursor)
            reply = replies.get((post_id, cursor))
            if reply is None:
                outstanding.append(
                    {"post_id": post_id, "cursor_sha256": _cursor_sha256(cursor)}
                )
                continue
            reachable_reports.append(reply)
            if reply["has_next_page"] is True:
                page_has_next.add(post_id)
            children = set(str(value) for value in reply["more_cursors"])
            graph[cursor] = children
            stack.extend(sorted(children - reachable_by_post[post_id], reverse=True))

        visiting: set[str] = set()
        visited: set[str] = set()
        cycle_nodes: set[str] = set()

        def visit(cursor: str) -> None:
            if cursor in visiting:
                cycle_nodes.add(cursor)
                return
            if cursor in visited:
                return
            visiting.add(cursor)
            for child in sorted(graph.get(cursor, set())):
                if child in visiting:
                    cycle_nodes.update({cursor, child})
                else:
                    visit(child)
            visiting.remove(cursor)
            visited.add(cursor)

        for root in sorted(roots):
            visit(root)
        if cycle_nodes:
            cursor_cycles.append(
                {
                    "post_id": post_id,
                    "cursor_sha256s": sorted(_cursor_sha256(value) for value in cycle_nodes),
                }
            )

    for key, report in replies.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise AssertionError("reply key invariant")
        post_id, cursor = key
        if str(cursor) not in reachable_by_post[str(post_id)]:
            orphan_replies.append(
                {
                    "post_id": str(post_id),
                    "cursor_sha256": str(report["cursor_sha256"]),
                }
            )
    return {
        "reports": reachable_reports,
        "first_page_missing": sorted(first_page_missing),
        "cursor_outstanding": sorted(
            outstanding, key=lambda row: (row["post_id"], row["cursor_sha256"])
        ),
        "orphan_replies": sorted(
            orphan_replies, key=lambda row: (row["post_id"], row["cursor_sha256"])
        ),
        "cursor_cycles": sorted(cursor_cycles, key=lambda row: row["post_id"]),
        "page_has_next": sorted(page_has_next),
        "reachable_by_post": reachable_by_post,
    }


def _merge_comments(
    reports: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    comments: dict[str, dict[str, Any]] = {}
    sources: dict[str, set[str]] = defaultdict(set)
    conflicted: set[str] = set()
    conflicts: list[dict[str, Any]] = []
    for report in sorted(
        reports,
        key=lambda row: (
            str(row["post_id"]),
            str(row.get("cursor_sha256") or ""),
            str(row["payload_sha256"]),
        ),
    ):
        payload_sha256 = str(report["payload_sha256"])
        report_comments = report["comments"]
        assert isinstance(report_comments, list)
        for value in report_comments:
            assert isinstance(value, dict)
            comment_id = str(value["comment_id"])
            if comment_id in conflicted:
                continue
            existing = comments.get(comment_id)
            if existing is None:
                comments[comment_id] = dict(value)
                sources[comment_id].add(payload_sha256)
                continue
            differing = sorted(
                field
                for field in value
                if field != "source_payload_sha256s" and existing.get(field) != value[field]
            )
            if differing:
                conflicts.append(
                    {
                        "comment_id": comment_id,
                        "post_id": value["post_id"],
                        "differing_fields": differing,
                    }
                )
                conflicted.add(comment_id)
                del comments[comment_id]
                sources.pop(comment_id, None)
                continue
            sources[comment_id].add(payload_sha256)
    output = [
        {**comments[comment_id], "source_payload_sha256s": sorted(sources[comment_id])}
        for comment_id in sorted(comments)
    ]
    return output, sorted(conflicts, key=lambda row: str(row["comment_id"]))


def _analysis_record(source_type: str, source_id: str, text: str) -> dict[str, Any]:
    analysis = analyze_text(text)
    match = analysis.keyword_match
    return {
        "analysis_id": f"analysis_{source_type}_{source_id}",
        "source_type": source_type,
        "source_id": source_id,
        "sentiment_label": analysis.sentiment_label,
        "sentiment_score": analysis.sentiment_score,
        "topic": analysis.topic,
        "severity": analysis.severity,
        "confidence": analysis.confidence,
        "pain_points": list(analysis.pain_points),
        "keyword_match": {
            "brands": sorted(match.brands),
            "products": sorted(match.products),
            "categories": sorted(match.categories),
            "competitors": sorted(match.competitors),
            "excluded": match.excluded,
        },
    }


def build(
    identity_inventory: Path | str,
    *,
    set_id: str,
    expected_target_count: int,
    expected_target_sha256: str,
    search_report_roots: Sequence[Path | str],
    comment_report_roots: Sequence[Path | str],
) -> dict[str, Any]:
    """Build one byte-stable snapshot and explicit admission accounting."""
    target_ids, target_window, inventory_sha256 = _load_target_set(
        Path(identity_inventory),
        set_id=set_id,
        expected_count=expected_target_count,
        expected_sha256=expected_target_sha256,
    )
    target_set = set(target_ids)
    search = _scan_search_reports(
        [Path(value) for value in search_report_roots], target_set
    )
    comments = _scan_comment_reports(
        [Path(value) for value in comment_report_roots], target_set
    )
    posts_by_id = search["posts"]
    assert isinstance(posts_by_id, dict)

    outside_window: list[str] = []
    if target_window is not None:
        start = _parse_datetime(target_window["start"])
        end = _parse_datetime(target_window["end"])
        assert start is not None and end is not None
        for post_id, post in posts_by_id.items():
            assert isinstance(post, dict)
            created = _parse_datetime(post["created_at_utc"])
            if created is None or not start <= created < end:
                outside_window.append(str(post_id))

    lineage_missing = sorted(target_set - set(posts_by_id))
    reachable = _reachable_comment_reports(
        target_ids,
        comments["first_pages"],  # type: ignore[arg-type]
        comments["replies"],  # type: ignore[arg-type]
    )
    canonical_comments, comment_conflicts = _merge_comments(
        reachable["reports"]  # type: ignore[arg-type]
    )
    comments_by_post: dict[str, int] = defaultdict(int)
    for comment in canonical_comments:
        comments_by_post[str(comment["post_id"])] += 1

    incomplete_posts = set(lineage_missing)
    incomplete_posts.update(reachable["first_page_missing"])  # type: ignore[arg-type]
    incomplete_posts.update(row["post_id"] for row in reachable["cursor_outstanding"])  # type: ignore[index]
    incomplete_posts.update(reachable["page_has_next"])  # type: ignore[arg-type]
    incomplete_posts.update(str(row["post_id"]) for row in comment_conflicts)
    output_posts: list[dict[str, Any]] = []
    for post_id in sorted(posts_by_id):
        post = dict(posts_by_id[post_id])
        parsed_count = comments_by_post.get(post_id, 0)
        if post_id in incomplete_posts:
            coverage = "partial" if parsed_count else "post_only"
        else:
            coverage = "full"
        post.update(
            {
                "parsed_comment_count": parsed_count,
                "coverage_grade": coverage,
                "post_content_scope": "search_discovery_only",
                "author_hash": None,
            }
        )
        output_posts.append(post)

    analyses = [
        *(
            _analysis_record(
                "post", str(post["post_id"]), f"{post['title']}\n{post['selftext']}"
            )
            for post in output_posts
        ),
        *(
            _analysis_record("comment", str(comment["comment_id"]), str(comment["body"]))
            for comment in canonical_comments
        ),
    ]
    analyses.sort(
        key=lambda row: (
            0 if row["source_type"] == "post" else 1,
            str(row["source_id"]),
        )
    )

    failures = [*search["failures"], *comments["failures"]]  # type: ignore[list-item]
    failures = sorted(
        {canonical_bytes(row): row for row in failures}.values(),
        key=lambda row: (
            str(row["report_kind"]),
            str(row.get("post_id") or ""),
            str(row["report_sha256"]),
            str(row["reason"]),
        ),
    )
    search_conflicts = sorted(
        search["conflicts"], key=lambda row: str(row["post_id"])  # type: ignore[arg-type,index]
    )
    report_conflicts = sorted(
        comments["conflicts"],  # type: ignore[arg-type]
        key=lambda row: (
            str(row["report_kind"]),
            str(row["post_id"]),
            str(row.get("cursor_sha256") or ""),
        ),
    )
    blockers = {
        "lineage_missing": len(lineage_missing),
        "search_post_conflicts": len(search_conflicts),
        "outside_target_window": len(outside_window),
        "first_page_missing": len(reachable["first_page_missing"]),  # type: ignore[arg-type]
        "cursor_outstanding": len(reachable["cursor_outstanding"]),  # type: ignore[arg-type]
        "cursor_cycles": len(reachable["cursor_cycles"]),  # type: ignore[arg-type]
        "page_pagination_outstanding": len(reachable["page_has_next"]),  # type: ignore[arg-type]
        "orphan_reply_reports": len(reachable["orphan_replies"]),  # type: ignore[arg-type]
        "report_conflicts": len(report_conflicts),
        "comment_conflicts": len(comment_conflicts),
        "failed_reports": len(failures),
    }
    status = "complete" if not any(blockers.values()) else "blocked"

    source_reports = [*search["source_reports"], *comments["source_reports"]]  # type: ignore[list-item]
    source_reports = sorted(
        {canonical_bytes(row): row for row in source_reports}.values(),
        key=lambda row: (
            str(row["report_kind"]),
            str(row.get("post_id") or ""),
            str(row.get("cursor_sha256") or ""),
            str(row["report_sha256"]),
        ),
    )
    reply_source_resolution = comments["reply_source_resolution"]
    assert isinstance(reply_source_resolution, dict)
    include_reply_source_resolution = bool(
        reply_source_resolution["legacy_null_reply_report_count"]
        or reply_source_resolution["legacy_source_predecessor_missing_count"]
        or reply_source_resolution["legacy_source_predecessor_ambiguous_count"]
        or reply_source_resolution["legacy_source_chain_incomplete_count"]
        or reply_source_resolution["native_source_predecessor_missing_count"]
        or reply_source_resolution["native_source_predecessor_ambiguous_count"]
        or reply_source_resolution["native_source_mismatch_count"]
        or reply_source_resolution["native_source_chain_incomplete_count"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "target": {
            "set_id": set_id,
            "count": len(target_ids),
            "post_ids_sha256": expected_target_sha256,
            "identity_inventory_sha256": inventory_sha256,
            "target_window_utc": target_window,
        },
        "accounting": {
            "target_post_count": len(target_ids),
            "search_report_file_count": search["report_file_count"],
            "search_candidate_occurrence_count": search[
                "candidate_occurrences"
            ],
            "search_semantic_primary_occurrence_count": search[
                "semantic_occurrences"
            ],
            "search_row_rejection_count": len(search["row_rejections"]),
            "target_search_row_rejection_count": sum(
                1 for row in search["row_rejections"] if row["is_target"]
            ),
            "search_terminal_empty_report_count": search[
                "terminal_empty_reports"
            ],
            "duplicate_search_occurrence_count": search["duplicate_occurrences"],
            "comment_report_file_count": comments["report_file_count"],
            "ignored_non_target_comment_report_count": comments[
                "ignored_non_target"
            ],
            "duplicate_first_page_report_count": comments[
                "duplicate_first_pages"
            ],
            "duplicate_reply_report_count": comments["duplicate_replies"],
            **(
                {"reply_source_resolution": reply_source_resolution}
                if include_reply_source_resolution
                else {}
            ),
            "canonical_post_count": len(output_posts),
            "canonical_comment_count": len(canonical_comments),
            "canonical_analysis_count": len(analyses),
            "blockers": blockers,
            "lineage_missing_post_ids": lineage_missing,
            "outside_target_window_post_ids": sorted(outside_window),
            "first_page_missing_post_ids": reachable["first_page_missing"],
            "cursor_outstanding": reachable["cursor_outstanding"],
            "cursor_cycles": reachable["cursor_cycles"],
            "page_pagination_outstanding_post_ids": reachable["page_has_next"],
            "orphan_reply_reports": reachable["orphan_replies"],
            "search_post_conflicts": search_conflicts,
            "search_row_rejections": search["row_rejections"],
            "report_conflicts": report_conflicts,
            "comment_conflicts": comment_conflicts,
            "failed_reports": failures,
        },
        "posts": output_posts,
        "comments": canonical_comments,
        "analyses": analyses,
        "source_reports": source_reports,
        "privacy": {
            "raw_payload_embedded": False,
            "raw_username_embedded": False,
            "author_identity": "sha256_hash_or_null",
            "cursor_identity": "sha256_only",
        },
        "provider_call": False,
        "provider_attempt_made": False,
        "database_write": False,
        "production_merge": False,
        "git_push": False,
        "live_send": False,
        "dingtalk": False,
    }


def write_snapshot(snapshot: dict[str, object], destination: Path | str) -> str:
    path = Path(destination)
    payload = canonical_bytes(snapshot) + b"\n"
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise SnapshotContractError("snapshot_destination_conflict")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    path.chmod(0o600)
    return sha256(payload).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity-inventory", type=Path, required=True)
    parser.add_argument("--set-id", required=True)
    parser.add_argument("--expected-target-count", type=int, required=True)
    parser.add_argument("--expected-target-sha256", required=True)
    parser.add_argument(
        "--search-report-root", type=Path, action="append", required=True
    )
    parser.add_argument(
        "--comment-report-root", type=Path, action="append", required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        snapshot = build(
            args.identity_inventory,
            set_id=args.set_id,
            expected_target_count=args.expected_target_count,
            expected_target_sha256=args.expected_target_sha256,
            search_report_roots=args.search_report_root,
            comment_report_roots=args.comment_report_root,
        )
        digest = write_snapshot(snapshot, args.output)
    except SnapshotContractError as exc:
        print(f"reddit_v2_raw_snapshot_error={exc}", file=sys.stderr)
        return 64
    print(
        canonical_bytes(
            {
                "schema_version": "reddit_voc_v2_raw_snapshot_receipt_v1",
                "status": snapshot["status"],
                "snapshot_sha256": digest,
                "provider_call": False,
                "database_write": False,
                "production_merge": False,
                "live_send": False,
            }
        ).decode("utf-8")
    )
    return 0 if snapshot["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
