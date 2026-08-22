from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .keywords import KeywordMatch, match_keywords


PAIN_POINTS = {
    "output_supply": ["output", "supply", "not emptying", "emptying", "supply drop", "low supply"],
    "leakage": ["leak", "leaking", "spill", "spilled"],
    "fit_comfort": ["flange", "insert", "elastic nipples", "nipple", "pain", "suction", "hurts", "fit", "sizing"],
    "operations": [
        "cleaning",
        "parts",
        "battery",
        "charge",
        "charging",
        "motor",
        "app",
        "bluetooth",
        "noise",
        "loud",
        "dishwasher",
        "sanitize",
        "sterilize",
        "drying",
        "mold",
        "rust",
    ],
    "support": ["warranty", "customer service", "replacement", "return", "refund"],
    "health": ["mastitis", "clogged duct", "clog"],
    "work_scenario": ["return to work", "pumping at work", "commute", "travel", "daycare"],
    "family_scenario": ["twins", "multiples", "nicu", "postpartum", "registry", "first time mom", "ftm"],
    "insurance": ["insurance"],
}

NEGATIVE_TERMS = [
    "hate",
    "hurt",
    "hurts",
    "pain",
    "leak",
    "leaking",
    "terrible",
    "awful",
    "refund",
    "return",
    "broken",
    "replacement",
    "clogged",
    "mastitis",
    "mold",
    "rust",
]

POSITIVE_TERMS = ["love", "great", "works", "recommend", "helpful", "easy", "favorite", "worth it"]

_VALID_SENTIMENTS = {"positive", "negative", "neutral"}
_VALID_TOPICS = {
    "competitor_comparison", "insurance", "purchase_decision", "customer_service",
    "work_scenario", "troubleshooting", "product_evaluation", "other",
}
_VALID_SEVERITIES = {"high", "medium", "low"}

_DEEPSEEK_ANALYSIS_URL = "https://api.deepseek.com/chat/completions"
_DEEPSEEK_ANALYSIS_MODEL = "deepseek-chat"
_DEEPSEEK_ANALYSIS_SYSTEM = """\
You are a brand VOC (Voice of Customer) analyst specializing in baby/maternity products, especially Momcozy breast pumps.

Analyze each Reddit post/comment and return structured JSON. Be accurate about sentiment — distinguish between:
- Users asking for help/recommendations (neutral, not positive)  
- Users complaining about problems (negative)
- Users sharing positive experiences (positive)

Return exactly this JSON shape:
{"results":[{"id":"...","sentiment":"positive|negative|neutral","sentiment_score":-1.0~1.0,"topic":"competitor_comparison|insurance|purchase_decision|customer_service|work_scenario|troubleshooting|product_evaluation|other","severity":"high|medium|low","pain_points":["..."]}]}

Topic definitions:
- competitor_comparison: comparing Momcozy with other brands
- insurance: breast pump insurance coverage
- purchase_decision: asking for recommendations, deciding what to buy
- customer_service: warranty, return, customer support issues
- work_scenario: pumping at work, work-life balance
- troubleshooting: device problems, technical issues
- product_evaluation: reviews, sharing experience
- other: unrelated or unclear

Severity: high=health/safety issue or device failure, medium=inconvenience or moderate issue, low=general inquiry

Pain points (only if explicitly mentioned): output_supply, leakage, fit_comfort, operations, support, health, work_scenario, family_scenario, insurance
"""


@dataclass(frozen=True)
class Analysis:
    sentiment_label: str
    sentiment_score: float
    topic: str
    severity: str
    confidence: float
    keyword_match: KeywordMatch
    pain_points: list[str]


@dataclass(frozen=True)
class DeepSeekAnalysisItem:
    item_id: str
    text: str


@dataclass(frozen=True)
class DeepSeekAnalysisResult:
    item_id: str
    sentiment_label: str
    sentiment_score: float
    topic: str
    severity: str
    pain_points: list[str]
    provider_call: bool = True


def analyze_text(text: str) -> Analysis:
    lowered = text.lower()
    keyword_match = match_keywords(text)
    pain_points = [
        label
        for label, terms in PAIN_POINTS.items()
        if any(term in lowered for term in terms)
    ]

    negative_hits = sum(1 for term in NEGATIVE_TERMS if term in lowered)
    positive_hits = sum(1 for term in POSITIVE_TERMS if term in lowered)
    raw_score = positive_hits - negative_hits
    if raw_score > 0:
        sentiment_label = "positive"
    elif raw_score < 0:
        sentiment_label = "negative"
    else:
        sentiment_label = "neutral"

    if keyword_match.competitors and (keyword_match.brands or " vs " in lowered or "versus" in lowered):
        topic = "competitor_comparison"
    elif "insurance" in lowered:
        topic = "insurance"
    elif any(term in lowered for term in ["buy", "choose", "recommend", "option"]):
        topic = "purchase_decision"
    elif "customer service" in lowered or "warranty" in lowered:
        topic = "customer_service"
    elif "return to work" in lowered or "pumping at work" in lowered:
        topic = "work_scenario"
    elif pain_points:
        topic = "troubleshooting"
    else:
        topic = "product_evaluation" if keyword_match.is_relevant else "other"

    severity = "low"
    if any(point in pain_points for point in ["health", "support"]):
        severity = "high"
    elif sentiment_label == "negative" or pain_points:
        severity = "medium"

    confidence = 0.4
    if keyword_match.brands or keyword_match.categories:
        confidence += 0.2
    if pain_points:
        confidence += 0.2
    if keyword_match.excluded:
        confidence = 0.1

    return Analysis(
        sentiment_label=sentiment_label,
        sentiment_score=max(-1.0, min(1.0, raw_score / 3)),
        topic=topic,
        severity=severity,
        confidence=round(min(confidence, 0.95), 2),
        keyword_match=keyword_match,
        pain_points=sorted(pain_points),
    )


def analyze_batch_with_deepseek(
    items: Sequence[DeepSeekAnalysisItem],
    *,
    timeout: float = 60.0,
) -> list[DeepSeekAnalysisResult]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key or not items:
        return []

    user_payload = [
        {"id": item.item_id, "text": item.text[:1000]}
        for item in items
    ]
    request_body = {
        "model": _DEEPSEEK_ANALYSIS_MODEL,
        "messages": [
            {"role": "system", "content": _DEEPSEEK_ANALYSIS_SYSTEM},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    req = Request(
        _DEEPSEEK_ANALYSIS_URL,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "RedditVOC/1.0 DeepSeekAnalysis",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        content = parsed["choices"][0]["message"]["content"]
        data = json.loads(content)
    except (HTTPError, URLError, TimeoutError, OSError, KeyError, IndexError, json.JSONDecodeError):
        return []

    results: list[DeepSeekAnalysisResult] = []
    expected_ids = {item.item_id for item in items}
    seen_ids: set[str] = set()
    for entry in data.get("results", []):
        try:
            item_id = str(entry["id"])
            if item_id not in expected_ids or item_id in seen_ids:
                continue
            sentiment = str(entry.get("sentiment", "neutral"))
            if sentiment not in _VALID_SENTIMENTS:
                sentiment = "neutral"
            score = float(entry.get("sentiment_score", 0.0))
            score = max(-1.0, min(1.0, score))
            topic = str(entry.get("topic", "other"))
            if topic not in _VALID_TOPICS:
                topic = "other"
            severity = str(entry.get("severity", "medium"))
            if severity not in _VALID_SEVERITIES:
                severity = "medium"
            pain_points = [
                p for p in (entry.get("pain_points") or [])
                if isinstance(p, str) and p in PAIN_POINTS
            ]
            results.append(DeepSeekAnalysisResult(
                item_id=item_id,
                sentiment_label=sentiment,
                sentiment_score=score,
                topic=topic,
                severity=severity,
                pain_points=sorted(pain_points),
            ))
            seen_ids.add(item_id)
        except (KeyError, TypeError, ValueError):
            continue
    return results
