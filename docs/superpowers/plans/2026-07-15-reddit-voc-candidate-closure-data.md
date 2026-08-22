---
title: Reddit VOC Plan A - 全候选闭环、融合与经营重算
doc_type: implementation_plan
status: completed_local_candidate
created: 2026-07-15
updated: 2026-07-15
owner: codex
depends_on: 2026-07-15-reddit-voc-candidate-closure-ui-governance-design.md
evidence_grade: L3_readonly_then_L2_local_candidate
production_boundary: production_unchanged
provider_call: false
database_write: false
remote_write: false
deploy: false
collector_change: false
schedule_change: false
---

# Plan A：全候选闭环、融合与经营重算

完成证据：final candidate input `70a917e5...4ac1e`，manifest
`c18d313a...1cdfb7`，reconciliation `347fc37a...f957b7`，independent receipt
`e2958d7d...bc9f80`；证据等级 `L2_local_independent_validation`，
`production unchanged`。1,179 open coverage items 与18条 pending lineage 仍显式保留。

## 1. 目标与退出条件

Plan A 把最新冻结输入转换为一份可审计的数据候选。它先从当前生产 `current`
动态取得 `P0/L0/Q0/C0`，再把腾讯云生产报告、isolated staging、
`ai_nlp_voc` 归档、历史 canonical、V2 报告和本地标签/产品配置纳入同一 cutoff。

Plan A 完成必须同时满足：

- 四本明细账和一本 reconciliation ledger 均生成且由外层 manifest 记录 SHA；
- occurrence、post、comment、coverage 四类 `unaccounted` 均为 0；
- `P0 ⊆ P1`、`C0 ⊆ C1`、`L1 ∩ Q1 = ∅`，所有 linked comment 的父帖子存在；
- `release_net_new_posts/comments` 可由集合差独立复算；
- 存量正文/评论补齐、quarantine relink 和 coverage closure 不计入净新增；
- 生成新的 Base → Insights → Reports → Personas → public 本地候选；
- Momcozy 品牌主干、品类、product family、exact-SPU、竞品同样本、画像、
  日报/周报/月报、同比/环比/趋势均绑定本次上游 manifest；
- 18 个历史 lineage gap 和 freeze 后出现的每个新身份都有唯一结果及 reason code；
- 未闭合覆盖债务以 `open_carried` 等状态保留，绝不删除或冒充完成；
- 结束状态仍为 `production unchanged`。

## 2. 数据合同与文件范围

优先复用：

- `scripts/capture_reddit_production_snapshot.py`
- `scripts/capture_reddit_remote_snapshot.py`
- `scripts/build_reddit_site_insights.py`
- `scripts/build_reddit_v2_identity_freeze.py`
- `scripts/build_reddit_v2_raw_snapshot.py`
- `scripts/freeze_reddit_incremental_inputs.py`
- `scripts/build_reddit_site_snapshot.py`
- `scripts/build_reddit_insights_snapshot.py`
- `scripts/build_reddit_reports_snapshot.py`
- `scripts/build_reddit_personas_snapshot.py`
- `scripts/build_reddit_current_release.py`
- `src/reddit_voc/risk_report_contracts.py`
- 现有 `validate_reddit_*` validators 与对应 tests

预期新增的最小实现：

- `scripts/capture_reddit_candidate_sources.py`
- `scripts/build_reddit_candidate_ledgers.py`
- `scripts/validate_reddit_candidate_ledgers.py`
- `tests/test_reddit_candidate_ledgers.py`
- `tests/test_reddit_candidate_data_closure.py`

生成物只进入新的私有根 `tmp/reddit-voc-candidate-closure/`。子目录名为
candidate-input canonical SHA-256：对 source freeze SHA、production baseline SHA、
config SHA 和 `data_build_code_freeze` SHA 的有序 canonical payload 再做 SHA-256；
不使用时间戳作为内容身份，目录名必须匹配 `^[0-9a-f]{64}$`。候选根及子目录
mode 0700，私有文件 mode 0600。manifest 必须记录四个组成 SHA。至少包括：

```text
source-freeze-manifest.json
source-occurrence-ledger.jsonl
post-identity-delta-ledger.jsonl
comment-identity-delta-ledger.jsonl
coverage-work-ledger.jsonl
candidate-data-reconciliation-ledger.jsonl
candidate-data-manifest.json
candidate-data-validation-receipt.json
```

所有 JSON/JSONL 使用稳定排序、UTC 时间、UTF-8、LF 和 canonical serialization。
candidate data reconciliation ledger 不记录自身 SHA；它的 SHA 仅记录在
`candidate-data-manifest.json` 和 validation receipt 中。

## 3. Batch A1：生产 L3 只读静稳与重新冻结

### A1.1 预检工作区与工具

- 重新读取总规格、本计划、`.codex/context-pack.md` 与最新 acceptance receipt。
- 检查根仓库和嵌套 UI 仓库状态；不覆盖用户已有修改，不 commit、不 stage。
- 完整审阅 capture/freeze 脚本后才执行；不得读取或输出 `DDDD.pem` 内容。
- 记录生产 URL、current pointer、release SHA、Base/Insights/Reports/Personas 版本。

### A1.2 只读静稳门禁

在 `ubuntu@101.34.52.232` 上进行两次间隔至少 10 秒的只读观测。两次必须保存
相同成员集、bytes、mtime_ns、SHA、container ID/health/restart 和任务状态，至少校验：

- `reddit_voc_site_app-run-*` one-shot 容器不存在；
- collector、LibreTranslate 和洞察站 container ID、health、restart count 稳定；
- 数据库 stat、报告 current、候选报告 allowlist 的 bytes/mtime 稳定；
- 没有未结束的 task state、report lock 或临时采集网络；
- shared Nginx 与 cron SHA 只记录不修改；
- SQLite 只通过 `mode=ro`、`PRAGMA query_only=ON` 或 immutable copy 读取。

任一条件不满足即生成 `no_candidate_collection_not_quiescent` receipt 并停止，
不得暂停、重启或修改采集器来制造静稳。

### A1.3 动态基线与输入 allowlist

- 从当前生产 Base 独立导出 `P0/L0/Q0/C0` LF identity lists 和 SHA。
- 以服务器当前稳定报告为事实源生成 allowlist；排除 plan-only、临时、symlink、
  special file、越界路径和 cutoff 后漂移文件。
- 新增 `capture_reddit_candidate_sources.py`，通过固定 known-host、
  `StrictHostKeyChecking=yes` 和 stdout-only read-only SSH 导出 allowlist 内服务器报告；
  传输前后复核 member/stat/hash，拒绝 symlink、special file 和路径越界。
- 将 `/Users/pray/project/ai_nlp_voc/system_data/voc_data/reddit/` 作为本地归档来源，
  只复制 allowlist 命中的数据到当前候选私有输入目录；保留 source namespace、
  相对路径、bytes、SHA、mtime_ns，测试外部 root allowlist 和不可变碰撞。
- 此阶段只冻结外部数据、当前生产 baseline、`dim_tag_v6.3_final.csv`、产品 ledger 和
  构建配置。`source_cutoff_utc` 表示采集观察截止时间；Reddit event window 是独立合同。
- ledger/data 实现稳定后、正式候选构建前另建 `data_build_code_freeze` 和
  `code_cutoff_utc`。完整 React source tree 与 package lock 在 Plan B 完成后由 Plan C 冻结，
  不能与 source cutoff 混为同一时间点。
- 同一输入重复冻结必须返回同一 SHA 或 `no_change`；不同内容不得覆盖同名目录。

### A1.4 A1 验收

- 产出 L3 只读 snapshot receipt、quiescence receipt、allowlist 和 source freeze manifest；
- 基线集合数量和 SHA 与当前生产 manifest 互证；
- 远端传输仅为读取到本地候选目录，不存在 persistent remote write；
- `provider_call=false`、`database_write=false`、`production unchanged`。

## 4. Batch A2：确定性 Base、四本明细账与身份闭环

### A2.1 先写失败测试

在 `tests/test_reddit_candidate_ledgers.py` 覆盖：

- occurrence stable key、重复 occurrence 与 precedence；
- post/comment 各状态互斥且每个 identity 仅一行；
- canonical managed-field SHA 对字段顺序和无意义空白稳定，对受管内容变化敏感；
- 既有生产 identity 的无效更新不能从 `P1/C1` 删除；
- quarantine relink 不是净新增；
- coverage key 按 lineage/cursor/comment_page/search_lane 隔离；
- child cursor 只作为新 work item，不反向改写已冻结计数；
- reconciliation 不自哈希；外层 manifest 正确绑定五本账；
- tamper、missing file、duplicate status、path traversal、symlink、hash collision fail closed。

同时为 `capture_reddit_candidate_sources.py` 补外部 root allowlist、相对路径、
symlink/special file/path traversal、传输前后漂移、不可变碰撞和 0700/0600 权限测试。

### A2.2 先构建确定性 canonical Base

实际运行顺序固定为：

```text
source freeze + P0/L0/Q0/C0
→ deterministic fusion
→ provisional Base P1/L1/Q1/C1
→ occurrence/post/comment/coverage ledgers
```

Base 使用冻结输入、既有 precedence、生产 baseline append-only 合同和配置确定性生成，
不得读取尚未生成的 ledger summary 来决定准入。Base manifest 只绑定 source freeze、
生产 baseline、构建配置和 `data_build_code_freeze`，不绑定 reconciliation 或外层 manifest。

### A2.3 实现确定性账本生成器

`build_reddit_candidate_ledgers.py` 消费本次 source freeze、当前生产 baseline 和已生成的
`P1/L1/Q1/C1`，通过集合差与受管内容 SHA 描述融合结果，不反向控制 Base：

- occurrence ledger 对每个冻结 source occurrence 唯一归类；
- post ledger 动态计算 `newly_admitted/existing_upgraded/existing_unchanged/
  pending_lineage/rejected`；
- comment ledger 动态计算 new、upgrade、relink、retained、rejected；
- coverage ledger 汇总当前已冻结的 lineage、cursor、page 和 search lane 工单；
- 此阶段只生成前四本明细账；reconciliation 等全部下游 outputs 完成后生成。

所有数量必须从 ledger 行复算，禁止从手写 summary 或 UI 数字反向填充。

### A2.4 独立 validator

`validate_reddit_candidate_ledgers.py` 不导入 builder 内部聚合结果，独立读取 Base、账本并重算：

- 四类 accounting rate 与 `unaccounted_total`；
- `P0/P1`、`L0/L1`、`Q0/Q1` 集合关系；
- net-new、upgrade、relink、quarantine transition；
- coverage before/after 和 reason-code 完整性；
- source freeze、baseline、Base 与前四账的 SHA 绑定。

### A2.5 A2 验收

- focused tests RED → GREEN；
- 同一 freeze 重跑账本 bytes/SHA 完全一致；
- 所有旧 18 lineage gaps 与新发现身份均有唯一结果；
- `unaccounted_total=0`，但允许 `open_carried > 0`；
- validator 返回 A2 identity/ledger receipt；最终 `candidate-data-validation-receipt.json`
  在 A3 reconciliation 后生成。

## 5. Batch A3：融合与经营重算

### A3.1 完成 Base 后的业务派生

- A2 Base 已按现有 precedence 完成去重、正文升级、父子关联、quarantine、PII 和
  bot/deleted filtering；A3 不再用 ledger 反向重建 Base。
- 发布净新增指标只读取已独立验证的 post/comment ledger；existing upgrade/relink
  只进入质量与覆盖指标。
- 先执行 legacy semantic overlay，再由当前 v2
  `build_reddit_site_insights.py` / `risk_report_contracts` 构建 Momcozy 风险主线与
  日周月双层合同；不得用旧 snapshot builder 覆盖 v2 结果。

### A3.2 品牌、品类和产品三层

- 以 Momcozy 为分析主干，其他品牌只作为同检索策略、同 event window 的对比方。
- 从 `dim_tag_v6.3_final.csv` 重跑正文与评论标签，并使用字典中的画像对应关系作为
  evidence cohort 的一个维度，不把它解释为真实用户身份。
- 重算 category → product family → exact-SPU；无法精确绑定时保留更高层级或
  `unbound` reason，不做猜测性 SPU 分配。
- 每个聚合绑定上游 identity/freeze/tag/product manifest SHA。

### A3.3 Insights 与报告故事线

- 洞察页 A 主线：Momcozy 经营问题 → 品类/SPU 驱动 → 用户证据 → 竞品同样本 → 行动优先级。
- 报告页 B 分册：日报、周报、月报 current/archive，均按 Reddit
  `event_created_at_utc` 重算，晚到数据回写历史窗口。
- 同比、环比和趋势分别记录比较窗口、样本量、coverage 可比性和 reason code；
  不可比时数值可展示但方向为 `provisional/unavailable`。
- C 受控模块只消费 artifact/deployment 双状态合同，不从旧 build flags 推断生产状态。

### A3.4 Personas、案例和公开投影

- 重算 evidence personas 与合成头像绑定；头像必须继续标注 synthetic。
- 案例广场保持 `38 精选 + 12 待核验 + approved delta`，仅合并明确批准的增量。
- public projection 使用 allowlist，移除私有路径、内部 source text 和不需要的用户标识。
- 运行 Base/Insights/Reports/Personas/public 的独立 validators。

### A3.5 Final reconciliation、验收与移交 Plan B/C

- Base/Insights/Reports/Personas/public 全部完成后才生成 candidate data reconciliation ledger；
- reconciliation 绑定前四账和全部下游 output manifests，但任何内层 manifest 不得
  反向绑定 reconciliation；
- 最外层 `candidate-data-manifest.json` 绑定 reconciliation SHA；
- 独立 validator 最后重算四类 accounting、集合守恒和全部 SHA 依赖图。

- 业务 delta 可从新旧 manifests 和 ledger 集合差复算；
- 报告六态、产品三层、竞品同样本和 persona contracts 完整；
- 生成 Plan B 可直接消费的治理状态字段和 Plan C 可绑定的 data receipt；
- 本批不 build/部署生产，不发 Provider，不写生产 DB。

## 6. 验证命令（实施时以项目实际 CLI 为准）

```bash
PYTHONPATH=src python3 -m unittest tests.test_reddit_candidate_ledgers -v
PYTHONPATH=src python3 -m unittest tests.test_reddit_candidate_data_closure -v
PYTHONPATH=src python3 scripts/validate_reddit_candidate_ledgers.py --candidate-root "$CANDIDATE_ROOT"
PYTHONPATH=src python3 -m unittest \
  tests.test_reddit_site_v2_fusion \
  tests.test_reddit_site_product_enrichment \
  tests.test_validate_reddit_site_snapshot -v
PYTHONPATH=src pytest -q \
  tests/test_reddit_insights_snapshot.py \
  tests/test_reddit_reports_snapshot.py \
  tests/test_reddit_personas_snapshot.py \
  tests/test_validate_reddit_site_analytics.py \
  tests/test_reddit_risk_report_contracts.py
```

不得为了通过本计划而修改、跳过或删除既有失败测试。完整命令参数在阅读现有 CLI 后固定，
不能凭本计划文本臆造执行结果。

## 7. 停止门

以下任一情况立即停止并保留精确 receipt：采集不静稳、baseline/current 漂移、allowlist
漂移、生产身份丢失、unaccounted 非零、父帖子缺失、账本自相矛盾、上游 SHA 不匹配、
标签/产品 manifest 不可验证或测试三次仍无法收敛。

Plan A 不授权 Reddit/TikHub/DeepSeek 请求、采集续跑、远端数据库写入、cron/systemd、
Docker/Nginx/TLS/DNS 修改、生产 current 切换或 live send。
