from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.validate_reddit_daily_site_refresh import (
    DailySiteRefreshValidationError,
    validate_daily_site_refresh,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "ref/UI/momcozy-reddit-workbench/public"
RUN = ROOT / "tmp/reddit-voc-v3/candidate-orchestration/v3-daily-refresh-20260723"


class DailySiteRefreshValidationTests(unittest.TestCase):
    def test_validates_current_daily_candidate(self) -> None:
        value = validate_daily_site_refresh(
            public_root=PUBLIC,
            pointer_path=PUBLIC / "data/reddit-voc/current-release.json",
            e2e_summary_path=RUN / "e2e-result-summary.json",
            screenshot_root=RUN / "e2e-screenshots",
        )
        self.assertEqual(value["status"], "passed_candidate_only")
        self.assertEqual(len(value["datasets"]), 7)
        self.assertEqual({row["grain"] for row in value["screenshots"]}, {"daily", "weekly", "monthly"})

    def test_rejects_a_non_24_hour_business_window(self) -> None:
        with TemporaryDirectory() as directory:
            pointer = json.loads(
                (PUBLIC / "data/reddit-voc/current-release.json").read_text(encoding="utf-8")
            )
            invalid = deepcopy(pointer)
            invalid["freshness"]["window_start_utc"] = "2026-07-22T00:00:00Z"
            path = Path(directory) / "pointer.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                DailySiteRefreshValidationError,
                "freshness_window_invalid",
            ):
                validate_daily_site_refresh(
                    public_root=PUBLIC,
                    pointer_path=path,
                    e2e_summary_path=RUN / "e2e-result-summary.json",
                    screenshot_root=RUN / "e2e-screenshots",
                )


if __name__ == "__main__":
    unittest.main()
