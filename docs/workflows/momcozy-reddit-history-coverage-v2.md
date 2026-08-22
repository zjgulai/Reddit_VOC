---
title: Momcozy Reddit 历史覆盖 V2 执行计划
status: active
updated: 2026-07-14
scope: 2025-01-01 至当前已验证快照的帖子与评论采集
owner_gate: production merge、Git push、DingTalk/live send 均需独立授权；TikHub 仍须通过已授权的远端凭证注入通道
---

# Momcozy Reddit 历史覆盖 V2 执行计划

## 当前结论

历史采集已经启动，但尚未完成。旧运行
`backfill_momcozy_20250101_20260711` 只冻结了 15 个搜索词，其中只有 12
个语义不同的词，并且没有任何竞争品牌专属搜索 lane。Task 37 staging 现有
301 个帖子、3,225 条评论，但仍有 95 个 `unresolved_more` 和 1 个
`post_only_coverage` 候选；Task 37 本身没有发出新的 TikHub 请求。

本地另有 136 个已导入 JSON、4,153 条评论的竞品/对比归档，已净增 88
个帖子和 2,259 条评论。这证明已有可用竞品数据，不证明 2025-01-01 至今的
竞争品牌或 SPU 历史搜索已经完整。

Task 37 与本地 canonical union 现已按 Reddit ID 精确对账。在目标窗口内，
两者重叠 78 帖/2,023 条已关联评论；Task 37 独有 223 帖/1,202 条评论，
本地独有 109 帖/1,505 条评论，去重后的潜在 union 为 410 帖/4,730 条
已关联评论。production 原有 18 条孤儿评论中，Task 37 已包含一个缺失父帖，
因此 8 条可结构性恢复：6 条 comment ID 精确重叠，另 2 条是 production-only
但可重新挂接到该父帖；仍有 10 条跨 3 个父帖缺少父帖证据。这些结果只证明
身份层去重，不授权 production merge。

Momcozy 官方只读商品目录现已补充产品名称证据：406 个当前目录商品中按
主商品 handle 归并出 18 个相关产品族，验证了现有 25 个型号候选中的 24
个别名，并新增 6 个官网名称搜索词。官网商品 ID 与内部 `spu_id` 不是同一
标识，`BS03` 也不得与官网当前 `BM03` 自动等同。

此前遗漏的 Phase 3 v3.5 内部产品主数据现已补入证据链：431 个 SPU 编码
唯一，标签字典的 254 个 SPU ID 全部精确命中中文/英文名称，名称 join 已
完成。`BS03=SPU000714`，`BM03=SPU000176`，两者保持不同实体。该 2026-05
快照没有 `active_status/effective_date`，所以当前在售判断仍以 2026-07-14
官网目录为准。内部口语词文件对 162 个已 join SPU 提供 772 个启发式变体；
因包含大量 SKU/配件及启发式品牌组合，本轮自动启用 0 个，V2 仍为 75 个
候选词/69 个 delta。

69 个 delta 已在本地 canonical 与 Task 37 staging 的现有正文表面上完成
只读词法覆盖审计：19 个无既有词法证据，4 个只有评论证据，9 个只有帖子
证据，37 个同时有帖子和评论证据；合计 46 个词有帖子表面证据、41 个词有
评论证据，涉及 299 个不同父帖。该审计只用于冻结 Provider 探针优先级，
不会把任何 lane 标记为已完成；69 个 Provider discovery lane 仍全部未执行。
当前 P0 首三项为 `"Momcozy BM03"`、`"Momcozy DeepClean"`、
`"Momcozy S12 Pro Quick"`。

V2 profile 现已通过本地 `profile-admission` 准入：新的隔离 run ID 为
`backfill_momcozy_v2_20250101_20260711`，固定 75 个候选词、69 个 delta，
且旧 run 未被改写。TikHub 官方文档确认 Reddit 子评论端点为
`/api/v1/reddit/app/fetch_comment_replies`，请求需要原始评论页中
`more.cursor`；本地已加入仅提取已归档 cursor 的逻辑，但尚未把未验证的
Provider 响应结构当作可入库数据。远端只读准入确认 staging/run 根目录存在，
但非交互 shell 未注入 `TIKHUB_API_KEY`，所以本轮仍没有 Provider 请求。

新的本地 V2 staging 已创建为
`backfill_momcozy_v2_20250101_20260714`，窗口固定到
`2026-07-14T13:32:19Z`。它受 profile SHA 约束且只含 69 个 delta lane；已
递归导入 136 个归档 JSON，其中 102 个落在窗口、34 个按时间窗排除，得到
102 帖 / 3,132 条评论 / 3,234 条分析记录。136 个 raw artifact 全部逐个验证，
父子完整性为 0 orphan，重复执行后 SQLite 字节一致。该 staging 的 Provider
ledger 仍为 0，不能把本地导入误称为 Reddit Provider 采集完成。

V2 staging 的评论覆盖审计进一步确认：3 个帖子带有 27 个 `More` nodes，
因此至少需要 3 次 TikHub 帖子评论首页请求才能取得 reply cursor；浏览器归档
不包含 TikHub `more.cursor`，所以后续子评论请求数尚不可知。69 条 V2 discovery
lane 与这 3 条评论首页请求必须使用独立 ledger/guard，不能合并为一个“已完成”
预算；逐帖 `reported_minus_parsed` 只是优先级信号，不是保证可取回行数。

旧运行的 96 个评论债务候选也已完成只读身份审计。Task 37 在这些候选上有
752 条精确评论 ID；本地 canonical union 只给 7 个候选补入 21 条不重复评论，
96 个候选仍全部存在 reported-count gap。离线 union 后缺口为 2,082，另有
148 个 `More` nodes。按当前 endpoint 合同，仅每候选一次评论首页请求的下限
就是 96 次，而旧 guard 只余 1 次；96 次仍不是完整闭环预算，reported count
也不等于保证可取回的评论行数。本轮没有尝试 Provider 请求。

## 权威证据

- 标签字典分析与可复现 notebook：
  [`analysis.ipynb`](../analysis/momcozy-historical-collection-audit-20260714/analysis.ipynb)
- 分析摘要：
  [`analysis-summary.json`](../analysis/momcozy-historical-collection-audit-20260714/analysis-summary.json)
- 数据校验回执：
  [`validation-receipt.json`](../analysis/momcozy-historical-collection-audit-20260714/validation-receipt.json)
- SPU 主数据仓库检索回执：
  [`spu-master-source-audit.json`](../analysis/momcozy-historical-collection-audit-20260714/spu-master-source-audit.json)
- 254 个内部 SPU 名称精确 join：
  [`internal-spu-master-join.json`](../analysis/momcozy-historical-collection-audit-20260714/internal-spu-master-join.json)
- Momcozy 官方商品目录快照：
  [`official-product-catalog-snapshot.json`](../analysis/momcozy-historical-collection-audit-20260714/official-product-catalog-snapshot.json)
- 官网产品名称映射：
  [`official-product-name-catalog.csv`](../analysis/momcozy-historical-collection-audit-20260714/official-product-name-catalog.csv)
- V2 搜索候选：
  [`momcozy-search-profile-v2-candidate-20260714.json`](../../config/backfill/momcozy-search-profile-v2-candidate-20260714.json)
  （SHA-256 `38706378f42c6648fe43bb50f60947863816363d65714f16a3092f40d91b604d`，
  `reviewed_candidate_not_activated`）
- Task 37 执行证据：
  [`task-37-remote-execution-report.md`](../../.superpowers/sdd/task-37-remote-execution-report.md)
- Task 37 身份只读快照：
  [`task37-identity-snapshot.json`](../analysis/momcozy-historical-collection-audit-20260714/task37-identity-snapshot.json)
- 跨源 ID 去重审计：
  [`cross-source-overlap-audit.json`](../analysis/momcozy-historical-collection-audit-20260714/cross-source-overlap-audit.json)
- 跨源只读 merge plan：
  [`cross-source-readonly-merge-plan.json`](../analysis/momcozy-historical-collection-audit-20260714/cross-source-readonly-merge-plan.json)
- 本地归档融合证据：
  [`fusion-audit.json`](../../data/imports/ai_nlp_voc_reddit_20260714/fusion-audit.json)
- Production 最新身份只读刷新：
  [`production-identity-refresh.json`](../analysis/momcozy-historical-collection-audit-20260714/production-identity-refresh.json)
- 69 个 delta 的离线词法覆盖与 Provider 探针优先级：
  [`delta-term-offline-coverage-audit.json`](../analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage-audit.json)
- 可审阅的 69-lane 优先级明细：
  [`delta-term-offline-coverage.csv`](../analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage.csv)
- 独立词法覆盖校验回执：
  [`delta-term-offline-coverage-validation.json`](../analysis/momcozy-historical-collection-audit-20260714/delta-term-offline-coverage-validation.json)
- 96 个候选的评论覆盖债务审计：
  [`comment-coverage-debt-audit.json`](../analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt-audit.json)
- 可审阅的评论修复优先级：
  [`comment-coverage-debt.csv`](../analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt.csv)
- Production orphan-parent 恢复矩阵：
  [`production-orphan-recovery-matrix.csv`](../analysis/momcozy-historical-collection-audit-20260714/production-orphan-recovery-matrix.csv)
- 独立评论债务校验回执：
  [`comment-coverage-debt-validation.json`](../analysis/momcozy-historical-collection-audit-20260714/comment-coverage-debt-validation.json)
- Task 38 运行时实施路径只读审计：
  [`task38-runtime-implementation-audit-20260714.json`](../analysis/momcozy-historical-collection-audit-20260714/task38-runtime-implementation-audit-20260714.json)
- Data Analytics 报告工件与校验回执：
  [`artifact.json`](../analysis/momcozy-historical-collection-audit-20260714/artifact.json)、
  [`artifact-validation-receipt.json`](../analysis/momcozy-historical-collection-audit-20260714/artifact-validation-receipt.json)
- V2 隔离 staging seed 校验回执：
  [`v2-isolated-seed-validation-receipt-20260714.json`](../analysis/momcozy-historical-collection-audit-20260714/v2-isolated-seed-validation-receipt-20260714.json)
- V2 staging 评论覆盖审计与逐帖优先级：
  [`v2-seed-comment-coverage-audit.json`](../analysis/momcozy-historical-collection-audit-20260714/v2-seed-comment-coverage-audit.json)、
  [`v2-seed-comment-coverage.csv`](../analysis/momcozy-historical-collection-audit-20260714/v2-seed-comment-coverage.csv)
- 竞品与品类历史采集盘点（只读）：
  [`competitor-category-history-inventory-20260715.md`](../analysis/momcozy-historical-collection-audit-20260714/competitor-category-history-inventory-20260715.md)、
  [`competitor-category-history-inventory-20260715.csv`](../analysis/momcozy-historical-collection-audit-20260714/competitor-category-history-inventory-20260715.csv)
- P0 竞品与品类采集进度：
  [`p0-collection-progress-20260715.md`](../analysis/momcozy-historical-collection-audit-20260714/p0-collection-progress-20260715.md)

## 完成矩阵

| 工作流 | 状态 | 当前证据 | 未完成门禁 |
|---|---|---|---|
| 标签字典质量核验 | 完成 | 2,346 行、tag_id 唯一、无空值、candidate/final 语义一致 | 无 |
| Momcozy 与竞争品牌提取 | 完成 | 1 个品牌主体、17 个字典治理竞品 | 无 |
| SPU 名称提取 | 名称 join 完成 | Phase 3 v3.5 对 254/254 个字典 SPU 提供中文/英文名称；BS03=SPU000714、BM03=SPU000176 | 内部快照没有 active_status/effective_date；当前在售仍以官网为准 |
| 旧历史搜索配置 | 部分完成且冻结 | 15 个词、12 个不同语义、无竞品专属 lane | 不得回改旧运行 |
| V2 搜索配置 | 隔离 staging 首页探针完成 | 75 个候选词，69 个 delta；69/69 lane HTTP 200、schema 校验通过、`provider_attempt_made=true`；首轮 payload 得到 394 个原始 ID，其中 388 个通过 Reddit ID 形状校验 | 每 lane 只执行一页；`pageInfo.endCursor` 后续分页仍未采集 |
| V2 评论覆盖 | 隔离 staging 首页与回复采集完成 | 372 个新帖子首屏报告，HTTP 200/校验通过 372/372，解析 1,568 条评论、182 个首屏 `More`；回复报告 658 个，HTTP 200/校验通过 658/658，解析 3,315 条、产生 476 个嵌套 `More`，候选闭合 0 未处理 | 仅完成 raw page-level 采集；canonical merge/export 仍未执行 |
| V2 delta 离线覆盖与探针优先级 | 优先级已完成，Provider 首页已执行 | 69/69 已审计：19 无证据、4 仅评论、9 仅帖子、37 帖子和评论均有；P0 从 `"Momcozy BM03"` 开始；本轮 69 个隔离 guard 均限制为单次 Provider 请求 | 不把一页探针当成全历史 discovery；后续分页与时间窗口仍待执行 |
| 竞品归档导入 | 本地完成 | 136/136 文件解析，4,153 条评论，88 帖/2,259 评论净增 | 不得当成 Provider 全覆盖 |
| Task 37 staging | 已由新 packet 采集补齐 raw 游标 | 基线 301 帖/3,225 评论；新运行首屏 96/96、回复请求 441 个；raw page-level parsed reply rows 2,056，剩余游标 0 | 不把 raw 行数当去重 canonical 行数；production merge 仍禁止 |
| 跨源 ID 去重 | 身份层完成 | 本地/Task37 重叠 78 帖/2,023 评论；去重 union 410 帖/4,730 评论；8 条 production 孤儿可结构性恢复 | 10 条 production 孤儿仍缺少父帖证据；production merge 未授权 |
| 竞品/SPU 历史 lane | 离线优先级完成、Provider 未开始 | 69 个 delta 已按现有帖子/评论词法证据排序；0 个 Provider lane 完成 | 新运行、去重、probe、Provider 授权 |
| 2026-07-12 至当前 | 日报部分覆盖 | 最新只读刷新仍为 85 帖/414 评论、相较前快照增量 0；最晚帖子为北京时间 2026-07-14 06:37 | 下一日报快照或独立 catch-up |
| production merge / live send | 未授权 | `production unchanged`、`live_send=false`、`git_push=false` | 独立 owner gate |

## V2 搜索口径

V2 候选总计 75 个词，旧运行已精确覆盖其中 6 个，剩余 69 个 delta：

- 品牌别名缺口：1 个（`mcozy`）。
- Momcozy 型号/产品：25 个候选，旧运行覆盖 5 个，剩余 20 个。
- 官网产品别名：6 个，旧运行覆盖 0 个。
- 字典治理竞品：17 个，旧运行覆盖 0 个。
- 相关品类锚点：26 个，旧运行覆盖 1 个，剩余 25 个。

17 个字典治理竞品为：Baby Bjorn、Boppy、Comfelie、Dr. Brown's、
Elvie、Ergobaby、Haakaa、Kindred Bravely、Lansinoh、Medela、Nanit、
Owlet、Philips Avent、Spectra、Tommee Tippee、Wabi Baby、Willow。

旧运行必须保持不可变。V2 必须使用新 run ID、新 profile SHA 和独立
checkpoint，不得把 69 个 delta 直接写入旧 manifest。

内部 SPU 名称 join 没有改变查询集合：772 个口语变体仅作为待审别名证据，
没有自动进入 profile。当前 75/69 配置继续由治理品牌、官网当前产品名与高
信号品类锚点组成，避免用内部 SKU 编码或配件名制造高噪声 lane。

现有语料的离线词法命中只说明“已知数据中能否看见该短语”，不证明 Reddit
历史发现已穷尽，也不能替代 Provider 搜索。探针顺序固定为：无证据、仅评论、
仅帖子、帖子与评论均有；同类内优先官网别名、Momcozy 型号、owner alias、
竞品、品类。69 个 delta 全部保留为待执行 lane。

## TODO

### A. 已完成的断点

- [x] 对 `dim_tag_v6.3_final.csv` 与 candidate 做语义/字节差异、完整性、唯一性、关键词冲突和范围分布核验。
- [x] 提取 Momcozy、17 个治理竞品、254 个 SPU ID、24 个 SPU 级 `voc_category`。
- [x] 从 Phase 3 v3.5 内部产品主数据完成 254/254 个 `spu_id -> spu_name/product_name_en` 精确 join；明确缺少 active_status/effective_date，未把 772 个启发式口语变体自动激活。
- [x] 只读抓取 Momcozy 官方目录并验证 18 个当前产品族、24 个现有别名和 6 个官网新增搜索词；明确 BS03/BM03 不等同。
- [x] 导入并校验 136 个外部 Reddit JSON；隔离 18 条生产孤儿评论。
- [x] 执行 Task 37 一次性 staging guard；确认实际 `provider_call=false`。
- [x] 从保留的 Task 37 staging 以 SQLite immutable/query-only 模式导出身份字段，并完成与本地 canonical union 的精确 ID 对账；未导出正文或用户名，远端无写入。
- [x] 冻结 V2 候选搜索 profile；保持旧 15 词运行不可变。
- [x] 对 69 个 delta 完成本地 canonical + Task 37 staging 的只读词法覆盖审计与独立校验，冻结 P0/P1/P2/P3 探针顺序；没有把词法命中冒充 Provider lane 完成。
- [x] 对 96 个旧运行 partial 候选完成只读评论身份 reconciliation 和独立校验：本地仅净增 21 条，仍有 2,082 reported-count gap、148 个 More nodes，首页请求下限 96 次；没有触发 Provider。
- [x] 更正 production orphan 恢复口径：8 条可由 Task 37 父帖结构性恢复，其中 6 条 comment ID 精确重叠、2 条 production-only；10 条仍缺少父帖证据。

### B. Task 38：本地新运行合同

- [x] 从项目记录的 Phase 3 v3.5 内部产品主数据补齐 254/254 个 `spu_id -> spu_name/product_name_en`；`voc_category` 与官网商品 ID 均未冒充内部 SPU ID。
- [ ] 若未来把 772 个内部口语变体用于查询，必须先按品牌、主产品/配件、当前状态和 Reddit 信号做人工治理；本轮自动启用 0 个。
- [x] 新增独立 V2 profile loader 和新 run ID；旧 `DEFAULT_TIKHUB_SEARCH_TERMS`、旧 baseline、旧 release manifest 均未改写。
- [x] 为 profile hash、term 去重、lane 快照、旧运行隔离和未知字段 fail-closed 增加 RED/GREEN 测试；V2 准入和相关回归为 `241 passed, 218 subtests passed`。
- [x] 在 `backfill_momcozy_v2_20250101_20260714` 创建新隔离 staging；递归导入 136 个既有原始 JSON（102 window 内导入、34 outside），raw、父子完整性、空 Provider ledger 与 SQLite byte-identical replay 均已验证。
- [x] 完成运行时只读审计：当前 hydrator 只处理 `pending` 候选，`hydrated/unresolved_more` 与 `hydrated/post_only_coverage` 没有 reopen 迁移；现有评论请求只有 `post_id`/`after`，缺少已验证的 More-child 合同，因此不得把重复首页面伪称为补采。
- [x] 只读导入 136 文件归档与 Task 37 ID 清单并完成目标窗口 overlap reconciliation；原始 layer 计数仍不得直接相加，只可使用 410 帖/4,730 条已关联评论的去重 union。
- [x] 生成只读、不可执行的 merge plan：保留本地独有 109 帖/1,505 评论，引入 Task 37 独有 223 帖/1,202 评论，并把 8 条可结构性恢复的 production 孤儿评论作为独立恢复候选；其中 6 条是 exact duplicates、2 条是 production-only；未执行 production merge。
- [ ] 当前 no-test 协调边界解除后，在新的 local isolated staging 中实现上述 merge plan，并用主键、父子完整性、内容等价与 replay 测试验证；不得直接写 production。
- [ ] 生成 query-only admission、lane 数量、每 lane 首页面上限和 one-shot guard 候选。

本地测试协调边界已解除。下一项阻断不是本地 gate，而是远端 one-shot shell
缺少已批准通道注入的 `TIKHUB_API_KEY`；不得用文件、命令行或日志替代该通道。

### C. V2 Provider discovery

- [x] 基于既有只读语料冻结 69-lane 离线优先级：19 个无证据 lane 为 P0，4 个仅评论为 P1，9 个仅帖子为 P2，37 个帖子/评论均有为 P3。
- [x] 由实际准入 lane 数生成 69 个 one-page-per-lane probe；每 lane 使用独立 packet、staging 与 one-shot guard。
- [x] 冻结 packet、CLI、runner、source DB/raw tree/profile/release manifest 的 SHA；未改写旧运行。
- [x] 按自动授权规则执行 69 次 Provider 请求，每个 guard `provider_invocation_limit=1`；HTTP 200/响应校验通过 69/69。
- [x] 记录首轮结果：原始帖子 ID 394 个，按 Reddit ID 形状校验后有效 388 个；3 个 lane 返回零有效帖子。
- [ ] 由真实 probe 的 `pageInfo.endCursor` 继续分页，推导完整 discovery/hydration 预算；当前不能宣称历史 discovery 已穷尽。

### D. 旧运行评论覆盖债务

- [x] 完成 96 个 partial 候选的离线精确 ID reconciliation、More-node 分布、reported-count gap 分层与 31/31 + 30/30 双重校验；确认本地仅补 21 条且 96 个候选均未闭合。
- [ ] 为 95 个 `unresolved_more` 和 1 个 `post_only_coverage` 设计显式 reopen 状态迁移。
- [ ] 完成 More-child 响应解析合同；当前已实现并测试首屏 response 的身份/schema、评论、More 节点与 cursor 摘要，Task39 已取得 1 个可验证首屏 Provider 响应，但尚未取得 More-child 响应样本。不得把 96 次首页请求下限解释为完整闭环预算，也不得把 2,082 gap 解释为保证可取回行数。
- [ ] 把 reopen/comment hydration 与 V2 discovery 分成两个预算和两个 guard，避免相互吞预算。
- [ ] 通过本地测试、replay 和独立审查后再申请远程执行；Task 37 guard 不得复用。

### D1. Task 39 评论重开 packet（一次性执行记录）

- [x] 新增只读 `comment_repair` 队列：按 `unresolved_more`、More 节点数和 reported/parsed gap 排序；远端当前冻结快照为 95 个 `unresolved_more` + 1 个 `post_only_coverage`。
- [x] 将 96 个候选的首屏 raw artifact ID/payload SHA 纳入计划哈希；确认每个候选均只有 page 1、没有可直接复用的 checkpoint cursor。
- [x] 生成新的 Task 39 candidate packet：packet SHA `61716f614774e7e4850660a2262fa7f1ce38f912dc0e3dd9cd53d58ea9e01853`，plan file SHA `bb2945038d25f6506f8a7d548373f36008cf658c1193169ac7b369c09a5caed5`，bundle SHA `00ec4565eb16864de0801f78958a7cd093c130f49fcd78bd48baf5c85315006b`，runner SHA `9fa709d2bae7d39092b6b23f6e57d84601cca6ec43490420ca4996b6af9e6880`。
- [x] 新 runner 固定 `sudo -n` root-only 远端访问、全新 staging/guard 和最多 1 次首屏 Provider 请求；旧 Task 37 packet/guard 不复用。
- [x] 用户已提供 packet `61716f614774e7e4850660a2262fa7f1ce38f912dc0e3dd9cd53d58ea9e01853`、bundle `00ec4565eb16864de0801f78958a7cd093c130f49fcd78bd48baf5c85315006b`、runner `9fa709d2bae7d39092b6b23f6e57d84601cca6ec43490420ca4996b6af9e6880`；工件已上传并按哈希安装。
- [x] 一次性 runner 已执行：`provider_attempt_made=true`，仅调用 `/api/v1/reddit/app/fetch_post_comments` 1 次，HTTP `200`；隔离 staging/guard 已创建，source DB SHA 保持 `8356981018466164fe1f84953bd1e1e19010114817dd9689a31b996d9cc51497`。
- [ ] 96 个修复候选仍未闭合：本次仅完成 1 个候选的首屏探针（post `1uj41a9`，`commentCount=169`，`hasNextPage=true`）；不得据此宣称历史采集完成。剩余请求需新的 exact packet 与独立授权。

### D2. Task 40 评论重开 packet（待授权）

- [x] 基于 Task39 的只读执行证据排除已探测 post `1uj41a9`，生成剩余 95 个候选的新 plan；Task39 packet 不复用。
- [x] 新 packet：packet SHA `5aeb09bc890c75a46a5db70af1303e3ae0c2d3b5fd986ed91ad0ca3e59650e28`，plan SHA `408a7f3702ff4114062274627c3726ce5d1bfce66b28219837feeba06d64e7b3`，bundle SHA `9e95b37c47c56564e3bd26ef025a248072a6600c0977951f6dc730c8e6cebd3e`，runner SHA `b330367b4e7882bd084428ded7a05be289dc4b2fe8bc7cc71f5e6a3ffdba4bbb`。
- [x] bundle 内新增首屏响应 schema/身份校验与评论、More 节点摘要，避免下一次执行只留下未验证的 raw payload。
- [x] Task40 已在 bundle/runner 哈希门禁后发出 1 次请求，但响应解析失败（`runner_rc=1`），raw 未落盘；guard/staging 已创建，不能重试，source DB 未变。
- [x] Task41 已生成 fail-safe runner：packet SHA `8faf6cc47109311a2819e0cad4c85e3e120f1516db061c95a104c12bcf1c1301`，plan SHA `408a7f3702ff4114062274627c3726ce5d1bfce66b28219837feeba06d64e7b3`，bundle SHA `68eec63fef2ff6c09cab393fd646693a02ecbb546b3811090f8b99d7d7f4a550`，runner SHA `141c9d768519ebb0920d39f55f400527ab024d0d1f4f2e616f01b37a35f22387`。
- [x] Task41 已发出 1 次请求，但隔离 runner 的 `PYTHONPATH` 错误导致 import 失败，raw 仍未落盘；guard/staging 已创建，不能重试，source DB 未变。
- [x] Task42 已生成并修正 `PYTHONPATH=${CODE}/src`：packet SHA `4c76935235a23d7f5d7fea11425a70a53d73cc180b3c354ef3f61eb45ca567ce`，plan SHA `408a7f3702ff4114062274627c3726ce5d1bfce66b28219837feeba06d64e7b3`，bundle SHA `68eec63fef2ff6c09cab393fd646693a02ecbb546b3811090f8b99d7d7f4a550`，runner SHA `6c24ca155380400ec5c39fc55cbd6e14efbcb1c3e10825a7e1315349780e55d1`。
- [x] Task42 已成功完成 1 次请求：post `1ucuux5`，HTTP `200`，raw payload SHA `16fd6868019cb4a38ebd7ba3c06fcd5e66abd686d990ed167bf1d35091096bc0`，解析 8 条评论、4 个 More 节点/4 个 cursor，`commentCount=71`、`hasNextPage=true`；source DB 未变。
- [ ] Task43 新 packet：packet SHA `930ed1357a437a9927ee396dacd77b4d29b057cd543a859e67cf5ea1c41f848b`，plan SHA `a1be1ec5240cc6bd5c9d2169d3de2e733769cf157e1b7cc7cabbd7e8cf73bf0c`，bundle SHA `68eec63fef2ff6c09cab393fd646693a02ecbb546b3811090f8b99d7d7f4a550`，runner SHA `7b7b99c2f13743bbf7c40f8c6500688ebd120bf391ebc6b496d7219e5cf2c26d`；已排除 `1ucuux5`，剩余 94 个候选，等待新授权。
- [x] Task43 已成功完成 1 次请求：post `1u9zf0q`，HTTP `200`，raw payload SHA `34a6631d8ad549a571978790ae40c04805a3ce7e642a56128d384fb26aac9590`，解析 8 条评论、3 个 More 节点/3 个 cursor，`commentCount=64`、`hasNextPage=true`；source DB 未变。
- [ ] Task44 新 packet：packet SHA `4aef77d4c9d9cfe5afffe08fd5d8117d85c54d9eae5f09f909ab013d546eaa2f`，plan SHA `d5ddd5b62eec6445da75971ec60aeca6c4764e618afba1580c1ca0cff681c150`，bundle SHA `68eec63fef2ff6c09cab393fd646693a02ecbb546b3811090f8b99d7d7f4a550`，runner SHA `01a3f43356cb7bdd5091aff1650b3fb1148dc9af8680ef73f93ed0817f44537a`；已排除 `1u9zf0q`，剩余 93 个候选，按自动授权规则待执行。

### D3. Task 138–579 More-child raw 采集收口（2026-07-15）

- [x] 新 packet/runner 逐游标执行；每个 packet 最多 1 次 TikHub Provider 请求，未复用旧 packet。
- [x] 首屏报告 96/96、首屏唯一帖子 96/96；发现首屏 `More` cursor 148 个。
- [x] 回复报告 441 个（Task 138–579 的成功报告，Task 352 无报告且不重试）；HTTP 200 为 441/441，`response_validation=passed` 为 441/441，`provider_attempt_made=true` 为 441/441。
- [x] 441 个唯一回复请求全部从候选集合闭合，未处理游标 0；回复报告解析到 2,056 条 page-level 评论行，产生 293 个嵌套 `More` 节点。
- [x] 隔离 staging/guard 保留 raw 报告；未执行 SQLite/canonical merge、production merge、Git push 或 DingTalk/live send，production unchanged。
- [ ] 证据缺口保留：Task 138 报告/raw 有效但 binding JSON 格式损坏；Task 352 未生成报告、Provider 尝试结果未知，其游标已由 Task 353 的新 packet 成功回收。不得把两项写成成功请求。

### D4. V2 discovery、首屏评论与递归回复（2026-07-15）

- [x] 69/69 搜索 lane 完成独立一页探针；69/69 HTTP 200、响应校验通过，69/69 guard 的 `provider_call=true` 且 `provider_invocation_limit=1`。
- [x] 搜索 raw payload 发现 394 个原始 ID；其中 388 个通过 Reddit ID 形状校验，3 个 lane 为零有效帖子。搜索响应仍带有 `pageInfo.endCursor`，所以这里只是 bounded first-page discovery。
- [x] 对去除旧运行重叠后的 372 个新帖子完成首屏评论采集：HTTP 200/校验通过 372/372，解析 1,568 条 page-level 评论，发现 182 个首屏 `More`。
- [x] 完成递归回复采集：658 个唯一 `(post_id, cursor)` 报告，HTTP 200/校验通过 658/658，解析 3,315 条 page-level 评论，产生 476 个嵌套 `More`；candidate accounting 闭合，未处理游标 0。
- [x] 1,033 个 V2 comment/reply guard 的 provider binding 全部为单次上限，`binding_forbidden_count=0`；未执行 SQLite/canonical merge、production merge、Git push 或 DingTalk/live send，`production unchanged`。
- [ ] 继续采集搜索 `endCursor` 后续页并完成时间窗口、去重与 canonical merge 前的只读验收；当前不宣称 2025-01-01 至今全历史完整。

### D5. P0 竞品与品类 continuation（2026-07-15）

- [x] 对 9 个 P0 lane 继续执行 159 个独立 continuation packet；全部 HTTP 200、响应校验通过，得到 844 个有效 Reddit 帖子 ID，并另行保留 32 个非 Reddit 形状 raw ID。
- [x] 9 个 P0 lane 当前均已分页终止；这只表示 Provider 分页终止，不得写成 canonical 历史完整。
- [x] 将 P0 发现帖子接入首屏评论与回复 worker：844 份有效帖子评论报告（838 通过、6 fail-closed，3,985 条解析评论；6 份均为不重试的 source-only ID），821 份 P0 回复报告（821/821 通过，3,921 条解析评论）；首屏评论缺口为 0，candidate accounting 仍有 279 个未处理回复游标。
- [x] 本批新增评论/回复 binding 均为单次 Provider 上限，禁止动作标志全部为 false；未执行 SQLite/canonical merge、production merge、Git push 或 DingTalk/live send。
- [ ] 处理 279 个 P0 回复游标，并完成 P0 的按 `post_id/comment_id` 去重与只读验收；当前仍不能宣称 P0 历史完整。

### E. 截止“至今”的滚动衔接

- [ ] 固定 V2 历史结束点与 production daily 起点，按 `post_id` 去重，证明没有时间洞或重复计数。
- [ ] 对北京时间 2026-07-14 06:37 之后的数据使用下一日报快照或独立 catch-up；不能把当前半日快照说成全天完成。

### F. 验收与后续门禁

- [ ] 每个必跑搜索 lane 终止于可解释状态；candidate accounting、评论 cursor、raw lineage、replay fingerprint 全部闭合。
- [ ] 输出 2025-01-01 至 cutover 的品牌、型号、品类覆盖矩阵和未解析列表。
- [ ] validation 通过后只生成 read-only merge plan。
- [ ] production merge、Git push、DingTalk/live send 各自等待独立授权。

## 完成定义

只有同时满足以下条件，才可声明“2025-01-01 至今历史采集完成”：

1. 权威 SPU 名称已补齐或明确排除不可得范围；（当前 254/254 已满足名称 join，active/effective 状态仍按官网边界处理）
2. 旧品牌运行、V2 竞品/型号/品类运行与 daily cutover 的 ID/时间重叠已核对；
3. 所有必跑 discovery lane 和评论 lane 都有可解释终点；
4. raw、SQLite、analysis、replay、时间窗口和请求预算校验全部通过；
5. 未把 staging、导入归档、production read-only 或日报快照混称为 production merge；
6. `live_send=false`，除非另有独立明确授权。
