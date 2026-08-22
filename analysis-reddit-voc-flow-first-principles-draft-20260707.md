---
title: Reddit VOC 数据采集-提取-洞察流程深度分析
doc_type: analysis
module: automation
topic: reddit-voc-flow
status: draft
created: 2026-07-07
updated: 2026-07-07
owner: self
source: codex
evidence_level: L1-repo-analysis
production_boundary: production unchanged
provider_call: false
---

# Reddit VOC 数据采集-提取-洞察流程深度分析

## 0. 结论边界

### 已验证事实

1. 当前仓库没有 `reddit` 专属 collector、专属 Dataset 类型或专属情感/主题分析服务。
2. 当前稳定 collector 是 `github_repo`、`github_topic`、`generic_web`、`public_feed`、`manual_json`、`ecommerce_product_discovery`、`ecommerce_product_page`。
3. 当前 PRD2 把 Reddit 放在 P2 边界：`Reddit 聚合趋势`，默认路径是 SOP/import-only 或明确授权 read-only，不采个人级画像。
4. 当前平台包 `public-web-rss-docs` 已能把 `public_feed` 和 `generic_web` 采集结果转换为 `public_content_update` DatasetVersion，并支持 content hash drift、drift event、只读 report preview 和 Report asset。
5. `manual_json` 可以导入人工或外部工具结构化样本，并通过 RawRecord -> EntitySnapshot 链路沉淀为实体快照；但当前没有把 `manual_json` 直接转换为 `public_content_update` 或 `reddit_voc` Dataset 的专用服务。

### 基于事实的推断

当前项目处理 Reddit VOC 的稳健路线不是“直接写 Reddit 爬虫”，而是把 Reddit 当作高风险社区平台，先走聚合/导入/明确授权只读，再复用统一证据链：

```text
授权边界
-> public_feed / generic_web / manual_json / future ExternalToolSnapshot
-> RawRecord
-> EntitySnapshot
-> DatasetVersion 或 Signal
-> Evidence
-> Report / Alert
```

### 不确定项

1. 当前没有验证任何真实 Reddit URL、Reddit API、Reddit RSS 或外部 Reddit 导出文件。
2. 当前没有生产 read-only Reddit gate，也没有 authorized live Reddit execution。
3. 当前没有 Reddit VOC 专用字段合同，如 `subreddit`、`post_id`、`comment_id`、`pain_point`、`purchase_intent`、`feature_request`、`sentiment`。
4. 当前没有内置 NLP 情感、主题聚类、意图分类或 VOC 去重服务；如果报告需要这些洞察，需要新增本地分析层或受控 provider gate。

## 1. 第一性原理：VOC 流程不是爬虫问题，而是证据链问题

Reddit VOC 的目标不是“拿到尽可能多的帖子/评论”，而是以最小合规风险回答业务问题：

```text
用户在公开社区表达了什么问题？
哪些问题重复出现？
哪些问题和购买、退货、竞品、功能缺陷、使用场景相关？
这些结论能否追溯到原始公开证据？
```

因此系统设计应从四个不可变约束出发。

| 约束 | 对 Reddit VOC 的含义 | 当前项目承接方式 |
|---|---|---|
| 授权优先 | 不默认进入登录态、评论区批采、cookie 复用或反检测 | PRD2 明确 Reddit 先 SOP/import-only 或授权 read-only |
| 原始证据不可丢 | 洞察必须能回溯到 URL、RawRecord、content_hash、TaskRun | RawRecord 保存 content、source_url、content_hash、collected_at |
| 结构化字段可复用 | 每次采集都应产生稳定字段，而不是只保留页面文本 | public content Dataset 使用 link、title、time、summary、content_hash 等字段 |
| 洞察不新增事实 | LLM/报告只能总结已有证据，不能凭空判断 | Intelligence/Evidence 由 Signal、Snapshot、RawRecord 构建 |

这意味着 Reddit VOC 的合理最小单元不是“用户”，而是“公开内容条目”或“聚合讨论单元”：

```text
reddit_voc_item = {
  external_id,
  source_url,
  subreddit_or_topic,
  title,
  body_or_summary,
  published_at,
  updated_at,
  score_or_engagement,
  comment_count,
  tags,
  content_hash,
  evidence_boundary
}
```

作者字段如必须保留，也应只作为去重或来源上下文字段，默认不做人级画像，不做跨平台身份拼接。

## 2. 当前系统的事实链路

### 2.1 主链路

README、架构文档和代码都围绕同一条链：

```text
Source
-> CollectionTask
-> TaskRun
-> RawRecord
-> EntitySnapshot
-> Signal
-> IntelligenceItem
-> Evidence
-> Report / Alert / Notification
```

执行采集时，`execute_collection_task` 会：

1. 锁定 task，避免并发重复运行。
2. 合并 Source 和 Task config，实例化 collector。
3. 执行 collector，得到 `CollectorRawRecord[]`。
4. 对 RawRecord 计算 content hash，并按 `source_id + content_hash` 去重。
5. 写入 RawRecord。
6. 调用 normalization 生成 EntitySnapshot。
7. 调用 signal service 检测变化。
8. 由 signal 生成 Intelligence 和 Evidence。

这条链路对 Reddit 的意义是：不管 Reddit 数据来自 feed、静态页面还是人工导入，只要能进入 RawRecord，就能获得基本追溯能力。

### 2.2 RawRecord 是事实入口

`RawRecord` 保存：

- `record_type`
- `source_url`
- `content`
- `content_hash`
- `screenshot_url`
- `collected_at`
- `task_run_id`

Reddit VOC 中最关键的是 `content_hash` 和 `source_url`：前者用于去重/漂移，后者用于证据回溯。

### 2.3 EntitySnapshot 是可比较状态

Normalization 层把 RawRecord 变成实体快照：

- `generic_web` -> `web_page`
- `public_feed` -> `public_feed`
- `manual_json` -> `entity_type` 指定的实体，payload list 会拆成多个实体

对 Reddit 来说，推荐的 `manual_json.entity_type` 可以是：

- `reddit_voc_item`
- `reddit_thread`
- `reddit_topic_cluster`
- `community_signal`

当前代码会从 payload 的 `external_id`、`id`、`url`、`name`、`title` 等字段里选 external_id，并自动抽取数值字段为 metrics。因此 `score`、`comment_count`、`upvote_ratio`、`mention_count` 这类字段可以先进入 metrics，但当前不会自动生成 Reddit 专用 signal。

## 3. Reddit VOC 的采集方法

### 3.1 方法 A：`manual_json` 授权导入，推荐作为 Reddit MVP 主路径

适用场景：

- 运营或研究人员已经通过合规方式获得 Reddit 样本。
- 数据来自官方 API、授权导出、人工审核样本或外部工具结果。
- 需要保留结构化字段，而不是抓取页面 HTML。

最小 payload 形态：

```json
{
  "entity_type": "reddit_voc_item",
  "json_data": [
    {
      "external_id": "reddit-post-or-comment-id",
      "url": "https://www.reddit.com/...",
      "subreddit": "example_subreddit",
      "title": "Post title",
      "body": "User text or reviewed excerpt",
      "published_at": "2026-07-07T00:00:00Z",
      "score": 128,
      "comment_count": 42,
      "tags": ["pain_point", "competitor_mention"],
      "content_hash": "source-or-import-generated-hash"
    }
  ]
}
```

当前链路会形成：

```text
manual_json CollectorRawRecord
-> RawRecord(record_type=manual_json)
-> EntitySnapshot(entity_type=reddit_voc_item)
-> metrics(score/comment_count 等数值字段)
```

优点：

1. 合规边界清楚，避免默认页面批采。
2. 字段稳定，适合 VOC 后续 NLP。
3. 可保留人工审核状态和来源说明。

限制：

1. 当前没有 `manual_json -> public_content_update DatasetVersion` 的专用转换。
2. 当前没有 Reddit 专用 drift 或 insight service。
3. 需要后续补 `ExternalToolSnapshot` 或 `reddit_aggregate_import` Dataset 保存链路。

### 3.2 方法 B：`public_feed` 公开 RSS/Atom 更新监控，适合作为聚合趋势路径

适用场景：

- 操作者提供的是公开 RSS/Atom feed。
- 目标是监控公开内容更新，不进入登录态、私信、付费墙、验证码或评论区。
- 业务问题偏“趋势/新增讨论/内容变化”，不是深层评论语义分析。

当前 `public_feed` 输出字段包括：

- `feed_url`
- `feed_type`
- `title`
- `site_url`
- `entries[]`
- entry 的 `title`、`link`、`published_at`、`updated_at`、`author`、`tags`、`summary`、`content_hash`

随后可进入：

```text
public_feed TaskRun
-> public-content-dataset-preview
-> public_content_update DatasetVersion
-> public-content-drift-check
-> public_content_drift event
-> public-content-report preview / asset
```

对 Reddit 的解释：如果存在经授权确认的公开 feed，它可以被视为“社区公开内容更新流”，但不能因此推断评论区、个人主页、登录态内容也可采。

### 3.3 方法 C：`generic_web` 公开页面 hash 监控，仅适合页面级变化

适用场景：

- 页面公开、匿名可访问、没有登录墙/验证码/付费墙。
- 只需要页面标题、正文摘要、页面 content hash、更新时间。
- 用于监控 subreddit wiki、公告页、公开文档或静态页面变化。

当前 `generic_web` 输出：

- `schema_version=generic_web.v1`
- `url`
- `title`
- `text_content`
- `text_length`
- `content_hash`
- `html_content`
- `provenance.public_url_checked=true`

限制：

1. Reddit 动态评论页可能强依赖交互脚本，`generic_web` 不保证能复现真实浏览器内容。
2. 平台包明确阻断登录态、评论区和个人画像采集。
3. 这条路径适合“页面变化监控”，不适合“完整评论 VOC 抽取”。

### 3.4 方法 D：Browser Diagnostic 只读预检，不是采集

Browser Diagnostic 可以作为页面结构诊断和 selector/network metadata 证据，但当前合同要求：

- `run_started=false` 或受控本地 run。
- `collection_resources_written=false`。
- 不创建 Source/Task/TaskRun/Dataset。
- 不导出 cookie，不保存 headers/body。
- 不复用用户主 Chrome profile。

对 Reddit 的用途：只能回答“这个页面是否适合后续授权采集/导入”，不能直接作为 Reddit VOC 采集完成证据。

## 4. Reddit VOC 的提取方法

### 4.1 字段提取的当前能力

当前公开内容 Dataset 支持字段：

- `title`
- `link`
- `published_at`
- `updated_at`
- `author`
- `tags`
- `summary`
- `content_hash`
- `feed_url`
- `feed_title`
- `feed_type`
- `site_url`
- `source_type`
- `content_kind`
- `text_length`

其中 `link` 是主键，`content_hash` 是 drift signal。

对 Reddit VOC 来说，这套字段可以承接“公开内容更新监控”，但还不足以承接完整 VOC。完整 VOC 需要补充：

- `subreddit`
- `thread_url`
- `post_id`
- `comment_id`
- `parent_id`
- `body`
- `language`
- `score`
- `comment_count`
- `topic`
- `sentiment`
- `intent`
- `pain_point`
- `feature_request`
- `competitor_mention`
- `product_mention`
- `moderation_or_deleted_status`
- `privacy_boundary`

### 4.2 清洗策略

当前 public content 清洗草案体现了几个原则：

1. 清理 title、author、feed_title 空白。
2. 标准化 link 和 feed_url。
3. 保留 published_at / updated_at 原始时间语义。
4. tags 归一为小写数组。
5. 用 content_hash 识别相同链接下内容变化。
6. 保留 source_type 和 content_kind，区分 feed 与 page snapshot。
7. 缺失值显式保留为 null。

Reddit VOC 应沿用这些原则，并增加三条：

1. 作者字段默认不作为分析主体；如保留，需脱敏或只用于单条证据上下文。
2. 删除/隐藏/版主管理状态不能当作用户观点本身，需要单独字段。
3. 主题、情感、意图属于推断字段，必须和原文证据分层存储。

### 4.3 去重策略

当前 RawRecord 按 `source_id + content_hash` 去重。Reddit VOC 还应增加业务级去重：

| 层级 | 推荐 key | 目的 |
|---|---|---|
| 原始记录 | `source_id + content_hash` | 避免重复写入相同采集结果 |
| 内容条目 | `platform + post_id/comment_id` | 避免同一条 Reddit 内容多次进入 VOC |
| 文本语义 | `normalized_text_hash` | 合并跨贴复制粘贴、模板化抱怨 |
| 洞察主题 | `topic + product + time_bucket` | 聚合重复痛点 |

当前项目只覆盖第一层，第二到第四层属于 Reddit 专用扩展。

## 5. Reddit VOC 的洞察方法

### 5.1 当前已实现的洞察能力

当前项目有两类可复用洞察机制。

第一类是 Signal -> Intelligence -> Evidence：

- `page_changed`：对 `web_page` content hash 变化生成 signal。
- `star_growth`：对 GitHub repo star 增长生成 signal。
- `data_quality_anomaly`：对采集失败率/连续失败生成 signal。
- Intelligence 根据 impact/confidence/novelty/urgency 评分。
- Evidence 绑定 signal、snapshot、raw_record、url。

第二类是 public content Dataset -> drift/report：

- `content_added`
- `content_removed`
- `content_hash_changed`
- `completeness_drift_exceeded`
- `approved_fields_missing`
- `freshness_target_missed`
- public-content report 汇总 entry_count、feed_count、unique_author_count、tagged_entry_count、entries_with_summary、content_hash_count，并生成风险边界。

### 5.2 对 Reddit VOC 的可用洞察

在不新增 NLP 的情况下，当前系统可以产生的 Reddit 相关洞察主要是“结构性/变化型”：

| 洞察 | 可用入口 | 当前能否支持 | 说明 |
|---|---|---|---|
| 新讨论出现 | `public_feed` | 可支持，需公开 feed 和授权 | `content_added` |
| 讨论消失或链接不再出现 | `public_feed` | 可支持 | `content_removed` |
| 同一链接内容摘要变化 | `public_feed` / `generic_web` | 可支持 | `content_hash_changed` |
| 页面内容变化 | `generic_web` | 可支持 | `page_changed` 或 public-content drift |
| 采集健康异常 | 任意 collector | 可支持 | `data_quality_anomaly` |
| 高频痛点 | `manual_json` + 新增聚合 | 当前不支持，需要扩展 | 需要 topic/pain_point 字段 |
| 情感趋势 | `manual_json` + NLP | 当前不支持，需要扩展 | 需要 sentiment pipeline |
| 购买/退货/竞品意图 | `manual_json` + NLP/规则 | 当前不支持，需要扩展 | 需要 intent taxonomy |

### 5.3 推荐的 Reddit VOC 洞察模型

Reddit VOC 的洞察应拆成三层。

#### L1 证据层：不做语义推断

保存每条公开/授权内容的事实字段：

```text
url, title, body_or_summary, subreddit/topic, published_at, score, comment_count, content_hash
```

#### L2 结构层：可解释规则

从事实字段计算：

```text
mention_count, duplicate_count, engagement_bucket, freshness_bucket, source_coverage
```

#### L3 语义层：需单独 gate

通过本地规则或受控 provider 生成：

```text
sentiment, pain_point, feature_request, competitor_mention, purchase_intent, severity
```

L3 字段必须记录：

- `model_or_rule_version`
- `evidence_raw_record_id`
- `confidence`
- `manual_review_status`
- `provider_call` 状态

## 6. 案例

### 案例 1：公开 feed 到内容漂移报告，已由测试验证，可迁移到 Reddit 聚合趋势

测试样例使用 `public_feed`：

1. 创建 `public_feed` Source。
2. 启用 Task。
3. 第一次 TaskRun 返回两条公开内容。
4. 保存 `public_content_update` DatasetVersion，`row_count=2`。
5. 第二次 TaskRun 中一条内容变更、一条消失、一条新增。
6. `public-content-drift-check` 返回：
   - `added_rows=1`
   - `removed_rows=1`
   - `content_hash` drift=1
   - `run_started=false`
   - `alert_created=false`
7. 保存 `public_content_drift` event。
8. 生成 public-content report preview。
9. 在显式 confirm 下创建 Report asset，并通过 idempotency key 防重复。

迁移到 Reddit 时，这个案例对应：

```text
公开 Reddit 聚合更新源
-> 新帖子/新讨论出现
-> 某讨论摘要或标题 hash 改变
-> 某讨论从 feed 消失
-> 生成“Reddit 聚合趋势变化”报告
```

边界：这不是评论全文 VOC，不代表 Reddit 登录态或评论区批采已授权。

### 案例 2：公开页面 hash 监控，已由测试验证，可用于 Reddit 公告/wiki/静态页

测试样例使用 `generic_web`：

1. 创建 `generic_web` Source。
2. 第一次 TaskRun 采集公开 docs page。
3. 保存 `public_content_update` DatasetVersion，`row_count=1`。
4. 第二次 TaskRun 改变页面正文，link 不变。
5. drift check 返回 `content_hash_changed`，`row_change=unchanged`。
6. 保存 `public_content_drift` event。
7. 生成 public-content report / Report asset。

迁移到 Reddit 时，这个案例只适合：

- subreddit wiki
- 公开规则页
- 公开公告页
- 公开静态列表页

不适合：

- 无限滚动评论区
- 登录态页面
- 需要用户画像的评论网络
- 反检测或验证码页面

### 案例 3：授权 Reddit JSON 导入，当前是推荐方案但未闭环到专用 Dataset

推荐步骤：

1. 业务方定义问题：例如“某类产品在 Reddit 上的主要抱怨和购买阻力是什么？”
2. 人工或授权工具获得样本 JSON。
3. 用 `manual_json` 导入：
   - `entity_type=reddit_voc_item`
   - payload list 每项是一条 post/comment 或聚合后的 thread。
4. 系统生成 RawRecord 和 EntitySnapshot。
5. 后续扩展一个 `reddit_aggregate_import` Dataset save：
   - `dataset_type=reddit_voc_aggregate`
   - `primary_key=external_id or url`
   - `drift_signal=content_hash`
   - `fields=subreddit,title,body,score,comment_count,tags,sentiment,pain_point`
6. 生成 VOC report：
   - 高频痛点
   - 新增痛点
   - 情感分布
   - 竞品提及
   - 证据 URL 列表

当前缺口：第 5、6 步不是现有代码能力，需要新增。

## 7. 推荐落地方案

### Phase 1：不新增爬虫，先做 Reddit 导入合同

目标：把 Reddit VOC 样本接进证据链。

建议实现：

1. 新增 `reddit_voc_import.v1` 字段合同文档。
2. 复用 `manual_json` 作为入口。
3. 增加 `reddit_voc_item` 示例 payload 和测试。
4. 报告里明确：
   - `provider_call=false`
   - `production unchanged`
   - `no live Reddit read`
   - `manual review required`

验收：

1. `manual_json` 导入样本后能生成多个 EntitySnapshot。
2. 每个 EntitySnapshot 可回溯 RawRecord。
3. 作者字段默认可省略或脱敏。

### Phase 2：新增 Reddit VOC Dataset 保存服务

目标：把 `manual_json` Reddit 样本变成可导出、可漂移、可报告的 DatasetVersion。

建议新增：

```text
POST /api/automation/reddit-voc-dataset-preview
POST /api/automation/reddit-voc-dataset-save
POST /api/automation/reddit-voc-drift-check
POST /api/automation/reddit-voc-report
```

字段：

```text
source_url, subreddit, title, body_or_summary, published_at,
score, comment_count, tags, content_hash,
sentiment, pain_point, feature_request, competitor_mention,
manual_review_status
```

### Phase 3：受控语义洞察

目标：从“内容更新”升级到“VOC 洞察”。

推荐先用本地规则/词表：

- pain point taxonomy
- competitor mention dictionary
- purchase/return intent phrase list
- feature request pattern

然后再考虑 provider gate：

- 每次 provider call 必须有授权。
- 输出只写 semantic fields，不覆盖原文事实。
- 保留 prompt/schema/model/version。

## 8. 风险清单

| 风险 | 触发条件 | 处理方式 |
|---|---|---|
| 把 Reddit 当普通网页抓取 | 直接用 `generic_web` 批采评论区 | 停止，改 import-only 或明确授权 read-only |
| 登录态/403 风险 | 需要账号、cookie、代理、反检测 | 不进入自动采集；只做 SOP/import |
| 个人画像风险 | 跨贴聚合作者、追踪用户行为 | 禁止个人级画像；作者字段最小化 |
| 洞察无证据 | 报告输出痛点但无 RawRecord/URL | 必须绑定 Evidence |
| LLM 编造事实 | 语义层直接生成结论 | 语义字段必须绑定原文和置信度 |
| 重复样本污染趋势 | 同一 post/comment 多次导入 | 增加 external_id/content hash 去重 |
| 把 draft 当完成 | 只有方案文档没有测试 | 明确 `draft`、`L1-repo-analysis`、`production unchanged` |

## 9. 一句话方法论

当前项目对 Reddit VOC 的正确方法是：

> 先把 Reddit 当作高风险社区数据源，使用授权导入或公开聚合更新源获得最小事实样本；再用 RawRecord 保留原始证据，用 EntitySnapshot/DatasetVersion 固化结构化字段，用 content_hash 和 link/external_id 做去重与漂移，用 Evidence 绑定每条洞察，最后只在可追溯证据范围内生成报告。

## 10. 证据索引

| 证据 | 路径 |
|---|---|
| 项目核心链路 | `README.md`、`.Codex/context-pack.md` |
| PRD2 Reddit 边界 | `docs/product/product-prd-data-intelligence-hub-stable.md` |
| 平台采集执行计划 M6-2 | `docs/workflows/workflow-prd2-platform-collection-execution-plan-stable.md` |
| 稳定 collector 合同 | `docs/api/api-contract-data-intelligence-hub-stable.md`、`apps/api/src/data_intelligence_hub/services/collector_catalog.py` |
| RawRecord 写入、去重、normalize、signal 链路 | `apps/api/src/data_intelligence_hub/services/collector_service.py` |
| manual_json normalization | `apps/api/src/data_intelligence_hub/services/normalization_service.py` |
| public content Dataset/drift/report | `apps/api/src/data_intelligence_hub/services/automation_service.py` |
| public_feed/generic_web 案例测试 | `apps/api/tests/integration/test_sources_tasks.py` |
| manual_json/generic_web normalization 测试 | `apps/api/tests/unit/test_normalization.py` |

