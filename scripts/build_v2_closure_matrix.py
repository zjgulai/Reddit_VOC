#!/usr/bin/env python3
"""Build an evidence matrix for the V2 ticket ledger.

Why this exists
---------------
`docs/v2/TICKETS.md` has 105 tickets but no status column. Completion was
inferred from commit messages and hand-written reports, so K11 could not be
computed and "closed" meant whatever the latest report said. This script does
not decide that a ticket is done: it records the two pieces of evidence a human
can review -- the commits that name the ticket and the named tests that exist --
and leaves `owner_signoff` null.

Output is intentionally conservative:
  * `commit_referenced` means a commit subject/body contains the ticket id;
  * `named_test_present` means the test file exists and, when a node name is
    given, that node name appears in the file;
  * `formally_closed` stays 0 until an owner signs the matrix.

Usage:
  python3 scripts/build_v2_closure_matrix.py --check
  python3 scripts/build_v2_closure_matrix.py --write
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TICKETS = ROOT / "docs" / "v2" / "TICKETS.md"
DEFAULT_OUTPUT = ROOT / "docs" / "audit" / "v2-closure-matrix.json"
DEFAULT_REV = "main..HEAD"

SCHEMA = "echo_agent_v2_closure_matrix_v1"
HEADING = re.compile(r"^#### `(?P<id>L[1-6]-T\d+)`\s*(?P<title>.*)$", re.MULTILINE)
PRIORITY = re.compile(r"\*\*严重度\*\*：\s*(P[0-3])")
TEST_PATH = re.compile(r"`(tests/[^`]+?)`")
TICKET_ID = re.compile(r"\bL[1-6]-T\d+\b")
WAVE = re.compile(r"\bWave\s*([1-5])\b", re.IGNORECASE)


def _ticket_blocks(text: str) -> list[dict[str, Any]]:
    matches = list(HEADING.finditer(text))
    tickets: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end():end]
        priority = PRIORITY.search(block)
        wave = WAVE.search(block)
        named_tests = sorted(set(TEST_PATH.findall(block)))
        tickets.append(
            {
                "ticket_id": match.group("id"),
                "lane": match.group("id").split("-")[0],
                "title": match.group("title").strip(),
                "priority": priority.group(1) if priority else None,
                "wave": f"W{wave.group(1)}" if wave else None,
                "named_tests": named_tests,
            }
        )
    return tickets


def _commit_map(commits: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    references: dict[str, list[str]] = {}
    for commit_hash, text in commits:
        for ticket_id in set(TICKET_ID.findall(text)):
            references.setdefault(ticket_id, []).append(commit_hash[:12])
    for hashes in references.values():
        hashes.sort()
    return references


def _test_status(named_tests: list[str], tests_root: Path) -> tuple[str, list[dict[str, str]]]:
    details: list[dict[str, str]] = []
    present = 0
    missing = 0
    for node in named_tests:
        path_text, _, node_name = node.partition("::")
        path = tests_root / path_text
        exists = path.is_file()
        node_found = False
        if exists and node_name:
            try:
                node_found = node_name in path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                node_found = False
        if exists and (not node_name or node_found):
            present += 1
            status = "present"
        elif exists:
            missing += 1
            status = "node_missing"
        else:
            missing += 1
            status = "file_missing"
        details.append({"node": node, "status": status})
    if not named_tests:
        return "none", details
    if missing == 0:
        return "present", details
    return "partial" if present else "missing", details


def build_matrix(
    tickets_text: str,
    commits: Iterable[tuple[str, str]],
    tests_root: Path,
) -> dict[str, Any]:
    tickets = _ticket_blocks(tickets_text)
    references = _commit_map(commits)
    rows: list[dict[str, Any]] = []
    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        test_status, test_details = _test_status(ticket["named_tests"], tests_root)
        commit_refs = references.get(ticket_id, [])
        if commit_refs and test_status == "present":
            evidence = "commit+named_test"
        elif commit_refs:
            evidence = "commit_only"
        elif test_status == "present":
            evidence = "named_test_only"
        else:
            evidence = "none"
        rows.append(
            {
                **ticket,
                "commit_references": commit_refs,
                "test_status": test_status,
                "test_details": test_details,
                "evidence_status": evidence,
                "owner_signoff": None,
            }
        )
    summary = {
        "total": len(rows),
        "commit_referenced": sum(1 for row in rows if row["commit_references"]),
        "named_test_present": sum(1 for row in rows if row["test_status"] == "present"),
        "named_test_missing": sum(
            1 for row in rows if row["test_status"] in {"missing", "partial"}
        ),
        "evidence_complete": sum(
            1 for row in rows if row["evidence_status"] == "commit+named_test"
        ),
        "no_evidence": sum(1 for row in rows if row["evidence_status"] == "none"),
        "formally_closed": 0,
    }
    return {
        "schema_version": SCHEMA,
        "source": "docs/v2/TICKETS.md",
        "note": (
            "Evidence only. owner_signoff stays null; formally_closed is not "
            "inferred from commits or tests."
        ),
        "summary": summary,
        "tickets": rows,
    }


def git_commits(repo_root: Path, rev: str) -> list[tuple[str, str]]:
    completed = subprocess.run(
        ["git", "log", rev, "--pretty=format:%H%x00%s%x00%b%x00%x00"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"git log failed: {completed.stderr.strip()}")
    commits: list[tuple[str, str]] = []
    for record in completed.stdout.split("\x00\x00"):
        parts = record.strip("\x00").split("\x00")
        if not parts or not parts[0].strip():
            continue
        commit_hash = parts[0].strip()
        subject = parts[1] if len(parts) > 1 else ""
        body = parts[2] if len(parts) > 2 else ""
        commits.append((commit_hash, f"{subject}\n{body}"))
    return commits


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the V2 closure evidence matrix")
    parser.add_argument("--tickets", type=Path, default=DEFAULT_TICKETS)
    parser.add_argument("--tests-root", type=Path, default=ROOT)
    parser.add_argument("--rev", default=DEFAULT_REV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--write", action="store_true", help="write the matrix JSON")
    parser.add_argument("--check", action="store_true", help="print the summary only")
    args = parser.parse_args()

    text = args.tickets.read_text(encoding="utf-8")
    matrix = build_matrix(text, git_commits(ROOT, args.rev), args.tests_root)
    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(matrix, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(matrix["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())