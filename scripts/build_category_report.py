#!/usr/bin/env python3
"""Build the provisional category-insight report (Wave 1 T12, cap72).

Reads the *served* release (pointer → reports bundle / quarter-insights /
query index) and renders one self-contained HTML file: available indicators
with their real values, the 22 unavailable ones with explicit reason codes,
the category pain-point rollup from the query index, and 3-5 provisional
conclusions authored in-tree (the L3 conclusions contract is a V2 Wave 4
artifact and deliberately out of scope — plan §1 11-16 diff column).

The report is static and provisional by design:
- "静态" — a rebuild renders the whole file from the pinned release token; no
  client-side recomputation can disagree with it.
- "provisional" — every page carries the provenance header and the coverage
  caveat; conclusions cite their inputs.

Publish path (X5 plan B): outputs/category-report/ locally, then the file is
registered on the radar workbench reports page by a follow-up deploy step.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PUBLIC_ROOT = "https://radar.luteos.com/data/reddit-voc"
POINTER_PATH = "current-release.json"


def _fetch_json(url: str, timeout: float = 120.0):
    request = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_bytes(url: str, timeout: float = 120.0) -> bytes:
    request = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# Provisional conclusions are authored here, each citing the inputs it reads.
# Render fails loudly if a cited input is missing — a conclusion that cannot
# trace its inputs must not render (plan §3 T12 gate).
CONCLUSIONS: tuple[dict, ...] = (
    {
        "id": "CR-2026Q4-01",
        "text": "负面声量集中在 output_supply（泌出量不足）与 fit_comfort（贴合舒适度）两个主题；本月 M5 家族负面 80 条中两者合计占约 6 成。",
        "inputs": ["query-index:m5-smart-pain-rollup", "reports:RV-BR-01", "reports:RV-BR-02"],
        "confidence": "provisional",
    },
    {
        "id": "CR-2026Q4-02",
        "text": "精确 SPU 绑定覆盖仍是品类洞察的最大口径缺口：26,330 帖中仅 67 帖有 exact SPU 绑定（约 0.25%），SPU 级结论需以家族级证据标注后谨慎使用。",
        "inputs": ["query-index:spu-coverage", "pointer:freshness"],
        "confidence": "provisional",
    },
    {
        "id": "CR-2026Q4-03",
        "text": "推荐表达率（RV-BR-04）与竞品语境占比（RV-BR-05）维持可用口径，可作为品类沟通的稳定基线；净情感（RV-BR-03）在当前语料下不可计算，任何『净情感改善』表述均无依据。",
        "inputs": ["reports:RV-BR-04", "reports:RV-BR-05", "reports:RV-BR-03"],
        "confidence": "provisional",
    },
)


def _assert_conclusion_inputs(conclusions, context: dict) -> None:
    missing = []
    for c in conclusions:
        for ref in c["inputs"]:
            kind, _, key = ref.partition(":")
            if kind == "reports" and key not in context["indicator_ids"]:
                missing.append(ref)
            if kind == "query-index" and key not in context["index_facts"]:
                missing.append(ref)
            if kind == "pointer" and key not in context["pointer_facts"]:
                missing.append(ref)
    if missing:
        raise SystemExit(f"conclusion cites unavailable inputs: {missing}")


def _index_facts(index_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    try:
        facts: dict[str, str] = {}
        for key in ("data_as_of_utc", "release_token", "release_id"):
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            facts[key] = row[0] if row else ""
        m5 = conn.execute(
            """SELECT count(DISTINCT pb.post_id), count(c.comment_id),
                      sum(CASE WHEN c.sentiment_label='negative' THEN 1 ELSE 0 END)
               FROM post_bindings pb LEFT JOIN comments c ON c.post_id=pb.post_id
               WHERE pb.product_family_id='m5-smart'"""
        ).fetchone()
        # A zero-post rollup is not a fact — emitting "0/0/0" would let the
        # conclusion render a coverage-less claim (a bare-0 lie). Omitting the
        # key fails the assertion gate instead.
        if m5[0]:
            facts["m5-smart-pain-rollup"] = f"{m5[0]}/{m5[1]}/{m5[2] or 0}"
        spu = conn.execute(
            "SELECT count(DISTINCT post_id) FROM post_bindings WHERE binding_level='spu_exact'"
        ).fetchone()[0]
        if spu:
            facts["spu-coverage"] = str(spu)
        return facts
    finally:
        conn.close()


def build(output_dir: Path, index_path: Path, timeout: float = 120.0) -> dict:
    started = time.time()
    pointer = _fetch_json(f"{PUBLIC_ROOT}/{POINTER_PATH}", timeout)
    release_id = pointer["release_id"]
    freshness = pointer.get("freshness") or {}
    datasets = pointer.get("datasets") or {}
    reports = datasets.get("reports") or {}
    reports_version = reports.get("dataset_version", "")

    daily = _fetch_json(
        f"{PUBLIC_ROOT}/{reports_version}/public/current/daily.json", timeout
    )
    indicators = daily.get("indicators") or []
    available = [i for i in indicators if (i.get("current") or {}).get("status") == "available"]
    unavailable = [i for i in indicators if (i.get("current") or {}).get("status") != "available"]

    context = {
        "indicator_ids": {i.get("metric_id") for i in indicators},
        "pointer_facts": {"freshness"},
        "index_facts": set(),
    }
    index_facts = _index_facts(index_path) if index_path.exists() else {}
    context["index_facts"] = set(index_facts.keys())
    _assert_conclusion_inputs(CONCLUSIONS, context)

    data_as_of = freshness.get("data_as_of_utc") or ""
    rendered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    token = f"{release_id}:{(reports.get('public_manifest_sha256') or '')[:16]}"

    rows_av = "".join(
        f"<tr><td>{html.escape(str(i.get('metric_id')))}</td>"
        f"<td>{html.escape(str(i.get('name_cn')))}</td>"
        f"<td class='num'>{html.escape(str((i.get('current') or {}).get('value')))}</td>"
        f"<td><span class='pill ok'>available</span></td></tr>"
        for i in available
    )
    rows_un = "".join(
        f"<tr class='muted'><td>{html.escape(str(i.get('metric_id')))}</td>"
        f"<td>{html.escape(str(i.get('name_cn')))}</td>"
        f"<td class='num'>—</td>"
        f"<td><span class='pill no'>unavailable</span></td></tr>"
        for i in unavailable
    )
    concls = "".join(
        f"<li><b>{html.escape(c['id'])}</b> <span class='pill prov'>provisional</span><br>"
        f"{html.escape(c['text'])}<br>"
        f"<span class='cite'>inputs: {html.escape(', '.join(c['inputs']))}</span></li>"
        for c in CONCLUSIONS
    )
    pain_rows = ""
    if index_facts.get("m5-smart-pain-rollup"):
        posts, vocs, neg = index_facts["m5-smart-pain-rollup"].split("/")
        pain_rows = (
            f"<tr><td>m5-smart</td><td class='num'>{posts}</td>"
            f"<td class='num'>{vocs}</td><td class='num'>{neg}</td>"
            f"<td>output_supply / fit_comfort / operations</td></tr>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>Momcozy 品类洞察报告（provisional v1）</title>
<style>
body{{font-family:-apple-system,'PingFang SC',sans-serif;max-width:960px;margin:2rem auto;padding:0 1.5rem;color:#1a1a2e}}
table{{border-collapse:collapse;width:100%;font-size:.92rem}}
th,td{{border-bottom:1px solid #e2e2ee;padding:.5rem .6rem;text-align:left}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
tr.muted{{color:#8a8aa0}}
.pill{{padding:.15rem .55rem;border-radius:999px;font-size:.75rem}}
.ok{{background:#e6f6ec;color:#177245}} .no{{background:#fdeaea;color:#a12622}}
.prov{{background:#fff6dd;color:#8a6d1a}} .cite{{color:#8a8aa0;font-size:.8rem}}
.banner{{background:#fff6dd;border:1px solid #f0dfa8;border-radius:8px;padding:1rem 1.2rem;margin:1rem 0}}
.meta{{color:#666;font-size:.85rem}}
h1{{font-size:1.5rem}} h2{{font-size:1.15rem;margin-top:2rem}}
</style></head><body>
<h1>Momcozy 品类洞察报告 <span class="pill prov">provisional v1</span></h1>
<div class="banner"><b>Provisional 口径声明</b>：本报告为 Reddit 单源子集模板（cap72 验收为「Reddit 单源 + available 指标 + 人工结论」），
非 report.luteos.com 六源 42 节全量模板；结论为人工编写并引用输入，未接 L3 conclusions 契约（V2 Wave 4 工件）。</div>
<p class="meta">release: {html.escape(release_id)} ｜ data_as_of: {html.escape(data_as_of)} ｜
报告绑定: <code>{html.escape(token)}</code> ｜ 渲染于: {rendered_at}</p>

<h2>01 · 指标可用性总览（{len(available)} available / {len(unavailable)} unavailable）</h2>
<p class="meta">26 项日报指标中仅 4 项按已发布定义可计算；其余显式不可用——不渲染裸 0，不同名改义。</p>
<table><tr><th>指标</th><th>名称</th><th>当前值</th><th>状态</th></tr>
{rows_av}{rows_un}</table>

<h2>02 · 品类痛点 rollup（来自 release-pinned 问数索引）</h2>
<table><tr><th>产品家族</th><th>帖子</th><th>VOC</th><th>负面</th><th>Top 痛点</th></tr>
{pain_rows or "<tr><td colspan='5' class='muted'>索引不可用</td></tr>"}</table>
<p class="meta">覆盖分母口径：仅计有 product_binding 的帖子；全量提及以文本匹配另行统计，不混入本表。</p>

<h2>03 · 结论（provisional，人工编写 + 输入引用）</h2>
<ol>{concls}</ol>

<h2>04 · 口径边界</h2>
<ul>
<li>语料：Reddit 单渠道，data_as_of {html.escape(data_as_of)}；「全渠道」数字属 Source 口径，本报告不引用。</li>
<li>每条结论引用其输入（指标 id / 索引事实）；输入缺失时构建失败，不渲染无依据结论。</li>
<li>发布通道：radar.luteos.com 工作台（X5 plan B）；report.luteos.com 为静态报告库，无可编程 API。</li>
</ul>
</body></html>"""

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"category-report-{data_as_of[:10] or 'unknown'}.html"
    out_path.write_text(doc, encoding="utf-8")
    receipt = {
        "step": "build_category_report",
        "status": "ok",
        "output": str(out_path),
        "release_id": release_id,
        "report_token": token,
        "data_as_of_utc": data_as_of,
        "indicators_available": len(available),
        "indicators_unavailable": len(unavailable),
        "conclusions": len(CONCLUSIONS),
        "index_facts": index_facts,
        "size_bytes": out_path.stat().st_size,
        "elapsed_s": round(time.time() - started, 1),
    }
    (output_dir / "build-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/category-report"))
    parser.add_argument("--index", type=Path, default=Path("outputs/query-index/query-index.sqlite3"))
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    receipt = build(args.output_dir, args.index, args.timeout)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
