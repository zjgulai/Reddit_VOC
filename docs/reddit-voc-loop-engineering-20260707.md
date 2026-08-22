---
title: Reddit VOC Loop Engineering Configuration
doc_type: loop_config
status: draft
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit VOC Loop Engineering Configuration

## Component 1: Objective

The loop objective is a bounded daily VOC digest for Momcozy and wearable breast pump Reddit discussions. The loop must not expand into broad Reddit scraping, author profiling, live social actions, or unapproved provider calls.

## Component 2: State

The loop state is local and evidence-first:

- `.kiro/plan/task_plan.md`
- `.kiro/plan/progress.md`
- `.kiro/plan/findings.md`
- local SQLite under `data/`
- local artifacts under `outputs/` and `tmp/smoke/`

Secrets and browser cookies are excluded from loop state.

## Component 3: Policy

The loop policy controls fallback and stop conditions:

1. Try browser-authenticated `.json` or DOM only after user-confirmed browser/profile setup.
2. Use Agent-Reach/OpenCLI when Reddit backend is enabled.
3. Use TikHub only as an explicitly gated fallback.
4. Use RSS for discovery and health fallback.
5. Stop on login wall, CAPTCHA, provider-call need, live-send need, or unknown comment coverage.

## Component 4: Executor

The executor always takes the smallest safe next step:

- local initialization
- no-network fixture loop
- parser tests
- local SQLite migration
- DingTalk dry-run rendering
- read-only smoke only after confirmation

Default mode is dry-run.

## Component 5: Evaluator

The evaluator decides whether to continue, retry, fallback, or stop using:

- unit test results
- fixture row counts
- raw capture hashes
- coverage grade
- artifact presence
- explicit boundary flags

Partial read-only evidence must not be promoted to production acceptance.

