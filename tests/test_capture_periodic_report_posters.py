from __future__ import annotations

from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from scripts.capture_periodic_report_posters import (
    PERIOD_SPECS,
    PosterCaptureError,
    evaluate_golden,
    png_dimensions,
    validate_observation,
)


def valid_observation(period: str) -> dict[str, object]:
    spec = PERIOD_SPECS[period]
    width = int(spec["width"])
    height = int(spec["height"])
    box = {"x": 0, "y": 0, "width": width, "height": height}
    return {
        "status": "observed",
        "url": f"http://127.0.0.1/dashboard/reports?period={period}&capture=poster",
        "stableBoxes": [box.copy(), box.copy(), box.copy()],
        "browserErrors": [],
        "requestFailures": [],
        "httpFailures": [],
        "externalRequests": [],
        "contract": {
            "attributes": {
                "data-report-ready": "true",
                "data-report-period": period,
                "data-report-period-id": f"{period}:fixture",
                "data-report-release-id": "reddit_voc_release_fixture",
                "data-report-dataset-version": "reddit_voc_reports_fixture",
                "data-report-data-as-of": "2026-07-24",
                "data-report-source-freshness": "partial",
                "data-report-coverage": "100",
                "data-report-capture-width": str(width),
                "data-report-capture-height": str(height),
            },
            "root": {
                "clientWidth": width,
                "clientHeight": height,
                "scrollWidth": width,
                "scrollHeight": height,
                "rectangleWidth": width,
                "rectangleHeight": height,
            },
            "footerOverlap": False,
            "fontsStatus": "loaded",
            "visibleTooltips": 0,
            "textLength": 900,
            "chineseCharacterCount": 300,
            "maxTextBlockLength": 90,
            "containsExtremePercent": period == "monthly",
            "chartCount": 0 if period == "daily" else 1,
            "cardCount": 12,
            "hasLoadingText": False,
            "hasCaptureError": False,
        },
    }


def capture_row(period: str, digest: str = "a" * 64) -> dict[str, object]:
    return {
        "period": period,
        "period_id": f"{period}:fixture",
        "release_id": "reddit_voc_release_fixture",
        "dataset_version": "reddit_voc_reports_fixture",
        "sha256": digest,
    }


class PeriodicPosterContractTests(unittest.TestCase):
    def test_accepts_all_three_fixed_poster_contracts(self) -> None:
        for period, spec in PERIOD_SPECS.items():
            result = validate_observation(
                valid_observation(period),
                period=period,
                width=int(spec["width"]),
                height=int(spec["height"]),
            )
            self.assertEqual(result["status"], "observed")

    def test_rejects_partial_clipping_instead_of_sending_a_cropped_image(self) -> None:
        observation = valid_observation("weekly")
        observation["contract"]["root"]["scrollHeight"] = 2001  # type: ignore[index]
        with self.assertRaisesRegex(PosterCaptureError, "weekly_capture_overflow"):
            validate_observation(observation, period="weekly", width=1440, height=2000)

    def test_rejects_loading_empty_or_failed_capture_state(self) -> None:
        observation = valid_observation("daily")
        observation["contract"]["hasLoadingText"] = True  # type: ignore[index]
        with self.assertRaisesRegex(PosterCaptureError, "daily_visual_quality_failed"):
            validate_observation(observation, period="daily", width=1440, height=1800)

    def test_empty_success_source_status_can_render_the_latest_closed_report(self) -> None:
        observation = valid_observation("daily")
        observation["contract"]["attributes"][  # type: ignore[index]
            "data-report-source-freshness"
        ] = "empty_success"
        result = validate_observation(
            observation, period="daily", width=1440, height=1800
        )
        self.assertEqual(
            result["contract"]["attributes"]["data-report-source-freshness"],  # type: ignore[index]
            "empty_success",
        )

    def test_reads_png_dimensions_without_image_fallback_library(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "poster.png"
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + struct.pack(">I", 13)
                + b"IHDR"
                + struct.pack(">II", 1440, 2200)
            )
            self.assertEqual(png_dimensions(path), (1440, 2200))

    def test_exact_identity_requires_exact_image_hashes(self) -> None:
        captures = [capture_row(period) for period in PERIOD_SPECS]
        golden = {
            "baseline": {
                "release_id": "reddit_voc_release_fixture",
                "dataset_version": "reddit_voc_reports_fixture",
                "validator_script_sha256": "b" * 64,
                "captures": {
                    period: {"period_id": f"{period}:fixture", "sha256": "a" * 64}
                    for period in PERIOD_SPECS
                },
            }
        }
        result = evaluate_golden(
            golden=golden,
            golden_sha256="c" * 64,
            captures=captures,
            validator_sha256="b" * 64,
        )
        self.assertEqual(result["status"], "passed_exact_pixel_baseline")
        captures[0]["sha256"] = "d" * 64
        with self.assertRaisesRegex(PosterCaptureError, "golden_exact_image_mismatch:daily"):
            evaluate_golden(
                golden=golden,
                golden_sha256="c" * 64,
                captures=captures,
                validator_sha256="b" * 64,
            )

    def test_new_data_identity_requires_manual_visual_review(self) -> None:
        captures = [capture_row(period) for period in PERIOD_SPECS]
        golden = {
            "baseline": {
                "release_id": "reddit_voc_release_older",
                "dataset_version": "reddit_voc_reports_older",
                "validator_script_sha256": "b" * 64,
                "captures": {
                    period: {"period_id": f"{period}:older", "sha256": "e" * 64}
                    for period in PERIOD_SPECS
                },
            }
        }
        result = evaluate_golden(
            golden=golden,
            golden_sha256="c" * 64,
            captures=captures,
            validator_sha256="b" * 64,
        )
        self.assertEqual(result["status"], "passed_structural_new_identity")
        self.assertTrue(result["manual_visual_review_required"])


if __name__ == "__main__":
    unittest.main()
