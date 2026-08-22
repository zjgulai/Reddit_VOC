---
title: Reddit VOC Execution TODO
doc_type: execution_todo
status: draft
created: 2026-07-07
updated: 2026-07-19
owner: codex
project: Reddit_VOC
production_boundary: authorized_live_operational_partial
provider_call: true
live_send: true
---

# Reddit VOC Execution TODO

## 2026-07-19 Insights Candidate Refresh

- [x] 合并中心数据并校正守恒口径：3,535 帖、27,316 存量评论、20,363 已关联、6,953 待父帖关联、0 隔离。
- [x] 重建 Base、VOC、治理标签、指标、日报/周报/月报、正式洞察和用户画像公开投影。
- [x] 将实际 UI 指向 `reddit_voc_release_20260719_v3_center_refresh_003`，不回退 Mock。
- [x] 日报只展示 6 个可计算指标；周报/月报各展示 11 个可计算指标；不可计算指标不展示。
- [x] 最近季度用户画像按当前 Base 帖子日期重新关联：Momcozy 画像赋值 369，品类语境赋值 2,712。
- [x] 前端 195 tests passed / 46 skipped；lint/typecheck/build passed；13 路由桌面端/移动端同源 E2E passed。
- [x] 案例广场存量内容和三个业务视图保持不变。
- [x] 基于最新中心重建品牌健康、最近季度洞察，并验证案例方法辅助投影；案例存量内容未改，4 帖 + 16 评论全部可在最新中心解析。
- [x] 使用项目级临时 BuildKit builder 拉取固定 Nginx digest，未修改 Docker Desktop 全局镜像配置；正式 linux/amd64 容器、container smoke、13 路由桌面/移动端 E2E、安全探针和 CSV/PDF/PPTX/DOCX 导出验收均通过，临时 builder/image/container/network 已清理。
- [x] 本地候选已注册并通过独立 registry validator：candidate `648313d45b26513910656109dc66435fa9cf3f0cd7509ab692f3717b40fd5bc7`，release `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b`。
- [x] 停在生产授权边界：未生成 promotion packet，未 SSH、传输、部署或切换生产指针。
- [x] 修复全仓测试基础设施：`pytest` 已进入锁定开发依赖，项目通过 Hatchling editable install，pytest 同时加载 `src` 与仓库根；日报 release import closure、标签快照子进程、高位继承锁 FD 和 schema-drift 测试均修复。
- [x] 全仓除历史回溯冻结契约外通过：1,588 tests + 817 subtests；六个变更相关模块通过 132 tests + 96 subtests。
- [x] 清理当前候选链中 24 个未被 registry/文档/测试引用、可确定性重建的中间目录，释放约 677 MB；历史生产验收证据、当前候选和冻结数据均保留。清理后 registry 仍为 `passed`，tree SHA 保持 `99f02455427d66b990d67e41c8cc4cdfb80810fab702514b5136a9acefacebf0`。
- [x] 完成 2026-07-11 回溯采集 release manifest 的独立专项复审。5 个冻结版本均已按原 SHA 恢复并与现行代码逐字节对比，差异来自后续 v2 admission/seed、递归 seed、run-scoped raw capture、24 小时重叠抓取和原始证据落盘演进，不是旧 manifest 损坏。
- [x] 保持旧 manifest 不变，将其 23 个 reviewed files 绑定到不可变历史源码归档 `config/backfill/archive/momcozy-backfill-reviewed-files-20260711.tar.gz`；禁止用当前源码 SHA 机械重签旧 release。当前采集代码若要部署，必须另建新 release attestation。
- [x] 历史契约修复后全仓通过：1,596 tests + 840 subtests；backfill/storage/TikHub 扩大集通过 441 tests + 538 subtests。
- [x] Owner 已明确授权为 candidate `648313d45b26513910656109dc66435fa9cf3f0cd7509ab692f3717b40fd5bc7` / release `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b` 生成一次性 promotion packet。
- [x] 生产只读基线于 `2026-07-19T10:04:31Z` 通过：当前生产 release `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2`，所需容器 healthy，候选端口为空，数据库/容器清单/cron/Nginx 稳定且未发生远端写入。
- [x] Promotion packet `cbf43b1a8b9709d6fc985f1288c90b4bcb9fe723b55b597e0905a27d47527fe9` 已生成并通过独立 validator，绑定 20 项精确 artifact，`promotion_authorized=false`、`consumed=false`、`deploy=false`，有效期至 `2026-07-19T12:06:25Z`。
- [x] Promotion packet 构建、validator 与 execution boundary 专项测试 23/23 通过。
- [x] Owner 已在 packet 有效期内同时精确授权 packet SHA `cbf43b1a8b9709d6fc985f1288c90b4bcb9fe723b55b597e0905a27d47527fe9` 与 release SHA `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b`；一次性 permit SHA `78c06e8c1e198ac0b2b274c76497edb0ee1e5b5f90b76dc8b2b3b6516b59372d` 验证通过。
- [x] 仅洞察站受控生产提升完成：`reddit_voc_insights_web` 已切换至 release `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b`，image id `sha256:bba3d6989659f8b6ddebab288b773576358ab477217fe9c2e12d257bdff9f045`，health `healthy`。
- [x] 公网验收通过：13/13 routes 200、8/8 public artifacts 200、20/20 sensitive paths 404，TLS、release marker 与数据指针精确匹配。
- [x] 生产 acceptance SHA `fed962a99d27653b44001229e6ab42c6ca2d8f90ff2317023f91cddb36d561bf` 与 consumption SHA `73321a2383460c2ca39966a92ab64a7fbfb8452d470ca14bb1fd81060ae1cfe0` 均独立验证通过；permit 已在证据层一次性消费。
- [x] 切换前后采集器与翻译容器 ID/health/restart count 不变，数据库、cron、共享 Nginx、TLS、DNS、其他 Docker、Provider、live send 与调度均未修改；回滚 release `6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2` 校验和通过。

Boundary: this refresh is local-only. Production, collector, cron, shared Nginx,
TLS, DNS, database, provider calls, live sends and other Docker applications are
unchanged.

### 2026-07-19 Six-Dimension Adversarial Review

Conclusion: the exact local insights candidate passes its own release chain;
the whole repository does not yet pass the global test gate. Confidence is high
for the same-dist candidate and medium for repository-wide health.

- [x] Requirements completeness: latest Base, brand health, rolling-quarter
  insights, personas, reports, cases, 13 UI routes and four download formats are
  bound into the candidate. Production promotion remains intentionally outside
  this batch.
- [x] Logic correctness: post VOC and linked comment-context VOC remain distinct;
  comparison direction is supported by the Owner's 100% historical collection
  attestation; unavailable/provisional states remain explicit. The quarter
  negative rate is calculated on 1,522 classified Momcozy VOCs, not all 1,752
  Momcozy VOCs.
- [x] Boundary and edge cases: 6,953 unresolved-parent comments remain stored and
  excluded from comment-context analysis rather than dropped; casebook external
  evidence remains non-canonical; no login, author linkage or private paths are
  exposed.
- [x] Code quality: native V3 candidate entries are now validated using their
  exact native artifact set; legacy registry validation remains covered. The
  temporary BuildKit mirror is project-local and did not alter Docker Desktop
  global state.
- [x] Test coverage infrastructure: focused candidate checks, frontend gate,
  browser/container and exports pass; missing-`pytest`, project import,
  daily-report release-closure, tag snapshot subprocess, schema-drift and
  inherited-lock failures are repaired.
- [x] Historical attestation: the 2026-07-11 release manifest remains immutable
  and now validates all 23 reviewed file bytes against its dedicated source
  archive. Current collector code is intentionally not represented as that old
  release and needs a new attestation before a future collector deployment.
- [x] Actual runtime: isolated immutable container, readonly-rootfs/security
  contract, 13-route desktop/mobile browser acceptance and CSV/PDF/PPTX/DOCX
  downloads passed against the exact release bytes.

Retained debt, ordered by operational impact:

1. P2 analysis coverage: 230 Momcozy quarter VOCs lack a governed sentiment;
   brand health remains provisional even though all four displayed dimensions
   have values.
2. P2 relationship debt: 6,953 stored comments lack a resolvable parent post in
   the latest center. This is relationship debt, not collection completeness.
3. P2 lineage clarity: formal reports/insights retain a `20260716` dataset label
   while their metrics lineage and coverage window end on 2026-07-18. The bytes
   are correctly bound, but the label can confuse operators.
4. P3 dormant auxiliary: the dist still carries the older unpointed V2 business
   activation projection (3,494 posts / 27,158 comments). Current release
   consumers use the V3 pointer and latest auxiliaries; remove or rebuild this
   dormant asset in a later cleanup instead of representing it as current.

## 2026-07-08 Current Live Status

- [x] 腾讯云网站已部署到 `https://reddit.brand.lute-tlz-dddd.top/`，根页面继续走统一登录网关。
- [x] `/artifacts/` 已开放只读公网访问，用于钉钉 HTML、XLSX、CSV、PNG 链接。
- [x] 服务器 cron 目标：北京时间每天 07:00 采集，08:00 报告。
- [x] repo 外部 runtime env 已就绪，权限 `600`，TikHub/DingTalk 必要变量通过脱敏校验。
- [x] TikHub 动态搜索、详情、评论接口已按官方 GET 合约修复并部署。
- [x] 手动 07:00-style 真实采集已跑通：`daily_collect_20260708_0700`，7 帖、20 评论、27 分析项，`provider_call=true`。
- [x] 手动 report-style 报告已生成并发送钉钉：`status=sent`、`http_status=200`、`live_send=true`。
- [x] 钉钉消息包含 HTML 报告、XLSX、CSV、PNG 链接；四个公网 artifact URL 均返回 HTTP 200。
- [ ] 接入真实中文翻译 provider；当前自由文本翻译状态为 `provider_required`，不是完整机器翻译。
- [ ] 处理 TikHub subreddit feed HTTP 400；当前依赖 dynamic search 覆盖，运行状态为 `partial`。
- [ ] 观察下一次自然 07:00/08:00 cron，确认不只是手动验收通过。

## Phase 0: Planning and Contracts

- [x] Create persistent planning files under `.kiro/plan/`.
- [x] Create product plan under `docs/`.
- [x] Create execution TODO under `tasks/`.
- [x] Add `docs/reddit-voc-data-contract-20260707.md`.
- [x] Add `.env.example` with names only, no secrets.
- [x] Add `config/subreddits.yaml`.
- [x] Add `config/keywords.yaml`.

Acceptance:

- Product plan and TODO have frontmatter.
- Documents state `production unchanged`, `provider_call=false`, and `live_send=false`.

## Phase 1: Local Browser Read-Only Smoke

- [x] Check existing browser-harness availability at `/Users/pray/.local/bin/browser-harness`.
- [x] Check Agent-Reach Reddit backend status.
- [x] Draft `docs/reddit-voc-readonly-smoke-runbook-20260707.md`.
- [x] Fix or stabilize browser-harness daemon health if `--doctor` still fails.
- [ ] Install or enable Agent-Reach OpenCLI Reddit backend if absent.
- [x] Create a dedicated Chrome profile for Reddit VOC read-only collection.
- [ ] Manually log in to Reddit in that profile.
- [x] Open a known public Reddit post URL in browser.
- [x] Open the same URL with `.json` appended in browser context.
- [x] Open a target category subreddit listing with `.json`.
- [x] Save sanitized smoke artifacts under `tmp/smoke/`.
- [x] Record whether comments are `full`, `partial`, or `failed`.
- [x] Probe RSS fallback separately as `discovery_only`.

Acceptance:

- Browser smoke artifact includes method, URL, HTTP/browser status, parsed post ID, parsed comment count, and coverage grade.
- No cookie, token, password, or webhook value is stored.

## Phase 2: Data Contract and Fixtures

- [x] Define `runs`, `posts`, `comments`, `matches`, `analysis_items`, and `delivery_attempts` schema.
- [x] Define JSONL export format for posts and comments.
- [x] Add sanitized fixture for one Reddit `.json` thread.
- [x] Add sanitized fixture for RSS discovery.
- [x] Add sanitized fixture for partial comment tree with `more` marker.

Acceptance:

- Fixtures can run offline.
- Schema includes evidence fields and coverage grade.

## Phase 3: Collector MVP

- [x] Implement `BrowserJsonAdapter`.
- [ ] Implement `AgentReachAdapter` wrapper.
- [x] Implement `RssDiscoveryAdapter`.
- [ ] Implement `TikHubAdapter` as gated fallback with dry-run default.
- [ ] Implement `DomFallbackAdapter` only after browser smoke proves need.
- [x] Implement fixed Asia/Shanghai daily window logic. Current product default is 07:00.
- [x] Implement duplicate prevention by `platform + post_id/comment_id`.
- [ ] Implement rate limit and retry policy.
- [x] Add adapter fixture loop into local SQLite dry-run path.
- [x] Implement browser-harness runner for read-only `.json` capture.
- [x] Ingest one real browser read-only target thread into local SQLite dry-run storage.
- [x] Add blocked/login/CAPTCHA/non-JSON classification before JSON parse.
- [x] Add controlled summary output for JSON error object and invalid JSON-like body.

Acceptance:

- Fixture collector test passes.
- Adapter fixture dry-run can ingest one browser-json-shaped thread into local storage.
- Real browser read-only smoke can ingest at least one target thread into local storage.
- Browser smoke artifact stores summary/hash/counts; selected local SQLite stores parsed rows.
- TikHub adapter cannot call provider unless explicitly enabled.

## Phase 4: Analysis MVP

- [x] Implement keyword matcher with brand, category, competitor, model, pain point dictionaries.
- [x] Add model disambiguation rules for `M5`, `M6`, `M9`, `S9`, `V1`, and `V2`.
- [ ] Implement VADER sentiment.
- [x] Implement topic and pain point classifier.
- [x] Implement severity and confidence scoring.
- [x] Add local rule tests for analysis output.

Acceptance:

- Known positive, negative, neutral, competitor, and false-positive fixtures classify as expected.

## Phase 5: Reports and DingTalk

- [x] Generate fixture Markdown digest.
- [x] Generate posts CSV.
- [x] Generate comments CSV.
- [x] Generate fixture analysis JSON summary.
- [x] Implement DingTalk signed webhook payload builder.
- [x] Default DingTalk mode to dry-run.
- [x] Add delivery preview records.
- [x] Add DingTalk dry-run digest with structured export artifact links.

Acceptance:

- Dry-run produces exact outbound body and signature metadata without sending.
- Live-send path is blocked unless explicit env gate and user authorization exist.

## Phase 6: Local Scheduling

- [x] Prefer `launchd` job over cron for macOS local deployment.
- [x] Add run wrapper script.
- [x] Add log rotation or bounded logs.
- [x] Add missed-run handling policy.
- [x] Add local scheduler dry-run acceptance procedure.

Acceptance:

- Manual run works.
- Scheduled dry-run works once.
- Missed schedule does not silently claim success.

## Phase 7: Operational Hardening

- [x] Add status summary command.
- [x] Add issue summary command.
- [x] Add artifact retention policy.
- [x] Add README runbook.
- [x] Add troubleshooting guide for login expiry, Reddit block page, 429, empty comments, TikHub fallback, and DingTalk delivery issue.

Acceptance:

- Operator can determine whether a day is `success`, `partial`, `empty`, or `failed` from local artifacts.

## Immediate Next Development Step

Continue from local operation hardening to owner-gated runtime activation:

1. Keep launchd install/load behind explicit authorization.
2. Prepare a scheduler install acceptance checklist if owner authorizes it.
3. Keep dedicated Chrome profile/login and real browser daily collection as the next operational hardening path.
4. Keep Agent-Reach OpenCLI, TikHub, and DingTalk live send behind explicit gates.

## Loop 4 TODO: Structured Export, Retry, and Status

- [x] Add read APIs in `VocStore` for exported posts, exported comments, run row lookup, run counts, and coverage summary.
- [x] Add `src/reddit_voc/exporter.py` to write:
  - posts JSONL
  - comments JSONL
  - posts CSV
  - comments CSV
- [x] Add `export-run` CLI command with explicit `--run-id`; default output stays under `outputs/`.
- [x] Add `status-summary` CLI command that returns one JSON object with `success|partial|empty|failed` semantics.
- [x] Add browser runner retry settings:
  - `max_attempts`
  - `retry_delay_seconds`
  - retry only for browser-harness process errors by default
  - stop immediately for `ok`, `login_required`, `captcha`, `blocked`, or valid non-platform JSON handled by CLI summary
- [x] Add tests for export files, status summary, retry behavior, and no live-send/provider-call flags.
- [x] Run acceptance commands:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v`
  - `PYTHONPATH=src python3 -m reddit_voc.cli run-adapter-fixture-loop --database <tmp>/adapter.sqlite3 --output-dir <tmp>/out`
  - `PYTHONPATH=src python3 -m reddit_voc.cli export-run --database <tmp>/adapter.sqlite3 --output-dir <tmp>/out --run-id adapter_fixture_run_20260707`
  - `PYTHONPATH=src python3 -m reddit_voc.cli status-summary --database <tmp>/adapter.sqlite3 --run-id adapter_fixture_run_20260707`
  - `PYTHONPATH=src python3 -m reddit_voc.cli doctor --no-network`
  - project secret scan
  - `codegraph sync . && codegraph status .`

Loop 4 acceptance:

- Export artifacts exist and include non-empty post/comment rows for adapter fixture runs.
- Status summary distinguishes status, counts, coverage grades, provider_call, and live_send.
- Retry behavior is covered by unit tests and does not retry login/CAPTCHA/blocked states.
- No TikHub call, no DingTalk live send, no Reddit write action.

Loop 4 evidence:

- Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> 28 tests OK.
- Acceptance run: `loop4_acceptance_20260707`.
- Export artifacts:
  - `outputs/loop4_acceptance_20260707-posts.jsonl`
  - `outputs/loop4_acceptance_20260707-comments.jsonl`
  - `outputs/loop4_acceptance_20260707-posts.csv`
  - `outputs/loop4_acceptance_20260707-comments.csv`
- Status summary: `partial`, counts raw captures `1`, threads `1`, comments `2`, analysis `3`, coverage `partial=1`.
- `provider_call=false`, `live_send=false`.

## Loop 5 TODO: DingTalk Dry-Run Delivery and Local Operation

- [x] Add `build-dingtalk-dry-run` CLI command:
  - requires `--run-id`
  - regenerates/links structured export artifacts
  - renders Markdown digest with status, counts, coverage, and artifact paths
  - writes exact outbound DingTalk body to `outputs/{run_id}-dingtalk-dry-run.json`
  - writes delivery preview row with `live_send=0`
- [x] Add tests for DingTalk digest artifact links and no live send.
- [x] Add `scripts/run_local_daily_dry_run.sh`:
  - initializes local dirs/schema
  - runs fixture-safe local collector
  - exports JSONL/CSV
  - builds DingTalk dry-run payload
  - writes status summary
  - accepts env overrides for `REDDIT_VOC_RUN_ID`, `REDDIT_VOC_DATABASE_PATH`, `REDDIT_VOC_OUTPUT_DIR`
- [x] Add launchd dry-run plan under `docs/`.
- [x] Add launchd plist template under `config/launchd/` without installing it.
- [x] Run acceptance commands:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v`
  - `scripts/run_local_daily_dry_run.sh` with a deterministic `REDDIT_VOC_RUN_ID`
  - `PYTHONPATH=src python3 -m reddit_voc.cli status-summary --database data/reddit_voc_loop5_acceptance.sqlite3 --run-id loop5_acceptance_20260707`
  - verify outbox contains export artifact paths and `msgtype=markdown`
  - `PYTHONPATH=src python3 -m reddit_voc.cli doctor --no-network`
  - project secret scan
  - `codegraph sync . && codegraph status .`

Loop 5 acceptance:

- DingTalk dry-run outbox exists and references posts/comments JSONL+CSV artifacts.
- Delivery preview row exists with `live_send=0`.
- Wrapper runs end-to-end locally with deterministic run ID.
- Launchd plan/template exists but no scheduler is installed by this loop.
- No TikHub call, no DingTalk live send, no Reddit write action.

Loop 5 evidence:

- Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> 29 tests OK.
- Wrapper run: `REDDIT_VOC_RUN_ID=loop5_acceptance_20260707 REDDIT_VOC_DATABASE_PATH=data/reddit_voc_loop5_acceptance.sqlite3 REDDIT_VOC_OUTPUT_DIR=outputs REDDIT_VOC_LOG_DIR=logs scripts/run_local_daily_dry_run.sh`.
- Status summary: `partial`, raw captures `1`, threads `1`, comments `2`, analysis `3`, delivery previews `1`, coverage `partial=1`.
- DingTalk dry-run outbox: `outputs/loop5_acceptance_20260707-dingtalk-dry-run.json`.
- Outbox includes posts/comments JSONL and CSV artifact paths.
- `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template`: OK.
- `PYTHONPATH=src python3 -m reddit_voc.cli doctor --no-network`: status `ok`, `provider_call=false`, `live_send=false`.
- Secret scan over project docs/config/src/tests/scripts/outputs/tmp: no matches.
- Frontmatter check for README, troubleshooting, launchd plan, and TODO: all true.
- `codegraph sync . && codegraph status .`: 28 files, 330 nodes, 661 edges, index up to date.
- `scheduler_installed=false`.
- `provider_call=false`, `live_send=false`.

## Loop 9 TODO: Dedicated Reddit Chrome Profile Hardening

- [x] Add `src/reddit_voc/browser_profile.py`.
- [x] Add CLI commands:
  - `browser-profile-init`
  - `browser-profile-status`
  - `browser-profile-launch-command`
- [x] Add `scripts/open_reddit_chrome_profile.sh`.
- [x] Add `docs/reddit-voc-browser-profile-runbook-20260707.md`.
- [x] Update `.env.example` with profile path and start URL variables.
- [x] Update README with Reddit Chrome profile runbook section.
- [x] Add tests for:
  - profile path outside workspace
  - profile path inside workspace blocked
  - launch command generation
  - cookie-store existence check without reading cookie contents
  - secret-safe CLI output
- [x] Create default profile directory outside repo:
  - `/Users/pray/.reddit-voc/chrome-profile`
- [x] Open dedicated Chrome profile to Reddit login URL.

Loop 9 acceptance:

- Profile directory exists outside repo.
- Repo does not contain Chrome profile data.
- CLI status does not read cookie contents.
- Launch command uses dedicated `--user-data-dir`.
- Manual Reddit login remains an explicit human step before real read-only browser collection.
- No TikHub provider call, no DingTalk live send, no Reddit write action, no scheduler install.

Loop 9 evidence:

- `PYTHONPATH=src python3 -m unittest tests.test_browser_profile -v`: 5 tests OK.
- `PYTHONPATH=src python3 -m py_compile src/reddit_voc/browser_profile.py src/reddit_voc/cli.py tests/test_browser_profile.py`: exit 0.
- `bash -n scripts/open_reddit_chrome_profile.sh`: exit 0.
- `browser-profile-init`: status `ready_for_manual_login`, profile outside workspace, `provider_call=false`, `live_send=false`, `reddit_write=false`.
- `browser-profile-status` after launch request: `profile_present_login_unverified`, profile outside workspace, cookie store exists, `provider_call=false`, `live_send=false`, `reddit_write=false`.
- `repo_profile_data=absent`.

Loop 9 final verification:

- Full unit suite: 43 tests OK.
- `doctor --no-network`: status `ok`, `provider_call=false`, `live_send=false`.
- Dedicated profile status: `profile_present_login_unverified`; cookie store exists by file presence only.
- Secret scan: no webhook/token matches in repo docs/config/src/tests/scripts/plans.
- Scheduler template lint: OK; scheduler remains uninstalled.
- CodeGraph status: 30 files, 395 nodes, 786 edges, index up to date.

## Loop 10 TODO: CDP-Targeted Browser Smoke Gate

- [x] Prove whether plain `browser-harness` is attached to the dedicated Reddit profile.
- [x] Add remote-debugging launch support to the repo-local Chrome profile script.
- [x] Add `--browser-cdp-url` support to `run-browser-json-smoke`.
- [x] Ensure the smoke runner reloads a named `browser-harness` daemon when a CDP endpoint is supplied.
- [x] Test CDP env propagation, remote-debug launch command, and CLI summary output.
- [x] Run a real local CDP smoke against Reddit `.json`.
- [x] Record the account-state gate without calling TikHub, DingTalk, or scheduler.

Loop 10 acceptance:

- Browser-harness default route is no longer assumed to be the dedicated Reddit profile.
- A repo-external automation profile can expose a DevTools endpoint on `http://127.0.0.1:9333`.
- Standard smoke writes a sanitized summary artifact with `provider_call=false`, `live_send=false`, and `secrets_written=false`.
- Reddit `.json` collection remains gated by manual Reddit login in the CDP-enabled profile.

Loop 10 evidence:

- Default browser-harness manual smoke read a Reddit network-security login wall.
- Attempting to add remote debugging to the already-running `~/.reddit-voc/chrome-profile` did not expose port `9333`.
- Launching `~/.reddit-voc/chrome-automation-profile` with `REDDIT_VOC_CHROME_REMOTE_DEBUG_PORT=9333` exposed Chrome DevTools on `http://127.0.0.1:9333/json/version`.
- `PYTHONPATH=src python3 -m reddit_voc.cli run-browser-json-smoke --database data/reddit_voc_loop10_cdp_smoke.sqlite3 --output-dir outputs --run-id loop10_cdp_profile_smoke_20260707 --url https://www.reddit.com/r/shopify/comments/1umbsm4/shopify_store_traffic_is_100_visitorsday_but/.json --browser-cdp-url http://127.0.0.1:9333 --browser-daemon-name reddit-voc-profile --max-attempts 2 --retry-delay-seconds 0`
  - `browser_status=login_required`
  - `blocked_reason=text_login_wall`
  - artifact `outputs/loop10_cdp_profile_smoke_20260707-browser-json-smoke-summary.json`
  - `provider_call=false`
  - `live_send=false`
  - `secrets_written=false`

Loop 10 final verification:

- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 47 tests OK.
- `PYTHONPATH=src python3 -m py_compile src/reddit_voc/browser_profile.py src/reddit_voc/browser_runner.py src/reddit_voc/cli.py src/reddit_voc/ops.py tests/test_browser_profile.py tests/test_browser_runner.py`: exit 0.
- `status-summary` for `loop10_cdp_profile_smoke_20260707`: `status=failed`, counts all zero, `provider_call=false`, `live_send=false`.
- `issue-summary` for `loop10_cdp_profile_smoke_20260707`: `operational_state=attention`, issue `run_failed`.
- `doctor --no-network`: status `ok`.
- `bash -n scripts/open_reddit_chrome_profile.sh`: exit 0.
- `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template`: OK.
- Secret scan: no webhook/token matches in repo docs/config/src/tests/scripts/plans.
- Repo profile data check: `repo_profile_data=absent`.

## Loop 7 TODO: DingTalk Live-Send Gate

- [x] Treat the provided DingTalk webhook as runtime secret only:
  - do not write URL/token into repo files
  - do not write URL/token into tests
  - do not write URL/token into output artifacts
- [x] Add `send-dingtalk-live` CLI command:
  - requires `--run-id`
  - requires `--authorize-live-send`
  - requires `REDDIT_VOC_ENABLE_DINGTALK_LIVE_SEND=1`
  - reads `DINGTALK_WEBHOOK_URL` only from environment
  - reads optional `DINGTALK_WEBHOOK_SECRET` only from environment
  - supports `--required-keyword LL`
- [x] Add DingTalk keyword injection helper.
- [x] Add HTTP send wrapper with JSON body and response hash.
- [x] Add live delivery record path with `mode=live` and `live_send=1`.
- [x] Add tests:
  - default blocked path does not call send function
  - mocked live send includes keyword `LL`
  - mocked live send records local delivery row
  - command result does not echo webhook token
- [x] Update README and context docs with live-send gate.

Loop 7 acceptance:

- Live-send capability exists but is blocked by default.
- Mocked live-send path passes without real network.
- DingTalk keyword `LL` is present in outgoing mocked message body/title.
- Webhook URL/token is not persisted in repo files or output artifacts.
- No real DingTalk live send executed by this loop.

Loop 7 evidence:

- `PYTHONPATH=src python3 -m unittest tests.test_dingtalk_delivery tests.test_storage_dingtalk -v`: 6 tests OK.
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 36 tests OK.
- `PYTHONPATH=src python3 -m py_compile src/reddit_voc/dingtalk.py src/reddit_voc/cli.py src/reddit_voc/storage.py tests/test_dingtalk_delivery.py tests/test_storage_dingtalk.py`: exit 0.
- `PYTHONPATH=src python3 -m reddit_voc.cli send-dingtalk-live --database data/reddit_voc_loop6_acceptance.sqlite3 --output-dir outputs --run-id loop6_acceptance_20260707 --required-keyword LL`: blocked with `reason=live_send_not_authorized`, `live_send=false`.
- `PYTHONPATH=src python3 -m reddit_voc.cli doctor --no-network`: status `ok`, secret env values empty.
- Secret scan over project docs/config/src/tests/scripts/outputs/tmp/logs: no real DingTalk webhook/token matches.
- Key document check: no real webhook URL or `access_token` string persisted in README, TODO, context pack, or progress file.
- `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template`: OK.
- `codegraph sync . && codegraph status .`: 28 files, 349 nodes, 706 edges, index up to date.
- `provider_call=false`, `live_send=false`, `scheduler_installed=false`.

## Loop 8 TODO: Authorized DingTalk Live Send

- [x] Add sanitized transport error handling before live send.
- [x] Add DingTalk response `errcode` interpretation:
  - `errcode=0` keeps status `sent`
  - non-zero `errcode` marks status `rejected`
- [x] Generate fresh local send run:
  - run ID `dingtalk_live_send_20260707_1851`
  - database `data/dingtalk_live_send_20260707_1851.sqlite3`
  - output dir `outputs`
- [x] Execute authorized DingTalk live send:
  - required keyword `LL`
  - `provider_call=false`
  - `live_send=true`
  - webhook URL/token supplied only as runtime environment variable
- [x] Verify local delivery record:
  - dry-run delivery row exists
  - live delivery row exists
  - live row status `sent`
  - live row `live_send=true`
- [x] Verify status summary reflects delivery-level live send.

Loop 8 acceptance:

- DingTalk live send returned HTTP 200 and status `sent`.
- Message required keyword `LL` was present.
- Status summary for the run reports `live_send=true`.
- Secret scan does not find persisted DingTalk webhook/token.
- No TikHub provider call, no Reddit write action, no scheduler install.

Loop 8 evidence:

- Send run: `dingtalk_live_send_20260707_1851`.
- Live send result:
  - `status=sent`
  - `http_status=200`
  - `response_hash=sha256:3f1f7d2bbe160de9de91cfbe2408088da0d383e1b96041a943cc401e17b6eac2`
  - `message_hash=sha256:582a8237674ed8e9942fa22e14a4b747cd49d0cd2aea02a8673c21426b41f0a0`
  - `required_keyword_present=true`
  - `provider_call=false`
  - `live_send=true`
- Delivery records:
  - `mode=dry_run`, `status=created`, `live_send=false`
  - `mode=live`, `status=sent`, `live_send=true`
- `status-summary`: `partial`, raw captures `1`, threads `1`, comments `2`, analysis `3`, delivery previews `2`, coverage `partial=1`, `provider_call=false`, `live_send=true`.
- Final verification:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 38 tests OK.
  - Secret scan over repo docs/config/src/tests/scripts/outputs/tmp/logs/data: no real DingTalk webhook/token matches.
  - `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template`: OK.
  - scheduler install check: `scheduler_installed=false`.
  - `codegraph sync . && codegraph status .`: 28 files, 358 nodes, 715 edges, index up to date.

## Loop 6 TODO: Operation Governance and Runbooks

- [x] Add `issue-summary` CLI command:
  - requires `--run-id`
  - reports operational state and issue codes
  - keeps `provider_call=false` and `live_send=false`
- [x] Add `missed-run-check` CLI command:
  - computes the expected Asia/Shanghai daily collection window
  - reports matching local run IDs
  - exits non-zero when the expected window has no local run
- [x] Add `prune-artifacts` CLI command:
  - supports dry-run preview by default
  - supports explicit `--apply`
  - keeps newest local files by count
- [x] Update `scripts/run_local_daily_dry_run.sh`:
  - writes `logs/{run_id}.log`
  - writes `outputs/{run_id}-issue-summary.json`
  - writes `outputs/{run_id}-log-retention-summary.json`
  - keeps newest 30 log files by default
- [x] Add root `README.md` runbook.
- [x] Add `docs/reddit-voc-troubleshooting-20260707.md`.
- [x] Update local env template with run/log retention variables.
- [x] Run acceptance commands:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v`
  - `scripts/run_local_daily_dry_run.sh` with deterministic Loop 6 run ID
  - `status-summary`
  - `issue-summary`
  - `missed-run-check`
  - `prune-artifacts`
  - `doctor --no-network`
  - `plutil -lint`
  - project secret scan
  - `codegraph sync . && codegraph status .`

Loop 6 acceptance:

- Issue summary identifies partial coverage without enabling live send.
- Missed-run check can prove the expected Beijing-time collection window is covered by a local run.
- Wrapper writes per-run log and retention summary.
- README and troubleshooting docs exist with frontmatter and boundary tags.
- No TikHub call, no DingTalk live send, no Reddit write action, no scheduler install.

Loop 6 evidence:

- Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests -v` -> 33 tests OK.
- Wrapper run: `REDDIT_VOC_RUN_ID=loop6_acceptance_20260707 REDDIT_VOC_DATABASE_PATH=data/reddit_voc_loop6_acceptance.sqlite3 REDDIT_VOC_OUTPUT_DIR=outputs REDDIT_VOC_LOG_DIR=logs REDDIT_VOC_LOG_KEEP_LAST=30 scripts/run_local_daily_dry_run.sh`.
- Status summary: `partial`, raw captures `1`, threads `1`, comments `2`, analysis `3`, delivery previews `1`, coverage `partial=1`.
- Issue summary: `operational_state=attention`, issue code `partial_coverage`, count `1`.
- Missed-run check at anchor `2026-07-06T20:00:00+00:00`: `status=covered`, matching run `loop6_acceptance_20260707`.
- Retention summary: `status=ok`, `apply=true`.
- Log artifact: `logs/loop6_acceptance_20260707.log`.
- `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template`: OK.
- `scheduler_installed=false`.
- `provider_call=false`, `live_send=false`.

## Loop 9 TODO: Phase 1-6 Daily Collector and Chinese Report Automation

- [x] Phase 1: Add `run-daily-collector` CLI command for Asia/Shanghai rolling 24-hour windows. Current product default is 07:00.
- [x] Phase 2: Add Chinese daily detail report generation:
  - CSV: `{run_id}-daily-detail.csv`
  - Excel: `{run_id}-daily-detail.xlsx`
  - one row per post
  - post title/body Chinese fields
  - all parsed comments merged into `评论整合原文` and `评论整合中文`
- [x] Phase 3: Keep translation provider boundary explicit:
  - `REDDIT_VOC_TRANSLATION_MODE=dry_run`
  - fixture/local glossary text is translated locally
  - unknown text is marked `【待授权翻译】...`
  - provider translation call remains disabled
- [x] Phase 4: Add Chinese insight PNG generation: `{run_id}-insights.png`.
- [x] Phase 5: Add business daily DingTalk dry-run payload: `{run_id}-daily-dingtalk-dry-run.json`.
- [x] Phase 5: Add gated business daily DingTalk live-send command: `send-daily-report-live`.
- [x] Phase 6: Add production-shape local automation wrappers and scheduler templates:
  - `scripts/run_daily_collect.sh`
  - `scripts/run_daily_report.sh`
  - `scripts/run_daily_report_dry_run.sh`
  - `config/launchd/com.reddit-voc.daily-collect.plist.template`
  - `config/launchd/com.reddit-voc.daily-report.plist.template`
- [x] Update README, data contract, env template, and launchd plan.

Loop 9 acceptance:

- Collector path is implemented as local wrapper and launchd template. Current product default is 07:00.
- Report path is implemented as local wrapper and launchd template. Current product default is 08:00.
- Daily insight summary is Chinese and image-based.
- Detail table is CSV/XLSX and contains Chinese post fields plus merged comment cells.
- DingTalk business message is generated as dry-run JSON only.
- DingTalk live-send path exists but is blocked unless explicit runtime gates are enabled.
- No provider translation call, no DingTalk live send, no launchd install/load in this loop.

Loop 9 evidence:

- `PYTHONPATH=src python3 -m py_compile src/reddit_voc/collector.py src/reddit_voc/daily_report.py src/reddit_voc/cli.py tests/test_daily_collector.py tests/test_daily_report.py`: exit 0.
- `bash -n scripts/run_daily_collect.sh scripts/run_daily_report.sh scripts/run_daily_report_dry_run.sh scripts/run_local_daily_dry_run.sh`: exit 0.
- `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template config/launchd/com.reddit-voc.daily-collect.plist.template config/launchd/com.reddit-voc.daily-report.plist.template`: all OK.
- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_daily_collector.py' -v`: 2 tests OK.
- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_daily_report.py' -v`: 4 tests OK.
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 54 tests OK.
- Local fixture acceptance:
  - run ID `phase1_6_acceptance_20260707_v2`
  - database `data/reddit_voc_phase1_6_acceptance_v2.sqlite3`
  - wrapper `scripts/run_local_daily_dry_run.sh`
  - report wrapper `scripts/run_daily_report.sh`
  - `provider_call=false`
  - `live_send=false`
- Generated daily report artifacts:
  - `outputs/phase1_6_acceptance_20260707_v2-daily-detail.xlsx`
  - `outputs/phase1_6_acceptance_20260707_v2-daily-detail.csv`
  - `outputs/phase1_6_acceptance_20260707_v2-insights.png`
  - `outputs/phase1_6_acceptance_20260707_v2-daily-dingtalk-dry-run.json`
  - `outputs/phase1_6_acceptance_20260707_v2-daily-report-summary.json`
- Artifact content checks:
  - CSV rows `1`
  - XLSX sheet `Momcozy Reddit VOC 日报`
  - XLSX rows `2`, columns `20`
  - Chinese title cell `Momcozy M5 在工作时漏奶`
  - merged Chinese comment blocks `2`
  - PNG format `PNG`, size `1400x900`, bytes `77733`
  - DingTalk dry-run JSON contains `LL`, daily detail CSV/XLSX, insight PNG, `provider_call=false`, and `live_send=false`
- Secret scan over repo docs/config/src/tests/scripts/outputs/tmp/logs/data: no real DingTalk webhook/token/provider key pattern found.
- `codegraph sync . && codegraph status .`: 34 files, 526 nodes, 1105 edges, index up to date.
- Git evidence unavailable: `/Users/pray/project/Reddit_VOC` is not a Git repository.

## Loop 10 TODO: TikHub Provider, 07:00/08:00 Timeline, Single HTML Insight Report

- [x] Update product timeline:
  - collection window closes at 07:00 Asia/Shanghai
  - report wrapper runs at 08:00 Asia/Shanghai
  - default run ID shape `daily_collect_<YYYYMMDD>_0700`
- [x] Add TikHub Reddit provider plan:
  - `/api/v1/reddit/app/fetch_subreddit_feed`
  - `/api/v1/reddit/app/fetch_dynamic_search`
  - `/api/v1/reddit/app/fetch_post_details_batch_large`
  - `/api/v1/reddit/app/fetch_post_comments`
- [x] Add `src/reddit_voc/tikhub.py` with runtime-secret-only provider client and collector.
- [x] Add `tikhub-api-plan` CLI command.
- [x] Add `run-tikhub-collector` CLI command:
  - requires `--authorize-provider-call`
  - requires `REDDIT_VOC_ENABLE_TIKHUB=1`
  - requires runtime `TIKHUB_API_KEY`
  - stores `provider_call=true` only when a provider collector run is actually executed
- [x] Update `scripts/run_daily_collect.sh` to use TikHub provider by default.
- [x] Update launchd templates to 07:00 collector and 08:00 report.
- [x] Add single-page HTML insight report:
  - `{run_id}-insight-report.html`
  - full Chinese insight storyline
  - VOC detail table at the bottom
  - CSV/XLSX/PNG kept as auxiliary artifacts
- [x] Update DingTalk daily report payload so HTML report is the primary artifact.
- [x] Block DingTalk live HTML send when `REDDIT_VOC_ARTIFACT_BASE_URL` is missing.
- [x] Update README, data contract, launchd plan, env template, and tests.

Loop 10 acceptance:

- HTML report is generated and contains a complete Chinese storyline plus bottom detail table.
- Daily report DingTalk dry-run references the HTML report first.
- TikHub collector is implemented but does not call provider unless runtime secret and explicit gates are present.
- Live DingTalk report send is implemented but blocks without a reachable artifact base URL.
- No API key, webhook URL, webhook secret, bearer token, or provider secret is persisted in repo artifacts.

Loop 10 evidence:

- Chrome/TikHub marketplace inspection:
  - Chrome extension backend was unavailable in this session.
  - Available browser backend list only exposed Codex In-app Browser, not the user's logged-in Chrome profile.
  - Runtime environment had no `TIKHUB_API_KEY`, no `DINGTALK_WEBHOOK_URL`, no `DINGTALK_WEBHOOK_SECRET`, no `REDDIT_VOC_ARTIFACT_BASE_URL`.
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 59 tests OK.
- `bash -n scripts/run_daily_collect.sh scripts/run_daily_report.sh scripts/run_daily_report_dry_run.sh scripts/run_local_daily_dry_run.sh`: exit 0.
- `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template config/launchd/com.reddit-voc.daily-collect.plist.template config/launchd/com.reddit-voc.daily-report.plist.template`: all OK.
- `PYTHONPATH=src python3 -m reddit_voc.cli tikhub-api-plan`: outputs TikHub endpoint plan with `provider_call=false`, `live_send=false`.
- `PYTHONPATH=src REDDIT_VOC_ENABLE_TIKHUB=1 python3 -m reddit_voc.cli run-tikhub-collector --database data/reddit_voc_tikhub_missing_key.sqlite3 --output-dir outputs --run-id tikhub_missing_key_20260707 --authorize-provider-call`: blocked with `reason=missing_tikhub_api_key_env`, `provider_call=false`.
- Local HTML report acceptance:
  - run ID `html_report_acceptance_20260707`
  - database `data/reddit_voc_html_report_acceptance.sqlite3`
  - `outputs/html_report_acceptance_20260707-insight-report.html` exists, bytes `9021`
  - `outputs/html_report_acceptance_20260707-daily-detail.csv` exists, bytes `1288`
  - `outputs/html_report_acceptance_20260707-daily-detail.xlsx` exists, bytes `6195`
  - `outputs/html_report_acceptance_20260707-insights.png` exists, bytes `77844`
  - `outputs/html_report_acceptance_20260707-daily-dingtalk-dry-run.json` exists, bytes `704`
- HTML content checks:
  - contains `完整中文故事线`
  - contains story sections `1. 今天先看结论` through `5. 建议动作`
  - contains bottom `VOC 明细表`
  - contains Chinese title `Momcozy M5 在工作时漏奶`
  - CSV row count `1`
  - merged Chinese comment blocks `2`
  - XLSX sheet `Momcozy Reddit VOC 日报`, rows `2`, columns `20`
  - PNG format `PNG`, size `1400x900`
  - DingTalk dry-run text contains HTML report, XLSX, `provider_call=false`, and `live_send=false`
- Secret scan over repo docs/config/src/tests/scripts/outputs/tmp/logs/data: no real DingTalk webhook/token/TikHub key/bearer pattern found.
- Frontmatter check for README, launchd plan, data contract, and TODO: all true.
- CodeGraph verification unavailable: `codegraph` not found in current PATH.

## Loop 13 TODO: Reddit VOC Website and Tencent Cloud Deployment

- [x] Read Product Design workflow requirements and confirm the supplied brief:
  - three modules: collection settings, Reddit data dashboard, Chinese sentiment insight.
  - full interactivity for filters, scope switch, detail drawer and report preview.
- [x] Build a read-only website under `webapp/`:
  - `webapp/app.py`
  - `webapp/static/index.html`
  - `webapp/static/styles.css`
  - `webapp/static/app.js`
- [x] Add read-only APIs:
  - `/api/health`
  - `/api/settings`
  - `/api/dashboard?scope=latest|all`
  - `/api/insights?scope=latest|all`
  - `/api/artifacts`
- [x] Add Docker deployment assets:
  - `webapp/Dockerfile`
  - `webapp/docker-compose.yml`
  - `.dockerignore`
  - `scripts/deploy_webapp_tencent.sh`
- [x] Keep SSH key and secrets out of deployment artifacts:
  - exclude `ai_video.pem`
  - exclude `*.pem`
  - exclude real `.env`
  - skip macOS `._*` metadata files.
- [x] Fix stale project default from 04:00 to 07:00 in `pyproject.toml`.
- [x] Update `.env.example` search terms with expanded Momcozy product/category terms.
- [x] Deploy to Tencent Cloud server:
  - remote directory `/opt/reddit-voc-site`
  - container `reddit_voc_site_app`
  - host binding `127.0.0.1:18337->8080`
  - Docker network `reddit_voc_site_net`
  - shared Nginx network `lighthouse_ai_video_net`
- [x] Add Nginx route for `reddit_brand.lute-tlz-dddd.top`:
  - HTTP route works for current underscore domain.
  - HTTPS route exists but trusted certificate is blocked by invalid underscore domain.
- [x] Verify local and public E2E.

Loop 13 evidence:

- Backups before edits:
  - `/Users/pray/.Codex/file-history/Reddit_VOC/20260707-webapp-deploy-223000/pyproject.toml`
  - `/Users/pray/.Codex/file-history/Reddit_VOC/20260707-webapp-deploy-223000/README.md`
  - `/Users/pray/.Codex/file-history/Reddit_VOC/20260707-webapp-deploy-223000/.env.example`
  - `/Users/pray/.Codex/file-history/Reddit_VOC/20260707-webapp-deploy-223000/reddit-voc-execution-todo-20260707.md`
- Local tests:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 65 tests OK.
  - `PYTHONPATH=src:. python3 -m unittest discover -s tests -p 'test_webapp.py' -v`: 3 tests OK.
  - `python3 -m py_compile webapp/app.py`: OK.
- Local browser smoke:
  - `http://127.0.0.1:18765/`
  - dashboard rows `1`
  - drawer title `Momcozy M5 在工作时漏奶`
  - story line `最近一个采集批次共沉淀 1 篇帖子和 2 条解析评论，主讨论社区集中在 r/ExclusivelyPumping。`
  - screenshots in `tmp/webapp-smoke/`.
- Remote server checks:
  - SSH key `ai_video.pem` works.
  - Docker version available on server.
  - `reddit_voc_site_app Up`, port `127.0.0.1:18337->8080/tcp`.
  - `docker exec ai_video_nginx nginx -t`: successful.
  - Nginx marker block present: `BEGIN reddit-voc-site`, `server_name reddit_brand.lute-tlz-dddd.top`.
  - remote `/opt/reddit-voc-site` and container `/app` have `0` macOS `._*` files after cleanup.
- Public HTTP checks:
  - `curl -I http://reddit_brand.lute-tlz-dddd.top/`: HTTP 200.
  - `curl -I http://reddit_brand.lute-tlz-dddd.top/api/health`: HTTP 200.
  - `/api/health`: `sqlite_files=14`, `artifacts=142`.
  - `/api/dashboard?scope=latest`: posts `1`, comments `2`, title `Momcozy M5 在工作时漏奶`.
  - `/api/insights?scope=all`: posts `12`, comments `27`, Chinese story line.
- Public browser smoke:
  - dashboard screenshot `tmp/webapp-smoke/public-dashboard-desktop.png`.
  - insights screenshot `tmp/webapp-smoke/public-insights-desktop.png`.
- HTTPS blocker:
  - `curl -I https://reddit_brand.lute-tlz-dddd.top/` fails certificate validation.
  - Let's Encrypt certbot rejects the identifier because `reddit_brand` contains `_`.
  - A valid HTTPS URL requires a DNS label without underscore, for example `reddit-brand.lute-tlz-dddd.top` pointing to `101.34.52.232`.

## Loop 14 TODO: Valid Domain HTTPS, Server Cron, and Blocked-Safe Runtime Gates

- [x] Replace public domain with valid DNS label:
  - target URL `https://reddit.brand.lute-tlz-dddd.top/`
  - DNS resolves to `101.34.52.232`.
- [x] Update deployment defaults:
  - `scripts/deploy_webapp_tencent.sh`
  - `webapp/static/index.html`
  - server artifact base URL defaults in `scripts/server_daily_collect.sh` and `scripts/server_daily_report.sh`.
- [x] Add server runtime wrappers:
  - `scripts/server_daily_collect.sh`
  - `scripts/server_daily_report.sh`
  - both default to `/home/ubuntu/.reddit-voc/secrets/reddit-voc-live.env`
  - both write blocked JSON instead of silently succeeding when runtime prerequisites are missing.
- [x] Update Docker runtime shape:
  - `PYTHONPATH=/app/src:/app`
  - install `Pillow` and `openpyxl`
  - use mounted server directories for `config/`, `data/`, `outputs/`, `logs/`, `src/`, `scripts/`, `docs/`.
- [x] Fix deployment data preservation:
  - deployment tar excludes `data/` and `outputs/`.
  - remote deployment does not delete `/opt/reddit-voc-site/data` or `/opt/reddit-voc-site/outputs`.
  - Dockerfile creates empty `/app/data`, `/app/outputs`, `/app/logs` instead of copying local historical artifacts into the image.
  - `.dockerignore` excludes `data/` and `outputs/` from Docker build context.
- [x] Install server cron file:
  - `CRON_TZ=Asia/Shanghai`
  - `0 7 * * * ubuntu /opt/reddit-voc-site/scripts/server_daily_collect.sh`
  - `0 8 * * * ubuntu /opt/reddit-voc-site/scripts/server_daily_report.sh`
- [x] Issue valid Let's Encrypt certificate for `reddit.brand.lute-tlz-dddd.top`.
- [x] Keep public app behind existing `auth_gate.conf`.
- [x] Verify no provider call or DingTalk live send happens without runtime env.

Loop 14 evidence:

- Local backups before edits:
  - `/Users/pray/.Codex/file-history/Reddit_VOC/20260707-domain-cron-232900/`
  - `/Users/pray/.Codex/file-history/Reddit_VOC/20260707-docker-pip-mirror-restore/`
  - `/Users/pray/.Codex/file-history/Reddit_VOC/20260707-docs-current-domain-restore/`
- Local verification:
  - `bash -n scripts/deploy_webapp_tencent.sh scripts/server_daily_collect.sh scripts/server_daily_report.sh scripts/run_daily_collect.sh scripts/run_daily_report.sh`: OK.
  - `python3 -m py_compile webapp/app.py`: OK.
  - `PYTHONPATH=src:. python3 -m unittest discover -s tests -v`: 65 tests OK.
- Remote deployment:
  - `scripts/deploy_webapp_tencent.sh`: completed.
  - Docker build uses `https://pypi.tuna.tsinghua.edu.cn/simple` to avoid remote `pip` download hang.
  - Docker build context after final data-preservation deployment is about `10.81kB`.
  - `reddit_voc_site_app Up`, port `127.0.0.1:18337->8080/tcp`.
  - `http://127.0.0.1:18337/api/health`: `status=ok`, `sqlite_files=14`, `artifacts=144`.
  - Docker mounts include `/opt/reddit-voc-site/data -> /app/data`, `/outputs -> /app/outputs`, `/logs -> /app/logs`, `/src -> /app/src`, `/scripts -> /app/scripts`, `/docs -> /app/docs`, `/config -> /app/config`.
  - Data preservation regression: before redeploy `data=14`, `outputs=144`; after redeploy `data=14`, `outputs=144`.
- HTTPS and Nginx:
  - certificate saved under `/etc/letsencrypt/live/reddit.brand.lute-tlz-dddd.top/`.
  - certificate subject `CN=reddit.brand.lute-tlz-dddd.top`.
  - certificate issuer `Let's Encrypt YE1`.
  - certificate validity `Jul 7 14:41:34 2026 GMT` to `Oct 5 14:41:33 2026 GMT`.
  - `docker exec ai_video_nginx nginx -t`: successful.
  - `curl -I https://reddit.brand.lute-tlz-dddd.top/`: HTTP/2 302 to existing login page.
- Site/API smoke:
  - internal page returns Chinese console HTML with `采集模块`, `数据看板`, `舆情洞察`.
  - `/api/settings` returns `collection_time=07:00`, `collection_window_hours=24`, `report_time=08:00`.
  - `/api/dashboard` returns latest fixture-backed batch.
  - `/api/insights` returns Chinese story line.
- Deployed browser smoke through SSH tunnel:
  - page title `Momcozy Reddit VOC Console`.
  - nav texts `采集模块`, `数据看板`, `舆情洞察`.
  - table rows `1`.
  - insight story text is Chinese.
  - collection form values `07:00`, `24`, `08:00`.
  - artifact placeholder `https://reddit.brand.lute-tlz-dddd.top/artifacts/`.
  - screenshots:
    - `tmp/webapp-smoke/deployed-tunnel-collection.png`
    - `tmp/webapp-smoke/deployed-tunnel-dashboard.png`
    - `tmp/webapp-smoke/deployed-tunnel-insights.png`
- Cron:
  - `/etc/cron.d/reddit-voc-site` contains 07:00 collection and 08:00 report entries under `CRON_TZ=Asia/Shanghai`.
- Blocked-safe runtime:
  - runtime secret directory exists with `700` permission: `/home/ubuntu/.reddit-voc/secrets`.
  - `/opt/reddit-voc-site/scripts/server_daily_collect.sh`: blocked with `reason=missing_runtime_env_file`, `provider_call=false`, `live_send=false`.
  - `/opt/reddit-voc-site/scripts/server_daily_report.sh`: blocked with `reason=missing_daily_database`, `provider_call=false`, `live_send=false`.
  - blocked artifacts are readable through the app artifact route.
- Remaining live activation TODO:
  - create `/home/ubuntu/.reddit-voc/secrets/reddit-voc-live.env` on the server with TikHub and DingTalk secrets.
  - run one manual 07:00-style collection after env is installed.
  - verify `data/reddit_voc_daily.sqlite3` is created with real Reddit rows.
  - run one manual report-style report and confirm DingTalk receives HTML report plus XLSX/CSV detail links.
  - inspect logged cron behavior on the next natural 07:00 and 08:00 Asia/Shanghai windows.

## Loop 12 TODO: Online Actions Plan, Adversarial Audit, HTML Report Review

- [x] Add online action runbook: `docs/reddit-voc-online-actions-runbook-20260707.md`.
- [x] Tell operator how to provide API keys without storing secrets in repo:
  - create `~/.reddit-voc/secrets/reddit-voc-live.env`
  - set `REDDIT_VOC_ENV_FILE=~/.reddit-voc/secrets/reddit-voc-live.env`
  - never paste real key/webhook/secret into repo files.
- [x] Add `scripts/load_runtime_env.sh`.
- [x] Wire `REDDIT_VOC_ENV_FILE` into:
  - `scripts/run_daily_collect.sh`
  - `scripts/run_daily_report.sh`
  - `scripts/run_daily_report_dry_run.sh`
- [x] Add adversarial audit: `docs/reddit-voc-adversarial-audit-20260707.md`.
- [x] Fix artifact URL generation:
  - DingTalk export links now use `base_url/<artifact_filename>`.
  - daily HTML report links now use `base_url/<artifact_filename>`.
  - local absolute paths are not included when `REDDIT_VOC_ARTIFACT_BASE_URL` is set.
- [x] Improve Chinese report style:
  - table headers `社区`, `帖子 ID`, `发帖时间（UTC）`
  - comment meta `评论ID`, `分数`, `层级`
  - HTML report metadata `运行 ID`
  - PNG metadata `运行 ID`, `采集窗口`, `主题前五`, `痛点前五`
  - report palette changed from warm beige to restrained light blue-gray.
- [x] Run local online-action probes without side effects:
  - TikHub probe blocked with `missing_tikhub_api_key_env`
  - DingTalk live-send probe blocked with `missing_dingtalk_webhook_env`
  - `provider_call=false`, `live_send=false`

Loop 12 evidence:

- Fixture report smoke run: `online_audit_html_smoke_20260707`.
- Generated artifacts:
  - `outputs/online_audit_html_smoke_20260707-insight-report.html`
  - `outputs/online_audit_html_smoke_20260707-daily-detail.xlsx`
  - `outputs/online_audit_html_smoke_20260707-daily-detail.csv`
  - `outputs/online_audit_html_smoke_20260707-insights.png`
  - `outputs/online_audit_html_smoke_20260707-insight-report.png`
- HTML text checks:
  - contains `运行 ID=`
  - contains `社区`, `帖子 ID`, `发帖时间（UTC）`
  - contains `评论ID=`
  - does not contain `comment_id=`, `Subreddit`, `Post ID`, or `run_id=`
- DingTalk dry-run link checks with artifact base URL:
  - contains `https://files.example/reddit-voc/online_audit_html_smoke_20260707-insight-report.html`
  - does not contain `/Users/`, `/var/folders/`, or `outputs/online_audit_html_smoke`
- XLSX checks:
  - sheet `Momcozy Reddit VOC 日报`
  - `max_row=2`, `max_column=20`
  - first columns: `采集窗口`, `社区`, `帖子 ID`, `帖子链接`, `发帖时间（UTC）`
  - comment cell starts with `[1] 评论ID=t1_c1 | 分数=4 | 层级=0`
- Runtime env loader checks:
  - unset `REDDIT_VOC_ENV_FILE`: `no_env_ok`
  - external chmod `600` env file: `external_env_ok`
  - project-internal env file: blocked with rc `2` and `runtime_env_file_inside_project_blocked=...`
- Verification:
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 62 tests OK
  - `bash -n scripts/load_runtime_env.sh scripts/run_daily_collect.sh scripts/run_daily_report.sh scripts/run_daily_report_dry_run.sh scripts/run_local_daily_dry_run.sh`: OK
  - `plutil -lint` launchd templates: all OK
  - frontmatter check: online actions runbook, adversarial audit, keyword expansion plan all true
  - secret scan: placeholder examples only, no real provider key/webhook/bearer token found
- Git evidence unavailable: `/Users/pray/project/Reddit_VOC` is not a Git repository.

## Loop 11 TODO: Momcozy Keyword/Subreddit Expansion and Product Panorama

- [x] Parse historical Momcozy Reddit data from `/Users/pray/project/ai_nlp_voc/system_data/voc_data/reddit/Momcozy/`.
- [x] Mine historical product, category, competitor, pain-point and scenario terms from posts and comments.
- [x] Add network-informed subreddit coverage for pumping, buying-for-baby, babywearing, mixed-feeding, NICU and broad parenting fallback communities.
- [x] Update `config/keywords.yaml` with expanded brand variants, products, independent categories, contextual categories, competitors, pain points and model context.
- [x] Update `config/subreddits.yaml` with 07:00 Beijing collection window, P0/P1/P2 tiers and keyword policies.
- [x] Sync runtime defaults in `src/reddit_voc/keywords.py`, `src/reddit_voc/collector.py`, `src/reddit_voc/cli.py`, `src/reddit_voc/time_window.py`, `src/reddit_voc/ops.py` and report pain-point labels.
- [x] Add tests for bottle-washer recall, contextual baby-gear precision and 07:00 window defaults.
- [x] Add implementation plan: `docs/reddit-voc-keyword-subreddit-expansion-plan-20260707.md`.
- [x] Add product panorama HTML: `docs/reddit-voc-product-panorama-20260707.html`.

Loop 11 evidence:

- Historical mining output: `outputs/momcozy-history-keyword-mining-20260707.json`.
- Historical parse counts: `files=55`, `parsed_threads=55`, `parsed_comments=2215`, `parse_errors=0`.
- Top historical signals:
  - subreddits: `ExclusivelyPumping=41`, `babywearing=4`, then low-volume regional/mixed communities.
  - Momcozy products: `M5=154`, `M9=81`, `S12=59`, `M6=51`, `V1=44`.
  - adjacent categories: `bottle washer=92`, `high chair=70`, `sterilizer=18`, `bottle warmer=12`, `baby carrier=6`.
  - competitors: `Spectra=242`, `Eufy=185`, `Medela=48`, `Willow=41`, `Baby Brezza=25`, `Grownsy=14`, `Ergobaby=10`.
- Keyword smoke:
  - `KleanPal bottle washer vs Baby Brezza Washer Pro for pump parts` is relevant.
  - `Which high chair is easiest to clean?` is not relevant without brand/product/competitor context.
  - `Momcozy DinerPal high chair looks easier to clean than Graco.` is relevant.
  - default window end local is `2026-07-07T07:00:00+08:00`.
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`: 62 tests OK.
- YAML parse check: `config/keywords.yaml`, `config/subreddits.yaml`, `config/loop_engineering.yaml` parse as dictionaries.
- `bash -n scripts/run_daily_collect.sh scripts/run_daily_report.sh scripts/run_daily_report_dry_run.sh scripts/run_local_daily_dry_run.sh`: exit 0.
- `plutil -lint config/launchd/com.reddit-voc.daily-dry-run.plist.template config/launchd/com.reddit-voc.daily-collect.plist.template config/launchd/com.reddit-voc.daily-report.plist.template`: all OK.
- `PYTHONPATH=src python3 -m reddit_voc.cli tikhub-api-plan`: `provider_call=false`, `live_send=false`.
- Product panorama HTML parse smoke: file exists, bytes `15659`, contains inline `svg` and `Momcozy Reddit VOC 产品全景图`.
- Product panorama PNG screenshot: `outputs/reddit-voc-product-panorama-20260707.png`, bytes `451475`, size `1680x1540`, mode `RGB`.
- Secret scan found placeholder examples only:
  - `TIKHUB_API_KEY='<runtime-only-api-key>'`
  - `ACCESS_TOKEN`
  No real webhook, provider key or bearer token was found in scanned repo text files.
- Git evidence unavailable: `/Users/pray/project/Reddit_VOC` is not a Git repository.
- CodeGraph verification unavailable: `codegraph` not found in current PATH.
