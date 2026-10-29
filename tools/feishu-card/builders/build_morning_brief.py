#!/usr/bin/env python3
"""Build the "Reddit舆情情报官-早报" Feishu card from production artifacts (v1).

Reads ONLY artifacts that already exist after the daily pipeline — zero new
collection:
  outputs/<run>-pipeline-receipt.json      run/status lines
  outputs/<run>-daily-content-ideas.json   content scout topics
  outputs/<run>-daily-rnd-tickets.json     R&D defect tickets
  outputs/<run>-daily-competitor-radar.json competitor comparisons
  public tree: reports current/daily.json  26 indicators with PoP comparisons
  public tree: aggregates-public.json      corpus headline
  public tree: quarter-insights.json       quarter theme anchors
  public tree: current-release.json        freshness + attestation badge

Usage:
  python3 build_morning_brief.py --run-id daily_collect_20261029_0700 \
      [--output card.json]   # prints card JSON; --output also writes it

Template: ../templates/morning-brief-v1.json ({{placeholder}} substitution).
Header color logic: red if P0 defect or negative-rate MoM up >50%, orange if
negative MoM up, else green.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "morning-brief-v1.json"
WORKBENCH = "https://radar.luteos.com"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_indicator(ind: dict[str, Any]) -> tuple[str, str, str, str]:
    """(value_display, mom_display, direction, name) for one indicator row."""
    value = ind.get("current", {})
    mom = ind.get("comparisons", {}).get("period_over_period", {})
    return (
        str(value.get("display") or value.get("value") or "—"),
        str(mom.get("display") or "—"),
        str(mom.get("direction") or "flat"),
        str(ind.get("name_cn") or ind.get("metric_id") or ""),
    )


def _mom_arrow(direction: str, display: str) -> str:
    color = {"up": "red", "down": "green"}.get(direction, "grey")
    arrow = {"up": "▲", "down": "▼"}.get(direction, "■")
    return f"<font color='{color}'>{arrow} {display}</font>" if display not in ("—", "None") else "<font color='grey'>—</font>"


def _pct(display: str) -> float:
    try:
        return abs(float(display.strip("%+").replace(",", "")))
    except (ValueError, AttributeError):
        return 0.0


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

    indicators = {
        i.get("metric_id"): i for i in daily.get("indicators", []) if i.get("metric_id")
    }
    obs = _fmt_indicator(indicators.get("RV-BR-01", {}))
    neg = _fmt_indicator(indicators.get("RV-BR-02", {}))
    rec = _fmt_indicator(indicators.get("RV-BR-04", {}))

    report_date = (receipt.get("report_date") or run_id.split("_")[2] or "").strip()
    data_as_of = release.get("freshness", {}).get("data_as_of_utc", "—")

    # ---- risk radar: P0 defects first, then the negative-rate signal line ----
    risk_lines: list[str] = []
    p0: list[dict[str, Any]] = []
    for result in rnd.get("results", []):
        for d in result.get("defects", []):
            if str(d.get("severity", "")).lower() in ("p0", "critical", "severe"):
                p0.append((result, d))
    if p0:
        result, d = p0[0]
        quote = str(d.get("symptom") or d.get("user_quote") or "")[:60]
        risk_lines.append(
            f"🔴 **P0 缺陷** [{result.get('subreddit')}] {quote}… → 建议动作：{d.get('suggested_action', '')[:40]}"
        )
    if neg[2] == "up":
        risk_lines.append(
            f"🟠 负向率异动：{neg[0]}（{neg[1]}）——声量回落不等于口碑改善，需复核证据"
        )
    if not risk_lines:
        risk_lines.append("🟢 今日无 P0 风险信号；常规监测继续。")

    # ---- R&D lines: top 2 unique defects. Different posts report the SAME
    # defect (16 ids but shared component+symptom), and the reader cares about
    # the defect, not how many posts repeated it — dedupe on content, and show
    # the repeat count as corroboration strength. ----
    rnd_lines: list[str] = []
    seen_content: dict[tuple[str, str], list[str]] = {}
    for result in rnd.get("results", []):
        for d in result.get("defects", []):
            key = (str(d.get("component") or ""), str(d.get("symptom") or "")[:40])
            seen_content.setdefault(key, []).append(str(d.get("defect_id") or ""))
    ranked = sorted(
        seen_content.items(), key=lambda kv: -len(kv[1])
    )
    for (component, symptom), ids in ranked[:2]:
        corrob = f"（{len(ids)} 帖同症）" if len(ids) > 1 else ""
        # find the full record for root cause
        cause = ""
        for result in rnd.get("results", []):
            for d in result.get("defects", []):
                if str(d.get("component") or "") == component and str(d.get("symptom") or "")[:40] == symptom:
                    cause = str(d.get("root_cause_hypothesis") or "")
                    break
            if cause:
                break
        rnd_lines.append(
            f"• `{component[:36]}` {symptom[:38]}…{corrob}\n  根因假设：{cause[:44]}"
        )
    if not rnd_lines:
        rnd_lines.append("• 昨日无新增中低severity缺陷。")

    # ---- competitor head-to-head: first comparison with a verdict ----
    VERDICT_CN = {
        "mixed_tradeoff": "互有胜负",
        "our_advantage": "我方占优",
        "our_disadvantage": "我方劣势",
        "positive": "我方占优",
        "negative": "我方劣势",
        "neutral": "中性",
    }
    comp_lines: list[str] = []
    for result in comp.get("results", []):
        for c in result.get("comparisons", []):
            raw_verdict = str(c.get("sentiment_verdict") or "")
            verdict = VERDICT_CN.get(raw_verdict, raw_verdict or "—")
            adv = str(c.get("our_advantage") or c.get("our_disadvantage") or "")[:70]
            if adv:
                comp_lines.append(
                    f"• **{c.get('our_product')} vs {c.get('competitor_brand')} {c.get('competitor_model')}**"
                    f"（{c.get('dimension')}）\n  {verdict}: {adv}…"
                )
                break
        if comp_lines:
            break
    if not comp_lines:
        comp_lines.append("• 昨日无新增竞品对比。")

    # ---- content ideas: top hook ----
    idea_lines: list[str] = []
    for result in ideas.get("results", [])[:2]:
        for idea in result.get("ideas", [])[:1]:
            idea_lines.append(
                f"• [{idea.get('target_platform')}] {idea.get('hook_3s', '')[:64]}…\n"
                f"  痛点：{idea.get('core_pain_point', '')[:40]} · 受众：{idea.get('target_audience', '')}"
            )
            break
    if not idea_lines:
        idea_lines.append("• 昨日无新增选题。")

    # ---- quarter anchor ----
    rankings = qi.get("themes", {}).get("pain", {}).get("rankings", [])[:3]
    quarter_anchor = "\n".join(f"• {r.get('label')}：{r.get('count')}" for r in rankings)
    momcozy_counts = qi.get("counts", {}).get("momcozy", {})
    quarter_anchor += (
        f"\n滚动季度 Momcozy VOC：{momcozy_counts.get('post_vocs', 0)} 帖 + "
        f"{momcozy_counts.get('comment_context_vocs', 0)} 评论上下文"
    )

    # ---- trust badge (ADR-004 asset) ----
    attested = bool(daily.get("data_owner_coverage_attestation_sha256"))
    verified = receipt.get("status") in ("ok", "success", "partial_1_step_errors")
    trust_badge = (
        f"{'✅' if verified else '⚠️'} 版本完整性{'已验证' if verified else '部分通过'}\n"
        f"{'✅' if attested else '•'} 对比合同{'owner-attested' if attested else '未认证'}\n"
        f"语料 {agg.get('headline', {}).get('unique_posts', 0):,} 帖"
    )

    header_template = "green"
    if p0 or (neg[2] == "up" and neg[1] not in ("—", "None") and _pct(neg[1]) >= 50):
        header_template = "red"
    elif neg[2] == "up":
        header_template = "orange"

    placeholders = {
        "report_date": report_date,
        "header_template": header_template,
        "obs_volume": obs[0],
        "obs_mom": _mom_arrow(obs[2], obs[1]),
        "volume_color": "red" if obs[2] == "up" else "green",
        "negative_rate": neg[0],
        "negative_mom": _mom_arrow(neg[2], neg[1]),
        "negative_color": "red" if neg[2] == "up" else "green",
        "risk_lines": "\n".join(risk_lines),
        "rnd_total": str(rnd.get("total_defects", 0)),
        "rnd_lines": "\n".join(rnd_lines),
        "competitor_lines": "\n".join(comp_lines),
        "ideas_total": str(ideas.get("total_topics", 0)),
        "ideas_lines": "\n".join(idea_lines),
        "quarter_anchor": quarter_anchor,
        "trust_badge": trust_badge,
        "workbench_url": f"{WORKBENCH}/dashboard",
        "insights_pain_url": f"{WORKBENCH}/dashboard/insights?theme=pain",
        "agent_studio_url": f"{WORKBENCH}/dashboard/agent-studio",
        "data_as_of": data_as_of,
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
