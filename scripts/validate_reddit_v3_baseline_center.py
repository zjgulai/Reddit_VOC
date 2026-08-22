#!/usr/bin/env python3
"""Independently reconcile V3 canonical identities with one local V2 center."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reddit_voc.report_contracts import canonical_json_bytes  # noqa: E402
from reddit_voc.v2_center import BOUNDARIES, V2CenterError, V2CenterStore  # noqa: E402
from reddit_voc.v3_baseline_source_batch import (  # noqa: E402
    V3BaselineSourceBatchError,
    load_validated_v3_canonical_snapshot,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fullname(value: object, prefix: str) -> str:
    text = str(value or "")
    return text if text.startswith(prefix) else prefix + text


def _write_immutable(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise V2CenterError("baseline reconciliation receipt immutable collision")
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


def validate(
    *,
    canonical_root: Path,
    canonical_validation_receipt: Path,
    bridge_receipt: Path,
    center_database: Path,
) -> dict[str, object]:
    manifest, _canonical_receipt, documents = load_validated_v3_canonical_snapshot(
        canonical_root, canonical_validation_receipt
    )
    try:
        bridge_payload = bridge_receipt.read_bytes()
        bridge = json.loads(bridge_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2CenterError("V3 baseline bridge receipt is invalid") from exc
    if (
        not isinstance(bridge, dict)
        or bridge_payload != canonical_json_bytes(bridge) + b"\n"
        or bridge.get("schema_version") != "reddit_voc_v3_baseline_bridge_receipt_v1"
        or bridge.get("status") != "passed"
        or bridge.get("source_dataset_id") != manifest.get("dataset_id")
    ):
        raise V2CenterError("V3 baseline bridge receipt is invalid")
    expected_posts = {
        _fullname(row.get("canonical_reddit_id"), "t3_")
        for row in documents["posts.jsonl"]
    }
    expected_comments = {
        _fullname(row.get("canonical_reddit_id"), "t1_")
        for name in ("comments.jsonl", "quarantine.jsonl")
        for row in documents[name]
    }
    store = V2CenterStore(center_database, read_only=True)
    with store.connect() as connection:
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        observed_posts = {
            str(row[0]) for row in connection.execute("SELECT post_id FROM canonical_posts")
        }
        observed_comments = {
            str(row[0]) for row in connection.execute("SELECT comment_id FROM canonical_comments")
        }
        bridge_row = connection.execute(
            "SELECT * FROM baseline_bridges WHERE source_dataset_id=?",
            (manifest["dataset_id"],),
        ).fetchone()
        state_counts = {
            "linked_comments": int(
                connection.execute(
                    "SELECT COUNT(*) FROM comment_parent_edges WHERE relationship_status='linked'"
                ).fetchone()[0]
            ),
            "quarantined_comments": int(
                connection.execute("SELECT COUNT(*) FROM comment_quarantine").fetchone()[0]
            ),
            "unresolved_parent_comments": int(
                connection.execute("SELECT COUNT(*) FROM relationship_debt").fetchone()[0]
            ),
        }
    missing_posts = expected_posts - observed_posts
    unexpected_posts = observed_posts - expected_posts
    missing_comments = expected_comments - observed_comments
    unexpected_comments = observed_comments - expected_comments
    expected_counts = manifest["canonical_counts"]
    if (
        quick_check != "ok"
        or missing_posts
        or unexpected_posts
        or missing_comments
        or unexpected_comments
        or bridge_row is None
        or bridge_row["receipt_sha256"] != hashlib.sha256(bridge_payload).hexdigest()
        or state_counts["linked_comments"] != expected_counts["linked_comments"]
        or state_counts["quarantined_comments"] != expected_counts["quarantined_comments"]
        or state_counts["unresolved_parent_comments"]
        != expected_counts["unresolved_parent_comments"]
    ):
        raise V2CenterError("V3 baseline center zero-diff reconciliation failed")
    return {
        "boundaries": dict(BOUNDARIES),
        "bridge_receipt_sha256": _sha(bridge_receipt),
        "canonical_manifest_sha256": _sha(canonical_root / "manifest.json"),
        "canonical_validation_receipt_sha256": _sha(canonical_validation_receipt),
        "center_state_sha256": store.state_sha256(),
        "checks": {
            "bridge_center_binding": True,
            "comment_identity_zero_diff": True,
            "post_identity_zero_diff": True,
            "sqlite_integrity": True,
            "structural_state_conservation": True,
        },
        "counts": {
            **expected_counts,
            "comment_identity_missing": 0,
            "comment_identity_unexpected": 0,
            "post_identity_missing": 0,
            "post_identity_unexpected": 0,
        },
        "schema_version": "reddit_voc_v3_baseline_center_validation_receipt_v1",
        "source_dataset_id": manifest["dataset_id"],
        "status": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--canonical-validation-receipt", type=Path, required=True)
    parser.add_argument("--bridge-receipt", type=Path, required=True)
    parser.add_argument("--center-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = validate(
            canonical_root=args.canonical_root,
            canonical_validation_receipt=args.canonical_validation_receipt,
            bridge_receipt=args.bridge_receipt,
            center_database=args.center_database,
        )
        payload = canonical_json_bytes(value) + b"\n"
        write_status = _write_immutable(args.output, payload)
    except (OSError, sqlite3.Error, ValueError, V2CenterError, V3BaselineSourceBatchError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc), "status": "failed"}, sort_keys=True) + "\n")
        return 1
    sys.stdout.write(
        json.dumps(
            {
                "receipt_sha256": hashlib.sha256(payload).hexdigest(),
                "status": "passed",
                "write_status": write_status,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
