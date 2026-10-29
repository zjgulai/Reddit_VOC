# ADR-002: 数据时效对齐——指针诚实化回拨（方案A）与派生数据集每日重算引擎（方案B）

- **状态**: Accepted（方案A 已执行；方案B 交付中）
- **日期**: 2026-10-27
- **决策人**: Echo-Agent 核心研发团队
- **关联**: ADR-001（多 Agent 架构）、每日 T-1 流水线（echo-agent-daily.timer）

---

## 1. 背景与问题陈述

ADR-001 落地的每日流水线实现了 base 快照增量合并与 freshness 指针前移。但深度审计（2026-10-27）发现：

| 数据集 | 页面消费方 | 实际时间边界 |
|---|---|---|
| quarter-insights.json（趋势 buckets/anchor） | 概览、洞察、优先行动 | ❌ 冻结于 2026-07-23 |
| reports dataset（日报 period_id/同环比） | 报告页 | ❌ daily:2026-07-23 |
| brand_health 投影 | 概览健康度雷达 | ❌ source: center_20260723 |
| personas dataset | 画像 | ❌ generated 07-23 |
| aggregates-public.json（分析页 date_range） | 分析 | ❌ 止于 07-22 |
| posts-public.json（base 快照） | 搜索/明细 | ✅ 已随流水线到 10-27 |

而 `current-release.json.freshness.data_as_of_utc` 已前移至 10-26 —— **指针与 8/9 个数据集内容脱节**，全站除搜索页外均在消费 7 月冻结投影，且封面声称 T-1，构成时效性自相矛盾。

### 根因
1. 流水线只覆盖 base 增量合并与指针前移，未重算派生数据集（设计疏漏）；
2. 派生数据集在原架构中是**离线批处理产物**（V2 center → V3 指标 → 投影），无法增量追加，必须全量重算；
3. 原治理准则禁止用不完整语料重算派生指标，采集断供后投影被冻结；前移指针导致"封面新刊、内页旧文"。

## 2. 决策

### 方案 A（立即执行）：指针诚实化回拨
`freshness.data_as_of_utc / window_* / collector_run_id` 回拨至派生数据集的真实边界（2026-07-23 07:00 CST），`status` 保持 `partial` 并如实标注。前端顶部状态条恢复"数据截止 2026-07-23"的真实呈现，消除自相矛盾。搜索页仍展示流水线合并的新帖（其在 base 快照内，合法）。

### 方案 B（主交付）：派生数据集每日重算引擎
在每日流水线 Step 3 与 Step 4 之间新增 **Step 3.5 recompute_derivatives**，用纯 Python 从 SQLite 全量重算，schema 与 7 月版逐字段兼容（前端零改动）：

| 顺序 | 产物 | 重算逻辑 |
|---|---|---|
| 3.5.1 | aggregates-public.json | 全量 posts/comments 重算 date_range / headline 计数 / 情感与痛点分布 |
| 3.5.2 | quarter-insights.json | anchor=昨日；重算 dashboard_windows 三窗口 daily buckets（post_vocs/comment_context_vocs/negative_rate）与 themes |
| 3.5.3 | reports current/daily.json | 当日指标 + 6 期 sparkline 历史滚动；period_id=daily:{T-1}:{T}；同环比基于真实历史桶 |
| 3.5.4 | brand_health 投影 | 四维评分（口碑/体验/信任/韧性）按 7 月版权重公式重算，并更新 source_snapshot_id |
| 3.5.5 | personas | 暂缓重算；manifest 标注 frozen_as_of，页面继承全局新鲜度条 |

所有重算完成后统一重写各 manifest 内部 sha256，并同步 current-release.json 各绑定（复用 ADR 修复中的 binding_updated 机制），最后才前移 freshness 指针——**保证"先内容后指针"的原子顺序**。

### 口径冻结
重算指标沿用 7 月版权重与口径（VOC=治理品牌事实确认的 post_voc+comment_context_voc；负面率分母=已分类 VOC；健康度四维权重不变），保证跨期可比。口径变更必须走新的 ADR。

## 3. 后果

- **正向**：全站时效自洽 → 真滚动 T-1；指标跨期可比；每日 08:00 前全自动。
- **风险与缓解**：重算口径漂移 → 口径冻结 + 与 7 月版逐字段回归比对；全量重算耗时（~20k 评论）→ SQLite 索引 + 单进程 < 5 分钟；personas 冻结期展示 → 明确标注，不做假更新。

## 4. 执行状态

- 方案 A：**已执行**（指针回拨至 2026-07-23T23:00Z 边界，页面状态条与内容一致）。
- 方案 B：**已交付**（2026-10-27）。B1 引擎 → B2 回归 → B3 并入流水线 → B4 线上验收，四步全部完成。

## 5. 方案 B 交付细则（2026-10-27）

### 5.1 引擎实现 `scripts/recompute_derivatives.py`

| 函数 | 产物 | 关键口径 |
|---|---|---|
| `recompute_aggregates()` | base 数据集 `aggregates-public.json` | 全量 posts/comments 的 date_range 与 headline 计数 |
| `recompute_quarter_insights()` | `quarter-insights.json` | anchor=T-1；三窗口 **连续零填充** buckets；themes 基于季度 VOC 集 |
| `recompute_reports_daily()` | `reports/current/daily.json` | `period_id=daily:{T-1}:{T}`；sparkline 6 历史日 + 当日 |
| `recompute_brand_health()` | `brand-health.json` + `manifest.json` | 四维评分 + 等权总分，manifest 与 data 血缘自洽 |

### 5.2 冻结的三条口径补丁

1. **anchor = T-1（最后一整日），不是当日。** 07:00 日切意味着 T 日运行发布的是 T-1 数据；用当日做 anchor 会让趋势图最后一根柱子是"半天"，"T-1 滚动"就成了假话。`_t1_anchor()` 单独存在，便于测试固定锚点。
2. **buckets 连续零填充。** 7 月基线是 7/30/7 个连续桶；稀疏桶（只保留有数据的日期）会让趋势图退化成单点。`_zero_fill()` 按日/月粒度补齐，183 天窗口为 7 个月桶（`0..days//30` 含锚点月）。
3. **period 语义对齐 7 月。** `period.start = anchor`、`period.end = anchor + 1 天`，即 `daily:2026-10-26:2026-10-27` 对应"10-26 07:00 → 10-27 07:00"这个已闭合业务日，`is_complete: true` 才成立。

### 5.3 品牌健康 v2 定义（替代不可复现的 V1）

7 月版由仓外 V2 center 的 `entity_brand_fact` 促销引擎生成，仓内无法复现，故冻结如下 v2 定义（等权总分与 7 月一致：72.55 = mean(57.07, 99.94, 50.45, 82.76)）：

| 维度 | 公式 |
|---|---|
| 口碑健康 reputation | `100 × (正向 + 0.5×中性) / 已分类` |
| 产品体验 product_experience | `100 − 100 × (topic=troubleshooting 且 severity=high) / 已分类` |
| 推荐信任 recommendation_trust | `100 × 正向 / (正向 + 负向)` |
| 风险韧性 risk_resilience | `100 − 2 × 负向率` |

总分 = 四维算术平均。已分类样本 < 30 时整组降为 `unavailable`；分类覆盖率 < 90% 时标 `provisional` 并附原因码 `comment_context_voc:classification_coverage_below_90_percent`。

### 5.4 顺带修掉的两个数据缺陷

- **评论从未合并进快照。** `merge_snapshot` 取了 `fetch_comments_for_run()` 却没用，导致 `comment_context_voc`（VOC 总量的 80%）永远停在 7 月。现已按与帖子相同的规则打标合并。
- **评论时间戳继承父帖。** `apify_collector` 给每条评论写的是帖子的 `createdAt`，全部回复被记到开帖当天，日桶失真。现改为读评论自身 `createdAt`。

### 5.5 验收证据（radar.luteos.com，2026-10-27 18:45 UTC+8）

- 7/7 数据集 manifest SHA-256 与 `current-release.json` 绑定一致（原先全站报"manifest SHA-256 不一致"的问题消失）。
- `data_as_of_utc=2026-10-26T23:00:00Z`（北京 10-27 07:00）→ 期望 T-1 = 2026-10-26。
- quarter-insights anchor = 2026-10-26；7/30/7 桶分别落在 `10-20..10-26`、`09-27..10-26`、`04..10`。
- reports `period_id = daily:2026-10-26:2026-10-27`。
- brand health overall = 74.46，`source_snapshot_id = echo_agent_base_snapshot_2026-10-26`。
- 流水线回执：collect → agents → merge_snapshot → recompute_derivatives → advance_pointer → feishu_push，`errors: []`。

### 5.6 契约适配层（本轮补做的关键工作）

第一次真正打开浏览器验收时发现：**引擎算对了数，但快照不符合前端的冻结契约**，10 个页面里 6 个报错。逐层修复如下，每一层都是"页面能渲染"的必要条件：

| 层 | 症状 | 根因 | 修复 |
|---|---|---|---|
| manifest ↔ binding | 发布 manifest SHA-256 不一致 | 流水线改写 manifest 后未同步绑定；浏览器 `force-cache` 又长期钉住旧副本 | 绑定随写随同步；前端 6 处 `fetch` 由 `force-cache` 改为 `no-cache`（Nginx 配置未动，避免影响同机其他应用） |
| base manifest 计数 | 真实数据文件 bytes 不一致 | 只更新了 `sha256`，没更新 `bytes`；`canonical_counts` / `projection_counts` 未随语料增长 | 新增 `refresh_base_manifest()`：按实际数组重算 bytes/sha/计数，并保持 `comments_jsonl = linked + unresolved`、`stored = jsonl + quarantined` 等守恒式 |
| time_precision | 时间精度计数不守恒／聚合与 manifest 不一致 | 两侧各算一遍，键序与口径漂移 | 统一到 `compute_time_precision()` 单一实现，聚合与 manifest 用同一份输出 |
| 记录级 v3 schema | 帖子结构覆盖等级不受支持 | 增量合并写入的记录缺 `schema_version` / `event_time_precision` / `structural_coverage_grade` / `tagging` 等字段 | 新增 `scripts/merge_normalize.py`，以已通过校验的记录为模板重塑全部 pipeline 合并记录，并对全量语料统一覆盖等级枚举（full/partial/post_only/source_observed） |
| quarter-insights 结构 | boundaries 字段合同不一致、personas/source 缺失、rankings 形状不符 | B1 只求"数值对"，未实现冻结 schema | 重写 `recompute_quarter_insights()`：18 键 boundaries、16 键 source（全部绑定真实产物哈希）、三窗口、四主题（rankings/evidence/method）、personas 八字段与 8 个 cohort、case_references；并由 `run_recompute` 同步生成 `manifest.json` |
| aggregates 附加字段 | 分析页崩溃（`.slice` / `.toLocaleString` 对 undefined） | 缺 `tagging.top_tags`、`headline.comments_with_rule_tags_in_voc_metrics`、`brand_sample_mentions` 为 `{}` 而非数组 | 补全三处，`top_tags` 由标签字典解析中英文名与 theme |

> 这一层的教训：ADR 里写的"schema 逐字段兼容（前端零改动）"必须用**浏览器真实渲染**来验收，单测和 curl 都发现不了。

### 5.7 已知残留

- **近 7 日 VOC 量偏低**（rolling_7_days total=2）。这是采集覆盖问题，不是口径问题：Apify 每日只拉 5 个 subreddit × 2 个搜索词 × 25 条，且绝大多数命中帖并不点名 Momcozy，经品牌治理后落入 `brand_unbound`。要提升需扩大采集面（关键词、subreddit、时间回溯），属于数据层扩容，另立议题。
- **personas 冻结且无法诚实重算**。其 manifest 绑定 `governed_signal_snapshot_id`（`reddit_voc_governed_signals_20260723_daily_v1`）、`governed_signal_source_snapshot_id`（V2 center canonical）、以及 automation classification / persona dictionary / reference manifest 等上游产物，这些引擎都不在本仓库内。强行重算只能伪造血缘哈希，因此选择不重算，改为在洞察页显式标注：「画像分组快照生成于 2026-07-23，早于当前统计季度起点 …；分组卡片来自该快照，上方计数为当前季度实时值。」——计数来自实时的 quarter-insights，卡片来自冻结快照，两者边界写在页面上了。

## 7. 采集面扩容与滚动窗口修复（2026-10-27）

### 7.1 `maxItems` 是全局预算，不是单查询上限

Apify actor 的 `maxItems` 对**整次 run** 生效。原配置 `maxItems=25` 意味着全天只采 25 条（帖+评合计），这正是「近 7 日 VOC 只有个位数」的真正原因——不是口径问题，是采集预算问题。

实测（12 个品牌/品类查询词）：`maxItems=60` → 60 条/16 帖；`maxItems=400` → 265 条/49 帖（10 分钟仍在跑，取部分数据集）。品牌与品类查询在共享预算下比 `r/<sub>` 查询产出更高，因此 subreddit 查询已移除。

现配置：12 个查询词（Momcozy / M5 / M9 / S12 / Elvie / Willow / Spectra / Medela / wearable breast pump / pumping at work / flange size / milk supply）、`maxItems=400`、`maxComments=20`、actor 等待上限 900s。

**效果**：单日入库从 2–7 帖 / 19 条评论提升到 **32 帖 / 149 条评论**；rolling_7_days VOC 从 2 → **25**，rolling_30_days 从 10 → **47**。

### 7.2 滚动窗口被季度切片截断（已修）

重写 `recompute_quarter_insights` 时，三个滚动窗口的 `in_window` 都从 90 天季度池 `in_quarter` 里过滤，导致 `rolling_183_days` 实际等于 `rolling_30_days`（两者都被截断到 90 天内）。已改为各自从全量治理池 `vocs` 扫描，并新增回归测试 `test_wider_windows_are_supersets`：宽窗口的 VOC 数必须 ≥ 窄窗口，且月桶合计必须等于窗口合计。

修复后 rolling_183_days 从错误的 47 恢复为 **626**（213 帖 + 413 评论）。

### 7.3 归一化层不得覆盖既有治理字段

`merge_normalize.normalize_all` 曾用父帖绑定覆盖评论自身的 `brand_binding`，会把 7 月语料里已治理的 `comment_context_voc` 全部降级为 `brand_unbound`。现规则：**只给 pipeline 自己新建、且没有受控绑定的记录补绑定，已有绑定一律保留**。同时保留既有的 `include_in_voc_metrics` 与 `metric_eligibility_status`。

## 6. 报告数据集整束重建（2026-10-27）

### 6.1 为什么不能只写 daily.json

报告页消费的不是单个文件，而是九个互相绑定的产物：`current/{daily,weekly,monthly}.json`、`archive/{daily,weekly,monthly}.json`、`report-index.json`、`business-history-index.json`、`validation-receipt.json`、`manifest.json`。前端逐项交叉校验：报告角色 ↔ manifest 的 `comparison_contract_proven`、`period` ↔ index、`source` ↔ receipt ↔ index、文件 `bytes`/`sha256` ↔ manifest、`manifest.lineage_manifest_sha256` ↔ release 绑定。任何一处单独更新都会让整束失衡。

### 6.2 采用"未获覆盖证明"版本

我们没有数据所有者签署的 100% 覆盖声明，因此发布 `comparison_contract_proven = false` 的诚实版本：

- 角色 `latest_closed_calendar_period_unattested`，标签「最新闭合周期（覆盖未证明）」
- `completeness_percent = null`、`coverage_attestation = null`、绑定 SHA `null`
- 所有同环比一律 `provisional` + `owner_attestation_missing_observed_same_profile`，趋势图 `trend_claim_supported = false`
- 该分支强制 `history_report_count = 0`——既然证明不了历史周期，就不发布历史入口

### 6.3 指标口径

26 个指标 ID 全部保留。当前引擎能真算的 4 个（RV-BR-01 观察量、RV-BR-02 负向率、RV-BR-04 推荐表达率、RV-BR-05 竞品语境占比）给出当期值与观测环比（6 期 sparkline）；其余标记 `unavailable` + `metric_not_recomputed_by_current_engine`，不编造数值。品牌健康四维按 §5.3 公式写入 `brand_health.rows` 与 8 条 `dimension_rows`（4 维 × 2 口径，权重 25.00，贡献分 = 维度分/4）。

### 6.4 实现与验收

- `scripts/recompute_reports_bundle.py`：以最后一个合法版本为结构模板，只替换动态数字，因此冻结 schema 不会漂移；`lineage_manifest_sha256` 用"先置零再回填"的不动点方式计算。
- `scripts/build_reports_bundle.py`：从公开根装配输入并输出到独立目录，可在替换线上数据前先校验。
- 回归门禁：`src/features/redditSnapshot/__tests__/generatedReportsBundle.test.ts` 用真实 loader + 全部 v3 校验器跑生成物（设 `ECHO_REPORTS_BUNDLE_DIR` 时启用，CI 无该变量则跳过）。
- `run_recompute` 内的顺序固定为：aggregates → base manifest → quarter-insights → brand health → reports bundle → 各绑定 SHA/lineage 同步。
- 线上实测：日报 `daily:2026-10-26:2026-10-27`、周报 `weekly:2026-10-19:2026-10-26`、月报 `monthly:2026-09-01:2026-10-01`，三档均无契约报错。

### 6.5 遗留

- 磁盘上仍保留 7 月遗留的 `history/*.json`（39 个文件）。新 manifest 不引用它们，客户端不会加载；保留是为了可回溯，不做删除。
- 同环比目前全部是观测级 `provisional`。要升级为正式结论，需要一份真实的数据所有者覆盖声明，属于业务侧输入。
- **reports 数据集已改为整束重建（2026-10-27 完成）。** 见 §6。
