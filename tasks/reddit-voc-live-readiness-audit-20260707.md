---
title: Reddit VOC Live Readiness Audit
doc_type: execution_audit
status: active
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit VOC Live Readiness Audit

## Verdict

The full target is not complete yet.

Facts:

- Local fixture and browser-smoke infrastructure exists.
- One DingTalk live send was previously executed for `dingtalk_live_send_20260707_1851`.
- That live send was `status=partial`, with `threads=1`, `comments=2`, `analysis=3`, `provider_call=false`, and `live_send=true`.
- The sent screenshot did not include clickable detail links because artifact paths were rendered as local text paths.
- The current repository still has `scheduler_installed=false`.
- The CDP browser route exists, but Reddit `.json` real collection is gated by manual Reddit login in the CDP-enabled profile.
- The current wrapper still runs fixture-safe collection, not a real daily Reddit discovery and post-detail collection loop.

Inference:

- The project has a local MVP and an owner-gated DingTalk sender, but it is not yet proven by natural cron as an unattended daily 07:00 Beijing-time collection plus 08:00 DingTalk production workflow.
- Local artifact paths cannot become DingTalk mobile-clickable links without a reachable artifact base URL or file-hosting channel.

Uncertain:

- Whether the current Chrome automation profile can access Reddit after manual login has not been re-proven in this loop.
- Whether DingTalk should receive another live message with the fixed digest requires explicit live-send authorization and runtime webhook env.

## Executed In This Loop

- Added `analysis` structured exports:
  - `outputs/<run_id>-analysis.jsonl`
  - `outputs/<run_id>-analysis.csv`
- Added `source_url` to exported comment rows.
- Added DingTalk `Details` section with Reddit post/comment links and local analysis summary.
- Added optional artifact link hosting support through `--artifact-base-url` or `REDDIT_VOC_ARTIFACT_BASE_URL`.
- Regenerated local dry-run payload for screenshot run:
  - `outputs/dingtalk_live_send_20260707_1851-dingtalk-dry-run.json`
  - `outputs/dingtalk_live_send_20260707_1851-analysis.jsonl`
  - `outputs/dingtalk_live_send_20260707_1851-analysis.csv`
- Ran a new non-live acceptance run:
  - run_id `link_detail_acceptance_20260707`
  - `provider_call=false`
  - `live_send=false`

## Remaining Execution Plan

1. Real Reddit read gate:
   - Manually log in to Reddit in `~/.reddit-voc/chrome-automation-profile`.
   - Re-run `run-browser-json-smoke` against a target `.json` URL through `--browser-cdp-url http://127.0.0.1:9333`.
   - Acceptance: at least one real target thread ingests with `browser_status=ok` and parsed rows.

2. Daily collection gate:
   - Replace fixture wrapper collection with real discovery plus detail-fetch loop.
   - Enforce post creation-time window: Beijing 07:00 run collects posts created in the previous 24 hours only.
   - Acceptance: no old-post-new-comment rows are treated as new posts.

3. Artifact-link gate:
   - Choose a reachable artifact base URL or DingTalk file/upload channel.
   - Set `REDDIT_VOC_ARTIFACT_BASE_URL` only at runtime.
   - Acceptance: artifact links in DingTalk resolve outside the local machine.

4. Scheduler gate:
   - Install/load launchd only after owner authorization.
   - Acceptance: one scheduled local collection run at Beijing 07:00 is observed and `missed-run-check` reports `covered`.

5. Live-send gate:
   - Send the fixed digest only after explicit owner authorization for that run and runtime webhook env is present.
   - Acceptance: DingTalk response `errcode=0`, local delivery row `mode=live`, and secret scan remains clean.

## Verification

- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 48 tests OK.
- `PYTHONPATH=src python3 -m reddit_voc.cli doctor --no-network`: status `ok`.
- `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template`: OK.
- `bash -n scripts/run_local_daily_dry_run.sh`: exit 0.
- `codegraph sync . && codegraph status .`: index up to date.
- Secret scan found no real webhook/provider secrets; matches were placeholders or test-only `example.invalid` values.
