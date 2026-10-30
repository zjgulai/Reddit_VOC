"""A quote is only evidence if the cited post actually says it.

On 2026-10-30 the morning card carried, as a consumer's 原话:

    "Momcozy empties me faster for a fraction of the cost..."

cited against `r/BayAreaBuyers` post `1xhbr1l` -- a house listing whose 2,621
characters never mention Momcozy. Checking all 27 competitor comparisons from that
run against their own sources: 0 hits. The string was hardcoded in the offline
agent fallback and stamped onto every row, so an invented user voice was served as
evidence to a business audience.

These tests pin three layers of the fix:
  - the verifier (`evidence.py`) must reject a quote the source does not contain,
    while tolerating presentation-only differences (HTML entities, smart quotes,
    wrapping) so real quotes are not thrown away;
  - the offline fallback must draw its quote from the post, never from a template;
  - the publish-time gate must null any unverifiable quote before the card is built,
    so a future LLM path cannot reintroduce the same failure.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit_voc.agents.evidence import (  # noqa: E402
    MIN_QUOTE_CHARS,
    best_evidence_sentence,
    normalize_text,
    quote_in_source,
    verify_quote,
)
from reddit_voc.agents.competitor_radar import CompetitorRadarAgent  # noqa: E402
from reddit_voc.agents.rnd_voc import RndVocAgent  # noqa: E402

# The exact post that was cited on 2026-10-30, verbatim from the served snapshot.
HOUSE_LISTING = (
    "New Listing, Home For Sale - 1519 Peregrino Way, San Jose, CA 95125 "
    "Processing img jost7azh84yh1... Listed by Mark Chiavetta, Coldwell Banker Realty "
    "Full Disclosure - I am not the listing agent of this property. This is Ramsin "
    "Jacob, a California Real Estate Broker whose website is connected to the local "
    "MLS via an authorized IDX data feed. Description: Rare opportunity to own an "
    "exceptional home in Willow Glen's coveted Dry Creek neighborhood."
)

# The sentence that was actually attributed to it.
INVENTED_QUOTE = (
    "Momcozy empties me faster for a fraction of the cost, "
    "even if competitor is a bit quieter."
)


def _load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "run_daily_t1_pipeline", ROOT / "scripts" / "run_daily_t1_pipeline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quote_in_source_rejects_the_quote_that_started_this() -> None:
    verdict = verify_quote(INVENTED_QUOTE, HOUSE_LISTING)
    assert verdict["status"] == "absent"
    assert quote_in_source(INVENTED_QUOTE, HOUSE_LISTING) is False


def test_quote_in_source_accepts_a_real_substring() -> None:
    real = "Rare opportunity to own an exceptional home in Willow Glen"
    assert quote_in_source(real, HOUSE_LISTING) is True


def test_quote_in_source_tolerates_presentation_differences() -> None:
    """HTML entities, smart quotes and wrapping change bytes, not what was said."""
    source = (
        "I&#39;ve used both pumps. The Momcozy empties me faster and it’s "
        "half the price — honestly a better deal for me."
    )
    quote = "The Momcozy empties me faster and it's half the price - honestly a better deal"
    assert normalize_text("it’s") == "it's"
    assert quote_in_source(quote, source) is True


def test_quote_in_source_rejects_short_fragments() -> None:
    """A 3-word fragment matches almost any review, so it carries no weight."""
    assert quote_in_source("it broke", "it broke yesterday, sad") is False
    too_short = "ok yes"
    assert len(too_short) < MIN_QUOTE_CHARS
    assert verify_quote(too_short, "ok yes indeed").get("status") in {"too_short", "absent"}


def test_verify_quote_distinguishes_empty_from_absent() -> None:
    assert verify_quote("", HOUSE_LISTING)["status"] == "empty"
    assert verify_quote("   ", HOUSE_LISTING)["status"] == "empty"
    assert verify_quote(INVENTED_QUOTE, HOUSE_LISTING)["status"] == "absent"


def test_best_evidence_sentence_returns_source_text_or_none() -> None:
    source = (
        "Unrelated opening line that says nothing useful.\n"
        "Every time I lean forward the milk leaks out of the top seal and ruins my shirt.\n"
    )
    picked = best_evidence_sentence(source, ("leak", "spill"))
    assert picked is not None
    assert picked in source, "the picked sentence must be copied verbatim from the source"
    assert "leak" in picked.lower()

    assert best_evidence_sentence(source, ("nonexistent-term",)) is None


def test_competitor_fallback_never_invents_a_quote() -> None:
    """The regression itself: the offline path must not stamp a template quote."""
    agent = CompetitorRadarAgent(client=None)
    result = agent.analyze(
        post_id="1xhbr1l",
        subreddit="r/BayAreaBuyers",
        title="New Listing, Home For Sale - 1519 Peregrino Way",
        content=HOUSE_LISTING,
    )
    # A house listing contains no Momcozy-vs-competitor comparison, so the honest
    # answer is no comparison at all -- not a comparison padded with a quote
    # scraped from the listing text.
    assert result.comparisons == [], (
        f"a non-comparative post must not yield a comparison: {result.comparisons}"
    )
    assert "empties me faster for a fraction of the cost" not in str(result.to_dict())


def test_competitor_fallback_quotes_a_real_comparative_post() -> None:
    agent = CompetitorRadarAgent(client=None)
    title = "Momcozy M5 vs Willow 3.0 after three months"
    body = (
        "I tried both. Momcozy empties me faster and costs a third of the Willow, "
        "though the Willow is quieter."
    )
    result = agent.analyze(
        post_id="p-real", subreddit="r/ExclusivelyPumping", title=title, content=body
    )
    quote = result.comparisons[0].user_verbatim_quote
    assert quote, "a genuinely comparative post should yield a citable quote"
    assert quote_in_source(quote, f"{title}\n{body}")


def test_rnd_fallback_never_invents_a_quote() -> None:
    agent = RndVocAgent(client=None)
    body = (
        "I bought this pump last week. Every time I lean forward to pick up my baby, "
        "milk leaks right out of the top seal. Very frustrating."
    )
    result = agent.analyze(
        post_id="p-leak", subreddit="r/ExclusivelyPumping",
        title="Pump leaks when I bend over", content=body,
    )
    quote = result.defects[0].user_quote
    assert quote
    assert quote_in_source(quote, f"Pump leaks when I bend over\n{body}"), (
        f"rnd fallback produced a quote absent from the source: {quote!r}"
    )


def test_rnd_fallback_returns_none_when_nothing_is_quotable() -> None:
    """No quotable sentence is better than an invented one."""
    agent = RndVocAgent(client=None)
    result = agent.analyze(
        post_id="p-noise", subreddit="r/ExclusivelyPumping",
        title="noisy", content="noisy",
    )
    quote = result.defects[0].user_quote
    assert quote is None or quote_in_source(quote, "noisy\nnoisy")


def test_pipeline_gate_drops_unverifiable_quotes_and_records_why() -> None:
    """The publish-time gate: an unverifiable quote is nulled, not rendered."""
    pipeline = _load_pipeline()

    class _Post:
        def __init__(self, pid: str, title: str, selftext: str) -> None:
            self.post_id = pid
            self.title = title
            self.selftext = selftext

    class _Comparison:
        def __init__(self, quote):
            self.user_verbatim_quote = quote

    class _RadarResult:
        def __init__(self, pid, quote):
            self.source_post_id = pid
            self.comparisons = [_Comparison(quote)]

    class _Batch:
        def __init__(self, quotes):
            self.competitor_radar_results = quotes
            self.rnd_voc_results = []

    posts = [
        _Post("p1", "Home for sale in Willow Glen", "A nice house, nothing about pumps at all."),
    ]
    good = "Home for sale in Willow Glen"
    bad = "Momcozy empties me faster for a fraction of the cost."
    batch = _Batch([_RadarResult("p1", good), _RadarResult("p1", bad)])

    receipt = pipeline._verify_agent_evidence(batch, posts)

    assert receipt["checked"] == 2
    assert receipt["dropped"] == 1
    assert receipt["kept"] == 1
    assert receipt["examples"][0]["status"] == "absent"

    # The batch dataclass is frozen, so the scrubber returns rebuilt records.
    # The citable quote survives; the invented one is nulled rather than replaced.
    kept = [
        c.user_verbatim_quote
        for r in receipt["competitor_radar_results"]
        for c in r.comparisons
    ]
    assert good in kept
    assert bad not in kept
    assert None in kept
