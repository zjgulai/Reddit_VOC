---
name: voc-insight-storylines-v2
description: VOC洞察故事线集合v2 — 将标签、指标、分析维度串联为业务可读的叙事框架。37条故事线覆盖7大业务链路+反直觉洞察，每条含触发条件、SRAC评分、6段式叙事结构（含反直觉洞察）、所需数据、输出模板、关联story_lines与strategy_package。
created: 2026-05-21
updated: 2026-05-22
status: stable
depends: dim_tag_v6, 10_voc_analysis_dimension_catalog, 11_voc_indicator_caliber_table
---

# VOC 洞察故事线集合 v2

> **文档定位**：标签字典 → 指标字典 → 分析维度 → **洞察故事线** → 业务行动
> 
> 故事线是分析师从 VOC 数据中提取业务价值的**叙事框架**。它回答：当某个指标异常时，应该讲什么故事？故事的结构是什么？需要哪些标签和指标支撑？最终输出什么给业务方？
>
> **关联文档**：
> - [指标维度目录](10_voc_analysis_dimension_catalog.md) — 28 指标定义与公式
> - [指标口径表](11_voc_indicator_caliber_table.md) — 26 指标 SQL 模板
> - [打标管道](04_labeling_pipeline.md) — LLM 打标流程（**所有故事线依赖 voc_tags 非空**）

---

## 一、洞察故事线模板结构（6 段式叙事框架）

每条故事线遵循统一的叙事结构，确保输出给业务方的洞察报告格式一致、逻辑闭环。

**相比 v1 的升级**：从 5 段式扩展为 **6 段式**，新增「**2.5. 反直觉洞察**」—— 这是故事线的灵魂。大量实战案例证明，最有价值的洞察往往与表面认知相反，常见于“反直觉”维度的深挖。

```
【标题】一句话概括核心发现

【1. 信号发现】What — 数据发现了什么异常？
  → 触发指标 + 当前值 + 与基准的对比 + 置信度
  → SRAC 四维评分（Severity / Reach / Actionability / Confidence）

【2. 根因归因】Why — 为什么会发生？
  → Top-3 根因标签 + 情感分布 + 平台/国家/SPU 细分
  → 每条根因标注「证据强度」（★主观抱怨 ★★多用户共识 ★★★带实物拆解 ★★★★可复现实验）
  → Top-3 消费者原话（含 review_id，可溯源）
  → AGRS 聚合摘要（50 字以内概括核心抱怨）
  → 与历史同期的对比 + 竞品对标（如有）

【2.5. 反直觉洞察】Wait — 有什么与直觉相反的发现？
  → 直觉认知：业务方通常怎么理解这个现象？
  → 反直觉发现：数据揭示了什么与直觉相反的事实？
  → 深层机制：为什么会形成这种反直觉现象？
  → 高后果信号：低频但高严重度的隐藏风险

【3. 影响评估】So What — 对业务的影响有多大？
  → 影响的用户规模 / 潜在 revenue at risk / NPS 拖累
  → 关联的 business_impact 字段（退货率/复购率/口碑评分等）
  → 竞品迁移信号（如有用户流向竞品）

【4. 行动建议】Now What — 建议做什么？
  → 关联的 strategy_package（核心体验改良包 / 履约提速包等）
  → 主责部门 (dept_owner) + 优先级 (default_priority)
  → 预期修复周期 + 验收指标
  → **预期指标变化**（MAA 式，如：同标签命中量 12257 → 目标下降 30% → 8579）

【5. 持续监控】How — 如何跟踪改善效果？
  → 监控指标 + 监控频率 + 预警阈值
  → 下次复盘时间
```

### 核心升级说明

| 升级项 | v1 | v2（本次升级） | 来源 |
|---|---|---|---|
| 叙事段数 | 5 段 | **6 段**（新增反直觉洞察） | 实战案例反复验证 |
| 优先级依据 | 人工标注 P0/P1/P2 | **SRAC 四维评分** 量化排序 | MAA 策略包方法论 |
| 根因深度 | 标签 + 提及次数 | 标签 + **证据强度** + **消费者原话** + **聚合摘要** | AGRS 评论摘要 |
| 洞察层次 | 表层结论 | **表层结论** + **反直觉洞察** + **深层机制** | 九步工作流 |
| 行动闭环 | 建议 + 验收指标 | 建议 + **预期指标变化** + **竞品迁移防御** | MAA 策略包 |

### 证据强度四级定义

| 等级 | 标识 | 定义 | 示例 |
|---|---|---|---|
| L1 | ★ | 主观抱怨，无具体证据 | "company is trash" |
| L2 | ★★ | 多用户共识，有具体描述 | "my M5 also broke after 3 months" |
| L3 | ★★★ | 带实物拆解 / 图片 / 视频证据 | 用户上传拆机照片，指出密封缺陷 |
| L4 | ★★★★ | 可复现实验，有技术细节 | 用户设计替代密封件并验证有效 |

> **关键原则**：高后果信号往往不在高频词里，而在**高证据强度、强迁移意图、强机制解释**的信号里。详见本文“**2.5 反直觉洞察**”章节的案例拆解思路。

---

## 二、故事线全景索引

| # | 故事线 | 业务链路 | 触发指标 | 主责部门 | story_lines | strategy_package |
|---|---|---|---|---|---|---|
| S01 | 北极星崩塌：NPS 异常下滑 | 品牌与市场 | VOC_NPS_adjusted | 品牌市场中心 | 核心体验问题 | 核心体验改良包 |
| S02 | 广告信任危机 | 品牌与市场 | ATI | 品牌市场中心 | 信任校验 | 信息架构优化包 |
| S03 | 搜索信息黑洞 | 品牌与市场 | ITI | 品牌市场中心 | 卖点认知偏差 | 信息架构优化包 |
| S04 | 竞品情感失守 | 品牌与市场 | CEG | 品牌市场中心 | 竞品隔离诊断 | 竞品差异化包 |
| S05 | 社媒负面先兆 | 品牌与市场 | SLI | 品牌市场中心 | 人群内容匹配 | 人群内容匹配包 |
| S06 | 种草转化率低迷 | 营销与获客 | SCI | 电商运营部 | 卖点认知偏差 | 核心卖点校准包 |
| S07 | 价格感知崩塌 | 营销与获客 | PPD | 电商运营部 | 价值感争议 | 价值表达优化包 |
| S08 | 促销承诺不兑现 | 营销与获客 | PFR | 电商运营部 | 承诺偏差 | 承诺一致性校对包 |
| S09 | 购买动机转化瓶颈 | 销售与转化 | PMF | 电商运营部 | 价值感争议 | 价值表达优化包 |
| S10 | 促销信任危机 | 销售与转化 | PAI | 电商运营部 | 承诺偏差 | 承诺一致性校对包 |
| S11 | 库存-投诉螺旋 | 销售与转化 | ICL | 仓储物流部 | 履约体验 | 履约提速包 |
| S12 | 品线健康度恶化 | 产品与研发 | PLH | 产品中心 | 核心体验问题 | 核心体验改良包 |
| S13 | 标签紧急度风暴 | 产品与研发 | TUI | 产品中心 | 质量风险闭环 | 质量风险防控包 |
| S14 | SPU 问题热力爆发 | 产品与研发 | SPH | 产品中心 | 核心体验问题 | 核心体验改良包 |
| S15 | 产品衰退加速 | 产品与研发 | DA | 产品中心 | 核心体验问题 | 核心体验改良包 |
| S16 | 策略包修复无效 | 产品与研发 | SPC | 产品中心 | 质量风险闭环 | 质量风险防控包 |
| S17 | 品质波动异常 | 产品与研发 | QVC | 产品中心 | 质量风险闭环 | 质量风险防控包 |
| S18 | 物流满意度滑坡 | 供应链与物流 | LSS | 仓储物流部 | 履约体验 | 履约提速包 |
| S19 | 跨境物流投诉激增 | 供应链与物流 | CLCR | 仓储物流部 | 履约体验 | 履约提速包 |
| S20 | 包装投诉集中爆发 | 供应链与物流 | PCR | 仓储物流部 | 使用负担 | 场景适配优化包 |
| S21 | 物流时效系统性偏差 | 供应链与物流 | LTD | 仓储物流部 | 承诺偏差 | 履约提速包 |
| S22 | 客服体验恶化 | 客服与售后 | CSS | 全球客服中心 | 服务体验断点 | 一次解决提升包 |
| S23 | 退换货痛苦加剧 | 客服与售后 | RPI | 全球客服中心 | 售后闭环能力 | 售后服务SOP包 |
| S24 | 投诉持续升级 | 客服与售后 | EUR | 全球客服中心 | 售后闭环能力 | 售后服务SOP包 |
| S25 | 信任恢复失败 | 客服与售后 | TRR | 全球客服中心 | 信任恢复 | 售后服务SOP包 |
| S26 | 推荐意愿不足 | 客户体验与忠诚 | RWI | 品牌市场中心 | 复购准备度 | 复购激活包 |
| S27 | 复购信号消失 | 客户体验与忠诚 | RSS | 电商运营部 | 复购准备度 | 复购激活包 |
| S28 | 新手妈妈流失加剧 | 客户体验与忠诚 | NMPI | 产品中心 | 新手上手断点 | 核心体验改良包 |
| S29 | 高价值用户沉默 | 客户体验与忠诚 | CAS | 电商运营部 | 高价值客诉治理 | 个性化运营增强包 |
| S30 | P0 触发率飙升 | 运营与质量 | P0R | 品质管理中心 | 质量风险闭环 | 质量风险防控包 |
| S31 | 安全问题信号 | 运营与质量 | SSR | 品质管理中心 | 质量风险闭环 | 合规背书强化包 |
| S32 | 部门 SLA 不达标 | 运营与质量 | DSR | 品质管理中心 | 售后闭环能力 | 一次解决提升包 |
| S33 | 风险暴露度超限 | 运营与质量 | REE | 品质管理中心 | 质量风险闭环 | 质量风险防控包 |
| S34 | 竞品迁移链断裂 | 反直觉洞察 | — | 品牌市场中心 | 竞品迁移叙事 | 竞品差异化包 |
| S35 | 二手转让原因映射 | 反直觉洞察 | — | 电商运营部 | 新手上手断点 | 购买决策优化包 |
| S36 | 用户 DIY 维修信号 | 反直觉洞察 | — | 产品中心 | 可维修性信号 | 核心体验改良包 |
| S37 | 价格-期望错配陷阱 | 反直觉洞察 | — | 电商运营部 | 价格锚点偏差 | 价值表达优化包 |

---

## 三、核心故事线详解（精选 15 条）

### S01 · 北极星崩塌：NPS 异常下滑

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | NPS < 30 | P0 | 8 | 10 | 6 | 9 | **8.6** |
| 环比 | 周环比下滑 > 10pp | P0 | 7 | 8 | 7 | 8 | **7.5** |
| 同比 | 连续 2 周低于去年同期 | P1 | 6 | 7 | 6 | 7 | **6.5** |

**叙事结构**
```
【1. 信号发现】
  VOC_NPS_adjusted 本周为 {value}，环比下滑 {delta}pp。
  其中 Promoter 占比 {promoter_pct}%，Detractor 占比 {detractor_pct}%。
  按平台拆分：{platform_breakdown}。

【2. 根因归因】
  Top-3 拖累标签（含证据强度 + AGRS 聚合摘要）：
    1. {tag_1} ({mention_1}次, 负向{neg_pct_1}%, 证据强度:{evidence_level_1})
       AGRS 摘要：{agr_summary_1}
       消费者原话："{consumer_quote_1}" — {source_platform_1}, {country_1}
    2. {tag_2} ({mention_2}次, 负向{neg_pct_2}%, 证据强度:{evidence_level_2})
       AGRS 摘要：{agr_summary_2}
       消费者原话："{consumer_quote_2}" — {source_platform_2}, {country_2}
    3. {tag_3} ({mention_3}次, 负向{neg_pct_3}%, 证据强度:{evidence_level_3})
       AGRS 摘要：{agr_summary_3}
       消费者原话："{consumer_quote_3}" — {source_platform_3}, {country_3}
  关联 story_lines：{top_story_lines}
  竞品对标：{competitor_gap}

【2.5. 反直觉洞察】
  直觉认知：NPS 下滑 → 用户整体不满意 → 需要全面提升产品/服务。
  反直觉发现：NPS 下滑往往由**少数几个高证据强度的根因标签**驱动，
    而非"全面崩塌"。例如：1 个防水设计缺陷标签（★★★★）可能比
    100 个"一般不满"（★）对 NPS 的拖累更大。
  深层机制：
    - Promoter 转化率下降 ≠ Detractor 增加。有时是"沉默的被动者"变多。
    - 竞品情感差距 CEG 可能先于 NPS 下滑 2-4 周出现（社媒先兆）。
    - 高频提及 ≠ 高业务影响。低频但高证据强度的问题（如安全隐患）
      可能在 NPS 中尚未充分暴露。
  高后果信号：
    - 若 Detractor 中 "安全隐患" 类标签（如 TAG_L1_035 烧焦）
      提及量周环比 > 50%，即使总 NPS 仍 > 30，也应立即升级为 P0。

【3. 影响评估】
  影响用户规模：{affected_users} 人
  关联 business_impact：{biz_impacts}
  预计 revenue at risk：${revenue_at_risk}

【4. 行动建议】
  主责部门：{dept_owner}
  strategy_package：{strategy_packages}
  优先级：P0 — 72 小时内启动专项
  预期修复周期：{expected_fix_weeks} 周
  预期指标变化（MAA 式）：
    - VOC_NPS_adjusted：当前 {current_nps} → 目标提升 {target_nps_delta}pp → {target_nps}
    - Detractor 占比：当前 {current_detractor_pct}% → 目标降至 {target_detractor_pct}%
    - Top-3 拖累标签提及量：当前 {current_top3_mentions} → 目标下降 ≥30% → {target_top3_mentions}
    - Promoter 占比：目标提升至 {target_promoter_pct}%

【5. 持续监控】
  监控指标：VOC_NPS_adjusted + Top-3 拖累标签提及量 + CEG（竞品情感差距，提前 2-4 周预警）
  监控频率：每周
  预警阈值：NPS < 35 或 Top-3 标签提及量周环比增长 > 20% 或 CEG 环比恶化 > 5pp
```

**所需数据**
- 指标：`VOC_NPS_adjusted` (BM-1)
- 标签：`proxy_nps_role IN ('promoter','detractor')` 的 2,009 标签
- 维度：平台 / 国家 / PL / SPU / 时间
- 竞品：`is_own_brand` 对比

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | 全节点 A→L3 | 无 | NPS 是北极星，需全局视角 |
| **标签范围** | `proxy_nps_role IN ('promoter','detractor','passive')` 的 2,346 标签 | 无 proxy_nps_role 的标签 | passive 不参与分子但参与分母 |
| **情感方向** | 正向 + 负向 + 中性（全部） | 无 | NPS 需要全量情感分布 |
| **平台范围** | 全 7 信源 | 无 | 跨平台才能反映真实品牌健康度 |
| **时间窗口** | 滑动 30 天（周环比）/ 90 天（月环比） | — | 短期波动用 30 天，趋势用 90 天 |
| **质量等级** | quality_tier IN ('A','B','C') | quality_tier='D' | D 级内容质量太低，引入噪音 |
| **特殊条件** | `content_en IS NOT NULL` | 空内容 / 纯表情符号 | 确保有可分析文本 |

**SQL WHERE 片段**
```sql
WHERE vl.quality_tier IN ('A','B','C')
  AND vl.content_en IS NOT NULL
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND dt.tag_id IS NOT NULL
```

> **关键说明**：NPS 计算的特殊性在于 `passive` 用户虽不参与分子，但必须计入分母。若只筛选 promoter/detractor，会虚高 NPS 绝对值。

---

### S07 · 价格感知崩塌

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | PPD > 60% | P0 | 7 | 8 | 9 | 8 | **8.0** |
| 环比 | PPD 周环比上升 > 15pp | P1 | 6 | 7 | 8 | 7 | **7.0** |
| 关联 | 促销活动期间 PPD > 50% | P1 | 6 | 6 | 8 | 7 | **6.8** |

**叙事结构**
```
【1. 信号发现】
  价格感知偏差 PPD 本周为 {ppd_value}%，即 {ppd_value}% 的价格相关 VOC 为负向。
  价格标签总提及 {total_price_mentions} 次，负向 {negative_price_mentions} 次。
  按品线拆分：{pl_breakdown}。

【2. 根因归因】
  Top-3 价格负向标签（含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, 负向{neg_pct_1}%, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}, {country_1}
    2. {tag_2} ({mentions_2}次, 负向{neg_pct_2}%, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}, {country_2}
    3. {tag_3} ({mentions_3}次, 负向{neg_pct_3}%, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}, {country_3}
  触发场景：{intent_type_distribution}
  关联 SPU：{spu_list}
  竞品价格对标：{competitor_price_comparison}

【2.5. 反直觉洞察】
  直觉认知：低价购买的用户对质量容忍度更高 → 价格敏感型用户更容易满足。
  反直觉发现：促销获客的用户反而**更挑剔**。
    案例：用户因 "big sale $120 instead of $199" 购买，故障后却认为
    "They should be waterproof. Especially for the price they're listed at."
    用户以**正价产品标准**要求促销购买品。
  深层机制：
    - 母婴品类用户对安全/质量的期望不因价格而降低
    - 促销降低的是"购买门槛"，不是"质量期望"
    - "先涨后降"的促销策略会放大价格感知偏差
  高后果信号：
    - 若促销期 PPD > 50% 且 "质量感知" 标签同时下滑 → 
      说明促销策略正在侵蚀品牌价值，需立即调整

【3. 影响评估】
  影响用户规模：{affected_users} 人
  关联 business_impact：转化率下降 / 购物车放弃率上升 / 退货率上升
  竞品价格对标：{competitor_price_comparison}
  Revenue at risk：${revenue_at_risk}

【4. 行动建议】
  主责部门：电商运营部
  strategy_package：价值表达优化包 + 核心卖点校准包
  建议：
    - 短期：检查定价页面信息是否充分，确保"为什么值这个价"清晰传达
    - 中期：调整促销策略，避免"先涨后降"，改用"赠品增值"替代"直接降价"
    - 长期：建立价格锚定机制 + 促销用户期望管理机制
  预期指标变化（MAA 式）：
    - PPD：当前 {current_ppd}% → 目标降至 {target_ppd}%（促销期 < 40%）
    - 价格标签负向占比：当前 {current_neg_pct}% → 目标降至 {target_neg_pct}%
    - 购物车放弃率：目标下降 {target_cart_abandon_delta}pp

【5. 持续监控】
  监控指标：PPD + 价格标签情感占比 + 促销期 NPS 变化
  监控频率：每周（促销期每日）
  预警阈值：PPD > 50% 或促销期 PPD > 45%
```

**所需数据**
- 指标：`PPD` (MK-2)
- 标签：`theme ILIKE '%价格%'` 的 6 标签
- 维度：PL / SKU / 促销档期 / 平台

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | P1→P2→L1 | A/I/L2/L3 | 价格感知主要在决策和首次使用阶段形成 |
| **标签范围** | `problem_type='价格'` 或 `tag_id IN (价格相关6标签)` | 物流/客服/产品性能标签 | 聚焦价格-价值判断，排除其他噪音 |
| **情感方向** | 负向 + 中性（中性也反映"无感"/"无惊喜"） | 纯正向 | 正向价格评价不进入 PPD 分子 |
| **平台范围** | Amazon + Trustpilot + Zendesk | Reddit/Meltwater | 购买后评价的价格感知更真实 |
| **时间窗口** | 滑动 30 天 | — | 价格感知变化快，需短期窗口 |
| **质量等级** | quality_tier IN ('A','B') | C/D | 价格感知需要高质量文本支撑语义判断 |
| **特殊条件** | 区分 `verified_purchase=true` vs `false` | — | 未购买用户的价格评价权重应降低 |

**SQL WHERE 片段**
```sql
WHERE vl.quality_tier IN ('A','B')
  AND dt.problem_type = '价格'
  AND vl.aipl_node IN ('P1','P2','L1')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND (vl.source_name IN ('amazon','trustpilot','zendesk')
       OR vl.verified_purchase = true)
```

> **关键说明**：PPD 计算时，**未验证购买**用户的价格评价应降权 50%。Reddit 用户可能从未购买但参与价格讨论，其评价不等于真实购买者感知。

---

### S13 · 标签紧急度风暴

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | Top-10 TUI 中 ≥3 个 P0 标签 | P0 | 9 | 6 | 9 | 8 | **8.0** |
| 关联 | 同一 SPU 出现 ≥2 个 P0 标签 | P0 | 10 | 5 | 9 | 7 | **7.8** |
| 趋势 | P0 标签提及量周环比增长 > 50% | P1 | 7 | 5 | 8 | 7 | **6.8** |

**数据实况（v6.2 字典验证）**
> P0 标签仅 **13 个**（占 0.6%），且**全部为 L2-SPU 专属**，
> 且**全部标记为"中风险"**（无高风险 P0 标签）。
> 这导致 P0R/SSR/REE 的统计基数极小，月度波动可能较大。
> **修正触发逻辑**：不能仅依赖 P0 标签数量，必须结合「证据强度」和「提及量增长趋势」。

**叙事结构**
```
【1. 信号发现】
  紧急度 Top-10 标签中，P0 标签 {p0_count} 个，高风险标签 {high_risk_count} 个。
  Top-1 紧急标签：{tag_1} (TUI={tui_1}, 提及 {mentions_1} 次)
  按品线分布：{pl_distribution}。
  ⚠️ 注意：P0 标签仅 13 个，需结合证据强度和增长趋势综合判断。

【2. 根因归因】
  P0 标签详情（含证据强度 + 消费者原话）：
    1. {tag_1} (TUI={tui_1}, 提及 {mentions_1}次, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}
    2. {tag_2} (TUI={tui_2}, 提及 {mentions_2}次, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}
    3. {tag_3} (TUI={tui_3}, 提及 {mentions_3}次, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}
  关联问题类型：{problem_types}
  涉及 SPU：{affected_spus}

【2.5. 反直觉洞察】
  直觉认知：P0 标签 = 最高优先级 = 最高风险 = 必须立即响应。
  反直觉发现：
    - P0 标签仅 13 个，且**全部标记为"中风险"**（无高风险 P0）
    - P0 标签的 TUI 权重为 1.0，但风险权重为 1.0（中风险）
    - 真正的高风险标签（6 个高风险 + 2 个极高风险）反而**没有 P0 优先级**
    - 这意味着「优先级」和「风险等级」两个维度**没有对齐**
  深层机制：
    - TUI 的公式中 priority 维度对绝大多数标签贡献为常数（P1 占 85.5%）
    - 真实区分度主要来自 sentiment（负向 1.0 vs 正向 0.3）
    - 13 个 P0 标签全部是 L2-SPU 专属，说明 P0 标签集中在具体产品问题上，
      而非系统性安全问题
  高后果信号：
    - 若某 P0 标签（如"加热部件烧焦异味"）的证据强度达到 ★★★★
      且周环比增长 > 50%，即使总提及量 < 10 次，也应立即升级为 P0 响应
    - 因为此类问题可能涉及**安全召回**

【3. 影响评估】
  关联 business_impact：{business_impacts}
  涉及 SPU：{affected_spus}
  预计受影响用户：{estimated_users}
  召回风险评估：{recall_risk_assessment}

【4. 行动建议】
  主责部门：产品中心（质量问题）+ 品质管理中心（安全评估）
  strategy_package：质量风险防控包
  优先级：P0 — 24 小时内启动根因分析
  建议：
    - 立即：品质管理中心介入，确认是否为系统性问题
    - 立即：若证据强度 ≥ ★★★★，冻结该 SPU 相关批次出货
    - 短期：工程师介入问题复现，区分"设计缺陷"vs"批次质量问题"
    - 中期：设计/工艺变更
  预期指标变化（MAA 式）：
    - P0 标签提及量：当前 {current_p0_mentions} → 目标降至 {target_p0_mentions}
    - 关联 SPU 退货率：当前 {current_return_rate}% → 目标降至 {target_return_rate}%
    - TUI Top-10 中 P0 标签数：目标 ≤ 1 个

【5. 持续监控】
  监控指标：P0 标签提及量 + 关联 SPU 退货率 + 安全相关标签提及量
  监控频率：每日
  验收标准：P0 标签提及量降至基线以下，且连续 7 天无新增 ★★★★ 证据
```

**所需数据**
- 指标：`TUI` (PD-2) — **唯一可预计算的指标**（不依赖 voc_tags）
- 标签：`default_priority='P0'` 的 13 标签 + `risk_level IN ('高风险','极高风险')` 的 8 标签
- 维度：tag_id / SPU / PL / 时间

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | 全节点 A→L3 | 无 | P0 标签可能出现在任何阶段（如 A 节点广告误导也可触发 P0） |
| **标签范围** | `default_priority='P0'` OR `risk_level IN ('高风险','极高风险')` | 仅 `default_priority` 的普通标签 | 需同时关注「标称 P0」和「实质高风险」 |
| **情感方向** | 负向为主 + 中性（中性安全描述也值得关注） | 纯正向 | 正向安全评价不反映紧急度 |
| **平台范围** | 全 7 信源 | 无 | P0 问题可能在任何平台首发（Reddit 常先发） |
| **时间窗口** | 滑动 7 天（日监控）/ 30 天（周汇总） | — | P0 需要每日监控，TUI Top-10 每周汇总 |
| **质量等级** | quality_tier IN ('A','B','C') | D | P0 问题即使 C 级也应纳入，不能因质量过滤漏掉 |
| **特殊条件** | `evidence_strength >= '★★'` 优先响应 | 仅 ★ 的孤立抱怨 | 单用户主观抱怨（★）不触发 P0，需多用户共识（★★+） |

**SQL WHERE 片段**
```sql
WHERE dt.default_priority = 'P0'
   OR dt.risk_level IN ('高风险', '极高风险')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '7 days'
  AND vl.quality_tier IN ('A','B','C')
```

> **关键说明**：TUI 可预计算，但 P0 触发必须结合 **证据强度** 和 **增长趋势**。v6.2 字典中 13 个 P0 标签全为 L2-SPU 专属且风险等级全为"中风险"，这意味着「标称 P0」和「实质风险」存在错位，需同时监控两个维度。

---

### S14 · SPU 问题热力爆发

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | SPH > 阈值 (按 SPU 动态设定) | P1 | 7 | 6 | 9 | 8 | **7.5** |
| 排名 | SPH 在同类 SPU 中 Top-5% | P1 | 6 | 5 | 8 | 7 | **6.5** |
| 趋势 | SPH 连续 3 周上升 | P2 | 5 | 4 | 8 | 7 | **6.0** |

**叙事结构**
```
【1. 信号发现】
  SPU {spu_id} ({spu_name}) 问题热力 SPH = {sph_value}。
  该 SPU 负向标签提及 {negative_mentions} 次，TUI 加权后 {weighted_mentions}。
  在 {product_line} 品线中排名 {rank}/{total_spus}。

【2. 根因归因】
  Top-5 负向标签（含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, TUI={tui_1}, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}
    2. {tag_2} ({mentions_2}次, TUI={tui_2}, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}
    3. {tag_3} ({mentions_3}次, TUI={tui_3}, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}
    4. {tag_4} ({mentions_4}次, TUI={tui_4}, 证据强度:{evidence_4})
    5. {tag_5} ({mentions_5}次, TUI={tui_5}, 证据强度:{evidence_5})
  关联 story_lines：{story_lines}
  AGRS 聚合摘要：{agr_summary}

【2.5. 反直觉洞察】
  直觉认知：SPH 最高的 SPU = 问题最严重的 SPU = 需要最多资源投入。
  反直觉发现：
    - SPH 高可能是因为该 SPU **销量大/评论基数大**，而非问题率更高
    - 真正危险的可能是 SPH "中等" 但 **退货率异常高** 的 SPU
    - 用户自行维修 / 二手转让 / 竞品迁移信号 不会直接体现在 SPH 中
      但这些信号的业务后果可能比 SPH 更严重
  深层机制：
    - SPH = Σ(负向×TUI)/总提及，分母是"总提及"而非"总销量"
    - 冷门 SPU 即使问题率 100%，如果总提及少，SPH 也可能不高
    - 需结合「退货率 / 客服工单量 / 竞品迁移率」综合判断
  高后果信号：
    - 若某 SPU 的 SPH 中等但「用户自行维修」相关内容在 Reddit/社区
      中获得高赞 → 说明问题已被用户"自行解决"，品牌在失去改进机会

【3. 影响评估】
  该 SPU 占总销量 {sales_share}%
  退货率：{return_rate}% (品线平均 {avg_return_rate}%)
  关联 business_impact：{business_impacts}
  竞品迁移信号：{competitor_migration_signals}

【4. 行动建议】
  主责部门：产品中心
  strategy_package：核心体验改良包
  优先级：P1
  建议：
    - 产品改进：针对 Top-3 标签对应的功能/质量问题
    - 运营调整：临时增加该 SPU 的客服响应优先级
    - 供应链：检查该 SPU 近期批次质量
  预期指标变化（MAA 式）：
    - SPH：当前 {current_sph} → 目标降至 {target_sph}
    - 退货率：当前 {current_return_rate}% → 目标降至 {target_return_rate}%
    - Top-3 负向标签提及量：目标下降 ≥30%

【5. 持续监控】
  监控指标：SPH + 退货率 + 客服工单量 + 竞品迁移率
  监控频率：每周
  预警阈值：SPH 连续 3 周上升 或 退货率 > 品线平均 2 倍
```

**所需数据**
- 指标：`SPH` (PD-3)
- 标签：`tag_scope='L2-SPU专属' AND spu_id='{spu_id}'` 的 1,225 标签子集
- 维度：SPU / 时间

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | L1（产品使用）+ L2（售后） | A/I/P1/P2 | SPU 问题在使用和售后阶段暴露 |
| **标签范围** | `tag_scope='L2-SPU专属'` + 目标 SPU | L0/L1 通用标签、物流/客服/价格标签 | 只看该 SPU 专属问题，排除跨品线噪音 |
| **情感方向** | 负向为主 | 纯正向 | 正向评价不增加 SPH |
| **平台范围** | Amazon + Zendesk + Reddit | Meltwater/Facebook/Instagram | 产品深度评价集中在 Amazon/Reddit，Zendesk 含售后 |
| **时间窗口** | 滑动 30 天 | — | SPH 需要足够样本量，7 天可能太少 |
| **质量等级** | quality_tier IN ('A','B','C') | D | C 级含关键产品问题信号 |
| **特殊条件** | 按 SPU 聚合，分母为该 SPU 总提及 | 跨 SPU 混算 | SPH 是 SPU 级指标，不能跨 SPU 平均 |

**SQL WHERE 片段**
```sql
WHERE vl.product_id = '{target_spu_id}'
  AND dt.tag_scope = 'L2-SPU专属'
  AND vl.aipl_node IN ('L1','L2')
  AND dt.problem_type NOT IN ('物流','客服','价格')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND vl.quality_tier IN ('A','B','C')
```

> **关键说明**：SPH 计算的分母是 **该 SPU 的总提及量**（非总销量）。冷门 SPU 即使问题率 100%，总提及少时 SPH 也可能不高。需同时看 **退货率** 和 **客服工单量** 做交叉验证。

---

### S18 · 物流满意度滑坡

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | LSS < 40% | P0 | 7 | 8 | 8 | 7 | **7.5** |
| 环比 | LSS 周环比下降 > 15pp | P1 | 6 | 7 | 8 | 7 | **7.0** |
| 国家 | 单一国家 LSS < 30% | P1 | 7 | 6 | 7 | 6 | **6.5** |
| 关联 | 物流投诉中 "tracking" 类占比 > 50% | P1 | 5 | 6 | 9 | 7 | **6.8** |

**叙事结构**
```
【1. 信号发现】
  物流满意度 LSS 本周为 {lss_value}%，环比 {delta}pp。
  物流标签总提及 {total_logistics} 次，正向 {positive} 次，负向 {negative} 次。
  按国家拆分：{country_breakdown}。
  按问题类型拆分：时效 {timing_pct}% / 信息透明度 {info_pct}% / 包裹损坏 {damage_pct}%。

【2. 根因归因】
  Top-3 物流负向标签（含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, 负向{neg_pct_1}%, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}, {country_1}
    2. {tag_2} ({mentions_2}次, 负向{neg_pct_2}%, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}, {country_2}
    3. {tag_3} ({mentions_3}次, 负向{neg_pct_3}%, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}, {country_3}
  关联 story_lines：履约体验 / 承诺偏差
  外部因素：{tracking_issues} / {carrier_delays} / {customs_delays}

【2.5. 反直觉洞察】
  直觉认知：物流投诉 = 物流慢 = 换更快的物流商。
  反直觉发现：
    - 物流投诉中大量是"信息不透明"而非"真的慢"——
      用户不知道包裹在哪里比包裹真的晚到更焦虑
    - 用户留言："The package took 2 weeks which is fine, but I had NO IDEA
      where it was for 10 days. That was the worst part."
    - 跨境物流投诉中，部分"物流问题"实际上是产品适配问题
      （如德国用户吐槽插头不兼容欧标，归类为"产品不符预期"而非物流）
  深层机制：
    - 物流体验 = 实际时效 × 信息透明度 × 预期管理
    - 信息透明度为 0 时，即使时效正常，用户焦虑感也会爆表
    - 跨境物流的"黑箱期"（出库后 → 目的国清关前）是焦虑峰值区
    - 不同国家对物流时效的期望差异巨大（欧美容忍度高，东南亚容忍度低）
  高后果信号：
    - 若 "tracking 信息缺失" 类投诉占比 > 50% →
      问题在信息系统而非物流商，换物流商无法解决
    - 若某国家 LSS 异常低且投诉集中在 "customs/duty" →
      可能是关税政策变化或产品资质问题，需法务/合规介入

【3. 影响评估】
  受影响订单：{affected_orders}
  退货率关联：物流投诉用户退货率 {return_rate}%（非物流用户 {baseline_return_rate}%）
  客服成本：每单物流投诉平均客服处理成本 ${cs_cost}
  关联 business_impact：退货率 / 差评率 / 客服成本 / 复购率
  Revenue at risk：${revenue_at_risk}

【4. 行动建议】
  主责部门：仓储物流部（物流优化）+ 电商运营部（信息透明）
  strategy_package：履约提速包 + 信息架构优化包
  优先级：P1
  建议：
    - 立即：检查 tracking 信息推送机制，确保关键节点（出库/登机/清关/派送）及时通知
    - 短期：更换时效不达标的物流商，建立物流商评分淘汰机制
    - 短期：在详情页增加"预计送达时间"动态计算（基于国家+物流商历史数据）
    - 中期：优化仓库作业流程，缩短"订单确认 → 出库"时间
    - 长期：建立物流时效 SLA 监控体系 + 自动化物流商切换机制
    - 长期：针对高投诉国家建立本地仓或前置仓
  预期指标变化（MAA 式）：
    - LSS：当前 {current_lss}% → 目标提升至 {target_lss}%（> 60%）
    - tracking 信息缺失类投诉：目标下降 ≥50%
    - 物流相关退货率：当前 {current_return_rate}% → 目标降至 {target_return_rate}%

【5. 持续监控】
  监控指标：LSS + LTD + CLCR + **tracking 信息缺失类投诉占比** + **物流商评分**
  监控频率：每周
  预警阈值：LSS < 45% 或 tracking 信息缺失投诉占比 > 40%
```

**所需数据**
- 指标：`LSS` (SC-1)
- 标签：`theme ILIKE '%物流%'` 的 60 标签
- 维度：国家 / 物流商 / 时间 / 问题类型（时效/信息/损坏）

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | P2（下单/发货）→ L1（收货） | A/I/L2/L3 | 物流只发生在下单到收货阶段 |
| **标签范围** | `problem_type='物流'` 或 `theme ILIKE '%物流%'` | 产品/价格/客服/售后标签 | 严格隔离物流主题，避免产品问题混入 |
| **情感方向** | 全部（正向用于算满意度，负向用于定位问题） | 无 | LSS 需要正负向比例 |
| **平台范围** | Amazon + Zendesk + Trustpilot | Reddit/Meltwater | 物流评价集中在购买后平台 |
| **时间窗口** | 滑动 14 天 | — | 物流时效短，14 天足够覆盖完整履约周期 |
| **质量等级** | quality_tier IN ('A','B','C') | D | — |
| **特殊条件** | 区分 `country` + `carrier` | — | 不同国家/物流商的 LSS 不能混算 |

**SQL WHERE 片段**
```sql
WHERE dt.problem_type = '物流'
  AND vl.aipl_node IN ('P2','L1')
  AND vl.source_name IN ('amazon','zendesk','trustpilot')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '14 days'
  AND vl.quality_tier IN ('A','B','C')
```

> **关键说明**：物流 VOC 的 **AIPL 节点归属** 容易混淆——用户说"还没收到"可能在 P2（购买阶段），"收到了但包装破了"在 L1。两种都应纳入。同时需区分 **物流时效** vs **物流信息透明度** 两个子主题。

---

### S23 · 退换货痛苦加剧

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | RPI > 阈值 | P1 | 7 | 6 | 8 | 7 | **7.0** |
| 趋势 | RPI 连续 4 周上升 | P1 | 6 | 5 | 8 | 7 | **6.5** |
| 关联 | 退换货客服工单量增长 > 30% | P1 | 6 | 6 | 7 | 7 | **6.5** |

**叙事结构**
```
【1. 信号发现】
  退换货痛苦指数 RPI = {rpi_value}。
  退换货相关 VOC 共 {mentions} 次，负向占比 {negative_pct}%。
  其中 P0 权重标签 {p0_weighted_count} 次。

【2. 根因归因】
  Top-3 退换货痛点（含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, P0权重{p0_weight_1}, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}
    2. {tag_2} ({mentions_2}次, P0权重{p0_weight_2}, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}
    3. {tag_3} ({mentions_3}次, P0权重{p0_weight_3}, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}
  关联问题类型：{problem_types}

【2.5. 反直觉洞察】
  直觉认知：免费更换/快速退款 = 优质客服 = 用户满意。
  反直觉发现：
    - 频繁更换反而让用户形成"产品注定会坏"的预期
    - 用户直言："They are definitely losing tons of money by replacing
      the product. Terrible business model."
    - "客服好"不能抵消"产品差"的负面印象
  深层机制：
    - 在母婴品类，产品可靠性 > 售后服务
    - 频繁更换策略可能被视为"计划性报废"而非"优质服务"
    - 用户对"折腾"的容忍度极低（照顾婴儿本身已耗费大量精力）
  高后果信号：
    - 若 "replacement 后仍转向竞品" 的用户比例 > 30% →
      说明 replacement 策略正在失效，需立即评估产品根因

【3. 影响评估】
  退换货率：{return_rate}%
  客服处理时长：{avg_handling_time} 小时
  二次投诉率：{second_complaint_rate}%
  Replacement → 竞品迁移率：{replacement_to_competitor_rate}% ⚠️ 关键指标

【4. 行动建议】
  主责部门：全球客服中心（流程优化）+ 产品中心（根因解决）
  strategy_package：售后服务SOP包 + 一次解决提升包
  建议：
    - 短期：优化退换货流程，减少用户操作步骤（如预付费退货标签）
    - 短期：增加主动关怀触点（退换货后 3 天回访 + 7 天满意度追踪）
    - 中期：建立「一次解决率」指标，追踪 replacement 后用户是否再次投诉
    - 长期：将 top-3 退换货原因反馈给产品中心，推动设计改进
  预期指标变化（MAA 式）：
    - RPI：当前 {current_rpi} → 目标降至 {target_rpi}
    - 一次解决率：当前 {current_fcr}% → 目标提升至 {target_fcr}%
    - Replacement → 竞品迁移率：目标降至 < 15%

【5. 持续监控】
  监控指标：RPI + 退换货率 + 客服满意度 CSS + **一次解决率** + **Replacement→竞品迁移率**
  监控频率：每周
  预警阈值：RPI 连续 2 周上升 或 一次解决率 < 70%
```

**所需数据**
- 指标：`RPI` (CS-2)
- 标签：`theme ILIKE '%退换%'` + `aipl_node='L2'` 的客服相关标签
- 维度：渠道 / SKU / 时间

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | L2（售后）+ L3（复购/推荐） | A/I/P1/P2 | 退换货发生在售后阶段，但"退换后不再购买"在 L3 |
| **标签范围** | `theme ILIKE '%退换%'` OR `problem_type IN ('退换货','售后政策')` | 产品性能/物流/价格标签 | 聚焦退换货流程本身，排除"因产品质量差而退货"的产品问题 |
| **情感方向** | 负向为主 + 中性 | 纯正向 | 正向退换货评价（如"退货很方便"）反映流程好，但 RPI 关注痛点 |
| **平台范围** | Zendesk + Amazon + Trustpilot | Reddit/Meltwater | 退换货是购买后行为，评价集中在售后/购买平台 |
| **时间窗口** | 滑动 30 天 | — | 退换货周期通常 2-4 周 |
| **质量等级** | quality_tier IN ('A','B','C') | D | — |
| **特殊条件** | 区分"流程问题"vs"产品问题导致的退换" | — | 若退换因产品缺陷，应归因 S14 而非 S23 |

**SQL WHERE 片段**
```sql
WHERE (dt.theme ILIKE '%退换%' OR dt.problem_type IN ('退换货','售后政策'))
  AND vl.aipl_node = 'L2'
  AND vl.source_name IN ('zendesk','amazon','trustpilot')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND vl.quality_tier IN ('A','B','C')
  AND dt.problem_type NOT IN ('产品性能','产品设计','质量故障')
```

> **关键说明**：RPI 的核心边界是区分 **"退换货流程痛苦"**（应归因客服/流程）和 **"因产品问题而退换"**（应归因产品）。后者不应进入 RPI 计算，否则产品问题会淹没流程问题信号。

---

### S28 · 新手妈妈流失加剧

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | NMPI > 阈值 | P1 | 7 | 6 | 8 | 7 | **7.0** |
| 趋势 | NMPI 连续 3 周上升 | P1 | 6 | 6 | 8 | 7 | **6.8** |
| 关联 | 新手妈妈 persona 占比下降 > 20% | P2 | 5 | 5 | 7 | 6 | **5.8** |

**叙事结构**
```
【1. 信号发现】
  新手妈妈痛点 NMPI = {nmpi_value}。
  新手妈妈 persona 相关 VOC 共 {mentions} 次，P0 负向 {p0_negative} 次。
  环比：{delta}pp。
  关联标签：{top_tags}

【2. 根因归因】
  Top-3 新手痛点（含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, P0权重{p0_weight_1}, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}
    2. {tag_2} ({mentions_2}次, P0权重{p0_weight_2}, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}
    3. {tag_3} ({mentions_3}次, P0权重{p0_weight_3}, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}
  关联 story_lines：新手上手断点 / 使用负担

【2.5. 反直觉洞察】
  直觉认知：新手妈妈流失是因为产品太难用，需要更简化的入门教程。
  反直觉发现：
    - 大量新手妈妈并非"不会用"，而是"不敢用"——对产品缺乏信任
    - 二手平台出现大量"仅拆封/使用1次"的转卖，说明适配问题在
      购买前就已存在，而非使用中才暴露
    - 用户留言："Bought it thinking it would be a lifesaver, but
      couldn't figure out the right size. Too scared to try."
  深层机制：
    - 母婴品类的特殊性：新手妈妈对产品安全性的敏感度远高于便利需求
    - 购买前信息缺失（如喇叭罩尺寸适配）导致"买后用不了" → 转卖
    - 转卖行为在公共平台形成"这个产品对新手不友好"的负面传播
  高后果信号：
    - 若 "转卖原因=尺寸不适配/不会组装" 的占比 > 40% →
      说明产品信息传递有结构性缺陷，非教程可解决
    - 若转卖帖中出现竞品推荐 → 说明新手妈妈正在流失到竞品

【3. 影响评估】
  新手妈妈占新客比例：{newbie_share}%
  30 天留存率：{retention_30d}%
  二手平台转卖量（关联 SPU）：{resale_count} 件 ⚠️ 新增指标
  转卖原因分布：{resale_reason_breakdown}
  关联 business_impact：复购率 / 口碑推荐 / 品牌信任

【4. 行动建议】
  主责部门：产品中心 + 电商运营部
  strategy_package：核心体验改良包 + 信息架构优化包
  建议：
    - 立即：电商详情页增加"新手妈妈尺码指南"交互工具
    - 短期：推出"新手安心包"（含试用装+视频教程+7天1v1咨询）
    - 中期：优化新用户引导流程，首用前主动推送"尺寸自测"工具
    - 长期：针对 Top-3 痛点优化产品设计（如傻瓜式组装、防误操作）
  预期指标变化（MAA 式）：
    - NMPI：当前 {current_nmpi} → 目标降至 {target_nmpi}
    - 30天留存率：当前 {current_retention}% → 目标提升至 {target_retention}%
    - 二手转卖率：目标降至 < 5%

【5. 持续监控】
  监控指标：NMPI + 新手妈妈 persona 渗透率 + 30天留存率 + **二手平台转卖量**
  监控频率：每月
  预警阈值：NMPI 连续 2 周上升 或 二手转卖量环比增长 > 50%
```

**所需数据**
- 指标：`NMPI` (CL-3)
- 标签：`default_priority='P0' AND sentiment='负向'` 的 9 标签 + `persona='新手妈妈'`
- 维度：产品 / persona / 时间

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | A→I→P1→L1 | P2/L2/L3 | 新手妈妈痛点主要在认知→决策→首次使用阶段 |
| **标签范围** | `persona='新手妈妈'` + `default_priority='P0'` + `sentiment='负向'` | 非 P0 标签、非新手妈妈标签 | 只看新手妈妈的核心痛点（P0 级） |
| **情感方向** | 负向 | 正向/中性 | NMPI 是痛点指数，只看负向 |
| **平台范围** | Amazon + Reddit + Facebook | Zendesk/Trustpilot | 新手评价集中在购买前社区和购买后 Amazon |
| **时间窗口** | 滑动 30 天 | — | 新手妈妈的"新手期"通常 30 天内 |
| **质量等级** | quality_tier IN ('A','B') | C/D | 新手痛点需要高质量语义判断 |
| **特殊条件** | persona 标签由规则匹配（非 LLM） | — | 55 个原子画像规则已校准，作为单源真值 |

**SQL WHERE 片段**
```sql
WHERE vl.persona_tags @> '新手妈妈'::jsonb
  AND dt.default_priority = 'P0'
  AND dt.sentiment = '负向'
  AND vl.aipl_node IN ('A','I','P1','L1')
  AND vl.source_name IN ('amazon','reddit','facebook')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND vl.quality_tier IN ('A','B')
```

> **关键说明**：新手妈妈的 **persona 识别** 是 NMPI 的核心边界。v6.2 字典中 persona 标签由 55 个原子规则匹配（见 `persona_tags_55.json`），不依赖 LLM 打标。这意味着即使 voc_tags 为空，NMPI 的部分组件仍可计算。

---

### S30 · P0 触发率飙升

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | P0R > 0.5% | P0 | 9 | 8 | 9 | 9 | **8.8** |
| 趋势 | P0R 周环比增长 > 100% | P0 | 9 | 7 | 9 | 8 | **8.3** |
| 关联 | 同一 SPU 出现 ≥2 个 P0 标签 | P0 | 8 | 6 | 9 | 8 | **7.8** |
| 异常 | 安全类 P0 标签（如 electrocution）首次出现 | P0 | 10 | 5 | 9 | 7 | **7.8** |

**叙事结构**
```
【1. 信号发现】
  P0 触发率 P0R = {p0r_value}%（P0 标签帖 / 总帖）。
  P0 标签总提及 {p0_mentions} 次，涉及 {affected_spus} 个 SPU。
  环比：{delta}pp。
  安全类 P0 标签占比：{safety_pct}% ⚠️ 若 > 0 需立即升级

【2. 根因归因】
  P0 标签详情（共 13 个，含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}
    2. {tag_2} ({mentions_2}次, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}
    3. {tag_3} ({mentions_3}次, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}
  集中爆发的 SPU：{spu_concentration}
  关联问题类型：{problem_types}
  高频失效模式：{failure_mode_breakdown}

【2.5. 反直觉洞察】
  直觉认知：P0 标签爆发 = 产品质量差，需要加强质检。
  反直觉发现：
    - 大量 P0 问题与用户清洁方式相关（如 moisture leakage → shorting）
    - 用户留言："opened it up... moisture everywhere... shorting the board"
      — 这不是生产缺陷，而是防水设计 + 清洁指引不足
    - 低频高后果问题（如 cracking、electrical short）出现的绝对次数可能
      不多，但业务严重度远高于高频低后果问题（如 suction weak）
  深层机制：
    - 可穿戴吸奶器的核心失效模式与"液体暴露场景"高度相关
    - 用户清洁行为往往与说明书不一致（或说明书本身不够清晰）
    - 在社媒平台，一个带拆解图的 P0 投诉比 100 条"吸力弱"的杀伤力更大
  高后果信号：
    - 若出现 "electrocution" / "shorted" / "burned smell" 等关键词 →
      24 小时内启动安全评估，涉及法律风险
    - 若 Reddit/社媒出现拆机级别工程分析 → 说明问题已引起技术型用户关注，
      可能形成系统性负面叙事

【3. 影响评估】
  涉及退货/召回风险：{recall_risk}
  受影响订单量估算：{affected_orders}
  关联 business_impact：安全召回风险 / 品牌信任 / 法律风险
  法务合规风险：{compliance_risk}
  竞品迁移信号：{competitor_migration_mentions} 次 ⚠️ 关键指标

【4. 行动建议】
  主责部门：品质管理中心（牵头）+ 产品中心（设计改进）+ 法务合规部（法律评估）
  strategy_package：质量风险防控包 + 合规背书强化包
  优先级：P0 — 24 小时内启动
  建议：
    - 立即：质量部介入，确认是否为系统性问题
    - 立即：若涉及安全类标签，法务部同步评估召回风险
    - 短期：受影响批次隔离检测 + 暂停相关批次发货
    - 中期：供应链/工艺根因分析 + 防水设计/密封件专项测试
    - 长期：建立 P0 标签预警自动化（实时钉钉/飞书告警）
  预期指标变化（MAA 式）：
    - P0R：当前 {current_p0r}% → 目标降至 {target_p0r}%
    - 安全类 P0 标签：目标归零
    - 竞品迁移率：目标降至 < 10%

【5. 持续监控】
  监控指标：P0R + 退货率 + 安全相关标签提及量 + **竞品迁移信号**
  监控频率：每日
  预警阈值：任何安全类 P0 标签出现即触发 P0 响应
```

**所需数据**
- 指标：`P0R` (OQ-1)
- 标签：`default_priority='P0'` 的 13 标签
- 维度：SPU / 时间

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | 全节点 A→L3 | 无 | P0 问题可能出现在任何阶段（如广告误导属 A 节点） |
| **标签范围** | `default_priority='P0'` 的 13 标签 | 非 P0 标签 | 严格只看 P0 级标签 |
| **情感方向** | 负向为主 + 中性（中性安全描述） | 纯正向 | 正向不反映 P0 问题 |
| **平台范围** | 全 7 信源 | 无 | P0 问题首发可能在任何平台 |
| **时间窗口** | 滑动 7 天（日监控）/ 30 天（周汇总） | — | P0 需要每日监控 |
| **质量等级** | quality_tier IN ('A','B','C') | D | P0 不能因质量过滤漏掉 |
| **特殊条件** | 安全类 P0 标签出现即 P0 响应，无需阈值 | — | 安全问题是零容忍 |

**SQL WHERE 片段**
```sql
WHERE dt.default_priority = 'P0'
  AND vl.review_date >= CURRENT_DATE - INTERVAL '7 days'
  AND vl.quality_tier IN ('A','B','C')
```

> **关键说明**：P0R 的分母是 **总帖数**（非 P0 帖数）。这意味着 P0R 对总 VOC 量敏感——总帖下降时即使 P0 帖不变，P0R 也会上升。需同时监控 **P0 绝对提及量** 作为交叉验证。

---

## 四、反直觉类故事线（新增 S34-S37）

> 以下故事线并非由单一指标触发，而是由**跨指标、跨平台的低频高后果信号**组合触发。它们揭示的是隐藏在数据表面之下的结构性风险，往往与业务直觉相反。

### S34 · 竞品迁移链断裂

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 复合信号 | 竞品推荐提及量增长 > 30% 且 本品牌复购信号下降 | P1 | 6 | 7 | 8 | 7 | **7.0** |
| 复合信号 | Reddit 评论区出现 "从 X 换到 Y" 的迁移叙事链 | P1 | 6 | 6 | 7 | 7 | **6.5** |
| 趋势 | 连续 4 周出现竞品推荐 + 本品牌负向叠加 | P0 | 7 | 7 | 7 | 7 | **7.0** |

**叙事结构**
```
【1. 信号发现】
  竞品推荐提及量 = {comp_mentions} 次，环比增长 {delta}%.
  迁移叙事链识别：{migration_chains}
  本品牌复购信号提及 = {repurchase_mentions} 次（环比 {repurchase_delta}%）.

【2. 根因归因】
  Top-3 迁移驱动标签：
    1. {tag_1} — 被提及为"离开原因"
    2. {tag_2} — 被提及为"选择竞品原因"
    3. {tag_3} — 被提及为"对比落差"
  消费者原话：
    "{quote_1}" — {source_1}
    "{quote_2}" — {source_2}

【2.5. 反直觉洞察】
  直觉认知：用户离开是因为我们比竞品差。
  反直觉发现：
    - 大量迁移并非"我们差"，而是"竞品形成了集体叙事"
    - 用户可能从未同时用过两个品牌，迁移决策基于社区共识而非真实对比
    - "从 Momcozy → Eufy"的迁移链一旦形成，会自我强化
  深层机制：
    - 母婴社区的信任机制：口碑 > 参数 > 品牌
    - 一个高赞的竞品推荐帖可以影响数百人的购买决策
    - 迁移链的断裂需要"打断叙事"而非"改进产品"
  高后果信号：
    - 若迁移链中出现 "本来要买 X 后来买了 Y" 的转化信号 →
      说明迁移叙事正在影响购买决策漏斗的顶层

【3. 影响评估】
  受影响潜在新客：{affected_prospects}
  竞品迁移率：{migration_rate}%
  品牌信任度变化：{trust_delta}

【4. 行动建议】
  主责部门：品牌市场中心 + 产品中心
  strategy_package：品牌认知校准包 + 竞品差异化包
  建议：
    - 短期：在社媒平台主动回应迁移叙事（非辩护式，而是"信息补充"式）
    - 短期：识别迁移链中的关键节点用户（高赞评论作者），进行 1v1 沟通
    - 中期：制作"对比实测"内容，用真实数据打破迁移叙事
    - 长期：建立品牌倡导者计划，让现有用户在社区中发声
  预期指标变化：
    - 竞品推荐/本品牌负向叠加率：目标降至 < 15%
    - 迁移叙事链增长：目标归零或负增长

【5. 持续监控】
  监控指标：竞品推荐量 + 迁移叙事链数量 + 复购信号量
  监控频率：每周
```

**所需数据**
- 标签：`competitor_mentioned` + `sentiment` + `migration_intent`
- 维度：平台 / 时间 / 竞品品牌

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | I→P1→L1→L3 | A/P2 | 竞品比较和迁移发生在决策→使用→忠诚阶段 |
| **标签范围** | `competitor_mentioned IS NOT NULL` | 无竞品提及的 VOC | 只看竞品相关对话 |
| **情感方向** | 全部（竞品正向+本品牌负向 = 迁移信号） | 无 | CEG 需要双向情感对比 |
| **平台范围** | Reddit + Amazon + Facebook | Zendesk/Trustpilot | 竞品讨论集中在社区和购买平台 |
| **时间窗口** | 滑动 30 天 | — | 迁移叙事需要时间积累 |
| **质量等级** | quality_tier IN ('A','B') | C/D | 竞品讨论需要高质量语义 |
| **特殊条件** | 需识别 `migration_intent`（迁移意图强度） | — | 仅提及竞品 ≠ 迁移意图 |

**SQL WHERE 片段**
```sql
WHERE vl.competitor_mentioned IS NOT NULL
  AND vl.aipl_node IN ('I','P1','L1','L3')
  AND vl.source_name IN ('reddit','amazon','facebook')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND vl.quality_tier IN ('A','B')
```

> **关键说明**：竞品情感差距 CEG 的核心难点是 **品牌归属判定**。LLM 需先判定帖子讨论的是 Momcozy 还是竞品，再计算各自的情感得分。若品牌归属错误，CEG 方向可能完全相反。

---

### S35 · 二手转让原因映射

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | 二手平台关联 SPU 转让量 > 阈值 | P2 | 5 | 5 | 7 | 6 | **5.8** |
| 关联 | 转让原因中产品适配类 > 40% | P1 | 6 | 5 | 8 | 7 | **6.5** |
| 趋势 | 二手转让量连续 4 周增长 > 50% | P1 | 6 | 6 | 7 | 6 | **6.3** |

**叙事结构**
```
【1. 信号发现】
  二手平台关联 SPU 转让量 = {resale_count} 件/周。
  转让原因分布：{resale_reason_breakdown}.
  转让价格折扣中位数：{discount_median}%.

【2. 根因归因】
  Top-3 转让原因：
    1. {reason_1} — {count_1} 件 ({pct_1}%)
    2. {reason_2} — {count_2} 件 ({pct_2}%)
    3. {reason_3} — {count_3} 件 ({pct_3}%)

【2.5. 反直觉洞察】
  直觉认知：二手转让 = 产品不好 → 改进产品。
  反直觉发现：
    - 大量转让原因是"买错了"而非"不好用"——尺码不适配、功能超预期
    - 转让帖中的"仅拆封/使用1次"说明问题在购买决策阶段就已存在
    - 用户在转让时往往会推荐"更好的选择"，形成二次竞品传播
  深层机制：
    - 购买前信息不足 → 期望错位 → 快速流失 → 二手转让 → 负面传播
    - 这个链条的损失不仅是"少了一个用户"，而是"多了一个负面传播节点"
  高后果信号：
    - 若转让帖中出现"推荐竞品" → 每一个转让帖都是一个竞品广告
    - 若转让原因集中在"尺寸""适配" → 说明详情页的信息架构有缺陷

【3. 影响评估】
  潜在流失用户：{potential_churn}
  负面传播节点数：{negative_nodes}
  Revenue at risk：{revenue_at_risk}

【4. 行动建议】
  主责部门：电商运营部 + 产品中心
  strategy_package：信息架构优化包 + 核心体验改良包
  建议：
    - 立即：详情页增加"适用性自测"工具
    - 短期：推出"新手试用装"降低首次购买决策门槛
    - 中期：优化退货流程，将"二手转让"转化为"官方回收/以旧换新"
    - 长期：建立用户生命周期管理，在"购买后7天"主动推送使用指导

【5. 持续监控】
  监控指标：二手转让量 + 转让原因分布 + 转让帖竞品提及率
  监控频率：每月
```

**所需数据**
- 外部数据：二手平台（eBay/Facebook Marketplace/闲鱼等）抓取数据
- 标签：`fit_issue` + `size_related` + `usage_difficulty`

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | L1→L2→L3 | A/I/P1/P2 | 二手转让发生在使用→售后阶段 |
| **标签范围** | 外部二手数据 + `fit_issue`/`size_related`/`usage_difficulty` | 其他内部 VOC 标签 | 核心输入是外部二手平台数据 |
| **情感方向** | 全部（二手帖通常中性描述转让原因） | 无 | 转让原因本身不完全是情感表达 |
| **平台范围** | 外部：eBay/Facebook Marketplace/闲鱼/Poshmark | 内部 7 信源 | 二手转让数据不在内部 VOC 中 |
| **时间窗口** | 滑动 30 天 | — | 二手流转速度快 |
| **质量等级** | 外部数据不经过 quality_tier，需人工标注 | — | 二手数据需要独立的结构化标注 |
| **特殊条件** | 需识别转让原因（适配/质量/功能不符/换新款） | — | 转让原因分类是 S35 的核心 |

**SQL WHERE 片段**
```sql
-- 外部数据（非内部 VOC 表）
SELECT * FROM external_resale_data
WHERE listing_date >= CURRENT_DATE - INTERVAL '30 days'
  AND brand IN ('Momcozy', 'Momcozy M5', 'Momcozy M6', ...)

-- 内部 VOC 辅助验证
WHERE dt.tag_id IN ('fit_issue','size_related','usage_difficulty')
  AND vl.aipl_node IN ('L1','L2')
```

> **关键说明**：S35 是**唯一依赖外部数据源**的故事线。二手平台数据需通过 RPA/爬虫获取，然后用 LLM 标注转让原因。内部 VOC 中的 `fit_issue` 等标签可作为交叉验证。

---

### S36 · 用户 DIY 维修信号

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | Reddit/社区出现 "自行拆解/维修" 内容 > 3 条/周 | P1 | 6 | 5 | 8 | 7 | **6.5** |
| 信号强度 | DIY 维修内容获赞 > 50 或引发跟帖讨论 | P1 | 5 | 5 | 7 | 7 | **6.0** |
| 关联 | DIY 维修内容与 P0 标签问题类型一致 | P0 | 8 | 5 | 9 | 7 | **7.3** |

**叙事结构**
```
【1. 信号发现】
  DIY 维修相关内容 = {diy_count} 条/周。
  最高赞 DIY 内容：{top_diy_post}（{upvotes} 赞）.
  涉及的 SPU/问题类型：{affected_spus}

【2. 根因归因】
  DIY 维修主题分布：
    1. {theme_1} — {count_1} 条
    2. {theme_2} — {count_2} 条
    3. {theme_3} — {count_3} 条
  消费者原话：
    "{quote_1}" — {source_1}

【2.5. 反直觉洞察】
  直觉认知：用户自己修好了 = 问题解决了 = 不用管。
  反直觉发现：
    - 用户主动 DIY 维修说明：①产品存在系统性缺陷 ②官方售后渠道不畅
    - 一篇带拆解图的 DIY 维修帖，其工程分析价值远超 100 条普通差评
    - "用户替品牌补设计"是需求外溢的强烈信号——市场在呼唤"可维修"产品
  深层机制：
    - 母婴用户对"折腾"容忍度极低，愿意 DIY 说明问题已严重到无法容忍
    - DIY 维修帖在社区中获得高赞 → 说明该问题具有普遍性
    - 品牌失去了从"售后维修"中获取产品改进信息的机会
  高后果信号：
    - 若 DIY 维修内容涉及安全改造（如防水处理、电路修改）→
      说明产品设计存在安全盲区，可能引发更严重后果
    - 若 DIY 方案被大量复制 → 品牌正在失去对产品质量叙事的主导权

【3. 影响评估】
  受影响用户规模：{affected_users}
  品牌信任损失：{trust_impact}
  竞品迁移信号：{competitor_mentions} 次

【4. 行动建议】
  主责部门：产品中心（研发）+ 全球客服中心
  strategy_package：质量风险防控包 + 核心体验改良包
  建议：
    - 立即：将 DIY 维修帖中的技术分析纳入产品改进输入
    - 短期：联系 DIY 内容作者，邀请参与产品改进反馈计划
    - 中期：评估推出"官方维修套件"或"模块化替换件"的可行性
    - 长期：建立"用户创新实验室"，将高级用户的 DIY 方案产品化

【5. 持续监控】
  监控指标：DIY 维修内容量 + 获赞数 + 安全改造提及量
  监控频率：每周
```

**所需数据**
- 标签：`repair` + `DIY` + `opened_up` + `fixed_myself`
- 维度：平台 / SPU / 问题类型

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | L1（产品使用）+ L2（售后） | A/I/P1/P2 | DIY 维修发生在使用和售后阶段 |
| **标签范围** | 关键词匹配：`repair`, `DIY`, `opened_up`, `fixed_myself`, `took apart` | 无关键词的帖子 | 需用关键词+LLM双重识别 |
| **情感方向** | 全部（DIY 帖可能中性描述维修过程） | 无 | 情感不是核心，维修行为本身才是信号 |
| **平台范围** | Reddit + Facebook Groups | Amazon/Trustpilot | DIY 讨论集中在社区 |
| **时间窗口** | 滑动 30 天 | — | — |
| **质量等级** | quality_tier IN ('A','B','C') | D | — |
| **特殊条件** | 需识别是否含图片/拆解步骤（证据强度 ≥ ★★★） | 纯文字描述（★） | 带拆解图的 DIY 帖工程价值更高 |

**SQL WHERE 片段**
```sql
WHERE (vl.content_en ILIKE '%repair%' 
       OR vl.content_en ILIKE '%opened it up%'
       OR vl.content_en ILIKE '%fixed%myself%'
       OR vl.content_en ILIKE '%DIY%')
  AND vl.source_name IN ('reddit','facebook')
  AND vl.aipl_node IN ('L1','L2')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND vl.quality_tier IN ('A','B','C')
```

> **关键说明**：DIY 维修信号的核心价值不在情感分析，而在 **失效模式提取**。一篇拆机帖中提到的 "moisture shorting the board" 比 100 条 "product broke" 更有工程价值。需用 LLM 从 DIY 内容中提取具体失效模式。

---

### S37 · 价格-期望错配陷阱

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 复合信号 | 价格负向标签增长 > 30% 且 好评中"性价比"提及下降 | P1 | 6 | 7 | 8 | 7 | **7.0** |
| 关联 | "不值这个价"类 VOC 占比 > 15% | P1 | 6 | 6 | 8 | 7 | **6.8** |
| 趋势 | 价格-质量期望差连续 4 周扩大 | P0 | 7 | 7 | 7 | 7 | **7.0** |

**叙事结构**
```
【1. 信号发现】
  价格负向标签提及 = {price_neg_mentions} 次，环比 {delta}%.
  "不值这个价"类 VOC 占比 = {value_mismatch_pct}%.
  好评中"性价比"提及量 = {value_mentions} 次（环比 {value_delta}%）.

【2. 根因归因】
  Top-3 价格-期望错配类型：
    1. {type_1} — "买了贵的但功能和便宜的一样" — {count_1} 次
    2. {type_2} — "便宜但质量太差" — {count_2} 次
    3. {type_3} — "促销价买的感觉值，正价买的不值" — {count_3} 次
  消费者原话：
    "{quote_1}" — {source_1}
    "{quote_2}" — {source_2}

【2.5. 反直觉洞察】
  直觉认知：用户嫌贵 = 定价太高 = 降价促销。
  反直觉发现：
    - 大量"不值这个价"并非价格本身问题，而是"价值感知传递失败"
    - 用户可能完全不了解产品的高端功能，因为详情页没有有效传达
    - "促销价感觉值"说明用户有支付能力，问题在"价值锚定"而非" affordability"
  深层机制：
    - 价格感知 = 实际体验 - 期望值
    - 期望值的形成主要来自：详情页描述、KOL 推荐、社媒口碑
    - 当期望值 > 实际体验时，即使产品不差，也会产生"不值"的感觉
    - 降价促销会进一步压低价格锚点，形成"越降越不值"的恶性循环
  高后果信号：
    - 若 "正价购买" 用户的不满率显著高于 "促销购买" →
      说明价格锚点已被促销破坏，品牌价值正在流失
    - 若竞品在相同价位段获得更高"性价比"评价 →
      说明问题不在价格，而在价值传达

【3. 影响评估】
  受影响 SKU 数：{affected_skus}
  正价销售转化率：{full_price_conversion}%
  品牌价值感指数：{brand_value_index}

【4. 行动建议】
  主责部门：电商运营部 + 品牌市场中心
  strategy_package：价值表达优化包 + 核心卖点校准包
  建议：
    - 短期：重新梳理详情页价值传达逻辑，突出"为什么值这个价"
    - 短期：收集"觉得值"的用户原话，作为社会证明放在详情页
    - 中期：调整促销策略，避免过度依赖折扣（考虑赠品/服务增值）
    - 长期：建立"价值感知"监控指标，追踪用户 price-value match 变化
  预期指标变化：
    - "不值这个价"类 VOC 占比：目标降至 < 8%
    - 正价销售转化率：目标提升 {target_pp}%

【5. 持续监控】
  监控指标：价格负向标签量 + "性价比"好评提及量 + 正价转化率
  监控频率：每月
```

**所需数据**
- 标签：`price_negative` + `value_for_money` + `overpriced`
- 维度：价格段 / SKU / 购买渠道（正价 vs 促销）

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | P1→P2→L1 | A/I/L2/L3 | 价格-期望错配发生在决策→使用阶段 |
| **标签范围** | `price_negative` + `value_for_money` + `overpriced` + `worth the price` | 物流/客服/产品性能 | 聚焦价格-价值感知 |
| **情感方向** | 负向 + 中性 | 纯正向 | 正向"性价比"评价用于对比 |
| **平台范围** | Amazon + Trustpilot + Reddit | Zendesk | 价格评价集中在购买决策和使用后平台 |
| **时间窗口** | 滑动 30 天 | — | 价格感知变化快 |
| **质量等级** | quality_tier IN ('A','B') | C/D | 价格语义判断需要高质量文本 |
| **特殊条件** | 区分 `verified_purchase=true/false` + 正价/促销渠道 | — | 未购买用户和促销用户的价格评价需降权 |

**SQL WHERE 片段**
```sql
WHERE dt.tag_id IN ('price_negative','value_for_money','overpriced')
  AND vl.aipl_node IN ('P1','P2','L1')
  AND vl.source_name IN ('amazon','trustpilot','reddit')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND vl.quality_tier IN ('A','B')
```

> **关键说明**：S37 需要 **双向对比**——不仅看"不值这个价"的负向，还要看"性价比很高"的正向。当正向比例下降+负向比例上升时，才是真正的价格-期望错配（而非单纯的价格抱怨）。

---

### S04 · 竞品情感失守

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | CEG < -0.2 | P1 | 6 | 7 | 8 | 7 | **7.0** |
| 趋势 | CEG 连续 4 周下降 | P1 | 6 | 6 | 8 | 7 | **6.8** |
| 关联 | 竞品推荐量增长 > 30% 且本品牌贬损量同步增长 | P0 | 7 | 8 | 7 | 7 | **7.3** |

**叙事结构**
```
【1. 信号发现】
  竞品情感差距 CEG = {ceg_value}（本品牌 - 竞品情感均值）。
  竞品推荐提及量 = {comp_recommend} 次，环比增长 {delta}%。
  本品牌贬损提及量 = {brand_detract} 次，环比增长 {brand_delta}%。
  按平台拆分：{platform_breakdown}。
  按竞品拆分：{competitor_breakdown}。

【2. 根因归因】
  Top-3 竞品胜出标签（含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}
    2. {tag_2} ({mentions_2}次, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}
    3. {tag_3} ({mentions_3}次, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}
  本品牌主要劣势维度：{weakness_dimensions}
  竞品主要优势维度：{competitor_strengths}

【2.5. 反直觉洞察】
  直觉认知：竞品推荐多 = 竞品产品更好 = 我们要追赶功能。
  反直觉发现：
    - 大量竞品推荐并非基于真实对比，而是基于"社区共识"——
      用户可能从未同时用过两个品牌
    - "Eufy 更可靠"这类评价往往没有具体证据，但传播力极强
    - 用户留言："Everyone in my pumping group says Eufy is better,
      so I just went with that."
    - 竞品胜出不一定靠技术参数，而是靠"集体叙事"
  深层机制：
    - 母婴社区的信任机制：熟人推荐 > 口碑 > 参数 > 品牌
    - 一个高赞的竞品推荐帖可以影响数百人的购买决策
    - 竞品被推荐的原因往往不是"功能更多"，而是"问题更少"
    - 用户从"规避风险"角度做决策，而非"追求最优"
  高后果信号：
    - 若竞品推荐帖中出现"从 Momcozy 换过来的"迁移叙事 →
      说明竞品正在侵蚀我们的核心用户群
    - 若竞品推荐集中在某个特定场景（如"夜间使用""背奶"）→
      说明我们在该场景的产品力存在结构性差距

【3. 影响评估】
  受影响潜在新客：{affected_prospects}
  品牌信任度变化：{trust_delta}
  竞品迁移率：{migration_rate}%
  Revenue at risk：${revenue_at_risk}

【4. 行动建议】
  主责部门：品牌市场中心 + 产品中心
  strategy_package：品牌认知校准包 + 竞品差异化包
  建议：
    - 立即：识别竞品推荐的关键节点用户（高赞评论作者），进行 1v1 沟通
    - 短期：制作"对比实测"内容，用真实数据打破"社区共识"叙事
    - 短期：在社媒平台主动回应迁移叙事（非辩护式，而是"信息补充"式）
    - 中期：建立品牌倡导者计划，让现有满意用户在社区中发声
    - 长期：针对竞品集中推荐的场景进行产品力专项提升
  预期指标变化（MAA 式）：
    - CEG：当前 {current_ceg} → 目标提升至 {target_ceg}（>-0.1）
    - 竞品推荐量：目标下降 ≥30%
    - 品牌贬损量：目标下降 ≥40%

【5. 持续监控】
  监控指标：CEG + 竞品推荐量 + 本品牌贬损量 + 迁移叙事链数量
  监控频率：每周
  预警阈值：CEG < -0.15 或 竞品推荐量周环比增长 > 20%
```

**所需数据**
- 指标：`CEG` (BM-4)
- 标签：`competitor_mentioned` + `recommendation` + `migration_intent`
- 维度：竞品品牌 / 平台 / 时间

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | I→P1→L1→L3 | A/P2 | 竞品比较和迁移发生在决策→使用→忠诚阶段 |
| **标签范围** | `competitor_mentioned IS NOT NULL` | 无竞品提及的 VOC | 只看竞品相关对话 |
| **情感方向** | 全部（竞品正向+本品牌负向 = 迁移信号） | 无 | CEG 需要双向情感对比 |
| **平台范围** | Reddit + Amazon + Facebook | Zendesk/Trustpilot | 竞品讨论集中在社区和购买平台 |
| **时间窗口** | 滑动 30 天 | — | 迁移叙事需要时间积累 |
| **质量等级** | quality_tier IN ('A','B') | C/D | 竞品讨论需要高质量语义 |
| **特殊条件** | 需识别 `migration_intent`（迁移意图强度） | — | 仅提及竞品 ≠ 迁移意图 |

**SQL WHERE 片段**
```sql
WHERE vl.competitor_mentioned IS NOT NULL
  AND vl.aipl_node IN ('I','P1','L1','L3')
  AND vl.source_name IN ('reddit','amazon','facebook')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '30 days'
  AND vl.quality_tier IN ('A','B')
```

> **关键说明**：竞品情感差距 CEG 的核心难点是 **品牌归属判定**。LLM 需先判定帖子讨论的是 Momcozy 还是竞品，再计算各自的情感得分。若品牌归属错误，CEG 方向可能完全相反。

---

### S22 · 客服体验恶化

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | CSS < 50% | P1 | 6 | 7 | 9 | 7 | **7.3** |
| 环比 | CSS 周环比下降 > 15pp | P1 | 6 | 6 | 9 | 7 | **7.0** |
| 关联 | 客服工单量增长 > 30% 且一次解决率 < 70% | P0 | 7 | 7 | 8 | 7 | **7.3** |

**叙事结构**
```
【1. 信号发现】
  客服满意度 CSS 本周为 {css_value}%，环比 {delta}pp。
  客服相关 VOC 共 {mentions} 次，负向 {negative} 次（占比 {neg_pct}%）。
  一次解决率 FCR = {fcr}%。
  按问题类型拆分：{issue_breakdown}。

【2. 根因归因】
  Top-3 客服负向标签（含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}
    2. {tag_2} ({mentions_2}次, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}
    3. {tag_3} ({mentions_3}次, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}
  关联 story_lines：售后闭环能力 / 信任恢复

【2.5. 反直觉洞察】
  直觉认知：客服满意度低 = 客服态度差 = 加强客服培训。
  反直觉发现：
    - 大量客服投诉的根源不是"客服态度"，而是"客服没有权力解决问题"
    - 用户留言："The agent was nice but couldn't do anything.
      Had to escalate 3 times."
    - 客服满意度与产品问题严重度负相关——产品问题越严重，
      用户对客服的期望越高，越难满足
    - 一次解决率低的真正原因往往是"流程复杂"而非"能力不足"
  深层机制：
    - 客服体验 = 态度 × 能力 × 授权
    - 当授权为 0 时，态度再好也无法解决问题
    - 母婴用户对"折腾"容忍度极低，多次转接/升级会指数级放大不满
    - 客服满意度实际上是产品问题的"滞后指标"
  高后果信号：
    - 若 "客服态度好但解决不了问题" 类投诉占比 > 40% →
      问题在流程和授权，而非客服培训
    - 若同一用户因同一问题联系客服 ≥2 次 →
      说明一次解决机制失效，需立即排查根因

【3. 影响评估】
  客服工单总量：{total_tickets}
  每单平均处理成本：${cost_per_ticket}
  重复投诉率：{repeat_rate}%
  关联 business_impact：客服成本 / 用户流失 / 品牌信任
  Revenue at risk：${revenue_at_risk}

【4. 行动建议】
  主责部门：全球客服中心 + 产品中心（根因解决）
  strategy_package：一次解决提升包 + 售后服务SOP包
  建议：
    - 立即：排查"客服无权解决"类投诉的 TOP-3 场景，赋予客服临时处置权
    - 短期：优化升级流程，减少用户重复描述问题的次数
    - 短期：建立"同一问题二次投诉"自动预警机制
    - 中期：建立客服-产品直通机制，客服可直接提交产品改进建议
    - 长期：将一次解决率纳入客服核心 KPI（权重 ≥30%）
  预期指标变化（MAA 式）：
    - CSS：当前 {current_css}% → 目标提升至 {target_css}%（>70%）
    - 一次解决率 FCR：当前 {current_fcr}% → 目标提升至 {target_fcr}%（>80%）
    - 重复投诉率：目标降至 < 15%

【5. 持续监控】
  监控指标：CSS + FCR + 重复投诉率 + **客服授权不足类投诉占比**
  监控频率：每周
  预警阈值：CSS < 55% 或 FCR < 75% 或 重复投诉率 > 20%
```

**所需数据**
- 指标：`CSS` (CS-1)
- 标签：客服相关 L2 标签
- 维度：客服渠道 / 问题类型 / 处理时长

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | L2（售后） | A/I/P1/P2/L1/L3 | 客服只发生在售后阶段 |
| **标签范围** | `problem_type='客服'` + `aipl_node='L2'` 的客服主题标签 | 产品/物流/价格标签 | 严格隔离客服主题 |
| **情感方向** | 全部（CSS 需要正负向比例） | 无 | 客服满意度需要全量情感 |
| **平台范围** | Zendesk + Amazon + Trustpilot | Reddit/Meltwater | 客服评价集中在售后/购买平台 |
| **时间窗口** | 滑动 14 天 | — | 客服响应周期短 |
| **质量等级** | quality_tier IN ('A','B','C') | D | — |
| **特殊条件** | 区分"客服态度"vs"客服能力"vs"客服授权" | — | 三者根因不同，需分别统计 |

**SQL WHERE 片段**
```sql
WHERE dt.problem_type = '客服'
  AND vl.aipl_node = 'L2'
  AND vl.source_name IN ('zendesk','amazon','trustpilot')
  AND vl.review_date >= CURRENT_DATE - INTERVAL '14 days'
  AND vl.quality_tier IN ('A','B','C')
```

> **关键说明**：CSS 的核心边界是 **区分"流程问题"和"人的问题"**。若用户抱怨"客服态度很好但解决不了问题"，根因是授权不足而非培训不足，不应归因客服团队。

---

### S31 · 安全问题信号

**触发条件与 SRAC 评分**
| 阈值类型 | 条件 | 优先级 | SRAC-S | SRAC-R | SRAC-A | SRAC-C | 总分 |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| 绝对值 | SSR > 阈值 | P0 | 10 | 6 | 9 | 7 | **8.0** |
| 信号强度 | 出现 ★★★★ 级安全证据（拆机/实测） | P0 | 10 | 5 | 9 | 8 | **8.0** |
| 趋势 | 安全标签周环比增长 > 50% | P0 | 9 | 6 | 9 | 7 | **7.8** |
| 关联 | 同一问题在 ≥2 个平台出现 | P0 | 9 | 7 | 9 | 7 | **8.0** |

**叙事结构**
```
【1. 信号发现】
  安全问题信号 SSR = {ssr_value}。
  安全相关 VOC 共 {mentions} 次，涉及 {affected_spus} 个 SPU。
  按严重度拆分：极高风险 {extreme} 次 / 高风险 {high} 次 / 中风险 {medium} 次。
  按平台拆分：{platform_breakdown}。
  ⚠️ 任何安全类标签出现即触发 P0 响应，无需等待阈值。

【2. 根因归因】
  安全标签详情（含证据强度 + 消费者原话）：
    1. {tag_1} ({mentions_1}次, 风险等级:{risk_1}, 证据强度:{evidence_1})
       消费者原话："{quote_1}" — {source_platform_1}
    2. {tag_2} ({mentions_2}次, 风险等级:{risk_2}, 证据强度:{evidence_2})
       消费者原话："{quote_2}" — {source_platform_2}
    3. {tag_3} ({mentions_3}次, 风险等级:{risk_3}, 证据强度:{evidence_3})
       消费者原话："{quote_3}" — {source_platform_3}
  涉及 SPU：{affected_spus}
  失效模式：{failure_modes}

【2.5. 反直觉洞察】
  直觉认知：安全问题很少见，出现个案不必过度反应。
  反直觉发现：
    - 安全问题的 VOC 提及量往往极低（因为涉及安全的问题用户会优先联系官方/退货，
      而非公开评论），但每一条都是高证据强度
    - 用户留言："opened it up... moisture everywhere... shorting the board"
      — 一篇拆机帖揭示的是系统性设计缺陷，不是个例
    - "没有大量投诉"不等于"没有安全问题"，可能等于"用户直接退货了"
  深层机制：
    - 安全问题的公开提及量 = 实际发生量 × 用户公开意愿
    - 母婴品类中，涉及宝宝安全的问题，用户公开意愿极低（怕担责/怕引发恐慌）
    - 所以 VOC 中安全问题的"信号密度"远高于表面数量
    - 一个带拆解图的安全投诉 = 潜在 100+ 个未公开的同样问题
  高后果信号：
    - 若安全投诉涉及 "electrocution" / "burned smell" / "shorted" →
      24 小时内启动安全评估，48 小时内决定是否批次隔离
    - 若安全投诉来自 Reddit 等社区且获得高赞 →
      说明问题已引起广泛关注，可能触发媒体/监管关注
    - 若同一失效模式在 ≥2 个 SPU 中出现 →
      说明是平台级/设计级缺陷，非批次问题

【3. 影响评估】
  涉及退货/召回风险：{recall_risk}
  受影响订单量估算：{affected_orders}
  法务合规风险：{compliance_risk}
  品牌信任损失：{trust_impact}
  媒体/监管风险：{media_risk}
  Revenue at risk：${revenue_at_risk}

【4. 行动建议】
  主责部门：品质管理中心（牵头）+ 法务合规部 + 产品中心
  strategy_package：合规背书强化包 + 质量风险防控包
  优先级：P0 — 24 小时内启动
  建议：
    - 立即：品质管理中心介入，确认失效模式是否为系统性问题
    - 立即：法务部评估召回风险和法律合规要求
    - 立即：若证据强度 ≥ ★★★★，冻结该 SPU/批次出货
    - 短期：工程师介入问题复现，区分"设计缺陷"vs"批次质量问题"
    - 短期：联系投诉用户，了解详细使用情况，收集失效样本
    - 中期：设计/工艺变更，必要时启动召回
    - 长期：建立安全标签自动预警（任何安全标签出现即 P0 告警）
  预期指标变化（MAA 式）：
    - SSR：目标归零
    - 安全类标签提及量：目标归零
    - 受影响批次退货率：控制在 {target_return_rate}% 以内

【5. 持续监控】
  监控指标：SSR + 安全标签提及量 + **证据强度 ≥ ★★★★ 的安全内容**
  监控频率：每日
  预警阈值：任何安全标签出现即触发 P0 响应
  验收标准：连续 30 天无新增安全标签，且已出现的安全问题全部闭环
```

**所需数据**
- 指标：`SSR` (OQ-3)
- 标签：安全相关 13 标签（含 `risk_level` 字段）
- 维度：SPU / 失效模式 / 平台 / 证据强度

### VOC 筛选边界

| 筛选维度 | 包含规则 | 排除规则 | 业务逻辑 |
|---|---|---|---|
| **AIPL 节点** | 全节点 A→L3 | 无 | 安全问题可能在任何阶段暴露 |
| **标签范围** | `risk_level IN ('极高风险','高风险')` OR `default_priority='P0'` 的安全标签 | 中/低风险标签 | 以 risk_level 为主，default_priority 为辅 |
| **情感方向** | 全部 | 无 | 安全信号不依赖情感极性 |
| **平台范围** | 全 7 信源 | 无 | 安全问题首发可能在任何平台 |
| **时间窗口** | 滑动 7 天 | — | 安全问题需每日监控 |
| **质量等级** | quality_tier IN ('A','B','C') | D | 安全不能因质量过滤漏掉 |
| **特殊条件** | 证据强度 ≥ ★★ 才纳入统计 | 仅 ★ 的孤立抱怨 | 安全需要证据支撑 |

**SQL WHERE 片段**
```sql
WHERE (dt.risk_level IN ('极高风险', '高风险')
       OR (dt.default_priority = 'P0' AND dt.problem_type LIKE '%安全%'))
  AND vl.review_date >= CURRENT_DATE - INTERVAL '7 days'
  AND vl.quality_tier IN ('A','B','C')
```

> **关键说明**：安全问题的 **VOC 筛选最特殊**——它不能只看 `default_priority='P0'`，因为 v6.2 字典中 13 个 P0 标签全为"中风险"。真正的高风险标签（6 个高风险 + 2 个极高风险）反而没有 P0 优先级。安全监控必须 **以 risk_level 为主，default_priority 为辅**。

---

## 五、故事线速查表（全部 37 条）

### 品牌与市场 (S01-S05)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S01 | 北极星崩塌 | NPS < 30 或环比 > 10pp | proxy_nps 2,009 标签 | NPS 专项报告 |
| S02 | 广告信任危机 | ATI < 60% | A节点 46 标签 | 广告策略建议 |
| S03 | 搜索信息黑洞 | ITI < 50% | I节点 49 标签 | 信息架构优化方案 |
| S04 | 竞品情感失守 | CEG < -0.2 | competitor_mentioned | 竞品对标报告 |
| S05 | 社媒负面先兆 | SLI < 7 天 | Reddit→Amazon 跨平台 | 社媒预警报告 |

### 营销与获客 (S06-S08)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S06 | 种草转化率低迷 | SCI < 40% | A节点 promoter 标签 | 种草策略优化 |
| S07 | 价格感知崩塌 | PPD > 60% | 价格 6 标签 | 定价策略建议 |
| S08 | 促销承诺不兑现 | PFR < 70% | P2→L1 关联标签 | 促销合规检查 |

### 销售与转化 (S09-S11)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S09 | 购买动机转化瓶颈 | PMF < 50% | P1/P2 89 标签 | 转化漏斗优化 |
| S10 | 促销信任危机 | PAI < 80% | 价格负向 6 标签 | 促销真实性审计 |
| S11 | 库存-投诉螺旋 | ICL < 3 天 | 物流+库存标签 | 库存-物流协同方案 |

### 产品与研发 (S12-S17)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S12 | 品线健康度恶化 | PLH < 1.0 | L1+L2S 1,385 标签 | 品线诊断报告 |
| S13 | 标签紧急度风暴 | Top-10 中 ≥3 P0 | P0 13 标签 | 紧急响应预案 |
| S14 | SPU 问题热力爆发 | SPH Top-5% | L2S 1,225 标签 | SPU 改进方案 |
| S15 | 产品衰退加速 | DA < -0.1 | 全量标签时序 | 产品生命周期预警 |
| S16 | 策略包修复无效 | SPC > 30 天 | strategy_package | 策略包效果审计 |
| S17 | 品质波动异常 | QVC > 2.0 | problem_type=产品性能 | 品质波动根因报告 |

### 供应链与物流 (S18-S21)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S18 | 物流满意度滑坡 | LSS < 40% | 物流 60 标签 | 物流优化方案 |
| S19 | 跨境物流投诉激增 | CLCR > 20% | 物流+country≠US | 跨境物流整改 |
| S20 | 包装投诉集中爆发 | PCR > 10% | 包装完整性 4 标签 | 包装改进方案 |
| S21 | 物流时效系统性偏差 | LTD > 3 天 | 物流+tracking | 时效 SLA 调整 |

### 客服与售后 (S22-S25)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S22 | 客服体验恶化 | CSS < 50% | 客服 L2 标签 | 客服培训方案 |
| S23 | 退换货痛苦加剧 | RPI > 阈值 | 退换货主题 | 退换货流程优化 |
| S24 | 投诉持续升级 | EUR > 15% | L2→L1 关联 | 投诉升级管控 |
| S25 | 信任恢复失败 | TRR < 30% | L2→L3 追踪 | 信任恢复方案 |

### 客户体验与忠诚 (S26-S29)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S26 | 推荐意愿不足 | RWI < 40% | L3 promoter | 推荐激励优化 |
| S27 | 复购信号消失 | RSS < 30% | 决策旅程卡 290 标签 | 复购激活方案 |
| S28 | 新手妈妈流失加剧 | NMPI > 阈值 | P0 负向+新手persona | 新手体验优化 |
| S29 | 高价值用户沉默 | CAS > 20% | L1 负向→L3 沉默 | 用户挽回方案 |

### 运营与质量 (S30-S33)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S30 | P0 触发率飙升 | P0R > 0.5% | P0 13 标签 | 紧急质量响应 |
| S31 | 安全问题信号 | SSR > 阈值 | 安全 13 标签 | 安全合规检查 |
| S32 | 部门 SLA 不达标 | DSR < 80% | dept_owner 聚合 | SLA 整改方案 |
| S33 | 风险暴露度超限 | REE > 2.0 | risk_level 加权 | 风险管控方案 |

### 反直觉洞察 (S34-S37)

| # | 故事线 | 触发条件 | 核心标签 | 输出物 |
|---|---|---|---|---|
| S34 | 竞品迁移链断裂 | 竞品推荐+复购下降+迁移叙事 | competitor_mentioned + migration_intent | 竞品叙事干预方案 |
| S35 | 二手转让原因映射 | 二手转让量>阈值+适配类>40% | fit_issue + size_related | 购买决策优化方案 |
| S36 | 用户 DIY 维修信号 | DIY维修内容>3条/周 | repair + DIY + opened_up | 可维修性改进方案 |
| S37 | 价格-期望错配陷阱 | 价格负向+性价比好评下降 | price_negative + value_for_money | 价值传达优化方案 |

---

## 六、VOC 筛选条件速查总表

以下表格汇总 15 条详解故事线的 VOC 筛选边界，供分析师快速查阅。完整筛选条件（含 SQL 片段）见各故事线详解。

### 6.1 按 AIPL 节点筛选

| 故事线 | 包含 AIPL 节点 | 排除 AIPL 节点 | 说明 |
|---|---|---|---|
| S01 NPS 异常 | 全节点 A→L3 | 无 | 北极星需全局 |
| S04 竞品情感失守 | I→P1→L1→L3 | A/P2 | 竞品比较在决策→忠诚 |
| S07 价格感知崩塌 | P1→P2→L1 | A/I/L2/L3 | 价格感知在决策→使用 |
| S13 标签紧急度风暴 | 全节点 | 无 | P0 可出现在任何阶段 |
| S14 SPU 问题热力 | L1→L2 | A/I/P1/P2 | 产品问题在使用→售后 |
| S18 物流满意度滑坡 | P2→L1 | A/I/L2/L3 | 物流在下单→收货 |
| S22 客服体验恶化 | L2 | A/I/P1/P2/L1/L3 | 客服只在售后 |
| S23 退换货痛苦加剧 | L2→L3 | A/I/P1/P2 | 退换货在售后→复购 |
| S28 新手妈妈流失 | A→I→P1→L1 | P2/L2/L3 | 新手痛点在认知→使用 |
| S30 P0 触发率飙升 | 全节点 | 无 | P0 可出现在任何阶段 |
| S31 安全问题信号 | 全节点 | 无 | 安全可在任何阶段 |
| S34 竞品迁移链断裂 | I→P1→L1→L3 | A/P2 | 迁移在决策→忠诚 |
| S35 二手转让原因映射 | L1→L2→L3 | A/I/P1/P2 | 转让在使用→售后 |
| S36 用户 DIY 维修信号 | L1→L2 | A/I/P1/P2 | DIY 在使用→售后 |
| S37 价格-期望错配陷阱 | P1→P2→L1 | A/I/L2/L3 | 错配在决策→使用 |

### 6.2 按问题类型排除

| 故事线 | 必须包含的问题类型 | 必须排除的问题类型 | 原因 |
|---|---|---|---|
| S01 NPS 异常 | 全量 | 无 | 全局指标 |
| S07 价格感知崩塌 | 价格 | 物流/客服/产品 | 聚焦价格感知 |
| S13 标签紧急度风暴 | P0/高风险 | 普通优先级 | 只看紧急度 |
| S14 SPU 问题热力 | 产品相关 | 物流/客服/价格 | 聚焦产品问题 |
| S18 物流满意度滑坡 | 物流 | 产品/价格/客服 | 聚焦物流履约 |
| S22 客服体验恶化 | 客服 | 产品/物流/价格 | 聚焦售后交互 |
| S23 退换货痛苦加剧 | 退换货/售后政策 | 产品性能（根因时） | 区分流程 vs 产品问题 |
| S28 新手妈妈流失 | P0 负向 | 非 P0 标签 | 只看核心痛点 |
| S30 P0 触发率飙升 | P0 | 非 P0 标签 | 严格 P0 边界 |
| S31 安全问题信号 | 安全/极高+高风险 | 中/低风险 | 以 risk_level 为主 |
| S34 竞品迁移链断裂 | 竞品提及 | 无竞品提及 | 只看竞品对话 |
| S35 二手转让原因映射 | 适配/尺寸 | 其他 | 外部数据为主 |
| S36 用户 DIY 维修信号 | 维修/DIY | 无关键词 | 关键词匹配 |
| S37 价格-期望错配陷阱 | 价格负向 | 物流/客服/产品 | 聚焦价格-价值感知 |

### 6.3 按平台范围筛选

| 故事线 | 包含平台 | 排除平台 | 原因 |
|---|---|---|---|
| S01 NPS 异常 | 全 7 信源 | 无 | 跨平台品牌健康度 |
| S04 竞品情感失守 | Reddit/Amazon/Facebook | Zendesk | 竞品讨论在社区+购买平台 |
| S07 价格感知崩塌 | Amazon/Trustpilot/Zendesk | Reddit/Meltwater | 购买后评价更真实 |
| S13 标签紧急度风暴 | 全 7 信源 | 无 | P0 可在任何平台首发 |
| S14 SPU 问题热力 | Amazon/Zendesk/Reddit | Meltwater/FB/IG | 产品深度评价集中 |
| S18 物流满意度滑坡 | Amazon/Zendesk/Trustpilot | Reddit/Meltwater | 物流评价在购买后平台 |
| S22 客服体验恶化 | Zendesk/Amazon/Trustpilot | Reddit/Meltwater | 客服评价在售后平台 |
| S23 退换货痛苦加剧 | Zendesk/Amazon/Trustpilot | Reddit/Meltwater | 退换货在购买后平台 |
| S28 新手妈妈流失 | Amazon/Reddit/Facebook | Zendesk/Trustpilot | 新手评价在社区+购买 |
| S30 P0 触发率飙升 | 全 7 信源 | 无 | P0 可在任何平台首发 |
| S31 安全问题信号 | 全 7 信源 | 无 | 安全问题可在任何平台 |
| S34 竞品迁移链断裂 | Reddit/Amazon/Facebook | Zendesk | 竞品讨论在社区 |
| S35 二手转让原因映射 | 外部二手平台 | 内部 7 信源 | 外部数据为主 |
| S36 用户 DIY 维修信号 | Reddit/Facebook | Amazon/Trustpilot | DIY 讨论在社区 |
| S37 价格-期望错配陷阱 | Amazon/Trustpilot/Reddit | Zendesk | 价格评价在购买平台 |

### 6.4 关键边界原则速查

| 原则 | 适用故事线 | 说明 |
|---|---|---|
| **全局 vs 局部** | S01/S13/S30/S31 用全局，其余用局部 | 北极星/紧急度/安全需全局，其他聚焦 |
| **情感全量 vs 负向** | S01/S18/S22 用全量，其余用负向为主 | 满意度指标需正负向比例 |
| **时间窗口** | P0/安全用 7 天，物流用 14 天，其他用 30 天 | 紧急度决定窗口长度 |
| **质量等级** | P0/安全含 C 级，其他只含 A/B | 高紧急度不能过滤 |
| **外部数据** | 仅 S35 依赖外部二手平台 | 其余全为内部 VOC |
| **证据强度** | S13/S31/S36 需 ≥ ★★，其他无此要求 | 安全/紧急度需要证据支撑 |

---

## 七、交叉引用索引

### 6.1 按 story_lines 索引

| story_lines | 关联故事线 | 标签数 | strategy_package |
|---|---|---|---|
| 核心体验问题 | S01, S12, S14, S15, S28 | 1,354 | 核心体验改良包 |
| 场景使用冲突 | S12, S14, S17 | 172 | 场景适配优化包 |
| 使用负担 | S20, S28 | 145 | 场景适配优化包 |
| 价值感争议 | S07, S09, S37 | 125 | 价值表达优化包 |
| 质量风险闭环 | S13, S16, S17, S30, S31, S33, S36 | 95 | 质量风险防控包 |
| 参数透明度诊断 | S03, S17 | 84 | 信息架构优化包 |
| 新手上手断点 | S28, S35 | 65 | 核心体验改良包 |
| 卖点认知偏差 | S03, S06 | 55 | 核心卖点校准包 |
| 信任校验 | S02, S25 | 52 | 信息架构优化包 |
| 履约体验 | S11, S18, S19, S21 | 49 | 履约提速包 |
| 承诺偏差 | S08, S10, S21 | 37 | 承诺一致性校对包 |
| 品牌破冰效率 | S02, S04, S34 | 32 | 品牌认知校准包 |
| 售后闭环能力 | S23, S24, S32 | 26 | 售后服务SOP包 |
| 复购准备度 | S26, S27 | 12 | 复购激活包 |
| 信任恢复 | S25 | 11 | 售后服务SOP包 |
| 竞品迁移叙事 | S34 | 8 | 竞品差异化包 |
| 可维修性信号 | S36 | 5 | 核心体验改良包 |
| 价格锚点偏差 | S37 | 4 | 价值表达优化包 |

### 6.2 按 strategy_package 索引

| strategy_package | 关联故事线 | 标签数 | 主责部门 |
|---|---|---|---|
| 核心体验改良包 | S01, S12, S14, S15, S28, S36 | 1,502 | 产品中心 |
| 场景适配优化包 | S12, S14, S20, S28 | 184 | 产品中心 |
| 价值表达优化包 | S07, S09, S37 | 156 | 电商运营部 |
| 信息架构优化包 | S02, S03, S35 | 123 | 品牌市场中心 |
| 质量风险防控包 | S13, S16, S17, S30, S33, S36 | 118 | 品质管理中心 |
| 核心卖点校准包 | S03, S06 | 56 | 品牌市场中心 |
| 合规背书强化包 | S31 | 50 | 品质管理中心 |
| 履约提速包 | S11, S18, S19, S21 | 49 | 仓储物流部 |
| 承诺一致性校对包 | S08, S10, S21 | 33 | 电商运营部 |
| 一次解决提升包 | S22, S24, S32 | 23 | 全球客服中心 |
| 品牌认知校准包 | S02, S04, S34 | 16 | 品牌市场中心 |
| 复购激活包 | S26, S27 | 14 | 电商运营部 |
| 售后服务SOP包 | S23, S24, S25 | 10 | 全球客服中心 |
| 人群内容匹配包 | S05 | 10 | 品牌市场中心 |
| 竞品差异化包 | S04, S34 | 8 | 品牌市场中心 |
| 购买决策优化包 | S35 | 6 | 电商运营部 |

### 6.3 按 dept_owner 索引

| 部门 | 负责故事线 | 核心指标 |
|---|---|---|
| 产品中心 | S12-S17, S28, S36 | PLH, TUI, SPH, DA, SPC, QVC, NMPI |
| 品牌市场中心 | S01-S05, S26, S34 | NPS, ATI, ITI, CEG, SLI, RWI |
| 电商运营部 | S06-S11, S27, S29, S35, S37 | SCI, PPD, PFR, PMF, PAI, ICL, RSS, CAS |
| 仓储物流部 | S18-S21 | LSS, CLCR, PCR, LTD |
| 全球客服中心 | S22-S25 | CSS, RPI, EUR, TRR |
| 品质管理中心 | S30-S33 | P0R, SSR, DSR, REE |
| 法务合规部 | S31（安全合规） | SSR（协同品质管理中心） |

---

## 八、洞察报告模板（Markdown 输出格式）

分析师使用故事线输出洞察报告时，遵循以下统一模板：

```markdown
# [Sxx] 故事线标题 — {品线/SPU} — {时间周期}

> **触发指标**: {指标名} = {当前值} (基准: {基准值}, 阈值: {阈值})
> **优先级**: {P0/P1/P2} | **主责部门**: {dept_owner}
> **关联 strategy_package**: {strategy_packages}
> **分析师**: {name} | **报告日期**: {date}

---

## 1. 信号发现

{数据可视化: 指标趋势图 + 当前值标注}

- 指标当前值: {value}
- 环比变化: {delta}pp
- 与基准对比: {vs_baseline}
- 置信度: {confidence}

## 2. 根因归因

### Top-3 根因标签

| 排名 | 标签 ID | 标签名称 | 提及次数 | 负向占比 | TUI |
|---|---|---|---|---|---|
| 1 | {tag_id} | {name_cn} | {mentions} | {neg_pct}% | {tui} |
| 2 | {tag_id} | {name_cn} | {mentions} | {neg_pct}% | {tui} |
| 3 | {tag_id} | {name_cn} | {mentions} | {neg_pct}% | {tui} |

### 消费者原话采样

> "{consumer_phrase_1}" — {source_platform}, {country}
> "{consumer_phrase_2}" — {source_platform}, {country}
> "{consumer_phrase_3}" — {source_platform}, {country}

### 细分维度

- 平台: {platform_breakdown}
- 国家: {country_breakdown}
- SPU: {spu_breakdown}

## 3. 影响评估

- 影响用户规模: {affected_users}
- 关联 business_impact: {business_impacts}
- Revenue at risk: ${revenue_at_risk}
- 竞品对标: {competitor_comparison}

## 4. 行动建议

### 立即行动 (24-72h)
- [ ] {action_1}
- [ ] {action_2}

### 短期行动 (1-4 周)
- [ ] {action_3}
- [ ] {action_4}

### 中长期行动 (1-3 月)
- [ ] {action_5}

### 资源需求
- 部门: {dept_owner}
- 预算: {budget}
- 人力: {headcount}

## 5. 持续监控

| 监控指标 | 当前值 | 目标值 | 监控频率 | 下次复盘 |
|---|---|---|---|---|
| {metric_1} | {val_1} | {target_1} | 每周 | {date_1} |
| {metric_2} | {val_2} | {target_2} | 每周 | {date_2} |

---

**附录**
- 完整标签列表: {tag_list_link}
- SQL 查询: {sql_link}
- 数据导出: {data_export_link}
```

---

## 九、使用流程

```
Step 1: 监控指标异常
  ↓ 触发某个指标的阈值条件
Step 2: 匹配故事线
  ↓ 查 "故事线全景索引" 表，找到对应的故事线编号 (Sxx)
Step 3: 执行叙事结构
  ↓ 按 6 段式模板填充数据
Step 4: 输出洞察报告
  ↓ 使用 "洞察报告模板" 生成 Markdown
Step 5: 分发给业务方
  ↓ 主责部门 (dept_owner) 接收并执行
Step 6: 持续监控
  ↓ 按故事线定义的监控指标跟踪改善效果
Step 7: 复盘闭环
  ↓ 下次复盘时验证指标是否回归正常
```

---

> **最近更新**: 2026-05-23 — 洞察故事线 v2.1 升级：在 v2 基础上，为 **15 条详解故事线逐条定义 VOC 筛选边界**（含 7 维度筛选规则 + SQL WHERE 片段 + 关键边界说明），新增 **VOC 筛选条件速查总表**（按 AIPL 节点 / 问题类型排除 / 平台范围 / 关键边界原则 4 个维度汇总）。完整输入输出链路：原始 VOC → 质量过滤 → AIPL 节点筛选 → 问题类型隔离 → 平台范围限定 → 情感方向选择 → 故事线指标计算 → 阈值触发 → 6 段式洞察报告 → 业务行动分发。
