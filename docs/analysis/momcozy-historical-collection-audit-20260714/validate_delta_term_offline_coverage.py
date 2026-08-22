#!/usr/bin/env python3
"""Independently validate selected delta-term coverage and audit structure."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
AUDIT = OUT / "delta-term-offline-coverage-audit.json"
LOCAL_POSTS = ROOT / "data/processed/reddit_voc_site_snapshot_20260714/posts.json"
LOCAL_COMMENTS = ROOT / "data/processed/reddit_voc_site_snapshot_20260714/comments.json"
REMOTE_DB = (
    "/opt/reddit-voc-staging/"
    "task37-2560998311fc176c366c70086ba3a58f6b76ee073dba855ea9a0eb1c5f9a94b1/"
    "backfill_momcozy_20250101_20260711/reddit_voc_backfill.sqlite3"
)
EXPECTED_REMOTE_DB_SHA256 = (
    "8356981018466164fe1f84953bd1e1e19010114817dd9689a31b996d9cc51497"
)
WINDOW_START = "2025-01-01T00:00:00+00:00"
SPOT_TERMS = [
    '"Momcozy BM03"',
    '"Momcozy DeepClean"',
    '"Momcozy M5 Smart"',
    '"tommee tippee"',
    '"spectra"',
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dequote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


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
        timeout=90,
    )
    return completed.stdout


def local_literal_matches() -> dict[str, Any]:
    posts = [
        row for row in load_json(LOCAL_POSTS) if row["created_at_utc"] >= WINDOW_START
    ]
    post_ids = {row["post_id"] for row in posts}
    comments = [
        row for row in load_json(LOCAL_COMMENTS) if row["post_id"] in post_ids
    ]
    result: dict[str, Any] = {}
    for query_term in SPOT_TERMS:
        phrase = dequote(query_term).casefold()
        matched_posts = sorted(
            row["post_id"]
            for row in posts
            if phrase in f'{row.get("title", "")}\n{row.get("content", "")}'.casefold()
        )
        matched_comments = sorted(
            (
                {"comment_id": row["comment_id"], "post_id": row["post_id"]}
                for row in comments
                if phrase in row.get("body", "").casefold()
            ),
            key=lambda row: row["comment_id"],
        )
        result[query_term] = {
            "post_ids": matched_posts,
            "comments": matched_comments,
        }
    return result


def remote_literal_query() -> str:
    return f'''\
import json
import sqlite3

path = {REMOTE_DB!r}
terms = {SPOT_TERMS!r}
window_start = "2025-01-01"

def dequote(value):
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '\"' else value

connection = sqlite3.connect(f"file:{{path}}?mode=ro&immutable=1", uri=True)
connection.execute("PRAGMA query_only=ON")
result = {{}}
for query_term in terms:
    phrase = dequote(query_term).casefold()
    pattern = "%" + phrase + "%"
    posts = [
        row[0]
        for row in connection.execute(
            "SELECT post_id FROM reddit_threads "
            "WHERE created_at_utc >= ? AND lower(title || char(10) || selftext) LIKE ? "
            "ORDER BY post_id",
            (window_start, pattern),
        )
    ]
    comments = [
        {{"comment_id": comment_id, "post_id": post_id}}
        for comment_id, post_id in connection.execute(
            "SELECT c.comment_id, c.post_id FROM reddit_comments AS c "
            "JOIN reddit_threads AS p ON p.post_id = c.post_id "
            "WHERE p.created_at_utc >= ? AND lower(c.body) LIKE ? "
            "ORDER BY c.comment_id",
            (window_start, pattern),
        )
    ]
    result[query_term] = {{"post_ids": posts, "comments": comments}}
print(json.dumps({{
    "query_only": connection.execute("PRAGMA query_only").fetchone()[0] == 1,
    "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
    "results": result,
}}, ensure_ascii=False, separators=(",", ":")))
'''


def remote_literal_matches(
    *, remote: str, ssh_key: Path
) -> tuple[dict[str, Any], str, str]:
    hash_output = run_ssh(
        remote=remote,
        ssh_key=ssh_key,
        command=f"sudo -n sha256sum -- {REMOTE_DB}",
    )
    remote_sha256 = hash_output.split(maxsplit=1)[0]
    if remote_sha256 != EXPECTED_REMOTE_DB_SHA256:
        raise RuntimeError(
            f"Task 37 DB hash mismatch: {remote_sha256} != {EXPECTED_REMOTE_DB_SHA256}"
        )
    query = remote_literal_query()
    raw = run_ssh(
        remote=remote,
        ssh_key=ssh_key,
        command="sudo -n python3 -",
        stdin=query,
    )
    return json.loads(raw), remote_sha256, sha256(query.encode("utf-8")).hexdigest()


def counts(result: dict[str, Any]) -> dict[str, int]:
    return {
        "post_surface_matches": len(result["post_ids"]),
        "comment_matches": len(result["comments"]),
        "comment_parent_posts": len({row["post_id"] for row in result["comments"]}),
    }


def forbidden_keys(value: Any) -> set[str]:
    forbidden = {"body", "title", "selftext", "author", "username"}
    found: set[str] = set()
    if isinstance(value, dict):
        found |= forbidden & set(value)
        for child in value.values():
            found |= forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            found |= forbidden_keys(child)
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="ubuntu@101.34.52.232")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT / "delta-term-offline-coverage-validation.json",
    )
    args = parser.parse_args()
    if not args.ssh_key.is_file():
        raise FileNotFoundError(args.ssh_key)

    audit = load_json(AUDIT)
    audit_by_term = {row["term"]: row for row in audit["rows"]}
    local = local_literal_matches()
    remote, remote_db_sha256, remote_query_sha256 = remote_literal_matches(
        remote=args.remote,
        ssh_key=args.ssh_key,
    )

    spot_checks: dict[str, Any] = {}
    for term in SPOT_TERMS:
        local_counts = counts(local[term])
        remote_counts = counts(remote["results"][term])
        audit_row = audit_by_term[term]
        local_literal_superset = all(
            local_counts[field] >= audit_row["local"][field]
            for field in local_counts
        )
        remote_literal_superset = all(
            remote_counts[field] >= audit_row["task37_remote"][field]
            for field in remote_counts
        )
        spot_checks[term] = {
            "local_literal": local_counts,
            "local_audit": audit_row["local"],
            "local_match": local_counts == audit_row["local"],
            "local_literal_superset": local_literal_superset,
            "task37_remote_literal": remote_counts,
            "task37_remote_audit": audit_row["task37_remote"],
            "task37_remote_match": remote_counts == audit_row["task37_remote"],
            "task37_remote_literal_superset": remote_literal_superset,
        }

    rows = audit["rows"]
    aggregate = audit["aggregate"]
    recalculated_classes = {
        coverage_class: sum(row["coverage_class"] == coverage_class for row in rows)
        for coverage_class in aggregate["coverage_classes"]
    }
    recalculated_post_ids = {
        post_id for row in rows for post_id in row["identities"]["post_ids"]
    }
    recalculated_comment_ids = {
        comment_id for row in rows for comment_id in row["identities"]["comment_ids"]
    }
    recalculated_parent_ids = {
        post_id
        for row in rows
        for post_id in [
            *row["identities"]["post_ids"],
            *row["identities"]["comment_parent_post_ids"],
        ]
    }
    priorities = [row["priority_rank"] for row in rows]
    checks = {
        "audit_checks_passed": all(audit["checks"].values()),
        "rows_69": len(rows) == 69,
        "coverage_class_counts_recomputed": recalculated_classes
        == aggregate["coverage_classes"],
        "distinct_post_ids_recomputed": len(recalculated_post_ids)
        == aggregate["distinct_matching_post_ids"],
        "distinct_comment_ids_recomputed": len(recalculated_comment_ids)
        == aggregate["distinct_matching_comment_ids"],
        "distinct_evidence_parent_ids_recomputed": len(recalculated_parent_ids)
        == aggregate["distinct_evidence_parent_post_ids"],
        "priority_ranks_complete": priorities == list(range(1, 70)),
        "all_provider_lanes_still_required": all(
            row["provider_discovery_still_required"] for row in rows
        ),
        "top_probe_is_momcozy_bm03": rows[0]["term"] == '"Momcozy BM03"',
        "remote_database_sha256_matches": remote_db_sha256
        == EXPECTED_REMOTE_DB_SHA256,
        "remote_query_only": remote["query_only"],
        "remote_quick_check_ok": remote["quick_check"] == "ok",
        "five_literal_spot_checks_cover_token_phrase_results": all(
            check["local_literal_superset"]
            and check["task37_remote_literal_superset"]
            for check in spot_checks.values()
        ),
        "four_unambiguous_literal_spot_checks_exact": all(
            spot_checks[term]["local_match"]
            and spot_checks[term]["task37_remote_match"]
            for term in SPOT_TERMS
            if term != '"spectra"'
        ),
        "spectra_token_boundary_excludes_literal_substrings": (
            spot_checks['"spectra"']["local_literal"]["comment_matches"]
            > spot_checks['"spectra"']["local_audit"]["comment_matches"]
            and spot_checks['"spectra"']["task37_remote_literal"]["comment_matches"]
            > spot_checks['"spectra"']["task37_remote_audit"]["comment_matches"]
        ),
        "audit_contains_no_content_or_identity_keys": not forbidden_keys(audit),
        "remote_validation_output_identity_and_counts_only": not forbidden_keys(remote),
        "boundary_provider_call_false": audit["boundaries"]["provider_call"]
        is False,
        "boundary_remote_write_false": audit["boundaries"]["remote_write"]
        is False,
        "boundary_remote_content_exported_false": audit["boundaries"][
            "remote_content_exported"
        ]
        is False,
    }
    result = {
        "schema_version": "momcozy_v2_delta_offline_coverage_validation_v1",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "source": {
            "audit_path": str(AUDIT.relative_to(ROOT)),
            "audit_sha256": file_sha(AUDIT),
            "remote_database_path": REMOTE_DB,
            "remote_database_sha256": remote_db_sha256,
            "remote_query_sha256": remote_query_sha256,
            "method": "independent casefold literal substring spot-check plus identity recomputation",
        },
        "spot_checks": spot_checks,
        "recomputed": {
            "coverage_classes": recalculated_classes,
            "distinct_matching_post_ids": len(recalculated_post_ids),
            "distinct_matching_comment_ids": len(recalculated_comment_ids),
            "distinct_evidence_parent_post_ids": len(recalculated_parent_ids),
        },
        "checks": checks,
        "boundaries": {
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
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not all(checks.values()):
        raise RuntimeError([name for name, passed in checks.items() if not passed])
    print(
        json.dumps(
            {
                "output": str(args.output),
                "checks_passed": sum(checks.values()),
                "checks_total": len(checks),
                "audit_sha256": result["source"]["audit_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
