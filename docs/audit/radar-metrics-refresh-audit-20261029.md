# radar.luteos.com 全站指标与结论自动刷新审计报告

- 审计时间：2026-10-29（CST）
- 审计范围：9 个页面/模块 × 指标口径 / 数据链路 / 刷新能力
- 方法：6 路并行页面审计 + 6 轮对抗验证（248 项检查，16 项原判定被推翻并修正）
- 结论基线：base 语料 25,873 帖 / 100,778 关联评论（本日回补 21 天后），`data_as_of_utc=2026-10-28T23:00:00Z`

---

## 一、执行摘要

**核心结论：数字大部分活了，结论大部分没活；四个数据集完全不在自动化链路上。**

| 页面 | 数字刷新 | 结论刷新 | 综合判定 |
|---|---|---|---|
| 概览 `/dashboard` | ✅ 全部跟随最新语料 | ⚠️ 数字部分跟随，定性判断硬编码 | `partial_auto` |
| 报告 `/dashboard/reports` | ✅ T-1 重算 | ⚠️ 模板句 + 3 处计算 bug | `partial_auto` |
| 洞察 `/dashboard/insights` | ✅ 读 quarter_insights（非 insights 数据集） | ❌ 用户画像恒 0.00% | `partial_auto` |
| 分析 `/dashboard/analytics` | ✅ 读 aggregates + posts | ⚠️ 与品牌健康口径冲突 | `partial_auto` |
| 搜索 `/dashboard/search` | ✅ 直读 posts-public | ⚠️ 标签 facet 用冻结字典 | `partial_auto` |
| 案例广场 `/cases` | ❌ 冻结在 2026-07-16 | ❌ 静态策展 | `static` |
| 高价值内容 `/ugc-showcase` | ✅ 实时帖子重排 | ✅ | `auto` |
| 舆情信号 `/messages` | ✅ 由 quarter_insights 派生 | ✅ | `auto` |
| Agent 工作室 `/agent-studio` | ✅ 计数实时 | ⚠️「每日 07:05」文案与事实脱节 | `partial_auto` |

### 品牌健康度指数：确已刷新

| 指标 | 回补前（17,542/58,587 语料） | 当前（25,873/100,778 语料） |
|---|---|---|
| 总分 | 74.20 | **75.42** |
| 口碑健康 | 58.77 | **58.96** |
| 产品体验 | 95.39 | **96.03** |
| 推荐信任 | 69.68 | **71.14** |
| 风险韧性 | 72.96 | **75.53** |
| 样本说明 | — | 2,280 条（前端估算，非投影样本） |

用 live 语料按 `recompute_brand_health` 公式完整复算，精确复现 58.96/96.03/71.14/75.53→75.42，证明分数确实来自最新数据源。所有 7 个数据集 binding SHA 与 `/dashboard` 渲染值一致。

---

## 二、数据集刷新能力矩阵（权威版）

| 数据集 | 生产者 | 是否自动 | 当前时效 |
|---|---|---|---|
| `base`（posts/comments/manifest/aggregates） | `step3_merge_snapshot` + `step3.5` | ✅ | 10-29 19:30 |
| `quarter_insights` | `step3.5 recompute_quarter_insights` | ✅ | 10-29 11:30 UTC |
| `brand_health` | `step3.5 recompute_brand_health` | ✅ | 10-29 19:30 |
| `reports` bundle | `step3.5 build_reports_bundle` | ✅ | 10-29 11:30 UTC |
| `agent-studio/latest-*.json` | `step2_agents` | ✅ | 10-29 19:09 |
| `current-release.json` | `step4_advance_pointer` | ✅ | 10-29 11:30 UTC |
| **`personas`** | `build_reddit_personas_snapshot.py`（手工） | ❌ | 10-28，语料 17,469/58,296 |
| **`insights`** | `mb_build_attested_reports_insights.py`（手工 + 前端 allowlist 改写） | ❌ | 10-28，语料 17,469/58,296 |
| **`casebook`** | `build_reddit_casebook_snapshot.py`（手工） | ❌ | **2026-07-16** |
| **`tag-dictionary-public.json`** | `build_public_tag_dictionary.py`（手工） | ❌ | `dim_tag_v6.3_final` |

`run_daily_t1_pipeline.py` 的 steps 仅六步：`collect → agents → merge_snapshot → recompute_derivatives → advance_pointer → feishu_push`。服务器仅有 `echo-agent-daily.timer`（07:05）与两个 legacy cron，无 personas/insights/casebook 构建入口。

---

## 三、六大系统性缺陷（按业务影响排序）

### P0-1 自动刷新当日断裂：07:05 定时跑批失败，靠人工救回

- `echo-agent-daily.service` 于 07:17:38 因 `PermissionError: /opt/voc-report/html/data/reddit-voc/lineage/product-entity-ledger.json` 失败
- `advance_pointer` 被 `POINTER_PREREQUISITES` 正确阻断（守卫生效，这是好事）
- 但 base 内容在 merge 阶段已改写：07:17–19:30 期间站点呈现「新 base 上下文 + 旧报告指标」的混合态
- 当前 success 版本来自 19:01 的手工重跑（`collector_run_id` 仍被合成成 `daily_collect_20261029_0700`，无法区分）
- `_preflight_writability` 只对目录做 `os.access(W_OK)`，检测不到「root 留下的 700 文件」

**这不是偶发**：同一 root 属主问题今日已出现两次（lineage 文件、`data/raw` 目录阻断回补）。

### P0-2 用户画像恒为 0.00%：ID 空间不匹配（结构性 bug）

```
每日重算生成的 assignment_id = sha256(f"{kind}:{post_id}:{comment_id}:{topic}")   # recompute_derivatives.py:582-585
persona 快照的 assignment_id  = canonical JSON 身份                             # v3_persona_inference.py:1694-1708
实测交集 = 0
```

洞察页「8 类用户画像 · 真实帖子与评论证据」全部显示 `0.00% · 0 条`，仍标「合计 100.00%」。这是前端拿两套 ID 求交集的结果，**只重建 personas 不能修复**。

### P0-3 品类机会把 topic 当 SPU：指标对象错误

`recompute_derivatives.py:498-552` 用 `analysis.topic`（`troubleshooting` / `product_evaluation`）生成 `product_rankings` / `exact_spu_rankings` / `family_rankings`，页面却标「产品家族」「已批准精确 SPU 证据」，两栏都显示 `问题排查 187 / 产品评价 77`。

页面自带文案「不把家族证据冒充精确 SPU」——与实际展示直接矛盾。同时污染新品机会结论「围绕『问题排查』等品类证据识别未满足需求」。

### P1-1 完整度分档漏计 61.4%

```
页面展示：完整 933 + 部分 1,094 + 仅帖子 7,955 = 9,982
实际总数：canonical_counts.posts = 25,873
缺口：source_observed 15,891（61.4%）被静默丢弃
```

同页「数据证据」弹窗却完整显示「来源观察 15,891」——同一页面两套口径。

### P1-2 月报环比基线跳月 + 六期趋势隔月

`recompute_reports_bundle.py:123-131` 的 `_previous_period` 对 monthly 用 `start-1day`（2026-08-31）再调 `compute_period`，返回 `2026-07-01:2026-08-01`：

- 月报环比基线实际是 **7 月**（应为 8 月）：观察量「-97.7%」实为 +23.5%
- 六期趋势隔月采样：2025-09/11、2026-01/03/05/07，页面仍标「同粒度完整周期」

### P1-3 结论文字是 TSX 模板，不是数据产品

| 硬编码结论 | 位置 |
|---|---|
| 「四维差异明显，需将优势与短板分开管理」 | `BrandHealthSnapshotCard.tsx:94` |
| 「从品类、产品族、SPU 与证据帖定位真实使用阻力」 | `SnapshotDashboard.tsx:145-166` |
| 「构成问题库」「不把家族证据冒充具体商品」 | `SnapshotDashboard.tsx:565-576` |
| 「机器人与自动化评论只作内容类型观察」 | 同上（但 `is_bot` 恒 False、`moderation_claims` 硬编码 `[]`） |

数字变了，判断句不变 —— 当排名翻转时会出现**自相矛盾的结论**（如「操作与可靠性位居首位，优先级高于适配舒适度」中的后半句是硬编码，排名翻转后仍然如此说）。

### P2 前端缓存永不失效

`service.ts:103-104,1481-1489` 的 `summaryPromise`/`corePromise`、`brandHealth.ts:114,267,298` 的 `brandHealthCache` 都是模块级单例。已打开的页面跨过 07:05 发布**不会自动重取**，必须手动刷新。

---

## 四、逐页审计明细

### 4.1 概览 `/dashboard`

**自动刷新（已确认）**：状态条 data_as_of、治理范围 25,873/100,778、核心经营指标（170 帖 VOC / 708 观察量 / 5.93% 负面 / eufy 530）、品牌健康 75.42+四维、三窗口趋势、关键驱动排名、竞品参照、证据帖链接

**缺口**：
- 完整度分档漏 source_observed 15,891
- 品类机会把 topic 当 SPU
- 品牌健康样本说明 2,280（前端 `isMomcozyPost` 估算）≠ 投影实际样本 1,136 帖 + 2,289 评论 = 3,425 VOCs
- 机器人评论 / 版务治理证据结构性恒 0（`is_bot` 恒 False；`moderation_claims` 硬编码 `[]`）
- `data_as_of=10-28T23:00Z` 但 aggregates 最新事件到 `10-29T11:04Z` — 当日盘中数据混入 T-1 口径
- 证据链接 `release=…20260723_daily_v2` 自 7 月未变，`releaseMismatch` 永不触发

### 4.2 报告 `/dashboard/reports`

**自动刷新**：日报 `daily:2026-10-28:2026-10-29`、周报/月报周期、26 项指标、环比、六期 sparkline、archive、business-history-index

**缺口**：
- 月报环比基线跳月（P1-2）
- RV-BR-05「竞品语境占比」恒 100.00%（分子未与竞品品牌求交，governed 帖必含 Momcozy），前端还把它当「净情感差 pp」生成战略建议
- 品牌健康总分未渲染：producer 只写 `score`，前端 `V3BrandHealthRow` 要求 `value`/`display` → `periodBrandHealth` 为 null
- 同比 78/78 全部 unavailable，但文案承诺「7 日替代窗口」
- `history_entry_count=0`，磁盘上却有 38 个孤儿 history 文件未入 manifest
- 「周期结束（不含）」对所有粒度都显示 `as_of_date=2026-10-29`（周报应为 10-26）
- 自动重算把 M-B 的 `comparison_contract_proven=true` 降级为 `false`

### 4.3 洞察 `/dashboard/insights`

**关键修正**：页面实际消费的是 **quarter_insights**（每日重算），不是 `insights` 数据集。季度 VOC 20,741 帖 / 755 VOC / 痛点排名 162 条「操作与可靠性」均为实时。

**缺口**：
- 用户画像 0.00%（P0-2）
- 78 条 storyline 被 allowlist 门禁强制校验，但页面**从未渲染** —— 无效依赖
- `case_references` 全为 `null`（casebook 冻结在 7 月）
- 洞察页「自动化评论 / 版务治理证据」= 0/0，真正的分类数据集（58,296 行）未被消费

### 4.4 分析 `/dashboard/analytics`

**自动刷新**：25,873 帖及各分布，来自 aggregates + posts

**缺口**：`brandObservationScore`（`50+50*(pos-neg)/posts`，仅帖子）与品牌健康「口碑健康」（`pos+0.5*neutral` over posts+comments）是不同口径，展示为同一语义。

### 4.5 搜索 `/dashboard/search`

**自动刷新**：结果数、品牌/社区 facet 计数，直读 `posts-public.json`

**缺口**：标签 facet 名称来自手工 `tag-dictionary-public.json`（2,346 rules，从不重建）；`comments-public.json` 约 200MB 按需拉取。

### 4.6 案例广场 `/cases`

**完全静态**：33 条人工策展案例，`generated_at=2026-07-16`，`review_due=2026-07-30` **已逾期 91 天**。不随 Reddit 语料更新。

### 4.7 高价值内容 / 舆情信号 / Agent 工作室 / 指标口径

- **高价值内容**：排序规则固定（先评论数后 Score，取前 20），但作用于实时帖子 → 442/165/107/396 随语料重算 ✅
- **舆情信号**：从 `quarter_insights.themes` 派生，实时 ✅
- **Agent 工作室**：Run id / 选题 94 / 改款 23 来自 `latest-*.json` 实时插值 ✅；但「由每日 07:05 自动流水线生成」是静态文案，且今日 07:05 实际失败
- **指标口径**：计数实时，字典文本静态

---

## 五、自动化刷新方案

### 总原则

1. **结论服务端化**：所有出现在页面上的判断句必须由 `recompute_derivatives` 生成 `conclusions[]`（含 `text` + `inputs` + `template_id` + `generated_at`），前端只做映射渲染
2. **统一 freshness 契约**：每个数据集 manifest 强制 `generated_at_utc` / `derived_from_run_id` / `source_snapshot_id`
3. **发布原子化**：所有派生数据集在 staging 目录构建完成后一次性切换，消除「新 base + 旧指标」混合窗口
4. **发布后回归断言**：跨页数值一致性作为流水线门禁

### 5.1 概览页

| 目标 | 动作 | 文件 |
|---|---|---|
| 完整度分档守恒 | 打印四档并加断言 `sum(coverage_grade)===canonical_counts.posts` | `governance/contracts.ts:127-132` |
| 品类/SPU 真实化 | 从 `posts[].product_bindings` 的 `category`/`product_family`/`exact_spu` 聚合；无绑定数据时输出 `status=unavailable` | `recompute_derivatives.py:498-552` |
| 品牌健康样本说明 | 输出 `source_voc_counts`（1,136 帖 + 2,289 评论），删除前端 `isMomcozyPost` 估算 | `recompute_derivatives.py:716-842` + `SnapshotDashboard.tsx:516` |
| 结论服务端化 | brand-health.json 增 `conclusion_codes` / `spread_band`（max-min 分档） | `BrandHealthSnapshotCard.tsx:94` |
| 风险两项 | 接入 `record_authority=='automation'` 与版务证据；或删行，避免「未接入」="无异常" | `recompute_derivatives.py:485`、`run_daily_t1_pipeline.py:226,281` |
| 缓存失效 | 以 `release.generated_at_utc` 或 ETag 作缓存键；加 5–15 分钟轮询/窗口聚焦重取 | `service.ts:103-104`、`brandHealth.ts:114` |
| 边界一致 | merge 按发布边界截断，或并列展示 `observation_max` 与 `data_as_of` | `run_daily_t1_pipeline.py:152-378` |

### 5.2 报告页

| 目标 | 动作 |
|---|---|
| 月报环比修复 | `_previous_period` 对 monthly 改为取上一个完整自然月起点 |
| 六期趋势修复 | `_period_chain` 同步修正，避免隔月 |
| RV-BR-05 修复 | 分子改为与 `competitor_brand_ids` 求交，或改名「品牌提及覆盖率」并删除净情感差结论 |
| 品牌健康渲染 | producer 输出 `value`/`display`，或前端适配 `score` |
| 同比口径 | 实现上年同日/ISO 周/同月基线，或删除「7 日替代窗口」文案 |
| 历史周期 | 把 38 个 history 文件纳入 manifest + index，或删除孤儿文件并移除下拉 |
| 周期结束标签 | 绑定 `report.period.end` 而非 `index.as_of_date` |
| 低样本门禁 | n<100 不出战略建议，仅展示观察值 + 分母 |

### 5.3 洞察页

| 目标 | 动作 |
|---|---|
| 画像修复（二选一） | A：前端改用 quarter-insights 已输出的 `personas.cohorts`（8 组计数）；B：`recompute_derivatives` 输出 per-cohort 证据实体 id，恢复 personas 投影读取 |
| storylines 依赖 | 要么渲染 78 条并标注 dataset 生成时间，要么移除 allowlist 门禁，避免 stale 数据集成为整页 gate |
| insights 自动化 | 把 metrics input → attested reports/insights 链做成带 attestation 文件的定时/审批作业；新版本 SHA 注册改为自动（读 manifest 而非预先登记） |
| insights 时间戳 | builder 写入 `generated_at_utc` + `source_counts` |

### 5.4 persona / insights / casebook 纳入流水线

**方案 A（推荐，渐进）**
```
07:05  collect → agents → merge → recompute → advance_pointer
07:40  personas（基于当日 base，无需 attestation）
08:10  insights（attested 链，读 personas + reports 输出）
月度    casebook（策展 + 自动 dossier 刷新）
```

**方案 B（最小改动，先止血）**
- 页面上明确标注 `personas` / `insights` / `casebook` 的生成时间与语料规模
- 移除 insights allowlist 的手工登记要求，改为「sha256 出现在 release pointer 中即信任」
- casebook 加「已过期」徽标（`review_due` 逾期 91 天）

### 5.5 标签字典自动化

在 `recompute_derivatives.py:943-946` 读取字典处改为：检测源字典版本变化时自动执行 `build_public_tag_dictionary.py`，并把 `dictionary_version` / `dictionary_sha256` / `generated_at` 写入 base manifest。同时解决标签结构性冻结（`merge_normalize.py:140-142` 对新行写空白 tagging、`:195/:371-372` 对评论写 `include_in_voc_metrics=False`）。

### 5.6 可靠性加固（P0）

1. **属主守卫**：`_preflight_writability` 从目录 `W_OK` 扩展为**遍历所有目标文件**，并拒绝 root-owned 路径
2. **事务化重建**：staging 目录 → 全部成功 → 原子切换（消除半发布状态）
3. **合并延迟可见**：base 内容改写延迟到 pointer advance 时生效
4. **run_id 真实化**：`collector_run_id` 使用真实启动时间，区分 schedule/manual
5. **发布后断言**（新增 `step6_post_publish_assert`）：
   ```
   概览 KPI == quarter_insights.rolling_30_days
   brand_health.overall == brand-health.json.overall.score
   search 总数 == base manifest canonical_counts.posts
   任一不等 → pipeline fail + Feishu 卡片标注
   ```

---

## 六、实施路线图

| 阶段 | 内容 | 影响 |
|---|---|---|
| **第 1 周（止血）** | 属主守卫 + 事务化重建 + 发布后断言 + 前端缓存失效 | 消除当日断裂与「打开页面看不到更新」 |
| **第 2 周（口径）** | 完整度分档守恒、RV-BR-05、月报环比/六期趋势、品牌健康渲染、周期结束标签 | 修正会误导决策的数字 |
| **第 3 周（结论）** | 结论服务端化（`conclusions[]`）、品类/SPU 真实化、品牌健康样本说明 | 让结论跟随数据变化 |
| **第 4 周（自动化）** | personas 并入 07:40、insights attested 链并入 08:10、标签字典按版本触发 | 覆盖缺口 40% 语料 |
| **月度** | casebook 刷新节拍 + 过期徽标；画像 ID 空间统一 | 消除静态页 |

---

## 七、审计可信度声明

- 248 项检查中 232 项经独立对抗验证确认，**16 项原判定被推翻并已修正**
- 典型修正：`状态条新鲜度` 从 auto 改判为「status 硬编码 partial」；`品牌健康样本说明` 从 auto 改判为「auto 但样本值错误」；`风险焦点两项` 从 static 改判为「数据驱动但值退化」；`60 条比较帖` 确认是 **post×品牌 pair 数**而非帖子数（实际 distinct geo posts = 91）
- 未能验证：`/dashboard/search` 200MB 评论按需拉取在弱网下的表现；`reports/history/` 40 个历史文件与现行 schema 的兼容性
- 全程只读，未修改生产任何文件
