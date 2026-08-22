---
title: Reddit VOC Context Pack
doc_type: context_pack
status: active
created: 2026-07-07
updated: 2026-07-23
owner: codex
production_boundary: insights_site_l4_production_accepted
provider_call: false
live_send: false
---

# Reddit VOC Context Pack

Goal: Momcozy Reddit VOC monitor and read-only website. Product schedule is 07:00 Asia/Shanghai collection for the previous rolling 24h, then 08:00 DingTalk delivery of Chinese HTML insight report plus XLSX/CSV detail artifacts.

Accepted collection priority: local browser login state plus Reddit `.json`/DOM, Agent-Reach/OpenCLI, browser-harness, TikHub only as gated fallback, RSS discovery fallback.

Current state:

- On 2026-07-23, the local Reports V3 candidate closed the business-visible
  history contract without changing production. The independent
  `reddit_voc_business_history_index_v1` publishes 14 prior complete days, 12
  prior complete ISO weeks and 12 prior complete calendar months. Together
  with the three latest complete periods this is 41 business entries; the
  three internal comparison archives remain non-business artifacts, so the
  bundle contains 44 report documents. The immutable current local version is
  `reddit_voc_reports_20260723_v3_382d621ae075_history2`; the earlier history1
  name was not reused after the public manifest contract changed. Candidate manifest
  `3240005aec33b9e519674797eb5265c9f8a1ce7e94011446fdce3b9d71ead2c6`
  and public manifest
  `637a955282fa4eed78efee682a967978702104a1de2c9cd52ce522d0ed62e72f`
  passed independent deterministic full-byte replay. The local-only
  current-release pointer SHA is
  `5207fcdc85c0e21c555b16a87e43718e3a8ad93caa8582f383bc5ce42af55669`.
  The frontend validates nine report bootstrap files, does not eagerly fetch
  any of the 38 history bodies, and lazily loads exactly one descriptor- and
  SHA-bound report for `period` + `period_id`. Chrome acceptance passed the
  current view, selection, deep-link refresh and 390px overflow checks with no
  browser errors. History loading failures and rapid period switches now keep
  export disabled, and recursive undeclared files plus ancestor symlinks fail
  closed in writers, validators and current-release assembly. Related Python
  and dist-audit tests passed 49/49; the full frontend suite
  passed 212 tests with 46 existing contract-gated skips. Lint, typecheck and
  production build passed, with only the seven existing
  Fast Refresh warnings and two existing React key warnings. Production,
  collector, cron, DingTalk, shared Nginx, TLS, DNS and other Docker state were
  unchanged.
  A bare Vite build is not the deployable projection because it copies retained
  historical versions from `public/data`; the release path must keep the
  existing `audit_insights_dist.py --prepare-dist` pruning step followed by a
  second read-only dist audit.

- On 2026-07-22, the local report candidate added the hash-bound
  `reddit_voc_brand_health_dimension_contribution_v1` contract. Every complete
  period now carries two comparison sides times four dimensions; each
  dimension combines post and comment scores at 50/50 and contributes 25% to
  the displayed index. The monthly booklet shows the governed organic four
  dimensions and explicitly labels them as index composition, not period
  change attribution. The weekly booklet now carries
  `reddit_voc_action_review_v1`; because no real action ledger was supplied it
  truthfully renders `ledger_available=false`, `completion_supported=false`
  and no completion-rate value. Metrics manifest
  `382d621ae075ed2519b51d59947cd40f3f228b978fc1f921047610abbddd3902`,
  reports manifest
  `1e2c0e73bc1d20faf75a179e717aba24254e7f79393bc15370aa70df24526217`
  and public manifest
  `580517a1c524ecb752db083e90568f5da5d961d5e1acf85bfb9e2a85af1a6a35`
  passed deterministic replay and the staged local pointer SHA is
  `671709b00f30cea311dbacfd4fbfb7d4ec38b7621310aae2ba1210c7920367c0`.
  Focused Python tests passed 38/38; report-focused frontend tests passed 11
  plus the updated story test passed 4/4 with a 30-second timeout under the
  loaded desktop environment. Production build, lint (seven existing Fast
  Refresh warnings) and Chrome headless weekly/monthly DOM acceptance passed.
  The browser receipt is
  `tmp/reddit-voc-v3/report-health-action-20260722/browser-acceptance/receipt.json`,
  SHA `675ab295508e31fbc4c46829b4ee861fcbf47e3bc6aca40d261fa57c7b17c34f`;
  an independent verifier recomputed both DOM artifact hashes and approved the
  local candidate with no blocker.
  An attempted full Vitest run did not produce a trustworthy final summary
  because workers remained alive in the loaded desktop environment; those
  processes created by this run were stopped and the focused run was repeated.
  Independent audit confirmed the existing archive is only a comparison
  baseline container. Business-visible history remains the next contract and
  must use a separate index plus complete history reports. Production,
  collector, schedule, DingTalk and provider state were unchanged.

- On 2026-07-22, the next local V2.0 report-data batch closed the daily
  activity split without touching production. `reddit_voc_period_activity_v1`
  is a hash-bound extension of the periodized metrics candidate and conserves
  each period's comments across current-period posts, historical posts and
  unresolved parents. It publishes separate `all_observed` and governed
  `momcozy` scopes. For the latest complete day, 2026-07-18 Asia/Shanghai, the
  all-observed pool contains 7 new posts and 25 new comments, including 11
  comments on 4 historical posts; governed Momcozy contains 2 new posts and 14
  new comments, including 9 comments on 2 historical posts. The weekly row
  also preserves five unresolved-parent comment observations instead of
  misclassifying them. Metrics candidate manifest
  `a71a3a723bd9cc1ad1b7cc4a55424598e7ff07e27e6f16c4444a38bfab9ffbf9`
  passed independent deterministic full-byte recomputation. Reports candidate
  manifest `d7c958c8ab5be11b45ea2c805b4ee78c11bc4f7d438c9cb6f49109d64545c489`
  and public manifest
  `216532b6b724fdadae3a248225d8337b03487c2a144937a39ef1aaaf14ec0d13`
  passed deterministic and privacy-safe validation. The local frontend now
  points only its Reports binding to
  `reddit_voc_reports_20260716_v3_a71a3a723bd9`; Base, Insights, Personas and
  Cases remain unchanged. Focused Python tests passed 18/18; focused frontend
  tests passed 12 with seven existing contract-gated skips; lint retained the
  same seven Fast Refresh warnings; typecheck/build passed. Local Playwright
  acceptance found one activity module, exact `2/14/9/2` Momcozy and
  `7/25/11/4` all-pool values, no horizontal overflow and no console errors.
  The complete frontend suite passed 205 tests with 46 contract-gated skips;
  two pre-existing React list-key warnings remain visible in Settings and
  CompetitorBrandConfig tests.
  Weekly action writeback, monthly health-dimension contribution and multiple
  business-visible historical reports remain open. No deploy, collector,
  schedule, DingTalk, provider or production mutation occurred.

- On 2026-07-22, V2.0 UI Gate 2 advanced locally without production changes.
  The shared snapshot layout now renders an evidence-based data status bar for
  Base, Reports and Insights: business as-of/latest observed event, center and
  projection identities, release time, owner-declared completeness, collector
  run explicitly unavailable when absent, structural coverage and 6,953
  unresolved-parent comments. It does not infer fresh/stale from dates because
  the current release has no freshness SLA state. `MetricHelpPopover` is now
  the single help interaction for dashboard metrics, comparison cards and V3
  report indicators, with 44px targets, Escape/outside close and focus return.
  The overview primary story now flows from governed scope and window KPIs to
  all-history health, dual-axis trend, four decision entries (pain, reputation,
  new product, GEO) and priority actions. No window health score was invented:
  the 7/30/183-day projection lacks the required four-dimensional inputs. The
  Reports now assign post events to Asia/Shanghai business days. The daily
  booklet recalls six Momcozy-related new posts and five real evidence posts
  for the current complete day, and daily/weekly/monthly use distinct 4/4/5-step
  business narratives. The fake single-choice "latest complete period" control
  was removed; the UI shows the actual current period and explicitly states
  that V3 internal comparison archives are not independently browsable business
  reports. Active-historical-post comment splits, weekly action writeback,
  monthly health-dimension contribution and multiple business-visible archives
  remain upstream contract gaps and were not fabricated. The report page passed
  12 desktop/tablet/390px/reduced-motion visual checks, and the 13-route
  desktop/390px same-dist E2E passed with receipt SHA
  `f1efb17f4ac3add2ce43c668a3661dfa369be1075d0abc8ad34d9ffe4eb27844`.
  The full frontend suite passed 204 tests with 46 contract-gated skips; lint kept
  seven pre-existing Fast Refresh warnings and `tsc -b` plus Vite build passed.
  No deploy, schedule, DingTalk send, provider call or production write occurred.

- On 2026-07-19, the latest merged center and the previously stale auxiliary
  projections were closed into one immutable local V3 insights candidate. The
  center conserves 3,535 posts and 27,316 stored comments = 20,363 linked
  comments + 6,953 unresolved-parent comments + 0 quarantined comments. The
  current-release pointer remains
  `reddit_voc_release_20260719_v3_center_refresh_003`, SHA
  `330d74bea480b1a5942c8e89308b030e5b5d7d88e3b9149a3eb007567cf13622`;
  it binds Base `reddit_voc_site_snapshot_20260718_v3_center_refresh_003`,
  reports/insights `...984feb57d25f`, and Personas
  `reddit_voc_personas_20260718_center_v2`.

  Brand health was rebuilt as
  `reddit_voc_brand_health_20260719_center_refresh_003` with overall index
  `72.54` and four dimensions `57.06/99.94/50.41/82.76`; it remains
  provisional because label coverage is not complete. The rolling-quarter
  projection `reddit_voc_quarter_insights_20260719_center_refresh_003` covers
  2026-04-20 through 2026-07-18 and contains 832 canonical posts plus 8,474
  stored comments, of which 8,258 are linked and 216 remain parent-debt inside
  the quarter. Its analysis pool is 828 posts + 8,258 contextual comments =
  9,086 VOCs; Momcozy contributes 1,752 VOCs, with 1,522 sentiment-classified,
  230 unclassified and 88 negative. Therefore the displayed `5.78%` negative
  rate is a classified-base rate, not an all-VOC rate. Persona output is 377
  assignments across 231 unique evidence entities. The historical casebook was
  not mutated; all four canonical posts and all 16 evidence comments resolve in
  the latest center, while its one external reference remains intentionally
  outside canonical data.

  The corrected frontend source candidate is
  `325ac56ebc5fb1699d735866dcc72f0c8e6ff31dbc8ea7cfa997b00b8d3fc578`;
  source manifest SHA is
  `84996673fd5cbed65eb20d7d7ecd17ab8dae970793b8de422bac5843323ae463`
  and independent source validation receipt SHA is
  `c32ec91953fb3d7d94fcb5ac33813a81097342590cabadd31888df11f9a3d60a`.
  The linux/amd64 immutable release is
  `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b`.
  A temporary project-local BuildKit builder used `dockerproxy.net` only for
  the pinned Nginx digest; Docker Desktop global configuration was not changed
  and the builder/image/container/network were removed after validation.
  Local isolated container smoke, 13-route desktop/mobile same-dist browser
  acceptance, security probes and CSV/PDF/PPTX/DOCX export acceptance passed.
  Final candidate receipt SHA is
  `71966bb85cbf8106305011157511f898f7b297309c255a8f5177f3cad1118437`.
  Local registry candidate
  `648313d45b26513910656109dc66435fa9cf3f0cd7509ab692f3717b40fd5bc7`
  validates with tree SHA
  `99f02455427d66b990d67e41c8cc4cdfb80810fab702514b5136a9acefacebf0`.

  Focused current-candidate checks are green: 86 Python tests passed; the
  targeted frontend set passed 52 tests with 45 contract-gated skips; the
  isolated frontend source gate passed 195 tests with 46 skips plus lint,
  typecheck and build (seven existing Fast Refresh warnings). Repository test
  infrastructure was then repaired: `pytest` is a locked development
  dependency, the project is editable-installable through Hatchling, and the
  test path includes `src` plus the repository root. Daily-report release
  import closure was restored by lazy-loading backfill/V2 commands and adding
  `raw_artifacts.py` to the exact runtime release. The inherited-lock validator
  now accepts every numeric file descriptor >=3, and the current schema-drift
  test targets the run-scoped raw-capture uniqueness contract. The six affected
  modules passed 132 tests + 96 subtests. A dedicated collector/backfill review
  then recovered the exact frozen bytes for the five evolved files
  (`pyproject.toml`, `backfill_cli.py`, `backfill_seed.py`, `storage.py` and
  `tikhub.py`) and confirmed that the drift comes from later V2 functionality,
  not corruption of the 2026-07-11 release. The old manifest was not re-signed.
  Its 23 reviewed files are now preserved in
  `config/backfill/archive/momcozy-backfill-reviewed-files-20260711.tar.gz`
  with archive SHA
  `909a8f5f0f6aa5c03e506d648bc2eb8caa9ef2d62b33d484c006cdedae5fab39`.
  The historical contract passes 5 tests + 23 subtests, the expanded
  backfill/storage/TikHub set passes 441 tests + 538 subtests, and the entire
  repository passes 1,596 tests + 840 subtests. Current collector code requires
  a new release attestation before any future collector deployment. The same
  batch removed 24 unreferenced, deterministically rebuildable current-candidate
  intermediates (about 677 MB); candidate registry validation remained `passed`
  with tree SHA
  `99f02455427d66b990d67e41c8cc4cdfb80810fab702514b5136a9acefacebf0`.
  No promotion packet was generated and no SSH, deploy, remote write,
  collector/cron/shared-Nginx/TLS/DNS change, provider call or live send
  occurred. Production remains on its previously accepted release.

- On 2026-07-19, after a new explicit owner authorization limited to packet
  generation, a fresh SSH-stdin read-only production baseline passed at
  `2026-07-19T10:04:31Z`. Production was still release
  `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`;
  required containers were healthy, candidate port 18339 was unused, and the
  database, container inventory, cron and shared Nginx remained stable. The
  immutable native-V3 promotion packet is
  `tmp/reddit-voc-v3/candidate-orchestration/v3-center-refresh-002/promotion-r6-20260719/promotion-packet.json`,
  SHA
  `cbf43b1a8b9709d6fc985f1288c90b4bcb9fe723b55b597e0905a27d47527fe9`,
  for release
  `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b`.
  It binds 20 artifacts, validates `passed`, has mode `0600`, expires at
  `2026-07-19T12:06:25Z`, and remains `promotion_authorized=false`,
  `consumed=false`, `deploy=false`. Packet build/validation/execution-boundary
  tests passed 23/23. No production switch or remote write occurred; a second
  exact owner authorization naming both packet SHA and release SHA is required.

- Later on 2026-07-19, the owner supplied that exact dual-SHA authorization.
  Permit
  `tmp/reddit-voc-v3/candidate-orchestration/v3-center-refresh-002/promotion-r6-20260719/promotion-permit.json`
  has SHA
  `78c06e8c1e198ac0b2b274c76497edb0ee1e5b5f90b76dc8b2b3b6516b59372d`.
  The established insights-only runner promoted release
  `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b`;
  image id is
  `sha256:bba3d6989659f8b6ddebab288b773576358ab477217fe9c2e12d257bdff9f045`
  and `reddit_voc_insights_web` is healthy. Public acceptance passed 13/13
  routes, 8/8 public artifacts and 20/20 sensitive-path 404 checks, with exact
  TLS, release marker and data pointer bindings. Canonical remote promotion
  receipt SHA is
  `4460f75aff7e7979c491a3c59b4419bbf8d886dec0ad62c6a4b6998be54c3cfd`;
  production acceptance SHA is
  `fed962a99d27653b44001229e6ab42c6ca2d8f90ff2317023f91cddb36d561bf`;
  consumption SHA is
  `73321a2383460c2ca39966a92ab64a7fbfb8452d470ca14bb1fd81060ae1cfe0`.
  The collector and translation container identities, health and restart
  counts remained unchanged; database, cron, shared Nginx, TLS, DNS, other
  Docker environments, Provider calls, live sends and schedules were not
  modified. Rollback release
  `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`
  remains checksum-valid.

- On 2026-07-18, the production A10 release received fresh public browser
  acceptance against `https://reddit.lute-tlz-dddd.top`: the existing 13-route
  desktop/mobile callback exited successfully, and a focused browser smoke
  independently confirmed dashboard, reports, insights and cases as HTTP 200
  with exact paths, required content, no horizontal overflow, no console errors
  and no failed requests. Four 1440px full-page screenshots are bound by receipt
  SHA `7f63b2adbf6fd6adbeadb9fd5d4d715286c69c4a6b1c817f705f34235f4fad92`.
  This was read-only; production remained unchanged.

- On 2026-07-18, the latest collector SQLite snapshot was copied read-only from
  `reddit_voc_site_app` after matching remote pre/post and local SHA
  `3ae47f91ce9d22249fb9b0c4815b89829f163adba1c5656b4a03f33c4f28a0f6`.
  A new deterministic server-snapshot SourceBatch bridge produced manifest
  `9d66f8d526180a921f9d6dab50da879fa0e23b0769796cfd720dda991546775a`
  and passed validation receipt
  `e25e856c6402250bfa2d90e88c4e821c9ab7e6d4548dc2f20aaad0acd52b9bda`.
  Local V2 fusion added 41 posts and 158 comments, producing 3,535 posts and
  27,316 stored comments = 20,365 linked + 6,951 unresolved-parent + 0
  quarantined. All ten former quarantine rows were upgraded from fresh server
  evidence: two linked and eight moved to explicit parent-post debt. The
  original 6,943 unresolved rows had zero parent-post and zero comment matches
  in this server snapshot. Independent candidate validation passed and replay
  was `no_change`. This is a local candidate only; collector, cron, shared
  Nginx, production data, deployment and live send were unchanged.

- On 2026-07-18, A10 local candidate release
  `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`
  was built as a linux/amd64 immutable insights-site container after the pinned
  `nginxinc/nginx-unprivileged:1.29.4-alpine@sha256:a6c4f61f456b85b8fdf7ec7ab28cc3e299440e6fb4a9dea520e5fd8fd440025e`
  base image became available in the local Docker cache. Build receipt SHA is
  `c32d007295df2134a7c0f4fae4d25ef5a3abea68a8c32d399281bfeb212f61b3`,
  release manifest SHA is
  `cf184b96fce98cf84b2d032b861f0daf3cba5032963dd355b615cd1f5cc359ec`,
  image tar SHA is
  `7d4d8c12e42b249bd5ca58f168ce3104ff1bc2b92798ce09b4bf87ef5dc1734c`,
  and transfer tgz SHA is
  `32a6678ca602cbd87cfd92b8395308479aaad0709e9a9647c9ecf0502e81ce72`.
  Local isolated container smoke passed with receipt
  `4840cedaee3d6b36f80d12d440481defef5a9946c904b13b7510faa2706f4996`;
  same-dist browser E2E passed after the help-popover close fallback was added
  to `scripts/playwright_insights_e2e.js`, receipt
  `6a48ecdd3c82f001faae32e7a8586cb4d89ba8491fc722056c683278c9ecbbe2`.
  Export acceptance must run against the candidate container, not a bare dist
  preview, because `/release.json` is generated by the Dockerfile at image
  build time. Container-backed CSV/PDF/PPTX/DOCX export acceptance passed with
  receipt `fa7caffaea8f24961a5310dcd642b0166f7692cd8e06a46fe586397e2d477d0e`;
  security receipt `356eb305d3d7f5db87f3b63241cedb6fd7ba9ca7227e888aa1752b9877eee87d`
  binds release, compose, container-smoke and export evidence. Production was
  unchanged. A10 is not yet a registered candidate: the current registry/final
  receipt path still forces legacy Plan A/source-manifest-v1 lineage, while A10
  uses native V3 source-manifest-v2 four-dataset lineage. Do not register A10
  by reusing the old 2026-07-15 Plan A closure; its dataset SHAs do not match
  the A10 release pointer.

- On 2026-07-18, a read-only server Docker/Nginx inventory found the production
  insights site at container `reddit_voc_insights_web`, image
  `reddit-voc-insights:9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`,
  port binding `172.20.0.1:18338->8080`, compose project
  `reddit_voc_insights`, working under
  `/opt/reddit-voc-insights-site/releases/9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`.
  The data collection platform is `reddit_voc_site_app`, image
  `reddit-voc-site:20260707`, binding `127.0.0.1:18337->8080`, compose project
  `reddit_voc_site`, working under `/opt/reddit-voc-site/webapp`. Shared Nginx
  is in `ai_video_nginx`: `reddit.lute-tlz-dddd.top` proxies to
  `http://172.20.0.1:18338`, while `reddit.brand.lute-tlz-dddd.top` proxies to
  `reddit_voc_site_app:8080`. This observation was read-only; collector, cron,
  shared Nginx, TLS, DNS and other Docker environments were not modified.

- On 2026-07-18, PPC-03 added a local immutable V3 orchestration-contract materializer and a v2
  terminal-marker monitor contract. A nonterminal marker now blocks before auxiliary probes; a terminal
  marker still requires a two-point quiescence check. Focused candidate tests are `67 passed, 38 subtests
  passed`; production remains unchanged. The audit also proved that the current V3 orchestrator role contract
  is fixture-only: real source/metrics artifacts and `passed_candidate_only` receipts do not satisfy its generic
  `status/upstream_sha256` assumptions. Two complete real candidate cycles remain pending a dedicated
  source-freeze-to-V3-source bridge and real artifact adapter; no fixture result is treated as production-ready.

- On 2026-07-17, B2b center-to-business activation completed locally. Activation manifest
  `670964755588b9a9c7eb8a0744c0dc614090904cb1ff76459a3d99055c5a3a14` binds the complete center to
  23,586 analysis-ready VOCs, 159,044 governed facts, 26 indicators, 82 atomic persona definitions,
  eight persona cohorts, six report artifacts and 78 storyline units. The independently validated frontend source
  `454598e73f7bacfa9da0b68f562bf65d571aaa922cc98aff293c00ad85debcab` includes the privacy-safe activation
  projection. Release `f335d9d27e168068385d99e022a9a4fc6cd5e898485845c965186e3034325d4b` has 76 files,
  passed 195 unit tests, lint/typecheck/build, same-dist 26-page E2E and isolated container smoke. Two final read-only
  shadows passed and classified the delta from production `9c4a45f2...84cc5` as the same four business datasets plus
  a new activation-governance projection; 6,943 unresolved parents and 10 quarantined comments remain explicit debt.
  Packet `fa54470d7e20e406875febd5315d42749d7a69bdc6742570542663b91dd246f6` is independently validated as
  `ready_for_owner_authorization`, expires at `2026-07-17T13:08:30Z`, and has not been permitted or consumed.
  Production remains unchanged.
- On 2026-07-17, the complete validated V3 canonical baseline was bridged into the V2 local center.
  The immutable SourceBatch manifest SHA is
  `fcb6b5d18e823e2b63feacc906fa2c4a0fd8807a1561d4f155d6cf6912abd77d`; its passed validation
  receipt SHA is `f2b0cc3c77f0790bcb533d69fc7b23e04921ff01f6a2353c10d42d37b3bfda00`, and the bridge
  receipt SHA is `2e21861c5a73d7d9e1db6c33c0c04f8d8ed9d37b1b8893731592fea55c5463f4`. The new local
  center conserves exactly 3,494 posts and 27,158 stored comments = 20,205 linked + 6,943
  unresolved-parent + 10 quarantined, with zero missing or unexpected post/comment identities.
  Independent candidate validation and zero-diff validation passed; the second orchestration was
  fusion/metric/candidate `no_change`. The candidate SHA is
  `13fbfcbbbad2f9170780ea2489b0aebec8a52345c05b8668881d688076aefc55`. This closes only the
  full-baseline-to-center portion of B2. The center-to-page builders, full-page E2E and shadow cycles
  were subsequently closed by B2b as recorded above. Provider reply schema remains outside this batch.
- On 2026-07-17, Product V2.0 completed its local control-plane implementation and four-round
  independent read-only review. The final review result is `PASS — V2 local control plane`, with
  P0/P1/P2/P3 all zero across requirements completeness, logic, edge cases, code quality, test
  coverage and actual local runtime evidence. The reviewed candidate binds 16 code/test SHAs;
  65 focused tests, compileall, shell syntax and diff checks pass. The r6 historical-subset smoke
  contains 102 posts and 3,132 linked comments, five bound surface artifacts, a passed independent
  validator and deterministic consumed/created/created then no_change/no_change/no_change replay.
  Partial coverage keeps daily/weekly/monthly comparisons closed. This is not a complete product or
  production release. At that historical checkpoint, B1 still required a reviewed
  `fetch_comment_replies` response fixture and B2 required the complete baseline bridge. The baseline
  bridge, page activation, E2E and two read-only shadow cycles have since passed as recorded above.
  Production, providers, cron, deployment, live send and remote state were unchanged.
- On 2026-07-17, the quarterly-insights and executive-overview iteration completed an owner-authorized,
  insights-only production promotion and L4 public acceptance. The only consumable frontend source is A9
  `c7e5eeedf118c1af74564f843e57699d1f3efb925658533b6efe75ccd35df7c8`, source manifest
  `41b567ac32b9e8c145921cbd4cc2ac64cce13b628e748509cfdbff571cdf17ac`; promoted release
  `9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5` has release manifest
  `41f46821f335f198df6375ca6fc3328e6468f1c960e13548c59cfb589015a30e`.
  Packet `7ff1227cc63e03c1102de9bad4371361d3cf00da6739cbec91d5a9c29bcdceb8` and permit
  `8e68138ba62a624e5c03af9070615ad6623af37358638de8a37d00b7f04c95c5` were consumed in-window to switch only
  the insights site from `627fbab6...2478bed4` to this release. Data release remains
  `reddit_voc_release_20260716_v3_818f7eae7627_ui2`: 3,494 posts and 27,158 stored comments = 20,205 linked +
  6,943 unresolved-parent + 10 quarantined; historical collection completeness follows the owner's 100%
  declaration and the 6,943 rows remain relationship debt.
  Public HTTPS passed exact 13 routes, eight public artifacts and 20 security 404s. The first browser attempt
  failed closed because the harness did not wait for state submission; that log is retained. After the harness
  wait contract passed 10/10 tests, r2 passed 26/26 desktop/mobile pages, three report states and cases 33/17/1
  with zero browser, same-origin HTTP or external-request failures. Remote promotion receipt SHA is
  `c4e7d2f01b186bfb2313cf5176e388c0c5e6d8ba795e4fcaf15709ffdf6e597a`; production acceptance SHA is
  `c37248efc026457286adbc3d7d8eab9005d24072e889afab67b120004518255a`; immutable consumption SHA is
  `20d4d05d832e42427ec37c6e26b1e3d68434a618f1e1b286cdb55503c0259058`.
  Collector, cron, shared Nginx, TLS, DNS, database, scheduling, provider calls, live sends and other Docker
  environments were unchanged. The prior release remains rollback-ready; rollback was not executed. This new
  release has `four_exports_complete=false`; the prior release's 4/4 export receipt is historical only. Earlier
  A6/A7/A8 sources and A8/A9 build releases are superseded. Future production promotion still requires a new
  exact owner authorization.
- On 2026-07-16 at `11:56:43Z`, the owner-authorized insights-only promotion
  consumed packet
  `ace4553d7007703e081a4a0a4a654417d332368661b357d972d1e16891de4f6e`
  and release
  `627fbab6622d73326386b57010e852a10c3d2133e2e47d941246767b2478bed4`.
  At that historical checkpoint, production pointed to data release
  `reddit_voc_release_20260716_v3_818f7eae7627_ui2`: 3,494 posts and 27,158
  stored comments = 20,205 linked + 6,943 unresolved-parent + 10 quarantined.
  Public acceptance passed 13 routes, eight public artifacts, 20 security 404s,
  26/26 desktop/mobile pages and cases 33/17/1 with zero browser, same-origin
  HTTP and external-request failures. The L4 acceptance receipt SHA-256 is
  `c609b83bd200fc010afb9bbc89e7bdc61b4f9135b318ea0892485eec9abdeb1d`;
  the permit-consumption receipt SHA-256 is
  `de757bd20e2fa3a6571c07c11b1f8106570020ef7ff6fe3dac5a38cca469323c`.
  On the same production release, CSV/PDF/PPTX/DOCX real downloads then passed
  independent read-only structure, business-content and release-binding checks;
  export receipt SHA-256 is
  `c2ce743d6babd7d6abbb114efebff5db0041411e39e6befdfd53c0878d6ca5a4`.
  Two-point read-only HTTPS observation also found `release.json` and
  `current-release.json` byte-stable and terminal/quiescent; monitor receipt
  SHA-256 is
  `8ab8dee2d853f420c64c1d4d23d6bf45a6d3b2c66d78b14b19c1a76a0020ad88`.
  Production remained unchanged by export acceptance. Historical collection
  completeness remains the owner's 100% declaration; 6,943 rows are explicit
  relationship debt. Candidate automation development remains local-only until
  a new exact authorization.
- On 2026-07-16 at `09:16:06Z`, the owner-authorized V3 insights-only
  promotion consumed packet
  `103efd8c7405d5dd7c5b414c93d7601297b9be9703c628737cdfa4a3583329a2`
  and release
  `ea15b3ef0a1af7a2c9e644b2090c4d36a3dd1038e7967ba8a78402e659a0efc1`.
  The same remote deployment lock covered fresh L3 preflight, exact artifact
  verification, the isolated 18339 candidate smoke, expected-current CAS and
  the 18338 production smoke. Public HTTPS then passed 13 routes, eight public
  artifacts, 20 security 404s and 26/26 desktop/mobile browser pages with zero
  browser, same-origin HTTP or external-request failures. Production now points
  to `reddit_voc_release_20260716_v3_1ab1c634f225`: 3,494 posts, 27,158 stored
  comments, 20,205 linked comments, 10 quarantined comments and 6,943
  unresolved-parent comments. Historical collection completeness is the
  owner's 100% declaration; the 6,943 rows remain explicit relationship debt,
  not a collection-completeness downgrade. The L4 acceptance receipt SHA-256 is
  `972253ec811ed4627a033a1675c071e3b683f0c22f045833002afe184a61a914`
  and the immutable permit-consumption receipt SHA-256 is
  `ad73e0a147a0abea22b8d372581dc5efe585dc1bc80db1ee0e905864955689be`.
  Collector and LibreTranslate IDs/restart counts, cron, shared Nginx,
  database/report state and all unrelated running containers were preserved;
  TLS, DNS, schedules, provider calls and live sends were not modified.
- On 2026-07-15, Plan A completed as a local-only independently validated
  candidate closure. The only consumable candidate input is
  `70a917e5bdf0df319d52d8077f3cc71b813a36f54c609194b07fea386844ac1e`;
  its manifest/reconciliation/receipt SHAs are
  `c18d313ae7ee038d06e2402022548709bcba2b71e54bef106b636215291cdfb7`,
  `347fc37a167f8bdb3562928af850d62c5be7b720f501f9a8a65383dc2cf957b7`,
  and `e2958d7d057c25a265839e7693aa164079c7dfad9dc131f1291d8266c7bc9f80`.
  The a3e code freeze is `8de68f3b7310fa58d396d6ddb28505e176ee2d41ec472ef4f33d62a61108276e`;
  both builder and independent validator now require `--code-root` and rehash
  all 15 frozen code files. The closure has exactly eight private files,
  0700/0600 modes, zero symlinks, byte-identical source-freeze/four-ledger
  copies, `unaccounted_total=0`, and deterministic `no_change` reruns.
  Independent adversarial review closed at P0=0/P1=0. Base totals are 1,322
  posts, 16,591 stored comments, 16,581 linked comments and 10 quarantined;
  release net-new versus the pre-promotion RC3 baseline is zero posts and 3,605 linked
  comments. Public A3c is 21 files / 30,102,047 bytes with 42 risk themes, 17
  Momcozy product scopes, six report states, competitor same-sample dimensions,
  323 evidence-persona assignments, and cases 38/12/0. Open coverage 1,179 and
  pending lineage 18 remain explicit. Plan B is now complete at local L2: its
  only consumable frontend candidate input is
  `c04aec93775179be20f6b5538795c647b66a2a6df36c3a898fdc6b7119eb022e`, source
  manifest `32afe3adb5ed7b24c62d28a76856ca509432b441941c8befe4946630a2384e6d`, and
  independent source receipt
  `340e4f65c753eff75031bd129654f9faa8699366e5f76c97726e6cb1c44853ab`.
  The UI source uses the final 1,322/16,591/16,581/10 Base and manifest-only
  27-file public stage; frontend 166/166, lint/typecheck and ephemeral build pass,
  with independent artifact/UI audits P0=0/P1=0/P2=0. Receipt-less
  `870855c1...885e` is superseded. Plan B source validation remains L2, while
  Plan C has now supplied the separate production evidence. The only promoted release is
  `a5fa1e0a0a224969669d7e6ad79a9415b69f2ba4646b6e2bbca9030ff3d460f3` and
  the consumed promotion packet is
  `83d5ebeaf2345bc78495ed99064d34dcb4f23d09d2c8eda5274110f50a510570`.
  Remote 18339 candidate smoke, CAS cutover, healthy UID-101/read-only/zero-mount
  production runtime, HTTPS, 13 routes, 20 security 404s and 26/26 public browser
  pages passed. Production pointer is `reddit_voc_release_20260715_70a917e5bdf0`;
  the L4 acceptance receipt SHA is
  `b5fcd6821de7f4047b1deb9bee6bd60c3d81bcaa6380fc2d8e8912f0a5a76ade`.
  Collector, LibreTranslate, shared Nginx, cron, database/report state and other
  Docker environments were preserved. Registry and four-export completion remain
  deferred; `latest_collection_integrated=true` and
  `latest_collection_fully_hydrated=false` remain explicit.
- On 2026-07-15, Plan A Batch A2 passed the independent identity/ledger gate.
  The only consumable bundle is `ledgers-a2h` with manifest SHA
  `bcc1ac74a770af733ca08f724705da543d2589cccbd2878de92f446007f87639`;
  its r2 validation receipt SHA is
  `5700b8e40d698f3041d226e85a8115a0cc01349014cdb26114eae4ea36bbc913`.
  Four ledgers contain 5,928/1,573/18,746/4,116 rows, classify 233 rejected
  posts, 2,155 rejected comments, 35 invalid report occurrences and 18 pending
  lineage identities, and admit 3,605 net-new comments but zero net-new posts.
  `unaccounted_total=0` coexists with 1,179 open coverage items and 35
  nonretryable failures. A2g and the preliminary `ledger-validation-a2h`
  receipt are superseded and must never be selected by directory scan. This is
  the historical A2 checkpoint now superseded by the final Plan A closure above;
  production remains unchanged.
- On 2026-07-15, the owner approved the controlled candidate-closure direction
  for the next insights-site version. The written umbrella design is
  `docs/superpowers/specs/2026-07-15-reddit-voc-candidate-closure-ui-governance-design.md`.
  It separates identity net-new from existing-entity upgrades, requires four
  typed detail ledgers plus an externally hashed reconciliation ledger, removes
  normal-state warning glyphs without deleting coverage facts, and splits
  artifact-build provenance from site-deployment status. The owner has now
  approved the written specification. Implementation is split into Plan A
  `docs/superpowers/plans/2026-07-15-reddit-voc-candidate-closure-data.md`,
  Plan B `docs/superpowers/plans/2026-07-15-reddit-voc-ui-governance.md`, and
  Plan C `docs/superpowers/plans/2026-07-15-reddit-voc-candidate-automation.md`.
  At that historical checkpoint, Plan A had started. Its two-point L3 production
  read-only quiescence check at
  `2026-07-15T08:21:00Z/08:21:11Z` passed with stable collector/translation/
  insights containers, database stat/SHA, current pointer, shared Nginx, cron and
  zero one-shot/report-network/lock holders. This is read-only evidence only;
  source capture/freeze and all fusion remain in progress. Provider calls,
  persistent remote writes, production DB writes, scheduling and deployment remain
  unstarted and unauthorized under the new design.
- On 2026-07-15 at `07:29:59Z`, exact promotion packet
  `7d429a8354be451b90f04e7609845e4b49a350256d7c48ee5cfd5b64eda64f11`
  was consumed to promote RC3 release
  `9e0d23131824c9d5e195ef9e0950d62e1c89893a40bafa1ec72c53fab330d650`.
  Production pointer is `reddit_voc_release_20260715_a900e6ce7b63`; the site is
  public without login and is accepted as
  `production_accepted_with_explicit_coverage_debt`. Remote candidate smoke,
  healthy read-only UID-101 zero-mount runtime, public HTTPS, 13 routes at desktop
  and mobile, all six current/archive daily-weekly-monthly states, A/B/C story
  contracts, synthetic avatars, cases `38+12+0`, collector link, CSV and DOCX all
  passed. The L4 acceptance receipt SHA-256 is
  `deee7ec9b827d73a902b359f4e11caaec77e0c039973582b4dc075f0a3b787cc`.
  Collector and LibreTranslate IDs/restart counts, shared Nginx SHA and cron SHA
  remained unchanged; there was no collector, TLS, DNS, database, schedule or
  other-Docker modification. Automatic candidate generation is still not
  implemented or enabled, and production promotion remains manually authorized.
- Before that promotion, the task2600-task2603 increment was frozen and fused into
  a separate RC3 candidate. The immutable input freeze
  is `reddit_voc_incremental_freeze_20260715_task2600_2603_rc3` with SHA-256
  `44c2b85be53b11e92a818267a4afa75e521d1fcee5024840c2c3be775e8d93f4`.
  Relative to the production V2 public projection, RC3 adds 23 posts and 139
  linked comments; 137 of those comments enter VOC metrics. Candidate totals are
  1,322 posts, 12,986 stored comments, 12,976 linked comments and 10 quarantined
  comments. The event-time increment is historical: posts fall in 2025-09 and
  2026-02, while three associated comments fall in 2026-03. Current daily,
  weekly and monthly report-index counts therefore do not change. The only
  visible historical Momcozy revision is the 2026-02 comment observation count
  `27 → 28` and negative-evidence share `11.11% → 10.71%`; direction claims remain
  unsupported. The increment creates zero governed product bindings, so the
  existing 708 Momcozy bindings, 633 bound records and 205 exact-SPU bindings
  stay unchanged; evidence-persona assignments increase `233 → 234`.
- RC3 release `reddit_voc_release_20260715_a900e6ce7b63` first validated as
  `candidate_validated_with_explicit_debt`, then passed controlled production
  promotion and acceptance. The frontend/container
  release SHA is
  `9e0d23131824c9d5e195ef9e0950d62e1c89893a40bafa1ec72c53fab330d650`;
  its local linux/amd64 image tar, non-root UID 101 contract, 55/55 dist files and
  four-layer release pointer were verified offline before any remote action. The
  same bytes then passed remote candidate smoke and production browser E2E. RC3
  still has 348 partial threads, 367 outstanding cursors, 339
  outstanding page continuations and 18 lineage gaps, so
  production has `latest_collection_integrated=true`,
  `latest_collection_fully_hydrated=false`, and
  `completion_claim_supported=false`. The full gate intentionally records
  `evidence_grade=L2-fixture-or-dry-run`; that candidate receipt is not relabeled
  as production acceptance. Production evidence is separately L4.
  Its `browser_e2e_evaluated=false` field is intentionally scoped to that gate;
  a separate immutable browser receipt reran the exact candidate dist across
  13 routes at desktop/mobile and passed 26/26 with no external requests.
  Promotion packet SHA-256
  `7d429a8354be451b90f04e7609845e4b49a350256d7c48ee5cfd5b64eda64f11`
  binds the freeze, candidate receipt, browser receipt, release manifest,
  SHA lists, transfer TGZ and linux/amd64 image tar.
  Verification includes 98 Python tests plus 9 subtests, 135/135 frontend tests,
  new incremental validators with Pyright 0 errors, and a reproducible notebook
  plus portable executive report whose validation/package/browser verification
  all passed. This promotion performed the authorized insights-only remote write
  and deploy; no schedule change, provider call, database write or live send
  occurred. Automatic incremental work must first stop at a candidate registry;
  each future production promotion remains an exact packet-SHA owner-authorized step.
- Historical production checkpoint: on 2026-07-15 at `05:53:48Z`, the public
  insights site was upgraded to immutable
  release `f7a4c67a904a71b2fd204765921da92b762b2cd6b47dc2fcecc5bd576224cf5e`.
  Its dynamic pointer selects Base/Insights/Reports/Personas V2. Base contains
  1,299 posts, 12,847 stored comments, 12,837 linked comments and 10 quarantined
  comments; 12,688 comments enter VOC metrics. The public story is Momcozy risk
  governance with product category/product-family/exact-SPU analysis, competitor
  context, daily/weekly/monthly comparisons and two synthetic-avatar content
  evidence cohorts with 233 assignments. The same immutable dist passed local
  desktop/mobile 26-route DOM/network E2E, public-data allowlist audit and all
  135 frontend tests. Production container/HTTP/current-pointer checks passed;
  the collector and LibreTranslate stayed healthy with restart count 0, and
  Nginx/cron hashes did not change. Direct production Playwright was not obtained:
  local macOS killed Chrome at launch for memory pressure, before navigation;
  do not relabel that attempt as browser acceptance. Task2600+ was excluded from
  that V2 release; RC3 later superseded this production checkpoint and obtained
  direct production Playwright acceptance.
- The historical production V2 identity reconciliation superseded `+13`, `887` and other
  earlier waterlines at that checkpoint. Against the old 221-post site baseline,
  V2 global known is 1,317 and V2 net-new is 1,096. V2 semantic/materialized/
  discovery-only counts are 1,133/369/860; 842 discovery-only identities were
  hydrated and 18 non-V2-lineage identities remain excluded. Coverage debt is
  explicit and this is a governed time-point snapshot, not Reddit exhaustion.
  RC3 now supersedes that identity inventory in production: global known 1,340,
  net-new 1,119, semantic/materialized/discovery-only
  1,156/369/883 and the same 18 lineage gaps.
- Historical 2026-07-14 evidence-persona checkpoint (superseded by the V2
  production release above): the approved evidence-persona design and implementation plan are
  `docs/superpowers/specs/2026-07-14-reddit-voc-evidence-personas-design.md` and
  `docs/superpowers/plans/2026-07-14-reddit-voc-evidence-personas.md`. Scheme A is
  locally implemented. The four held-tag predicates evaluated 243 candidates as
  `20 confirmed / 92 needs_review / 131 rejected`; all four tags remain held
  (`0 promoted`) because the independent-sample Wilson/sample gates were not met,
  so no Insights/reports v2 was created. The versioned persona dataset
  `reddit_voc_personas_20260714_v1` (manifest
  `a06968e0bcb8b6a7b596e61b260665c5153914494cb98bbef7caeb361aa5bf41`)
  contains 2 evidence cohorts and 109 assignments, with manifest-bound local SVG
  avatars visibly labeled as synthetic and not real Reddit users. It is activated
  on `/dashboard/insights`; report UI/data remain on
  `reddit_voc_reports_20260714_v1`. Focused Python contract tests `67/67`, five
  independent validators, frontend `104/104`, lint/build, HTTP and Chromium
  desktop/mobile checks passed after closing three P2
  review gaps: five-SHA persona receipts, full optional tag-repair validation,
  and mandatory explicit review overrides. Latest full Python regression is
  `743 passed / 4 failed`: three persistent historical backfill release-manifest
  hash drifts outside this batch for `backfill_cli.py`, `backfill_seed.py`, and
  `tikhub.py`, plus one full-suite-only fake-host launcher
  `inherited_lock_fd_invalid`; that exact launcher test passed `1/1` in isolation,
  so its root cause remains unconfirmed. This batch did not rewrite the old
  manifest or skip the failures. Exact batch boundary: `production unchanged`, `provider_call=false`,
  `database_write=false`, `live_send=false`, `webhook_send=false`, `deploy=false`,
  `schedule_change=false`, `git_commit=false`, `git_push=false`, `git_merge=false`,
  `independent_human_review=false`.
- Historical 2026-07-14 report checkpoint (superseded by the V2 production
  release above): the approved real daily/weekly/monthly report design and implementation plan are
  `docs/superpowers/specs/2026-07-14-reddit-voc-real-reports-design.md` and
  `docs/superpowers/plans/2026-07-14-reddit-voc-real-reports.md`. Scheme A is now
  locally implemented and browser-validated at `/dashboard/reports` using the
  versioned static dataset `reddit_voc_reports_20260714_v1` (manifest
  `5e121a1c...d0ef`). Current daily/weekly/monthly contain `8/37`, `83/392`, and
  `85/395` posts/VOC comments; archive daily/weekly contain `12/59` and `67/307`;
  archive monthly is an explicit `coverage_gap`, not zero discussion. The route
  intentionally uses `SnapshotReports.tsx + RealReportView.tsx` instead of the
  old side-effectful `Dashboard.tsx`, while retaining the three-tab report UI,
  card hierarchy, colors and export interaction. Only promoted tags
  `L0-GEN-075` and `L0-GEN-103` are consumed; 8 held tags are excluded and
  `consumer_card` remains reference-only, not a persona. Python tests and three
  validators, frontend `91/91`, lint, build, HTTP smoke, and Chromium desktop/
  mobile checks passed; console was clean and network traffic was static GET
  only. Exact boundary: `production unchanged`, `provider_call=false`,
  `database_write=false`, `live_send=false`, `webhook_send=false`, `deploy=false`,
  `schedule_change=false`, `git_commit=false`.
- The approved consolidated DeepSeek daily-report translation design is
  `docs/superpowers/specs/2026-07-13-deepseek-daily-report-translation-design.md`.
  Its task-by-task implementation plan is
  `docs/superpowers/plans/2026-07-13-deepseek-daily-report-translation.md`.
  Any future daily translation implementation must read it before editing the
  report pipeline. The approved direction is report-only prepared artifacts,
  `deepseek-v4-flash`, Chinese-first display, full English source in
  HTML/CSV/XLSX and Reddit links, fail-closed quality gates, and a narrow release
  that does not restart or reload other backends. The core prepare/translate/
  validate/render/frozen-send implementation is locally verified at the L1
  mock/fixture and fake-host layer: the protected-placeholder repair passed
  focused `62/62`; the latest exclusive split full validation passed Python
  3.12 unittest `654/654` plus the separately executed pytest-only module `3/3`.
  Provider-free runtime smoke `passed` with `database_write=local-test-only`.
  The fixed host launcher now hard-blocks
  `send` as `dingtalk_disabled_by_owner`; its no-argument cron route accepts
  only one exact one-run `prepare_only` schedule permit. Owner-authorized L2 has
  now executed three times and all attempts failed closed before semantic validation
  on `protected_entity_changed`. The semantic-fix replacement used request
  `deepseek-l2-semanticfix-replacement-20260714-175924`, release
  `eec615b6...e29d4` and copied DB `b4151728...c92d7c`; 9/9 model responses
  succeeded with zero retries, but its manifest marked all 54 items pending
  under one report-level reason. A later local audit proved that this is a
  cascade artifact, not 54 independent failures: 22/54 items had no protected
  value. Its blocked
  manifest is `3c20a6a9...0b8ca9`; that historical checkpoint was 18/100.
  Current exact boundary is `local_core_implementation=L1_verified`,
  `l2_status=blocked`, `provider_call=true`,
  `translation_provider_attempt_made=true`, `semantic_validation_attempt=false`,
  `live_send=false`, `production unchanged`.
  Host Task 11 now has a local candidate for release/import-closure verification,
  exact container inspection, gate/permit recovery, fake-host
  `bootstrap|activate|rollback|recover-prepared-state|commit-prepared|commit-blocked`,
  read-only `capture-host` facts and strict L4/L5/L6 terminal comparison. This is
  not production evidence: no live host capture, Docker/network action, launcher
  switch, cron change or L5 prepare was executed. The isolated key was installed
  and used only through the redacted stdin/no-log path; its content was not
  emitted. The latest permit pair is terminal `blocked`, gates are all-off,
  runtime is cleaned and no prepared report/L3 package exists.
  A local post-block repair aggregates attributed item failures,
  preserves pending status for unvalidated items, and permits only case
  normalization of noncanonical model matches while still rejecting model
  identity changes. Candidate release `861a88d8...a5f54`, manifest
  `193035f2...4174`, validation `9f8f0961...0668` and request packet
  `13f576a3...80a5` were exact-verified, then explicitly authorized and executed
  once. All 9 translation responses succeeded with zero retry, but automatic
  checks returned 4 blocked items plus 50 pending items. Later read-only input
  diagnosis proved `protected_entity_changed` was a generic row-level reason:
  all 4 items have number categories, while only 2 also have a model category.
  Semantic validation did not run. Blocked manifest is
  `6f3ecb2b...2da4d`; sanitized terminal evidence is `106c2904...eb784`.
  Cumulative DeepSeek use is 27/100 with 73 remaining.
  The subsequent local-only protected-placeholder repair masks every maximal
  protected span with a collision-safe occurrence marker before Provider input,
  requires exact one-for-one marker return, restores original bytes locally,
  and then retains the existing entity/number/semantic gates. Provider-free
  copied-input proof passed 9 posts / 9 bundles / 54 items, 157 markers across
  32 items, zero residual protected values, zero namespace collision and exact
  byte round-trip. New release `bc51d736...340e4`, release manifest
  `e4edef8f...9d92`, validation `a6be9cc3...43f2` and request packet
  `7f76571b...3002` was exact-verified and then approved once. The runner
  stopped before Provider transport with `runtime_env_required_value_missing`;
  no Provider attempt or budget consumption occurred, and both permits are now
  terminal `blocked`. A new runtime-fix candidate adds the five required
  non-secret base fields while keeping webhook values blank and gates off.
  Its validation is `e066dd14...54daa2` and replacement packet
  `f1f9b99d...ce066`; request
  `deepseek-l2-protected-placeholder-runtimefix-20260714-211414` was explicitly
  approved and executed exactly once. That runner stopped before Provider
  transport with `runtime_env_required_name_missing`, because the immutable
  materializer also requires the dynamic names it overwrites (run/attempt/
  artifact IDs, report roots, provider-attempt root and config root). Attempt
  `attempt-20260714T133104260742Z-d970fb46d50debfe` exists only as a
  pre-Provider binding; no request or budget consumption occurred. Both new
  permits are terminal `blocked`, gates are all-off, the materialized env and
  runtime root are absent, and no Provider process remains. Therefore
  `host_release_ready=false`, `deploy_executed=false`,
  `cron_changed=false`, and `service_restarted=false`; do not route the current
  08:00 production job to this candidate. A follow-up local full-field runtime
  candidate now contains the 5 base values plus all 18 names the immutable
  materializer overwrites. Static parser/replacement round-trip passed with
  blank webhooks and all gates off. New Request
  `deepseek-l2-protected-placeholder-runtimefix-fields-20260714-225341` was
  explicitly approved and executed exactly once with packet SHA
  `355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb`,
  validation SHA `b54b283079d380d83d9e418f71baa66c1c810fd7ec82e4ae598f070fb800240c`,
  runtime SHA `8aeb1ae50f2d2a7040630b3957b4d379dc796c5c2382aab8a72591685eaaf0c6`,
  and cap 73. The shadow completed 9 translation + 9 semantic-validation
  requests with 54/54 accepted items and all five semantic verdicts true;
  live sends are false, gates are restored all-off, runtime is absent, and
  production is unchanged. Cumulative use is 45/100, with 55 remaining. L3
  review and all later layers remain separately unauthorized.
- On 2026-07-15, the owner supplied the mode-600 local RSA key `DDDD.pem` and
  authorized one L4 report-only bootstrap for `ubuntu@101.34.52.232`. The
  release was staged and passed remote import verification, but bootstrap
  stopped at `cron_file_invalid` because the standard `/etc/cron.d` file is
  `root:root` while the current reader requires caller ownership. No current
  pointer, launcher, cron bytes, service, report network, Provider or DingTalk
  send changed; the permit is terminal `blocked`. A new release and exact L4
  authorization are required after a narrow root-owned-cron contract repair.
- On 2026-07-15, the narrow repair was completed locally: caller ownership
  remains the default for host files, while only fixed cron reads allow UID 0
  with mode/SHA checks intact. Report ops passed `30/30`, release/import `7/7`,
  related report/translation/DeepSeek/DingTalk tests `130/130`, and shell/
  compile checks passed. New local-only release SHA is
  `d6c97382d12bf861663b767b2592ae884c75df08e30bb6767ac4a5c01cf5f61c`, manifest
  SHA `ec21502990fee9a3638d4803e7c7e638f7943b191a3d05b7d87972f0f77a21d5`,
  launcher SHA `1448eafc8aa669b0aab8f870b03a251824d5b43b7f718d2ca5b9ea924aa91d8e`.
  No new remote action occurred; fresh exact L4 authorization is pending and
  the old blocked permit cannot be reused.
- The fresh authorization `reddit-voc-l4-bootstrap-20260715-004545` was then
  used once. Remote release/import verification passed, but the host launcher
  passed relative `python3` to strict `verify-imports`, causing
  `release_import_verification_failed` / `report_smoke_failed`. Recovery
  restored `current=absent`, the legacy launcher and unchanged cron, removed
  the empty report network and freeze, and left the site app restart count at
  `0`; Provider/DingTalk remained false. The permit is terminal `blocked`.
  Next repair must resolve the host Python executable to an absolute path,
  produce a new release and obtain fresh exact L4 authorization.
- The follow-up local repair resolved non-absolute `REDDIT_VOC_HOST_PYTHON_BIN`
  with `type -P` before `verify-imports`; the relative-`python3` smoke regression
  passed. Targeted control/launcher/release tests passed `45/45`, related
  report/translation/DeepSeek/DingTalk tests `122/122`, and local import closure
  remained `19` modules with `repository_fallback=false`. New local-only release
  SHA is `463a9e17ee8e181741b0a4fd223cb9ba2e3b7e08bd9eea7032d133390f4ac5f9`,
  manifest SHA `3b023951d9808727f9fbc6b715c040303b2383be6217af51455137104d91850f`,
  launcher SHA `cc0340f50b3e2f9b7ae48679a998e15264c42289ed2a686ee873599aacf1025d`.
  No new remote action occurred; fresh exact L4 authorization is pending.
- The next exact L4 bootstrap `reddit-voc-l4-bootstrap-20260715-011053` reached
  report smoke but stopped at `report_smoke_failed` because the admin process
  held the daily-report lock while the launcher tried to acquire it again
  (`lock_busy`). Recovery left `current=absent`, the legacy launcher and cron
  unchanged, report network/freeze absent and service restart count `0`; the
  permit is terminal `blocked`, with no Provider/DingTalk call.
- Local repair now passes the held lock descriptor to authorized smoke via
  `pass_fds` and `REDDIT_VOC_INHERITED_LOCK_FD`; the launcher validates exact
  owner/mode/inode/device/held-lock and rejects non-smoke use. Targeted
  control/launcher/release `46/46`, related suites `122/122`, import closure
  `19`, `repository_fallback=false`. New local candidate release
  `3594a09e0fce3f311a2708a6e77a1c24937d5919c3f0080b3d2377aab72e8aa4`, manifest
  `227acfd5c44a08477c7ad98ace5a80c1abc5c85c19c4d2ea1f8a8743deedd370`,
  launcher `ed32f3708ac1bdec446cdf7fc3d53d5f9931062311958f31777b5da592072424`;
  fresh exact L4 authorization is required.
- The approved Momcozy historical backfill lane uses run ID
  `backfill_momcozy_20250101_20260711` and Beijing natural days 2025-01-01
  through 2026-07-11 inclusive. Tasks 1-13 are complete through the staging
  contract-probe layer: Task 11 froze
  the reviewed seed baseline, comment cursor contract, and exact release
  manifest; Task 12 completed local seed, byte-identical replay, seed-scope
  validation, upload-sidecar cleanup, and stable-snapshot revalidation; Task 13
  transferred only reviewed assets and used 2/4 authorized TikHub attempts.
- Historical seed was independently computed twice from the 55 source payloads:
  `55/48 imported/7 outside/0 excluded/0 duplicate/0 parse error`,
  `48 threads/1,894 comments/1,942 analyses`, coverage `45/3/0`.
  `source_inventory_sha256=af39a40c8ed657f440f9db6595d5f4e8e4a26164f43ffa78373215b40b3e881b`;
  `known_partial_post_ids_sha256=1664b77cb94992959a0dc638d25580aad41aa65e8665462490c78d5220532769`.
- Historical Task 13/14 executed release manifest:
  `config/backfill/momcozy-backfill-release-manifest-20260711.json`, SHA-256
  `471dc848cdadff544a8e7009e044ca2cdba03e2add81f741d0d37b4dd0fb949e`.
  The Task 18 zero-page-checkpoint candidate later executed by Task 19 at the
  same fixed path has SHA-256
  `c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`;
  the historical Task 16 candidate used by Task 17 was
  `0663168b890cbd858068548eb3b43ee70345e01854090f42ae0baf91ac9fe0ba`;
  the earlier Task 14A transferred candidate was
  `ec5548c6606e587ae8d9d18809ae643553a03306a44ef2371867a64659a52253`.
  Task 20 locally verified the hashes now stored at that fixed path: canonical
  reviewed files `22/22`, full suite `445/445`, independent review with no
  P0/P1, and manifest SHA
  `347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94`.
  This SHA is not retroactive Task 14 authorization.
  Task 12 DB SHA-256 is
  `f8cfa0727be667ae2f9c6d8b89372251cb50db08b53bd370cf22b380ce082c43`;
  acceptance SHA-256 is
  `f6060cd81136010b6716b32760f2c50404e388bd774662b4d8dac5fd9ae91076`;
  stable 58-file inventory SHA-256 is
  `4149f5663936fca0cab78f28140d9f94af76a36c408c7cb3d86ea557eb6bd12d`.
  Task 13 probe report SHA-256 is
  `75abc643a745ac0a63c2e65d7c0bcda4167981594980b2c664448a1bb206e2bc`;
  it is `ready`, with 2 succeeded attempts, 2 pages and 9 candidates. Task 14
  option B was later authorized and reached cumulative request count `670`, all
  succeeded, but the immutable collect result is `partial/budget_exhausted`:
  the first dynamic lane used all 670 pages, 29 lanes used zero pages, and 238
  candidates remain `budget_deferred`. Replay failed closed on
  `discovery_occurrence_mismatch`, so no replay DB, acceptance report or merge
  plan exists. The lane remains `staging_only`, `production unchanged`,
  `provider_call=true`, `provider_attempt_made=true`, `actor_run=false`,
  `live_send=false`; Task 15 remains unauthorized. The local replay repair is
  independently approved with backfill `261/261` and full-suite `344/344`.
  Its manifest-SHA-versioned bundle was later transferred and used for exactly
  one authorized network-disabled staging replay, which still failed closed on
  `discovery_occurrence_mismatch`. A read-only diagnostic found a second
  historical invalid-row shape: raw parsing produced a post ID while the frozen
  source occurrence stored null identity/time fields. Task 16 local tracing
  later showed that canonical JSON key sorting can exchange same-page raw
  ordinals between collection and replay; the prior "second persistence shape"
  interpretation was therefore downgraded to an ordinal-level observation.
  Collection now parses the exact archived bytes and replay requires an exact
  page contract multiset before reconstructing source order. Local evidence is
  backfill `263/263`, full suite `346/346`, manifest `22/22`, independent review
  `APPROVED`. Task 17 transferred the exact 23-file candidate and ran one
  permanent-guarded `--network none` replay. Occurrence reconciliation passed,
  but replay failed closed on `discovery_checkpoint_mismatch`: 30 checkpoint
  lanes exist while only one has artifacts, and the other 29 are legitimate
  page-zero `partial/budget_exhausted` lanes. No replay DB, acceptance report or
  merge plan was published; source DB/raw archive, Provider count and production
  remained unchanged. No retry is authorized. Task 18 now replays only the
  exact configured page-zero budget-exhausted checkpoint shape and keeps every
  artifact-only, unconfigured, positive-page and tampered state fail-closed.
  Focused `5/5`, validation `56/56`, offline full-suite `351/351`, exact
  manifest `22/22` and two independent reviews are green. The Task 18 SHA is
  `c6d289329443a92ed59c5849fa9fbfe15afc854df709497351c1b7003fd9b2dc`.
  Task 19 transferred that exact SHA-versioned bundle and executed its one
  authorized network-disabled staging replay. It returned
  `complete/replay_complete`, proved equivalent fingerprints and published
  replay DB SHA
  `3504190ab2b80ad1a003da27574455802f4184499eeaa7d458a6b771c3a8c638`.
  This proves deterministic replay, not complete historical coverage; formal
  full validation was not run, Task 14 remains unaccepted and Task 15 remains
  unauthorized. Task 20 is `local_verified` for budget-extension,
  hydration-resume, bounded round-robin discovery and strict offline discovery
  reindex machinery. Task 21 then transferred the exact manifest SHA
  `347c6ede...9d94` bundle and consumed its one authorized network-none staging
  reindex. It failed closed on `strict_discovery_schema_unknown`: no target DB
  was published, while all postflight invariants passed and source/raw/production
  remained unchanged. The staging failure report SHA is
  `9de8ca1170a9479d269fc2f6ab2421513b0cc0a01a52d530658d4e07a8ee1a62`.
  A read-only scan found `670` legacy discovery pages: the `635` empty pages
  passed, while the `35` non-empty pages initially exposed reviewed
  telemetry/Crosspost shapes. Task 21R repaired those wrappers locally, but its
  authorized real-corpus gate then failed closed on exactly two
  `SearchCrosspost.post.crosspostRoot={"post": ...}` lineage wrappers; no
  staging or guard was created. Task 21S accepted only that exact lineage
  wrapper and passed the serialized full suite `454/454`. Its separately
  approved manifest
  `44935d6a1cacdfa6e6a5694cc9178a850f40ec770737531c13243fa00a1906e9`
  exact-passed the original-corpus gate: `670/670`, wrapper `241/2`, recognized
  `243`, eligible/outside/invalid `238/5/0`, zero payload mismatch and exact
  candidate/provenance parity. One permanent-guarded `--network none` staging
  reindex returned `complete/reindex_complete` and published target DB SHA
  `2046e908dd29389fa56189184a20c17dfc53c41e7932e7781250c38a3370e3d9`.
  Fresh postflight passed `14/14` invariants and `9/9` success checks;
  source/raw/production, Provider ledger and delivery state remained unchanged.
  The original corpus is legitimately UID-1000 owned; root ownership/mode is
  required only for the frozen staging and evidence files. No subagent or
  independent reviewer was used per owner instruction. Task 22 Provider
  continuation remains unauthorized and historical coverage is still
  incomplete.
- Task 22A now has a local canonical authorization candidate at
  `.superpowers/sdd/task-22-budget-extension-authorization-packet.json`, SHA
  `6fbec55efdd506fbfcb2376f6bbb47bbca5e7d9ede914caf7542ca6e004a106f`.
  It binds the Task 21S target DB SHA, current `670/670` Provider ledger,
  discovery ceiling `699`, hydration reserve `779`, cumulative maximum `1478`,
  all `30` ordered lane ceilings and subreddit sweep. Related regression passed
  `106/106`; the serialized full suite exited `0` with `454` discovered tests.
  This is `ready_for_owner_authorization`, not approval: no SSH, remote transfer,
  Provider call, database write, production merge, Git push or DingTalk occurred.
- The owner subsequently authorized Task 22A, but remote read-only preflight
  rejected it before transfer or Provider execution: the first lane was still
  `partial/budget_exhausted` at page `670`, while the packet had no forward room
  (`670 -> 670`). Exact current code reproduced
  `budget_extension_checkpoint_state_mismatch`. Task 22C candidate SHA
  `4b969be4af4abf343e0dac093f4c8465ef867981009b1a5180787f318f3da24c`
  corrects the first lane to `670 -> 671` and binds discovery/reserve/total
  `700/789/1489`; it passed an ephemeral network-none read-only check against
  the exact remote source and related regression `106/106`, but is not
  authorized. No persistent remote write, Provider call or production change
  occurred. See `.superpowers/sdd/task-22b-remote-preflight-report.md`.
  BaiduNetdisk synchronization was observed
  historically, paused, and its 48 generated sidecars were removed before
  independent stable-snapshot approval.
- Task 22C was later explicitly authorized and executed once on isolated
  staging. It added `32/32` successful Provider attempts (`670 -> 702`) and
  stopped `partial/candidate_failures`: real subredditV3 and terminal-comments
  payloads were archived but rejected by the then-current strict contracts.
  Source and production stayed unchanged; live send stayed false. See
  `.superpowers/sdd/task-22c-remote-execution-report.md`.
- Task 23 packet
  `ab5386e7d2022dd1a354569bd5fa0abfadcd741549902d4cae53b90d8f17daa1`,
  manifest `edc6ec9b44871d9a93e9a77ca2fdaf3f91a7ede2e282d48bd3f6d1bdc91e9c51`
  and bundle `de66baf3c76f9a69289feb43045de9c3cf7b3f4ed1dc5dc06f9fc6b89664a01e`
  were explicitly authorized and exact-installed into fresh SHA paths. The
  current complete-runtime suite passed `549/549`; remote read-only preflight
  and a network-none contract audit passed before one guarded collect. The
  Provider ledger advanced `670 -> 702` with `32/32` new succeeded attempts,
  but collect stopped `partial/candidate_failures`. Postflight passed `26/26`
  invariants; Task 21S source/raw and production remained unchanged, staging DB
  SHA is `f53ddf6f7ebac2bd88b05954b0f452cf1ccbacd182c83c79266daefd102ab5cb`
  and raw is `757` files at tree SHA
  `8ffcc30d1b3cd95e7757032b1d19623222b49eb23368f131a721731c0cd5339e`.
  Offline diagnosis found `14/15` subreddit lanes still rejected because every
  nonempty edge carries a strict `crosspostCells` typename mirror and auxiliary
  main cells; the comments response parsed eight comments plus one `more` but
  had `hasNextPage=true` without `endCursor`. All `252` selected candidates were
  therefore marked `comments_schema_drift`. The permanent Task 23 guard is
  consumed; no retry is authorized. See
  `.superpowers/sdd/task-23-remote-execution-report.md`.
- Task 24 is locally verified. Exact live subreddit mirrors/cells,
  `unresolved_more` comment preservation, per-candidate failure isolation,
  atomic archive recovery and existing-budget resume authorization passed the
  complete runtime suite `613/613`. Manifest SHA is
  `dbaf6186d45bd5a52e08177dd60ffa00f72b7e5f4f2661a38a3acd4dee6181ad`,
  bundle SHA is
  `28eb1847ba9250ab1839cd6ca43d6416fc9eeba29d5e29bb3341a20c2c18e034`,
  and Task 25 offline-only packet SHA is
  `8821d64a927e5c0d83a774dbab0301cfee6bf394101dac45067cd5683cd011f5`.
  Task 25 was explicitly authorized, exact-passed preflight/admission and
  consumed one permanent-guarded network-none recovery. It returned exit `1`,
  `failed/strict_discovery_page_chain_invalid`, result SHA
  `10aded9bcc0ec01f91c5759e13d1f97577cfbdf12cdedcdb5d4abfe99334ad7e`,
  and published no target DB. Failure postflight passed `21/21`: source DB/raw,
  Provider `702/1200` and production remained unchanged; Provider attempt,
  database write and live send are false. Read-only diagnosis proved all 14
  schema-drift lanes have a sequential extra page, but their checkpoint request
  counts `686-689,691-700` do not equal final manifest count `702`; the current
  recovery rule incorrectly requires equality. Task 25's guard is consumed.
  Task 26 then completed the exact-authorized local-only repair: per-request
  succeeded-attempt/run-ID/endpoint binding and failure-aware postflight passed
  focused `38/38`, related `407/407` and complete-runtime `634/634`. Manifest
  SHA is `d375b127...b38d17`, deterministic bundle SHA is
  `a265dc1f...dadfed`, and Task 27 packet SHA is
  `66f666a2...01c6b3`; local review passed `19/19`. Task 27 then completed one
  authorized network-none recovery into target DB `56d74951...8570a4`; final
  postflight passed all invariants, source/raw/production stayed unchanged and
  Provider stayed `702/1200`. The target still has 258 pending candidates and
  seven missing batch members at that checkpoint, so Provider continuation was
  not yet authorized at that time; historical coverage remained incomplete.
  See
  `.superpowers/sdd/task-25-remote-recovery-report.md` and
  `.superpowers/sdd/task-26-per-request-recovery-contract-report.md` and
  `.superpowers/sdd/task-27-remote-recovery-report.md`. Task 28 candidate packet
  SHA is `5b0ff5af...4cd63`; refreshed release manifest is
  `214577e5...b47136f`, deterministic bundle is `cf5ad3d2...c73a09c`, and
  CLI resume packet is `031e4d96...d5002d`. The authorized continuation
  reached `969/1200` successful Provider requests and stopped at
  `candidate_failures`; target DB SHA is `8baa6613...c29f2f`, production
  remained unchanged, and historical coverage is incomplete.

- No Reddit OAuth.
- DingTalk webhook was supplied in chat and treated as secret; do not persist URL/token in repo artifacts.
- DingTalk live-send code path is gated.
- Runtime env now exists outside the repo at `/home/ubuntu/.reddit-voc/secrets/reddit-voc-live.env` with mode `600`; masked validation showed required TikHub and DingTalk variables present.
- Authorized TikHub live collection has executed for run `daily_collect_20260708_0700`; window is `2026-07-06T23:00:00+00:00` to `2026-07-07T23:00:00+00:00`, matching Beijing time 2026-07-07 07:00 to 2026-07-08 07:00.
- Latest verified collection status is `partial`: `discovered_posts=77`, `window_posts=25`, `relevant_posts=7`, `ingested_threads=7`, `ingested_comments=20`, `analysis_items=27`, coverage `full=6`, `partial=1`.
- Authorized DingTalk daily report live send has executed for run `daily_collect_20260708_0700`; send result `status=sent`, `http_status=200`, `required_keyword_present=true`, `live_send=true`.
- Public artifact links are enabled under `/artifacts/` for DingTalk delivery; `https://reddit.brand.lute-tlz-dddd.top/` and `/api/health` are now served directly by the Reddit VOC app without the shared portal auth gate.
- Production now runs private Docker sidecar `reddit_voc_libretranslate` on `reddit_voc_site_net`; repo-external runtime env sets `REDDIT_VOC_TRANSLATION_MODE=libretranslate` and `LIBRETRANSLATE_BASE_URL=http://reddit_voc_libretranslate:5000`.
- LibreTranslate smoke on a copied production DB for run `daily_collect_20260708_0700` returned `translation_status=translated`, `provider_call=true`, `live_send=false`, `row_count=6`, `comment_count=29`.
- Dedicated Reddit Chrome profile exists outside repo at `~/.reddit-voc/chrome-profile`; Reddit login still requires manual verification and is not proven by file checks.
- Explicit CDP smoke is supported through `--browser-cdp-url`; a repo-external automation profile reached DevTools on `http://127.0.0.1:9333`, but Reddit `.json` still returned a login-required body until manual Reddit login is completed in that profile.
- CodeGraph initialized.
- Python MVP exists under `src/reddit_voc`.
- Tests run with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
- Website deployed on Tencent Cloud: `https://reddit.brand.lute-tlz-dddd.top/`; container `reddit_voc_site_app`, server path `/opt/reddit-voc-site`, port `127.0.0.1:18337`.
- Actual server cron is deployed as two-stage under `CRON_TZ=Asia/Shanghai`: `0 7 * * *` collect-only and `0 8 * * *` report/DingTalk delivery for the same `daily_collect_<YYYYMMDD>_0700` run ID.
- Authorized manual full-cycle live test has executed for run `manual_full_push_20260709_155252`; window is `2026-07-08T07:52:52+00:00` to `2026-07-09T07:52:52+00:00`, matching Beijing time `2026-07-08 15:52:52` to `2026-07-09 15:52:52`.
- Latest manual collection status is `partial`: `discovered_posts=105`, `window_posts=36`, `relevant_posts=12`, `ingested_threads=12`, `ingested_comments=59`, `analysis_items=71`, coverage `full=8`, `partial=4`.
- Latest manual DingTalk live send for `manual_full_push_20260709_155252` returned `status=sent`, `http_status=200`, `required_keyword_present=true`, `provider_call=true`, `live_send=true`.
- Latest manual report delivery used LibreTranslate with `translation_status=translated`; strict DingTalk/detail visibility showed `row_count=4`, `comment_count=16`, and all visible rows had `Momcozy/momcozy` in post body or comments.
- Public artifact URLs for the latest manual run returned HTTP 200 for HTML, XLSX, CSV, and `insight-report-screenshot.png`; screenshot file validated as PNG `1440 x 4703`.
- Server health note after the manual run: root disk usage is about `81%`; swap was fully used during preflight, so resource pressure remains an operational risk.
- 2026-07-09 report template update deployed to Tencent Cloud: DingTalk/HTML VOC blocks now display original Reddit body/comment text for user voice instead of translated Chinese, keep raw subreddit names, add `---` separators between post blocks, and render post images in DingTalk Markdown when media exists.
- Post-deploy dry-run on `manual_full_push_20260709_155252` returned `return_code=0`, `live_send=false`, `translation_mode=disabled`, `row_count=4`, `comment_count=16`; generated markdown had separators and original English user voice, and the latest HTML/XLSX/CSV/screenshot artifact URLs returned HTTP 200. The current visible real-data rows had no media files, so image rendering was covered by tests and deployed source markers rather than real-sample media.
- 2026-07-09 final production template update: DingTalk VOC blocks keep `用户声音` as original Reddit post text, render `原文摘要` from Chinese translation or Chinese fallback summary, and append per-comment translations in parentheses after each original comment, e.g. `- 评论 N original text (中文翻译：...)`.
- Latest authorized full-cycle live test after the final template update: run `manual_full_push_20260709_164307`, window `2026-07-08T08:43:07+00:00` to `2026-07-09T08:43:07+00:00` (Beijing `2026-07-08 16:43:07` to `2026-07-09 16:43:07`), `collect_rc=0`, `report_rc=0`, collector status `partial`, `discovered_posts=104`, `window_posts=34`, `relevant_posts=11`, `ingested_threads=11`, `ingested_comments=51`, `analysis_items=62`, coverage `full=8`, `partial=3`.
- Latest live DingTalk send for `manual_full_push_20260709_164307` returned `status=sent`, `http_status=200`, `required_keyword_present=true`, `live_send=true`; report summary showed `translation_mode=libretranslate`, `translation_status=translated`, `row_count=4`, `comment_count=18`, and generated Markdown contained 18 `(中文翻译：...)` comment translations with no fallback.
- Public endpoint verification after reverse-proxy repair: `https://reddit.brand.lute-tlz-dddd.top/api/health` returned HTTP 200; latest HTML/XLSX/CSV/screenshot artifact URLs for `manual_full_push_20260709_164307` returned HTTP 200.
- Production reverse-proxy repair on 2026-07-09: `ai_video_nginx` had been restarting because `auth_gate.conf` was referenced but not mounted; `/opt/ai-video/deploy/lighthouse/docker-compose.prod.yml` was backed up and given a read-only `./auth_gate.conf:/etc/nginx/auth_gate.conf:ro` mount, and the Reddit VOC nginx block was updated to remove `include /etc/nginx/auth_gate.conf;`. Local `scripts/deploy_webapp_tencent.sh` was updated so future Reddit VOC deployments do not reintroduce the auth gate include.

Boundaries:

- Keep website deployment separate from real Reddit collection, TikHub provider calls, and DingTalk live send.
- Do not execute additional provider calls or live sends unless repo-external runtime env remains present and explicit gate variables are set.
- Stop on login wall, CAPTCHA, provider-call need without env, live-send need without env, or secret exposure risk.

## 2026-07-14 — held 标签 v2 证据扩展

- 新增 `reddit_semantic_predicates_20260714_v2`，只修复否定词、受控产品上下文、
  Momcozy 相邻句对比和第一人称配件意图；v1 policy 与 v1 repair manifest 未变。
- development evidence 绑定 v1 repair manifest，并排除 92 条已阅读 needs-review、
  12 条 v1 review 和 80 条 v1 challenge；去重排除 152 条。
- v2 assignments 为 `46 confirmed / 65 needs_review / 132 rejected`，但冻结规则后
  四标签的未见 confirmed 都为 0；不得把开发样本重复作为独立验证。
- v2 manifest SHA 为
  `dc8a7518c24af6a0722ebe39c8fc5159cf7904745b66b74c88ec9392fc73ec42`，独立 validator
  `passed`；相关数据链测试 `92 passed`。全仓为 `759 passed / 3 failed`，失败是本批
  未触碰的历史 backfill release manifest 三个 SHA 漂移。
- 最终 `completed_no_new_promotions`、`0 promoted / 4 held`；未生成
  Insights/reports/persona v2，日报/周报/月报 v1 和 UI 未修改。
- 后续若继续，必须取得新的版本化 Reddit 实体；优先路径是经用户单独授权的腾讯生产
  只读快照/导出。本批 `production unchanged`、`provider_call=false`、
  `database_write=false`、`live_send=false`、`deploy=false`。

## 2026-07-18 — V3 retry-003 本地 dist 与浏览器验收断点

- 当前四数据集指针为 `reddit_voc_release_20260718_v3_retry_003`；Base/Insights/Reports/Personas
  分别绑定 `reddit_voc_site_snapshot_20260718_v3_retry_002`、
  `reddit_voc_insights_20260716_v3_fe25d97f07ae`、
  `reddit_voc_reports_20260716_v3_fe25d97f07ae`、
  `reddit_voc_personas_20260716_candidate_a4`。最新采集合并已接入，但仍有关系/水合债务，
  因此 `latest_collection_integrated=true`、`latest_collection_fully_hydrated=false`。
- A8 同 dist 浏览器验收发现洞察页缺少 `public-validation-receipt.json`。根因是前端已经精确
  allowlist 当前 insights manifest `e92d8b4e...be2f`，但 `audit_insights_dist.py` 的 sidecar
  allowlist 仍只登记旧 manifest，`--prepare-dist` 因而删除当前合法 sidecar。现已将三组已审
  manifest/sidecar bytes/SHA 改成精确映射，并新增“当前版本保留、未审版本拒绝”回归测试；
  不允许 wildcard。
- 修复后 A9 dist 两次 public projection audit 通过，最终 76 个文件；预容器 release SHA 为
  `0153aa28ee2da205f3f60ae0eea2717125d1415d53d219e13b61aba57631c082`。同一 dist 的
  13 路由 × desktop/mobile 浏览器验收通过，回执 SHA 为
  `5febc618339e8a197e1bbfa2304b58f7c22e36cc8a751a1ef4dbeed3c87fe28c`。
- 前端门禁为 40 个文件、195 项测试通过。新增 reports public validation sidecar 合同后，修复
  `test_frontend_source_v3_contract.py` 的测试夹具，使 insights 与 reports 均复制各自公开回执；
  V3 source/sidecar/release/E2E 专项 Python 回归现为 70 项通过。lint exit 0，保留 7 条既有
  Fast Refresh warning；typecheck/build 通过。
- 全量 Python 回归在夹具修复前运行 1,332 项，结果为 9 failures、21 errors；其中本次范围内的
  4 个 frontend source sidecar 失败/错误已由上述 70 项专项回归验证修复。其余失败主要属于既有
  backfill release bundle SHA/schema 漂移和 daily report/import closure 债务；本轮未改写或跳过这些
  测试，也未在夹具修复后声称全量套件已转绿。
- linux/amd64 image tar、容器 smoke 与 candidate registry 尚未完成。两次 candidate-container
  构建均在锁定 Nginx 基础镜像元数据阶段失败。本次恢复复核进一步确认：腾讯云 Docker mirror
  域名无法解析，Docker Hub registry TCP 443 超时，本地也没有锁定 Nginx 基础镜像缓存；这属于
  外部镜像链路，不是应用/数据失败。未安装额外工具、未修改 Docker mirror、未替换基础镜像，也
  未进行无状态变化的盲目重试。不得把预容器 manifest 或浏览器回执称为可部署容器候选。
- 本轮未 SSH、未部署、未启动或切换生产容器，未修改采集器、cron、共享 Nginx、TLS、DNS 或
  其他 Docker 环境。恢复点：镜像链路恢复后，以 A9 inputs 重新生成 immutable image tar，随后
  运行本地容器 smoke、export/security evidence、candidate registry 独立校验；生产仍需新的精确授权。

## 2026-07-18 — A10 native V3 candidate registry 与 promotion packet 本地闭环

- `scripts/build_reddit_candidate.py` 已支持 `--native-v3` 注册路径：不再强制 legacy Plan A /
  source-manifest-v1，可直接校验 frontend-source-manifest-v2、source receipt、source stage receipt、
  Base/Insights/Reports/Personas 四数据集 public manifest/receipt、release manifest 与 build receipt。
- 新增单测覆盖 native V3 final receipt v2 与无 Plan A 注册路径；`python3 -m unittest
  tests.test_build_reddit_candidate` 结果为 7/7 通过。
- A10 缺失的 personas validation receipt 已在
  `tmp/reddit-voc-v3/reddit_add_data_20260715_v1/personas-validation-a4/receipt.json` 召回，SHA
  `784e8b1cfd35368f3407a0cc2d22281c93afa89e6e288ac890f581dda8830816`。
- A10 source stage receipt 通过本地 deterministic source-stage materializer 从重组的 exact source root
  生成：`tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/frontend-source-stage-a10/443d69deb91ffa2f03480068555d114a991835b799c0fbc5018ff5788eb31f75/frontend/source-stage-receipt.json`，
  SHA `d2a8cc0500dee850255fe29407eb28e1e3658d2e4c423c86d3c7337a1579ced5`。重组 root 仅用于本地证据恢复，
  274/274 文件匹配 A10 source manifest。
- A10 native final UI receipt 已生成：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/candidate-final-a10-native/candidate-ui-validation-receipt.json`，
  SHA `326ebee4cf5a2a52b4699df24bb74ecc9dc87747afb904cc069796ece7a8f55f`。
- A10 已本地 append-only 注册到 candidate registry：candidate id
  `88e8c0ad4791b310037bdc6025b62f8b7e81ef85e38968b979f8db6ff64fa940`，entry SHA
  `424decf3a0ef02f27e2d1cf83bbdc97109508e0ca658cafbeeb41d3368557417`，release SHA
  `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`，`deploy=false`、
  `remote_write=false`、`production_unchanged=true`。
- 新 production baseline 通过只读 SSH 探针生成：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/production-baseline-receipt-a10-native.json`，
  SHA `4994a1d97bf861cbe176f14357fc4534a5bb1d4c579bb924628d9d5ba864c337`，observed_at
  `2026-07-18T13:21:56Z`，current production release
  `9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`。
- A10 native promotion packet 已生成并通过本地 validator：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/promotion-packet-a10-native.json`，
  packet SHA `cb6971652ce392f4dbc44a42e97895ad0bd6c878ab64e2b37027a27a9e67af3d`；validator 结果
  `status=passed`、`artifact_count=20`、`promotion_authorized=false`、`consumed=false`、
  `deploy=false`、`remote_write=false`。
- 本轮只生成本地候选、只读 baseline 与未授权 promotion packet；未执行 permit、consume、SSH 上传、
  Docker load、18339 candidate、生产切换或回滚，未修改采集器、cron、shared Nginx、TLS、DNS 或其他 Docker 环境。

## 2026-07-18 — A10 native V3 受控生产提升完成

- Owner 授权上一轮明确对象：promotion packet
  `cb6971652ce392f4dbc44a42e97895ad0bd6c878ab64e2b37027a27a9e67af3d` 与 release
  `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`。
- 本地 permit 已生成：`tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/promotion-permit-a10-native.json`，
  SHA `8e55efc7b44e33bb61f58cebe2fcd27c64cc55f19d4b9647735a041928e1b811`，authorization id
  `owner-a10-native-20260718-1336`。
- 本地 execution contract 已生成：`tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/promotion-execution-contract-a10-native.json`，
  SHA `f66a4d2384ae09fdb7f1722c75e91c73c2083922d266a72f02c927e0cf78ea80`。远端 runner 为
  `scripts/remote_install_insights_release.sh`，SHA `dfed1c82918075fcbd244d770238b3e922111c114d55361f3f5dc4556505ac29`。
- 真实生产切换通过 `scripts/deploy_insights_tencent.sh` 调用既有三参数远端 runner 完成；runner 输出：
  release `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`，image id
  `sha256:a25815a6bf9e4029941c1525add6b9f67ffae3f28f90b63e8c4216ecd637dfb6`，container health `healthy`，
  evidence `/opt/reddit-voc-insights-site/evidence/container-deploy-20260718T134141Z-6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2.txt`。
- Canonical remote promotion receipt 已本地生成并上传至
  `/opt/reddit-voc-insights-site/evidence/promotion-20260718T134141Z-6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2.json`，
  SHA `dbab71ee93144b48b88d8c2afedc2d8af02ac0ad3b13be815be9e665524f6373`。
- 公网 HTTP acceptance 通过：13/13 routes 200、8/8 public artifacts 200、20/20 sensitive paths 404，
  TLS 与 release/data pointer 均通过；receipt
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/public-http-acceptance-a10-native.json`，
  SHA `7a9c0c33bedbe50dc70f92bfeb262bbdffe963ad0d3ee3f734483752f21c80f0`。
- Production acceptance 已封存：`tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/production-acceptance-a10-native.json`，
  SHA `38de81a08d26b67b5f617d2f9b81bd61e9bb4cd90a2c2f3fc5af4980672220ad`，status `passed`。
  注：本地无 Playwright runtime，因此 `public_browser` 字段采用 HTTP route smoke 证据补足，未声称真实浏览器渲染。
- Promotion consumption 已封存并复验通过：
  `tmp/reddit-voc-v3/candidate-orchestration/v3-governed-retry-002/promotion-consumption-a10-native.json`，
  SHA `379a4fb0e02fbdd3996cf51e3f406879ad94d7cbae123ee26b9fdd549b8c5199`。
- 最终远程只读复核：`/opt/reddit-voc-insights-site/current` 指向
  `releases/6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`，internal `/release.json`
  返回同一 release，`/healthz=ok`，`reddit_voc_insights_web=healthy`，采集后台 `/api/health status=ok`。
- 本次只切换 Reddit VOC 洞察站。采集器、cron、shared Nginx、TLS、DNS、数据库、Provider、live send、
  调度和其他 Docker 环境未修改；`latest_collection_fully_hydrated=false` 与 6,943 unresolved-parent 结构债务继续保留。
