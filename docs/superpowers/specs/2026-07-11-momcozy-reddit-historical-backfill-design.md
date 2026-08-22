---
title: Momcozy Reddit 历史数据混合回填设计
doc_type: design_spec
status: approved
created: 2026-07-11
updated: 2026-07-11
owner: codex
decision: hybrid_seed_and_paginated_tikhub
production_boundary: production_unchanged
provider_call: false
live_send: false
---

# Momcozy Reddit 历史数据混合回填设计

## 1. 决策

采用用户于 2026-07-11 批准的方案 3：

1. 先把已有 Reddit 原始 JSON 中落在目标窗口且符合现有 Momcozy 口径的数据导入独立 backfill SQLite。
2. 再通过 TikHub Reddit APP API 的游标分页补齐历史发现、帖子详情和评论。
3. 在独立数据库完成完整性、覆盖率、幂等性和请求终止原因验收。
4. 生产库合并保持独立授权门槛；合并时只插入新实体，不覆盖现有日采实体和 run lineage。

本设计不使用现有 `run-tikhub-collector` 直接扩大 `rolling_window_hours`。现有参数只能过滤已发现结果，现有 discovery 和 comments 都未翻页，无法证明历史召回完整。

## 2. 目标与非目标

### 2.1 目标

- 按帖子发布时间采集北京时间 2025-01-01 至 2026-07-11 的 Momcozy Reddit 数据。
- 沿用当前 Momcozy 品牌、产品、品类、竞品标注和排除词规则，不临时扩词。
- 将原始响应保存为私有、可校验、可重放的归档，并生成结构化 post、comment 和 local-rules analysis 数据。
- 支持分页、去重、请求预算、重试、断点续跑和确定性重放。
- 整个 backfill 阶段保持 `live_send=false`，不生成或发送 DingTalk 报告。

### 2.2 非目标

- 不运行 `server_daily_cycle.sh`、`server_daily_report.sh`、`run_daily_report.sh` 或任何 DingTalk 命令。
- 不修改 07:00 日采、08:00 报告的现有 cron。
- 不修改网站、报告模板或翻译链路。
- 不新增 Reddit OAuth。
- 不把 Provider 请求成功等同于平台全量覆盖；验收只声明已完成配置搜索词和社区范围内、由 TikHub 游标可达的数据回填。
- 未经单独授权，不写现有生产数据库 `/app/data/reddit_voc_daily.sqlite3`。

## 3. 已验证基线

### 3.1 生产只读基线

2026-07-11 的只读检查结果：

- `runs=14`
- `raw_captures=14`
- `reddit_threads=48`
- `reddit_comments=258`
- `analysis_results=288`
- 生产帖子创建时间约覆盖 `2026-07-07T00:50:56Z` 至 `2026-07-10T18:25:21Z`
- `raw_captures` 没有 raw payload、payload path 或 raw JSON 列

生产库现状不足以覆盖本次历史窗口。

### 3.2 已有原始数据基线

来源目录：

`/Users/pray/project/ai_nlp_voc/system_data/voc_data/reddit/Momcozy/`

只读解析结果：

- 原始 JSON：55 个帖子 payload
- 目标窗口内：48 帖、1,894 评论
- 目标窗口外：7 帖
- 目标窗口内 48 帖均符合当前 `match_keywords` 口径
- thread 正文直接命中：47 帖
- 仅在 thread/comment 合并文本中命中：1 帖
- coverage：45 `full`、3 `partial`
- parse error：0

这批数据是确定性的零 Provider 成本种子，不代表整个日期区间的全量召回。

### 3.3 现有实现约束

- Browser listing 只读取每个 subreddit 的 `/new/.json` 首屏，最多 100 条。
- TikHub dynamic search、subreddit feed 和 comments 当前都只请求首屏。
- 详情接口每批最多 30 个 post ID。
- 当前 `REDDIT_VOC_TIKHUB_DAILY_REQUEST_LIMIT` 只被传入容器，collector 没有读取或执行预算。
- `post_id`、`comment_id`、`analysis_id` 是全局主键，重复采集会把旧实体的 `run_id` 更新为新 run。
- TikHub 同一 `run_id` 重跑会在 Provider 请求前清除该 run 的采集数据。
- Raw capture 当前只保存 hash 和元数据，原始 discovery/detail/comment 响应不会落盘。

## 4. 日期与相关性语义

### 4.1 日期窗口

完整自然日窗口采用左闭右开区间：

```text
Beijing: [2025-01-01T00:00:00+08:00, 2026-07-12T00:00:00+08:00)
UTC:     [2024-12-31T16:00:00Z,      2026-07-11T16:00:00Z)
```

由于 2026-07-11 的首次执行发生在该自然日尚未结束时：

- 首次执行的 `effective_end` 取执行开始时刻；
- 若要求覆盖 7 月 11 日整日，在北京时间 2026-07-12 00:05 后执行同一窗口的余量补采；
- 帖子创建时间必须满足 `start <= created_at_utc < effective_end`；
- 评论不按评论发布时间过滤。只要所属帖子落窗，就保存 Provider 当前可返回的评论。

### 4.2 关键词口径

- 候选召回继续使用当前 `DEFAULT_TIKHUB_SEARCH_TERMS`，包括 Momcozy、Momcozy 产品词、wearable/breast pump、bottle washer 等现有词。
- 结构化匹配继续使用当前 `match_keywords`，包括 brand、product、category、contextual category、competitor 和 exclude 规则。
- 不新增 competitor-only 搜索词；竞品主要作为现有结构化标注维度。
- 详情获取后，对 `title + selftext + comments` 的合并文本再次执行当前匹配器；不符合当前口径或命中排除词的候选不进入最终结构化实体。
- 每次运行把解析后的搜索词、subreddit 列表和关键词配置 SHA-256 写入 manifest，防止配置漂移被误认为同口径回放。

## 5. 架构

### 5.1 独立执行单元

#### A. HistoricalRawImporter

- 输入：已有 Reddit `.json` thread payload 文件。
- 职责：校验 JSON、解析 thread/comments、日期过滤、关键词复核、生成 run-scoped raw capture ID、写入 staging DB。
- 输出：seed import summary、文件级 manifest、结构化 thread/comment/analysis。
- 失败边界：单文件解析失败会记录文件 hash 和错误，不静默跳过；只要存在解析失败，seed 阶段不得标记 complete。

#### B. TikHubBackfillDiscoverer

- 输入：冻结后的搜索词、subreddit、目标时间窗、请求预算和 checkpoint。
- Dynamic search 参数：`search_type=post`、`sort=NEW`、`time_range=all`、`after=<cursor>`、`need_format=false`。
- Subreddit feed 参数：`sort=NEW`、`after=<cursor>`、`need_format=false`。
- 职责：提取 post ID、创建时间、来源 lane 和 next cursor；跨搜索词、社区和页面按 post ID 去重。
- Dynamic search 是必跑 lane；subreddit feed 是扩大召回 lane，在探针完成并获得请求预算后运行。
- 停止条件：next cursor 为空，或在 `NEW` 排序下连续两页的最新帖子都早于窗口开始时间。
- 非完成条件：请求预算耗尽、cursor 重复、响应缺少可解释的分页结构、鉴权失败或响应 schema 漂移。

#### C. TikHubDetailHydrator

- 输入：落在目标窗口、尚未结构化的去重 post IDs。
- 每批详情最多 30 帖。
- 每帖按 `fetch_post_comments` 的 `after` 游标翻页，直到 cursor 为空。
- 合并多页评论时按 comment ID 去重并保留层级、parent ID 和删除状态。
- 未能展开的 `more`/nested cursor 必须增加 unresolved counter，并使该 thread 的 coverage 不高于 `partial`。
- 详情或评论未完整获取时保留可用数据，但整体 run 状态为 `partial`。

#### D. PrivateRawArchive

- 位置：独立 backfill 数据目录下的非公开路径，不放入网站 `/artifacts/`。
- 保存内容：seed 原始文件、TikHub discovery 页、详情批次、评论页及对应 metadata。
- 文件名不包含作者名或正文片段，只使用 run、lane、页序号、post/batch identity hash。
- 每个文件记录相对路径、SHA-256、字节数、压缩格式、来源 endpoint 和采集时间。
- 不保存 Authorization header、API key、runtime env 或 webhook。

#### E. BackfillStore

- 使用独立 SQLite，例如 `data/reddit_voc_backfill_20250101_20260711.sqlite3`。
- 整个首次回填使用一个 umbrella `run_id`，分页、seed 和 detail hydration 不拆成互相覆盖的 run。
- 保留现有 runs/raw/thread/comment/analysis 表以复用导出和校验能力。
- 增加仅服务 backfill 的 manifest、checkpoint、raw artifact metadata 和 issue 记录。
- 新的 raw capture ID 必须包含 `run_id + source_method + source_url + payload_hash`，避免相同 payload 跨 run 复用旧 raw lineage。

#### F. ProductionMerge

- 输入：验收通过的 staging DB、只读生产基线和生产 DB 备份。
- 在单个 SQLite transaction 内执行 insert-only 合并。
- 对已存在的 `post_id`、`comment_id`、`analysis_id` 不执行 update；冲突写入 merge manifest。
- 只合并被新 thread/comment 引用的 raw captures，避免孤儿 capture。
- 任何 lineage、外键式关系或计数检查失败时整体 rollback。
- 生产 merge 是独立授权动作，不属于首次 staging backfill 自动步骤。

### 5.2 数据流

```text
existing raw JSON ──> seed importer ────────────────┐
                                                    │
TikHub search/feed ──> cursor checkpoint ──> dedupe ├─> detail batches
                                                    │        │
                                                    │        └─> comment pages
                                                    │
                                                    └─> private raw archive
                                                             │
                                                             v
                                                     staging SQLite
                                                             │
                                                             v
                                                validation + replay check
                                                             │
                                                separately authorized merge
                                                             │
                                                             v
                                              production insert-only entities
```

## 6. Backfill 状态与断点续跑

运行状态：

- `prepared`：配置和窗口已冻结，未发 Provider 请求。
- `seed_complete`：已有原始 JSON 已完整导入并通过 seed 验收。
- `running`：Provider 分页或详情 hydration 正在运行。
- `partial`：已保留部分有效数据，但分页、预算、详情或评论存在未完成项。
- `success`：所有必跑搜索 lane 达到可解释终点，所有候选都有明确处理结果，且完整性检查通过。
- `blocked`：缺少运行门禁、API key、明确请求预算或运行环境。
- `failed`：响应不可解析、鉴权失败、持久化失败或不变量检查失败。

Checkpoint 至少记录：

- run ID
- lane 类型和 lane key
- 当前 cursor、页序号和上一 cursor
- 已见最老/最新帖子时间
- 已发现及已去重 post 数
- Provider request count
- 最近成功时间和最近错误
- lane 状态与停止原因

恢复执行从最后一个已提交 checkpoint 继续，不清除已导入数据。相同页面或实体重放必须由 hash 和主键去重。

## 7. Provider 请求控制与错误处理

- 合约探针硬限制为 4 次 Provider 请求，只验证 dynamic search 两页、cursor 提取和响应 schema，不写生产库。
- 完整运行必须显式提供 `max_provider_requests`；无预算不启动。
- 每次请求先原子增加 request counter，再发送请求，防止崩溃后超预算。
- 对网络错误、HTTP 429 和 HTTP 5xx 最多重试 3 次，等待 2、4、8 秒。
- HTTP 401、403、422 不重试，立即记录并停止对应 lane。
- 相同 cursor 第二次出现立即停止并标记 `cursor_loop`。
- 响应 JSON 不符合已验证 schema 时保存脱敏 raw response，标记 `schema_drift`，不得尝试猜测字段后继续。
- 请求预算耗尽时持久化 checkpoint，状态为 `partial`，不标记 success。

## 8. 推送隔离

- Backfill CLI 不调用或导入任何 send command。
- Server wrapper 只向容器传 TikHub、窗口、数据库、输出和预算变量，不传 `DINGTALK_*`。
- 不调用 `server_daily_cycle.sh`；该脚本在 collect 后会进入 report 阶段。
- 所有 backfill summary 固定包含 `live_send=false`。
- 验收需扫描本次运行的 delivery 表增量为 0，并确认没有 `*-live-send.json` 新产物。

## 9. 验收标准

### 9.1 Seed 阶段

- 输入文件 55 个全部有 manifest 结果。
- 目标窗口内 exactly 48 threads、1,894 comments。
- 窗口外 7 threads 不进入结构化表。
- parse failures 为 0。
- 45 个 `full`、3 个 `partial` 的已知 coverage 基线可重现。
- 所有目标 thread 均通过当前关键词口径复核。

### 9.2 Provider 阶段

- 每个必跑 search term 都有终止原因：`cursor_exhausted` 或 `older_than_window`。
- 所有 cursor 单调推进，无 cursor loop。
- `discovered = outside_window + excluded + duplicate + hydrated + failed_or_truncated` 可核对。
- 每个详情候选都有 hydrated、excluded、failed 或 budget-deferred 状态。
- 每个评论 lane 有 cursor 终点或明确 partial 原因。
- Provider request count 不超过显式预算。

### 9.3 数据完整性

- thread、comment、analysis 到 raw/run 的缺失或跨 run lineage 为 0。
- comment 找不到所属 thread 为 0。
- post analysis 数等于 thread 数，comment analysis 数等于 comment 数。
- thread 的 `parsed_comment_count` 等于同 run 实际 comment 数。
- 所有 thread 创建时间落在 `[window_start, effective_end)`。
- 重复执行到两个全新 staging DB 后，post/comment ID 集合、raw hash 集合和结构化计数一致。
- `success` run 中不存在 budget exhaustion、unresolved required lane、schema drift 或未解释 truncation。

### 9.4 推送与生产边界

- `live_send=false`。
- delivery 增量为 0。
- DingTalk、报告、翻译和网站链路均未执行。
- Staging 验收完成前 `production unchanged`。
- 生产 merge 必须有独立备份、授权、transaction rollback 和只读 postcheck 证据。

## 10. 测试策略

- 时间窗口：北京时间到 UTC 转换、左闭右开边界、首次执行时刻和次日余量补采。
- Seed importer：55 文件基线、窗口过滤、comment-only 命中、解析失败 fail-fast、重放幂等。
- Cursor：第一页、下一页、空 cursor、重复 cursor、跨页重复 post、连续两页越过下界。
- 请求预算：预算恰好用完、重试计数、预算耗尽 checkpoint、恢复后不重复计费。
- Hydration：30-ID 批次、评论多页合并、comment ID 去重、unresolved more 降级。
- Raw archive：hash 校验、文件路径安全、无 secret、可重放。
- Storage：同一 umbrella run 重放不迁移 lineage；raw/thread/comment/analysis 不产生孤儿。
- Merge：insert-only、冲突清单、失败 rollback、生产原有 run 计数不下降。
- 推送隔离：backfill 命令路径无法触达 report/send，delivery 增量为 0。

## 11. 执行顺序

1. 写失败测试，覆盖日期、seed importer、cursor、预算、checkpoint、raw archive 和 insert-only merge。
2. 实现最小 backfill 组件并跑定向测试及完整测试。
3. 建立独立 staging DB，导入已知 48 帖、1,894 评论并完成 seed 验收。
4. 使用 repo 外 runtime env 执行最多 4 请求的 TikHub 合约探针，确认真实 cursor 路径和响应 schema。
5. 根据探针统计请求密度，计算 dynamic search 和 subreddit sweep 的请求预算；预算不足时停在 `blocked` 等待授权。
6. 在显式预算内执行完整 staging backfill，支持断点续跑。
7. 生成完整性、覆盖率、请求、cursor 终止原因和幂等重放验收报告。
8. 若目标是完整覆盖 2026-07-11，自北京时间 2026-07-12 00:05 起执行余量补采并重复验收。
9. 单独批准后，备份并以 insert-only transaction 合并生产库，再做只读 postcheck。

## 12. 当前证据状态

- `production unchanged`
- `provider_call=false`
- `live_send=false`
- 本轮已完成生产只读聚合检查、源码调用链审查、官方 TikHub 合约核对及 17 项定向测试。
- 系统 Python 缺少 Pillow；使用项目既有 bundled Python 后同一测试集 17 项通过，因此该失败属于解释器依赖环境差异，不是业务断言失败。
