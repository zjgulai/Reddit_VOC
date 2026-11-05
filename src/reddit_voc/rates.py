"""Shared rounding helpers for cross-runtime numeric contracts.

The workbench client validates served numbers against JS ``Math.round``
semantics (half-up).  Python's builtin ``round()`` is banker's rounding
(half-even): at exact ``.5`` boundaries the two disagree, and 2026-11-04 hit
exactly that boundary (2/64 = 312.5 -> 3.12 vs 3.13) with the workbench
refusing to render the whole dashboard.  Every percent rate that the client
recomputes must round half-up like JS, never half-even.
"""

from __future__ import annotations

import math


def half_up_percent(numerator: int, denominator: int) -> float | None:
    """Return ``numerator/denominator`` as a percent rounded half-up to 2 dp.

    Matches the client contract ``Math.round(numerator * 1e4 / denominator) / 100``.
    Returns ``None`` when the denominator is zero (no classified VOCs) so both
    writer and validator render the same explicit absence instead of a bare 0.
    """
    if not denominator:
        return None
    return math.floor(numerator * 10_000 / denominator + 0.5) / 100
