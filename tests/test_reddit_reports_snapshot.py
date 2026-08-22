import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.build_reddit_reports_snapshot import build, write_snapshot
from scripts.validate_reddit_reports_snapshot import validate


ROOT = Path(__file__).resolve().parents[1]
BASE_SNAPSHOT = ROOT / "data/processed/reddit_voc_site_snapshot_20260714"
INSIGHTS_SNAPSHOT = ROOT / "data/processed/reddit_voc_insights_20260714"


def _write_fixture(output_dir: Path) -> dict:
    reports, index, manifest = build(BASE_SNAPSHOT, INSIGHTS_SNAPSHOT)
    return write_snapshot(output_dir, reports, index, manifest)


def _rewrite_report_and_manifest(
    output_dir: Path, relative_path: str, report: dict
) -> None:
    report_path = output_dir / relative_path
    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][relative_path] = {
        "bytes": report_path.stat().st_size,
        "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def test_builds_six_dual_window_reports_and_validates(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    manifest = _write_fixture(output_dir)
    receipt = validate(output_dir, BASE_SNAPSHOT, INSIGHTS_SNAPSHOT)
    index = json.loads((output_dir / "report-index.json").read_text(encoding="utf-8"))

    assert manifest["report_count"] == 6
    assert receipt["status"] == "passed"
    assert all(receipt["checks"].values())
    assert index["current"]["daily"]["posts"] == 8
    assert index["current"]["daily"]["voc_comments"] == 37
    assert index["current"]["weekly"]["posts"] == 83
    assert index["current"]["weekly"]["voc_comments"] == 392
    assert index["current"]["monthly"]["posts"] == 85
    assert index["current"]["monthly"]["voc_comments"] == 395
    assert index["archive"]["daily"]["posts"] == 12
    assert index["archive"]["daily"]["voc_comments"] == 59
    assert index["archive"]["weekly"]["posts"] == 67
    assert index["archive"]["weekly"]["voc_comments"] == 307
    assert index["archive"]["monthly"]["coverage_status"] == "coverage_gap"
    assert receipt["production_unchanged"] is True
    assert receipt["provider_call"] is False
    assert receipt["database_write"] is False
    assert receipt["live_send"] is False
    assert receipt["webhook_send"] is False


def test_output_is_byte_stable_for_identical_inputs(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_manifest = _write_fixture(first)
    second_manifest = _write_fixture(second)

    assert first_manifest == second_manifest
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    for relative_path in first_manifest["files"]:
        assert (first / relative_path).read_bytes() == (second / relative_path).read_bytes()


def test_output_is_byte_stable_across_python_hash_seeds(tmp_path: Path) -> None:
    outputs = []
    for seed in ("1", "2"):
        output_dir = tmp_path / f"seed-{seed}"
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/build_reddit_reports_snapshot.py"),
                "--snapshot-dir",
                str(BASE_SNAPSHOT),
                "--insights-dir",
                str(INSIGHTS_SNAPSHOT),
                "--output-dir",
                str(output_dir),
            ],
            check=True,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        outputs.append(output_dir)

    first, second = outputs
    first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    for relative_path in first_manifest["files"]:
        assert (first / relative_path).read_bytes() == (second / relative_path).read_bytes()


def test_rejects_hash_tampering_before_semantic_validation(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    _write_fixture(output_dir)
    daily_path = output_dir / "current/daily.json"
    daily_path.write_text(daily_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ValueError, match="byte mismatch: current/daily.json"):
        validate(output_dir, BASE_SNAPSHOT, INSIGHTS_SNAPSHOT)


def test_rejects_rehashed_headline_count_tampering(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    _write_fixture(output_dir)
    relative_path = "current/daily.json"
    report = json.loads((output_dir / relative_path).read_text(encoding="utf-8"))
    report["headline"]["posts"] += 1
    _rewrite_report_and_manifest(output_dir, relative_path, report)

    with pytest.raises(ValueError, match="headline post count mismatch"):
        validate(output_dir, BASE_SNAPSHOT, INSIGHTS_SNAPSHOT)


def test_rejects_held_tag_injection_even_after_rehash(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    _write_fixture(output_dir)
    relative_path = "current/weekly.json"
    report = json.loads((output_dir / relative_path).read_text(encoding="utf-8"))
    held = dict(report["promoted_signals"][0])
    held["tag_id"] = "L0-SVC-019"
    held["name_cn"] = "正面反馈"
    report["promoted_signals"].append(held)
    _rewrite_report_and_manifest(output_dir, relative_path, report)

    with pytest.raises(ValueError, match="promoted report signal set mismatch"):
        validate(output_dir, BASE_SNAPSHOT, INSIGHTS_SNAPSHOT)


def test_rejects_persona_and_side_effect_overclaims(tmp_path: Path) -> None:
    output_dir = tmp_path / "reports"
    _write_fixture(output_dir)
    relative_path = "current/monthly.json"
    report = json.loads((output_dir / relative_path).read_text(encoding="utf-8"))
    report["interpretation_boundaries"]["persona_tags_generated"] = True
    report["runtime_boundaries"]["webhook_send"] = True
    _rewrite_report_and_manifest(output_dir, relative_path, report)

    with pytest.raises(ValueError, match="persona overclaim"):
        validate(output_dir, BASE_SNAPSHOT, INSIGHTS_SNAPSHOT)


def test_monthly_archive_is_explicit_coverage_gap_not_zero_discussion_claim(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "reports"
    _write_fixture(output_dir)
    report = json.loads(
        (output_dir / "archive/monthly-2026-06.json").read_text(encoding="utf-8")
    )

    assert report["window"]["coverage_status"] == "coverage_gap"
    assert report["window"]["comparison_status"] == "coverage_unverified"
    assert report["headline"]["posts"] == 0
    assert report["headline"]["voc_comments"] == 0
    assert report["interpretation_boundaries"]["trend_claim_supported"] is False
    assert report["capabilities"]["unsupported"]


def test_comments_are_windowed_by_comment_time_not_parent_post_time() -> None:
    reports, _, _ = build(BASE_SNAPSHOT, INSIGHTS_SNAPSHOT)
    weekly = reports["current/weekly.json"]
    base_posts = json.loads((BASE_SNAPSHOT / "posts.json").read_text(encoding="utf-8"))
    comments = json.loads((BASE_SNAPSHOT / "comments.json").read_text(encoding="utf-8"))
    post_by_id = {row["post_id"]: row for row in base_posts}
    start = weekly["window"]["start_utc"]
    end = weekly["window"]["end_utc"]

    independently_windowed = [
        row
        for row in comments
        if row["include_in_voc_metrics"] and start <= row["created_at_utc"] < end
    ]
    parent_windowed = [
        row
        for row in independently_windowed
        if start <= post_by_id[row["post_id"]]["created_at_utc"] < end
    ]

    assert weekly["headline"]["voc_comments"] == len(independently_windowed)
    assert len(independently_windowed) >= len(parent_windowed)
