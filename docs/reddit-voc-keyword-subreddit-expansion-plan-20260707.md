---
title: Momcozy Reddit VOC Keyword and Subreddit Expansion Plan
doc_type: implementation_plan
status: executed
created: 2026-07-07
updated: 2026-07-07
owner: codex
project: Reddit_VOC
production_boundary: production unchanged
provider_call: false
live_send: false
---

# Momcozy Reddit VOC Keyword and Subreddit Expansion Plan

## 1. 目标

围绕 Momcozy 品牌和品类 VOC，更新帖子正文与评论正文的搜索词、分析词和 subreddit 覆盖池。目标不是扩大成泛母婴爬虫，而是在高召回和可解释精度之间分层：泵奶与 bottle washer 可独立召回，carrier/high chair/sound machine 等泛育儿词必须结合 Momcozy、产品名或竞品上下文。

## 2. 证据来源

本地历史数据：

- 输入目录：`/Users/pray/project/ai_nlp_voc/system_data/voc_data/reddit/Momcozy/`
- 解析结果：55 个 Reddit thread，2215 条评论，0 个解析失败。
- 证据产物：`/Users/pray/project/Reddit_VOC/outputs/momcozy-history-keyword-mining-20260707.json`

网络洞察：

- Reddit 搜索确认泵奶社区继续存在 Momcozy/M5/M9/S12/output/flange 等讨论。
- Reddit 搜索确认 babywearing 社区存在 Momcozy carrier/PureHug 类讨论。
- Reddit 搜索确认 Buyingforbaby、NewParents、beyondthebump、moderatelygranolamoms 等混合社区存在 bottle washer/KleanPal/sterilizer 类讨论。
- Momcozy 官网检索确认 KleanPal、DinerPal、PureHug 等非泵奶产品线应进入上下文关键词池。

## 3. 历史数据发现

### 3.1 subreddit 分布

| subreddit | 历史 thread 数 | 处理策略 |
|---|---:|---|
| ExclusivelyPumping | 41 | P0，每日采集 |
| babywearing | 4 | P1，需上下文品类词 |
| breastfeeding | 1 | P0，每日采集 |
| parentsofmultiples | 1 | P1，高强度泵奶场景 |
| BabyBumpsCanada | 1 | P2，区域补充 |
| HumansPumpingMilk | 1 | P0，每日采集 |
| Mommit | 1 | P2，低精度泛社区 |
| BabyBumpsandBeyondAu | 1 | P2，区域补充 |
| BabyBumps | 1 | P1，孕期购买决策 |

### 3.2 高频产品与品类

| 类型 | 高频项 | 结论 |
|---|---|---|
| Momcozy pump | M5, M9, S12, M6, V1, V1 Pro, V2, S9, Air 1 | 旧关键词覆盖基本完整，但 M9 需要进入 TikHub 默认搜索词 |
| Pump category | flange, collection cups, wearable pump, breast pump, hospital grade, portable pump, manual pump | 需要把 `breast pump`, `pump parts`, `hospital grade pump`, `manual pump`, `electric pump` 加入召回 |
| Baby adjacent | bottle washer, high chair, dryer, sterilizer, bottle warmer, baby carrier, sound machine | 需要扩出 bottle washer 独立召回；carrier/high chair/sound machine 作为上下文召回 |
| Competitor | Spectra, Eufy, Medela, Willow, Baby Buddha, Baby Brezza, Elvie, Grownsy, Ergobaby, Papablic, Maymom | 竞品池要从泵奶扩到 bottle washer、carrier、baby gear |
| Pain point | parts, output, suction, supply, motor, replacement, dishwasher, customer service, nipple, fit, app, warranty, charging, cleaning, battery | 分析词要补 `motor`, `replacement`, `dishwasher`, `charging`, `mold`, `rust`, `fit`, `sizing` |
| Scenario | work, insurance, twins, postpartum, FTM, travel, registry, NICU, daycare | 场景分析要补 `twins`, `multiples`, `NICU`, `registry`, `daycare` |

## 4. 搜索配置更新方案

### 4.1 关键词分层

| 层级 | 用途 | 示例 | 召回规则 |
|---|---|---|---|
| Brand | 明确 Momcozy | `momcozy`, `mom cozy`, `momcozy bottle washer`, `momcozy carrier` | 独立相关 |
| Product | 产品线识别 | `M5`, `M9`, `S12`, `KleanPal`, `DinerPal`, `PureHug` | 需品牌或品类上下文，避免短型号误伤 |
| Independent category | 可独立成为 VOC 主题 | `wearable pump`, `breast pump`, `bottle washer`, `bottle sterilizer` | 独立相关 |
| Contextual category | 泛母婴词 | `baby carrier`, `high chair`, `sound machine`, `diaper bag` | 必须同时出现品牌、产品或竞品 |
| Competitor | 品类对比和替代方案 | `Spectra`, `eufy S1 Pro`, `Baby Brezza`, `Ergobaby`, `Hatch` | 独立相关，但 P2 社区需结合上下文复核 |

### 4.2 subreddit 分层

| Tier | 社区 | 策略 |
|---|---|---|
| P0 | ExclusivelyPumping, BreastPumping, breastfeeding, HumansPumpingMilk, breastpumps | 每日采集，品牌或品类词即可进入候选 |
| P1 | Buyingforbaby, BabyBumps, beyondthebump, workingmoms, NewParents, babywearing, moderatelygranolamoms, FormulaFeeders, parentsofmultiples, NICUParents | 每日容量允许时采集，优先品牌/产品/bottle washer/carrier 场景 |
| P2 | Mommit, pregnant, Parenting, toddlers, ScienceBasedParenting, SAHP, BabyBumpsCanada, BabyBumpsandBeyondAu, daddit | 搜索或 fallback 使用，要求品牌、产品或竞品上下文 |

## 5. 已执行变更

- 更新 `/Users/pray/project/Reddit_VOC/config/keywords.yaml`：增加产品线、bottle washer、上下文品类、竞品和痛点词。
- 更新 `/Users/pray/project/Reddit_VOC/config/subreddits.yaml`：默认采集小时改为 07:00，扩充 P0/P1/P2 社区池和 keyword policy。
- 更新 `/Users/pray/project/Reddit_VOC/src/reddit_voc/keywords.py`：同步运行时默认词库，增加上下文品类匹配规则。
- 更新 `/Users/pray/project/Reddit_VOC/src/reddit_voc/analyzer.py`：补齐评论中的操作、售后、家庭场景痛点词。
- 更新 `/Users/pray/project/Reddit_VOC/src/reddit_voc/collector.py`：扩充默认每日 subreddit。
- 更新 `/Users/pray/project/Reddit_VOC/src/reddit_voc/cli.py`：扩充 TikHub dynamic search 默认关键词。
- 更新 `/Users/pray/project/Reddit_VOC/src/reddit_voc/time_window.py` 和 `/Users/pray/project/Reddit_VOC/src/reddit_voc/ops.py`：默认滚动窗口对齐 07:00 北京时间。
- 更新 `/Users/pray/project/Reddit_VOC/tests/test_keywords_analyzer.py` 和 `/Users/pray/project/Reddit_VOC/tests/test_time_window.py`：覆盖新增召回和泛词抑制边界。

## 6. 执行计划与 TODO

| 阶段 | 状态 | 任务 | 验收证据 |
|---|---|---|---|
| Phase 1 | done | 解析历史 Momcozy Reddit 数据 | `parsed_threads=55`, `parsed_comments=2215`, `parse_errors=0` |
| Phase 2 | done | 网络补充 subreddit 和产品线洞察 | Reddit/Momcozy 官网检索结果已用于配置 |
| Phase 3 | done | 更新关键词、品类、竞品和 subreddit 配置 | `config/keywords.yaml`, `config/subreddits.yaml` 已修改 |
| Phase 4 | done | 同步运行时默认词库与采集社区 | `keywords.py`, `collector.py`, `cli.py` 已修改 |
| Phase 5 | in_progress | 生成产品全景图 | `docs/reddit-voc-product-panorama-20260707.html` |
| Phase 6 | pending | 运行单测、配置校验、边界检查 | `python -m unittest`, YAML parse, secret scan |

## 7. 剩余运营事项

- 配置真实 TikHub API key、DingTalk webhook 和可访问的 artifact base URL 后，才能执行 provider_call/live_send。
- P2 社区容易产生泛育儿噪音，建议先跑 3-5 天人工复核命中率，再决定是否加入默认每日采集。
- 如果 DingTalk 端需要直接预览完整 HTML，仍需要把 HTML/XLSX/CSV/PNG 放到可访问的静态文件服务或对象存储；本地路径不能在群里被其他人打开。
