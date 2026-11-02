#!/usr/bin/env python3
"""Automated T-1 Daily Pipeline & Site Projection Refresher.

Bridges the gap between daily collection and the public static site:
1. Calculates the latest closed Shanghai 07:00 boundary (T-1 data_as_of_utc).
2. Refreshes current-release.json with honest T-1 freshness status.
3. Automatically advances the public site pointer to prevent the 95-day stalling gap.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("reddit_voc.t1_pipeline")

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
PUBLIC_DATA_DIR = Path("ref/UI/momcozy-reddit-workbench/public/data/reddit-voc")
CURRENT_RELEASE_FILE = PUBLIC_DATA_DIR / "current-release.json"


def calculate_t1_shanghai_window(now_utc: datetime | None = None) -> tuple[datetime, datetime, datetime]:
    """Calculate (window_start_utc, window_end_utc, data_as_of_utc) for closed T-1."""
    now = now_utc.astimezone(timezone.utc) if now_utc else datetime.now(timezone.utc)
    # The 07:00 Asia/Shanghai daily window ends at 23:00 UTC of previous day
    close = now.replace(hour=23, minute=0, second=0, microsecond=0)
    if close > now:
        close -= timedelta(days=1)
    window_end_utc = close
    window_start_utc = close - timedelta(days=1)
    data_as_of_utc = close
    return window_start_utc, window_end_utc, data_as_of_utc


def advance_release_document(
    current_data: dict,
    *,
    status: str = "partial",
    now_utc: datetime | None = None,
    run_id: str | None = None,
) -> dict:
    """Apply the T-1 freshness advance to a release document in memory.

    Split out of `advance_current_release_to_t1` so the pipeline can prepare the
    document that its single commit will publish, without touching a file. In
    symlink mode a file write here would replace the *live* pointer, which is the
    one thing L6-T08 exists to prevent.

    `run_id` is the pipeline's real identity (start time to the second). The
    standalone CLI keeps the historical date-only fallback when it is omitted,
    so existing callers and byte-order tests remain valid.
    """
    w_start, w_end, as_of = calculate_t1_shanghai_window(now_utc)

    now = now_utc or datetime.now(timezone.utc)
    current_date_str = now.astimezone(SHANGHAI_TZ).strftime("%Y%m%d")

    # Update freshness block
    freshness = current_data.get("freshness", {})
    freshness.update({
        "status": status,
        "timezone": "Asia/Shanghai",
        "data_as_of_utc": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_start_utc": w_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end_utc": w_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "collector_run_id": run_id or f"daily_collect_{current_date_str}_0700",
    })
    current_data["freshness"] = freshness
    current_data["generated_at_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return current_data


def release_receipt(current_data: dict, status: str = "partial") -> dict[str, object]:
    """The step receipt shape shared by the CLI and the pipeline."""
    freshness = current_data.get("freshness", {})
    return {
        "status": "advanced",
        "release_id": current_data.get("release_id"),
        "data_as_of_utc": freshness["data_as_of_utc"],
        "window_start_utc": freshness["window_start_utc"],
        "window_end_utc": freshness["window_end_utc"],
        "freshness_status": status,
    }


def advance_current_release_to_t1(
    *,
    current_release_path: Path = CURRENT_RELEASE_FILE,
    status: str = "partial",
    now_utc: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    """Atomically advance current-release.json freshness to latest closed T-1 window."""
    if not current_release_path.exists():
        raise FileNotFoundError(f"Missing {current_release_path}")

    current_data = json.loads(current_release_path.read_text(encoding="utf-8"))
    current_data = advance_release_document(
        current_data, status=status, now_utc=now_utc, run_id=run_id
    )

    # Atomic write to current-release.json
    temp_path = current_release_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(current_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(current_release_path)

    return release_receipt(current_data, status)


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance Reddit VOC current-release to T-1")
    parser.add_argument("--current-release", type=Path, default=CURRENT_RELEASE_FILE)
    parser.add_argument("--status", choices=["full", "partial"], default="partial")
    parser.add_argument("--run-id", default=None, help="pipeline run id; defaults to date-only")
    args = parser.parse_args()

    result = advance_current_release_to_t1(
        current_release_path=args.current_release,
        status=args.status,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
