---
title: Reddit VOC V2 报告、概览、案例与画像设计
doc_type: design_spec
status: ready_for_owner_review
created: 2026-07-15
updated: 2026-07-15
owner: codex
decision: option_a_observed_sample_brand_index
self_review: independent_p0_0_p1_0
production_boundary: production_unchanged
provider_call: false
database_write: false
live_send: false
---

# Reddit VOC V2 报告、概览、案例与画像设计

## 1. 已确认决策

Owner 于 2026-07-15 确认推荐方案 A。本版本采用以下业务定义：

1. 概览页恢复总体指数与雷达的视觉结构，但不恢复旧模拟六维分数。
2. 新指标名为 `Momcozy 观察样本品牌指数`，版本为
   `brand_situation_index_v1`，由四个真实数据维度等权计算。
3. 报告页只保留一个业务入口，称为 `最新完整周期`；归档数据继续保留为比较基期与审计证据。
4. 同比、环比能算则显示真实观察样本值，不能算则显示 `—`；右上角 `?` 解释口径与覆盖边界。
5. 指标卡内展示观察样本 sparkline；上升红、下降绿，颜色只表达升降，不表达业务好坏。
6. Owner 提供的品牌使命 PNG 放在概览页首屏、指数雷达上方。
7. 案例广场默认只展示通过质量门禁的策展内容和已审核增量；存量不删除，未通过项进入审核队列。
8. 画像从两张标签卡升级为多证据群组；画像、决策旅程和使用场景保持为三个不同层次。
9. `add_data/` 两份 Reddit Excel 进入同一 V2 数据版本：先按 Reddit 实体身份去重，
   再做字段质量与父帖关联门禁；无法入主数据的记录全量保留在待补全账，不静默丢弃。
10. VOC 使用双粒度事实模型：帖子始终单独形成一条 `post_voc`；每条评论再与其父帖
    组成一条 `comment_context_voc`。帖子不是评论的附属字段，评论也不脱离父帖上下文
    直接冒充完整评论 VOC。

## 2. 目标

- 修复日报趋势轴全部显示 `00:00` 的确定性缺陷。
- 把工程状态转译为老板和运营能理解的报告口径。
- 让日报、周报、月报中的当前值、环比、同比和样本轨迹可快速扫描。
- 在不伪造市场份额、NPS、行业基准或趋势结论的前提下恢复概览总体指数和雷达。
- 确保案例默认结果中的外链均通过明确质量门禁。
- 用帖子、评论、品牌绑定、主题、痛点和标签字典构建可解释的 Momcozy 人群证据群组。
- 将 `add_data/` 的 13,534 个源记录全部纳入身份守恒和去重账，仅让通过
  完整性、时间精度、父帖关联、统一 NLP 口径以及来源选择/指标资格门禁的实体进入
  网站经营指标分母。
- 保持当前 UI 调性、导航和基础组件，不做无关页面重构。

## 3. 非目标与边界

- 不修改采集器、cron、共享 Nginx、TLS、DNS 或其他 Docker 环境。
- 不启用登录。
- 不在浏览器运行时联网搜索案例；案例仍由同源版本化静态索引提供。
- 不把两份原始 Excel 直接复制到网站 `public/` 或浏览器可下载路径。
- 不把帖子/评论实体计数解释为真实用户人数或总体人群占比。
- 不恢复旧 `reportEngine.ts` 的模拟评分、固定行业基准 70、NPS、ROI、转化率、响应速度或市场份额。
- 不用数据覆盖度惩罚或奖励品牌指数；覆盖度独立呈现。
- 不隐藏 open coverage、pending lineage、`fully_hydrated=false` 或 partial coverage。
- 不复用已消费的 production promotion packet。
- 本设计确认不等于 production deploy；生产提升仍需新 release 与新 packet 的精确授权。

## 4. 页面故事线与首屏布局

概览页首屏固定顺序：

1. 页面标题与数据版本；
2. 品牌使命横幅；
3. `Momcozy 观察样本品牌指数`；
4. 既有四张核心数量/结构指标卡；
5. 趋势、品类/SPU、风险、竞品和证据模块。

### 4.1 品牌使命横幅

源资产：Owner 提供的 PNG，2,064 × 386，SHA-256
`c59ebf5583dc703269f663e02144618ec7add70c063d75558bcef2c78e40beed`。

交付规则：

- 复制为项目内版本化静态资产，不在运行时引用临时目录。
- 桌面端完整显示 5.35:1 画面，使用当前卡片圆角与轻边框。
- 桌面端不叠加重复标题，因为原图已包含使命文案。
- 移动端使用同一图片作为装饰性裁切背景，聚焦右侧地球；同时用 HTML 显示等价使命文案，保证可读与可访问。
- 移动端装饰图 `aria-hidden=true`；HTML 文案进入可访问树。
- 不让横幅改变侧栏、页宽或其他页面的视觉系统。

## 5. 品牌指数与雷达合同

### 5.1 名称与解释

- 标题：`Momcozy 观察样本品牌指数`
- 副标题：`近30个完整自然日 · Reddit 已观察样本（非市场份额/NPS）`
- 指标版本：`brand_situation_index_v1`
- 总分范围：0–100，四舍五入为整数。

### 5.2 四个维度

| 维度 | 公式 | `add_data` 融合前诊断输入 | 融合前参考 |
|---|---|---:|---:|
| 帖子样本能见度 | Momcozy 侧 distinct 帖子 /（Momcozy 侧 + 竞品 union 侧 distinct 帖子） | 131 / (131 + 43) | 75 |
| 评论样本能见度 | Momcozy 侧 distinct 评论 VOC /（Momcozy 侧 + 竞品 union 侧 distinct 评论 VOC） | 274 / (274 + 833) | 25 |
| 帖子非负向证据 | 1 - Momcozy 负向帖子 / Momcozy 已分类帖子 | 1 - 17 / 131 | 87 |
| 评论非负向证据 | 1 - Momcozy 负向评论 / Momcozy 已分类评论 | 1 - 14 / 274 | 95 |

计算单位固定为 `side-bound distinct entity observation`：同一实体在 Momcozy 侧最多计
一次，在所有竞品的 union 侧最多计一次。同一实体同时讨论 Momcozy 和竞品时，
可在两侧各计一次；不得因同时提及多个竞品而在竞品侧重复累加。

总体指数使用四个未取整比率求均值，最后只做一次四舍五入：

```text
round_half_up(mean(raw_post_visibility,
                   raw_comment_visibility,
                   raw_post_non_negative,
                   raw_comment_non_negative))
```

融合前原始均值约为 `70.49`，取整为 `70`；该值仅是 `pre_add_data_baseline`，
不是 V2 验收 fixture。最终值必须在 `add_data` 去重、父帖补链、统一标签和统一
情感口径全部通过后，由版本化 analytics 重算并独立对账，不在前端即时拼算。

### 5.3 可用性门禁

- 能见度维度：总分母至少 30，Momcozy 分子至少 10。
- 非负向维度：Momcozy 已分类分母至少 30。
- 任一维度缺失、分母为零或低于门槛：该维度显示 `—`，总体指数也显示 `—`。
- 禁止把缺失维度补零。
- 禁止因缺失而重新分配权重。
- 当前趋势方向门禁为 false，因此指数面板不显示上涨、下降、等级或预测。
- Insights 加载或 SHA/contract 校验失败时，仅指数面板 fail closed；基础概览仍可显示，且不得回退旧模拟分数。
- competitor universe 由版本化品牌 alias 清单冻结，显式排除 Momcozy；`multi_brand_context`
  参与 union，但每个内容实体每侧最多计一次。
- 评论维度只消费已形成完整 `父帖 + 1 条评论` 的 comment-context VOC；
  `parent_link_status=unresolved` 的评论不进指数分母。
- 两份 Excel 的源情感不参与指数；统一 governed sentiment 只是必要条件，不会消除
  source-selection bias。指数仅消费通过 `reddit_voc_metric_eligibility_v1` 的实体。

### 5.4 研判基础

以下指标独立显示，不进入总分；表内数值同样是融合前参考：

| 指标 | 当前值 | 解释 |
|---|---:|---|
| Momcozy 产品关联度 | 145 / 405 = 36% | 品牌绑定实体中可绑定品类/产品族/SPU的观察比例 |
| 完整线程覆盖 | 859 / 1322 = 65% | 帖子级评论结构覆盖状态，不是市场或品牌表现 |

### 5.5 视觉结构

- 左：融合后实际结果 `/100` 环形总分和 `部分覆盖` 中性徽标；重算未通过时显示 `—`。
- 中：四维雷达，坐标轴固定 0–100。
- 右：四维分子/分母、指标版本和研判基础。
- 复用当前 Momcozy 白卡、粉色主色和 Recharts；删除旧默认 `+3.2%`、优秀/良好/需改进等文案。
- 移动端按总分、雷达、明细纵向堆叠，无横向滚动。

## 6. 报告时间与唯一业务入口

### 6.1 `00:00` 根因与修复

当前日报同时包含：

- `observed_timeline`：24 个小时桶；
- `trend.points`：14 个完整自然日窗口，均从本地 `00:00` 开始。

前端错误地按 `identity.period=daily` 把两类序列都格式化为 `HH:mm`，导致14个自然日标签全部变成 `00:00`。

新格式合同：

| 序列粒度 | 标签 |
|---|---|
| hour | `HH:mm` |
| day | `MM-DD` |
| week | 周起始 `MM-DD`；tooltip显示完整起止日期 |
| month | `YYYY-MM` |

- formatter 接收显式 `seriesGrain`，不再从页面类型猜测。
- 所有报告时间、标题和 tooltip 显式指定 `Asia/Shanghai`，不依赖浏览器本地时区。

`add_data` 的两份工作表将 `发布时间` 全部写成 `YYYY-MM-DD 00:00:00`，但该字段
只能证明自然日，不能证明真实发布时刻。导入合同必须增加：

- `event_time_precision = instant | hour | day | unknown`；
- `source_timezone = known_value | unknown`；
- 两份 Excel 全部标记为 `event_time_precision=day` 和 `source_timezone=unknown`；
- 日精度实体在时间上只允许进入日/周/月候选桶，但是否进入经营总量仍由来源选择与
  metric-family 资格决定；不得被分配到 `00:00` 小时桶；
- 日报小时图只统计 `instant/hour` 实体，并单列 `时间未提供 N 条`，与当日总量守恒；
- 任何导入器不得将日精度强行升格为真实零点时间。

### 6.2 报告入口

- 删除 `当前闭合期 / 闭合归档` 主切换。
- 页面始终读取并展示 `data.current[period]`。
- 文案改为：
  - `最新日报 · YYYY-MM-DD`
  - `最新周报 · YYYY-MM-DD 至 YYYY-MM-DD`
  - `最新月报 · YYYY-MM`
- 辅助说明：`按北京时间已完整结束的自然日/自然周/自然月生成`。
- `闭合期与数据边界` 改为 `统计周期与数据范围`。
- `相邻闭合期` 改为 `相邻完整周期`。
- archive 文件、manifest、SHA 和加载验证全部保留，不删除、不改写历史数据。
- `最新完整周期` 的“完整”只表示时间周期已结束；数据覆盖仍单独显示
  `完整 / 部分 / 不可用`，不得把时间闭合误解为数据全量。

## 7. 同环比指标卡

### 7.1 卡片结构

将现有“环比/同比 × 帖子/评论”的大段文字区，改为四张指标卡：

1. Momcozy 帖子观察量；
2. Momcozy 评论观察量；
3. Momcozy 帖子负面证据占比；
4. Momcozy 评论负面证据占比。

每张卡包括：

- 左上：指标名；
- 右上：键盘可达的 `?`；
- 主值：当前周期值；
- 右侧：该指标 14/13/12 点 sparkline；
- 底部：环比与同比；
- 辅助状态：`已观察样本`、`部分覆盖` 或 `—`。

### 7.2 计算与显示

数量指标：

- 只消费报告合同预计算的 `relative_delta/absolute_delta`，前端不自己重建基期。
- `comparison_status=unavailable`：即使 payload 恰好保留 current/baseline，页面也必须显示 `—`。
- `comparison_status=provisional_observed_sample` 且 current 与 baseline 均有效、baseline > 0：
  显示 `relative_delta × 100%`，同时保留覆盖说明。
- baseline 为 0 或缺失：相对变化显示 `—`。
- absolute delta 可在 `?` 中展示，但不得冒充百分比。

负面证据占比：

- current 与 baseline 均有效：显示 `absolute_delta × 100 pp`。
- baseline 为 0 仍可显示百分点变化。
- 任一值缺失：显示 `—`。

禁止规则：

- 不用 `0` 替代 unavailable。
- 不把 `comparison_status=provisional_observed_sample` 隐藏成泛化文案；真实算术值照常显示。
- `direction_claim_supported=false` 时不得写“增长趋势”“下降趋势”或预测性结论。

### 7.3 Sparkline

- 数据源为相同指标的 `report.trend.points`。
- 至少两个有限值才绘制。
- 最后值高于首值：红线；低于首值：绿线；相等：灰线。
- 首尾仅取序列中第一个与最后一个有限值；中间 null 必须断线，不跨缺口连接。
- 颜色只表达升降，不表达好坏。
- tooltip 固定包含：`观察样本轨迹，不代表总体趋势`。
- 数据不足时显示灰色短横线，不制造走势。

### 7.4 `?` 说明

popover/tooltip 必须包含：

- 指标定义；
- 当前周期；
- 比较基期；
- 公式；
- 当前值、基期值和分母；
- coverage/comparison status；
- 中文化 reason codes；
- `方向门禁未通过` 时的明确说明。

`?` 必须可键盘聚焦、Enter/Space 打开、Esc 关闭、关闭后焦点返回触发器，
并在移动端提供不小于 44×44 px 的触达区。

正常的 partial/provisional 状态使用中性信息图标，不使用感叹号。只有实际加载、校验或系统失败才保留错误图标。

## 8. 案例广场质量合同

### 8.1 数据保留与默认展示

- 38 条 curated seed 原记录继续保留。
- 12 条 legacy simulated records 继续保留在审核数据中，但不进入默认搜索。
- 已审核增量 `approved_delta` 进入默认搜索。
- 默认结果集合：`default_eligible curated seed + verified approved_delta`。
- 不删除 Apple Podcasts 条目；在其 canonical link 通过复核或替换前，`default_eligible=false`。

### 8.2 质量门禁

每条默认案例必须同时满足：

1. URL 语法有效且最终 canonical URL 使用 HTTPS；
2. 有限重定向后返回可接受状态；
3. 标题、来源域和内容摘要与案例主题一致；
4. 具有 provenance；
5. 具有 `last_verified_at`；
6. 具有稳定内容哈希；
7. 不与 seed/delta 中的 ID、canonical URL 或内容哈希重复。

网络验证的可复现参数固定为：最多 5 次重定向、连接超时 10 秒、总超时 20 秒，
仅 2xx 进入下一门禁；content-type 不在版本化域名允许列表、网络受限、captcha 或
5xx 一律进入 `review_required`，不自动放行。`verified` 有效期为 30 天，过期后须重新验证。

失败分类：

- `review_required`：网络受限、500、captcha、需要浏览器复核；
- `rejected`：404、确定无关、伪造或来源不匹配；
- `verified`：所有门禁通过。

浏览器页面只消费静态验证结果，不实时访问外部网站。
建立版本化 `verified-seed ledger`，包含 `default_eligible`、`verification_status`、
`last_verified_at`、canonical URL 和内容哈希。加载 delta 失败时也只能回退到
ledger 中通过门禁的 seed 子集，不能回退到全部 38 条。`add_data` 中的 Reddit VOC
不会自动晋级为案例广场内容，除非单独通过案例质量审核。

### 8.3 当前盘点基线

- 38 seed：37 条自动 HTTP 请求返回 2xx；Apple Podcasts 1 条返回 500，保持审核中。
- 12 legacy：9 条 404、2 条 403、1 条网络失败；默认全部排除。
- `approved_delta=0`，后续增量通过版本化索引添加。

## 9. 聚合画像 schema v2

### 9.1 三层业务模型

1. **原子画像标签**：引入 `dim_persona_v1.csv` 的 82 个 persona tag，覆盖
   WHO/WHY/WHAT/WHEN/HOW/EMOTION/TECH 7 维，作为画像事实层。
2. **受众证据群组**：页面主卡，把原子画像标签与 VOC 主题/痛点/品牌/产品证据
   汇总为 8 个可解释的复合群组。
3. **决策旅程与使用场景**：引用 `aipl_node`、`intent_type`、story lines 与
   `consumer_card`，回答“处在什么阶段”和“在什么任务中使用”。

`consumer_card` 的“场景任务卡/决策旅程卡/画像卡”只是业务卡路由，不是人群画像本体，
也不作为 persona ID。

### 9.2 八个群组与原子标签 bridge

映射为 many-to-many，同一 VOC 可以进入多个群组，不要求八选一。范围表达式如
`PER-WHAT-010..013` 包含首尾全部 ID。

| persona_id | 中文名 | promoted `PER-*` bridge | 最终晋级条件 |
|---|---|---|---|
| purchase_decision | 选购决策者 | `PER-WHO-003`；`PER-WHAT-010..013`；`PER-WHEN-009`；`PER-HOW-005,006,008..016`；`PER-EMOTION-011..013` | `topic=purchase_decision` 或 bridge 中任一 promoted persona |
| product_evaluator | 产品评估者 | `PER-WHO-005..007`；`PER-WHAT-001..009,011,012`；`PER-HOW-002..005,010,012`；`PER-EMOTION-005,008`；`PER-TECH-001..003` | `topic=product_evaluation` 或 bridge 中任一 promoted persona |
| competitor_comparer | 竞品比较者 | `PER-WHO-002,006`；`PER-HOW-004,005,016`；`PER-EMOTION-013` | `topic=competitor_comparison`，或 bridge 命中且同 VOC 有 governed competitor entity |
| operations_troubleshooter | 操作与故障求助者 | `PER-WHO-001,005`；`PER-WHY-001..006,012,013`；`PER-WHAT-002,004`；`PER-WHEN-010`；`PER-EMOTION-002`；`PER-TECH-002,003` | 必须有 `topic=troubleshooting` 或 governed operations pain；persona 只增强解释 |
| fit_output_optimizer | 舒适适配与产出关注者 | `PER-WHO-008,009,011,012`；`PER-WHY-001,004,007,008,012,013`；`PER-WHAT-003,004,006..009`；`PER-EMOTION-001,005,006,008` | 必须有 promoted `fit_comfort`、`output_supply` 或 `leakage` 证据；persona 只增强解释 |
| scenario_adapter | 工作与家庭场景适配者 | `PER-WHO-003,004,008..012`；`PER-WHY-002,003,005,009`；`PER-WHAT-002,004,005`；`PER-WHEN-001..012`；`PER-HOW-001,002,004`；`PER-EMOTION-001,007,009` | `work_scenario`、`family_scenario` 或 bridge 中任一 promoted persona |
| service_support_seeker | 服务支持需求者 | `PER-WHO-001,004,005`；`PER-WHY-001,004,006,012,013`；`PER-WHEN-010,011`；`PER-EMOTION-002,004`；`PER-TECH-002,003` | 必须有 promoted `customer_service` 或 `support` 证据；persona 不能单独触发 |
| recommendation_expression | 推荐表达群 | `PER-HOW-006,007,009,010,011`；`PER-EMOTION-001,008,010` | 必须由同一 VOC 已晋级 `L0-GEN-103` 触发；persona 只增强解释 |

`PER-WHY-010`、`PER-WHY-011`、`PER-EMOTION-003` 只保留为原子描述标签，不强行塞入
运营群组。bridge 内容必须物化为 versioned `persona_cohort_bridge_v1` 并绑定 SHA；
assignment ID 固定为
`sha256(voc_id + "\x1f" + composite_persona_id + "\x1f" + cohort_config_sha256)`。

当前没有已晋级的复购证据，因此不使用“忠诚/复购人群”命名；字典里有“复购准备度”不等于
当前 Reddit 样本已出现复购证据。

### 9.3 证据范围

每个群组分别统计：

- `momcozy_direct`：`momcozy_entity_reviewed` / Momcozy 直接绑定；
- `momcozy_multi`：含 Momcozy 的多品牌比较上下文；
- `category_context`：其余品类/竞品背景。

帖子与评论 VOC 分开计数；评论只消费完整 `父帖 + 1 条评论` 上下文 VOC。
同一内容实体在同一群组内去重，在不同群组间允许重叠。每个群组同时保存
`assignment_count` 和 `unique_entity_count`，两者都必须与明细守恒。

### 9.4 证据等级

- `promoted_tag_evidence`：来源标签已通过现有 stratified gate；
- `governed_rule_observation`：来自当前 deterministic topic/pain-point/brand-binding 合同；
- held/mismatch 标签不得作为画像主规则；只能记录在排除账本。
- 原子画像标签与 VOC 标签分开存储：`persona_tag_ids` 只引用 `PER-*`，
  `voc_tag_ids` 只引用 `dim_tag_v6.3_final.csv`。
- `add_data_xlsx` 为新 source stratum；可以生成 evidence-only persona facts，但只有通过字段、
  父帖、统一标签和 metric-eligibility 门禁后才可进入画像数量、占比或群组比较分母。

页面不得把 `governed_rule_observation` 写成逐条人工验证。

样本状态门禁：单个群组合格实体 `n>=30` 才允许比较和排名；`10<=n<30`
显示数量但标为“方向性样本”；`n<10` 显示 `—`，不生成人群结论。

### 9.5 `persona_atomic_match_v1`

字典必须精确绑定 SHA-256 `279b313509141eb0f7432040818e261178fd9f75ec67a947a0cb9e6211799b1e`、
82 行/82 唯一 ID、7 维和 ID regex `^PER-(WHO|WHY|WHAT|WHEN|HOW|EMOTION|TECH)-\d{3}$`。
`keywords` 必须是非空 JSON string array，`confidence_rules` 必须精确为
`{"直接陈述":"A","行为暗示":"B"}`；任一门禁失败，画像模块整体 fail closed。

当前字典有 454 个关键词实例、425 个唯一词、28 个跨标签共享词和 5 个
`[brand]/[platform]` 模板。旧裸子串 matcher 禁用：例如 `app` 不得命中 `happy`。

证据边界：

```text
post_voc:
  persona_text = post_title + post_body
  evidence_field = post_title | post_body

comment_context_voc:
  persona_text = current comment_body only
  evidence_field = comment_body
```

父帖通常与评论作者不同，只可帮助评论做品牌、品类、SPU、主题和指代消歧；父帖的身份、
阶段、偏好、场景、情绪永远不得生成或继承评论的 `PER-*`。Markdown 引用块、代码块、URL
和父帖文本不参与 persona matcher。

`persona_text_preprocess_v1` 固定使用 Unicode 15.0.0 NFKC、Python HTML5 entity decode、
casefold、弯引号转 ASCII apostrophe，并按 `nfkc_ws_v1` 的 code-point 清单统一空白；全过程
保留 normalized span 到 source field/code-point span 的 offset map。Markdown fenced code
（未闭合 fence 删除到 EOF）、inline backtick code、首个非空字符为 `>` 的整行 quote，及
`https?://\S+|www\.\S+` URL 均以等 code-point 数空格替换，换行保留。

preprocessor manifest 必须绑定 `persona_text_preprocess_v1`、Unicode data version、HTML5
entity table SHA、tokenizer regex 和实现代码 SHA；builder/validator 任一运行时表不一致即
fail closed，禁止用浏览器 ICU 重新计算。

segment 只在 `. ! ?` 或换行处切分。tokenizer 固定为 casefold 后的 ASCII regex
`[a-z0-9]+(?:'[a-z0-9]+)*`；keyword 与正文使用同一 tokenizer，多词 keyword 必须连续 token
匹配，pronoun ±4 token 规则不得跨 segment。零 token keyword 使字典门禁失败。

每个命中先生成 `(persona_id, normalized_keyword, field, start, end, token_count)`。对每个
`(voc_id,persona_id)` 独立做 overlap resolution；候选按
`token_count desc, span_length desc, normalized_keyword asc, field_order asc, start asc, end asc`
排序，其中 `field_order=post_title,post_body,comment_body`；greedy 保留不与已保留 span 重叠的
候选。同一 normalized keyword 重复出现只保留最早的 retained span。最终 evidence arrays 再按
`field_order,start,end,normalized_keyword` 升序输出。

`[brand]` 只展开为冻结品牌 alias，`[platform]` 只展开为冻结平台 alias。28 个共享关键词若是
某 persona 的唯一证据，相关候选全部 held；只有该 persona 另有非共享独立证据才解除。
`semantic_pattern` 在 provider-free v1 只作说明，不做自由语义推断。

证据等级与 deterministic confidence：

```text
A direct evidence:
  - keyword 至少 2 个 lexical token；或
  - 字典原词是全大写 acronym；或
  - 单词命中与 i|me|my|mine|we|our 在同一句前后 4 token 内
B behavioral hint:
  - 其余合法单词命中

fact evidence_class = A if any retained evidence is A else B
base(A)=0.80; base(B)=0.60
distinct retained keyword count >=2: +0.10 exactly once
distinct retained keyword count >=3: +0.05 exactly once
count >3 不再加分；v1 无其他 corroborator bonus
cap=0.95; ROUND_HALF_UP 到 2 位
```

上述 confidence 是版本化规则强度，不是统计准确率。只有 `confidence>=0.80` 且无 blocker
才 promoted；其余进入 held ledger。闭集 held reason：

```text
empty_or_ineligible_text / parent_only_evidence / quoted_or_code_only_evidence
ambiguous_shared_keyword / template_placeholder_unresolved / weak_single_keyword
exclusive_conflict / dictionary_or_hash_mismatch / missing_evidence_span
```

`PER-TECH-001/002/003` 是唯一硬互斥组：最高分必须比次高至少 0.15，否则相关候选全部 held。
其他维度允许真实多标签共存。B-only 最高为 0.75，因此保持 held。每条 atomic fact 保存：

```text
voc_id / source_entity_type / persona_id / decision_status=promoted|held
confidence / evidence_class=A|B / matched_keywords[]
evidence_spans[{field,start,end,normalized_keyword,evidence_hash}]
decision_reason / dictionary_sha256 / matcher_version / snapshot_id
```

`evidence_hash=sha256(utf8(field + "\x1f" + start + "\x1f" + end + "\x1f" + source_substring))`。
`matched_keywords[]` 从已排序 evidence spans 投影，不另行重排。数据集 facts 按
`voc_id,persona_id,decision_status`，assignments 按 `voc_id,composite_persona_id` 排序；每行使用
`canonical_json_v1`，LF 结尾。输入顺序不得改变输出 bytes/SHA。

### 9.6 assignment 合同

统一使用 lowercase snake_case 的复合群组 ID；原子画像保持 `PER-{DIM}-{SEQ}`。
每条 assignment 必须包含：

```text
entity_id
source_entity_type = post | comment
voc_type = post_voc | comment_context_voc
voc_id
thread_id
parent_post_id
composite_persona_id
persona_tag_ids[]
voc_tag_ids[]
scope = momcozy_direct | momcozy_multi | category_context
evidence_scope[] = post_title | post_body | comment_body | cross_context
evidence_grade
source_stratum
snapshot_id
```

评论 assignment 必须至少有一条来自当前 `comment_body` 的 promoted persona/VOC/topic/pain
证据；仅由父帖提供的标签不得重复计为每条评论命中。`cross_context` 只允许在当前评论
span 存在且父帖用于消歧时记录，不能表示 parent-only evidence。

每个 `(voc_id,composite_persona_id)` 只允许一条 assignment。`persona_tag_ids[]` 与
`voc_tag_ids[]` 先去重再按 ASCII ID 升序；`evidence_scope[]` 先去重再按固定枚举顺序
`post_title,post_body,comment_body,cross_context`；其他 reason/rule ID arrays 同样去重并按
ASCII 升序。空数组保留为 `[]`，不得省略或写 null；由此保证输入重排不改变 assignment bytes。

### 9.7 隐私与头像

- `author_level_personas=false`；
- `public_author_identifiers=false`；
- `counts_are_content_entities_not_users=true`；
- `population_share_supported=false`；
- 头像为八张本地 512×512 合成插画；
- `real_user_image=false`、`derived_from_reddit_media=false`、`identity_claim=false`；
- alt 文本必须包含 `非真实用户`。

### 9.8 卡片表现

- 头像、群组名、定义；
- Momcozy direct 帖子/评论；
- Momcozy multi 帖子/评论；
- category context 帖子/评论；
- AIPL、intent、story line、主要品类/SPU；
- 证据等级和覆盖说明；
- 不显示人口占比或虚构年龄、地区、职业。

## 10. `add_data` 与双粒度 VOC 融合合同

### 10.1 源数据冻结

| 源文件 | SHA-256 | 数据行 | 帖子 / 评论 | 自然日范围 | 关键质量边界 |
|---|---|---:|---:|---|---|
| `reddit-舆情数据_20260715222622510.xlsx` | `136bbfc5…eabb` | 12,720 | 2,094 / 10,626 | 2025-07-01 至 2025-12-31 | 源情感全空；`content summary` 仅 987 行非空 |
| `舆情数据_20260715223255129.xlsx` | `331f1dce…7a5b5` | 814 | 132 / 682 | 2026-02-15 至 2026-07-14 | 814 行源情感全为“负向”，明显存在筛选偏置 |

两个 workbook 的 OOXML `dimension` 都错误声明为 `A1`，导入器不得信任该值；
必须按实际 `sheetData` 读取，并断言实际范围分别为 `A1:U12721` 和 `A1:U815`。

### 10.2 双粒度 VOC 定义

原始实体层与分析 VOC 层必须分开：原始记录始终使用 `source_entity_type=post|comment`；
只有满足正文和关联门禁后，才物化为以下分析 VOC：

```text
post_voc
  voc_id = post:{post_id}
  source_entity_type = post
  voc_type = post_voc
  analysis_fields = {post_title, post_body}

comment_context_voc
  voc_id = comment:{comment_id}
  source_entity_type = comment
  voc_type = comment_context_voc
  pair_key = (root_post_id, comment_id)
  analysis_fields = {root_post_title, root_post_body, current_comment_body}
```

示例：帖子 `P1` 有评论 `C1/C2`，分析事实为 `post:P1`、`comment:C1(P1+C1)`、
`comment:C2(P1+C2)` 三条；不是只算两条评论，也不是把整个线程合成一条 VOC。

本合同中的“父帖”固定指评论所在的 Reddit 根帖子 `root_post_id`，不是嵌套回复的直接父评论。
根帖 ID 解析器分别生成最多三个候选：casefold 后的 `link_id` 用
`^t3_([a-z0-9]+)$`；permalink 先按 RFC 3986 取 path 并 casefold，再用
`^/(?:r/[^/]+/)?comments/([a-z0-9]+)(?:/|$)`；仅当 casefold 后的 `parent_id` 匹配
`^t3_([a-z0-9]+)$` 时取直接父级候选。捕获 ID 必须匹配 `^[a-z0-9]+$`。
所有非空候选必须完全一致；不一致为
`root_post_identity_conflict` 并 fail closed，全部为空为 `root_post_identity_missing`。
禁止按标题、slug、作者或相似内容回退。`parent_id=t1_*` 只保存为
`direct_parent_comment_id` lineage；即使评论回复另一条评论，分析单元仍是
`根帖子 + 当前这一条评论`，不把整条评论链拼入同一 VOC。

`parent_post_context` 的文本可用合同为：对根帖 `title` 与 `body` 分别执行
`nfkc_ws_v1`，至少一个结果非空即可；两者都非空时按 `title + "\n\n" + body` 组成，
只有一个非空时只用该字段。评论正文也必须在归一化后非空。当前 3,582 条采用的正是
“根帖标题或正文至少一个非空 + 当前评论正文非空”，不是“父帖 body 必须非空”。

分析器不依赖字符串拼接分隔符，而消费字段化 payload。`analysis_input_version` 固定为
`reddit_voc_analysis_input_v1`；每个字段先执行 `nfkc_ws_v1`，空字段保留为空字符串。
用于 identity/hash 的 `canonical_json_v1` 固定为：object key 按 ASCII 升序、RFC 8259
JSON escaping、`ensure_ascii=false`、分隔符 `,`/`:`、UTF-8、无 BOM、无末尾换行。
`analysis_input_sha256=sha256(canonical_json_v1(analysis_fields))`。规则在原字段上执行并记录
field/span，不在 JSON 序列化文本上匹配。

- 帖子始终作为独立 VOC 分析对象，不因存在评论而被替代。
- 一个帖子有 N 条评论，生成 1 条 `post_voc` 与 N 条 `comment_context_voc`。
- `post_voc` 与 `comment_context_voc` 分别进入帖子分析和评论上下文分析；页面、报告、
  标签覆盖、情感、品类/SPU、画像和品牌指标均不得把两种分母混为一个总数。
- 尚未解析父帖的原始评论仍是有效 `comment` 实体并全量入账，但不冒充完整
  `comment_context_voc`；补链后沿用原评论 ID 晋级，不生成第二条评论实体。
- 父帖在评论 VOC 中只作上下文；父帖独有的标签不得复制成 N 个评论命中。
- 评论标签必须记录 `evidence_scope=comment_body|cross_context`；`post_context`
  可用于指代解析和品牌/产品上下文继承，但不得用来重复放大问题、情感或画像。
- 帖子、评论和线程三种分母分开发布；线程指标按 `distinct post_id` 去重。

### 10.3 字段语义与映射

| Excel 字段 | 规范用途 | 禁止行为 |
|---|---|---|
| `舆情ID` | `source_record_id` 和 lineage | 不得直接作为 Reddit canonical ID |
| `舆情链接` | 解析 `post_id/comment_id/subreddit`，并规范化 permalink | 解析失败时不得用内容哈希伪造 ID |
| `内容类型` | `Forum Post -> source post`；`Forum Post Reply -> source comment` | 未补父帖的 reply 不得提前标成完整 `comment_context_voc` |
| `标题` | 导入为 `source_text`；post 行映射 post body，reply 行映射 comment body | 不得机械映射成 Reddit post title |
| `内容概要` | `source_summary`，仅作辅助与质量对账 | 不覆盖原始 body |
| `发布时间` | 自然日 + `event_time_precision=day` | 不得当真实 00:00 |
| `情感描述/相关性/产品分类/问题类别` | `source_supplied_*` 供交叉评估 | 不覆盖 governed NLP 结果 |
| `浏览量/转赞评数/环比` | 私有源审计字段 | 不冒充 Reddit score、comment count 或网站同环比 |

与 Base 重合的样本已证明字段语义：`标题` normalized-exact 匹配已有 post content 的
39/54，匹配已有 comment body 的 731/738；normalized-exact 统一指以下 `nfkc_ws_v1`
归一化后的精确哈希相等，而不是 raw bytes 相等：

```text
nfkc_ws_v1(text):
  1. null -> ""；其余转为 Unicode string
  2. 使用 Unicode 15.0.0 normalization table 执行 NFKC
  3. 将下列连续 code points 折叠为一个 ASCII space：
     U+0009..U+000D, U+0020, U+0085, U+00A0, U+1680,
     U+2000..U+200A, U+2028, U+2029, U+202F, U+205F, U+3000
  4. trim 首尾空白
  5. 不做 lowercase、HTML unescape、Markdown 清洗或标点删除

normalized_text_sha256 = sha256(utf8(nfkc_ws_v1(text)))
normalized_exact = both_nonempty && left_sha256 == right_sha256
```

normalizer manifest 必须记录 `normalizer_version=nfkc_ws_v1` 与
`unicode_data_version=15.0.0`；运行时 Unicode table 不一致时 fail closed，不允许静默用
Node/ICU 或其他版本重算。

raw string 精确相等实际只有 post `24/54`、comment `688/738`；使用上述固定 normalizer
后才是 post `39/54`、comment `731/738`。因此映射依据是 Reddit ID 对账与可复现的
normalized-exact 证据，不是中文列名猜测。

### 10.4 去重与数量守恒

| 层级 | 帖子 | 评论 | 说明 |
|---|---:|---:|---|
| 源行 | 2,226 | 11,308 | 共 13,534 行 |
| `add_data` 内 distinct Reddit ID | 2,226 | 11,305 | 3 条评论是同 ID 重复行 |
| 与 Base A2 精确重合 | 54 | 738 | 只补 lineage，不覆盖 Base |
| 净新增身份候选 | 2,172 | 10,567 | 身份层全部纳入账本 |

净新增中：

- 2,105 个帖子有源 post body，67 个帖子正文待补全；
- 10,500 条评论有 comment body，67 条评论正文待补全；
- 3,624 条评论身份可关联既有或新增根帖，其中 3,582 条同时具备非空评论正文和
  可用 `parent_post_context`，42 条的根帖 title/body 均为空；若错误地强制要求父帖
  body 非空，则只剩 3,578 条并误排除 4 条 title-only 父帖，V2 明确不采用该口径；
- 6,943 条评论指向 3,859 个尚未进入 canonical posts 的根帖，状态为
  `unresolved_parent_context`，不丢弃。

因此当前净新增身份中，文本/根帖上下文门禁之后可进入下一步统一打标的上限为
`2,105 post_voc + 3,582 comment_context_voc = 5,687` 条分析事实；这是打标输入上限，
不是已通过标签/情感/SPU 治理的网站指标分母，更不是 5,687 个用户。

当前源行终局守恒必须精确满足：

```text
13,534 source rows
= 3 duplicate rows
+ 792 exact Base overlap rows
+ 5,687 net-new text-available analysis inputs
+ 6,943 unresolved-parent rows
+ 109 incomplete-text/context rows
```

其中 109 = 67 个缺少 source post text 的帖子 + 42 条已关联但根帖 title/body 均空的评论；
67 条 comment body 为空的评论都已先落入 6,943 条 unresolved-parent，遵循
`unresolved_parent -> incomplete_text` 的终局优先级，不得重复计数。

`ai_nlp_voc/system_data/voc_data/reddit` 的 136 个帖子和 4,153 条评论已做只读交叉，
未找到上述 3,859 个根帖中的新匹配。当前 candidate closure ledger 中命中 3 个根帖，
但其中 1 个是 `window_outside_subreddit_post`、2 个是 `v2_search_identity_lineage_missing`，
只影响 4 条评论；在内容和 lineage 复核通过前仍不视为已补链。

### 10.5 身份与冲突优先级

帖子：

1. 规范化 Reddit `post_id` 为主键；
2. 链接 ID 与任何显式 Reddit ID 不一致时 fail closed；
3. 同 ID 且稳定字段一致时合并 lineage；
4. 同 ID 但正文、时间或 subreddit 冲突时，既有 governed Base 优先，workbook 版本进冲突账；
5. 无权威 Reddit ID 时，内容指纹只能用于近重人工分组，不自动合并。

评论：

1. 规范化 `comment_id` 为主键，上下文唯一键为 `(post_id, comment_id)`；
2. 同 comment ID 指向不同 post 是硬冲突；
3. 同 ID 正文不同时保留 Base，将 workbook 版本记为 source variant；
4. 无 parent post 时进 `unresolved_parent_context`，不构造虚假帖子壳。

固定来源优先级为 `existing governed canonical > add_data workbook`。Base 重合时只允许
补充私有 provenance，不允许用日精度时间、源情感、概要或交互聚合量覆盖
已有高精度字段。

### 10.6 私有标准化产物

两份 XLSX 先转换为独立可验证的私有包，不直接进入 Base：

```text
posts.jsonl
comments.jsonl
row-outcomes.jsonl
parent-link-ledger.jsonl
conflict-ledger.jsonl
manifest.json
independent-validation-receipt.json
```

manifest 绑定 workbook SHA/字节/表头 schema/行数/类型数、每个结果集计数、canonical identity set/hash
与 `workbook + sheet + row ordinal` lineage。每个源行只有一个 terminal outcome，按
`duplicate -> exact_base_overlap -> conflict/rejected -> unresolved_parent -> incomplete_text -> net_new_text_ready`
的固定优先级分类，并满足：

```text
source_rows
= duplicate_rows
+ exact_base_overlap_rows
+ net_new_text_ready_rows
+ unresolved_parent_rows
+ incomplete_text_rows
+ conflict_or_rejected_rows
```

身份全量纳入不等于全部进网站分母。`text_ready_post_voc` 与
`text_ready_comment_context_voc` 只获得进入统一打标的资格；能否进入经营指标还必须通过
source-selection/metric-eligibility 门禁。其他状态在账本中可见且可重入，补全后使用
原定义 `voc_id` 晋级，不产生第二个实体。

### 10.7 来源选择与指标分母资格

第一性原则固定为：

```text
可形成 VOC ≠ 可进入业务指标分母

业务分母资格
= 至少一条独立、非结果筛选、选择框架可证明的 observation lineage
+ 当前 metric family 自身的字段、覆盖和口径门禁
```

合同版本固定为：

```text
source_selection_contract_version = reddit_voc_source_selection_v1
metric_eligibility_contract_version = reddit_voc_metric_eligibility_v1
source_selection_registry_version = add_data_20260715_v1
```

Base、Reports、Insights、Personas 与 public projection manifest 必须绑定上述版本、
`source_selection_registry_sha256` 和 `metric_policy_sha256`；前端不得自行推断资格。

每个 source snapshot 的 registry 至少保存：

```text
source_snapshot_id / source_kind / source_file_sha256
selection_class / selection_evidence_status / source_frame_status
selection_rule_hash / query_profile_hash / coverage_manifest_sha256
selection_window_start / selection_window_end / selection_window_grain
source_timezone / event_time_precision / coverage_status
allowed_metric_families[] / selection_reason_codes[]
```

枚举固定为：

```text
selection_class = non_outcome_monitoring | scoped_query_frame |
                  outcome_conditioned_negative | outcome_conditioned_other |
                  manual_curated | unknown
selection_evidence_status = manifest_verified | owner_declared | empirical_trigger | unknown
source_frame_status = eligible_scoped_observation | pending_source_manifest |
                      ineligible_outcome_conditioned | ineligible_curated
```

`allowed_metric_families` 不是来源自报字段，builder 与独立 validator 都必须按下表重算并
精确一致：

| `selection_class` | `selection_evidence_status` 与 manifest checks | `source_frame_status` | allowed families |
|---|---|---|---|
| `outcome_conditioned_negative` 或 `outcome_conditioned_other` | 任意 | `ineligible_outcome_conditioned` | `source_intake,data_health_identity,evidence_search,tag_assignment,tag_hypothesis` |
| `manual_curated` | 任意 | `ineligible_curated` | `source_intake,data_health_identity,evidence_search,tag_assignment,tag_hypothesis` |
| `unknown` | 任意 | `pending_source_manifest` | `source_intake,data_health_identity,evidence_search,tag_assignment,tag_hypothesis` |
| `non_outcome_monitoring` 或 `scoped_query_frame` | `manifest_verified`，且 selection/query/coverage hash、window 与 grain 全部非空并通过 | `eligible_scoped_observation` | 上述 evidence families + `observed_count,rate,comparison,index,persona_aggregate` |
| `non_outcome_monitoring` 或 `scoped_query_frame` | `owner_declared`、`empirical_trigger` 或 `unknown`，或任一必需 manifest check 缺失 | `pending_source_manifest` | `source_intake,data_health_identity,evidence_search,tag_assignment,tag_hypothesis` |

未声明 enum、空 source snapshot ID、SHA/窗口不合法或 registry 行重复属于 registry invalid，
整包 fail closed，不降级为 pending。`owner_declared` 单独不足以开启经营分母；必须补成
`manifest_verified`。`coverage_status=partial` 在 coverage manifest 已验证时仍可成为
`eligible_scoped_observation`，但对应窗口最多是 `provisional_observed_sample`。

`eligible_scoped_observation` 仅表示可用于已冻结查询范围内的观察样本，不代表 Reddit 总体、
真实用户总体或市场份额。当前初始分类为：

| 来源 | `selection_class` / evidence / frame | 当前处理 |
|---|---|---|
| existing governed Base | `non_outcome_monitoring` / `manifest_verified` / 条件性 `eligible_scoped_observation` | 仅当既有 query/collection/coverage manifest 全部通过时可作 metric anchor |
| 12,720 行 workbook | `unknown` / `unknown` / `pending_source_manifest` | 全量进入身份、证据和打标；源情感全空不证明未筛选，暂不进经营分母 |
| 814 行 workbook | `outcome_conditioned_negative` / `empirical_trigger` / `ineligible_outcome_conditioned` | 全量进入身份、负向证据和打标；即使重跑情感也不进经营分母 |

12,720 行 workbook 只有补齐并冻结查询条件、时间窗口、导出范围、分页/覆盖状态，以及
“未按情感、严重度、互动量或人工案例筛选”的来源证据后，才可晋级。814 行来源的
负向筛选属于不可逆的 observation-frame 偏差，重新打标签或情感不能将其洗白。

每个 canonical entity 的 lineage 至少保存：

```text
canonical_entity_id / source_entity_type / source_snapshot_id / source_record_id
identity_match_status / exact_identity_match / lineage_role
independent_observation_proven / metric_anchor_source_id
field_provenance / event_time_precision / text_status / parent_link_status
```

`lineage_role=metric_anchor|supplemental_evidence|only_lineage|conflicting_variant`。指标资格由
独立事实表给出，不用一个无法审计的总开关：

```text
canonical_entity_id / metric_family
eligibility_status = eligible | excluded
eligibility_anchor_source_id / eligibility_reason_codes[] / policy_version
```

54 个帖子和 738 条评论的 Base 重合处理固定为：同 canonical Reddit ID 去重，评论还要验证
相同 `root_post_id`；Base 只有存在独立且合格的 observation lineage 时才是 `metric_anchor`，
workbook 仅为 `supplemental_evidence`。实体只计一次，biased workbook 不增加分母、不覆盖 Base，
也不让合格 Base 实体失去资格。反之，仅“Base 有同 ID”不够，必须证明其合格 lineage；
禁止用同帖、同作者、相似文本或 URL slug 给 biased-only 实体提供资格。

| 用途 | 814 行 negative-selected only | 12,720 行 manifest 未补齐 | 与 eligible Base 精确重合 |
|---|---|---|---|
| 源行盘点、身份去重、父帖补链 | 可 | 可 | 各源入账，canonical 只计一次 |
| 安全搜索、证据回看、governed tag facts | 可，标记 `evidence_only` | 可，标记 `evidence_only` | 可 |
| 标签候选发现 | 可作假设发现，不得按频率自动晋级 | 同左 | 可 |
| 观察量、样本能见度、标签/问题率 | 不可 | 不可 | 凭 Base anchor 可 |
| 情感率、负向占比、品牌指数 | 不可 | 不可 | 凭 Base anchor 且本指标门禁通过时可 |
| 画像占比、Momcozy/竞品结构比较 | 不可 | 不可 | 凭 Base anchor 可 |
| 同比、环比、趋势 | 不进入业务趋势分母 | 不进入业务趋势分母 | 两个窗口比较门禁都通过时可 |

workbook 的 `浏览量` 只作来源审计字段，不等于 Reddit 原生 score/reach。负向筛选源可单列
`selected_negative_case_intake_count`，但只出现在数据质量/来源盘点区，不进入日报主 KPI、
品牌指数或“舆情上升”结论。

每个窗口必须发布 `eligible_entity_count`、`excluded_entity_count`、
`excluded_counts_by_reason`、`source_selection_profile_hash`、`query_profile_hash`、
`coverage_profile_hash` 以及 dedupe/tag/sentiment/persona contract versions。

- `comparable`：当前期和基准期均闭合且有合格分母，来源选择、查询范围、社区、采集深度、
  父帖/评论策略、去重、标签、情感与产品目录口径一致，覆盖门禁通过。
- `provisional_observed_sample`：两期都有确定的合格分母且来源框架一致，但存在 partial
  coverage、晚到数据或 hydration debt；可显示算术值，`direction_claim_supported=false`。
- `unavailable`：任一窗口只有 outcome-conditioned/unknown 来源、来源策略不一致、分母资格
  不成立或基期缺失；显示 `—`。

biased rows 的存在不会自动使整个窗口失效：先排除 biased-only entities，再判断剩余合格
子集；过滤后分母为 0 才 unavailable。趋势中的不合格点输出 `null`，前端不得跨缺口连线。

闭集 reason code 为：

```text
source_selection_unknown / selection_manifest_missing / query_profile_missing
outcome_conditioned_negative / outcome_conditioned_other / manual_curated_source
eligible_base_lineage_missing / independent_observation_unproven / metric_family_not_allowed
measurement_semantics_unknown / event_time_precision_insufficient / coverage_unverified
policy_version_mismatch / baseline_missing / baseline_zero / parent_context_unresolved
text_incomplete / entity_conflict / governed_sentiment_missing / brand_binding_missing
persona_assignment_held / competitor_universe_mismatch / sample_below_threshold
```

新增 reason 必须提升合同版本。独立 validator 必须从 source lineage 重新计算资格，不能信任
builder 自报的 eligibility；任何指标都必须满足
`numerator_ids ⊆ denominator_ids ⊆ eligible_entity_ids`。

## 11. 标签 → 指标 → 指标体系 → 洞察合同

### 11.1 可复用事实源

- 当前附件与 `ai_nlp_voc` 的 `dim_tag_v6.3_final.csv` 字节级完全相同：
  2,346 个唯一 tag、28 字段，SHA-256 `22664c9c…82e14`。当前项目已有该文件，
  不再复制第二份语义源。
- `dim_persona_v1.csv`：82 个 persona tag、7 维，SHA-256 `279b3135…b1e`。
- `indicator_tag_mapping.csv`：8,854 条关系，覆盖全部 2,346 tag，orphan=0，
  SHA-256 `ebb6ee92…9270`。
- `voc-indicator-registry-stable.csv`：43 个 canonical indicator，29 stable / 14 review，
  12 个依赖外部数据，SHA-256 `7a8b0fef…bac`。
- `indicator_storyline_matrix.csv`：43 条触发规则、33 个 indicator code，
  SHA-256 `c017e7f3…ac5`。

上述资产在实施时作为版本化 reference 复制进当前项目，同时派生
`reddit_voc_indicator_registry_v1`。原矩阵存在口径债务：26 个 mapping code 与 33 个 storyline code
仅 19 个经 alias 归一后直接交叉，因此不得把旧阈值/状态原样宣称为 Reddit 已验证口径。

### 11.2 打标主链

```text
text-ready post/comment-context VOC
→ schema/hash/source gate
→ text normalization + ID dedupe + parent linkage
→ Momcozy/竞品品牌识别
→ product_line/category/SPU 实体路由
→ source + entity + sentiment + AIPL 候选池裁剪
→ 规则命中 + 闭集判定
→ 泛化标签二次下钻
→ evidence/conflict/risk 验证
→ confidence 重标定
→ high-risk/manual-review gate
→ entity-tag fact
→ per-entity × metric-family eligibility fact
→ Reddit indicator registry / storyline consumption
```

第一版不调用 provider：复用现有 deterministic rule 与字典候选裁剪，高风险/低证据命中
fail closed 进 review queue。后续若启用 LLM 闭集判定，需另行授权 provider 调用，并保持相同 schema。

候选池目标 `<=100`，硬上限 150；有明确 SPU 证据时优先 L2-SPU，无实体证据时只允许 L0/品牌层，
不得猜测 SPU。每个命中至少保存：

```text
entity_id / source_entity_type / voc_type / voc_id / thread_id / parent_post_id
tag_id / dictionary_version / dictionary_sha256
confidence / evidence_scope / evidence_span_or_hash
decision_reason / label_source / source_stage / snapshot_id
```

### 11.3 四层覆盖率

1. **原始覆盖率**：`n_tags > 0`；
2. **业务有效覆盖率**：过滤低置信、无证据、held 和无理由泛化标签后仍有命中；
3. **经营分母资格率**：业务有效标签事实同时具有合格 metric anchor；
4. **产品可消费覆盖率**：合格实体命中已注册指标、故事线和页面。

帖子、评论上下文、父帖关联、SPU 归属、证据有效、来源资格和指标可消费覆盖率分开报告，
不得用单一“已打标”覆盖所有质量边界。biased/unknown 来源可以有业务有效标签事实，
但经营分母资格必须为 0。

### 11.4 Reddit 第一阶段指标层

| 层 | 可用指标 | 分母要求 |
|---|---|---|
| 数据健康 | 父帖关联率、文本完整率、业务有效标签覆盖率、来源资格率、SPU 绑定率、证据完整率 | 帖子/评论分开；源行盘点可含全部 lineage |
| 品牌健康 | Momcozy 观察量、负向证据率、净情感平衡、代理推荐信号、同口径竞品差距 | eligible metric anchor + 品牌绑定 + 情感合格实体 |
| 品类/SPU | VOC 占比、问题率、环比/同比、Top 问题、品类/SPU 竞品差距 | eligible metric anchor + 实体路由通过 |
| 洞察行动 | 标签紧急度、共现 lift、画像差异、线程放大、异常加速 | eligible metric anchor + 最小样本 + 证据回链 |

标签提及率固定为
`count(distinct eligible entity_id with tag) / count(distinct eligible entity_id)`，不用标签命中行数
代替帖子数、评论数、用户数或 reach。Momcozy 与竞品只在相同周期、`voc_type`、
来源选择 profile、品类/SPU 与证据门禁下对比。

当前不可用的指标显示 `—`：真实 NPS、销售额、ROI、转化率、库存/物流延迟、SLA、
用户级复购/流失/信任恢复、市场份额/SOV 和无完整历史基线的因果/预测。

### 11.5 `reddit_voc_indicator_registry_v1`

旧 registry 的 43 个 canonical indicator 声明了 79 个 raw code/alias，当前 collision=0；
经声明 alias 归一后，tag mapping 有 26 个 code、storyline 有 33 个，交集只有 19。
legacy `status=stable` 不等于 Reddit 可用。

alias bridge 只收集 `canonical_indicator_id`、显式 `aliases[]`、`tag_mapping_code`、
`storyline_code`、`production_code`。标准化仅做 NFKC、trim、ASCII uppercase，不删除或互换
`_` 与 `-`；同一 alias 指向多个 canonical 时构建失败。禁用旧 evaluator 的
`XX-n_suffix -> XX-n` 启发式回退；未知 code 一律 held，reason 为
`unregistered_indicator_alias`。旧指标与 Reddit 指标的关系仅允许
`equivalent|adapted_from|reference_only|not_supported`，只有 `equivalent` 才能成为 alias。
`BM-1/BM-1_NPS` 不得 alias 成推荐表达率或 NPS 替代值。

每个 Reddit 指标 registry row 必须包含：

```text
reddit_indicator_id / indicator_name_cn / metric_family
output_shape=scalar|ranking / unit / entity_grain / scope_dimensions[]
formula_version / numerator_definition / denominator_definition / required_fields[]
legacy_canonical_indicator_id / legacy_relation / directionality
min_sample_available / min_sample_stable / comparison_rule / calibration_rule_id
scope_fallback_allowed / availability_status / unavailable_reasons[]
registry_version
```

registry payload 不含自身 SHA 或 snapshot ID，避免自引用。每行 object key 使用
`canonical_json_v1`，rows 按 `reddit_indicator_id` 升序，以 UTF-8 JSONL 输出且每行（含最后一行）
以 LF 结束；`registry_sha256=sha256(exact_payload_bytes)` 只写入外层 manifest。manifest 绑定
payload bytes/SHA、row count、builder/validator code SHA 和 `snapshot_id`，但 manifest 自身不进入
payload SHA。duplicate indicator ID、未知字段、非 canonical row order 或 payload hash 漂移均 fail closed。
`snapshot_id` 固定为 `reddit_voc_indicator_registry_v1_{registry_sha256前12位}`，不得使用
wall-clock 或目录扫描结果生成身份。

V1 固定指标集合：

| ID | 公式/输出 | legacy relation |
|---|---|---|
| `RV-DH-01` | 已关联根帖 distinct comments / 全部 distinct comments | 新增数据健康 |
| `RV-DH-02` | text-ready VOC / identity canonical entity，帖子评论分开 | 新增数据健康 |
| `RV-DH-03` | 至少 1 个 promoted tag 的 text-ready VOC / text-ready VOC | `adapted_from SYS-COVERAGE` |
| `RV-DH-04` | 有 governed SPU 的 product-relevant VOC / product-relevant VOC | `reference_only PD-3` |
| `RV-DH-05` | 所有 promoted facts 证据完整的 tagged VOC / tagged VOC | 新增数据健康 |
| `RV-BR-01` | side-bound distinct eligible brand VOC count | 新增 |
| `RV-BR-02` | negative distinct eligible VOC / sentiment-classified eligible VOC | `adapted_from SYS-NEG-RATE` |
| `RV-BR-03` | `(positive-negative) / sentiment-classified eligible VOC` | `reference_only SAT-*` |
| `RV-BR-04` | promoted recommendation-expression VOC / brand-eligible VOC；v1 allowlist 仅 `L0-GEN-103` | `adapted_from CL-1`，不是 NPS |
| `RV-BR-05` | Momcozy net sentiment balance - competitor-union balance | `adapted_from BM-4` |
| `RV-PS-01` | scoped SPU/category eligible VOC / 同父级 routed eligible VOC | 新增 |
| `RV-PS-02` | scoped issue/negative eligible VOC / scoped eligible VOC | `adapted_from PD-3` |
| `RV-PS-03` | issue ranking：count desc、rate desc、tag_id asc | `reference_only PD-3` |
| `RV-PS-04` | Momcozy issue rate - competitor-union issue rate，同 SPU/category | `adapted_from PD-8` |
| `RV-IN-01` | 对 scope 内每个 eligible VOC 取 promoted negative tag 的最高 priority weight，无命中取 0；再做 `100 × sum(weight)/distinct eligible VOC`；P0=1、P1=.7、P2=.3 | `adapted_from PD-2` |
| `RV-IN-02` | `lift(A,B)=nAB×N/(nA×nB)` | 新增 |
| `RV-IN-03` | cohort tag rate - comparable overall tag rate，单位 pp | 新增 |
| `RV-IN-04` | tagged-thread mean complete comments / all eligible-thread mean complete comments | 新增 |
| `RV-IN-05` | `Δ²log1p(eligible volume)`，要求连续完整周期 | `adapted_from PD-4` |

共同可用性门禁：普通比例 `n>=30` available、`10<=n<30` provisional、`n<10`
unavailable；竞品差距两侧均 `n>=30`；lift 要求 `N>=100` 且 `nA,nB,nAB>=10`；
persona difference 的群组与对照均 `n>=30`；thread amplification 两侧均至少 30 个
distinct threads。单条安全/P0 证据可进风险明细，不能冒充稳定聚合结论。unavailable
固定输出 `value=null`，前端显示 `—`，不得写 0。

`RV-IN-01` 的分母固定为相同周期、scope、`voc_type` 下的全部 distinct eligible VOC；
每个 VOC 最多贡献一次。只有字典 sentiment 为 negative、decision 为 promoted 且 priority
在 `P0|P1|P2` 闭集内的 tag 参与 max；无合格负向 tag 的 VOC 权重为 0，不从分母删除。
未知 priority 的 tag held，不得偷偷按 P2 处理。该指标因此同时反映负向问题覆盖与最高严重度，
不等于“仅负向样本内部的平均严重度”。

### 11.6 阈值标定合同

旧 `indicator_storyline_matrix.csv` 的固定数值只作历史参考，不继承。标定必须冻结
`registry_sha + snapshot_sha + eligibility_filter_sha + period_series_sha`；当前周期不进入自身
标定样本。只使用 entity grain、scope、source strata set 与 coverage contract 都一致的
完整历史周期。

最小历史周期为 daily 56、weekly 26、monthly 24。历史不足时指标值仍可显示，但
`threshold_status=insufficient_history`，不生成异常/恶化结论；这不妨碍在两个可比窗口上
单独计算 MoM/YoY。

全部计算使用 Decimal，`ROUND_HALF_UP` 到 6 位。每个历史 series row 固定包含
`indicator_id,period_id,period_start,period_end,scope,voc_type,value_decimal_6,
source_selection_profile_hash,coverage_profile_hash,eligibility_filter_sha`；scope 使用
`canonical_json_v1`。只收录完整且合格的非 null period，按 `period_start,period_id` 升序，
重复 period fail closed；每行 canonical JSONL + LF，得到 `input_series_sha256`。

median 对奇数样本取中位元素，对偶数样本取两个中间 Decimal 的算术平均并 half-up 到 6 位。
quantile 固定为 nearest-rank：

```text
Q(p) = sorted_values[ceil(p*n)-1]

higher_is_worse: P1=Q90, P0=Q95
lower_is_worse:  P1=Q10, P0=Q05
two_sided:       center=上述 median；对 abs(value-center) 使用 Q90/Q95
```

等于阈值即命中，先判 P0 再判 P1。P1/P0 阈值相同或分布退化时为
`degenerate_distribution`，不自动报警。scope fallback 只有 registry 明确允许时才按
`SPU -> voc_category -> product_line -> total` 执行并记录；竞品差距与 persona difference
禁止 fallback。比例变化用 pp，数量基期大于 0 时用百分比；基期为 0 只给绝对差值。

标定输出必须绑定：

```text
calibration_id / calibration_level / history_period_count
center_median / directionality / quantile_method=nearest_rank
threshold_p1 / threshold_p0 / threshold_status
input_series_sha256 / algorithm_version=reddit_voc_calibration_nearest_rank_v1
```

`calibration_id` 固定为：

```text
sha256(utf8(registry_sha256 + "\x1f" + indicator_id + "\x1f" +
            canonical_json_v1(scope) + "\x1f" + voc_type + "\x1f" +
            input_series_sha256 + "\x1f" + algorithm_version))
```

two-sided 当前值按 `abs(current-center_median)` 与 deviation threshold 比较；higher/lower
指标直接比较当前值。calibration payload 同样按 `indicator_id,scope,voc_type` 排序并用
canonical JSONL + LF；manifest 才保存 payload SHA，不在 payload 内自哈希。

### 11.7 洞察与报告故事线

复用 `ai_nlp_voc` 的六段式方法，但所有阈值用融合后 Reddit 数据重新标定：

1. Signal：发生了什么、当前值、基线、覆盖与置信；
2. Root Cause：Top 标签、方面情感、品类/SPU、画像和帖评证据；
3. Counter-intuitive：与整体或竞品走势相反的结构变化；
4. Impact：影响的内容实体、线程、产品范围和业务风险；
5. Action：动作、owner、优先级、时间范围和目标指标；
6. Monitoring：复盘指标、频率、阈值和下次日期。

日报优先新问题和异常线程；周报优先 WoW、4/12 周轨迹、Momcozy 对竞品和品类/SPU/画像差异；
月报优先 MoM、有可比基期时的 YoY、结构变化和长期机会。任何不完整窗口、口径不一致、
负向筛选源或样本不足都显示 `—` 并通过 `?` 说明。

## 12. 数据与代码改动边界

预期实现区域：

- `ref/UI/momcozy-reddit-workbench/src/components/reports/RealReportView.tsx`
- `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotReports.tsx`
- `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
- `ref/UI/momcozy-reddit-workbench/src/components/BrandScoreCard.tsx`
- `ref/UI/momcozy-reddit-workbench/src/services/caseService.ts`
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/personas.ts`
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/brandSituation.ts`
- `src/reddit_voc/risk_report_contracts.py` 或等价的版本化 brand-index analytics 构建器
- `scripts/import_reddit_add_data_workbooks.py` 及独立 validator
- source-selection registry / metric-eligibility builder 与独立 validator
- `scripts/build_reddit_site_snapshot.py` / `scripts/validate_reddit_site_snapshot.py`
- `scripts/build_public_site_projection.py` / `scripts/validate_public_site_projection.py`
- `scripts/build_reddit_reports_snapshot.py` 及报告时间精度 validator
- `scripts/build_reddit_personas_snapshot.py`
- provider-free `persona_atomic_match_v1`、`persona_cohort_bridge_v1` builder/validator
- `reddit_voc_indicator_registry_v1` alias bridge、metric builder 与 calibration validator
- 案例 verified-seed ledger builder/validator
- 从 `ai_nlp_voc` 绑定 SHA 复制的 persona/indicator/storyline reference，以及派生的
  `reddit_voc_indicator_registry_v1`
- 与上述合同直接相关的 tests、config、versioned public data 和静态资产。

不因本次任务顺手重构其他页面或替换现有设计系统。

## 13. 验收标准

### 13.1 Unit / contract

- 24 小时桶标签为 `00:00` 至 `23:00`；14 日趋势标签为不同日期。
- 周/月跨年标签无歧义，且不受浏览器本地时区影响。
- 页面不存在 `当前闭合期 / 闭合归档` 主切换。
- 六份 current/archive 报告仍通过 SHA 和 schema 校验。
- 同环比值与 current/baseline 精确对账；missing baseline 显示 `—`。
- baseline=0 时数量相对变化为 `—`；share 可显示 pp。
- sparkline 颜色、数据不足灰态和 tooltip 文案通过测试。
- `add_data` 行数 13,534、distinct 2,226/11,305、Base 重合 54/738、净新增
  2,172/10,567 逐层对账通过；3 条重复评论不产生新实体。
- `舆情ID` 不作为 canonical ID；`标题` 按 entity type 映射 body；工作表错误 `A1`
  dimension 不得截断行。
- 日精度记录不进 24 小时桶，但与当日总量的“时间未提供”守恒。
- 帖子 VOC 和 `父帖 + 1 条评论` VOC 分别唯一；父帖独有标签不复制放大到每条评论。
- root post 的 link/permalink/t3-parent 候选不一致时 fail closed；analysis input 使用字段化
  canonical JSON，Unicode table、空白 code points、字段顺序和 payload SHA 均可独立复算。
- 814 行 negative-selected 来源的 biased-only 实体对经营指标全部 excluded；12,720 行来源
  在 selection manifest 缺失时保持 `pending_source_manifest`，两者仍可进入身份/证据/打标层。
- source decision table 的全部 class/evidence/manifest 分支由 validator 重算；`owner_declared`
  不能开启业务分母，registry invalid 不能降级 pending，partial coverage 最多 provisional。
- 54/738 Base overlap 只生成一个 canonical entity；只有合格 Base lineage 可作 metric anchor，
  workbook 只补 provenance，不重复计数，也不能给 biased-only entity 洗白。
- 每个指标满足 `numerator_ids ⊆ denominator_ids ⊆ eligible_entity_ids`；独立 validator
  从 lineage 重算资格。篡改来源资格、把 biased-only entity 塞入分母或强行跨 profile 比较均 fail closed。
- 当前期/基期的 source/query/coverage profile 不一致时 comparison 为 unavailable；
  biased-only 窗口即使数学上是 100% 负向也显示 `—`。
- 品牌指数融合后由 analytics 重算并与前端精确一致；不硬编码 68/70；
  任一维度缺失时总分为 `—`，且不重权。
- 禁止词测试：市场份额、NPS、行业基准、健康等级不得出现在指数合同中。
- 案例默认结果不含 pending/rejected；seed/delta 去重守恒。
- v6.3 字典 SHA 、2,346 tag 闭集、8,854 映射、orphan=0 和 Reddit 可用指标注册表通过。
- persona v2 的 82 原子画像、8 复合群组、scope 拆分、assignment/unique entity 守恒、
  held-tag 排除和头像边界通过。
- persona matcher 的 token boundary 通过：`happy` 不命中 `app`、`previous` 不因子串命中
  `vs`；父帖写 “I am pregnant” 而评论只写 “which size?” 时，评论不得获得 `PER-WHO-003`。
- 父帖有 N 条评论时，其 persona facts 不复制成 N 个评论 facts；TECH 互斥、共享关键词 held、
  template alias 和 evidence span/hash 均通过。输入顺序打乱后 facts/assignments 字节一致。
- persona tokenizer、segment、longest-span-first、重复 keyword、混合 A/B、第二/第三证据加分和
  evidence arrays 排序均有固定 fixture；第四个证据不得继续加分，B-only 不得晋级。
- 显式 alias `BM-1_NPS -> BM-1`；未知 `PD-11_X` held；`BM-1` 不得 alias 成 `RV-BR-04`。
  registry alias collision、required fields、entity grain、样本门禁和 unavailable null 均通过。
- 月历史少于 24 个完整可比周期时 threshold 为 unavailable；标定不含当前周期，nearest-rank、
  Decimal rounding、scope fallback 和退化分布门禁通过，输入重排后 calibration 字节一致。
- registry payload 不得自哈希；canonical JSONL、末行 LF、manifest SHA 边界通过。
  calibration input series、奇偶 median、two-sided center、calibration ID 和输出排序均可独立复算。

### 13.2 Frontend quality

- TypeScript、lint、unit tests、production build 全部通过。
- 正常页面不再使用感叹号表达 partial/provisional 状态；实际 failure 仍 fail closed。
- 桌面与移动端无横向滚动、文字裁切或不可达 tooltip。
- banner、指数、报告卡、案例和画像均符合当前 Momcozy 视觉调性。

### 13.3 E2E

- 13 条既有路由不回归。
- 日/周/月报告切换、时间轴、同环比、`?` 和 sparkline 可用。
- 概览 banner、与当前 analytics 合同一致的总分、四维雷达和研判基础可见。
- 帖子和评论上下文 VOC 可分开查看；未补父帖在账本中显示为“暂未匹配到所属帖子”，
  不进入完整评论 VOC 结论。
- 案例默认搜索只出现质量门禁通过项，外链 target/rel 安全。
- 八复合画像卡、82 原子画像引用、头像 fallback、证据层切换和边界声明可用。
- 浏览器 error、same-origin 404 和意外外部请求均为 0。

## 14. 发布顺序

1. 冻结两份 workbook、v6.3 字典和可复用 reference 的 SHA/schema；
2. 构建并独立验证 `add_data` 私有标准化/去重/父帖账；
3. 构建 source-selection registry，物化 canonical lineage 与 source-frame 资格；
4. 只追加融合 Base，完成帖子 VOC 和评论上下文 VOC 守恒；
5. 重跑品牌、品类/SPU、情感、VOC 标签和 `persona_atomic_match_v1`；
6. 构建 per-metric eligibility、Reddit indicator registry、画像群组、阈值和故事线；
7. 重建日报/周报/月报、Insights、Personas 与 public projection，并独立对账；
8. 实现前端 UI 改动与定向测试；
9. 全量 frontend test/lint/type/build 与 Python contract/validator 回归；
10. desktop/mobile E2E；
11. isolated container smoke 与安全路径检查；
12. 生成新的 immutable release 与 promotion packet；
13. Owner 精确授权 release + packet 后，才执行 insights-site-only 受控提升；
14. 公网 TLS、路由、数据身份、报告、案例、画像和安全404验收；
15. 增量自动接入、candidate registry 和四导出完整验收继续作为后续独立批次，不混入本次完成声明。

## 15. 失败与回滚

- 指数输入失败：仅指数模块 fail closed，不回退旧假分。
- workbook 结构、行数、ID 或守恒失败：不融合任何 `add_data` 实体，保留上一 Base。
- 父帖未解析或文本不完整：仅该实体留在可重入账本，不阻断其他合格实体。
- 标签/指标注册表对不上：不发布新 Reports/Insights/Personas，不回退旧模拟洞察。
- persona v2 校验失败：画像模块 fail closed，不暴露未校验 assignments。
- case quality ledger 失败：回退到通过门禁的 seed 子集，不展示 legacy。
- 本地测试或候选 E2E 未通过：不生成 promotable packet。
- 生产候选未通过：不切 current。
- 切换后验收失败：只按既有 Reddit VOC 洞察站回滚机制处理，不修改共享基础设施。

## 16. 未完成债务

本设计不把以下事项标记完成：

- open coverage 1,179；
- pending lineage 18；
- `fully_hydrated=false`；
- candidate registry 深度治理；
- 四导出完整验收；
- 增量数据自动接入与调度；
- `add_data` 中 3,859 个暂未匹配根帖及对应 6,943 条评论上下文 VOC 待补链；
- 67 个帖子 source text、67 条评论正文和 42 个已关联评论的根帖 title/body 待补全；
- 12,720 行 workbook 的 source-selection manifest 待 Owner/来源系统补齐；在此之前其经营指标
  资格 fail closed。814 行 negative-selected 来源保持 evidence-only，不作为后续自动解锁债务；
- v6.3 本地 2,346、batch 2,381、production 3,146 之间的跨系统字典 mapping contract；
- Apple Podcasts canonical link 复核；
- 画像 lexical/held 标签的额外人工抽样门禁。
