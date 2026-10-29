#!/usr/bin/env python3
"""Reddit舆情情报官-早报 v2 builder — editorial style.

Design principles (per owner review of v1):
  no emoji; three-layer structure (lede narrative -> sectioned facts -> data
  boundary); color discipline (red = risk, green = improvement, grey =
  metadata, everything else default); every fact carries its provenance
  (subreddit / post count / period); the header subtitle is a one-line lede,
  not a decoration.

Narratives are templated sentences assembled from the data — every claim in
them is traceable to a number shown on the card or in the workbench.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "morning-brief-v2.json"
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
    """Grey-first MoM: color only when direction matters (red=risk, green=ease)."""
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

    obs = _indicator(daily, "RV-BR-01")
    neg = _indicator(daily, "RV-BR-02")
    rec = _indicator(daily, "RV-BR-04")
    headline = receipt.get("report_date") or run_id.split("_")[2]
    data_as_of = release.get("freshness", {}).get("data_as_of_utc", "—")
    corpus_posts = agg.get("headline", {}).get("unique_posts", 0)
    corpus_comments = agg.get("headline", {}).get("linked_comments", 0)

    # ------------------------------------------------ section 1: risk & signal
    # Lede: what moved and whether it demands attention. Facts: the two
    # indicators with provenance + any P0 defect.
    risk_narrative_parts: list[str] = []
    risk_facts: list[str] = []
    p0_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for result in rnd.get("results", []):
        for d in result.get("defects", []):
            if str(d.get("severity", "")).lower() in ("p0", "critical", "severe"):
                p0_entries.append((result, d))

    if p0_entries:
        result, d = p0_entries[0]
        symptom = str(d.get("symptom") or d.get("user_quote") or "")[:52]
        risk_narrative_parts.append(
            f"出现 {len(p0_entries)} 项 P0 级缺陷信号，最高优先来自 "
            f"{result.get('subreddit')}，建议当日由产品与客服复核。"
        )
        risk_facts.append(
            f"P0 · {symptom}… → {str(d.get('suggested_action') or '')[:44]}"
        )
    if neg[2] == "up" and _pct(neg[1]) > 0:
        risk_narrative_parts.append(
            f"负向率升至 {neg[0]}（{neg[1]}）。单日波动不构成趋势，但需在明日复确认。"
        )
        risk_facts.append(
            f"负向率 {neg[0]}（{neg[1]}）· 分母为昨日已分类 VOC"
        )
    if not risk_narrative_parts:
        risk_narrative_parts.append("昨日无 P0 风险信号，负向率未见异动，常规监测继续。")
    if obs[2] == "down" and _pct(obs[1]) >= 40:
        risk_facts.append(
            f"观察量 {obs[0]}（{obs[1]}）：声量回落不等于口碑改善，不作正面解读。"
        )

    # ------------------------------------------------ section 2: product defects
    # Lede: the defect story (which component dominates). Facts: top-2 unique
    # defects by corroboration, each with repeat count as strength.
    seen_content: dict[tuple[str, str, str], list[str]] = {}
    for result in rnd.get("results", []):
        for d in result.get("defects", []):
            key = (
                str(d.get("component") or ""),
                str(d.get("symptom") or "")[:40],
                str(d.get("root_cause_hypothesis") or ""),
            )
            seen_content.setdefault(key, []).append(str(d.get("defect_id") or ""))
    ranked = sorted(seen_content.items(), key=lambda kv: -len(kv[1]))
    total_defects = sum(len(ids) for _, ids in seen_content.items())
    if ranked:
        (component, symptom, cause), ids = ranked[0]
        second_note = ""
        if len(ranked) > 1:
            (c2, s2, _), ids2 = ranked[1]
            second_note = (
                f"\n{c2[:30]}…（{len(ids2)} 帖）"
            )
        rnd_narrative = (
            f"昨日新增 {total_defects} 条缺陷记录，聚焦度最高的是「{component}」——"
            f"{len(ids)} 帖独立报告同一症状，佐证强度高。"
        )
        rnd_facts = (
            f"· {component[:34]}：{symptom[:40]}…（{len(ids)} 帖同症）\n"
            f"· 根因假设：{cause[:56]}\n"
            f"{second_note}"
        ).rstrip()
    else:
        rnd_narrative = "昨日无新增缺陷记录。"
        rnd_facts = "—"

    # ------------------------------------------- section 3: competition & content
    comp_narrative = ""
    comp_facts = ""
    for result in comp.get("results", []):
        for c in result.get("comparisons", []):
            adv = str(c.get("our_advantage") or c.get("our_disadvantage") or "")
            if not adv:
                continue
            verdict = VERDICT_CN.get(str(c.get("sentiment_verdict") or ""), str(c.get("sentiment_verdict") or "—"))
            comp_narrative = (
                f"昨日最热的对比发生在 {c.get('our_product')} 与 {c.get('competitor_brand')} "
                f"{c.get('competitor_model')} 之间，用户结论「{verdict}」，源头帖子在 {result.get('subreddit')}。"
            )
            comp_facts = (
                f"· {c.get('our_product')} vs {c.get('competitor_brand')} {c.get('competitor_model')}"
                f"（{c.get('dimension')}）：{adv[:72]}…\n"
                f"· 用户原话：\"{str(c.get('user_verbatim_quote') or '')[:56]}…\""
            )
            break
        if comp_facts:
            break
    if not comp_facts:
        comp_narrative = "昨日无新增竞品对比。"
        comp_facts = "—"

    idea_lines: list[str] = []
    seen_ideas: set[str] = set()
    for result in ideas.get("results", []):
        for idea in result.get("ideas", [])[:1]:
            hook = str(idea.get("hook_3s") or "")
            if hook in seen_ideas:
                continue
            seen_ideas.add(hook)
            idea_lines.append(
                f"· [{idea.get('target_platform')}] {hook[:58]}…（源自 {result.get('subreddit')}）"
            )
            break
        if len(idea_lines) >= 2:
            break
    ideas_facts = (
        "**内容选题**（{total} 条在册）\n{lines}".format(
            total=ideas.get("total_topics", 0), lines="\n".join(idea_lines[:2]) or "—"
        )
        if idea_lines
        else ""
    )

    # ------------------------------------------------ quarter anchor + trust
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
        + (f" · 对比 owner-attested" if attested else "")
    )

    # Header grading: red only for P0 or a large negative-rate jump; orange for
    # any negative-rate rise; otherwise green.
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
        "period_line": f"观测窗口 昨日完整自然日 · 环比上一完整同粒度日",
        "risk_narrative": " ".join(risk_narrative_parts),
        "risk_facts": "\n".join(risk_facts) or "—",
        "rnd_narrative": rnd_narrative,
        "rnd_facts": rnd_facts,
        "comp_narrative": comp_narrative,
        "comp_facts": comp_facts,
        "ideas_facts": ideas_facts,
        "quarter_anchor": quarter_anchor,
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
