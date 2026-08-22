from __future__ import annotations

from collections.abc import Sequence


DEFAULT_DAILY_SUBREDDITS: tuple[str, ...] = (
    "ExclusivelyPumping",
    "BreastPumping",
    "breastfeeding",
    "HumansPumpingMilk",
    "breastpumps",
    "Buyingforbaby",
    "BabyBumps",
    "beyondthebump",
    "workingmoms",
    "NewParents",
    "babywearing",
    "moderatelygranolamoms",
    "FormulaFeeders",
    "parentsofmultiples",
    "NICUParents",
)

# Backfill code uses the reviewed immutable name; the daily collector keeps its
# established public alias for compatibility.
DEFAULT_REVIEWED_SUBREDDITS = DEFAULT_DAILY_SUBREDDITS


DEFAULT_TIKHUB_SEARCH_TERMS: Sequence[str] = (
    "Momcozy",
    "momcozy",
    '"Momcozy"',
    '"momcozy"',
    '"mom cozy"',
    '"Momcozy M5"',
    '"Momcozy S12"',
    '"Momcozy M9"',
    '"Momcozy KleanPal"',
    '"Momcozy bottle washer"',
    '"Momcozy baby carrier"',
    '"Momcozy PureHug"',
    '"wearable pump"',
    '"breast pump"',
    '"bottle washer"',
)
