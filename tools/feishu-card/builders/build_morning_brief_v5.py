#!/usr/bin/env python3
"""Reddit舆情情报官-早报 v5 builder.

v5 additions over v4 (Wave 1 T9, plan §3 D4-D5):
  1. Interactive action buttons alongside the v4 url buttons: 认领痛点
     (claim:top_pain) and 追问原话 (ask:evidence) — the card.action.trigger
     callbacks are handled by reddit_voc.card_action (T5b) with the action
     ledger (T8) as the source of truth.
  2. Button context carries run_id so a claim ties to the exact generation
     that surfaced the pain point.

Everything else (narrative structure, sources, line discipline, header
grading) carries over from v4 unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "morning-brief-v5.json"
WORKBENCH = "https://radar.luteos.com"

VERDICT_CN = {
    "mixed_tradeoff": "互有胜负",
    "our_advantage": "我方占优",
    "our_disadvantage": "我方劣势",
    "positive": "我方占优",
    "negative": "我方劣势",
    "neutral": "中性",
}


def _load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read a JSON artifact, or fall back to `default` when it is absent.

    The card must still render when an artifact is missing: a card that raises
    leaves the group chat with yesterday's card and no signal at all, which is worse
    than a red card that says what is missing.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        if default is not None:
            return default
        raise


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


def build_card(
    run_dir: Path,
    public_root: Path,
    run_id: str,
    *,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render the morning brief card.

    `receipt` may be passed in memory: step5 calls this builder from inside the run
    that just produced the receipt, and re-reading it from disk raced the writer on
    2026-10-29 (the card was assembled before the file landed). When it is omitted
    the builder reads disk and degrades to an explicit `unavailable` receipt rather
    than raising, so a missing artifact still produces an honest red card.
    """
    if receipt is None:
        receipt = _load(
            run_dir / f"{run_id}-pipeline-receipt.json",
            default={"status": "unavailable", "steps": [], "errors": []},
        )
    ideas = _load(run_dir / f"{run_id}-daily-content-ideas.json")
    rnd = _load(run_dir / f"{run_id}-daily-rnd-tickets.json")
    comp = _load(run_dir / f"{run_id}-daily-competitor-radar.json")

    # How the agent prose was produced. Under `template_offline` every post gets the
    # same component/symptom/root_cause, so "N 帖同症" is an artefact of the template
    # collapsing onto one key -- not N independent reports.
    #
    # The receipt field is the primary signal, but it is not always available: a
    # receipt written before this field existed (or by an older pipeline) has no
    # `analysis_mode`. So also infer template mode from the data itself -- if every
    # defect shares one component and one root cause, the analysis cannot be
    # per-post reasoning. Inference is preferred here because it is self-evidencing.
    analysis_mode = "llm"
    for step in receipt.get("steps") or []:
        if isinstance(step, dict) and step.get("step") == "agents":
            candidate = step.get("analysis_mode")
            if isinstance(candidate, str) and candidate:
                analysis_mode = candidate
            break

    _rnd_defects = [
        d
        for result in (rnd.get("results") or [])
        for d in (result.get("defects") or [])
    ]
    if len(_rnd_defects) > 1:
        _keys = {
            (
                str(d.get("component") or ""),
                str(d.get("symptom") or ""),
                str(d.get("root_cause_hypothesis") or ""),
            )
            for d in _rnd_defects
        }
        if len(_keys) == 1:
            analysis_mode = "template_offline"

    release = _load(public_root / "data/reddit-voc/current-release.json")
    reports_manifest = public_root / release["datasets"]["reports"]["manifest_path"]
    daily = _load(reports_manifest.parent / "current" / "daily.json")
    base_manifest = public_root / release["datasets"]["base"]["manifest_path"]
    agg = _load(base_manifest.parent / "aggregates-public.json")
    qi = _load(public_root / "data/reddit-voc/reddit_voc_quarter_insights_20260723_public_v1/quarter-insights.json")

    posts = _load(base_manifest.parent / "posts-public.json")
    permalink_by_id = {str(p["post_id"]): str(p.get("permalink") or "") for p in posts}
    title_by_id = {str(p["post_id"]): str(p.get("title") or "")[:60] for p in posts}

    SOURCES: list[tuple[int, str, str, str]] = []

    def source_link(post_id: str) -> tuple[str, str]:
        pid = str(post_id)
        n = len(SOURCES) + 1
        url = permalink_by_id.get(pid, "")
        title = title_by_id.get(pid, "")
        SOURCES.append((n, pid, url, title))
        label = f"[{n}]"
        footer = (
            f"{label} {title}… — [原帖]({url})" if url else f"{label} {title}…（链接缺失）"
        )
        return label, footer

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

    if p0_entries:
        result, d = p0_entries[0]
        symptom_en = str(d.get("symptom") or d.get("user_quote") or "")[:70]
        marker, footer_line = source_link(result.get("source_post_id"))
        risk_narrative_parts.append(
            f"出现 **{len(p0_entries)} 项 P0 级缺陷信号**{marker}，最高优先来自 "
            f"{result.get('subreddit')}，**建议当日由产品与客服复核**。"
        )
        risk_facts.append(f"· P0 ｜ {symptom_en}…")
        risk_facts.append(f"　 建议动作｜{str(d.get('suggested_action') or '')[:50]}")
    if neg[2] == "up" and _pct(neg[1]) > 0:
        risk_narrative_parts.append(
            f"负向率升至 **{neg[0]}（{neg[1]}）**。单日波动不构成趋势，**需在明日复确认**。"
        )
        risk_facts.append(f"· 负向率 {neg[0]}（{neg[1]}）｜分母为昨日已分类 VOC")
    if not risk_narrative_parts:
        risk_narrative_parts.append("昨日无 P0 风险信号，负向率未见异动，常规监测继续。")
    if obs[2] == "down" and _pct(obs[1]) >= 40:
        risk_facts.append(
            f"· 观察量 {obs[0]}（{obs[1]}）｜声量回落不等于口碑改善，不作正面解读"
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
        marker, _ = source_link(first["_result"].get("source_post_id"))
        zh_summary = str(first["_result"].get("engineering_summary") or "")[:60]
        if analysis_mode == "template_offline":
            # Every post collapsed onto the same template key, so the count here is
            # the number of posts the template ran on -- not corroboration. Report
            # the observation without claiming frequency.
            rnd_narrative = (
                f"昨日 {total_defects} 条缺陷记录均按同一模板归纳为**「{component}」**{marker}；"
                f"模板模式未区分具体症状，**不构成同症频次证据**。"
                + (f"\n工程摘要｜{zh_summary}…" if zh_summary else "")
            )
        else:
            rnd_narrative = (
                f"昨日新增 {total_defects} 条缺陷记录，聚焦度最高的是**「{component}」**——"
                f"**{len(ids)} 帖独立报告同一症状**{marker}，佐证强度高。"
                + (f"\n工程摘要｜{zh_summary}…" if zh_summary else "")
            )
        rnd_facts_lines.append(f"· 症状｜{symptom[:52]}…（{len(ids)} 条记录）")
        rnd_facts_lines.append(f"· 根因假设｜{cause[:60]}")
        if ranked[1:]:
            (c2, s2, _), ids2 = ranked[1]
            second = content_meta[(c2, s2, _)]
            marker2, _ = source_link(second["_result"].get("source_post_id"))
            rnd_facts_lines.append(f"· 次要｜{c2[:32]}…（{len(ids2)} 条）{marker2}")
    else:
        rnd_narrative = "昨日无新增缺陷记录。"
    rnd_facts = "\n".join(rnd_facts_lines) or "—"

    # ----------------------------------------------- section 03 competition
    comp_narrative = ""
    comp_facts_lines: list[str] = []
    for result in comp.get("results", []):
        for c in result.get("comparisons", []):
            adv = str(c.get("our_advantage") or c.get("our_disadvantage") or "")
            if not adv:
                continue
            raw_verdict = str(c.get("sentiment_verdict") or "")
            verdict = VERDICT_CN.get(raw_verdict, raw_verdict or "—")
            marker, _ = source_link(result.get("source_post_id"))
            comp_narrative = (
                f"昨日热度最高的对比发生在 **{c.get('our_product')} vs {c.get('competitor_brand')} "
                f"{c.get('competitor_model')}**{marker}，用户结论**「{verdict}」**，"
                f"讨论集中在 {result.get('subreddit')}。"
            )
            quote_en = str(c.get("user_verbatim_quote") or "")[:80]
            comp_facts_lines.append(f"· 维度｜{c.get('dimension')}")
            comp_facts_lines.append(f"· 我方要点｜{adv[:80]}…")
            if quote_en:
                comp_facts_lines.append(f"· 用户原话（原文）｜\"{quote_en}…\"")
            takeaway = str(result.get("market_takeaway") or "")[:90]
            if takeaway:
                comp_facts_lines.append(f"· 市场启示｜**{takeaway}**…")
            break
        if comp_facts_lines:
            break
    comp_facts = "\n".join(comp_facts_lines) if comp_facts_lines else "—"

    # ------------------------------------------- section 04 content ideas Top-3
    idea_entries: list[dict[str, Any]] = []
    seen_ideas: set[str] = set()
    for result in ideas.get("results", []):
        idea = result.get("ideas", [{}])[0] if result.get("ideas") else {}
        hook = str(idea.get("hook_3s") or "")
        key = hook[:40]
        if not hook or key in seen_ideas:
            continue
        seen_ideas.add(key)
        marker, _ = source_link(result.get("source_post_id"))
        idea_entries.append(
            {
                "platform": idea.get("target_platform", "—"),
                "audience": idea.get("target_audience", "—"),
                "pain": str(idea.get("core_pain_point") or "")[:40],
                "hook": hook,
                "conflict": str(idea.get("story_conflict") or "")[:56],
                "marker": marker,
                "subreddit": result.get("subreddit", ""),
            }
        )
        if len(idea_entries) >= 3:
            break

    ideas_narrative = (
        f"昨日 Agent 从真实帖子里提炼 **{ideas.get('total_topics', 0)} 条**选题，"
        f"以下为去向明确的 Top 3（按源帖热度排序）。"
        if idea_entries
        else "昨日无新增选题。"
    )
    ideas_facts_lines: list[str] = []
    for rank, e in enumerate(idea_entries, 1):
        # "原文" is a claim that a human wrote this. Under template mode the hook is
        # generated prose, so the label changes to match.
        hook_label = "模板话术" if analysis_mode == "template_offline" else "原文"
        ideas_facts_lines.append(
            f"**Top {rank} ｜ {e['platform']} × {e['audience']}**{e['marker']}\n"
            f"  · 痛点｜{e['pain']}\n"
            f"  · Hook（{hook_label}）｜\"{e['hook'][:58]}…\"\n"
            f"  · 故事冲突｜{e['conflict']}…"
        )
    ideas_facts = "\n\n".join(ideas_facts_lines) or "—"

    # ------------------------------------------------------ quarter + trust + sources
    rankings = qi.get("themes", {}).get("pain", {}).get("rankings", [])[:3]
    quarter_anchor = " · ".join(f"{r.get('label')} {r.get('count')}" for r in rankings)
    momcozy_counts = qi.get("counts", {}).get("momcozy", {})
    quarter_anchor += (
        f" ｜ 滚动季度 Momcozy VOC {momcozy_counts.get('post_vocs', 0)} 帖 + "
        f"{momcozy_counts.get('comment_context_vocs', 0)} 评论"
    )

    attested = bool(daily.get("data_owner_coverage_attestation_sha256"))

    # The card is the only place a human learns whether today's publish is real.
    # `partial_1_step_errors` used to count as verified, so on 2026-10-29 a run that
    # died in recompute still told the group "版本完整性已验证". Only an exact
    # `success` may claim verification; everything else states the failed steps.
    receipt_status = str(receipt.get("status") or "unavailable")
    verified = receipt_status == "success"

    READY_STEP_STATUSES = {
        "ok", "success", "empty_success", "partial", "skipped_already_covered",
        "advanced", "sent", "skipped_by_kill_switch", "skipped_no_posts",
    }

    def _failed_steps() -> list[str]:
        """Steps that did not reach a ready state, falling back to receipt.errors."""
        names: list[str] = []
        for step in receipt.get("steps") or []:
            if not isinstance(step, dict):
                continue
            name = str(step.get("step") or "")
            status = str(step.get("status") or "")
            if name and status and status not in READY_STEP_STATUSES:
                names.append(name)
        if not names:
            for err in receipt.get("errors") or []:
                if isinstance(err, dict) and err.get("step"):
                    names.append(str(err["step"]))
        return names

    failed_steps = _failed_steps()
    if verified:
        trust_line = "版本完整性已验证" + (" · 对比 owner-attested" if attested else "")
    else:
        detail = "、".join(failed_steps) if failed_steps else f"回执状态 {receipt_status}"
        trust_line = f"版本完整性未验证 · 失败步骤：{detail}"

    # Section 02/03 stay as observations, not conclusions, when the analysis is a
    # template. `analysis_mode` was already resolved near the top of build_card
    # (receipt field first, then inferred from the data itself), so it is reused
    # here rather than re-read -- a second read without the inference fallback would
    # silently downgrade this line on receipts written before the field existed.
    if analysis_mode == "template_offline":
        trust_line += " · 分析为模板模式（未接入模型），仅原话可核"

    header_template = "green"
    if not verified:
        # A failed pipeline outranks any business signal: the numbers below may be
        # from a previous generation and must never look like a healthy report.
        header_template = "red"
    elif p0_entries or (neg[2] == "up" and _pct(neg[1]) >= 50):
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
        if analysis_mode == "template_offline":
            # Must agree with section 02: under template mode the count is the number
            # of posts analysed, not corroboration. Saying "N 帖同症" here while 02
            # says the opposite is worse than either statement alone.
            exec_summary_parts.append(
                f"产品侧聚焦**「{component}」**（模板归纳，{len(ids)} 条记录）"
            )
        else:
            exec_summary_parts.append(f"产品侧聚焦**「{component}」**（{len(ids)} 帖同症）")
    if idea_entries:
        exec_summary_parts.append(
            f"内容侧 Top 选题：**{idea_entries[0]['pain'] or idea_entries[0]['hook'][:20]}**"
        )

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
        "ideas_narrative": ideas_narrative,
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
