---
title: Reddit VOC Project Management Index
doc_type: project_index
status: active
created: 2026-07-09
updated: 2026-07-14
owner: codex
production_boundary: authorized_live_operational_partial
provider_call: true
live_send: true
---

# Reddit VOC Project Management Index

## Core Context

- Codex context: `.codex/context-pack.md`
- Session handoff: `.codex/session-thread.md`
- Task plan: `.kiro/plan/task_plan.md`
- Progress log: `.kiro/plan/progress.md`
- Findings and risks: `.kiro/plan/findings.md`
- Acceptance evidence: `.kiro/plan/acceptance.md`
- Latest historical backfill execution and local repair:
  `.superpowers/sdd/task-25-remote-recovery-report.md` and
  `.superpowers/sdd/task-26-per-request-recovery-contract-report.md` and
  `.superpowers/sdd/task-27-remote-recovery-report.md`; read all three before
  any Provider continuation.

## Runtime Boundaries

- Secrets stay outside the repo. Do not commit `.env`, webhook URLs, API keys, or private keys.
- Local/generated runtime paths stay outside Git: `data/`, `outputs/`, `logs/`, `tmp/`, `.codegraph/*.db`.
- Current production schedule: 07:00 Asia/Shanghai collect-only, 08:00 Asia/Shanghai report and DingTalk delivery.
- Historical backfill collect remains `partial/budget_exhausted`; the original
  `670/670` successful Provider attempts did not establish complete historical
  coverage. Task 19 transferred the exact Task 18 bundle under manifest SHA
  `c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`
  and ran its one authorized network-disabled staging replay. Replay returned
  `complete/replay_complete`, fingerprints were equivalent, and replay DB SHA
  is `3504190ab2b80ad1a003da27574455802f4184499eeaa7d458a6b771c3a8c638`.
  Formal full validation was not authorized or run, so Task 14 acceptance and a
  merge plan still do not exist.
- Task 20 is `local_verified` for budget-extension/hydration-resume
  authorization and strict discovery reindex: combined `243/243`, heavy
  validation/replay/reindex `108/108`, full suite `445/445`, independent review
  with no P0/P1, and canonical `22/22` manifest SHA
  `347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94`.
  Task 21 later transferred the exact bundle and consumed one authorized
  network-none staging reindex. It failed closed on
  `strict_discovery_schema_unknown`; no target DB was published. The failure
  report SHA is `9de8ca1170a9479d269fc2f6ab2421513b0cc0a01a52d530658d4e07a8ee1a62`
  and all postflight invariants passed. Source/raw and production are unchanged;
  Provider/live-send are false. The one-shot guard is consumed. Task 21R has
  locally repaired the two reviewed wrapper shapes and added a read-only corpus
  gate; reindex `26/26`, full suite `452/452`, candidate manifest
  `88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f`.
  Task 21S later exact-passed the real `670`-artifact gate and completed one
  authorized network-none staging reindex, publishing target DB SHA
  `2046e908dd29389fa56189184a20c17dfc53c41e7932e7781250c38a3370e3d9`
  without changing source/raw/production or the Provider ledger. Task 22A now
  has local packet candidate SHA
  `6fbec55efdd506fbfcb2376f6bbb47bbca5e7d9ede914caf7542ca6e004a106f`
  with cumulative maximum `1478`. The owner approved it, but exact remote
  preflight rejected its first-lane `670 -> 670` ceiling before transfer or
  Provider execution. Corrected Task 22C packet SHA
  `4b969be4af4abf343e0dac093f4c8465ef867981009b1a5180787f318f3da24c`
  was later authorized and executed once. Its `32/32` new Provider attempts
  succeeded, but collection stopped on strict subreddit/comment schema gaps;
  production/source stayed unchanged. Task 23 repaired those initially reviewed
  contracts locally and produced release manifest SHA
  `edc6ec9b44871d9a93e9a77ca2fdaf3f91a7ede2e282d48bd3f6d1bdc91e9c51`
  plus fresh Task 21S-source packet SHA
  `ab5386e7d2022dd1a354569bd5fa0abfadcd741549902d4cae53b90d8f17daa1`.
  Task 23 was later authorized and executed once. It advanced Provider
  `670 -> 702` with `32/32` new succeeded attempts, then stopped
  `partial/candidate_failures`; postflight passed `26/26` and source/raw/
  production remained unchanged. Offline diagnosis found remaining nonempty
  subreddit structural-mirror and nonterminal comments/failure-isolation gaps.
  The Task 23 guard is consumed. Task 24 locally verified (`613/613`) manifest
  `dbaf6186...181ad` and bundle `28eb1847...e034`. Task 25 then exact-passed
  preflight/admission and consumed one authorized network-none recovery, but
  failed closed on `strict_discovery_page_chain_invalid`; no target DB was
  published. Failure postflight passed `21/21`, and source/raw, Provider
  `702/1200` and production remained unchanged. Its guard is consumed. Task 26
  then locally repaired exact per-request succeeded-attempt/endpoint binding
  and failure-aware postflight; focused `38/38`, related `407/407`, full suite
  `634/634`. Candidate manifest is `d375b127...b38d17`, deterministic bundle is
  `a265dc1f...dadfed`, and Task 27 packet is `66f666a2...01c6b3`. Task 27 then
  passed exact preflight/admission and one network-none recovery, publishing
  target DB `56d74951...8570a4`; final postflight passed all invariants. The
  target had 258 pending candidates and seven missing batch members at that
  checkpoint. Source coverage remains partial; Task 28 later ran once in
  isolated staging and stopped at `candidate_failures` after `969/1200`
  successful Provider requests. Any further Provider work requires a new
  state freeze and authorization; production merge, Git push and DingTalk
  remain prohibited.

## Verification Commands

```bash
bash -n scripts/deploy_webapp_tencent.sh scripts/server_daily_collect.sh scripts/server_daily_report.sh scripts/run_daily_collect.sh scripts/run_daily_report.sh
plutil -lint config/launchd/com.reddit-voc.daily-collect.plist.template config/launchd/com.reddit-voc.daily-report.plist.template
PYTHONPATH=src:. python3 -m unittest discover -s tests -v
codex doctor
```
