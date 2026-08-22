from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from reddit_voc.v3_base_public import _event_time, _sanitize_text


ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "reddit_voc_site_snapshot_20260716_v3_base_a1"
PUBLIC_ROOT = (
    ROOT
    / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc"
    / DATASET_VERSION
)
RECEIPT_PATH = (
    ROOT
    / "tmp/reddit-voc-v3/reddit_add_data_20260715_v1"
    / "base-public-validation-a1/receipt.json"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_formal_v3_base_public_candidate_is_complete_and_privacy_safe() -> None:
    manifest = _load(PUBLIC_ROOT / "manifest-public.json")
    posts = _load(PUBLIC_ROOT / "posts-public.json")
    comments = _load(PUBLIC_ROOT / "comments-public.json")
    aggregates = _load(PUBLIC_ROOT / "aggregates-public.json")

    assert manifest["schema_version"] == "reddit_voc_site_snapshot_manifest_v3"
    assert manifest["dataset_version"] == DATASET_VERSION
    assert manifest["status"] == "validated_candidate"
    assert manifest["promotable"] is True
    assert manifest["privacy_safe_projection"] is True
    assert manifest["completeness_percent"] == 100
    assert manifest["lineage_manifest_sha256"] == (
        "36bbc15074437ab0b48732200a50a3356091391175e565f4e9769122ece2c1ce"
    )
    assert manifest["canonical_counts"] == {
        "posts": 3494,
        "comments_jsonl": 27148,
        "linked_comments": 20205,
        "unresolved_parent_comments": 6943,
        "quarantined_comments": 10,
        "stored_comments": 27158,
    }
    assert len(posts) == 3494
    assert len(comments) == 20205
    assert len({row["post_id"] for row in posts}) == len(posts)
    assert len({row["comment_id"] for row in comments}) == len(comments)
    assert {row["post_id"] for row in comments} <= {row["post_id"] for row in posts}
    assert all(row["author_pseudonym"] is None for row in [*posts, *comments])
    assert all(
        row["author_pseudonym_status"] == "suppressed_for_public_projection"
        for row in [*posts, *comments]
    )
    day_rows = [
        row for row in [*posts, *comments] if row["event_time_precision"] == "day"
    ]
    assert len(day_rows) == 2172 + 3624
    assert all(row["event_created_at_utc"] is None for row in day_rows)
    assert all(row["created_at_utc"] == row["source_calendar_date"] for row in day_rows)
    assert aggregates["headline"]["unresolved_parent_comments"] == 6943
    assert aggregates["metric_notes"]["unresolved_parent_comments"].startswith(
        "待关联评论"
    )
    for name, contract in manifest["files"].items():
        path = PUBLIC_ROOT / name
        assert path.stat().st_size == contract["bytes"]
        assert _sha(path) == contract["sha256"]


def test_formal_v3_base_public_receipt_binds_the_public_manifest() -> None:
    receipt = _load(RECEIPT_PATH)
    public_manifest_sha = _sha(PUBLIC_ROOT / "manifest-public.json")

    assert receipt["schema_version"] == "reddit_voc_base_public_validation_receipt_v1"
    assert receipt["status"] == "passed_candidate_only"
    assert receipt["promotable"] is True
    assert receipt["privacy_safe_projection"] is True
    assert receipt["completeness_percent"] == 100
    assert receipt["bundle_manifest_sha256"] == public_manifest_sha
    assert receipt["public_manifest_sha256"] == public_manifest_sha
    assert receipt["all_checks_passed"] is True
    assert all(receipt["checks"].values())


def test_projection_helpers_redact_identity_and_preserve_day_precision() -> None:
    text, flags = _sanitize_text(
        "Email a@example.com, call +1 212 555 0100, or ask u/sample_user."
    )
    assert "a@example.com" not in text
    assert "+1 212 555 0100" not in text
    assert "sample_user" not in text
    assert set(flags) == {"email", "phone_candidate", "username_mention"}

    event = _event_time(
        {"event_time_precision": "day", "source_calendar_date": "2025-07-01"},
        "fixture",
    )
    assert event == {
        "created_at_utc": "2025-07-01",
        "event_created_at_utc": None,
        "source_calendar_date": "2025-07-01",
        "event_time_precision": "day",
    }

