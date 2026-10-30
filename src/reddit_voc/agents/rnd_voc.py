"""RndVocAgent: Hardware defect discovery and engineering CAPA recommendation Agent."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from ..deepseek_client import DeepSeekClient
from ..report_contracts import AttemptBudget
from .contracts import RndDefectFinding, RndVocResult
from .evidence import MIN_QUOTE_CHARS, best_evidence_sentence

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位拥有 15 年消费电子硬件研发与可靠性工程经验的资深质量总监 (VP of Hardware Quality & Reliability)。
你的职责是从真实的海外 Reddit 消费者声音（VOC）中，精准识别产品在实际使用中的硬件缺陷、结构设计隐患、材质老化破损、电气噪音与装配人机工效问题。
基于识别出的缺陷，你必须以第一性原理分析可能的工程根本原因 (Root Cause Hypothesis)，并给出切实可行的工程整改与纠正预防措施 (CAPA / Engineering Action)。

输出必须严格遵循以下 JSON Schema，不得包含任何 Markdown 代码块外的无关文本：
{
  "defects": [
    {
      "defect_id": "string (唯一标识，如 defect_1)",
      "category": "string (可选值: sealing_leakage / motor_noise / suction_failure / battery_charging / material_wear / usability_assembly)",
      "component": "string (具体硬件构件，如 collection cup silicone flange / duckbill valve / motor pump unit / diaphragm)",
      "severity": "string (critical / major / minor)",
      "symptom": "string (消费者表述的直观故障现象)",
      "root_cause_hypothesis": "string (工程根本原因假设分析)",
      "suggested_action": "string (具体工程设计优化或改款建议)",
      "frequency_signal": "string (isolated / recurring / common_complaint)",
      "user_quote": "string (帖子或评论中的原文证据)",
      "user_workaround": "string or null (消费者自行采取的临时应对办法)"
    }
  ],
  "engineering_summary": "string (对该发声涉及问题的工程综合研判)",
  "urgency_rating": "string (P0 / P1 / P2 / P3)"
}
"""


class RndVocAgent:
    """Agent responsible for identifying hardware failure modes and engineering solutions."""

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
    ) -> RndVocResult:
        """Analyze a post or comment to extract engineering defect findings."""
        user_prompt = (
            f"【来源社区】: {subreddit}\n"
            f"【帖子标题】: {title}\n"
            f"【帖子正文/评论】: {content}\n\n"
            f"请从硬件可靠性工程与产品改款的角度，进行严密的工程失效分析与整改建议输出。"
        )

        if self.client is None:
            # Deterministic domain-aware fallback when offline / no LLM client is
            # configured.
            #
            # The quotes here used to be hardcoded English sentences that no user
            # ever wrote: the 2026-10-30 morning card cited them as 原话 and they
            # appeared 0 times in the cited posts. A fallback may be less insightful
            # than a model, but it may not invent evidence -- so every quote below is
            # now copied out of the post itself, and is None when the post contains
            # nothing quotable (the card renders that as unavailable).
            text_lower = (title + " " + content).lower()
            source_text = f"{title}\n{content}"
            if "leak" in text_lower or "spill" in text_lower:
                defects = [
                    RndDefectFinding(
                        defect_id=f"defect_{post_id}_1",
                        category="sealing_leakage",
                        component="collection cup silicone flange & seal ring",
                        severity="major",
                        symptom="Milk leaks out of the top silicone seal when bending over or tilting forward.",
                        root_cause_hypothesis="Under forward tilt, hydrostatic pressure exceeds the friction seal retention limit; lack of positive interlocking latch on cup lid.",
                        suggested_action="Redesign silicone flange with dual-lip sealing profile and add mechanical tactile snap latch to reinforce top cover under dynamic movement.",
                        frequency_signal="common_complaint",
                        user_quote=best_evidence_sentence(
                            source_text, ("leak", "spill", "leaking", "drip")
                        ),
                        user_workaround=None,
                    )
                ]
                summary = "典型的穿戴式吸奶器动态倾斜密封失效。需重点通过双唇密封结合卡扣锁止方案消除倾斜漏奶。"
                urgency = "P1"
            elif "noise" in text_lower or "loud" in text_lower or "squeak" in text_lower:
                defects = [
                    RndDefectFinding(
                        defect_id=f"defect_{post_id}_1",
                        category="motor_noise",
                        component="micro diaphragm pump motor assembly",
                        severity="major",
                        symptom="Motor produces loud mechanical pulsing noise and occasional squeaking during pumping.",
                        root_cause_hypothesis="Insufficient acoustic isolation damping between motor housing and outer chassis, causing resonance amplification against bra fabric.",
                        suggested_action="Incorporate silicone vibration dampening grommets on motor mounting posts and add acoustic baffling foam inside outer casing.",
                        frequency_signal="recurring",
                        user_quote=best_evidence_sentence(
                            source_text, ("noise", "loud", "squeak", "squeal", "noisy")
                        ),
                        user_workaround=None,
                    )
                ]
                summary = "电机共振与高频机械噪声问题。需优化电机减震阻尼并降低声学泄露。"
                urgency = "P2"
            else:
                defects = [
                    RndDefectFinding(
                        defect_id=f"defect_{post_id}_1",
                        category="usability_assembly",
                        component="modular valve & diaphragm interface",
                        severity="minor",
                        symptom="General wear and difficulty ensuring airtight fit during daily reassembly.",
                        root_cause_hypothesis="Silicone fatigue after repeated steam sterilization cycles, leading to micro-clearance air gaps.",
                        suggested_action="Specify higher tear-strength medical silicone and add clear visual alignment markers on mating parts.",
                        frequency_signal="isolated",
                        # A truncated slice can cut a sentence in half; prefer a whole
                        # sentence, else the opening clause. Must clear the same length
                        # floor the verifier applies, or it is not citable evidence --
                        # returning None is the honest answer.
                        user_quote=(
                            best_evidence_sentence(source_text, ("pump", "clean", "wash", "valve", "flange"))
                            or ((content.strip()[:240] or None)
                                if len(content.strip()) >= MIN_QUOTE_CHARS else None)
                        ),
                        user_workaround=None,
                    )
                ]
                summary = "日常反复清洗拆装后的硅胶公差疲劳。建议提高材质耐久规格并增加对齐导引。"
                urgency = "P3"

            return RndVocResult(
                source_post_id=post_id,
                subreddit=subreddit,
                source_title=title,
                defects=defects,
                engineering_summary=summary,
                urgency_rating=urgency,
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
            phase="rnd_voc",
        )

        parsed: Mapping[str, Any] = json.loads(response.content)
        defects = [
            RndDefectFinding(
                defect_id=item.get("defect_id", f"defect_{post_id}"),
                category=item.get("category", "usability_assembly"),
                component=item.get("component", "hardware_component"),
                severity=item.get("severity", "minor"),
                symptom=item.get("symptom", ""),
                root_cause_hypothesis=item.get("root_cause_hypothesis", ""),
                suggested_action=item.get("suggested_action", ""),
                frequency_signal=item.get("frequency_signal", "isolated"),
                user_quote=item.get("user_quote", ""),
                user_workaround=item.get("user_workaround"),
            )
            for item in parsed.get("defects", [])
        ]

        return RndVocResult(
            source_post_id=post_id,
            subreddit=subreddit,
            source_title=title,
            defects=defects,
            engineering_summary=parsed.get("engineering_summary", ""),
            urgency_rating=parsed.get("urgency_rating", "P2"),
        )
