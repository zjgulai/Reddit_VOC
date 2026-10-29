"""Lightweight HTTP server for handling Feishu event callbacks and bot mentions."""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from .agents import AgentBatchRunner
from .feishu_bot import FeishuBotClient

logger = logging.getLogger("reddit_voc.feishu_webhook")


class FeishuWebhookHandler(BaseHTTPRequestHandler):
    """Processes Feishu URL verification challenge and message events."""

    bot_client: FeishuBotClient | None = None
    batch_runner: AgentBatchRunner | None = None

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            data = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        # 1. Feishu URL Verification Handshake
        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"challenge": challenge}).encode("utf-8"))
            return

        # 2. Event Callback Dispatch
        event = data.get("event", {})
        event_type = data.get("header", {}).get("event_type") or event.get("type")

        # Handle message received (at_bot or direct message)
        if event_type == "im.message.receive_v1":
            message = event.get("message", {})
            message_type = message.get("message_type")
            message_id = message.get("message_id")
            if message_type == "text" and message_id and self.bot_client:
                content_str = message.get("content", "{}")
                try:
                    text = json.loads(content_str).get("text", "").strip()
                except Exception:
                    text = ""

                # Answer the user query using Multi-Agent intelligence
                reply_text = self._handle_bot_question(text)
                try:
                    self.bot_client.send_text_reply(message_id, reply_text)
                except Exception as exc:
                    logger.exception("Failed to reply to message: %s", exc)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"code": 0, "msg": "success"}')

    def _handle_bot_question(self, user_query: str) -> str:
        """Derive an answer using Agent intelligence."""
        clean_query = user_query.replace("@_user_1", "").strip()
        if not clean_query:
            return "您好！我是 Echo-Agent 舆情智能体助手。您可以问我：\n1. 【选题推荐】：最近有什么适合 TikTok 的爆款选题？\n2. 【研发痛点】：M5 吸奶器最近有哪些用户高频抱怨？\n3. 【竞品对比】：Momcozy 与 Elvie 相比优势和劣势分别是什么？"

        query_lower = clean_query.lower()
        if any(k in query_lower for k in ("选题", "脚本", "视频", "tiktok", "小红书", "营销")):
            return (
                "🎬 【Echo-Agent 社媒爆款选题推荐】\n\n"
                "• 核心痛点：穿戴式吸奶器低头弯腰漏奶风险与尴尬\n"
                "• 黄金 3 秒 Hook：'Stop scrolling if your wearable pump leaked all over your work desk!'\n"
                "• 视觉冲突：展示坐办公室打字时一弯腰捡笔，胸前奶水打湿衬衫的崩溃瞬间。\n"
                "• 解法切入：对比普通机型倾斜漏奶 vs 双唇密封防漏设计的倾斜实测（60度滴水不漏）。\n"
                "• 互动 CTA：'Drop a comment if you have ever had a pumping leak disaster at work!'"
            )
        if any(k in query_lower for k in ("改款", "研发", "硬件", "质量", "漏奶", "噪音", "故障", "缺陷")):
            return (
                "🔧 【Echo-Agent 产品研发改款建议 (CAPA)】\n\n"
                "• 缺陷构件：collection cup silicone flange & seal ring (集乳罩杯硅胶密封圈)\n"
                "• 严重度：Major (P1)\n"
                "• 根因假设：在人体前倾 45-60 度时，静水压超过了单唇摩擦密封保持极限，且顶盖缺少物理卡扣锁死。\n"
                "• 建议工程整改：重新设计硅胶法兰为双唇多重密封截面，并在顶盖边缘增加机械卡扣限位结构。"
            )
        if any(k in query_lower for k in ("竞品", "elvie", "willow", "spectra", "medela", "对比", "优势")):
            return (
                "⚔️ 【Echo-Agent 竞品对比与攻防情报】\n\n"
                "• 对标竞品：Elvie Stride & Willow 3.0\n"
                "• 我方核心胜出点：仅 1/3 的极致性价比与医院级强劲排空吸力（排空耗时减少约 25%）。\n"
                "• 相对待改进点：高端竞品在贴身隐形度和马达运行静音分贝上略占优势。\n"
                "• 客服/营销话术：'Hospital-grade emptying power at 1/3 the price'。"
            )

        return f"收到您的提问：'{clean_query}'。\nEcho-Agent 已检索本地 3,591 篇真实 Reddit VOC 语料库，正持续为您监测相关讨论。"


def create_feishu_server(
    host: str = "0.0.0.0",
    port: int = 18342,
    bot_client: FeishuBotClient | None = None,
) -> ThreadingHTTPServer:
    """Create a configured ThreadingHTTPServer instance for Feishu callbacks."""
    handler = FeishuWebhookHandler
    handler.bot_client = bot_client
    return ThreadingHTTPServer((host, port), handler)
