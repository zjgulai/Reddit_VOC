---
title: Reddit VOC Monitoring Task Plan
doc_type: plan
status: active
created: 2026-07-07
updated: 2026-07-17
owner: codex
production_boundary: insights_site_l4_production_accepted
provider_call: false
live_send: false
---

# Reddit VOC Monitoring Task Plan

## 2026-07-27 V3 Canonical 数据可信闭环

完整执行计划见
`.kiro/plan/v3-canonical-data-trust-closure.md`。当前阶段为
`V3CT-complete_local_independent_validation`，范围仅限本地
workbook importer、独立 validator、canonical fusion 与回归验收；不调用
Provider、不写远程或生产、不构建或提升生产 release。

| ID | TODO | 状态 |
|---|---|---|
| V3CT-01 | 修复新增 canonical regression 的 JSONL 夹具解析 | complete |
| V3CT-02 | importer 读取并治理 optional unresolved parent ledger | complete |
| V3CT-03 | validator 独立重算同一 unresolved overlap / relink 合同 | complete |
| V3CT-04 | 覆盖 importer relink 与 fusion ledger 清退回归 | complete |
| V3CT-05 | 运行 focused、模块全量和本地 validator 门禁 | complete_90_of_90_and_two_validators |
| V3CT-06 | 记录最终证据与剩余风险 | complete |

## 2026-07-27 V2-05B 待关联评论父帖输入审计

当前阶段为 `v2_05b_blocked_missing_real_parent_post_evidence`，证据见
`.kiro/plan/v2-05b-unresolved-parent-input-audit.md`。正式 V3 基线中的
6,943 条 unresolved 评论、3,859 个缺失根帖已与 2026-07-23 最新本地日增量
canonical 做 SHA 绑定集合对账：旧缺失根帖与最新 3,591 条帖子交集为 0，
6,943 条旧评论全部仍 unresolved，日增量另新增 10 条 unresolved 评论和
3 个根帖。V3CT 已证明有真实父帖输入时可以安全 relink，但当前没有可消费的
父帖事实；禁止伪造关系、调用 Provider、写数据库或生成候选。

## 2026-07-27 V3 Task 14 Python 全量回归收口

V3 Task 14 Python suite、PPC-03 candidate automation hardening、PPC-01
业务术语清理与 PPC-02 跨页对账契约均已关闭。当前阶段为
`ppc_02_cross_page_reconciliation_contract_complete_local`，证据见
`.kiro/plan/ppc-02-cross-page-reconciliation-closure.md`。本批只新增本地
日历边界归一化、可比性门禁、三页业务说明与回归验证；该 build 不是持久候选，
禁止 Provider、远程写入、部署或生产切换。

## 2026-07-17 V2 中心数据业务激活 B2b

执行以
`docs/superpowers/plans/2026-07-17-reddit-voc-v2-center-business-activation.md`
为单一计划。B2a 已完成 3,494 帖、27,158 存储评论的全量中心桥接与 identity 零差异验证；
本地 B2b 已完成中心→VOC/标签/指标/画像/报告/洞察→frontend→release→E2E→shadow 闭环。
Provider、cron、部署和生产切换均未发生；仅执行了生产只读基线与两个 HTTPS shadow 观察。

| ID | TODO | 状态 |
|---|---|---|
| B2B-01 | 中心业务激活 manifest + 独立 validator | complete |
| B2B-03 | VOC/标签/品牌/产品/风险事实守恒 | complete |
| B2B-04 | 指标、画像、报告、洞察和概览制品守恒 | complete |
| B2B-08 | 新 frontend source candidate | complete |
| B2B-09 | 本地 release 与全路由 E2E | complete |
| B2B-11 | 两个本地 shadow 周期 | complete |
| B2B-12 | 新 production packet | ready_for_owner_authorization |

最终候选 release 为 `f335d9d27e16...34325d4b`，76-file dist 已包含业务激活 manifest/data；
packet `fa54470d7e20...1dd246f6` 已独立验证，尚未授权、未创建 permit、未提升生产。

## 2026-07-17 上线后可信运营闭环

截至 2026-07-27 只读核对，当前生产 release 为
`8a8a5a01772c73987cd7e471eedd8818b5b0c0d9efbdba4e8cecad54e7b5eded`，
pointer release ID 为 `reddit_voc_release_20260724_dashboard_fix_v1`。2026-07-17 A9
`9c4a45f2...84cc5` 的授权提升继续保留为历史验收事实，不冒充当前 release。
当前生产日报四格式已完成新的公共只读真实下载验收，回执 SHA
`8f737906bfe83d32487169883e3afb53d476985b593d235dc310770405e5a5bb`；
本次没有远程写入或生产变更，未来任何提升仍需新的精确授权。

| ID | TODO | 状态 | 验收证据 |
|---|---|---|---|
| PPC-00 | 上一生产 release 日报四格式真实下载验收 | complete_historical_public_readonly | `627fbab6...bed4` 的 CSV/PDF/PPTX/DOCX 4/4；receipt SHA `c2ce743d...a5a4`；当前 release 不继承该结论 |
| PPC-01 | 统一报告/洞察/画像/概览/内容证据下钻 | complete_local_business_terminology_cleanup | URL 主题/周期/筛选恢复与证据返回合同沿用已通过证据；新增术语回归 `1/1`，前端聚焦 `31 passed / 19 skipped`，lint exit 0（8 warnings），TypeScript/Vite build 通过；未生成候选 |
| PPC-02 | 老板视图业务文案与跨页同周期指标对账 | complete_local_cross_page_reconciliation_contract | 概览滚动窗口、洞察滚动季度与报告完整自然周期统一发布来源/范围/VOC 粒度/半开日期边界；仅四项完全一致才允许数值对账；新增契约 `4/4`、三页回归 `18/18`、lint 0、build 通过；未生成候选 |
| PPC-03 | Candidate-only 增量编排、singleton、quiescence 与 registry | complete_local_adversarial_hardening | 跨角色 promotion/permit 脚本拒绝 `1 passed, 4 subtests`；runner override + precommit/commit-marker 原子性 `3 passed`；orchestrator/registry 聚焦模块 `20 passed, 6 subtests`；未生成持久候选 |
| PPC-04 | permit/production acceptance/consumption/rollback 产品化 | complete_l4_control_path_exercised | packet/permit 精确绑定；remote receipt `c4e7d2f0...e597a`；acceptance `c37248ef...8255a`；consumption `20d4d05d...59058`；rollback-ready、未执行 |
| PPC-05 | 同一 dist 浏览器 E2E、容器 smoke 与候选 release | complete_l4_production_accepted | release `9c4a45f2...84cc5` 已生产可见；公网 13/8/20、双端 26/26；packet `7ff1227c...ceb8` 已一次性消费 |
| PPC-06 | 洞察页滚动季度口径、季度画像与四主题 Tab | complete_production_browser_accepted | 正式投影 `6fa37e4b...a18d26`；2026-04-17 至 2026-07-15；8,939 分析 VOC / 1,708 Momcozy VOC / 369 画像赋值；四 Tab、案例边界与双端公网 E2E 通过 |
| PPC-07 | 概览页领导摘要、圆形雷达与三时间窗口 | complete_production_browser_accepted | 7/30/183 天正式窗口 32/146/210 帖、306/1,567/2,006 VOC；圆形雷达、5 个公式、双坐标趋势、跨页精华及移动端公网验收通过 |
| PPC-08 | 当前生产日报 CSV/PDF/PPTX/DOCX 四格式真实下载验收 | complete_current_production_public_readonly_4_of_4 | release `8a8a5a...5eded` / pointer `bc715e...82ca`；4/4 结构、业务内容及 release/report 绑定通过；browser/HTTP/external errors 0；receipt `8f737906...a5bb`；production unchanged |

6,943 条待关联评论继续按关系债务展示；本轮不外部补抓、不伪造父帖关系。

PPC-06/PPC-07 是 Owner 在当前 Batch 1 本地候选形成前新增的业务变更。A6、A7、A8 source freeze
与 release 均已 supersede，不得进入生产提升；最终可消费源码身份仅为 A9 `c7e5eeedf...df7c8`。
日报/周报/月报正式数据合同不因洞察页季度化而改变；本次新 release 已按精确授权提升并完成验收，
后续 release 上传或生产切换仍需新的精确授权。

## 2026-07-16 Reddit VOC 完整体系、干预治理与案例闭环规格审计

当前阶段为 `reddit_voc_v3_task_5_explicit_automation_and_atomic_facts`。Owner 已确认 V3 书面规格；source
manifest、workbook import、canonical 三态守恒、双粒度 VOC/资格账本以及隔离 V3 站点状态清单均已形成
正式私有候选和独立回执，当前进入显式自动化排除、原子事实与画像证据实施。生产提升仍需新的精确
candidate/release/packet 授权；采集器、cron、共享 Nginx、TLS、DNS 与其他 Docker 不在本地实施
授权内。

Owner 已明确：`reddit-舆情数据_20260715222622510.xlsx` 的 12,720 行属于未按情感、严重度、
互动量或人工案例筛选的完整范围导出，目标是经 source manifest、文件指纹、身份去重与覆盖守恒
验证后进入合格观测池和品牌指数；该口径不会自动扩展到 814 行全负向工作簿。所有 Reddit 帖子
按 canonical Reddit identity 去重后进入分析池，但“进入分析池”与“进入经营指标分母”继续分层。

| ID | TODO | 状态 | 验收证据 |
|---|---|---|---|
| SYS-00 | 固化 12,720 行完整范围导出的 owner 声明与可复算 source manifest | complete_independently_validated | manifest SHA `8c90d349...e9b`；22/22 测试；13,534 行真实文件与 Base 双绑定复算通过；P0=0/P1=0 |
| SYS-01 | 深度审计 `ai_nlp_voc` 自动打标、指标、故事线和画像推理资产 | complete_readonly_evidence | 精确代码/配置路径；直接复用/适配/禁用三分表；Reddit V1 为 19 个指标，不复用旧 SQL/NPS/AIPL |
| SYS-02 | 建立全 Reddit 帖子/评论 canonical 去重分析池与双粒度 VOC 合同 | complete_design_contract | 13,534 源行与 3,494/27,158 目标守恒；identity/provenance/metric eligibility 三层；post_voc + comment_context_voc |
| SYS-03 | 建立 Momcozy 疑似不当干预、机器人与不规范推广证据体系 | complete_readonly_evidence | 官方 Reddit 规则映射、C0-C3/I0-I4 信号分级、误报控制、审计账本、采集缺口 |
| SYS-03A | 固化 r/ExclusivelyPumping 版主公告与处置事件链 | complete_external_verification | 2025-05 至 2026-06 五条原帖、版主自述、封禁/人工审核动作、本地覆盖与缺口账；按 C2/I3 发布，不冒充 Reddit 官方品牌归因 |
| SYS-04 | 把案例广场升级为洞察—证据—行动—监测—复盘闭环 | complete_readonly_evidence | 38+12 存量保留、默认 verified-only、非空 delta 发布合同、CaseReference/CaseDossier/ActionLedger 三对象与应用效果指标 |
| SYS-05 | 形成 2–3 个架构方案并收敛品牌指数/治理指数的唯一口径 | complete_owner_confirmed_option_a | 品牌健康四维总分 + 独立内容诚信治理；I1/I2/C2/I3 不额外扣分 |
| SYS-06 | 编写完整 Reddit VOC 体系规格和实施计划并独立对抗复审 | complete_owner_approved_and_planned | spec 独立门禁 P0=0/P1=0；14-task 文件级 plan SHA `71bd2462...ccfb7`，结构/覆盖/placeholder scan 通过 |
| SYS-07 | 实施 V3 Package 1 source manifest、workbook import 与 canonical 守恒 | complete_task_3_independently_validated | canonical manifest SHA `36bbc150...c1ce`；receipt SHA `9f7af1b2...b4c2`；59/59；3,494 posts / 27,158 comments 三态与 13,534 源行守恒通过 |
| SYS-08 | 实施 V3 Package 2–9 与本地候选 | complete_task_14_python_suite_1858_passed | Tasks 5–13 与 Task 14 frontend/E2E/container/registry 已有完成证据；恢复 3 个清单绑定的公开归档后，focused `1/1` 与 Python 全量 `1858 passed, 881 subtests passed`；无部署或远程动作 |

设计边界：疑似机器人、协同推广或商业干预只能作为风险信号与待审证据，未经多信号验证和人工
复核不得写成“机器人”“违规”或品牌事实；报告必须区分 earned VOC、owned/affiliated content、
suspected coordinated activity 和 unknown。`production unchanged`。

新增外部证据边界：已核实 r/ExclusivelyPumping 以版主公告形式多次公开描述 Momcozy 相关
AI bot/虚假账号推广，并称已封禁账号、曾逐条人工审核 Momcozy 帖子与评论。该事实足以形成
`I3=external community moderation action`，并与重复商业传播描述共同形成 `C2+I3`；但当前
未获得 Reddit 官方平台裁定、涉事账号全量、雇佣/控制关系或 Momcozy 官方确认，因此不得写成
`C3+I4` 的“已确认品牌机器人项目”。

## 2026-07-15 报告口径、品牌总览、案例与画像 V2 迭代

当前阶段为 `written_spec_ready_for_owner_review`。Owner 已确认概念方案 A，并新增
`add_data` 去重融合、帖子独立 VOC + `父帖 + 1 条评论` 上下文 VOC，以及复用
`ai_nlp_voc` 标签→指标→故事线体系的要求。修订规格已完成两轮独立门禁，P0=0/P1=0；
不复用上一 release 的生产授权，不在规格审阅门前修改前端或生成新生产候选。

| ID | TODO | 状态 | 验收证据 |
|---|---|---|---|
| V2-00A | 冻结两份 `add_data` Excel，完成字段/时间精度/采样偏置盘点 | complete_design_evidence | 13,534 源行、SHA/schema/完整性/日精度证据 |
| V2-00B | 完成 `add_data` 与 Base 的 Reddit ID 去重、父帖交叉和守恒设计 | complete_design_evidence | 2,172 净新帖子、10,567 净新评论、3,582 个文本可用评论上下文输入 |
| V2-00C | 冻结双粒度 VOC：帖子独立，每条评论与父帖构成一条上下文 VOC | complete_design_evidence | post/comment_context/thread 分母、pair key、evidence_scope |
| V2-00D | 冻结 source-selection 与 per-metric 分母资格 | superseded_by_SYS-00 | 814 negative-selected 仍为 evidence-only；12,720 已获 Owner 完整范围声明，待 manifest/validator 固化后进入合格观测池；Base overlap anchor 规则不变 |
| V2-01 | 复核日报趋势时间粒度、时区和标签格式 | complete_design_evidence | formatter 矩阵 + 日精度不进小时桶 |
| V2-02 | 合并双报告口径并改为业务称谓 | complete_design_evidence | 唯一默认报告视图、历史对比仍可追溯、不丢六份报告数据 |
| V2-02A | 重构同环比指标卡与卡内趋势 | complete_design_evidence | 可比值/`—` 三态、`?` 口径说明、上红下绿 sparkline |
| V2-03 | 从旧 UI 与真实数据召回品牌雷达和总体评分 | complete_design_evidence | distinct side-union 口径、融合后动态重算、不可用规则 |
| V2-03A | 将 owner 提供的品牌使命图片加入概览首屏 | superseded_removed_by_owner | Owner 后续明确要求移除；最终候选 DOM 与源码清单均不再包含该图片 |
| V2-04 | 盘点案例默认搜索与高质量链接门禁 | complete_design_evidence | verified-seed ledger、默认 fail-closed、legacy 不放行 |
| V2-05 | 从标签字典和帖子/评论证据重建聚合画像 | complete_design_evidence | 82 原子画像 + 8 复合 cohort、assignment 守恒、合成头像 |
| V2-05A | 复用 `ai_nlp_voc` 标签→指标→故事线成果并生成 Reddit 专属 registry | complete_design_evidence | v6.3 SHA、8,854 mapping、43 registry/触发规则债务与可用边界 |
| V2-05B | 补全暂未匹配到所属帖子的评论上下文 | blocked_missing_real_parent_post_evidence | 正式基线 3,859 父帖 / 6,943 评论；与最新本地日增量 3,591 posts 交集 0，旧评论 6,943/6,943 仍 unresolved；日增量新增 10 评论 / 3 父帖；等待受治理真实父帖快照，不伪造父帖 |
| V2-05C | 冻结 82 原子画像 matcher、8 群组 bridge、19 个 Reddit 指标及阈值算法 | complete_design_evidence_corrected | parent persona 不继承、token boundary/held、explicit alias、nearest-rank calibration；5+5+4+5 重算纠正旧 18 计数 |
| V2-06 | 完成书面设计、独立复核和 owner 审阅 | ready_for_owner_review | 两轮独立门禁 P0=0/P1=0；等待 Owner 确认 spec |
| V2-07 | 实施、真实数据重算、测试和本地候选 | complete_current_production_four_exports_other_debt_retained | 原 UI/候选证据保持历史有效；当前生产 `8a8a5a...5eded` 日报四格式 4/4 公共只读验收完成，receipt `8f737906...a5bb`；未发布的 PPC-01/PPC-02 本地源码不继承该回执 |
| V2-08 | 新 packet 精确授权后才允许生产提升 | complete_l4_production_accepted | packet `7ff1227c...ceb8` + release `9c4a45f2...84cc5` 已精确授权并一次性消费；acceptance `c37248ef...8255a`；consumption `20d4d05d...59058` |

candidate registry 的本地深度治理已在 PPC-03 与 CRG-01 闭合；CRA-01 已启用 request-driven 本地增量自动接入。
当前状态为 `armed_idle_no_pending_request`，不继承为 promotion、deploy、Provider、数据库、远程写入或 live send 授权。

## 2026-07-15 全候选闭环、UI 治理与受控候选计划

用户已确认 umbrella written spec。三个 implementation plan 共用同一最终
release identity，不能独立提升生产：

| Plan | 状态 | 实施文件 | 退出证据 |
|---|---|---|---|
| A 全候选与融合 | complete — final a3e local closure independently validated | `docs/superpowers/plans/2026-07-15-reddit-voc-candidate-closure-data.md` | L3 quiescence/freeze + 五本账 + data receipt，`unaccounted_total=0` |
| B UI 治理 | complete — local source/DOM and independent source receipt validated | `docs/superpowers/plans/2026-07-15-reddit-voc-ui-governance.md` | 治理组件、正常态无 error glyph、失败态 fail closed、source manifest/receipt |
| C 候选自动化 | complete — L4 accepted and local registry automation armed | `docs/superpowers/plans/2026-07-15-reddit-voc-candidate-automation.md` | release `a5fa1e0a...d460f3`、packet `83d5ebea...10570` consumed、acceptance `b5fcd682...76ade`；registry/export debt follows production visibility |

Plan A 最终可消费身份是 candidate input
`70a917e5bdf0df319d52d8077f3cc71b813a36f54c609194b07fea386844ac1e`，
manifest `c18d313ae7ee038d06e2402022548709bcba2b71e54bef106b636215291cdfb7`，
reconciliation `347fc37a167f8bdb3562928af850d62c5be7b720f501f9a8a65383dc2cf957b7`，
independent receipt `e2958d7d057c25a265839e7693aa164079c7dfad9dc131f1291d8266c7bc9f80`。
旧 a3c/a3d code freeze 与 `a61899f3...c9fab` closure 均为 superseded，不得消费。

Plan B 唯一可消费 frontend candidate input 为
`c04aec93775179be20f6b5538795c647b66a2a6df36c3a898fdc6b7119eb022e`，source manifest
`32afe3adb5ed7b24c62d28a76856ca509432b441941c8befe4946630a2384e6d`，independent source
receipt `340e4f65c753eff75031bd129654f9faa8699366e5f76c97726e6cb1c44853ab`。
receipt-less `870855c1...885e` 已 superseded，禁止消费。

“老板可见生产优先”关键路径已完成：packet `83d5ebea...10570` 的精确授权被一次性消费，
release `a5fa1e0a...d460f3` 通过 18339 候选 smoke、CAS 切换与公网验收后成为当前生产。
candidate registry 深度治理、四导出验收与 request-driven 本地自动接入均已闭合；首轮为空 inbox idle。此次没有续采或调用
Provider，没有写生产 DB、启用调度或修改采集器/cron/shared Nginx/TLS/DNS/其他 Docker。
`unaccounted_total=0` 不等于历史覆盖完整；仍显式保留 1,179 个 open coverage items 与
18 条 pending lineage。

## Goal

Build a Reddit VOC monitoring system for Momcozy brand mentions and relevant product-category discussions. Every day at 07:00 Asia/Shanghai, collect Reddit posts created in the previous rolling 24 hours and their available comments. At 08:00 Asia/Shanghai, generate the Chinese VOC report and send one DingTalk message with post-level blocks and structured artifact links.

## 2026-07-09 Current Execution Plan

| Workstream | Status | Acceptance Evidence |
|---|---|---|
| Codex project context | active | `.codex/context-pack.md` and `.codex/session-thread.md` exist and reflect the latest 07:00/08:00 schedule |
| CodeGraph context | partial | `.codegraph/` exists and ignores local DB files; current shell has no `codegraph` executable in PATH |
| Git initialization | pending | Root `.gitignore` excludes secrets, local DBs, generated outputs, logs, tmp files, and CodeGraph DB files before `git init` |
| Scheduler change | in_progress | Local deploy script writes `0 7 * * *` collect-only and `0 8 * * *` report/DingTalk cron entries |
| Website settings | in_progress | `/api/settings` returns `collection_time=07:00` and `report_time=08:00` |
| Verification | pending | Shell syntax, launchd plist lint, Python tests, Codex doctor, and deployment/cron smoke where applicable |
| Historical backfill | in_progress — Task 29 review complete; local comments schema repair required before any new Provider packet | Target `8baa6613...c29f2f`; 12/12 failures are `comments_schema_drift`; Provider remains `969/1200` |

## 2026-07-15 Momcozy P0 Collection Closure Plan

Scope is limited to existing P0 competitor/category staging. It does not
authorize canonical/SQLite merge, production merge, Git push, DingTalk/live
send, deployment, cron changes or changes to the daily collector.

Verified baseline: all nine P0 search lanes are terminal; 876 raw IDs contain
844 Reddit-shaped IDs and 32 invalid IDs; first-page comments cover all 844
valid posts (838 passed, 6 fail-closed); reply cursor accounting has 279
unprocessed candidate pairs after 821 passed reply reports. Reply pages can
create new `More` cursors, so the count is a checkpoint rather than a fixed
request total.

| ID | TODO | Status | Exit evidence |
|---|---|---|---|
| P0-C00 | Freeze current reports/bindings and verify no local worker remains | complete | all lanes terminal; remote audit counts recorded |
| P0-C01 | Drain replies in 9-worker batches of up to 45 fresh one-shot packets | in_progress | reports/bindings pass and each batch records cursor delta |
| P0-C02 | Reconcile six failed comment posts by source lineage and response shape | complete | all six are source-only nonresolvable IDs; no old packet reuse |
| P0-C03 | For an eligible retry candidate only, issue one new packet per post with a distinct task ID | not_applicable | no transient candidate survived source-lineage classification |
| P0-C04 | Run read-only closure audit across IDs, comments, replies, bindings and forbidden flags | pending | accounting closed or exact unresolved set listed |
| P0-C05 | Generate a read-only canonical merge plan and coverage matrix, then stop | pending | deterministic identity counts and production unchanged |

Execution rules: every retry uses a new packet; a non-passing response remains
fail-closed; search termination does not prove comment/reply/dedup/merge
completion.

### P0-C01 Next-Batch Schedule

| Batch | Work | Bound | Checkpoint before continuing |
|---|---|---:|---|
| R2 | Reply workers `0..8`, five fresh packets each | <=45 requests | complete: 776 reports / 292 remaining after remote audit |
| R3 | Reply workers `0..8`, five fresh packets each, task IDs `17000..17008` | <=45 requests | complete: 821 reports / 279 remaining after remote audit |
| R4 | Reply workers `0..8`, five fresh packets each, task IDs `18000..18008` | <=45 requests | eligible: R3 had a positive net reduction (`292 -> 279`) |
| FC | Read-only classify six `payload_post_missing` comment reports | 0 Provider requests | source ID validity, post lineage and response shape recorded |
| FR | Fresh one-shot retry only for an FC-approved transient candidate | <=6 requests | one new task/packet per post; old packet never reused |

The completed reply drains reduced the candidate set `324 -> 308 -> 292 -> 279`.
This is an observation rather than a forecast. R4 uses new task IDs
`18000..18008`; no more than one Provider request may be issued for each packet.
The batch ends early if a remote report is absent or fails validation; audit the
remote artifact before any replacement action. If the net cursor reduction is
zero or negative, do not start a subsequent batch automatically.

## 2026-07-14 DeepSeek L2 Protected-Value Local Repair TODO

Decision being gated: diagnose the four items blocked by the third L2 shadow,
separate the generic report-level `protected_entity_changed` reason from the
item-specific model/number categories, then repair the local translation
contract without weakening either deterministic gate. This lane is local-only
and ends at a new immutable candidate plus an exact request packet in
`ready_for_owner_authorization` state.

Current evidence boundary:

- request `deepseek-l2-postblock-repair-20260714-193359` is terminal
  `consumed_terminal_blocked`; its attempt cannot be retried;
- all 9 translation responses succeeded, but 4 items failed the number gate,
  only 2 of those also contain an item-specific model category, and the
  remaining 50 items were not semantically validated;
- cumulative DeepSeek use is `27/100`; the remaining `73` attempts are budget,
  not authorization;
- the blocked manifest intentionally contains no source text or candidate `zh`,
  so this loop may diagnose input shape but cannot reconstruct or claim the
  exact Provider mutation;
- both permits are terminal `blocked`, gates are all-off, the runner runtime is
  absent, and production is unchanged.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-H00 | Freeze terminal hashes, branch/worktree, permits, gates, runtime and no-Provider boundary | complete | Prior attempt remains immutable; no new permit, key read, runtime or Provider process |
| DS-L2-H01 | Join the four stable IDs to the copied input and record only sanitized protected-value structure | complete | Item type and protected category/count/overlap evidence without source, candidate `zh`, username, URL or stable ID |
| DS-L2-H02 | Add RED tests for protected-value masking/restoration and tamper failures | complete | Current code demonstrably exposed protected values; RED exit 1 covered success and four tamper modes |
| DS-L2-H03 | Implement the minimum collision-safe placeholder contract and update the single prompt source | complete | Provider input contains opaque markers; restored output preserves exact source values; existing entity/number checks remain strict |
| DS-L2-H04 | Run focused and exclusive serialized full regression plus static/schema checks | complete | Focused `62/62`; Python 3.12 unittest split `654/654`; pytest-only module `3/3`; static/schema checks exit 0 |
| DS-L2-H05 | Build and verify a new immutable release candidate with provider-free copied-DB smoke | complete | Release/import/manifest/DB hashes close; `translation_provider_attempt_made=false`, `live_send=false` |
| DS-L2-H06 | Build a new exact request packet capped at the remaining `73` attempts | complete | Packet SHA `7f76571b...3002` is `ready_for_owner_authorization`; no permits installed |
| DS-L2-H07 | Sync README/context/design/plan/findings/progress/acceptance and stop | complete — stopped | `production unchanged`; no Provider, DingTalk, deploy, commit, push, merge or L3/L4/L5 action |

Stop before installing a permit, reading/copying the isolated key, creating a
new shadow/runtime root or issuing Provider transport. A local green candidate
is preventative contract evidence only; without retained third-attempt output
it does not prove the exact historical model behavior or a future L2 pass.

## 2026-07-14 DeepSeek Protected-Placeholder Authorized L2 Execution TODO

Decision being executed: run exactly one isolated L2 shadow for
`daily_collect_20260714_0700` using the protected-placeholder candidate. The
owner explicitly approved the complete request ID, packet SHA and 73-attempt
cap in the current Codex task. This approval does not grant L3/L4/L5, send,
production, Docker, deploy, cron/service or Git authority.

Authorization binding:

- request: `deepseek-l2-protected-placeholder-repair-20260714-205534`;
- packet SHA: `7f76571b67a1178b54827e64d281cdee0e53519f4f8f22fb1711260caeda3002`;
- release SHA: `bc51d736f3d07b1c307fa3b6ecc1948be2ef541947be6cd32f08bd13aec340e4`;
- release manifest SHA: `e4edef8fd83eda87aeb19c04aee7abffb875f7d0be345cc53fde3787ae939d92`;
- validation SHA: `a6be9cc34df7a65a85ed54d2671c6f8fe76b25dd721cc55058a1a87cf38a43f2`;
- copied DB SHA: `b415172856a336a1a00ac5118984159a4afab299fb2913d7bace3dcdc8c92d7c`;
- run: `daily_collect_20260714_0700`; model: `deepseek-v4-flash`;
- expiry: `2026-07-16T23:59:59+08:00`; cap: `73` additional attempts;
- prepare authorization: `deepseek-l2-prepare-protected-placeholder-20260714-205534`;
- provider authorization: `deepseek-l2-shadow-protected-placeholder-20260714-205534`.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-A00 | Re-freeze exact packet/release/DB/runtime/runner hashes and no-process boundary | complete | Preflight passed; no new root, permit, key read or Provider process |
| DS-L2-A01 | Re-run release/import, packet/schema, copied-DB and provider-free gates | complete | Exit 0; round-trip exact; release/import 19 modules; no new Provider |
| DS-L2-A02 | Initialize mode-700 shadow, copy DB and install all-off env | complete | Exact root descriptor, DB SHA, env mode 600 and gates all-off |
| DS-L2-A03 | Install exact permits and copy/check key through no-log stdin path | complete — terminalized after pre-provider block | Both bindings installed; key metadata valid; content never emitted |
| DS-L2-A04 | Execute exactly one host-native shadow with translation gates only | complete — blocked before Provider | One runner invocation; `translation_provider_attempt_made=false`; gates restored all-off |
| DS-L2-A05 | Verify ledger, output, automatic gates, usage and non-interference | complete | Runtime root cleaned; permits blocked; no Provider process; production unchanged |
| DS-L2-A06 | Sync current terminal evidence and stop | complete — stopped for runtime-contract repair | New packet prepared; no retry of terminal permits; no L3/L4/L5/send action |

Stop immediately on any packet/release/DB/runtime/key/permit mismatch, stale
expiry, dirty gate, missing recovery or process ambiguity. After the first
Provider attempt line exists, do not launch a second runner or retry.

## 2026-07-14 DeepSeek Runtime-Contract Repair TODO

The approved packet reached a fail-closed pre-Provider stop because its
all-off `runtime.env` contained only gate fields. `materialize-prepare-env`
requires five non-secret base fields before any report can run. No DeepSeek
request was made and no attempt budget was consumed; both exact permits are
terminal `blocked` and cannot be reused.

The local repair adds only the required non-secret contract fields: the new
shadow database path, a non-network `https://files.example/reddit-voc` artifact
base URL, `DINGTALK_REQUIRED_KEYWORD=LL`, `18000` byte and `2` part limits. Both
DingTalk values remain blank, all gates remain off, and no production path is
referenced.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-RF00 | Record the approved packet's pre-Provider terminal stop and clean runtime root | complete | Reason `runtime_env_required_value_missing`; no Provider attempt; gates all-off |
| DS-L2-RF01 | Build and statically validate corrected runtime template | complete | Required fields, blank webhook values, mode 600 and requested shadow DB binding |
| DS-L2-RF02 | Build exact replacement validation manifest and request packet | complete | Packet `f1f9b99d...ce066`, status `ready_for_owner_authorization` |
| DS-L2-RF03 | Obtain owner approval for the replacement packet | complete | Exact new Request ID/SHA and 73-attempt cap approved in the current Codex task |
| DS-L2-RF04 | Execute one replacement shadow only after RF03 | complete — blocked before Provider | One runner invocation; `runtime_env_required_name_missing`; no retry or L3/L4/L5/send action |

Replacement packet: `deepseek-l2-protected-placeholder-runtimefix-20260714-211414`,
SHA `f1f9b99d696fb60ab76edb5de3b6c783ed1e734bf4f4a47fac4ee7e7f54ce066`.
Remaining budget is still `27/100` consumed and `73` available; budget is not
authorization.

## 2026-07-14 DeepSeek Runtime-Fix Replacement Terminal Stop

The owner explicitly approved the replacement packet above with its full
Request ID, SHA and 73-attempt cap. Exactly one fresh shadow was initialized,
the copied DB and all-off runtime were verified, both exact permits were
installed, and the isolated key was copied through the approved stdin/no-log
path. The host-native runner was invoked exactly once.

The runner failed closed before Provider transport during
`materialize-prepare-env` with `runtime_env_required_name_missing`, followed by
`prepare_runtime_env_materialize_failed`. The corrected template supplied the
five non-secret base values, but the immutable runner also requires the names
that it replaces at materialization time (`REDDIT_VOC_RUN_ID`, attempt and
artifact IDs, report roots, provider-attempt root and config root). No
DeepSeek request, response, token usage, semantic validation or report
manifest was produced. This is a local runtime-template contract defect, not a
Provider-quality result.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-RF05 | Freeze the replacement packet, permits, attempt and runner boundary | complete | Packet SHA exact; attempt `attempt-20260714T133104260742Z-d970fb46d50debfe`; `translation_provider_attempt_made=false` |
| DS-L2-RF06 | Verify terminal recovery and non-interference | complete | Permits `blocked`; gate journal `restored`; gates all-off; runtime root removed; DB SHA unchanged; no Provider process; production unchanged |
| DS-L2-RF07 | Stop for a new local template repair and owner authorization | complete — stopped | No retry; no new permit/key/root; no L3/L4/L5/send/deploy/Git action |

Replacement terminal boundary:

```text
evidence_grade=L2-authorized-replacement-preprovider-blocked
executed_request_id=deepseek-l2-protected-placeholder-runtimefix-20260714-211414
executed_request_sha256=f1f9b99d696fb60ab76edb5de3b6c783ed1e734bf4f4a47fac4ee7e7f54ce066
executed_attempt_id=attempt-20260714T133104260742Z-d970fb46d50debfe
runner_exit=1
reason=runtime_env_required_name_missing
prepare_failure=prepare_runtime_env_materialize_failed
provider_call=false
translation_provider_attempt_made=false
deepseek_attempts_consumed=27
deepseek_attempts_remaining=73
prepare_permit_status=blocked
provider_permit_status=blocked
gates=all_off
runtime_root=absent
provider_process=absent
live_send=false
failure_alert_send=false
database_write=false
production unchanged
L3_authorized=false
L4_authorized=false
L5_authorized=false
retry=false
```

The packet and its permits are terminal for this execution and cannot be
reused. A future attempt requires a new local template/packet plus a new exact
owner authorization; the remaining 73 is a cap, not permission.

## 2026-07-14 DeepSeek Runtime-Template Full-Field Repair TODO

The replacement runner exposed a second local contract layer: after the five
non-secret base values pass, `materialize-prepare-env` requires every name it
will overwrite to already exist in the runtime document. This repair is local
only. It creates no shadow/runtime root, installs no permit, reads no key and
does not call Provider.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-RF08 | Trace the immutable materializer replacement-name contract | complete | Exact 18-name set recorded from release code; prior failure remains `runtime_env_required_name_missing` |
| DS-L2-RF09 | Build full-field all-off runtime candidate and static round-trip proof | complete | Runtime mode 600; 5/5 base values; 18/18 replacement names; blank webhooks; replacement parser round-trip passes |
| DS-L2-RF10 | Build validation manifest and exact new Request packet capped at 73 | complete | Packet SHA `355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb`; manifest SHA `b54b283079d380d83d9e418f71baa66c1c810fd7ec82e4ae598f070fb800240c` |
| DS-L2-RF11 | Obtain owner approval for the new Request ID/SHA/cap | complete | Explicit approval received in the current Codex task |
| DS-L2-RF12 | Execute exactly one full-field replacement shadow | complete | Runner exit 0; 18 requests; 54/54 items accepted; semantic validation all five true; no send |
| DS-L2-RF13 | Verify terminal recovery and sync L2 evidence | complete | Permits consumed; gates restored all-off; runtime absent; DB unchanged; production unchanged |

New local candidate:

- request: `deepseek-l2-protected-placeholder-runtimefix-fields-20260714-225341`;
- packet SHA: `355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb`;
- validation manifest SHA:
  `b54b283079d380d83d9e418f71baa66c1c810fd7ec82e4ae598f070fb800240c`;
- runtime template SHA:
  `8aeb1ae50f2d2a7040630b3957b4d379dc796c5c2382aab8a72591685eaaf0c6`;
- release/manifest/DB remain `bc51d736...340e4` / `e4edef8f...9d92` /
  `b4151728...c92d7c`; cap remains 73.

Current boundary:

```text
evidence_grade=local_verified_full_runtime_candidate_ready_for_owner_authorization
request_id=deepseek-l2-protected-placeholder-runtimefix-fields-20260714-225341
request_sha256=355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb
request_status=ready_for_owner_authorization
materializer_names=18/18
runtime_contract_static_roundtrip=passed
deepseek_attempts_consumed=27
deepseek_attempts_remaining=73
new_permits_installed=false
provider_key_read=false
new_shadow_root=absent
new_runtime_root=absent
provider_call=false
live_send=false
production unchanged
```

The packet was explicitly approved and executed exactly once. Its 73-attempt
cap was not exceeded; 18 requests were used and the cumulative budget is now
`45/100`, with 55 remaining. The shadow result is complete at L2 automatic
gates only; no L3/L4/L5/send authority is inferred.

## 2026-07-14 DeepSeek Full-Field Replacement L2 Complete

The approved packet executed one isolated shadow successfully. The runner
returned `complete` with 9 translation requests and 9 semantic-validation
requests, all using `deepseek-v4-flash`, 0 retries and 45,249 total tokens.
All 54 items were accepted; 32 had entity checks and 22 were not applicable;
all five semantic verdict fields were true for all 54 items and critical error
count was zero.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-RF14 | Preserve sanitized terminal evidence and artifact hashes | complete | Evidence SHA `0befd35b3fe6147a7436c39f9f5897a95863525258ec119c24aac9786f60acc6`; bundle/outbox/manifest hashes recorded |
| DS-L2-RF15 | Keep L3 boundary explicit and stop | complete — stopped | `l3_blind_review_package=false`; no L3/L4/L5/send/deploy/cron/service/Git action |

Terminal boundary:

```text
evidence_grade=L2_shadow_complete_automatic_gates_passed
executed_request_id=deepseek-l2-protected-placeholder-runtimefix-fields-20260714-225341
executed_request_sha256=355d95b17702386de786dc53ed78eb49f276e0c2c9ffd79f1a6c9752c80e5ceb
executed_attempt_id=attempt-20260714T152314241954Z-ff5dfb42df4dc5a8
artifact_version_id=20260714T152314241954Z-4b2b8140178434c842bc62181018b589
runner_exit=0
provider_call=true
translation_provider_attempt_made=true
translation_requests=9
semantic_validation_requests=9
retry_count=0
items=54/54_accepted
entity_status=32_accepted_22_not_applicable
semantic_verdict_all_five_true=true
critical_error_count=0
packet_requests_used=18
deepseek_attempts_consumed=45
deepseek_attempts_remaining=55
prepare_permit_status=consumed
provider_permit_status=consumed
gates=all_off
gate_journal=restored
runtime_root=absent
provider_process=absent
live_send=false
failure_alert_send=false
current_advanced=false
database_unchanged=true
production unchanged
L3_authorized=false
L4_authorized=false
L5_authorized=false
```

L2 automatic gates passing does not create an L3 blind-review approval or an
L4/L5 release/production decision. The consumed permits cannot be reused.

## 2026-07-14 DeepSeek L2 Post-Block Repair Authorized Execution TODO

Decision being gated: execute exactly one isolated third L2 shadow for
`daily_collect_20260714_0700` using the locally verified post-block repair
candidate. The owner explicitly approved the exact packet in the current Codex
task after it was presented with its full SHA-256 and remaining-attempt cap.

Owner authorization recorded in the current Codex task:

- request ID: `deepseek-l2-postblock-repair-20260714-193359`;
- request packet SHA-256:
  `13f576a3fea6b2173f372a167f850bc76fbdc3646cf5973bced8b123a09a80a5`;
- candidate release SHA-256:
  `861a88d829f4afce2ec3c3f2db99f75e7d59db9a764ae1e1975d38bbe6aa5f54`;
- candidate manifest SHA-256:
  `193035f220ae2ca953f0a5a1402dce62975159629c003d355e1f7f6b8b874174`;
- validation manifest SHA-256:
  `9f8f096130834d7df99f5f6176546ebb1f4ef0128057157ecc36f555d85d0668`;
- copied database SHA-256:
  `b415172856a336a1a00ac5118984159a4afab299fb2913d7bace3dcdc8c92d7c`;
- authority: read/copy the isolated key without exposing it and perform at most
  `82` additional DeepSeek attempts for exactly one replacement shadow report;
- expiry: `2026-07-15T23:59:59+08:00`;
- prohibited: DingTalk/report alert send, production DB/output/control write,
  local or remote Docker mutation, Colima creation, software installation,
  L3/L4/L5 acceptance or activation, deploy, cron/service change, commit, push
  or merge.

Evidence gate: `allowed-with-label` for one authorized L2 shadow only. Provider
success is not automatic-quality-gate success; an L2 complete result is not L3
human acceptance, L4 release readiness, L5 production prepare acceptance or
report delivery.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-P00 | Freeze exact authorization, packet, candidate, DB, branch/worktree and prior terminal state | complete | Exact hashes/expiry/cap match; no new root, permit or Provider process before initialization |
| DS-L2-P01 | Re-run release/import, copied-DB, shell/static and provider-free preflight gates | complete | Exit 0 on exact immutable candidate; `translation_provider_attempt_made=false`, `live_send=false` |
| DS-L2-P02 | Initialize a fresh mode-700 shadow, copy the exact DB and install the all-off env; keep runner-created runtime absent | complete | Exact shadow descriptor/release/DB/env; no key read and runtime root absent |
| DS-L2-P03 | Install exact prepare/provider permits, then install/check the mode-600 key via stdin/no-log | complete | Bindings match packet/release/run/DB/cap `82`; no key content emitted |
| DS-L2-P04 | Execute exactly one host-native isolated shadow with translation gates only | complete — blocked | One terminal complete or blocked attempt; gates restored all-off in `finally` |
| DS-L2-P05 | Verify ledger, manifests, hashes, model, usage, retries, output alignment and non-interference | complete | No active permit/journal/gate/process residue; `live_send=false`; `production unchanged` |
| DS-L2-P06 | Apply automatic quality gates and create an L3 blind package only if all automatic gates pass | complete — fail-closed | Five-true semantic verdict plus mapping/entity-number gates, or exact fail-closed reason |
| DS-L2-P07 | Sync README/context/design/plan/findings/progress/acceptance and stop | complete — stopped | Terminal state explicit; no L3/L4/L5/send action inferred |

Stop before Provider transport on any packet/release/manifest/DB/runtime/key
metadata mismatch, stale/expired permit, dirty active gate, missing all-off
recovery, validation failure or authorization ambiguity. After the first
Provider attempt record exists, do not launch a second runner or retry outside
the authorized runner.

## 2026-07-14 DeepSeek L2 Post-Block Local Repair TODO

Decision being gated: diagnose and repair the local deterministic translation
contract after the terminal semantic-fix shadow blocked before semantic
validation. This lane is local-only. It does not authorize a DeepSeek request,
DingTalk/report alert send, production write, Docker/Colima mutation, deploy,
cron/service change, commit, push or merge.

Current evidence boundary:

- both prior L2 permits and attempts are terminal `blocked` and cannot be reused;
- `18/100` DeepSeek requests are consumed and `82` remain, but remaining budget
  is not authorization;
- the blocked manifest retained no Provider translation text, so the exact
  missing entity cannot be reconstructed or claimed as proven;
- the pipeline currently converts the first deterministic item failure into
  all-item `pending` evidence, so `54/54 pending` is not proof that all 54 items
  independently violated the entity contract;
- the real copied input contains three model-pattern matches with noncanonical
  casing. The implementation detects those matches case-insensitively but
  enforces byte-for-byte case preservation, which is a reproducible local
  contract inconsistency and a bounded repair candidate.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-R00 | Freeze terminal evidence, branch/worktree and no-Provider boundary | complete | Exact prior hashes/budget retained; no active Reddit VOC test/Provider process |
| DS-L2-R01 | Trace deterministic entity extraction, validation and failure propagation | complete | Exact code path plus sanitized real-input category counts; no source/PII output |
| DS-L2-R02 | Add RED tests for safe model-case normalization and model-identity changes | complete | Current code rejected case-only normalization while still rejecting a different model |
| DS-L2-R03 | Add sanitized first-failure item/category evidence without storing source or `zh` | complete | Blocked manifest distinguishes known blocked items from unvalidated pending items and aggregates failures across bundles |
| DS-L2-R04 | Implement the minimum model-case contract repair | complete | Case-only normalization accepted; model identity, numbers, exact currency, URLs and Reddit refs remain protected |
| DS-L2-R05 | Run focused tests, serialized full suite, schema/release/import and copied-DB provider-free preflight | complete | Fresh exit-0 evidence; `translation_provider_attempt_made=false`, `live_send=false` |
| DS-L2-R06 | Build a new immutable candidate release, validation manifest and exact request packet capped at `82` | complete | Content-addressed candidate and packet status `ready_for_owner_authorization` |
| DS-L2-R07 | Sync README/context/design/plan/findings/progress/acceptance and stop | complete — stopped | `production unchanged`; no Provider call; no permit installation; no L3/L4/L5 action |

Stop before installing any new permit or reading/using the isolated Provider
key. A local green candidate only supports a new owner authorization decision;
it is not evidence that the real Provider output will pass.

## 2026-07-14 DeepSeek L2 Semantic-Fix Replacement Execution TODO

Decision being gated: execute exactly one isolated replacement L2 shadow for
`daily_collect_20260714_0700` after the prior nine-request DeepSeek translation
attempt failed closed on `protected_entity_changed`.

Owner authorization recorded in the current Codex task:

- request ID: `deepseek-l2-semanticfix-replacement-20260714-175924`;
- request packet SHA-256:
  `70dba4a85d7b963120bd963baee1b78b9b623c95ec9c6938cbe46acf1d1e8940`;
- candidate release SHA-256:
  `eec615b69588ed5843a2997ede1937f44b54a5ad94ef0ae5b2597f96fbbe29d4`;
- candidate manifest SHA-256:
  `bec40c1517c0f8f344bea100e41cf88d7e795e8d45b406d02a1b116449f1e249`;
- copied database SHA-256:
  `b415172856a336a1a00ac5118984159a4afab299fb2913d7bace3dcdc8c92d7c`;
- authority: read/copy the isolated key without exposing it and perform at most
  `91` additional DeepSeek attempts for exactly one replacement shadow report;
- prohibited: DingTalk/report alert send, production DB/output/control write,
  local or remote Docker mutation, Colima creation, software installation,
  L4/L5 activation, deploy, cron/service change, commit, push or merge.

Evidence gate: `allowed-with-label` for one L2 authorized shadow only. An L2
success is not L3 human acceptance, L4 release readiness, L5 production prepare
acceptance or report delivery.

| ID | TODO | Status | Required exit evidence |
|---|---|---|---|
| DS-L2-00 | Freeze the exact packet, candidate, DB and current worktree state; write plan/acceptance boundaries | complete | All named SHA-256 values rechecked; no new Provider call |
| DS-L2-01 | Run the latest full Python suite serially on one stable snapshot | complete | Exit 0, exact discovered test count and duration; no concurrent shared-output test process |
| DS-L2-02 | Re-run release/import verification, candidate DB preflight, shell/static gates and provider-free smoke | complete | All checks pass; `translation_provider_attempt_made=false`, `live_send=false` for preflight |
| DS-L2-03 | Initialize a new mode-700 semantic-fix shadow/runtime root; install all-off env and mode-600 key through the verified no-log path | complete | Exact root/release/DB/key metadata checks pass; no key content emitted |
| DS-L2-04 | Install and reserve the exact prepare/provider replacement permits under the isolated lock | complete | New authorization IDs bind the packet, release, DB, one report and remaining `91`-attempt cap |
| DS-L2-05 | Execute one host-native isolated DeepSeek shadow with translation gates only | complete — blocked | Terminal complete or blocked evidence; gates restored all-off in `finally`; no send or production write |
| DS-L2-06 | Verify attempt ledger, manifests, hashes, model, usage, retry count, output alignment and non-interference | complete | No active permit/journal/gate residue; `live_send=false`; `production unchanged` |
| DS-L2-07 | Apply automatic quality gates and prepare the blinded L3 review package | complete — fail-closed | 100% mapping/entity-number checks and five-true semantic verdicts, or explicit fail-closed reason |
| DS-L2-08 | Sync README, context pack, design/plan status, findings, progress and acceptance to the verified terminal state | complete | No stale no-key/no-provider claims; `git diff --check` passes |
| DS-L2-09 | Stop for owner L3 decision or a new bounded repair authorization | complete — stopped | No L4/L5/L6/L7 action inferred from this authorization |

Stop immediately before Provider transport if any packet/release/DB/runtime/key
metadata mismatch, stale/expired permit, dirty active gate, missing all-off
recovery, test failure or authorization ambiguity is observed. After the first
Provider attempt line exists, do not retry outside the authorized runner; a
blocked result must be preserved and a new exact replacement packet requested.

## Decisions

- No Reddit OAuth is available; do not plan around official API credentials.
- Primary collection route: local browser login state plus Reddit `.json` / DOM through Agent-Reach OpenCLI and browser-harness.
- TikHub is allowed only as a partial production collector, high-value thread completion path, or failure fallback.
- RSS is fallback for discovery and health checks, not proof of full comment capture.
- Deployment is local machine first.
- DingTalk delivery shape: concise Markdown digest plus structured artifact reference.
- Live DingTalk send, TikHub provider calls, and any credentialed browser collection require explicit gate and evidence.

## Phases

| Phase | Status | Purpose | Exit Evidence |
|---|---|---|---|
| P0 Product plan | complete | Consolidate product plan, execution checklist, and TODO | Plan files and docs exist with boundaries |
| P1 Browser read-only smoke | complete | Prove local browser `.json` route can read target Reddit content | Saved smoke artifacts, no writes |
| P2 Data contract | complete | Define structured post/comment/analysis/run schemas | SQLite schema, models, docs, tests |
| P3 Collector MVP | in_progress | Implement adapters and local dry-run collector | Browser/RSS adapters, adapter fixture dry-run, real browser payload ingestion, and retry policy pass |
| P4 Analysis MVP | in_progress | Add keyword, brand, topic, pain point, sentiment logic | Local rule tests pass; VADER/provider not added |
| P5 DingTalk delivery | in_progress | Generate dry-run body and gated live-send path | Fixture dry-run outbox, structured exports, and live-send mock tests pass |
| P6 Local scheduling | in_progress | Configure local launchd/cron wrapper | Manual run, missed-run check, bounded logs, and owner-gated scheduled dry-run evidence |
| P7 Historical backfill | in_progress — Task 29 review complete; provider-free parser repair is next | Backfill Beijing 2025-01-01 through 2026-07-11 into isolated structured staging only | Target `8baa6613...c29f2f`; 242 hydrated, 12 `comments_schema_drift`, 5 excluded; no Provider authorization requested |

## Current Next Step

Continue from local operation hardening to owner-gated runtime activation:

- Task 25 exact-installed manifest `dbaf6186...181ad` and bundle
  `28eb1847...e034`, exact-passed read-only preflight/admission, then consumed
  its single authorized network-none recovery. It returned
  `failed/strict_discovery_page_chain_invalid`, result SHA
  `10aded9b...ad7e`, and published no target DB. Failure postflight passed
  `21/21`; source/raw, Provider `702/1200` and production remained unchanged.
  The guard is consumed.

- Task 23 exact-installed packet `ab5386e7...7daa1`, manifest
  `edc6ec9b...e9c51` and bundle `de66baf3...4a01e` into fresh paths and
  consumed one permanent-guarded collect. All `32` new Provider attempts
  succeeded and the ledger advanced `670 -> 702`, but collect stopped
  `partial/candidate_failures`. Postflight passed `26/26`; source/raw and
  production stayed unchanged. Offline diagnosis found an under-modeled
  subreddit `crosspostCells` typename mirror and a nonterminal comments page
  with eight parseable comments, one `more`, `hasNextPage=true` and no cursor.
  Task 24 repaired those parser/failure-isolation defects locally; Task 25 later
  exposed a separate recovery page-chain contract defect.

- Task 14 option B has executed: cumulative `670/670` attempts succeeded, but
  collect remains `partial/budget_exhausted` and no acceptance/merge plan
  exists. Task 19 later transferred the reviewed Task 18 bundle and executed
  exactly one authorized network-none staging replay. It returned
  `complete/replay_complete`, proved equivalent source/target fingerprints and
  published replay DB SHA
  `3504190ab2b80ad1a003da27574455802f4184499eeaa7d458a6b771c3a8c638`.
  This is deterministic replay evidence, not complete historical coverage.
- Task 20 local verification is complete for append-only budget-extension and
  hydration-resume authorization, bounded round-robin discovery, and offline
  strict discovery reindex. Evidence is combined `243/243`, heavy
  validation/replay/reindex `108/108`, full suite `445/445`, independent review
  with no P0/P1, and canonical `22/22` manifest SHA
  `347c6ede1fe36852509dffe051fa7bf2b4d0c1e24ead8dda1af085bc44ff9d94`.
  The historical source is still partial; the overall backfill is not complete.
- Task 21 transferred the exact reviewed bundle, passed `20/20` preflight and
  consumed its one authorized network-none staging reindex. It returned
  `failed/strict_discovery_schema_unknown`; no target DB was published. All
  `14/14` postflight invariants passed and production/source/raw remained
  unchanged. Read-only diagnosis found `35/670` legacy pages rejected by the
  strict whole-payload wrapper uniqueness rule.
- Task 21R completed that local RED-to-GREEN repair. Exact mixed-wrapper and
  negative fixtures pass; reindex is `26/26`, related regression `200/200`, and
  the complete-runtime serialized suite is `452/452`. The new canonical
  `22/22` candidate manifest SHA is
  `88f3d58c89980ed0c685796c340c6752c11f5394e61409f6beeb8a4303b3938f`.
  No subagent or independent reviewer was used per owner instruction.
- Task 26 completed the authorized local RED-to-GREEN repair. Focused
  reindex/recovery passed `38/38`, related bundled-runtime regression passed
  `407/407`, and the complete bundled-runtime suite passed `634/634`. Manifest
  SHA is `d375b127...b38d17`; deterministic bundle SHA is
  `a265dc1f...dadfed`; local review passed `19/19`.
- Task 27 completed the exact-authorized network-none staging recovery. Preflight
  `7e657b94...01f8c`, admission `9e88981a...1cca2`, recovery result
  `465b4aa6...7de19`, target DB `56d74951...8570a4` and final postflight
  `95bad68f...5bb93` are recorded in the Task 27 report. No Provider call or
  production write occurred.
- Task 29 completed the post-Task-28 read-only freeze and fail-closed review packet. All 12 failed candidates are `comments_schema_drift`; packet `c949d101...0cae7` requests zero Provider attempts and generates no CLI resume authorization. The next safe batch is a provider-free local parser contract repair; only after fresh post-repair evidence may a new exact Provider packet be considered. Production merge, Git push and DingTalk remain separately prohibited.
- Historical backfill must remain no-push: no DingTalk/public artifact/report
  delivery, no production merge, no deploy, and no Git push.

- Prepare launchd install acceptance checklist only if owner authorizes scheduler installation.
- Dedicated Chrome profile path is `~/.reddit-voc/chrome-profile`; Reddit login state must remain manually verified before browser collection.
- For browser-harness collection, use a CDP-enabled repo-external profile such as `~/.reddit-voc/chrome-automation-profile` with `--browser-cdp-url http://127.0.0.1:9333`.
- Current browser gate is Reddit login-required; do not treat file-level cookie presence as a usable session.
- Keep issue summary, missed-run check, and bounded log retention green in local dry-run loops.
- Do not install scheduler or execute another DingTalk live send without explicit authorization for that run.
- Treat the DingTalk webhook URL/token as runtime secret only; do not persist it in repo artifacts.
- Keep Agent-Reach Reddit backend as a pending optional route until OpenCLI or rdt-cli is enabled.
- Keep local dry-run loop green with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.

### CRG-01 — Candidate registry 本地治理闭环（2026-07-27）

- [x] 区分历史 `tmp/**/candidate-registry` 夹具与正式 `output/reddit-voc-candidate-registry`。
- [x] 清点正式 registry 的 `entries/events/commits/runs` 四类不可变记录。
- [x] 对正式 registry 执行现有只读 validator，确认跨记录关系、schema 与事务完整性通过。
- [x] 将 candidate registry 深度治理标记为本地完成，不创建新 candidate、不修改 registry。
- [x] CRA-01 已安装并 bootstrap 独立 LaunchAgent；`registry_automation_enabled=true`，空 inbox fail-closed idle。

状态：`local_registry_governance_complete_automation_armed_idle`。自动化仅可处理精确 SHA 绑定的本地 reviewed request，并停止于 append-only registry；不构成 promotion、deploy、remote write、provider call、database write 或 live send 授权。

### CRA-01 — Candidate registry 增量自动接入启用（2026-07-27）

- [x] 新增 canonical request + reviewed profile SHA 双绑定的一次一请求 runner。
- [x] 新增 `enabled=true` 本地配置，固定 candidate-only/no-production side-effect 边界。
- [x] 新增独立 LaunchAgent，`RunAtLoad=true`、`StartInterval=900`，不改 collect/report 任务。
- [x] 新增聚焦用例覆盖 idle、exactly-once、profile SHA 漂移和边界篡改。
- [x] bootstrap 后首轮 `status=idle`、exit `0`、stderr 为空，正式 registry tree 未变化。

状态：`registry_automation_enabled_armed_idle`。当前无 reviewed profile/request，因此没有创建 candidate；后续只有在 inbox 出现 canonical request 且 profile 路径受限、SHA 精确匹配时才进入现有 local-only orchestrator。

### Task 29 — Post-Task-28 Provider continuation review（2026-07-27）

- [x] 远程只读冻结 Task 28 隔离 target；校验 DB SHA、integrity/FK、candidate/batch/checkpoint。
- [x] 以 manifest 和 provider-attempt ledger 交叉确认 `969/1200`，不对累计 checkpoint 计数求和。
- [x] 绑定 12 个失败候选；确认 `comments_schema_drift=12`、detail batches `10`、漏分批 `0`。
- [x] 生成 canonical mode-600 review packet并通过本地校验。
- [x] Provider 请求上限固定为 `0`，不生成 CLI resume authorization。
- [x] 下一项：provider-free `comments_schema_drift` parser/fixture 修复与回归验证。

状态：`task29_review_complete_local_contract_repair_required`。Provider、permit、production、remote write、database write、live send、Git push 均未授权或执行。

## Task 30：comments_schema_drift provider-free 结构回归（2026-07-27）

- [x] 以只读 SQLite + 只读 `.json.gz` 工件提取 12/12 失败响应的脱敏结构；未复制正文、用户名、URL 或原始 payload。
- [x] 确认 12/12 均匹配帖子身份，`commentForest.trees=[]`，终止页 `pageInfo={commentCount:null,hasNextPage:false}`；4 个形态差异仅来自外围 subreddit/profile 元数据。
- [x] 确认当前本地终止页 schema allowlist 已精确覆盖该形态，不扩大非终止页、cursor 路径或身份校验。
- [x] 新增端到端组合回归 `test_empty_terminal_nullable_count_shape_hydrates_without_schema_drift`；仅测试文件变更，生产代码变更为 0。
- [x] 新增用例 `1/1 OK`；相邻串行回归 `4/4 OK`。
- [x] 证据：`tmp/task30-comments-schema-drift-20260727/sanitized-shape-receipt.json`（SHA-256 `fe692cd564d6350be087a0589a6c3f3585c52d533839ef8ad05d0fb61a314323`）与 `tmp/task30-comments-schema-drift-20260727/task30-regression-receipt.json`。
- [x] 边界：Provider 请求 0、数据库写入 0、远端写入 0、生产动作 0；未生成新状态冻结。
- [ ] 下一项：取得明确 staging DB 写入授权后，仅用已归档的 12 个 comment 工件执行 archived-only repair，并生成 fresh state freeze；继续保持 Provider 请求 0。

状态：`task30_regression_complete_staging_archived_repair_authorization_required`

## Task 31：staging archived-only recovery 授权前置批次（2026-07-27）

- [x] 只读复核 Task28 source DB：SHA 未变，integrity `ok`、FK `0`、candidate `242 hydrated / 12 failed / 5 excluded`。
- [x] 只读复核 12/12 `comments_schema_drift` comment 工件齐全，当前无活跃 backfill 进程。
- [x] 确认 `recover-collection` 从固定 source DB + read-only raw archive 构建新的 recovery target；Provider executor 硬禁用，源 DB/raw 不修改。
- [x] 绑定 Task26 bundle SHA `a265dc1f1334e71d592d2cc722f946ba2d1b5ed39336ee6d02bde6a1b8dadfed` 与 release manifest SHA `d375b127d1e0ac282b5c714f8882e0c8db6a0792cc703273fb50e93ba2b38d17`。
- [x] 生成 fail-closed 前置包 `.superpowers/sdd/task-31-staging-archived-repair-preflight-packet.json`；`execution_enabled=false`、`cli_authorization_generated=false`、Provider cap `0`。
- [x] 本批证据等级为 `L3-staging-read-only`；未传输 bundle、未创建远端目录、未创建 target DB/report。
- [ ] 取得明确的新 staging recovery target DB/report 写入授权后，生成 exact executable authorization，并执行 network-none `recover-collection`。

状态：`task31_execution_admission_blocked_stale_pinned_bundle_no_database_write`

### Task 31 执行 admission（2026-07-27）

- [x] 用户明确授权创建新的隔离 staging recovery target DB/report；source DB/raw 固定只读、network none、Provider cap `0`。
- [x] 即时 admission 通过：source DB SHA 未变、目标根目录不存在、无活跃 backfill、`unshare --net` 可用。
- [x] 生成 execution authorization，SHA-256 `22b050a2f3cc0b9c412f9d2c1890b2f585bac44bf70f939bf5122ba159dd929d`。
- [x] 固定 Task26 bundle 已传输并安全展开；bundle 与 release manifest SHA 均精确匹配。
- [x] runtime admission fail-closed：pinned Task26 bundle 缺少 `_REVIEWED_COMMENT_CURSOR_PATH`，不能证明包含 Task30 终止页修复。
- [x] 未调用 `recover-collection`；target DB/report 不存在，output 为空，source DB 与 Provider ledger 未变化。
- [ ] Task31R：从当前 reviewed source 生成新的 manifest + deterministic bundle，先通过终止页 regression/release review，再申请新的 exact execution authorization。

证据：`tmp/task31-staging-archived-repair-preflight-20260727/execution-admission-failure-receipt.json`，SHA-256 `edb8f2802e4bda7f8cd7212335c49a395af7b9bfb356af9ee18d7582a304cbb1`。

## Task 31R：fresh minimal-overlay recovery bundle（2026-07-27）

- [x] 新增终止页组合回归 `1/1 OK`；相邻 cursor/hydration 门禁 `4/4 OK`。
- [x] collection-recovery 在 Codex bundled Python 下 `2/2 OK`；系统 Python 缺少 SQLite `serialize()` 的环境失败已隔离。
- [x] 以 Task26 bundle 为固定基线，仅 overlay 当前 `src/reddit_voc/backfill_provider.py` 并刷新 bundle 内 manifest。
- [x] fresh manifest SHA `748d02fe710105003f3adffbd605b8c7c445b95c0de2832fb7c0ea5a02a6d77a`；bundle SHA `f455b809258fa02ba3a677d842572341af11a66c4ea8d54133b00007c3c3c772`。
- [x] 双 bundle deterministic equality 通过；24 个成员集合不变，差异严格为 manifest + `backfill_provider.py`。
- [x] bundle 自身 runtime smoke 通过：release manifest 可加载、terminal allowlist 匹配、`_ForbiddenProviderExecutor` 可导入、`recover-collection --help` 可加载。
- [x] local release review `approved_candidate_only`，SHA-256 `3ea4b7b8158b75e98e7273b40843233a738a66ca60a78040daf86bfea8e29e79`。
- [x] 生成 fail-closed preflight packet `.superpowers/sdd/task-31r-fresh-bundle-preflight-packet.json`；未生成 CLI authorization。
- [ ] 取得绑定 fresh bundle SHA 与全新 `task31r` remote root 的 exact authorization 后，才可传输并执行 network-none recovery。

状态：`task31r_bundle_approved_new_exact_authorization_required`

## Task 31R fresh-bundle exact authorization gate (2026-07-27)

- [x] Refresh remote state using a read-only admission probe.
- [x] Confirm source DB SHA `8baa66135aa58e34c83c7b1d7fd3170adf05f7fdeb342363f3cac13459c29f2f`, integrity `ok`, and FK violations `0`.
- [x] Confirm candidate state `242 hydrated / 12 failed / 5 excluded` and Provider attempts `969 / 1200`.
- [x] Confirm no matching recovery process, fresh root absent, stale failed root present, and `unshare -Urn` available.
- [x] Persist local read-only receipt SHA `562cc2918f9d084884be5e81e597c01dd128250c1760216200f8d5360e7ef3de`.
- [x] Generate non-executable exact authorization request SHA `d691cbfb3ef7e579e353735149e78cffd6fe57b0c1d6ba68914ece34db7ab92f`.
- [ ] Receive explicit authorization bound to fresh bundle SHA `f455b809258fa02ba3a677d842572341af11a66c4ea8d54133b00007c3c3c772` and new remote root `/opt/reddit-voc-staging/task31r-comments-schema-recovery-20260727`.
- [ ] Only after that authorization, generate an executable authorization artifact and run the bounded staging recovery.
- [ ] Verify postflight target counts, source immutability, Provider count, integrity, FK state, and write-set receipt.

Current gate: `task31r_exact_authorization_request_ready_explicit_db_write_authorization_required`.
Generic continuation does not authorize bundle transfer, remote-root creation, target DB/report creation, or `recover-collection`.

## Task 31R authorized execution runtime admission (2026-07-27)

- [x] Receive exact authorization bound to fresh bundle SHA, new isolated remote root, target DB/report creation, source/raw read-only, network none, and Provider cap 0.
- [x] Generate executable authorization and pass immediate source/candidate/process/root/network preflight.
- [x] Create `/opt/reddit-voc-staging/task31r-comments-schema-recovery-20260727` and transfer the exact bundle plus authorization artifact.
- [x] Verify remote bundle SHA `f455b809258fa02ba3a677d842572341af11a66c4ea8d54133b00007c3c3c772` and execution authorization SHA `1f704519b1fcfb2acea065244be2150755f18ebc5f7984beb841bb08dac02a7c`.
- [x] Verify extracted manifest/provider SHA and import `_REVIEWED_COMMENT_CURSOR_PATH` plus `_ForbiddenProviderExecutor`.
- [x] Fail closed before `recover-collection`: remote `/usr/bin/python3` uses SQLite `3.37.2` and lacks `Connection.serialize/deserialize`; no additional Python 3.11+ runtime was found.
- [x] Confirm recovery target DB/report absent, source DB SHA unchanged, and Provider request count unchanged at `969`.
- [x] Persist matching local/remote blocker receipt SHA `eb70c98f3eb6866ae83c4b8dcabef00d0579d739d2eddc729251016a25901722`.
- [ ] Prepare and review a fresh remote-compatible runtime solution; any changed bundle/runtime input requires a new exact authorization before execution.

Current gate: `task31r_execution_blocked_remote_python_missing_sqlite_serialize_no_recovery_write`.

## Task 31S Python-without-serialize compatibility candidate (2026-07-27)

- [x] Confirm `recover-collection` reaches `_open_approved_reindex_source_connection`, which required `Connection.serialize/deserialize`.
- [x] Preserve the serialize path when available and add a pinned SQLite backup fallback when unavailable.
- [x] Verify descriptor SHA before and after backup while retaining inode identity and immutable source checks.
- [x] Add an end-to-end collection recovery regression that forces the backup fallback.
- [x] System Python without serialize: collection recovery `3/3 OK`.
- [x] Bundled Python serialize path: collection recovery `3/3 OK`.
- [x] Bundled Python forced fallback: inode/path-swap safety regressions `3/3 OK`.
- [x] Build Task31S twice with deterministic equality; bundle SHA `694bc6efba905bd8c74515338544107d256afd6f6e8bbbc7ce8154ad452c66b2`.
- [x] Confirm 24-member set unchanged and changed members strictly equal manifest plus `src/reddit_voc/backfill_validation.py`.
- [x] Approve local candidate review SHA `cc0901e0eccb033244cf342a1b699a30133bea632e66d0a9d354abee551fada5`.
- [x] Generate non-executable preflight SHA `22f131d4e7ac079848e493004d2fc6511fe87e5f776f9e925ce4236ec51e5fb7` and authorization request SHA `7d3e54cd9268bbb440780a076292464a7252df59b02b27add422e211122efd81`.
- [ ] Receive explicit authorization bound to Task31S bundle SHA and the fresh `/opt/reddit-voc-staging/task31s-comments-schema-recovery-20260727` root.
- [ ] After exact authorization, run immediate remote preflight and network-none recovery; never reuse or modify the Task31R root.

Current gate: `task31s_bundle_approved_new_exact_authorization_required`.

## Task 31S authorized execution path-topology admission (2026-07-27)

- [x] Receive exact authorization for Task31S bundle SHA `694bc6efba905bd8c74515338544107d256afd6f6e8bbbc7ce8154ad452c66b2` and `/opt/reddit-voc-staging/task31s-comments-schema-recovery-20260727`.
- [x] Generate executable authorization SHA `5508ee2f641aaf7495dbc004ceba7e2ba8b57f9f3365a23c4dd090087e261f29`.
- [x] Pass immediate source/candidate/Provider/Python/network preflight SHA `f031fda5b88db850883599ec40e090fb565aa4a432aff176c6bcbe0b5069371b`.
- [x] Create the exact authorized Task31S root, transfer exact bundle/authorization, and pass runtime admission SHA `c6c826aa246cb19b05119bee89d5a887621e9b9fcca66b6d7470bb9519abbde6`.
- [x] Invoke network-none `recover-collection` once; CLI failed closed before target creation with `reindex_path_outside_run_root`.
- [x] Confirm target DB/report absent, source DB SHA and integrity/FK unchanged, candidate state `242/12/5`, and Provider count `969`.
- [x] Persist matching local/remote blocker receipt SHA `a34864b0c671c5c358624070279e700cae48a59b1c46fab7604c95a40bbb282b`.
- [x] Confirm the CLI contract requires target parent to descend from the resolved source DB parent and remain outside the raw archive.
- [x] Verify compatible Task31T root is absent and generate non-executable preflight SHA `64334c3440caa032525505b8666ce02594538810a785b1a73fcc51e307143fdb`.
- [x] Generate Task31T authorization request SHA `9b74f9fb5ffdc44e059289342e911b63da2490043153d7705ad6ce406adbde28`.
- [ ] Receive explicit authorization bound to the compatible Task31T child root; generic continuation is insufficient.

Current gate: `task31t_compatible_root_ready_explicit_write_authorization_required`.

## Task 31T compatible-root authorized execution timestamp gate (2026-07-27)

- [x] Receive exact authorization for the compatible Task31T child root and Task31S bundle SHA.
- [x] Generate executable authorization SHA `50e3614ab2749d81ac484856f26c7933e57484147aa1d12bbc6ade6a8f00ea98`.
- [x] Pass compatible-topology immediate preflight SHA `0c21942486edd1f69b6dcd0203f6a8146900329370040eb19bcc227db0be988e`.
- [x] Create Task31T child root, transfer exact inputs, and pass runtime admission SHA `7ca31c32d644fdb4e8ede30dd01f5eb42347448ac4d35312d24004b805efb242`.
- [x] Invoke network-none recovery once; remote Python rejected `2026-07-27T11:42:19Z` with `collection_recovery_timestamp_invalid` before target creation.
- [x] Prove remote Python rejects `Z` but accepts semantic-equivalent `2026-07-27T11:42:19+00:00` with UTC offset zero.
- [x] Confirm target DB/report absent and source SHA/integrity/FK, candidate `242/12/5`, and Provider `969` unchanged.
- [x] Persist matching local/remote timestamp blocker receipt SHA `d982da11302d542b16e5aa955e8f19d48abc1215435682391a43304e6ecd70f2`.
- [x] Generate non-executable one-shot retry preflight SHA `e06b6b044b6656b6c6f0ad41fbb2e7bf773e70b0e74e61de9aaddd936fe043f6`.
- [x] Generate retry authorization request SHA `7efeb9ba205c545b26e9661b2d67f564537ce2dd6d525b4cdbd0b50c35d124e8`.
- [ ] Receive explicit authorization for one timestamp-normalized retry while preserving all first-attempt evidence.

Current gate: `task31t_timestamp_normalized_one_shot_retry_authorization_required`.

## Task 31T timestamp-normalized one-shot retry result (2026-07-28)

- [x] Receive exact one-shot retry authorization preserving all first-attempt evidence.
- [x] Generate retry execution authorization SHA `63e1c053985c39638cdf0efb01fe191f6a14a1e4810a77213f42358d00a03091`.
- [x] Confirm preserved output set, source/candidate/Provider state, target absence, and normalized timestamp before retry.
- [x] Pass retry runtime admission SHA `07bf96cbdada7f74e9a247b9ff401526bbe31b377a8ac2e3790181ef9a62adbf`.
- [x] Invoke exactly one network-none retry using `2026-07-27T11:42:19+00:00`.
- [x] Retry failed closed with `schema_drift_recovery_page_missing`, `database_write=false`, and Provider attempt false.
- [x] Verify failed recovery report and retry stdout payload are equal; SHA `2271478e81b1e9de6921b3a885c146ee9620b12e2d3ebf6184d37f15bcbfa662`.
- [x] Confirm target DB/sidecars absent, recovery residue `0`, source SHA/integrity/FK unchanged, candidate `242/12/5`, and Provider `969`.
- [x] Persist matching local/remote retry postflight receipt SHA `8cf637904e26cbb7b662697e18dbe171a69a6b9f5dea34e6f4b2ba62a6b58797`.
- [ ] Task31U: implement and review a comment-only archived recovery path that does not require a recovered discovery lane.
- [ ] Generate a fresh deterministic bundle and request new exact authorization before any further remote recovery.

Current gate: `task31t_retry_consumed_comment_only_recovery_implementation_required`.


## Task31U - comment-only comments schema recovery candidate (2026-07-28)

- Implemented local-only recovery support for committed discovery plus comments_schema_drift.
- Failed-candidate scope is derived only from failed/comments_schema_drift snapshot rows.
- With zero recovered discovery lanes, recovery requires an empty discovery delta and skips discovery writes.
- Focused gates: new comment-only 1/1 OK; collection recovery 4/4 OK; source snapshot/identity safety 4/4 OK.
- Deterministic Task31U bundle SHA: 37237551b3e66e8481cb19099c6cf328e2da943355135a0b83c58f8121cb52c3.
- Release manifest SHA: 75c7d79853298fc81f2a411733d0dfc9a1c817a63766d95fc958308307df9127.
- Validation module SHA: 28033bc29f3cb20013ed4907115fba5cbbc3115201c29d54abc75ac111c3f25f.
- Local release review SHA: 8231c438c3017c300c77f8a7bcc747106ddd65f59ca4d4e29efadf44129996ca.
- Non-execution remote preflight SHA: 62f20f7a05217a1cba9111bd06b105f3a00b47db7a4f5b59354c979c21a8d31b.
- Remote authorization request SHA: 4c89662fc67e34c2c285edc6c343e7a291286cd3e4c4900c339eabe8a19d6af4.
- No SSH, transfer, remote directory creation, provider call, database write, deploy, live-send, or git action was performed.
- Proposed fresh compatible root: /opt/reddit-voc-staging/task28-5b0ff5afc5bac1df7907bcd8fd2fa2a3d335918f97471c378d4d405db194cd63/backfill_momcozy_20250101_20260711/task31u-comments-only-recovery-20260728.
- Current gate: task31u_remote_execution_explicit_authorization_required.


## Task31U remote admission blocker (2026-07-28)

- Explicit Task31U authorization was admitted only for the exact pinned source parent and fresh Task31U child root.
- Local bundle SHA matched the authorized SHA.
- Remote admission stopped before all writes with source_or_raw_missing.
- Read-only diagnosis confirmed the exact authorized source parent, source DB, and raw archive are absent.
- The fresh Task31U root remains absent.
- No transfer, extraction, recover-collection, target/report creation, provider call, source/raw write, old-root write, live-send, deploy, or git action occurred.
- Blocker receipt SHA: 97a6911fc7a370cf46a7b7f8d28b114048e6b42836a2e6ec525726510ecc856a.
- Current gate: task31u_authorized_source_parent_missing_fresh_authorization_required.


## Task31U sudo read-only admission correction and pass (2026-07-28)

- The prior source-missing blocker was a permission false negative caused by task28 root:root mode 0700.
- Correction receipt SHA: c6c2061bd8255c22c62a7dccd982f44ab70e69a034d1f3dbcd9937e110cfe9d8.
- Sudo read-only admission passed with source SHA 8baa66135aa58e34c83c7b1d7fd3170adf05f7fdeb342363f3cac13459c29f2f, integrity ok, FK 0, Provider 969/1200, and no active recovery process.
- Candidate state: 5 excluded, 12 failed comments_schema_drift, 147 hydrated without reason, 95 hydrated unresolved_more.
- Raw diagnostic inventory: 1024 files, SHA 145abf44dd743110913f944cd3791bac03bd7a901a8d1cc557897693cba8c509.
- Task31U root remains absent; transfer/write/provider/target/report counts remain zero.
- Read-only admission receipt SHA: b50fc466a2cdb3afb41f63d32020a6d85ed369cd1d8fb06347dcbcbf30be86e2.
- Fresh remote execution authorization request SHA: 88480f222d39d66b425b69e16ba112a9693f386ff76d7513c7ac614352a0883b.
- Current gate: task31u_remote_write_and_recovery_explicit_authorization_required.


## Task31U authorized remote execution result (2026-07-28)

- Prewrite admission passed and the exact authorized bundle was transferred to the fresh Task31U root.
- Bundle SHA, 24-member safe extraction, validation SHA, manifest SHA, and Python 3.10 runtime were verified.
- recover-collection ran once under network-none plus a mount namespace with source parent/raw read-only and Task31U root writable.
- Execution failed closed with schema_drift_recovery_batch_mismatch.
- Recovery output: database_write=false, provider_call=false, provider_attempt_made=false, live_send=false.
- Target DB and sidecars are absent; temporary recovery residue is empty.
- Failure report SHA: 3112f509273b35a759dad967bab187c0004c8d5d34d82e79a8bc75c87af1803e.
- Postflight passed: source SHA/mtime/integrity/FK/candidate state/Provider ledger/raw inventory and all old-root fingerprints are unchanged.
- Task31U execution authorization is consumed; no retry is authorized.
- Execution receipt SHA: d8b797b46726c270120edc7303c9373b7393fe76de627f5797efcea856d06c9d.
- Current gate: task31v_local_mixed_batch_scope_fix_and_fresh_candidate_required.


## Task31V local mixed-batch scope candidate (2026-07-28)

- Reset helper now scopes batch validation and writes to affected rows where status is failed or stop_reason is comments_schema_drift.
- Unrelated complete historical batches and hydrated candidates remain untouched.
- Focused gates: new mixed-batch scope 1/1 OK; collection recovery 4/4 OK; source snapshot/identity safety 4/4 OK.
- Deterministic Task31V bundle SHA: c2958435657dee1da0b301d07fdd02a9faab43cd281a4ba2043dcf6c9abbfc03.
- Release manifest SHA: 8866d2f3226b80fd71ff1fa6c0c20d916bac7f4e0e1d321178557b830b1eca70.
- Validation SHA: 3bae0a3929ea49b5bcf3ea38bf24d18b69ce1a22173c2195f8a0b198cb16cb5b.
- Local review SHA: 9ed74202888d233c684262e41380fc0472979d5b97603af84e70c108de7078c5.
- No remote reads/writes, transfer, Provider call, recover, target/report, deploy, live-send, or git action occurred.
- Read-only batch-scope preflight SHA: 9cce201db762a68140b400784b2f09dfed82b956c36c1ca4abfd2afefaff978e.
- Read-only batch-scope authorization request SHA: e906be93d4a4bcd9975b52b2dafbeddd2f583a11cde6480ef5b4a8f959fc1481.
- Current gate: task31v_remote_readonly_batch_scope_explicit_authorization_required.


## Task31V remote read-only batch-scope blocker (2026-07-28)

- Local Task31U receipt and Task31V bundle SHAs matched the authorization.
- Sudo read-only admission confirmed the proposed Task31V root is absent and the source SHA matches.
- The real source has zero detail batches where status is failed or stop_reason is comments_schema_drift.
- Task31V affected-batch selector therefore has no rows and is not eligible for remote execution.
- The gate failed closed before transfer, root creation, Provider, recover, target/report, or any remote write.
- Blocker receipt SHA: 9ad7d1c43ca6e03b00a6d116d457c690e170d70a2881139e0fe06ddab5969a1f.
- Current gate: task31w_local_batchless_comments_recovery_candidate_required.


## Task31W local owner-batch replay candidate (2026-07-28)

- Hydrator contract requires a complete owner batch containing a newly pending candidate to be replayed, not ignored.
- Reset helper now selects owner batches by failed candidate membership.
- Allowed owner states are complete/null or failed/comments_schema_drift; unrelated batches are untouched.
- Extra owner members must already be hydrated or excluded.
- Focused gates: complete-owner E2E 1/1 OK; collection recovery 5/5 OK; mixed reset 1/1 OK; source safety 4/4 OK.
- Deterministic Task31W bundle SHA: 87f4b29d23e9c8ad7da7682844fb70181feb162ad71c8bc8cd55bfe8195b1549.
- Release manifest SHA: 06498304ce38cf8b9ba0810d493737a6cafcaa4acd5c6a065f6959edb6d995bd.
- Validation SHA: ecfd3ece7f23c8162598a51677393f919e80eafc920fb3931263de9e12eb4d93.
- Local review SHA: 4ea78c22df42d39dd299cba1abf41fda06e0fb661db21615cc7bee4c2dc633d3.
- No remote action, transfer, Provider, recover, target/report, deploy, live-send, or git action occurred.
- Owner-batch preflight SHA: 2758825e2f37d4556443033d1f9be41f758c53574362c4c6098b554216e917a0.
- Owner-batch authorization request SHA: 8a1d15af43b8e11fb88aede9c7114b0f1db9502920e84e8abde8c6bc68e3ba26.
- Current gate: task31w_remote_readonly_owner_batch_explicit_authorization_required.


## Task31W remote read-only owner-batch admission pass (2026-07-28)

- Local Task31V blocker and Task31W bundle SHAs matched.
- Source SHA/integrity/FK/Provider/raw inventory matched pinned evidence.
- The 12 failed candidates map to 6 complete/null owner batches with 6 valid detail artifacts.
- Owner batches contain 178 members: 12 failed candidates plus 166 hydrated/excluded terminal members.
- Comments checkpoints/artifacts are 12/12 and structured residue is zero.
- Task31W root is absent; active recovery process, remote write, Provider, transfer, target/report counts are zero.
- Task31U root fingerprint pinned to bf1b9f5a735b13ec4e77ad37c45d76680dfebfb9c2cccf83f78df8fb47825526.
- Read-only admission receipt SHA: 6f6bc74cf2645a7b4c0130ce3a18d3c586558ddad2f0fd8e3e649fe481f1b14d.
- Execution authorization request SHA: db1e955742d33e23a2b3704a7dab9a026ca1573e9b4ff35d33bbef7daced9789.
- Current gate: task31w_remote_execution_explicit_authorization_required.

### Task31W remote owner-batch recovery execution (2026-07-28)

- [x] Validate Task31W readonly admission receipt and local bundle SHA.
- [x] Create the fresh Task31W root, transfer the bundle, and revalidate SHA.
- [x] Safely extract 24 regular relative members and validate module/manifest SHA.
- [x] Pass the execution preflight for source SHA, SQLite/candidates, 6 owner batches, 178 owner members, 166 extra members, Provider 969, raw inventory, and old roots.
- [x] Fail closed at the mount/network namespace gate before invoking recover-collection.
- [x] Confirm source/raw/Provider/candidates/old roots unchanged; target/report/temp residue absent; active recovery 0.
- [ ] Obtain a new exact authorization for a readonly namespace diagnostic. Do not reuse Task31W for recovery.
- [ ] After the diagnostic is closed, prepare a separately authorized fresh-root recovery task.

### Task31W namespace diagnostic and production reporting plan (2026-07-29)

- [x] Run the authorized readonly namespace diagnostic with per-subgate output.
- [x] Identify `/sys/class/net` as a host-sysfs false-negative source inside the new net namespace.
- [x] Replace the gate contract with net namespace inode plus `/proc/net/dev` and `/proc/net/route`.
- [x] Pass the corrected readonly gate with only `lo`, zero routes, required mounts, source SHA unchanged, and recovery CLI calls 0.
- [x] Record the diagnostic receipt and production deployment/DingTalk acceptance plan.
- [ ] Build a new fresh-root recovery task; Task31W remains evidence-only.
- [ ] Implement governed prepared-outbox live send for daily reports.
- [ ] Implement real-data weekly report backend, outbox, scheduler, and receipts.
- [ ] Implement real-data monthly report backend, outbox, scheduler, and receipts.
- [ ] Obtain separate exact authorizations for production switch and each DingTalk canary send.

### Task31X fresh-root recovery admission (2026-07-29)

- [x] Build a new Task31X envelope around the validated Task31W application payload.
- [x] Bind the corrected namespace-aware gate and both Task31W parent receipts.
- [x] Pass shell syntax, forbidden sysfs probe, required procfs gate, safe-member, and reproducibility checks.
- [x] Produce Task31X bundle SHA `8260287ed8fd63333dfd35856576d3eac43f40ef5b5abcc41f85adcbae32f112`.
- [x] Pass remote readonly fresh-root admission with receipt SHA `de54718a8089da882fdc0f9e10a42d4d1b6ecc048ffeeb7426a55f484e03a6d5`.
- [x] Confirm Task31X root absent, remote writes 0, Provider calls 0, and recovery CLI calls 0.
- [ ] Obtain the generated exact authorization before creating or transferring to Task31X root.
- [ ] Execute one network-none recovery and complete immutable postflight.

### Task31X remote recovery execution (2026-07-29)

- [x] Revalidate authorization receipt, bundle SHA, source SHA, fresh root, and network-none capability.
- [x] Create the fresh Task31X root and verify the transferred outer bundle SHA.
- [x] Safely extract 4 outer and 24 inner regular relative members.
- [x] Pass the corrected namespace-aware network-none and mount gates.
- [x] Invoke recover-collection exactly once with Provider cap 0.
- [x] Fail closed on `schema_drift_recovery_comment_mismatch` without retry.
- [x] Confirm source/raw/Task31-Task31W unchanged, Provider 969, target absent, report present, and temp residue 0.
- [ ] Diagnose the comments recovery selection mismatch locally with a focused regression test.
- [ ] Build a new bundle and obtain a new exact authorization before any remote retry.

### P2E freshness automation closure (2026-08-10)

- [x] Restore P2D4 release continuity and identify the next unclosed collect-to-publication gate.
- [x] Run an L3 production read-only audit of cron, August 10 artifacts, database, runtime source, containers and public current.
- [x] Prove the August 10 direct failure is a CLI/collector ABI mismatch before Provider transport or database write.
- [x] Add a reusable daily runtime closure validator and focused tests.
- [x] Build and locally accept a single-file collector ABI/raw-artifact hotfix from the exact production preimage.
- [x] Build and test a fail-closed remote installer with exact preflight, atomic rollback and no-provider smoke.
- [x] Freeze a collector-only production gate and a separate August 10 collection retry gate.
- [x] Obtain exact owner authorization and execute the collector-only production gate.
- [x] After a passing install receipt, obtain separate authorization for the Provider/database retry gate.
- [x] Execute one non-replayable August 10 retry run and preserve all prior failure evidence.
- [x] Prove on a stable production snapshot that the database schema is already current and no production migration is required.
- [x] Build and validate the seven-payload source-receipt runtime closure in a local shadow.
- [x] Freeze a single-transaction remote install/read-only replay gate with full rollback.
- [x] Obtain exact authorization and execute the frozen G3 remote runtime/source-receipt transaction once; it failed closed before source receipt.
- [x] Execute the first authorized G3 transaction and prove fail-closed seven-target rollback on smoke-contract failure.
- [x] Correct the smoke import, add a real candidate runtime-smoke regression, and freeze retry1.
- [x] Obtain fresh exact authorization for the corrected-installer retry without reusing the consumed first authorization.
- [x] Obtain fresh authorization and complete retry1 runtime install plus read-only source receipt.
- [x] Independently validate database/cron/current/container invariants and container-visible runtime closure.
- [x] Build and validate the G4 data candidate in an isolated shadow under a separate authorization; data/report checks passed, overall admission blocked on 64 missing Chinese fields.
- [x] Keep public current unchanged because translation acceptance did not pass.
- [x] Read-only verify the existing 2026-08-11 07:00 collect / 08:00 bounded DingTalk schedule and active live policy.
- [x] Run a separately authorized G4T translation-delta gate for exactly 64 non-empty fields, then rerun G4 admission.
- [x] Recover and hash-bind the exact prior translation sidecars and 64-field missing set.
- [x] Build an independently validated 64-item provider source packet and no-Provider merge fixture.
- [x] Prove fail-closed rejection of source tampering, hash tampering and extra identities.
- [x] Freeze the exact G4T Provider gate and pass its no-call preflight.
- [x] Obtain explicit authorization for gate SHA `74d4a36900a9babc2b8399db30bc18e4038874591bb6fd129d41216399c67258` before any DeepSeek request.
- [x] Execute 12/24 requests for exactly 64 fields, merge locally, rerun translation audit and emit the passing G4T admission receipt.
- [x] Assemble a separately gated G5 local public candidate from the admitted base/reports/insights/merged translations and validate every UI route.
- [x] Obtain exact authorization and execute G6 production-candidate freeze plus read-only promotion-readiness auditing.
- [x] Freeze and byte-audit the exact G5 deploy package, while fail-closing public promotion because the 2026-08-11 natural source run is newer than the candidate.
- [ ] Obtain exact authorization for G6F to forward-port `daily_collect_20260811_0700` into a new local candidate without Provider, production writes, deploy/current switch or send.
- [ ] Only after a freshness-forward candidate passes should a separate deployment/public-current gate be proposed; DingTalk remains an independent effect.
- [ ] Add candidate-builder shadow automation, freshness watchdog and explicit promotion policy.
## G6R1-B5BR3 — Production dual-destination terminal activation

Status: `COMPLETE_L4_AUTHORIZED_LIVE_TERMINAL_ACTIVATION / NO_SEND`

- [x] Restore B5BR/B5BR1/B5BR2 continuity and distinguish two message parts from two destination receipts.
- [x] Re-read DWS Webhook send boundaries and keep all live sends fail closed.
- [x] Verify the corrected B5BR2 focused suite with the project runtime: `5/5` passed.
- [x] Confirm fresh L3 production preflight: double snapshot equal, zero blockers, activation absent.
- [x] Confirm exact bundle was installed root-owned and inactive; receipt states `activation_executed=false` and `dingtalk_send=false`.
- [x] Freeze a non-executable B5BR3 Owner authorization draft for one activation transaction only.
- [x] Obtain exact Owner approval of draft SHA-256 `feba95be7f5877dbf35e6d61bc4d1a16e617adcaa61a559f630ab3a0f3d20971`.
- [x] Run fresh L3 admission, create a fresh <=15-minute execution permit, execute once and verify the terminal marker/journal/current/cron postimages.
- [x] Independently inventory today's run without database access: collection exists, but no prepared-current/report payload or destination receipt exists.
- [x] Freeze B5BR4A preparation-only authorization for exact run `daily_collect_20260812_0700`; keep all Webhook sends disabled.
- [ ] Only after a verified current payload exists, freeze B5BR4B with exact payload hashes and one primary plus one secondary destination send.

## G6R1-B5BR4 — 2026-08-12 catch-up report delivery

Status: `COMPLETE_L4_AUTHORIZED_LIVE / B5BR5_R14_TRANSLATION_ACCEPTED / PRIMARY_AND_SECONDARY_2_OF_2_SENT / B5BR4A_R1_UNCONSUMED_SUPERSEDED`

- [x] Production scheduler/dual-authority activation is terminal and verified.
- [x] Exact 07:00 run exists; collector exited 0 and source batch is truthfully `partial`.
- [x] Confirm no prepared-current and no 2026-08-12 cron-report record without database access.
- [x] B5BR4A: bind one bounded late preparation slot, exact run/source state and Provider ceiling in a non-executable draft; Owner approved SHA `8118644f4cc668ec125765243049103a27e51d0c4704cb04f570bad0fb0d47cf`, but the authorization remained unconsumed and was later invalidated by its stale report-control hash.
- [x] Record exact B5BR4A Owner approval; fresh admission stopped before permit creation because required network `reddit_voc_report_net` is absent. Approval remains unconsumed.
- [x] B5BR4N: exact Owner approval was consumed by one default-IPAM network-create call; Docker returned failure and left the network absent. No container, Provider, database query/write or Webhook action occurred.
- [x] B5BR4N Retry-1: concurrent executor consumed the exact authorized explicit-IPAM create; sudo journal and exact empty-network readback reconcile the postimage. This executor correctly stopped before duplicate creation.
- [ ] B5BR4A-R1: exact correction-only approval received, but keep it unconsumed while a concurrent B5BR5 supplemental/hotfix preparation lane is active on the same run; reconcile its terminal state before any duplicate Provider/prepare action.
- [x] B5BR5 r14: independently accept 92/92 Chinese translations, deterministic checks, five-dimension semantic verdicts, zero placeholders and 25/25 Provider terminal-success requests with zero retry/unknown.
- [x] B5BR5 send attempt: primary and secondary each received part 1/2 with HTTP 200 and terminal sent ledger; part 2/2 was never attempted for either destination; DB persistence failed and aggregate execution stopped.
- [x] Freeze and execute a recovery-only gate that projects the proven part-1 ledgers into DB and permits exactly primary-part2 plus secondary-part2; part1 was not resent and Provider was disabled during send.
- [x] Independently verify four terminal HTTP-200 delivery ledgers, four DB `sent` rows, one shared outbox hash, unchanged translation acceptance/prepared-current, and zero running report containers.
