from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


DEFAULT_BRANDS = {
    "Momcozy": [
        "momcozy",
        "mom cozy",
        "momcozi",
        "momcozie",
        "momcozy pump",
        "momcozy pumps",
        "momcozy wearable",
        "momcozy bottle washer",
        "momcozy carrier",
    ],
}

DEFAULT_PRODUCTS = {
    "Momcozy": [
        "M5",
        "M6",
        "M9",
        "S9",
        "S9 Pro",
        "S12",
        "S12 Pro",
        "V1",
        "V1 Pro",
        "V2",
        "V2 Pro",
        "Air 1",
        "Mobile Flow",
        "W1",
        "KleanPal",
        "KleanPal Pro",
        "Klean Pal",
        "Klean Pal Pro",
        "D8",
        "DinerPal",
        "PureHug",
        "Pure Hug",
        "WeeSnug",
        "Wee Snug",
        "BumpEase",
        "Ergonest",
        "Dreamlign",
        "Ergowrap",
    ],
}

DEFAULT_CATEGORY = [
    "breast pump",
    "wearable breast pump",
    "wearable pump",
    "wearables",
    "hands-free pump",
    "hands free pump",
    "hands-free breast pump",
    "in-bra pump",
    "cordless pump",
    "portable pump",
    "collection cups",
    "pumping bra",
    "pump parts",
    "flange inserts",
    "flange insert",
    "primary pump",
    "wall pump",
    "hospital grade pump",
    "hospital grade",
    "manual pump",
    "electric pump",
    "milk collector",
    "breast milk cooler",
    "milk storage",
    "baby bottle washer",
    "bottle washer",
    "countertop bottle washer",
    "bottle washer sterilizer",
    "bottle sterilizer",
    "sterilizer dryer",
    "sterilizer and dryer",
    "bottle dryer",
    "bottle warmer",
    "pump parts washer",
    "descaling tablets",
    "detergent pods",
]

DEFAULT_CONTEXTUAL_CATEGORY = [
    "baby carrier",
    "structured carrier",
    "wrap carrier",
    "stretchy wrap",
    "baby wrap",
    "newborn carrier",
    "hip seat",
    "babywearing",
    "carrier fit check",
    "high chair",
    "feeding chair",
    "learning tower",
    "pregnancy pillow",
    "nursing pillow",
    "belly band",
    "maternity belly band",
    "postpartum wrap",
    "postpartum belly band",
    "sound machine",
    "white noise machine",
    "baby monitor",
    "diaper bag",
]

DEFAULT_COMPETITORS = [
    "Elvie",
    "Willow",
    "eufy",
    "eufy S1",
    "eufy S1 Pro",
    "eufy E10",
    "eufy E20",
    "Medela",
    "Medela Freestyle",
    "Medela InBra",
    "Spectra",
    "Lansinoh",
    "Lansinoh DiscreetDuo",
    "Motif",
    "Motif Aura",
    "Zomee",
    "Freemie",
    "Pumpables",
    "Baby Buddha",
    "Imani",
    "Legendairy Milk",
    "Fraupow",
    "Tommee Tippee",
    "YOUHA",
    "MomMed",
    "TSRETE",
    "Bellababy",
    "Philips Avent",
    "Ardo",
    "FetalPlus",
    "Fetal Plus",
    "Baby Brezza",
    "Baby Brezza Washer Pro",
    "Papablic",
    "Dr. Brown",
    "Dr. Brown's",
    "Grownsy",
    "Maymom",
    "Nenesupply",
    "BeauGen",
    "Haakaa",
    "Ceres Chill",
    "Kindred Bravely",
    "Boppy",
    "My Brest Friend",
    "Ergobaby",
    "Ergo Embrace",
    "BabyBjorn",
    "Baby Bjorn",
    "Tushbaby",
    "WildBird",
    "Solly Baby",
    "Boba",
    "Tula",
    "Lillebaby",
    "LennyLamb",
    "Didymos",
    "Hatch",
    "Dreamegg",
    "Yogasleep",
    "Stokke",
    "Abiie",
    "Graco",
    "Skip Hop",
    "Lalo",
]

DEFAULT_EXCLUDES = ["BMW M5", "BMW M6", "BMW M9", "Samsung S9", "Galaxy S9"]
MODEL_CONTEXT = [
    "pump",
    "breast",
    "wearable",
    "nursing",
    "milk",
    "momcozy",
    "bottle",
    "washer",
    "sterilizer",
    "carrier",
    "babywearing",
    "high chair",
    "belly band",
    "pregnancy pillow",
    "nursing pillow",
]


def keyword_rules_snapshot() -> dict[str, object]:
    return {
        "brands": DEFAULT_BRANDS,
        "products": DEFAULT_PRODUCTS,
        "category": DEFAULT_CATEGORY,
        "contextual_category": DEFAULT_CONTEXTUAL_CATEGORY,
        "competitors": DEFAULT_COMPETITORS,
        "excludes": DEFAULT_EXCLUDES,
        "model_context": MODEL_CONTEXT,
    }


def keyword_rules_sha256() -> str:
    payload = json.dumps(
        keyword_rules_snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class KeywordMatch:
    brands: list[str]
    products: list[str]
    categories: list[str]
    competitors: list[str]
    excluded: bool

    @property
    def matched_terms(self) -> list[str]:
        return self.brands + self.products + self.categories + self.competitors

    @property
    def is_relevant(self) -> bool:
        return bool(self.matched_terms) and not self.excluded


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"(?<![A-Za-z0-9])" + re.escape(phrase.lower()) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text.lower()) is not None


def _has_model_context(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in MODEL_CONTEXT)


def match_keywords(text: str) -> KeywordMatch:
    excluded = any(_contains_phrase(text, phrase) for phrase in DEFAULT_EXCLUDES)
    brands: list[str] = []
    products: list[str] = []
    categories: list[str] = []
    competitors: list[str] = []

    for brand, variants in DEFAULT_BRANDS.items():
        if any(_contains_phrase(text, variant) for variant in variants):
            brands.append(brand)

    for brand, product_terms in DEFAULT_PRODUCTS.items():
        for product in product_terms:
            if _contains_phrase(text, product) and (brand in brands or _has_model_context(text)):
                products.append(product)

    for category in DEFAULT_CATEGORY:
        if _contains_phrase(text, category):
            categories.append(category)

    for competitor in DEFAULT_COMPETITORS:
        if _contains_phrase(text, competitor):
            competitors.append(competitor)

    if brands or products or competitors:
        for category in DEFAULT_CONTEXTUAL_CATEGORY:
            if _contains_phrase(text, category):
                categories.append(category)

    return KeywordMatch(
        brands=sorted(set(brands)),
        products=sorted(set(products)),
        categories=sorted(set(categories)),
        competitors=sorted(set(competitors)),
        excluded=excluded,
    )
