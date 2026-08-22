---
title: Reddit VOC launchd Dry-Run Plan
doc_type: runbook
status: draft
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
scheduler_installed: false
---

# Reddit VOC launchd Dry-Run Plan

## Purpose

Prepare a macOS local scheduler path for the Reddit VOC monitor without installing or loading any scheduler job in this loop.

## Current Scope

- Wrapper script: `scripts/run_local_daily_dry_run.sh`
- Template: `config/launchd/com.reddit-voc.daily-dry-run.plist.template`
- Collector wrapper: `scripts/run_daily_collect.sh`
- Report wrapper: `scripts/run_daily_report.sh`
- Report dry-run sub-wrapper: `scripts/run_daily_report_dry_run.sh`
- Collector template: `config/launchd/com.reddit-voc.daily-collect.plist.template`
- Report template: `config/launchd/com.reddit-voc.daily-report.plist.template`
- Default local database: `data/reddit_voc.sqlite3`
- Default local outputs: `outputs/`
- Default logs: `logs/`

## Schedule Target

- Local time zone: Asia/Shanghai.
- Collector target run time: 07:00 Beijing time.
- Report target run time: 08:00 Beijing time.
- Collector launchd fields: `StartCalendarInterval` Hour `7`, Minute `0`.
- Report launchd fields: `StartCalendarInterval` Hour `9`, Minute `0`.

## Dry-Run Acceptance

Manual dry-run command:

```bash
REDDIT_VOC_RUN_ID=launchd_dry_run_manual \
REDDIT_VOC_DATABASE_PATH=data/reddit_voc_launchd_dry_run.sqlite3 \
REDDIT_VOC_OUTPUT_DIR=outputs \
scripts/run_local_daily_dry_run.sh
```

Expected artifacts:

- `outputs/launchd_dry_run_manual-posts.jsonl`
- `outputs/launchd_dry_run_manual-comments.jsonl`
- `outputs/launchd_dry_run_manual-posts.csv`
- `outputs/launchd_dry_run_manual-comments.csv`
- `outputs/launchd_dry_run_manual-dingtalk-dry-run.json`
- `outputs/launchd_dry_run_manual-daily-detail.xlsx`
- `outputs/launchd_dry_run_manual-daily-detail.csv`
- `outputs/launchd_dry_run_manual-insight-report.html`
- `outputs/launchd_dry_run_manual-insights.png`
- `outputs/launchd_dry_run_manual-daily-dingtalk-dry-run.json`
- `outputs/launchd_dry_run_manual-daily-report-summary.json`
- `outputs/launchd_dry_run_manual-status-summary.json`
- `outputs/launchd_dry_run_manual-issue-summary.json`
- `outputs/launchd_dry_run_manual-log-retention-summary.json`
- `logs/launchd_dry_run_manual.log`

Daily-shape manual commands:

```bash
REDDIT_VOC_RUN_DATE=20260707 \
REDDIT_VOC_DATABASE_PATH=data/reddit_voc_daily_manual.sqlite3 \
REDDIT_VOC_OUTPUT_DIR=outputs \
scripts/run_daily_collect.sh

REDDIT_VOC_RUN_DATE=20260707 \
REDDIT_VOC_DATABASE_PATH=data/reddit_voc_daily_manual.sqlite3 \
REDDIT_VOC_OUTPUT_DIR=outputs \
REDDIT_VOC_REPORT_OUTPUT_DIR=outputs \
scripts/run_daily_report.sh
```

The report wrapper uses the default run ID shape `daily_collect_<YYYYMMDD>_0700`, matching the collector wrapper for the same Beijing local date.
It defaults to `REDDIT_VOC_DINGTALK_MODE=dry_run`. Live send requires `REDDIT_VOC_DINGTALK_MODE=live`, `REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1`, a runtime `DINGTALK_WEBHOOK_URL`, `REDDIT_VOC_ARTIFACT_BASE_URL`, and the CLI `--authorize-live-send` gate inside the wrapper.

## Missed-Run Check

After a manual or scheduled dry-run, check the expected 07:00 Beijing-time collection window:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli missed-run-check \
  --database data/reddit_voc_launchd_dry_run.sqlite3
```

For historical acceptance, pass a fixed UTC anchor that corresponds to the target Beijing-time run:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli missed-run-check \
  --database data/reddit_voc_launchd_dry_run.sqlite3 \
  --anchor-utc 2026-07-06T23:00:00+00:00
```

## Log Retention

The wrapper writes `logs/{run_id}.log` and keeps newest log files by `REDDIT_VOC_LOG_KEEP_LAST`, default `30`.

Preview retention without deleting:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli prune-artifacts \
  --path logs \
  --pattern "*.log" \
  --keep-last 30
```

## Install Gate

Do not run these commands until explicitly authorized:

```bash
cp config/launchd/com.reddit-voc.daily-dry-run.plist.template ~/Library/LaunchAgents/com.reddit-voc.daily-dry-run.plist
launchctl load ~/Library/LaunchAgents/com.reddit-voc.daily-dry-run.plist

cp config/launchd/com.reddit-voc.daily-collect.plist.template ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist
cp config/launchd/com.reddit-voc.daily-report.plist.template ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:REDDIT_VOC_ENV_FILE string $HOME/.reddit-voc/secrets/reddit-voc-live.env" ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:REDDIT_VOC_ENV_FILE string $HOME/.reddit-voc/secrets/reddit-voc-live.env" ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist
plutil -lint ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist
launchctl load ~/Library/LaunchAgents/com.reddit-voc.daily-collect.plist
launchctl load ~/Library/LaunchAgents/com.reddit-voc.daily-report.plist
```

## Boundaries

- `provider_call=false`
- `live_send=false`
- `scheduler_installed=false`
- TikHub is only called when `REDDIT_VOC_ENABLE_TIKHUB=1`, `TIKHUB_API_KEY` is present, and provider authorization is passed.
- For live scheduler usage, keep secrets in the repo-external `REDDIT_VOC_ENV_FILE`; do not paste secrets into plist files.
- DingTalk live webhook is not sent.
- Reddit write actions are not performed.
