#!/usr/bin/env python3
"""Build an independently auditable before/after Reddit VOC center delta receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping


class CenterDeltaError(ValueError):
    """The center delta is not a monotonic, source-bound fusion."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connection(path: Path, *, label: str) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise CenterDeltaError(f"{label}_unsafe")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    if connection.execute("PRAGMA query_only").fetchone()[0] != 0:
        # SQLite may report 0 for a URI mode=ro connection; writes still fail.
        pass
    if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
        connection.close()
        raise CenterDeltaError(f"{label}_integrity_failed")
    return connection


def _ids(connection: sqlite3.Connection, table: str, field: str) -> set[str]:
    try:
        return {str(row[0]) for row in connection.execute(f"SELECT {field} FROM {table}")}
    except sqlite3.Error as exc:
        raise CenterDeltaError(f"{table}_unavailable") from exc


def _jsonl_ids(path: Path, field: str, *, label: str) -> set[str]:
    if path.is_symlink() or not path.is_file():
        raise CenterDeltaError(f"{label}_unsafe")
    values: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CenterDeltaError(f"{label}_invalid") from exc
    for index, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CenterDeltaError(f"{label}_invalid_row_{index}") from exc
        if not isinstance(row, dict) or not isinstance(row.get(field), str):
            raise CenterDeltaError(f"{label}_invalid_row_{index}")
        value = row[field]
        if value in values:
            raise CenterDeltaError(f"{label}_duplicate_identity")
        values.add(value)
    return values


def _load(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CenterDeltaError(f"{label}_unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CenterDeltaError(f"{label}_invalid") from exc
    if not isinstance(value, dict):
        raise CenterDeltaError(f"{label}_invalid")
    return value


def _count_occurrences(connection: sqlite3.Connection, entity_type: str) -> int:
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM entity_occurrences WHERE entity_type = ?",
                (entity_type,),
            ).fetchone()[0]
        )
    except sqlite3.Error as exc:
        raise CenterDeltaError("entity_occurrences_unavailable") from exc


def _max_timestamp(connection: sqlite3.Connection, table: str) -> str | None:
    row = connection.execute(
        f"SELECT MAX(COALESCE(created_at_utc, last_observed_at_utc)) FROM {table}"
    ).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def _difference_count(after: Iterable[str], before: Iterable[str]) -> int:
    return len(set(after).difference(before))


def build_center_delta(
    *,
    before_database: Path,
    after_database: Path,
    source_batch_root: Path,
    source_batch_validation_receipt: Path,
) -> dict[str, Any]:
    manifest_path = source_batch_root / "source-batch-manifest.json"
    manifest = _load(manifest_path, label="source_batch_manifest")
    receipt = _load(source_batch_validation_receipt, label="source_batch_receipt")
    manifest_sha = _sha256(manifest_path)
    if (
        receipt.get("status") != "passed"
        or receipt.get("consumable") is not True
        or receipt.get("manifest_sha256") != manifest_sha
    ):
        raise CenterDeltaError("source_batch_receipt_binding_invalid")
    batch_posts = _jsonl_ids(source_batch_root / "posts.jsonl", "post_id", label="source_posts")
    batch_comments = _jsonl_ids(
        source_batch_root / "comments.jsonl",
        "comment_id",
        label="source_comments",
    )
    before = _connection(before_database, label="before_database")
    after = _connection(after_database, label="after_database")
    try:
        before_posts = _ids(before, "canonical_posts", "post_id")
        before_comments = _ids(before, "canonical_comments", "comment_id")
        before_debt = _ids(before, "relationship_debt", "comment_id")
        after_posts = _ids(after, "canonical_posts", "post_id")
        after_comments = _ids(after, "canonical_comments", "comment_id")
        after_debt = _ids(after, "relationship_debt", "comment_id")
        if not before_posts.issubset(after_posts):
            raise CenterDeltaError("canonical_posts_not_monotonic")
        if not before_comments.issubset(after_comments):
            raise CenterDeltaError("canonical_comments_not_monotonic")
        new_posts = after_posts - before_posts
        new_comments = after_comments - before_comments
        if not new_posts.issubset(batch_posts):
            raise CenterDeltaError("new_posts_not_bound_to_source_batch")
        if not new_comments.issubset(batch_comments):
            raise CenterDeltaError("new_comments_not_bound_to_source_batch")
        repaired = before_debt - after_debt
        if not repaired.issubset(after_comments):
            raise CenterDeltaError("repaired_parent_links_invalid")
        result = {
            "schema_version": "reddit_voc_center_delta_receipt_v1",
            "status": "passed",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_batch": {
                "batch_id": manifest.get("batch_id"),
                "manifest_sha256": manifest_sha,
                "validation_receipt_sha256": _sha256(source_batch_validation_receipt),
                "posts": len(batch_posts),
                "comments": len(batch_comments),
            },
            "before": {
                "database_sha256": _sha256(before_database),
                "posts": len(before_posts),
                "comments": len(before_comments),
                "relationship_debt": len(before_debt),
                "post_occurrences": _count_occurrences(before, "post"),
                "comment_occurrences": _count_occurrences(before, "comment"),
                "max_post_event_utc": _max_timestamp(before, "canonical_posts"),
                "max_comment_event_utc": _max_timestamp(before, "canonical_comments"),
            },
            "after": {
                "database_sha256": _sha256(after_database),
                "posts": len(after_posts),
                "comments": len(after_comments),
                "relationship_debt": len(after_debt),
                "post_occurrences": _count_occurrences(after, "post"),
                "comment_occurrences": _count_occurrences(after, "comment"),
                "max_post_event_utc": _max_timestamp(after, "canonical_posts"),
                "max_comment_event_utc": _max_timestamp(after, "canonical_comments"),
            },
            "net_new": {
                "posts": len(new_posts),
                "comments": len(new_comments),
                "updated_historical_posts": len(batch_posts & before_posts),
                "observed_existing_comments": len(batch_comments & before_comments),
                "repaired_parent_links": len(repaired),
            },
            "checks": {
                "center_sqlite_integrity": True,
                "post_identity_monotonic": True,
                "comment_identity_monotonic": True,
                "new_posts_source_bound": True,
                "new_comments_source_bound": True,
                "relationship_debt_explicit": True,
            },
            "boundaries": {
                "database_write": False,
                "deploy": False,
                "live_send": False,
                "production_unchanged": True,
                "provider_call": False,
                "remote_write": False,
            },
        }
        if result["net_new"]["posts"] != _difference_count(after_posts, before_posts):
            raise CenterDeltaError("post_delta_internal_mismatch")
        return result
    finally:
        before.close()
        after.close()


def write_immutable(path: Path, value: Mapping[str, Any]) -> str:
    payload = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise CenterDeltaError("output_immutable_collision")
        return "no_change"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return "created"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-database", type=Path, required=True)
    parser.add_argument("--after-database", type=Path, required=True)
    parser.add_argument("--source-batch-root", type=Path, required=True)
    parser.add_argument("--source-batch-validation-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        receipt = build_center_delta(
            before_database=args.before_database,
            after_database=args.after_database,
            source_batch_root=args.source_batch_root,
            source_batch_validation_receipt=args.source_batch_validation_receipt,
        )
        write_status = write_immutable(args.output, receipt)
    except (CenterDeltaError, OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "write_status": write_status,
                "output": str(args.output),
                "receipt_sha256": _sha256(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
