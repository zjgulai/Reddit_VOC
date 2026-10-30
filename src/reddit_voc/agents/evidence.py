"""Evidence discipline for Agent output: a quote must exist in the source it cites.

Why this module exists
----------------------
On 2026-10-30 the morning card cited, as a consumer's "原话":

    "Momcozy empties me faster for a fraction of the cost..."

against `r/BayAreaBuyers` post `1xhbr1l`, a house listing. Checked against the
post's own 2,621 characters, that quote (and the 26 other competitor quotes from
the same run) appear **0 times**. The string was hardcoded in
`competitor_radar.py`'s offline fallback and stamped onto every comparison, so a
business reader was handed an invented user voice as evidence.

The same failure mode applies to a language model that paraphrases instead of
quoting. So verification cannot live in one code path -- it has to be a property
the pipeline checks on every artifact before publish.

Contract
--------
`verify_quote` answers one question: *does this string occur in this source text,
after normalizing the differences that are presentation rather than substance?*
Normalization collapses whitespace, folds smart quotes/dashes to ASCII, and
lowercases -- because Reddit HTML entities (`&#39;`), typographic apostrophes and
line wrapping all change bytes without changing what the consumer said.

Nothing here decides whether a claim is *good*; it decides whether it is
*citable*. A failed check must surface as `unavailable`, never as a silent
substitute.
"""

from __future__ import annotations

import html
import re
import unicodedata

# A quote shorter than this carries no evidentiary weight even if it matches: "ok",
# "yes", "it broke" are substrings of almost any review.
MIN_QUOTE_CHARS = 24

_WHITESPACE = re.compile(r"\s+")
_TYPOGRAPHIC = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", "…": "...",
})


def normalize_text(value: str) -> str:
    """Fold presentation differences: entities, typographic marks, whitespace, case."""
    text = html.unescape(value or "")
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TYPOGRAPHIC)
    text = text.replace("​", "")  # zero-width space
    text = _WHITESPACE.sub(" ", text)
    return text.strip().lower()


def _strip_wrapping(quote: str) -> str:
    text = quote.strip()
    # Models and templates often hand back a quoted string with its own punctuation.
    for left, right in (('"', '"'), ("'", "'"), ("“", "”"), ("«", "»")):
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[1:-1].strip()
    return text


def quote_in_source(quote: str, source_text: str, *, min_chars: int = MIN_QUOTE_CHARS) -> bool:
    """True when `quote` is a real substring of `source_text` after normalization."""
    needle = normalize_text(_strip_wrapping(quote))
    if len(needle) < min_chars:
        return False
    return needle in normalize_text(source_text)


def _sentences(source_text: str) -> list[str]:
    text = html.unescape(source_text or "")
    text = unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHIC)
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def best_evidence_sentence(
    source_text: str,
    keywords: tuple[str, ...],
    *,
    min_chars: int = MIN_QUOTE_CHARS,
) -> str | None:
    """Return a real sentence from the source that mentions one of `keywords`.

    This is the only honest way for a non-LLM path to produce a quote: copy a
    sentence the consumer actually wrote. Returns None when no sentence qualifies,
    which callers must render as "unavailable" rather than filling in a template.
    """
    lowered = [k.lower() for k in keywords if k]
    if not lowered:
        return None
    for sentence in _sentences(source_text):
        if len(sentence) < min_chars:
            continue
        haystack = normalize_text(sentence)
        if any(keyword in haystack for keyword in lowered):
            return sentence
    return None


def verify_quote(quote: str, source_text: str, *, min_chars: int = MIN_QUOTE_CHARS) -> dict:
    """Describe whether a quote is citable, for artifacts and receipts.

    Returns {'status': 'verified'|'absent'|'too_short'|'empty', 'normalized_chars': n}.
    The extra fields exist so a reviewer can tell "the model paraphrased" from
    "the field was blank" without re-running the check.
    """
    stripped = _strip_wrapping(quote or "")
    normalized = normalize_text(stripped)
    if not normalized:
        return {"status": "empty", "normalized_chars": 0}
    if len(normalized) < min_chars:
        return {"status": "too_short", "normalized_chars": len(normalized)}
    if normalized in normalize_text(source_text):
        return {"status": "verified", "normalized_chars": len(normalized)}
    return {"status": "absent", "normalized_chars": len(normalized)}


__all__ = [
    "MIN_QUOTE_CHARS",
    "best_evidence_sentence",
    "normalize_text",
    "quote_in_source",
    "verify_quote",
]
