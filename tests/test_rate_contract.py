"""Rate-contract tests: every served negative_rate must round half-up like JS.

The workbench client recomputes percentages as
``Math.round(negative * 1e4 / classified) / 100`` (half-up). Python's builtin
``round()`` is banker's rounding and disagrees at exact .5 boundaries — the
2026-11-04 production incident (2/64 = 312.5 -> 3.12 vs 3.13) made every page
embedding quarter-insights refuse to render. These tests pin three things:

1. the shared helper's JS-parity semantics at known boundaries,
2. that the two rate implementations in the repo (the daily-pipeline engine in
   scripts/recompute_derivatives.py and the quarter-projection producer in
   src/reddit_voc/v3_quarter_insights_public.py) cannot drift apart again,
3. that writer and validator inside the projection share one helper.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import unittest

from reddit_voc.rates import half_up_percent

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "recompute_derivatives", ROOT / "scripts" / "recompute_derivatives.py"
)
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)


class HalfUpPercentContractTests(unittest.TestCase):
    """The helper alone must reproduce the JS Math.round client contract."""

    def test_matches_js_math_round_at_known_boundaries(self) -> None:
        # (negative, classified, expected) — the JS semantics for every case:
        for negative, classified, expected in [
            (2, 64, 3.13),    # 312.5 -> 313: the exact 2026-11-04 failure
            (1, 64, 1.56),    # 156.25 -> 156
            (3, 64, 4.69),    # 468.75 -> 469
            (1, 8, 12.5),     # 1250.0 -> 1250: exact integers stay put
            (1, 3, 33.33),    # 3333.33 -> 3333
            (2, 3, 66.67),    # 6666.67 -> 6667
            (1, 6, 16.67),    # 1666.67 -> 1667
            (0, 5, 0.0),
        ]:
            self.assertEqual(half_up_percent(negative, classified), expected, (negative, classified))

    def test_returns_none_for_zero_denominator(self) -> None:
        self.assertIsNone(half_up_percent(0, 0))
        self.assertIsNone(half_up_percent(5, 0))

    def test_disagrees_with_bankers_rounding_at_half_boundary(self) -> None:
        # Guard the reason this helper exists: builtin round() is half-even.
        self.assertEqual(round(2 * 10_000 / 64), 312)          # banker's: 312
        self.assertEqual(round(2 * 10_000 / 64 + 0.5) // 1, 313)  # half-up: 313
        self.assertEqual(half_up_percent(2, 64), 3.13)


class DriftLockTests(unittest.TestCase):
    """The pipeline engine and the projection producer must share one contract."""

    def test_pipeline_engine_rate_is_the_shared_helper(self) -> None:
        # scripts/recompute_derivatives.py:_rate is the deployed 07:05 path;
        # it must stay semantically identical to the shared helper.
        for negative, classified in [(2, 64), (1, 64), (1, 3), (2, 3), (110, 1708), (0, 5), (7, 0)]:
            self.assertEqual(
                rd._rate(negative, classified),
                half_up_percent(negative, classified),
                (negative, classified),
            )

    def test_pipeline_engine_rate_documentation_names_js_contract(self) -> None:
        source = inspect.getsource(rd._rate)
        self.assertIn("Math.round", source)

    def test_projection_writer_uses_the_shared_helper(self) -> None:
        from reddit_voc import v3_quarter_insights_public as producer

        source = inspect.getsource(producer)
        # The writer site and both validator sites must go through the helper —
        # banker's round() on a percent rate is the drift this locks out.
        self.assertNotIn("negative_rate\": round(", source)
        self.assertNotIn("expected_rate = round(", source)
        self.assertNotIn("rate = round(", source)
        self.assertIn("half_up_percent(negative, classified)", source)
        self.assertIn("half_up_percent(momcozy[\"negative_vocs\"], momcozy[\"classified_vocs\"])", source)
        self.assertIn("half_up_percent(bucket[\"negative_vocs\"], bucket[\"classified_vocs\"])", source)
        self.assertIn("half_up_percent(sentiment[\"negative\"], classified)", source)


if __name__ == "__main__":
    unittest.main()
