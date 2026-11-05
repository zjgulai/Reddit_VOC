---
title: Wave 1 · PMO 对齐执行计划（方案 B：主干优先，v2 对抗审查修订版）
doc_type: plan
status: active
created: 2026-11-05
revised: 2026-11-05（v2：按对抗审查 B1-B8/H1-H13 修订）
owner: Pray
decision_date: 2026-11-05
evidence_base: pmo.luteos.com 全站实测 + 仓库代码/回执/测试交叉验证（9-agent 差距分析 + 1-agent 对抗审查，审查时点 2026-11-05 16:19 CST）
---

# Wave 1 · PMO 对齐执行计划（方案 B：主干优先，v2）

## 0. 决策记录（2026-11-05 Pray 拍板）

| # | 决策 | 内容 |
|---|---|---|
| D1 | 主方案 B 主干优先 | 先过 Stage 2 硬门禁（card.action 回调 + 动作账本主链），再填三条业务线；PMO 四个日期作为对外承诺切片 |
| D2 | 问数口径 | 11-09 验收 = 基于 07:05 日更 release 的只读问数：Reddit 单渠道，回答带 data_as_of / 覆盖分母 / 置信度，无绑定时 exact→family→category→unavailable 显式降级 |
| D3 | Bot 底座 | 复用 Main `apps/bot-gateway` + PMO `feishu_bot.py` 底座，Echo 只做事件路由 / card handler / 账本适配，不新建第三套 |
| D4 | 拖拽降级 | 11-15 交付 = Superset 深链 + 3-5 个保存视图（维度由 query log 高频项决定），不做字面拖拽台 |

### v2 关键修正（对抗审查后的事实基线，替代 v1 表述）

| # | v1 错误 | v2 修正 |
|---|---|---|
| C1 | 「producer round() 未修，11-06 07:05 会再挂」 | 07:05 路径是 `scripts/recompute_derivatives.py`，`f8a4226` 已修复**且已部署生产**；`v3_quarter_insights_public.py` 未部署、不在 07:05 路径。T1 降级为仓库一致性 PR（writer+validator 同一 helper），无假紧急 |
| C2 | 「保留 ws 为唯一入口」 | /sop Stage 2 原文要求 **WS长连接 + Webhook 双通道**；关 webhook 会削弱硬门禁证据。改为：双通道保留 + gateway 层按 `event_id` 去重；WS-only 须 PMO 书面同意（并入 X7） |
| C3 | 「PMO measuredActions 是账本，Echo 已有 1 条真实回写」 | PMO `POST /api/sop/telemetry` 是**无鉴权/无幂等/无状态更新**的聚合计数器；`business_actions` 6 条全部创建于 2026-11-03 16:35（同一批 seed）。**本地 JSONL 是唯一真源**，PMO 只收聚合计数与终态回写；「真实回写」表述废弃 |
| C4 | 「11-07~11-11 五个工作日」 | 11-07 周六 / 11-08 周日 / 11-09 周一 / 11-14 周六 / 11-15 周日。外部依赖确认死线前移至 **11-06（周五）EOD**；周末排产只排不依赖外部回复的任务 |
| C5 | 「按 L4 byte-range index 取 Range」 | L4 comment_index 是 V2-PLAN Wave 5 工件，生产不存在，且按 post 分组、服务单帖证据，**不能服务聚合问数**。T6 改为：发布后按 generation 构建本地索引（SQLite FTS / 内存索引），release token = pointer sha + manifest sha |
| C6 | 「M5 有 exact SPU 覆盖 2.9%」 | 生产 26,330 帖中 exact-SPU 67 帖（M9 25 / M6 23 / Air1 10 / V2 Pro 9 / BS03 8），**M5 为 0**；M5 走 family（49 帖 `m5-smart`，447 帖文本提及）。PMO bot-kit 示例命令正是「@Echo 查询M5…高频差评原话」——降级链是主路径不是兜底；exact→family→category 覆盖上限 198 帖≈8.5%（按 Momcozy 相关 2,331 帖口径另算） |
| C7 | 「206 例测试绿」 | 精确门禁 = `python scripts/run_backend_test_lane.py repository --enforce-known-failures`（208 模块/repository lane 170）+ `npm test && npm run lint && npm run build`（49 文件/249 用例）；known-failures baseline 不变 |
| C8 | 「管线自动刷新生产锁」 | `/opt/echo-agent-bot` 非 git checkout、无锁文件。改为：pipeline 写 `outputs/release-lock.json` 回执；CI 定时跑 `verify_workbench_lock.py --public-url` 漂移即红；仓库锁文件经 PR 更新 |

### 需向 PMO 披露的事故（11-06 随 X7 一并书面说明）

对抗审查验证 PMO telemetry API 时，空 body POST 被 200 接受并改写了 emily 候选（sop_candidates id=5）的 `updated_at`（2026-11-05T08:20Z）。需说明：①该写入为验证事故、非业务数据；②API 无鉴权/无校验/默认 slug=emily 是其自身完整性风险（建议 PMO 修复）；③`business_actions`/`sop_candidates` 全部为 2026-11-03 同批 seed，Stage 3 统计不应采用。

## 1. 对外交付切片（四项，对齐 PMO cap69-72）

| 日期 | PMO 能力项 | 我们交付（v2） | 与 PMO 字面口径的差异（已声明） |
|---|---|---|---|
| 11-09（周一） | cap69 多渠道数据查询 | @Echo 消息级只读问数 demo：golden answer set（release-backed 预生成，含 M5 family 级示例）+ 简单查询在线应答；query log 开始落盘 | 消息级先行，卡片回调在 11-13；Reddit 单渠道；M5 等 SPU 走 family 级降级 |
| 11-13（周五） | cap70 风险指数&机会洞察（milestone） | 晨报卡片 action 按钮上线（测试群 dry-run 通过）+ 本地 action ledger + **Stage 2 证据包提交** | 证据包「提交」与「解除 50% 封顶」是两件事，后者待 PMO 验收（X7） |
| 11-15（周日） | cap71 拖拉式多维分析 | Superset 深链 + 3-5 个保存视图（query log 窗口 11-09~15 一周，不足 ≥10 次/周的维度标 provisional） | 「拖拽台」降级为保存视图（D4） |
| 11-16（周一） | cap72 自动化品类洞察报告（milestone） | 品类报告模板 v1：**静态 provisional**，3-5 条人工结论（不带 L3 conclusions 契约——那是 V2 Wave 4 工件），只渲染 available 指标，发布走 radar `/dashboard/reports`（X5 Plan B 默认路径） | 非 report.luteos.com 自动发布（其为静态报告库，无可编程 API）；非回调驱动编译（T10 认领结果作为 v2 输入规划进 Wave 2） |

## 2. 外部依赖（确认死线 11-06 EOD，Plan B 切换死线 11-08）

| # | 依赖 | 找谁 | 需要什么 | Plan B |
|---|---|---|---|---|
| X1 | Main bot-gateway 仓库/版本/契约 | 周健 | apps/bot-gateway 访问权 + card.action 契约（PMO registry 已确认 Echo kit_ready=true/bot_live=true，但缺仓库与版本） | Echo 侧 shim 封装既有 ws/webhook 服务为兼容接口（写 ADR，Wave 2/3 归还组标准） |
| X2 | PMO telemetry 写入契约修复 | PMO | 共享 token/HMAC + 幂等键 + payload 校验 + status 字段（现状无鉴权，见披露事故） | 本地 JSONL 唯一真源；PMO 只在验收时人工导出聚合 |
| X3 | Echo 飞书应用 card.action 权限 | Pray | 应用后台开启卡片回调 + verifier/encrypt key。**11-13 硬前置**：11-10 未就绪则 T11 证据包整体移至 11-16，11-13 明确降级、不写「解除封顶」 | 无满足 Stage 2 的替代（url 按钮不算），只能延期不能降级 |
| X4 | Superset 访问权 + 29 张看板归属 | PMO/数据平台 | URL + 账号 + 看板清单 | radar 工作台内静态保存视图 |
| X5 | report.luteos.com 发布通道 | 品类平台 owner | 确认是否存在可编程发布 API（实测为静态报告库，默认无） | 默认走 radar `/dashboard/reports` 发布 + 链接登记回 PMO |
| X6 | pilot 群（品牌市场部 ≥5 真实用户） | Pray 引荐 | 群名 + 名单，**11-10 前到位（硬依赖）** | D6 闸门降级为「synthetic 10 问 + PMO 书面接受」，§5 R7 跟踪 |
| X7 | PMO 书面裁定 | PMO | ①Stage 2 按 /sop 全文执行下，WS-only 是否可接受（card.action 属制度定义，不再问）；②cap69/70 P2 标 100% 但代码为 0 的 RACI 修正；③证据包验收流程；④telemetry API 加固与 seed 清理 | 无 Plan B：未裁定前对外进度按 50% 封顶保守表述（§5 R7） |

## 3. 每日计划（日历感知：11-07/08、11-14/15 为周末）

### D0 · 11-06 周五（修复与基线日）

- **T1' 仓库一致性 PR**：`v3_quarter_insights_public.py` 四处 `round()` 与 `scripts/recompute_derivatives.py` 的 `_rate` 收敛到同一 helper（百分比 half-up 正确式：`math.floor(x*100+0.5)/100`，对 3.125 得 3.13）；writer+validator 共用；测试 2/64→3.13、1/64→1.56、0/0→None。普通正确性 PR，**非救火**（生产 07:05 路径已是修复版）。
  - **执行记录（2026-11-05）**：✅ 已完成——PR #7（`fix/rate-contract-unify`，cherry-pick 已部署热修 f8a4226 + 共享 helper `reddit_voc.rates.half_up_percent` + producer 4 处收敛 + drift-lock 测试 6 用例）；repository lane 全量门禁 exit 0（1907 passed / 1 known genuine / unknown_failures=[]）。
  - **新发现待办（fixture cleanup ticket）**：`tests/test_reddit_quarter_insights_public_projection.py` 3 例失败为预先存在——冻结 fixture `tmp/reddit-voc-v3/reddit_add_data_20260715_v1` 本地缺失，模块属 local-artifact lane（CI 不跑），10-30 基线冻结未逐模块覆盖。修复=恢复/重建 fixture 或将其显式降级为 skip-with-reason；处理人 Pray，建议 Wave 1 内关闭（不阻塞对外交付）。
- **T2 基线归档**：`api/export.csv` + `/api/backup.json` 双归档至 `docs/v2/wave1/pmo-baseline-20261106/`，记录 cap69-72 ↔ export 序号 20-23 映射与 seed 时间戳；X1-X7 请求全部发出（EOD 死线）；随附 §0 披露事故说明。
- **T3' 双入口受控测试**：向测试群发一条 @Echo，抓 ws/webhook 两边日志与群回复，确认是否重复回复（审查未发现重复日志，先取证再决策）；gateway 层 `event_id` 去重设计定稿；**双通道保留**。
- **T14' 锁漂移检测**：CI 加定时 `verify_workbench_lock.py --public-url`（现锁 101e1e… vs 现网 ed89ac…，锁指向的 11-03 代已被 GC）；pipeline 写 `outputs/release-lock.json` 回执；仓库锁文件经 PR 更新。
- **T16 reply_engine 抽取启动**：硬编码「3,591 篇/10-26」存在于 ≥5 处（`src/reddit_voc/feishu_ws_bot.py`、`feishu_webhook_server.py:101`、`scripts/server_feishu_bot.py:99/138/146`）+ 生产未入库的 `/opt/echo-agent-bot/server_feishu_ws.py`（自带一份 `generate_agent_reply`）；抽共享 reply_engine，所有入口 import；生产 ws 脚本纳入仓库或替换为 tracked 模块；grep 闸门覆盖 src/scripts/部署 bundle。
- **T17 systemd 单元入库**：`echo-agent-ws/bot/daily` 单元纳入 `config/systemd/` + 部署 runbook（生产为文件拷贝、非 git，不入库无法审计 T3'/T4 变更）。

**闸门**：T1'/T14' PR 绿（C7 精确命令）；11-07 07:05 scheduled success（K1 第 4 天）；/dashboard 浏览器实测渲染；双入口取证回执归档。

### D1 · 11-07~08 周末（不依赖外部回复的产出）

- **T5' 意图槽位解析**（fake transport，与 X1 解耦）：slot = brand/spu/family/时间窗/社区/情感/严重度；**飞书 3 秒 ack + 异步 worker** 应答（同步处理会被飞书重试→重复回复/记账）；`event_id`/`open_message_id` 幂等。
- **T6' release-pinned 索引**：发布后按 generation 构建本地索引（SQLite FTS 或按 product_binding 的内存索引），release token = pointer sha + manifest sha（防 07:05 切代读到混合代）；禁止每查一次扫 196MB comments；p95 ≤30s 压测。
- **T18 golden answer set**：必测集=PMO 官方示例「M5 本周高频差评原话」（family 级：`level=product_family`、`coverage=49/447`、`exact_spu=unavailable`）+ M9/M6 exact-SPU 正例 + 1 个无绑定 SPU unavailable 反例；覆盖分母按查询实体定义（M5 文本 447 ≠ Momcozy 相关 2,331，不混用）。

**闸门**：意图解析 ≥10 用例；索引构建 <10min、查询 p95≤30s；golden set 全部答案带 data_as_of（取自 `current-release.json.freshness.data_as_of_utc`，当前 2026-11-04T23:00Z）。

### 11-09 周一 · 对外交付①

- 交付内容见 §1；若 T6' 索引未就绪，demo 用 golden answer set + 既有 ws bot 在线应答兜底（**不承诺 11-09 交完整 query service**）。
- **闸门**：@Echo 群内问答端到端 ≤30s；降级文案正确；query log JSONL 落盘（字段含 `source=real_user|golden|test`，Stage 3 只统计 real_user）；07:05 scheduled success。

### 11-10~11 周二三（卡片回调 + 账本）

- **T5b card.action 路由**（X3 硬前置）：验签（签名无效→拒绝并记录，响应码按飞书规范防重试风暴；业务失败→200+toast）；operator allowlist；不长期落原文/open_id。
- **T8' action ledger（本地为真）**：状态机 claimed→done→verified 在本地 JSONL（映射 PMO 枚举：已认领/执行中/已回写）；仅终态同步 PMO `measured_action`（7 字段固定，`receipt_ref`=本地 action_id，**不得引用 11-03 seed 行**）；幂等键=event_id+action value。
- **T9 晨报卡 action 化 + dry-run**：同一 builder 向测试群发 dry-run 卡（不同 chat_id），保留旧 url 卡 fallback；测试群点击成功才算过。
- **T6 完整 query service**：基于 T6' 索引开放 SPU/family/主题/时间窗聚合查询。

**闸门**：验签测试（伪造拒绝）；幂等测试（重复点击不重复记账）；测试群 dry-run 点击成功；X3 未就绪则触发 §1 降级预案。

### 11-12 周四 · pilot + buffer

- **T10 pilot**（X6 硬依赖）：真实群 10 问 + 3 认领；X6 未到位→闸门降级为 synthetic + PMO 书面接受（R7）。
- 本日预留 buffer：前四日任何 slip 在此消化。

**闸门**：query log real_user ≥10 条、ledger ≥3 条新 action_id（时间戳 >11-12）、0 验签事故、pilot 反馈成文（返工率基线）。

### 11-13 周五 · 对外交付② + Stage 2 证据包

- **T11 证据包**（owner：Pray；存 `docs/v2/evidence/wave1/`，记 sha256）：app_id（生产 `cli_aa1d3c178db85d23`）、WS+Webhook 双通道日志、card action JSON 与回调回执、新 action_id 样本、query log 计数（real_user 口径）、release_id/data_as_of；「提交证据包」与「解除 50% 封顶」分开验收。
- cap70 里程碑收口验收。

### 11-14~15 周末 · 对外交付③④

- **T12 品类报告模板 v1（静态 provisional）**：Reddit 单源子集；3-5 条人工结论；26 指标列出 available 清单（RV-BR-01/02/04/05）与其余 22 项的 reason_code；发布走 radar `/dashboard/reports`。
- **T13 Superset 深链 + 保存视图**：query log 窗口 11-09~15 满一周；不足 ≥10 次/周的维度标 `provisional` 并写明选择规则与样本量。

### 11-16 周一 · 收官

- cap72 验收 + Wave 1 复盘 + Wave 2/3 移交物打包（§6）。

## 4. 贯穿纪律（每日不变项）

1. **K1 streak 保护**：部署冻结窗 **06:35-07:35**；禁止手动重跑当日流水线（补数走 hotfix collector_run_id 模式）；K1 当前 3/14（11-03/04/05），任何 scheduled 日失败即断。
2. **变更纪律**：全部 PR + C7 精确门禁绿后合并；修复类 PR 不零 review 合并；known-failures baseline 不动。
3. **语料口径红线**：对外按 release 实时计算并带 data_as_of 与 coverage_denominator（示例值截至 2026-11-04：Momcozy brand-bound 2,331 / brand-or-text 2,339 / exact-SPU 67 / M5 family 49）；「712.2 万全渠道」仅 Source 口径，禁止混算。
4. **risk_index 命名边界**：对齐既有 `risk_resilience`（76.89）与 RiskCommandCenter 合同（`ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/types.ts:685-710`）；`risk_score` 被测试禁写（`tests/test_reddit_risk_report_contracts.py:475`）。
5. **LLM 纪律**：复用既有 `DeepSeekClient` + provider_attempt_ledger + TokenUsage；单问预算上限 + 日软上限（200 次/日超限降级模板应答）；Wave 1 先 50 样本 smoke，200 样本 VOC 精度门禁 owner 归 刘华丽（Wave 2 全量，RACI 并入 X7）。

## 5. 风险登记

| # | 风险 | 触发条件 | 应对 |
|---|---|---|---|
| R1 | bot-gateway 依赖延迟 | X1 11-06 EOD 无回复 | 11-07 启动 shim（ADR），T5' 已解耦不受影响 |
| R2 | 飞书卡片权限未开 | X3 11-10 未就绪 | T11 证据包移至 11-16，11-13 明确降级不写解除封顶 |
| R3 | SPU 覆盖缺口 | 问数命中 M5 等 0 exact SPU | family 级为主路径（T18 golden set 已含）；降级文案打磨 |
| R4 | P3 产能单点 | 刘华丽 在手 15 项 | RACI 裁定（X7）前按「Pray 补 P2、刘华丽 只做验收」 |
| R5 | K1 streak 与部署冲突 | 收口期密集发版 | §4.1 冻结窗 + hotfix 模式 |
| R6 | Superset/report 平台归属不明 | X4/X5 无主 | 默认 Plan B（radar 内交付），11-08 确认 |
| R7 | X7 无回复 / X6 无群 | 11-12 仍未决 | 按 50% 封顶保守表述；pilot 降级 synthetic + PMO 书面接受 |
| R8 | 周末外部依赖冻结 | 11-07/08、11-14/15 | 死线全部压在 11-06/11-10/11-13 工作日 EOD |

## 6. Wave 2/3 移交物（11-16 产出）

①事件路由 + 意图槽位解析 spec（含 3s-ack/异步 worker/幂等模式）；②card.action 验签 + 幂等模板；③动作账本契约（本地真源 + PMO 终态同步）；④query log→SOP 蒸馏流程（≥10 次/周、real_user 口径、source 标注）；⑤reply_engine 共享化与双通道去重教训；⑥systemd/部署 runbook（含未入库脚本入库清单）。
