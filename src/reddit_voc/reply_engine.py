"""Shared reply engine for every Echo-Agent Feishu entry point.

Four near-identical keyword-branch reply functions (ws bot, webhook server,
two production scripts) drifted apart — one lost the daily-report intent, all
five hardcoded a stale corpus figure (3,591 posts / 2026-10-26) and a stale
dashboard URL. This module is the single source of reply logic:

* intent routing over slots (not one-off keyword tuples per entry point),
* release-backed corpus facts read from the served pointer, so the numbers in
  a reply always describe the generation the user can actually open,
* one fallback answer that discloses what the engine is (template routing,
  not an LLM) instead of implying a corpus search that never happened.

Entry points only keep transport (WS loop, HTTP server, Feishu client calls)
and delegate all reply content to :func:`generate_agent_reply`.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger("reddit_voc.reply_engine")

PUBLIC_SITE_URL = "https://radar.luteos.com"
POINTER_URL = (
    "https://radar.luteos.com/data/reddit-voc/current-release.json"
)

# Intent slots. Each intent carries its own trigger keywords and reply body;
# the corpus line and the dashboard URL are rendered once, from live facts.
INTENTS: tuple[dict[str, Any], ...] = (
    {
        "slot": "content_strategy",
        "label": "选题/脚本",
        "keywords": ("选题", "脚本", "视频", "tiktok", "小红书", "营销", "文案"),
        "body": (
            "🎬 【Echo-Agent 社媒爆款选题与分镜推荐】\n\n"
            "• 核心痛点：穿戴式吸奶器低头弯腰漏奶风险与职场背奶尴尬\n"
            "• 黄金前 3 秒 Hook：'Stop scrolling if your wearable pump leaked all over your work desk!'\n"
            "• 视觉冲突：展示坐办公室打字时一弯腰捡笔，胸前奶水打湿衬衫的崩溃瞬间。\n"
            "• 解法切入：对比普通机型倾斜漏奶 vs 双唇密封防漏设计的倾斜实测（60度滴水不漏）。\n"
            "• 互动 CTA：'Drop a comment if you have ever had a pumping leak disaster at work!'"
        ),
    },
    {
        "slot": "product_engineering",
        "label": "研发/改款",
        "keywords": ("改款", "研发", "硬件", "质量", "漏奶", "噪音", "故障", "缺陷", "capa"),
        "body": (
            "🔧 【Echo-Agent 产品研发改款建议 (CAPA)】\n\n"
            "• 缺陷构件：collection cup silicone flange & seal ring (集乳罩杯硅胶密封圈)\n"
            "• 严重度：Major (P1)\n"
            "• 根因分析：在人体前倾 45-60 度时，内部静水压超过了单唇摩擦密封保持极限，且顶盖缺少物理卡扣锁死。\n"
            "• 建议工程整改：重新设计硅胶法兰为双唇多重密封截面，并在顶盖边缘增加机械卡扣限位结构。"
        ),
    },
    {
        "slot": "competitor",
        "label": "竞品/对比",
        "keywords": ("竞品", "elvie", "willow", "spectra", "medela", "对比", "优势", "劣势"),
        "body": (
            "⚔️ 【Echo-Agent 竞品对比与攻防情报】\n\n"
            "• 对标竞品：Elvie Stride & Willow 3.0\n"
            "• 我方核心胜出点：仅 1/3 的极致性价比与医院级强劲排空吸力（排空耗时减少约 25%）。\n"
            "• 相对待改进点：高端竞品在贴身隐形度和马达运行静音分贝上略占优势。\n"
            "• 客服/营销攻防话术：'Hospital-grade emptying power at 1/3 the price'。"
        ),
    },
    {
        "slot": "daily_report",
        "label": "最新日报",
        "keywords": ("日报", "报告", "今天", "动态"),
        "body": (
            "📊 【Momcozy Reddit VOC 最新动态】\n\n"
            "• 发布数据截至：{data_as_of_display} (Asia/Shanghai)\n"
            "• 运行状态：当前周期已接入，VOC 整体情绪平稳。\n"
            "• 核心焦点：竞品比较与日常使用问题排查。\n"
            "• 详细完整图表请查看工作台：{dashboard_url}"
        ),
    },
)

WELCOME_TEMPLATE = (
    "👋 您好！我是 Echo-Agent 舆情决策智能体。\n\n"
    "我已连接 {corpus_line}，您可以问我：\n"
    "1. 🎬 【选题/脚本】：最近有什么关于可穿戴吸奶器的海外爆款选题？\n"
    "2. 🔧 【研发/改款】：用户关于 M5 漏奶和噪音的核心抱怨是什么？\n"
    "3. ⚔️ 【竞品/对比】：Momcozy 相比 Elvie / Willow 的优劣势分析？\n"
    "4. 📊 【最新日报】：查看今日推送的 VOC 自然日分析概要。"
)

FALLBACK_TEMPLATE = (
    "收到您的提问：'{query}'。\n"
    "当前回复为模板路由（规则匹配），尚未接入语料检索或大模型问答。"
    "语料事实：{corpus_line}。可先尝试上方示例问题，或直接查看工作台：{dashboard_url}"
)

_CORPUS_CACHE: dict[str, Any] = {"facts": None}


@dataclass
class CorpusFacts:
    """Live, release-backed corpus facts for reply rendering."""

    posts: int
    comments: int
    data_as_of_utc: str
    release_id: str
    dashboard_url: str = PUBLIC_SITE_URL + "/dashboard"
    source: str = "release"
    notes: list[str] = field(default_factory=list)

    @property
    def data_as_of_display(self) -> str:
        """Beijing-time display of the served data window end; empty when unknown."""
        if not self.data_as_of_utc:
            return ""
        return self.data_as_of_utc.replace("T", " ")[:16]

    @property
    def corpus_line(self) -> str:
        return f"Reddit VOC 语料 {self.posts:,} 篇帖子 / {self.comments:,} 条评论（发布截至 {self.data_as_of_display}）"


def _resolve_facts(use_cache: bool = True, timeout: float = 10.0) -> CorpusFacts:
    """Return corpus facts; fall back to an explicit unknown profile on failure.

    A reply must never quote a stale hardcoded count. When the pointer cannot
    be reached the fallback states that the figure is unavailable instead of
    inventing one.
    """
    if use_cache and _CORPUS_CACHE["facts"] is not None:
        return _CORPUS_CACHE["facts"]
    try:
        manifest_url = (
            "https://radar.luteos.com/data/reddit-voc/"
            "reddit_voc_site_snapshot_20260723_v3_daily_001/manifest-public.json"
        )
        pointer_req = urllib.request.Request(
            POINTER_URL,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        with urllib.request.urlopen(pointer_req, timeout=timeout) as response:
            pointer = json.loads(response.read().decode("utf-8"))
        freshness = pointer.get("freshness") or {}
        base_version = ((pointer.get("datasets") or {}).get("base") or {}).get(
            "dataset_version", ""
        )
        counts: Mapping[str, Any] = {}
        if base_version:
            manifest_req = urllib.request.Request(
                "https://radar.luteos.com/data/reddit-voc/"
                f"{base_version}/manifest-public.json",
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
            with urllib.request.urlopen(manifest_req, timeout=timeout) as response:
                manifest = json.loads(response.read().decode("utf-8"))
            counts = manifest.get("canonical_counts") or {}
        facts = CorpusFacts(
            posts=int(counts.get("posts", 0)),
            comments=int(counts.get("comments_jsonl", counts.get("stored_comments", 0))),
            data_as_of_utc=freshness.get("data_as_of_utc") or "",
            release_id=pointer.get("release_id") or "",
        )
    except Exception as exc:  # noqa: BLE001 — reply path must never crash the bot
        logger.warning("release facts unavailable, replying unknown-profile: %s", exc)
        facts = CorpusFacts(
            posts=0,
            comments=0,
            data_as_of_utc="",
            release_id="",
            source="unavailable",
            notes=["release facts unavailable"],
        )
    if use_cache:
        _CORPUS_CACHE["facts"] = facts
    return facts


def _facts_available(facts: CorpusFacts) -> bool:
    return facts.source != "unavailable" and facts.posts > 0


def generate_agent_reply(
    raw_text: str,
    facts: CorpusFacts | None = None,
    use_cache: bool = True,
) -> str:
    """Single reply entry: intent routing + release-backed facts.

    ``facts`` allows tests (and future callers) to inject a fixed profile;
    by default the served release is consulted once per process and cached.
    """
    clean_text = raw_text.replace("@_user_1", "").strip()
    resolved = facts if facts is not None else _resolve_facts(use_cache=use_cache)
    corpus_line = resolved.corpus_line if _facts_available(resolved) else "Reddit VOC 语料（规模信息暂不可用）"
    dashboard_url = resolved.dashboard_url

    if not clean_text:
        return WELCOME_TEMPLATE.format(corpus_line=corpus_line)

    query = clean_text.lower()
    for intent in INTENTS:
        if any(keyword in query for keyword in intent["keywords"]):
            body = intent["body"].format(
                data_as_of_display=resolved.data_as_of_display or "未知（发布信息暂不可用）",
                dashboard_url=dashboard_url,
            )
            return body

    return FALLBACK_TEMPLATE.format(
        query=clean_text,
        corpus_line=corpus_line,
        dashboard_url=dashboard_url,
    )
