# Echo-Agent 数据模型方案（七层）

- **状态**: 待评审
- **日期**: 2026-10-27
- **作者**: Echo-Agent 研发
- **依据**: 七层并行代码审计（7 个审计单元、846 次工具调用、171 万 token）+ 两次线上采集探测
- **前置**: ADR-001（多 Agent 架构）、ADR-002（数据时效与派生重算）

---

## 0. 先给结论：三件必须先接受的事实

### 0.1 补采 74 天空洞，用当前 Apify actor 做不到（已实测，两条路径都失败）

| 探测 | 参数 | 结果 |
|---|---|---|
| 搜索路径 | 12 查询词，`maxItems=500`，`postDateLimit=2026-07-20` | 返回帖子最早 **2026-10-06**，空洞内 0 条 |
| 列表路径 | 7 个 subreddit `/new/`，`maxItems=800`，`postDateLimit=2026-07-20` | 返回帖子 **2026-10-26 .. 10-27**，空洞内 0 条 |

关键认知修正：

- `maxItems` 是**全局预算**，不是深度。加到 500/800 只是把"最新 N 条"这条线拉长，拉不到 3 个月前。
- 列表页的深度由 `scrollTimeout` 控制（页面持续滚动的秒数），`maxItems` 只是上限。两次探测都远未跑满预算（500 → 265 条；800 → 393 条），说明**卡在滚动深度/分页，不是预算**。
- 因此「继续放大采集参数」对补采无效，只对**当日采样宽度**有效。

### 0.2 仓库里已经有能做补采的引擎，但缺凭据

`src/reddit_voc/backfill_provider.py:308` 的 `TikHubBackfillDiscoverer` 是唯一具备回溯能力的采集器：

- 游标分页 + 持久化 checkpoint（`:618-620`）
- `time_range: "all"`（`:690`）——真正的历史回溯参数
- 预算预留、评论游标分页与逐页归档（`:1494-1935`）
- 连续两页全部早于窗口起点即停止（`older_than_window`）

**但它没有接进日常流水线，而且服务器上没有任何 TikHub 凭据**（`/etc/systemd/system/echo-agent-daily.service` 中 `TIKHUB` 出现 0 次，无 `.env`）。此前实测 TikHub 上游返回 HTTP 400。

→ **补采的前置条件是拿到可用的 TikHub key**，不是改参数。这是业务侧输入，我无法自行解决。

### 0.3 当前"可用指标数"在下降，而发布门禁没有察觉

审计实测：报告数据集 `current_available` 从 7 月的 21 降到 9，`year_over_year` 全部不可用，但 release 仍标记为 `validated / promotable`。流水线只管"进程成功"，不管"指标质量下降"。

---

## 1. 七层现状总览

| # | 层 | 现状一句话 | 最严重的问题 |
|---|---|---|---|
| 1 | 采集 | 4 条互不共享模型的入库路径，Apify 只取"最新 N 条" | 无日期窗口、无覆盖账本、原始 payload 不落盘 |
| 2 | 存储 | SQLite 与公开 JSON 双写，整文件重写 | 只有"当前值"，没有"何时观测到何值" |
| 3 | 打标 | 纯子串规则，单一 `brand_binding` 枚举 | 对比语料被自己的过滤规则删除 |
| 4 | 指标 | 26 个指标 ID，真算 4 个 | 同一 metric_id 在不同数据集口径不同 |
| 5 | 分析 | 只有计数与排名 | 竞品/GEO 在数据模型上不可能成立 |
| 6 | 呈现 | 双端重复定义严格契约 | 任一处不符整页拒渲染 |
| 7 | 洞察 | 三个 Agent 上线跑确定性 fallback | 无证据锚点、无质量评估、无反馈闭环 |

---

## 2. 采集层

### 2.1 现状（有证据）

**四条入库路径，只有两条接了调度器：**

| 路径 | 入口 | 分页 | 日期窗口 | 原始 payload |
|---|---|---|---|---|
| TikHub 日常 | `scripts/run_daily_collect.sh` → `cli.py run-tikhub-collector` | ❌ 单页 | ✅ 24h 窗口过滤 | ✅ 落盘 + manifest |
| Apify T-1 | `scripts/run_daily_t1_pipeline.py:53-94` | ❌ 单次 run | ❌ **完全不用窗口** | ❌ **只存哈希** |
| TikHub 回溯 | `backfill_provider.py:308` | ✅ 游标+检查点 | ✅ `time_range=all` | ✅ 逐页归档 |
| 浏览器/RSS | `adapters.py` | — | — | — |

**Apify 路径的具体缺陷**（`src/reddit_voc/apify_collector.py`）：

1. `:95` 算了 `daily_window` 却**从不使用**——只写进 `runs` 行。
2. `:106-112` 只发 `searches / maxItems / maxComments / sort / type`，**没有 `postDateLimit`**（该字段在 actor schema 里存在）。
3. `:146-220` 不按 `created_at` 过滤，返回什么入什么。
4. `:138-140` 只有传了 `raw_artifact_root` 才落盘；生产调用（`run_daily_t1_pipeline.py:65-85`）没传 → **原始响应不可恢复、不可重解析**。
5. `:66-75` 轮询超时仍 `RUNNING` 时**继续用部分数据集并标 success**。
6. `:166-170 / :199-207` 时间戳缺失时**伪造为采集时刻**。
7. `:187` `coverage_grade="full" if len(post_comments)>0` —— 有一条评论就算"完整"，下游当真。
8. `:144-155` 父帖不在同批次的评论**静默丢弃**。
9. `:127` `raw_capture_id` 用 `run_id[:16]`，而 `run_id=daily_collect_20261027_0700` 截 16 位后同一天重跑**撞 ID**。
10. 无重试、无退避、无成本核算、无 `maxTotalChargeUsd` 上限。

**没有任何覆盖账本**：74 天空洞对所有产物不可见。

### 2.2 设计：采集计划 → 分片执行 → 覆盖账本

引入三个一等对象。

```python
# 1. 采集计划（执行前生成、可哈希、可版本化）
CollectionPlan {
  plan_id: str                    # sha256(规范化 JSON)
  created_at_utc: datetime
  provider: "apify" | "tikhub"
  provider_actor: str | None      # "trudax~reddit-scraper-lite"
  mode: "incremental" | "backfill"
  date_from: date                 # Asia/Shanghai 自然日
  date_to: date
  lanes: [CollectionLane]         # 见下
  budget: {max_items: int, max_cost_usd: float, max_wall_seconds: int}
  code_version: str               # git sha
  query_profile_sha256: str       # 查询集的哈希
  parser_version: str
}

# 2. 采集分片（一条查询 × 一个日期区间 = 一个可重试单元）
CollectionLane {
  lane_id: str                    # f"{plan_id[:8]}:{query_slug}:{date_from}:{date_to}"
  kind: "search" | "subreddit" | "post_comments"
  query: str | None
  subreddit: str | None
  date_from: date
  date_to: date
  sort: "new" | "top"
  cursor_in: str | None           # 上次停在哪
  cursor_out: str | None
  pages_fetched: int
  items_yielded: int
  reached_floor: bool             # 是否探到 date_from 边界
  exhausted: bool                 # 游标是否耗尽
  status: "pending"|"running"|"ok"|"empty"|"truncated"|"failed"
  failure_reason: str | None
  attempts: [ProviderAttempt]
}

# 3. 覆盖账本（按 自然日 × lane 记录，这是补采的判定依据）
CoverageLedgerEntry {
  business_date: date             # Asia/Shanghai
  lane_id: str
  observed_posts: int
  observed_comments: int
  expected_floor_hit: bool        # 是否真的探到了这一天的边界
  completeness: "complete"|"partial"|"unknown"|"missing"
  reason: str | None              # 例 "actor_crawl_depth_limit" / "no_lane_covered"
  first_observed_at_utc: datetime
  last_observed_at_utc: datetime
}
```

**关键设计点：**

- **`reached_floor` 是补采的判定核心**。一个日期只有在该日的某个 lane 报了 `reached_floor=true` 时才算"已覆盖"。当前系统把"没查到"和"没查过"混为一谈，这是 74 天空洞无人发现的根本原因。
- **成本前置约束**：`budget.max_cost_usd` 传给 Apify 的 `maxTotalChargeUsd`，执行前拒绝超预算计划。
- **原始 payload 必落盘**（内容寻址）。当前 43MB 的 comments JSON 可以重算，但如果明天换了打标规则，没有原始响应就无法重打——这是数据资产的最大风险。

### 2.3 采集参数建议（可立即执行）

| 参数 | 现值 | 建议 | 理由 |
|---|---|---|---|
| `scrollTimeout` | 未设置（默认） | **120–180s** | 这才是列表页深度的真旋钮，两次探测都卡在这 |
| `maxItems` | 400 | 保持 400 | 探测显示远未跑满，不是瓶颈 |
| `maxComments` | 20 | 30 | 评论是 VOC 主体（当前 20,835 : 3,662） |
| `postDateLimit` | 未传 | **传 T-1** | 至少把"只要昨天"变成显式约束，避免拉回大量旧帖占预算 |
| `searchComments` | 未传 | `true` | 目前只搜帖子，评论搜索完全放弃 |
| subreddit 列表 | `[]` | 保留 5–7 个核心板块 | 列表路径覆盖比搜索更稳（搜索受排序算法影响） |

---

## 3. 存储层

### 3.1 现状（有证据）

**双写、无历史、整文件重写：**

| 问题 | 证据 |
|---|---|
| 指针按墙钟推进，与数据是否真更新解耦 | `advance_daily_t1_release.py:60-71` 无条件写 `data_as_of_utc` |
| 只追加新 id，**从不更新已存在记录** | `run_daily_t1_pipeline.py:176-185`、`:239-240`；score/评论数/正文编辑/**删除状态全部冻结在首次采集时刻** |
| 无墓碑 | 463 条帖子正文是 `[deleted]/[removed]` 却无 `deleted_or_removed` 字段（评论侧有） |
| 原始 payload 只存哈希 | `apify_collector.py:124-140` |
| `unresolved_parent_comments` 是冻结常量 | `recompute_derivatives.py:1049` 从旧 manifest 读，实测偏差 ≥804 条 |
| O(全量) 重写，一次运行读 43MB JSON **5 次、写 2 次以上** | `run_daily_t1_pipeline.py:174/228/234/270/279/287` + `refresh_base_manifest` 再读一遍 |
| 用 `indent=2` 重写，凭空增加 ~10.3MB | `:228/270/279`；磁盘 8.06MB 的 posts 用 indent=2 输出 9.94MB |
| 生产库**零索引** | `PRAGMA index_list` 只有 autoindex；`storage.py:415/452/481/508/539` 全是全表扫描 |
| 无 schema 版本、无迁移 | `user_version` 实测为 0；`storage.py:193-215` 用 `DROP TABLE` 重建，非原子 |
| `dataset_version` 永不轮转 | `recompute_derivatives.py:1073` 硬编码 `..._20260723_v3_daily_001` |
| `record_authority` 被常量覆写、`run_id` 被剥离 | `merge_normalize.py:189/274`；实测快照中 `run_id` 出现 **0 次** |
| **lineage 哈希是假数据** | `recompute_derivatives.py:1132-1149`：`canonical_validation_receipt_sha256 = sha(comments-public.json)`、`governed_signal_manifest_sha256 = sha(posts-public.json)`——命名槽位填的是无关文件 |

### 3.2 设计：事件溯源 + 双时态 + 内容寻址

**核心原则：系统当前只存"当前值"，这是所有时效问题的根源。改为同时存"何时观测到何值"。**

```python
# 1. 原始负载（内容寻址，不可变）
RawPayload {
  payload_sha256: str             # PK，也是存储路径
  provider: str
  provider_run_id: str
  request_fingerprint: str        # sha256(规范化请求)
  fetched_at_utc: datetime
  content_type: str
  bytes_len: int
  storage_uri: str                # s3://… 或 /var/lib/echo/raw/<sha[:2]>/<sha>
  compression: str
}
# 同 sha 自动去重；任何 parsed 记录都能回到它

# 2. 观测事实（append-only，这是新增的关键表）
Observation {
  observation_id: str             # sha256(entity_id + observed_at + payload_sha)
  entity_type: "post" | "comment"
  entity_id: str
  observed_at_utc: datetime       # 事务时间：我们何时看到的
  event_at_utc: datetime | None   # 有效时间：内容本身何时发生
  event_precision: "instant" | "day" | "unknown"
  payload_sha256: str             # 回到原始字节
  state_sha256: str               # 规范化后的状态哈希，用于判断"有没有变"
  score: int | None
  num_comments: int | None
  lifecycle: "alive" | "deleted" | "removed" | "edited" | "unknown"
  # 不变的是 entity_id，变的一切都在新 Observation 行里
}

# 3. 实体当前状态（物化视图，从 Observation 推导，可随时重建）
EntityState = Observation 的最新一条 + first_observed_at + last_changed_at

# 4. 内容指纹与去重簇
ContentFingerprint {
  entity_id: str
  simhash64: str                  # 正文近似指纹
  exact_sha256: str               # 规范化正文精确哈希
  duplicate_cluster_id: str | None
  crosspost_parent_id: str | None
}
# 实测 371 条帖子共享规范化标题——当前完全不处理

# 5. 发布注册表（不可变）
ReleaseCatalog {
  release_id: str                 # 时间戳 + 内容摘要
  created_at_utc: datetime
  datasets: [{key, dataset_version, manifest_sha256, built_from_observation_window}]
  metric_definition_version: str
  code_version: str
  # dataset_version 必须随内容变化，不能是静态目录名
}

# 6. 双时态索引（as-of 查询）
# "2026-10-01 那天，我们对 2026-09 的负向率看到的是什么？"
# → SELECT … WHERE valid_from <= '2026-09-30' AND recorded_at <= '2026-10-01'
```

**为什么这值得做：**

- **补采变得可表达**：`Observation.observed_at` 与 `event_at_utc` 分离后，"7 月的数据是 10 月补的"这件事天然可记录，指标可以标注"回填"而非假装一直有。
- **删除可表达**：现在 463 条已删帖永远显示原样。
- **重打标可比较**：`payload_sha256` 保留原始响应 → 换词典后可全量重打并与旧结果逐条 diff。
- **指针不再说谎**：`freshness.data_as_of_utc` 从 `CoverageLedger` 推导，而不是墙钟。

**渐进迁移**：SQLite 加表即可，不必立刻换库。但 `posts-public.json`（8MB）和 `comments-public.json`（43MB）的整文件重写必须逐步退役——建议保留为**发布产物**（只读投影），系统记录改为 SQLite。

---

## 4. 打标层

### 4.1 现状（有证据，这一层问题最致命）

**品牌归属：单一互斥枚举，且把自己的分析对象过滤掉了。**

```python
# recompute_derivatives.py:130
GOVERNED_BINDINGS = {"momcozy_sentence_bound", "momcozy_entity_reviewed", "momcozy_entity_cooccurrence"}
# 不含 multi_brand_context
```

而 `build_reddit_site_snapshot.py:313-333`：同时出现 Momcozy + 竞品 → `multi_brand_context`。

→ **所有"Momcozy vs Elvie"这类对比帖，在 Momcozy 方向被排除、在竞品方向也被排除。竞品分析层拿到的样本集里根本没有对比帖。** 这不是算法不准，是数据模型自相矛盾。

**其他关键缺陷：**

| 问题 | 证据 |
|---|---|
| 只识别 6 个品牌，57 个竞品别名不可见 | `run_daily_t1_pipeline.py:188`；实测 55 条 `competitor_sentence_bound` 帖的品牌全在 6 个之外（Boppy 32 / Baby Brezza 4 / Philips Avent 4 / eufy 4…） |
| 四个生产者四套 `brand_binding` 规则 | `v3_base_public.py:437-446`、`build_reddit_site_snapshot.py:313-333`、`merge_normalize.py:137`、`run_daily_t1_pipeline.py:185-195` |
| **每日新增记录从不打标** | `merge_normalize.py:24-31` `_BLANK_TAGGING` 全空；新帖 `product_bindings=[]` |
| 无"没尝试"vs"试了没命中"的区别 | 同上，两者都表现为空数组 |
| 子串匹配无词边界 | `analyzer.py:130-134` `term in lowered`；实测 423 条负向帖中 **31 条唯一命中的是 "rust" 出现在 "frustrat…" 里** |
| 无否定处理 | 实测 30 条明确写 "no leak / not painful / never hurt" 的帖子被标为负向/有痛点 |
| severity 由痛点类别反推 | `analyzer.py:161-165`，`support` 词表含 warranty/return/refund → 实测 **291 条 high severity 中 42 条情感为 positive**（"退货很方便"被判高危） |
| 三份互不一致的竞品清单 | `keywords.py:120-186`（63 个）vs `product_entities/*.json`（19 个）vs `dim_tag`（17 个），交集仅 13 |
| 品牌标签硬编码"竞品=负向" | 同上 |
| 10 条 L0 规则被永久禁用，含漏奶/噪音/破损/异味 | `tag_dictionary.py:102-110` 单 token 不确认；`L0-GEN-066 Leakage Issue` 等 |
| 39% 帖子正文为空或已删，17% 是中文占位摘要，仍被分析 | `v3_base_public.py:340-356`；实测 1411/3591 |
| LLM 打标在当前契约下不可发布 | 前端 `service.ts:1119-1120` 逐条断言 `provider_call === false` |
| DeepSeek 重分析被永久记成规则分析 | `storage.py:628-632` 写死 `'local_rules_v1'` |

### 4.2 设计：四元归属模型 + 证据事实表

**放弃 `brand_binding` 单值枚举，改为多对多关系事实：**

```python
# 1. 实体提及（一个内容可以提及任意多个品牌，各有角色）
BrandMention {
  entity_id: str
  brand_id: str                   # 规范化 ID，不是自由文本
  role: "subject" | "comparator" | "passing_mention" | "negative_of"
  # subject      = 这条内容主要在讲这个品牌
  # comparator   = 拿来做对比的另一个品牌
  # passing      = 顺带一提
  # negative_of  = 明确在骂/劝退
  sentiment: "positive" | "neutral" | "negative" | None
  sentiment_target: str | None    # 情感指向哪个方面（客服/漏奶/价格…）
  evidence_span: {start: int, end: int, text: str}
  sentence_index: int
  negated: bool                   # "no leak" 的 negated=True
  confidence: float
  matcher_version: str
  dictionary_version: str
  tagging_run_id: str
}
# 关键：一条 "Momcozy 比 Elvie 便宜但噪音大" 产生 2 条 BrandMention，
# 各自独立情感，谁也不会被"过滤掉"

# 2. 标签归属（行级，不是数组挂载）
TagAssignment {
  entity_id: str
  dimension: "pain" | "topic" | "aspect" | "brand" | "stage" | "intent"
  label_id: str                   # dim_tag_v6.3_final 的 tag_id
  polarity: "positive" | "neutral" | "negative" | None
  evidence_span: {start, end, text}
  negated: bool
  confidence: float
  dictionary_version: str
  tagging_run_id: str
}

# 3. 打标运行（可重打、可比对）
TaggingRun {
  tagging_run_id: str
  started_at_utc: datetime
  analyzer_version: str           # "rules_v2" / "llm_deepseek_v1"
  dictionary_sha256: str
  matcher_config_sha256: str
  entity_count: int
  provider_call: bool             # 前端契约需要，但要允许 true（见下）
  output_payload_sha256: str
}

# 4. 打标状态（消除"没试"vs"没命中"的歧义）
TaggingStatus = "not_attempted" | "attempted_no_match" | "matched" | "skipped_no_content"
# skipped_no_content: 正文为空/已删/占位摘要 → 不进分母
```

**必须同时修的规则引擎缺陷：**

1. **词边界匹配**：`term in text` → 正则 `\b(term)\b`（`keywords.py:244-246` 已有正确实现，可复用）。
2. **否定检测**：命中词前 3 个 token 内出现 `no/not/never/without/n't` → `negated=True`，不计入负向。
3. **severity 与痛点解耦**：`severity=high` 只由**危害证据**（健康/安全/伤害/召回）决定；`support`（退货/保修/客服）另立 `service_friction` 维度。
4. **内容可用性门控**：`body_len < 40` 或正文为 `[deleted]/[removed]` 或标题是占位摘要 → `skipped_no_content`，不进 sentiment/topic 分母，单独统计覆盖率。
5. **统一品牌注册表**：一份 `brands.json`（id / 规范名 / 别名数组 / 是否竞品），三处代码全部读它。
6. **放开对比帖**：`multi_brand_context` 从"排除"改为"每个 BrandMention 独立参与"。
7. **解锁高价值标签**：漏奶/噪音/破损/异味改为短语匹配（`leaking`, `leaks`, `noise level`, `too loud`, `cracked`, `smell`）后恢复正常识别。
8. **允许 LLM 打标进入契约**：前端 `provider_call === false` 的断言需要加白名单，否则永远只能用规则。

---

## 5. 指标层

### 5.1 现状（有证据）

| 问题 | 证据 |
|---|---|
| 26 个指标 ID，**真算 4 个** | `recompute_reports_bundle.py:63-68`；线上 69/78 实例 unavailable |
| **90 天指标实际是 30 天** | 线上 quarter period 2026-07-29..10-26 与 rolling_30_days **同为 47 个 VOC、同 13 个观测日** |
| 同一 metric_id **不同分母** | reports 按"父帖受治理"选评论（`recompute_reports_bundle.py:143-153`）；quarter-insights 按"评论自身 brand_binding"（`recompute_derivatives.py:142-146`） |
| **RV-BR-05 身份变了** | 每日引擎算"含任意品牌提及的 VOC 占比(%)"（`:171-176`）；注册表与 UI 当"竞品净情感差(pp)" → 前端发出错误的竞品结论 |
| RV-BR-04 不是推荐表达率 | `:166-170` 算的是正向情感占比；快照里根本没有 recommendation 字段 |
| 无统计门控 | 只要 `value is not None` 就 `available`，n=5 也发；注册表自己的阈值策略从未被读 |
| **业务日语义不一致** | reports 用 `str(ts)[:10]`（UTC 截断，`:84-90`）；quarter-insights 用 `source_calendar_date` 或上海时区（`:247`）→ 同一条内容两页落在不同天 |
| 品牌健康 v2 与 v1 不同构念却同名 | `recompute_derivatives.py:951-968` 换了公式，四项全标 `available` |
| 品牌健康"基线"就是当前值 | `recompute_reports_bundle.py:299-354` 忽略 period 参数 |
| profile hashes 是常量 | `:75-81` 对字面量做哈希，每个数据集每个周期都相同 → "可比性证明"是假的 |
| reports manifest **自证通过**，没跑任何校验器 | `:591-637` 直接写 `passed` / `promotable=True` |
| **死代码里有硬编码假指标** | `recompute_derivatives.py:824-833` `RV-DH-05=100.00`、`RV-PS-02=0.00`、`RV-PS-04=0.00pp`；`:849` 设 `is_complete=true` 假覆盖声明；而 `tests/test_recompute_parity.py` 只测这条死路径 |
| 零数据月份发成"可用的 0" | 线上 monthly 报告 `monthly:2026-09-01` `RV-BR-01=0.0 status=available` |
| 机器人污染未清除 | 787 条评论含 "I am a bot"，只有 112 条 `is_bot=True`；其中 **474 条 `include_in_voc_metrics=True`** |
| 183 天窗口实际约 209 天 | `:442-455` 月粒度 `months_back<=6` + `_zero_fill` 生成 7 个月桶 |
| 零基线被当缺失 | `recompute_reports_bundle.py:190` `baseline_value == 0` 与 `None` 同处理 → 环比被抑制 |

> **必须点明**：`RV-DH-05=100.00`（证据完整率恒 100%）与 `RV-PS-02=0.00`（产品问题率恒 0）是我此前留下的硬编码常量。虽然该函数已不在生产路径上，但它是**假数据**，必须删除而不是保留。

### 5.2 设计：指标注册表 + 指标事实表 + 不确定性

**1. 指标注册表（唯一权威，Python/TS 都从它生成）**

```yaml
# config/metrics/registry.yaml
- metric_id: RV-BR-02
  name_cn: 负向率
  version: 3                      # 公式变更必须升版本
  effective_from: 2026-11-01
  unit: percent
  grain: [daily, weekly, monthly, quarter]
  population:                     # 分子分母都显式声明
    numerator: entity WHERE BrandMention(role=subject, brand=momcozy) AND sentiment=negative AND NOT negated
    denominator: entity WHERE BrandMention(role=subject, brand=momcozy) AND sentiment IN (positive,neutral,negative)
    exclusions: [is_bot, tagging_status=skipped_no_content, duplicate_cluster_non_primary]
  business_day_rule: asia_shanghai_natural_day
  min_sample: 30
  uncertainty: wilson_interval   # 二项比例用 Wilson，不用正态近似
  on_insufficient: {status: provisional, reason: sample_below_threshold}
  on_zero_denominator: {status: unavailable, value: null, reason: zero_denominator}
```

**2. 指标事实表（不可变，可按 as-of 回看）**

```python
MetricFact {
  metric_id: str
  metric_version: int
  period_id: str                  # "daily:2026-10-26:2026-10-27"
  business_date_start: date
  business_date_end: date
  scope: "momcozy" | "all_observed" | "competitor:<id>"
  value: float | None
  numerator: int
  denominator: int
  n: int                          # 有效样本
  confidence_low: float | None
  confidence_high: float | None
  status: "available"|"provisional"|"unavailable"
  reason_codes: [str]
  computed_at_utc: datetime
  computed_from: {observation_window, dataset_version, metric_definition_version}
  coverage: {observed_days: int, expected_days: int, gap_dates: [date]}
}
# 关键：coverage 是必填字段。没有它，47 个 VOC 的"90 天指标"永远无法自证
```

**3. 三条硬规则**

- **一个 metric_id 全站唯一口径**。reports / quarter-insights / brand-health 都从 `MetricFact` 读，不允许各自算。
- **业务日唯一**：所有落窗统一 `Asia/Shanghai` 自然日，`event_at_utc` 转业务日的函数只有一个。
- **样本不足必须降级**：`n < min_sample` → `provisional` + 原因码，并**在前端显式展示 n**，而不是给一个看起来精确的百分比。

**4. 立即删除的假数据**

- `recompute_reports_daily()` 整个函数（死代码，含硬编码 100/0/0）。
- `profile_hashes()` 的字面量哈希 → 改为真实内容的哈希（查询集 + 词典 + 排除规则）。
- `recompute_derivatives.py:1132-1149` 的假 lineage → 改为真实产物哈希，或干脆置 `null` 并标 `lineage_unavailable`。

---

## 6. 分析层

### 6.1 现状（有证据）

| 问题 | 证据 |
|---|---|
| **竞品/GEO 在数据模型上不可能成立** | `GOVERNED_BINDINGS` 不含 `multi_brand_context`，对比帖全部被排除 |
| **personas 的 assignment_id 是两套不相交的哈希命名空间** | `recompute_derivatives.py:645-646` 用 `kind:post_id:comment_id:topic` 的 sha256；冻结的 persona-tags 是另一套 → 前端交集**恒为空** |
| `new_product` 把 topic 计数冒充分类/产品族/SPU | `:610-619` `category_rankings = _topic_rankings(in_quarter, ("product_evaluation",))` |
| 分析池被重定义 | `:675-677` 把 `analysis_post_vocs` 从"所有已分析内容"改成"Momcozy governed VOC" |
| 完全不看采集覆盖率 | 7 月 183 条 governed posts 的 `linked_comment_count` 合计 1427，语料只有 337 条（23.6%），仍当总体 |
| evidence 不按 ranking 归因 | `:523-541` 取列表前 5 条、reason 写死；7 月版甚至每个季度固定 5 篇 |
| **comment evidence 重复加 `t1_` 前缀** | `:531` `comment_id: f"t1_{...}"`，但 base 里已经是 `t1_c9obtk0` → **一旦进入 top5，整个 quarter-insights 会被前端拒绝** |
| brand_health.rows 缺 value/display | `recompute_reports_bundle.py:337-353` → 前端 `periodBrandHealth` 永远返回 null，报告页品牌健康静默消失 |
| reputation rankings 不是排序 | `:550-559` 按 dict 插入序（实跑 0,27,47,0） |
| product_rankings 与 exact_spu_rankings 完全重复 | `:610-619` 同一输入 |
| 月度趋势不补零，跨 74 天空洞直接连线 | `:221` 只保留有数据的月份 |
| cohort 映射用了分析器永不产出的 topic | `:629-638` 用 `recommendation/service/scenario/fit`，而 analyzer 产出 `competitor_comparison/customer_service/...` → 8 个 cohort 中 4 个**结构性不可达** |
| insights 数据集**从不刷新** | 仍是 7-23，且声称 owner-attested 100%，与 reports 的"未证明"同站矛盾 |
| 前端在浏览器里重实现一套分析 | `operational.ts:6-9` `MOMCOZY_BRAND_BINDINGS` 缺 `momcozy_entity_cooccurrence` |

### 6.2 设计：分析事实表 + 显式暴露模型

**1. 一切分析从事实表出发，不再从内容行上的数组出发**

```python
# 主题排名
ThemeRanking {
  theme: "pain"|"reputation"|"new_product"|"geo"
  dimension: str
  label_id: str
  count: int
  denominator: int                # 该主题的适用总体
  share: float | None
  rank: int
  evidence: [EntityRef]           # 每条 ranking 有自己的证据，不是全局前 5
}

# 竞品对比（现在根本不存在）
ComparisonFact {
  entity_id: str
  subject_brand: str
  comparator_brand: str
  dimension: str | None           # 价格/噪音/吸力/舒适度/客服
  direction: "favors_subject"|"favors_comparator"|"mixed"|"neutral"
  evidence_span: {...}
  sentiment_subject: str | None
  sentiment_comparator: str | None
}
# 有了它，"Elvie 静音 vs Momcozy 吸力强"才可统计
```

**2. 暴露与覆盖模型（必须进每个分析）**

```python
AnalysisCoverage {
  population_definition: str
  observed_entities: int
  expected_entities: int | None   # 来自 linked_comment_count 等
  coverage_ratio: float | None
  observed_days: int
  expected_days: int
  gap_dates: [date]
  collection_regime: str          # "apify_newest_n" —— 采集方式会影响可比性
}
```

**3. 规则**

- **覆盖率低于阈值时，分析结论必须降级**（`provisional` + 显示 `observed/expected`）。现在 23.6% 的评论覆盖率下给出的排名，不能与"完整数据"的排名并列。
- **排名必须有分母和 tie-break**，零值不排名、不画条。
- **时间序列必须补零**，空洞显式标注"未采集"而非连成一条线。
- **personas 要么修复 ID 命名空间接入实时数据，要么彻底下线**。当前状态（冻结快照 + 不相交 ID + 页面声称实时计数）是最差组合。

---

## 7. 呈现层

### 7.1 现状

严格契约是**优点**（拒绝展示假数据），但代价是**任一处不符整页死不显示**，且契约在 Python 写入方和 TS 校验方各写一份。

今天实测已修好的坑（作为前车之鉴）：

| 坑 | 后果 |
|---|---|
| manifest `bytes` 只更新 sha 不更新 bytes | 整页「真实数据文件 bytes 不一致」 |
| `time_precision` 两侧各算一遍 | 「时间精度计数不守恒」 |
| Python `round()` 银行家舍入 vs JS `Math.round` 半上 | 74.5/4=18.625 → 18.62 vs 18.63，整页拒渲染 |
| 子版块名 `r/r/BabyBumps` | 显示错但不崩 |
| 只写 `current/daily.json` 不重建整束 | 「V3 报告业务角色异常」 |

### 7.2 设计：单一契约源 + 写入即校验

**1. 契约从 Python 生成 TypeScript**

用 JSON Schema / Pydantic 作为唯一源，生成两端的类型与校验器。当前 26 个字段必须逐字节相等的地方（`bytes`、`sha256`、守恒式、舍入规则）全部编码进 schema 的 `x-invariants`。

**2. 写入前校验，不是发布后报错**

```python
# pipeline 里 recompute 之后、advance_pointer 之前
validate_bundle(public_root)   # 跑与前端**同一套**断言
# 任何一条失败 → 不推进指针，保留上一版可服务
```

现在 `advance_pointer` 与 `recompute` 之间没有门禁，step 异常被 try/except 吞掉后继续推进指针（`run_daily_t1_pipeline.py:465-483`）——这是"指针说谎"的机制来源。

**3. 性能与失败 UX**

- 冷加载目前要拉 43MB comments + 8MB posts。建议 `comments-public.json` 拆分（按年月分片 + 索引），首屏只拉索引与聚合。
- 失败时**降级渲染可用的数据集**，而不是整页白屏。

---

## 8. 洞察层

### 8.1 现状

| 问题 | 证据 |
|---|---|
| **三个 Agent 上线跑的是确定性 fallback** | `run_daily_t1_pipeline.py:107` `AgentBatchRunner(client=None, ...)` |
| fallback 输出包含**虚构的竞品结论和用户引语** | `agents/content_scout.py:68-100` 等 |
| 无证据锚点 | 输出不含 `evidence_ids`，无法回溯到帖子 |
| 无质量评估 | `tests/agents/test_agent_evals.py` 只断言字段存在性 |
| 无反馈闭环 | 从不检验"预测的趋势是否发生" |
| Agent Studio 把 fallback 当"分析"展示 | 页面上没有标注"确定性规则" |

### 8.2 设计：证据绑定 → 质量门禁 → 结果回检

**1. 每条洞察必须带证据锚点**

```python
Insight {
  insight_id: str
  kind: "topic_idea"|"rnd_defect"|"competitor_gap"|"risk_alert"
  claim: str
  evidence: [EntityRef]           # 必填，至少 1 条
  supporting_metrics: [MetricFactRef]
  confidence: float
  generator: {kind: "rules", version: "v2"} | {kind: "llm", model: "...", prompt_sha: "..."}
  # generator 必须透传到前端并显示 —— 不能把规则输出说成"AI 分析"
  human_review: {status: "pending"|"accepted"|"rejected", reviewer, at}
}
```

**2. 质量门禁（EDD）**

- Golden Dataset 断言的是**判断正确性**，不是字段存在性：给定 10 条已知漏奶帖，`rnd_defect` 必须识别出 ≥8 条且构件归到密封圈/阀门。
- 每次改动打标规则或提示词，跑一次离线评测，记录 precision/recall，回归即拦截。

**3. 结果回检（闭环）**

```python
InsightOutcome {
  insight_id: str
  check_at: date                  # T+7 / T+30
  observed: {...}                 # 该主题实际讨论量、情感变化
  verdict: "confirmed"|"refuted"|"inconclusive"
}
# 没有这个，洞察永远只是"听起来有道理"
```

**4. 诚实性原则（写入产品契约）**

- 规则产出标"规则引擎"，LLM 产出标模型名，**不允许混称**。
- 样本不足的洞察不生成，而不是生成后加免责声明。

---

## 9. 优先级路线

| 批次 | 内容 | 为什么排这里 |
|---|---|---|
| **P0（本周）** | ① 删除死代码假指标 `recompute_reports_daily`；② 修 `comment_id` 双前缀；③ 假 lineage → null 或真哈希；④ 修 `unresolved_parent_comments` 冻结常量；⑤ `advance_pointer` 加就绪门禁；⑥ 品牌注册表统一 + 放开 `multi_brand_context` | 全部是**正确性缺陷**，且 ②⑤ 会让整页崩溃或指针说谎 |
| **P1（两周）** | ① 指标注册表 + `MetricFact` + Wilson 区间 + `min_sample`；② 业务日统一；③ 打标词边界+否定+severity 解耦；④ 内容可用性门控；⑤ 覆盖账本 `CoverageLedger` | 决定"数字能不能信" |
| **P2（一个月）** | ① 原始 payload 落盘（内容寻址）；② `Observation` 事件溯源；③ 双时态 as-of 查询；④ 去重簇；⑤ 契约单一源 + 写入前校验 | 决定"能不能重算、能不能回看" |
| **P3（季度）** | ① 竞品对比事实表；② 洞察证据锚点 + 结果回检；③ personas 修复或下线；④ 补采（依赖 TikHub key） | 决定"能不能做真正的分析" |

---

## 10. 需要你决策的四件事

1. **补采 74 天空洞**：唯一可行路径是 TikHub 回溯引擎，需要**可用的 TikHub API key**。没有它，这个洞只能作为"已知缺口"写进覆盖账本，并在所有图表上显式标注。你的选择是？
2. **`multi_brand_context` 放开**：会让 Momcozy VOC 总量上升约 20–30%（当前 1011 条 `multi_brand_context` 帖子被排除），并让竞品分析首次有数据。是否接受口径变化带来的历史断点（可以靠指标版本号处理）？
3. **LLM 打标**：要引入 DeepSeek 打标就必须放开前端 `provider_call === false` 的硬断言。这会改变"纯规则、零外部调用"的合规叙事。是否推进？
4. **personas**：修好并接入实时数据（工作量约 1–2 天）还是直接从导航下线？当前状态是最差组合。

---

## 附录 A：已验证的审计证据索引

- 采集：`apify_collector.py:40/66-75/95/106-112/124-140/144-155/166-170/187/199-207`；`run_daily_t1_pipeline.py:53-94`
- 存储：`advance_daily_t1_release.py:44-71`；`run_daily_t1_pipeline.py:174-313`；`storage.py:173-216/311-374/415-559`；`recompute_derivatives.py:1038-1049/1132-1149`
- 打标：`analyzer.py:24-61/130-165`；`keywords.py:120-186/244-246`；`tag_dictionary.py:102-110`；`merge_normalize.py:24-31/137/281-285`
- 指标：`recompute_reports_bundle.py:63-68/75-81/84-90/143-153/166-176/190/299-354/392-445/591-637`；`recompute_derivatives.py:130/142-146/442-469/824-849/951-968`
- 分析：`recompute_derivatives.py:523-541/550-559/610-619/629-660/675-677`；`operational.ts:6-9`
- 呈现：`release.ts:389-405`；`service.ts:1100-1230/1520-1570`；`reports.ts:1011-1210/1571-1750`
- 洞察：`run_daily_t1_pipeline.py:107`；`agents/*.py`；`tests/agents/test_agent_evals.py`

## 附录 B：补采探测原始结论

```
搜索路径 12 查询词 maxItems=500 postDateLimit=2026-07-20
  → status RUNNING(超时取部分) 786s items=143 posts=30
  → 日期范围 2026-10-06 .. 2026-10-27
  → 空洞内 0 条

列表路径 7 subreddit /new/ maxItems=800 postDateLimit=2026-07-20
  → status SUCCEEDED 743s items=393 posts=60
  → 日期范围 2026-10-26 .. 2026-10-27
  → 空洞内 0 条
```

结论：该 actor 的爬取深度受 `scrollTimeout`/分页限制，`maxItems` 不是瓶颈；无法回溯 3 个月。
