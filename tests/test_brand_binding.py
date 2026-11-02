"""A brand name in a post is not the same as a post about the brand.

Two false bindings reached the 2026-10-30 morning card's evidence list:

  - `r/BayAreaBuyers` "1519 Peregrino Way" -> competitor comparison, because the
    listing says the house is in **Willow Glen**. Word-boundary matching is not
    enough: "Willow" is a genuine standalone word there.
  - `r/dubaiclassifieds` "[WTS] Home & Baby Clearout" -> Momcozy post, because a
    used-goods listing itemised a "Momcozy S12 Pro". The brand is real; the post is
    an advert, not an experience.

`assess_brand_binding` adds the two gates that separate a mention from a VOC
binding, and returns the reason so a surprising label is explainable rather than
mysterious.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit_voc.brand_binding import BrandAssessment, assess_brand_binding  # noqa: E402


def test_house_listing_mentioning_a_neighbourhood_is_not_a_competitor_post() -> None:
    """The exact 2026-10-30 false positive."""
    assessment = assess_brand_binding(
        "New Listing, Home For Sale - 1519 Peregrino Way, San Jose, CA 95125",
        "Description: Rare opportunity to own an exceptional home in Willow Glen's "
        "coveted Dry Creek neighborhood.",
        "r/BayAreaBuyers",
    )
    assert assessment.binding == "brand_unbound"
    assert assessment.reason == "no_product_domain_context"
    # The mention itself is real and is still reported, so the reason is auditable.
    assert "Willow" in assessment.mentions
    assert assessment.is_bound() is False


def test_classified_ad_with_a_real_brand_is_not_voc_evidence() -> None:
    """The brand is genuinely present; the post sells rather than reports."""
    assessment = assess_brand_binding(
        "[WTS] Home & Baby Clearout: Large Framed Mirror, Spectra Dual Compact",
        "Momcozy S12 Pro Double, Mambobaby float, and other baby items. Price starts at 2500.",
        "r/dubaiclassifieds",
    )
    assert assessment.binding == "brand_unbound"
    assert assessment.reason == "transaction_listing"
    assert "Momcozy" in assessment.mentions


def test_a_transaction_subreddit_alone_is_enough_to_decline() -> None:
    assessment = assess_brand_binding(
        "Momcozy pump for cheap",
        "Used twice, works great, my baby outgrew it.",
        "r/phclassifieds",
    )
    assert assessment.binding == "brand_unbound"
    assert assessment.reason == "transaction_listing"


def test_real_comparative_post_binds_to_the_competitor() -> None:
    assessment = assess_brand_binding(
        "Willow 3.0 vs Spectra S1",
        "I pumped with both for a month. Willow is quieter but the suction on Spectra "
        "is stronger for me and my supply went up.",
        "r/ExclusivelyPumping",
    )
    assert assessment.binding == "competitor_sentence_bound"
    assert assessment.reason == "competitor_in_product_context"
    assert {"Willow", "Spectra"} <= set(assessment.mentions)


def test_subject_brand_post_binds_to_momcozy() -> None:
    assessment = assess_brand_binding(
        "Momcozy M5 review after 3 months",
        "The wearable pump is fine but the flange sizing guide is confusing.",
        "r/breastfeeding",
    )
    assert assessment.binding == "momcozy_sentence_bound"
    assert assessment.reason == "subject_brand_in_product_context"


def test_post_without_any_brand_is_unbound() -> None:
    assessment = assess_brand_binding(
        "Sleep regression at 4 months",
        "Anyone else's baby waking every two hours?",
        "r/beyondthebump",
    )
    assert assessment.binding == "brand_unbound"
    assert assessment.reason == "no_brand_alias"
    assert assessment.mentions == ()


def test_reason_is_always_populated_for_a_bound_post() -> None:
    """Every non-unbound label must explain itself, because it becomes visible evidence."""
    for title, body, sub in [
        ("Momcozy pump leaks", "The milk leaks when I bend over during pumping.", "r/breastfeeding"),
        ("Elvie vs Momcozy", "I used both pumps; Elvie is quieter.", "r/ExclusivelyPumping"),
    ]:
        assessment = assess_brand_binding(title, body, sub)
        assert isinstance(assessment, BrandAssessment)
        if assessment.is_bound():
            assert assessment.reason.endswith("_in_product_context")
            assert assessment.mentions


def test_fortnite_post_with_willow_and_pump_shotgun_is_not_a_pump_post() -> None:
    """The 2026-11-02 production false positive: Willow + Pump Shotgun + shield potion."""
    assessment = assess_brand_binding(
        "Willow is such a fun drop spot",
        "I landed at Willow, hit a 200 with the Pump Shotgun, then popped a shield "
        "potion and clutched the Victory Royale.",
        "r/FortNiteBR",
    )
    assert assessment.binding == "brand_unbound"
    assert assessment.reason == "non_product_domain_context"
    assert "Willow" in assessment.mentions


def test_buynothing_gift_post_with_a_real_brand_is_not_voc_evidence() -> None:
    """The other 2026-11-02 false positive: a r/PDXBuyNothing giveaway, not a review."""
    assessment = assess_brand_binding(
        "Miscellaneous Baby Stuff",
        "Giving away a Medela pump and some Philips bottles. Porch pickup only.",
        "r/PDXBuyNothing",
    )
    assert assessment.binding == "brand_unbound"
    assert assessment.reason == "transaction_listing"
    assert "Medela" in assessment.mentions


def test_gaming_veto_does_not_block_a_real_pump_comparison() -> None:
    """The veto is context-specific: a normal pumping post still binds."""
    assessment = assess_brand_binding(
        "Willow 3.0 vs Spectra S1",
        "I pumped with both for a month. Willow is quieter but the suction on Spectra "
        "is stronger for me and my supply went up.",
        "r/ExclusivelyPumping",
    )
    assert assessment.binding == "competitor_sentence_bound"
