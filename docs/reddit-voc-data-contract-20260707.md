---
title: Reddit VOC Data Contract
doc_type: data_contract
status: draft
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit VOC Data Contract

## 1. Contract Principles

- Store evidence first, analysis second.
- Every analysis item must trace back to `run_id`, `raw_capture_id`, and `source_url`.
- Browser-derived data, RSS-derived data, manual imports, and TikHub enrichment must remain distinguishable.
- Missing fields stay null; do not invent score, comment count, author, or timestamp values.
- Author identity is not a product entity; default to omitted or hashed author context.

## 2. Run

```json
{
  "run_id": "run_20260707_040000_asia_shanghai",
  "run_type": "manual|scheduled|smoke",
  "status": "running|success|partial|failed|empty",
  "window_start_utc": "2026-07-06T20:00:00Z",
  "window_end_utc": "2026-07-07T20:00:00Z",
  "timezone": "Asia/Shanghai",
  "started_at_utc": "2026-07-07T20:00:00Z",
  "finished_at_utc": null,
  "collection_methods": ["browser_json"],
  "provider_call": false,
  "live_send": false,
  "error_summary": null
}
```

## 3. Raw Capture

```json
{
  "raw_capture_id": "raw_...",
  "run_id": "run_...",
  "source_method": "browser_json|browser_dom|agent_reach_opencli|rss|manual_json|tikhub",
  "source_url": "https://www.reddit.com/r/.../comments/.../",
  "captured_at_utc": "2026-07-07T20:03:12Z",
  "auth_boundary": "browser_login|anonymous_public|provider_api|manual_import",
  "http_status": 200,
  "browser_status": "ok|blocked|login_required|captcha|error",
  "raw_payload_hash": "sha256:...",
  "payload_format": "json|html|atom|text",
  "selector_version": null,
  "blocked_reason": null,
  "secrets_written": false
}
```

## 4. Reddit Thread

```json
{
  "thread_id": "t3_...",
  "post_id": "...",
  "run_id": "run_...",
  "raw_capture_id": "raw_...",
  "subreddit": "ExclusivelyPumping",
  "title": "...",
  "selftext": "...",
  "url": "https://www.reddit.com/r/.../comments/.../",
  "permalink": "https://www.reddit.com/r/.../comments/.../",
  "created_at_utc": "2026-07-07T00:50:56Z",
  "score": null,
  "upvote_ratio": null,
  "num_comments_reported": null,
  "parsed_comment_count": 0,
  "more_node_count": 0,
  "coverage_grade": "full|partial|post_only|failed",
  "matched_keywords": ["momcozy", "wearable pump"],
  "author_hash": null
}
```

## 5. Reddit Comment

```json
{
  "comment_id": "t1_...",
  "post_id": "...",
  "run_id": "run_...",
  "raw_capture_id": "raw_...",
  "parent_id": "t3_...|t1_...",
  "body": "...",
  "created_at_utc": "2026-07-07T01:10:00Z",
  "score": null,
  "depth": null,
  "is_submitter": null,
  "matched_keywords": ["leak"],
  "author_hash": null,
  "deleted_or_removed": false
}
```

## 6. VOC Item

`voc_items` are normalized evidence units derived from either posts or comments.

```json
{
  "voc_item_id": "voc_...",
  "run_id": "run_...",
  "source_type": "post|comment",
  "source_id": "t3_...|t1_...",
  "source_url": "https://www.reddit.com/...",
  "text": "...",
  "normalized_text_hash": "sha256:...",
  "brand_mentions": ["Momcozy"],
  "product_mentions": ["M5"],
  "competitor_mentions": ["eufy"],
  "category_mentions": ["wearable pump"],
  "pain_points": ["leak", "output"],
  "intent_labels": ["purchase_decision"],
  "manual_review_status": "not_reviewed|needs_review|reviewed"
}
```

## 7. Analysis Result

```json
{
  "analysis_id": "analysis_...",
  "run_id": "run_...",
  "voc_item_id": "voc_...",
  "analysis_version": "local_rules_v1",
  "sentiment_label": "positive|neutral|negative",
  "sentiment_score": 0.0,
  "topic": "product_evaluation|purchase_decision|troubleshooting|work_scenario|insurance|customer_service|competitor_comparison|safety_health|other",
  "severity": "low|medium|high",
  "confidence": 0.8,
  "evidence_ids": ["raw_..."],
  "provider_call": false
}
```

## 8. Delivery Preview

```json
{
  "delivery_id": "delivery_...",
  "run_id": "run_...",
  "channel": "dingtalk",
  "mode": "dry_run|live",
  "status": "created|sent|failed|blocked",
  "message_hash": "sha256:...",
  "artifact_paths": ["outputs/...csv", "outputs/...jsonl"],
  "live_send": false,
  "response_status": null,
  "error_message": null
}
```

## 9. Structured Exports

For each run, exports are written under `outputs/` by default:

- `{run_id}-posts.jsonl`
- `{run_id}-comments.jsonl`
- `{run_id}-analysis.jsonl`
- `{run_id}-posts.csv`
- `{run_id}-comments.csv`
- `{run_id}-analysis.csv`
- `{run_id}-daily-detail.csv`
- `{run_id}-daily-detail.xlsx`
- `{run_id}-insight-report.html`
- `{run_id}-insights.png`
- `{run_id}-daily-dingtalk-dry-run.json`
- `{run_id}-daily-report-summary.json`

Posts JSONL and CSV fields:

```text
post_id, run_id, raw_capture_id, subreddit, title, selftext, source_url,
created_at_utc, score, num_comments_reported, parsed_comment_count,
more_node_count, coverage_grade, matched_keywords, author_hash
```

Comments JSONL and CSV fields:

```text
comment_id, post_id, run_id, raw_capture_id, parent_id, body, created_at_utc,
score, depth, is_submitter, matched_keywords, author_hash, deleted_or_removed,
source_url
```

Analysis JSONL and CSV fields:

```text
analysis_id, run_id, source_type, source_id, analysis_version,
sentiment_label, sentiment_score, topic, severity, confidence, pain_points,
provider_call, source_url
```

Export boundaries:

- `provider_call=false`
- `live_send=false`
- exports contain parsed local SQLite rows, not browser cookies, browser storage, webhook secrets, or raw Reddit `.json` payloads.
- DingTalk artifact paths are local evidence unless an operator provides `REDDIT_VOC_ARTIFACT_BASE_URL` or `--artifact-base-url` pointing to a reachable file host.

Chinese daily detail CSV/XLSX fields:

```text
采集窗口, Subreddit, Post ID, 帖子链接, 发帖时间UTC, 标题原文, 标题中文,
正文原文, 正文中文, 匹配关键词, 情感标签, 情感分数, 主题, 严重度, 痛点,
评论数, 评论整合原文, 评论整合中文, 覆盖状态, 翻译状态
```

Daily report rules:

- The table keeps one row per Reddit post.
- The post title/body have Chinese fields.
- All parsed comments under the post are merged into `评论整合原文` and `评论整合中文` in the same row.
- `dry_run` translation uses local glossary entries when available and preserves unknown text without calling a provider.
- `libretranslate` translation posts body/comment text to a runtime-configured LibreTranslate-compatible `/translate` endpoint and writes returned Chinese text into `正文中文` and `评论整合中文`.
- `{run_id}-insights.png` is the Chinese daily insight image for DingTalk preview or manual upload.
- `{run_id}-insight-report.html` is the primary single-page Chinese public-opinion report. It contains the full insight storyline and keeps the VOC detail table at the bottom.
- DingTalk live delivery should point to the HTML report through `REDDIT_VOC_ARTIFACT_BASE_URL`; local paths are dry-run evidence only.

## 10. TikHub Reddit Provider Contract

Selected TikHub Reddit APP endpoints:

```text
/api/v1/reddit/app/fetch_subreddit_feed
/api/v1/reddit/app/fetch_dynamic_search
/api/v1/reddit/app/fetch_post_details_batch_large
/api/v1/reddit/app/fetch_post_comments
```

Provider-call gates:

- `REDDIT_VOC_ENABLE_TIKHUB=1`
- `TIKHUB_API_KEY` exists in runtime environment
- CLI receives `--authorize-provider-call`
- secret values are not written to SQLite, JSON, CSV, HTML, logs, docs, tests, or memory

## 11. Deduplication Keys

| Layer | Key |
|---|---|
| Raw capture | `source_method + source_url + raw_payload_hash` |
| Post | `platform + post_id` |
| Comment | `platform + comment_id` |
| VOC item | `source_type + source_id + normalized_text_hash` |
| Delivery | `run_id + channel + message_hash + mode` |

## 12. Status Semantics

- `success`: all required collectors completed and no required thread is partial.
- `partial`: at least one source failed, comment tree was partial, or fallback was needed.
- `empty`: collectors succeeded but no matching new posts were found.
- `failed`: no usable source completed or core storage/report generation failed.
