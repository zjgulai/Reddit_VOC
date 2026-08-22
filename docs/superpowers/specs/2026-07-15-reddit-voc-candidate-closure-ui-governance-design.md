---
title: Reddit VOC 全候选闭环与 UI 治理设计
doc_type: design_spec
status: approved
created: 2026-07-15
updated: 2026-07-15
owner: codex
decision: controlled_candidate_closure_single_production_release
scope: umbrella_design_three_implementation_plans
implementation_status: plan_a_batch_a1_readonly_in_progress
validation_status: written_spec_approved
production_boundary: production_unchanged
provider_call: false
database_write: false
live_send: false
deploy: false
schedule_change: false
collector_change: false
shared_nginx_change: false
tls_change: false
dns_change: false
other_docker_change: false
git_commit: false
---

# Reddit VOC 全候选闭环与 UI 治理设计

## 1. 决策

采用用户于 2026-07-15 批准的方案 B：所有冻结候选进入可审计处理闭环，
但只有相对当前生产基线首次出现并通过准入门禁的 Reddit `post_id` 或
`comment_id` 才计为本版本净新增。已有实体的正文补齐、评论补齐、父子关系修复、
隔离迁移和覆盖升级单独记账，不能重复计入净新增。

本文件是统领三个实施计划的 umbrella design：Plan A 负责 freeze、四本明细账、
reconciliation、融合与经营重算；Plan B 负责 UI 状态组件、感叹号治理和双状态证据；
Plan C 负责 candidate-only 编排、导出、容器、安全回归和 promotion 工具。执行依赖为
Plan A 先建立数据合同，Plan B 消费该合同，Plan C 可并行准备通用编排，三者最终只汇聚为
一个生产候选。自动化只能写不可变候选和 candidate registry，不能直接切换生产
`current`。生产提升继续要求负责人同时批准精确 promotion packet SHA 与 release SHA。

本设计不要求 Reddit 覆盖债务绝对清零。完成定义是每个冻结 occurrence、identity 和
coverage work item 都有唯一、可复算的状态，`unaccounted=0`；仍未完成的项目必须保留为
`open_carried` 或明确失败状态，不能删除、零填充或冒充净新增。

## 2. 方案比较

### 2.1 方案 A：全部覆盖债务清零后发布（不采用）

持续处理所有 lineage、cursor、评论分页和搜索续页，直到没有任何未完成项。
该方案把无法证明的 Reddit 绝对完整性当成终点；cursor 可能生成子 cursor，搜索续页也
可能产生新身份，因此发布时间和请求规模不可控。

### 2.2 方案 B：受控闭环、单次生产发布（采用）

所有冻结输入都有唯一去向，净新增按身份集合差计算，存量升级和覆盖工单分账。
未完成债务可在证据完整时随候选发布，但必须以精确状态和数量进入 release receipt。
该方案同时满足数据真实性、老板可读性、可回滚性和不干扰采集后台的要求。

### 2.3 方案 C：先发布 UI 去警示，数据后更新（不采用）

只清理感叹号和控制证据文案，随后再接入数据。视觉改善更快，但会让新版 UI 继续承载
旧数据水位和旧口径，增加二次返工与误读风险。

## 3. 当前已验证基线

本节只描述当前不可变 RC3 证据，不代表冻结截止时间之后的服务器实时状态。

### 3.1 生产数据基线

生产 Base `reddit_voc_site_snapshot_20260715_6efd951e6095` 包含：

- 1,322 个唯一帖子；
- 12,986 条 stored comments；
- 12,976 条 linked comments；
- 10 条 quarantine comments；
- 12,825 条进入 VOC 指标的评论；
- Base 帖子身份 LF SHA-256：
  `d9803f44cbfa7407110d8fafa0bef57aabc01fe252893cee77e03fd2cc68376e`；
- Stored comment 身份 LF SHA-256：
  `6e694bc9dc1ecf3dca14731eedd303183ece652b7605c06e73927cc70c352e70`。

当前生产 release SHA 为
`9e0d23131824c9d5e195ef9e0950d62e1c89893a40bafa1ec72c53fab330d650`，
已取得独立 L4 生产验收回执。该回执不授权本设计中的新生产提升。

### 3.2 候选身份关系

身份冻结 `reddit-v2-identity-freeze-20260715-incremental1.json` 的截止时间为
`2026-07-15T04:25:57.752337Z`。当前精确关系为：

```text
global_known 1340 = production 1322 ⊎ lineage_gap 18
discovery_only 883 = admitted 865 ⊎ lineage_gap 18
net_new_vs_initial_site 1119 = published_new 1101 ⊎ pending_gap 18
```

因此：

- 883 个 discovery candidates 不是下一版还能新增的 883 个帖子；
- 865 个已经进入当前生产 Base；
- 当前冻结事实中只有 18 个 lineage gaps 可能转成下一版新帖子；
- 18 个缺口最终是否准入取决于正文、事件时间、去重、隐私和结构校验；
- 新的搜索续页可能发现额外身份，其数量必须在下一次 freeze 后计算。

### 3.3 覆盖债务关系

V2 已准入的 865 个帖子由 517 个 `full-observed` 和 348 个 `partial` 组成：

```text
cursor work items        = 367 tokens on 232 posts
comment page outstanding = 339 posts
cursor/page intersection = 223 posts
cursor/page union        = 348 partial posts
```

367 个 cursor、339 个评论分页和 348 个 partial threads 是相互重叠的不同粒度，
不能相加为候选总量，也不能计为净新增帖子。当前生产 Base 的所有来源合计还有
464 个 `observed_first_page` 帖子和 1 个 `post_only` 帖子；348 只是 V2 discovery 子集。

此外还有 69 个搜索 lane，其中 19 个 terminal、50 个仍有搜索续页债务。搜索续页可能
发现新帖子，评论分页只补全已知帖子，两者必须使用不同工单类型。

## 4. 目标与非目标

### 4.1 目标

- 以当前生产身份集合而不是历史人工数字为每个新版本的比较基线。
- 让全部冻结候选和覆盖工单都有唯一结果，达到 `unaccounted=0`。
- 同时展示候选总量、已激活、待激活、本版本净新增和存量补全，避免重复计数。
- 将最新合并数据重新应用标签字典、画像、Momcozy 品牌主干、品类、product family 和
  exact-SPU 规则。
- 按 Reddit event time 重算日报、周报、月报、同比、环比和趋势。
- 剔除正常页面中的装饰性或重复性感叹号，同时保留真实数据边界和 fail-closed 错误。
- 将离线 artifact build 状态与当前网站 deployment 状态拆成两个独立证据对象。
- 产品化 candidate-only 自动链；生产提升继续人工精确授权。
- 保持案例广场 38 条精选和 12 条待核验存量，approved delta 继续增量合并。
- 新版生产提升继续只操作隔离洞察站，不干扰采集器或其他 Docker 项目。

### 4.2 非目标

- 不承诺 Reddit 绝对完整或所有 coverage debt 归零。
- 不把 cursor、分页、source occurrence 或已有实体升级计为净新增。
- 不修改、重启或重新调度现有 Reddit 采集器。
- 不在本设计中授权 Reddit、TikHub、DeepSeek 或其他 Provider 请求。
- 不授权生产数据库写入、回填或 merge。
- 不授权 cron/systemd 调度启用或修改。
- 不授权上传生产制品、`docker load`、启动远端候选容器或切换生产 `current`。
- 不修改共享 Nginx、TLS、DNS 或其他 Docker 环境。
- 不把合成画像解释为真实 Reddit 用户或进行跨帖用户跟踪。
- 不为了删除感叹号而删除 coverage status、reason codes、待核验来源或错误信息。

## 5. 核心计数合同

令：

```text
B = 初始网站 221 个帖子组成的冻结身份集合
G1 = 下一候选 global-known 帖子身份集合
P0 = 当前生产帖子身份集合
L0 = 当前生产 linked comment 身份集合
Q0 = 当前生产 quarantine comment 身份集合
C0 = L0 ∪ Q0

P1 = 下一候选帖子身份集合
L1 = 下一候选 linked comment 身份集合
Q1 = 下一候选 quarantine comment 身份集合
C1 = L1 ∪ Q1
```

必须满足：

```text
P0 ⊆ P1
C0 ⊆ C1
L1 ∩ Q1 = ∅
∀ c ∈ L1: c.post_id ∈ P1
B ⊆ G1
B ⊆ P1

net_new_posts = |P1 \ P0|
net_new_comments = |C1 \ C0|
relinked_existing_comments = |Q0 ∩ L1|
known_cumulative_net_new = |G1 \ B|
activated_cumulative_net_new = |P1 \ B|
```

如果来源明确证明某个既有实体需要移除，必须另建删除/撤回治理流程；本批默认 append-only
身份守恒，不允许因输入缺失静默删除生产身份。

### 5.1 UI 指标合同

管理层页面必须区分：

- `known_cumulative_net_new`：相对初始 221 帖基线的 global-known 净新增；
- `activated_cumulative_net_new`：相对初始基线已进入生产 Base 的净新增；
- `pending_known_identities`：已发现但尚未准入的身份；
- `release_net_new_posts`：当前候选相对 `P0` 的新增帖子；
- `release_existing_post_upgrades`：正文、结构或覆盖发生升级的既有帖子；
- `release_net_new_comments`：当前候选相对 `C0` 的新增评论；
- `release_relinked_comments`：原 quarantine 转为 linked 的既有评论；
- `occurrence_accounting_rate`：已归类 occurrence 数除以冻结 occurrence 数；
- `post_accounting_rate`：已归类 post identity 数除以冻结 post identity 数；
- `comment_accounting_rate`：已归类 comment identity 数除以冻结 comment identity 数；
- `coverage_accounting_rate`：已归类 coverage work item 数除以冻结 work item 数；
- `unaccounted_total`：上述四类未归类数量之和，候选通过时必须为 0；
- `coverage_debt_before/after`：按工单类型分别呈现，不求和成帖子数。

当前静态基线可显示：已知累计净新增 1,119、已激活累计净新增 1,101、
待激活 18、discovery 漏斗 `883 = 865 + 18`。下一版本所有 release delta 必须重新计算，
不得把这些数硬编码成新版本结果；上述数值只作为 RC3 历史证据。

## 6. 五本账设计

五本账均为构建期私有证据，不直接进入公开投影。每行必须有稳定 key、source cutoff、
输入证据引用、结果状态和 reason code；manifest 记录文件 bytes 与 SHA-256。

### 6.1 Source occurrence ledger

一行代表一个输入文件或报告 occurrence。稳定 key 为
`source_namespace + normalized_relative_path + bytes + sha256 + observed_cutoff`，唯一状态为：

```text
accepted_new_occurrence
accepted_duplicate_occurrence
superseded_by_precedence
rejected_invalid
quarantined_input
```

该账回答“所有冻结文件去了哪里”，不参与帖子净新增计数。

### 6.2 Post identity delta ledger

一行代表一个候选 `post_id`，唯一状态为：

```text
newly_admitted
existing_upgraded
existing_unchanged
pending_lineage
rejected
```

只有 `newly_admitted` 进入 `release_net_new_posts`。

`existing_upgraded` 必须通过受管 canonical 字段白名单的前后规范化内容 SHA 变化证明；
帖子白名单至少包括 title、content、permalink、event time、结构覆盖和受管分析绑定。
一个身份无论升级几个字段只计一次。`rejected` 只适用于 `P1` 之外的新候选；针对 `P0`
既有实体的无效更新必须保留生产实体，身份结果记 `existing_unchanged`，对应输入
occurrence 记 `rejected_invalid`。

### 6.3 Comment identity delta ledger

一行代表一个 `comment_id`，唯一状态为：

```text
new_linked
new_quarantined
existing_upgraded
existing_unchanged
existing_quarantine_relinked
existing_quarantine_retained
rejected
```

`existing_quarantine_relinked` 是结构升级，不是净新增评论。
评论的 `existing_upgraded` 同样以受管字段白名单 canonical SHA 变化为准；评论白名单至少
包括 body、parent/post linkage、event time、VOC 准入和受管分析绑定。一个 `comment_id`
只计一次。`rejected` 只适用于 `C1` 之外的新候选；针对 `C0` 既有实体的无效更新不得删除
实体，身份结果记 `existing_unchanged`，输入 occurrence 记 `rejected_invalid`。

### 6.4 Coverage work ledger

工单 key 按类型隔离：

```text
lineage:<post_id>
cursor:<post_id>:<cursor_sha256>
comment_page:<post_id>
search_lane:<lane_index>:<term_sha256>
```

每个冻结工单唯一状态为：

```text
closed_success
closed_no_more
superseded
retryable_failed
nonretryable_rejected
open_carried
```

执行 cursor 可能暴露子 cursor；是否继续请求由单独授权和预算控制。本批数据构建只消费
已经存在的冻结报告，不自行发起 Provider 请求。

### 6.5 Candidate data reconciliation ledger

每个候选一行，绑定：

- production baseline release SHA；
- source cutoff；
- input freeze SHA；
- `P0/L0/Q0/C0` identity SHA；
- `P1/L1/Q1/C1` identity SHA；
- 前四本明细账文件 SHA；
- coverage before/after；
- quarantine transition counts；
- Base、Insights、Reports、Personas 和 public manifests；
- evidence grade 与所有副作用边界。

Candidate data reconciliation ledger 不包含自身最终 SHA，避免自哈希循环。其文件 SHA
由 Plan A 外层 data manifest 和 data receipt 记录。Plan C 的 final release manifest/receipt
再绑定 Plan A data receipt、frontend source-tree、dist、container、E2E 和 export receipts；
不得要求 Plan A 的不可变 reconciliation 预留或回写未来 frontend 字段。

## 7. 数据重新冻结与融合流程

### 7.1 只读静稳门禁

候选构建不能只按时钟启动。必须满足：

- 没有 `reddit_voc_site_app-run-*` one-shot 采集容器；
- 采集服务 container ID、health 和 restart count 稳定；
- 报告文件清单、bytes 和 mtime 在两个观测点稳定；
- 没有未结束的任务状态；
- 读取 SQLite 时使用 URI `mode=ro`、`PRAGMA query_only=ON`，适用时使用 immutable
  快照；
- 远端只读审计不修改采集器、数据库、报告指针或调度。

任一条件不满足时返回 `no_candidate_collection_not_quiescent`，不强行构建。

### 7.2 动态基线与冻结

- 从生产 `current` 读取 Base manifest 和身份 SHA，形成 `P0/L0/Q0/C0`。
- 只复制 allowlist 内文件，拒绝 symlink、special file、越界路径和 cutoff 后漂移。
- Plan A source/data freeze 冻结腾讯云生产数据、isolated staging、`ai_nlp_voc` 归档、
  历史 canonical lineage、V2 报告、标签字典、产品 ledger 和配置；
- Plan A 在 data implementation 稳定后另建 `data_build_code_freeze`；
- Plan C 在 Plan B 完成后冻结最终 frontend/release source tree、package lock 和 toolchain；
- 三层分别记录独立 cutoff 与 SHA，不伪装成同一时间点。
- 相同输入重跑必须返回相同 SHA 或 `no_change`，不得覆盖内容不同的同名版本目录。
- 如果身份和受管内容均无变化，生成 no-change receipt，不制造空版本。

### 7.3 融合与业务重算

按既有优先级执行确定性去重、正文升级、父子关联、quarantine、PII、机器人/删除内容
过滤和本地规则分析。随后重新应用：

- `dim_tag_v6.3_final.csv`；
- Momcozy 品牌主体绑定；
- 品类、product family、exact-SPU ledger；
- 证据型聚合画像及合成头像合同；
- 竞品同检索策略、同事件窗口的对比；
- Base → Insights → Reports → Personas → public projection。

日报、周报、月报与归档均按 Reddit `event_created_at_utc` 重算。晚到数据必须回写对应
历史窗口。同比、环比和趋势只有在关键词、subreddit、采集深度、时间窗、去重和 coverage
可比时才允许方向性措辞；否则保留数值和 reason codes，状态为 provisional 或 unavailable。

## 8. UI 警示治理

### 8.1 视觉语义

系统错误、业务风险、数据覆盖和功能状态必须使用不同视觉语法：

- `failed`：红色 error，允许真实警示图标，只用于运行或数据合同失败；
- `provisional`：中性或蓝色信息状态，表示部分覆盖或方向不可解释；
- `unavailable`：中性灰色状态，表示能力未启用或证据不足；
- `verified`：绿色确认状态；
- P0/P1/P2/P3：保留业务优先级文字和颜色，但不使用系统错误式感叹号。

### 8.2 新的共用组件

1. `DataScopeBar`：每个受管数据页面最多出现一次，承载 coverage、comparison 和标签成熟度；
   cases 使用 catalog status，营销页和 gated 空态不强塞。
2. `GovernanceStatusBadge`：统一呈现 `verified/provisional/unavailable/failed`。
3. `ReleaseEvidenceCard`：分栏展示 artifact build provenance 与 site deployment status。

这些组件复用现有设计 token 和 Lucide 图标，不增加依赖，不重做页面布局。

### 8.3 正常态替换范围

- `/dashboard`：隔离评论卡改用中性关联/隔离图标，保留数值和“不进入指标”说明。
- `/dashboard/reports`：负面证据、痛点、关注项使用内容分析图标，不把栏目本身渲染成系统警告。
- `/dashboard/insights`：hero、KPI 和风险主题使用 `Shield/Radar` 等中性业务图标；
  `insufficient` 改为“仅观察”信息状态，reason codes 保留。
- `/dashboard/analytics`：规则标签统一为“规则提取/未晋级语义洞察”中性状态。
- `/dashboard/search`：列表和详情中的“待语义复核”合并为一次规则状态说明。
- `/cases`：删除无条件红色通知点；12 条 `legacy_unverified` 保留，改用历史/待核验状态。
- `/dashboard/messages`、`/dashboard/ugc-showcase`、`/dashboard/settings`：使用中性
  “功能状态 · 未启用”，继续 fail closed。
- 营销和功能说明页删除黄色/橙色纯装饰警示，不改变已证明能力的文字。

### 8.4 错误图标 allowlist

所有治理状态组件必须提供稳定的 `data-governance-status` 和可访问 `aria-label`。正常数据
下，活动路由不得在 `verified/provisional/unavailable` 状态渲染 error-status 图标；验收只
检查受管 UI 状态组件，不扫描 Reddit 标题、正文中的 `!` 标点，也不依赖编译后 Lucide
组件名。
以下错误分支可继续使用红色错误警示：

- 全局 React ErrorBoundary；
- 快照、报告或搜索 manifest/fetch/hash 合同失败；
- 画像 manifest、资源 SHA 或安全 SVG 合同失败；
- 搜索评论加载失败；
- 案例 seed/index 完整性失败。

### 8.5 控制证据双状态

当前不可变数据中的 `production_unchanged=true`、`deploy=false` 和
`release_switch_executed=false` 描述的是离线 artifact 构建阶段，不能改写历史字节。
下一版 schema 新增：

```text
artifact_build_state
  built_at_utc
  production_unchanged
  provider_call
  database_write
  live_send

site_deployment_state
  served_release_id
  release_sha
  promotion_status
  promoted_at_utc
  acceptance_status
  acceptance_receipt_sha
  status_source
  status_source_sha
```

生产页面默认从实际加载的 current pointer 显示 served release identity；只有存在独立、
可校验且与 served release SHA 一致的 deployment status source 时才显示 promotion/
acceptance，否则显示 `unavailable`，不得把候选 build flags 改写成部署事实。离线副作用
边界放入可展开技术证据区。

## 9. Candidate-only 编排

现有底层已经具备只读抓取、冻结、四层构建/验证、public projection、前端 dist、
linux/amd64 容器、浏览器 E2E、隔离安装和回滚能力。新增最小编排层：

```text
singleton lock acquisition
  → terminal marker / quiescence double observation
  → allowlist export
  → identity/data/code/frontend freeze
  → deterministic Base
  → four detail ledgers
  → Insights/Reports/Personas/public
  → reconciliation ledger and outer manifest
  → independent validators
  → isolated dist/container
  → same-dist browser E2E
  → immutable candidate receipt
  → candidate registry
  → stop
```

候选 registry 至少记录 release SHA、input freeze SHA、数据版本、业务 delta、coverage
before/after、全部回执 SHA、创建时间、过期时间和 `deploy=false`。相同冻结输入重复触发
只返回既有 receipt。

Promotion packet、remote candidate smoke 和 production acceptance receipt 从 RC3 临时
制品产品化为版本无关工具，但不进入无人值守候选任务。部署入口必须机械校验一次性 owner
permit、promotion packet SHA 和 release SHA；任何字节漂移使许可失效。

## 10. 测试与证据门禁

### 10.1 数据门禁

- 五本账集合互斥且守恒；
- `unaccounted=0`；
- `P0 ⊆ P1`、`C0 ⊆ C1`、`L1 ∩ Q1=∅`；
- linked comment 的父帖子均存在；
- net-new、upgrade、relink 和 quarantine transition 可从集合差独立复算；
- 18 lineage gaps 和所有新增身份均有准入或拒绝 reason；
- coverage 工单 before/after 可复算，不将 work item 数当帖子数；
- 标签、品牌、产品/SPU、画像和报告版本均绑定上游 manifest SHA；
- no-change、tamper、缺文件、碰撞和 symlink 测试 fail closed。

### 10.2 前端门禁

- frontend unit、lint、typecheck 和 production build 通过；
- 完整 source-tree manifest 与 dist manifest 绑定；
- 正常态 active routes 的受管状态组件无 error-status 图标；
- 注入快照、画像和案例合同失败时错误警示仍出现并停止指标渲染；
- 13 个路由在 desktop/mobile 同一不可变 dist 上通过；
- 日报、周报、月报 current/archive 六种状态通过；
- A 洞察主线、B 报告分册、C 受控模块、Momcozy 产品三层、竞品同样本、合成头像、
  案例和采集后台安全外链通过；
- 无未知外部请求、浏览器错误、同源失败或横向溢出；
- 案例保持 `38 精选 + 12 待核验 + approved delta`；
- CSV、DOCX、PDF、PPT 在候选上实际生成并验证内容合同；
- 洞察容器内 `/.env` 明确返回 404，受管私有数据路径继续 404。

### 10.3 证据等级

- 本地构建与测试：L2 fixture/dry-run；
- 生产只读基线：L3 production read-only；
- 远端上传、候选容器和生产切换：必须另有精确授权，完成并记录后才是 L4；
- candidate registry 通过不等于 production accepted；
- 本地浏览器 E2E 不等于公网生产浏览器验收。

## 11. 生产提升与回滚合同

生产提升是独立动作，必须重新获得精确授权：

1. 校验 promotion packet SHA 与 release SHA；
2. 读取生产 current、洞察容器、采集器、LibreTranslate、cron、共享 Nginx 和网络基线；
3. 确认安全窗口与采集静稳；
4. 上传到隔离 release 目录并校验 SHA；
5. 在 18339 执行候选 smoke；
6. 只替换 `reddit_voc_insights_web/current`；
7. 执行公网 HTTP、浏览器、六种报告、四种导出和安全路径验收；
8. 复核 collector ID/restart、cron SHA、shared Nginx SHA 和其他 Docker 不变；
9. 通过后生成 L4 production acceptance receipt；
10. 任一门禁失败只回滚洞察站 current，不修改采集后台。

普通数据版本升级不重新修改共享 Nginx、TLS 或 DNS。不得执行 Docker prune、停止或重建
其他 Compose project。

## 12. 实施计划分解、批次与完成定义

本 umbrella design 已完成书面审阅并拆成三个独立 implementation plan：

- Plan A：Batch 1–3，数据冻结、四本明细账、reconciliation、融合与经营重算；
- Plan B：Batch 4，UI 状态组件、感叹号治理和 artifact/deployment 双状态；
- Plan C：Batch 5–7，candidate-only 编排、本地/远端分层验收和受控 promotion。

Plan A 的数据合同是 Plan B 的输入。Plan C 可并行实现不依赖业务数据的通用编排，但生成
最终候选时必须绑定已通过的 Plan A 与 Plan B 制品。三个计划不能各自提升生产。

### Batch 1：最新事实重新冻结

取得 L3 只读静稳证据、最新 allowlist、生产基线身份 SHA 和新的 source freeze。

### Batch 2：确定性 Base、四本明细账与身份重算

先从冻结输入确定性构建 Base，再由 `P0/C0` 与 `P1/C1` 比较生成四本明细账；所有
冻结候选唯一归类，净新增相对 RC3 生产基线动态计算，账本不得反向控制 Base。

### Batch 3：数据融合与经营重算

生成 Insights/Reports/Personas/public 候选，重算品牌、品类、SPU、画像和日周月报告；
全部 outputs 完成后生成 reconciliation，再由外层 manifest 记录其 SHA。

### Batch 4：UI 警示治理

实现三个共用状态组件、正常态去感叹号、C 模块双状态和案例红点清理，不改变核心布局。

### Batch 5：Candidate-only 编排

实现静稳、singleton、no-change、candidate registry 和版本无关候选回执；自动链停止于 registry。

### Batch 6：完整本地同一 dist/container 隔离验收

完成数据、前端、同一 dist 浏览器、四种导出、本地容器和篡改/无变化回归，生成精确
promotion packet。本批不上传制品、不 `docker load` 到远端，也不启动远端 18339 候选。

### Batch 7：受控生产提升

仅在负责人另行批准 promotion packet SHA 与 release SHA 后执行。授权后才允许远端上传、
`docker load` 和 18339 candidate smoke。通过生产 HTTP、浏览器、导出和不变性验收后，
才可把新版本标记为 L4 accepted。

本设计完成不等于 Batch 1–7 已完成。当前状态保持：

```text
design_approved=true
written_spec_review_pending=false
implementation_plans_created=true
implementation_started=true
production_unchanged=true
provider_call=false
database_write=false
live_send=false
deploy=false
schedule_change=false
collector_changed=false
shared_nginx_changed=false
tls_changed=false
dns_changed=false
other_docker_changed=false
git_commit=false
```

实施计划入口：

- Plan A：`docs/superpowers/plans/2026-07-15-reddit-voc-candidate-closure-data.md`；
- Plan B：`docs/superpowers/plans/2026-07-15-reddit-voc-ui-governance.md`；
- Plan C：`docs/superpowers/plans/2026-07-15-reddit-voc-candidate-automation.md`。

## 13. 单独授权清单

以下动作不由本设计批准自动获得权限：

- Reddit/TikHub/DeepSeek 等 Provider 请求或继续采集；
- SSH 定时导出或启用长期自动读取；
- cron、systemd 或其他调度变更；
- 上传 TGZ、`docker load` 或启动远端候选容器；
- 切换生产 current、替换生产洞察容器、执行 rollback/disable 或故障注入；
- 共享 Nginx 修改或 reload；
- TLS/ACME、DNS 变更；
- 数据库写入、生产 merge 或回填；
- DingTalk、Webhook 或其他 live send；
- 操作采集器或其他 Docker project。

## 14. 证据入口

- 生产验收：
  `tmp/reddit-voc-incremental-candidate-20260715/production-acceptance-receipt-rc3.json`；
- RC3 Base：
  `tmp/reddit-voc-incremental-candidate-20260715/base/reddit_voc_site_snapshot_20260715_6efd951e6095/`；
- 身份冻结：`tmp/reddit-v2-identity-freeze-20260715-incremental1.json`；
- V2 raw snapshot：`tmp/reddit-v2-raw-snapshot-20260715-incremental1.json`；
- 当前增量计划：
  `docs/superpowers/plans/2026-07-15-reddit-voc-incremental-activation.md`；
- 部署计划：
  `docs/superpowers/plans/2026-07-15-reddit-voc-insights-site-deploy.md`；
- UI 主要实现：
  `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/`、
  `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`、
  `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotInsights.tsx`、
  `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotReports.tsx`、
  `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotAnalytics.tsx`、
  `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotSearch.tsx` 和
  `ref/UI/momcozy-reddit-workbench/src/pages/CaseGallery.tsx`。
