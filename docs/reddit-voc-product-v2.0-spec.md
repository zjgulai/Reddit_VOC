---
title: Reddit VOC 洞察产品 V2.0 规格
doc_type: product_and_engineering_spec
status: local_control_plane_implemented_integration_blocked
created: 2026-07-17
updated: 2026-07-17
owner: codex
project: Reddit_VOC
production_boundary: production_unchanged
provider_call: false
database_write: false
remote_write: false
deploy: false
schedule_change: false
live_send: false
---

# Reddit VOC 洞察产品 V2.0 规格

## 1. 产品定位

V2.0 将当前“静态真实数据洞察站 + 独立历史采集 + 独立日报采集”升级为一套可持续运行的
Reddit VOC 决策系统：以 Momcozy 品牌和品类为主干，在统一、可追溯、可重放的中心数据集上
持续生成日报、周报、月报、品牌健康、用户画像、用户痛点、舆情风险、新品机会和 GEO 机会。

V2.0 不追求实时流式处理。当前业务需要的是每天一个闭合、可信、可解释的数据版本，并且
历史回溯和每日增量不会互相污染、重复计数或争抢采集资源。

## 2. 产品用户与核心任务

| 用户 | 核心问题 | V2.0 输出 |
|---|---|---|
| 管理层 | 品牌是否健康，风险和增长机会在哪里 | 概览、品牌指数、关键趋势、行动优先级 |
| 品牌/舆情运营 | 过去 24 小时发生了什么，是否需要介入 | 日报、风险事件、活跃帖子、新增评论 |
| 产品与品类团队 | 哪些品类/SPU 痛点和未满足需求最强 | 痛点、需求、品类/SPU 对比、新品机会 |
| 内容/GEO 团队 | Reddit 用户如何提问，哪些内容有被引用机会 | 问题簇、证据链、GEO 主题和内容建议 |
| 数据/研发 | 数字来自哪里，能否重算、回滚和解释 | SourceBatch、canonical、版本、账本、回执 |

## 3. V2.0 已冻结决策

1. 每日数据为过去 24 小时新帖，以及活跃历史帖子过去 24 小时新增评论。
2. 普通帖子活跃策略为 30 天最大年龄或最近 7 天有新评论；高风险、品牌介入、内容合规、
   管理员曝光和人工案例为 90 天最大年龄、连续 30 天无新增后退出。
3. 自动化边界到 candidate：采集、融合、分析、构建、校验和 candidate 注册可自动；生产
   release 继续受控提升。
4. 品牌、竞品、SPU、subreddit、关键词或覆盖规则变化后，必须先补对应历史 delta，再开放
   新旧周期同环比。
5. 采用不可变文件批次和微批融合；当前不引入新的 PostgreSQL 生产基础设施。
6. 采集器不能直接写网站数据；React 不能直接读取采集 SQLite。

## 4. V2.0 核心能力

### 4.1 统一采集

- 历史回溯和每日增量共用 Reddit ID、raw persistence、分页、reply cursor、checkpoint、
  Provider 请求账本、issue 和终态模型。
- 调度策略分离：日报优先，历史回溯消费独立预算并可断点续跑。
- 新帖 lane 与活跃历史帖子 lane 分离，避免只看到“新发帖子”而遗漏旧帖新增评论。

### 4.2 中心数据集

- 每一次采集先形成不可变 `SourceBatch v2`。
- occurrence、canonical identity、content version、engagement snapshot、父子关系债务分层。
- 帖子和评论分别作为 VOC；组合上下文是派生事实，不替代原始事实。
- 标签和指标可重算，改变字典/算法不需要重新采集 Reddit。

### 4.3 专业报告

- 日报：过去 24 小时新帖、新评论、风险、痛点、品牌/品类/SPU 变化和行动建议。
- 周报：周内结构变化、Momcozy 与竞品同口径对比、环比和趋势。
- 月报：品牌健康、同比/环比、品类和 SPU 驱动、风险复盘、机会路线图。
- 所有报告绑定同一 canonical/metric release 和明确数据截止时间。

### 4.4 洞察故事线

- 用户画像：最近季度人群证据分组、占比、解释和原始证据。
- 用户痛点：品牌、品类、SPU、场景、严重度、情感和互动量。
- 舆情洞察：风险、危机、品牌介入、机器人/不规范推广、管理员处置和内容合规。
- 新品机会：未满足需求、竞品优势、需求强度和可执行产品假设。
- GEO 机会：高频问题、权威回答缺口、可引用证据和内容主题。

### 4.5 可运营与可审计

- 每个数字可回溯到 release → metric fact → canonical entity → occurrence → raw payload。
- 重复运行相同输入返回 no-change。
- candidate 失败、partial 或 no-change 不改变生产 current。
- 生产回滚只切换洞察站 release pointer，不回滚或重启采集任务。

## 5. 数据架构

```text
Acquisition Plane
  historical_backfill / daily_incremental / comment_refresh
          ↓
Immutable SourceBatch Plane
  raw + posts + comments + occurrences + checkpoints + issues + manifest + receipt
          ↓
Canonical Fusion Plane (single writer)
  entities + parent edges + content versions + engagement snapshots + debt + provenance
          ↓
Analysis Fact Plane
  VOC + tags + sentiment + severity + brand + competitor + category + SPU + persona + risk
          ↓
Metric & Storyline Plane
  daily / weekly / monthly / overview / insights / cases
          ↓
Release Plane
  Base → Reports → Insights → Personas → public projection → candidate registry
          ↓
Controlled Production Promotion
```

完整采集与融合合同见
[`docs/workflows/reddit-voc-unified-collection-fusion-v1.md`](workflows/reddit-voc-unified-collection-fusion-v1.md)。

## 6. 统一领域对象

### 6.1 SourceBatch

一个已经结束的采集任务交付单元。它绑定生产者类型、时间窗、query/coverage profile、
raw payload、解析结果、occurrence、checkpoint、issue、计数、状态和 SHA。

### 6.2 Occurrence

表示一个 Reddit 实体在某个 batch、查询 lane、页面、cursor 和 raw payload 中出现。重复
occurrence 不增加实体数，但不能删除，因为它是覆盖和来源证据。

### 6.3 Canonical Entity

标准化后的 `t3_<post_id>` 或 `t1_<comment_id>`。它保存稳定身份和最新业务视图，但不覆盖
历史内容版本、互动量快照或来源出现。

### 6.4 Content Version 与 Engagement Snapshot

- 标题、正文、评论内容变化形成 content version。
- score、upvote ratio、reported comment count 形成带观察时间的 engagement snapshot。
- deleted/removed 是状态变化，不删除历史证据。

### 6.5 Analysis Fact 与 Metric Fact

Analysis Fact 绑定 source entity、分析版本和标签证据；Metric Fact 绑定周期、分母、算法、
数据版本和比较窗口。UI 只展示 Metric Fact，不自行拼接或推导指标。

## 7. 每日闭环

```text
07:00 关闭 [昨日07:00, 今日07:00) 业务窗口
  → 新帖发现使用前置2小时重叠窗口
  → 活跃历史帖子评论刷新
  → raw 与 checkpoint 落盘
  → SourceBatch 校验
  → 单写者融合
  → 标签和指标增量重算
  → 日报与洞察 candidate
  → candidate registry
  → 等待受控生产提升
```

如果采集未终态、文件未静稳或 SourceBatch 校验失败，系统保持上一闭合 release，并输出明确
阻断原因。报告不得直接读取半成品 SQLite。

## 8. Profile 治理

### 8.1 Query Profile

绑定品牌、竞品、SPU/产品别名、关键词、subreddit、检索 lane 和查询语法。运行时实际配置
必须冻结进 batch，不能只引用代码默认值。

### 8.2 Coverage Profile

绑定时间窗口、重叠、分页、评论树、reply cursor、活跃帖子生命周期、停止条件和 Provider
预算。30/7 和 90/30 属于 coverage profile，不硬编码成永久不可变业务规则。

### 8.3 Delta 回溯

任何 profile 变化先计算 lane delta。新增范围完成历史回溯和融合之前，单周期事实可展示，
但同环比方向保持不可比，避免把覆盖扩张当作舆情增长。趋势只有在已通过独立校验的
SourceBatch 时间窗并集无缺口覆盖完整比较区间后才可开放；profile delta closure v2 回执还
必须逐批绑定 manifest SHA、validation receipt SHA 和目标 profile，不能依赖自声明日期。

## 9. 产品发布路线

### V2.0-M1：统一证据批次

- [x] SourceBatch v2 parser、物理绑定、raw 终态守恒和独立 validator。
- [x] 24 小时窗口与活跃帖子策略合同。
- [x] 日报 browser/TikHub discovery、detail 和 comments raw payload 不可变持久化。
- [x] 日报 SourceBatch exporter、CLI 与现有日报脚本影子产物接线。
- [x] 历史 SourceBatch exporter；`seed_complete` 如实映射为带覆盖债务的 `partial`。

退出条件：日报和历史 fixture 均能生成可消费、可重放、tamper fail-closed 的同构批次。

### V2.0-M2：活跃历史评论

- [x] Active Thread Registry 与 30/7、90/30 状态机。
- [x] `new_post_lane` 与 `active_thread_lane` 分离；后者生成独立 `comment_refresh` SourceBatch。
- [x] 评论 late arrival 去重、内容版本和互动量快照。
- [x] reply cursor 原样提取、checkpoint 和 unresolved continuation 留痕。
- [ ] TikHub `fetch_comment_replies` 响应合同审阅与完整分页消费。

退出条件：旧帖窗口内新增评论可在次日进入中心数据集且不重复计数。

### V2.0-M3：单写者融合

- [x] SQLite singleton lock 与 Batch consumption ledger。
- [x] SourceBatch → V2 canonical center adapter。
- [x] occurrence/entity/content version/engagement snapshot/relationship debt 分层。
- [x] stable identity conflict fail-closed、事务回滚、late arrival 和 no-change。
- [x] profile SHA 漂移仅在受影响比较窗口内关闭跨周期比较；旧漂移退出窗口后自动恢复。
- [ ] V2 canonical center → 现有完整 V3 canonical/reports/insights 构建链桥接。

退出条件：同批次重放 no-change；历史与日报并行时 canonical 结果确定且可回滚。

### V2.0-M4：报告与洞察统一

- [x] 建立统一 V2 metric release；日报、周报、月报周期和 profile 可比性同源。
- [x] overview/reports/insights/personas/cases 五个独立 artifact 绑定同一 metric release ID 和 SHA。
- [ ] 使用最新完整 V3 canonical 基线重建 Momcozy、竞品、品类/SPU、画像和四模块洞察成品。
- [ ] 对新 candidate 执行现有前端全页面数据合同与浏览器 E2E。

退出条件：页面不再存在数据版本分叉；所有核心指标可追溯和解释。

### V2.0-M5：自动 candidate 与受控上线

- [x] passed SourceBatch receipt + 双点静稳 → fusion → metric release → candidate registry 本地编排。
- [x] 独立 V2 candidate validator，从只读 SQLite 重算账本、指标、ID 和五 surface artifact SHA。
- [x] 相同输入重放 `no_change` 且 immutable receipt 字节一致。
- [ ] 连续两个真实每日 shadow 周期与旧链对账。
- [ ] 完整数据、报告、浏览器和回滚验收。
- [ ] 精确 packet/release 授权后才允许生产提升。

退出条件：自动链不触碰 production；受控提升后采集器、cron、共享设施和其他 Docker 不变。

## 10. V2.0 验收指标

### 数据正确性

- occurrence accounting、post accounting、comment accounting、coverage accounting 均为 100%。
- `stored comments = linked + unresolved-parent + quarantined`。
- 重叠窗口重复实体和评论不会重复进入指标。
- 所有 UI/报告记录具有 release、metric、canonical 和 raw lineage。

### 运行可靠性

- 相同输入 byte-identical/no-change。
- checkpoint 恢复不重发已成功页、不突破预算。
- 日报优先，历史任务失败不影响每日闭合。
- 任一校验失败时 production current 不变。

### 产品完整性

- 日报、周报、月报均有真实数据、解释、趋势和可用比较值。
- 概览浓缩全站高价值信息。
- 洞察四模块和画像使用最近季度统一数据集。
- 案例广场保留存量，只接入已批准增量。

## 11. V2.0-M1 实施结果

本批已经完成：

1. 通用不可变 raw artifact sink。
2. 日报 TikHub/browser discovery、detail 和 comments 原始响应落盘。
3. daily SourceBatch exporter、CLI 和日报脚本影子产物接线。
4. backfill raw archive → historical SourceBatch 只读适配器与 CLI。
5. fixture、tamper、no-change、缺失 raw fail-closed 和组合回归。

仓库内最新本地回溯数据只读 smoke：

```text
run_id=backfill_momcozy_v2_20250101_20260714
source_status=seed_complete
source_batch_status=partial
posts=102
comments=3132
raw_objects=136
unresolved_continuations=27
validation_status=passed
```

`partial` 是有意的事实表达：现有回溯库证明种子导入完成，但不等价于在线 discovery 和
hydration 全范围完成。该批次可以进入后续中心融合，同时保留
`historical_seed_only_coverage` 覆盖债务。

## 12. 本轮 M2-M5 本地实施结果

实现入口：

- `src/reddit_voc/comment_refresh.py`
- `src/reddit_voc/v2_center.py`
- `scripts/orchestrate_reddit_v2_candidate.py`
- `scripts/validate_reddit_v2_candidate.py`
- `tests/test_v2_center_pipeline.py`
- `tests/test_validate_v2_candidate.py`

真实本地历史子集融合 smoke（不是活跃刷新、趋势或完整 V3 smoke）：

```text
source_batches=1
canonical_posts=102
canonical_comments=3132
entity_occurrences=3234
content_versions=3234
engagement_snapshots=3234
active_thread_registry_rows=102
active_threads_as_of_cutoff=0
relationship_debt=0
comment_parent_linked=3132
comment_quarantine=0
raw_terminal_entity_observed=102
raw_terminal_no_entity=34
candidate_status=local_candidate_registered
candidate_promotable=false
independent_validation_status=passed
replay=no_change
daily_weekly_monthly_current=0
daily_weekly_monthly_previous=0
```

新审查修复后证据位于：

- `tmp/v2-source-batch-smoke-20260717-r3`
- `tmp/v2-pipeline-smoke-20260717-r6`

该 smoke 证明 receipt 绑定、raw/occurrence 终态守恒、父评论关系、中心融合、不可变重放、
指标独立重算和五个 surface artifact SHA。`attempt-created.json` 与
`attempt-no-change.json` 分别记录首次消费和独立重放；重放的 fusion、metric、candidate 均为
`no_change`。历史子集 SourceBatch 状态为 `partial`，所以日/周/月比较均保持
`comparison_available=false`、`comparison_blockers=["coverage_incomplete"]`、
`voc_change=null`，不会把覆盖扩张误报为趋势。该 smoke 不证明真实每日趋势、Provider reply
分页、完整 V3 桥接或浏览器 E2E。

本地手工入口 `scripts/run_v2_daily_pipeline.sh` 只生成 SourceBatch、融合、metric、candidate、
attempt receipt 和独立 validation receipt。入口会在 refresh 与校验完成后等待静稳期，再重新
取得 orchestration observation 时间；它尚未接入系统 cron，也不触碰生产 current。本轮 65 项
V2 聚焦测试通过，其中包含成功批次时间窗缺口、伪造 closure 证据和 fresh wrapper 时序测试。

## 13. 尚未关闭的集成阻塞

### B1：reply cursor 响应合同

现有代码和 raw 能可靠提取 `more.cursor`，但仓库没有已审阅的
`/api/v1/reddit/app/fetch_comment_replies` 响应 fixture/字段合同。V2 当前把该状态导出为
`partial + unresolved_continuations`，不会猜测解析。需要一次受控 fixture 采集或已有脱敏响应，
才能完成完整分页解析、恢复和预算测试。

### B2：完整 V3 基线桥接与页面激活

现有生产数据为 3,494 帖、27,158 stored comments。2026-07-17 已完成 B2a“完整基线进入
V2 中心”的本地闭环，不再使用 102/3,132 子集代表完整基线：

```text
V3 canonical manifest/independent receipt
→ immutable SourceBatch V2
→ passed SourceBatch receipt
→ single-writer V2 center
→ immutable bridge receipt
→ identity zero-diff receipt
```

实测守恒为 3,494 帖、27,158 存储评论 = 20,205 已关联 + 6,943 待父帖关联 + 10 隔离；
帖子和评论 identity 的 missing/unexpected 均为 0。完整 SourceBatch manifest SHA-256 为
`fcb6b5d18e823e2b63feacc906fa2c4a0fd8807a1561d4f155d6cf6912abd77d`，candidate SHA-256 为
`13fbfcbbbad2f9170780ea2489b0aebec8a52345c05b8668881d688076aefc55`，独立 candidate validator
和零差异 validator 均 passed，重复编排的 fusion/metric/candidate 均为 `no_change`。

B2b“从中心激活完整网站”已在 2026-07-17 完成本地闭环：

```text
validated V2 center baseline
+ consumed daily/comment-refresh SourceBatch delta
→ new center state
→ facts/metrics/reports/insights/personas builders
→ frontend candidate
```

B2b 激活 manifest SHA 为
`670964755588b9a9c7eb8a0744c0dc614090904cb1ff76459a3d99055c5a3a14`，独立验证 receipt SHA 为
`7690e9786d36e838fa95cdf613908a5608d3aaee430bf8782bbf4ec1019598a8`。frontend source
`454598e73f7bacfa9da0b68f562bf65d571aaa922cc98aff293c00ad85debcab`、本地 release
`f335d9d27e168068385d99e022a9a4fc6cd5e898485845c965186e3034325d4b`、同一 dist 26 页面 E2E、
隔离容器 smoke 与两个只读 shadow 周期均已通过。此前 promotion packet 已过期且未消费；生产仍为
`9c4a45f2da54d1fd417ed2930516d49bae526406cf9fbf20325df682e9784cc5`。

因此 B2 数据到页面激活已关闭；V3 candidate-only orchestration 已具备 terminal-marker 合同与
profile → run contract materializer。2026-07-18 又完成两次完整 `add_data` workbook 的
`source-freeze → V3 source manifest → source validator` 本地周期：每次均验证 13,534 条原始行
（2,226 帖、11,308 评论），不触碰生产。下一未闭合项是把其余 V3 builders/validators、same-dist
证据与 registry 接入该真实合同，完成两轮完整 candidate cycle；在此之前不讨论调度或新的生产提升。

该真实链现已推进到 pre-canonical facts：两个 source-freeze run 均独立得到 3,494 帖、27,158
存储评论和 23,586 VOC（3,423 帖子 VOC、20,163 已关联评论 context VOC）。6,943 条待父帖关联评论
继续作为结构债务，不进入 context VOC；不是采集缺失，也不得以零值或自动关联掩盖。

原下游实现债务已关闭：governed-signal loader 现接受调用方显式传入的 facts manifest/receipt SHA，仍保留
schema、计数、边界和 receipt-to-manifest 校验，旧 facts-a2 固定调用保持兼容。两轮真实 source-freeze
均已通过 governed 八表与 26 指标的 candidate-only 独立复算；后续未闭合项是 integrity/persona/casebook/
report/insights/export、same-dist、registry 与页面 E2E，而不是放宽数据门禁或回退旧 facts。

M1 本地实施不启用新调度、不运行真实 Provider、不写生产数据库、不构建或提升生产 release：

```text
production unchanged
provider_call=false
database_write=local-test-only
production_database_write=false
remote_write=false
deploy=false
schedule_change=false
live_send=false
```

## 14. 独立审查与当前验收结论

独立只读审查任务 `019f6f1c-1335-7150-88ab-cd53f28fc205` 经四轮闭环后给出：

```text
PASS — V2 本地控制平面
B1/B2 integration blocked
production unchanged
```

最终审查从需求完整性、逻辑正确性、边界情况、代码质量、测试覆盖和实际运行结果六个方面
复验，P0/P1/P2/P3 均为 0。审查依据为 16 个文件的 reviewed SHA、65 项 V2 聚焦测试、r6
历史子集 smoke、五 surface SHA、独立 candidate validator 和 created/no-change 重放证据。

该历史 PASS 不扩大其当时证据边界。此后 B2a 完整 3,494/27,158 V3 baseline bridge 与 B2b
页面数据激活、E2E、container smoke、两个只读 shadow 周期均已在本地完成并独立验证；B1 Provider
reply schema fixture 仍未完成。
未执行 Provider、生产写入、cron 变更、部署或 live send。

全仓 `unittest discover` 使用系统 Python 运行 1,312 项，结果为 7 failures / 18 errors；其中
大量 error 来自系统环境缺少 `openpyxl`、`PIL`、`pytest`，failure 还包含历史 frozen manifest
漂移、SQLite schema drift 探针和 daily release import closure。它们未被冒充为绿色，也不改变
本轮 65 项 V2 聚焦验收，但在完整 V3 bridge/E2E 阶段必须重新按项目依赖环境归零。
