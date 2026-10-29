from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reddit_voc.v2_center_canonical_export import (
    CenterCanonicalExportError,
    _canonical_comment_state,
    _read_previous_bundle,
)


CANONICAL_DATA_FILES = {
    "comments.jsonl",
    "conflict-ledger.jsonl",
    "posts.jsonl",
    "provenance-ledger.jsonl",
    "quarantine.jsonl",
    "unresolved-parent-ledger.jsonl",
}


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _write_previous_bundle(root: Path, schema_version: str) -> None:
    root.mkdir()
    files: dict[str, dict[str, object]] = {}
    for name in sorted(CANONICAL_DATA_FILES):
        payload = b""
        (root / name).write_bytes(payload)
        files[name] = {
            "bytes": 0,
            "rows": 0,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    (root / "manifest.json").write_bytes(
        _canonical_json(
            {
                "files": files,
                "schema_version": schema_version,
                "status": "candidate_built",
            }
        )
    )


@pytest.mark.parametrize(
    "schema_version",
    [
        "reddit_voc_canonical_snapshot_manifest_v1",
        "reddit_voc_canonical_snapshot_manifest_v2",
    ],
)
def test_previous_canonical_bundle_supports_safe_daily_chaining(
    tmp_path: Path, schema_version: str
) -> None:
    root = tmp_path / "canonical"
    _write_previous_bundle(root, schema_version)

    payloads = _read_previous_bundle(root)

    assert set(payloads) == CANONICAL_DATA_FILES | {"manifest.json"}


def test_previous_canonical_bundle_rejects_unknown_schema(tmp_path: Path) -> None:
    root = tmp_path / "canonical"
    _write_previous_bundle(root, "reddit_voc_canonical_snapshot_manifest_v3")

    with pytest.raises(CenterCanonicalExportError, match="manifest is invalid"):
        _read_previous_bundle(root)


def test_comment_with_missing_immediate_parent_stays_linked_when_root_post_exists() -> None:
    assert (
        _canonical_comment_state(
            post_id="t3_present",
            post_ids={"t3_present"},
            relationship_status="unresolved",
        )
        == "linked"
    )
    assert (
        _canonical_comment_state(
            post_id="t3_missing",
            post_ids={"t3_present"},
            relationship_status="unresolved",
        )
        == "unresolved_parent"
    )
