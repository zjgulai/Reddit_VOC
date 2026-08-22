---
title: Reddit VOC Troubleshooting Guide
doc_type: runbook
status: draft
created: 2026-07-07
updated: 2026-07-09
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit VOC Troubleshooting Guide

## Login Expiry

Signal: browser `.json` smoke reports `login_required` or a HTML login wall.

Action:

- Re-open the dedicated Reddit browser profile.
- Manually verify the Reddit session.
- Re-run `run-browser-json-smoke` against a known public post.
- Do not switch to TikHub or live DingTalk delivery from this signal alone.

## Reddit Block Page or CAPTCHA

Signal: browser status reports `captcha`, `blocked`, or HTML content instead of Reddit JSON.

Action:

- Stop the current collection route.
- Keep `provider_call=false` and `live_send=false`.
- Record the blocked reason in the daily summary.
- Re-run only after manual browser access is usable again.

## 429 or Rate Limit

Signal: browser body or page text indicates rate limiting.

Action:

- Increase delay between URLs before another live browser read-only attempt.
- Reduce subreddit/listing breadth.
- Keep TikHub as an explicitly authorized fallback only.

## Empty Comments

Signal: post is present but comments are absent or coverage is `post_only`.

Action:

- Check whether Reddit returned `more` nodes.
- Keep the run as `partial` rather than treating the comment tree as complete.
- Use structured exports to inspect `parsed_comment_count`, `more_node_count`, and `coverage_grade`.

## TikHub Fallback

Signal: local browser route cannot cover high-value threads and the owner authorizes provider fallback.

Action:

- Require explicit provider authorization before setting `REDDIT_VOC_ENABLE_TIKHUB=1`.
- Keep request count, endpoint, and cost evidence in the run note.
- Do not store API keys in repo files or memory.

## TikHub Subreddit Feed 400

Signal: `outputs/<run_id>-collector-summary.json` shows `stage=listing`, `url=/api/v1/reddit/app/fetch_subreddit_feed`, `http_status=400`.

Action:

- Keep the bearer token out of logs and repo files.
- Use documented query params for subreddit feed: `subreddit_name`, uppercase `sort` such as `NEW`, `after`, and `need_format=false`.
- Do not pass undocumented `limit` to `fetch_subreddit_feed`; keep `limit` only on dynamic search unless TikHub documentation changes.
- Validate with a collect-only run before the next live DingTalk send.

## Manual Rolling 24h Run

Signal: owner requests an immediate run anchored at the current time instead of the scheduled 07:00 collection window.

Action:

- Keep cron unchanged; the scheduled tasks remain `0 7 * * *` collect-only and `0 8 * * *` report/DingTalk delivery under `CRON_TZ=Asia/Shanghai`.
- Set `REDDIT_VOC_WINDOW_END_UTC=<current UTC timestamp>` and `REDDIT_VOC_ROLLING_WINDOW_HOURS=24` on the manual collect/report invocation.
- Use `server_daily_cycle.sh` only when a live DingTalk send is explicitly authorized.
- Use `server_daily_collect.sh` for provider validation without sending a DingTalk message.

## Category-Only or Empty-Body Posts

Signal: collected Reddit data includes category-only posts, link posts, image posts, or posts with empty `selftext`.

Action:

- Keep collection breadth unchanged so category demand and discovery coverage are not lost.
- DingTalk VOC blocks and daily detail CSV/XLSX should show only rows whose post body or parsed comments contain `Momcozy`/`momcozy`.
- Do not use title-only brand/category matches as enough evidence for DingTalk detail display.
- If a displayed row has empty body, it must be retained only because parsed comments mention `Momcozy`/`momcozy`; otherwise it should be hidden from the push detail.

## DingTalk Delivery Issue

Signal: dry-run payload exists but live delivery is not authorized or not yet validated.

Action:

- Inspect `outputs/<run_id>-dingtalk-dry-run.json`.
- Verify `msgtype=markdown` and artifact links.
- Keep `live_send=false` until webhook URL, secret, and owner authorization are present.

## Missed Daily Window

Signal: `missed-run-check` returns `status=missed`.

Action:

- Inspect launchd state only if a scheduler was explicitly installed.
- Run the wrapper manually with a clear `REDDIT_VOC_RUN_ID`.
- Use `status-summary` and `issue-summary` to distinguish no run, empty result, and partial coverage.
