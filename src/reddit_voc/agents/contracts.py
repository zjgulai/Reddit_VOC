"""Contracts and models for specialized Reddit VOC AI Agents."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ContentTopicIdea:
    """A high-converting social media topic derived from a consumer post."""

    topic_id: str
    target_platform: str  # e.g., "tiktok", "reels", "xiaohongshu"
    target_audience: str
    core_pain_point: str
    hook_3s: str
    story_conflict: str
    solution_angle: str
    call_to_action: str
    visual_scene_script: Sequence[Mapping[str, str]]
    hashtags: Sequence[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContentScoutResult:
    """The output payload from ContentScoutAgent."""

    source_post_id: str
    subreddit: str
    source_title: str
    ideas: Sequence[ContentTopicIdea]
    reasoning_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ==========================================
# RndVocAgent Contracts
# ==========================================

@dataclass(frozen=True)
class RndDefectFinding:
    """A specific product defect, structural flaw, or failure mode identified from VOC."""

    defect_id: str
    category: str  # e.g., "sealing_leakage", "motor_noise", "suction_failure", "battery_charging", "material_wear", "usability_assembly"
    component: str  # e.g., "collection cup silicone flange", "duckbill valve", "motor unit", "diaphragm"
    severity: str  # "critical", "major", "minor"
    symptom: str  # Consumer-described defect symptom
    root_cause_hypothesis: str  # Engineering analysis of potential root cause
    suggested_action: str  # Recommended engineering/design CAPA
    frequency_signal: str  # "isolated", "recurring", "common_complaint"
    user_quote: str  # Direct verbatim evidence from the Reddit post/comment
    user_workaround: str | None = None  # Coping behavior used by the consumer

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RndVocResult:
    """The output payload from RndVocAgent."""

    source_post_id: str
    subreddit: str
    source_title: str
    defects: Sequence[RndDefectFinding]
    engineering_summary: str
    urgency_rating: str  # "P0", "P1", "P2", "P3"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ==========================================
# CompetitorRadarAgent Contracts
# ==========================================

@dataclass(frozen=True)
class CompetitorComparison:
    """A head-to-head comparison between Momcozy and a competing brand/model."""

    comparison_id: str
    competitor_brand: str  # e.g., "Elvie", "Willow", "Spectra", "Medela"
    competitor_model: str | None  # e.g., "Elvie Stride", "Willow 3.0", "Spectra S1"
    our_product: str  # e.g., "Momcozy M5", "Momcozy S12 Pro", "Momcozy Mobile Style"
    dimension: str  # e.g., "suction_power", "motor_noise", "leak_resistance", "portability_discretion", "cleaning_assembly", "price_value"
    our_advantage: str  # Competitive strengths mentioned by consumer
    our_disadvantage: str  # Areas where competitor outperformed
    sentiment_verdict: str  # "prefer_momcozy", "prefer_competitor", "mixed_tradeoff", "neutral"
    user_verbatim_quote: str  # Key quote capturing comparative sentiment

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompetitorRadarResult:
    """The output payload from CompetitorRadarAgent."""

    source_post_id: str
    subreddit: str
    source_title: str
    comparisons: Sequence[CompetitorComparison]
    market_takeaway: str
    positioning_advice: Sequence[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

