# Reddit VOC 日期、新鲜度与全站页面审计（2026-08-09）

## 1. 执行结论

当前页面仍显示 `2026-07-23`，不是北京时间或浏览器时钟错误，也不应通过把日期文本替换成 `2026-08-09` 来修复。

问题由三条彼此独立、但在页面上被混在一起的链路造成：

1. **数据链路停滞**：当前有效发布的数据截至 `2026-07-23 07:00 CST`，最新可见采集批次为 `daily_collect_20260723_0700`；按现有 07:00 日切与 90 分钟 SLO 分类，2026-08-09 应显示为 `stalled`。
2. **时间语义错误**：前端把“版本与完整性已校验”当成“数据新鲜”，默认使用绿色 `verified`，却没有消费发布指针中的 `freshness.status`、`data_as_of_utc`、采集批次和窗口边界。
3. **生产部署漂移**：本地候选站点与生产站不是同一套页面实现。生产 `/dashboard` 仍是无样式/旧演示版，并显示演示指标；更新数据指针本身不能修好生产 UI。

截至本轮审计，只进行了只读检查、本地浏览器审计与本文档写入；未执行采集、供应商调用、候选发布、生产切换或远端计划任务变更。

## 2. 事实、推断与未知

### 2.1 已确认事实

| 证据面 | 当前状态 |
| --- | --- |
| 当前北京时间 | `2026-08-09`，系统时区为 `Asia/Shanghai` |
| 本地候选发布 | `reddit_voc_release_20260723_daily_v2`，生成于 `2026-07-23T15:00:00Z` |
| 生产发布 | `reddit_voc_release_20260724_dashboard_fix_v1`，生成于 `2026-07-24T07:15:00Z` |
| 两端业务数据截至 | 均为 `2026-07-22T23:00:00Z`，即 `2026-07-23 07:00 CST` |
| 最新可见采集批次 | `daily_collect_20260723_0700` |
| 发布声明的新鲜度 | `partial` |
| 2026-08-09 现时分类 | `stalled`；预期周期结束 `2026-08-09 07:00 CST`，SLO 截止 `08:30 CST` |
| 数据滞后 | 审计时约 17 天 5 小时，远超 90 分钟 SLO |
| 7 月 23 日之后的本地可追踪采集 | 未发现新的 `daily_collect_*`、可发布候选或已切换发布 |
| 2026-08-07 backfill manifest | 只是待运行文件的 SHA 清单，不是已经执行的采集快照或新发布 |

### 2.2 有证据支持的归因

- 仓库任务记录明确显示：07:00 自动 SourceBatch 导出、两条生产采集通道、同批次重放、双周期 shadow、SLO 观测和自动切换没有全部闭环，因此不能把现状称为“每日自动更新”。
- 当前候选登记自动化只处理经审核的本地请求，不负责采集、派生数据重建或生产发布；它无法让数据日期自行前进。
- 前端绿色状态只证明静态发布包通过完整性校验，不证明数据属于今天，也不证明最新计划采集成功。

### 2.3 本轮不能声称已确认的事项

没有当前远端只读授权/回执，暂时不能在以下原因中做唯一归因：

1. 远端 cron 未触发；
2. cron 已触发但采集失败；
3. 新快照已生成但候选构建失败；
4. 候选已生成但未获准/未成功切换。

因此“远端 cron 已坏”目前只是待验证假设，不能当作事实。

## 3. 日期血缘与页面能力图谱

系统至少存在五类日期，必须分别显示和测试：

| 时间概念 | 定义 | 当前示例 | 应用场景 |
| --- | --- | --- | --- |
| 当前时间 | 用户所在地墙钟时间 | `2026-08-09` | 页头、审计时刻；不能代表数据新鲜度 |
| 数据截至 | 已发布数据覆盖到的周期边界 | `2026-07-23 07:00 CST` | 全站统一新鲜度状态 |
| 最新观测 | 单条帖子/评论中最大的事件时间 | 约 `2026-07-23 06:52 CST` | 搜索、工作台明细 |
| 报告周期 | 报告的开始/结束边界 | 日报 `[2026-07-23, 2026-07-24)` | 报告页；结束日可能是排他边界 |
| 发布生成时间 | 静态发布包生成/切换时间 | 本地 7 月 23 日、生产 7 月 24 日 | 版本审计；不能冒充数据截至时间 |

### 3.1 数据源与洞察站逐页审计

| 页面 | 当前日期来源 | 现状 | 主要风险 | 目标状态 |
| --- | --- | --- | --- | --- |
| `/dashboard` | `quarter_insights.period.anchor_date` | 显示 `2026-07-23` | 绿色完整性提示掩盖停滞 | 同时显示发布 ID、数据截至、滞后和 recency 状态 |
| `/dashboard/reports` | 报告索引 `as_of_date` 与半开周期 | 索引日期为 7 月 24 日，最新日报覆盖 7 月 23 日 | 用户可能把排他结束日误认为数据更新日 | 明示“覆盖至/结束边界”，统一北京时间 |
| `/dashboard/search` | 基础聚合中的最新事件 | 最新评论约 7 月 23 日 06:52 | 与全站数据截至缺乏关联说明 | 显示“单条最新观测”和“发布数据截至”两行 |
| `/dashboard/analytics` | 基础帖子全集范围 | 最新帖子约 7 月 23 日 06:21 | 全历史分析容易被误认为实时 | 标注全历史范围、数据截至和覆盖缺口 |
| `/dashboard/insights` | 季度洞察周期 | `2026-04-25` 至 `2026-07-23` | 洞察生成时间和数据窗口混淆 | 明示窗口、anchor、发布版本和 recency |
| `/dashboard/ugc-showcase` | 基础快照最新观测 | 停在 7 月 23 日 | 旧内容看起来像当前精选 | 在页面级状态条继承统一时间上下文 |
| `/dashboard/messages` | 基础快照最新观测 | 停在 7 月 23 日 | 行动项可能被当作今日线索 | 明示数据年龄；默认按发布窗口而非墙钟排序 |
| `/dashboard/settings` | 当前发布指针/基础快照 | 能看到版本，但仍显示绿色已验证 | 最接近真实血缘，却未显示 stalled | 升级为发布诊断页，展示三轴状态和采集回执 |
| `/cases` | 独立静态案例目录 | 生成于 `2026-07-15`，`staleAfter=2026-08-15` | 与 Reddit 主数据的新鲜度被视觉混淆 | 单独标为“静态案例目录”并展示复核/过期日 |
| `?period=live` | 实际无 live 合约 | 未知 period 静默回退到 daily | “今日动态”实际展示 7 月 23 日日报，严重误导 | 实现真 live 合约，或改名为“最新完整日报”并显式 `period=daily` |
| `/`、`/features`、`/how-it-works` | 无动态日期 | 主要是产品说明/演示 | 访客无法判断真实数据年龄 | 增加公共数据状态卡，演示指标永久标注为 demo |
| `/faq` | 静态说明 | 已说明快照/受控发布、无实时承诺 | 没有暴露当前实际滞后 | 补充当前发布、数据截至、计划节奏和异常状态 |

## 4. 代码与产品脆弱点

### 4.1 P0：完整性与新鲜度耦合

`createBaseDataFreshness` 为页面默认构造 `status: verified`，但没有把发布指针中的 freshness 字段映射进 UI；`DataFreshnessBar` 又将 verified 渲染为绿色。结果是：

- 包完整且数据停滞时仍显示绿色；
- `partial`、`stalled`、`stale` 等状态无法到达用户；
- `collector_run_id` 被丢弃，无法追踪最新采集尝试；
- 无法区分“数据旧但可信”与“数据新但校验失败”。

### 4.2 P0：“今日动态”是静默降级而非真实能力

入口硬编码 `period=live`，报告页只实现 weekly/monthly，其他值一律退回 daily。这不是容错，而是语义篡改。未知枚举值必须显式失败、重定向并告知用户，不能静默改变用户选择。

### 4.3 P0：生产站与本地候选部署漂移

生产 `/dashboard` 仍为旧演示 UI，样式与路由能力均未对齐本地候选，并包含演示计数、作者和相对时间。需要将“前端候选资产”和“数据发布指针”纳入同一个可验证发布门禁；两者任一未切换，都不能宣称站点升级完成。

### 4.4 P1：按页面各自解释时间

Dashboard、Reports、Search、Analytics、Insights、Cases 各取不同字段并自行命名。没有中央时间语义，最终会造成：

- inclusive/end-exclusive 边界混乱；
- UTC 与 CST 格式不一致；
- 发布生成日被误作业务数据日；
- 单条最新观测被误作全量覆盖终点；
- 静态案例资产与日更 Reddit 数据共享同一种绿色状态。

### 4.5 P1：自动化只有“局部存在”，没有端到端闭环

采集、候选登记、派生投影、发布许可、生产切换、回读和告警是不同阶段。当前证据表明部分脚本和调度曾存在，但缺少每周期可持久化 attempt receipt、无尝试告警、终态告警、候选/发布超时告警与连续 shadow 证明。

## 5. 最终目标模型

### 5.1 中央时间上下文

建立单一 `TemporalContext`，由发布指针和受控时钟生成，所有数据页面只消费该对象：

```ts
type TemporalContext = {
  nowCst: string;
  releaseId: string;
  releaseGeneratedAtUtc: string;
  dataAsOfUtc: string;
  observationMaxUtc?: string;
  reportPeriod?: {
    startUtc: string;
    endUtc: string;
    endInclusive: boolean;
  };
  expectedPeriodEndUtc: string;
  deadlineUtc: string;
  lagSeconds: number;
  collectorRunId?: string;
  integrity: 'verified' | 'failed';
  recency: 'fresh' | 'partial' | 'awaiting' | 'stalled' | 'stale' | 'failed' | 'rollback';
  coverage: 'complete' | 'partial' | 'owner-attested';
};
```

三个状态轴必须并列，不能互相代替：

- **Integrity**：文件、哈希、schema、计数和引用是否有效；
- **Recency**：相对于计划周期和 SLO 是否新鲜；
- **Coverage**：数据源、时间窗和投影是否完整。

页面正确示例：

- `版本完整性：已校验`（绿色）；
- `数据链路：已停滞 17 天 5 小时`（红色）；
- `数据截至：2026-07-23 07:00 CST`；
- `当前北京时间：2026-08-09 12:43 CST`；
- `采集批次：daily_collect_20260723_0700`。

### 5.2 新鲜度判定唯一来源

复用 `scripts/observe_reddit_data_release.py` 的计划关闭时间、deadline 和状态机，提取为前后端共享契约或在构建时生成标准 freshness payload。前端不得自行发明第二套阈值。

### 5.3 “今日”和“刷新”的严格语义

- 只有最新闭合周期已被包含且满足 SLO 时，才能出现“今日数据/今日动态”。
- 若暂时没有 live 数据合约，入口应改为“最新完整日报”，参数固定为 `period=daily`。
- 未知 period 值必须显式错误或安全重定向，并展示原因。
- “刷新当前报告”应改名为“重新读取当前发布版本”；它只重新读取 pointer，不得暗示触发了采集。

### 5.4 不同节奏资产分开治理

案例目录维持独立契约：`生成于 2026-07-15 / 下次复核或过期 2026-08-15`。不得用主数据的“实时/新鲜”徽标描述案例目录。

## 6. 分阶段执行 TODO 与门禁

### P0：本地时间语义与误导修复

1. 新增 `TemporalContext` 与可注入 clock；固定时钟测试使用 `2026-08-09 Asia/Shanghai`。
2. 将 `createBaseDataFreshness` 改为消费 release freshness、data-as-of、collector run 和窗口字段。
3. 将状态条拆为 integrity、recency、coverage 三轴；`stalled` 使用红色并显示滞后。
4. 修复 `period=live`：优先改名为“最新完整日报”；若要保留 live，先定义独立数据合约与空状态。
5. 统一每个数据页面的 release ID、数据截至和 recency；在报告页明确半开周期。
6. 将 `/cases` 改为独立静态资产状态。
7. 增加固定时钟、未知 period、旧 pointer、partial/stalled、时区与 DST 边界测试。

**P0 验收**：在当前旧 pointer 下，所有数据页继续诚实显示 7 月 23 日数据截至，同时显示 8 月 9 日当前时间和红色 stalled；任何页面不得称其为今日数据。

### P1：远端只读归因与数据恢复设计

获得明确远端只读授权后，按顺序检查：

1. `/etc/cron.d`、cron 服务和实际加载状态；
2. 7 月 24 日以来每次计划周期的启动/终态日志；
3. attempt receipt、供应商预算/限流、磁盘、进程和环境指纹；
4. 输出目录中是否存在未登记快照；
5. 是否存在未晋级 candidate 或失败 permit。

只读审计完成后，把根因归入 A 未触发、B 已触发失败、C 有快照无候选、D 有候选未晋级，再制定精确恢复动作。此阶段不自动调用供应商。

### P2：有界补采、全投影重建与原子候选

1. 明确选择“逐日补齐”或“单次 catch-up 发布”，不得把缺口伪装成连续覆盖。
2. 在授权的供应商预算、时间窗和隔离输出目录内执行采集。
3. 同一 source batch 重建 canonical center、base、personas、governed signals、insights、reports/history、brand health、quarter insights，并单独决定 casebook。
4. 若任何必需投影未重建，禁止混合新旧 pointer；除非契约显式提供每投影 as-of，且 UI 逐项展示。
5. 单一不可变 release pointer 绑定所有数据集版本、哈希、计数和中心快照。

**P2 验收**：哈希/schema/计数通过；页面时间可对账；无未来数据；无混合中心快照；freshness 不为 stalled/failed；覆盖债务显式可见。

### P3：候选验证、生产切换与回滚

严格顺序：

1. 构建候选；
2. 本地单元/集成/构建测试；
3. 全路由浏览器审计与安全 404；
4. 生成精确发布包、许可和回滚包；
5. 同步晋级前端候选资产与数据 pointer；
6. 生产回读 pointer、HTML/CSS/路由和关键页面截图；
7. 记录切换与回滚回执。

当前生产 UI 的旧演示页必须在此阶段作为独立阻断项处理，不能用“数据 pointer 已更新”代替 UI 上线证据。

### P4：自动化与可观测性闭环

1. 分离 collect、candidate build、promotion 三种调度；自动采集不等于自动发布。
2. 每个期望周期必须持久化 attempt receipt，包括失败、no-change 和 rollback。
3. 建议告警：07:05 无 attempt、08:00 无终态、08:30 未形成合格发布。
4. 监控与页面统一复用 `observe_reddit_data_release.py` 的状态语义。
5. 至少运行两个连续 shadow 周期，验证重放幂等、missed-run catch-up、no-change 和回滚演练。
6. shadow 与控制门禁未持续通过前，不启用自动 production promotion。

## 7. 最终验收矩阵

| 门禁 | 必须满足 |
| --- | --- |
| 旧数据诚实性 | 固定时钟为 2026-08-09 时，旧 pointer 显示数据截至 7 月 23 日且状态为 stalled |
| 新发布日期 | 合格新发布后，data-as-of 前进到最新闭合的 07:00 周期；当前时间仍独立显示 |
| 参数安全 | `period=live` 在未实现时绝不静默展示 daily |
| 全站一致性 | 所有数据页显示同一 release ID、recency 与数据截至 |
| 周期语义 | 报告页明确 end-exclusive；Dashboard/Insights 明确 anchor/window |
| 独立资产 | Cases 使用自身 generated/staleAfter 节奏 |
| 生产 UI | HTML、CSS、真实路由均回读通过，不再出现旧演示指标或无样式页面 |
| 发布原子性 | 前端资产与数据 pointer 同一受控门禁晋级，并有回滚回执 |
| 自动化 | 连续两个 shadow 周期有 attempt、终态、发布/不发布原因和告警证据 |

## 8. 本轮浏览器证据

证据目录：`output/audit/2026-08-09/date-lineage/`

代表性截图：

- `04-dashboard.png`：本地 Dashboard 的 7 月 23 日 anchor 与绿色完整性状态；
- `05-reports.png`：报告索引/周期日期；
- `07-insights.png`：季度洞察窗口；
- `10-settings.png`：发布版本与数据源状态；
- `12-today-live.png`：“今日动态”实际回退到旧日报；
- `18-production-dashboard.png`：生产旧演示/无样式 Dashboard。

## 9. 建议执行顺序

下一门禁只执行 **P0 本地修复**：先消除时间语义和“今日动态”的误导，并用固定时钟测试把旧数据状态准确呈现。P0 通过后，再单独申请 P1 远端只读归因授权；在没有归因和预算门禁前，不启动补采或生产切换。

## 10. P0 本地执行回执（2026-08-09）

### 10.1 已完成

1. 建立统一 `ReleaseTemporalContext`：复用后端 07:00 Asia/Shanghai 日切和 90 分钟 SLO 语义，支持注入固定时钟。
2. 状态条拆分为 integrity、recency、coverage 三轴；当前发布真实显示为：
   - 版本完整性已校验；
   - 数据链路已停滞；
   - 覆盖部分完成；
   - 发布数据截至 `2026-07-23 07:00 CST`；
   - 当前北京时间独立显示。
3. 所有八个数据工作台路由均回读到同一发布时效：Dashboard、Reports、Search、Analytics、Insights、UGC、Messages、Settings。
4. “今日动态”入口改为“最新完整日报”，参数为 `period=daily`。
5. 未知报告周期（包括 `period=live`）现在失败闭合，并明确提示“系统未回退到其他周期”。
6. “刷新当前报告”改为“重新读取当前发布版本”，明确不会触发采集。
7. 日报中的“今日/今天/昨日”相对墙钟文案改为“本期/下一步”，避免旧报告冒充当前行动日。
8. Cases 增加独立静态节奏：生成于 `2026-07-15`、内容截至 `2026-07-15`、复核/过期日 `2026-08-15`。
9. 将 corpus-backed 测试的全量门禁超时从 Vitest 默认 5 秒调整为 15 秒，并继续保持文件串行，消除同一用例单跑通过、全量随机超时的脆弱性。

### 10.2 验收证据

- `npm run lint`：退出码 0；无 error，保留 15 条既有 warning。
- `npm test -- --run`：46 个测试文件通过、1 个按条件跳过；223 个测试通过、46 个按条件跳过。
- `npm run build`：TypeScript 与 Vite production build 通过，2666 个模块完成转换。
- 浏览器路由回读：八个数据页面均同时包含 `stalled`、`2026-07-23 07:00`、当前北京时间和版本完整性证据。
- 截图目录：`output/audit/2026-08-09/p0-date-freshness/`
  - `01-dashboard-stalled.png`
  - `02-reports-latest-complete.png`
  - `03-reports-invalid-period.png`
  - `04-cases-static-cadence.png`

### 10.3 未越权执行

P0 没有改变 `current-release.json`、数据快照或报告内容，也没有执行远端只读检查、供应商调用、补采、候选晋级、生产部署或计划任务修改。P1 仍需单独的远端只读授权。

## 11. P1 远端只读归因回执

P1 已于 2026-08-09 完成。用户关于“远端这些日期的数据都采集了”的判断得到 L3 生产只读证据支持：采集连续到 `daily_collect_20260809_0700`；页面停在 7 月是采集后的 candidate/publication 链断开。

同时确认生产 UI 的灾难性渲染来自未编译 Tailwind CSS，且当前运行镜像绕过了受控 UI release pointer。完整证据、能力图谱、风险分级和下一门禁见：

- `docs/reddit-voc-p1-remote-readonly-root-cause-audit-20260809.md`
- `output/audit/2026-08-09/p1-remote-readonly/remote-publication-gap-receipt.json`
