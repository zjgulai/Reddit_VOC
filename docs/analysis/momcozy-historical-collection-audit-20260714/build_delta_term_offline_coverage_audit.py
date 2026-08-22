#!/usr/bin/env python3
"""Audit V2 delta-term lexical coverage without exporting remote content."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any
import unicodedata


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
WINDOW_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
PROFILE = ROOT / "config/backfill/momcozy-search-profile-v2-candidate-20260714.json"
LOCAL_POSTS = ROOT / "data/processed/reddit_voc_site_snapshot_20260714/posts.json"
LOCAL_COMMENTS = ROOT / "data/processed/reddit_voc_site_snapshot_20260714/comments.json"
OVERLAP_AUDIT = OUT / "cross-source-overlap-audit.json"
REMOTE_DB = (
    "/opt/reddit-voc-staging/"
    "task37-2560998311fc176c366c70086ba3a58f6b76ee073dba855ea9a0eb1c5f9a94b1/"
    "backfill_momcozy_20250101_20260711/reddit_voc_backfill.sqlite3"
)
EXPECTED_REMOTE_DB_SHA256 = (
    "8356981018466164fe1f84953bd1e1e19010114817dd9689a31b996d9cc51497"
)
EXPECTED_PROFILE_SHA256 = (
    "38706378f42c6648fe43bb50f60947863816363d65714f16a3092f40d91b604d"
)

CLASS_PRIORITY = {
    "zero_existing_lexical_evidence": 0,
    "comment_only_existing_lexical_evidence": 1,
    "post_only_existing_lexical_evidence": 2,
    "post_and_comment_existing_lexical_evidence": 3,
}
GROUP_PRIORITY = {
    "official_catalog_aliases": 0,
    "momcozy_model_gap": 1,
    "owner_alias_gap": 2,
    "governed_competitors": 3,
    "category_anchors": 4,
}


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


def dequote(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        return stripped[1:-1]
    return stripped


def lexical_normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = lexical_normalize(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {lexical_normalize(text)} "


def local_coverage(terms: list[str]) -> dict[str, Any]:
    posts = [
        row
        for row in load_json(LOCAL_POSTS)
        if parse_utc(row["created_at_utc"]) >= WINDOW_START
    ]
    post_ids = {row["post_id"] for row in posts}
    comments = [
        row for row in load_json(LOCAL_COMMENTS) if row["post_id"] in post_ids
    ]
    results: dict[str, Any] = {}
    for query_term in terms:
        phrase = dequote(query_term)
        matched_posts = sorted(
            row["post_id"]
            for row in posts
            if contains_phrase(f'{row.get("title", "")}\n{row.get("content", "")}', phrase)
        )
        matched_comments = sorted(
            (
                {
                    "comment_id": row["comment_id"],
                    "post_id": row["post_id"],
                }
                for row in comments
                if contains_phrase(row.get("body", ""), phrase)
            ),
            key=lambda row: row["comment_id"],
        )
        results[query_term] = {
            "post_ids": matched_posts,
            "comments": matched_comments,
        }
    return {
        "profile": {
            "posts": len(posts),
            "linked_comments": len(comments),
            "post_min_utc": min(row["created_at_utc"] for row in posts),
            "post_max_utc": max(row["created_at_utc"] for row in posts),
        },
        "results": results,
    }


def remote_query_source(terms: list[str]) -> str:
    return f'''\
import json
import re
import sqlite3
import unicodedata

path = {REMOTE_DB!r}
terms = {terms!r}
window_start = "2025-01-01"

def dequote(value):
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\\\"'":
        return stripped[1:-1]
    return stripped

def lexical_normalize(value):
    folded = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())

def contains_phrase(text, phrase):
    normalized_phrase = lexical_normalize(phrase)
    if not normalized_phrase:
        return False
    return f" {{normalized_phrase}} " in f" {{lexical_normalize(text)}} "

connection = sqlite3.connect(f"file:{{path}}?mode=ro&immutable=1", uri=True)
connection.execute("PRAGMA query_only=ON")
integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
post_columns = [row[1] for row in connection.execute("PRAGMA table_info(reddit_threads)")]
comment_columns = [row[1] for row in connection.execute("PRAGMA table_info(reddit_comments)")]
posts = [
    {{"post_id": post_id, "created_at_utc": created_at_utc, "title": title, "selftext": selftext}}
    for post_id, created_at_utc, title, selftext in connection.execute(
        "SELECT post_id, created_at_utc, title, selftext FROM reddit_threads "
        "WHERE created_at_utc >= ? ORDER BY post_id",
        (window_start,),
    )
]
post_ids = {{row["post_id"] for row in posts}}
comments = [
    {{"comment_id": comment_id, "post_id": post_id, "body": body}}
    for comment_id, post_id, body in connection.execute(
        "SELECT comment_id, post_id, body FROM reddit_comments ORDER BY comment_id"
    )
    if post_id in post_ids
]
results = {{}}
for query_term in terms:
    phrase = dequote(query_term)
    matched_posts = sorted(
        row["post_id"]
        for row in posts
        if contains_phrase(row["title"] + "\\n" + row["selftext"], phrase)
    )
    matched_comments = sorted(
        (
            {{"comment_id": row["comment_id"], "post_id": row["post_id"]}}
            for row in comments
            if contains_phrase(row["body"], phrase)
        ),
        key=lambda row: row["comment_id"],
    )
    results[query_term] = {{"post_ids": matched_posts, "comments": matched_comments}}
print(json.dumps({{
    "profile": {{
        "posts": len(posts),
        "linked_comments": len(comments),
        "post_min_utc": min(row["created_at_utc"] for row in posts),
        "post_max_utc": max(row["created_at_utc"] for row in posts),
        "quick_check": integrity,
        "post_columns_required": all(column in post_columns for column in ["post_id", "created_at_utc", "title", "selftext"]),
        "comment_columns_required": all(column in comment_columns for column in ["comment_id", "post_id", "body"]),
        "query_only": connection.execute("PRAGMA query_only").fetchone()[0] == 1,
    }},
    "results": results,
}}, ensure_ascii=False, separators=(",", ":")))
'''


def run_ssh(
    *, remote: str, ssh_key: Path, command: str, stdin: str | None = None
) -> str:
    completed = subprocess.run(
        [
            "ssh",
            "-i",
            str(ssh_key),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            remote,
            command,
        ],
        input=stdin,
        capture_output=True,
        check=True,
        text=True,
        timeout=120,
    )
    return completed.stdout


def remote_coverage(*, terms: list[str], remote: str, ssh_key: Path) -> tuple[dict[str, Any], str, str]:
    hash_output = run_ssh(
        remote=remote,
        ssh_key=ssh_key,
        command=f"sudo -n sha256sum -- {REMOTE_DB}",
    )
    remote_db_sha256 = hash_output.split(maxsplit=1)[0]
    if remote_db_sha256 != EXPECTED_REMOTE_DB_SHA256:
        raise RuntimeError(
            f"Task 37 DB hash mismatch: {remote_db_sha256} != {EXPECTED_REMOTE_DB_SHA256}"
        )
    query = remote_query_source(terms)
    raw = run_ssh(
        remote=remote,
        ssh_key=ssh_key,
        command="sudo -n python3 -",
        stdin=query,
    )
    return json.loads(raw), remote_db_sha256, sha256(query.encode("utf-8")).hexdigest()


def classify(post_count: int, comment_count: int) -> str:
    if post_count == 0 and comment_count == 0:
        return "zero_existing_lexical_evidence"
    if post_count == 0:
        return "comment_only_existing_lexical_evidence"
    if comment_count == 0:
        return "post_only_existing_lexical_evidence"
    return "post_and_comment_existing_lexical_evidence"


def merge_term(
    *,
    query_term: str,
    group: str,
    local: dict[str, Any],
    remote: dict[str, Any],
) -> dict[str, Any]:
    local_posts = set(local["post_ids"])
    remote_posts = set(remote["post_ids"])
    local_comments = {row["comment_id"]: row["post_id"] for row in local["comments"]}
    remote_comments = {row["comment_id"]: row["post_id"] for row in remote["comments"]}
    for comment_id in set(local_comments) & set(remote_comments):
        if local_comments[comment_id] != remote_comments[comment_id]:
            raise RuntimeError(f"comment parent mismatch: {comment_id}")
    merged_comments = {**local_comments, **remote_comments}
    union_posts = local_posts | remote_posts
    comment_parent_posts = set(merged_comments.values())
    evidence_parent_posts = union_posts | comment_parent_posts
    coverage_class = classify(len(union_posts), len(merged_comments))
    priority = CLASS_PRIORITY[coverage_class]
    return {
        "term": query_term,
        "normalized_phrase": lexical_normalize(dequote(query_term)),
        "group": group,
        "coverage_class": coverage_class,
        "provider_lane_status": "unexecuted_offline_lexical_evidence_only",
        "provider_discovery_still_required": True,
        "priority_tier": f"P{priority}",
        "local": {
            "post_surface_matches": len(local_posts),
            "comment_matches": len(local_comments),
            "comment_parent_posts": len(set(local_comments.values())),
        },
        "task37_remote": {
            "post_surface_matches": len(remote_posts),
            "comment_matches": len(remote_comments),
            "comment_parent_posts": len(set(remote_comments.values())),
        },
        "deduplicated_union": {
            "post_surface_matches": len(union_posts),
            "comment_matches": len(merged_comments),
            "comment_parent_posts": len(comment_parent_posts),
            "evidence_parent_posts": len(evidence_parent_posts),
            "local_remote_post_overlap": len(local_posts & remote_posts),
            "local_remote_comment_overlap": len(set(local_comments) & set(remote_comments)),
        },
        "identities": {
            "post_ids": sorted(union_posts),
            "comment_ids": sorted(merged_comments),
            "comment_parent_post_ids": sorted(comment_parent_posts),
        },
    }


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    coverage_classes = {
        name: sum(row["coverage_class"] == name for row in rows)
        for name in CLASS_PRIORITY
    }
    by_group: dict[str, Any] = {}
    for group in GROUP_PRIORITY:
        group_rows = [row for row in rows if row["group"] == group]
        by_group[group] = {
            "terms": len(group_rows),
            "zero_existing_lexical_evidence": sum(
                row["coverage_class"] == "zero_existing_lexical_evidence"
                for row in group_rows
            ),
            "comment_only_existing_lexical_evidence": sum(
                row["coverage_class"] == "comment_only_existing_lexical_evidence"
                for row in group_rows
            ),
            "post_surface_covered_terms": sum(
                row["deduplicated_union"]["post_surface_matches"] > 0
                for row in group_rows
            ),
            "comment_covered_terms": sum(
                row["deduplicated_union"]["comment_matches"] > 0
                for row in group_rows
            ),
        }
    all_post_ids = {
        post_id for row in rows for post_id in row["identities"]["post_ids"]
    }
    all_comment_ids = {
        comment_id for row in rows for comment_id in row["identities"]["comment_ids"]
    }
    all_evidence_parent_ids = {
        post_id
        for row in rows
        for post_id in [
            *row["identities"]["post_ids"],
            *row["identities"]["comment_parent_post_ids"],
        ]
    }
    return {
        "terms": len(rows),
        "coverage_classes": coverage_classes,
        "terms_with_post_surface_evidence": sum(
            row["deduplicated_union"]["post_surface_matches"] > 0 for row in rows
        ),
        "terms_with_comment_evidence": sum(
            row["deduplicated_union"]["comment_matches"] > 0 for row in rows
        ),
        "distinct_matching_post_ids": len(all_post_ids),
        "distinct_matching_comment_ids": len(all_comment_ids),
        "distinct_evidence_parent_post_ids": len(all_evidence_parent_ids),
        "by_group": by_group,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "priority_rank",
        "priority_tier",
        "group",
        "term",
        "normalized_phrase",
        "coverage_class",
        "post_surface_matches",
        "comment_matches",
        "comment_parent_posts",
        "evidence_parent_posts",
        "provider_lane_status",
        "provider_discovery_still_required",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for rank, row in enumerate(rows, start=1):
            union = row["deduplicated_union"]
            writer.writerow(
                {
                    "priority_rank": rank,
                    "priority_tier": row["priority_tier"],
                    "group": row["group"],
                    "term": row["term"],
                    "normalized_phrase": row["normalized_phrase"],
                    "coverage_class": row["coverage_class"],
                    "post_surface_matches": union["post_surface_matches"],
                    "comment_matches": union["comment_matches"],
                    "comment_parent_posts": union["comment_parent_posts"],
                    "evidence_parent_posts": union["evidence_parent_posts"],
                    "provider_lane_status": row["provider_lane_status"],
                    "provider_discovery_still_required": row[
                        "provider_discovery_still_required"
                    ],
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="ubuntu@101.34.52.232")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=OUT / "delta-term-offline-coverage-audit.json",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=OUT / "delta-term-offline-coverage.csv",
    )
    args = parser.parse_args()
    if not args.ssh_key.is_file():
        raise FileNotFoundError(args.ssh_key)

    profile = load_json(PROFILE)
    profile_sha256 = file_sha(PROFILE)
    if profile_sha256 != EXPECTED_PROFILE_SHA256:
        raise RuntimeError(
            f"profile hash mismatch: {profile_sha256} != {EXPECTED_PROFILE_SHA256}"
        )
    terms = profile["delta_terms"]
    term_group: dict[str, str] = {}
    for group, candidates in profile["candidate_groups"].items():
        for term in candidates:
            if term not in terms:
                continue
            if term in term_group:
                raise RuntimeError(f"delta term appears in multiple groups: {term}")
            term_group[term] = group

    local = local_coverage(terms)
    remote, remote_db_sha256, remote_query_sha256 = remote_coverage(
        terms=terms,
        remote=args.remote,
        ssh_key=args.ssh_key,
    )
    rows = [
        merge_term(
            query_term=term,
            group=term_group[term],
            local=local["results"][term],
            remote=remote["results"][term],
        )
        for term in terms
    ]
    rows.sort(
        key=lambda row: (
            CLASS_PRIORITY[row["coverage_class"]],
            GROUP_PRIORITY[row["group"]],
            row["term"].casefold(),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["priority_rank"] = rank

    aggregate = aggregate_rows(rows)
    overlap = load_json(OVERLAP_AUDIT)[
        "task37_increment_vs_local_canonical_union"
    ]
    expected_union = overlap["potential_deduplicated_union"]
    checks = {
        "profile_sha256_matches": profile_sha256 == EXPECTED_PROFILE_SHA256,
        "delta_terms_69": len(terms) == 69,
        "delta_terms_unique": len(terms) == len(set(terms)),
        "every_delta_term_has_one_group": set(terms) == set(term_group),
        "local_requested_posts_187": local["profile"]["posts"] == 187,
        "local_linked_comments_3528": local["profile"]["linked_comments"] == 3528,
        "remote_database_sha256_matches": remote_db_sha256
        == EXPECTED_REMOTE_DB_SHA256,
        "remote_query_only": remote["profile"]["query_only"],
        "remote_quick_check_ok": remote["profile"]["quick_check"] == "ok",
        "remote_required_post_columns": remote["profile"]["post_columns_required"],
        "remote_required_comment_columns": remote["profile"][
            "comment_columns_required"
        ],
        "remote_requested_posts_301": remote["profile"]["posts"] == 301,
        "remote_linked_comments_3225": remote["profile"]["linked_comments"]
        == 3225,
        "potential_union_posts_410": expected_union["posts"] == 410,
        "potential_union_comments_4730": expected_union["linked_comments"] == 4730,
        "every_term_classified": len(rows) == 69
        and all(row["coverage_class"] in CLASS_PRIORITY for row in rows),
        "no_provider_lane_marked_complete": all(
            row["provider_discovery_still_required"] for row in rows
        ),
        "remote_output_identity_and_counts_only": all(
            set(result) == {"post_ids", "comments"}
            and all(set(comment) == {"comment_id", "post_id"} for comment in result["comments"])
            for result in remote["results"].values()
        ),
    }
    if not all(checks.values()):
        raise RuntimeError([name for name, passed in checks.items() if not passed])

    result = {
        "schema_version": "momcozy_v2_delta_offline_coverage_audit_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": {
            "match_type": "unicode_nfkc_casefold_ascii_alnum_token_phrase",
            "post_surface": "title plus selftext/content",
            "comment_surface": "comment body",
            "window_rule": "post_created_at_utc >= 2025-01-01T00:00:00Z; comments linked to in-window posts",
            "interpretation": "Lexical evidence already present in collected content. It is not proof that the corresponding search lane has been exhaustively collected.",
            "priority_rule": "zero evidence, comment-only, post-only, then post-and-comment; within class official aliases, Momcozy models, owner alias, competitors, then broad categories",
        },
        "sources": {
            "profile": {
                "path": str(PROFILE.relative_to(ROOT)),
                "sha256": profile_sha256,
            },
            "local_posts": {
                "path": str(LOCAL_POSTS.relative_to(ROOT)),
                "sha256": file_sha(LOCAL_POSTS),
            },
            "local_comments": {
                "path": str(LOCAL_COMMENTS.relative_to(ROOT)),
                "sha256": file_sha(LOCAL_COMMENTS),
            },
            "task37_remote_staging": {
                "remote": args.remote,
                "database_path": REMOTE_DB,
                "database_sha256": remote_db_sha256,
                "database_mode": "sqlite_uri_mode_ro_immutable_query_only",
                "remote_query_sha256": remote_query_sha256,
                "content_exported": False,
                "usernames_exported": False,
            },
            "cross_source_overlap_audit": {
                "path": str(OVERLAP_AUDIT.relative_to(ROOT)),
                "sha256": file_sha(OVERLAP_AUDIT),
            },
        },
        "source_profiles": {
            "local": local["profile"],
            "task37_remote": remote["profile"],
            "potential_deduplicated_union": expected_union,
        },
        "aggregate": aggregate,
        "recommended_probe_order": [
            {
                "priority_rank": row["priority_rank"],
                "priority_tier": row["priority_tier"],
                "group": row["group"],
                "term": row["term"],
                "coverage_class": row["coverage_class"],
                "evidence_parent_posts": row["deduplicated_union"][
                    "evidence_parent_posts"
                ],
                "provider_discovery_still_required": True,
            }
            for row in rows
        ],
        "rows": rows,
        "checks": checks,
        "boundaries": {
            "offline_coverage_evidence_only": True,
            "search_profile_changed": False,
            "provider_call": False,
            "provider_attempt_made": False,
            "remote_write": False,
            "remote_content_exported": False,
            "remote_usernames_exported": False,
            "database_write": "local-analysis-output-only",
            "production_unchanged": True,
            "local_product_tests_run": False,
            "live_send": False,
        },
    }
    write_json(args.json_output, result)
    write_csv(args.csv_output, rows)
    print(
        json.dumps(
            {
                "json_output": str(args.json_output),
                "csv_output": str(args.csv_output),
                "aggregate": aggregate,
                "checks_passed": sum(checks.values()),
                "checks_total": len(checks),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
