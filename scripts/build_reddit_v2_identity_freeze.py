#!/usr/bin/env python3
"""Freeze Reddit post identities from an immutable V2 report archive.

This is an offline, identity-only reconciliation step.  It validates every
archived report byte-for-byte, parses dynamic-search payloads with the reviewed
strict parser, and joins the resulting identities to the previously audited
remote materialized/semantic sets and the current site set.  The output is
private (0600) and intentionally contains no post body, comment, author, raw
search term, credential, or production mutation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Sequence

from reddit_voc.tikhub import (
    FETCH_DYNAMIC_SEARCH,
    TikHubDiscoveryShapeError,
    _STRICT_DISCOVERY_CONTENT_TYPENAMES,
    _discovery_post_from_row,
    _strict_dynamic_search_post_records,
)


SCHEMA_VERSION = "reddit_voc_v2_identity_freeze_v1"
MANIFEST_SCHEMA_VERSION = "reddit_voc_v2_report_file_manifest_v1"
SEARCH_REPORT_SCHEMAS = frozenset(
    {
        "reddit_voc_search_lane_probe_v1",
        "reddit_voc_search_continuation_probe_v1",
    }
)
SEARCH_REPORT_NAMES = frozenset(
    {"search-lane-probe.json", "search-continuation-probe.json"}
)
POST_ID_RE = re.compile(r"^[a-z0-9]{5,10}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PERMALINK_RE = re.compile(r"/comments/([a-z0-9]{5,10})(?:/|$)", re.I)


class IdentityFreezeContractError(ValueError):
    """An immutable input contract failed; no identity freeze is trustworthy."""


@dataclass(frozen=True)
class ValidatedArchive:
    cutoff: datetime
    manifest_sha256: str
    file_manifest_lf_sha256: str
    file_count: int
    total_bytes: int
    entries: tuple[tuple[str, int, str, Path], ...]


@dataclass(frozen=True)
class SearchPage:
    lane_index: int
    continuation_depth: int
    term_sha256: str
    has_next_page: bool
    report_sha256: str
    semantic_rows: tuple[tuple[str, datetime], ...]
    profile_rows_excluded: int
    quarantined_reason: str | None


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def identity_hash(values: Iterable[str]) -> str:
    ordered = sorted(set(values))
    payload = "".join(f"{value}\n" for value in ordered).encode("utf-8")
    return sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_datetime(value: object, *, error: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise IdentityFreezeContractError(error)
    candidate = value.strip().replace("Z", "+00:00")
    candidate = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", candidate)
    candidate = re.sub(
        r"(\.\d{6})\d+(?=[+-]\d\d:\d\d$)", r"\1", candidate
    )
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise IdentityFreezeContractError(error) from exc
    if parsed.tzinfo is None:
        raise IdentityFreezeContractError(error)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_post_id(value: object, *, error: str) -> str:
    if not isinstance(value, str):
        raise IdentityFreezeContractError(error)
    normalized = value.strip().lower()
    if normalized.startswith("t3_"):
        normalized = normalized[3:]
    if POST_ID_RE.fullmatch(normalized) is None:
        raise IdentityFreezeContractError(error)
    return normalized


def _load_json(path: Path, *, error: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IdentityFreezeContractError(error) from exc


def _manifest_lf_hash(rows: Sequence[tuple[str, int, str]]) -> str:
    payload = "".join(
        f"{relative_path}|{size}|{digest}\n"
        for relative_path, size, digest in rows
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def validate_report_archive(
    reports_root: Path,
    manifest_path: Path,
    *,
    expected_manifest_cutoff_utc: str,
) -> ValidatedArchive:
    """Validate every manifest entry, aggregate, and filesystem member."""

    try:
        root = reports_root.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise IdentityFreezeContractError("reports_root_unreadable") from exc
    if not root.is_dir():
        raise IdentityFreezeContractError("reports_root_not_directory")

    manifest = _load_json(manifest_path, error="report_manifest_unreadable")
    if not isinstance(manifest, dict):
        raise IdentityFreezeContractError("report_manifest_invalid")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise IdentityFreezeContractError("report_manifest_schema_invalid")
    if manifest.get("raw_payload_embedded_in_manifest") is not False:
        raise IdentityFreezeContractError("report_manifest_payload_boundary_invalid")

    expected_cutoff = _parse_datetime(
        expected_manifest_cutoff_utc, error="expected_manifest_cutoff_invalid"
    )
    manifest_cutoff = _parse_datetime(
        manifest.get("freeze_cutoff_utc"), error="manifest_search_cutoff_invalid"
    )
    if manifest_cutoff != expected_cutoff:
        raise IdentityFreezeContractError("manifest_search_cutoff_mismatch")

    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise IdentityFreezeContractError("report_manifest_files_invalid")

    entries: list[tuple[str, int, str, Path]] = []
    aggregate_rows: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != {
            "relative_path",
            "bytes",
            "sha256",
        }:
            raise IdentityFreezeContractError("report_manifest_file_row_invalid")
        relative_path = raw.get("relative_path")
        size = raw.get("bytes")
        digest = raw.get("sha256")
        if not isinstance(relative_path, str) or not relative_path:
            raise IdentityFreezeContractError("report_manifest_relative_path_invalid")
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise IdentityFreezeContractError("report_manifest_relative_path_unsafe")
        if relative_path in seen:
            raise IdentityFreezeContractError("report_manifest_relative_path_duplicate")
        if type(size) is not int or size < 1:
            raise IdentityFreezeContractError("report_manifest_file_bytes_invalid")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise IdentityFreezeContractError("report_manifest_file_sha256_invalid")

        file_path = root.joinpath(*pure_path.parts)
        try:
            resolved_file = file_path.resolve(strict=True)
            resolved_file.relative_to(root)
        except (OSError, ValueError) as exc:
            raise IdentityFreezeContractError(
                "report_manifest_file_unreadable"
            ) from exc
        if not resolved_file.is_file():
            raise IdentityFreezeContractError("report_manifest_member_not_file")
        if resolved_file.stat().st_size != size:
            raise IdentityFreezeContractError("report_manifest_file_bytes_mismatch")
        if _file_sha256(resolved_file) != digest:
            raise IdentityFreezeContractError("report_manifest_file_sha256_mismatch")

        seen.add(relative_path)
        aggregate_rows.append((relative_path, size, digest))
        entries.append((relative_path, size, digest, resolved_file))

    if [row[0] for row in aggregate_rows] != sorted(seen):
        raise IdentityFreezeContractError("report_manifest_files_not_sorted")
    actual_members = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual_members != seen:
        raise IdentityFreezeContractError("report_manifest_filesystem_set_mismatch")
    if manifest.get("file_count") != len(entries):
        raise IdentityFreezeContractError("report_manifest_file_count_mismatch")
    total_bytes = sum(row[1] for row in aggregate_rows)
    if manifest.get("total_bytes") != total_bytes:
        raise IdentityFreezeContractError("report_manifest_total_bytes_mismatch")
    aggregate_hash = _manifest_lf_hash(aggregate_rows)
    if manifest.get("file_manifest_lf_sha256") != aggregate_hash:
        raise IdentityFreezeContractError("report_manifest_aggregate_sha256_mismatch")

    return ValidatedArchive(
        cutoff=manifest_cutoff,
        manifest_sha256=_file_sha256(manifest_path),
        file_manifest_lf_sha256=aggregate_hash,
        file_count=len(entries),
        total_bytes=total_bytes,
        entries=tuple(entries),
    )


def _report_page_info(payload: Any) -> tuple[bool, dict[str, Any]]:
    try:
        main = payload["data"]["search"]["dynamic"]["components"]["main"]
    except (KeyError, TypeError) as exc:
        raise IdentityFreezeContractError(
            "search_report_page_info_missing"
        ) from exc
    if not isinstance(main, dict) or not isinstance(main.get("pageInfo"), dict):
        raise IdentityFreezeContractError("search_report_page_info_invalid")
    page_info = main["pageInfo"]
    if not isinstance(page_info.get("hasNextPage"), bool):
        raise IdentityFreezeContractError("search_report_has_next_page_invalid")
    return page_info["hasNextPage"], main


def _strict_semantic_row(row: dict[str, Any]) -> tuple[str, datetime]:
    post_id = _normalize_post_id(
        row.get("id"), error="search_semantic_post_id_invalid"
    )
    permalink = row.get("permalink")
    match = PERMALINK_RE.search(permalink) if isinstance(permalink, str) else None
    if match is None:
        raise IdentityFreezeContractError("search_semantic_permalink_invalid")
    permalink_id = _normalize_post_id(
        match.group(1), error="search_semantic_permalink_id_invalid"
    )
    if permalink_id != post_id:
        raise IdentityFreezeContractError("search_semantic_permalink_id_mismatch")
    created_at = _parse_datetime(
        row.get("createdAt"), error="search_semantic_created_at_invalid"
    )

    parsed = _discovery_post_from_row(row, "tikhub_dynamic_search")
    if (
        parsed.post_id != post_id
        or parsed.created_at_utc != created_at
        or not parsed.source_url
    ):
        raise IdentityFreezeContractError("search_semantic_strict_parse_mismatch")
    return post_id, created_at


def _validate_search_report(
    path: Path,
    *,
    report_sha256: str,
    cutoff: datetime,
) -> SearchPage:
    report = _load_json(path, error="search_report_unreadable")
    if not isinstance(report, dict):
        raise IdentityFreezeContractError("search_report_invalid")
    schema = report.get("schema_version")
    if schema not in SEARCH_REPORT_SCHEMAS:
        raise IdentityFreezeContractError("search_report_schema_invalid")
    expected_name = (
        "search-lane-probe.json"
        if schema == "reddit_voc_search_lane_probe_v1"
        else "search-continuation-probe.json"
    )
    if path.name != expected_name or report.get("endpoint") != FETCH_DYNAMIC_SEARCH:
        raise IdentityFreezeContractError("search_report_endpoint_contract_invalid")
    if report.get("http_status") != 200:
        raise IdentityFreezeContractError("search_report_http_status_invalid")
    if report.get("response_validation") != "passed":
        raise IdentityFreezeContractError("search_report_response_validation_failed")
    if report.get("provider_attempt_made") is not True:
        raise IdentityFreezeContractError("search_report_provider_attempt_missing")
    for boundary in ("live_send", "production_merge", "git_push", "dingtalk"):
        if report.get(boundary) is not False:
            raise IdentityFreezeContractError(
                f"search_report_{boundary}_boundary_invalid"
            )

    captured_at = _parse_datetime(
        report.get("captured_at_utc"), error="search_report_captured_at_invalid"
    )
    if captured_at > cutoff:
        raise IdentityFreezeContractError("search_report_after_freeze_cutoff")
    lane_index = report.get("lane_index")
    if type(lane_index) is not int or lane_index < 1:
        raise IdentityFreezeContractError("search_report_lane_index_invalid")
    if schema == "reddit_voc_search_lane_probe_v1":
        continuation_depth = 0
    else:
        continuation_depth = report.get("continuation_depth")
        if type(continuation_depth) is not int or continuation_depth < 1:
            raise IdentityFreezeContractError(
                "search_report_continuation_depth_invalid"
            )
    term = report.get("term")
    if not isinstance(term, str) or not term:
        raise IdentityFreezeContractError("search_report_term_invalid")
    term_sha256 = sha256(term.encode("utf-8")).hexdigest()

    payload = report.get("payload")
    if not isinstance(payload, dict):
        raise IdentityFreezeContractError("search_report_payload_missing")
    payload_sha256 = report.get("payload_sha256")
    if not isinstance(payload_sha256, str) or SHA256_RE.fullmatch(payload_sha256) is None:
        raise IdentityFreezeContractError("search_report_payload_sha256_invalid")
    if sha256(canonical_bytes(payload)).hexdigest() != payload_sha256:
        raise IdentityFreezeContractError("search_report_payload_sha256_mismatch")
    has_next_page, _main = _report_page_info(payload)

    semantic_rows: list[tuple[str, datetime]] = []
    profile_rows_excluded = 0
    quarantined_reason: str | None = None
    try:
        records = _strict_dynamic_search_post_records(payload)
    except TikHubDiscoveryShapeError as exc:
        post_ids = report.get("post_ids")
        if (
            str(exc) == "TikHub dynamic search children are missing"
            and post_ids == []
            and report.get("parsed_post_count") == 0
            and report.get("unique_post_count") == 0
        ):
            records = []
            quarantined_reason = "post_ids_zero_children_missing"
        else:
            raise IdentityFreezeContractError(
                "search_report_strict_parser_failed"
            ) from exc

    for wrapper_typename, row in records:
        if wrapper_typename not in _STRICT_DISCOVERY_CONTENT_TYPENAMES:
            raise IdentityFreezeContractError("search_wrapper_typename_invalid")
        row_typename = row.get("__typename")
        if row_typename == "ProfilePost":
            profile_rows_excluded += 1
            continue
        if row_typename != "SubredditPost":
            raise IdentityFreezeContractError("search_row_typename_unreviewed")
        semantic_rows.append(_strict_semantic_row(row))

    return SearchPage(
        lane_index=lane_index,
        continuation_depth=continuation_depth,
        term_sha256=term_sha256,
        has_next_page=has_next_page,
        report_sha256=report_sha256,
        semantic_rows=tuple(semantic_rows),
        profile_rows_excluded=profile_rows_excluded,
        quarantined_reason=quarantined_reason,
    )


def _load_identity_set(
    inventory: dict[str, Any], *, set_id: str
) -> set[str]:
    raw_sets = inventory.get("identity_sets")
    if not isinstance(raw_sets, list):
        raise IdentityFreezeContractError("baseline_identity_sets_missing")
    matches = [
        row
        for row in raw_sets
        if isinstance(row, dict) and row.get("set_id") == set_id
    ]
    if len(matches) != 1:
        raise IdentityFreezeContractError("baseline_identity_set_not_unique")
    selected = matches[0]
    raw_ids = selected.get("post_ids")
    if not isinstance(raw_ids, list):
        raise IdentityFreezeContractError("baseline_identity_post_ids_invalid")
    normalized = [
        _normalize_post_id(value, error="baseline_identity_post_id_invalid")
        for value in raw_ids
    ]
    values = set(normalized)
    if len(values) != len(normalized):
        raise IdentityFreezeContractError("baseline_identity_post_ids_duplicate")
    if selected.get("count") != len(values):
        raise IdentityFreezeContractError("baseline_identity_count_mismatch")
    if selected.get("sha256") != identity_hash(values):
        raise IdentityFreezeContractError("baseline_identity_sha256_mismatch")
    return values


def _load_site_ids(site_posts_path: Path) -> set[str]:
    raw = _load_json(site_posts_path, error="site_posts_unreadable")
    if not isinstance(raw, list):
        raise IdentityFreezeContractError("site_posts_invalid")
    normalized: list[str] = []
    for row in raw:
        if not isinstance(row, dict):
            raise IdentityFreezeContractError("site_post_row_invalid")
        normalized.append(
            _normalize_post_id(
                row.get("post_id") or row.get("reddit_id"),
                error="site_post_id_invalid",
            )
        )
    values = set(normalized)
    if len(values) != len(normalized):
        raise IdentityFreezeContractError("site_post_ids_duplicate")
    return values


def _identity_set(set_id: str, values: set[str]) -> dict[str, object]:
    ordered = sorted(values)
    return {
        "set_id": set_id,
        "count": len(ordered),
        "lf_sha256": identity_hash(ordered),
        "post_ids": ordered,
    }


def build_identity_freeze(
    reports_root: Path,
    report_manifest_path: Path,
    baseline_inventory_path: Path,
    site_posts_path: Path,
    *,
    materialized_set_id: str,
    baseline_semantic_set_id: str,
    target_start_utc: str,
    target_end_utc: str,
    manifest_cutoff_utc: str,
    search_cutoff_utc: str,
) -> dict[str, Any]:
    archive = validate_report_archive(
        reports_root,
        report_manifest_path,
        expected_manifest_cutoff_utc=manifest_cutoff_utc,
    )
    search_cutoff = _parse_datetime(
        search_cutoff_utc, error="expected_search_cutoff_invalid"
    )
    if search_cutoff < archive.cutoff:
        raise IdentityFreezeContractError("search_cutoff_before_manifest_cutoff")
    target_start = _parse_datetime(
        target_start_utc, error="target_window_start_invalid"
    )
    target_end = _parse_datetime(target_end_utc, error="target_window_end_invalid")
    if target_start > target_end:
        raise IdentityFreezeContractError("target_window_order_invalid")

    baseline_inventory = _load_json(
        baseline_inventory_path, error="baseline_inventory_unreadable"
    )
    if not isinstance(baseline_inventory, dict):
        raise IdentityFreezeContractError("baseline_inventory_invalid")
    baseline_window = baseline_inventory.get("target_window_utc")
    if not isinstance(baseline_window, dict):
        raise IdentityFreezeContractError("baseline_target_window_missing")
    baseline_start = _parse_datetime(
        baseline_window.get("start"), error="baseline_target_window_start_invalid"
    )
    baseline_end = _parse_datetime(
        baseline_window.get("end"), error="baseline_target_window_end_invalid"
    )
    if baseline_start != target_start or baseline_end != target_end:
        raise IdentityFreezeContractError("baseline_target_window_mismatch")

    materialized = _load_identity_set(
        baseline_inventory, set_id=materialized_set_id
    )
    baseline_semantic = _load_identity_set(
        baseline_inventory, set_id=baseline_semantic_set_id
    )
    site_ids = _load_site_ids(site_posts_path)

    search_entries = [
        entry for entry in archive.entries if Path(entry[0]).name in SEARCH_REPORT_NAMES
    ]
    if not search_entries:
        raise IdentityFreezeContractError("search_reports_missing")
    pages = [
        _validate_search_report(
            path,
            report_sha256=report_sha256,
            cutoff=search_cutoff,
        )
        for _relative, _size, report_sha256, path in search_entries
    ]

    by_lane: dict[int, list[SearchPage]] = {}
    for page in pages:
        by_lane.setdefault(page.lane_index, []).append(page)
    coverage_ledger: list[dict[str, object]] = []
    for lane_index, lane_pages in sorted(by_lane.items()):
        ordered = sorted(lane_pages, key=lambda value: value.continuation_depth)
        depths = [value.continuation_depth for value in ordered]
        if depths != list(range(depths[-1] + 1)):
            raise IdentityFreezeContractError("search_lane_depth_sequence_invalid")
        term_hashes = {value.term_sha256 for value in ordered}
        if len(term_hashes) != 1:
            raise IdentityFreezeContractError("search_lane_term_changed")
        latest = ordered[-1]
        coverage_ledger.append(
            {
                "lane_index": lane_index,
                "term_sha256": latest.term_sha256,
                "report_count": len(ordered),
                "max_continuation_depth": latest.continuation_depth,
                "latest_has_next_page": latest.has_next_page,
                "terminal": not latest.has_next_page,
                "debt": latest.has_next_page,
            }
        )

    v2_created_at: dict[str, datetime] = {}
    for page in pages:
        for post_id, created_at in page.semantic_rows:
            previous = v2_created_at.setdefault(post_id, created_at)
            if previous != created_at:
                raise IdentityFreezeContractError(
                    "search_semantic_created_at_conflict"
                )
    v2_within_window = {
        post_id
        for post_id, created_at in v2_created_at.items()
        if target_start <= created_at < target_end
    }
    v2_outside_window = set(v2_created_at) - v2_within_window

    semantic = baseline_semantic | v2_within_window
    discovery_only = semantic - materialized
    remote_union = semantic | materialized
    global_known = remote_union | site_ids
    net_new_vs_site = remote_union - site_ids

    if discovery_only != semantic - materialized:
        raise IdentityFreezeContractError("discovery_only_set_relation_failed")
    if remote_union != semantic | materialized:
        raise IdentityFreezeContractError("remote_union_set_relation_failed")
    if global_known != remote_union | site_ids:
        raise IdentityFreezeContractError("global_known_set_relation_failed")

    quarantine = [
        {
            "lane_index": page.lane_index,
            "continuation_depth": page.continuation_depth,
            "report_sha256": page.report_sha256,
            "reason": page.quarantined_reason,
        }
        for page in pages
        if page.quarantined_reason is not None
    ]
    identity_sets = [
        _identity_set("semantic", semantic),
        _identity_set("materialized", materialized),
        _identity_set("discovery_only", discovery_only),
        _identity_set("remote_union", remote_union),
        _identity_set("global_known", global_known),
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "freeze_cutoff_utc": _iso_utc(search_cutoff),
        "target_window_utc": {
            "start": _iso_utc(target_start),
            "end": _iso_utc(target_end),
            "interval": "[start,end)",
        },
        "scope": "private_identity_only_no_body_no_comment_no_author_no_term",
        "source_validation": {
            "report_manifest_sha256": archive.manifest_sha256,
            "archive_manifest_cutoff_utc": _iso_utc(archive.cutoff),
            "file_manifest_lf_sha256": archive.file_manifest_lf_sha256,
            "manifest_file_count": archive.file_count,
            "manifest_total_bytes": archive.total_bytes,
            "all_manifest_files_bytes_sha256_verified": True,
            "manifest_aggregate_verified": True,
            "search_report_count": len(pages),
            "search_report_quarantine_count": len(quarantine),
            "baseline_inventory_sha256": _file_sha256(baseline_inventory_path),
            "site_posts_sha256": _file_sha256(site_posts_path),
        },
        "search_semantics": {
            "strict_dynamic_search_parser_reused": True,
            "accepted_wrapper_typenames": sorted(
                _STRICT_DISCOVERY_CONTENT_TYPENAMES
            ),
            "accepted_row_typename": "SubredditPost",
            "v2_unique_strict_post_count_all_dates": len(v2_created_at),
            "v2_unique_strict_post_count_within_window": len(v2_within_window),
            "v2_unique_strict_post_count_outside_window": len(v2_outside_window),
            "profile_post_rows_excluded": sum(
                page.profile_rows_excluded for page in pages
            ),
            "baseline_semantic_count": len(baseline_semantic),
            "v2_overlap_baseline_semantic_count": len(
                v2_within_window & baseline_semantic
            ),
        },
        "quarantine": quarantine,
        "coverage_ledger": coverage_ledger,
        "coverage_summary": {
            "lane_count": len(coverage_ledger),
            "terminal_lane_count": sum(
                row["terminal"] is True for row in coverage_ledger
            ),
            "debt_lane_count": sum(row["debt"] is True for row in coverage_ledger),
        },
        "identity_sets": identity_sets,
        "current_site": {
            "count": len(site_ids),
            "lf_sha256": identity_hash(site_ids),
        },
        "net_new_vs_site": {
            "count": len(net_new_vs_site),
            "lf_sha256": identity_hash(net_new_vs_site),
        },
        "set_relations": {
            "semantic_equals_baseline_union_v2_within_window": semantic
            == baseline_semantic | v2_within_window,
            "discovery_only_equals_semantic_minus_materialized": discovery_only
            == semantic - materialized,
            "remote_union_equals_semantic_union_materialized": remote_union
            == semantic | materialized,
            "global_known_equals_remote_union_union_site": global_known
            == remote_union | site_ids,
            "net_new_equals_remote_union_minus_site": net_new_vs_site
            == remote_union - site_ids,
        },
        "boundaries": {
            "provider_call": False,
            "remote_write": False,
            "database_write": False,
            "production_merge": False,
            "live_send": False,
            "deployment": False,
        },
    }


def write_identity_freeze(snapshot: dict[str, Any], output_path: Path) -> str:
    payload = canonical_bytes(snapshot) + b"\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    descriptor = os.open(
        temporary_path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
        os.chmod(output_path, 0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return sha256(payload).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reports-root",
        type=Path,
        default=root
        / "data/imports/tencent_v2_reports_20260715/private/reports",
    )
    parser.add_argument(
        "--report-manifest",
        type=Path,
        default=root
        / "data/imports/tencent_v2_reports_20260715/private/report-file-manifest.json",
    )
    parser.add_argument(
        "--baseline-inventory",
        type=Path,
        default=root
        / "tmp/reddit-full-inventory-20260715/remote-reddit-identity-inventory-final.json",
    )
    parser.add_argument(
        "--site-posts",
        type=Path,
        default=root / "data/processed/reddit_voc_site_snapshot_20260714/posts.json",
    )
    parser.add_argument(
        "--materialized-set-id",
        default="remote_all_materialized_sqlite",
    )
    parser.add_argument(
        "--baseline-semantic-set-id",
        default="remote_semantic_primary_within_window",
    )
    parser.add_argument("--target-start-utc", default="2024-12-31T16:00:00Z")
    parser.add_argument("--target-end-utc", default="2026-07-15T16:00:00Z")
    parser.add_argument(
        "--manifest-cutoff-utc", default="2026-07-15T04:15:20.212680Z"
    )
    parser.add_argument(
        "--search-cutoff-utc", default="2026-07-15T04:15:20.214394Z"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    snapshot = build_identity_freeze(
        args.reports_root,
        args.report_manifest,
        args.baseline_inventory,
        args.site_posts,
        materialized_set_id=args.materialized_set_id,
        baseline_semantic_set_id=args.baseline_semantic_set_id,
        target_start_utc=args.target_start_utc,
        target_end_utc=args.target_end_utc,
        manifest_cutoff_utc=args.manifest_cutoff_utc,
        search_cutoff_utc=args.search_cutoff_utc,
    )
    digest = write_identity_freeze(snapshot, args.output)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "output_sha256": digest,
                "output_mode": "0600",
                "identity_counts": {
                    row["set_id"]: row["count"]
                    for row in snapshot["identity_sets"]
                },
                "net_new_vs_site": snapshot["net_new_vs_site"]["count"],
                "quarantine_count": len(snapshot["quarantine"]),
                "debt_lane_count": snapshot["coverage_summary"][
                    "debt_lane_count"
                ],
                "boundaries": snapshot["boundaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
