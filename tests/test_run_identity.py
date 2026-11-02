"""A run id must name one run, and its kind must be measurable.

`daily_collect_YYYYMMDD_0700` was a calendar label: two runs on the same day
produced the same id, the second receipt overwrote the first, and K1 could not
tell a scheduled run from a manual rerun. These tests pin the new identity:

* run_id carries the start time to the second;
* run_kind is `scheduled` inside 07:05 CST ±30 minutes, otherwise `manual`;
* the pointer's `collector_run_id` is the same id the pipeline used, not a
  separately synthesized date label.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "run_daily_t1_pipeline", ROOT / "scripts" / "run_daily_t1_pipeline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_advance():
    spec = importlib.util.spec_from_file_location(
        "advance_daily_t1_release", ROOT / "scripts" / "advance_daily_t1_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduled_window_is_0705_plus_minus_30_minutes() -> None:
    pipeline = _load_pipeline()
    run_id, kind, trigger = pipeline._run_identity(
        datetime(2026, 11, 2, 7, 5, 0, tzinfo=SHANGHAI)
    )
    assert run_id == "daily_collect_20261102_070500"
    assert kind == "scheduled"
    assert trigger == "systemd_timer"

    _, kind, trigger = pipeline._run_identity(
        datetime(2026, 11, 2, 7, 35, 1, tzinfo=SHANGHAI)
    )
    assert kind == "manual"
    assert trigger == "manual_cli"


def test_two_runs_in_the_same_day_get_distinct_ids() -> None:
    pipeline = _load_pipeline()
    first, _, _ = pipeline._run_identity(datetime(2026, 11, 2, 7, 5, 0, tzinfo=SHANGHAI))
    second, _, _ = pipeline._run_identity(datetime(2026, 11, 2, 7, 5, 1, tzinfo=SHANGHAI))
    assert first != second
    assert first.startswith("daily_collect_20261102_")
    assert second.startswith("daily_collect_20261102_")


def test_t1_bounds_returns_run_kind_and_closed_window() -> None:
    pipeline = _load_pipeline()
    # 2026-11-01T23:05Z == 2026-11-02 07:05 CST
    start, end, run_id, report_date, kind, trigger = pipeline._t1_bounds(
        datetime(2026, 11, 1, 23, 5, tzinfo=timezone.utc)
    )
    assert start.isoformat() == "2026-10-31T23:00:00+00:00"
    assert end.isoformat() == "2026-11-01T23:00:00+00:00"
    assert report_date == "2026-11-02"
    assert run_id == "daily_collect_20261102_070500"
    assert kind == "scheduled"
    assert trigger == "systemd_timer"


def test_pointer_uses_the_pipeline_run_id() -> None:
    advance = _load_advance()
    document = {"freshness": {}}
    updated = advance.advance_release_document(
        document,
        status="partial",
        now_utc=datetime(2026, 11, 1, 23, 5, tzinfo=timezone.utc),
        run_id="daily_collect_20261102_070500",
    )
    assert updated["freshness"]["collector_run_id"] == "daily_collect_20261102_070500"


def test_standalone_advance_keeps_the_date_only_fallback(tmp_path: Path) -> None:
    advance = _load_advance()
    pointer = tmp_path / "current-release.json"
    pointer.write_text(json.dumps({"freshness": {}, "release_id": "demo"}), encoding="utf-8")
    advance.advance_current_release_to_t1(
        current_release_path=pointer,
        status="partial",
        now_utc=datetime(2026, 11, 1, 23, 5, tzinfo=timezone.utc),
    )
    written = json.loads(pointer.read_text(encoding="utf-8"))
    # The CLI keeps the historical label when no run_id is supplied.
    assert written["freshness"]["collector_run_id"] == "daily_collect_20261102_0700"