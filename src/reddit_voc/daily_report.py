from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import os
import re
import shutil
from html import escape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import shorten
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlparse
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .keywords import match_keywords
from .dingtalk import with_required_keyword
from .report_contracts import canonical_json_bytes, sha256_hex
from .storage import VocStore


DETAIL_COLUMNS = [
    "采集窗口",
    "社区",
    "帖子 ID",
    "帖子链接",
    "媒体链接",
    "发帖时间（UTC）",
    "标题原文",
    "标题中文",
    "正文原文",
    "正文中文",
    "匹配关键词",
    "相关性校验",
    "相关依据",
    "内容类型",
    "Reddit 分数",
    "互动热度",
    "情感标签",
    "情感分数",
    "主题",
    "严重度",
    "痛点",
    "评论数",
    "评论整合原文",
    "评论整合中文",
    "覆盖状态",
    "翻译状态",
]

PREVALIDATED_DETAIL_COLUMNS = [
    "采集窗口",
    "社区",
    "帖子 ID",
    "帖子链接",
    "媒体链接",
    "发帖时间（UTC）",
    "标题中文",
    "标题原文",
    "正文中文",
    "正文原文",
    "匹配关键词",
    "相关性校验",
    "相关依据",
    "内容类型",
    "Reddit 分数",
    "互动热度",
    "情感标签",
    "情感分数",
    "主题",
    "严重度",
    "痛点",
    "评论数",
    "评论整合中文",
    "评论整合原文",
    "覆盖状态",
    "翻译状态",
]

DEFAULT_MEDIA_DIR = "media"
BRAND_BODY_COMMENT_PATTERN = re.compile(r"\bmomcozy\b", re.IGNORECASE)
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")

CATEGORY_PRODUCT_LABELS = {
    "baby bottle washer": "Bottle Washer",
    "bottle washer": "Bottle Washer",
    "countertop bottle washer": "Bottle Washer",
    "bottle washer sterilizer": "Bottle Washer Sterilizer",
    "pump parts washer": "Pump Parts Washer",
    "wearable breast pump": "Wearable Pump",
    "wearable pump": "Wearable Pump",
    "hands-free pump": "Wearable Pump",
    "hands free pump": "Wearable Pump",
    "hands-free breast pump": "Wearable Pump",
    "in-bra pump": "Wearable Pump",
    "cordless pump": "Wearable Pump",
    "portable pump": "Wearable Pump",
    "breast pump": "Breast Pump",
    "hospital grade pump": "Hospital Grade Pump",
    "manual pump": "Manual Pump",
    "electric pump": "Electric Pump",
    "collection cups": "Collection Cups",
    "pumping bra": "Pumping Bra",
    "flange inserts": "Flange Inserts",
    "flange insert": "Flange Inserts",
    "bottle sterilizer": "Bottle Sterilizer",
    "sterilizer dryer": "Sterilizer Dryer",
    "bottle dryer": "Bottle Dryer",
    "bottle warmer": "Bottle Warmer",
    "baby carrier": "Baby Carrier",
    "structured carrier": "Baby Carrier",
    "wrap carrier": "Baby Wrap",
    "baby wrap": "Baby Wrap",
    "high chair": "High Chair",
    "pregnancy pillow": "Pregnancy Pillow",
    "nursing pillow": "Nursing Pillow",
    "diaper bag": "Diaper Bag",
}


SENTIMENT_ZH = {
    "positive": "正面",
    "neutral": "中性",
    "negative": "负面",
}

TOPIC_ZH = {
    "competitor_comparison": "竞品对比",
    "insurance": "保险/报销",
    "purchase_decision": "购买决策",
    "customer_service": "客服/售后",
    "work_scenario": "工作/通勤场景",
    "troubleshooting": "问题排查",
    "product_evaluation": "产品评价",
    "other": "其他",
}

SEVERITY_ZH = {
    "low": "低",
    "medium": "中",
    "high": "高",
}

PAIN_POINT_ZH = {
    "output_supply": "吸奶量/供给",
    "leakage": "漏奶/溢出",
    "fit_comfort": "贴合/舒适度",
    "operations": "清洁/配件/电池/噪音",
    "support": "售后/退换/保修",
    "health": "乳腺健康",
    "work_scenario": "复工/通勤",
    "family_scenario": "家庭/新生儿场景",
    "insurance": "保险/报销",
}

EXACT_TRANSLATIONS = {
    "Momcozy M5 leaking at work": "Momcozy M5 在工作时漏奶",
    "I need a wearable pump for pumping at work, but my Momcozy M5 is leaking into the collection cups.": "我需要一款上班时使用的可穿戴吸奶器，但我的 Momcozy M5 会漏到集奶杯里。",
    "My Momcozy M5 kept leaking and customer service was slow.": "我的 Momcozy M5 一直漏奶，而且客服响应很慢。",
    "Elvie was quieter, but output was lower for me.": "Elvie 更安静，但对我来说吸奶量更低。",
}

LIBRETRANSLATE_MODES = {"libretranslate", "provider", "machine"}
DEEPSEEK_TRANSLATE_MODES = {"deepseek"}


@dataclass(frozen=True)
class TranslationResult:
    text: str
    status: str
    provider_call: bool = False


_TRANSLATION_CACHE: dict[tuple[str, str, str, str], TranslationResult] = {}


@dataclass(frozen=True)
class DailyReportResult:
    run_id: str
    insight_html: Path
    detail_csv: Path
    detail_xlsx: Path
    insight_png: Path
    row_count: int
    comment_count: int
    translation_mode: str
    translation_status: str
    provider_call: bool = False
    live_send: bool = False
    report_summary: dict[str, Any] = field(default_factory=dict)

    def artifact_paths(self) -> list[str]:
        return [str(self.insight_html), str(self.detail_xlsx), str(self.detail_csv), str(self.insight_png)]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "insight_html": str(self.insight_html),
            "detail_csv": str(self.detail_csv),
            "detail_xlsx": str(self.detail_xlsx),
            "insight_png": str(self.insight_png),
            "row_count": self.row_count,
            "comment_count": self.comment_count,
            "translation_mode": self.translation_mode,
            "translation_status": self.translation_status,
            "provider_call": self.provider_call,
            "live_send": self.live_send,
            "report_summary": self.report_summary,
        }


@dataclass(frozen=True)
class DailyReportSource:
    run: Mapping[str, object]
    posts: tuple[Mapping[str, object], ...]
    comments_by_post: Mapping[str, tuple[Mapping[str, object], ...]]
    analysis_by_post: Mapping[str, Mapping[str, object]]
    recent_threads: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class ReportContentField:
    run_id: str
    post_id: str
    comment_id: str | None
    field: str
    language: str
    text: str


class DailyReportBlocked(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class PreparedRenderResult:
    report: DailyReportResult
    dingtalk_bodies: tuple[Mapping[str, object], ...]
    content_fields: tuple[ReportContentField, ...]


def select_visible_daily_report_source(
    source: DailyReportSource,
    *,
    visibility_keyword: str = "Momcozy",
    visibility_rule_version: str = "daily-visible-v1",
) -> DailyReportSource:
    if visibility_keyword != "Momcozy":
        raise ValueError("visibility_keyword_unsupported")
    if visibility_rule_version != "daily-visible-v1":
        raise ValueError("visibility_rule_version_unsupported")
    matcher = re.compile(re.escape(visibility_keyword), re.IGNORECASE)
    visible_posts: list[Mapping[str, object]] = []
    visible_comments: dict[str, tuple[Mapping[str, object], ...]] = {}
    visible_analysis: dict[str, Mapping[str, object]] = {}
    seen: set[str] = set()
    for post in source.posts:
        post_id = str(post.get("post_id") or "")
        if not post_id or post_id in seen:
            raise ValueError("daily_report_source_post_id_invalid")
        seen.add(post_id)
        comments = tuple(source.comments_by_post.get(post_id, ()))
        original_text = "\n".join(
            [
                str(post.get("selftext") or ""),
                *(str(comment.get("body") or "") for comment in comments),
            ]
        )
        if matcher.search(original_text) is None:
            continue
        visible_posts.append(post)
        visible_comments[post_id] = comments
        if post_id in source.analysis_by_post:
            visible_analysis[post_id] = source.analysis_by_post[post_id]
    return DailyReportSource(
        run=source.run,
        posts=tuple(visible_posts),
        comments_by_post=visible_comments,
        analysis_by_post=visible_analysis,
        recent_threads=source.recent_threads,
    )


def source_excerpt_v1(
    *, title: str, body: str, comments: Sequence[str], max_bytes: int
) -> str:
    if isinstance(max_bytes, bool) or max_bytes < 0:
        raise ValueError("excerpt_max_bytes_invalid")
    if max_bytes == 0:
        return ""
    segments: list[tuple[str, str]] = []
    normalized_title = normalize_display_newlines(title)
    normalized_body = normalize_display_newlines(body)
    if normalized_title.strip():
        segments.append(("Title: ", normalized_title))
    if normalized_body.strip():
        segments.append(("Body: ", normalized_body))
    for index, comment in enumerate(comments, start=1):
        normalized_comment = normalize_display_newlines(comment)
        if normalized_comment.strip():
            segments.append((f"Comment {index}: ", normalized_comment))
    if not segments:
        return _utf8_prefix("(no English source text)", max_bytes)

    result = ""
    for label, value in segments:
        separator = "\n" if result else ""
        full_segment = separator + label + value
        remaining = max_bytes - len(result.encode("utf-8"))
        if remaining <= 0:
            break
        full_bytes = full_segment.encode("utf-8")
        if len(full_bytes) <= remaining:
            result += full_segment
            continue
        prefix = separator + label
        prefix_bytes = prefix.encode("utf-8")
        if len(prefix_bytes) >= remaining:
            result += _utf8_prefix(prefix, remaining)
        else:
            result += prefix + _utf8_prefix(value, remaining - len(prefix_bytes))
        break
    return result


def normalize_display_newlines(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("display_text_must_be_string")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def render_prevalidated_daily_report(
    source: DailyReportSource,
    *,
    translations: Mapping[str, str],
    output_dir: Path,
    artifact_version_url: str,
    dingtalk_max_bytes: int,
    dingtalk_required_keyword: str,
    dingtalk_max_parts: int = 2,
) -> PreparedRenderResult:
    if isinstance(dingtalk_max_bytes, bool) or dingtalk_max_bytes <= 0:
        raise ValueError("dingtalk_max_bytes_invalid")
    if isinstance(dingtalk_max_parts, bool) or not 1 <= dingtalk_max_parts <= 2:
        raise ValueError("dingtalk_max_parts_invalid")
    if not isinstance(artifact_version_url, str) or not artifact_version_url.startswith(("http://", "https://")):
        raise ValueError("artifact_version_url_invalid")
    run_id = str(source.run.get("run_id") or "")
    if not run_id:
        raise ValueError("daily_report_run_id_missing")

    expected_ids = {
        stable_id
        for post in source.posts
        for stable_id in _source_translation_ids(
            post,
            source.comments_by_post.get(str(post.get("post_id") or ""), ()),
        )
    }
    if set(translations) != expected_ids or any(not isinstance(value, str) for value in translations.values()):
        raise DailyReportBlocked("translation_id_set_mismatch")

    rows: list[dict[str, Any]] = []
    content_fields: list[ReportContentField] = []
    post_comments: dict[str, tuple[Mapping[str, object], ...]] = {}
    for post in source.posts:
        post_id = str(post.get("post_id") or "")
        comments = tuple(source.comments_by_post.get(post_id, ()))
        post_comments[post_id] = comments
        analysis = source.analysis_by_post.get(post_id, {})
        title_source = _exact_string(post.get("title"))
        body_source = _exact_string(post.get("selftext"))
        title_zh = translations[f"post:{post_id}:title"]
        body_zh = translations[f"post:{post_id}:body"]
        comment_original = _format_prevalidated_comments(comments, translations=None)
        comment_zh = _format_prevalidated_comments(comments, translations=translations)
        relevance_label, relevance_basis = _relevance_check(dict(post), [dict(value) for value in comments])
        row = {
            "采集窗口": _window_label(dict(source.run)),
            "社区": post.get("subreddit"),
            "帖子 ID": post_id,
            "帖子链接": post.get("source_url"),
            "媒体链接": _media_links(post.get("media_urls")),
            "_media_items": [],
            "发帖时间（UTC）": post.get("created_at_utc"),
            "标题原文": title_source,
            "标题中文": title_zh,
            "正文原文": body_source,
            "正文中文": body_zh,
            "匹配关键词": post.get("matched_keywords"),
            "相关性校验": relevance_label,
            "相关依据": relevance_basis,
            "内容类型": _content_type_for_post(dict(post), [dict(value) for value in comments], dict(analysis)),
            "Reddit 分数": post.get("score"),
            "互动热度": _heat_score(dict(post), [dict(value) for value in comments]),
            "情感标签": _sentiment_zh(analysis.get("sentiment_label")),
            "情感分数": analysis.get("sentiment_score"),
            "主题": _topic_zh(analysis.get("topic")),
            "严重度": _severity_zh(analysis.get("severity")),
            "痛点": _pain_points_zh(analysis.get("pain_points")),
            "评论数": len(comments),
            "评论整合原文": comment_original,
            "评论整合中文": comment_zh,
            "覆盖状态": _coverage_zh(post.get("coverage_grade")),
            "翻译状态": "deepseek_validated",
        }
        rows.append(row)
        content_fields.extend(
            [
                ReportContentField(run_id, post_id, None, "title", "zh", title_zh),
                ReportContentField(run_id, post_id, None, "title", "en", title_source),
                ReportContentField(run_id, post_id, None, "body", "zh", body_zh),
                ReportContentField(run_id, post_id, None, "body", "en", body_source),
            ]
        )
        for comment in comments:
            comment_id = str(comment.get("comment_id") or "")
            content_fields.extend(
                [
                    ReportContentField(
                        run_id,
                        post_id,
                        comment_id,
                        "comment",
                        "zh",
                        translations[f"comment:{comment_id}:body"],
                    ),
                    ReportContentField(
                        run_id,
                        post_id,
                        comment_id,
                        "comment",
                        "en",
                        _exact_string(comment.get("body")),
                    ),
                ]
            )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_csv = output_dir / f"{run_id}-daily-detail.csv"
    detail_xlsx = output_dir / f"{run_id}-daily-detail.xlsx"
    insight_html = output_dir / f"{run_id}-insight-report.html"
    insight_png = output_dir / f"{run_id}-insight-report-screenshot.png"
    _write_csv(detail_csv, rows, columns=PREVALIDATED_DETAIL_COLUMNS)
    _write_prevalidated_xlsx(detail_xlsx, rows=rows, content_fields=content_fields)
    _write_prevalidated_html(
        insight_html,
        run_id=run_id,
        run=source.run,
        rows=rows,
        content_fields=content_fields,
    )
    _write_insight_png(insight_png, rows, run_id=run_id, run=dict(source.run))

    bodies = _pack_prevalidated_dingtalk_bodies(
        run_id=run_id,
        rows=rows,
        posts=source.posts,
        comments_by_post=post_comments,
        translations=translations,
        artifact_version_url=artifact_version_url,
        max_bytes=dingtalk_max_bytes,
        required_keyword=dingtalk_required_keyword,
        max_parts=dingtalk_max_parts,
    )
    report_summary = _report_summary(rows, run=dict(source.run), collected_rows=rows)
    report_summary.update(
        {
            "visibility_rule_version": "daily-visible-v1",
            "visibility_keyword": "Momcozy",
            "visible_post_ids": [str(post.get("post_id")) for post in source.posts],
        }
    )
    report_summary["report_input_fingerprint"] = sha256_hex(
        canonical_json_bytes(
            {
                "visibility_rule_version": "daily-visible-v1",
                "visibility_keyword": "Momcozy",
                "content_fields": [
                    {
                        "run_id": field.run_id,
                        "post_id": field.post_id,
                        "comment_id": field.comment_id,
                        "field": field.field,
                        "language": field.language,
                        "text": field.text,
                    }
                    for field in content_fields
                ],
                "dingtalk_bodies": list(bodies),
            }
        )
    )
    report = DailyReportResult(
        run_id=run_id,
        insight_html=insight_html,
        detail_csv=detail_csv,
        detail_xlsx=detail_xlsx,
        insight_png=insight_png,
        row_count=len(rows),
        comment_count=sum(len(value) for value in post_comments.values()),
        translation_mode="deepseek_prevalidated",
        translation_status="complete",
        provider_call=False,
        live_send=False,
        report_summary=report_summary,
    )
    return PreparedRenderResult(
        report=report,
        dingtalk_bodies=bodies,
        content_fields=tuple(content_fields),
    )


def _utf8_prefix(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    payload = value.encode("utf-8")
    if len(payload) <= max_bytes:
        return value
    return payload[:max_bytes].decode("utf-8", errors="ignore")


def _exact_string(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("daily_report_text_not_string")
    return value


def _source_translation_ids(
    post: Mapping[str, object],
    comments: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    post_id = str(post.get("post_id") or "")
    if not post_id:
        raise ValueError("daily_report_source_post_id_invalid")
    identifiers = [f"post:{post_id}:title", f"post:{post_id}:body"]
    seen = set(identifiers)
    for comment in comments:
        comment_id = str(comment.get("comment_id") or "")
        stable_id = f"comment:{comment_id}:body"
        if not comment_id or stable_id in seen:
            raise ValueError("daily_report_source_comment_id_invalid")
        if comment.get("post_id") is not None and str(comment.get("post_id")) != post_id:
            raise ValueError("comment_post_id_mismatch")
        seen.add(stable_id)
        identifiers.append(stable_id)
    return tuple(identifiers)


def _format_prevalidated_comments(
    comments: Sequence[Mapping[str, object]],
    *,
    translations: Mapping[str, str] | None,
) -> str:
    parts: list[str] = []
    for index, comment in enumerate(comments, start=1):
        comment_id = str(comment.get("comment_id") or "")
        if translations is None:
            label = "原文"
            text = _exact_string(comment.get("body"))
        else:
            label = "中文"
            text = translations[f"comment:{comment_id}:body"]
        parts.append(
            "\n".join(
                [
                    f"[{index}] 评论ID={comment_id} | 分数={comment.get('score')} | 层级={comment.get('depth')}",
                    f"{label}：{text}",
                ]
            )
        )
    return "\n\n".join(parts)


def _write_prevalidated_xlsx(
    path: Path,
    *,
    rows: Sequence[Mapping[str, object]],
    content_fields: Sequence[ReportContentField],
) -> None:
    workbook = Workbook()
    detail = workbook.active
    detail.title = "detail"
    for column_index, column in enumerate(PREVALIDATED_DETAIL_COLUMNS, start=1):
        detail.cell(row=1, column=column_index, value=column)
    for row_index, row in enumerate(rows, start=2):
        for column_index, column in enumerate(PREVALIDATED_DETAIL_COLUMNS, start=1):
            value = "" if row.get(column) is None else str(row.get(column, ""))
            if len(value) > 500:
                value = value[:480] + "…（完整内容见 normalized sheets）"
            detail.cell(row=row_index, column=column_index, value=value)

    normalized_headers = [
        "run_id",
        "post_id",
        "comment_id",
        "field",
        "language",
        "part_index",
        "part_count",
        "text_chunk",
    ]
    content_sheet = workbook.create_sheet("content")
    comments_sheet = workbook.create_sheet("comments")
    for sheet in [content_sheet, comments_sheet]:
        sheet.append(normalized_headers)
    for field in content_fields:
        chunks = _unicode_chunks(field.text, max_code_points=30_000)
        target = comments_sheet if field.field == "comment" else content_sheet
        for part_index, chunk in enumerate(chunks, start=1):
            target.append(
                [
                    field.run_id,
                    field.post_id,
                    field.comment_id,
                    field.field,
                    field.language,
                    part_index,
                    len(chunks),
                    chunk,
                ]
            )
    workbook.save(path)


def _unicode_chunks(value: str, *, max_code_points: int) -> tuple[str, ...]:
    if max_code_points <= 0:
        raise ValueError("chunk_size_invalid")
    if not value:
        return ("",)
    return tuple(
        value[index : index + max_code_points]
        for index in range(0, len(value), max_code_points)
    )


def _write_prevalidated_html(
    path: Path,
    *,
    run_id: str,
    run: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
    content_fields: Sequence[ReportContentField],
) -> None:
    fields_by_post: dict[str, list[ReportContentField]] = {}
    for field in content_fields:
        fields_by_post.setdefault(field.post_id, []).append(field)
    articles: list[str] = []
    for row in rows:
        post_id = str(row.get("帖子 ID") or "")
        url = str(row.get("帖子链接") or "")
        sections = []
        for field in fields_by_post.get(post_id, []):
            comment_label = f" comment_id={field.comment_id}" if field.comment_id else ""
            sections.append(
                f'<section data-field="{escape(field.field)}" data-language="{escape(field.language)}">'
                f"<h3>{escape(field.field)} {escape(field.language)}{escape(comment_label)}</h3>"
                f"<pre>{escape(field.text)}</pre></section>"
            )
        articles.append(
            f'<article data-post-id="{escape(post_id)}">'
            f"<h2>{escape(str(row.get('标题中文') or ''))}</h2>"
            f'<a href="{escape(url)}">{escape(url)}</a>'
            + "".join(sections)
            + "</article>"
        )
    html = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<title>Reddit VOC 日报</title><style>body{font-family:sans-serif;max-width:1200px;margin:auto}"
        "article{border-bottom:1px solid #ddd;padding:20px 0}pre{white-space:pre-wrap;word-break:break-word}</style>"
        "</head><body>"
        f"<h1>Reddit VOC 日报 {escape(run_id)}</h1>"
        f"<p>{escape(str(run.get('window_start_utc') or ''))} — {escape(str(run.get('window_end_utc') or ''))}</p>"
        + "".join(articles)
        + "</body></html>"
    )
    path.write_text(html, encoding="utf-8")


def _pack_prevalidated_dingtalk_bodies(
    *,
    run_id: str,
    rows: Sequence[Mapping[str, object]],
    posts: Sequence[Mapping[str, object]],
    comments_by_post: Mapping[str, Sequence[Mapping[str, object]]],
    translations: Mapping[str, str],
    artifact_version_url: str,
    max_bytes: int,
    required_keyword: str,
    max_parts: int,
) -> tuple[Mapping[str, object], ...]:
    row_by_post = {str(row.get("帖子 ID")): row for row in rows}
    rendered_blocks: list[list[str]] = []
    for index, post in enumerate(posts, start=1):
        post_id = str(post.get("post_id") or "")
        row = row_by_post[post_id]
        comments = comments_by_post.get(post_id, ())
        rendered_blocks.append(
            _fit_prevalidated_block(
                index=index,
                post=post,
                row=row,
                comments=comments,
                translations=translations,
                run_id=run_id,
                artifact_version_url=artifact_version_url,
                max_bytes=max_bytes,
                required_keyword=required_keyword,
                max_parts=max_parts,
            )
        )

    if not rendered_blocks:
        rendered_blocks = [["## 今日 VOC", "本周期没有符合 daily-visible-v1 的可见帖子。"]]
    packed: list[list[list[str]]] = []
    current: list[list[str]] = []
    block_index = 0
    while block_index < len(rendered_blocks):
        block = rendered_blocks[block_index]
        candidate = [*current, block]
        body = _prevalidated_body(
            run_id=run_id,
            blocks=candidate,
            artifact_version_url=artifact_version_url,
            required_keyword=required_keyword,
            part_index=max(1, len(packed) + 1),
            part_count=max_parts,
        )
        if len(canonical_json_bytes(body)) <= max_bytes:
            current = candidate
            block_index += 1
            continue
        if not current:
            raise DailyReportBlocked("dingtalk_body_too_large")
        if len(packed) + 1 < max_parts:
            packed.append(current)
            current = []
            continue

        omitted = len(rendered_blocks) - block_index
        omission = [
            "## 其余 VOC",
            f"另有 {omitted} 条已完成中文翻译；完整标题、正文和评论请查看 HTML 洞察报告与采集明细。",
        ]
        while current:
            omission_body = _prevalidated_body(
                run_id=run_id,
                blocks=[*current, omission],
                artifact_version_url=artifact_version_url,
                required_keyword=required_keyword,
                part_index=max(1, len(packed) + 1),
                part_count=max_parts,
            )
            if len(canonical_json_bytes(omission_body)) <= max_bytes:
                break
            current.pop()
            omitted += 1
            omission[1] = (
                f"另有 {omitted} 条已完成中文翻译；完整标题、正文和评论请查看 HTML 洞察报告与采集明细。"
            )
        omission_body = _prevalidated_body(
            run_id=run_id,
            blocks=[*current, omission],
            artifact_version_url=artifact_version_url,
            required_keyword=required_keyword,
            part_index=max(1, len(packed) + 1),
            part_count=max_parts,
        )
        if len(canonical_json_bytes(omission_body)) > max_bytes:
            raise DailyReportBlocked("dingtalk_body_too_large")
        current = [*current, omission]
        block_index = len(rendered_blocks)
    if current:
        packed.append(current)
    if len(packed) > max_parts:
        raise DailyReportBlocked("dingtalk_body_too_large")

    bodies = tuple(
        _prevalidated_body(
            run_id=run_id,
            blocks=blocks,
            artifact_version_url=artifact_version_url,
            required_keyword=required_keyword,
            part_index=part_index,
            part_count=len(packed),
        )
        for part_index, blocks in enumerate(packed, start=1)
    )
    if any(len(canonical_json_bytes(body)) > max_bytes for body in bodies):
        raise DailyReportBlocked("dingtalk_body_too_large")
    return bodies


def _fit_prevalidated_block(
    *,
    index: int,
    post: Mapping[str, object],
    row: Mapping[str, object],
    comments: Sequence[Mapping[str, object]],
    translations: Mapping[str, str],
    run_id: str,
    artifact_version_url: str,
    max_bytes: int,
    required_keyword: str,
    max_parts: int,
) -> list[str]:
    title = _exact_string(post.get("title"))
    body = _exact_string(post.get("selftext"))
    comment_sources = [_exact_string(comment.get("body")) for comment in comments]

    def block_for(excerpt_budget: int) -> list[str]:
        excerpt = source_excerpt_v1(
            title=title,
            body=body,
            comments=comment_sources,
            max_bytes=excerpt_budget,
        )
        return _prevalidated_block_lines(
            index=index,
            post=post,
            row=row,
            comments=comments,
            translations=translations,
            excerpt=excerpt,
        )

    minimum_budget = min(96, max_bytes)
    minimum_block = block_for(minimum_budget)
    minimum_body = _prevalidated_body(
        run_id=run_id,
        blocks=[minimum_block],
        artifact_version_url=artifact_version_url,
        required_keyword=required_keyword,
        part_index=1,
        part_count=max_parts,
    )
    if len(canonical_json_bytes(minimum_body)) > max_bytes:
        raise DailyReportBlocked("dingtalk_body_too_large")
    low = minimum_budget
    high = max(minimum_budget, min(1200, max_bytes))
    best = minimum_block
    while low <= high:
        middle = (low + high) // 2
        candidate = block_for(middle)
        candidate_body = _prevalidated_body(
            run_id=run_id,
            blocks=[candidate],
            artifact_version_url=artifact_version_url,
            required_keyword=required_keyword,
            part_index=1,
            part_count=max_parts,
        )
        if len(canonical_json_bytes(candidate_body)) <= max_bytes:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _prevalidated_block_lines(
    *,
    index: int,
    post: Mapping[str, object],
    row: Mapping[str, object],
    comments: Sequence[Mapping[str, object]],
    translations: Mapping[str, str],
    excerpt: str,
) -> list[str]:
    post_id = str(post.get("post_id") or "")
    url = _exact_string(post.get("source_url"))
    if not url:
        raise DailyReportBlocked("missing_reddit_url")
    title_zh = translations[f"post:{post_id}:title"] or "（标题为空）"
    body_zh = translations[f"post:{post_id}:body"] or "（帖子正文为空）"
    lines = [
        "---",
        f"### {index}. {normalize_display_newlines(title_zh)}",
        "",
        "中文正文：",
        normalize_display_newlines(body_zh),
        "",
        "中文评论：",
    ]
    if comments:
        for comment_index, comment in enumerate(comments, start=1):
            comment_id = str(comment.get("comment_id") or "")
            comment_zh = translations[f"comment:{comment_id}:body"] or "（评论为空）"
            lines.append(f"- 评论 {comment_index}：{normalize_display_newlines(comment_zh)}")
    else:
        lines.append("- （无已解析评论）")
    lines.extend(
        [
            "",
            "业务判断：",
            _business_judgment(dict(row)),
            "",
            "英文原文节选：",
            excerpt or "(no English source text)",
            "",
            f"Reddit 链接：{url}",
            "完整英文原文与完整中文译文见附件。",
        ]
    )
    return lines


def _prevalidated_body(
    *,
    run_id: str,
    blocks: Sequence[Sequence[str]],
    artifact_version_url: str,
    required_keyword: str,
    part_index: int,
    part_count: int,
) -> Mapping[str, object]:
    suffix = f"（第 {part_index}/{part_count} 条）" if part_count > 1 else ""
    title = f"Momcozy Reddit VOC 日报 {run_id}{suffix}"
    lines = [f"# {title}", "", *[line for block in blocks for line in block]]
    lines.extend(
        [
            "",
            "## 完整附件",
            f"- [HTML 洞察报告]({artifact_version_url.rstrip('/')}/{run_id}-insight-report.html)",
            f"- [Excel 完整明细]({artifact_version_url.rstrip('/')}/{run_id}-daily-detail.xlsx)",
            f"- [CSV 完整明细]({artifact_version_url.rstrip('/')}/{run_id}-daily-detail.csv)",
        ]
    )
    markdown = "\n".join(lines)
    title, markdown = with_required_keyword(
        title=title,
        markdown=markdown,
        required_keyword=required_keyword,
    )
    return {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": markdown},
    }


def build_daily_report(
    store: VocStore,
    *,
    run_id: str,
    output_dir: Path | str,
    translation_mode: str = "dry_run",
) -> DailyReportResult:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    posts = store.fetch_metric_threads_for_run(run_id)
    comments = store.fetch_metric_comments_for_run(run_id)
    analysis_rows = store.fetch_analysis_for_run(run_id)
    run = store.get_run(run_id) or {}

    comments_by_post: dict[str, list[dict[str, Any]]] = {}
    for comment in comments:
        comments_by_post.setdefault(str(comment.get("post_id")), []).append(comment)
    analysis_by_source = {
        (str(row.get("source_type")), str(row.get("source_id"))): row
        for row in analysis_rows
    }

    media_root = out / DEFAULT_MEDIA_DIR

    rows: list[dict[str, Any]] = []
    translation_statuses: set[str] = set()
    translation_provider_call = False
    for post in posts:
        post_id = str(post.get("post_id"))
        post_analysis = analysis_by_source.get(("post", post_id), {})
        post_comments = comments_by_post.get(post_id, [])
        title_zh = translate_to_chinese(str(post.get("title") or ""), mode=translation_mode)
        body_zh = translate_to_chinese(str(post.get("selftext") or ""), mode=translation_mode)
        comment_translations = [
            translate_to_chinese(str(comment.get("body") or ""), mode=translation_mode)
            for comment in post_comments
        ]
        comment_original = _format_comments(post_comments, translated=False)
        comment_zh = _format_comments(post_comments, translated=True, translated_results=comment_translations)
        translation_statuses.add(title_zh.status)
        translation_statuses.add(body_zh.status)
        translation_statuses.update(result.status for result in comment_translations)
        row_translation_status = _combined_translation_status(
            [title_zh.status, body_zh.status, *(result.status for result in comment_translations)]
        )
        translation_provider_call = (
            translation_provider_call
            or title_zh.provider_call
            or body_zh.provider_call
            or any(result.provider_call for result in comment_translations)
        )
        relevance_label, relevance_basis = _relevance_check(post, post_comments)
        content_type = _content_type_for_post(post, post_comments, post_analysis)
        media_links = _media_links(post.get("media_urls"))
        media_items = _prepare_post_media_assets(
            post_id=post_id,
            run_id=run_id,
            output_dir=media_root,
            media_urls=post.get("media_urls"),
        )
        heat_score = _heat_score(post, post_comments)

        rows.append(
            {
                "采集窗口": _window_label(run),
                "社区": post.get("subreddit"),
                "帖子 ID": post_id,
                "帖子链接": post.get("source_url"),
                "媒体链接": media_links,
                "_media_items": media_items,
                "发帖时间（UTC）": post.get("created_at_utc"),
                "标题原文": post.get("title"),
                "标题中文": title_zh.text,
                "正文原文": post.get("selftext"),
                "正文中文": body_zh.text,
                "匹配关键词": post.get("matched_keywords"),
                "相关性校验": relevance_label,
                "相关依据": relevance_basis,
                "内容类型": content_type,
                "Reddit 分数": post.get("score"),
                "互动热度": heat_score,
                "情感标签": _sentiment_zh(post_analysis.get("sentiment_label")),
                "情感分数": post_analysis.get("sentiment_score"),
                "主题": _topic_zh(post_analysis.get("topic")),
                "严重度": _severity_zh(post_analysis.get("severity")),
                "痛点": _pain_points_zh(post_analysis.get("pain_points")),
                "评论数": len(post_comments),
                "评论整合原文": comment_original,
                "评论整合中文": comment_zh,
                "覆盖状态": _coverage_zh(post.get("coverage_grade")),
                "翻译状态": row_translation_status,
            }
        )

    visible_rows = _brand_body_comment_rows(rows)
    cumulative_rows = _cumulative_core_rows(store.fetch_recent_threads(limit=200))
    detail_csv = out / f"{run_id}-daily-detail.csv"
    detail_xlsx = out / f"{run_id}-daily-detail.xlsx"
    insight_png = out / f"{run_id}-insight-report-screenshot.png"
    insight_html = out / f"{run_id}-insight-report.html"
    _write_csv(detail_csv, visible_rows)
    _write_xlsx(detail_xlsx, visible_rows)
    _write_insight_html(insight_html, visible_rows, cumulative_rows=cumulative_rows, run_id=run_id, run=run)
    _write_report_screenshot(insight_png, insight_html, rows=visible_rows, run_id=run_id, run=run)
    return DailyReportResult(
        run_id=run_id,
        insight_html=insight_html,
        detail_csv=detail_csv,
        detail_xlsx=detail_xlsx,
        insight_png=insight_png,
        row_count=len(visible_rows),
        comment_count=sum(_int_value(row.get("评论数")) for row in visible_rows),
        translation_mode=translation_mode,
        translation_status=_combined_translation_status(sorted(translation_statuses)),
        provider_call=translation_provider_call,
        report_summary=_report_summary(visible_rows, run=run, collected_rows=rows),
    )


def translate_to_chinese(text: str, *, mode: str = "dry_run") -> TranslationResult:
    normalized = " ".join((text or "").split())
    if not normalized:
        return TranslationResult("", "empty")
    if normalized in EXACT_TRANSLATIONS:
        return TranslationResult(EXACT_TRANSLATIONS[normalized], "local_glossary")
    if mode in {"dry_run", "glossary"}:
        return TranslationResult(normalized, "provider_required")
    if mode == "disabled":
        return TranslationResult(normalized, "disabled")
    if mode in LIBRETRANSLATE_MODES:
        return _translate_with_libretranslate(normalized)
    if mode in DEEPSEEK_TRANSLATE_MODES:
        return _translate_with_deepseek(normalized)
    return TranslationResult(normalized, "provider_required")


def _translate_with_libretranslate(text: str) -> TranslationResult:
    base_url = (
        os.getenv("LIBRETRANSLATE_BASE_URL", "").strip()
        or os.getenv("REDDIT_VOC_LIBRETRANSLATE_BASE_URL", "").strip()
    )
    if not base_url:
        return TranslationResult(text, "provider_missing_config")

    source = os.getenv("REDDIT_VOC_TRANSLATION_SOURCE", "auto").strip() or "auto"
    target = os.getenv("REDDIT_VOC_TRANSLATION_TARGET", "zh").strip() or "zh"
    cache_key = (base_url.rstrip("/"), source, target, text)
    cached = _TRANSLATION_CACHE.get(cache_key)
    if cached:
        return cached

    timeout = _translation_timeout_seconds()
    payload: dict[str, Any] = {
        "q": text,
        "source": source,
        "target": target,
        "format": "text",
    }
    api_key = os.getenv("LIBRETRANSLATE_API_KEY", "").strip()
    if api_key:
        payload["api_key"] = api_key
    request = Request(
        base_url.rstrip("/") + "/translate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "RedditVOC/1.0 LibreTranslate",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        result = TranslationResult(text, f"provider_error:{type(exc).__name__}", provider_call=True)
        _TRANSLATION_CACHE[cache_key] = result
        return result

    translated = str(parsed.get("translatedText") or parsed.get("translated_text") or "").strip()
    if not translated:
        result = TranslationResult(text, "provider_error:empty_response", provider_call=True)
    else:
        result = TranslationResult(translated, "libretranslate", provider_call=True)
    _TRANSLATION_CACHE[cache_key] = result
    return result


_DEEPSEEK_TRANSLATE_CACHE: dict[str, TranslationResult] = {}

_DEEPSEEK_TRANSLATE_SYSTEM_PROMPT = (
    "You are an English-to-Simplified-Chinese translation engine. "
    "Return only one valid JSON object with a single key \"zh\" whose value is the complete "
    "faithful translation of the input into natural Simplified Chinese. "
    "Preserve brands, product models, numbers, percentages, URLs, r/subreddit references, "
    "u/user references, emoji, negation, comparison, and sentiment. "
    "Do not summarize, explain, answer questions, add facts, omit content, or output markdown."
)
_DEEPSEEK_TRANSLATE_URL = "https://api.deepseek.com/chat/completions"
_DEEPSEEK_TRANSLATE_MODEL = "deepseek-chat"


def _translate_with_deepseek(text: str) -> TranslationResult:
    cached = _DEEPSEEK_TRANSLATE_CACHE.get(text)
    if cached is not None:
        return cached

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        result = TranslationResult(text, "provider_missing_config")
        _DEEPSEEK_TRANSLATE_CACHE[text] = result
        return result

    timeout = _translation_timeout_seconds()
    request_body = {
        "model": _DEEPSEEK_TRANSLATE_MODEL,
        "messages": [
            {"role": "system", "content": _DEEPSEEK_TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        _DEEPSEEK_TRANSLATE_URL,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "RedditVOC/1.0 DeepSeekTranslate",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        result = TranslationResult(text, f"provider_error:{type(exc).__name__}", provider_call=True)
        _DEEPSEEK_TRANSLATE_CACHE[text] = result
        return result

    try:
        content = parsed["choices"][0]["message"]["content"]
        zh = json.loads(content).get("zh", "")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        result = TranslationResult(text, "provider_error:unexpected_response", provider_call=True)
        _DEEPSEEK_TRANSLATE_CACHE[text] = result
        return result

    translated = str(zh).strip()
    if not translated:
        result = TranslationResult(text, "provider_error:empty_response", provider_call=True)
    else:
        result = TranslationResult(translated, "deepseek", provider_call=True)
    _DEEPSEEK_TRANSLATE_CACHE[text] = result
    return result


def _translation_timeout_seconds() -> float:
    raw = os.getenv("REDDIT_VOC_TRANSLATION_TIMEOUT_SECONDS", "12").strip()
    try:
        value = float(raw)
    except ValueError:
        return 12.0
    return max(1.0, min(value, 60.0))


def render_business_dingtalk_markdown(
    *,
    run_id: str,
    report: DailyReportResult,
    status_summary: dict[str, Any],
    artifact_base_url: str | None = None,
    provider_call: bool = False,
    live_send: bool = False,
    max_bytes: int | None = None,
) -> str:
    parts = render_business_dingtalk_markdown_parts(
        run_id=run_id,
        report=report,
        status_summary=status_summary,
        artifact_base_url=artifact_base_url,
        provider_call=provider_call,
        live_send=live_send,
        max_bytes=max_bytes,
        max_parts=1,
    )
    return parts[0] if parts else ""


def render_business_dingtalk_markdown_parts(
    *,
    run_id: str,
    report: DailyReportResult,
    status_summary: dict[str, Any],
    artifact_base_url: str | None = None,
    provider_call: bool = False,
    live_send: bool = False,
    max_bytes: int | None = None,
    max_parts: int = 2,
) -> list[str]:
    counts = status_summary.get("counts", {}) or {}
    summary = report.report_summary or {}
    sentiment_counts = summary.get("sentiment_counts") or {}
    content_counts = summary.get("content_type_counts") or {}
    voc_posts = summary.get("voc_posts") or summary.get("top_posts") or []
    title = f"Momcozy Reddit Post 日报 - {summary.get('report_date') or _report_date_label(run_id, status_summary)}"
    threads = int(counts.get("threads", report.row_count) or 0)
    comments = int(counts.get("comments", report.comment_count) or 0)
    visible_threads = int(summary.get("visible_post_count", report.row_count) or 0)
    max_parts = max(1, min(max_parts, 2))
    fit_max_bytes = max_bytes - 160 if max_bytes and max_bytes > 160 else max_bytes
    footer = _business_markdown_footer(report, artifact_base_url)
    parts: list[str] = []
    lines = _business_markdown_header(
        title=title,
        voc_posts=voc_posts,
        threads=threads,
        visible_threads=visible_threads,
        comments=comments,
        sentiment_counts=sentiment_counts,
        content_counts=content_counts,
    )
    if voc_posts:
        sorted_posts = _top_rows(voc_posts, limit=len(voc_posts))
        index = 1
        while index <= len(sorted_posts):
            item = sorted_posts[index - 1]
            block = _render_voc_markdown_block(item, index=index, artifact_base_url=artifact_base_url)
            candidate = [*lines, *block]
            if _markdown_fits(candidate, footer, max_bytes=fit_max_bytes):
                lines = candidate
                index += 1
                continue
            compact = _render_voc_markdown_block(
                item,
                index=index,
                artifact_base_url=artifact_base_url,
                body_limit=360,
                summary_limit=320,
                comment_limit=240,
                max_comments=2,
            )
            compact_candidate = [*lines, *compact]
            if _markdown_fits(compact_candidate, footer, max_bytes=fit_max_bytes):
                lines = compact_candidate
                index += 1
                continue

            if len(parts) + 1 < max_parts and _has_rendered_voc_block(lines):
                notice = ["", "本条已接近钉钉大小上限，剩余 VOC 将在下一条继续。"]
                if _markdown_fits([*lines, *notice], [], max_bytes=fit_max_bytes):
                    lines.extend(notice)
                parts.append("\n".join(lines))
                lines = _business_markdown_continuation_header(title)
                continue

            omitted_count = len(sorted_posts) - index + 1
            notice = [
                "",
                f"因钉钉消息大小限制，已展示前 {len(sorted_posts) - omitted_count} 条高热 VOC；"
                f"其余 {omitted_count} 条请查看 HTML 洞察报告和采集明细表。",
            ]
            if _markdown_fits([*lines, *notice], footer, max_bytes=fit_max_bytes):
                lines.extend(notice)
            break
    else:
        lines.append("今日采集数据中暂无“正文或评论明确提及 Momcozy/momcozy”的 VOC 帖子，品类-only 帖子已从推送明细中隐藏。")
    lines.extend(footer)
    parts.append("\n".join(lines))
    if len(parts) > 1:
        parts = [
            part.replace(f"# {title}", f"# {title}（第 {part_index}/{len(parts)} 条）", 1)
            for part_index, part in enumerate(parts, start=1)
        ]
    return parts


def _business_markdown_header(
    *,
    title: str,
    voc_posts: list[dict[str, Any]],
    threads: int,
    visible_threads: int,
    comments: int,
    sentiment_counts: dict[str, int],
    content_counts: dict[str, int],
) -> list[str]:
    return [
        f"# {title}",
        "",
        "## 今日判断",
        _daily_business_judgment(voc_posts),
        "",
        "## 今日概览",
        f"采集帖子：{threads}｜推送明细：{visible_threads}｜解析评论：{comments}",
        "明细规则：仅展示帖子正文或评论中明确提及 Momcozy/momcozy 的帖子。",
        f"情绪：{_format_count_sentence(sentiment_counts) or '暂无可分布样本'}",
        f"内容类型：{_format_count_sentence(content_counts) or '暂无可分布样本'}",
        (
            f"高热 VOC：{_high_heat_count(voc_posts)}｜负面 VOC：{_negative_count(voc_posts)}｜"
            f"品牌提及：{_mention_count(voc_posts, '品牌提及')}｜品类提及：{_mention_count(voc_posts, '品类提及')}"
        ),
        "",
        "## VOC 明细｜按热度降序",
    ]


def _business_markdown_continuation_header(title: str) -> list[str]:
    return [
        f"# {title}",
        "",
        "## VOC 明细｜续",
        "以下继续按热度降序展示；完整全文、评论和表格请查看 HTML 洞察报告与采集明细。",
    ]


def _has_rendered_voc_block(lines: list[str]) -> bool:
    return any(line == "---" for line in lines)


def _business_markdown_footer(report: DailyReportResult, artifact_base_url: str | None) -> list[str]:
    return [
        "",
        "## 采集明细",
        f"- {_artifact_reference(str(report.insight_html), artifact_base_url, label='HTML 洞察报告')}",
        f"- {_artifact_reference(str(report.detail_xlsx), artifact_base_url, label='采集明细表（Excel）')}",
        f"- {_artifact_reference(str(report.detail_csv), artifact_base_url, label='采集明细表（CSV）')}",
    ]


def _markdown_fits(lines: list[str], footer: list[str], *, max_bytes: int | None) -> bool:
    if not max_bytes or max_bytes <= 0:
        return True
    return len("\n".join([*lines, *footer]).encode("utf-8")) <= max_bytes


def _render_voc_markdown_block(
    row: dict[str, Any],
    *,
    index: int,
    artifact_base_url: str | None = None,
    body_limit: int | None = None,
    summary_limit: int | None = None,
    comment_limit: int | None = None,
    max_comments: int | None = None,
) -> list[str]:
    title = _clean_markdown_text(row.get("标题原文") or row.get("标题中文") or "无标题", limit=96)
    heat = _int_value(row.get("互动热度"))
    tags = "、".join(_voc_tags(row))
    product = _product_label(row)
    signal = _signal_label(row)
    subreddit = str(row.get("社区") or "unknown")
    url = str(row.get("帖子链接") or "").strip()
    link = f"[Reddit]({url})" if url else "无链接"
    user_voice = _full_markdown_text(row.get("正文原文") or "")
    original = _chinese_original_summary(row)
    comments = _comment_full_lines(row)
    if not user_voice:
        user_voice = "帖子正文为空；该条因评论中明确提及 Momcozy 而保留。"
    if body_limit:
        user_voice = _clip_markdown_text(user_voice, limit=body_limit)
    if summary_limit:
        original = _clip_markdown_text(original, limit=summary_limit)
    if max_comments is not None:
        comments = comments[: max(0, max_comments)]
    if comment_limit:
        comments = [_clip_markdown_text(comment, limit=comment_limit) for comment in comments]
    media_lines = _markdown_media_lines(row, artifact_base_url=artifact_base_url)

    lines = [
        "",
        "---",
        "",
        f"### {index}. {_heat_badge(heat)} {title}",
        f"标签：{tags}；商品：{product}；类型：{row.get('内容类型') or '未分类'}；情绪：{row.get('情感标签') or '未知'}；线索：{signal}",
        (
            f"社区：r/{subreddit}；热度：{heat}；评论：{row.get('评论数') or 0}；"
            f"相关性：{row.get('相关性校验') or '待复核'}"
        ),
    ]
    if media_lines:
        lines.extend(["", "帖子图片：", *media_lines])
    lines.extend(
        [
            "",
            "用户声音：",
            user_voice,
            "",
            "原文摘要：",
            original,
            "",
            "评论原文：",
        ]
    )
    if comments:
        lines.extend(comments)
    else:
        lines.append("- 暂无已解析评论。")
    lines.extend(
        [
            "",
            "业务判断：",
            _business_judgment(row),
            "",
            f"帖子链接：{link}",
        ]
    )
    return lines


def _clean_markdown_text(value: object, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _full_markdown_text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _clip_markdown_text(value: str, *, limit: int) -> str:
    text = _full_markdown_text(value)
    if len(text) <= limit:
        return text
    suffix = "...（全文见 HTML/采集明细）"
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def _chinese_original_summary(row: dict[str, Any]) -> str:
    body_original = _full_markdown_text(row.get("正文原文") or "")
    body_zh = _full_markdown_text(row.get("正文中文") or "")
    if body_zh and (CJK_PATTERN.search(body_zh) or not body_original or body_zh != body_original):
        return body_zh
    if not body_original:
        return "帖子正文为空；该条因评论中明确提及 Momcozy 而保留，请结合评论原文和原帖链接复核。"
    product = _product_label(row)
    content_type = str(row.get("内容类型") or "一般讨论")
    sentiment = str(row.get("情感标签") or "未知")
    topic = str(row.get("主题") or "未分类主题")
    pain_points = str(row.get("痛点") or "暂未形成明确痛点")
    return (
        f"该帖围绕“{product}”展开，内容类型为“{content_type}”，情绪倾向为“{sentiment}”，"
        f"主题集中在“{topic}”，主要痛点为“{pain_points}”。完整英文原文见上方用户声音。"
    )


def _brand_body_comment_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _has_brand_in_body_or_comments(row)]


def _has_brand_in_body_or_comments(row: dict[str, Any]) -> bool:
    text = "\n".join(
        str(row.get(key) or "")
        for key in [
            "正文原文",
            "正文中文",
            "评论整合原文",
            "评论整合中文",
        ]
    )
    return bool(BRAND_BODY_COMMENT_PATTERN.search(text))


def _row_keyword_match(row: dict[str, Any]):
    text = "\n".join(
        str(row.get(key) or "")
        for key in [
            "标题原文",
            "标题中文",
            "正文原文",
            "正文中文",
            "评论整合原文",
            "评论整合中文",
            "匹配关键词",
            "相关依据",
        ]
    )
    return match_keywords(text)


def _voc_tags(row: dict[str, Any]) -> list[str]:
    match = _row_keyword_match(row)
    tags: list[str] = []
    if match.brands or match.products:
        tags.append("品牌提及")
    if match.categories:
        tags.append("品类提及")
    if match.competitors:
        tags.append("竞品线索" if tags else "竞品/品类线索")
    if not tags:
        relevance = str(row.get("相关性校验") or "").strip()
        tags.append(relevance or "待人工复核")
    return tags


def _product_label(row: dict[str, Any]) -> str:
    match = _row_keyword_match(row)
    terms = match.products or match.categories
    if not terms:
        return "未指向具体型号"
    labels = []
    for term in terms:
        labels.append(CATEGORY_PRODUCT_LABELS.get(term.lower(), term))
    deduped = list(dict.fromkeys(labels))
    return "、".join(deduped[:3])


def _signal_label(row: dict[str, Any]) -> str:
    content_type = str(row.get("内容类型") or "")
    sentiment = str(row.get("情感标签") or "")
    severity = str(row.get("严重度") or "")
    if sentiment == "负面" or severity == "高" or any(term in content_type for term in ["售后", "退换", "问题", "吐槽"]):
        return "风险线索"
    if "竞品" in content_type or any("竞品" in tag for tag in _voc_tags(row)):
        return "竞品线索"
    if any(term in content_type for term in ["求助", "购买", "保险", "报销", "经验"]):
        return "机会线索"
    if _int_value(row.get("互动热度")) >= 30:
        return "高热观察"
    return "观察线索"


def _heat_badge(heat: int) -> str:
    if heat >= 100:
        return "🔥🔥🔥"
    if heat >= 30:
        return "🔥🔥"
    if heat >= 10:
        return "🔥"
    return "☆"


def _comment_full_lines(row: dict[str, Any]) -> list[str]:
    originals = _comment_bodies(row.get("评论整合原文"), label="原文")
    if not originals:
        return []
    translations = _comment_bodies(row.get("评论整合中文"), label="中文")
    excerpts: list[str] = []
    for index, body in enumerate(originals, start=1):
        translation = _comment_translation_for_display(
            translations[index - 1] if index <= len(translations) else "",
            original=body,
        )
        excerpts.append(f"- 评论 {index} {body} (中文翻译：{translation})")
    return excerpts


def _comment_bodies(value: Any, *, label: str) -> list[str]:
    text = str(value or "")
    if not text.strip():
        return []
    bodies: list[str] = []
    prefix = f"{label}："
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            body = stripped.split("：", 1)[1].strip()
            if body:
                bodies.append(body)
    return bodies


def _comment_translation_for_display(translated: str, *, original: str) -> str:
    value = _full_markdown_text(translated)
    if not value or value == _full_markdown_text(original):
        return "暂未生成，请以原文为准"
    return value


def _markdown_media_lines(row: dict[str, Any], *, artifact_base_url: str | None = None) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(_row_media_items(row)[:4], start=1):
        source = str(item.get("source") or "").strip()
        local = str(item.get("local") or "").strip()
        image_url = _artifact_relative_url(local, artifact_base_url) if local else source
        if not image_url:
            continue
        lines.append(f"![帖子图片 {index}]({image_url})")
        if source and source != image_url:
            lines.append(f"[图片原图 {index}]({source})")
    return lines


def _business_judgment(row: dict[str, Any]) -> str:
    signal = _signal_label(row)
    product = _product_label(row)
    content_type = str(row.get("内容类型") or "一般讨论")
    if signal == "风险线索":
        return f"这是需要优先复核的风险 VOC，建议围绕“{product}”核查产品体验、配件、售后响应或用户误用场景。"
    if signal == "竞品线索":
        return f"这是竞品或替代方案比较线索，建议沉淀用户选择标准，用于优化“{product}”卖点表达。"
    if signal == "机会线索":
        return f"这是可转化的需求线索，适合沉淀为“{content_type}”内容素材，帮助解释“{product}”的购买理由和使用场景。"
    if signal == "高热观察":
        return f"这是高热讨论，建议跟踪评论区后续变化，并判断“{product}”是否存在内容教育或产品定位机会。"
    return f"这是常规观察 VOC，建议并入“{product}”历史样本，观察后续是否形成重复主题。"


def _daily_business_judgment(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "本周期未发现新的可展开 VOC，建议保持 24 小时滚动监控并复核关键词覆盖。"
    top_content = next(iter(_count_by(rows, "内容类型")), "一般讨论")
    top_topic = next(iter(_count_by(rows, "主题")), "未分类主题")
    top_pain = next(iter(_count_pain_points(rows)), "暂未形成集中痛点")
    negative = _negative_count(rows)
    high_heat = _high_heat_count(rows)
    return (
        f"今日相关讨论以“{top_content}”为主，核心主题集中在“{top_topic}”，"
        f"主要痛点是“{top_pain}”。其中高热 VOC {high_heat} 条、负面 VOC {negative} 条，"
        "建议优先查看高热需求、售后风险和竞品比较线索。"
    )


def _high_heat_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if _int_value(row.get("互动热度")) >= 30)


def _negative_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("情感标签") == "负面")


def _mention_count(rows: list[dict[str, Any]], tag: str) -> int:
    return sum(1 for row in rows if tag in _voc_tags(row))


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    columns: Sequence[str] = DETAIL_COLUMNS,
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in columns})


def _write_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Momcozy Reddit VOC 日报"
    header_fill = PatternFill(fill_type="solid", fgColor="1F4E5F")
    header_font = Font(color="FFFFFF", bold=True)
    for col_idx, column in enumerate(DETAIL_COLUMNS, start=1):
        cell = sheet.cell(row=1, column=col_idx, value=column)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, column in enumerate(DETAIL_COLUMNS, start=1):
            cell = sheet.cell(row=row_idx, column=col_idx, value=row.get(column, ""))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    widths = {
        "采集窗口": 34,
        "社区": 18,
        "帖子 ID": 14,
        "帖子链接": 48,
        "媒体链接": 48,
        "发帖时间（UTC）": 25,
        "标题原文": 36,
        "标题中文": 36,
        "正文原文": 48,
        "正文中文": 48,
        "匹配关键词": 28,
        "相关性校验": 14,
        "相关依据": 28,
        "内容类型": 16,
        "Reddit 分数": 12,
        "互动热度": 12,
        "评论整合原文": 70,
        "评论整合中文": 70,
    }
    for col_idx, column in enumerate(DETAIL_COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(col_idx)].width = widths.get(column, 16)
    sheet.freeze_panes = "A2"
    workbook.save(path)


def _write_insight_png(path: Path, rows: list[dict[str, Any]], *, run_id: str, run: dict[str, Any]) -> None:
    width, height = 1500, 1700
    image = Image.new("RGB", (width, height), "#F4F7FB")
    draw = ImageDraw.Draw(image)
    font_title = _font(44)
    font_h2 = _font(28)
    font_body = _font(22)
    font_small = _font(18)

    draw.rounded_rectangle((40, 36, width - 40, height - 36), radius=16, fill="#FFFFFF", outline="#D8E2EA", width=2)
    title = f"Momcozy Reddit Post 日报 - {_report_date_label(run_id, {'window_end_utc': run.get('window_end_utc')})}"
    draw.text((76, 70), title, fill="#1F2933", font=font_title)
    draw.text((78, 132), f"采集窗口：{_window_label(run)}", fill="#60707A", font=font_small)
    draw.text((78, 162), "中文 VOC 洞察长图｜覆盖新增帖子、评论、情绪、内容类型、痛点与重点帖子", fill="#60707A", font=font_small)

    card_specs = [
        ("帖子数", str(len(rows)), "#2F6F73"),
        ("评论数", str(sum(int(row.get("评论数") or 0) for row in rows)), "#A45A52"),
        ("负面帖", str(sum(1 for row in rows if row.get("情感标签") == "负面")), "#B4443E"),
        ("高严重度", str(sum(1 for row in rows if row.get("严重度") == "高")), "#8A5A9E"),
    ]
    x = 76
    for label, value, color in card_specs:
        draw.rounded_rectangle((x, 220, x + 310, 350), radius=9, fill=color)
        draw.text((x + 28, 244), label, fill="#FFFFFF", font=font_body)
        draw.text((x + 28, 282), value, fill="#FFFFFF", font=font_title)
        x += 340

    sentiment_counts = _count_by(rows, "情感标签")
    content_counts = _count_by(rows, "内容类型")
    topic_counts = _count_by(rows, "主题")
    pain_counts = _count_pain_points(rows)
    _draw_bar_section(draw, (76, 410), "情感分布", sentiment_counts, font_h2, font_body)
    _draw_bar_section(draw, (520, 410), "内容类型", dict(list(content_counts.items())[:5]), font_h2, font_body)
    _draw_bar_section(draw, (964, 410), "痛点前五", dict(list(pain_counts.items())[:5]), font_h2, font_body)

    draw.text((76, 850), "核心洞察", fill="#1F2933", font=font_h2)
    for idx, sentence in enumerate(_png_takeaways(rows)[:4], start=1):
        _draw_wrapped_text(draw, (76, 890 + (idx - 1) * 54), f"{idx}. {sentence}", font_body, "#374151", max_chars=58)

    draw.text((76, 1130), "重点高热帖子", fill="#1F2933", font=font_h2)
    highlights = _highlight_rows(rows) or rows[:4]
    if not highlights:
        draw.text((76, 1180), "今日暂无需要单独升级关注的帖子。", fill="#60707A", font=font_body)
    else:
        y = 1180
        for item in highlights[:4]:
            title_text = str(item.get("标题原文") or item.get("标题中文") or "无标题")
            _draw_wrapped_text(draw, (76, y), "• " + title_text, font_body, "#374151", max_chars=60)
            meta = (
                f"社区=r/{item.get('社区')}  内容类型={item.get('内容类型')}  情感={item.get('情感标签')}  "
                f"评论={item.get('评论数')}  热度={item.get('互动热度')}"
            )
            draw.text((98, y + 58), meta, fill="#60707A", font=font_small)
            y += 112
    image.save(path)


def _write_report_screenshot(
    path: Path,
    html_path: Path,
    *,
    rows: list[dict[str, Any]],
    run_id: str,
    run: dict[str, Any],
) -> None:
    try:
        _write_playwright_screenshot(path, html_path)
    except Exception:
        _write_insight_png(path, rows, run_id=run_id, run=run)


def _write_playwright_screenshot(path: Path, html_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("playwright is not available") from exc

    launch_args = [
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-crash-reporter",
        "--disable-crashpad",
        "--font-render-hinting=medium",
    ]

    with sync_playwright() as playwright:
        browser = None
        launch_errors: list[str] = []
        executable_candidates: list[str | None] = [None]
        chromium_path = _chromium_executable()
        if chromium_path:
            executable_candidates.append(chromium_path)
        for executable in executable_candidates:
            launch_options: dict[str, Any] = {"args": launch_args}
            if executable:
                launch_options["executable_path"] = executable
            try:
                browser = playwright.chromium.launch(**launch_options)
                break
            except Exception as exc:
                label = executable or "bundled_playwright_chromium"
                launch_errors.append(f"{label}: {type(exc).__name__}: {exc}")
        if browser is None:
            raise RuntimeError("; ".join(launch_errors) or "chromium launch failed")
        try:
            page = browser.new_page(
                viewport={"width": 1440, "height": 1400},
                device_scale_factor=1,
            )
            page.set_default_timeout(60_000)
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle", timeout=90_000)
            page.wait_for_function(
                """
                () => {
                    const images = Array.from(document.querySelectorAll('img'));
                    return images.every((img) => img.complete);
                }
                """,
                timeout=90_000,
            )
            page.wait_for_timeout(1_200)
            page.screenshot(path=str(path), full_page=True)
        finally:
            browser.close()


def _chromium_executable() -> str | None:
    candidates = [
        os.getenv("REDDIT_VOC_CHROMIUM_PATH", ""),
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "chromium",
        "chromium-browser",
        "google-chrome",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = candidate if Path(candidate).exists() else shutil.which(candidate)
        if resolved:
            return str(resolved)
    return None


def _write_insight_html(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    cumulative_rows: list[dict[str, Any]],
    run_id: str,
    run: dict[str, Any],
) -> None:
    metrics = _story_metrics(rows)
    title = f"Momcozy Reddit Post 中文日报 - {_report_date_label(run_id, {'window_end_utc': run.get('window_end_utc')})}"
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - {escape(run_id)}</title>
  <style>
    :root {{
      --ink: #1f2933;
      --muted: #62707c;
      --line: #d8e2ea;
      --paper: #f4f7fb;
      --card: #ffffff;
      --teal: #2f6f73;
      --red: #b4443e;
      --clay: #a45a52;
      --purple: #8a5a9e;
      --amber: #c08a3e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      line-height: 1.62;
    }}
    .page {{ max-width: 1180px; margin: 0 auto; padding: 36px 28px 56px; }}
    .hero {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 34px 38px 30px;
      box-shadow: 0 18px 48px rgba(31, 41, 51, 0.08);
    }}
    h1 {{ margin: 0; font-size: 40px; line-height: 1.2; letter-spacing: 0; }}
    h2 {{ margin: 38px 0 14px; font-size: 25px; line-height: 1.25; }}
    h3 {{ margin: 22px 0 8px; font-size: 18px; }}
    .sub {{ margin-top: 10px; color: var(--muted); font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-top: 26px; }}
    .metric {{ border-radius: 8px; padding: 18px 18px 16px; color: #fff; min-height: 112px; }}
    .metric:nth-child(1) {{ background: var(--teal); }}
    .metric:nth-child(2) {{ background: var(--clay); }}
    .metric:nth-child(3) {{ background: var(--red); }}
    .metric:nth-child(4) {{ background: var(--purple); }}
    .metric span {{ display: block; font-size: 14px; opacity: .92; }}
    .metric strong {{ display: block; margin-top: 10px; font-size: 38px; line-height: 1; }}
    .story, .details {{
      margin-top: 22px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 30px 34px;
    }}
    .lead {{ font-size: 18px; margin: 0 0 16px; }}
    .callout {{
      border-left: 5px solid var(--teal);
      background: #f1f7f6;
      padding: 14px 16px;
      border-radius: 8px;
      color: #263b40;
    }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .mini {{ border: 1px solid #dfe8f0; border-radius: 8px; padding: 16px; background: #ffffff; }}
    .bars {{ display: grid; gap: 10px; }}
    .bar-row {{ display: grid; grid-template-columns: 112px 1fr 34px; gap: 10px; align-items: center; color: var(--muted); }}
    .bar {{ height: 11px; border-radius: 999px; background: #e9e5dc; overflow: hidden; }}
    .bar i {{ display: block; height: 100%; border-radius: 999px; background: var(--teal); }}
    .bar-row:nth-child(2n) .bar i {{ background: var(--clay); }}
    .bar-row:nth-child(3n) .bar i {{ background: var(--amber); }}
    .evidence {{ padding-left: 18px; }}
    .evidence li {{ margin: 8px 0; }}
    .report-img {{ width: 100%; border: 1px solid var(--line); border-radius: 8px; margin-top: 14px; }}
    .post-cards {{ display: grid; gap: 14px; }}
    .post-card {{ border: 1px solid #dfe8f0; border-radius: 8px; padding: 16px; background: #fff; }}
    .post-meta {{ color: var(--muted); font-size: 13px; margin-top: 6px; }}
    .post-card p {{ margin: 10px 0 0; color: #374151; }}
    .post-card details {{ margin-top: 10px; border-top: 1px solid #eef2f6; padding-top: 10px; }}
    .post-card summary {{ cursor: pointer; color: #245b63; font-weight: 600; }}
    .post-card .full-text {{ white-space: pre-wrap; color: #374151; font-size: 14px; }}
    .media-strip {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    .media-item {{ display: grid; gap: 6px; width: 132px; }}
    .media-link {{ font-size: 12px; color: #1f6f8b; text-decoration: none; }}
    .media-link:hover {{ text-decoration: underline; }}
    .media-item img {{ width: 132px; height: 92px; object-fit: cover; border-radius: 6px; border: 1px solid var(--line); background: #f4f7fb; }}
    table {{ width: 100%; min-width: 1200px; border-collapse: collapse; font-size: 13px; }}
    th {{ position: sticky; top: 0; background: #1f4e5f; color: #fff; text-align: left; }}
    th, td {{ border: 1px solid #d8e2ea; padding: 8px 9px; vertical-align: top; }}
    td {{ background: #fff; }}
    .table-wrap {{ overflow: auto; max-height: 560px; border: 1px solid var(--line); border-radius: 8px; }}
    a {{ color: #1f6f8b; }}
    .empty {{ color: var(--muted); }}
    @media (max-width: 760px) {{
      .page {{ padding: 20px 14px 40px; }}
      .hero, .story, .details {{ padding: 22px 18px; }}
      h1 {{ font-size: 30px; }}
      .grid, .two-col {{ grid-template-columns: 1fr; }}
      .bar-row {{ grid-template-columns: 86px 1fr 28px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>{escape(title)}</h1>
      <div class="sub">采集窗口：{escape(_window_label(run))} · 单页 HTML 报告 · 底部含当日与累计帖子核心字段表</div>
      <div class="grid">
        <div class="metric"><span>新增相关帖子</span><strong>{metrics["posts"]}</strong></div>
        <div class="metric"><span>解析评论</span><strong>{metrics["comments"]}</strong></div>
        <div class="metric"><span>负面帖子</span><strong>{metrics["negative_posts"]}</strong></div>
        <div class="metric"><span>高严重度</span><strong>{metrics["high_severity"]}</strong></div>
      </div>
    </section>

    <section class="story">
      <p class="lead">{escape(_lead_sentence(rows))}</p>
      <div class="callout">{escape(_executive_takeaway(rows))}</div>

      <h2>核心摘要</h2>
      <p>下面按“核心结论、重点高热帖子、情绪与内容结构、痛点证据、行动建议、明细追溯”的顺序展开。</p>

      <h2>1. 今天先看结论</h2>
      <p>{escape(_what_happened(rows))}</p>

      <h2>2. 重点高热帖子</h2>
      {_html_hot_posts(rows)}

      <h2>3. 情绪与内容结构</h2>
      <div class="two-col">
        <div class="mini">
          <h3>情感分布</h3>
          {_html_bars(_count_by(rows, "情感标签"))}
        </div>
        <div class="mini">
          <h3>内容类型</h3>
          {_html_bars(dict(list(_count_by(rows, "内容类型").items())[:6]))}
        </div>
      </div>

      <h2>4. 主题与痛点分布</h2>
      <div class="two-col">
        <div class="mini">
          <h3>主题分布</h3>
          {_html_bars(dict(list(_count_by(rows, "主题").items())[:6]))}
        </div>
        <div class="mini">
          <h3>痛点 Top</h3>
          {_html_bars(dict(list(_count_pain_points(rows).items())[:8]))}
        </div>
      </div>

      <h2>5. 证据链与重点声音</h2>
      {_html_evidence(rows)}

      <h2>6. 建议动作</h2>
      {_html_actions(rows)}

    </section>

    <section class="details">
      <h2>帖子核心字段表</h2>
      <p class="sub">当日表用于本周期复盘；累计表展示历史样本的最新 200 条核心字段。</p>
      <h3>当日帖子核心字段</h3>
      <div class="table-wrap">
        {_html_core_table(rows)}
      </div>
      <h3>累计帖子核心字段</h3>
      <div class="table-wrap">
        {_html_compact_table(cumulative_rows)}
      </div>

      <h2>VOC 采集明细表</h2>
      <p class="sub">每行对应一个 Reddit 帖子，帖子下评论已整合到同一行评论单元格。</p>
      <div class="table-wrap">
        {_html_detail_table(rows)}
      </div>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def _format_comments(
    comments: list[dict[str, Any]],
    *,
    translated: bool,
    translated_results: list[TranslationResult] | None = None,
) -> str:
    parts: list[str] = []
    for index, comment in enumerate(comments, start=1):
        body = str(comment.get("body") or "")
        if translated:
            if translated_results and index <= len(translated_results):
                value = translated_results[index - 1].text
            else:
                value = body
        else:
            value = body
        label = "中文" if translated else "原文"
        parts.append(
            "\n".join(
                [
                    f"[{index}] 评论ID={comment.get('comment_id')} | 分数={comment.get('score')} | 层级={comment.get('depth')}",
                    f"{label}：{value}",
                ]
            )
        )
    return "\n\n".join(parts)


def _media_url_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in re.split(r"[\n,;]+", text) if part.strip()]


def _prepare_post_media_assets(
    *,
    post_id: str,
    run_id: str,
    output_dir: Path,
    media_urls: Any,
) -> list[dict[str, str]]:
    urls = _media_url_list(media_urls)
    if not urls:
        return []

    assets: list[dict[str, str]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(urls[:6]):
        local_path = _download_media_to_file(url, output_dir=output_dir, run_id=run_id, post_id=post_id, index=index)
        if local_path:
            assets.append({"source": url, "local": local_path})
        else:
            assets.append({"source": url})
    return assets


def _download_media_to_file(url: str, *, output_dir: Path, run_id: str, post_id: str, index: int) -> str | None:
    normalized = _normalize_media_url(url)
    if not normalized:
        return None
    file_name = _make_media_filename(normalized, run_id=run_id, post_id=post_id, index=index)
    target_path = output_dir / file_name
    if target_path.exists() and target_path.stat().st_size > 0:
        return f"{DEFAULT_MEDIA_DIR}/{file_name}"

    headers = {
        "User-Agent": "Mozilla/5.0 RedditVOC/1.0 (+https://github.com)"
    }
    if "reddit" in normalized:
        headers["Referer"] = "https://www.reddit.com/"
    request = Request(normalized, headers=headers)
    try:
        with urlopen(request, timeout=12) as response:
            content_type = str(response.getheader("Content-Type") or "").lower()
            if content_type and not content_type.startswith("image/"):
                return None
            data = response.read()
    except (HTTPError, URLError, ValueError, OSError):
        return None
    if not data:
        return None
    if len(data) > 4 * 1024 * 1024:
        return None

    try:
        target_path.write_bytes(data)
    except OSError:
        return None
    return f"{DEFAULT_MEDIA_DIR}/{file_name}"


def _normalize_media_url(url: str) -> str | None:
    value = url.strip()
    if not value.lower().startswith(("http://", "https://")):
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return value


def _make_media_filename(url: str, *, run_id: str, post_id: str, index: int) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if not suffix or len(suffix) > 6:
        suffix = mimetypes.guess_extension("image/jpeg") or ".jpg"
    safe_run = re.sub(r"[^a-zA-Z0-9_-]", "_", run_id)
    safe_post = re.sub(r"[^a-zA-Z0-9_-]", "_", post_id)
    hash_key = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{safe_run}_{safe_post}_{index}_{hash_key}{suffix}"


def _media_links(value: Any) -> str:
    return "\n".join(_media_url_list(value))


def _relevance_check(post: dict[str, Any], comments: list[dict[str, Any]]) -> tuple[str, str]:
    combined = "\n".join(
        [
            str(post.get("title") or ""),
            str(post.get("selftext") or ""),
            "\n".join(str(comment.get("body") or "") for comment in comments[:20]),
        ]
    )
    match = match_keywords(combined)
    basis = "、".join(match.matched_terms)
    if match.excluded:
        return "需排除", basis or "命中排除词"
    if match.brands and (match.products or match.categories):
        return "强相关", basis
    if match.brands:
        return "品牌相关", basis
    if match.products or match.categories:
        return "品类相关", basis
    if match.competitors:
        return "竞品/品类线索", basis
    return "待人工复核", basis or "未命中当前关键词"


def _content_type_for_post(
    post: dict[str, Any],
    comments: list[dict[str, Any]],
    post_analysis: dict[str, Any],
) -> str:
    text = " ".join(
        [
            str(post.get("title") or ""),
            str(post.get("selftext") or ""),
            " ".join(str(comment.get("body") or "") for comment in comments[:8]),
        ]
    ).lower()
    topic = str(post_analysis.get("topic") or "")
    sentiment = str(post_analysis.get("sentiment_label") or "")
    if any(term in text for term in ["refund", "return", "warranty", "customer service", "support", "客服", "售后"]):
        return "售后/退换咨询"
    if topic == "insurance" or any(term in text for term in ["insurance", "covered", "reimburse", "报销", "保险"]):
        return "保险/报销咨询"
    if any(term in text for term in ["which", "recommend", "advice", "anyone", "help", "tips", "should i", "?"]):
        return "求助咨询"
    if sentiment == "negative" or any(term in text for term in ["leak", "broken", "stopped working", "hate", "terrible", "slow", "吐槽"]):
        return "吐槽/问题反馈"
    if any(term in text for term in ["vs", "compare", "comparison", "better than", "medela", "elvie", "willow", "eufy"]):
        return "竞品对比"
    if any(term in text for term in ["review", "journey", "experience", "worked for me", "love", "分享"]):
        return "经验分享"
    if any(term in text for term in ["for sale", "sell", "sold", "转让"]):
        return "转让/交易"
    return "一般讨论"


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _heat_score(post: dict[str, Any], comments: list[dict[str, Any]]) -> int:
    score = max(0, _int_value(post.get("score")))
    reported = max(len(comments), _int_value(post.get("num_comments_reported")))
    return score + reported * 3


def _report_summary(rows: list[dict[str, Any]], *, run: dict[str, Any], collected_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sorted_rows = _top_rows(rows, limit=len(rows))
    collected_rows = collected_rows if collected_rows is not None else rows
    return {
        "report_date": _report_date_label("", {"window_end_utc": run.get("window_end_utc")}),
        "collected_post_count": len(collected_rows),
        "visible_post_count": len(rows),
        "filter_rule": "仅展示帖子正文或评论中明确提及 Momcozy/momcozy 的帖子；采集口径保持品牌+品类不变。",
        "sentiment_counts": _count_by(rows, "情感标签"),
        "content_type_counts": _count_by(rows, "内容类型"),
        "topic_counts": _count_by(rows, "主题"),
        "pain_point_counts": _count_pain_points(rows),
        "lead_sentence": _lead_sentence(rows),
        "top_posts": sorted_rows[:5],
        "voc_posts": sorted_rows,
    }


def _top_rows(rows: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _int_value(row.get("互动热度")),
            _int_value(row.get("评论数")),
            1 if row.get("情感标签") == "负面" else 0,
        ),
        reverse=True,
    )[:limit]


def _format_count_sentence(counts: dict[str, int]) -> str:
    return "、".join(f"{key} {value} 个" for key, value in counts.items() if key and value)


def _report_date_label(run_id: str, status_summary: dict[str, Any]) -> str:
    end = status_summary.get("window_end_utc")
    parsed = _parse_datetime(end)
    if parsed is not None:
        return parsed.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    match = re.search(r"(20\d{6})", run_id or "")
    if match:
        raw = match.group(1)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cumulative_core_rows(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for post in posts:
        relevance_label, relevance_basis = _relevance_check(post, [])
        rows.append(
            {
                "日期（UTC）": post.get("created_at_utc"),
                "社区": post.get("subreddit"),
                "帖子标题": post.get("title"),
                "帖子链接": post.get("source_url"),
                "评论数": post.get("parsed_comment_count"),
                "Reddit 分数": post.get("score"),
                "媒体数": len(_media_url_list(post.get("media_urls"))),
                "相关性校验": relevance_label,
                "相关依据": relevance_basis or post.get("matched_keywords"),
            }
        )
    return rows


def _png_takeaways(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["本周期未发现新的强相关帖子，建议继续观察关键词和 subreddit 覆盖。"]
    sentiment = _format_count_sentence(_count_by(rows, "情感标签"))
    content = _format_count_sentence(_count_by(rows, "内容类型"))
    top_pain = next(iter(_count_pain_points(rows)), "暂未形成集中痛点")
    top_topic = next(iter(_count_by(rows, "主题")), "未知主题")
    media_count = sum(1 for row in rows if str(row.get("媒体链接") or "").strip())
    return [
        f"共识别 {len(rows)} 条相关新帖，情绪结构为：{sentiment}。",
        f"内容类型结构为：{content}，主讨论主题集中在“{top_topic}”。",
        f"最突出的可行动痛点是“{top_pain}”，适合进入产品、客服和内容 FAQ 复盘。",
        f"其中 {media_count} 条帖子带有可展示图片链接，报告已保留媒体入口便于人工复核。",
    ]


def _window_label(run: dict[str, Any]) -> str:
    start = run.get("window_start_utc") or ""
    end = run.get("window_end_utc") or ""
    return f"{start} ~ {end}"


def _combined_translation_status(statuses: list[str]) -> str:
    values = {status for status in statuses if status and status != "empty"}
    if not values:
        return "empty"
    if values == {"local_glossary"}:
        return "local_glossary"
    if values <= {"local_glossary", "libretranslate"}:
        return "translated"
    if values <= {"local_glossary", "deepseek"}:
        return "translated"
    if "provider_missing_config" in values:
        return "provider_missing_config"
    if "provider_required" in values:
        return "provider_required"
    provider_errors = sorted(status for status in values if status.startswith("provider_error:"))
    if provider_errors:
        return provider_errors[0]
    return ",".join(sorted(values))


def _sentiment_zh(value: object) -> str:
    return SENTIMENT_ZH.get(str(value or ""), str(value or "未知"))


def _topic_zh(value: object) -> str:
    return TOPIC_ZH.get(str(value or ""), str(value or "未知"))


def _severity_zh(value: object) -> str:
    return SEVERITY_ZH.get(str(value or ""), str(value or "未知"))


def _pain_points_zh(value: object) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
    else:
        parsed = value
    return "、".join(PAIN_POINT_ZH.get(str(item), str(item)) for item in parsed)


def _coverage_zh(value: object) -> str:
    return {
        "full": "完整",
        "partial": "部分评论",
        "post_only": "仅帖子",
        "failed": "失败",
    }.get(str(value or ""), str(value or "未知"))


def _run_status_zh(value: object) -> str:
    return {
        "success": "成功",
        "partial": "部分成功",
        "empty": "无新增",
        "failed": "失败",
    }.get(str(value or ""), str(value or "未知"))


def _translation_status_zh(value: str) -> str:
    if value.startswith("provider_error:"):
        return "翻译服务异常"
    return {
        "translated": "已翻译",
        "libretranslate": "已翻译",
        "local_glossary": "本地词表翻译",
        "provider_missing_config": "未配置翻译服务",
        "provider_required": "未翻译",
        "disabled": "未启用",
        "empty": "无内容",
    }.get(value, value)


def _count_by(rows: list[dict[str, Any]], column: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(column) or "未知")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _count_pain_points(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for item in str(row.get("痛点") or "").split("、"):
            if not item:
                continue
            counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _story_metrics(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "posts": len(rows),
        "comments": sum(int(row.get("评论数") or 0) for row in rows),
        "negative_posts": sum(1 for row in rows if row.get("情感标签") == "负面"),
        "high_severity": sum(1 for row in rows if row.get("严重度") == "高"),
    }


def _lead_sentence(rows: list[dict[str, Any]]) -> str:
    metrics = _story_metrics(rows)
    if metrics["posts"] == 0:
        return "本周期未采集到新的 Momcozy 或品类相关 Reddit 帖子，建议保持常规监控。"
    dominant_topic = next(iter(_count_by(rows, "主题")), "未知主题")
    dominant_pain = next(iter(_count_pain_points(rows)), "暂无集中痛点")
    return (
        f"本周期共识别 {metrics['posts']} 条相关新帖和 {metrics['comments']} 条评论，"
        f"主线集中在“{dominant_topic}”，最突出的用户痛点是“{dominant_pain}”。"
    )


def _executive_takeaway(rows: list[dict[str, Any]]) -> str:
    metrics = _story_metrics(rows)
    if metrics["posts"] == 0:
        return "结论：今天没有新增可行动舆情，重点是确认采集链路和关键词覆盖是否正常。"
    if metrics["negative_posts"] > 0:
        return "结论：今天的声音偏风险预警，应优先检查负面帖中反复出现的产品体验、售后和使用场景问题。"
    return "结论：今天的声音未形成明显负面风险，可继续跟踪主题变化并积累可复用用户表达。"


def _what_happened(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "没有进入采集窗口的新帖，因此本日报不生成具体产品或竞品判断。"
    topics = "、".join(list(_count_by(rows, "主题").keys())[:3])
    pains = "、".join(list(_count_pain_points(rows).keys())[:3]) or "暂无明确痛点"
    return f"用户讨论从具体使用场景切入，主要主题包括 {topics}；可行动问题集中在 {pains}。"


def _html_bars(counts: dict[str, int]) -> str:
    if not counts:
        return '<p class="empty">暂无数据</p>'
    max_value = max(counts.values(), default=1)
    rows = []
    for label, value in counts.items():
        width = max(4, int(100 * value / max_value))
        rows.append(
            f'<div class="bar-row"><span>{escape(label)}</span><div class="bar"><i style="width:{width}%"></i></div><b>{value}</b></div>'
        )
    return '<div class="bars">' + "".join(rows) + "</div>"


def _html_hot_posts(rows: list[dict[str, Any]]) -> str:
    top_rows = _top_rows(rows, limit=5)
    seen_ids = {str(row.get("帖子 ID")) for row in top_rows}
    for row in rows:
        if not _media_url_list(row.get("媒体链接")):
            continue
        post_id = str(row.get("帖子 ID"))
        if post_id not in seen_ids:
            top_rows.append(row)
            seen_ids.add(post_id)
        if len(top_rows) >= 8:
            break
    if not top_rows:
        return '<p class="empty">暂无高热帖子。</p>'
    cards = []
    for row in top_rows:
        title = escape(str(row.get("标题原文") or row.get("标题中文") or "无标题"))
        url = escape(str(row.get("帖子链接") or ""))
        label = f'<a href="{url}">{title}</a>' if url else title
        meta = escape(
            f"r/{row.get('社区')} · {row.get('内容类型')} · {row.get('情感标签')} · "
            f"评论 {row.get('评论数') or 0} · 热度 {row.get('互动热度') or 0} · 相关性 {row.get('相关性校验')}"
        )
        body = escape(_full_markdown_text(row.get("正文原文") or "帖子正文为空；请结合评论和原帖链接复核。"))
        comments = escape(_full_markdown_text(row.get("评论整合原文") or "暂无已解析评论。"))
        cards.append(
            '<article class="post-card">'
            f"<strong>{label}</strong>"
            f'<div class="post-meta">{meta}</div>'
            f"<details><summary>用户声音全文</summary><div class=\"full-text\">{body}</div></details>"
            f"<details><summary>评论原文全文</summary><div class=\"full-text\">{comments}</div></details>"
            f"{_html_media_thumbs(row)}"
            "</article>"
        )
    return '<div class="post-cards">' + "".join(cards) + "</div>"


def _html_media_thumbs(row: dict[str, Any]) -> str:
    media_items = _row_media_items(row)
    if not media_items:
        return ""
    images = ""
    for item in media_items[:4]:
        source = escape(str(item.get("source") or ""))
        local = item.get("local") or ""
        src = escape(str(local) if local else source)
        if not source:
            continue
        images += (
            '<figure class="media-item">'
            f'<a class="media-link" href="{source}" target="_blank" rel="noopener noreferrer">媒体原图</a>'
            f'<a href="{source}" target="_blank" rel="noopener noreferrer">'
            f'<img src="{src}" alt="帖子图片" loading="eager" referrerpolicy="no-referrer"/>'
            "</a></figure>"
        )
    return f'<div class="media-strip">{images}</div>'


def _html_evidence(rows: list[dict[str, Any]]) -> str:
    highlights = _highlight_rows(rows) or rows[:3]
    if not highlights:
        return '<p class="empty">暂无可展示证据。</p>'
    items = []
    for row in highlights[:6]:
        title = escape(str(row.get("标题原文") or row.get("标题中文") or "无标题"))
        url = escape(str(row.get("帖子链接") or ""))
        meta = escape(f"情感={row.get('情感标签')} · 类型={row.get('内容类型')} · 主题={row.get('主题')} · 痛点={row.get('痛点')}")
        label = f'<a href="{url}">{title}</a>' if url else title
        items.append(f"<li><strong>{label}</strong><br><span>{meta}</span>{_html_media_thumbs(row)}</li>")
    return '<ul class="evidence">' + "".join(items) + "</ul>"


def _row_media_items(row: dict[str, Any]) -> list[dict[str, str]]:
    media_items = row.get("_media_items")
    if isinstance(media_items, list):
        normalized: list[dict[str, str]] = []
        for item in media_items:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            if not source:
                continue
            local = str(item.get("local") or "").strip()
            normalized.append(
                {
                    "source": source,
                    **({"local": local} if local else {}),
                }
            )
        if normalized:
            return normalized
    urls = _media_url_list(row.get("媒体链接"))
    return [{"source": url} for url in urls]


def _html_actions(rows: list[dict[str, Any]]) -> str:
    if not rows:
        actions = [
            "继续保持 24 小时滚动监控，确认采集源和关键词没有断档。",
            "若连续多日无新增，可复核 subreddit 和搜索关键词覆盖。"
        ]
    else:
        pain_counts = _count_pain_points(rows)
        top_pain = next(iter(pain_counts), "")
        actions = [
            f"围绕“{top_pain or '核心痛点'}”整理用户原话，沉淀给产品、客服和内容团队。",
            "对负面或中高严重度帖子建立人工复核清单，优先判断是否需要客服或产品响应。",
            "对竞品对比和复工场景表达做素材归档，用于后续卖点、FAQ 和内容选题。"
        ]
    return '<ul class="evidence">' + "".join(f"<li>{escape(action)}</li>" for action in actions) + "</ul>"


def _html_detail_table(rows: list[dict[str, Any]]) -> str:
    header = "".join(f"<th>{escape(col)}</th>" for col in DETAIL_COLUMNS)
    body_rows = []
    for row in rows:
        cells = []
        for col in DETAIL_COLUMNS:
            raw_value = row.get(col, "")
            value = "" if raw_value is None else str(raw_value)
            if col == "帖子链接" and value:
                cells.append(f'<td><a href="{escape(value)}">{escape(value)}</a></td>')
            elif col == "媒体链接" and value:
                links = "<br>".join(f'<a href="{escape(url)}">{escape(url)}</a>' for url in _media_url_list(value))
                cells.append(f"<td>{links}</td>")
            else:
                cells.append(f"<td>{escape(value).replace(chr(10), '<br>')}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    if not body_rows:
        body_rows.append(f'<tr><td colspan="{len(DETAIL_COLUMNS)}" class="empty">本周期无明细数据</td></tr>')
    return "<table><thead><tr>" + header + "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"


def _html_core_table(rows: list[dict[str, Any]]) -> str:
    columns = ["发帖时间（UTC）", "社区", "标题原文", "帖子链接", "内容类型", "情感标签", "评论数", "互动热度", "相关性校验", "媒体链接"]
    return _html_table(rows, columns, empty_text="本周期无当日核心字段数据")


def _html_compact_table(rows: list[dict[str, Any]]) -> str:
    columns = ["日期（UTC）", "社区", "帖子标题", "帖子链接", "评论数", "Reddit 分数", "媒体数", "相关性校验", "相关依据"]
    return _html_table(rows, columns, empty_text="暂无累计帖子核心字段数据")


def _html_table(rows: list[dict[str, Any]], columns: list[str], *, empty_text: str) -> str:
    header = "".join(f"<th>{escape(col)}</th>" for col in columns)
    body_rows = []
    for row in rows:
        cells = []
        for col in columns:
            raw_value = row.get(col, "")
            value = "" if raw_value is None else str(raw_value)
            if col == "帖子链接" and value:
                cells.append(f'<td><a href="{escape(value)}">{escape(value)}</a></td>')
            elif col in {"媒体链接"} and value:
                links = "<br>".join(f'<a href="{escape(url)}">{escape(url)}</a>' for url in _media_url_list(value))
                cells.append(f"<td>{links}</td>")
            else:
                cells.append(f"<td>{escape(value).replace(chr(10), '<br>')}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    if not body_rows:
        body_rows.append(f'<tr><td colspan="{len(columns)}" class="empty">{escape(empty_text)}</td></tr>')
    return "<table><thead><tr>" + header + "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    *,
    max_chars: int,
) -> None:
    x, y = origin
    normalized = " ".join(text.split())
    lines = [normalized[i : i + max_chars] for i in range(0, len(normalized), max_chars)] or [""]
    for line in lines[:2]:
        draw.text((x, y), line, fill=fill, font=font)
        y += 30


def _clip_label(value: object, *, max_chars: int = 14) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _draw_bar_section(draw: ImageDraw.ImageDraw, origin: tuple[int, int], title: str, counts: dict[str, int], font_h2: ImageFont.FreeTypeFont, font_body: ImageFont.FreeTypeFont) -> None:
    x, y = origin
    draw.text((x, y), title, fill="#1F2933", font=font_h2)
    max_value = max(counts.values(), default=1)
    y += 48
    palette = ["#2F6F73", "#A45A52", "#8A5A9E", "#C08A3E", "#627D98"]
    if not counts:
        draw.text((x, y), "暂无数据", fill="#60707A", font=font_body)
        return
    for idx, (label, value) in enumerate(counts.items()):
        bar_width = int(260 * value / max_value)
        draw.text((x, y), _clip_label(label, max_chars=14), fill="#374151", font=font_body)
        draw.rounded_rectangle((x, y + 34, x + bar_width, y + 52), radius=9, fill=palette[idx % len(palette)])
        draw.text((x + 278, y + 24), str(value), fill="#60707A", font=font_body)
        y += 76


def _highlight_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    highlights = [
        row
        for row in rows
        if row.get("严重度") == "高" or row.get("情感标签") == "负面" or _int_value(row.get("互动热度")) >= 10
    ]
    return _top_rows(highlights, limit=len(highlights))


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default(size=size)


def _artifact_reference(path: str, artifact_base_url: str | None, *, label: str | None = None) -> str:
    display_label = label or Path(path).name
    if artifact_base_url:
        return f"[{display_label}]({_artifact_url(path, artifact_base_url)})"
    return f"`{path}`"


def _artifact_url(path: str, artifact_base_url: str) -> str:
    return artifact_base_url.rstrip("/") + "/" + quote(Path(path).name)


def _artifact_relative_url(path: str, artifact_base_url: str | None) -> str:
    value = str(path or "").strip().lstrip("/")
    if not value:
        return ""
    if not artifact_base_url:
        return value
    return artifact_base_url.rstrip("/") + "/" + quote(value, safe="/")


def _artifact_image_url(path: str, artifact_base_url: str) -> str:
    url = _artifact_url(path, artifact_base_url)
    try:
        version = int(Path(path).stat().st_mtime)
    except OSError:
        version = int(datetime.now(timezone.utc).timestamp())
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={version}"
