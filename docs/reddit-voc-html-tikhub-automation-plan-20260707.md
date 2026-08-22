---
title: Reddit VOC HTML TikHub Automation Plan
doc_type: execution_plan
status: draft
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: gated
live_send: gated
---

# Reddit VOC HTML TikHub Automation Plan

## Product Shape

The daily product is a single-page Chinese HTML public-opinion report. The report tells a complete insight story first and keeps the VOC detail table at the bottom. CSV/XLSX and PNG remain auxiliary artifacts.

Daily timeline:

- 07:00 Asia/Shanghai: collect Reddit posts created in the previous rolling 24 hours.
- 08:00 Asia/Shanghai: generate the Chinese HTML report and send the DingTalk message.

## TikHub API Selection

Selected Reddit APP endpoints:

- `/api/v1/reddit/app/fetch_subreddit_feed`: subreddit feed discovery.
- `/api/v1/reddit/app/fetch_dynamic_search`: brand and category keyword recall.
- `/api/v1/reddit/app/fetch_post_details_batch_large`: batch post detail enrichment, capped at 30 post IDs per batch.
- `/api/v1/reddit/app/fetch_post_comments`: fallback comment tree endpoint if the detail payload is incomplete.

The chosen sequence is `discover -> filter 24h window -> filter Momcozy/category relevance -> batch details/comments -> normalize -> analyze -> report -> DingTalk`.

## Execution Team Model

Data-source owner:

- Maintains TikHub endpoint mapping, request limits, and API-key runtime environment.
- Confirms provider status after each API or pricing change.

Pipeline owner:

- Maintains collector, SQLite schema, run status, and artifact generation.
- Ensures no secret is persisted to database, logs, reports, tests, or docs.

Insight owner:

- Maintains Chinese narrative structure, VOC labels, sentiment logic, and action recommendations.
- Reviews high-severity or negative posts before external circulation when needed.

DingTalk owner:

- Maintains webhook runtime configuration and reachable artifact host.
- Verifies HTML report links from DingTalk before enabling live schedule.

Ops owner:

- Installs launchd only after manual approval.
- Monitors missed-run checks, log retention, and failure summaries.

## Gates

TikHub provider call gates:

- `REDDIT_VOC_ENABLE_TIKHUB=1`
- `TIKHUB_API_KEY` present in runtime environment
- CLI uses `--authorize-provider-call`

DingTalk live send gates:

- `REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1`
- `DINGTALK_WEBHOOK_URL` present in runtime environment
- `REDDIT_VOC_ARTIFACT_BASE_URL` points to a reachable artifact host
- CLI uses `--authorize-live-send`

Scheduler gate:

- launchd plist files are templates only until explicitly installed and loaded by an operator.

## Current Execution Status

Implemented:

- TikHub provider module and gated CLI collector.
- 07:00/08:00 wrapper and launchd template defaults.
- Single-page HTML report with Chinese storyline and bottom detail table.
- DingTalk dry-run payload with HTML report as primary artifact.
- Live-send guard that blocks HTML report delivery without reachable artifact links.

Not executed in this loop:

- Real TikHub API call, because no runtime `TIKHUB_API_KEY` is available in the shell and Chrome extension access to the logged-in TikHub page is unavailable.
- DingTalk live send, because no runtime webhook or artifact base URL is available.
- launchd install/load.

## Acceptance Evidence

- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 59 tests OK.
- `bash -n` wrapper check: OK.
- `plutil -lint` launchd templates: OK.
- Local acceptance run ID: `html_report_acceptance_20260707`.
- Primary HTML artifact: `outputs/html_report_acceptance_20260707-insight-report.html`.
