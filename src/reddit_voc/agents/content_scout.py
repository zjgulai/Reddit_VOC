"""Content Scout Agent: Transforms raw consumer discussions into viral social media topics and video scripts."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from ..deepseek_client import DeepSeekClient
from ..report_contracts import AttemptBudget
from .contracts import ContentScoutResult, ContentTopicIdea

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位拥有 10 年海外母婴与消费电子出海经验的资深内容营销总监与短视频操盘手。
你的任务是从真实的 Reddit 消费者发声（VOC）中，敏锐捕捉消费者的真实痛点、尴尬瞬间、情绪共鸣点，并将其转化为海外社媒（TikTok / Instagram Reels / YouTube Shorts / 小红书）的爆款短视频选题与分镜脚本。

输出必须严格遵循以下 JSON Schema，不得输出任何前言、后语或 Markdown 格式包裹以外的文本：
{
  "ideas": [
    {
      "topic_id": "string (唯一标识，如 topic_1)",
      "target_platform": "string (如 TikTok / Instagram Reels / 小红书)",
      "target_audience": "string (如 职场背奶妈妈 / 新手首产宝妈 / 夜间吸奶妈妈)",
      "core_pain_point": "string (核心痛点，如 办公室吸奶电机噪音像拖拉机尴尬)",
      "hook_3s": "string (抓人眼球的黄金前 3 秒台词/画面钩子)",
      "story_conflict": "string (情绪矛盾/痛点展开)",
      "solution_angle": "string (产品解法切入角度，突出静音/防漏/便携卖点)",
      "call_to_action": "string (互动或引导下单 CTA)",
      "visual_scene_script": [
        {
          "scene_num": "1",
          "visual": "画面描述 (镜位、动作、道具)",
          "audio": "台词旁白或配乐声效",
          "text_overlay": "屏幕花字文案"
        }
      ],
      "hashtags": ["string"]
    }
  ],
  "reasoning_summary": "string (简要阐述为何此帖适合转化为社媒选题，背后的心理学动因)"
}
"""


class ContentScoutAgent:
    """Agent responsible for discovering social media topics from Reddit posts."""

    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client

    def scout(
        self,
        *,
        post_id: str,
        subreddit: str,
        title: str,
        content: str,
        budget: AttemptBudget | None = None,
    ) -> ContentScoutResult:
        """Analyze a post and generate high-converting social media ideas."""
        user_prompt = (
            f"【来源社区】: {subreddit}\n"
            f"【帖子标题】: {title}\n"
            f"【帖子正文/评论】: {content}\n\n"
            f"请深入挖掘此发声背后的真实痛点，输出 1-2 个极具爆款潜质的社交媒体内容选题方案。"
        )

        if self.client is None:
            # Deterministic fallback / mock mode when no external API client is provided
            return ContentScoutResult(
                source_post_id=post_id,
                subreddit=subreddit,
                source_title=title,
                ideas=[
                    ContentTopicIdea(
                        topic_id=f"idea_{post_id}_1",
                        target_platform="TikTok",
                        target_audience="职场背奶妈妈",
                        core_pain_point="穿戴式吸奶器低头弯腰漏奶风险与尴尬",
                        hook_3s="Stop scrolling if your wearable pump leaked all over your work desk!",
                        story_conflict="展示坐办公室打字时一弯腰捡笔，胸前奶水打湿衬衫的崩溃瞬间。",
                        solution_angle="对比传统吸奶器单向阀与 Momcozy 双唇密封防漏设计的倾斜测试。",
                        call_to_action="Drop a comment if you've ever had a pumping leak disaster at work!",
                        visual_scene_script=[
                            {
                                "scene_num": "1",
                                "visual": "特写：职场妈妈在工位前倒吸一口凉气，手忙脚乱拿纸巾擦胸前污渍",
                                "audio": "音效：急促心跳声 + 旁白: 'The ultimate pumping nightmare just happened...'",
                                "text_overlay": "POV: You bent over at work while pumping 😭",
                            },
                            {
                                "scene_num": "2",
                                "visual": "分屏实测：普通机型倾斜漏奶 vs 防漏阀机型 60 度倾斜滴水不漏",
                                "audio": "旁白: 'This is why design matters for working moms.'",
                                "text_overlay": "Test before you buy! 🍼",
                            },
                        ],
                        hashtags=["#workingmom", "#pumpingmom", "#wearablebreastpump", "#momlifehacks"],
                    )
                ],
                reasoning_summary="该发声直击职场妈妈最恐惧的漏奶尴尬，具象化冲突强烈，极易引发评论区宝妈抱团共鸣与二次传播。",
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
            phase="content_scouting",
        )

        parsed: Mapping[str, Any] = json.loads(response.content)
        ideas = [
            ContentTopicIdea(
                topic_id=item.get("topic_id", f"idea_{post_id}"),
                target_platform=item.get("target_platform", "TikTok"),
                target_audience=item.get("target_audience", "海外宝妈"),
                core_pain_point=item.get("core_pain_point", ""),
                hook_3s=item.get("hook_3s", ""),
                story_conflict=item.get("story_conflict", ""),
                solution_angle=item.get("solution_angle", ""),
                call_to_action=item.get("call_to_action", ""),
                visual_scene_script=item.get("visual_scene_script", []),
                hashtags=item.get("hashtags", []),
            )
            for item in parsed.get("ideas", [])
        ]

        return ContentScoutResult(
            source_post_id=post_id,
            subreddit=subreddit,
            source_title=title,
            ideas=ideas,
            reasoning_summary=parsed.get("reasoning_summary", ""),
        )
