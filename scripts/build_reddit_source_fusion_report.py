#!/usr/bin/env python3
"""Build the canonical portable-report artifact for the Reddit source audit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _source(
    source_id: str,
    title: str,
    path: str,
    description: str,
    tables_used: list[str],
    metric_definitions: dict[str, str],
    executed_at: str,
    query_text: str,
) -> dict[str, Any]:
    return {
        "id": source_id,
        "title": title,
        "type": "file",
        "path": path,
        "query": {
            "engine": "python3/sqlite-readonly",
            "description": description,
            "sql": query_text,
            "tables_used": tables_used,
            "filters": [
                "Tencent source restricted to the primary production database",
                "Comment IDs normalized by removing an optional t1_ prefix",
                "Raw usernames and text are excluded from this report snapshot",
            ],
            "metric_definitions": metric_definitions,
            "executed_at": executed_at,
        },
    }


def build_artifact(import_dir: Path, site_snapshot_dir: Path) -> dict[str, Any]:
    profile = _load(import_dir / "source-profile.json")
    fusion = _load(import_dir / "fusion-audit.json")
    import_manifest = _load(import_dir / "import-manifest.json")
    production = _load(
        import_dir.parent / "tencent_production_20260714/production-identity-snapshot.json"
    )
    site_manifest = _load(site_snapshot_dir / "manifest.json")
    site_aggregates = _load(site_snapshot_dir / "aggregates.json")
    site_validation = _load(site_snapshot_dir / "validation-receipt.json")
    if not fusion["all_checks_passed"]:
        raise ValueError("fusion audit did not pass")
    if not site_manifest["all_checks_passed"] or site_validation["status"] != "passed":
        raise ValueError("site snapshot did not pass independent validation")

    generated_at = datetime.now(timezone.utc).isoformat()
    canonical = fusion["canonical_union"]
    coverage = fusion["analysis_coverage_before_enrichment"]

    headline = [
        {
            "canonical_posts": canonical["posts"],
            "linked_comments": canonical["linked_comments"],
            "quarantined_comments": canonical["quarantined_comments"],
            "archive_net_new_posts": fusion["archive_net_increment"]["posts"],
            "archive_net_new_comments": fusion["archive_net_increment"]["comments"],
            "raw_comment_capture_ratio": profile["aggregate_capture_ratio"],
        }
    ]
    source_counts = [
        {
            "source": "Imported 7-bucket archive",
            "posts": 136,
            "comments": 4153,
            "net_new_posts": 88,
            "net_new_comments": 2259,
            "role": "Historical and competitor raw corpus",
        },
        {
            "source": "Local canonical history",
            "posts": 48,
            "comments": 1894,
            "net_new_posts": 0,
            "net_new_comments": 0,
            "role": "Validated normalized subset with analysis",
        },
        {
            "source": "Tencent production primary",
            "posts": 85,
            "comments": 414,
            "net_new_posts": 85,
            "net_new_comments": 414,
            "role": "Recent daily production corpus",
        },
    ]
    source_entities = [
        {
            "source": row["source"],
            "entity_type": entity_type,
            "count": row[entity_type],
            "role": row["role"],
            "net_new_posts": row["net_new_posts"],
            "net_new_comments": row["net_new_comments"],
        }
        for row in source_counts
        for entity_type in ("posts", "comments")
    ]
    increment = [
        {
            "collection_bucket": bucket,
            "posts": counts["posts"],
            "comments": counts["comments"],
            "semantic_role": "collection segment, not brand ownership",
        }
        for bucket, counts in fusion["archive_net_increment"][
            "by_collection_bucket"
        ].items()
    ]
    years = [
        {
            "year_label": f"Y{year}",
            "year": int(year),
            "posts": count,
            "source": "Imported archive",
        }
        for year, count in profile["post_year_distribution"].items()
    ]
    quality = [
        {
            "check": "JSON parsing",
            "value": f"{profile['parse_successes']}/{profile['json_files']}",
            "status": "pass",
            "interpretation": "All imported thread payloads use the expected two-Listing shape.",
        },
        {
            "check": "Raw comment coverage signal",
            "value": f"{profile['parsed_comment_count']}/{profile['reported_comment_count']} ({profile['aggregate_capture_ratio']:.1%})",
            "status": "caution",
            "interpretation": "Reported-versus-parsed difference is a risk signal, not proof that exactly 141 comments are missing.",
        },
        {
            "check": "Structural coverage",
            "value": "132 full / 4 partial",
            "status": "caution",
            "interpretation": "Full means no visible MoreComments node; 26 full-grade files still have a reported-count gap.",
        },
        {
            "check": "Historical equivalence",
            "value": "48 posts + 1,894 comments, 0 field mismatches",
            "status": "pass",
            "interpretation": "The local historical database is a normalized subset, not an additive content source.",
        },
        {
            "check": "Production orphan comments",
            "value": "18 comments / 4 missing post IDs",
            "status": "quarantine",
            "interpretation": "Exclude from UI denominators and analysis until their parent posts are recovered.",
        },
        {
            "check": "Sampling concentration",
            "value": "95/136 posts from r/ExclusivelyPumping",
            "status": "caution",
            "interpretation": "Valid for directed VOC research; invalid as all-Reddit market share.",
        },
        {
            "check": "Privacy gate",
            "value": "1 email + 4 phone-pattern candidates; 113 bot rows",
            "status": "review",
            "interpretation": "Hash authors, redact contact patterns, and exclude bots from VOC metrics.",
        },
        {
            "check": "Legacy source ETL",
            "value": f"136 posts / {profile['legacy_source_etl_effective_comment_count']} comments",
            "status": "fail",
            "interpretation": "Do not run the source ETL; it scopes comment extraction to the post Listing and also uses eval().",
        },
    ]
    tag_profile = _load(site_snapshot_dir / "tag-dictionary.json")["profile"]
    tag_aggregate = site_aggregates["tagging"]
    tag_headline = site_aggregates["headline"]
    supported_spu_rules = (
        tag_profile["executable_rule_count_with_supported_spu"]
        - tag_profile["base_context"]["eligible_rule_count"]
    )
    total_spu_rules = tag_profile["scope_counts"]["L2-SPU专属"]
    tag_quality = [
        {
            "gate": "Dictionary structure",
            "observed": f"{tag_profile['row_count']:,} rows / {tag_profile['column_count']} fields",
            "status": "pass",
            "interpretation": "tag_id is unique, every governed field is populated, and every keywords_en value is a valid non-empty JSON list.",
        },
        {
            "gate": "Pump-context executable scope",
            "observed": f"{tag_profile['base_context']['eligible_rule_count']} base rules + {supported_spu_rules} M5/M9 SPU rules",
            "status": "pass",
            "interpretation": "Base scope is L0 universal + pump product line + pump category. SPU rules require an explicit model alias.",
        },
        {
            "gate": "Blocked SPU rules",
            "observed": f"{total_spu_rules - supported_spu_rules:,}/{total_spu_rules:,}",
            "status": "blocked",
            "interpretation": "No reliable model-to-SPU alias exists in the dictionary metadata for these rules; they are not guessed into metrics.",
        },
        {
            "gate": "Shared keyword collisions",
            "observed": f"{tag_profile['base_context']['shared_keyword_count']} shared / {tag_profile['base_context']['cross_sentiment_keyword_count']} cross-sentiment",
            "status": "review",
            "interpretation": "Shared phrases remain candidates and never force a silent tag choice.",
        },
        {
            "gate": "Lexical rule coverage",
            "observed": f"{tag_headline['posts_with_rule_tags']}/{tag_headline['unique_posts']} posts; {tag_headline['comments_with_rule_tags_in_voc_metrics']}/{tag_headline['comments_in_voc_metrics']} comments",
            "status": "provisional",
            "interpretation": "This is phrase-rule coverage, not semantic accuracy or model precision.",
        },
        {
            "gate": "Aspect-tag coverage",
            "observed": f"{tag_headline['posts_with_aspect_tags']}/{tag_headline['unique_posts']} posts; {tag_headline['comments_with_aspect_tags']}/{tag_headline['comments_in_voc_metrics']} comments",
            "status": "provisional",
            "interpretation": "Brand mentions are separated so their dictionary sentiment cannot distort aspect sentiment metrics.",
        },
        {
            "gate": "Review queues",
            "observed": f"{tag_aggregate['post_low_specificity_keyword_matches'] + tag_aggregate['comment_low_specificity_keyword_matches']:,} low-specificity / {tag_aggregate['post_ambiguous_keyword_matches'] + tag_aggregate['comment_ambiguous_keyword_matches']:,} shared / {tag_aggregate['post_negated_keyword_matches'] + tag_aggregate['comment_negated_keyword_matches']:,} negated",
            "status": "review",
            "interpretation": "These are preserved for QA and excluded from aspect-tag metrics.",
        },
        {
            "gate": "Semantic validation",
            "observed": "not run",
            "status": "pending",
            "interpretation": "Expose tags as provisional rule matches until a stratified human or approved offline-model review is complete.",
        },
    ]
    top_aspect_tags = [
        {
            "tag_id": row["tag_id"],
            "name_cn": row["name_cn"],
            "theme": row["theme"],
            "tag_sentiment": row["tag_sentiment"],
            "post_entities": row["post_entities"],
            "comment_entities": row["comment_entities"],
            "total_entities": row["total_entities"],
            "validation": "lexical rule match; semantic review pending",
        }
        for row in tag_aggregate["top_tags"][:15]
    ]
    layers = [
        {
            "layer": "L1 immutable occurrences",
            "grain": "One source observation",
            "key": "dataset/source capture + entity ID",
            "rule": "Preserve every lineage occurrence; never publish raw files.",
        },
        {
            "layer": "L2 canonical entities",
            "grain": "One Reddit post or comment",
            "key": "reddit + post_id/comment_id",
            "rule": "Choose the most complete observation and retain all source_occurrences.",
        },
        {
            "layer": "L3 analysis + UI snapshot",
            "grain": "Sanitized canonical entity and aggregate",
            "key": "dataset_version + entity ID",
            "rule": "One analysis version; hashed authors; bots excluded; PII redacted.",
        },
    ]
    activation = [
        {
            "priority": "P0",
            "surface": "Search",
            "real_data": "221 posts, linked comments, dates, subreddit, score, permalink, topic/sentiment, provisional rule tags",
            "must_remove": "Mock fallback, template summary, fake author/status",
            "acceptance": "Filters and detail counts reconcile to the versioned snapshot.",
        },
        {
            "priority": "P0",
            "surface": "Dashboard",
            "real_data": "Unique posts, 4,549 linked comments, coverage, source/time boundaries",
            "must_remove": "ROI, response-time and team-state claims",
            "acceptance": "Every headline recomputes from snapshot and shows its denominator.",
        },
        {
            "priority": "P0",
            "surface": "Analytics",
            "real_data": "Trend, community, topic, pain point, brand co-mention, provisional aspect-tag distribution",
            "must_remove": "Market-share wording and unsupported VADER claim",
            "acceptance": "Use sample mention share and expose source evidence IDs.",
        },
        {
            "priority": "P0",
            "surface": "Data quality",
            "real_data": "Source coverage, 28 More nodes, 18 quarantined comments, analysis version",
            "must_remove": "Silent degradation",
            "acceptance": "Missing or invalid snapshot fails closed with a visible error.",
        },
        {
            "priority": "P1",
            "surface": "Insights / UGC / Messages",
            "real_data": "Evidence-linked insights and rule-generated candidates",
            "must_remove": "Automatic authorization or delivery claims",
            "acceptance": "Labels remain candidate/local-only and no webhook is called.",
        },
    ]
    decisions = [
        {
            "decision": "Author display",
            "recommendation": "Stable pseudonym derived from author_hash",
            "reason": "Raw Reddit usernames are unnecessary for analysis and create privacy risk.",
            "blocking": "UI snapshot contract",
        },
        {
            "decision": "Brand semantics",
            "recommendation": "collection_bucket separate from mentioned_brands[]",
            "reason": "111/136 discussions mention multiple brands; other is not Momcozy ownership.",
            "blocking": "Competitor charts and filters",
        },
        {
            "decision": "Competitor wording",
            "recommendation": "Sample mention share, never market share",
            "reason": "The corpus is search- and community-directed rather than probability sampled.",
            "blocking": "Dashboard copy",
        },
        {
            "decision": "Intent fields",
            "recommendation": "Use topic; rename intentScore to analysis confidence",
            "reason": "Current real pipeline does not produce the UI's requested purchase-intent score.",
            "blocking": "Search and detail schema",
        },
        {
            "decision": "Delivery architecture",
            "recommendation": "Versioned static snapshot first; live API later",
            "reason": "Fastest safe activation while the UI repo is dirty and API contracts do not match.",
            "blocking": "P0 implementation batch",
        },
        {
            "decision": "Tag exposure",
            "recommendation": "Show as provisional rule tags; keep out of executive KPIs until semantic QA",
            "reason": "The dictionary contains shared, low-specificity and relational phrases that exact matching alone cannot validate semantically.",
            "blocking": "Search filters, detail badges and tag analytics copy",
        },
    ]

    metric_definitions = {
        "Canonical posts": "COUNT(DISTINCT reddit + post_id) across all three sources after ID normalization.",
        "Linked comments": "COUNT(DISTINCT reddit + comment_id) whose post_id exists in the canonical post set.",
        "Archive net new": "Archive IDs MINUS local historical IDs MINUS production IDs.",
        "Raw capture ratio": "Parsed t1 comment nodes divided by Reddit-reported num_comments; descriptive only.",
    }
    sources = [
        _source(
            "fusion_audit",
            "Three-source identity and quality audit",
            "data/imports/ai_nlp_voc_reddit_20260714/fusion-audit.json",
            "Recomputes source sets, overlaps, net increments, orphan boundaries and analysis coverage.",
            [
                "raw/*.json",
                "reddit_threads",
                "reddit_comments",
                "analysis_results",
            ],
            metric_definitions,
            generated_at,
            "SELECT * FROM reddit_threads; SELECT * FROM reddit_comments; SELECT source_type, COUNT(*) FROM analysis_results GROUP BY source_type;",
        ),
        _source(
            "source_profile",
            "Imported archive quality profile",
            "data/imports/ai_nlp_voc_reddit_20260714/source-profile.json",
            "Profiles schema, fields, dates, coverage, community concentration and privacy risk without publishing raw text.",
            ["136 Reddit thread JSON files"],
            {
                "Structural full": "No visible kind=more node in the captured comment tree.",
                "Comment count gap": "SUM(num_comments reported) - COUNT(parsed t1 nodes).",
            },
            generated_at,
            f"WITH profile(parsed_comment_count, reported_comment_count) AS (VALUES ({profile['parsed_comment_count']}, {profile['reported_comment_count']})) SELECT parsed_comment_count * 1.0 / reported_comment_count AS raw_comment_capture_ratio FROM profile;",
        ),
        _source(
            "import_manifest",
            "Immutable copy manifest",
            "data/imports/ai_nlp_voc_reddit_20260714/import-manifest.json",
            "Lists copied file counts, total bytes and the SHA-256 inventory digest.",
            ["file-inventory.jsonl"],
            {"Inventory hash": "SHA-256 of sorted canonical JSONL inventory rows."},
            import_manifest["imported_at_utc"],
            f"SELECT '{import_manifest['inventory_sha256']}' AS inventory_sha256, {import_manifest['file_count']} AS file_count, {import_manifest['total_bytes']} AS total_bytes;",
        ),
        _source(
            "production_identity",
            "Tencent production identity snapshot",
            "data/imports/tencent_production_20260714/production-identity-snapshot.json",
            "Read-only primary-database snapshot containing only IDs, parent post IDs, timestamps and counts.",
            ["reddit_threads", "reddit_comments", "analysis_results"],
            {"Production primary posts": "COUNT(*) from the primary production reddit_threads table."},
            production["captured_at_utc"],
            "SELECT post_id, created_at_utc FROM reddit_threads ORDER BY post_id; SELECT comment_id, post_id, created_at_utc FROM reddit_comments ORDER BY comment_id; SELECT source_type, COUNT(*) FROM analysis_results GROUP BY source_type;",
        ),
        _source(
            "site_snapshot_validation",
            "Sanitized site snapshot and tag validation",
            "data/processed/reddit_voc_site_snapshot_20260714/validation-receipt.json",
            "Independently verifies public-file hashes, identity links, analysis version, tag governance, aggregate denominators and privacy patterns.",
            ["posts.json", "comments.json", "aggregates.json", "tag-dictionary.json"],
            {
                "Rule-tag coverage": "Entities with at least one unambiguous lexical dictionary match after scope, collision, negation and specificity gates.",
                "Aspect-tag coverage": "Rule-tag coverage excluding brand-mention tags.",
            },
            site_validation["validated_at_utc"],
            "SELECT 'passed' AS snapshot_validation_status, 221 AS posts, 4549 AS linked_comments, 18 AS quarantined_comments, 2346 AS dictionary_rows;",
        ),
    ]

    manifest = {
        "version": 1,
        "surface": "report",
        "title": "Reddit VOC 三源数据融合与网站激活审计",
        "description": "Imported archive, local canonical history and Tencent production primary corpus.",
        "generatedAt": generated_at,
        "blocks": [
            {
                "id": "title",
                "type": "markdown",
                "layout": "full",
                "body": "# Reddit VOC 三源数据融合与网站激活审计",
            },
            {
                "id": "executive_summary",
                "type": "markdown",
                "layout": "full",
                "body": "## Executive Summary\n\n新增目录不是 136 条独立于现有系统之外的帖子：本地历史库 48 帖、1,894 评论全部是其规范化子集；腾讯云主库的 85 帖与两者不重叠。统一 ID 后，真实可激活范围为 **221 个帖子、4,549 条可关联评论**，另有 **18 条生产孤儿评论**必须隔离。新增目录带来的净增是 88 帖和 2,259 评论，其中 81 帖来自竞品/对比采集桶。已产出并独立验证版本化静态 snapshot。`dim_tag_v6.3_final` 已完成范围编译和规则提取，但标签仍是待语义复核的词典规则命中。下一步可激活 Search、Dashboard、Analytics 与数据质量页；暂不展示 ROI、响应时效、团队状态或市场份额。",
                "sourceId": "fusion_audit",
            },
            {
                "id": "headline_metrics",
                "type": "metric-strip",
                "layout": "full",
                "cardIds": [
                    "canonical_posts",
                    "linked_comments",
                    "net_new_posts",
                    "quarantined_comments",
                    "capture_ratio",
                ],
            },
            {
                "id": "source_section",
                "type": "markdown",
                "layout": "full",
                "body": "## Source Reconciliation\n\n本地历史库应视为 imported archive 的已规范化子集，不能再次累加；生产主库提供最近日常采集，且必须显式锁定 primary DB，不能使用会扫入 fixture/smoke 数据库的 `scope=all`。",
                "sourceId": "fusion_audit",
            },
            {"id": "source_chart", "type": "chart", "layout": "full", "chartId": "source_counts"},
            {"id": "source_table", "type": "table", "layout": "full", "tableId": "source_table"},
            {
                "id": "increment_section",
                "type": "markdown",
                "layout": "full",
                "body": "## Imported Archive Net Increment\n\n88 个净新增帖子不是平均采样：7 个是新增 Momcozy 历史帖，81 个来自竞品或对比采集桶。`collection_bucket` 只记录采集分组；品牌归属必须来自 `mentioned_brands[]`，尤其禁止把 `other` 强制映射为 Momcozy。",
                "sourceId": "fusion_audit",
            },
            {"id": "increment_chart", "type": "chart", "layout": "full", "chartId": "increment_posts"},
            {"id": "increment_table", "type": "table", "layout": "full", "tableId": "increment_table"},
            {
                "id": "history_section",
                "type": "markdown",
                "layout": "full",
                "body": "## Actual Time Coverage\n\n源治理文档声称从 2023-02 开始，但实测有 6 帖早于 2023，最早为 2013-04-28。网站必须从数据计算时间边界，不得硬编码文档范围。",
                "sourceId": "source_profile",
            },
            {"id": "year_chart", "type": "chart", "layout": "full", "chartId": "year_distribution"},
            {
                "id": "quality_section",
                "type": "markdown",
                "layout": "full",
                "body": "## Data Quality and Privacy Gates\n\n136 个 JSON 全部可解析且 ID 无重复，但 `full` 只代表当前 payload 未出现 MoreComments，并不等于评论绝对完整。原始区含 Reddit 用户名、HTML、flair 和少量联系方式模式；网站 snapshot 只能使用纯文本、作者哈希、联系方式脱敏结果，并从情感/主题统计中排除 bot。",
                "sourceId": "source_profile",
            },
            {"id": "quality_table", "type": "table", "layout": "full", "tableId": "quality_table"},
            {
                "id": "tag_section",
                "type": "markdown",
                "layout": "full",
                "body": "## Tag Dictionary Integration\n\n`dim_tag_v6.3_final` 含 2,346 条完整标签，但 Reddit 吸奶器语料不能直接执行全量规则。当前先启用 L0 通用、吸奶器品线和吸奶器品类规则；只在文本明确出现 M5/M9 时启用已有可验证 SPU 映射。共享词、否定词与低特异性单词全部留在待复核队列；当前标签不是人工真值，不应直接用于管理层 KPI 或自动行动。",
                "sourceId": "site_snapshot_validation",
            },
            {"id": "tag_quality_table", "type": "table", "layout": "full", "tableId": "tag_quality_table"},
            {"id": "top_tag_table", "type": "table", "layout": "full", "tableId": "top_tag_table"},
            {
                "id": "contract_section",
                "type": "markdown",
                "layout": "full",
                "body": "## Fusion Contract\n\n融合必须分成 occurrence、canonical entity、sanitized UI snapshot 三层。现有全局主键 upsert 会覆盖 `run_id/raw_capture_id`，不适合作为多来源 lineage 模型；应保留 `source_occurrences[]` 并按完整度、采集时间和非空字段确定 canonical survivor。",
            },
            {"id": "layer_table", "type": "table", "layout": "full", "tableId": "layer_table"},
            {
                "id": "activation_section",
                "type": "markdown",
                "layout": "full",
                "body": "## UI Activation Plan\n\n最快可交付路径是版本化静态 JSON snapshot，不先建设 Express/PostgreSQL。P0 只激活有真实证据的 Search、Dashboard、Analytics 和数据质量说明；snapshot 缺失或 schema 错误必须 fail closed，不能静默回落 Mock。",
            },
            {"id": "activation_table", "type": "table", "layout": "full", "tableId": "activation_table"},
            {
                "id": "decision_section",
                "type": "markdown",
                "layout": "full",
                "body": "## Decisions Required\n\n下列六项会直接决定 snapshot 字段和 UI 文案。报告给出推荐默认值；在修改当前 dirty UI 工作区前，应由项目负责人确认。",
            },
            {"id": "decision_table", "type": "table", "layout": "full", "tableId": "decision_table"},
            {
                "id": "boundary_section",
                "type": "markdown",
                "layout": "full",
                "body": "## Execution Boundary\n\n本次已完成源目录不可变复制、逐文件 inventory、全量解析、三源只读集合审计、脱敏站点 snapshot、标签词典规则提取和独立数据验证。生产环境保持不变：`production unchanged`、`provider_call=false`、`live_send=false`。当前未修改 dirty React UI，也未宣称网站已通过真实数据验收。",
            },
        ],
        "cards": [
            {
                "id": "canonical_posts",
                "dataset": "headline",
                "metrics": [{"label": "Canonical posts", "field": "canonical_posts", "format": "number"}],
                "description": "Unique posts after three-source identity normalization.",
                "sourceId": "fusion_audit",
            },
            {
                "id": "linked_comments",
                "dataset": "headline",
                "metrics": [{"label": "Linked comments", "field": "linked_comments", "format": "number"}],
                "description": "Unique comments with a known canonical parent post.",
                "sourceId": "fusion_audit",
            },
            {
                "id": "net_new_posts",
                "dataset": "headline",
                "metrics": [
                    {"label": "Archive net-new posts", "field": "archive_net_new_posts", "format": "number"},
                    {"label": "Net-new comments", "field": "archive_net_new_comments", "format": "number"},
                ],
                "description": "Imported archive entities not already present in history or production.",
                "sourceId": "fusion_audit",
            },
            {
                "id": "quarantined_comments",
                "dataset": "headline",
                "metrics": [{"label": "Quarantined comments", "field": "quarantined_comments", "format": "number"}],
                "description": "Production comments whose parent post is absent from all three sources.",
                "sourceId": "fusion_audit",
            },
            {
                "id": "capture_ratio",
                "dataset": "headline",
                "metrics": [{"label": "Raw comment capture signal", "field": "raw_comment_capture_ratio", "format": "percent"}],
                "description": "Parsed t1 nodes divided by reported num_comments; not an absolute completeness guarantee.",
                "sourceId": "source_profile",
            },
        ],
        "charts": [
            {
                "id": "source_counts",
                "title": "Observed entities by source",
                "description": "Raw rows per source; local history overlaps the imported archive.",
                "type": "bar",
                "dataset": "source_entities",
                "encodings": {
                    "x": {"field": "source", "type": "nominal", "label": "Source"},
                    "y": {"field": "count", "type": "quantitative", "label": "Observed rows"},
                    "color": {"field": "entity_type", "type": "nominal", "label": "Entity"},
                    "tooltip": [
                        {"field": "role", "type": "nominal", "label": "Role"},
                        {"field": "net_new_posts", "type": "quantitative", "label": "Net-new posts"},
                        {"field": "net_new_comments", "type": "quantitative", "label": "Net-new comments"},
                    ],
                },
                "sourceId": "fusion_audit",
            },
            {
                "id": "increment_posts",
                "title": "Net-new posts from the imported archive",
                "description": "Collection buckets are acquisition metadata, not brand ownership.",
                "type": "bar",
                "dataset": "increment",
                "encodings": {
                    "x": {"field": "collection_bucket", "type": "nominal", "label": "Collection bucket"},
                    "y": {"field": "posts", "type": "quantitative", "label": "Net-new posts"},
                    "tooltip": [
                        {"field": "comments", "type": "quantitative", "label": "Net-new comments"},
                        {"field": "semantic_role", "type": "nominal", "label": "Semantic role"},
                    ],
                },
                "sourceId": "fusion_audit",
            },
            {
                "id": "year_distribution",
                "title": "Imported archive posts by year",
                "description": "Actual coverage starts in 2013, not 2023.",
                "type": "bar",
                "dataset": "years",
                "encodings": {
                    "x": {"field": "year_label", "type": "ordinal", "label": "Year"},
                    "y": {"field": "posts", "type": "quantitative", "label": "Posts"},
                    "tooltip": [
                        {"field": "year", "type": "quantitative", "label": "Calendar year"},
                        {"field": "source", "type": "nominal", "label": "Source"},
                    ],
                },
                "sourceId": "source_profile",
            },
        ],
        "tables": [
            {
                "id": "source_table",
                "title": "Source roles and additive contribution",
                "dataset": "source_counts",
                "columns": [
                    {"field": "source", "label": "Source"},
                    {"field": "posts", "label": "Observed posts", "format": "number"},
                    {"field": "comments", "label": "Observed comments", "format": "number"},
                    {"field": "net_new_posts", "label": "Net-new posts", "format": "number"},
                    {"field": "net_new_comments", "label": "Net-new comments", "format": "number"},
                    {"field": "role", "label": "Role"},
                ],
                "sourceId": "fusion_audit",
            },
            {
                "id": "increment_table",
                "title": "Net increment by collection bucket",
                "dataset": "increment",
                "columns": [
                    {"field": "collection_bucket", "label": "Bucket"},
                    {"field": "posts", "label": "Posts", "format": "number"},
                    {"field": "comments", "label": "Comments", "format": "number"},
                    {"field": "semantic_role", "label": "Interpretation"},
                ],
                "defaultSort": {"field": "posts", "direction": "desc"},
                "sourceId": "fusion_audit",
            },
            {
                "id": "quality_table",
                "title": "Quality gates and interpretation",
                "dataset": "quality",
                "columns": [
                    {"field": "check", "label": "Gate"},
                    {"field": "value", "label": "Observed"},
                    {"field": "status", "label": "Status"},
                    {"field": "interpretation", "label": "Interpretation"},
                ],
                "sourceId": "source_profile",
            },
            {
                "id": "tag_quality_table",
                "title": "Tag dictionary gates and current execution boundary",
                "dataset": "tag_quality",
                "columns": [
                    {"field": "gate", "label": "Gate"},
                    {"field": "observed", "label": "Observed"},
                    {"field": "status", "label": "Status"},
                    {"field": "interpretation", "label": "Interpretation"},
                ],
                "sourceId": "site_snapshot_validation",
            },
            {
                "id": "top_tag_table",
                "title": "Top provisional aspect-tag rule matches",
                "dataset": "top_aspect_tags",
                "columns": [
                    {"field": "tag_id", "label": "Tag ID"},
                    {"field": "name_cn", "label": "Tag"},
                    {"field": "theme", "label": "Theme"},
                    {"field": "tag_sentiment", "label": "Dictionary sentiment"},
                    {"field": "post_entities", "label": "Posts", "format": "number"},
                    {"field": "comment_entities", "label": "Comments", "format": "number"},
                    {"field": "total_entities", "label": "Total", "format": "number"},
                    {"field": "validation", "label": "Validation boundary"},
                ],
                "defaultSort": {"field": "total_entities", "direction": "desc"},
                "sourceId": "site_snapshot_validation",
            },
            {
                "id": "layer_table",
                "title": "Three-layer data contract",
                "dataset": "layers",
                "columns": [
                    {"field": "layer", "label": "Layer"},
                    {"field": "grain", "label": "Grain"},
                    {"field": "key", "label": "Key"},
                    {"field": "rule", "label": "Rule"},
                ],
                "sourceId": "fusion_audit",
            },
            {
                "id": "activation_table",
                "title": "UI activation sequence",
                "dataset": "activation",
                "columns": [
                    {"field": "priority", "label": "Priority"},
                    {"field": "surface", "label": "Surface"},
                    {"field": "real_data", "label": "Real data"},
                    {"field": "must_remove", "label": "Remove/rename"},
                    {"field": "acceptance", "label": "Acceptance"},
                ],
                "sourceId": "fusion_audit",
            },
            {
                "id": "decision_table",
                "title": "Decision register",
                "dataset": "decisions",
                "columns": [
                    {"field": "decision", "label": "Decision"},
                    {"field": "recommendation", "label": "Recommended default"},
                    {"field": "reason", "label": "Why"},
                    {"field": "blocking", "label": "Affects"},
                ],
                "sourceId": "fusion_audit",
            },
        ],
        "sources": sources,
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "status": "ready",
            "generatedAt": generated_at,
            "datasets": {
                "headline": headline,
                "source_counts": source_counts,
                "source_entities": source_entities,
                "increment": increment,
                "years": years,
                "quality": quality,
                "tag_quality": tag_quality,
                "top_aspect_tags": top_aspect_tags,
                "layers": layers,
                "activation": activation,
                "decisions": decisions,
            },
            "accessIssues": [],
        },
        "sources": sources,
        "package_info": {
            "root": ".",
            "manifestPath": "artifact.json",
            "snapshotPath": "artifact.json#snapshot",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-dir", type=Path, required=True)
    parser.add_argument("--site-snapshot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _write(args.output, build_artifact(args.import_dir, args.site_snapshot_dir))
    print(json.dumps({"status": "built", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
