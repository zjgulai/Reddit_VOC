"""
导出 Reddit VOC 数据为 ai_nlp_voc 兼容的 Reddit API JSON 格式。

数据来源：
  output/reddit-voc-private-exports/.../bundle/reddit-entities-full.jsonl
  - 包含 3,494 个帖子 + 27,158 条评论（完整去重后的生产数据）

输出格式：
  export/<BrandName>/<slug>_<n>.json
  每个 JSON 文件对应一个 Reddit 帖子，结构为：
  [
    { "kind": "Listing", "data": { "children": [{ "kind": "t3", "data": {...post...} }] } },
    { "kind": "Listing", "data": { "children": [{ "kind": "t1", "data": {...comment...} }, ...] } }
  ]

运行：
  python3 scripts/export_voc_data.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
EXPORT_BUNDLE = (
    PROJECT_ROOT
    / "output"
    / "reddit-voc-private-exports"
    / "reddit_voc_export_20260716_v3_818f7eae7627_private_audit_v2"
    / "bundle"
    / "reddit-entities-full.jsonl"
)
EXPORT_DIR = PROJECT_ROOT / "export"


# ──────────────────────────────────────────────────────────────────────────────
# 时间戳转换
# ──────────────────────────────────────────────────────────────────────────────
def _iso_to_epoch(iso: str | None) -> float | None:
    """将 ISO 8601 字符串转为 Unix 时间戳（float）。"""
    if not iso:
        return None
    try:
        ts = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 格式构建
# ──────────────────────────────────────────────────────────────────────────────
def _build_post_child(r: dict) -> dict:
    """将 export record 的 post record 转为 Reddit API t3 child 格式。"""
    post_id = r.get("post_id", "")
    subreddit = r.get("subreddit", "")
    permalink_raw = r.get("permalink", "")
    # 统一成相对路径，如 /r/xxx/comments/yyy/zzz/
    if permalink_raw.startswith("https://www.reddit.com"):
        permalink = permalink_raw[len("https://www.reddit.com"):]
    elif permalink_raw.startswith("http://www.reddit.com"):
        permalink = permalink_raw[len("http://www.reddit.com"):]
    else:
        permalink = permalink_raw

    created_utc = _iso_to_epoch(r.get("created_at_utc"))
    created = created_utc  # Reddit API 里 created == created_utc（本地时区已无实质区别）

    return {
        "kind": "t3",
        "data": {
            "id": post_id,
            "name": f"t3_{post_id}",
            "subreddit": subreddit,
            "subreddit_name_prefixed": f"r/{subreddit}",
            "title": r.get("title", ""),
            "selftext": r.get("content", ""),
            "score": r.get("score") or 0,
            "ups": r.get("score") or 0,
            "upvote_ratio": r.get("upvote_ratio") or 0.0,
            "num_comments": r.get("num_comments_reported") or r.get("parsed_comment_count") or 0,
            "created": created,
            "created_utc": created_utc,
            "author": r.get("author_pseudonym", "[redacted]"),
            "author_fullname": None,
            "permalink": permalink,
            "url": r.get("permalink", ""),
            "is_self": True,
            "domain": f"self.{subreddit}",
            # 附加项：方便下游分析直接读取
            "_voc_matched_keywords": r.get("matched_keywords", []),
            "_voc_collection_buckets": r.get("collection_buckets", []),
            "_voc_mentioned_brands": r.get("mentioned_brands", []),
            "_voc_sentiment_label": r.get("analysis", {}).get("sentiment_label"),
            "_voc_topic": r.get("analysis", {}).get("topic"),
            "_voc_pain_points": r.get("analysis", {}).get("pain_points", []),
            "_voc_tags": r.get("tagging", {}).get("aspect_tag_ids", []),
        },
    }


def _build_comment_child(r: dict) -> dict:
    """将 export record 的 comment record 转为 Reddit API t1 child 格式。"""
    comment_id = r.get("comment_id", r.get("reddit_id", ""))
    # comment_id 可能已经带 t1_ 前缀
    if comment_id.startswith("t1_"):
        bare_id = comment_id[3:]
    else:
        bare_id = comment_id
        comment_id = f"t1_{bare_id}"

    created_utc = _iso_to_epoch(r.get("created_at_utc"))

    return {
        "kind": "t1",
        "data": {
            "id": bare_id,
            "name": comment_id,
            "parent_id": r.get("parent_id", ""),
            "link_id": f"t3_{r.get('post_id', '')}",
            "subreddit": None,  # 评论来源 subreddit 由帖子决定，此处省略
            "body": r.get("body", ""),
            "score": r.get("score") or 0,
            "ups": r.get("score") or 0,
            "created": created_utc,
            "created_utc": created_utc,
            "author": r.get("author_pseudonym", "[redacted]"),
            "author_fullname": None,
            "depth": r.get("depth") or 0,
            "is_submitter": bool(r.get("is_submitter", False)),
            "replies": "",
            # 附加项
            "_voc_mentioned_brands": r.get("mentioned_brands", []),
            "_voc_sentiment_label": r.get("analysis", {}).get("sentiment_label"),
            "_voc_topic": r.get("analysis", {}).get("topic"),
            "_voc_pain_points": r.get("analysis", {}).get("pain_points", []),
            "_voc_tags": r.get("tagging", {}).get("aspect_tag_ids", []),
            "_voc_include_in_voc_metrics": r.get("include_in_voc_metrics", True),
        },
    }


def _build_reddit_json(post_r: dict, comment_rs: list[dict]) -> list[dict]:
    """组装成 [post_listing, comments_listing] 格式。"""
    post_child = _build_post_child(post_r)
    comment_children = [_build_comment_child(c) for c in comment_rs]
    return [
        {
            "kind": "Listing",
            "data": {
                "after": None,
                "dist": 1,
                "modhash": "",
                "geo_filter": "",
                "children": [post_child],
                "before": None,
            },
        },
        {
            "kind": "Listing",
            "data": {
                "after": None,
                "dist": len(comment_children),
                "modhash": "",
                "geo_filter": "",
                "children": comment_children,
                "before": None,
            },
        },
    ]


# ──────────────────────────────────────────────────────────────────────────────
# 文件名生成
# ──────────────────────────────────────────────────────────────────────────────
def _safe_slug(text: str, max_len: int = 40) -> str:
    """将任意字符串转为安全文件名片段。"""
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "_", text.strip())
    return text[:max_len]


# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    if not EXPORT_BUNDLE.exists():
        print(f"ERROR: 找不到 export bundle: {EXPORT_BUNDLE}", file=sys.stderr)
        sys.exit(1)

    print(f"读取 {EXPORT_BUNDLE} …")

    # 一次性加载所有 entities，按 entity_type 分类
    posts: dict[str, dict] = {}        # post_id -> record
    comments: dict[str, list[dict]] = defaultdict(list)  # post_id -> [comment_record]

    with EXPORT_BUNDLE.open(encoding="utf-8") as fh:
        for i, raw in enumerate(fh, 1):
            if not raw.strip():
                continue
            entity = json.loads(raw)
            etype = entity.get("entity_type")
            # 只处理 post/comment，跳过无 record 的其他类型
            if "record" not in entity.get("payload", {}):
                continue
            record = entity["payload"]["record"]
            if etype == "post":
                posts[record["post_id"]] = record
            elif etype == "comment":
                post_id = record.get("post_id", "")
                comments[post_id].append(record)

    print(f"  posts={len(posts)}, comment_groups={len(comments)}, "
          f"total_comments={sum(len(v) for v in comments.values())}")

    # ── 决定每个帖子归属哪个品牌目录 ──────────────────────────────────────────
    # 用 collection_buckets 第一个 bucket 作为目录名；若为空则 other
    bucket_posts: dict[str, list[str]] = defaultdict(list)  # bucket -> [post_id]
    for pid, pr in posts.items():
        buckets = pr.get("collection_buckets") or []
        bucket = buckets[0] if buckets else "other"
        bucket_posts[bucket].append(pid)

    print("\n各品牌帖子数量：")
    for b, pids in sorted(bucket_posts.items()):
        print(f"  {b}: {len(pids)} posts, "
              f"{sum(len(comments.get(p, [])) for p in pids)} comments")

    # ── 写出文件 ───────────────────────────────────────────────────────────────
    EXPORT_DIR.mkdir(exist_ok=True)
    total_written = 0

    for bucket, post_ids in sorted(bucket_posts.items()):
        brand_dir = EXPORT_DIR / bucket
        brand_dir.mkdir(exist_ok=True)

        # 按 created_at_utc 排序，保持时序
        sorted_ids = sorted(
            post_ids,
            key=lambda p: posts[p].get("created_at_utc") or "",
        )

        for idx, post_id in enumerate(sorted_ids, 1):
            pr = posts[post_id]
            cr = sorted(
                comments.get(post_id, []),
                key=lambda c: c.get("created_at_utc") or "",
            )

            reddit_json = _build_reddit_json(pr, cr)

            # 文件名：<brand>_<idx>.json
            filename = f"{bucket}_{idx}.json"
            out_path = brand_dir / filename
            with out_path.open("w", encoding="utf-8") as fout:
                json.dump(reddit_json, fout, ensure_ascii=False, indent=2)

            total_written += 1

    print(f"\n✅ 导出完成：{total_written} 个 JSON 文件写入 {EXPORT_DIR}/")
    print("\n目录结构：")
    for brand_dir in sorted(EXPORT_DIR.iterdir()):
        if brand_dir.is_dir():
            files = list(brand_dir.glob("*.json"))
            print(f"  {brand_dir.name}/  ({len(files)} 文件)")


if __name__ == "__main__":
    main()
