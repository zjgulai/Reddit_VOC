from __future__ import annotations

import unittest

from reddit_voc.backfill_validation import (
    _ReplayDataError,
    _is_replayable_zero_page_budget_checkpoint,
    _validate_hydration_resume_ledgers,
    _validated_budget_extension_boundaries,
)


RUN_ID = "backfill_momcozy_20250101_20260711"
LANES_SHA256 = "a" * 64


def _manifest(*, request_count: int, maximum: int) -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "status": "partial",
        "provider_request_count": request_count,
        "max_provider_requests": maximum,
        "include_subreddit_sweep": 1,
        "required_lanes_sha256": LANES_SHA256,
    }


def _run() -> dict[str, object]:
    return {"run_id": RUN_ID, "status": "partial"}


def _extension(
    *,
    authorization: str = "b" * 64,
    expected: int = 670,
    new_maximum: int = 870,
    discovery_ceiling: int = 820,
) -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "authorization_sha256": authorization,
        "expected_provider_request_count": expected,
        "expected_max_provider_requests": expected,
        "new_max_provider_requests": new_maximum,
        "discovery_request_ceiling": discovery_ceiling,
        "lane_page_ceilings_sha256": "c" * 64,
        "include_subreddit_sweep": 1,
        "required_lanes_sha256": LANES_SHA256,
        "applied_at_utc": "2026-07-13T12:00:00+00:00",
    }


def _zero_page_checkpoint(
    *, request_count: int, phase: bool = False
) -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "lane_type": "dynamic_search",
        "lane_key": "Momcozy wearable breast pump",
        "cursor": None,
        "previous_cursor": None,
        "page_number": 0,
        "newest_seen_utc": None,
        "oldest_seen_utc": None,
        "discovered_count": 0,
        "unique_count": 0,
        "provider_request_count": request_count,
        "last_success_utc": None,
        "last_error": (
            "ProviderPhaseBudgetExhausted" if phase else "ProviderBudgetExhausted"
        ),
        "status": "partial",
        "stop_reason": (
            "discovery_budget_exhausted" if phase else "budget_exhausted"
        ),
        "cursor_json_path": None,
        "cursor_schema_sha256": None,
        "consecutive_old_pages": 0,
    }


class BudgetExtensionReplayBoundaryTests(unittest.TestCase):
    def test_legacy_current_global_exhaustion_remains_replayable(self) -> None:
        manifest = _manifest(request_count=670, maximum=670)
        global_boundaries, phase_boundaries = (
            _validated_budget_extension_boundaries(manifest, ())
        )

        self.assertTrue(
            _is_replayable_zero_page_budget_checkpoint(
                _zero_page_checkpoint(request_count=670),
                manifest,
                _run(),
                global_budget_boundaries=global_boundaries,
                discovery_phase_boundaries=phase_boundaries,
            )
        )

    def test_extended_momcozy_budget_requires_authorization_ledger(self) -> None:
        with self.assertRaises(_ReplayDataError) as raised:
            _validated_budget_extension_boundaries(
                _manifest(request_count=850, maximum=870), ()
            )

        self.assertEqual(
            raised.exception.stop_reason,
            "budget_extension_ledger_invalid",
        )

    def test_historical_global_and_phase_boundaries_are_authorization_bound(self) -> None:
        manifest = _manifest(request_count=850, maximum=870)
        global_boundaries, phase_boundaries = (
            _validated_budget_extension_boundaries(
                manifest, (_extension(),)
            )
        )

        self.assertTrue(
            _is_replayable_zero_page_budget_checkpoint(
                _zero_page_checkpoint(request_count=670),
                manifest,
                _run(),
                global_budget_boundaries=global_boundaries,
                discovery_phase_boundaries=phase_boundaries,
            )
        )
        self.assertTrue(
            _is_replayable_zero_page_budget_checkpoint(
                _zero_page_checkpoint(request_count=820, phase=True),
                manifest,
                _run(),
                global_budget_boundaries=global_boundaries,
                discovery_phase_boundaries=phase_boundaries,
            )
        )

    def test_unbound_old_or_wrongly_typed_boundary_is_rejected(self) -> None:
        manifest = _manifest(request_count=850, maximum=870)
        global_boundaries, phase_boundaries = (
            _validated_budget_extension_boundaries(manifest, (_extension(),))
        )
        cases = (
            _zero_page_checkpoint(request_count=669),
            {
                **_zero_page_checkpoint(request_count=670),
                "stop_reason": "discovery_budget_exhausted",
                "last_error": "ProviderPhaseBudgetExhausted",
            },
            {
                **_zero_page_checkpoint(request_count=820, phase=True),
                "last_error": "ProviderBudgetExhausted",
            },
        )

        for checkpoint in cases:
            with self.subTest(checkpoint=checkpoint):
                self.assertFalse(
                    _is_replayable_zero_page_budget_checkpoint(
                        checkpoint,
                        manifest,
                        _run(),
                        global_budget_boundaries=global_boundaries,
                        discovery_phase_boundaries=phase_boundaries,
                    )
                )

    def test_extension_chain_must_be_contiguous_and_match_live_manifest(self) -> None:
        valid_second = _extension(
            authorization="d" * 64,
            expected=870,
            new_maximum=1070,
            discovery_ceiling=1020,
        )
        global_boundaries, phase_boundaries = (
            _validated_budget_extension_boundaries(
                _manifest(request_count=1000, maximum=1070),
                (_extension(), valid_second),
            )
        )
        self.assertEqual(global_boundaries, frozenset((670, 870)))
        self.assertEqual(phase_boundaries, frozenset((820, 1020)))

        invalid_cases = (
            (
                _manifest(request_count=1000, maximum=1070),
                (
                    _extension(),
                    _extension(
                        authorization="d" * 64,
                        expected=900,
                        new_maximum=1070,
                        discovery_ceiling=1020,
                    ),
                ),
            ),
            (
                _manifest(request_count=850, maximum=900),
                (_extension(),),
            ),
            (
                _manifest(request_count=850, maximum=870),
                ({**_extension(), "required_lanes_sha256": "e" * 64},),
            ),
            (
                _manifest(request_count=850, maximum=870),
                ({**_extension(), "authorization_sha256": "NOT-A-SHA"},),
            ),
        )
        for manifest, extensions in invalid_cases:
            with self.subTest(manifest=manifest, extensions=extensions):
                with self.assertRaises(_ReplayDataError) as raised:
                    _validated_budget_extension_boundaries(manifest, extensions)
                self.assertEqual(
                    raised.exception.stop_reason,
                    "budget_extension_ledger_invalid",
                )

    def test_momcozy_extension_chain_must_start_at_frozen_670_budget(self) -> None:
        surviving_second_extension = _extension(
            authorization="d" * 64,
            expected=870,
            new_maximum=1070,
            discovery_ceiling=1020,
        )

        with self.assertRaises(_ReplayDataError) as raised:
            _validated_budget_extension_boundaries(
                _manifest(request_count=1000, maximum=1070),
                (surviving_second_extension,),
            )

        self.assertEqual(
            raised.exception.stop_reason,
            "budget_extension_ledger_invalid",
        )

    def test_momcozy_extension_requires_matching_hydration_resume_ledger(self) -> None:
        with self.assertRaises(_ReplayDataError) as raised:
            _validate_hydration_resume_ledgers(
                run_id=RUN_ID,
                extension_rows=[_extension()],
                resume_rows=[],
                source_rows={
                    "backfill_candidates": [],
                    "backfill_detail_batches": [],
                    "backfill_detail_batch_members": [],
                },
            )

        self.assertEqual(
            raised.exception.stop_reason,
            "hydration_resume_ledger_invalid",
        )


if __name__ == "__main__":
    unittest.main()
