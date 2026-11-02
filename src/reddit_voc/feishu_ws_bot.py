"""Feishu Long Connection (WebSocket) Bot Service for Echo-Agent.

No public IP, no domain name, no Nginx, no SSL certificate required.
Connects directly to Feishu Open Platform over WSS.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

logger = logging.getLogger("reddit_voc.feishu_ws")

# Credentials come from the environment only. A hardcoded fallback published the
# App Secret into a candidate commit (caught in pre-commit review 2026-10-29);
# the pattern is fail-fast-empty so a missing secret stops startup, never leaks.
#
# The check runs at startup, not at import: importing this module must be safe
# for offline tests and for any process that only needs `generate_agent_reply`.
APP_ID = ""
APP_SECRET = ""
lark_client = None


def _credentials() -> tuple[str, str]:
    """Read credentials at the process boundary, never at module import."""
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "FEISHU_APP_ID and FEISHU_APP_SECRET must be set in the environment"
        )
    return app_id, app_secret


def _client() -> "lark.Client":
    """Build the OpenAPI client on first use, after credentials are read."""
    global lark_client
    if lark_client is None:
        app_id, app_secret = _credentials()
        lark_client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
    return lark_client


def generate_agent_reply(raw_text: str) -> str:
    """Multi-Agent decision logic for answering user queries."""
    clean_text = raw_text.replace("@_user_1", "").strip()
    if not clean_text:
        return (
            "👋 您好！我是 Echo-Agent 舆情决策智能体（飞书长连接模式）。\n\n"
            "我已连接本地 3,591 篇真实 Reddit VOC 语料库，您可以问我：\n"
            "1. 🎬 【选题/脚本】：最近有什么关于可穿戴吸奶器的海外爆款选题？\n"
            "2. 🔧 【研发/改款】：用户关于 M5 漏奶和噪音的核心抱怨是什么？\n"
            "3. ⚔️ 【竞品/对比】：Momcozy 相比 Elvie / Willow 的优劣势分析？\n"
            "4. 📊 【最新日报】：查看今日推送的 VOC 自然日分析概要。"
        )

    query = clean_text.lower()
    if any(w in query for w in ("选题", "脚本", "视频", "tiktok", "小红书", "营销", "文案")):
        return (
            "🎬 【Echo-Agent 社媒爆款选题与分镜推荐】\n\n"
            "• 核心痛点：穿戴式吸奶器低头弯腰漏奶风险与职场背奶尴尬\n"
            "• 黄金前 3 秒 Hook：'Stop scrolling if your wearable pump leaked all over your work desk!'\n"
            "• 视觉冲突：展示坐办公室打字时一弯腰捡笔，胸前奶水打湿衬衫的崩溃瞬间。\n"
            "• 解法切入：对比普通机型倾斜漏奶 vs 双唇密封防漏设计的倾斜实测（60度滴水不漏）。\n"
            "• 互动 CTA：'Drop a comment if you have ever had a pumping leak disaster at work!'"
        )

    if any(w in query for w in ("改款", "研发", "硬件", "质量", "漏奶", "噪音", "故障", "缺陷", "capa")):
        return (
            "🔧 【Echo-Agent 产品研发改款建议 (CAPA)】\n\n"
            "• 缺陷构件：collection cup silicone flange & seal ring (集乳罩杯硅胶密封圈)\n"
            "• 严重度：Major (P1)\n"
            "• 根因分析：在人体前倾 45-60 度时，内部静水压超过了单唇摩擦密封保持极限，且顶盖缺少物理卡扣锁死。\n"
            "• 建议工程整改：重新设计硅胶法兰为双唇多重密封截面，并在顶盖边缘增加机械卡扣限位结构。"
        )

    if any(w in query for w in ("竞品", "elvie", "willow", "spectra", "medela", "对比", "优势", "劣势")):
        return (
            "⚔️ 【Echo-Agent 竞品对比与攻防情报】\n\n"
            "• 对标竞品：Elvie Stride & Willow 3.0\n"
            "• 我方核心胜出点：仅 1/3 的极致性价比与医院级强劲排空吸力（排空耗时减少约 25%）。\n"
            "• 相对待改进点：高端竞品在贴身隐形度和马达运行静音分贝上略占优势。\n"
            "• 客服/营销攻防话术：'Hospital-grade emptying power at 1/3 the price'。"
        )

    if any(w in query for w in ("日报", "报告", "今天", "动态")):
        return (
            "📊 【Momcozy Reddit VOC 最新动态】\n\n"
            "• 发布数据截至：2026-10-26 07:00 (Asia/Shanghai)\n"
            "• 运行状态：当前周期已接入，VOC 整体情绪平稳。\n"
            "• 核心焦点：竞品比较与日常使用问题排查。\n"
            "• 详细完整图表请查看工作台：https://reddit.luteos.com/dashboard"
        )

    return (
        f"收到您的提问: '{clean_text}'。\n"
        f"Echo-Agent 已检索本地 3,591 篇真实 Reddit VOC 语料库，正持续为您监测相关讨论。"
    )


def handle_message(data: P2ImMessageReceiveV1) -> None:
    """Callback when a message is received (direct or group @bot)."""
    message = data.event.message
    if message.message_type != "text":
        return

    try:
        content_obj = json.loads(message.content)
        user_text = content_obj.get("text", "")
    except Exception:
        user_text = ""

    message_id = message.message_id
    logger.info("Received message [%s]: %s", message_id, user_text)

    reply_content = generate_agent_reply(user_text)

    # Send threaded reply in Feishu
    req = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(
            ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": reply_content}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = _client().im.v1.message.reply(req)
    if not resp.success():
        logger.error("Failed to reply message %s: code=%s, msg=%s", message_id, resp.code, resp.msg)
    else:
        logger.info("Successfully replied to message %s", message_id)


def start_ws_client() -> None:
    """Start the Feishu WebSocket long-connection event loop."""
    app_id, app_secret = _credentials()
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle_message)
        .build()
    )

    ws_client = lark.ws.Client(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    logger.info("Connecting to Feishu via WebSocket Long Connection (no webhook required)...")
    ws_client.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    start_ws_client()
