---
title: Reddit Momcozy VOC Monitoring Product Plan
doc_type: product_plan
status: draft
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Reddit Momcozy VOC Monitoring Product Plan

## 1. Product Objective

Build a local, scheduled Reddit VOC monitor for Momcozy brand and product-category discussions. The system should collect daily at 07:00 Beijing time, use the rolling previous 24-hour post window, generate a Chinese single-page HTML insight report plus structured CSV/XLSX details, and prepare delivery for DingTalk at 08:00 Beijing time after explicit live-send authorization.

The product is not a generic Reddit scraper. It is a bounded evidence pipeline for brand and category monitoring. Every daily conclusion must be traceable to a post URL, comment URL or ID, collection method, run ID, and artifact hash.

## 2. Product Scope

### In Scope

- Reddit public community monitoring for Momcozy, wearable breast pump, bottle washer/sterilizer, and contextual baby-gear category terms.
- New posts only: post `created_at` must fall inside `[previous day 07:00, current day 07:00)` Asia/Shanghai.
- For matched new posts, collect currently available comments.
- Local browser-based collection through logged-in Chrome context where allowed by user.
- Agent-Reach/OpenCLI, browser-harness, browser `.json`, DOM fallback, RSS fallback, and TikHub fallback.
- Structured local storage, JSONL/CSV/XLSX export, lightweight rule analysis, Chinese HTML insight report, Chinese PNG insight card, and DingTalk Markdown delivery payload.

### Out of Scope

- Reddit OAuth official API, because no credentials are available.
- Posting, commenting, voting, messaging, or any Reddit write action.
- Cross-user profiling, author graph building, private community access, cookie export into repo files, or bypassing CAPTCHA.
- Treating TikHub calls as authorized before a separate provider gate.
- Treating DingTalk dry-run payload generation as live delivery.

## 3. Users and Jobs

Primary user: brand/VOC operator responsible for daily Momcozy category monitoring.

Daily jobs:

- See whether new Reddit conversations mention Momcozy, products, competitors, or category pain points.
- Identify negative signals such as leaks, output drop, pain, customer service, app, battery, cleaning, or return-to-work issues.
- Compare Momcozy with pump, bottle-washer, carrier, and baby-gear competitors such as Elvie, Willow, eufy, Medela, Spectra, Baby Brezza, Papablic, Ergobaby, BabyBjorn, Hatch, and other category players.
- Open original evidence quickly when a thread needs manual review.

## 4. Collection Strategy

### Priority Order

| Priority | Method | Role | Completion Meaning |
|---|---|---|---|
| P0 | Local browser `.json` | Primary structured thread reader | Browser-authenticated JSON parsed and stored |
| P0 | Agent-Reach/OpenCLI | Command router over browser login state | Search/read/subreddit commands return structured output |
| P0 | browser-harness | Real Chrome CDP control | Browser can open, inspect, and extract target pages |
| P1 | DOM fallback | Recovery when `.json` is unavailable | Visible page text/comments extracted with lower confidence |
| P1 | TikHub | Completion and fallback | Paid/API provider returns structured post/comment data after authorization |
| P2 | RSS | Discovery and health fallback | New post feed discovered, not full comment proof |
| P2 | browser-use | Diagnostic/exception handling | One-off browser task support, not deterministic core |
| P3 | last30days-skill | Retrospective research | Weekly/monthly research supplement |

### Collection Pipeline

```text
07:00 Asia/Shanghai collection scheduler
-> compute fixed 24h post window
-> discover candidate posts by subreddit and keyword
-> filter only posts created inside the window
-> fetch thread content/comments by browser .json
-> expand or mark partial when comments contain more nodes
-> fallback to DOM or TikHub only when needed and authorized
-> normalize and store posts/comments/matches
-> analyze sentiment/topic/pain points
-> export HTML, CSV/XLSX, JSONL and PNG artifacts
-> 08:00 Asia/Shanghai DingTalk dry-run or authorized send
```

### Required Read-Only Smoke Before Coding Collector

1. Confirm local browser automation can open Reddit using a dedicated Chrome profile.
2. Confirm a target post URL plus `.json` can be read from the browser context.
3. Confirm `r/ExclusivelyPumping` or another target subreddit can produce recent candidate posts.
4. Confirm a Momcozy or wearable pump thread can be parsed into post and comment records.
5. Record `full`, `partial`, or `failed` coverage for comment tree extraction.

## 5. Monitoring Targets

### Subreddit Tiers

P0:

- `r/ExclusivelyPumping`
- `r/BreastPumping`
- `r/breastfeeding`
- `r/HumansPumpingMilk`
- `r/breastpumps`

P1:

- `r/Buyingforbaby`
- `r/BabyBumps`
- `r/beyondthebump`
- `r/workingmoms`
- `r/NewParents`
- `r/babywearing`
- `r/moderatelygranolamoms`
- `r/FormulaFeeders`
- `r/parentsofmultiples`
- `r/NICUParents`

P2:

- `r/Mommit`
- `r/pregnant`
- `r/Parenting`
- `r/toddlers`
- `r/ScienceBasedParenting`
- `r/SAHP`
- `r/BabyBumpsCanada`
- `r/BabyBumpsandBeyondAu`
- `r/daddit`

### Keyword Families

Brand and variants:

- `momcozy`, `mom cozy`, `momcozi`, `momcozie`, `momcozy pump`, `momcozy pumps`, `momcozy wearable`, `momcozy bottle washer`, `momcozy carrier`

Momcozy products:

- `M5`, `M6`, `M9`, `S9`, `S9 Pro`, `S12`, `S12 Pro`, `V1`, `V1 Pro`, `V2`, `V2 Pro`, `Air 1`, `Mobile Flow`, `W1`, `KleanPal`, `KleanPal Pro`, `Klean Pal`, `Klean Pal Pro`, `D8`, `DinerPal`, `PureHug`, `Pure Hug`, `WeeSnug`, `BumpEase`, `Ergonest`, `Dreamlign`, `Ergowrap`

Category:

- Independent recall: `breast pump`, `wearable breast pump`, `wearable pump`, `hands-free pump`, `in-bra pump`, `portable pump`, `collection cups`, `pumping bra`, `flange inserts`, `pump parts`, `hospital grade pump`, `manual pump`, `electric pump`, `milk collector`, `baby bottle washer`, `bottle washer`, `bottle washer sterilizer`, `bottle sterilizer`, `sterilizer dryer`, `bottle warmer`, `pump parts washer`.
- Contextual recall only when Momcozy/product/competitor is present: `baby carrier`, `structured carrier`, `wrap carrier`, `babywearing`, `high chair`, `pregnancy pillow`, `nursing pillow`, `belly band`, `sound machine`, `white noise machine`, `baby monitor`, `diaper bag`.

Competitors:

- `Elvie`, `Willow`, `eufy`, `eufy S1`, `eufy S1 Pro`, `eufy E10`, `eufy E20`, `Medela`, `Spectra`, `Lansinoh`, `Motif`, `Zomee`, `Freemie`, `Pumpables`, `Baby Buddha`, `Baby Brezza`, `Papablic`, `Dr. Brown`, `Grownsy`, `Maymom`, `Nenesupply`, `BeauGen`, `Haakaa`, `Ceres Chill`, `Kindred Bravely`, `Ergobaby`, `BabyBjorn`, `Tushbaby`, `WildBird`, `Solly Baby`, `Hatch`, `Dreamegg`, `Yogasleep`, `Stokke`, `Abiie`, `Graco`, `Skip Hop`, `Lalo`

Pain points and scenarios:

- `output`, `supply`, `not emptying`, `leak`, `spill`, `suction`, `pain`, `flange`, `elastic nipples`, `noise`, `cleaning`, `parts`, `motor`, `replacement`, `battery`, `charging`, `dishwasher`, `mold`, `rust`, `app`, `insurance`, `customer service`, `mastitis`, `clogged duct`, `return to work`, `pumping at work`, `NICU`, `twins`, `multiples`, `postpartum`, `registry`

## 6. Data Product Contract

### Core Tables

- `runs`: one row per scheduled or manual run.
- `posts`: one row per Reddit post created inside the target window.
- `comments`: one row per parsed comment under a matched post.
- `matches`: keyword and rule matches at post/comment level.
- `analysis_items`: sentiment, topic, pain point, intent, and severity outputs.
- `delivery_attempts`: DingTalk dry-run/live-send attempts and status.

### Required Evidence Fields

- `run_id`
- `source_method`
- `source_url`
- `post_id`
- `comment_id`
- `created_at_utc`
- `collected_at_utc`
- `window_start_utc`
- `window_end_utc`
- `raw_payload_hash`
- `coverage_grade`
- `evidence_boundary`

### Privacy Defaults

- Store author only if needed for evidence context.
- Prefer `author_hash` over raw username.
- Do not store cookies, browser storage, tokens, webhook secrets, or provider keys in artifacts.

## 7. Analysis Design

Lightweight analysis should be deterministic first:

- sentiment: VADER compound score and label.
- brand_mentions: exact and variant matching.
- product_mentions: model matching with context rules.
- competitor_mentions: competitor dictionary.
- topic: product evaluation, purchase decision, troubleshooting, work scenario, insurance, customer service, competitor comparison, safety/health, other.
- pain_point: output/supply, leakage, pain/suction, flange fit, cleaning burden, parts, battery, app, noise, support, price, work use, health concern.
- severity: rule-based low/medium/high.
- confidence: rule confidence plus coverage grade.

LLM/provider analysis is optional future work and requires a separate provider-call gate.

## 8. DingTalk Delivery

Default delivery is Markdown digest:

- run window and collection method summary.
- posts matched, comments parsed, full/partial/failed coverage.
- Momcozy mentions and category mentions.
- positive/neutral/negative distribution.
- top posts and top negative signals.
- artifact links for HTML, XLSX, CSV and PNG when `REDDIT_VOC_ARTIFACT_BASE_URL` is configured.
- explicit boundary if data is partial.

Live DingTalk send is disabled until a specific authorization enables it. Dry-run should save the exact outbound body without sending.

## 9. Acceptance Layers

| Layer | Evidence | Not Equivalent To |
|---|---|---|
| Fixture tests | Local parser and analyzer pass | Real Reddit collection |
| Browser read-only smoke | Real browser can read target content | Scheduled daily success |
| TikHub read-only smoke | Provider returns sample data | Unlimited provider authorization |
| DingTalk dry-run | Request body generated | Message sent |
| DingTalk live smoke | One authorized test message sent | Daily production operation |
| Scheduled dry-run | Local scheduler executes | Production monitoring maturity |

## 10. Open Risks

- Browser login state may expire.
- Reddit may block `.json` in browser context or present anti-bot pages.
- Comment trees may be partial due to `more` nodes.
- Local machine sleep may skip scheduled runs.
- TikHub requires provider credential management and spend caps.
- DingTalk webhook must be protected and never logged.
