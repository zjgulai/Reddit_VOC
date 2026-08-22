#!/usr/bin/env python3
"""Read-only Reddit identity reconciliation for the 2026-07-15 inventory freeze.

The script emits aggregate counts and LF-normalized SHA-256 hashes only. It never
prints post IDs, comment IDs, text, authors, credentials, or remote paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


POST_ID_RE = re.compile(r"^[a-z0-9]+$")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_id(value: Any, prefix: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix) :]
    return normalized if POST_ID_RE.fullmatch(normalized) else None


def normalized_ids(values: Iterable[Any], prefix: str) -> set[str]:
    result = {normalize_id(value, prefix) for value in values}
    result.discard(None)
    return result  # type: ignore[return-value]


def lf_sha256(values: set[str]) -> str:
    payload = "".join(f"{value}\n" for value in sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def manifest_sets(
    manifest: dict[str, Any], list_key: str, id_key: str, prefix: str
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for item in manifest[list_key]:
        values = normalized_ids(item[id_key], prefix)
        if len(values) != item["count"]:
            raise ValueError(f"count mismatch for {item['set_id']}")
        if lf_sha256(values) != item["sha256"]:
            raise ValueError(f"hash mismatch for {item['set_id']}")
        result[item["set_id"]] = values
    return result


def reconcile(root: Path) -> dict[str, Any]:
    base_posts_raw = load_json(
        root / "data/processed/reddit_voc_site_snapshot_20260714/posts.json"
    )
    base_posts = normalized_ids(
        (row.get("post_id") or row.get("reddit_id") for row in base_posts_raw),
        "t3_",
    )

    task37 = load_json(
        root
        / "data/imports/tencent_production_20260715/task37-identity-snapshot.json"
    )
    task37_posts = normalized_ids(
        (row.get("post_id") or row.get("reddit_id") for row in task37["posts"]),
        "t3_",
    )

    remote_post_manifest = load_json(
        root
        / "tmp/reddit-full-inventory-20260715/remote-reddit-identity-inventory-final.json"
    )
    post_sets = manifest_sets(
        remote_post_manifest, "identity_sets", "post_ids", "t3_"
    )
    materialized = post_sets["remote_all_materialized_sqlite"]
    semantic = post_sets["remote_semantic_primary_within_window"]
    discovery_only = post_sets[
        "remote_unmaterialized_semantic_primary_within_window"
    ]
    remote_union = post_sets[
        "remote_materialized_plus_semantic_primary_within_window"
    ]
    daily_increment_after_task37 = materialized - (base_posts | task37_posts)

    base_comments_raw = load_json(
        root / "data/processed/reddit_voc_site_snapshot_20260714/comments.json"
    )
    base_linked_comments = normalized_ids(
        (
            row.get("comment_id") or row.get("reddit_id")
            for row in base_comments_raw
        ),
        "t1_",
    )
    quarantine_raw = load_json(
        root / "data/processed/reddit_voc_site_snapshot_20260714/quarantine.json"
    )
    base_quarantine_comments = normalized_ids(
        (
            row.get("comment_id") or row.get("reddit_id")
            for row in quarantine_raw
        ),
        "t1_",
    )
    base_stored_comments = base_linked_comments | base_quarantine_comments

    remote_comment_manifest = load_json(
        root
        / "tmp/reddit-full-inventory-20260715/remote-reddit-comment-identity-inventory-final.json"
    )
    comment_sets = manifest_sets(
        remote_comment_manifest,
        "comment_identity_sets",
        "comment_ids",
        "t1_",
    )
    remote_comments = comment_sets["remote_all_valid_reddit_comment_ids"]
    remote_linked_comments = comment_sets[
        "remote_comments_linked_to_materialized_posts"
    ]
    remote_orphan_comments = comment_sets[
        "remote_comments_orphan_from_materialized_posts"
    ]
    task37_comments = comment_sets["remote_task37_db_comments"]
    daily_comments = comment_sets["remote_daily_db_comments"]

    if discovery_only != semantic - materialized:
        raise ValueError("discovery-only set relation failed")
    if remote_union != semantic | materialized:
        raise ValueError("remote union set relation failed")
    if remote_comments != remote_linked_comments | remote_orphan_comments:
        raise ValueError("remote comment partition failed")
    if remote_linked_comments & remote_orphan_comments:
        raise ValueError("remote linked/orphan sets overlap")

    return {
        "posts": {
            "current_site": len(base_posts),
            "task37_materialized": len(task37_posts),
            "task37_overlap_site": len(task37_posts & base_posts),
            "task37_net_new": len(task37_posts - base_posts),
            "local_confirmed_union": len(base_posts | task37_posts),
            "remote_materialized": len(materialized),
            "remote_materialized_overlap_site": len(materialized & base_posts),
            "remote_materialized_net_new": len(materialized - base_posts),
            "daily_materialized_net_new_after_task37": len(
                daily_increment_after_task37
            ),
            "semantic_target_window": len(semantic),
            "semantic_overlap_materialized": len(semantic & materialized),
            "discovery_only": len(discovery_only),
            "remote_union": len(remote_union),
            "remote_union_overlap_site": len(remote_union & base_posts),
            "net_new_vs_site": len(remote_union - base_posts),
            "global_known_union": len(base_posts | remote_union),
            "hashes": {
                "current_site_lf_sha256": lf_sha256(base_posts),
                "remote_materialized_lf_sha256": lf_sha256(materialized),
                "semantic_target_window_lf_sha256": lf_sha256(semantic),
                "discovery_only_lf_sha256": lf_sha256(discovery_only),
                "remote_union_lf_sha256": lf_sha256(remote_union),
                "global_union_lf_sha256": lf_sha256(base_posts | remote_union),
            },
        },
        "comments": {
            "current_site_linked": len(base_linked_comments),
            "current_site_quarantine": len(base_quarantine_comments),
            "current_site_stored": len(base_stored_comments),
            "remote_valid": len(remote_comments),
            "remote_linked": len(remote_linked_comments),
            "remote_orphan": len(remote_orphan_comments),
            "remote_overlap_site_stored": len(
                remote_comments & base_stored_comments
            ),
            "remote_net_new_vs_site_stored": len(
                remote_comments - base_stored_comments
            ),
            "global_stored_union": len(base_stored_comments | remote_comments),
            "new_orphan_vs_site_stored": len(
                remote_orphan_comments - base_stored_comments
            ),
            "remote_orphan_overlap_site_quarantine": len(
                remote_orphan_comments & base_quarantine_comments
            ),
            "task37": len(task37_comments),
            "task37_overlap_site_stored": len(
                task37_comments & base_stored_comments
            ),
            "task37_net_new_vs_site_stored": len(
                task37_comments - base_stored_comments
            ),
            "daily": len(daily_comments),
            "daily_overlap_site_stored": len(daily_comments & base_stored_comments),
            "daily_net_new_vs_site_stored": len(
                daily_comments - base_stored_comments
            ),
            "hashes": {
                "current_site_stored_lf_sha256": lf_sha256(
                    base_stored_comments
                ),
                "remote_valid_lf_sha256": lf_sha256(remote_comments),
                "global_union_lf_sha256": lf_sha256(
                    base_stored_comments | remote_comments
                ),
            },
        },
        "validation": {
            "remote_post_manifest_sets_checked": len(post_sets),
            "remote_comment_manifest_sets_checked": len(comment_sets),
            "set_relations": "passed",
            "output_contains_raw_ids": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Reddit_VOC repository root",
    )
    args = parser.parse_args()
    result = reconcile(args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
