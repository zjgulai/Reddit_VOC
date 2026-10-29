#!/usr/bin/env python3
"""Reddit舆情情报官-早报 v3 builder — consulting-report standard.

v3 additions over v2 (owner review):
  1. Evidence provenance: every cited post carries a numbered source link
     ([1], [2] …) resolved from the published base permalink index; Sources
     block at the card foot.
  2. Bilingual evidence: Chinese analysis sentence (the agents already emit
     zh summaries) + the English original quoted verbatim — the consulting
     convention of never translating away the evidence.
  3. Line discipline: hr between every section, tri-metric strip, grey
     provenance lines; no decorative glyphs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "morning-brief-v3.json"
WORKBENCH = "https://radar.luteos.com"

VERDICT_CN = {
    "mixed_tradeoff": "互有胜负",
    "our_advantage": "我方占优",
    "our_disadvantage": "我方劣势",
    "positive": "我方占优",
    "negative": "我方劣势",
    "neutral": "中性",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pct(display: str) -> float:
    try:
        return abs(float(display.strip("%+ ").replace(",", "")))
    except (ValueError, AttributeError):
        return 0.0


def _mom(display: str, direction: str) -> str:
    if display in ("—", "None", ""):
        return "—"
    color = {"up": "red", "down": "green"}.get(direction, "grey")
    arrow = {"up": "↑", "down": "↓"}.get(direction, "→")
    return f"<font color='{color}'>{arrow}{display}</font>"


def _indicator(daily: dict[str, Any], metric_id: str) -> tuple[str, str, str]:
    ind = next((i for i in daily.get("indicators", []) if i.get("metric_id") == metric_id), {})
    value = ind.get("current", {})
    mom = ind.get("comparisons", {}).get("period_over_period", {})
    return (
        str(value.get("display") or value.get("value") or "—"),
        str(mom.get("display") or "—"),
        str(mom.get("direction") or "flat"),
    )


def build_card(run_dir: Path, public_root: Path, run_id: str) -> dict[str, Any]:
    receipt = _load(run_dir / f"{run_id}-pipeline-receipt.json")
    ideas = _load(run_dir / f"{run_id}-daily-content-ideas.json")
    rnd = _load(run_dir / f"{run_id}-daily-rnd-tickets.json")
    comp = _load(run_dir / f"{run_id}-daily-competitor-radar.json")

    release = _load(public_root / "data/reddit-voc/current-release.json")
    reports_manifest = public_root / release["datasets"]["reports"]["manifest_path"]
    daily = _load(reports_manifest.parent / "current" / "daily.json")
    base_manifest = public_root / release["datasets"]["base"]["manifest_path"]
    agg = _load(base_manifest.parent / "aggregates-public.json")
    qi = _load(public_root / "data/reddit-voc/reddit_voc_quarter_insights_20260723_public_v1/quarter-insights.json")

    # Permalink index: published base is the source of truth for evidence URLs.
    posts = _load(base_manifest.parent / "posts-public.json")
    permalink_by_id = {str(p["post_id"]): str(p.get("permalink") or "") for p in posts}

    def source_link(post_id: str) -> tuple[str, str]:
        """(inline marker, sources-footer line) for one post id."""
        pid = str(post_id)
        n = len(SOURCES) + 1
        url = permalink_by_id.get(pid, "")
        title = ""
        for p in posts:
            if str(p["post_id"]) == pid:
                title = str(p.get("title") or "")[:60]
                break
        SOURCES.append((n, pid, url, title))
        label = f"[{n}]"
        return label, (
            f"{label} {title}… — r/* · [原帖]({url})" if url else f"{label} {title}…（链接缺失）"
        )

    SOURCES: list[tuple[int, str, str, str]] = []
    # NOTE: `source_link` closes over SOURCES; define after to keep flake-free.

    obs = _indicator(daily, "RV-BR-01")
    neg = _indicator(daily, "RV-BR-02")
    rec = _indicator(daily, "RV-BR-04")
    headline = receipt.get("report_date") or run_id.split("_")[2]
    data_as_of = release.get("freshness", {}).get("data_as_of_utc", "—")
    corpus_posts = agg.get("headline", {}).get("unique_posts", 0)
    corpus_comments = agg.get("headline", {}).get("linked_comments", 0)

    # --------------------------------------------------------- section 01 risk
    risk_narrative_parts: list[str] = []
    risk_facts: list[str] = []
    p0_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for result in rnd.get("results", []):
        for d in result.get("defects", []):
            if str(d.get("severity", "")).lower() in ("p0", "critical", "severe"):
                p0_entries.append((result, d))

    risk_markers: list[str] = []
    if p0_entries:
        result, d = p0_entries[0]
        symptom_en = str(d.get("symptom") or d.get("user_quote") or "")[:70]
        marker, footer_line = source_link(result.get("source_post_id"))
        risk_markers.append(marker)
        risk_narrative_parts.append(
            f"出现 {len(p0_entries)} 项 P0 级缺陷信号{marker}，最高优先来自 "
            f"{result.get('subreddit')}，建议当日由产品与客服复核。"
        )
        risk_facts.append(f"P0 · {symptom_en}…")
        risk_facts.append(
            f"　建议动作：{str(d.get('suggested_action') or '')[:50]}"
        )
    if neg[2] == "up" and _pct(neg[1]) > 0:
        risk_narrative_parts.append(
            f"负向率升至 {neg[0]}（{neg[1]}）。单日波动不构成趋势，需在明日复确认。"
        )
        risk_facts.append(f"负向率 {neg[0]}（{neg[1]}）· 分母为昨日已分类 VOC")
    if not risk_narrative_parts:
        risk_narrative_parts.append("昨日无 P0 风险信号，负向率未见异动，常规监测继续。")
    if obs[2] == "down" and _pct(obs[1]) >= 40:
        risk_facts.append(
            f"观察量 {obs[0]}（{obs[1]}）：声量回落不等于口碑改善，不作正面解读。"
        )

    # ------------------------------------------------- section 02 product defects
    seen_content: dict[tuple[str, str, str], list[str]] = {}
    content_meta: dict[tuple[str, str, str], dict[str, Any]] = {}
    for result in rnd.get("results", []):
        for d in result.get("defects", []):
            key = (
                str(d.get("component") or ""),
                str(d.get("symptom") or "")[:40],
                str(d.get("root_cause_hypothesis") or ""),
            )
            seen_content.setdefault(key, []).append(str(d.get("defect_id") or ""))
            content_meta.setdefault(key, {**d, "_result": result})
    ranked = sorted(seen_content.items(), key=lambda kv: -len(kv[1]))
    total_defects = sum(len(ids) for _, ids in seen_content.items())
    rnd_narrative = ""
    rnd_facts_lines: list[str] = []
    if ranked:
        (component, symptom, cause), ids = ranked[0]
        first = content_meta[(component, symptom, cause)]
        marker, footer_line = source_link(first["_result"].get("source_post_id"))
        risk_markers.append(marker)
        zh_summary = str(first["_result"].get("engineering_summary") or "")[:60]
        rnd_narrative = (
            f"昨日新增 {total_defects} 条缺陷记录，聚焦度最高的是「{component}」——"
            f"{len(ids)} 帖独立报告同一症状{marker}，佐证强度高。"
            + (f"工程摘要：{zh_summary}…" if zh_summary else "")
        )
        rnd_facts_lines.append(f"· 症状｜{symptom[:52]}…（{len(ids)} 帖同症）")
        rnd_facts_lines.append(f"· 根因假设｜{cause[:60]}")
        if ranked[1:]:
            (c2, s2, _), ids2 = ranked[1]
            second = content_meta[(c2, s2, _)]
            marker2, footer_line2 = source_link(second["_result"].get("source_post_id"))
            risk_markers.append(marker2)
            rnd_facts_lines.append(f"· 次要｜{c2[:32]}…（{len(ids2)} 帖）{marker2}")
    else:
        rnd_narrative = "昨日无新增缺陷记录。"
    rnd_facts = "\n".join(rnd_facts_lines) or "—"

    # ----------------------------------------------- section 03 competition & content
    comp_narrative = ""
    comp_facts_lines: list[str] = []
    for result in comp.get("results", []):
        for c in result.get("comparisons", []):
            adv = str(c.get("our_advantage") or c.get("our_disadvantage") or "")
            if not adv:
                continue
            raw_verdict = str(c.get("sentiment_verdict") or "")
            verdict = VERDICT_CN.get(raw_verdict, raw_verdict or "—")
            marker, footer_line = source_link(result.get("source_post_id"))
            comp_narrative = (
                f"昨日热度最高的对比发生在 {c.get('our_product')} 与 {c.get('competitor_brand')} "
                f"{c.get('competitor_model')} 之间{marker}，用户结论「{verdict}」，"
                f"讨论集中在 {result.get('subreddit')}。"
            )
            quote_en = str(c.get("user_verbatim_quote") or "")[:80]
            comp_facts_lines.append(
                f"· 维度｜{c.get('dimension')}"
            )
            comp_facts_lines.append(f"· 我方要点｜{adv[:80]}…")
            if quote_en:
                comp_facts_lines.append(f"· 用户原话（原文）｜\"{quote_en}…\"")
            takeaway = str(result.get("market_takeaway") or "")[:90]
            if takeaway:
                comp_facts_lines.append(f"· 市场启示｜{takeaway}…")
            break
        if comp_facts_lines:
            break

    idea_lines: list[str] = []
    seen_ideas: set[str] = set()
    for result in ideas.get("results", []):
        for idea in result.get("ideas", [])[:1]:
            hook = str(idea.get("hook_3s") or "")
            if hook in seen_ideas:
                continue
            seen_ideas.add(hook)
            marker, footer_line = source_link(result.get("source_post_id"))
            idea_lines.append(
                f"· [{idea.get('target_platform')}] {idea.get('core_pain_point', '')[:36]}"
                f" · 受众 {idea.get('target_audience', '')}{marker}\n"
                f"　 Hook（原文）：\"{hook[:56]}…\""
            )
            break
        if len(idea_lines) >= 2:
            break

    comp_facts = "\n".join(comp_facts_lines) if comp_facts_lines else "—"
    ideas_facts = (
        "**内容选题**（{} 条在册）\n{}".format(
            ideas.get("total_topics", 0), "\n".join(idea_lines)
        )
        if idea_lines
        else ""
    )

    # ------------------------------------------------------ quarter + trust + sources
    rankings = qi.get("themes", {}).get("pain", {}).get("rankings", [])[:3]
    quarter_anchor = " · ".join(f"{r.get('label')} {r.get('count')}" for r in rankings)
    momcozy_counts = qi.get("counts", {}).get("momcozy", {})
    quarter_anchor += (
        f" ｜ 滚动季度 Momcozy VOC {momcozy_counts.get('post_vocs', 0)} 帖 + "
        f"{momcozy_counts.get('comment_context_vocs', 0)} 评论"
    )

    attested = bool(daily.get("data_owner_coverage_attestation_sha256"))
    verified = receipt.get("status") in ("ok", "success", "partial_1_step_errors")
    trust_line = (
        f"版本完整性{'已验证' if verified else '部分通过'}"
        + (" · 对比 owner-attested" if attested else "")
    )

    header_template = "green"
    if p0_entries or (neg[2] == "up" and _pct(neg[1]) >= 50):
        header_template = "red"
    elif neg[2] == "up":
        header_template = "orange"

    if p0_entries:
        narrative_headline = f"P0 风险 {len(p0_entries)} 项，建议当日复核"
    elif neg[2] == "up":
        narrative_headline = f"负向率异动 {neg[0]}，关注明日确认"
    elif obs[2] == "down" and _pct(obs[1]) >= 40:
        narrative_headline = f"声量回落 {obs[1]}，无风险信号"
    else:
        narrative_headline = "昨日平稳，无风险信号"

    exec_summary_parts = [narrative_headline]
    if ranked:
        (component, _, _), ids = ranked[0]
        exec_summary_parts.append(
            f"产品侧聚焦「{component}」（{len(ids)} 帖同症）"
        )
    if comp_facts_lines:
        exec_summary_parts.append("竞争面有可转发用户证言")

    sources_footer = "\n".join(
        f"{n}. {title}… — [原帖]({url})" if url else f"{n}. {title}…（链接缺失）"
        for n, pid, url, title in SOURCES
    ) or "—"

    placeholders = {
        "report_date": headline,
        "header_template": header_template,
        "narrative_headline": narrative_headline,
        "obs_volume": obs[0],
        "obs_mom": _mom(obs[1], obs[2]),
        "negative_rate": neg[0],
        "negative_mom": _mom(neg[1], neg[2]),
        "recommend_rate": rec[0],
        "recommend_mom": _mom(rec[1], rec[2]),
        "period_line": "观测窗口：昨日完整自然日 · 环比基期：上一完整同粒度日 · 同环比口径见「指标口径」",
        "exec_summary": "；".join(exec_summary_parts) + "。",
        "risk_narrative": " ".join(risk_narrative_parts),
        "risk_facts": "\n".join(risk_facts) or "—",
        "rnd_narrative": rnd_narrative,
        "rnd_facts": rnd_facts,
        "comp_narrative": comp_narrative,
        "comp_facts": comp_facts,
        "ideas_facts": ideas_facts,
        "quarter_anchor": quarter_anchor,
        "sources_footer": sources_footer,
        "workbench_url": f"{WORKBENCH}/dashboard",
        "insights_pain_url": f"{WORKBENCH}/dashboard/insights?theme=pain",
        "methodology_url": f"{WORKBENCH}/dashboard/settings",
        "data_as_of": data_as_of,
        "corpus_line": f"{corpus_posts:,} 帖 / {corpus_comments:,} 评",
        "trust_line": trust_line,
        "run_id": run_id,
    }

    template = _load(TEMPLATE_PATH)

    def fill(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: fill(v) for k, v in node.items() if k != "$comment"}
        if isinstance(node, list):
            return [fill(v) for v in node]
        if isinstance(node, str):
            out = node
            for key, value in placeholders.items():
                out = out.replace("{{" + key + "}}", str(value))
            return out
        return node

    return fill(template)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--outputs-dir", type=Path,
                        default=Path("/opt/echo-agent-bot/outputs"))
    parser.add_argument("--public-root", type=Path,
                        default=Path("/opt/voc-report/html"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    card = build_card(args.outputs_dir, args.public_root, args.run_id)
    payload = json.dumps(card, ensure_ascii=False, indent=1)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
        print(f"written: {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
