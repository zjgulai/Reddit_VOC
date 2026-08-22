from __future__ import annotations

import csv
import json
import mimetypes
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


APP_VERSION = "2026.07.07-webapp"
REPO_ROOT = Path(os.environ.get("REDDIT_VOC_SITE_ROOT", Path(__file__).resolve().parents[1])).resolve()
DATA_DIR = Path(os.environ.get("REDDIT_VOC_DATA_DIR", REPO_ROOT / "data")).resolve()
OUTPUT_DIR = Path(os.environ.get("REDDIT_VOC_OUTPUT_DIR", REPO_ROOT / "outputs")).resolve()
CONFIG_DIR = Path(os.environ.get("REDDIT_VOC_CONFIG_DIR", REPO_ROOT / "config")).resolve()
DOCS_DIR = Path(os.environ.get("REDDIT_VOC_DOCS_DIR", REPO_ROOT / "docs")).resolve()
STATIC_DIR = Path(__file__).resolve().parent / "static"

SENTIMENT_CN = {
    "positive": "正面",
    "neutral": "中性",
    "negative": "负面",
    "mixed": "混合",
    "unknown": "未知",
}

SEVERITY_CN = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "none": "无",
    "unknown": "未知",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def safe_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return [part.strip() for part in re.split(r"[,;/、]+", text) if part.strip()]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def read_env_template() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in read_text(REPO_ROOT / ".env.example").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def read_subreddit_config() -> dict[str, Any]:
    path = CONFIG_DIR / "subreddits.yaml"
    tiers: dict[str, list[dict[str, str]]] = defaultdict(list)
    current_tier = ""
    run_hour: int | None = None
    timezone_name = "Asia/Shanghai"
    current_item: dict[str, str] | None = None
    for line in read_text(path).splitlines():
        if match := re.search(r"timezone:\s*([A-Za-z_/\-]+)", line):
            timezone_name = match.group(1)
        if match := re.search(r"run_hour:\s*(\d+)", line):
            run_hour = int(match.group(1))
        if match := re.match(r"\s{2}(p\d):\s*$", line):
            current_tier = match.group(1)
            current_item = None
            continue
        if match := re.match(r"\s{4}- name:\s*(.+?)\s*$", line):
            current_item = {"name": match.group(1), "reason": ""}
            if current_tier:
                tiers[current_tier].append(current_item)
            continue
        if current_item is not None and (match := re.match(r"\s{6}reason:\s*(.+?)\s*$", line)):
            current_item["reason"] = match.group(1)
    return {
        "path": str(path),
        "timezone": timezone_name,
        "run_hour": run_hour,
        "tiers": dict(tiers),
        "total_subreddits": sum(len(items) for items in tiers.values()),
    }


def read_keyword_config() -> dict[str, Any]:
    path = CONFIG_DIR / "keywords.yaml"
    sections = {
        "brand": [],
        "products": [],
        "category": [],
        "contextual_category": [],
        "competitors": [],
        "pain_points": [],
    }
    section = ""
    in_context_terms = False
    for raw_line in read_text(path).splitlines():
        line = raw_line.rstrip()
        if re.match(r"^[A-Za-z_]+:", line):
            key = line.split(":", 1)[0]
            section = key if key in sections else ""
            in_context_terms = False
            continue
        if section == "contextual_category" and re.match(r"\s{2}terms:\s*$", line):
            in_context_terms = True
            continue
        if section == "pain_points" and re.match(r"\s{2}[A-Za-z_]+:\s*$", line):
            continue
        if match := re.match(r"\s*-\s*(.+?)\s*$", line):
            term = match.group(1).strip().strip("'\"")
            if not term:
                continue
            target = section
            if section == "contextual_category" and not in_context_terms:
                continue
            if target in sections:
                sections[target].append(term)
    return {
        "path": str(path),
        "counts": {key: len(value) for key, value in sections.items()},
        "samples": {key: value[:12] for key, value in sections.items()},
    }


def load_detail_translations() -> dict[str, dict[str, str]]:
    translations: dict[str, dict[str, str]] = {}
    if not OUTPUT_DIR.exists():
        return translations
    csv_files = sorted(
        (path for path in OUTPUT_DIR.glob("*daily-detail.csv") if not path.name.startswith("._")),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for path in csv_files:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeDecodeError):
            continue
        for row in rows:
            post_id = row.get("帖子 ID") or row.get("Post ID") or row.get("post_id") or ""
            source_url = row.get("帖子链接") or row.get("source_url") or ""
            payload = {
                "title_zh": row.get("标题中文", ""),
                "selftext_zh": row.get("正文中文", ""),
                "comments_zh": row.get("评论整合中文", ""),
                "translation_status": row.get("翻译状态", ""),
                "detail_csv": path.name,
            }
            for key in {post_id, source_url}:
                if key and key not in translations:
                    translations[key] = payload
    return translations


_PRODUCTION_DB_NAME = "reddit_voc_daily.sqlite3"


def sqlite_paths() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    prod = DATA_DIR / _PRODUCTION_DB_NAME
    if prod.exists():
        return [prod]
    return sorted(path for path in DATA_DIR.glob("*.sqlite3") if not path.name.startswith("._"))


def collect_runs() -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for db_path in sqlite_paths():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                if not table_exists(conn, "runs"):
                    continue
                for row in conn.execute("SELECT * FROM runs ORDER BY window_end_utc DESC, run_id"):
                    record = dict(row)
                    record["db_name"] = db_path.name
                    record["db_path"] = str(db_path)
                    record["db_mtime"] = db_path.stat().st_mtime
                    record["provider_call"] = bool(record.get("provider_call"))
                    record["live_send"] = bool(record.get("live_send"))
                    runs.append(record)
        except sqlite3.Error:
            continue
    runs.sort(key=lambda item: (parse_iso(item.get("window_end_utc")), item.get("db_mtime", 0)), reverse=True)
    return runs


def comment_source_url(post_source_url: str | None, comment_id: str) -> str | None:
    if not post_source_url:
        return None
    short_id = comment_id.split("_", 1)[1] if comment_id.startswith("t1_") else comment_id
    return post_source_url.rstrip("/") + f"/{short_id}/"


def collect_comments() -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    comments: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for db_path in sqlite_paths():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                if not table_exists(conn, "reddit_comments"):
                    continue
                rows = conn.execute(
                    """
                    SELECT
                        c.comment_id, c.post_id, c.run_id, c.parent_id, c.body,
                        c.created_at_utc, c.score, c.depth, c.is_submitter,
                        c.matched_keywords, c.deleted_or_removed,
                        t.source_url AS post_source_url,
                        a.sentiment_label, a.sentiment_score, a.topic, a.severity, a.pain_points
                    FROM reddit_comments c
                    LEFT JOIN reddit_threads t
                        ON c.post_id = t.post_id AND c.run_id = t.run_id
                    LEFT JOIN analysis_results a
                        ON a.run_id = c.run_id
                        AND a.source_type = 'comment'
                        AND a.source_id = c.comment_id
                    ORDER BY c.created_at_utc, c.comment_id
                    """
                ).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            record = dict(row)
            record["db_name"] = db_path.name
            record["source_url"] = comment_source_url(record.get("post_source_url"), record["comment_id"])
            record["sentiment_label_cn"] = SENTIMENT_CN.get(record.get("sentiment_label"), "未知")
            record["severity_cn"] = SEVERITY_CN.get(record.get("severity"), "未知")
            record["pain_points_list"] = safe_json_list(record.get("pain_points"))
            comments[(db_path.name, record["run_id"], record["post_id"])].append(record)
    return comments


def collect_posts() -> list[dict[str, Any]]:
    comments_by_key = collect_comments()
    translations = load_detail_translations()
    posts: list[dict[str, Any]] = []
    for db_path in sqlite_paths():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                if not (table_exists(conn, "reddit_threads") and table_exists(conn, "runs")):
                    continue
                media_expr = "t.media_urls" if "media_urls" in table_columns(conn, "reddit_threads") else "'[]'"
                rows = conn.execute(
                    f"""
                    SELECT
                        t.post_id, t.run_id, t.raw_capture_id, t.subreddit, t.title,
                        t.selftext, t.source_url, t.created_at_utc, t.score,
                        t.num_comments_reported, t.parsed_comment_count, t.more_node_count,
                        t.coverage_grade, t.matched_keywords, t.author_hash,
                        COALESCE({media_expr}, '[]') AS media_urls,
                        r.status AS run_status, r.window_start_utc, r.window_end_utc,
                        r.provider_call, r.live_send,
                        a.sentiment_label, a.sentiment_score, a.topic, a.severity,
                        a.confidence, a.pain_points
                    FROM reddit_threads t
                    LEFT JOIN runs r ON r.run_id = t.run_id
                    LEFT JOIN analysis_results a
                        ON a.run_id = t.run_id
                        AND a.source_type = 'post'
                        AND a.source_id = t.post_id
                    ORDER BY t.created_at_utc DESC, t.post_id
                    """
                ).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            record = dict(row)
            key = (db_path.name, record["run_id"], record["post_id"])
            row_comments = comments_by_key.get(key, [])
            merged_comments = "\n\n".join(
                f"[{index}] {item['body']}"
                for index, item in enumerate(row_comments, start=1)
            )
            translated = translations.get(record["post_id"]) or translations.get(record.get("source_url", "")) or {}
            record.update(
                {
                    "db_name": db_path.name,
                    "db_mtime": db_path.stat().st_mtime,
                    "row_id": f"{db_path.name}:{record['run_id']}:{record['post_id']}",
                    "provider_call": bool(record.get("provider_call")),
                    "live_send": bool(record.get("live_send")),
                    "matched_keywords_list": safe_json_list(record.get("matched_keywords")),
                    "media_urls_list": safe_json_list(record.get("media_urls")),
                    "pain_points_list": safe_json_list(record.get("pain_points")),
                    "sentiment_label_cn": SENTIMENT_CN.get(record.get("sentiment_label"), "未知"),
                    "severity_cn": SEVERITY_CN.get(record.get("severity"), "未知"),
                    "comments": row_comments,
                    "comments_merged": merged_comments,
                    "comments_merged_zh": translated.get("comments_zh", ""),
                    "title_zh": translated.get("title_zh", ""),
                    "selftext_zh": translated.get("selftext_zh", ""),
                    "translation_status": translated.get("translation_status", ""),
                    "detail_csv": translated.get("detail_csv", ""),
                }
            )
            posts.append(record)
    posts.sort(key=lambda item: (parse_iso(item.get("created_at_utc")), item.get("db_mtime", 0)), reverse=True)
    return posts


def latest_run_key(runs: list[dict[str, Any]]) -> tuple[str, str] | None:
    for run in runs:
        return (run["db_name"], run["run_id"])
    return None


def select_scope_posts(scope: str, posts: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if scope == "latest":
        key = latest_run_key(runs)
        if not key:
            return []
        return [post for post in posts if (post["db_name"], post["run_id"]) == key]
    return posts


def artifact_records() -> list[dict[str, Any]]:
    if not OUTPUT_DIR.exists():
        return []
    suffixes = {".html", ".png", ".csv", ".xlsx", ".json", ".jsonl"}
    records: list[dict[str, Any]] = []
    for path in sorted(OUTPUT_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or path.name.startswith("._") or path.suffix.lower() not in suffixes:
            continue
        records.append(
            {
                "name": path.name,
                "url": f"/artifacts/{path.name}",
                "suffix": path.suffix.lower().lstrip("."),
                "size": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
        )
    return records


def build_settings_payload() -> dict[str, Any]:
    env_defaults = read_env_template()
    subreddit_config = read_subreddit_config()
    keyword_config = read_keyword_config()
    report_hour = int(env_defaults.get("REDDIT_VOC_REPORT_HOUR") or 8)
    run_hour = subreddit_config.get("run_hour") or int(env_defaults.get("REDDIT_VOC_RUN_HOUR") or 7)
    return {
        "generated_at": now_iso(),
        "app_version": APP_VERSION,
        "schedule": {
            "timezone": subreddit_config.get("timezone") or env_defaults.get("REDDIT_VOC_TIMEZONE", "Asia/Shanghai"),
            "collection_time": f"{run_hour:02d}:00",
            "collection_window_hours": 24,
            "report_time": f"{report_hour:02d}:00",
            "collection_provider": env_defaults.get("REDDIT_VOC_COLLECTION_PROVIDER", "tikhub"),
        },
        "runtime_gates": {
            "tikhub_enabled_by_default": env_defaults.get("REDDIT_VOC_ENABLE_TIKHUB") == "1",
            "dingtalk_live_enabled_by_default": env_defaults.get("REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND") == "1",
            "browser_json_enabled_by_default": env_defaults.get("REDDIT_VOC_ENABLE_BROWSER_JSON") == "1",
            "secrets_expected_runtime_only": True,
        },
        "paths": {
            "data_dir": str(DATA_DIR),
            "output_dir": str(OUTPUT_DIR),
            "config_dir": str(CONFIG_DIR),
            "docs_dir": str(DOCS_DIR),
        },
        "subreddits": subreddit_config,
        "keywords": keyword_config,
        "command_template": (
            "REDDIT_VOC_ENV_FILE=~/.reddit-voc/secrets/reddit-voc-live.env "
            "REDDIT_VOC_DATABASE_PATH=data/reddit_voc_daily.sqlite3 "
            "REDDIT_VOC_OUTPUT_DIR=outputs scripts/run_daily_collect.sh"
        ),
    }


def post_metrics(posts: list[dict[str, Any]]) -> dict[str, Any]:
    comment_count = sum(len(post.get("comments", [])) for post in posts)
    sentiment = Counter(post.get("sentiment_label_cn") or "未知" for post in posts)
    topics = Counter(post.get("topic") or "未分类" for post in posts)
    subreddits = Counter(post.get("subreddit") or "unknown" for post in posts)
    severity = Counter(post.get("severity_cn") or "未知" for post in posts)
    pain_points: Counter[str] = Counter()
    for post in posts:
        pain_points.update(post.get("pain_points_list") or [])
        for comment in post.get("comments", []):
            pain_points.update(comment.get("pain_points_list") or [])
    return {
        "posts": len(posts),
        "comments": comment_count,
        "sentiment": dict(sentiment),
        "topics": dict(topics.most_common(12)),
        "subreddits": dict(subreddits.most_common(12)),
        "severity": dict(severity),
        "pain_points": dict(pain_points.most_common(12)),
    }


def build_dashboard_payload(scope: str = "latest") -> dict[str, Any]:
    runs = collect_runs()
    posts = collect_posts()
    scoped_posts = select_scope_posts(scope, posts, runs)
    filters = {
        "subreddits": sorted({post["subreddit"] for post in posts if post.get("subreddit")}),
        "sentiments": sorted({post["sentiment_label_cn"] for post in posts if post.get("sentiment_label_cn")}),
        "topics": sorted({post["topic"] for post in posts if post.get("topic")}),
        "severities": sorted({post["severity_cn"] for post in posts if post.get("severity_cn")}),
    }
    return {
        "generated_at": now_iso(),
        "scope": scope,
        "latest_run": runs[0] if runs else None,
        "runs": runs[:50],
        "totals": post_metrics(scoped_posts),
        "filters": filters,
        "posts": scoped_posts,
    }


def build_story(posts: list[dict[str, Any]], scope: str) -> list[str]:
    metrics = post_metrics(posts)
    scope_label = "最近一个采集批次" if scope == "latest" else "历史累计样本"
    if not posts:
        return [
            f"{scope_label}暂无可展示的 Reddit 帖子。当前站点只读取本地数据库与产物，不代表线上 Reddit 没有新增。",
            "下一步应优先确认 07:00 采集任务和 08:00 钉钉推送任务是否有真实线上数据进入。",
        ]
    top_sentiment = Counter(metrics["sentiment"]).most_common(1)[0][0]
    top_topic = Counter(metrics["topics"]).most_common(1)[0][0]
    top_pain = Counter(metrics["pain_points"]).most_common(1)
    pain_text = top_pain[0][0] if top_pain else "未形成稳定痛点"
    top_subreddit = Counter(metrics["subreddits"]).most_common(1)[0][0]
    return [
        f"{scope_label}共沉淀 {metrics['posts']} 篇帖子和 {metrics['comments']} 条解析评论，主讨论社区集中在 r/{top_subreddit}。",
        f"舆情基调以「{top_sentiment}」为主，最集中的议题是「{top_topic}」，优先关注的用户痛点是「{pain_text}」。",
        "明细层面保留 Reddit 原帖链接、帖子正文、中文翻译字段和同帖评论整合，便于运营、产品和客服共用同一张 VOC 表。",
    ]


def build_insights_payload(scope: str = "latest") -> dict[str, Any]:
    dashboard = build_dashboard_payload(scope)
    posts = dashboard["posts"]
    artifacts = artifact_records()
    html_reports = [item for item in artifacts if item["name"].endswith("-insight-report.html")]
    insight_images = [item for item in artifacts if item["name"].endswith("-insights.png") or item["name"].endswith(".png")]
    return {
        "generated_at": now_iso(),
        "scope": scope,
        "metrics": dashboard["totals"],
        "story": build_story(posts, scope),
        "top_posts": sorted(
            posts,
            key=lambda item: (abs(float(item.get("sentiment_score") or 0)), len(item.get("comments", []))),
            reverse=True,
        )[:8],
        "artifacts": {
            "latest_report": html_reports[0] if html_reports else None,
            "latest_image": insight_images[0] if insight_images else None,
            "recent": artifacts[:20],
        },
    }


def build_daily_report_latest() -> dict[str, Any]:
    if not OUTPUT_DIR.exists():
        return {"status": "no_report_today", "generated_at": now_iso()}
    summary_files = sorted(
        (p for p in OUTPUT_DIR.glob("*daily-report-summary.json") if not p.name.startswith("._")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not summary_files:
        return {"status": "no_report_today", "generated_at": now_iso()}
    latest = summary_files[0]
    try:
        raw = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "error", "generated_at": now_iso()}
    rs = raw.get("report_summary") or {}
    run_info = (raw.get("runs") or [{}])[0]
    voc_posts_raw = rs.get("voc_posts") or rs.get("top_posts") or []
    voc_posts = [
        {
            "社区": p.get("社区", ""),
            "帖子链接": p.get("帖子链接", ""),
            "标题原文": p.get("标题原文", ""),
            "标题中文": p.get("标题中文", ""),
            "情感": p.get("情感", ""),
            "内容类型": p.get("内容类型", ""),
            "主题": p.get("主题", ""),
            "摘要中文": p.get("摘要中文", "") or p.get("正文中文", ""),
        }
        for p in voc_posts_raw
    ]
    return {
        "status": "ok",
        "generated_at": now_iso(),
        "run_id": run_info.get("run_id", ""),
        "window_start_utc": run_info.get("window_start_utc", ""),
        "window_end_utc": run_info.get("window_end_utc", ""),
        "report_date": rs.get("report_date", ""),
        "collected_post_count": rs.get("collected_post_count", 0),
        "visible_post_count": rs.get("visible_post_count", 0),
        "lead_sentence": rs.get("lead_sentence", ""),
        "sentiment_counts": rs.get("sentiment_counts") or {},
        "topic_counts": rs.get("topic_counts") or {},
        "pain_point_counts": rs.get("pain_point_counts") or {},
        "voc_posts": voc_posts,
    }


def resolve_artifact_path(name: str) -> Path | None:
    safe_name = unquote(name).strip("/")
    if not safe_name or "\\" in safe_name:
        return None
    if ".." in safe_name.split("/"):
        return None
    output_root = OUTPUT_DIR.resolve()
    candidate = (output_root / safe_name).resolve()
    if not candidate.is_file():
        return None
    try:
        common_root = os.path.commonpath([str(candidate), str(output_root)])
    except ValueError:
        return None
    if common_root != str(output_root):
        return None
    return candidate


def resolve_static_path(name: str) -> Path | None:
    safe_name = unquote(name).strip("/")
    if not safe_name or "\\" in safe_name:
        return None
    candidate = (STATIC_DIR / safe_name).resolve()
    static_root = STATIC_DIR.resolve()
    if static_root != candidate and static_root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    return candidate


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "RedditVOCWeb/2026.07"

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("REDDIT_VOC_WEB_ACCESS_LOG", "0") == "1":
            super().log_message(format, *args)

    def do_HEAD(self) -> None:
        self.handle_request(head_only=True)

    def do_GET(self) -> None:
        self.handle_request(head_only=False)

    def handle_request(self, *, head_only: bool) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            self.send_file(STATIC_DIR / "index.html", head_only=head_only)
            return
        if path.startswith("/static/"):
            static_file = resolve_static_path(path.removeprefix("/static/"))
            if static_file is None:
                self.send_error(404, "static file not found")
                return
            self.send_file(static_file, head_only=head_only)
            return
        if path.startswith("/artifacts/"):
            artifact = resolve_artifact_path(path.removeprefix("/artifacts/"))
            if artifact is None:
                self.send_error(404, "artifact not found")
                return
            self.send_file(artifact, head_only=head_only)
            return
        if path == "/api/health":
            self.send_json(
                {
                    "status": "ok",
                    "app_version": APP_VERSION,
                    "generated_at": now_iso(),
                    "sqlite_files": len(sqlite_paths()),
                    "artifacts": len(artifact_records()),
                },
                head_only=head_only,
            )
            return
        if path == "/api/settings":
            self.send_json(build_settings_payload(), head_only=head_only)
            return
        if path == "/api/dashboard":
            scope = query.get("scope", ["latest"])[0]
            self.send_json(
                build_dashboard_payload(scope if scope in {"latest", "all"} else "latest"),
                head_only=head_only,
            )
            return
        if path == "/api/insights":
            scope = query.get("scope", ["latest"])[0]
            self.send_json(
                build_insights_payload(scope if scope in {"latest", "all"} else "latest"),
                head_only=head_only,
            )
            return
        if path == "/api/artifacts":
            self.send_json({"generated_at": now_iso(), "artifacts": artifact_records()}, head_only=head_only)
            return
        if path == "/api/daily-report/latest":
            self.send_json(build_daily_report_latest(), head_only=head_only)
            return
        self.send_error(404, "not found")

    def send_json(self, payload: Any, status: int = 200, *, head_only: bool = False) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def send_file(self, path: Path, *, head_only: bool = False) -> None:
        resolved = path.resolve()
        if not resolved.is_file():
            self.send_error(404, "file not found")
            return
        mime_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        body = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


def run() -> None:
    host = os.environ.get("REDDIT_VOC_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("REDDIT_VOC_WEB_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Reddit VOC web console listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    run()
