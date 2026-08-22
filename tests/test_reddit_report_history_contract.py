from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.build_reddit_reports_snapshot import (
    V3ReportsBuildError,
    _v3_assert_output_inventory,
    _v3_safe_relative_path,
)
from scripts.validate_reddit_reports_snapshot import (
    V3ReportsValidationError,
    _v3_validate_inventory,
    _v3_validated_artifact_path,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "ref/UI/momcozy-reddit-workbench/public"


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_current_public_history_is_contiguous_and_sha_bound() -> None:
    release = _json(PUBLIC / "data/reddit-voc/current-release.json")
    reports_binding = release["datasets"]["reports"]
    manifest_path = PUBLIC / reports_binding["manifest_path"]
    reports_root = manifest_path.parent
    manifest = _json(manifest_path)
    index = _json(reports_root / "report-index.json")
    history = _json(reports_root / "business-history-index.json")

    assert manifest["report_count"] == 44
    assert manifest["history_report_count"] == 38
    assert manifest["business_entry_count"] == 41
    assert history["limits"] == {"daily": 14, "weekly": 12, "monthly": 12}
    assert history["history_entry_count"] == 38
    assert history["total_business_entry_count"] == 41

    seen_paths: set[str] = set()
    for grain, expected_count in {"daily": 14, "weekly": 12, "monthly": 12}.items():
        entries = history["reports"][grain]
        assert len(entries) == expected_count
        expected_end = index["reports"][grain]["period"]["start"]
        for entry in entries:
            relative_path = entry["artifact_path"]
            artifact_path = reports_root / relative_path
            report = _json(artifact_path)
            assert entry["period"]["end"] == expected_end
            assert report["period"] == entry["period"]
            assert report["artifact_role"] == "historical_complete_calendar_period"
            assert report["business_entry_visible"] is True
            assert "comparison_archive_path" not in report
            assert sha256(artifact_path.read_bytes()).hexdigest() == entry["artifact_sha256"]
            assert manifest["files"][relative_path]["sha256"] == entry["artifact_sha256"]
            assert relative_path not in seen_paths
            seen_paths.add(relative_path)
            expected_end = entry["period"]["start"]

    assert len(seen_paths) == 38


@pytest.mark.parametrize(
    "unsafe_path",
    ("../escape.json", "/absolute.json", "history/../escape.json", "history\\escape.json"),
)
def test_history_writer_rejects_unsafe_relative_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    with pytest.raises(V3ReportsBuildError, match="path is unsafe"):
        _v3_safe_relative_path(tmp_path, unsafe_path, "V3 history")


def test_history_writer_and_validator_reject_symlink_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "reports"
    root.mkdir()
    (root / "history").symlink_to(outside, target_is_directory=True)

    with pytest.raises(V3ReportsBuildError, match="path is unsafe"):
        _v3_safe_relative_path(root, "history/daily/2026-01-01.json", "V3 history")
    with pytest.raises(V3ReportsValidationError, match="path is unsafe"):
        _v3_validated_artifact_path(
            root,
            "history/daily/2026-01-01.json",
            "V3 history",
        )


def test_recursive_inventory_rejects_stale_undeclared_history_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reports"
    expected = root / "history/daily/expected.json"
    stale = root / "history/daily/stale.json"
    expected.parent.mkdir(parents=True)
    expected.write_text("{}\n", encoding="utf-8")
    stale.write_text("{}\n", encoding="utf-8")
    expected_files = {"history/daily/expected.json"}

    with pytest.raises(V3ReportsBuildError, match="undeclared files"):
        _v3_assert_output_inventory(root, expected_files, "V3 reports", exact=True)
    with pytest.raises(V3ReportsValidationError, match="recursive file set"):
        _v3_validate_inventory(root, expected_files, "V3 reports")
