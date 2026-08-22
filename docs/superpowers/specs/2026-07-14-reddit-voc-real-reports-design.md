---
title: Reddit VOC 真实日报周报月报设计
doc_type: design_spec
status: approved
created: 2026-07-14
updated: 2026-07-14
owner: codex
decision: separate_reports_route_existing_ui_dual_window
implementation_status: locally_implemented_and_validated
validation_status: passed_local_data_ui_browser
production_boundary: production_unchanged
provider_call: false
database_write: false
live_send: false
deploy: false
---

# Reddit VOC 真实日报、周报、月报设计

## 1. 决策

采用方案 A：保留当前真实数据概览 `/dashboard`，新增独立报告入口 `/dashboard/reports`，复用既有日报、周报、月报标签页、组件、视觉系统和导出交互。报告数据由新的版本化静态报告覆盖层提供，不再调用 `reportEngine.ts`、`unifiedEngine.ts` 或各类 `*ReportMock.ts` 生成随机数据。

报告采用用户于 2026-07-14 批准的双口径：

1. 网站当前报告使用以快照 `generated_at_utc` 为唯一锚点的滚动 `24h / 7d / 30d` 窗口。
2. 归档报告使用 `Asia/Shanghai` 闭合日历周期：昨日、上周一至周日、上一个自然月。
3. 当前报告与归档报告共享同一指标定义、证据边界和验证器，但拥有不同 `window_mode` 和 `report_id`。
4. 没有真实数据或采集覆盖证据时生成“覆盖缺口报告”，不使用 Mock、零值或推算补齐。

当前设计只授权本地静态数据构建和 UI 接入，不授权生产写入、Provider 调用、Webhook、DingTalk 发送、部署、定时任务修改或 Git commit。

## 2. 方案比较

### 2.1 方案 A：独立报告入口，复用原 UI（采用）

- `/dashboard` 保持当前真实数据概览。
- `/dashboard/reports` 通过独立的只读视图复用原日报、周报、月报的标签、卡片、配色与导出交互，不直接加载带发送副作用的旧 `Dashboard.tsx`。
- Sidebar 仅新增一个“报告”入口。
- 原报告组件只在分析维度缺乏真实数据支持时做条件隐藏、改名或边界说明。

该方案最符合“不轻易修改之前 UI”的要求，也避免把报告功能和概览页挤在同一页面。

### 2.2 方案 B：报告重新成为 `/dashboard` 首页（不采用）

优点是报告曝光最高；缺点是需要迁移已经通过真实数据激活的概览路由，并改变用户已有导航路径。

### 2.3 方案 C：把三类报告嵌入当前概览（不采用）

优点是只有一个入口；缺点是页面过重，原报告布局和当前概览的信息层级都会被破坏。

## 3. 目标与非目标

### 3.1 目标

- 日报、周报、月报成为网站 P0 核心能力。
- 保留原报告页面的视觉、标签页和主要交互，不重新设计整套 UI。
- 所有可见数字都能回溯到当前真实静态快照或已通过语义门禁的 Insights 覆盖层。
- 网站滚动报告与闭合日历归档使用明确、可重复计算的时间窗口。
- 将 Momcozy、竞品、多品牌和通用品类内容分开，避免错误品牌归因。
- 无法支持的 ROI、市场份额、响应时长等指标 fail closed。
- 报告加载不产生 Webhook、DingTalk、数据库或 Provider 副作用。

### 3.2 非目标

- 不在本批接入实时数据或腾讯云生产数据库。
- 不修改现有采集调度、07:00 采集或 08:00 日报发送流程。
- 不执行真实消息发送、定时归档任务或部署。
- 不把 `consumer_card` 当成用户级 `persona_id`。
- 不在本批生成真实 `persona_tags`；真实画像继续作为报告激活后的独立管线。
- 不在本批修复全部 held 标签；报告首版只消费当前通过语义门禁的标签。
- 不保留仅为填满原 UI 而存在的 Mock 指标或图表。

## 4. 已验证基线

基础数据版本为 `reddit_voc_site_snapshot_20260714_v1`，包含：

- 221 个唯一帖子；
- 4,549 条关联评论；
- 4,435 条进入 VOC 指标的评论；
- 18 条隔离评论；
- 帖子和评论实体情感、topic、pain point、subreddit、品牌提及和词典规则标签；
- `production unchanged`、`provider_call=false`、`live_send=false`。

语义 Insights 覆盖层为 `reddit_voc_insights_20260714_v1`：

- 10 个高频 aspect 标签、100 条上下文复核；
- 仅 `L0-GEN-075 工作场景` 和 `L0-GEN-103 强烈推荐` 晋级；
- 其余 8 个标签保持 `held`；
- `consumer_card_is_reference_not_persona_id=true`；
- `persona_tags_generated=false`。

报告 UI 基线已经存在：

- `src/pages/Dashboard.tsx`；
- `src/components/DailyReport.tsx`；
- `ReportDailyView.tsx`、`ReportWeeklyView.tsx`、`ReportMonthlyView.tsx`；
- 原 UI 当前由 `reportEngine.ts`、`unifiedEngine.ts` 和多个 Mock 文件供数；
- 当前 `/dashboard` 路由已绑定 `SnapshotDashboard.tsx`，因此原报告 UI 暂未成为可访问的核心页面。

## 5. 时间窗口与报告身份

### 5.1 统一时间锚点

所有窗口以基础快照 manifest 的 `generated_at_utc` 为锚点，不使用浏览器当前时间。这样同一版本数据在任何机器、任何时间重建都得到相同报告。

时区固定为 `Asia/Shanghai`。所有机器字段保留 ISO 8601，页面使用中文可读日期。

### 5.2 网站当前报告

| 报告 | window_mode | 窗口 |
|---|---|---|
| 日报 | `rolling` | `[as_of - 24h, as_of)` |
| 周报 | `rolling` | `[as_of - 7d, as_of)` |
| 月报 | `rolling` | `[as_of - 30d, as_of)` |

当前快照在 `2026-07-14 19:21:32 +08:00` 的已验证覆盖为：

| 报告 | 帖子 | VOC 评论 |
|---|---:|---:|
| 滚动 24h | 8 | 37 |
| 滚动 7d | 83 | 392 |
| 滚动 30d | 85 | 395 |

### 5.3 闭合日历归档

| 报告 | window_mode | 生成语义 |
|---|---|---|
| 日报归档 | `calendar_closed` | 上一个北京时间自然日 |
| 周报归档 | `calendar_closed` | 上一个完整周一至周日 |
| 月报归档 | `calendar_closed` | 上一个完整自然月 |

当前快照对应归档为：

| 归档 | 窗口 | 帖子 | VOC 评论 | 状态 |
|---|---|---:|---:|---|
| 日报 | 2026-07-13 | 12 | 59 | `observed_records_present` |
| 周报 | 2026-07-06 至 2026-07-12 | 67 | 307 | `observed_records_present` |
| 月报 | 2026-06 | 0 | 0 | `coverage_gap` |

月报归档的 0 不能解释为 Reddit 讨论量为零，因为当前静态数据没有证明 2026 年 6 月采集覆盖完整。页面必须显示“当前快照无可证明记录且采集覆盖未验证”，不得显示增长率、环比下降 100% 或空洞 KPI。

### 5.4 比较与趋势边界

当前快照不包含连续、逐日的采集成功率或覆盖率台账，因此：

- 可以展示当前窗口内的已观察帖子、评论和情感分布；
- 可以展示按小时或日期分桶的“已观察记录量”；
- 不得仅凭前后窗口记录量宣称增长、下降、爆发或市场趋势；
- 所有跨期比较默认 `comparison_status=coverage_unverified`；
- 只有未来显式接入 collection coverage ledger 且当前窗口与对照窗口都通过覆盖门禁后，才允许显示变化率和趋势箭头。

## 6. 版本化报告数据覆盖层

新数据集版本固定为 `reddit_voc_reports_20260714_v1`，输出到独立目录，不修改基础快照或 Insights 覆盖层。

### 6.1 文件布局

```text
reddit_voc_reports_20260714_v1/
  manifest.json
  report-index.json
  current/
    daily.json
    weekly.json
    monthly.json
  archive/
    daily-2026-07-13.json
    weekly-2026-07-06_2026-07-12.json
    monthly-2026-06.json
```

`manifest.json` 记录：

- report dataset schema/version；
- 基础快照版本和 manifest SHA-256；
- Insights 版本和 manifest SHA-256；
- 标签字典版本和 SHA-256；
- 所有报告文件的 byte size 和 SHA-256；
- 报告数量与窗口身份；
- 数据、画像和副作用边界。

`report-index.json` 提供 current/archive 报告列表、显示名称、窗口、记录量、覆盖状态和文件引用。

### 6.2 单份报告契约

每份报告包含以下稳定模块：

1. `identity`：`report_id`、`period`、`window_mode`、dataset version。
2. `window`：开始、结束、时区、as-of、是否闭合、coverage status。
3. `headline`：帖子数、VOC 评论数、隔离边界、帖子/评论情感计数和分母。
4. `observed_timeline`：按小时或日期分桶的已观察帖子、评论和情感。
5. `communities`：subreddit 帖子、评论和情感构成。
6. `topics`：帖子 topic 的实体计数。
7. `pain_points`：评论和帖子中可证明的 pain point 实体计数。
8. `brand_mentions`：同一窗口内的品牌提及帖子数，标签必须为“样本提及”，不得称市场份额。
9. `promoted_signals`：只包含 Insights 覆盖层中已晋级的标签。
10. `attention_items`：按确定性规则筛选的高互动负面或高严重度内容，名称为“关注项”，不宣称危机或紧急响应 SLA。
11. `evidence_posts`：用于回到原始 Reddit 内容的稳定证据实体。
12. `capabilities`：当前支持、条件支持和不支持的分析维度。
13. `interpretation_boundaries`：趋势、品牌、画像、ROI 和用户数边界。
14. `runtime_boundaries`：生产、Provider、数据库和发送边界。

### 6.3 分母与粒度

- 帖子情感分母：窗口内唯一 `post_id`。
- 评论情感分母：窗口内 `include_in_voc_metrics=true` 的唯一 `comment_id`。
- subreddit 帖子数按唯一 `post_id`。
- pain point 和标签计数为匹配实体数，不是用户数。
- 品牌提及按明确别名规则命中的唯一帖子数；多品牌帖子可进入多个品牌的提及计数，因此各品牌计数不能相加作为总市场。
- 所有百分比同时携带 numerator、denominator 和精确值，UI 再负责格式化。

## 7. 品牌主体绑定

报告生成器将每个内容实体划分为：

- `momcozy_sentence_bound`：Momcozy 别名与标签证据短语位于同一句；
- `momcozy_entity_cooccurrence`：同一实体同时出现 Momcozy 和标签，但不在同一句；
- `multi_brand`：同一实体明确出现 Momcozy 和至少一个竞品；
- `competitor_explicit`：只出现竞品；
- `category_general`：没有明确品牌。

只有 `momcozy_sentence_bound` 能进入 Momcozy 专属信号摘要。`momcozy_entity_cooccurrence` 只能作为待核查证据，不能写成“用户推荐 Momcozy”。多品牌、竞品和通用品类数据分开展示。

该绑定只说明文本证据关系，不推断作者身份、购买者身份或真实用户画像。

## 8. 标签与画像边界

首版报告只消费两个已晋级标签：

- `L0-GEN-075 工作场景`；
- `L0-GEN-103 强烈推荐`。

held 标签继续出现在数据质量诊断中，但不得进入日报、周报、月报的业务发现或推荐。

标签字典中的 `consumer_card`、`aipl_node`、`story_lines`、`intent_type`、`problem_type` 可以作为报告的参考切面。必须保持：

- `consumer_card` 是标签到洞察卡片的映射，不是 `persona_id`；
- 内容实体计数不是用户计数；
- `persona_tags_generated=false`；
- 在独立 `dim_persona_v1 + persona_tags` 管线通过验证前，不展示用户画像规模、画像占比或画像趋势。

## 9. UI 接入与最小变更原则

### 9.1 路由与导航

- `/dashboard`：保持 `SnapshotDashboard.tsx` 不变。
- `/dashboard/reports`：加载既有 `Dashboard.tsx` 报告页面。
- Sidebar 新增“报告”菜单项；不调整其他菜单顺序、样式或交互。
- 移动端导航仅在空间允许时增加“报告”，否则由页面内链接进入，不压缩既有四项至不可用宽度。

### 9.2 保留内容

- 日报、周报、月报标签页视觉和切换方式；
- 现有 SectionCard、MetricCard、趋势图、列表、表格和导出组件；
- 页面排版、颜色、字号、间距和响应式系统；
- 原始帖子详情/搜索跳转。

### 9.3 必须修改或隐藏的内容

由于真实分析维度发生变化，以下修改是必要的数据真实性修正，不属于重新设计：

- “紧急警报”改为“关注项”，除非未来存在经过验证的危机等级和响应规则；
- “刷新数据”改为“重新加载静态快照”，不得改变 seed 或产生随机数据；
- 自动 Webhook、自动报告摘要推送和页面加载触发发送全部关闭；
- 品牌综合评分、六维雷达、竞品能力雷达和随机竞品趋势默认隐藏；
- 高意向、UGC、平均响应时间、完成率、升级率默认隐藏；
- 内容 ROI、社区 ROI、市场份额、NPS、转化率、KPI 达成率、预测准确率默认隐藏；
- 不支持模块由一个紧凑的“当前数据边界”卡片统一说明，不保留一组空图表；
- 页面顶部增加数据版本、窗口和 coverage status，不改变主视觉结构。

### 9.4 数据服务

新增报告静态加载服务，行为与现有 Reddit snapshot/Insights 服务一致：

1. 先加载 manifest；
2. 验证 schema、dataset version、基础快照和 Insights hash binding；
3. 加载 index 和目标报告文件；
4. 使用 Web Crypto 复核文件 SHA-256；
5. 验证计数、窗口、晋级标签、画像和副作用边界；
6. 任一检查失败时停止指标渲染，不回退 Mock。

真实报告路由通过 `reports.ts` 和 `useRedditReports.ts` 加载 current 与 archive 六份报告，不导入旧 `reportStore`。`dataSeed`、`refreshSeed()` 和 `generateReportData()` 不再用于真实报告路由，但保留文件本身供未迁移的开发样例使用，避免无关清理。

## 10. 报告内容结构

### 10.1 日报

日报回答“过去 24 小时出现了什么需要关注的真实声音”：

1. 窗口和覆盖状态；
2. 帖子、评论与情感概览；
3. 小时级已观察记录量；
4. 关注项和原始证据；
5. 活跃社区；
6. 晋级标签与 Momcozy 主体绑定；
7. 数据边界。

### 10.2 周报

周报回答“过去 7 天哪些社区、主题和已验证信号最集中”：

1. 窗口和覆盖状态；
2. 帖子、评论与情感概览；
3. 日级已观察记录量；
4. subreddit、topic 和 pain point 分布；
5. 品牌样本提及，不称市场份额；
6. 晋级标签的来源与品牌主体拆分；
7. 关注项和下周人工核查建议；
8. 数据边界。

### 10.3 月报

月报回答“过去 30 天有哪些可证明的结构性集中点和数据缺口”：

1. 窗口和覆盖状态；
2. 帖子、评论与情感概览；
3. 日级已观察记录量和缺口；
4. 社区、topic、pain point 和品牌样本提及结构；
5. 晋级标签的字典参考维度；
6. Momcozy、竞品、多品牌和通用品类拆分；
7. 可执行的标签修复和补数建议；
8. 数据边界。

月报不输出 ROI、份额、增长、预测或用户画像结论。

## 11. 错误处理与空状态

- manifest、hash、schema 或基础绑定失败：整页 fail closed。
- 单份报告文件缺失：该周期停止渲染，不回退其他周期或 Mock。
- 窗口内无记录且 coverage 已验证：显示“已验证零记录”。
- 窗口内无记录但 coverage 未验证：显示“覆盖缺口”，不得显示零讨论。
- 晋级标签集合与 Insights 不一致：整份报告无效。
- 报告包含 held 标签业务信号、市场份额、ROI 或 persona 数量：验证失败。
- 浏览器不支持 Web Crypto：停止加载并提示完整性校验不可用。
- 静态页面不得触发通知、Webhook、DingTalk 或任何写接口。

## 12. 验证与验收标准

### 12.1 数据层

- 生成器对相同输入产生 byte-stable 报告文件；生成时间字段来自受控 manifest，不使用当前时间。
- current 和 archive 共 6 份报告全部通过 schema 和 hash 验证。
- 每份报告的帖子、评论、情感、subreddit、topic、pain point 和品牌计数与基础实体重新计算一致。
- 每个晋级信号都来自 Insights 晋级集合；held 标签数量为 0。
- Momcozy 专属信号只使用 `momcozy_sentence_bound`。
- 月度归档明确为 `coverage_gap`，不产生趋势或环比。
- 所有运行边界保持 false/unchanged。

### 12.2 前端

- `/dashboard` 原真实概览继续通过既有测试。
- `/dashboard/reports` 可切换日报、周报、月报。
- 页面沿用原报告 UI 组件和视觉 token。
- 页面不出现 Mock 随机值、市场份额、ROI、NPS、响应 SLA 或 persona 数量。
- 页面加载和标签切换只产生静态 GET，不产生 Webhook 或写请求。
- tampered hash、held 标签注入、画像越界和副作用边界异常全部 fail closed。
- 导出内容只包含当前真实支持字段，并携带窗口和边界说明。

### 12.3 工程验证

- 根目录报告生成器/验证器测试通过；
- 现有数据快照和 Insights 测试继续通过；
- 前端报告服务、store、路由和页面测试通过；
- 前端全量 Vitest、lint 和生产 build 通过；
- preview HTTP route 和所有报告 JSON 返回 200；
- 如宿主浏览器仍被 `SIGKILL`，浏览器视觉验收保持 pending，不用 jsdom 或 HTTP smoke 冒充。

## 13. 实施顺序

1. P0：报告覆盖层 schema、生成器、验证器和测试。
2. P0：品牌主体绑定和 Insights 晋级信号在窗口内的重新聚合。
3. P0：复制版本化报告数据到 UI public，并实现 fail-closed 静态加载服务。
4. P0：新增 `/dashboard/reports` 和 Sidebar 入口，改造 reportStore 为真实静态数据源。
5. P0：在原三套报告视图中隐藏不支持模块、关闭自动发送并接入真实字段。
6. P0：全量数据、UI、构建和 HTTP 验收。
7. P1：修复四个高价值 held 标签并重新抽样，通过后再进入报告。
8. P1：独立实施 `dim_persona_v1 + persona_tags` 真正画像管线。
9. P1：生产实时接入、归档调度和发送另行授权，不由本设计自动执行。

## 14. 运行边界

```text
delivery_mode=versioned_static_reports
production unchanged
provider_call=false
database_write=false
live_send=false
webhook_send=false
deploy=false
schedule_change=false
git_commit=false
independent_human_review=false
consumer_card_is_reference_not_persona_id=true
persona_tags_generated=false
market_share_supported=false
roi_supported=false
trend_claim_supported=false
```

## 15. 实施结果

### 15.1 数据激活

- 已生成 `reddit_voc_reports_20260714_v1`，报告 manifest SHA-256 为
  `5e121a1c773bf1b89862ca95a032aeed24d61d57032f3f8ce35c1afc550ad0ef`。
- 数据集绑定基础快照 manifest
  `f04edef8dc73c8975e4bba56cbeefd8b734fd86f2c5a95aa2a041325503720ef`
  与 Insights manifest
  `6fe8712e2eaacdae620840bc88d64371ac720c338dc392f3d00211b20851d195`。
- current 日/周/月报告分别覆盖 `8/37`、`83/392`、`85/395`
  个帖子/VOC 评论；archive 日/周报告分别覆盖 `12/59`、`67/307`。
- archive 月报没有采集覆盖证据，产物与页面均显示 `coverage_gap` 和“不能解释为零讨论”，不输出零值业务结论。
- 仅消费已晋级的 `L0-GEN-075`、`L0-GEN-103`；8 个 held 标签全部排除。
- `consumer_card` 只作为标签字典参考维度，未生成 `persona_id` 或 `persona_tags`。

### 15.2 必要实现差异

旧 `Dashboard.tsx` 在可见渲染前会进入随机 seed、轮询及 Webhook/通知相关路径。
为满足本设计的静态只读和零副作用要求，实际路由使用
`SnapshotReports.tsx + RealReportView.tsx`，只复用原有报告信息架构、三标签、
卡片、配色和导出体验。旧页面及其 Mock/发送模块未删除，也未被真实报告路由导入。

### 15.3 验证结果

- Python Insights + reports 测试、基础快照/Insights/reports 三个独立验证器通过。
- 报告确定性测试覆盖两个不同 `PYTHONHASHSEED` 的跨进程重建；修复了品牌别名由
  `set` 迭代顺序导致的潜在非确定性，当前产物 byte-stable。
- 前端全量 Vitest `13 files / 91 tests` 通过；lint 退出码 0，仅保留
  `shared.tsx` 的 5 条既有 Fast Refresh warning；生产 build 通过。
- preview 下路由、manifest、index 和六份报告均返回 HTTP 200。
- Chromium 桌面与 390px 移动端完成日报、周报、归档周报和月度覆盖缺口切换；
  console `0 errors / 0 warnings`。页面首次加载和“重新加载静态快照”只发出静态
  GET，没有 POST、Webhook 或写请求。

### 15.4 交付边界

```text
evidence_grade=local_static_data_ui_browser_validated
production unchanged
provider_call=false
database_write=false
live_send=false
webhook_send=false
deploy=false
schedule_change=false
git_commit=false
independent_human_review=false
```
