# ADR-004: 统一事实库收口与 personas/insights 重建

- **状态**: Accepted（M-A、M-B 均已执行并通过 2026-10-29 07:05 流水线实战检验）
- **日期**: 2026-10-29
- **决策人**: Echo-Agent 核心研发团队
- **关联**: ADR-002（数据时效对齐）、ADR-003（采集双通道）、M1/M2 迁移（content_entity 落地）

---

## 1. 背景与问题陈述

2026-10-28 全量语料发布（17,469 帖 / 58,296 评）后，审计发现两类被搁置的结构性缺口：

### 缺口一：事实库与发布集倒挂

服务器三层数据计数**真相箭头倒挂**——按数据流应当 单调递增 的各层，实际是：

```
content_entity 11,018 帖 / 27,123 评
      ↑ M1 迁移 ran BEFORE 最后两个归档周完成
reddit_threads 13,860 帖 / reddit_comments 37,687 评
      ↑ 归档导入写 legacy 表(可能未走双写)
发布数据集 17,469 帖 / 58,296 评   ← 最大
      ↑ 由本地全量构建后上传
```

**倒挂的三重后果**：

1. **明早 07:05 流水线依赖 DB → 发布集**：`step3_merge_snapshot` 从 legacy 表按时间窗拉取，只增不删——
   不会回退，但 step3.5 重算全部派生数据集的输入是已发布的 JSON；DB 里缺的 ~3,609 帖 / ~20,609 评
   永远进不了后续增量合并的唯一来源。
2. **回溯/重放不可能**：任何「从事实库重建发布集」的操作（ADR-002 口径变更、字段修复）都只能
   重建到 11,018，丢掉 6,451 帖。
3. **双写断层**：本地 `storage.upsert_*` 已双写 content_entity；部署版是否同步待测绘确认。

### 缺口二：personas/insights 冻结于 7 月

上游链 import-bundle → canonical → `vocs.jsonl` 在生产从未存在（ADR-002 已述），17,469 语料
从未参与画像/洞察。当前按 ADR-002 方案 A 暂缓（frozen_as_of 2026-07-23）。

---

## 2. 决策

### 决策一：content_entity 为唯一事实库（single source of truth）

**方向性决策**：统一事实库收口到 `content_entity`，legacy 表（`reddit_threads` /
`reddit_comments`）降级为**采集落地表**（ingress staging），逐步退役读路径。

**不变式**（进测试）：
1. `content_entity(post)` ⊇ `reddit_threads(post_id)`，`content_entity(comment)` ⊇
   `reddit_comments(comment_id)`（containment 不变式，违反即流水线拒绝发布）
2. 发布集 ⊆ content_entity（发布集可由事实库完整重建）
3. `is_backfilled` 首采集语义、state_hash 变更检测保持（ADR-002 已交付部分）

### 决策二：personas/insights 重建走「事实库投影」而非「历史离线链」

不在生产重建 import-bundle → canonical → vocs.jsonl 的历史链，而是：

1. **personas/insights builder 的输入源改为 content_entity**（本地构建、服务器发布）;
2. 沿用 7 月版算法与口径（ADR-002 口径冻结原则），只换语料与上游事实库;
3. **先内容后指针**原子发布，与 10-28 base 发布同一机制。

**理由**：历史链的中间产物（import-bundle、canonical manifest）携带 7 月运行时状态，
重建成本高且不可验证；content_entity 已含全部 38k+ 实体的 state_hash/first_seen/
is_backfilled，投影所需字段完备。

---

## 3. 里程碑与票据

### M-A 事实库收口（时间窗：今夜，07:05 流水线前完成）

| 票 | 内容 | 验收 |
|---|---|---|
| ECHO-A1 | 服务器 legacy→content_entity 差集导入脚本（幂等,首采集语义保留） | 差集=0, containment 断言通过 |
| ECHO-A2 | 部署版 storage.py 同步本地双写版（base64+SHA 校验上传） | sha256 一致, import 冒烟 OK |
| ECHO-A3 | 流水线发布守卫：发布前 containment 断言（继承 ADR-002 守卫机制） | 守卫注入 step3 前置, dry-run 通过 |
| ECHO-A4 | 浏览器验证 + 明早流水线观察 | 8 路由 0 错误; 07:05 后计数不回退 |

### M-B personas/insights 重建（时间窗：明日后）

| 票 | 内容 | 验收 |
|---|---|---|
| ECHO-B1 | personas builder 输入改 content_entity 投影（口径冻结） | 与 7 月版 schema 逐字段一致 |
| ECHO-B2 | insights builder 输入改 content_entity 投影 | quarter-insights 35 检查 0 违规 |
| ECHO-B3 | 本地全量构建 personas/insights（17,469 语料） | manifest SHA、守恒身份全过 |
| ECHO-B4 | 生产原子发布 + 浏览器验证 | 指针 7/7, 全路由 0 错误 |

---

## 4. 后果

- **正向**：事实库单调性恢复；回放/重放能力恢复；personas/insights 解冻。
- **风险与缓解**：今晚时间窗紧 → A1/A2 为最小关键路径，A3 守卫可明日补；双写改动
  → 先部署含守卫的脚本再导入；导入脚本幂等可重跑。

## 5. 执行状态

### 测绘结论（2026-10-29 01:30，5 个并行只读代理）

| 事实 | 数值 |
|---|---|
| 服务器 legacy 表 | 13,860 帖 / 37,687 评 |
| 服务器 content_entity（M-A 前） | 11,018 帖 / 27,123 评 |
| 发布数据集 | 17,469 帖 / 58,296 评 |
| DB ⊄ 发布集缺口 | 3,609 帖 / 20,609 评（仅存在于发布 JSON） |
| legacy ⊄ content_entity | 2,842 帖 / 10,564 评 |
| 部署版 storage.py 双写 | ❌ 无（SHA `f353afb…` ≠ 本地 `061cd8…`） |
| 部署版 content_entity.py | ❌ 不存在 |
| step3 评论去重 | ❌ 裸 ID 对 `t1_` 前缀集合，0/37,687 匹配 → 翻倍 95,983 |
| 模板标签渗漏 | 1xh7ks5 的 3 aspect/2 brand 标签渗入每个新帖 |
| lineage 目录属主 | root:root（ubuntu 流水线不可写 → 07:05 指针卡死） |

**发现时间线上的险情**：07:05 流水线会在 ADR 完成前触发评论翻倍——测绘代理在
ADR-004 起草过程中发现了它，M-A 立即转为事故修复。

### M-A 事实库收口 — ✅ 已完成（2026-10-29 02:10 北京，07:05 前完成）

| 票 | 结果 |
|---|---|
| ECHO-A1 | ✅ 服务器差集导入 2,842 帖 + 10,564 评；containment 断言 0 缺口；`is_backfilled=13,719` 首采集语义生效；DB 备份 `pre-echo-a1` |
| ECHO-A2 | ✅ storage.py（双写）+ content_entity.py + permalink.py 原子部署，SHA 校验，导入冒烟通过；root 拥有的陈旧 `__pycache__` 已 sudo 清除 |
| ECHO-A3 | ✅ release 守卫注入 step3（post/comment ID 唯一性，写 manifest 前 fail）；step3 去重修复 + normalize_all 标签渗漏修复；`tests/test_step3_merge_dedup.py` 5 测试钉住 |
| ECHO-A4 | ✅ 生产实跑 step3：0 追加 / 17,469 / 58,296 / SHA 绑定 MATCH / 4 文件 hash 全对；浏览器 9 路由 0 错误；lineage + pointer chown ubuntu |

**部署基础设施沉淀**：`scripts/deploy_file_to_server.sh`（base64 + 内嵌 SHA/长度
头、服务端写前校验、原子 mv）。**APFS 压缩克隆异常**：本仓多个经 Write→Edit 的
文件出现过 stat 与 read 不一致（差 4096 倍数，dd 读到 LZFSE 压缩垃圾头
`0x887d1c48`，即 10-28 scp「SHA 匹配却是二进制垃圾」的真正根因）——部署前一律
truncate-rewrite + stat==read + null 扫描三重校验。

### M-B personas/insights 重建 — ✅ 已完成（2026-10-29 04:45 北京）

测绘推翻了原「决策二」的部分前提，但 facts 代理用真实 builder+validator 端到端实证
了「发布基座 → canonical 形状投影 → 完整 7 月治理链」**可运行**。最终执行路线与
结果：

| 票 | 结果 |
|---|---|
| ECHO-B0 | ✅ `scripts/mb_project_base_to_canonical.py`：17,469/58,296 → canonical v2 bundle。关键规则：929 个前缀一致截断标题恢复为全文（含 1n2q1do 三条治理规则短语）；day-precision 记录省略 instant 时间戳；非 anchored 评论省略 permalink；父解析三态（34,226/18,523/5,547）；provenance 一行一实体（SHA 不带尾换行）。**真实 canonical validator passed** |
| ECHO-B1 | ✅ 真实 facts builder → 75,761 VOC（819 automation 排除、4 identity 冲突）→ **真实 facts validator passed**；真实 governed-signals builder → 416,803 fact 行（20,992 promoted）→ **真实 governed validator passed**（8 表，promotable） |
| ECHO-B2 | ✅ 真实 personas builder → 75,761 analysis-ready VOCs、33,752 cohort assignments（7 月的 3.4 倍）、82 atomic personas → **真实 personas validator passed，deterministic_full_byte_replay=true，全 checks true**。前端 82/8/14/9 契约零改动满足 |
| ECHO-B3 | ✅ `scripts/mb_build_attested_reports_insights.py`（honest_partial 的 attested 变体，直驱库函数）→ metrics（26 指标，deterministic replay=true）→ reports → insights。**comparison_contract_proven=true**（owner attestation 路径成立，无可见回退）。storyline 78/78；direction_supported 18（7 月 29；差异来自对比窗口需两期观测，属诚实降级而非合同降级） |
| ECHO-B4 | ✅ 数据集按内容寻址目录名上传（前端要求 `manifest_path == data/reddit-voc/{dataset_version}/public/manifest.json`，目录名必须等于 manifest 内部 dataset_version）；全部文件 SHA 服务端核验；指针原子翻转 + lineage 语义对齐（insights/reports=candidate manifest SHA，personas=self SHA）；前端 insightsV3 allowlist 加入新条目并重建部署。**浏览器 9 路由 0 错误；洞察页首次显示 17k 语料数据；报告页首现 attested 同环比** |

**发布产物 SHA**：personas manifest `9e3ff36b…`、insights public manifest
`e4f7d11a…`、reports public manifest `510d9437…`、owner attestation `046693af…`
（窗口 2013-04-28 至 2026-10-28，Asia/Shanghai 日期）。

**与测绘风险的差异**：
- 「前端常量需同 PR 更新」仅 insightsV3 allowlist 需要改（+1 条目）；82/8/14/9 与
  78 全部自然满足；
- 「attestation 无法伪造」成立，但 attestation 是 `data_owner_declaration` 声明性
  文件（2026-07 同 schema），按新窗口重出，`comparison_contract_proven=true` 保住；
- honest_partial coordinator 硬拒 attested 候选 → 新 driver 直驱库函数；
- manifest 内部 dataset_version 与目录名不一致会让前端 fail-closed → 数据集目录按
  内容寻址重命名解决。

**遗留标注**：lineage.py 的 personas receipt 仍写
`frozen_snapshot_upstream_engine_out_of_repo`——该 engine 现已在 repo（本次重建即证
明），标注文本待后续流水线迭代更新（不阻塞任何校验）。

### 实战检验：2026-10-29 07:05 流水线（M-A 上线后首跑）

| 环节 | 结果 |
|---|---|
| collect | ✅ 正常采集 |
| merge_snapshot | ✅ **+73 帖 / +291 评（0 翻倍——bare-id 去重生效）**；17,542/58,587；binding_updated=true；模板标签 0 渗漏 |
| recompute_derivatives | ❌→✅ 首跑失败：顶层 `data/reddit-voc/lineage/` 为 root:root（M-A chown 漏项）。**守卫按设计阻断指针**（partial_1_step_errors，坏数据没有出去）。人工 chown 后重跑 ok（aggregates `8fd11c78…`、quarter-insights `f75e12b7…`） |
| advance_pointer | ✅ 补跑成功，data_as_of → 2026-10-28T23:00Z（T-1 边界） |
| feishu_push | ✅ 已推送 |

**沉淀**：新增强制 preflight（`_preflight_writability`）——运行前枚举全部写目标
（store/output/pointer/lineage/各数据集 manifest 目录）做 W_OK 检查，不可写即在
collect 之前 fail-loud。已部署并验证。全树 root 属主清查仅剩 3 个 nginx 只读静态
文件（favicon/icons/robots，安全）。

**终态守恒链**（2026-10-29 11:00 北京核验）：
- 指针 7/7 绑定 SHA MATCH
- 双写生效：当日 run 触发 content_entity 461 行写入
- quarter-insights 自动引用新 personas manifest（`9e3ff36b…`）
