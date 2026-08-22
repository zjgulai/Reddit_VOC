---
title: Reddit VOC Dedicated Chrome Profile Runbook
doc_type: runbook
status: draft
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit VOC Dedicated Chrome Profile Runbook

## Purpose

Prepare a dedicated local Chrome profile for Reddit read-only browser collection before any scheduled run depends on browser login state.

## Boundaries

- The profile directory must stay outside this repo.
- Cookies, browser storage, screenshots with account information, and webhook values must not be written into repo artifacts.
- Profile readiness checks use file existence only and do not read cookie contents.
- This runbook does not authorize TikHub, DingTalk live send, Reddit write actions, or scheduler installation.

## Default Profile

Default directory:

```bash
~/.reddit-voc/chrome-profile
```

Initialize and inspect:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli browser-profile-init
PYTHONPATH=src python3 -m reddit_voc.cli browser-profile-status
```

Print the launch command:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli browser-profile-launch-command
```

Open Chrome for manual Reddit login:

```bash
scripts/open_reddit_chrome_profile.sh
```

Open Chrome with a local DevTools endpoint for `browser-harness`:

```bash
REDDIT_VOC_CHROME_USER_DATA_DIR="$HOME/.reddit-voc/chrome-automation-profile" \
REDDIT_VOC_CHROME_REMOTE_DEBUG_PORT=9333 \
scripts/open_reddit_chrome_profile.sh
```

Then use:

```bash
PYTHONPATH=src python3 -m reddit_voc.cli run-browser-json-smoke \
  --database data/reddit_voc_loop10_cdp_smoke.sqlite3 \
  --output-dir outputs \
  --run-id loop10_cdp_profile_smoke_20260707 \
  --url https://www.reddit.com/r/shopify/comments/1umbsm4/shopify_store_traffic_is_100_visitorsday_but/.json \
  --browser-cdp-url http://127.0.0.1:9333 \
  --browser-daemon-name reddit-voc-profile
```

Dry-run the launch command without opening Chrome:

```bash
REDDIT_VOC_OPEN_CHROME=0 scripts/open_reddit_chrome_profile.sh
```

## Manual Login Acceptance

After Chrome opens:

1. Log in to Reddit manually in that dedicated Chrome window.
2. Open `https://www.reddit.com/`.
3. Confirm the page shows the logged-in account state.
4. Do not save passwords or recovery codes into project files.
5. Re-run `browser-profile-status`; `profile_present_login_unverified` means a cookie store exists but still is not proof of a working Reddit session.

## Next Gate

Only after manual login is confirmed should a future loop run a read-only browser `.json` smoke with this profile. That future smoke must still keep:

- `provider_call=false`
- `live_send=false`
- `reddit_write=false`
- `scheduler_installed=false`
