"""Single source of truth for brand identity and matching.

Before this module there were three mutually inconsistent brand lists:

  - `src/reddit_voc/keywords.py`      : 63 competitor names (the richest)
  - `config/product_entities/...json` : 21 comparison aliases
  - `scripts/recompute_derivatives.py`: 6 hardcoded ids, and it matched with
    `b.lower().replace(" ")` so multi-word names could never hit

The practical damage: 55 posts labelled `competitor_sentence_bound` named brands
that simply were not in the 6-item set (Boppy 32, Baby Brezza 4, Philips Avent 4,
eufy 4, ...), so the competitor analysis silently saw almost nothing.

This module loads `config/brands.json` and exposes one normalised matcher. Matching
is word-boundary based (the same class of bug as `"rust" in "frustrated"`), and
every alias resolves to a canonical brand id so counts aggregate correctly.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path


def _resolve_registry_path() -> Path:
    """Locate config/brands.json regardless of how the package is deployed.

    Locally the module lives at `<repo>/src/reddit_voc/brands.py`, but in production
    the package is copied to `/opt/echo-agent-bot/reddit_voc/brands.py`. Hardcoding
    `parents[2]` therefore resolved to `/opt` on the server. Walk up from the module
    and stop at the first directory that actually contains the registry, with an
    explicit env override for unusual layouts.
    """
    override = os.getenv("ECHO_BRAND_REGISTRY", "").strip()
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "brands.json"
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[2] / "config" / "brands.json"


REGISTRY_PATH = _resolve_registry_path()


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


@lru_cache(maxsize=1)
def load_registry() -> dict:
    """Load and index the brand registry once per process."""
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    alias_to_brand: dict[str, str] = {}
    brand_meta: dict[str, dict] = {}
    patterns: list[tuple[re.Pattern[str], str]] = []

    for brand in payload.get("brands", []):
        brand_id = brand["brand_id"]
        brand_meta[brand_id] = {
            "brand_id": brand_id,
            "display_name": brand.get("display_name") or brand_id,
            "role": brand.get("role") or "competitor",
        }
        for alias in brand.get("aliases", []):
            key = _normalise(alias)
            if not key:
                continue
            alias_to_brand.setdefault(key, brand_id)
            patterns.append((
                re.compile(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])"),
                brand_id,
            ))

    # Longest alias first so "Medela Freestyle" wins over "Medela".
    patterns.sort(key=lambda item: -len(item[0].pattern))
    return {
        "alias_to_brand": alias_to_brand,
        "brand_meta": brand_meta,
        "patterns": patterns,
        "subject_ids": {
            bid for bid, meta in brand_meta.items() if meta["role"] == "subject"
        },
        "competitor_ids": {
            bid for bid, meta in brand_meta.items() if meta["role"] == "competitor"
        },
    }


def brand_id_for(alias: str) -> str | None:
    return load_registry()["alias_to_brand"].get(_normalise(alias))


def display_name(brand_id: str) -> str:
    meta = load_registry()["brand_meta"].get(brand_id)
    return meta["display_name"] if meta else brand_id.replace("_", " ").title()


def competitor_brand_ids() -> set[str]:
    return set(load_registry()["competitor_ids"])


def subject_brand_ids() -> set[str]:
    return set(load_registry()["subject_ids"])


def normalize_mention(alias: str) -> str | None:
    """Map a free-text brand mention to its canonical id (None if unknown)."""
    return brand_id_for(alias)


def find_brands(text: str) -> dict[str, list[str]]:
    """Return {brand_id: [matched surface forms]} using word-boundary matching."""
    registry = load_registry()
    lowered = _normalise(text or "")
    if not lowered:
        return {}
    found: dict[str, list[str]] = {}
    consumed: list[tuple[int, int]] = []
    for pattern, brand_id in registry["patterns"]:
        for match in pattern.finditer(lowered):
            start, end = match.span()
            # Skip overlaps already claimed by a longer alias.
            if any(s <= start and end <= e for s, e in consumed):
                continue
            consumed.append((start, end))
            found.setdefault(brand_id, []).append(match.group(0))
    return found


def mentioned_brand_ids(mentions: list[str]) -> set[str]:
    """Canonical ids for a list of raw mention strings."""
    ids: set[str] = set()
    for mention in mentions or []:
        bid = brand_id_for(mention)
        if bid:
            ids.add(bid)
    return ids


def has_competitor_mention(mentions: list[str]) -> bool:
    return bool(mentioned_brand_ids(mentions) & competitor_brand_ids())
