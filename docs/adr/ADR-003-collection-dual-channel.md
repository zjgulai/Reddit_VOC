# ADR-003: 采集层双通道 —— 归档回溯 + 实时兜底

- **状态**: Accepted（已实现并上线验证）
- **日期**: 2026-10-28
- **决策人**: Echo-Agent 核心研发团队
- **关联**: ADR-002（数据时效与派生重算）、`docs/prd/DATA-MODEL-v1.md` 第 2 章
- **取代**: ADR-002 §7.1 中"仅靠扩大 Apify 参数"的采集假设

---

## 1. 背景

ADR-002 交付后，采集层仍有两个未解决的问题：

1. **74 天数据空洞**（2026-07-23 .. 2026-10-04 零帖子）。
2. **无法表达"只要昨天"**。`current-release.json` 声称 T-1，但采集器只能取"最新 N 条"。

当时的假设是"扩大 `maxItems` 就能补采"。**这个假设是错的**，见 §2。

## 2. 实测否定了两个前提

### 2.1 `maxItems` 不是爬取深度

对 `trudax~reddit-scraper-lite` 的两条路径分别探测（`postDateLimit=2026-07-20`）：

| 路径 | 参数 | 返回最早帖子 | 空洞内 |
|---|---|---|---|
| 搜索 | 12 查询词，`maxItems=500` | 2026-10-06 | **0** |
| 列表 | 7 个 `/new/`，`maxItems=800` | 2026-10-26 | **0** |

两次都**远未跑满预算**（265 / 393 条即停），说明瓶颈是 `scrollTimeout` 控制的滚动深度与分页，不是 item 预算。

### 2.2 归档 actor 的三种模式不等价

Apify Store 有 134 个 Reddit actor。逐个拉输入 schema 后，只有 `logiover~reddit-historical-archive-scraper` 提供真正的区间参数（`afterDate` / `beforeDate`），它读的是 **PullPush 归档**而非实时 Reddit。

但它的三种模式**并不都名实相符**（2026-07-23..07-27 窗口实测）：

| 模式 | 产出 | 成本 | 判定 |
|---|---|---|---|
| `searchQueries`（3 词） | **0 items** | $0.00004 | ❌ 不稳定 |
| `commentSearchQueries`（1 词） | 300 items，**全为帖子，0 评论** | $0.233 | ❌ **名不副实** |
| `subreddits`（4 板块） | **800 帖** | $0.926 | ✅ 可靠发现 |
| **两阶段**：`postIds` 展开 | 5 帖 → **45 评论（9.0/帖）** | $0.023 | ✅ **评论唯一可靠通道** |

> `commentSearchQueries` 的 store 描述明确写着"对归档评论做全文检索，Reddit 自身搜索做不到"。实测返回 300 条全是帖子。**因此不能把评论召回建立在它之上** —— 这是本轮最重要的负面发现。

## 3. 决策

### 3.1 采集改为两阶段

```
阶段 1（发现）  subreddits 列表 → 帖子 id 集合 + 帖子元数据
阶段 2（展开）  按 numComments 降序取前 N 帖 → postIds 批量展开评论
```

- 阶段 2 按 `numComments` 排序：VOC 价值集中在高评论帖，展开预算有限时优先它们。
- 批量大小默认 15 帖/次；单批失败只记 issue，**已发现的帖子不丢失**。
- 两阶段会重复返回同一评论，按 `comment_id` 去重后再入库（实测不去重会重复计数）。

### 3.2 通道分工

| 场景 | 通道 | 说明 |
|---|---|---|
| 日常 T-1 | 归档 actor `subreddits` + 两阶段展开 | 归档新鲜度实测滞后 1 天，正好匹配 T-1 |
| 历史回补 | 归档 actor `afterDate/beforeDate` 按周分片 | 11 个分片覆盖 74 天 |
| T-0 当天 / 归档缺口 | 实时 actor（`scrollTimeout=150, maxItems=600`） | 兜底，不承担 SLA |

### 3.3 覆盖账本（新增，这是关键）

新建 `collection_coverage` 表，按 **(run, lane, 上海业务日)** 记录：

| 字段 | 含义 |
|---|---|
| `observed_posts` / `observed_comments` | 该日实际观测到的条数 |
| `reached_floor` | **该日是否真的有观测命中** —— 承重字段 |
| `completeness` | `complete` / `missing` / `unknown` |
| `reason` | 例 `lane_returned_zero_items_for_day` / `run_truncated_at_deadline` |

**为什么这是关键**：此前"采集器这天返回了 0 条"与"这天从来没人查过"在系统里完全不可区分——这才是 74 天空洞无人发现的根因。`coverage_gaps(from, to)` 直接列出未覆盖的日期，补采从"人想起来"变成"系统报缺"。

### 3.4 截断与失败语义

| 情况 | 旧行为 | 新行为 |
|---|---|---|
| 轮询超时仍 RUNNING | 用部分数据集标 `success` | 标 `partial`，该日 `completeness=unknown` |
| provider 报错 | 吞掉继续 | 标 `failed`，该分片计入 `failed_shards` |
| 评论父帖不在批次 | 静默丢弃 | 计入 `orphan_comments` 并上报 |
| 时间戳缺失 | 伪造为采集时刻 | 保持 unknown，账本记 `unknown` |

**部分数据永不晋升为"已覆盖"**：`--resume` 会因截断而重新捡起该日期。

## 4. 实现

| 文件 | 内容 |
|---|---|
| `src/reddit_voc/archive_collector.py` | 归档客户端（含重试/退避）、`build_plan`、`backfill_week_shards`、`collect_archive`（两阶段）、覆盖账本生成 |
| `src/reddit_voc/storage.py` | `collection_coverage`、`entity_observation` 表 + 8 个索引 + `record_coverage` / `coverage_gaps` / `record_observation` |
| `scripts/run_archive_backfill.py` | 分片驱动，支持 `--plan-only` / `--shard` / `--resume` / `--max-expand-posts` |
| `tests/test_archive_collector.py` | 19 项，钉住上述全部行为 |

### 4.1 过程中修掉的三个真缺陷

1. **`insert_raw_capture` 幂等性被破坏**（我重现了旧采集器的同款 bug）：整行比对里包含 `captured_at_utc`，而它是墙钟时间、重跑必变 → 任何 run 都无法安全重试。改为内容寻址语义，只比较非易变字段。
2. **孤立评论静默丢弃**：`linkId` 不在本批次帖子的评论被直接跳过且不计数。改为计入 `orphan_comments`。
3. **`datetime.time` 遮蔽 `time` 模块**：`from datetime import time` 使 `time.time()` 抛 `AttributeError`，采集器一启动就崩。改用 `clock_time` 别名。

## 5. 验收

### 5.1 单分片实测（2026-07-27 .. 08-02，7 天）

```
posts: 1200    comments: 3275
```

对比修复前的分片 0（4 帖 / 0 评论），提升约 300 倍。

### 5.2 与实时通道对比

| 通道 | 单日帖子 | 单日评论 | 评论/帖 |
|---|---|---|---|
| 实时 actor（`scrollTimeout=150`） | 67 | 315 | 4.7 |
| 归档两阶段 | ~170 | ~470 | **2.8→9.0** |

## 6. 成本

按实测约 $0.0012/条：

| 任务 | 估算 |
|---|---|
| 单日 T-1 采集（~600 条） | ~$0.7 |
| 74 天全量补采（11 分片） | ~$40–60 |

成本上限：`build_plan` 声明 `max_cost_usd`，可传给 actor 的 `maxTotalChargeUsd` 做硬熔断（当前未启用，见 §7）。

## 7. 已知限制

- **`commentSearchQueries` 不可用**：评论召回只有两阶段一条路。若将来该功能修复，应重新评估（能直接搜到"提到 Momcozy 的评论"，而不必先发现帖子）。
- **归档密度受 subreddit 列表深度限制**：分片 1 拿到 1200 帖是 `maxItemsPerTarget=250 × 7 板块` 的结果，不代表该周真实发帖量。覆盖账本记的是"观测到"，不是"存在多少"。
- **`maxTotalChargeUsd` 未接线**：`build_plan` 里有字段，但还没传给 actor。P1 补。
- **TikHub 凭据仍缺失**：`backfill_provider.py` 那套成熟回溯引擎无法使用。归档 actor 已覆盖该能力，TikHub 可降为纯备选。
