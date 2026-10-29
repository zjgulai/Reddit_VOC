# 存储层分析与目标模型

- **状态**: 待评审
- **日期**: 2026-10-28
- **依据**: 生产库实测（32.8MB / 11,018 帖 / 27,123 评论）+ 七层审计
- **上游**: ADR-003（采集层双通道）、`docs/prd/DATA-MODEL-v1.md` 第 3 章

---

## 1. 现状实测

### 1.1 表清单

| 表 | 列数 | 行数 | 状态 |
|---|---|---|---|
| `reddit_threads` | 16 | 11,018 | 主表，破坏性 upsert |
| `reddit_comments` | 13 | 27,123 | 主表，破坏性 upsert |
| `raw_captures` | 13 | 19 | 只有哈希 + 少量落盘 |
| `runs` | 6 | 13 | 仅计数与窗口 |
| `collection_coverage` | 10 | 60 | **本轮新建** |
| `entity_observation` | 6 | 1,727 | **本轮新建** |
| `analysis_results` | 12 | **0** | 从未写入 |
| `delivery_previews` | 8 | **0** | 从未写入 |

`PRAGMA user_version = 0`（无 schema 版本），`PRAGMA foreign_keys = 0`（无外键约束）。

### 1.2 双写偏差（最严重的发现）

| | SQLite | 公开快照 | 交集 | 各自独有 |
|---|---|---|---|---|
| 帖子 | 11,018 | 3,750 | **141** | 10,877 / 3,609 |
| 评论 | 27,123 | 21,295 | **686** | 26,437 / 20,609 |

**交集只有 141 帖 / 686 评。** 两条通路各自累积、互不相干：

- 快照侧的 3,609 帖来自 7 月导入，`run_id` 已被 `merge_normalize` 剥掉（快照里 `run_id` 出现 0 次），因此在 SQLite 中**找不到对应行**。
- SQLite 侧的 10,877 帖来自归档补采与日常采集，因为 `merge_snapshot` 按 `run_id` 取数，**永远看不到别人的 run**。

这不是"数据滞后"，是**两套事实源**。本轮已把 `merge_snapshot` 改为按日期窗口取数（`fetch_threads_in_window`），但历史偏差需一次性对齐。

### 1.3 重写放大

单次 `merge_snapshot` 触碰的数据量：

| 步骤 | 操作 | 字节 |
|---|---|---|
| 读 posts | 全量 | 11.0 MB |
| 读 comments | 全量 | 44.7 MB |
| `merge_normalize` 后重写 | 全量 ×2 | 55.7 MB |
| `refresh_base_manifest` 再读 | 全量 | 55.7 MB |
| manifest 更新后重写 | 全量 ×2 | 55.7 MB |

**合计约 3 次全量读 + 3 次全量写 ≈ 220 MB I/O**，随语料线性增长，与"今天新增了多少条"无关。

全量读取本身耗时实测：`SELECT * FROM reddit_threads` 48.9ms + `comments` 67.1ms = **116ms**。真正的成本在 JSON 序列化与落盘。

### 1.4 四个能力无法表达

| 能力 | 现状 |
|---|---|
| 删除/墓碑 | 帖表**无 tombstone 列**，672 条正文是 `[deleted]/[removed]` 却只能靠字符串猜测；评论表有 `deleted_or_removed` |
| 编辑历史 | 帖表**无任何** edit/version 字段 |
| 评分变化 | `ON CONFLICT DO UPDATE` 覆盖，无"上次观测值" |
| 回填标注 | 无字段能表达"这条是 10 月补采的 7 月数据" |

### 1.5 原始 payload

| 来源 | 是否落盘 |
|---|---|
| 归档补采（本轮） | ✅ 12 次捕获，磁盘 **56.4 MB** |
| 日常 Apify 采集 | ❌ **未传 `raw_artifact_root`** |

后果：换打标规则后，日常采集的数据**无法重打**。

---

## 2. 一处自我纠正

我在上一轮把"生产库零索引"标为 critical，并声称它导致日更全表扫描。**实测推翻了这个判断**：

| 查询 | 有索引 | 无索引 | 差异 |
|---|---|---|---|
| `threads WHERE run_id` | 6.59 ms | 8.71 ms | 24% |
| `comments WHERE created_at` 范围 | 20.80 ms | 15.54 ms | **无索引反而更快** |

在当前规模（1.1 万 / 2.7 万行）下，索引收益可以忽略，`comments` 范围查询甚至因为选择性低而变慢。**索引不是当前的瓶颈**，真实瓶颈是全量 JSON 重写。索引的价值要到百万行级才显现——那时它仍然是必需的，但把它当作"当务之急"是判断错误。

---

## 3. 五个结构性问题

### P1. 没有观测模型 → 只存"当前值"
系统无法回答"2026-10-01 那天，我们对 2026-09 的负向率看到的是什么"。删除、编辑、回填、重打标四件事全部无法表达。

### P2. 两套事实源 → 无法判断哪个是真的
SQLite 与公开 JSON 交集仅 141 帖，没有任何机制保证一致。

### P3. 单一可变行 → 历史不可追溯
`reddit_threads` 一行一条，`upsert` 覆盖。首次观测时间、状态变化全部丢失。

### P4. 发布产物与系统记录耦合 → I/O 放大 220 MB/次
公开 JSON 既是发布产物又是系统记录，导致每次合并都要全量重写。

### P5. 无 schema 版本、无外键、无迁移机制
`user_version = 0`，唯一一次迁移用 `DROP TABLE` 重建（非原子）。生产库结构变化只能靠人工。

---

## 4. 目标模型：一套统一的内容实体表

### 4.1 设计原则

1. **实体统一**：帖子与评论是同一类"内容实体"，共用一个表。当前代码为两者各写一套字段映射（`merge_normalize` 里重复约 100 行），已经产生过漂移。
2. **事实分层**：原始字节 → 实体当前态 → 观测历史 → 派生结果，每层可独立重建。
3. **双时态**：`event_at`（内容何时发生）与 `seen_at`（我们何时观测）分离。
4. **发布解耦**：公开 JSON 降级为**只读投影**，由 SQLite 生成，不再反向作为数据源。

### 4.2 核心表 `content_entity`

见 §5 的完整字段表。要点：

- **一张表容纳帖子与评论**：`entity_type` 区分，`thread_id` 自引用建立归属
- **`state_hash`** 是检测"有无变化"的关键：规范化后哈希，变了才写新观测
- **`lifecycle`** 显式建模删除/移除，不再靠正文猜测
- **`event_precision`** 保留日精度，不再用采集时刻伪造

### 4.3 配套表

| 表 | 作用 | 关键字段 |
|---|---|---|
| `raw_payload` | 内容寻址的原始字节 | `payload_sha256` PK, `storage_uri` |
| `observation` | append-only 观测历史 | `(entity_id, seen_at)` PK, `state_hash` |
| `tag_assignment` | 行级标签（替代数组挂载） | `(entity_id, dimension, label_id)` PK, `evidence_span` |
| `metric_fact` | 不可变指标 | `(metric_id, period_id, scope)` PK, `n`, `coverage` |
| `collection_coverage` | 覆盖账本（已建） | `(run_id, lane, business_date)` PK |
| `release_catalog` | 发布注册表 | `release_id` PK, `dataset_shas` |

---

## 5. `content_entity` 完整字段

| 字段 | 类型 | 约束 | 为什么需要 |
|---|---|---|---|
| `entity_id` | TEXT | PK | Reddit fullname（`t3_` / `t1_`），与外部 ID 对齐，避免前缀混乱 |
| `entity_type` | TEXT | NOT NULL, CHECK IN ('post','comment') | 一张表容纳两类实体 |
| `thread_id` | TEXT | FK → entity_id | 评论所属帖子；帖子为 NULL。用它替代当前的 `post_id` 冗余字段 |
| `parent_id` | TEXT | FK → entity_id, NULL | 评论的直接父（可能是另一条评论），支持层级 |
| `depth` | INTEGER | NULL | 评论深度，0 = 顶层 |
| **内容** | | | |
| `title` | TEXT | NULL | 仅帖子有 |
| `body` | TEXT | NOT NULL | 正文。空字符串与 `[deleted]` 语义不同，不可混淆 |
| `author_hash` | TEXT | NULL | 稳定假名，PII 已剥离 |
| `subreddit` | TEXT | NULL | 不带 `r/` 前缀，前端自己拼 |
| `permalink` | TEXT | NULL | 证据回溯入口 |
| **双时态** | | | |
| `event_at_utc` | TEXT | NOT NULL | **内容自身**的发生时刻（ISO8601 UTC） |
| `event_precision` | TEXT | NOT NULL, CHECK IN ('instant','day','unknown') | 日精度内容不得伪造时刻 |
| `source_date` | TEXT | NULL | 日精度时的原始日期（`YYYY-MM-DD`） |
| `first_seen_at_utc` | TEXT | NOT NULL | 我们**首次**观测到它的时间 |
| `last_seen_at_utc` | TEXT | NOT NULL | 最近一次观测时间 |
| `last_changed_at_utc` | TEXT | NULL | `state_hash` 变化的时间；NULL = 从未变化 |
| **可变状态** | | | |
| `score` | INTEGER | NULL | 最新观测的分数 |
| `num_comments` | INTEGER | NULL | 帖子报告评论数 |
| `lifecycle` | TEXT | NOT NULL, CHECK IN ('alive','deleted','removed','edited','unknown') | **显式墓碑**，不再靠正文猜测 |
| `state_hash` | TEXT | NOT NULL | 规范化状态的 SHA-256，用于判断"有没有变" |
| **采源** | | | |
| `first_seen_run_id` | TEXT | NOT NULL | **首次**采集它的 run，不被后续 run 覆盖 |
| `last_seen_run_id` | TEXT | NOT NULL | 最近一次采到它的 run |
| `raw_payload_id` | TEXT | FK → raw_payload | 回到原始字节 |
| `record_authority` | TEXT | NOT NULL | 记录权威来源（governed_base / backfill / workbook_net_new） |
| `is_backfilled` | INTEGER | NOT NULL DEFAULT 0 | 1 = 补采所得，指标可据此标注 |
| **治理** | | | |
| `created_at_utc` | TEXT | NOT NULL | 行创建时间（与 event_at 不同） |
| `updated_at_utc` | TEXT | NOT NULL | 行更新时间 |

### 5.1 关键设计说明

**为什么 `first_seen_run_id` 与 `last_seen_run_id` 都要有？**
当前 `upsert` 覆盖 `run_id`，导致"这个帖子是哪天第一次被采到的"永久丢失。两列分离后，补采可标注、覆盖度可计算。

**为什么 `state_hash` 而不是逐字段比较？**
一条记录有 10+ 个可变字段，逐字段比较代码冗长且容易漏。规范化 JSON 后哈希，一次比较即可判断变化，且哈希值本身可作为观测历史的去重键。

**为什么 `lifecycle` 而不是 `deleted_or_removed` 布尔？**
`[removed]`（版主删除，内容可能仍在）与 `[deleted]`（用户自删）语义不同，分析处理方式不同。布尔值无法区分，还会漏掉 `edited` 状态。

**为什么 `is_backfilled`？**
补采的 7 月数据与当日实时采集的数据，在时效性上不等价。指标层需要能标注"这一期包含回填"，否则时间序列会出现虚假的"突变"。

---

## 6. 迁移路径

| 阶段 | 动作 | 风险 |
|---|---|---|
| **M0（已完成）** | `collection_coverage`、`entity_observation` 建表并接线 | 无（新增表） |
| **M1** | 建 `content_entity`，从现有两表回填，`merge_snapshot` 改读新表 | 中：需一次性校验行数与内容一致 |
| **M2** | 公开 JSON 改为**由 SQLite 生成**，不再反读 | 中：发布链路切换 |
| **M3** | 退役 `reddit_threads` / `reddit_comments`（保留只读视图） | 低：可回滚 |
| **M4** | `analysis_results` / `delivery_previews` 补齐或删除 | 低 |

**M1 的回填校验**（必须通过才继续）：
- 行数守恒：`content_entity` 条数 == 两表之和
- 内容守恒：抽样 100 条的 `body` SHA 与原表一致
- 时间守恒：`event_at_utc` 分布与原表一致
- 幂等：重复执行不产生新行

---

## 7. 与前端契约的关系

**前端契约不变。** 公开 JSON 的结构、字段、字节校验规则全部保持，只是**生成方式**从"读旧文件 + 追加"改为"从 SQLite 查询 + 序列化"。这样：

- 本轮已修复的 7 个 manifest/lineage/守恒问题不会回退
- 前端不需要任何改动
- 存储层可以独立演进
