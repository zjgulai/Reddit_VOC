---
title: Reddit VOC Read-Only Smoke Runbook
doc_type: runbook
status: active
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit VOC Read-Only Smoke Runbook

## 1. Purpose

This runbook validates the local browser-based Reddit collection path before any collector code is built around it. It must prove what can be read from the local machine, what is blocked, and which fallback should be used.

This runbook is read-only. It must not post, comment, vote, message, alter account settings, call TikHub, or send DingTalk messages.

## 2. Current Local Probe Result

| Check | Result | Implication |
|---|---|---|
| `browser-harness` binary | available at `/Users/pray/.local/bin/browser-harness` | Browser CDP route exists |
| Codex browser-harness skill | available at `/Users/pray/.codex/skills/browser-harness/SKILL.md` | Skill route exists |
| Chrome | running | Local browser is available |
| `browser-harness --doctor` | daemon/connections reported fail, but direct `page_info()` later succeeded | Treat daemon as flaky until smoke repeats cleanly |
| Agent-Reach | available at `/Users/pray/.local/bin/agent-reach` | Router exists |
| Agent-Reach Reddit backend | `off` | Need OpenCLI or rdt-cli before relying on Agent-Reach for Reddit |
| Agent-Reach RSS backend | `ok`, feedparser | RSS can be fallback |
| Current active Chrome tab | Gmail / TikHub email verification | Do not clobber user tab; use `new_tab()` for any navigation |

## 3. Preconditions

- User confirms which Chrome profile can be used for Reddit read-only collection.
- User manually logs in to Reddit in that profile if login is required.
- Agent must not ask for or type credentials.
- No cookies, tokens, browser storage, screenshots containing secrets, or webhook values are written to repo files.
- If Reddit shows auth wall, CAPTCHA, or risk challenge, stop and report `browser_gate_blocked`.

## 4. Smoke Steps

### Step A: Browser Harness Health

Run:

```bash
browser-harness <<'PY'
ensure_real_tab()
print(page_info())
PY
```

Expected:

- Returns current browser page info.
- If it hangs or errors, stop and fix browser-harness before Reddit validation.

### Step B: Open a New Reddit Tab

Use `new_tab()` rather than `goto_url()` to avoid clobbering the user's active tab.

Target options:

- Known example: `https://www.reddit.com/r/shopify/comments/1umbsm4/shopify_store_traffic_is_100_visitorsday_but/`
- Category target: `https://www.reddit.com/r/ExclusivelyPumping/new/`

Expected:

- Page loads in a new tab.
- If login wall or CAPTCHA appears, stop.

### Step C: Browser `.json` Read

Open the same post with `.json` appended:

```text
https://www.reddit.com/r/shopify/comments/1umbsm4/shopify_store_traffic_is_100_visitorsday_but/.json
```

Expected:

- Browser-visible JSON or preformatted text can be read.
- Parsed top-level shape is a Reddit listing array.
- If backend `curl` returns `403` but browser succeeds, classify route as `browser_json_only`, not backend API.

### Step D: Target Category Thread

Find or open a Momcozy/wearable pump thread in a target subreddit and repeat Step C.

Required record:

- `post_id`
- `subreddit`
- `post_created_at`
- `post_title`
- `parsed_comment_count`
- `more_node_count`
- `coverage_grade`

### Step E: RSS Fallback Probe

For discovery fallback, probe:

```text
https://www.reddit.com/r/ExclusivelyPumping/new/.rss
https://www.reddit.com/r/breastfeeding/new/.rss
https://www.reddit.com/r/HumansPumpingMilk/new/.rss
```

Expected:

- Atom/RSS entries can be parsed.
- Result is tagged `discovery_only` unless comments are separately proven.

## 5. Smoke Artifact Contract

Save sanitized smoke output under:

```text
tmp/smoke/reddit-readonly-smoke-YYYYMMDD-HHMMSS.json
```

Required fields:

```json
{
  "run_id": "readonly-smoke-...",
  "started_at": "...",
  "finished_at": "...",
  "method": "browser_json|browser_dom|rss",
  "target_url": "...",
  "browser_status": "ok|blocked|login_required|captcha|error",
  "parsed_post_id": "...",
  "parsed_comment_count": 0,
  "more_node_count": 0,
  "coverage_grade": "full|partial|post_only|failed",
  "provider_call": false,
  "live_send": false,
  "secrets_written": false,
  "notes": []
}
```

## 6. Stop Conditions

Stop immediately if:

- Reddit asks for credentials, CAPTCHA, or account verification.
- The active browser tab contains unrelated sensitive material and navigation would clobber it.
- Any tool output would include cookies, tokens, webhook secrets, or private message content.
- TikHub or DingTalk would be called without explicit authorization.

## 7. Pass Criteria

Minimum pass for moving to collector implementation:

- Browser-harness returns stable page info.
- A new Reddit tab can be opened without clobbering the current tab.
- At least one `.json` post can be read and parsed in browser context.
- Coverage is explicitly recorded as `full`, `partial`, `post_only`, or `failed`.
- RSS fallback is probed separately and not conflated with comment capture.

## 8. Smoke Result 2026-07-07

Browser route evidence:

- `browser-harness --doctor`: Chrome running, daemon alive, active browser connection present.
- Optional `profile-use` and `BROWSER_USE_API_KEY` are not present; these are not required for local Chrome read-only smoke.
- Known post `.json` route passed:
  - URL: `https://www.reddit.com/r/shopify/comments/1umbsm4/shopify_store_traffic_is_100_visitorsday_but/.json`
  - parsed post ID: `1umbsm4`
  - parsed comments: `23`
  - more nodes: `0`
  - coverage grade: `full`
- Target subreddit `.json` route passed:
  - listing URL: `https://www.reddit.com/r/ExclusivelyPumping/new/.json?limit=5`
  - parsed post ID: `1upm96p`
  - parsed comments: `5`
  - more nodes: `0`
  - coverage grade: `full`
  - artifact: `tmp/smoke/reddit-readonly-smoke-20260707-154433.json`
- RSS discovery-only route passed:
  - `r/ExclusivelyPumping`: `ok`
  - `r/breastfeeding`: `ok`
  - `r/HumansPumpingMilk`: `ok`
  - artifact: `tmp/smoke/reddit-rss-smoke-20260707-154453.json`

Boundary:

- `provider_call=false`
- `live_send=false`
- No Reddit write action.
- No cookies, browser storage, tokens, or webhook values were written.

## 9. CDP Profile Smoke Result 2026-07-07

- Plain `browser-harness` attached to a different Chrome/CDP session and received a Reddit network-security login wall.
- The project now supports explicit `--browser-cdp-url` for `run-browser-json-smoke`.
- Launching the already-running `~/.reddit-voc/chrome-profile` with a new remote-debug port did not make `http://127.0.0.1:9333/json/version` available.
- Launching a separate repo-external automation profile at `~/.reddit-voc/chrome-automation-profile` with `REDDIT_VOC_CHROME_REMOTE_DEBUG_PORT=9333` exposed `http://127.0.0.1:9333/json/version`.
- Standard smoke artifact: `outputs/loop10_cdp_profile_smoke_20260707-browser-json-smoke-summary.json`.
- Result: CDP route is operational, Reddit still requires a manually logged-in account state for `.json` collection.

Boundary:

- `provider_call=false`
- `live_send=false`
- No TikHub call.
- No DingTalk send.
- No Reddit write action.
