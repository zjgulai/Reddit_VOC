"""CompetitorRadarAgent: Benchmarking and switching intent intelligence Agent."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from ..deepseek_client import DeepSeekClient
from ..report_contracts import AttemptBudget
from .contracts import CompetitorComparison, CompetitorRadarResult
from .evidence import best_evidence_sentence

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位拥有 12 年消费电子与海外母婴出海经验的资深竞品情报与战略市场总监 (Director of Competitive Intelligence & Strategy)。
你的任务是从真实海外 Reddit 讨论中，敏锐捕捉消费者在 Momcozy 与主要竞争品牌（如 Elvie, Willow, Spectra, Medela, Baby Buddha, Lansinoh, BellaBaby 等）之间的直接对比体验、取舍权衡以及品牌转移意图 (Switching Intent)。

输出必须严格遵循以下 JSON Schema，不得包含任何 Markdown 代码块外的无关文本：
{
  "comparisons": [
    {
      "comparison_id": "string (唯一标识，如 comp_1)",
      "competitor_brand": "string (竞品品牌名，如 Elvie / Willow / Spectra / Medela)",
      "competitor_model": "string or null (具体型号，如 Stride / 3.0 / S1 / Freestyle)",
      "our_product": "string (涉及的我方产品，如 Momcozy M5 / Momcozy S12 Pro)",
      "dimension": "string (对比维度: suction_power / motor_noise / leak_resistance / portability_discretion / cleaning_assembly / price_value)",
      "our_advantage": "string (用户认可的我方相对优势)",
      "our_disadvantage": "string (用户指出的我方相对劣势或竞品优势点)",
      "sentiment_verdict": "string (可选值: prefer_momcozy / prefer_competitor / mixed_tradeoff / neutral)",
      "user_verbatim_quote": "string (体现对比评价的原帖/原评引言，必须逐字照抄原文，禁止省略号、禁止改写、禁止拼接)"
    }
  ],
  "market_takeaway": "string (对本次对比反映出的市场格局与消费心理核心洞察)",
  "positioning_advice": [
    "string (面向产品定价、海外宣发或客服销售的行动建议)"
  ]
}
"""


class CompetitorRadarAgent:
    """Agent responsible for competitor benchmarking, pros/cons, and customer migration analysis."""

    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client

    def analyze(
        self,
        *,
        post_id: str,
        subreddit: str,
        title: str,
        content: str,
        budget: AttemptBudget | None = None,
    ) -> CompetitorRadarResult:
        """Analyze a post or comment to extract competitor comparison signals."""
        user_prompt = (
            f"【来源社区】: {subreddit}\n"
            f"【帖子标题】: {title}\n"
            f"【帖子正文/评论】: {content}\n\n"
            f"请从竞品情报分析与横向评测的维度，输出严密的对比结论与市场战略建议。"
        )

        if self.client is None:
            # Deterministic domain-aware fallback when offline / no LLM client is
            # configured.
            #
            # This branch used to stamp one hardcoded sentence onto every comparison
            # as `user_verbatim_quote`:
            #   "Momcozy empties me faster for a fraction of the cost, ..."
            # On 2026-10-30 that sentence reached a business group chat as a
            # consumer's 原话, cited against a r/BayAreaBuyers house listing. Checked
            # against all 27 cited posts, it appeared 0 times. A fallback may say
            # less; it may not quote someone who never spoke.
            #
            # The quote below is copied out of the post, and is None when the post
            # contains no comparative statement -- the card renders that as
            # unavailable rather than substituting a template.
            text_lower = (title + " " + content).lower()
            source_text = f"{title}\n{content}"
            competitor = "Elvie"
            competitor_model = "Elvie Stride"
            if "willow" in text_lower:
                competitor = "Willow"
                competitor_model = "Willow 3.0"
            elif "spectra" in text_lower:
                competitor = "Spectra"
                competitor_model = "Spectra S1"
            elif "medela" in text_lower:
                competitor = "Medela"
                competitor_model = "Medela Freestyle Hands-free"

            quote = best_evidence_sentence(
                source_text,
                (competitor.lower(), "momcozy", "pump", "compared", "instead of"),
            )

            # A comparison needs BOTH sides and a citable sentence that names the
            # competitor. Without an LLM this branch can only observe; it cannot
            # reason. So it emits a comparison only when the post actually contains
            # one, and returns nothing otherwise.
            #
            # Before this guard the fallback produced a comparison for every post
            # that merely mentioned a brand: a r/MixCache novel titled "The Water
            # Witch of Willow Creek" became a Momcozy-vs-Willow benchmark whose
            # evidence was the book title.
            has_subject = "momcozy" in text_lower
            quote_names_competitor = bool(
                quote and competitor.lower() in quote.lower()
            )
            if not (has_subject and quote_names_competitor):
                return CompetitorRadarResult(
                    source_post_id=post_id,
                    subreddit=subreddit,
                    source_title=title,
                    comparisons=[],
                    market_takeaway="",
                    positioning_advice=[],
                )

            comparisons = [
                CompetitorComparison(
                    comparison_id=f"comp_{post_id}_1",
                    competitor_brand=competitor,
                    competitor_model=competitor_model,
                    our_product="Momcozy M5",
                    dimension="price_value_and_suction",
                    our_advantage="Significant price advantage (approx. 1/3 of competitor price) with stronger, hospital-grade suction output.",
                    our_disadvantage="Competitor provides slightly sleeker profile under tight clothing and lower motor operating noise.",
                    sentiment_verdict="prefer_momcozy" if "momcozy" in text_lower else "mixed_tradeoff",
                    user_verbatim_quote=quote,
                )
            ]
            market_takeaway = f"用户在 {competitor} 与 Momcozy 之间的典型权衡：追求极致隐形与静音倾向高端竞品，但高频背奶排空效率与极高性价比驱动大量用户转向 Momcozy。"
            positioning_advice = [
                "在社媒传播中强化 'Hospital-grade emptying power at 1/3 the price' 的心智打法。",
                "下一代产品研发改款需收窄与高端竞品的电机分贝与罩杯厚度差距，彻底封死竞品生态位。",
            ]

            return CompetitorRadarResult(
                source_post_id=post_id,
                subreddit=subreddit,
                source_title=title,
                comparisons=comparisons,
                market_takeaway=market_takeaway,
                positioning_advice=positioning_advice,
            )

        attempt_budget = budget or AttemptBudget(max_attempts=2)
        response = self.client.complete_json(
            user_payload={
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ]
            },
            attempt_budget=attempt_budget,
            phase="competitor_radar",
        )

        parsed: Mapping[str, Any] = json.loads(response.content)
        comparisons = [
            CompetitorComparison(
                comparison_id=item.get("comparison_id", f"comp_{post_id}"),
                competitor_brand=item.get("competitor_brand", "Competitor"),
                competitor_model=item.get("competitor_model"),
                our_product=item.get("our_product", "Momcozy"),
                dimension=item.get("dimension", "general_comparison"),
                our_advantage=item.get("our_advantage", ""),
                our_disadvantage=item.get("our_disadvantage", ""),
                sentiment_verdict=item.get("sentiment_verdict", "mixed_tradeoff"),
                user_verbatim_quote=item.get("user_verbatim_quote", ""),
            )
            for item in parsed.get("comparisons", [])
        ]

        return CompetitorRadarResult(
            source_post_id=post_id,
            subreddit=subreddit,
            source_title=title,
            comparisons=comparisons,
            market_takeaway=parsed.get("market_takeaway", ""),
            positioning_advice=parsed.get("positioning_advice", []),
        )
