---
title: Reddit VOC Momcozy Risk Command Center Design
doc_type: design_spec
status: approved_in_execution
created: 2026-07-15
updated: 2026-07-15
owner: codex
decision_owner: project_owner
primary_decision: Momcozy 品牌风险与口碑治理
search_freeze_cutoff_utc: 2026-07-15T04:15:20.214394Z
search_file_mtime_cutoff_utc: 2026-07-15T04:15:20.212680Z
production_boundary: production_unchanged_until_release_gate
design_review_status: implementation_in_progress_rc_frozen
---

# Reddit VOC 风险指挥台、报告分册与受控发布设计

## 1. 决策目标

本版本首先服务老板判断，而不是展示尽可能多的图表。用户已选择的首要问题是：

> Momcozy 当前出现了什么品牌风险，风险由哪个品类、产品族或精确 SPU 驱动，
> 与竞品相比是否异常，证据是否可靠，应由谁在什么优先级下采取什么行动。

产品组合固定为：

- A：风险指挥台，承载老板查看与下钻的洞察主线；
- B：日报、周报、月报分册，承载不同经营节奏的复盘；
- C：数据质量、构建、测试、部署、验收和回滚的受控模块。

Momcozy 是所有指标、比较和行动建议的主语。其他品牌只作为同口径比较方，
不得把竞品声量误写为市场份额，也不得让竞品模块抢占主叙事。

## 2. 第一性约束

1. 网站只消费冻结、可校验、不可变的离线快照，不直连生产 SQLite，不在浏览时调用 Provider。
2. 采集成功、原始报告落盘、内容融合、网站快照生成、生产发布是五个不同证据层级。
3. 帖子数、评论数、趋势、环比和同比必须携带时间窗、分母和覆盖状态。
4. 未通过比较门禁时可以展示“样本内观察值”，但不能生成确定性的增长、恶化或领先结论。
5. SPU 必须区分“品类”“产品族”“精确 SPU”，不允许把歧义产品族强绑到一个 SPU。
6. 标签字典命中是可审计规则证据；未经语义复核的命中保持 provisional。
7. `consumer_card` 是画像参考维度，不是用户身份；头像继续使用合成图，不代表 Reddit 真人。
8. 案例广场保留现有全部存量内容，仅接入审核通过的增量。
9. 采集后台继续是安全外链，不与洞察站共享 token、容器、网络或故障域。
10. 不启用登录；公开页面只展示经过最小化和隐私检查的投影。
11. 业务时间统一使用 Reddit 内容的 `event_created_at_utc` 聚合，并按 `Asia/Shanghai`
    生成闭合日、周、月；`ingested_at_utc` 只用于延迟、回填和版本审计，不能替代业务事件时间。
12. 帖子与评论是两种不同观测实体。除非组件明确显示权重、分子和分母，否则不得默认合并。

## 3. 当前数据事实与差距

### 3.1 已确认事实

- 设计启动时的生产洞察站绑定 `reddit_voc_site_snapshot_20260714_v1`，包含 221 个帖子和
  4,549 条已关联评论。2026-07-15 执行后，生产已切换到本规格的 Base/Insights/Reports/
  Personas V2 链；该句只保留为版本升级前基线。
- materialized SQLite、V2 search/comment/reply 报告与网站静态快照是独立数据层，
  必须按 Reddit ID 去重后再融合。
- `dim_tag_v6.3_final.csv` 有 2,346 条规则，包含风险、责任部门、问题类型、意图、
  画像参考、故事线、业务影响、行动建议、品线、品类和 SPU 等字段。
- 内部产品主数据有 431 个唯一 SPU；标签字典中 254 个具体 SPU ID 均可精确连接到名称，
  但字典仍有大量 `total` 占位行，不能把它们解释为精确 SPU。
- 当前网站运行时只明确识别少量模型别名，精确 SPU 覆盖远低于品类覆盖，
  因此必须显示实体层级和覆盖率。

### 3.2 RC 冻结策略

- 本次老板版的 search 身份集合固定在 task2500 完成时的 cutoff：
  `2026-07-15T04:15:20.214394Z`。这是最后一份纳入报告内部的 `captured_at_utc`；
  对应文件 mtime 为 `2026-07-15T04:15:20.212680Z`，只保留为 provenance，不作为语义 cutoff。
- cutoff 后的 task2600 及后续 search 报告进入下一增量版本，不回写本 RC。
- comment/reply 可以使用晚于 search cutoff 的独立 hydration cutoff，但只能为 RC 身份集合补内容，
  不能把 cutoff 后新发现的帖子带入 RC。
- 本 RC 的 source chain 只允许：冻结时的 current site、materialized SQLite 清单、
  cutoff 内 V2 search，以及只服务这些 RC 身份的 comment/reply 报告。task2600+ 的 search identity
  和由其引出的新 post 均不得进入本 release。
- 仍有 `has_next=true` 的 search lane 必须记录为 coverage debt；本版本是可复现的时间点快照，
  不是“Reddit 全量”。
- 18 个旧非 V2 身份缺少 V2 primary lineage，继续隔离或使用独立适配器，
  不能伪装成 V2 已完整 hydration。

### 3.3 RC 最终证据表

本表是当前 RC 的可重算身份基线，不等同于 Reddit 自然全量：

| 集合/层级 | 数量 | LF SHA-256 或内容 SHA-256 | 解释 |
| --- | ---: | --- | --- |
| V2 semantic | 1,133 | `abf2b0beb0d36976190ed0747c7513434d1ba37c93443402904faa10b69c39bb` | cutoff 内严格语义身份 |
| materialized | 369 | `b99b47e38a097649133dc73c2697349b48a17606b4cbd5bbb21ac8113eaf0310` | 已物化 SQLite 身份 |
| discovery-only | 860 | `fcc58d0e42146355deb93cfbb0e09cae2d657811658b1884eccfb55bec780e7b` | semantic − materialized，V2 hydration 目标 |
| remote union | 1,229 | `14c0aef8393dd7719c9cf363f5aeed1b200ecd7f6227bee3e4cc2b5771f0ff83` | semantic ∪ materialized |
| 当前站点 | 221 | `c2696a02c3eb7ae12f9adf0da6ea2eb84465fee13967c2d1a0f5ba2109cda118` | 生产仍在使用的旧快照 |
| global known | 1,317 | `2e33c55f0345dfca4d06a7b288cefa9c5558b25d707875aa4c2859214dfa8a53` | remote union ∪ 当前站点 |
| net-new vs 当前站点 | 1,096 | `75978eaffe2b0dd284ba902613898899dd9c7fa658a7845b565faf5e2f136743` | 身份层净新增，不等于已激活 |

RC 原始报告已逐文件验证为 2,310 个文件、54,841,372 bytes，文件清单 LF SHA-256 为
`fdb572f560102b3cbdf098fc40daf137109b7c689414b7376cfee9c92034b01c`。其中 842/860 个
discovery-only 身份完成首屏 hydration，生成 842 个帖子、7,044 条已观察评论和 7,886 个
帖子/评论分析实体。剩余边界固定为：18 个 non-V2 lineage 缺口、360 个 reply cursor 债务、
331 个仍有后页的主题、52 条 search lane 覆盖债务。它们都必须进入 C 的 coverage ledger。

最新生产 daily SQLite 的独立只读冻结为 98 个帖子、454 条评论、534 条分析，数据库 SHA-256 为
`de7ecaa360b936f854b37b2ba8fc3e2daf217656f7442f8d4a71fba6a7230c41`；其中 18 条孤儿评论
继续隔离。该 daily 集合需要在最终融合时按 ID 去重，不能直接加到上述身份数上。

正式 Base v2 已完成全源去重与受治理 enrichment：1,299 个帖子、12,847 条 stored comments、
12,837 条 linked comments、10 条 quarantine，manifest SHA-256 为
`124104c1271ec3d45669176ed7b5157fdacb0e816a587f8db5f7ad4adc25381e`。
独立校验状态为 `passed_release_candidate`；该计数不包含 18 个 non-V2 lineage 缺口。

### 3.4 产品/SPU 治理结论

- 审核产品台账覆盖 10 个 Momcozy 产品族；精确 SPU 只允许 M6、M9、V2 Pro、Air 1、
  KleanPal Pro 共 5 个映射对外发布。
- M5、S9、S12、V1 保持产品族级，不使用裸型号强绑 SPU。
- BM03 的内部 SPU 映射与标签字典“温度计”分类存在 taxonomy drift；本 RC 只发布
  Baby Monitor 产品族，禁止启用该错误 SPU 标签上下文。
- 同一内容可以绑定多个产品族；标签提取按每个受治理产品上下文执行并去重。没有产品绑定时只开放
  L0 通用规则，不再用裸 `M5/M9` 自动升级 SPU。
- 产品台账补齐 category-only 与比较品牌归属门禁后的 SHA-256 为
  `cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab`；发布构建必须固定并核验该值。
- Base v2 共形成 708 个产品绑定，覆盖 633 个实体：160 个 category-only、343 个
  family-only、205 个 exact-SPU binding，其中 3 个 BM03 binding 保持 taxonomy blocked。
  帖子、评论与合并 coverage ledger 均通过守恒校验。

### 3.5 执行后状态与剩余缺口

- 动态 `current-release.json`、跨层 manifest/hash、公开 allowlist 与 V2 指针切换已完成。
- site snapshot 构建器已完成动态版本、staging/V2 融合、产品实体和受治理标签上下文；
  正式 Base v2 已通过独立 validator 并切换生产。
- A/B 报告合同已构建；品类、产品族、SPU、风险事件、同比、环比和趋势均受同一
  coverage gate 约束，不可比较窗口保留 null+reason。
- `Insights` 已重排为 Momcozy 风险治理故事线；标签审核只作为治理证据，不再主导页面。
- 搜索仍可作为证据终端，但所有新聚合必须能够以同一筛选条件回到证据集合。
- reply 游标可能尚未完全闭合；未闭合时只能计算已观察评论，不得声称完整评论总量。
- task2600+ 仍排除在本不可变 release 之外，自动增量接入是下一条独立发布链。

## 4. 信息架构

### 4.1 A：风险指挥台

不新增一套视觉系统，保留现有 Sidebar、Header、卡片、Tab、图表颜色和响应式布局。

#### `/dashboard`：老板摘要

页面自上而下回答六个问题：

1. **发生了什么**：当前 Momcozy 高优先级风险主题、负向证据占比、风险动量。
2. **影响哪里**：品类 → 产品族 → 精确 SPU 风险矩阵及覆盖率。
3. **为什么发生**：问题类型、意图、痛点、故事线、社区和时间驱动。
4. **是否异常**：Momcozy 与竞品同口径样本比较；不使用市场份额措辞。
5. **证据是否可靠**：品牌绑定、标签状态、数据覆盖、样本量和可钻取证据。
6. **下一步做什么**：责任部门、建议动作、优先级和复核时点；不提供假执行按钮。

首页只保留 1–3 个核心 KPI，其余作为诊断驱动和 guardrail：

| 类型 | 指标 | 用途 |
| --- | --- | --- |
| Primary | Momcozy 高优先级风险主题数 | 告诉老板需要处理多少个独立问题，而不是堆帖子数 |
| Primary | Momcozy 负向证据占比 | 衡量同一观察样本内负向实体的结构 |
| Primary | 风险动量 | 仅在比较门禁通过时判断风险扩大或收敛 |
| Driver | 受影响品类/产品族/精确 SPU | 定位产品范围 |
| Driver | 社区广度与问题类型 | 判断问题是否跨社区扩散及根因归属 |
| Guardrail | 覆盖可比状态、品牌绑定率、provisional 比例 | 防止把采集和标签缺口误当业务变化 |
| Guardrail | quarantine、游标债务、隐私检查 | 防止不完整或不合规数据进入结论 |

#### `/dashboard/insights`：风险洞察主线

复用现有 `SignalCard`、证据列表、画像参考和边界组件，但顺序调整为：

1. 风险发现；
2. 品类/SPU 影响范围；
3. Momcozy 品牌绑定与竞品上下文；
4. 原因与业务影响；
5. 责任部门与建议动作；
6. 证据列表；
7. 暂缓标签、数据覆盖和解释边界。

held 标签、审计计数和技术边界继续保留，但下沉到故事线尾部，不能占据老板首屏。

#### `/dashboard/analytics`：二级诊断

保留话题、痛点、社区、情感和时间图表，增加统一筛选：

- 品牌：默认 Momcozy，可选择比较品牌；
- 产品：品类、产品族、精确 SPU；
- 风险：风险等级、问题类型、意图、故事线；
- 时间：日、周、月及自定义闭合区间；
- 证据：帖子、评论、社区和标签状态。

任何图表点击后的筛选必须能传递到搜索证据页，并可通过 URL 恢复。

### 4.2 B：日报、周报、月报分册

继续使用 `/dashboard/reports` 和现有 Tab，不创建三套视觉语言。
三种报告共享同一数据版本和指标函数，但问题、比较基线和模块顺序不同。

#### 日报

回答“今天需要处理什么”：

- 新增高优先级风险主题；
- 昨日/近 24 小时 Momcozy 负向证据；
- 受影响品类、产品族和精确 SPU；
- 异常社区和竞品上下文；
- 今日建议动作与证据。

比较优先级：前一闭合日、上周同日、去年同日。最近窗口未闭合时只显示观察值。

#### 周报

回答“本周风险为什么变化”：

- 本周 vs 上周、去年同期；
- 风险主题新增、持续、缓解；
- 产品组合和社区扩散；
- Momcozy 与竞品的同口径负向证据结构；
- 责任部门和下周优先事项。

#### 月报

回答“结构性风险与治理方向是否改变”：

- 月环比、同比和 12 个月观察趋势；
- 品类/产品族/SPU 风险矩阵；
- 长期问题类型、意图和故事线迁移；
- 竞品对照和机会区；
- 治理复盘。没有真实动作台账前，只展示建议与复核状态，不展示虚构完成率、ROI 或响应时长。

### 4.3 C：受控模块

C 不做成公开的“操作后台”。实际构建、测试、部署和回滚继续在离线流水线执行，
网站只显示只读的数据可信度与 release 状态。

只读可信度卡放在 `/dashboard` 与 `/dashboard/insights` 的末端，不新增主导航入口；
只有当未来出现独立数据治理角色和稳定工作流时，才评估单独的数据质量页面。

受控流水线顺序固定为：

1. Freeze：冻结 source files、身份集合、cutoff、count 和 SHA；
2. Admit：验证 report schema、payload SHA、post/comment 主外键、冲突和 quarantine；
3. Enrich：重新运行分析、标签、产品实体和隐私处理；
4. Build：生成 Base → Insights → Reports → Personas → Cases 版本链；
5. Validate：执行数据质量、契约、单元、类型、构建、E2E 和视觉回归；
6. Release：生成 immutable release SHA 和 current 指针；
7. Deploy：只升级独立 insights 容器；
8. Accept：公网、导出、证据钻取、移动端和 non-interference 验收；
9. Rollback：current 指针或容器级回退，不触碰采集应用。

## 5. 数据模型

### 5.1 产品实体三层模型

每个内容实体可绑定零个或多个产品范围，但必须声明绑定层级：

| 层级 | 标识 | 允许来源 | 展示规则 |
| --- | --- | --- | --- |
| 品类 | `category` | 标签字典品线/品类、审核产品目录 | 可用于所有品类级分析 |
| 产品族 | `product_family` | 审核过的公开产品名和无歧义别名 | 只展示产品族，不声称唯一 SPU |
| 精确 SPU | `spu_exact` | 内部主数据精确 join + 单一无歧义别名 | 展示 SPU ID 和 SPU 名称 |

建议记录：

```text
product_binding_id
entity_type
entity_id
category_id
category_name
family_id
family_name
spu_id
spu_name
binding_level
binding_method
evidence_alias
confidence_status
catalog_version
```

一个别名映射多个 SPU 时，最高只能晋级为 `product_family`。启发式 spoken keyword
不得直接升级为精确 SPU。

### 5.2 风险事实表

建议 grain：`entity_id × risk_tag_id × product_binding_id × brand_binding`。

最小字段：

```text
risk_evidence_id
entity_type / entity_id / post_id
event_created_at_utc
brand_binding
brand_names
risk_tag_id
risk_level
default_priority
problem_type
intent_type
story_line
business_impact
dept_owner
suggested_action
product_binding_id
sentiment
severity
semantic_status
source_coverage_grade
```

`brand_binding` 只能使用以下受控值：

- `momcozy_sentence_bound`：同一语句或同一明确产品实体绑定到 Momcozy；
- `momcozy_entity_reviewed`：经审核的 Momcozy 实体绑定；
- `competitor_sentence_bound`：同一语句或明确实体绑定到比较品牌；
- `multi_brand_context`：内容同时讨论多个品牌，不能自动归因到任一单品牌；
- `brand_unbound`：未形成品牌绑定，只能用于无品牌总体探索。

品牌名在帖子其他位置出现，不足以把一条负向评论自动归因给 Momcozy。帖子事实和评论事实分别保存，
首页与报告默认分别展示；`combined` 仅作为显式可选视图，并必须公开固定权重。

同一帖子和评论可以产生多个标签分配，但首页主题数必须按治理后的 risk theme 去重，
不得把标签分配数直接当成事件数或用户数。

`suggested_action` 只表示基于标签字典与证据生成的治理建议。没有外部工单、负责人确认和完成证据时，
网站不得展示“已分派”“已处理”“已关闭”或治理完成率。

### 5.3 比较事实表

建议 grain：`period × brand × product_scope × risk_dimension`。

每条比较同时存储：

```text
current_numerator / current_denominator
baseline_numerator / baseline_denominator
absolute_delta / relative_delta
comparison_type
comparison_status
coverage_reason_codes
query_profile_version
dataset_version
```

## 6. 指标合同

### 6.1 Momcozy 高优先级风险主题数

- 分子：当前窗口内满足品牌绑定、风险规则和最小证据门槛的去重风险主题数；
- 粒度：risk theme，不是帖子数、评论数或标签分配数；
- 品牌：必须为 `momcozy_sentence_bound` 或经审核的 Momcozy entity binding；
- 门禁：provisional 规则可以进入观察区，只有 promoted 或人工批准主题进入高优先级数；
- 最小证据门槛不在代码中凭经验硬编码。首次 RC 先输出各主题的帖子数、评论数、社区数、
  品牌绑定率和时间广度分布，再冻结阈值版本；阈值冻结前首页值标记为 provisional，
  不进入确定性老板结论；
- 禁止解释：NPS、投诉率、市场占有率或真实用户数。

### 6.2 Momcozy 负向证据占比

```text
negative_momcozy_observed_entities / classified_momcozy_observed_entities
```

- 帖子和评论分别计算，再提供明确加权方式的 combined 视图；默认不混合；
- 删除、removed、bot、孤儿和 quarantine 不进入分母；
- 所有数值显示分子、分母和观察窗口；
- 竞品使用相同实体类型、时间窗、社区和覆盖筛选。

### 6.3 风险动量

- 输出绝对差和相对差，不只显示百分比；
- 日报支持 DoD、WoW same-day、YoY same-day；
- 周报支持 WoW、YoY；
- 月报支持 MoM、YoY 和滚动 12 月观察趋势；
- 分母为 0 时相对差为 `null`，不得显示无穷大或伪造 100%；
- `comparison_status != comparable` 时，值只能标为“样本内观察”或不显示。

### 6.4 Momcozy 与竞品比较

允许指标：

- 样本提及帖子数；
- 品牌绑定负向证据数与占比；
- 同一产品范围内的问题类型、意图和痛点结构；
- 社区覆盖和证据样本。

禁止指标：市场份额、SOV、渗透率、销售转化、ROI，除非将来建立完整分母合同和外部事实源。

## 7. 比较与趋势门禁

每个 period/dimension 组合必须得到以下状态之一：

- `comparable`：查询配置、来源集合、事件时间覆盖和实体口径一致；
- `provisional_observed_sample`：可计算样本内差值，但 coverage debt 可能影响方向；
- `unavailable`：分母、窗口或来源不可比，禁止计算。

比较门禁至少检查：

1. 同一 search profile 和标签/产品目录版本；
2. 当前期和基准期均为闭合窗口；
3. lane 对两个窗口具有可比事件时间覆盖；
4. `has_next=true` 未截断目标窗口，或明确降级为 provisional；
5. hydration 规则和评论深度策略一致；
6. 无 schema drift、ID 冲突或未解释的来源缺失；
7. 当前期不是尚在变化的 recent partition。

这套门禁既满足用户要求的同比、环比和趋势，也避免把历史回填深度差异解释成业务变化。

时间窗口合同固定为：日为 `00:00:00–23:59:59.999`（Asia/Shanghai），周为周一至周日，
月为自然月；展示窗口先转换为 UTC 半开区间 `[start_utc, end_utc)` 查询。同比、环比只比较
两个均已闭合的事件时间窗口。回填内容按原始 `event_created_at_utc` 归属历史窗口，
不得按本次采集时间制造“当日新增风险”。另行展示的“本批新增/回填”属于 ingestion 指标。

## 8. 静态版本与增量接入

### 8.1 当前版本指针

移除前端代码中的 `20260714` 固定常量，改为只读取一个发布时生成的、同源不可变指针：

```text
data/reddit-voc/current-release.json
```

指针至少包含：

```text
release_id
generated_at_utc
base_dataset_version / base_manifest_sha256
insights_dataset_version / insights_manifest_sha256
reports_dataset_version / reports_manifest_sha256
personas_dataset_version / personas_manifest_sha256
cases_dataset_version / cases_manifest_sha256
```

loader 先验证 pointer，再逐层验证 manifest、文件 hash 和跨层依赖；任一失败只关闭对应模块，
不能回退 Mock。

### 8.2 增量自动化

每次增量运行只处理新 source manifest 中未处理或内容 hash 变化的 post/comment ID：

```text
detect → freeze → hydrate → reconcile → enrich → aggregate → validate → stage
```

自动化只能产出 `staged_release`。生产 `current` 切换必须满足测试与验收门禁；
失败版本保持隔离，旧 release 继续服务。

## 9. 错误处理与隐私

- ID、payload SHA、父子关系、时间或 permalink 冲突：quarantine，禁止自动择一；
- first page 缺失：帖子可进入 post-only 隔离视图，不能进入完整评论指标；
- reply cursor 未闭合：标记 `partial`，只统计 observed comments；
- 标签冲突或低特异度：保持 candidate/held，不进入高优先级业务结论；
- 产品别名歧义：降级为 product family 或 category；
- 作者：公开投影为 null 或不可逆展示别名，不暴露原始用户名；
- 联系方式和显式用户名提及继续脱敏；
- 浏览器不得触发 Provider、Webhook、数据库写入或采集请求。

评论覆盖分为三个可审计状态：

- `post_only`：没有通过校验的首屏评论，只允许进入帖子指标；
- `observed_first_page`：首屏通过但后续 reply/cursor 未闭合，可进入明确标注的 observed-comments 指标；
- `thread_complete`：该采集合同下的分页与 reply 游标均闭合，可进入完整线程指标。

任何 `observed_first_page` 数据都不能用于“评论总量”“完整讨论深度”或与
`thread_complete` 基准期直接比较；页面必须同时显示覆盖状态和已观察评论数。

## 10. 测试与验收

### 10.1 数据质量

- source 文件 count/bytes/SHA 与冻结 manifest 完全一致；
- post/comment ID 唯一，comment → post 完整，孤儿进入 quarantine；
- search semantic、materialized、site、global 集合关系和 LF hash 可重算；
- 产品/SPU join 无多对一误绑定，歧义项不晋级；
- 所有比较值可由原子事实重算，分子分母一致；
- coverage ledger 能解释每个不可比窗口。

### 10.2 前端合同

- 所有生产 loader 使用同一 current release，不再写死 `20260714`；
- 任一 manifest/hash/依赖链不一致时 fail closed；
- A 首页每个 KPI 能下钻到同筛选证据；
- B 日/周/月使用不同业务编排和正确比较基线；
- C 显示真实 release、cutoff、覆盖和债务，不提供假操作；
- 生产 bundle 不引用 `*Mock` 或 `reportEngine`；案例 seed/legacy 是唯一明确例外。

### 10.3 E2E 与视觉

- 13 个既有路由和新增数据状态在 1440px、390px 下无错误与横向溢出；
- 筛选、Tab、证据抽屉、搜索、分页和 URL 恢复通过；
- 日/周/月 CSV、DOCX 继续验收；PDF/PPT 未真实通过前不扩大完成声明；
- 图表颜色、风险语义、空态、加载态和 reduced-motion 一致；
- 不重新设计 Sidebar、Header、Case Gallery 或营销页视觉。

### 10.4 生产与 non-interference

- 新 release 使用独立 insights 容器、目录、镜像和网络；
- 部署前后采集容器 ID、restart count、cron SHA、网络成员和后台 health 不变；
- 公网 HTTPS、SPA 深链接、静态 manifest、导出和采集后台外链通过；
- 浏览器网络无未知 API、Provider、Webhook 或自动采集请求；
- 回滚只影响新 insights release。

## 11. 发布顺序

1. 完成 RC identity/content/coverage freeze；
2. 生成并验证私有 canonical snapshot；
3. 实现产品实体、风险事实和比较事实；
4. 生成 Base → Insights → Reports → Personas；
5. 实现 current release loader；
6. 使用现有组件完成 A/B/C 页面编排；
7. 本地全量验证；
8. 生成 immutable release；
9. 隔离部署与公网验收；
10. task2600+ 进入下一增量版本，验证自动化接入。

## 12. 实现与验收结论

- 信息架构沿用现有视觉体系和组件，不需要另起一套 UI；
- A/B/C 已分别落实为老板故事线、经营报告分册与离线发布控制面；
- 产品、品牌、时间、实体类型、比较、评论覆盖和动作状态均有显式合同；
- RC 身份、search/first-page/reply cutoff、集合 SHA 与覆盖债务已经冻结；
- 动态 release pointer、产品实体解析器与受治理标签上下文已通过测试并进入 V2 release；
- A/B/C、全量 QA、不可变构建和隔离部署均已执行。剩余工作是 task2600+ 自动增量链与
  生产浏览器直跑补证，不是待补的产品设计决策。

## 13. 固定非能力声明

在相应事实源和门禁建立前，以下能力不得出现在正式结论中：

```text
market_share_supported=false
roi_supported=false
response_time_supported=false
nps_supported=false
user_level_persona_supported=false
realtime_supported=false
browser_provider_call=false
browser_database_write=false
browser_live_send=false
```
