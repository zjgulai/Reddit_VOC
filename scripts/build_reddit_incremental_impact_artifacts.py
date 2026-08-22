#!/usr/bin/env python3
"""Build and execute the incremental impact notebook, then author the report artifact.

The notebook reads only already-sanitized public projections plus manifests and
validation receipts. It never emits post titles, bodies, comment text, authors,
or raw Reddit identifiers.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import nbformat
from nbclient import NotebookClient


TITLE = "Reddit VOC 增量候选：可发布，但未完整水合"

REPORT_QUERIES = {
    "headline_metrics_sql": (
        "SELECT added_posts, added_comments, voc_comments, product_binding_delta "
        "FROM headline_metrics"
    ),
    "incremental_months_sql": (
        "SELECT month, entity_type, count FROM incremental_months "
        "ORDER BY month, CASE entity_type WHEN '帖子' THEN 0 ELSE 1 END"
    ),
    "hydration_state_sql": (
        "SELECT state, count, share FROM hydration_state ORDER BY row_order"
    ),
    "binding_stability_sql": (
        "SELECT metric, baseline, candidate, delta FROM binding_stability ORDER BY row_order"
    ),
    "report_effects_sql": (
        "SELECT metric, baseline, candidate, result FROM report_effects ORDER BY row_order"
    ),
}


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def _build_notebook(*, root: Path, output_dir: Path, inputs: dict[str, Path]) -> Any:
    input_literals = {
        name: _relative(root, path)
        for name, path in inputs.items()
    }
    summary_relative = _relative(root, output_dir / "impact-summary.json")

    notebook = nbformat.v4.new_notebook()
    notebook.metadata.kernelspec = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    notebook.metadata.language_info = {"name": "python", "version": "3.12"}
    notebook.cells = [
        nbformat.v4.new_markdown_cell(
            f"# {TITLE}\n\n"
            "## tl;dr\n\n"
            "本 notebook 以生产 V2 公开投影为基线，对 RC3 增量候选做可复现差异分析。"
            "最终判断来自下方已执行单元格：候选可作为受控发布对象，但不能宣称 Reddit 数据已完整水合。"
        ),
        nbformat.v4.new_markdown_cell(
            "## Context & Methods\n\n"
            "**读者与决策。** 面向产品负责人和管理层，支持“现在发布带显式覆盖债务的候选，还是先继续水合”的选择。\n\n"
            "**比较基线。** 生产 V2 公开 Base / Reports / Personas 对比 RC3 候选的同类公开投影；"
            "RC3 冻结、候选门禁与私有 Base manifest 只用于血缘和覆盖状态。\n\n"
            "### Key Assumptions\n\n"
            "- `event_created_at_utc` 是 Reddit 事件时间，采集时间不用于历史趋势归属。\n"
            "- `thread_complete` 仅表示当前抓取中未观察到 more node，不等价于 Reddit 绝对完整。\n"
            "- 品牌与产品结论只使用治理后的 `brand_binding` / `product_bindings`；不做全局品类插补。\n"
            "- 输出只保留聚合数字、版本与 SHA，不输出正文、评论、作者或 Reddit ID。"
        ),
        nbformat.v4.new_code_cell(
            "from collections import Counter\n"
            "from hashlib import sha256\n"
            "from pathlib import Path\n"
            "import json\n\n"
            "from IPython.display import Markdown, display\n\n"
            f"ROOT = Path({str(root)!r})\n"
            f"INPUTS = {input_literals!r}\n"
            f"SUMMARY_PATH = ROOT / {summary_relative!r}\n\n"
            "def load_json(relative_path):\n"
            "    return json.loads((ROOT / relative_path).read_text(encoding='utf-8'))\n\n"
            "def file_sha(relative_path):\n"
            "    return sha256((ROOT / relative_path).read_bytes()).hexdigest()\n\n"
            "def markdown_table(headers, rows):\n"
            "    head = '| ' + ' | '.join(headers) + ' |'\n"
            "    rule = '| ' + ' | '.join(['---'] * len(headers)) + ' |'\n"
            "    body = ['| ' + ' | '.join(str(value) for value in row) + ' |' for row in rows]\n"
            "    return '\\n'.join([head, rule, *body])"
        ),
        nbformat.v4.new_markdown_cell("## Data"),
        nbformat.v4.new_code_cell(
            "data = {name: load_json(path) for name, path in INPUTS.items()}\n"
            "source_rows = [(name, path, file_sha(path)[:12]) for name, path in INPUTS.items()]\n"
            "display(Markdown(markdown_table(['输入角色', '仓库相对路径', 'SHA-256 前缀'], source_rows)))"
        ),
        nbformat.v4.new_code_cell(
            "baseline_posts = data['baseline_posts']\n"
            "candidate_posts = data['candidate_posts']\n"
            "baseline_comments = data['baseline_comments']\n"
            "candidate_comments = data['candidate_comments']\n\n"
            "baseline_post_ids = {row['post_id'] for row in baseline_posts}\n"
            "candidate_post_ids = {row['post_id'] for row in candidate_posts}\n"
            "baseline_comment_ids = {row['comment_id'] for row in baseline_comments}\n"
            "candidate_comment_ids = {row['comment_id'] for row in candidate_comments}\n"
            "assert baseline_post_ids <= candidate_post_ids\n"
            "assert baseline_comment_ids <= candidate_comment_ids\n\n"
            "added_posts = [row for row in candidate_posts if row['post_id'] not in baseline_post_ids]\n"
            "added_comments = [row for row in candidate_comments if row['comment_id'] not in baseline_comment_ids]\n\n"
            "def binding_summary(rows):\n"
            "    bound_rows = [row for row in rows if row.get('product_bindings')]\n"
            "    bindings = [binding for row in bound_rows for binding in row['product_bindings']]\n"
            "    return {\n"
            "        'bound_records': len(bound_rows),\n"
            "        'binding_count': len(bindings),\n"
            "        'exact_spu_bindings': sum(binding.get('exact_spu') is not None for binding in bindings),\n"
            "        'categories': dict(sorted(Counter((binding.get('category') or {}).get('id') for binding in bindings).items())),\n"
            "        'families': dict(sorted(Counter((binding.get('product_family') or {}).get('id') for binding in bindings if binding.get('product_family')).items())),\n"
            "    }\n\n"
            "baseline_binding = binding_summary(baseline_posts + baseline_comments)\n"
            "candidate_binding = binding_summary(candidate_posts + candidate_comments)\n"
            "added_binding = binding_summary(added_posts + added_comments)"
        ),
        nbformat.v4.new_code_cell(
            "post_months = Counter(row['event_created_at_utc'][:7] for row in added_posts)\n"
            "comment_months = Counter(row['event_created_at_utc'][:7] for row in added_comments)\n"
            "incremental_months = [\n"
            "    {'month': month, 'posts': post_months.get(month, 0), 'comments': comment_months.get(month, 0)}\n"
            "    for month in sorted(set(post_months) | set(comment_months))\n"
            "]\n\n"
            "coverage = data['candidate_private_manifest']['source_boundaries']['tencent_v2_search_hydrated']\n"
            "target_count = coverage['target_count']\n"
            "hydration = {\n"
            "    'target_count': target_count,\n"
            "    'full_threads': coverage['coverage_grade_counts']['full'],\n"
            "    'partial_threads': coverage['coverage_grade_counts']['partial'],\n"
            "    'lineage_gaps': coverage['lineage_gap_count'],\n"
            "    'cursor_outstanding': coverage['cursor_outstanding'],\n"
            "    'page_pagination_outstanding': coverage['page_pagination_outstanding'],\n"
            "}\n\n"
            "baseline_index = data['baseline_report_index']\n"
            "candidate_index = data['candidate_report_index']\n"
            "report_index_unchanged = (\n"
            "    baseline_index['current'] == candidate_index['current']\n"
            "    and baseline_index['archive'] == candidate_index['archive']\n"
            ")\n\n"
            "def february_point(report):\n"
            "    return next(\n"
            "        point for point in report['trend']['points']\n"
            "        if point['window']['start_local'].startswith('2026-02-01')\n"
            "    )\n\n"
            "baseline_february = february_point(data['baseline_monthly_report'])\n"
            "candidate_february = february_point(data['candidate_monthly_report'])\n"
            "february_change = {\n"
            "    'momcozy_comment_observed_before': baseline_february['observed_count']['comment']['value'],\n"
            "    'momcozy_comment_observed_after': candidate_february['observed_count']['comment']['value'],\n"
            "    'negative_share_before': baseline_february['negative_evidence_share']['comment']['value'],\n"
            "    'negative_share_after': candidate_february['negative_evidence_share']['comment']['value'],\n"
            "    'direction_claim_supported': data['candidate_monthly_report']['trend']['direction_claim_supported'],\n"
            "}"
        ),
        nbformat.v4.new_markdown_cell("## Results"),
        nbformat.v4.new_code_cell(
            "gate = data['candidate_gate']\n"
            "summary = {\n"
            "    'schema_version': 'reddit_voc_incremental_impact_summary_v1',\n"
            "    'generated_at_utc': gate['validated_at_utc'],\n"
            "    'baseline': {\n"
            "        'posts': len(baseline_posts),\n"
            "        'linked_comments': len(baseline_comments),\n"
            "        'dataset_version': data['baseline_public_manifest']['dataset_version'],\n"
            "    },\n"
            "    'candidate': {\n"
            "        'posts': len(candidate_posts),\n"
            "        'linked_comments': len(candidate_comments),\n"
            "        'dataset_version': data['candidate_public_manifest']['dataset_version'],\n"
            "        'release_id': gate['release']['release_id'],\n"
            "        'release_candidate': gate['release_candidate'],\n"
            "        'completion_claim_supported': gate['completion_claim_supported'],\n"
            "        'evidence_grade': gate['evidence_grade'],\n"
            "        'hydration_status': gate['hydration_status'],\n"
            "    },\n"
            "    'increment': {\n"
            "        'posts': len(added_posts),\n"
            "        'linked_comments': len(added_comments),\n"
            "        'voc_comments': sum(bool(row.get('include_in_voc_metrics')) for row in added_comments),\n"
            "        'post_event_range': [min(row['event_created_at_utc'] for row in added_posts), max(row['event_created_at_utc'] for row in added_posts)],\n"
            "        'comment_event_range': [min(row['event_created_at_utc'] for row in added_comments), max(row['event_created_at_utc'] for row in added_comments)],\n"
            "        'post_brand_bindings': dict(sorted(Counter(row.get('brand_binding') for row in added_posts).items())),\n"
            "        'comment_brand_bindings': dict(sorted(Counter(row.get('brand_binding') for row in added_comments).items())),\n"
            "        'product_binding_count': added_binding['binding_count'],\n"
            "        'monthly_distribution': incremental_months,\n"
            "    },\n"
            "    'product_binding': {\n"
            "        'baseline': baseline_binding,\n"
            "        'candidate': candidate_binding,\n"
            "        'delta': {\n"
            "            'bound_records': candidate_binding['bound_records'] - baseline_binding['bound_records'],\n"
            "            'binding_count': candidate_binding['binding_count'] - baseline_binding['binding_count'],\n"
            "            'exact_spu_bindings': candidate_binding['exact_spu_bindings'] - baseline_binding['exact_spu_bindings'],\n"
            "        },\n"
            "    },\n"
            "    'reports': {\n"
            "        'current_and_archive_index_unchanged': report_index_unchanged,\n"
            "        'current': candidate_index['current'],\n"
            "        'february_2026_momcozy_comment_revision': february_change,\n"
            "    },\n"
            "    'personas': {\n"
            "        'baseline_assignments': data['baseline_personas_manifest']['assignment_count'],\n"
            "        'candidate_assignments': data['candidate_personas_manifest']['assignment_count'],\n"
    "        'delta': data['candidate_personas_manifest']['assignment_count'] - data['baseline_personas_manifest']['assignment_count'],\n"
            "    },\n"
            "    'hydration': hydration,\n"
            "    'gate': {\n"
            "        'status': gate['status'],\n"
            "        'checks_passed': all(gate['checks'].values()),\n"
            "        'side_effect_boundaries': gate['boundaries'],\n"
            "        'input_freeze_sha256': gate['input_freeze']['sha256'],\n"
            "        'release_sha256': gate['frontend']['release_sha256'],\n"
            "    },\n"
            "    'input_sha256': {name: file_sha(path) for name, path in INPUTS.items()},\n"
            "}\n\n"
            "assert summary['increment']['posts'] == 23\n"
            "assert summary['increment']['linked_comments'] == 139\n"
            "assert summary['increment']['voc_comments'] == 137\n"
            "assert summary['increment']['product_binding_count'] == 0\n"
            "assert summary['product_binding']['delta'] == {'bound_records': 0, 'binding_count': 0, 'exact_spu_bindings': 0}\n"
            "assert summary['reports']['current_and_archive_index_unchanged'] is True\n"
            "assert summary['candidate']['release_candidate'] is True\n"
            "assert summary['candidate']['completion_claim_supported'] is False\n"
            "assert summary['gate']['checks_passed'] is True\n"
            "assert not any(summary['gate']['side_effect_boundaries'].values())\n\n"
            "SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)\n"
            "SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n"
            "display(Markdown(markdown_table(\n"
            "    ['指标', '生产 V2', 'RC3 候选', '变化'],\n"
            "    [\n"
            "        ['帖子', summary['baseline']['posts'], summary['candidate']['posts'], f\"+{summary['increment']['posts']}\"],\n"
            "        ['已关联评论', summary['baseline']['linked_comments'], summary['candidate']['linked_comments'], f\"+{summary['increment']['linked_comments']}\"],\n"
            "        ['产品绑定', baseline_binding['binding_count'], candidate_binding['binding_count'], '0'],\n"
            "        ['画像分配', summary['personas']['baseline_assignments'], summary['personas']['candidate_assignments'], f\"+{summary['personas']['delta']}\"],\n"
            "    ],\n"
            ")))"
        ),
        nbformat.v4.new_code_cell(
            "display(Markdown('### 增量事件时间分布\\n\\n' + markdown_table(\n"
            "    ['月份', '新增帖子', '新增评论'],\n"
            "    [[row['month'], row['posts'], row['comments']] for row in incremental_months],\n"
            ")))\n\n"
            "display(Markdown('### 覆盖状态\\n\\n' + markdown_table(\n"
            "    ['状态', '数量', '占目标 883'],\n"
            "    [\n"
            "        ['当前抓取未观察到 more node', hydration['full_threads'], f\"{hydration['full_threads'] / hydration['target_count']:.1%}\"],\n"
            "        ['已观察但仍为部分线程', hydration['partial_threads'], f\"{hydration['partial_threads'] / hydration['target_count']:.1%}\"],\n"
            "        ['血缘缺口', hydration['lineage_gaps'], f\"{hydration['lineage_gaps'] / hydration['target_count']:.1%}\"],\n"
            "    ],\n"
            ")))"
        ),
        nbformat.v4.new_markdown_cell("## Takeaways"),
        nbformat.v4.new_code_cell(
            "feb = summary['reports']['february_2026_momcozy_comment_revision']\n"
            "display(Markdown(\n"
            "    f\"- **候选已真实纳入 {summary['increment']['posts']} 个帖子和 {summary['increment']['linked_comments']} 条已关联评论。** \"\n"
            "    f\"其中 {summary['increment']['voc_comments']} 条评论进入 VOC 指标；事件主要落在 2025-09 和 2026-02，而不是当前日报或周报窗口。\\n\"\n"
            "    f\"- **Momcozy 产品主线没有被稀释或虚构。** 新增记录带来 0 个产品绑定，候选仍有 {candidate_binding['binding_count']} 个 Momcozy 产品绑定、{candidate_binding['exact_spu_bindings']} 个 exact-SPU 绑定。\\n\"\n"
            "    f\"- **当前日/周/月报告索引不变；历史月度趋势只有一处可见修正。** 2026-02 Momcozy 评论观测数由 {feb['momcozy_comment_observed_before']} 变为 {feb['momcozy_comment_observed_after']}，负向证据占比由 {feb['negative_share_before']:.1%} 变为 {feb['negative_share_after']:.1%}；方向性结论仍不受支持。\\n\"\n"
            "    f\"- **发布候选门禁通过，但完整性声明不成立。** 仍有 {hydration['partial_threads']} 个部分线程、{hydration['cursor_outstanding']} 个 cursor debt、{hydration['page_pagination_outstanding']} 个 page debt 和 {hydration['lineage_gaps']} 个血缘缺口。\"\n"
            "))"
        ),
    ]
    return notebook


def _build_report_artifact(summary: dict[str, Any], generated_at: str) -> dict[str, Any]:
    increment = summary["increment"]
    hydration = summary["hydration"]
    product = summary["product_binding"]
    reports = summary["reports"]
    february = reports["february_2026_momcozy_comment_revision"]

    monthly_rows: list[dict[str, Any]] = []
    for row in increment["monthly_distribution"]:
        monthly_rows.extend(
            [
                {"month": row["month"], "entity_type": "帖子", "count": row["posts"]},
                {"month": row["month"], "entity_type": "评论", "count": row["comments"]},
            ]
        )

    hydration_rows = [
        {
            "state": "当前抓取未观察到 more node",
            "count": hydration["full_threads"],
            "share": hydration["full_threads"] / hydration["target_count"],
        },
        {
            "state": "部分线程",
            "count": hydration["partial_threads"],
            "share": hydration["partial_threads"] / hydration["target_count"],
        },
        {
            "state": "血缘缺口",
            "count": hydration["lineage_gaps"],
            "share": hydration["lineage_gaps"] / hydration["target_count"],
        },
    ]

    category_labels = {
        "breast_pump": "吸奶器",
        "bottle_washer": "洗奶瓶机",
        "baby_monitor": "婴儿监视器",
    }
    binding_rows = [
        {
            "metric": "产品绑定总数",
            "baseline": product["baseline"]["binding_count"],
            "candidate": product["candidate"]["binding_count"],
            "delta": product["delta"]["binding_count"],
        },
        {
            "metric": "有产品绑定的记录",
            "baseline": product["baseline"]["bound_records"],
            "candidate": product["candidate"]["bound_records"],
            "delta": product["delta"]["bound_records"],
        },
        {
            "metric": "Exact-SPU 绑定",
            "baseline": product["baseline"]["exact_spu_bindings"],
            "candidate": product["candidate"]["exact_spu_bindings"],
            "delta": product["delta"]["exact_spu_bindings"],
        },
    ]
    for category, baseline_value in product["baseline"]["categories"].items():
        candidate_value = product["candidate"]["categories"].get(category, 0)
        binding_rows.append(
            {
                "metric": f"品类：{category_labels.get(category, category)}",
                "baseline": baseline_value,
                "candidate": candidate_value,
                "delta": candidate_value - baseline_value,
            }
        )

    report_rows = []
    for period, label in (("daily", "当前日报"), ("weekly", "当前周报"), ("monthly", "当前月报")):
        state = reports["current"][period]
        report_rows.append(
            {
                "metric": label,
                "baseline": f"{state['posts']} 帖 / {state['voc_comments']} VOC 评论",
                "candidate": f"{state['posts']} 帖 / {state['voc_comments']} VOC 评论",
                "result": "未变化",
            }
        )
    report_rows.extend(
        [
            {
                "metric": "2026-02 Momcozy 评论观测数",
                "baseline": str(february["momcozy_comment_observed_before"]),
                "candidate": str(february["momcozy_comment_observed_after"]),
                "result": "+1",
            },
            {
                "metric": "2026-02 Momcozy 评论负向证据占比",
                "baseline": f"{february['negative_share_before']:.1%}",
                "candidate": f"{february['negative_share_after']:.1%}",
                "result": f"{(february['negative_share_after'] - february['negative_share_before']) * 100:+.1f} pp",
            },
        ]
    )

    file_sources = [
        {
            "id": "impact_summary",
            "label": "RC3 增量影响汇总",
            "path": "output/reddit-voc-incremental-impact-20260715/impact-summary.json",
        },
        {
            "id": "candidate_gate",
            "label": "RC3 候选验证回执",
            "path": "tmp/reddit-voc-incremental-candidate-20260715/candidate-validation-receipt-rc3.json",
        },
        {
            "id": "candidate_manifest",
            "label": "RC3 候选 Base manifest",
            "path": "tmp/reddit-voc-incremental-candidate-20260715/base/reddit_voc_site_snapshot_20260715_6efd951e6095/manifest.json",
        },
        {
            "id": "production_baseline",
            "label": "生产 V2 公开 Base manifest",
            "path": "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_site_snapshot_20260715_v2/manifest-public.json",
        },
    ]
    sql_sources = [
        {
            "id": source_id,
            "label": {
                "headline_metrics_sql": "RC3 头部指标 SQL",
                "incremental_months_sql": "增量月份分布 SQL",
                "hydration_state_sql": "水合状态 SQL",
                "binding_stability_sql": "产品绑定稳定性 SQL",
                "report_effects_sql": "报告影响 SQL",
            }[source_id],
            "path": "output/reddit-voc-incremental-impact-20260715/report-source.sqlite3",
            "query": {
                "engine": "sqlite",
                "language": "sql",
                "sql": query,
                "description": "从 notebook 生成的聚合报告源读取已复核行。",
                "executed_at": generated_at,
                "tables_used": [source_id.removesuffix("_sql")],
                "filters": ["RC3 candidate compared with production V2 baseline"],
            },
        }
        for source_id, query in REPORT_QUERIES.items()
    ]
    sources = [*file_sources, *sql_sources]

    cards = [
        {
            "id": "added_posts_card",
            "dataset": "headline_metrics",
            "sourceId": "headline_metrics_sql",
            "description": "相对生产 V2 新纳入的帖子。",
            "metrics": [{"label": "新增帖子", "field": "added_posts", "format": "number"}],
        },
        {
            "id": "added_comments_card",
            "dataset": "headline_metrics",
            "sourceId": "headline_metrics_sql",
            "description": "相对生产 V2 新纳入的已关联评论。",
            "metrics": [{"label": "新增评论", "field": "added_comments", "format": "number"}],
        },
        {
            "id": "voc_comments_card",
            "dataset": "headline_metrics",
            "sourceId": "headline_metrics_sql",
            "description": "新增评论中进入 VOC 指标的记录。",
            "metrics": [{"label": "新增 VOC 评论", "field": "voc_comments", "format": "number"}],
        },
        {
            "id": "product_delta_card",
            "dataset": "headline_metrics",
            "sourceId": "headline_metrics_sql",
            "description": "新增批次带来的治理后 Momcozy 产品绑定变化。",
            "metrics": [{"label": "产品绑定净变化", "field": "product_binding_delta", "format": "number", "signed": True}],
        },
    ]

    charts = [
        {
            "id": "increment_by_month",
            "title": "新增帖子与评论的事件月份分布",
            "subtitle": "事件时间集中在 2025 年 9 月与 2026 年 2 月；3 月仅有 3 条关联评论。",
            "type": "bar",
            "dataset": "incremental_months",
            "sourceId": "incremental_months_sql",
            "encodings": {
                "x": {"field": "month", "type": "nominal", "label": "事件月份"},
                "y": {"field": "count", "type": "quantitative", "label": "记录数"},
                "color": {"field": "entity_type", "type": "nominal", "label": "实体类型"},
            },
        },
        {
            "id": "hydration_state",
            "title": "目标帖子的当前水合状态",
            "subtitle": "以 883 个发现目标为分母；“未观察到 more node”不等于 Reddit 绝对完整。",
            "type": "horizontalBar",
            "dataset": "hydration_state",
            "sourceId": "hydration_state_sql",
            "encodings": {
                "x": {"field": "state", "type": "nominal", "label": "覆盖状态"},
                "y": {"field": "count", "type": "quantitative", "label": "帖子数"},
                "tooltip": [{"field": "share", "type": "quantitative", "label": "占目标比例", "format": "percent"}],
            },
        },
    ]

    tables = [
        {
            "id": "binding_stability",
            "title": "Momcozy 产品绑定稳定性",
            "subtitle": "生产 V2 与 RC3 候选的治理后产品绑定；新增批次未产生产品映射。",
            "dataset": "binding_stability",
            "sourceId": "binding_stability_sql",
            "defaultSort": {"field": "baseline", "direction": "desc"},
            "columns": [
                {"field": "metric", "label": "指标", "type": "text"},
                {"field": "baseline", "label": "生产 V2", "format": "number"},
                {"field": "candidate", "label": "RC3 候选", "format": "number"},
                {"field": "delta", "label": "变化", "format": "number", "movement": True},
            ],
        },
        {
            "id": "report_effects",
            "title": "报告与历史趋势影响",
            "subtitle": "当前闭合期索引保持不变；历史 2026 年 2 月出现一处 Momcozy 评论修正。",
            "dataset": "report_effects",
            "sourceId": "report_effects_sql",
            "defaultSort": {"field": "metric", "direction": "asc"},
            "columns": [
                {"field": "metric", "label": "指标", "type": "text"},
                {"field": "baseline", "label": "生产 V2", "type": "text"},
                {"field": "candidate", "label": "RC3 候选", "type": "text"},
                {"field": "result", "label": "结果", "type": "text"},
            ],
        },
    ]

    blocks = [
        {"id": "title", "type": "markdown", "body": f"# {TITLE}"},
        {
            "id": "executive_summary",
            "type": "markdown",
            "sourceId": "impact_summary",
            "body": (
                "## Executive Summary\n\n"
                "- **建议把 RC3 作为可发布候选，而不是完整数据版本。** 候选门禁通过并绑定不可变输入，但 `completion_claim_supported=false`。\n"
                f"- **增量已真实进入网站数据链。** 相对生产 V2，新增 {increment['posts']} 个帖子、{increment['linked_comments']} 条已关联评论，其中 {increment['voc_comments']} 条进入 VOC 指标。\n"
                "- **Momcozy 产品主线保持稳定。** 新增批次没有产生治理后产品绑定，因此品类、产品家族与 exact-SPU 分析没有被稀释或虚构。\n"
                "- **管理层应把变化理解为历史样本补齐。** 当前日报、周报和月报索引不变；2026 年 2 月 Momcozy 评论观测数仅从 27 修正为 28。"
            ),
        },
        {"id": "headline_metrics", "type": "metric-strip", "cardIds": [card["id"] for card in cards]},
        {
            "id": "definitions",
            "type": "markdown",
            "sourceId": "candidate_manifest",
            "body": (
                "## 先读定义：这是候选增量，不是完整 Reddit 全量\n\n"
                "本报告把“新增”定义为 RC3 候选中相对生产 V2 首次出现的公开实体；时间归属使用 Reddit 事件时间。"
                "`thread_complete` 只表示本次抓取未观察到 more node。因 cursor、分页和血缘债务仍非零，所有趋势、同比、环比及份额均应继续标注为 observed / provisional。"
            ),
        },
        {
            "id": "historical_increment",
            "type": "markdown",
            "sourceId": "impact_summary",
            "body": (
                "## 新增数据被真实接入，但集中在历史月份\n\n"
                "新增帖子全部落在 2025 年 9 月和 2026 年 2 月；新增评论还包括 2026 年 3 月的 3 条关联回复。"
                "因此这批数据扩大历史样本，不应制造当前经营周期“突然增长”的叙事。下图按事件月份展示实体增量，帖子与评论分组比较。"
            ),
        },
        {"id": "increment_chart", "type": "chart", "chartId": "increment_by_month"},
        {
            "id": "momcozy_spine",
            "type": "markdown",
            "sourceId": "impact_summary",
            "body": (
                "## Momcozy 产品主线保持稳定，新增主要补充对比样本\n\n"
                "23 个新增帖子中 4 个为 competitor sentence-bound，139 条新增评论中 8 条为 competitor sentence-bound、1 条为 Momcozy reviewed；"
                "新增帖子与评论均没有产品绑定。**经营含义是扩大竞品语境与历史分母，不是发现新的 Momcozy SPU 信号。**"
                "所以洞察页与日报、周报、月报应保持既有 Momcozy 品类与 SPU 结论，只更新证据分母和受影响的历史点。"
            ),
        },
        {"id": "binding_table", "type": "table", "tableId": "binding_stability"},
        {
            "id": "report_revision",
            "type": "markdown",
            "sourceId": "impact_summary",
            "body": (
                "## 日报与周报不变；月度趋势仅出现一处小幅修正\n\n"
                f"当前日报、周报和月报的帖子与 VOC 评论计数保持不变。2026 年 2 月 Momcozy 评论观测数由 {february['momcozy_comment_observed_before']} 变为 {february['momcozy_comment_observed_after']}，"
                f"负向证据占比由 {february['negative_share_before']:.1%} 变为 {february['negative_share_after']:.1%}。"
                "这是分母增加带来的轻微下调，方向性趋势仍不受支持，不能升级为增长或风险改善结论。"
            ),
        },
        {"id": "report_table", "type": "table", "tableId": "report_effects"},
        {
            "id": "coverage_finding",
            "type": "markdown",
            "sourceId": "candidate_manifest",
            "body": (
                "## 最大决策风险仍是覆盖债务，而不是前端或数据融合\n\n"
                f"883 个发现目标中，{hydration['full_threads']} 个在当前抓取中未观察到 more node，{hydration['partial_threads']} 个仍为部分线程，另有 {hydration['lineage_gaps']} 个血缘缺口。"
                f"同时仍记录 {hydration['cursor_outstanding']} 个 cursor debt 和 {hydration['page_pagination_outstanding']} 个分页 debt。"
                "下图展示目标帖子级状态；它是发布风险图，不是 Reddit 绝对完整率。"
            ),
        },
        {"id": "hydration_chart", "type": "chart", "chartId": "hydration_state"},
        {
            "id": "recommended_next_steps",
            "type": "markdown",
            "body": (
                "## 推荐下一步：自动构建候选，人工批准前两次生产提升\n\n"
                "1. 由负责人明确接受 `latest_collection_integrated=true`、`latest_collection_fully_hydrated=false` 后，再执行一次受控生产提升。\n"
                "2. 增量自动化先只做到“发现 → 冻结 → 构建 → 验证候选”，不自动切换生产 current release。\n"
                "3. 前两次周期保留人工核对：净新增身份数、覆盖债务变化、Momcozy 产品绑定变化、日报/周报/月报受影响窗口。\n"
                "4. 只有当同一不可变 SHA 的生产 smoke 与浏览器验收通过后，才把该次提升记为 production accepted。"
            ),
        },
        {
            "id": "further_questions",
            "type": "markdown",
            "body": (
                "## 仍需负责人决策的问题\n\n"
                "- 是否接受带显式覆盖债务的 RC3 先上线，还是先继续消化 cursor / page / lineage debt？\n"
                "- 增量自动化的生产提升是否坚持人工批准两个周期，之后再评估自动 promotion？\n"
                "- SPU 运营看板是否把“无新增绑定”作为正常状态展示，避免团队把零变化误判为数据故障？"
            ),
        },
        {
            "id": "caveats",
            "type": "markdown",
            "sourceId": "candidate_gate",
            "body": (
                "## Caveats and assumptions\n\n"
                "- 候选证据等级为 `L2-fixture-or-dry-run`；本报告不把本地容器制品、候选浏览器 E2E 或门禁通过等同于生产部署验收。\n"
                "- `production unchanged`、`deploy=false`、`remote_write=false`、`schedule_change=false`。\n"
                "- 当前结果不支持市场份额、ROI、响应时间或 Reddit 全量完整性结论。"
            ),
        },
    ]

    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": TITLE,
            "description": "面向管理层的 Reddit VOC RC3 增量候选影响与发布决策报告。",
            "generatedAt": generated_at,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "partial",
            "datasets": {
                "headline_metrics": [
                    {
                        "added_posts": increment["posts"],
                        "added_comments": increment["linked_comments"],
                        "voc_comments": increment["voc_comments"],
                        "product_binding_delta": product["delta"]["binding_count"],
                    }
                ],
                "incremental_months": monthly_rows,
                "hydration_state": hydration_rows,
                "binding_stability": binding_rows,
                "report_effects": report_rows,
            },
            "accessIssues": [
                {
                    "id": "reddit_hydration_incomplete",
                    "dataset": "complete_reddit_hydration",
                    "sourceId": "candidate_manifest",
                    "message": "Cursor、分页与血缘债务仍非零；候选不能宣称完整 Reddit 水合。",
                }
            ],
        },
        "sources": sources,
    }


def _build_source_notes(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "reddit_voc_incremental_report_source_notes_v1",
        "audience": "product stakeholders",
        "delivery_mode": "html",
        "report_spine": {
            "question": "RC3 增量候选是否适合上线，以及增量对 Momcozy 经营故事线产生了什么真实变化？",
            "decision_useful_answer": "可作为受控发布候选，但不能宣称完整水合；增量主要补齐历史与竞品语境。",
            "comparison_basis": "生产 V2 公开投影 vs RC3 候选公开投影",
            "recommended_action": "候选自动构建、前两次生产提升人工批准。",
        },
        "required_structure_mapping": [
            {"role": "Title", "block_id": "title"},
            {"role": "Executive summary", "block_id": "executive_summary"},
            {
                "role": "Key findings with visual evidence",
                "block_ids": ["historical_increment", "increment_chart", "momcozy_spine", "binding_table", "report_revision", "report_table", "coverage_finding", "hydration_chart"],
            },
            {"role": "Recommended next steps", "block_id": "recommended_next_steps"},
            {"role": "Further questions", "block_id": "further_questions"},
            {"role": "Caveats and assumptions", "block_id": "caveats"},
        ],
        "chart_map": [
            {
                "section": "新增数据被真实接入，但集中在历史月份",
                "question": "新增实体落在哪些 Reddit 事件月份？",
                "family": "Comparison & Ranking",
                "type": "grouped bar",
                "fields": ["month", "entity_type", "count"],
                "takeaway": "新增集中在历史月份，不应制造当前周期增长叙事。",
                "palette_policy": "hard two-root cap; blue and gold with visible group labels",
                "artifact": "report.html#increment_by_month",
            },
            {
                "section": "最大决策风险仍是覆盖债务，而不是前端或数据融合",
                "question": "883 个发现目标目前处于什么水合状态？",
                "family": "Comparison & Ranking",
                "type": "horizontal bar",
                "fields": ["state", "count", "share"],
                "takeaway": "覆盖债务仍非零，不能宣称完整水合。",
                "palette_policy": "single-root preferred with direct category labels",
                "artifact": "report.html#hydration_state",
            },
        ],
        "omitted_visuals": [
            {
                "topic": "当前日报/周报/月报变化",
                "reason": "当前索引完全相同，表格比零变化图更诚实。",
            },
            {
                "topic": "2026-02 Momcozy 评论修正",
                "reason": "仅两个离散比较点且量级很小，使用精确表格避免弱趋势图。",
            },
        ],
        "validation_posture": "Share with caveats",
        "evidence_grade": summary["candidate"]["evidence_grade"],
        "privacy": "No raw titles, bodies, comments, authors, or Reddit identifiers are emitted.",
    }


def _materialize_report_source_database(
    path: Path,
    datasets: dict[str, list[dict[str, Any]]],
) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(
            """
            CREATE TABLE headline_metrics (
                added_posts INTEGER NOT NULL,
                added_comments INTEGER NOT NULL,
                voc_comments INTEGER NOT NULL,
                product_binding_delta INTEGER NOT NULL
            );
            CREATE TABLE incremental_months (
                month TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                count INTEGER NOT NULL
            );
            CREATE TABLE hydration_state (
                row_order INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                count INTEGER NOT NULL,
                share REAL NOT NULL
            );
            CREATE TABLE binding_stability (
                row_order INTEGER PRIMARY KEY,
                metric TEXT NOT NULL,
                baseline INTEGER NOT NULL,
                candidate INTEGER NOT NULL,
                delta INTEGER NOT NULL
            );
            CREATE TABLE report_effects (
                row_order INTEGER PRIMARY KEY,
                metric TEXT NOT NULL,
                baseline TEXT NOT NULL,
                candidate TEXT NOT NULL,
                result TEXT NOT NULL
            );
            """
        )
        headline = datasets["headline_metrics"][0]
        connection.execute(
            "INSERT INTO headline_metrics VALUES (?, ?, ?, ?)",
            (
                headline["added_posts"],
                headline["added_comments"],
                headline["voc_comments"],
                headline["product_binding_delta"],
            ),
        )
        connection.executemany(
            "INSERT INTO incremental_months VALUES (?, ?, ?)",
            [
                (row["month"], row["entity_type"], row["count"])
                for row in datasets["incremental_months"]
            ],
        )
        connection.executemany(
            "INSERT INTO hydration_state VALUES (?, ?, ?, ?)",
            [
                (index, row["state"], row["count"], row["share"])
                for index, row in enumerate(datasets["hydration_state"])
            ],
        )
        connection.executemany(
            "INSERT INTO binding_stability VALUES (?, ?, ?, ?, ?)",
            [
                (index, row["metric"], row["baseline"], row["candidate"], row["delta"])
                for index, row in enumerate(datasets["binding_stability"])
            ],
        )
        connection.executemany(
            "INSERT INTO report_effects VALUES (?, ?, ?, ?, ?)",
            [
                (index, row["metric"], row["baseline"], row["candidate"], row["result"])
                for index, row in enumerate(datasets["report_effects"])
            ],
        )
        connection.commit()

        dataset_by_source = {
            "headline_metrics_sql": "headline_metrics",
            "incremental_months_sql": "incremental_months",
            "hydration_state_sql": "hydration_state",
            "binding_stability_sql": "binding_stability",
            "report_effects_sql": "report_effects",
        }
        for source_id, query in REPORT_QUERIES.items():
            rows = [dict(row) for row in connection.execute(query).fetchall()]
            expected = datasets[dataset_by_source[source_id]]
            if rows != expected:
                raise ValueError(f"report SQL output drift for {source_id}")
    finally:
        connection.close()

    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/reddit-voc-incremental-impact-20260715"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.project_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_base = root / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_site_snapshot_20260715_v2"
    candidate_base = root / "tmp/reddit-voc-incremental-candidate-20260715/public-bundle/data/reddit-voc/reddit_voc_site_snapshot_20260715_6efd951e6095"
    baseline_reports = root / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_reports_20260715_v2/public"
    candidate_reports = root / "tmp/reddit-voc-incremental-candidate-20260715/public-bundle/data/reddit-voc/reddit_voc_reports_20260715_a900e6ce7b63/public"

    inputs = {
        "baseline_posts": baseline_base / "posts-public.json",
        "candidate_posts": candidate_base / "posts-public.json",
        "baseline_comments": baseline_base / "comments-public.json",
        "candidate_comments": candidate_base / "comments-public.json",
        "baseline_public_manifest": baseline_base / "manifest-public.json",
        "candidate_public_manifest": candidate_base / "manifest-public.json",
        "candidate_private_manifest": root / "tmp/reddit-voc-incremental-candidate-20260715/base/reddit_voc_site_snapshot_20260715_6efd951e6095/manifest.json",
        "baseline_report_index": baseline_reports / "report-index.json",
        "candidate_report_index": candidate_reports / "report-index.json",
        "baseline_monthly_report": baseline_reports / "current/monthly.json",
        "candidate_monthly_report": candidate_reports / "current/monthly.json",
        "baseline_personas_manifest": root / "ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_personas_20260715_v2/manifest.json",
        "candidate_personas_manifest": root / "tmp/reddit-voc-incremental-candidate-20260715/personas/reddit_voc_personas_20260715_a900e6ce7b63/manifest.json",
        "candidate_gate": root / "tmp/reddit-voc-incremental-candidate-20260715/candidate-validation-receipt-rc3.json",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"required analysis inputs are missing: {missing}")

    notebook = _build_notebook(root=root, output_dir=output_dir, inputs=inputs)
    notebook_path = output_dir / "reddit-voc-incremental-impact.ipynb"
    client = NotebookClient(
        notebook,
        timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(root)}},
    )
    executed = client.execute()
    nbformat.write(executed, notebook_path)

    summary_path = output_dir / "impact-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_artifact = _build_report_artifact(summary, summary["generated_at_utc"])
    report_source = output_dir / "report-source.sqlite3"
    _materialize_report_source_database(
        report_source,
        report_artifact["snapshot"]["datasets"],
    )
    _write_json(output_dir / "artifact.json", report_artifact)
    _write_json(output_dir / "source-notes.json", _build_source_notes(summary))

    print(
        json.dumps(
            {
                "artifact": _relative(root, output_dir / "artifact.json"),
                "notebook": _relative(root, notebook_path),
                "report_source": _relative(root, report_source),
                "source_notes": _relative(root, output_dir / "source-notes.json"),
                "status": "executed_and_authored",
                "summary": _relative(root, summary_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
