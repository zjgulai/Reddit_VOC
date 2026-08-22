---
title: Reddit VOC 历史回溯与每日增量统一融合 V1
doc_type: architecture_and_execution_spec
status: phase_4_full_v3_baseline_bridge_validated
created: 2026-07-17
updated: 2026-07-17
owner: codex
project: Reddit_VOC
production_boundary: production_unchanged
provider_call: false
database_write: false
remote_write: false
deploy: false
schedule_change: false
live_send: false
---

# Reddit VOC 历史回溯与每日增量统一融合 V1

## 1. 已确认的产品与架构决策

1. 每日业务范围为“过去 24 小时新帖 + 活跃历史帖子过去 24 小时新增评论”。
2. 自动化到 candidate 为止：自动采集、自动融合、自动生成和注册 candidate；生产
   release 继续由负责人受控切换。
3. 品牌、竞品、SPU、subreddit 或查询规则变更后，先完成对应历史 delta 回溯，才允许把
   新旧窗口直接用于同环比。
4. 采用方案 A：不可变 SourceBatch + 微批融合 + 版本化静态发布；PostgreSQL 事件仓库仅
   作为未来规模化升级方向。
5. 活跃帖子生命周期：普通帖子发布后 30 天内或最近 7 天仍有新增评论；高风险、品牌介入、
   内容合规、管理员曝光和人工案例延长至 90 天，连续 30 天无新增评论后退出活跃池。

退出活跃池只停止每日刷新，不从中心数据集删除帖子、评论、版本、来源或分析事实。

## 2. 目标与非目标

### 2.1 目标

- 历史回溯和每日增量共享采集、原始证据、分页、checkpoint、错误和批次合同。
- 每一次 Reddit 发现都可追溯到 batch、raw object、查询 lane、分页与 Provider 请求。
- 实体身份、来源出现、内容版本和互动量观察分离，避免最新采集覆盖历史证据。
- 中心总数据集只有融合任务可以写入；采集器和 React 均不直接写或读其内部存储。
- 同一冻结输入可确定性重放；同内容返回 no-change；失败不改变 production current。

### 2.2 非目标

- 本规格不授权 Provider 请求、远端数据库写入、cron/systemd 修改或生产发布。
- 本规格不把当前日报 SQLite 改造成中心仓库。
- 本规格不自动切换生产 release，也不改变采集后台、共享 Nginx、TLS、DNS 或其他 Docker。
- 本规格不要求实时流式处理；日级微批足以支撑当前洞察站。

## 3. 第一性数据流

```text
historical_backfill ─┐
                     ├─> immutable SourceBatch ─> occurrence ledger
daily_incremental ───┘                              │
                                                    v
                                       single-writer canonical fusion
                                                    │
                     ┌──────────────────────────────┼────────────────────────┐
                     v                              v                        v
             canonical entities             content/engagement       relationship debt
                     │                         version ledger              ledger
                     └──────────────────────────────┼────────────────────────┘
                                                    v
                                    VOC / tags / atomic metrics / personas
                                                    v
                              Base → Reports → Insights → Personas → candidate
                                                    v
                                      controlled production promotion
```

采集是可重试的生产者，SourceBatch 是不可变交付边界，fusion 是 canonical 的唯一写者，
release builder 是网站唯一数据出口。

## 4. 业务时间合同

每日 07:00（Asia/Shanghai）形成一个闭合业务窗口：

```text
metric_window = [前一日 07:00, 当前日 07:00)
new_post_discovery_window = [前一日 05:00, 当前日 07:00)
```

两小时重叠只用于晚到发现和重试补偿。帖子、评论进入日报和趋势指标时必须按
`metric_window` 重新裁切，因此不能重复计数。

每日任务包含两个独立 lane：

- `new_post_lane`：发现窗口内的新帖子，并获取帖子详情和评论树。
- `active_thread_lane`：刷新活跃历史帖子，只接纳 metric window 内首次观察到的新增评论，
  同时保存内容变化和互动量快照。

如果到报告截止时间仍没有新的可消费 batch，日报使用最后一个已闭合 canonical release，并
明确显示数据截止时间；不能让未闭合采集结果直接进入报告。

## 5. SourceBatch V2 合同

实现入口：

- `src/reddit_voc/source_batch.py`
- `src/reddit_voc/raw_artifacts.py`
- `src/reddit_voc/daily_source_batch.py`
- `src/reddit_voc/backfill_source_batch.py`
- `src/reddit_voc/v3_baseline_source_batch.py`
- `scripts/validate_reddit_source_batch.py`
- `scripts/build_reddit_v3_baseline_source_batch.py`
- `scripts/build_reddit_v3_baseline_bridge_receipt.py`
- `scripts/validate_reddit_v3_baseline_center.py`
- `scripts/run_daily_collect.sh`
- `tests/test_source_batch.py`
- `tests/test_validate_source_batch.py`
- `tests/test_daily_source_batch_export.py`
- `tests/test_backfill_source_batch_export.py`

### 5.1 Manifest

每个 batch 根目录必须有 canonical JSON：

```text
source-batch-manifest.json
```

核心字段：

```text
schema_version = reddit_voc_source_batch_v2
batch_id
producer_type = historical_backfill | daily_incremental | comment_refresh
status = success | partial | empty | failed
window
profiles
active_thread_policy
members
counts
boundaries
```

`success`、`partial`、`empty` 可以进入融合；`failed` 仅可审计，不可消费。

### 5.2 必需成员

成员角色固定且按名称排序：

```text
checkpoints
comment_occurrences
comments
issues
post_occurrences
posts
raw_index
```

每个成员绑定相对路径、bytes、rows 和 SHA-256。所有 JSONL 必须为逐行 canonical JSON，
拒绝重复 JSON key、空行、symlink、越界路径、bytes/rows/hash 漂移。

`raw_index` 的每一行继续绑定原始 payload 的相对路径、bytes 和 SHA-256；manifest 绑定的
不只是解析结果，也包括不可变原始证据。

### 5.3 Profile 绑定

每个 batch 同时绑定：

- `query_profile_version` / `query_profile_sha256`
- `coverage_profile_version` / `coverage_profile_sha256`

query profile 管品牌、竞品、SPU、关键词、subreddit 和检索 lane；coverage profile 管分页、
评论水合、活跃帖、时间重叠和停止条件。任一 profile 变化都产生新版本，不能覆写旧 batch。

### 5.4 独立校验回执

校验器重新打开 manifest、全部 JSONL 和 raw payload，成功后生成：

```text
schema_version = reddit_voc_source_batch_validation_receipt_v1
status = passed
manifest_sha256
batch_id / producer_type / batch_status / consumable
profile_bindings
counts
source_boundaries
validation_boundaries
```

回执采用不可变写入：同内容返回 `no_change`，不同内容碰撞失败。校验器自身固定
`provider_call=false`、`database_write=false`、`remote_write=false`、`deploy=false`、
`live_send=false`、`production_unchanged=true`。

## 6. 中心总数据集

中心数据集不是某个采集 SQLite，也不是网站 public JSON，而是以下受管事实的合集：

### 6.1 追加账本

- `source_batches`：批次身份、窗口、profile、终态和校验回执。
- `raw_objects`：原始 payload 哈希、来源、捕获时间与物理位置。
- `entity_occurrences`：一个 Reddit 实体在哪个 batch/lane/page/raw object 被发现。
- `provider_attempts`：endpoint、request ordinal、状态、预算和错误。

这些记录只追加，不因去重或后续采集删除。

### 6.2 Canonical 实体与版本

- `canonical_posts`
- `canonical_comments`
- `comment_parent_edges`
- `content_versions`
- `engagement_snapshots`
- `relationship_debt`
- `quarantine`

帖子使用 `t3_<id>`，评论使用 `t1_<id>`。内容编辑产生新 content version；score、
upvote ratio、reported comment count 产生带观察时间的 engagement snapshot，不覆盖历史。

### 6.3 分析事实

- 帖子本身作为独立 VOC。
- 每条评论作为独立 VOC，并通过父帖取得语境。
- 需要组合推理时，生成“父帖上下文 + 单条评论”的派生分析单元，不改变原始帖子/评论事实。
- 标签、品牌、SPU、品类、竞品、情感、严重度、画像、风险和内容合规均绑定算法/字典版本。
- 标签字典或算法升级只重算分析事实与指标，不重新抓取 Reddit。

## 7. 融合与守恒规则

1. canonical identity 以标准化 Reddit ID 为准，URL 和文本相似度不能替代精确身份。
2. 每次重复发现都保留 occurrence；去重只作用于 canonical identity。
3. `created_at_utc` 等身份稳定字段冲突时进入 conflict ledger，不能静默覆盖。
4. 内容变化和互动量变化分别进入版本与快照，不混为一个“最新行”。
5. deleted/removed 是可观察状态，不删除已经保留的证据。
6. 评论的“归属帖子”和“即时父评论”分层：精确 `post_id` 可解析到 canonical post 时进入
   帖子级 linked；原始即时父级证据继续保留在 `source_record`。`post_id` 无法解析时才进入
   unresolved-parent，非法父级进入 quarantine。不能把历史源缺少即时父评论 ID 误报成帖子
   无法关联。
7. 生产已有 identity 默认 append-only；撤回必须进入独立治理流程。

每个 batch 和 candidate 必须满足：

```text
source occurrences
= accepted new + accepted duplicate + superseded + conflict + quarantine + invalid

stored comments
= linked + unresolved-parent + quarantined
```

两式任一未守恒时不得注册 candidate。

## 8. Profile 变更与历史 delta

query/coverage profile 变更时固定执行：

```text
新 profile candidate
→ 计算与当前 profile 的 lane delta
→ 使用新 run_id 和新 profile SHA 执行历史 delta
→ 历史 SourceBatch 校验
→ canonical 融合与指标重算
→ 新旧周期可比性校验
→ 才开放同环比和趋势方向
```

如果 delta 尚未闭合，单周期事实仍可显示，但跨周期方向必须标记为 profile 不可比；不得把
检索范围扩张解释为品牌声量增长。

## 9. 调度、并发与失败边界

- 每日任务优先级高于历史回溯，二者使用独立 Provider 预算和 checkpoint。
- 两类采集可并行生成 SourceBatch，但 canonical fusion 使用 singleton lock，保持单写者。
- fusion 只读取通过校验且达到 terminal/quiescence 的 batch。
- 同一 batch SHA 已消费时返回 no-change，不重复写 canonical 或生成新 release。
- 历史任务失败只暂停相应时间分片；不能阻塞已闭合的每日 batch。
- 每日 partial batch可以入候选，但必须完整携带 issue、continuation 和 coverage debt。
- candidate 构建失败保持 production current 不变；生产切换继续使用精确授权和原子 pointer。

## 10. 分阶段 TODO

### Phase 0：规格与边界

- [x] 确认每日新帖 + 活跃历史评论业务口径。
- [x] 确认 candidate 自动、production 受控。
- [x] 确认 profile 变化先历史 delta。
- [x] 确认方案 A 和 30/7、90/30 活跃生命周期。
- [x] 冻结统一架构和中心数据集分层。

### Phase 1：SourceBatch V2

- [x] 实现 manifest parser 和严格字段合同。
- [x] 绑定必需 JSONL、bytes、rows、SHA-256。
- [x] 绑定 raw payload index 并复核原始文件。
- [x] 拒绝 traversal、symlink、重复 JSON key、非 canonical JSON 和 hash drift。
- [x] 实现每日严格 24 小时窗口与活跃帖子策略校验。
- [x] 实现 consumable/failed 分离。
- [x] 实现不可变独立 validation receipt。
- [x] 完成 focused 红绿测试。

### Phase 2：采集器适配

- [x] 从现有日报 SQLite/outputs 导出 daily SourceBatch，不改变现有日报结果。
- [x] 从 backfill manifest/raw artifacts/checkpoints 导出 historical SourceBatch。
- [x] 建立 browser/TikHub discovery、detail、comments 共用 immutable raw persistence。
- [x] 建立 query profile 与 coverage profile 配置文件及 SHA 冻结。
- [x] 为 exporter 增加 no-change、缺失 raw 和 tamper fail-closed 测试。

### Phase 3：活跃历史评论

- [x] 建立 active thread registry 和 30/7、90/30 状态转移。
- [ ] 将管理员曝光、品牌介入、内容合规、高风险和人工案例映射为 priority reason code。
- [x] 建立正式 active refresh CLI、独立 wrapper、同 run 零调用重放和轮转 checkpoint。
- [ ] 取得脱敏 reply fixture 后复用 backfill reply cursor 消费能力。
- [x] 新增评论通过 canonical ID 去重，所有重复观察保留 occurrence。
- [x] 保存内容版本和 engagement snapshot。
- [x] active refresh 使用独立线程上限和独立 SourceBatch lane；未修改 cron。

### Phase 4：中心融合

- [ ] 扩展 V3 source manifest，使其消费 SourceBatch，不再只面向 workbook/base 输入。
- [x] 将已独立验证的完整 V3 canonical 基线转换为 SourceBatch V2，并登记不可变 bridge receipt。
- [x] 建立 batch consumption ledger，确保一个 manifest SHA 只消费一次。
- [x] 将 occurrence、canonical identity、content version、engagement snapshot 和关系债务分层。
- [x] 建立 comment parent edge、unresolved-parent、quarantine 和全账本 state SHA。
- [x] 完成 occurrence/raw terminal、评论关系、重放确定性、late arrival、轮转和 no-change 测试。

### Phase 5：分析与 candidate 自动化

- [ ] 从新 canonical release 重算帖子 VOC、评论 VOC 和组合上下文事实。
- [ ] 重算标签、Momcozy/竞品、品类、product family、exact-SPU、情感、画像和风险。
- [x] 建立日/周/月和五产品 surface 同源的 V2 metric release 合同。
- [x] 在 V2 candidate orchestrator 前强制 passed receipt、manifest SHA 和双点静稳 gate。
- [x] 自动注册本地 candidate；无业务变化生成 no-change receipt。
- [x] 保持 `deploy=false`、`remote_write=false`、`production_unchanged=true`。

### Phase 6：Shadow、E2E 与受控启用

- [ ] 至少连续两个每日周期同时运行旧链和新链，只读比较帖子、评论和报告指标。
- [ ] 对差异逐条归因：late arrival、活跃旧帖评论、分页补齐、版本变化或错误。
- [ ] 验证日报准时、历史回溯不中断、candidate 可回滚、采集器/cron/其他 Docker 不变。
- [ ] 通过完整本地、候选和浏览器验收后生成独立生产提升 packet。
- [ ] 生产切换必须另行取得精确 packet/release 授权。

## 11. 验收标准

- SourceBatch 同输入重跑 manifest 和成员 SHA 完全一致。
- 重叠窗口不会造成 canonical 或指标重复。
- 活跃旧帖的窗口内新增评论可以关联历史父帖。
- 每个实体的所有来源出现均可追溯，最新状态不覆盖内容/互动历史。
- checkpoint 中断后继续，不重发已成功页，不越过 Provider 预算。
- profile 变更未完成历史 delta 时，趋势方向不会被误开放。
- 比较窗口必须由 passed-receipt SourceBatch 的时间窗并集无缺口覆盖；closure 回执必须绑定
  精确 manifest/validation receipt/profile 证据，不能只声明起止时间。
- 历史和每日任务同时运行时，日报优先级和预算不受影响。
- candidate 失败或 no-change 时 production current 不变。
- 报告、洞察、画像和案例所引用的数据版本可回溯到同一 canonical release。

## 12. 当前证据边界

本地 SourceBatch producer、active thread registry、center fusion、metric release、candidate registry
和独立 validator 已实现。2026-07-17 的 V3 全量基线桥接也已本地关闭：输入为独立验证的
`reddit_add_data_20260715_v1_canonical_v1`，转换后的 SourceBatch manifest SHA-256 为
`fcb6b5d18e823e2b63feacc906fa2c4a0fd8807a1561d4f155d6cf6912abd77d`，bridge receipt SHA-256 为
`2e21861c5a73d7d9e1db6c33c0c04f8d8ed9d37b1b8893731592fea55c5463f4`。中心库守恒为：

```text
posts=3494
stored_comments=27158
linked_comments=20205
unresolved_parent_comments=6943
quarantined_comments=10
post_identity_missing/unexpected=0/0
comment_identity_missing/unexpected=0/0
```

独立零差异回执 SHA-256 为
`d5e0c883d6d6a3dd87b4181ffa265ce050d47d584db5929745751abf1d2a7053`；候选独立校验通过，
创建后重放为 `no_change`。这只关闭“完整基线进入 V2 中心”的部分，不代表网站 V2 已可生产
提升：完整 reply cursor、从中心重算 facts/标签/报告/洞察/画像、全页 E2E 与至少两个 shadow
周期仍未关闭，因此生产保持不变：

```text
production unchanged
provider_call=false
database_write=local-test-only
production_database_write=false
remote_write=false
deploy=false
schedule_change=false
live_send=false
```
