#!/usr/bin/env python3
"""Build an exact identity-only overlap audit for local and Task 37 sources."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import sqlite3
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
WINDOW_START = datetime(2025, 1, 1, tzinfo=timezone.utc)

SNAPSHOT_DIR = ROOT / "data/processed/reddit_voc_site_snapshot_20260714"
HISTORICAL_DB = (
    ROOT
    / "data/backfill/backfill_momcozy_20250101_20260711/reddit_voc_backfill.sqlite3"
)
PRODUCTION_IDENTITY = (
    ROOT
    / "data/imports/tencent_production_20260714/production-identity-snapshot.json"
)
TASK37_IDENTITY = OUT / "task37-identity-snapshot.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def has_source(row: dict[str, Any], source_kind: str) -> bool:
    if source_kind in row.get("source_kinds", []):
        return True
    return any(
        occurrence.get("source_kind") == source_kind
        for occurrence in row.get("source_occurrences", [])
    )


def unique_by(rows: list[dict[str, str]], key: str, source: str) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row[key]
        if value in indexed:
            raise RuntimeError(f"duplicate {key} in {source}: {value}")
        indexed[value] = row
    return indexed


def historical_source() -> tuple[list[dict[str, str]], list[dict[str, str]], str]:
    uri = f"file:{HISTORICAL_DB}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    posts = [
        {"post_id": post_id, "created_at_utc": created_at_utc}
        for post_id, created_at_utc in connection.execute(
            "SELECT post_id, created_at_utc FROM reddit_threads ORDER BY post_id"
        )
    ]
    comments = [
        {
            "comment_id": comment_id,
            "post_id": post_id,
            "created_at_utc": created_at_utc,
        }
        for comment_id, post_id, created_at_utc in connection.execute(
            "SELECT comment_id, post_id, created_at_utc "
            "FROM reddit_comments ORDER BY comment_id"
        )
    ]
    connection.close()
    return posts, comments, integrity


def source_profile(
    *,
    posts: list[dict[str, str]],
    comments: list[dict[str, str]],
    source: str,
) -> dict[str, Any]:
    posts_by_id = unique_by(posts, "post_id", source)
    comments_by_id = unique_by(comments, "comment_id", source)
    linked_comments = {
        comment_id: row
        for comment_id, row in comments_by_id.items()
        if row["post_id"] in posts_by_id
    }
    orphan_comments = {
        comment_id: row
        for comment_id, row in comments_by_id.items()
        if row["post_id"] not in posts_by_id
    }
    requested_posts = {
        post_id: row
        for post_id, row in posts_by_id.items()
        if parse_utc(row["created_at_utc"]) >= WINDOW_START
    }
    requested_comments = {
        comment_id: row
        for comment_id, row in linked_comments.items()
        if row["post_id"] in requested_posts
    }
    return {
        "posts_by_id": posts_by_id,
        "comments_by_id": comments_by_id,
        "linked_comments": linked_comments,
        "orphan_comments": orphan_comments,
        "requested_posts": requested_posts,
        "requested_comments": requested_comments,
    }


def public_counts(profile: dict[str, Any]) -> dict[str, Any]:
    posts = profile["posts_by_id"]
    comments = profile["comments_by_id"]
    requested_posts = profile["requested_posts"]
    requested_comments = profile["requested_comments"]
    return {
        "all_time": {
            "posts": len(posts),
            "stored_comments": len(comments),
            "linked_comments": len(profile["linked_comments"]),
            "orphan_comments": len(profile["orphan_comments"]),
            "post_min_utc": min(row["created_at_utc"] for row in posts.values()),
            "post_max_utc": max(row["created_at_utc"] for row in posts.values()),
            "comment_min_utc": min(row["created_at_utc"] for row in comments.values()),
            "comment_max_utc": max(row["created_at_utc"] for row in comments.values()),
        },
        "requested_window": {
            "posts": len(requested_posts),
            "linked_comments": len(requested_comments),
        },
    }


def overlap_row(
    left_name: str,
    right_name: str,
    entity: str,
    left: set[str],
    right: set[str],
) -> dict[str, Any]:
    intersection = left & right
    union = left | right
    return {
        "left_source": left_name,
        "right_source": right_name,
        "entity": entity,
        "left_count": len(left),
        "right_count": len(right),
        "overlap_count": len(intersection),
        "left_only_count": len(left - right),
        "right_only_count": len(right - left),
        "union_count": len(union),
        "left_overlap_rate": round(len(intersection) / len(left), 6) if left else 0.0,
        "right_overlap_rate": round(len(intersection) / len(right), 6) if right else 0.0,
        "jaccard": round(len(intersection) / len(union), 6) if union else 1.0,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    public_posts = load_json(SNAPSHOT_DIR / "posts.json")
    public_comments = load_json(SNAPSHOT_DIR / "comments.json")
    production = load_json(PRODUCTION_IDENTITY)
    task37 = load_json(TASK37_IDENTITY)
    historical_posts, historical_comments, historical_integrity = historical_source()

    imported_posts = [
        {
            "post_id": row["post_id"],
            "created_at_utc": row["created_at_utc"],
        }
        for row in public_posts
        if has_source(row, "imported_archive")
    ]
    imported_comments = [
        {
            "comment_id": row["comment_id"],
            "post_id": row["post_id"],
            "created_at_utc": row["created_at_utc"],
        }
        for row in public_comments
        if has_source(row, "imported_archive")
    ]
    local_posts = [
        {"post_id": row["post_id"], "created_at_utc": row["created_at_utc"]}
        for row in public_posts
    ]
    local_comments = [
        {
            "comment_id": row["comment_id"],
            "post_id": row["post_id"],
            "created_at_utc": row["created_at_utc"],
        }
        for row in public_comments
    ]
    production_posts = [
        {"post_id": row["post_id"], "created_at_utc": row["created_at_utc"]}
        for row in production["posts"]
    ]
    production_comments = [
        {
            "comment_id": row["comment_id"],
            "post_id": row["post_id"],
            "created_at_utc": row["created_at_utc"],
        }
        for row in production["comments"]
    ]

    source_rows = {
        "historical_canonical": (historical_posts, historical_comments),
        "imported_archive": (imported_posts, imported_comments),
        "tencent_production_primary": (production_posts, production_comments),
        "local_canonical_union": (local_posts, local_comments),
        "task37_remote_staging": (task37["posts"], task37["comments"]),
    }
    profiles = {
        name: source_profile(posts=rows[0], comments=rows[1], source=name)
        for name, rows in source_rows.items()
    }

    overlap_rows: list[dict[str, Any]] = []
    for left_name, right_name in combinations(profiles, 2):
        left = profiles[left_name]
        right = profiles[right_name]
        overlap_rows.append(
            overlap_row(
                left_name,
                right_name,
                "posts",
                set(left["requested_posts"]),
                set(right["requested_posts"]),
            )
        )
        overlap_rows.append(
            overlap_row(
                left_name,
                right_name,
                "linked_comments",
                set(left["requested_comments"]),
                set(right["requested_comments"]),
            )
        )

    local_profile = profiles["local_canonical_union"]
    task37_profile = profiles["task37_remote_staging"]
    local_posts_set = set(local_profile["requested_posts"])
    local_comments_set = set(local_profile["requested_comments"])
    task37_posts_set = set(task37_profile["requested_posts"])
    task37_comments_set = set(task37_profile["requested_comments"])
    task37_increment = {
        "local_canonical_union": {
            "posts": len(local_posts_set),
            "linked_comments": len(local_comments_set),
        },
        "task37_remote_staging": {
            "posts": len(task37_posts_set),
            "linked_comments": len(task37_comments_set),
        },
        "overlap": {
            "posts": len(local_posts_set & task37_posts_set),
            "linked_comments": len(local_comments_set & task37_comments_set),
        },
        "task37_only": {
            "posts": len(task37_posts_set - local_posts_set),
            "linked_comments": len(task37_comments_set - local_comments_set),
        },
        "local_only": {
            "posts": len(local_posts_set - task37_posts_set),
            "linked_comments": len(local_comments_set - task37_comments_set),
        },
        "potential_deduplicated_union": {
            "posts": len(local_posts_set | task37_posts_set),
            "linked_comments": len(local_comments_set | task37_comments_set),
        },
    }

    historical_profile = profiles["historical_canonical"]
    archive_profile = profiles["imported_archive"]
    production_profile = profiles["tencent_production_primary"]
    production_orphans = production_profile["orphan_comments"]
    task37_all_comments = task37_profile["comments_by_id"]
    production_missing_parent_ids = {
        row["post_id"] for row in production_orphans.values()
    }
    recoverable_parent_ids = production_missing_parent_ids & set(
        task37_profile["posts_by_id"]
    )
    orphan_comment_ids_in_task37 = set(production_orphans) & set(task37_all_comments)
    orphan_comment_ids_with_recoverable_parent = {
        comment_id
        for comment_id, row in production_orphans.items()
        if row["post_id"] in recoverable_parent_ids
    }
    parent_only_recovery_comment_ids = (
        orphan_comment_ids_with_recoverable_parent - orphan_comment_ids_in_task37
    )
    remaining_unlinked_orphan_comment_ids = (
        set(production_orphans) - orphan_comment_ids_with_recoverable_parent
    )
    production_orphan_recovery = {
        "production_orphan_comments": len(production_orphans),
        "distinct_missing_parent_post_ids": len(production_missing_parent_ids),
        "missing_parent_post_ids_present_in_task37": len(recoverable_parent_ids),
        "orphan_comment_ids_present_in_task37": len(orphan_comment_ids_in_task37),
        "production_only_orphan_comment_ids_with_parent_present_in_task37": len(
            parent_only_recovery_comment_ids
        ),
        "structurally_recoverable_after_task37_parent_insert": len(
            orphan_comment_ids_with_recoverable_parent
        ),
        "remaining_unlinked_production_comment_ids": len(
            remaining_unlinked_orphan_comment_ids
        ),
        "interpretation": (
            "Task 37 contains six exact orphan comment IDs and the missing parent "
            "post for eight production orphan comments in total. The two additional "
            "production-only comments become structurally linkable after that parent "
            "is inserted; this is recovery evidence, not merge authorization."
        ),
    }

    task37_only_post_ids = task37_posts_set - local_posts_set
    local_only_post_ids = local_posts_set - task37_posts_set
    task37_only_comment_ids = task37_comments_set - local_comments_set
    local_only_comment_ids = local_comments_set - task37_comments_set
    task37_only_comments = [
        {
            **task37_profile["requested_comments"][comment_id],
            "parent_action": (
                "insert_new_parent_post"
                if task37_profile["requested_comments"][comment_id]["post_id"]
                in task37_only_post_ids
                else "attach_to_existing_local_post"
            ),
        }
        for comment_id in sorted(task37_only_comment_ids)
    ]
    local_only_comments = [
        {
            **local_profile["requested_comments"][comment_id],
            "parent_state": (
                "local_only_post"
                if local_profile["requested_comments"][comment_id]["post_id"]
                in local_only_post_ids
                else "overlap_post"
            ),
        }
        for comment_id in sorted(local_only_comment_ids)
    ]
    merge_plan = {
        "schema_version": "momcozy_cross_source_readonly_merge_plan_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "identity_plan_frozen_not_executable",
        "source_database": {
            "task37_path": task37["source"]["database_path"],
            "task37_sha256": task37["source"]["database_sha256"],
            "local_canonical_snapshot_posts_sha256": file_sha(
                SNAPSHOT_DIR / "posts.json"
            ),
            "local_canonical_snapshot_comments_sha256": file_sha(
                SNAPSHOT_DIR / "comments.json"
            ),
        },
        "window": {
            "post_created_at_utc_gte": "2025-01-01T00:00:00Z",
            "comment_scope": "comments linked to an in-window post_id",
        },
        "actions": {
            "insert_task37_only_posts": 223,
            "insert_task37_only_comments": 1202,
            "insert_comments_with_new_parent_posts": sum(
                row["parent_action"] == "insert_new_parent_post"
                for row in task37_only_comments
            ),
            "attach_new_comments_to_existing_local_posts": sum(
                row["parent_action"] == "attach_to_existing_local_post"
                for row in task37_only_comments
            ),
            "preserve_local_only_posts": 109,
            "preserve_local_only_comments": 1505,
            "preserve_comments_on_local_only_posts": sum(
                row["parent_state"] == "local_only_post"
                for row in local_only_comments
            ),
            "preserve_comments_on_overlap_posts": sum(
                row["parent_state"] == "overlap_post"
                for row in local_only_comments
            ),
            "recoverable_production_orphan_comments": 8,
            "recoverable_by_exact_task37_comment_id": 6,
            "recoverable_by_task37_parent_only": 2,
            "remaining_unlinked_production_comments": 10,
        },
        "task37_only_posts": [
            task37_profile["requested_posts"][post_id]
            for post_id in sorted(task37_only_post_ids)
        ],
        "task37_only_comments": task37_only_comments,
        "local_only_posts_to_preserve": [
            local_profile["requested_posts"][post_id]
            for post_id in sorted(local_only_post_ids)
        ],
        "local_only_comments_to_preserve": local_only_comments,
        "production_orphan_recovery_candidates": [
            {
                **production_orphans[comment_id],
                "recovery_basis": (
                    "exact_comment_id_and_parent_in_task37"
                    if comment_id in orphan_comment_ids_in_task37
                    else "production_only_comment_parent_in_task37"
                ),
            }
            for comment_id in sorted(orphan_comment_ids_with_recoverable_parent)
        ],
        "production_orphans_remaining_unlinked": [
            production_orphans[comment_id]
            for comment_id in sorted(remaining_unlinked_orphan_comment_ids)
        ],
        "checks": {
            "task37_only_posts_223": len(task37_only_post_ids) == 223,
            "task37_only_comments_1202": len(task37_only_comment_ids) == 1202,
            "task37_new_comments_with_new_parent_1168": sum(
                row["parent_action"] == "insert_new_parent_post"
                for row in task37_only_comments
            )
            == 1168,
            "task37_new_comments_on_existing_post_34": sum(
                row["parent_action"] == "attach_to_existing_local_post"
                for row in task37_only_comments
            )
            == 34,
            "local_only_posts_109": len(local_only_post_ids) == 109,
            "local_only_comments_1505": len(local_only_comment_ids) == 1505,
            "local_comments_on_local_only_posts_1484": sum(
                row["parent_state"] == "local_only_post"
                for row in local_only_comments
            )
            == 1484,
            "local_comments_on_overlap_posts_21": sum(
                row["parent_state"] == "overlap_post"
                for row in local_only_comments
            )
            == 21,
            "all_task37_insert_comments_have_union_parent": all(
                row["post_id"] in (task37_posts_set | local_posts_set)
                for row in task37_only_comments
            ),
            "recovery_candidates_6": len(orphan_comment_ids_in_task37) == 6,
            "parent_only_recovery_candidates_2": len(
                parent_only_recovery_comment_ids
            )
            == 2,
            "structurally_recoverable_orphans_8": len(
                orphan_comment_ids_with_recoverable_parent
            )
            == 8,
            "remaining_orphans_10": len(remaining_unlinked_orphan_comment_ids)
            == 10,
        },
        "boundaries": {
            "identity_only": True,
            "executable": False,
            "local_isolated_staging_created": False,
            "production_merge_authorized": False,
            "production_unchanged": True,
            "provider_call": False,
            "provider_attempt_made": False,
            "remote_write": False,
            "git_push": False,
            "live_send": False,
        },
    }
    if not all(merge_plan["checks"].values()):
        raise RuntimeError(
            [
                name
                for name, passed in merge_plan["checks"].items()
                if not passed
            ]
        )

    checks = {
        "historical_integrity_ok": historical_integrity == "ok",
        "historical_counts_48_1894": (
            len(historical_profile["posts_by_id"]) == 48
            and len(historical_profile["comments_by_id"]) == 1894
        ),
        "archive_counts_136_4153": (
            len(archive_profile["posts_by_id"]) == 136
            and len(archive_profile["comments_by_id"]) == 4153
        ),
        "production_counts_85_414": (
            len(production_profile["posts_by_id"]) == 85
            and len(production_profile["comments_by_id"]) == 414
        ),
        "production_orphan_comments_18": len(production_profile["orphan_comments"]) == 18,
        "local_canonical_counts_221_4549": (
            len(local_profile["posts_by_id"]) == 221
            and len(local_profile["comments_by_id"]) == 4549
        ),
        "local_requested_counts_187_3528": (
            len(local_posts_set) == 187 and len(local_comments_set) == 3528
        ),
        "task37_counts_301_3225": (
            len(task37_profile["posts_by_id"]) == 301
            and len(task37_profile["comments_by_id"]) == 3225
        ),
        "task37_identity_snapshot_checks_passed": all(task37["checks"].values()),
        "production_missing_parent_post_ids_4": len(production_missing_parent_ids) == 4,
        "task37_recovers_one_missing_parent_post": len(
            recoverable_parent_ids
        )
        == 1,
        "task37_contains_six_production_orphan_comment_ids": len(
            orphan_comment_ids_in_task37
        )
        == 6,
        "task37_orphan_comment_links_are_consistent": all(
            task37_all_comments[comment_id]["post_id"]
            == production_orphans[comment_id]["post_id"]
            for comment_id in orphan_comment_ids_in_task37
        ),
        "task37_parent_structurally_recovers_eight_orphans": len(
            orphan_comment_ids_with_recoverable_parent
        )
        == 8,
        "two_recoverable_orphans_are_production_only": len(
            parent_only_recovery_comment_ids
        )
        == 2,
        "ten_orphans_still_lack_parent_evidence": len(
            remaining_unlinked_orphan_comment_ids
        )
        == 10,
        "historical_posts_subset_archive": set(historical_profile["posts_by_id"]).issubset(
            archive_profile["posts_by_id"]
        ),
        "historical_comments_subset_archive": set(
            historical_profile["comments_by_id"]
        ).issubset(archive_profile["comments_by_id"]),
        "local_union_posts_exact": set(local_profile["posts_by_id"]) == (
            set(archive_profile["posts_by_id"]) | set(production_profile["posts_by_id"])
        ),
        "local_union_linked_comments_exact": set(local_profile["comments_by_id"]) == (
            set(archive_profile["comments_by_id"])
            | set(production_profile["linked_comments"])
        ),
        "task37_window_start_respected": min(
            parse_utc(row["created_at_utc"])
            for row in task37_profile["posts_by_id"].values()
        )
        >= WINDOW_START,
    }
    if not all(checks.values()):
        raise RuntimeError([name for name, passed in checks.items() if not passed])

    audit = {
        "schema_version": "momcozy_cross_source_identity_overlap_audit_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "grain": {
            "posts": "unique Reddit post_id with post created_at_utc >= 2025-01-01T00:00:00Z",
            "comments": "unique Reddit comment_id linked to an in-window source post_id; comment timestamp is not used as the window filter",
            "production_orphans": "18 production comments without a captured parent post are excluded from requested-window linked-comment counts",
        },
        "source_counts": {
            name: public_counts(profile) for name, profile in profiles.items()
        },
        "pairwise_requested_window_overlap": overlap_rows,
        "task37_increment_vs_local_canonical_union": task37_increment,
        "production_orphan_recovery_from_task37": production_orphan_recovery,
        "checks": checks,
        "source_sha256": {
            "historical_database": file_sha(HISTORICAL_DB),
            "public_posts_snapshot": file_sha(SNAPSHOT_DIR / "posts.json"),
            "public_comments_snapshot": file_sha(SNAPSHOT_DIR / "comments.json"),
            "production_identity_snapshot": file_sha(PRODUCTION_IDENTITY),
            "task37_identity_snapshot": file_sha(TASK37_IDENTITY),
        },
        "boundaries": {
            "identity_only": True,
            "raw_content_exported": False,
            "usernames_exported": False,
            "provider_call": False,
            "provider_attempt_made": False,
            "database_write": "local-analysis-output-only",
            "remote_write": False,
            "production_unchanged": True,
            "live_send": False,
        },
    }
    json_path = OUT / "cross-source-overlap-audit.json"
    csv_path = OUT / "cross-source-overlap-matrix.csv"
    merge_plan_path = OUT / "cross-source-readonly-merge-plan.json"
    write_json(json_path, audit)
    write_json(merge_plan_path, merge_plan)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(overlap_rows[0]))
        writer.writeheader()
        writer.writerows(overlap_rows)

    print(
        json.dumps(
            {
                "checks": len(checks),
                "task37_increment": task37_increment,
                "outputs": {
                    json_path.name: file_sha(json_path),
                    csv_path.name: file_sha(csv_path),
                    merge_plan_path.name: file_sha(merge_plan_path),
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
