"""Decide whether a post is actually about a brand, not merely containing its name.

Word-boundary matching alone was not enough. On 2026-10-30 two false bindings
reached the morning card's evidence list:

  - `r/BayAreaBuyers` "1519 Peregrino Way" -> `competitor_sentence_bound`,
    because the listing body says the house is in **Willow Glen**. A San Jose
    neighbourhood matched a pump brand at a word boundary.
  - `r/dubaiclassifieds` "[WTS] Home & Baby Clearout" -> `momcozy_sentence_bound`,
    because a secondhand listing line itemised a "Momcozy S12 Pro Double" among
    used baby goods. The brand is genuinely present; the post is a classified ad,
    not a consumer describing an experience.

So a brand mention is only a *VOC* binding when the post also talks about the
product domain, and when it is not a sale/listing post. Both conditions are
cheap, deterministic and explainable -- which matters because the output feeds a
daily card a business reader trusts without re-checking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .brands import display_name, find_brands

# Domain vocabulary: a post mentioning a brand must contain at least one of these
# to be read as product discussion. Kept deliberately broad on the *product* side
# and narrow on the *"this is a shop"* side.
_DOMAIN_TERMS = (
    "pump", "pumping", "flange", "breast", "milk", "lactation", "nursing",
    "bottle", "steriliz", "sterilis", "wearable", "suction", "letdown",
    "mastitis", "clog", "supply", "wean", "nipple", "shield", "cup",
    "baby", "infant", "newborn", "toddler", "stroller", "carrier", "diaper",
)

# Posts that sell rather than describe. A classified ad is evidence that a product
# exists, not evidence of how it performs.
_TRANSACTION_TERMS = (
    "for sale", "wts", "wtb", "selling", "sell ", "fs:", "price starts",
    "negotiable", "dm me", "pick up only", "resale", "preloved",
)

_TRANSACTION_SUBREDDIT = re.compile(
    r"(classified|forsale|buysell|marketplace|swap|deals?)", re.IGNORECASE
)


@dataclass(frozen=True)
class BrandAssessment:
    """Why a post did or did not bind to a brand, in terms an on-call can read."""

    binding: str
    mentions: tuple[str, ...]
    reason: str

    def is_bound(self) -> bool:
        return self.binding != "brand_unbound"


def assess_brand_binding(title: str, content: str, subreddit: str = "") -> BrandAssessment:
    """Return the binding plus the reason, so a surprising label is explainable."""
    text = f"{title}\n{content}"
    lowered = text.lower()

    hits = find_brands(text)
    if not hits:
        return BrandAssessment("brand_unbound", (), "no_brand_alias")

    mentions = tuple(sorted({display_name(bid) for bid in hits}))

    if not any(term in lowered for term in _DOMAIN_TERMS):
        # e.g. a house in "Willow Glen": the brand word is there, the product
        # domain is not.
        return BrandAssessment("brand_unbound", mentions, "no_product_domain_context")

    if _TRANSACTION_SUBREDDIT.search(subreddit or "") or any(
        term in lowered for term in _TRANSACTION_TERMS
    ):
        # e.g. "[WTS] ... Momcozy S12 Pro": the brand is real, the post is an ad.
        return BrandAssessment("brand_unbound", mentions, "transaction_listing")

    if "momcozy" in hits:
        return BrandAssessment("momcozy_sentence_bound", mentions, "subject_brand_in_product_context")
    return BrandAssessment("competitor_sentence_bound", mentions, "competitor_in_product_context")


__all__ = ["BrandAssessment", "assess_brand_binding"]
