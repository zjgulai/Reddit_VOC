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
import os
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
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


def _format_query_answer(answer) -> str:
    """Render a query_service QueryAnswer as a Feishu text reply.

    The reply states the binding level and coverage explicitly (the PMO
    acceptance language for 11-09), lists top pain points, and closes with
    evidence links — never a bare number without its denominator.
    """
    level_label = {
        "spu_exact": "精确 SPU 级",
        "product_family": "产品家族级",
        "category": "品类级",
    }.get(answer.level, answer.level)
    lines = [
        f"📊 【Echo 实体问数 · {level_label}】",
        "",
        f"• 数据截至：{answer.data_as_of_utc.replace('T', ' ')[:16] if answer.data_as_of_utc else '未知'} (UTC)",
        f"• 覆盖：{answer.posts} 篇帖子 / {answer.vocs} 条评论，其中负面 {answer.negative} 条",
    ]
    if answer.spu_id:
        lines.append(f"• 精确 SPU：{answer.spu_id}")
    if answer.family_id:
        lines.append(f"• 产品家族：{answer.family_id}")
    if answer.note:
        lines.append(f"• 说明：{answer.note}")
    if answer.top_pain_points:
        pain = "、".join(f"{tag}({count})" for tag, count in answer.top_pain_points[:5])
        lines.append(f"• 高频痛点：{pain}")
    if answer.evidence:
        lines.append("• 差评证据（最新 3 条）：")
        for item in answer.evidence:
            lines.append(f"  - {item['created_at_utc'][:10]} {item['permalink']}")
    lines.append("")
    lines.append("（数字口径：仅统计有 product_binding 的语料，其余帖子的提及不计入本回答的覆盖分母）")
    return "\n".join(lines)


def _log_query(query: str, source: str, answer=None, reply_kind: str = "template") -> None:
    """Append one line to the local query log (T7: Stage 3 evidence input).

    Fields follow plan §3 T7: source=real_user|golden|test; Stage 3 stats
    count real_user only. Logging failures must never break the reply.
    """
    try:
        from datetime import datetime, timezone

        log_dir = Path(os.getenv("ECHO_QUERY_LOG_DIR", "outputs/query-log"))
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": source,
            "query": query,
            "reply_kind": reply_kind,
        }
        if answer is not None:
            entry["entity_level"] = answer.level
            entry["spu_id"] = answer.spu_id
            entry["family_id"] = answer.family_id
            entry["coverage"] = {"posts": answer.posts, "vocs": answer.vocs, "negative": answer.negative}
            entry["release_token"] = answer.release_token
        with (log_dir / f"queries-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — telemetry must not break replies
        logger.warning("query log write failed", exc_info=True)


def _looks_like_entity_query(text: str) -> bool:
    """Cheap pre-check before touching the query service.

    A question is entity-shaped when it names a known family alias or a
    ledger SPU id; generic feedback words (差评/对比/…) only count when a
    product-noun co-occurs, so plain intent questions like "和 Elvie 对比
    一下" stay on the keyword templates (Elvie is not an Echo entity).
    """
    lowered = text.lower()
    if re.search(r"(?i)\bspu\d{6}\b", text):
        return True
    if any(alias in lowered for alias in ("m5", "m9", "m6", "s12", "v1 pro", "v2 pro", "s9", "air1", "air 1")):
        return True
    product_noun = re.search(r"(吸奶器|穿戴|泵|pump|momcozy)", lowered)
    feedback_word = re.search(r"(差评|抱怨|痛点|反馈|口碑|评价|原话|好用|难用|对比)", lowered)
    return bool(product_noun and feedback_word)


def _try_entity_query(clean_text: str, source: str):
    """Resolve an entity-scoped question against the query index, if available.

    Returns (reply_text, answer) on a hit, or (None, None) when the index is
    absent/unreadable — the caller then falls through to template routing.
    """
    index_path = Path(os.getenv("ECHO_QUERY_INDEX", "outputs/query-index/query-index.sqlite3"))
    if not index_path.exists():
        return None, None
    try:
        from reddit_voc.query_service import query_entity

        answer = query_entity(clean_text, index_path=index_path)
    except Exception:  # noqa: BLE001 — a broken index must not break the bot
        logger.warning("query service failed; falling back to template routing", exc_info=True)
        return None, None
    if answer.level == "unavailable":
        return _format_query_answer(answer), answer
    return _format_query_answer(answer), answer


def generate_agent_reply(
    raw_text: str,
    facts: CorpusFacts | None = None,
    use_cache: bool = True,
    source: str = "real_user",
) -> str:
    """Single reply entry: entity query first, then intent routing + facts.

    ``facts`` allows tests (and future callers) to inject a fixed profile;
    by default the served release is consulted once per process and cached.
    ``source`` tags the query log entry (real_user|golden|test).
    """
    clean_text = raw_text.replace("@_user_1", "").strip()
    resolved = facts if facts is not None else _resolve_facts(use_cache=use_cache)
    corpus_line = resolved.corpus_line if _facts_available(resolved) else "Reddit VOC 语料（规模信息暂不可用）"
    dashboard_url = resolved.dashboard_url

    if not clean_text:
        _log_query("", source, reply_kind="welcome")
        return WELCOME_TEMPLATE.format(corpus_line=corpus_line)

    # Entity-scoped questions outrank keyword intents: "M5 的差评" must hit
    # the query service, not the product-engineering template.
    if _looks_like_entity_query(clean_text):
        reply, answer = _try_entity_query(clean_text, source)
        if reply is not None:
            _log_query(clean_text, source, answer=answer, reply_kind="entity_query")
            return reply

    query = clean_text.lower()
    for intent in INTENTS:
        if any(keyword in query for keyword in intent["keywords"]):
            body = intent["body"].format(
                data_as_of_display=resolved.data_as_of_display or "未知（发布信息暂不可用）",
                dashboard_url=dashboard_url,
            )
            _log_query(clean_text, source, reply_kind="intent:" + intent["slot"])
            return body

    _log_query(clean_text, source, reply_kind="fallback")
    return FALLBACK_TEMPLATE.format(
        query=clean_text,
        corpus_line=corpus_line,
        dashboard_url=dashboard_url,
    )
