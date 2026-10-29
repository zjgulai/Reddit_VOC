# V2.0 票据台账

- 总票据：**105** 张｜P0=16 P1=67 P2=13 P3=9
- 依赖图：**无循环**，拓扑层深 7 层（层 0 = 无前置，可立即开工）
- 每张票据均含可执行测试名（无测试的票据 = 0 张）

## 一、按波次与严重度

| 波次 | 主题 | 车道 | 票据数 | P0 | P1 | P2 | P3 |
|---|---|---|---|---|---|---|---|
| Wave 1 | 止血：可信发布、失败可见、缓存收敛 | L6, L5, L4, L1 | 72 | 13 | 44 | 10 | 5 |
| Wave 2 | 数字口径：每个数字要么按定义计算，要么显式不可用 | L2, L1, L4 | 20 | 3 | 12 | 2 | 3 |
| Wave 3 | 溯源与监控：工件自证、血缘可解引用、缺失可告警 | L5, L1, L6, L4 | 72 | 13 | 44 | 10 | 5 |
| Wave 4 | 结论与画像：判断句数据化，画像回到当前语料 | L3, L1, L4 | 13 | 0 | 11 | 1 | 1 |
| Wave 5 | 覆盖与规模化：评论按需、历史回填、遗留清理 | L1, L4, L2, L5, L6 | 92 | 16 | 56 | 12 | 8 |

> 波次按**车道首现**归属；实际施工顺序以依赖图拓扑序为准（见第三节）。

## 二、P0 票据（必须在 Wave 1 关闭）

| ID | 车道 | 类型 | 工作量 | 标题 |
|---|---|---|---|---|
| `L1-T01` | L1 | fix | M | quarter-insights v2：画像 VOC id 桥、血缘键改名、回执状态与 conclusions 槽位（一次 schema bum |
| `L2-T01` | L2 | fix | S | 修正月报环比基线与六期链，并给环比加低样本门禁 |
| `L2-T02` | L2 | fix | S | 撤回 RV-BR-05/04 同名改义，恢复注册表身份并标 unavailable |
| `L4-T01` | L4 | feature | M | release.ts：指针 5 分钟 TTL 重验证、并发合并、拒绝不缓存、refreshCurrentRelease |
| `L4-T06` | L4 | fix | M | 画像分布改用季度 cohort 计数，合计只在分母自证时显示 100.00% |
| `L5-T01` | L5 | fix | S | 早报卡片任何非 success 一律未验证并红标；回执优先取内存 |
| `L6-T01` | L6 | fix | S | 文件级写前检查：可写位 + 可读性 + 完整目标清单 |
| `L2-T03` | L2 | fix | M | 产品家族/品类/精确 SPU 只用 product_bindings 聚合，无绑定即 unavailable |
| `L4-T02` | L4 | feature | M | releaseKeyedCache 模块 + service.ts 四个缓存改为发布键（含 summary 漏 reset 修复） |
| `L4-T03` | L4 | feature | M | brandHealth / quarterInsights / casebook 值缓存改为发布键缓存 |
| `L4-T04` | L4 | feature | M | personas / reports / insights 缓存改为发布键；报表与洞察刷新按钮先刷新指针 |
| `L4-T05` | L4 | feature | M | useReleaseAwareData：挂载/可见/10 分钟轮询/失败重试，并接入七个 useReddit* hook |
| `L5-T05` | L5 | feature | M | 定时新鲜度监控 check_site_freshness.py：状态机 + 逐数据集自证 + 红卡/心跳/去重 |
| `L5-T06` | L5 | ops | S | 新鲜度告警单元入库并在服务器装起来 |
| `L6-T07` | L6 | feature | L | 代际事务模块：复制种子、原子 symlink 切换、回滚与 gc |
| `L6-T08` | L6 | feature | L | 事务接入流水线：step2/3/3.5/4 只写代目录，指针只替换一次 |

> **热修提示**：`L6-T01`（分支锁）与 `L6-T02`（文件级 preflight）可在今晚 07:05 运行**之前**单独上线，不需要等整波，直接消除今天的失败模式。

## 三、拓扑施工序（层 0 可并行开工）

### 层 0（46 张）
`L1-T01`, `L1-T05`, `L1-T08`, `L1-T09`, `L1-T12`, `L2-T01`, `L2-T02`, `L2-T04`, `L2-T07`, `L2-T10`, `L2-T11`, `L2-T13`, `L2-T14`, `L2-T18`, `L2-T19`, `L2-T20`, `L3-T01`, `L3-T02`, `L3-T09`, `L4-T01`, `L4-T06`, `L4-T07`, `L4-T09`, `L4-T10`, `L4-T11`, `L4-T12`, `L4-T13`, `L4-T14`, `L4-T15`, `L4-T16`, `L4-T17`, `L4-T18`, `L4-T20`, `L4-T23`, `L4-T24`, `L5-T01`, `L5-T02`, `L5-T03`, `L5-T08`, `L5-T10`, `L5-T11`, `L5-T12`, `L5-T13`, `L5-T14`, `L6-T01`, `L6-T05`

### 层 1（23 张）
`L1-T02`, `L1-T06`, `L2-T03`, `L2-T05`, `L2-T06`, `L2-T09`, `L2-T16`, `L2-T17`, `L3-T03`, `L3-T04`, `L3-T05`, `L4-T02`, `L4-T08`, `L4-T21`, `L4-T22`, `L4-T25`, `L4-T26`, `L5-T04`, `L5-T09`, `L5-T15`, `L5-T16`, `L6-T02`, `L6-T15`

### 层 2（15 张）
`L1-T03`, `L1-T11`, `L1-T13`, `L1-T14`, `L2-T12`, `L3-T06`, `L3-T07`, `L3-T08`, `L3-T10`, `L4-T03`, `L4-T04`, `L4-T05`, `L5-T05`, `L5-T07`, `L6-T03`

### 层 3（13 张）
`L1-T04`, `L1-T10`, `L2-T08`, `L2-T15`, `L3-T11`, `L3-T12`, `L3-T13`, `L4-T19`, `L5-T06`, `L6-T04`, `L6-T06`, `L6-T07`, `L6-T14`

### 层 4（2 张）
`L1-T07`, `L6-T08`

### 层 5（2 张）
`L6-T09`, `L6-T10`

### 层 6（4 张）
`L6-T11`, `L6-T12`, `L6-T13`, `L6-T16`

---

## 四、票据详情

### L1 — L1 — 数据生产层 (Data Production)

#### `L1-T01` quarter-insights v2：画像 VOC id 桥、血缘键改名、回执状态与 conclusions 槽位（一次 schema bump）

- **严重度**：P0｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：修复 P0-2 的生产者半边与 P3 血缘名称碰撞。新增 src/reddit_voc/voc_identity.py（bare_comment_id/voc_id，恰好剥一个 t1_/t3_，双前缀 ValueError）。recompute_derivatives.recompute_quarter_insights 的 576-597 段改为生成 main_voc_ids=sorted({voc_id(kind,post_id,comment_id)})，main_assignment_count=len(main_voc_ids)，删除 main_assignment_ids（585/604）。QUARTER_INSIGHTS_SCHEMA(287) 与 qi_manifest 的 schema(约 1078) 同时 bump 到 _v2。qi_source(1014-1033) 三个 governed_signal_* 改名 governed_binding_projection_*（值不变），新增 persona_validation_status（恒 'not_validated_frozen_snapshot'，T04 后按回执判定），payload 顶层新增 conclusions:[]。persona 三键与 COHORT_ORDER/cohort_of_topic 不动（L2-P16 拥有）。已实测：季度 evidence 中至少 6 个 post:<id> 已存在于线上 persona-tags 的 voc_id 值域，桥非空。消费者：L4 的 quarterInsights.ts 必须同发布接受 v2（见 contracts 第 1 条）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/src/reddit_voc/voc_identity.py`
  - `/Users/lute/Project/Echo-Agent/scripts/recompute_derivatives.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_quarter_persona_scope.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_recompute_parity.py`
- **验收**：
  - quarter-insights.json 的 schema_version == 'reddit_voc_quarter_insights_public_v2'，其 manifest 的 schema_version == 'reddit_voc_quarter_insights_public_manifest_v2'。
  - personas.main_voc_ids 为去重升序数组，元素形如 'post:<id>' 或 'comment:<bare id>'；main_assignment_count == len(main_voc_ids)；payload 与 manifest 中不再出现 main_assignment_ids。
  - source 同时包含 governed_binding_projection_manifest_sha256 / governed_binding_projection_snapshot_id / governed_binding_projection_validation_receipt_sha256，且不含任何 governed_signal_* 键；personas V3 manifest 仍保留四个 governed_signal_* 键。
  - source.persona_validation_status ∈ {'validated','not_validated_frozen_snapshot'} 且 persona_validation_receipt_sha256 仍是 64 位 hex。
  - payload 含顶层 conclusions: []（数组），manifest 键集不变。
  - 在 2 帖 2 评且至少 1 帖 1 评属 Momcozy 的 fixture 上，set(main_voc_ids) ∩ {a.voc_id for a in persona assignments} 非空。
- **测试**：
  - `tests/test_quarter_persona_scope.py::test_main_voc_ids_use_persona_namespace`
  - `tests/test_quarter_persona_scope.py::test_assignment_ids_are_gone_from_personas_block`
  - `tests/test_quarter_persona_scope.py::test_double_prefixed_comment_id_is_rejected`
  - `tests/test_recompute_parity.py::test_quarter_insights_matches_frozen_schema`
  - `ref/UI/momcozy-reddit-workbench/src/components/personas/__tests__/AggregatePersonaPanel.test.tsx (L4 同发布)`
- **完成定义**：pytest tests/test_quarter_persona_scope.py tests/test_recompute_parity.py 全绿；`python3 -c` 复算 fixture 的 main_voc_ids 交集为 {'post:<p1>','comment:<c1>'}；仓库中除本次 v2 外无其它 quarter schema 字符串残留；与 L4 quarter v2 同发布单元。

#### `L1-T02` canonical 投影切到 v1，并把被服务 base manifest 绑进 inputs

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：1
- **依赖**：`L1-T01`
- **描述**：修复 L1-P10。实测确认 v1 可用：comments-public.json 只含已关联评论（仓库副本 20,609 行、0 行父帖缺失；6,953 条 unresolved 只在 canonical_counts 计数），v1 校验器禁止 governed unresolved（scripts/validate_reddit_v3_canonical_snapshot.py:529、:1333）不会触发。改动：新增必填 --base-public-manifest-sha256 与可选 --base-lineage-manifest-sha256；main() 拆成 project_base(...) 返回摘要供驱动进程内调用；schema v2->v1、dataset_id 后缀 _canonical_v1、inputs 由 :281-288 的六个全零改为 v1 五键（base 两键真实，另三键 0*64）；删除 :322-341 手写 status='passed' 回执（如需保留改名 canonical-candidate-receipt.json + status='not_validated'，下游不得引用）；写盘前 preflight：任一评论 post_id 不在 posts 集合 -> projection_comment_parent_missing，不写任何文件。validator 已有 --base-public-manifest-sha256/--base-lineage-manifest-sha256（:1418-1419）与 INPUT_KEYS_V1（:38-45）；facts builder 接受 v1（build_reddit_v3_voc_facts.py:402-404），并要求 receipt.inputs == manifest.inputs（validate_reddit_v3_voc_facts.py:2183），真实 validator 天然满足。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/mb_project_base_to_canonical.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_mb_chain_driver.py`
  - `/Users/lute/Project/Echo-Agent/tests/fixtures/mb_chain/`
- **验收**：
  - project_base 产出的 manifest schema_version == 'reddit_voc_canonical_snapshot_manifest_v1'，dataset_id 以 _canonical_v1 结尾，inputs 恰为 5 个键且 base_public_manifest_sha256 == sha256(被服务 manifest-public.json)。
  - 运行 scripts/validate_reddit_v3_canonical_snapshot.py（带 --base-public-manifest-sha256 与三个 0*64 旗标）在 fixture 上退出 0，回执 schema 为 reddit_voc_canonical_snapshot_validation_receipt_v1 且 inputs 回显 5 键。
  - 投影过程不再写出任何 status='passed' 的回执；若存在候选回执，其 status=='not_validated' 且无下游引用。
  - 评论父帖缺失的 fixture 在写任何文件前以 projection_comment_parent_missing 失败。
  - canonical_counts.posts/comments 分别等于 base posts 与 comments-public.json 行数。
- **测试**：
  - `tests/test_mb_chain_driver.py::test_canonical_v1_binds_served_base_manifest`
  - `tests/test_mb_chain_driver.py::test_canonical_v1_passes_real_validator_on_fixture`
  - `tests/test_mb_chain_driver.py::test_projection_fails_closed_on_missing_parent_post`
  - `tests/test_mb_chain_driver.py::test_projection_never_claims_passed_receipt`
- **完成定义**：4 个新 pytest 全绿；fixture 语料 2 帖 2 评；golden canonical manifest 存 tests/fixtures/mb_chain/expected-canonical-manifest.json；validator 误传 base sha 时以 'canonical manifest input SHA bindings mismatch' 失败。

#### `L1-T03` 每周 personas 整链驱动：base 绑定、链回执、部署清单与 systemd timer

- **严重度**：P1｜**类型**：feature｜**工作量**：L｜**拓扑层**：2
- **依赖**：`L1-T02`
- **描述**：修复 L1-P2。新增驱动按规格第 3 节实现：从指针解析 base 并断言 sha；fresh run root（outputs/mb-chain/<data_as_of>-<base_sha[:12]>，已存在则退出 3）；singleton flock 与 8 GiB 预检；逐段 subprocess 跑 canonical->validate->facts->validate->governed->validate->personas->validate，所有 SHA 从产物字节计算；断言 canonical_inputs_base_public_manifest_sha256 == base_sha 且 base posts+linked_comments-identity_conflicts == personas analysis_ready_vocs；结束前重算 base manifest sha，变化 -> chain_base_drift；发布 personas 目录（0600/0700）并只改指针 datasets.personas；写 chain-receipt.json（echo_agent_mb_chain_receipt_v1）到 run root 与 data/reddit-voc/lineage/；保留最近 3 个 root。新增 build_mb_chain_deploy_manifest.py 遍历 sys.modules 生成 local->remote 清单（含 dim_tag_v6.3_final.csv、config/personas、config/analytics 三份策略、data/reference/reddit-voc-v3/*、全部链脚本与 src 模块）。新增 systemd service/timer（Sun 09:30 Asia/Shanghai，Persistent=true，TimeoutStartSec=6h，User=ubuntu，UMask=0077）。预算 4-6h/GB 级（ADR-004 M-B 2h35m @17k/58k）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_weekly_personas_chain.py`
  - `/Users/lute/Project/Echo-Agent/scripts/build_mb_chain_deploy_manifest.py`
  - `/Users/lute/Project/Echo-Agent/config/systemd/echo-agent-weekly-personas.service`
  - `/Users/lute/Project/Echo-Agent/config/systemd/echo-agent-weekly-personas.timer`
  - `/Users/lute/Project/Echo-Agent/tests/test_weekly_personas_chain.py`
- **验收**：
  - 指针 base sha 与 manifest-public.json 不一致时退出 2 chain_base_binding_mismatch，且不创建 run root。
  - chain receipt 含 base_manifest_sha256、canonical_inputs_base_public_manifest_sha256、8 段 manifest/receipt sha 与 counts；三者满足 base_manifest_sha256 == canonical_inputs_base_public_manifest_sha256 == sha256(served manifest)，且 base_counts.posts + linked_comments - identity_conflicts == personas_analysis_ready_vocs。
  - 两次 --dry-run --no-publish 于同一 fixture 产出逐字节一致的 14 个 personas 文件。
  - 运行中向 base 追加 1 帖 -> 以 chain_base_drift 失败，不发布。
  - 发布只改变 current-release.json 的 datasets.personas 值；其余 6 个 binding 在发布前后字节相同。
  - build_mb_chain_deploy_manifest.py 的输出与 golden 清单一致，覆盖全部导入模块与数据文件。
- **测试**：
  - `tests/test_weekly_personas_chain.py::test_chain_receipt_binds_base_manifest`
  - `tests/test_weekly_personas_chain.py::test_chain_is_byte_deterministic`
  - `tests/test_weekly_personas_chain.py::test_chain_detects_base_drift`
  - `tests/test_weekly_personas_chain.py::test_publish_updates_only_personas_binding`
  - `tests/test_weekly_personas_chain.py::test_deploy_manifest_covers_all_imports`
- **完成定义**：5 个 pytest 离线全绿（fixture 2 帖 2 评，--dry-run --no-publish）；人工在服务器手动跑一次产出 status=ok 的 chain receipt；timer enable 后下一次触发产生新 personas 目录且 validator 退出 0。

#### `L1-T04` 删除伪造 personas 回执，改为引用真实 reddit_voc_personas_validation_v3

- **严重度**：P2｜**类型**：fix｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L1-T03`
- **描述**：修复 L1-P3。lineage.py 的 personas_receipt(176-198) 换成 personas_validation(public_root, manifest_path) -> PersonaValidation{manifest_sha256, receipt_sha256, status}。真回执路径 data/reddit-voc/lineage/personas-<snapshot_id>-validation.json，必须 schema=reddit_voc_personas_validation_v3、status=passed、snapshot_id 与 manifest 一致 -> status='validated'。无真回执但数据集内仍有历史 echo_agent_personas_receipt_v1 -> status='not_validated_frozen_snapshot' 且 receipt_sha256 指向该文件（保证 source 槽位非空）。两者皆无 -> RuntimeError persona_validation_receipt_missing。删除 _write(manifest_abs.parent, 'lineage-personas-receipt.json', ...)，daily recompute 永不在 personas 目录内写文件。recompute_derivatives.py:1008 改用 dataclass，qi_source.persona_validation_status 取其 status。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/lineage.py`
  - `/Users/lute/Project/Echo-Agent/scripts/recompute_derivatives.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_lineage_personas_receipt.py`
- **验收**：
  - daily recompute 在 personas 目录内零写入；目录文件集合恰为 manifest.files + manifest.json（find 校验）。
  - 真回执存在时 quarter source.persona_validation_status=='validated' 且 persona_validation_receipt_sha256 == sha256(真实回执文件)。
  - 只有历史伪造回执时 status=='not_validated_frozen_snapshot' 且 sha 仍为 64 hex，dataset 仍可构建。
  - schema 错误、status 非 passed、snapshot_id 不匹配的回执一律被拒绝（RuntimeError），不得被引用。
  - T03 的周链发布后，线上 personas 目录通过 validate_reddit_v3_personas_snapshot.py（退出 0），quarter 引用真实回执。
- **测试**：
  - `tests/test_lineage_personas_receipt.py::test_receipt_is_written_outside_dataset_tree`
  - `tests/test_lineage_personas_receipt.py::test_fake_receipt_is_rejected`
  - `tests/test_lineage_personas_receipt.py::test_frozen_snapshot_reports_not_validated`
  - `tests/test_lineage_personas_receipt.py::test_validated_receipt_is_cited`
- **完成定义**：4 个 pytest 全绿；lineage.py 中不再存在 rebuild_status/frozen_snapshot_upstream_engine_out_of_repo 字符串；T03 的链回执中 personas_validation_receipt_sha256 非空且能解析到文件。

#### `L1-T05` 日更为新行解析并写入 product_bindings（含 S9 Pro 家族）

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：0
- **描述**：修复 L1-P5。step3 在 append 前加载一次 ProductEntityResolver.from_ledger(config/product_entities/momcozy-product-entity-ledger-v1.json)；帖解析 f'{title} {content}'、评论解析 body，把 [b.to_record() for b in result.product_bindings] 写入原始 record 的 product_bindings。merge_normalize 四条硬编码 product_bindings: []（128/190/258/363）改为只从 record 取（list 则保留，否则 []），绝不从 template 继承（与 tag 渗漏同类问题）。元素保持既有 9 字段形状（src/reddit_voc/v3_base_public.py:87-100）。不动无 run_id 的 July 行。已实测 resolve('Momcozy S9 Pro') -> binding_level='product_family', product_family.id='s9-pro', governance_status='family_only'；'S9 Pro'/'V2' 裸文本不绑定。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/scripts/merge_normalize.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_merge_product_bindings.py`
  - `/Users/lute/Project/Echo-Agent/tests/fixtures/product_bindings/`
- **验收**：
  - 种子帖文本 'Momcozy S9 Pro' 经 step3+normalize 后 product_bindings 含 binding_level=='product_family' 且 product_family.id=='s9-pro'。
  - 无品牌文本 product_bindings==[]；裸 'S9 Pro' 与 'V2' 不产生 spu_exact 绑定。
  - normalize_all 不覆盖已有非空 product_bindings，且无 run_id 的 July 行字节不变。
  - step3 回执 product_bound_posts/product_bound_comments > 0（种子运行）。
- **测试**：
  - `tests/test_merge_product_bindings.py::test_momcozy_s9_pro_binds_product_family`
  - `tests/test_merge_product_bindings.py::test_unbound_text_stays_empty`
  - `tests/test_merge_product_bindings.py::test_exact_spu_requires_approved_evidence`
  - `tests/test_merge_product_bindings.py::test_normalize_preserves_existing_bindings`
- **完成定义**：4 个 pytest 全绿；tests/fixtures/product_bindings/ 含 3 类文本；在种子 step3 上 product_bound_posts>0 且 product_bindings 元素通过前端 validateProductBinding 的 9 字段校验。

#### `L1-T06` 新行按自身文本打标、评论资格改为 governed-pending、字典版本触发器

- **严重度**：P1｜**类型**：feature｜**工作量**：L｜**拓扑层**：1
- **依赖**：`L1-T05`
- **描述**：修复 L1-P4。新增 refresh_public_tag_dictionary(base_dir, csv_path, allow_version_bump=False)：TagDictionary.from_csv(dim_tag_v6.3_final.csv) + build_public_dictionary -> 只写 tag-dictionary-public.json（不得写 tag-dictionary.json，否则破坏前端 4 文件集合），并把 manifest.tagging.dictionary_version/dictionary_sha256 与 manifest.inputs.tag_dictionary_sha256 三处同步为 sha256(csv)；版本变化且未 allow_version_bump -> tag_dictionary_version_drift。step3 preflight：CSV 缺失 -> tag_dictionary_file_missing。normalize_all 增加 tag_dictionary 与 product_contexts_by_post 参数：新帖用 title+content、新评用 body 调 extract_for_contexts，结果投影为公开 6 键；新评 include_in_voc_metrics=None + metric_eligibility_status='determined_in_governed_metrics_not_base_projection'（与 src/reddit_voc/v3_base_public.py:617-624 和前端 service.ts:1548-1551 一致）；评论 fast-path 接受两种一致组合；一次性迁移 run_id 存在且 record_authority=='workbook_net_new' 且 source_explicit 且 value is False 的行 -> None+governed（必须在 T11 之前发布，否则指纹消失）。不做历史打标回填。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/refresh_tag_dictionary.py`
  - `/Users/lute/Project/Echo-Agent/scripts/merge_normalize.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_merge_tagging.py`
  - `/Users/lute/Project/Echo-Agent/tests/fixtures/tagging/expected_tagged_rows.json`
- **验收**：
  - 命中 L0 规则的新帖 aspect_tag_ids 非空且 tagging.dictionary_version == manifest.tagging.dictionary_version；新评 include_in_voc_metrics is None 且 status 为 governed-pending。
  - manifest.inputs.tag_dictionary_sha256 == manifest.tagging.dictionary_sha256 == sha256(dim_tag_v6.3_final.csv) == 服务中 tag-dictionary-public.json 的 dictionary_sha256。
  - CSV 版本变化且未 allow_version_bump 时以 tag_dictionary_version_drift 失败，不写任何 manifest。
  - 种子日更后 posts_with_rule_tags 或 comments_with_rule_tags 增加，且新增行中不存在'文本命中 L0 规则但 aspect_tag_ids 为空'。
  - 迁移后历史 pipeline 评论中 include_in_voc_metrics is False 的计数不再增长（新行均为 null）；July 行字节不变。
- **测试**：
  - `tests/test_merge_tagging.py::test_new_post_is_tagged_from_own_text`
  - `tests/test_merge_tagging.py::test_new_comment_is_pending_not_false`
  - `tests/test_merge_tagging.py::test_template_tags_do_not_bleed`
  - `tests/test_merge_tagging.py::test_dictionary_hash_drift_fails_closed`
  - `tests/test_merge_tagging.py::test_public_dictionary_projection_matches_csv`
- **完成定义**：5 个 pytest 全绿；golden expected_tagged_rows.json 比对 3 行 fixture；服务端部署清单包含 dim_tag_v6.3_final.csv 与 src/reddit_voc/tag_dictionary.py；浏览器 /dashboard/analytics 的「有规则标签的帖子」在种子日更后增加。

#### `L1-T07` base 身份诚实化：generated_at 推进、lineage_mode/content_revision、日更血缘文档与指针同步

- **严重度**：P1｜**类型**：fix｜**工作量**：L｜**拓扑层**：4
- **依赖**：`L1-T04`
- **描述**：修复 L1-P6（ds_dir 硬编码条款归 L6-R4，本票不做）。新增 write_daily_base_lineage(...)（schema echo_agent_daily_base_lineage_v1，写 <base>/lineage/daily-merge-lineage.json）。refresh_base_manifest 增加关键字参数 run_id/previous_public_manifest_sha256/previous_binding_manifest_sha256/merged_at_utc；run_id=None 时只刷新 files/counts/time_precision（保持 step3_5 第二遍调用幂等）；同一 run_id 重复调用不推进时间/版本；首次写 lineage、set manifest.generated_at_utc=merged_at_utc、lineage_mode='daily_merge'、content_revision=prev+1、lineage_manifest_sha256=sha(document)。不移动 manifest.inputs（前端 exact-key 只允许 4 键，service.ts:986-994）。step3 调用带 run_id 与跑前 manifest sha，并同时更新指针 datasets.base.public_manifest_sha256 与 lineage_manifest_sha256。run_recompute 断言 sha256(base_manifest_abs)==binding（否则 base_binding_mismatch）、manifest_abs.parent==ds_dir（否则 base_dir_binding_mismatch，作为 L6-R4 前的桥梁）、daily_merge 且 generated_at 超 48h -> base_manifest_stale；回执新增 base_snapshot。消费者：L4 service.ts:981-999 必须同发布接受 lineage_mode 并跳过 canonical 等式（contracts 第 5 条）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/recompute_derivatives.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/scripts/lineage.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_base_lineage.py`
- **验收**：
  - 一次 step3 后 base manifest 的 generated_at_utc 推进、lineage_mode=='daily_merge'、content_revision 递增 1、lineage_manifest_sha256 == sha256(daily-merge-lineage.json)；inputs 4 键不变。
  - 指针 datasets.base.lineage_manifest_sha256 与 manifest.lineage_manifest_sha256 相等，且 release binding 键集不变。
  - recompute 回执 base_snapshot.manifest_sha256 == 指针 public_manifest_sha256；binding 不一致时以 base_binding_mismatch 失败。
  - lineage_mode=='daily_merge' 且 generated_at 距 now >48h 时以 base_manifest_stale 失败。
  - 同一 run_id 调用 refresh_base_manifest 两次，generated_at/content_revision/lineage_manifest_sha256 不变（幂等）。
- **测试**：
  - `tests/test_base_lineage.py::test_daily_lineage_binds_previous_manifest`
  - `tests/test_base_lineage.py::test_generated_at_advances_and_is_idempotent_per_run`
  - `tests/test_base_lineage.py::test_recompute_fails_on_base_binding_mismatch`
  - `tests/test_base_lineage.py::test_pointer_base_lineage_binding_updated`
  - `tests/test_base_lineage.py::test_manifest_inputs_key_set_unchanged`
- **完成定义**：5 个 pytest 全绿；两次日更 fixture 的 previous_public_manifest_sha256 正确串联；L4 lineage_mode 两形接受用例在同发布通过；浏览器 9 路由 0 错误。

#### `L1-T08` reports：attested 数据集只读保护 + 孤儿 history 归档

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：修复 L1-P7。抽 reports_recompute_decision(rp_root) -> 'skipped_attested_dataset'|'rebuilt_unattested'：读 <rp_root>/public/manifest.json，comparison_contract_proven is True 或 artifact_role/entry_label 含 attested 即跳过。run_recompute 在写 rp_root（1105）前决策；skip 时完全不调用 build_reports_bundle、不写任何字节；回执新增 reports_recompute（dry-run 记 skipped_dry_run）。新增 archive_orphan_reports_history.py（默认 --dry-run，--apply 才移动）：把 reports 目录中未出现在 manifest.files 的 history 文件移到 data/reddit-voc/lineage/reports-history/<ts>/ 并写 sha 清单，不删除。线上 attested 包已被覆盖，本票只防未来覆盖，不重建。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/recompute_derivatives.py`
  - `/Users/lute/Project/Echo-Agent/scripts/archive_orphan_reports_history.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_recompute_reports_guard.py`
- **验收**：
  - attested fixture（comparison_contract_proven=true）下 run_recompute 对 reports 目录零字节改动，回执 reports_recompute=='skipped_attested_dataset'，reports binding sha 不变。
  - 未 attested fixture 下重建，回执 reports_recompute=='rebuilt_unattested'，manifest 变化。
  - 连续两次运行在 attested fixture 上 history_report_count 与 manifest sha 稳定。
  - 归档脚本 --dry-run 仅列出文件；--apply 只移动不删除，并生成 sha 清单。
- **测试**：
  - `tests/test_recompute_reports_guard.py::test_attested_manifest_is_skipped`
  - `tests/test_recompute_reports_guard.py::test_unattested_manifest_is_rebuilt`
  - `tests/test_recompute_reports_guard.py::test_skipped_reports_leave_bytes_unchanged`
  - `tests/test_recompute_reports_guard.py::test_archive_moves_not_deletes`
- **完成定义**：4 个 pytest 全绿；线上当前 reports manifest（proven=false）走 rebuilt_unattested 且回执可见；38 个孤儿在 dry-run 输出中逐一列出。

#### `L1-T09` insights 降级：提交 owner attestation、CI 校验被引用 attestation 均可解析

- **严重度**：P1｜**类型**：ops｜**工作量**：S｜**拓扑层**：0
- **描述**：修复 L1-P8 的生产者半边（页面门禁移除归 L4-R4）。insights 冻结在 reddit_voc_insights_20261028_v3_aa80df7f4be9_rb895eac754fd，无定时作业写它，不新增 VALIDATED_PUBLIC_WRAPPERS 条目。提交 config/analytics/reddit-voc-data-owner-coverage-attestation-20261028-daily-v1.json，sha256 必须为线上引用的 046693af…（按 reddit_voc_data_owner_coverage_attestation_v1 schema，参考 20260723-daily-v1）。若字节不可恢复则按同 schema 重出并重新发布 insights（一次性人工），禁止伪造 sha。新增 check_attested_inputs.py：遍历 public root 下 manifest.json/manifest-public.json，收集所有 data_owner_coverage_attestation_sha256，要求在 config-dir 下存在同 sha 文件，缺失退出 1 并列出 manifest 路径。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/config/analytics/reddit-voc-data-owner-coverage-attestation-20261028-daily-v1.json`
  - `/Users/lute/Project/Echo-Agent/scripts/check_attested_inputs.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_attested_inputs.py`
- **验收**：
  - config/analytics 下存在 sha256 == 046693af… 的 attestation 文件，且其 dataset_id/source_snapshot_id 指向线上 insights 的 source。
  - check_attested_inputs.py 在当前被服务数据集上退出 0；删除任一被引用 attestation 的 fixture 退出 1 并打印 attested_input_missing:<sha>。
  - 仓库中没有任何新增 VALIDATED_PUBLIC_WRAPPERS 条目；无任何定时/流水线步骤写 insights 目录。
- **测试**：
  - `tests/test_attested_inputs.py::test_every_cited_attestation_is_committed`
  - `tests/test_attested_inputs.py::test_missing_attestation_fails_ci`
- **完成定义**：2 个 pytest 全绿；`python3 scripts/check_attested_inputs.py --public-root ref/UI/momcozy-reddit-workbench/public --config-dir config/analytics` 退出 0；attestation 文件 sha 与线上 manifest 引用一致。

#### `L1-T10` casebook 历史化：180 天复核节拍、删除 July 死默认、周链逾期告警

- **严重度**：P2｜**类型**：fix｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L1-T03`
- **描述**：修复 L1-P9。v3_casebook_snapshot.py:391-393 的 review_due_at 由 generated_at+14 天改为 +180 天。build_reddit_casebook_snapshot.py:24、32-38 删除 V3_ROOT 与三个 July 默认路径，--facts-root/--facts-receipt/--governed-root/--governed-receipt 改必填。周链回执在 dossier review_due_at 逾期时加 casebook_review_due{review_due_at,days_overdue,lifecycle_status,severity}，并在 30/7/0 天推 Feishu。不重建线上 casebook；案例目录（38 seed+12 legacy）不在范围。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/src/reddit_voc/v3_casebook_snapshot.py`
  - `/Users/lute/Project/Echo-Agent/scripts/build_reddit_casebook_snapshot.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_weekly_personas_chain.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_casebook_review_due.py`
- **验收**：
  - 新构建 dossier 的 review_due_at - generated_at == 180 天（ISO8601 秒精度）。
  - builder 在缺少显式 facts/governed 路径时以非零码失败，不再回落到 tmp/reddit-voc-v3/reddit_add_data_20260715_v1。
  - 线上 casebook（review_due 2026-07-30）对应的周链回执包含 casebook_review_due 且 days_overdue 为正。
  - 产物 casebook 文件集合与 schema 不变（前端 casebook.ts 的 exact-key 校验不受影响）。
- **测试**：
  - `tests/test_casebook_review_due.py::test_review_due_is_180_days_after_generated_at`
  - `tests/test_casebook_review_due.py::test_builder_requires_explicit_inputs`
  - `tests/test_casebook_review_due.py::test_weekly_receipt_reports_overdue_casebook`
- **完成定义**：3 个 pytest 全绿；golden tests/fixtures/casebook/expected-dossier.json；线上 dossier 不被改写（只由 L4 显示逾期徽标）。

#### `L1-T11` 保留 record_authority 并加 step3 守卫（daily_collect_* 必须 governed_base）

- **严重度**：P2｜**类型**：fix｜**工作量**：S｜**拓扑层**：2
- **依赖**：`L1-T06`
- **描述**：修复 L1-P12。merge_normalize.py:263、366 改为 record.get('record_authority') or 'governed_base'（帖/评各一），workbook_net_new 只保留给真正 workbook 导入的行。step3 在写 manifest 前统计 run_id 以 daily_collect_ 开头的行，任一 record_authority != 'governed_base' -> release_guard_unexpected_record_authority:<n>。依赖 T06 先落地：T06 的一次性资格迁移以 record_authority=='workbook_net_new' 为指纹，若本票先发布指纹消失。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/merge_normalize.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_merge_record_authority.py`
- **验收**：
  - step3 新增的帖/评 record_authority == 'governed_base'。
  - 无 run_id 的 July 行 record_authority 字节不变。
  - 构造一条 daily_collect_* 且 workbook_net_new 的行时，step3 在写 manifest 前以 release_guard_unexpected_record_authority 失败。
  - V3 facts 链的 record_authority 枚举无需新增值。
- **测试**：
  - `tests/test_merge_record_authority.py::test_pipeline_rows_keep_governed_base`
  - `tests/test_merge_record_authority.py::test_workbook_rows_untouched`
  - `tests/test_merge_record_authority.py::test_step3_guard_rejects_workbook_label`
- **完成定义**：3 个 pytest 全绿；一次种子 step3 后 daily_collect_* 行 100% governed_base，回执 record_authority_counts 可见。

#### `L1-T12` 发布前 content_entity 包含断言（SQL EXCEPT，零缺口才写 manifest）

- **严重度**：P2｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：修复 L1-P13 的守卫半边（读路径迁移不在 V2.0）。VocStore.assert_content_entity_containment() 用两条 SQL EXCEPT 比较 legacy reddit_threads/reddit_comments（补 t3_/t1_ 前缀）与 content_entity 的 entity_id，返回 {posts_missing, comments_missing}，不在 Python 里做 10 万级集合运算。step3 在 append 之前调用；非零 -> content_entity_containment_gap: <n> posts / <m> comments，不写任何 posts/comments/manifest 文件。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/src/reddit_voc/storage.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_step3_containment.py`
- **验收**：
  - legacy 行全部双写时断言的 posts_missing==comments_missing==0，step3 继续。
  - temp SQLite 中一条 legacy 行缺失于 content_entity 时，step3 以 content_entity_containment_gap 失败，且 posts-public.json 与 manifest-public.json 字节不变。
  - 断言使用 SQL EXCEPT（对 10 万行 O(1) 次查询），不构造 Python 全量集合。
  - 回执 containment 字段可见。
- **测试**：
  - `tests/test_step3_containment.py::test_containment_gap_fails_before_manifest_write`
  - `tests/test_step3_containment.py::test_containment_ok_passes`
- **完成定义**：2 个 pytest 全绿；一次种子 step3 回执 containment={0,0}；失败路径不产生任何写盘。

#### `L1-T13` is_bot 不再伪造 false：未知为 null，机器人检测状态显式化为 unavailable

- **严重度**：P2｜**类型**：fix｜**工作量**：S｜**拓扑层**：2
- **依赖**：`L1-T06`
- **描述**：修复 L1-P14（L2-P9 的上游）。step3 的 is_bot: False（:226 帖、:281 评）与 merge_normalize 的 :192、:365 改为 record.get('is_bot') if isinstance(..., bool) else None。不新增行级键（validate_reddit_v3_base_public_projection.py 的 POST_FIELDS/COMMENT_FIELDS 是精确集合，新增会触发 field_set_mismatch）。step3 回执加 bot_detection_status='unavailable_in_daily_ingress' 与计数。recompute 的 _voc_items 对 is_bot is None 仍纳入（not None 为真），不改变 VOC 口径。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/merge_normalize.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_merge_comment_eligibility.py`
- **验收**：
  - 新评论 is_bot is None（除非输入 record 显式带 bool）；新帖不新增/不伪造 is_bot 值。
  - step3 回执 bot_detection_status=='unavailable_in_daily_ingress'，且 comments with is_bot is False 不再随语料增长。
  - validate_reddit_v3_base_public_projection.py 的 COMMENT_FIELDS/POST_FIELDS 集合未变，验证器对 fixture 仍通过。
  - 不修改自动化分类数据集或 personas 的 automation 排除逻辑。
- **测试**：
  - `tests/test_merge_comment_eligibility.py::test_new_comment_is_bot_unknown`
  - `tests/test_merge_comment_eligibility.py::test_explicit_boolean_is_preserved`
  - `tests/test_merge_comment_eligibility.py::test_comment_field_set_unchanged`
- **完成定义**：3 个 pytest 全绿；种子 step3 后新评论 is_bot 全为 None；前端 comment 类型 boolean|null 不需改动。

#### `L1-T14` 评论字节区间索引 comments-index-public.json（manifest.comments_index 绑定）

- **严重度**：P3｜**类型**：feature｜**工作量**：M｜**拓扑层**：2
- **依赖**：`L1-T06`
- **描述**：补齐 L1-P15（L4-R12 的前置）。新增 build_comments_index.py：在 comments-public.json 写盘后，按 json.dumps(ensure_ascii=False, indent=2) 的精确布局计算每行 row 的 offset/length/sha256，按 post_id 聚合为 1..n 段（相邻段合并，保证 <=3 段/帖）；产物 comments-index-public.json（schema reddit_voc_comments_index_public_v1，含 source{file,bytes,sha256} 与 posts{post_id:{count,ranges:[{offset,length,sha256}]}}）。不加入 manifest.files（前端 EXPECTED_SNAPSHOT_FILES 精确 4 个），改为 manifest 顶层 comments_index{path,schema_version,bytes,sha256}。step3 必须在同一次写盘后重建索引（资格迁移等任何 comments 改写都会使旧索引失效）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/build_comments_index.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_comments_index.py`
- **验收**：
  - 索引的每个 range 用 Range 读取后 sha256 与 range.sha256 一致，且 JSON.parse 出的对象等于原 comments-public.json 对应行。
  - 单帖 range 数 <=3；25k 帖索引总量远小于单体文件。
  - comments-public.json 任何变化都会导致索引 sha 与 manifest.comments_index.sha256 不一致（无静默过期）。
  - manifest.files 仍恰为 4 个文件，前端 assertSnapshotFileManifest 通过。
- **测试**：
  - `tests/test_comments_index.py::test_ranges_slice_exact_rows`
  - `tests/test_comments_index.py::test_range_count_per_post_at_most_three`
  - `tests/test_comments_index.py::test_index_is_rebuilt_when_comments_change`
  - `tests/test_comments_index.py::test_manifest_file_set_unchanged`
- **完成定义**：4 个 pytest 全绿；在 3 帖 6 评 fixture 上逐段校验通过；manifest.comments_index 与文件字节一致；L4-R12 可用该索引做 <=3 次 Range 请求。

### L2 — 计算正确性层 (Computation Correctness)

#### `L2-T01` 修正月报环比基线与六期链，并给环比加低样本门禁

- **严重度**：P0｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：Wave 2。根因：compute_period('monthly', anchor) 返回 anchor 所在月之前的完整月（recompute_reports_bundle.py:106-108），而 _previous_period 对 monthly 仍传 start-1day（:123-131），所以 monthly:2026-09-01:2026-10-01 的 baseline 落到 monthly:2026-07-01:2026-08-01；_period_chain（:449-458）重复该错误。实现：(1) monthly 分支 prev_anchor=start；(2) 新增 _assert_period_step(grain, earlier, later)（daily 1 天 / weekly 7 天 / monthly 月差 1），在 _period_chain 每次推进和 final previous 调用，跳月即 raise；(3) _build_indicators 只算一次 current/previous governed_vocs，传 sample_size 给 _observed_comparison；(4) comparison 新增 sample_size:int|null、sample_gate:'ok'|'below_100'；<100 时 status 保持 provisional、追加 reason comparison_sample_below_100，direction/display/value 保持真实值（reports.ts:891-895 要求非 unavailable 比较必须有 direction 且 value 非空）。daily/weekly 分支不得改动。
- **涉及文件**：
  - `scripts/recompute_reports_bundle.py`
  - `tests/test_recompute_reports_bundle.py`
- **验收**：
  - anchor=2026-10-29 时 previous.period_id == monthly:2026-08-01:2026-09-01，current == monthly:2026-09-01:2026-10-01
  - 6 个 history period_id 相邻月差均为 1，不再出现 2025-09/11、2026-01/03/05/07 的隔月序列
  - fixture Aug 17 / Sep 21 输出 display='+23.5%'、direction='up'、sample_gate='below_100'、reason_codes 含 comparison_sample_below_100
  - sample_size>=100 时 sample_gate='ok'，reason_codes 不含 comparison_sample_below_100
  - 构造跳月的 compute_period 输入时 _period_chain 抛 period_chain_not_consecutive
- **测试**：
  - `tests/test_recompute_reports_bundle.py::test_monthly_previous_period_is_immediately_preceding_month`
  - `tests/test_recompute_reports_bundle.py::test_period_chain_monthly_is_consecutive`
  - `tests/test_recompute_reports_bundle.py::test_period_step_rejects_skipped_month`
  - `tests/test_recompute_reports_bundle.py::test_monthly_mom_uses_august_baseline`
  - `tests/test_recompute_reports_bundle.py::test_low_sample_comparison_is_provisional_with_reason`
  - `tests/test_recompute_parity.py::test_brand_health_contribution_matches_js_rounding`
- **完成定义**：pytest tests/test_recompute_reports_bundle.py -q 全绿且 test_recompute_parity.py 无回归；用 anchor=2026-10-29 生成的 bundle 中 previous period_id 为 2026-08-01:2026-09-01；无前端契约变更。

#### `L2-T02` 撤回 RV-BR-05/04 同名改义，恢复注册表身份并标 unavailable

- **严重度**：P0｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：Wave 2。根因：COMPUTED_METRICS 把 RV-BR-04 定义为 (percent, 推荐表达率) 却算正向情感占比、把 RV-BR-05 定义为 (percent, 竞品语境占比) 且分子只判 mentioned_brands 非空（recompute_reports_bundle.py:63-68,166-175），而注册表定义 RV-BR-05=竞品净情感差/pp（config/analytics/reddit-voc-indicator-registry-v1.json），规范实现在 src/reddit_voc/v3_indicators.py:1002-1074,1553-1576。实现：从 COMPUTED_METRICS 删除 RV-BR-04 与 RV-BR-05，两者落入 else 分支（:429-444）→ status=unavailable、value=null、display='—'、reason=metric_not_recomputed_by_current_engine；保留模板的 name_cn/unit（RV-BR-05 竞品净情感差/pp，RV-BR-04 推荐表达率/percent），不得重命名；删除 _metric_value 的 RV-BR-04/05 死分支；_build_indicators 显式写 observed_voc_type='post_voc+comment_context_voc'，不再复制模板；同步 ADR-002 第 164 行与 §5 中把 RV-BR-05 说成竞品语境占比的表述。前端无需改动：isDisplayableReportIndicator 对 unavailable 返回 false，competitorGap 自动为 null，净情感 pp 句与两条行动句不再渲染。
- **涉及文件**：
  - `scripts/recompute_reports_bundle.py`
  - `docs/adr/ADR-002-data-freshness-parity.md`
  - `tests/test_recompute_reports_bundle.py`
- **验收**：
  - build_reports_bundle 输出中 RV-BR-05 的 current.status=='unavailable'、value is None、unit=='pp'、name_cn=='竞品净情感差'
  - RV-BR-04 的 current.status=='unavailable'、value is None、unit=='percent'、name_cn=='推荐表达率'
  - 不存在 name_cn=='竞品语境占比' 或 unit=='percent' 的 RV-BR-05 行
  - 所有 indicator 的 current.observed_voc_type=='post_voc+comment_context_voc'，indicator.name_cn==current.name_cn
  - summary.current_unavailable 从 22 变为 24（26 指标中仅 RV-BR-01/02 可算）
- **测试**：
  - `tests/test_recompute_reports_bundle.py::test_rv_br_05_is_unavailable_not_redefined`
  - `tests/test_recompute_reports_bundle.py::test_rv_br_04_is_unavailable_not_positive_share`
  - `tests/test_recompute_reports_bundle.py::test_computed_indicators_preserve_registry_unit_and_name`
  - `tests/test_recompute_reports_bundle.py::test_observed_voc_type_matches_scope`
- **完成定义**：pytest tests/test_recompute_reports_bundle.py -q 全绿；生成的 bundle 中 RV-BR-04/05 均为 unavailable 且保留 pp/percent 与注册表名称；OperationalReportSupplement 不再出现『净情感较同样本竞品』字符串（人工或 L3 测试确认）。

#### `L2-T03` 产品家族/品类/精确 SPU 只用 product_bindings 聚合，无绑定即 unavailable

- **严重度**：P0｜**类型**：fix｜**工作量**：M｜**拓扑层**：1
- **依赖**：`L4-T11`
- **描述**：Wave 2。根因：new_product 的 category_rankings/exact_spu_rankings/family_rankings/product_rankings 全由 analysis.topic 生成（recompute_derivatives.py:498-508,547-556,670-680），family_only_ids 拼 topic_family（:552-553），页面却标产品家族/已批准精确 SPU。实现：新增 _product_binding_rankings(vocs, level)，只取 product_bindings 中 brand_id=='momcozy' 的绑定：category 需 binding_level=='category' 且 governance_status=='category_only'；product_family 需 binding_level in {product_family,spu_exact} 且 product_family 非 null；spu_exact 需 binding_level=='spu_exact' 且 governance_status=='exact_spu_approved'；每个 VOC 对同一实体去重；label 用实体 name_cn/name_en/spu_name。新增 coverage {status,bound_vocs,total_vocs,reason_codes}；bindings==0 时四个 rankings 与 family_only_ids 一律 []，status=unavailable，reason=no_governed_product_bindings_in_period（当前季度 live=0）。product_rankings=family_rankings（与 canonical v3_quarter_insights_public.py:885-890 一致）。evidence 保留 topic 证据，reason 改 product_or_topic_evidence；method 说明 topic 只做证据。必须与 L4-P15 同版本（quarterInsights.ts:394-396 当前要求 rankings 非空、:633-640 是 exact keys）。同步更新 tests/test_recompute_parity.py::test_quarter_insights_matches_frozen_schema 的 key 集合。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_derivatives_metrics.py`
  - `tests/test_recompute_parity.py`
- **验收**：
  - fixture 中 post 绑定 s9-pro family → family_rankings 的 id=='s9-pro'，绝不出现 'troubleshooting'/'product_evaluation'
  - 当前 live 语料（季度内 0 governed 绑定）→ coverage.status=='unavailable'、bound_vocs==0、四个 rankings==[]、family_only_ids==[]
  - family_only_ids 只含 binding_level=='product_family' 的 product_family.id
  - product_rankings 与 family_rankings 同源同值
  - exact_spu_rankings 只含 binding_level=='spu_exact' 且 governance_status=='exact_spu_approved' 的 spu_id
- **测试**：
  - `tests/test_recompute_derivatives_metrics.py::test_new_product_rankings_use_product_bindings`
  - `tests/test_recompute_derivatives_metrics.py::test_new_product_unavailable_when_no_bindings`
  - `tests/test_recompute_derivatives_metrics.py::test_product_family_ids_are_binding_ids_not_topics`
  - `tests/test_recompute_parity.py::test_quarter_insights_matches_frozen_schema`
- **完成定义**：pytest 新增用例全绿；fixture 输出只含 binding id；live 形状为 unavailable+空数组；与 L4-P15 同一 release 上线且 /dashboard/insights 不再显示『问题排查 187 / 产品评价 77』作为产品家族/SPU。

#### `L2-T04` GEO 恢复 canonical 定义：distinct decision-topic posts + topic rankings

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：Wave 2。根因：geo_vocs 用 topic==purchase_decision OR 任意竞品提及的混合谓词，rankings 按品牌计 post×brand pair，comparison_decision_posts=sum(rankings)=60（recompute_derivatives.py:510-526），而规范定义是仅 post_voc 且 topic in {competitor_comparison,purchase_decision}，count=sum(topic counts)，rankings 用 topic id（src/reddit_voc/v3_quarter_insights_public.py:676-688,894-899）。实现：geo_posts = [v for v in in_quarter if v['_kind']=='post' and topic in (...)]；comparison_decision_posts=len(geo_posts)；geo_rankings=Counter(topic)→[{id:topic,label:TOPIC_LABELS[topic],count}]；空时保留一行 unspecified 以兼容非空校验；evidence 取 geo_posts；method 改为 momcozy_post_topic_decision_v1。删除 geo_vocs 的竞品混合谓词（竞品维度由 T16/T17 的独立字段承担）。前端无需改动即正确：SnapshotInsightsV3.tsx:205-216 的 rankingValue('competitor_comparison') 将得到 70，comparison_decision_posts=112；quarterInsights.ts:641-646 的 sum==count 守恒仍成立。同步 frozen schema 测试（geo key 不变，仅 id/值变化）。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_derivatives_metrics.py`
  - `tests/test_recompute_parity.py`
- **验收**：
  - live-like fixture：70 条 competitor_comparison + 42 条 purchase_decision → comparison_decision_posts==112，rankings id 集合=={competitor_comparison,purchase_decision}
  - 两帖各提两个竞品 → comparison_decision_posts==2（不是 4）
  - 仅评论命中竞品、或帖子命中竞品但 topic 不是决策主题 → 不计入
  - sum(rankings.count)==comparison_decision_posts 对所有 fixture 成立
  - 前端 SnapshotInsightsV3 的『竞品比较问题』>0，『比较与决策帖子』显示 112
- **测试**：
  - `tests/test_recompute_derivatives_metrics.py::test_geo_decision_count_is_distinct_posts`
  - `tests/test_recompute_derivatives_metrics.py::test_geo_rankings_use_topic_ids`
  - `tests/test_recompute_derivatives_metrics.py::test_geo_ignores_comments_and_competitor_only_vocs`
- **完成定义**：pytest 新增用例与 test_recompute_parity.py::test_quarter_insights_matches_frozen_schema 全绿；live 输出 112 且 rankings 仅 topic id；/dashboard/insights 的 GEO 摘要与图表一致。

#### `L2-T05` brand-health.json 输出 governed sample 计数（帖子/评论/已分类/总 VOC）

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L4-T12`
- **描述**：Wave 2。根因：recompute_brand_health 不输出样本（recompute_derivatives.py:797-817），前端用 isMomcozyPost 估算 2,280（SnapshotDashboard.tsx:516、operational.ts:9-12,89-93），与打分用的 governed 集合不一致（实际 1,136 帖 + 2,289 评论 = 3,425 VOC）。实现：在 :731-733 的 _voc_items 结果上直接生成 sample {post_vocs, comment_context_vocs, classified_vocs, total_vocs} 与 sample_basis（governed brand_binding 集合且排除 is_bot），字段必须来自与 overall 打分完全相同的那一次调用。brand-health.json 的 DATA_KEYS 是 exact-key（brandHealth.ts:97-100），必须与 L4-P14 同版本：消费端先接受两种形态（有/无 sample），producer 后输出。本 ticket 不编辑前端。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_brand_health_lean.py`
- **验收**：
  - fixed fixture 3 帖/5 评论 → sample.post_vocs==3、comment_context_vocs==5、total_vocs==8，且与 dimensions 打分使用的集合一致
  - is_bot=True 的评论不计入 sample
  - live 语料输出 sample={1136,2289,3425,3425}（允许随语料增长，但四个数必须与 _voc_items 完全一致）
  - brand-health.json 仍通过 manifest SHA 自洽（canonical bytes 与 manifest.files 一致）
- **测试**：
  - `tests/test_brand_health_lean.py::test_brand_health_sample_counts_match_governed_vocs`
  - `tests/test_brand_health_lean.py::test_brand_health_sample_excludes_bots`
- **完成定义**：pytest tests/test_brand_health_lean.py -q 全绿；生成的 brand-health.json 含 sample 且数值等于打分集合；与 L4-P14 同 release 后卡片不再显示 2,280。

#### `L2-T06` 品牌健康四维改为公开数据可复现的 50/50 grain 公式，并声明 proxy

- **严重度**：P1｜**类型**：fix｜**工作量**：L｜**拓扑层**：1
- **依赖**：`L4-T12`, `L5-T11`
- **描述**：Wave 2。根因：lean 公式是池化 posts+comments（recompute_derivatives.py:731-795），与页面公布的 canonical 定义（BrandHealthSnapshotCard.tsx:6-27）和规范引擎（src/reddit_voc/v3_brand_health.py:250-395,415-419）不一致；comparison_side 标 qualified_organic 却未做排除。实现 B 方案：(1) 按 post_voc/comment_context_voc 两个 grain 分别算四维再 /2；(2) reputation=50+50*(pos-neg)/classified（canonical :250-283）；(3) product_experience 只在 brand_id=='momcozy' 且 product_bound 的已分类 VOC 上算 100-100*high_defects/classified（canonical :285-318，当前复算 94.81 n=283）；(4) recommendation 保持 pos/(pos+neg) 但 50/50 并声明 is_proxy、proxy_for='recommendation_closed_set_balance'；(5) risk 保持 100-2*neg_rate 但 50/50 并声明 proxy_for='priority_weighted_risk'；(6) 每个 dimension 增加 definition {id,formula_id,numerator_scope,denominator_scope,grain_weighting,is_proxy,proxy_for}，顶层增加 overall_score_basis='equal_weight_mean_of_four_dimensions'、comparison_side_basis='no_exclusion_applied'、formula_version='brand_health_lean_v2.1'；(7) 不改 overall_score_derived_from_axes（L5-P9 拥有）；(8) 更新 ADR-002 §5.3 记录新公式与 proxy；(9) 单 grain n<30 → 维度 unavailable + reason '<grain>:classified_sample_below_30'，两个 grain 都可用时才可 available；若某 grain 永久不足，保留 pooled 回退并在 reason 里注明 pooled_fallback（实现时二选一并写进 ADR）。整体分数将从 75.42 变为约 73.9，必须单独发版并在卡片标注 before/after。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `docs/adr/ADR-002-data-freshness-parity.md`
  - `tests/test_brand_health_lean.py`
  - `tests/test_recompute_parity.py`
- **验收**：
  - fixture pos=70,neg=30,n=200 分 grain 不同 → reputation==50+50*(70-30)/200==58.0（两 grain 均值后四舍五入）
  - product_experience 使用 product_bound 集合：fixture 70/213 高分故障 → 94.81（与审计复算一致）
  - 四个 dimension 都有 definition.id/is_proxy/grain_weighting；recommendation 与 risk 的 is_proxy==true 且 proxy_for 非空
  - overall == round_half_up(mean(四个 dimension score),2)，且与客户端 Math.round 公式一致
  - overall_score_derived_from_axes 仍为 false（本 lane 不改）
  - ADR-002 §5.3 的公式表与实现逐项一致，且明确 product_experience/recommendation/risk 哪些是 proxy
- **测试**：
  - `tests/test_brand_health_lean.py::test_reputation_is_signed_balance_50_50_grain`
  - `tests/test_brand_health_lean.py::test_product_experience_uses_product_bound_classified`
  - `tests/test_brand_health_lean.py::test_dimension_carries_definition_and_proxy_flags`
  - `tests/test_brand_health_lean.py::test_overall_equals_half_up_mean_of_dimensions`
  - `tests/test_recompute_parity.py::test_brand_health_projection_is_self_consistent`
- **完成定义**：pytest tests/test_brand_health_lean.py tests/test_recompute_parity.py -q 全绿；live 复算得到 58.58/94.81/70.08/72.26→约 73.9 并与 payload 一致；ADR 与实现无冲突；与 L4-P14/L5-P9 同 release。

#### `L2-T07` 报告 brand_health 行补齐 value/display/unit，并显式标注 all-history 口径

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：Wave 2。根因：_brand_health_block 的 rows 只有 score/status（recompute_reports_bundle.py:299-354），前端 V3BrandHealthRow 要求 value/display（reports.ts:696-701），periodBrandHealth 因此返回 null（OperationalReportSupplement.tsx:97-103）；raw_observed 与 qualified_organic 同值同 status；dimension_rows 两份同值；archive baselines 也是 all-history（:531-534）。实现：_brand_health_block(brand_health, period, grain, hashes, *, role='current'|'baseline')，keyword-only 保持现有 4 参调用兼容；rows 补 value/display/unit='index'/period_id/grain/time_precision/source_calendar_date/projection_period='all_observed_history'/period_applicability='not_period_scoped'/comparison_contract_proven=false/data_owner_coverage_attestation_sha256=null/profile hashes；raw_observed 标 unavailable、value=null、display='—'、reason=projection_side_not_computed；qualified_organic 用真实 overall；dimension_rows 的 raw 侧同样 unavailable/null，qualified 侧保留数值；role='baseline' 时 qualified 也 unavailable，reason=periodized_brand_health_not_available。report 根对象未被 exact-key 校验，additive 安全。
- **涉及文件**：
  - `scripts/recompute_reports_bundle.py`
  - `tests/test_recompute_reports_bundle.py`
- **验收**：
  - 每个 current 报告 brand_health.rows 长度为 2，且每行都有 value 与 display；qualified_organic.value 是两位小数字符串
  - raw_observed.status=='unavailable' 且 value===null，绝不与 qualified 同为 available 同值
  - periodBrandHealth(report) 返回非 null，报告管理摘要出现品牌健康
  - monthly 的 8 条 dimension_rows 都带 projection_period=='all_observed_history' 与 period_applicability=='not_period_scoped'
  - archive 的 brand_health_baselines 全部 unavailable + reason periodized_brand_health_not_available
- **测试**：
  - `tests/test_recompute_reports_bundle.py::test_report_brand_health_rows_have_value_and_display`
  - `tests/test_recompute_reports_bundle.py::test_raw_observed_not_duplicated_as_available`
  - `tests/test_recompute_reports_bundle.py::test_monthly_brand_health_flags_all_observed_history`
  - `tests/test_recompute_reports_bundle.py::test_period_brand_health_qualified_value_is_renderable`
- **完成定义**：pytest tests/test_recompute_reports_bundle.py -q 全绿；用生成 bundle 跑前端 RealReportViewV3 测试时 periodBrandHealth 非 null；/dashboard/reports 管理摘要出现品牌健康。

#### `L2-T08` 机器人评论计数移到品牌过滤之前，reports governed 过滤排除 bot

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L1-T13`
- **描述**：Wave 2。根因：_voc_items 先按 brand_binding+not is_bot 过滤（recompute_derivatives.py:143-157），automation_comments 再从 in_quarter 统计（:480-484），所以即使有 bot 也恒 0；reports._is_governed 也未排除 bot（recompute_reports_bundle.py:139-140）。实现：新增 _quarter_comments(comments, start, anchor)（按 _event_date 取季度内原始评论，不按 brand_binding、不排除 bot）；automation_comments 从该集合统计 is_bot is True 或 record_authority=='automation'；reports._is_governed 增加 not record.get('is_bot')。生产者 is_bot 硬编码是 L1-P14，本 ticket 不修改 run_daily_t1_pipeline.py/merge_normalize.py；L1-P14 未上线时 live 季度仍可能为 0，但 fixture 中 governed bot 与 ungoverned bot 都必须计数。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `scripts/recompute_reports_bundle.py`
  - `tests/test_recompute_derivatives_metrics.py`
- **验收**：
  - fixture 含 1 条 governed bot + 1 条品牌不绑定的 bot 评论 → automation_comments>=2
  - 无 bot 时 automation_comments==0 且不抛错
  - reports 的 governed VOCs 排除 is_bot=True 的评论（fixture 计数差 1）
  - quarter 的 momcozy.total_vocs 不因本改动变化（bot 仍不计入品牌归因）
- **测试**：
  - `tests/test_recompute_derivatives_metrics.py::test_automation_comments_counts_bots_before_brand_filter`
  - `tests/test_recompute_reports_bundle.py::test_reports_governed_vocs_exclude_bots`
- **完成定义**：pytest 两个文件全绿；fixture 证明计数顺序正确；现有 quarter-insights schema 测试无回归。

#### `L2-T09` 未接入的自动化/版务证据显式标 unavailable，不显示裸 0

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L4-T10`
- **描述**：Wave 2。根因：moderation_claims 硬编码 []（recompute_derivatives.py:485），automation 分类文件从未被消费，前端把 0 当已测结果。实现：themes.reputation 增加 coverage {automation_comments:{status,reason_codes}, moderation_claims:{status:'unavailable',reason_codes:['moderation_classification_artifact_not_consumed']}}；automation 无分类输入时 status='provisional'（is_bot flag 存在但未被分类文件验证）或 'unavailable'（连 flag 都没有），reason 明确；moderation_claims 保持 [] 但状态 unavailable。若未来 public root 存在 automation-classifications.jsonl，复用 v3_quarter_insights_public.py:733-758 的 allowlist 校验；V2.0 不建立该文件。该键是 quarter-insights exact-key 变更（quarterInsights.ts:621-632），必须与 L4-R10 同版本。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_derivatives_metrics.py`
- **验收**：
  - 无分类文件时 moderation_claims.status=='unavailable' 且 reason_codes 非空，UI 不显示『0 条版务治理证据』作为结论
  - automation_comments 的 coverage.status 反映数据来源：有 is_bot 字段→provisional；完全无字段→unavailable
  - coverage 状态与 reputationCounts 数值同时存在且不矛盾（数值可为 0，但状态不得是 available 除非分类文件已消费）
  - themes.reputation 的 rankings 仍与四个 count 键一一对应（前端守恒不破）
- **测试**：
  - `tests/test_recompute_derivatives_metrics.py::test_reputation_coverage_marks_moderation_unavailable`
  - `tests/test_recompute_derivatives_metrics.py::test_automation_coverage_reflects_classification_absence`
- **完成定义**：pytest 新增用例全绿；fixture 输出 coverage 且与 L4-R10 的消费端同版本后 /dashboard/insights 显示『未接入』而不是『0』。

#### `L2-T10` 抽出共享 event_business_date，reports/derivatives 统一上海业务日

- **严重度**：P1｜**类型**：refactor｜**工作量**：S｜**拓扑层**：0
- **描述**：Wave 2。根因：reports 的 _event_date 直接取 UTC 字符串前 10 位（recompute_reports_bundle.py:84-90），却声明 calendar_day_assignment_v1（:49-53）；derivatives 已有上海转换（recompute_derivatives.py:125-137），两份实现并存。live 10,672 帖/40,060 评论的 UTC 日≠上海日；daily 10-28 的 RV-BR-01=27（UTC）而上海口径 15，period_activity 9 vs 客户端 6。实现：新增 src/reddit_voc/event_time.py（event_datetime_utc / event_business_date；优先级 source_calendar_date > event_created_at_utc > created_at_utc；转 Asia/Shanghai 取日期；非法返回 None）；两个 producer 的 _event_date 都委托它并删除重复实现；report.period 可加 assignment_basis='asia_shanghai_business_date'（additive）。客户端 operational.ts:146-158 改用 event_created_at_utc ?? created_at_utc 属 L4，本 ticket 只保证 producer 一致。新模块必须加入 lean 部署文件清单。
- **涉及文件**：
  - `src/reddit_voc/event_time.py`
  - `scripts/recompute_reports_bundle.py`
  - `scripts/recompute_derivatives.py`
  - `tests/test_event_time.py`
  - `tests/test_recompute_reports_bundle.py`
- **验收**：
  - 2026-10-28T15:59:59Z → '2026-10-28'；2026-10-28T16:00:00Z → '2026-10-29'（Asia/Shanghai）
  - source_calendar_date 存在的记录优先返回该日期，不做午夜补造
  - daily:2026-10-28:2026-10-29 的 fixture（27 条，其中 12 条 16:00Z 之后）RV-BR-01==15
  - reports 与 quarter-insights 对同一 fixture 给出同一业务日桶
  - 非法/缺失时间戳返回 None，不静默归到某个日期
- **测试**：
  - `tests/test_event_time.py::test_event_business_date_prefers_source_calendar_date`
  - `tests/test_event_time.py::test_event_business_date_converts_utc_to_shanghai`
  - `tests/test_event_time.py::test_event_business_date_returns_none_on_invalid`
  - `tests/test_recompute_reports_bundle.py::test_reports_period_uses_shanghai_business_date`
  - `tests/test_recompute_reports_bundle.py::test_daily_report_count_matches_shanghai_fixture`
- **完成定义**：pytest 全绿；同一 fixture 在两个 producer 中得到同一上海业务日；发布说明记录最新日 27→15 的变化。

#### `L2-T11` 品牌实体规范化（读路径）：按 config/brands.json 聚合，同一 brand_id 唯一

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：Wave 2。根因：aggregates 三份实现都按 mentioned_brands 原始字符串计数（site_aggregates.py:137-141,196-206；v3_base_public.py:723-726,781-791；validate_reddit_v3_base_public_projection.py:353-359），把 eufy 555 + eufy S1 242 拆成两行；brands.py:134-141 已能规范化。实现：三处同改用 mentioned_brand_ids() 归一，每行输出 {brand_id, brand:display_name, posts:distinct posts with >=1 mention, sample_mention_share:posts/sum(posts)}；每个 post 对同一 brand_id 只计 1；行按 count desc, brand_id asc，brand_id 唯一。保留 brand 字段供前端 SnapshotAnalytics.tsx:107-123,172,186 直接渲染。三份实现必须逐字段一致，否则 validate_reddit_v3_base_public_projection.py:577-578 的整对象比较会拒绝。更新 test_site_aggregates.py 的 brand-heavy 断言（3 次 momcozy → posts=1，不是 3）。
- **涉及文件**：
  - `src/reddit_voc/site_aggregates.py`
  - `src/reddit_voc/v3_base_public.py`
  - `scripts/validate_reddit_v3_base_public_projection.py`
  - `tests/test_site_aggregates.py`
- **验收**：
  - fixture 'eufy' + 'eufy S1' → 单行 brand_id=='eufy'、posts==2（两个不同帖子各一次）
  - 同一帖子提及 'eufy' 与 'eufy S1' → 该 brand_id 的 posts 只加 1
  - brand_sample_mentions 中 brand_id 唯一，无重复行
  - 50+ config 竞品 id 都能通过 mentioned_brand_ids 命中（含 Boppy/Baby Brezza/Philips Avent/Motif/Zomee）
  - test_producers_agree_on_representative_corpus 与 test_producers_agree_on_brand_heavy_corpus 全绿
- **测试**：
  - `tests/test_site_aggregates.py::test_brand_sample_mentions_are_canonical`
  - `tests/test_site_aggregates.py::test_brand_mention_share_dedupes_per_post`
  - `tests/test_site_aggregates.py::test_producers_agree_on_representative_corpus`
  - `tests/test_site_aggregates.py::test_producers_agree_on_brand_heavy_corpus`
- **完成定义**：pytest tests/test_site_aggregates.py -q 全绿；live aggregates 中 eufy 只有一行（797）；SnapshotAnalytics 对比图只出现一根 eufy 柱。

#### `L2-T12` 新行品牌提及改用 brands.find_brands（写路径）

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：2
- **依赖**：`L1-T06`
- **描述**：Wave 2。根因：merge 只用 6 个硬编码品牌做 substring 匹配（run_daily_t1_pipeline.py:203），50+ 竞品被漏掉；merge_normalize 透传原始 mention。实现：run_daily_t1_pipeline.py:203 改为 find_brands(title+' '+content)，mentioned_brands=sorted(display_name(bid) for bid in found)；brand_binding 判定逻辑不变；merge_normalize 用新增 helper canonical_mention_labels(mentions)（mentioned_brand_ids→display_name→去重排序）；不新增 base schema 字段，避免 L1 base bump（代价是丢失 'eufy S1' 这类表面形式）。与新行 is_bot=False 同文件相邻，必须与 L1-P14 串行落地，避免文本冲突。
- **涉及文件**：
  - `scripts/run_daily_t1_pipeline.py`
  - `scripts/merge_normalize.py`
  - `src/reddit_voc/brands.py`
  - `tests/test_merge_brand_extraction.py`
- **验收**：
  - 新帖正文含 'eufy S1' → mentioned_brands==['eufy']（canonical 展示名）
  - 新帖含 'Boppy'/'Baby Brezza' → 能被识别，不再依赖 6 品牌白名单
  - 正文含 'Momcozy' → brand_binding 仍为 momcozy_sentence_bound
  - merge_normalize 对已有行不重写 mentioned_brands（幂等）
  - canonical_mention_labels(['eufy S1','eufy']) == ['eufy']
- **测试**：
  - `tests/test_merge_brand_extraction.py::test_new_post_uses_canonical_brand_ids`
  - `tests/test_merge_brand_extraction.py::test_competitor_ids_beyond_hardcoded_six_are_detected`
  - `tests/test_merge_brand_extraction.py::test_merge_keeps_canonical_labels`
- **完成定义**：pytest tests/test_merge_brand_extraction.py -q 全绿；新行 mentioned_brands 全部是 config/brands.json 中的展示名；与 L1-P14 联合回归。

#### `L2-T13` 发布 observation_window 与边界后计数（披露，不截断）

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：Wave 2。根因：merge 窗口 2000-2100（run_daily_t1_pipeline.py:171-174），aggregates date_range 取全量（site_aggregates.py:152-153,180-183），data_as_of 来自墙钟（advance_daily_t1_release.py:25-34）；live 有 52 帖/255 评论晚于 data_as_of=2026-10-28T23:00:00Z，但头条不披露。实现（approved plan 决策 A）：refresh_base_manifest 新增 keyword-only data_as_of_utc 参数；run_recompute 从 release['freshness']['data_as_of_utc'] 传入；在 base manifest 顶层写 observation_window {data_as_of_utc, observation_max_utc, events_after_data_as_of:{posts,comments}}；observation_max_utc=max(created_at_utc across posts+comments)；严格 > 比较；data_as_of 缺失时不写。写入 manifest 而非 aggregates，避免三 producer 整对象比较。不截断语料；截断是 L6 的条件性后续。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_observation_window.py`
- **验收**：
  - fixture 1 帖晚于 data_as_of → events_after_data_as_of.posts==1 且 observation_max_utc 等于该帖时间
  - data_as_of 缺失 → manifest 不含 observation_window 键（不是 null/空对象）
  - observation_max_utc > data_as_of_utc 时字段可直接驱动前端警示（live 52/255）
  - manifest 其余键、canonical_counts、time_precision 不变；manifest SHA 自洽
- **测试**：
  - `tests/test_observation_window.py::test_refresh_base_manifest_publishes_observation_window`
  - `tests/test_observation_window.py::test_events_after_data_as_of_counts_posts_and_comments`
  - `tests/test_observation_window.py::test_no_observation_window_without_data_as_of`
- **完成定义**：pytest tests/test_observation_window.py -q 全绿；生成的 manifest 含 observation_window；L4 的 DataFreshnessBar 能读取并显示『含边界后 X 帖/Y 评论』。

#### `L2-T14` 拆分评论分母：Base 显式资格 / governed VOC / 总关联评论

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：Wave 2。根因：comments_in_voc_metrics 只计 include_in_voc_metrics is True（site_aggregates.py:163-168；live 16,822/43,331/40,625），derivatives 用 brand_binding（recompute_derivatives.py:143-157，品牌健康 2,289），reports 用全部 linked comments（100,778）；前端把 16,822 称为分析分母（SnapshotBoundaryPanel.tsx:66、SnapshotAnalytics.tsx:146）。实现：三份 aggregates 的 headline 新增 comments_total（len(comments)）、comments_governed_voc（brand_binding in GOVERNED_BRAND_BINDINGS 且 not is_bot）、comments_in_voc_metrics_basis='canonical_base_explicit_eligibility_only'；保留 comments_in_voc_metrics 原值与原语义；linked_comments 不改（service.ts:1136 断言其等于 manifest）。三处同值同序。前端标签由 L4 改为『Base 显式资格评论』并并列显示三个分母。
- **涉及文件**：
  - `src/reddit_voc/site_aggregates.py`
  - `src/reddit_voc/v3_base_public.py`
  - `scripts/validate_reddit_v3_base_public_projection.py`
  - `tests/test_site_aggregates.py`
- **验收**：
  - fixture true/false/null 三态评论 → comments_in_voc_metrics 仍等于 true 数，comments_governed_voc 只计 governed 且非 bot
  - comments_total == len(comments)
  - 三份 producer 输出的三个新字段完全一致（test_producers_agree_on_representative_corpus）
  - comments_in_voc_metrics_basis 字符串固定，不被本地化/改写
  - 任何页面不再把 16,822 单独标成『分析分母』（L4 验收）
- **测试**：
  - `tests/test_site_aggregates.py::test_headline_publishes_comment_populations`
  - `tests/test_site_aggregates.py::test_comment_population_conservation`
  - `tests/test_site_aggregates.py::test_producers_agree_on_representative_corpus`
- **完成定义**：pytest tests/test_site_aggregates.py -q 全绿；live aggregates 同时含 16,822 / 2,289 / 100,778 三个分母；离线 validator 整对象比较通过。

#### `L2-T15` reports 增加 drivers 输入块（L3-P6 的 L2 半边）

- **严重度**：P1｜**类型**：feature｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L3-T10`
- **描述**：Wave 2。背景：L3 的叙述句目前混用 live base 与 reports bundle 两套数据（MECE 将 L3-P6 的 producer 半边分给 L2）。实现：build_reports_bundle 每份 current 报告新增顶层 drivers {period_id, basis:'governed_voc_in_period', top_topic, top_community, top_product, top_evidence}，全部从 governed_vocs(posts,comments,report.period) 计算，与 RV-BR-01 同池同周期；top_topic/community 用 Counter；top_product 来自 product_bindings（可能为 null）；top_evidence 取最高严重度负向 VOC（post_id/comment_id/reason）；空时 null。report 根对象未被 exact-key 校验，additive 安全。L3-R6 消费该块替换客户端现算的 drivers。
- **涉及文件**：
  - `scripts/recompute_reports_bundle.py`
  - `tests/test_recompute_reports_bundle.py`
- **验收**：
  - fixture 2 个 topic、2 个 subreddit、1 个 product binding → top_topic/top_community 的 count 等于 governed 池中的计数
  - 无 governed VOC → drivers 存在但四个子对象为 null，period_id/basis 仍在
  - drivers 的统计与同一报告 RV-BR-01 的 sample_size 完全一致（同一 governed_vocs 调用）
  - drivers 不改变任何现有 report 键
- **测试**：
  - `tests/test_recompute_reports_bundle.py::test_drivers_block_matches_governed_period_vocs`
  - `tests/test_recompute_reports_bundle.py::test_drivers_block_is_empty_when_no_vocs`
- **完成定义**：pytest tests/test_recompute_reports_bundle.py -q 全绿；生成 bundle 的 drivers 与 RV-BR-01 同池；L3-R6 可只读该块生成叙述。

#### `L2-T16` 新增独立非 RV 指标 competitor_context_share（不再复用 RV-BR-05）

- **严重度**：P2｜**类型**：feature｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L4-T10`
- **描述**：Wave 5。背景：RV-BR-05 被撤回后，若仍要展示竞品语境，必须用独立指标名，不能借用注册表 id。实现：themes.geo.competitor_context_share {value, numerator, denominator, unit:'percent', status, reason_codes}；分子 = governed VOCs 中 mentioned_brand_ids ∩ competitor_brand_ids 非空（复用 _comp_brands，recompute_derivatives.py:364-368），分母 = len(in_quarter)；value=round(100*n/d,2)，d==0 时 value=null、status='unavailable'、reason='no_governed_voc_in_period'。绝不命名为 RV-BR-05；不改 reports。exact-key 变更，依赖 L4-R10。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_derivatives_metrics.py`
  - `tests/test_recompute_parity.py`
- **验收**：
  - Momcozy-only governed VOC → numerator==0、value==0.0、status=='available'（分母>0）
  - Spectra 提及 → numerator 至少 1；与 COMPETITOR_IDS 求交，非注册表品牌不计
  - 分母==0 → value is None、status=='unavailable'、reason_codes 非空
  - 字段名与 RV-BR-05 无任何关联；reports 指标列表不出现该 id
- **测试**：
  - `tests/test_recompute_derivatives_metrics.py::test_competitor_context_share_intersects_competitor_ids`
  - `tests/test_recompute_derivatives_metrics.py::test_competitor_context_share_reports_numerator_denominator`
- **完成定义**：pytest 新增用例与 frozen schema 测试全绿；与 L4-R10 同版本后 insights 可展示『竞品语境占比』且明确不是净情感差。

#### `L2-T17` GEO 增加独立竞品榜（competitor_rankings / competitor_mention_pairs）

- **严重度**：P2｜**类型**：feature｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L4-T10`
- **描述**：Wave 5。背景：GEO rankings 改回 topic id 后，品牌维度需要有独立字段，不能复用 rankings（否则两种实体空间再次混用）。实现：themes.geo 新增 competitor_rankings [{id:brand_id,label:display_name,count}] 与 competitor_mention_pairs:int；只对 post 计 post×brand pair；brand id 来自 mentioned_brand_ids ∩ COMPETITOR_IDS；排序 count desc, id asc；空时 competitor_rankings=[]、competitor_mention_pairs=0（需要消费端允许空数组，L4-R10）。不参与 comparison_decision_posts 守恒。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_derivatives_metrics.py`
  - `tests/test_recompute_parity.py`
- **验收**：
  - 两帖各提 2 个竞品 → competitor_mention_pairs==4，competitor_rankings 两行各 count==2
  - 同一帖重复提及同一品牌 → 该品牌只计 1
  - competitor_mention_pairs == sum(competitor_rankings.count)
  - comparison_decision_posts 与 rankings 不受影响
- **测试**：
  - `tests/test_recompute_derivatives_metrics.py::test_geo_competitor_rankings_use_canonical_ids`
  - `tests/test_recompute_derivatives_metrics.py::test_competitor_mention_pairs_are_pairs_not_posts`
- **完成定义**：pytest 全绿；与 L4-R10 同版本后 dashboard 竞品参照读 competitor_rankings，GEO 图只读 topic rankings。

#### `L2-T18` 同比：daily 7 日替代窗口 + 上年同周/同月基线

- **严重度**：P3｜**类型**：feature｜**工作量**：M｜**拓扑层**：0
- **描述**：Wave 5。根因：lean 引擎所有 YoY 固定 unavailable（recompute_reports_bundle.py:409-410,421-423,436-438），模板却承诺 7 日替代窗口（comparison_help 来自活模板，:479-480），前端早已支持 seven_day_proxy（reports.ts:899-937）。实现：新增 _same_period_last_year(grain, period)（daily 同日历日、weekly anchor-364d 所在 ISO 周、monthly 同月）；有值且>0 → 输出同形比较，comparison_basis='exact_period'、display_label='同比观测（覆盖未证明）'（必须含『观测』，reports.ts:916-922）、status='provisional'、reason 含 owner_attestation_missing_observed_same_profile；daily 上年同日不可得 → weekly current vs weekly last-year 生成 proxy，comparison_basis='seven_day_proxy'、display_label='同比（7日替代窗口）'、line_color='blue'、status='provisional'、reason_codes 同时含 owner_attestation_missing_observed_same_profile 与 exact_daily_yoy_unavailable_used_seven_day_proxy；weekly/monthly 不可得 → unavailable；_build_indicators 显式覆盖 comparison_help.text（proxy 可用则保留承诺，否则改为『同比未接入；仅展示环比观测值』）。
- **涉及文件**：
  - `scripts/recompute_reports_bundle.py`
  - `tests/test_recompute_reports_bundle.py`
- **验收**：
  - daily fixture 有上年同周数据 → year_over_year.comparison_basis=='seven_day_proxy'、display_label=='同比（7日替代窗口）'、status=='provisional'、两个 reason code 都在
  - weekly/monthly 无上年数据 → unavailable（display='—'/value=null/direction=null）
  - 78 个同比槽中不存在『文案承诺 7 日替代但值为 —』的组合：有承诺时必有 proxy 或 exact 值
  - proxy 载荷通过 reports.ts:899-937 的 observedOnly 与 proxyWindow 两段校验（用前端测试或等价的字段断言）
  - exact YoY 可用时 display_label 含『观测』，不被客户端拒绝
- **测试**：
  - `tests/test_recompute_reports_bundle.py::test_daily_yoy_emits_seven_day_proxy`
  - `tests/test_recompute_reports_bundle.py::test_proxy_payload_passes_client_contract_shape`
  - `tests/test_recompute_reports_bundle.py::test_yoy_unavailable_when_no_historic_data`
- **完成定义**：pytest tests/test_recompute_reports_bundle.py -q 全绿；生成的 bundle 中 daily YoY 为 provisional proxy（有历史时），对比文案与载荷一致；report 页面显示『同比（7日替代窗口）』且不再是 —。

#### `L2-T19` 183 天窗口首月桶只统计 >= start_date 的事件

- **严重度**：P3｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：Wave 5。根因：window_bucket 的 month 分支只看 months_back<=6（recompute_derivatives.py:381-384），把 2026-04-01..04-28 计入 total_vocs；start_date 却写 2026-04-29（:424）。实现（remedy B）：month 分支增加 lower=anchor-(days-1)；d<lower 时返回 None；保留 7 个自然月桶与 183 天 start_date。这样 KPI=桶合计，证据下钻与 KPI 对齐；首月柱是 2 天部分月（诚实代价）。不改前端 validator（quarterInsights.ts:463-472 仍期望 start_date=end-182）。若产品要求『近 7 个自然月』标签，走 remedy A（start_date=04-01 + L3/L4 文案），V2.0 不做。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_derivatives_metrics.py`
- **验收**：
  - anchor=2026-10-28 时 rolling_183_days.start_date=='2026-04-29'，仍 7 个桶
  - 2026-04-10 的 VOC 不计入；2026-04-29 的 VOC 计入 2026-04 桶
  - sum(buckets.total_vocs)==momcozy.total_vocs
  - rolling_7_days/rolling_30_days 行为不变（day grain 分支不动）
- **测试**：
  - `tests/test_recompute_derivatives_metrics.py::test_rolling_183_excludes_events_before_start_date`
  - `tests/test_recompute_derivatives_metrics.py::test_rolling_183_totals_equal_bucket_sums`
  - `tests/test_recompute_parity.py::test_window_totals_equal_bucket_sums`
- **完成定义**：pytest 全绿；live 183 天 KPI 等于桶合计，不再包含 4 月前 28 天。

#### `L2-T20` cohort 映射对齐 analyzer 实际 topic

- **严重度**：P3｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：Wave 5。根因：cohort_of_topic 使用 recommendation/service/scenario/fit 键（recompute_derivatives.py:566-575），analyzer 实际只产出 competitor_comparison/insurance/purchase_decision/customer_service/work_scenario/troubleshooting/product_evaluation/other（src/reddit_voc/analyzer.py:147-159），导致 customer_service/work_scenario/insurance/other 全部落入 scenario_adapter（live 320），service_support_seeker/recommendation_expression/fit_output_optimizer 结构性 0。实现：映射改为 product_evaluation→product_evaluator、troubleshooting→operations_troubleshooter、purchase_decision→purchase_decision、competitor_comparison→competitor_comparer、customer_service→service_support_seeker、work_scenario→scenario_adapter、insurance→scenario_adapter、other→scenario_adapter；COHORT_ORDER 与 8 行 key 不变；conservation 保持。recommendation_expression/fit_output_optimizer 无 topic 来源，继续为 0，并在 docstring 注明『结构性 0，不是观测结论』；显式 status/reason 留待 L4-R6 的后续版本。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_derivatives_metrics.py`
  - `tests/test_recompute_parity.py`
- **验收**：
  - 8 个 analyzer topic 各自映射到期望 cohort（表驱动断言）
  - customer_service 不再落入 scenario_adapter
  - sum(cohorts.assignment_count)==main_assignment_count 对随机 fixture 成立
  - COHORT_ORDER 与前端 quarterInsights.ts:268-277 完全一致（key 集合与顺序）
- **测试**：
  - `tests/test_recompute_derivatives_metrics.py::test_cohort_mapping_covers_all_analyzer_topics`
  - `tests/test_recompute_derivatives_metrics.py::test_customer_service_is_not_scenario_adapter`
  - `tests/test_recompute_parity.py::test_quarter_insights_matches_frozen_schema`
- **完成定义**：pytest 全绿；live scenario_adapter 下降、service_support_seeker 上升且合计不变；前端 cohort 顺序校验不破。

### L3 — L3 — 结论生成层（Conclusion Generation）

#### `L3-T01` 前端两形态接受窗口：conclusions 校验器与可选键容忍

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：0
- **描述**：新增 conclusions.ts：十字段记录类型、ConclusionIndex、validateConclusions、optionalConclusions、递归禁键/URL 扫描、mustGet fail-closed。改 quarterInsights.ts:542-546 的 exactKeys 为 exactKeysAmong（11 键旧形态 / 12 键含 conclusions），schema_version 同时接受 v1/v2；改 brandHealth.ts:92-100 的 DATA_KEYS/MANIFEST_KEYS 为必需+可选（conclusions、generated_at_utc）；给 reports.ts:725-761 的 V3CurrentReport 增加可选 dataset_version/generated_at_utc/conclusions。本票只放宽接收，不产生任何数据；旧 bundle 行为完全不变。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/conclusions.ts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/quarterInsights.ts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/brandHealth.ts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reports.ts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/conclusions.test.ts`
- **验收**：
  - 现有 public 数据（无 conclusions）通过全部校验，npm test 全绿。
  - 合成的 12 键 quarter-insights 数据（含 1 条合法 conclusion）通过校验；11 键旧数据也通过。
  - 重复 conclusion_id、dataset_version 不一致、空数组、未知 gate.status、inputs 含禁键或 URL，五类输入分别被拒绝且错误信息可定位。
  - brand-health data 含 generated_at_utc + conclusions 时通过；manifest 含可选 generated_at_utc 时通过。
  - V3CurrentReport 类型接受三个可选字段，validateV3CurrentReport 对旧 bundle 行为不变。
  - 没有修改任何 producer 文件，没有修改 contract_extensions 断言。
- **测试**：
  - `src/features/redditSnapshot/__tests__/conclusions.test.ts::rejects duplicate conclusion ids`
  - `src/features/redditSnapshot/__tests__/conclusions.test.ts::rejects a dataset_version mismatch`
  - `src/features/redditSnapshot/__tests__/conclusions.test.ts::accepts a legacy payload without conclusions`
  - `src/features/redditSnapshot/__tests__/conclusions.test.ts::rejects an empty conclusions array`
  - `src/features/redditSnapshot/__tests__/conclusions.test.ts::rejects an unknown gate status`
  - `src/features/redditSnapshot/__tests__/conclusions.test.ts::rejects forbidden keys inside conclusion inputs`
  - `src/features/redditSnapshot/__tests__/conclusions.test.ts::rejects a record whose sentence does not match its dataset version`
- **完成定义**：npm test 全绿且旧数据零行为变化；conclusions.test.ts 七个用例全绿；diff 仅含上述五个前端文件。

#### `L3-T02` conclusions.py：模板注册表、样本/语义/占位符门禁与回放渲染

- **严重度**：P1｜**类型**：feature｜**工作量**：L｜**拓扑层**：0
- **描述**：新建纯函数库：常量（CONCLUSION_SCHEMA、GATE_POLICY_VERSION、GATE_LIMITS、REASON_CODES、PLACEHOLDER_IDS）、TEMPLATES、TEMPLATE_CONTRACT、render_conclusion、evaluate_gate、build_conclusion、validate_conclusions、is_placeholder、conclusions_enabled，以及三个 build_*_conclusions 构建器骨架。build_conclusion 按「缺输入 → evidence_kind_mismatch → metric_semantics_mismatch → placeholder_leader → 样本门禁 → advice 抑制」顺序选模板；inputs 内嵌 gate 副本保证 render(template_id, inputs)==sentence。本票不接 producer，仓库行为不变。
- **涉及文件**：
  - `src/reddit_voc/conclusions.py`
  - `tests/test_conclusions.py`
  - `tests/fixtures/conclusions/quarter_insights_fit_flip.json`
  - `tests/fixtures/conclusions/monthly_2026_09_tiny.json`
  - `tests/fixtures/conclusions/zero_drivers.json`
  - `tests/fixtures/conclusions/brand_health_tied.json`
  - `tests/fixtures/conclusions/brand_health_missing.json`
- **验收**：
  - 对全部 fixture 的每条结论执行 render_conclusion(template_id, inputs) == sentence，100% 通过。
  - 每条记录恰好十个键；inputs.gate 与顶层 gate 深相等；禁键/URL 扫描拒绝非法输入。
  - evaluate_gate 在 n_vocs=0 时返回 zero_observed；claim 在 30/10 边界两侧分别 passed/insufficient；advice 在 100/10/14 边界两侧正确。
  - placeholder（unspecified / none_observed）触发 placeholder_leader 且句子不含占位符字符串。
  - advice 且 gate!=passed 时模板切到 core.advice_suppressed.v1，句子包含样本量 n 与阈值。
  - 固定 generated_at_utc 下同一输入两次构建字节完全相同。
- **测试**：
  - `tests/test_conclusions.py::test_template_render_round_trip_matches_sentence`
  - `tests/test_conclusions.py::test_conclusion_records_have_exact_keys_and_no_forbidden_keys`
  - `tests/test_conclusions.py::test_conclusion_ids_unique_and_versioned_per_dataset`
  - `tests/test_conclusions.py::test_gate_thresholds_are_frozen_in_policy_version`
  - `tests/test_conclusions.py::test_placeholder_leader_is_insufficient`
  - `tests/test_conclusions.py::test_zero_observed_never_emits_directive`
  - `tests/test_conclusions.py::test_low_sample_monthly_suppresses_advice`
  - `tests/test_conclusions.py::test_competitor_gap_semantics_mismatch_is_insufficient`
  - `tests/test_conclusions.py::test_product_family_claim_requires_product_family_evidence_kind`
  - `tests/test_conclusions.py::test_missing_brand_health_emits_unavailable_sentence`
  - `tests/test_conclusions.py::test_brand_health_dimension_tie_is_not_a_spread_claim`
  - `tests/test_conclusions.py::test_conclusions_are_deterministic_for_fixed_generated_at`
- **完成定义**：tests/test_conclusions.py 全绿；模块无 IO/全局状态；import 路径与 reddit_voc.brands 一致（run_daily_t1_pipeline.py:29 插入 src 后可直接导入）。

#### `L3-T03` quarter_insights 结论生成：29 条槽位、排名派生、占位符与自动化披露

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：1
- **依赖**：`L3-T01`, `L3-T02`
- **描述**：在 recompute_quarter_insights（recompute_derivatives.py:333-661）返回前注入 conclusions：29 条槽位（pain 5、reputation 5、new_product 6、geo 5、dashboard 8），数据取自已算好的 themes/counts/dashboard_windows 与 in_quarter。qi.pain.leader.v2 由 rankings[0]/[1] 现算 gap 与 tied，不引用任何写死主题；unspecified/none_observed 触发 placeholder_leader；new_product.family/spu 因 producer 只有 topic 证据而自动 evidence_kind_mismatch；自动化披露按 detection_status（populated|legacy_only|not_populated）分支。新增 generated_at_utc/run_id 关键字参数，run_recompute 传 t0 与 run_id；ECHO_AGENT_CONCLUSIONS=off 时不写该键。同步更新 test_recompute_parity.py:175-178 的精确键集合。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_parity.py`
  - `tests/test_conclusions.py`
- **验收**：
  - recompute_quarter_insights 返回对象含 conclusions，且 29 个必需槽位齐全、id 唯一、前缀 qi.。
  - fit_comfort 反超 fixture：句子首位为 fit_comfort，不含「优先级高于适配舒适度」，不含旧第 2/3 名常量。
  - leader 为 unspecified/none_observed 时 gate.reason_codes 含 placeholder_leader，句子不含 Unspecified/None Observed。
  - new_product.family/spu 的 gate.reason_codes 含 evidence_kind_mismatch；页面上不会出现「居产品家族首位」。
  - 7 月本地 fixture（113 条 is_bot=true）下 detection_status=legacy_only；新建行为 not_populated；两种句子都不做品牌机器人归因。
  - 固定 generated_at_utc 与 run_id 时 quarter-insights.json 字节稳定；关掉开关后只有 conclusions 键消失。
  - tests/test_recompute_parity.py::test_quarter_insights_matches_frozen_schema 更新后通过。
- **测试**：
  - `tests/test_recompute_parity.py::test_quarter_insights_matches_frozen_schema`
  - `tests/test_conclusions.py::test_quarter_insights_conclusions_cover_every_required_slot`
  - `tests/test_conclusions.py::test_pain_leader_gap_derives_from_ranking_not_constants`
  - `tests/test_conclusions.py::test_placeholder_leader_is_insufficient`
  - `tests/test_conclusions.py::test_quarter_actions_are_gated_when_sample_below_threshold`
  - `tests/test_conclusions.py::test_automation_not_populated_is_disclosed`
  - `tests/test_conclusions.py::test_conclusions_are_deterministic_for_fixed_generated_at`
- **完成定义**：上述 pytest 全绿；step3_5 与 pointer 逻辑零改动；profiles 的 SHA 绑定仍由既有 step3_5 更新。

#### `L3-T04` brand_health 结论生成：generated_at_utc、5 条槽位与四维分档

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：1
- **依赖**：`L3-T01`, `L3-T02`
- **描述**：recompute_brand_health（:716-842）增加必填关键字 generated_at_utc、derived_from_run_id；data 增加 generated_at_utc 与 conclusions（bh.overall/bh.spread/bh.strongest/bh.weakest/bh.sample）。spread 用已发布两位小数分数算 max-min，band=wide(>=15)/narrow，tied=差值为 0；overall=unavailable 时输出不可用句；sample 来自投影的 n_vocs/n_distinct_posts（period_days=null）。manifest 本轮不加字段。同步更新 test_recompute_parity.py:126-132 的调用。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `tests/test_recompute_parity.py`
  - `tests/test_conclusions.py`
- **验收**：
  - data 含 generated_at_utc（RFC3339，+00:00/Z）与 5 条 conclusions；dataset_version 等于 projection_id；generated_at_utc 与 data 值一致。
  - 四维全等 fixture：band=narrow、tied=true，句子不点名优势/短板。
  - normal fixture：wide/narrow 句子分别正确，strongest/weakest 与分数来自输入而非前端排序。
  - overall.score=null 时 bh.overall 为不可用句，含原因码，不出现空的「品牌健康度为」半句。
  - 固定 generated_at_utc 下 canonical_json_document(data) 字节稳定；manifest.files sha/bytes 与写入字节一致。
  - tests/test_recompute_parity.py::test_brand_health_projection_is_self_consistent 更新后通过。
- **测试**：
  - `tests/test_recompute_parity.py::test_brand_health_projection_is_self_consistent`
  - `tests/test_conclusions.py::test_brand_health_dimension_tie_is_not_a_spread_claim`
  - `tests/test_conclusions.py::test_missing_brand_health_emits_unavailable_sentence`
  - `tests/test_conclusions.py::test_quarter_insights_conclusions_cover_every_required_slot`
  - `tests/test_conclusions.py::test_conclusions_are_deterministic_for_fixed_generated_at`
- **完成定义**：上述 pytest 全绿；canonical 字节/哈希契约保持不变；manifest 键集合不变。

#### `L3-T05` reports 结论生成：report 版本字段、14/15 条槽位与语义门禁

- **严重度**：P1｜**类型**：feature｜**工作量**：L｜**拓扑层**：1
- **依赖**：`L3-T01`, `L3-T02`
- **描述**：build_reports_bundle（recompute_reports_bundle.py:461-658）增加必填 generated_at_utc、run_id；每个 current report 增加 dataset_version、generated_at_utc、conclusions。结论覆盖 signal（brand_health/observation/negative_rate/net_sentiment/competitor_gap/acceleration）、driver（topic/product/community/evidence 或 driver.unavailable）、impact（observation/negative_rate/competitor_gap/sentiment_context）、action（daily 3、weekly/monthly 4）。RV-BR-05 声明 metric_semantics_id='rv-br-05.mention_coverage.v1'，竞品净情感差模板要求 'rv-br-05.net_sentiment_gap.v1' → 必然 metric_semantics_mismatch；同比固定 unavailable → comparison_not_supported；monthly advice 用 is_action=True（100/10/14）。同步更新 scripts/build_reports_bundle.py:62-72 的调用。
- **涉及文件**：
  - `scripts/recompute_reports_bundle.py`
  - `scripts/build_reports_bundle.py`
  - `tests/test_reports_bundle_conclusions.py`
  - `tests/test_conclusions.py`
- **验收**：
  - 三个 current report 都含 dataset_version/generated_at_utc/conclusions，槽位齐全、id 前缀 rpt.<grain>.。
  - 每条 sentence 可回放；结论 dataset_version 等于 build_reports_bundle 的 dataset_version。
  - 竞品净情感差两个槽 gate.reason_codes 含 metric_semantics_mismatch，句子不含「净情感差」字样。
  - 同比不可用的 bundle 中 impact.* 句含 comparison_not_supported，不出现方向判断。
  - 21 条治理 VOC 的 monthy fixture：action.* 全部为 core.advice_suppressed.v1 输出，含「样本不足（n=21 < 100）」。
  - 无 drivers 块时只输出 driver.unavailable，不读 live base。
  - 固定 generated_at_utc 时 manifest/validation-receipt 字节稳定；contract_extensions 断言不变。
- **测试**：
  - `tests/test_reports_bundle_conclusions.py::test_report_conclusions_are_present_for_all_grains`
  - `tests/test_reports_bundle_conclusions.py::test_report_conclusion_sentences_replay_from_inputs`
  - `tests/test_reports_bundle_conclusions.py::test_report_generated_at_is_byte_stable`
  - `tests/test_reports_bundle_conclusions.py::test_report_driver_conclusions_unavailable_without_drivers_block`
  - `tests/test_conclusions.py::test_low_sample_monthly_suppresses_advice`
  - `tests/test_conclusions.py::test_zero_observed_never_emits_directive`
  - `tests/test_conclusions.py::test_competitor_gap_semantics_mismatch_is_insufficient`
- **完成定义**：上述 pytest 全绿；reports.ts:1685 的 contract_extensions 精确数组零改动；bundle lineage/manifest 自洽。

#### `L3-T06` 洞察页改为按 conclusion_id 查表：summary / 解释 / 行动

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：2
- **依赖**：`L3-T01`, `L3-T03`
- **描述**：buildThemeViewModel（SnapshotInsightsV3.tsx:93-231）不再用 rankings 现拼句子：四个主题的 summary、businessExplanation 的业务判断、actions 全部改为按 id 从 quarterInsights.conclusions 查表并渲染 ConclusionSentence。删除 :110/:123-124/:129/:176/:191/:220 的写死主题名与判断；静态方法学/边界文案保留。conclusions 缺失时走 legacy 分支（临时）。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/components/insights/SnapshotInsightsV3.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/components/insights/__tests__/SnapshotInsightsV3.test.tsx`
- **验收**：
  - 四主题的 summary 与 actions DOM 文本逐字等于 dataset sentence。
  - fit_comfort 反超 fixture：摘要首位为 fit_comfort，不出现「优先级高于适配舒适度」，同卡不再出现旧第 2/3 名常量。
  - leader 为 placeholder 时渲染不可用句与原因码，不渲染 Unspecified/None Observed。
  - evidence_kind=topic 时页面不含「居产品家族首位」；静态方法学文案仍在。
  - conclusions 缺失的旧数据集仍渲染 legacy 文案，页面不报错。
- **测试**：
  - `src/components/insights/__tests__/SnapshotInsightsV3.test.tsx::renders theme sentences verbatim from quarter conclusions`
  - `src/components/insights/__tests__/SnapshotInsightsV3.test.tsx::ranking flip keeps leader and second labels consistent`
  - `src/components/insights/__tests__/SnapshotInsightsV3.test.tsx::unavailable leader renders the reason code`
  - `src/components/insights/__tests__/SnapshotInsightsV3.test.tsx::topic evidence never claims 产品家族首位`
- **完成定义**：上述 vitest 全绿且既有 SnapshotInsightsV3 测试不回归；diff 仅含两个文件。

#### `L3-T07` 概览页：四个决策入口与优先行动改为结论查表

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：2
- **依赖**：`L3-T01`, `L3-T03`
- **描述**：DashboardStoryMap（SnapshotDashboard.tsx:129-171）四条 description 与三个优先行动标题（:565/:570/:575）改为从 quarterInsights.conclusions 按 qi.dashboard.* id 查表；删除 :145/:152/:159/:166 的写死判断与 topDriver/topProduct/topCompetitor 直接插值。零计数与 placeholder 由服务端门禁决定句子；页面只渲染 sentence。conclusions 缺失时走 legacy 分支。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotDashboardV3.test.tsx`
- **验收**：
  - 四条入口 description 与三条行动 DOM 文本逐字等于 dataset sentence。
  - high_severity_vocs=0 或 comparison_decision_posts=0 fixture：页面无「先复核 0 条」「覆盖 0 条」等祈使句，显示零值不可用句。
  - top_competitor= none_observed fixture：页面不出现 None Observed 字样。
  - 品牌健康卡不受影响（仍用 brand_health 索引），同页两索引互不串用。
  - 旧数据集（无 conclusions）仍渲染 legacy 文案。
- **测试**：
  - `src/pages/__tests__/SnapshotDashboardV3.test.tsx::renders four decision entries from quarter conclusions`
  - `src/pages/__tests__/SnapshotDashboardV3.test.tsx::zero drivers render no imperative`
  - `src/pages/__tests__/SnapshotDashboardV3.test.tsx::placeholder competitor label is not rendered`
- **完成定义**：上述 vitest 全绿且既有 SnapshotDashboardV3 测试不回归；diff 仅含两个文件。

#### `L3-T08` 品牌健康卡：删除 isMomcozyPost 估算，改渲染 bh.* 结论

- **严重度**：P2｜**类型**：feature｜**工作量**：S｜**拓扑层**：2
- **依赖**：`L3-T01`, `L3-T04`
- **描述**：BrandHealthSnapshotCard.tsx:94 的「四维差异明显」、:73-74 的 strongest/weakest 排序、:76-78 的 sampleSize 文案全部改为查 bh.overall/bh.spread/bh.strongest/bh.weakest/bh.sample。删除 SnapshotDashboard.tsx:516 的 sampleSize={snapshot.posts.filter(isMomcozyPost).length} 与组件的 sampleSize prop；样本句只来自投影。四维并列时使用 tied 句；投影不可用时渲染带原因码的不可用句。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/BrandHealthSnapshotCard.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts`
- **验收**：
  - normal fixture：总体判断句、优势、短板、样本句逐字等于 dataset sentence。
  - 四维全等 fixture：不点名任何优势/短板，使用 tied 句。
  - 投影缺失 fixture：出现「不可用 + 原因码」，不出现空的「品牌健康度为」半句，也不出现客户端估算数字。
  - 页面上不再出现 isMomcozyPost 估算的样本数（例如 2,280）。
  - 旧 brand-health 数据（无 conclusions）仍渲染 legacy 文案。
- **测试**：
  - `src/features/redditSnapshot/__tests__/brandHealth.test.ts::renders the spread band sentence from bh.spread inputs`
  - `src/features/redditSnapshot/__tests__/brandHealth.test.ts::tied dimensions never name a strongest dimension`
  - `src/features/redditSnapshot/__tests__/brandHealth.test.ts::missing projection renders an unavailable sentence with a reason code`
  - `src/features/redditSnapshot/__tests__/brandHealth.test.ts::sample sentence comes from the projection not the client estimate`
- **完成定义**：上述 vitest 全绿；brandHealth.test.ts 既有 SHA 篡改用例不回归；diff 仅含三个文件。

#### `L3-T09` 报告叙事路径可用性化：删除 sparkline.direction 回退与恒真同比 token

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：新增 reportNarrative.ts::buildNarrativePath：path token 由 report 内指标的 comparisons 状态派生，year_over_year 仅在有 available 时出现且 label='同比'，否则 label='上期观测差' 并带 reason_codes。directionImpact（OperationalReportSupplement.tsx:150-157）只接受 comparisons.period_over_period.direction 且 status ∈ {available, provisional}，删除 :154 的 sparkline.direction 回退。STORY_CONFIG.path 改为 fallback 基础模板，渲染时由 buildNarrativePath 覆盖。同步更新 SnapshotReportsV3.test.tsx:401/:419 的固定 path 断言与 :412 的「战略建议」断言。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/components/reports/OperationalReportSupplement.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reportNarrative.ts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reportNarrative.test.ts`
  - `ref/UI/momcozy-reddit-workbench/src/components/reports/__tests__/SnapshotReportsV3.test.tsx`
- **验收**：
  - 同比全不可用的 bundle：周报/月报 path 不含「同比」token，显示「上期观测差」。
  - sparkline.direction='up' 但 period_over_period.status='unavailable' 的 fixture：页面不出现由 sparkline 生成的方向判断。
  - period_over_period.status='provisional' 时仍显示「环比（观测口径）」。
  - 既有 path 断言改为按 fixture 可用性驱动后通过；不再依赖固定字符串。
- **测试**：
  - `src/features/redditSnapshot/__tests__/reportNarrative.test.ts::all_year_over_year_unavailable_drops_yoy_token`
  - `src/features/redditSnapshot/__tests__/reportNarrative.test.ts::daily_sparkline_direction_never_creates_a_direction_claim`
  - `src/features/redditSnapshot/__tests__/reportNarrative.test.ts::provisional_period_over_period_keeps_observed_label`
  - `src/components/reports/__tests__/SnapshotReportsV3.test.tsx::renders narrative facts from report conclusions`
- **完成定义**：上述 vitest 全绿；SnapshotReportsV3.test.tsx 既有用例（除已改断言外）不回归；diff 仅含四个文件。

#### `L3-T10` 报告叙事全部改读 report.conclusions：删除 live base 驱动诊断

- **严重度**：P1｜**类型**：feature｜**工作量**：L｜**拓扑层**：2
- **依赖**：`L3-T01`, `L3-T05`, `L3-T09`
- **描述**：OperationalReportSupplement 的 signalFacts/driverFacts/impactFacts/actionFacts（:218-284）全部改为按 rpt.<grain>.* id 查 report.conclusions 并渲染 ConclusionSentence；删除 :176 与 :182-188 的 derivePeriodMetrics 叙事调用、:214-236 的 topTopic/topProduct/topCommunity/topEvidence 现算。驱动明细只在 report.drivers 存在时渲染，否则渲染 driver.unavailable；证据列表用 report.drivers.evidence_post_ids 与 base snapshot join（仅证据渲染）。RealReportView.tsx:741 改为无条件渲染 supplement（snapshot 作为可选证据源传入）。情绪饼图/图表块可继续使用 context（明确标注为 L4/L2 迁移债务），但其输出不得进入任何句子。conclusions 缺失时走 legacy 分支。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/components/reports/OperationalReportSupplement.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/components/reports/RealReportView.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/components/reports/__tests__/SnapshotReportsV3.test.tsx`
- **验收**：
  - 报告页 signal/driver/impact/action 的每一句 DOM 文本逐字等于 report.conclusions 的 sentence。
  - 同一 report 用两份不同的 base snapshot props 渲染，叙事文本完全相同（证明叙事不再读 live base）。
  - 21 条治理 VOC 的月报 fixture：页面无任何 advice 文本，出现「样本不足（n=21 < 100）」提示与分母。
  - high_severity_vocs=0 / comparison_decision_posts=0 时页面无祈使句。
  - report 无 drivers 块时显示 driver.unavailable 与原因码，不回退现算。
  - snapshot 加载失败时报告叙事仍完整渲染（RealReportView 不再以 snapshot 为渲染前提）。
- **测试**：
  - `src/components/reports/__tests__/SnapshotReportsV3.test.tsx::renders narrative facts from report conclusions`
  - `src/components/reports/__tests__/SnapshotReportsV3.test.tsx::monthly 21-VOC bundle renders the sample-insufficient notice and no advice`
  - `src/components/reports/__tests__/SnapshotReportsV3.test.tsx::zero high-severity count renders no imperative`
  - `src/components/reports/__tests__/SnapshotReportsV3.test.tsx::narrative text is unchanged when base snapshot props change`
- **完成定义**：上述 vitest 全绿；报告页不再有任何句子由 context.* 生成；diff 仅含三个文件。

#### `L3-T11` 语义门禁跨页断言：净情感差、产品家族/SPU、自动化披露

- **严重度**：P1｜**类型**：test｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L3-T03`, `L3-T04`, `L3-T05`, `L3-T06`, `L3-T07`, `L3-T10`
- **描述**：新增跨页测试：用三份带门禁结论的合成数据集分别渲染概览、洞察、报告（复用各页现有测试 harness 的 fixture 构造方式），断言全站不出现被门禁禁止的措辞，且不可用句包含原因码。本票只加测试，不改生产代码；若断言失败，说明上游 producer 或组件接线有缺陷，应回到对应 ticket 修复。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/crossPageConclusionSemantics.test.tsx`
- **验收**：
  - RV-BR-05 语义为 mention_coverage 时，三页 document.body 均不含「净情感差」。
  - new_product evidence_kind=topic 时，三页均不含「产品家族首位」「精确 SPU 首位」。
  - detection_status=not_populated/legacy_only 时，页面渲染「自动化评论识别未接入每日合并链路」并带原因码。
  - 上述断言在任何一页失败时，测试信息指出页面与违禁短语。
- **测试**：
  - `src/features/redditSnapshot/__tests__/crossPageConclusionSemantics.test.tsx::no page renders 净情感差 when semantics is mention_coverage`
  - `src/features/redditSnapshot/__tests__/crossPageConclusionSemantics.test.tsx::no page renders 产品家族首位 when evidence_kind is topic`
  - `src/features/redditSnapshot/__tests__/crossPageConclusionSemantics.test.tsx::automation disclosure renders the not-populated notice`
- **完成定义**：三个用例全绿；无生产代码改动；测试可独立运行。

#### `L3-T12` 全站结论同一性与禁语扫描：Playwright + vitest

- **严重度**：P1｜**类型**：test｜**工作量**：M｜**拓扑层**：3
- **依赖**：`L3-T06`, `L3-T07`, `L3-T08`, `L3-T10`
- **描述**：扩展 scripts/playwright_daily_release_e2e.js：新增 conclusion_identity_scan（遍历三页 [data-conclusion-id]，按 (dataset-version,id) 分组断言唯一文本，并与数据集 conclusions[] 的 sentence 全等）与 forbidden_phrase_scan（禁语与零值祈使句）。vitest 增加同一数据集两个索引的 sentence 字节相同用例（跨页同一性的单元级证明）。
- **涉及文件**：
  - `scripts/playwright_daily_release_e2e.js`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/conclusions.test.ts`
- **验收**：
  - 三页每个 [data-conclusion-id] 的 textContent 等于其 dataset-version 对应数据集的 sentence。
  - 同一 (dataset-version, conclusion_id) 在概览与洞察出现的文本唯一。
  - 三页 body.innerText 不含 净情感差 / 产品家族首位 / 精确 SPU 首位 / Unspecified / None Observed / 复核 0 条 / 覆盖 0 条。
  - 扫描报告列出违例页面、id 与文本，便于定位。
- **测试**：
  - `scripts/playwright_daily_release_e2e.js::conclusion_identity_scan`
  - `scripts/playwright_daily_release_e2e.js::forbidden_phrase_scan`
  - `src/features/redditSnapshot/__tests__/conclusions.test.ts::same dataset version yields byte-identical sentences across pages`
- **完成定义**：Playwright 脚本在 staging 与生产只读运行均通过；vitest 用例全绿；脚本不写任何文件到生产。

#### `L3-T13` 删除 legacy 文案分支：结论成为唯一真相

- **严重度**：P3｜**类型**：refactor｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L3-T06`, `L3-T07`, `L3-T08`, `L3-T10`
- **描述**：在 conclusions 已在生产稳定运行一个发布周期后，删除四个组件里的 legacy 文案分支与硬编码判断句，组件在 conclusions 缺失时渲染显式「结论数据未发布」错误态而不是旧句子。新增源码级测试扫描四个文件，断言禁语（优先级高于适配舒适度、四维差异明显、居产品家族首位、构成问题库、净情感差等）不再出现。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/components/insights/SnapshotInsightsV3.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/BrandHealthSnapshotCard.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/components/reports/OperationalReportSupplement.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/noHardcodedJudgements.test.ts`
- **验收**：
  - 四个组件不再包含任何业务判断句字面量；grep 级测试通过。
  - conclusions 缺失时页面显示「结论数据未发布」错误态，不渲染旧文案。
  - 既有 vitest 全绿；SnapshotInsightsV3/SnapshotDashboard/SnapshotReports 的快照/文本断言更新为新错误态。
  - npm run build 通过。
- **测试**：
  - `src/features/redditSnapshot/__tests__/noHardcodedJudgements.test.ts::no banned judgement phrase remains in the four conclusion components`
  - `src/components/insights/__tests__/SnapshotInsightsV3.test.tsx::renders theme sentences verbatim from quarter conclusions`
  - `src/components/reports/__tests__/SnapshotReportsV3.test.tsx::renders narrative facts from report conclusions`
- **完成定义**：源码扫描测试与全部 vitest 全绿；四个组件在无结论时 fail closed；生产已连续 7 天使用数据化结论。

### L4 — L4 — 交付与消费层 (Delivery & Consumption)

#### `L4-T01` release.ts：指针 5 分钟 TTL 重验证、并发合并、拒绝不缓存、refreshCurrentRelease

- **严重度**：P0｜**类型**：feature｜**工作量**：M｜**拓扑层**：0
- **描述**：把 release.ts:72 的 releasePromise 单例改为 cachedRelease + loadedAtMs + inFlight。loadCurrentRelease 保持非 async（release.test.ts:131 要求同 tick 两次调用 Promise 引用相等）：命中 TTL 返回缓存；并发返回同一 inFlight；重取成功后若 generated_at_utc 与 datasets 全等则返回旧对象（身份稳定）；重取失败且有缓存则返回缓存（last-known-good），无缓存则抛出且不缓存。fetch 继续用 cache:'no-cache'（release.ts:366），refresh 用 'reload'。新增 releaseDatasetGenerationKey（数据集 manifest SHA）与 releaseGenerationKey（generated_at_utc + base SHA）。resetCurrentReleaseCacheForTests 清三者。不改 validateCurrentRelease、fetchVerifiedReleaseManifest 的任何校验。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/release.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/release.test.ts`
- **验收**：
  - release.test.ts 既有 7 个用例全绿，尤其 'deduplicates concurrent pointer requests at module scope' 仍断言 fetch 只调用 1 次且两个 promise 引用相等
  - TTL 过期后再次调用会重新请求 current-release.json；内容未变时返回的对象与旧对象 ===（身份稳定）
  - 首次加载失败后再次调用会重新发起请求（拒绝未被缓存），第二次成功可返回数据
  - refreshCurrentRelease() 绕过 TTL 并返回新的 generated_at_utc；失败时向调用方抛错而不是返回旧值
- **测试**：
  - `src/features/redditSnapshot/__tests__/release.test.ts > scoped pointer revalidation > refetches the pointer after the TTL and keeps the same release object when the generation is unchanged`
  - `src/features/redditSnapshot/__tests__/release.test.ts > scoped pointer revalidation > does not cache a rejected pointer load and retries on the next call`
  - `src/features/redditSnapshot/__tests__/release.test.ts > scoped pointer revalidation > refreshCurrentRelease bypasses the TTL and returns the new generated_at_utc`
  - `src/features/redditSnapshot/__tests__/release.test.ts > current Reddit VOC release pointer > deduplicates concurrent pointer requests at module scope（回归）`
- **完成定义**：npm test -- release.test.ts 全绿；npm run build 通过；release.ts 不再有任何 `??=` 缓存 promise；无 JSON 契约变化。

#### `L4-T02` releaseKeyedCache 模块 + service.ts 四个缓存改为发布键（含 summary 漏 reset 修复）

- **严重度**：P0｜**类型**：feature｜**工作量**：M｜**拓扑层**：1
- **依赖**：`L4-T01`
- **描述**：新建 releaseKeyedCache.ts（接口见契约 C1）。service.ts:103-106 的 corePromise/summaryPromise/commentsPromise/insightsPromise 改为 ReleaseKeyedCache：summary 键 `${baseSha}:${release.freshness?.data_as_of_utc ?? ''}`，core 键 baseSha，comments 键 baseSha，legacy insights 键 insights SHA。loadSummaryUncached(release) 与 loadCoreUncached(summary) 改为接收已解析对象，保证同一代；loadRedditSnapshot() 先取 release，再取 summary，再取 core。resetSnapshotCacheForTests（:1591-1595）清四个缓存并调用 resetCurrentReleaseCacheForTests。readThroughReleaseCache 在 rejection 时清 key/promise（仅当仍是同一 promise）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/releaseKeyedCache.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/service.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/service.test.ts`
- **验收**：
  - 一个数据集 promise 首次拒绝后，第二次调用会重新 fetch 并成功（不再永久错误页）
  - 指针 base manifest SHA 变化后，summary 与 core 同时重建；SHA 未变但 data_as_of 前进时只重建 summary（aggregates 重取、posts 不重取）
  - resetSnapshotCacheForTests 之后再次加载会重新请求指针与全部四类数据（summary 不再泄漏跨用例）
  - 既有 service.test.ts 用例全绿
- **测试**：
  - `src/features/redditSnapshot/__tests__/service.test.ts > release-keyed dataset cache > evicts a rejected dataset promise so the next call retries`
  - `src/features/redditSnapshot/__tests__/service.test.ts > release-keyed dataset cache > rebuilds base caches when the pointer base manifest SHA changes`
  - `src/features/redditSnapshot/__tests__/service.test.ts > release-keyed dataset cache > rebuilds only the summary when data_as_of advances without a base byte change`
  - `src/features/redditSnapshot/__tests__/service.test.ts > release-keyed dataset cache > resets summary, core, comments and insights together for tests`
- **完成定义**：service.test.ts 全绿；`grep -n '??=' service.ts` 在四个缓存处无命中；reset 覆盖 summary；npm run build 通过。

#### `L4-T03` brandHealth / quarterInsights / casebook 值缓存改为发布键缓存

- **严重度**：P0｜**类型**：feature｜**工作量**：M｜**拓扑层**：2
- **依赖**：`L4-T02`
- **描述**：三个 loader 的模块级值缓存（brandHealth.ts:114/267/298、quarterInsights.ts:283/689/720、casebook.ts:145/279/303）改为 ReleaseKeyedCache<{data,manifest}>，键为各自 release.datasets[key].public_manifest_sha256。显式传 options.basePath 或 options.expectedManifestSha256 时绕过缓存（测试兼容）。reset*ForTests 同时 resetReleaseKeyedCache。校验逻辑、fetchText、lineage 断言一概不动。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/brandHealth.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/quarterInsights.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/casebook.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/quarterInsights.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/casebook.test.ts`
- **验收**：
  - 绑定的 manifest SHA 未变时第二次调用不产生新 fetch（缓存命中）
  - 绑定的 manifest SHA 变化后重新 fetch manifest 与 data，并返回新 data
  - 显式 options 调用不读也不写生产缓存
  - 三个既有测试文件全绿
- **测试**：
  - `src/features/redditSnapshot/__tests__/brandHealth.test.ts > release-keyed auxiliary cache > reloads the projection after the brand_health binding SHA changes`
  - `src/features/redditSnapshot/__tests__/quarterInsights.test.ts > release-keyed auxiliary cache > reuses the quarter projection within one manifest SHA`
  - `src/features/redditSnapshot/__tests__/casebook.test.ts > release-keyed auxiliary cache > does not touch the production cache when explicit fixture options are passed`
- **完成定义**：三个测试文件全绿；三个文件不再有 `let *_Cache: ... | null` 的值缓存；npm run build 通过。

#### `L4-T04` personas / reports / insights 缓存改为发布键；报表与洞察刷新按钮先刷新指针

- **严重度**：P0｜**类型**：feature｜**工作量**：M｜**拓扑层**：2
- **依赖**：`L4-T02`
- **描述**：personas.ts:217/764、reports.ts:802/2197、insights.ts:22/39/44 的 promise 缓存改为 ReleaseKeyedCache，键为各自 manifest SHA。reloadRedditReports（reports.ts:2201-2204）与 reloadRedditInsights（insights.ts:44-46）改为：await refreshCurrentRelease() → resetReleaseKeyedCache(cache) → 以新 release 调 load*Uncached(release, true)；reports 同时清 historicalReportPromises。loadReportsUncached/loadV3ReportsUncached/loadInsightsUncached 签名改为接收已解析 release。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/personas.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reports.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/insights.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reports.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/personas.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/insightsV3.test.ts`
- **验收**：
  - 指针从 v1 前进到 v2（reports SHA 变化）后，reloadRedditReports 返回的 snapshot.release.generated_at_utc 为 v2 值（修复前返回 v1）
  - reports SHA 未变时 reload 仍以当前指针的 release 对象重建快照（reset 后重新加载），generated_at_utc 为新值
  - personas/insights 在绑定 SHA 未变时不重复 fetch，变化时重取
  - 既有 reports/personas/insightsV3 测试全绿
- **测试**：
  - `src/features/redditSnapshot/__tests__/reports.test.ts > release-keyed reports cache > reload crosses a release boundary and returns the new generated_at_utc`
  - `src/features/redditSnapshot/__tests__/reports.test.ts > release-keyed reports cache > does not serve a cached reports promise when the pointer reports SHA changes`
  - `src/features/redditSnapshot/__tests__/personas.test.ts > release-keyed persona cache > refetches the persona manifest when the personas binding SHA changes`
  - `src/features/redditSnapshot/__tests__/insightsV3.test.ts > release-keyed insights cache > reloads insights after the pointer insights binding changes`
- **完成定义**：三个测试文件全绿；reports.ts 的 reload 路径中不再出现对 loadCurrentRelease() 的直接调用；npm run build 通过。

#### `L4-T05` useReleaseAwareData：挂载/可见/10 分钟轮询/失败重试，并接入七个 useReddit* hook

- **严重度**：P0｜**类型**：feature｜**工作量**：M｜**拓扑层**：2
- **依赖**：`L4-T02`
- **描述**：新建 useReleaseAwareData（契约 C1）。行为：挂载加载；document visibilitychange→visible 重载；默认 10 分钟轮询；结果与上次 Object.is 相同则不 setState；刷新失败且有旧数据时写 warning 保留 data；首次失败写 error 但轮询继续，成功即清 error；暴露 retry()。七个 hook 改为薄包装，保留既有返回字段（data/error/isLoading）并新增 warning/isRefreshing/retry。Dashboard 增加代际守卫：summary 与 core 的 base manifest SHA 不一致时只渲染 summary 派生区块并展示“数据版本切换中”，不混用两代。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useReleaseAwareData.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditSnapshot.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditSnapshotSummary.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditBrandHealth.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditQuarterInsights.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditPersonas.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditInsights.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditReports.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/useReleaseAwareData.test.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
- **验收**：
  - 挂载即加载；dispatch visibilitychange（document.hidden=false）触发第二次 load；前进 10 分钟后触发第三次
  - loader 返回同一对象引用时不发生额外渲染（用渲染计数器断言）
  - 有旧数据时刷新失败：data 保留、error 为 null、warning 非空
  - 首次失败后继续轮询并在成功时清除 error
  - Dashboard 在 summary/core 两代不一致时渲染切换提示且不显示混用数值
- **测试**：
  - `src/features/redditSnapshot/__tests__/useReleaseAwareData.test.tsx > useReleaseAwareData > loads on mount, refetches when the tab becomes visible, and polls on the interval`
  - `src/features/redditSnapshot/__tests__/useReleaseAwareData.test.tsx > useReleaseAwareData > does not re-render when the release-keyed loader returns the same object identity`
  - `src/features/redditSnapshot/__tests__/useReleaseAwareData.test.tsx > useReleaseAwareData > keeps last-known-good data and exposes a warning when a background refresh fails`
  - `src/features/redditSnapshot/__tests__/useReleaseAwareData.test.tsx > useReleaseAwareData > retries after a failed first load through the interval`
- **完成定义**：新增 hook 测试全绿；七个 hook 的既有调用点（pages/*.tsx）无需修改即可编译；npm test 与 npm run build 通过。

#### `L4-T06` 画像分布改用季度 cohort 计数，合计只在分母自证时显示 100.00%

- **严重度**：P0｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：SnapshotInsightsV3.tsx:531-537 传入 cohortAssignmentCounts={quarterInsights.personas.cohorts} 与 declaredMainAssignmentCount={quarterInsights.personas.main_assignment_count}。AggregatePersonaPanel：assignmentCount 优先取季度计数（缺失才回退 assignment 过滤结果）；statusLabel 阈值用同一数字；postCount/commentCount/threadCount 仅当 cohortAssignments.length === assignmentCount 时为真实值，否则 null 并渲染“—”；totalAssignments 为展示值之和；:125 的“合计 100.00%”改为条件渲染（>0 且等于声明分母），否则“分母不可用（已展示 X / 声明 Y）”。AggregatePersonaCard 类型相应允许 null。生产 ID 空间不相交时不再出现全 0。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/personas/AggregatePersonaPanel.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/personas/AggregatePersonaCard.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/SnapshotInsightsV3.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/personas/__tests__/AggregatePersonaPanel.test.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/__tests__/SnapshotInsightsV3.test.tsx`
- **验收**：
  - 生产形态 fixture（cohort 320/77/91/80/0/0/187/0，assignment 集合与之一致或完全不相交）下 8 条份额合计 100.00%，scenario_adapter 为 42.38% · 320 条，无任何非零 cohort 显示 0.00% · 0 条
  - assignment 与季度计数不相交时，帖子/评论/证据线程显示“—”而不是 0
  - 当展示合计不等于声明分母时显示“分母不可用”而非 100.00%
  - 仓库 7 月夹具（408/408、两套 ID 相同）下现有快照与拆分显示保持不变，既有测试全绿
- **测试**：
  - `src/components/personas/__tests__/AggregatePersonaPanel.test.tsx > AggregatePersonaPanel > renders quarter cohort counts when the persona assignment id space is disjoint`
  - `src/components/personas/__tests__/AggregatePersonaPanel.test.tsx > AggregatePersonaPanel > does not print 合计 100.00% when the displayed sum differs from the declared quarter total`
  - `src/components/personas/__tests__/AggregatePersonaPanel.test.tsx > AggregatePersonaPanel > keeps post and comment splits only when the assignment count matches the quarter count`
  - `src/components/insights/__tests__/SnapshotInsightsV3.test.tsx > SnapshotInsightsV3 quarterly story > passes quarter cohort counts into the persona panel`
- **完成定义**：四个用例通过；既有 AggregatePersonaPanel/SnapshotInsightsV3 用例不修改断言即绿；npm run build 通过。

#### `L4-T07` 报告品牌健康行：score/value 双形态 + 唯一归一化 + 严格校验

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：按契约 C2 重写 V3BrandHealthRow 与 brandHealthRowValue；validateV3CurrentReport（reports.ts:1057-1065）从只查 rows.length===2 升级为：两行且 comparison_side 各一、键 ⊆ 22 键白名单、available/provisional 必须归一化出 [0,100] 数值、unavailable 必须 null + 非空 reason codes、projection_role 枚举校验。periodBrandHealth（OperationalReportSupplement.tsx:97-102）改用 brandHealthRowValue，返回带 value/display 的行以保持 :219/:287/:403 逻辑不变。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reports.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/OperationalReportSupplement.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reports.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/__tests__/OperationalReportSupplement.test.tsx`
- **验收**：
  - 仅含 score 的生产形态行（75.42/available）被接受并归一化为 {value:75.42, display:'75.42'}
  - status=available 且 score/value 均缺失或非数值时校验抛错
  - status=unavailable 且无 reason codes 时校验抛错
  - 旧夹具（value/display 形态）继续通过；月报渲染“品牌健康度指数 75.42”且 data-brand-health='75.42'
- **测试**：
  - `src/features/redditSnapshot/__tests__/reports.test.ts > V3 brand-health row contract > accepts and normalizes a producer row that carries only score`
  - `src/features/redditSnapshot/__tests__/reports.test.ts > V3 brand-health row contract > rejects an available row without a numeric score or value`
  - `src/features/redditSnapshot/__tests__/reports.test.ts > V3 brand-health row contract > rejects an unavailable row without reason codes`
  - `src/components/reports/__tests__/OperationalReportSupplement.test.tsx > OperationalReportSupplement > renders the monthly brand-health index from a score-only row`
- **完成定义**：四个用例通过；reports.test.ts 既有用例全绿；npm run build 通过（V3BrandHealthRow 不再要求 display/value）。

#### `L4-T08` 报告品牌健康周期口径：全观测历史不再标“本月”

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L4-T07`
- **描述**：按契约 C3：报告 brand_health 增加可选 period_basis；新增 reportBrandHealthPeriodBasis(report)。OperationalReportSupplement.tsx:345-349 的副标题按口径切换：report_period 保留“本月指数构成”；all_observed_history 改为“品牌健康为全观测历史投影，不随报告周期变化；贡献分用于解释指数构成，不等同于环比变化贡献”。判定规则：显式字段优先；否则行内 period_id 与报告周期相同 → report_period；否则 all_observed_history。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/OperationalReportSupplement.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reports.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reports.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/__tests__/OperationalReportSupplement.test.tsx`
- **验收**：
  - 当前生产 payload（三粒度相同分数、无 period_basis、无 period_id）渲染“全观测历史”，不出现“本月”
  - 显式 period_basis='report_period' 时渲染“本月”
  - 仓库旧夹具（行内 period_id 与月报周期一致）仍渲染“本月”，既有测试不回归
- **测试**：
  - `src/features/redditSnapshot/__tests__/reports.test.ts > V3 brand-health period basis > defaults to all_observed_history when the block carries no period evidence`
  - `src/features/redditSnapshot/__tests__/reports.test.ts > V3 brand-health period basis > respects an explicit period_basis`
  - `src/components/reports/__tests__/OperationalReportSupplement.test.tsx > OperationalReportSupplement > labels an all-history projection without the current-month claim`
- **完成定义**：三个用例通过；OperationalReportSupplement 中不再出现无条件“本月”字样；npm run build 通过。

#### `L4-T09` 周期结束标签统一绑定 report.period.end（页面/海报/治理四处）

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：新建 reportPeriods.ts（契约 C13）。SnapshotReports.tsx：:394-395 的 projectionAsOf 改为 report.period.end；:447-449 的 captureDataAsOf 改为 report.period.end（并保留 data-report-data-as-of 属性名）；:497 的可见标签改为“周期结束（不含）”；:613-615 的可见值改为 report.period.end。governance/contracts.ts:275-279 的 tag_maturity detail 改为 `报告周期 ${start} 至 ${end}（结束不含当日）`。:57 的导出区已正确，不动。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reportPeriods.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotReports.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/governance/contracts.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reportPeriods.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/__tests__/SnapshotReportsV3.test.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/governance.test.tsx`
- **验收**：
  - 周报显示“周期结束（不含）：<report.period.end>”（夹具 2026-07-20），月报为 2026-07-01，日报为 2026-07-24；页面、海报属性、海报 dl、治理 detail 四处一致
  - 任何“周期结束（不含）”标签不再渲染 index.as_of_date
  - 治理 detail 不再把 as_of_date 描述为周期结束日期
- **测试**：
  - `src/features/redditSnapshot/__tests__/reportPeriods.test.ts > report period labels > derives the exclusive end from report.period.end for daily, weekly and monthly`
  - `src/features/redditSnapshot/__tests__/reportPeriods.test.ts > report period labels > renders the inclusive weekly and monthly ranges`
  - `src/components/reports/__tests__/SnapshotReportsV3.test.tsx > SnapshotReports V3 business story > shows the weekly period end instead of the daily index anchor`
  - `src/features/redditSnapshot/__tests__/governance.test.tsx > Reddit VOC UI governance components > anchors the report maturity detail to the report period, not the index as_of_date`
- **完成定义**：四个用例通过；`grep -n 'index.as_of_date' SnapshotReports.tsx governance/contracts.ts` 只剩非周期语义的 0 处；npm run build 通过。

#### `L4-T10` 覆盖分档展示四档并守恒，删除死代码 SnapshotBoundaryPanel

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：按契约 C13 增加 coverageGradeBreakdown。baseDataScope（contracts.ts:121-133）的 detail 改为“完整 / 部分 / 仅帖子 / 来源观察 + 合计 N 帖子”，status 仍为 total-full>0 时 provisional。删除 SnapshotBoundaryPanel.tsx（全仓零引用，且它只列 full/partial，是第二套口径）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/governance/contracts.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/SnapshotBoundaryPanel.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/governance.test.tsx`
- **验收**：
  - 生产形态（933/1,094/7,955/15,891，合计 25,873）的 detail 同时包含四个数字与“合计 25,873 帖子”
  - 四档之和与 canonical_counts.posts 不等时 conserved=false（helper 单测），且既有 loader 守恒断言仍在
  - grep 无 SnapshotBoundaryPanel 引用，文件删除后构建通过
- **测试**：
  - `src/features/redditSnapshot/__tests__/governance.test.tsx > Reddit VOC UI governance components > renders all four coverage grades with a conserved total`
  - `src/features/redditSnapshot/__tests__/governance.test.tsx > Reddit VOC UI governance components > never drops source_observed from the data scope statement`
  - `src/features/redditSnapshot/__tests__/governance.test.tsx > coverageGradeBreakdown > flags a non-conserved four-grade breakdown`
- **完成定义**：三个用例通过；SnapshotBoundaryPanel.tsx 已删除；npm run build 通过。

#### `L4-T11` 概览页分层绑定：产品家族用 family_rankings、品类用 category_rankings

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：SnapshotDashboard.tsx:462-463 增加 categoryRankings 与 familyRankings 绑定；:608-609 的“产品家族”列改为 familyRankings；精确 SPU 列保持 exactSpuRankings；:552/:570 的品类摘要与下钻改用 categoryRankings[0]；product_rankings 在有明确主体标签前不渲染；渲染 family_only_ids.length 的家族级映射提示；空数组显示“当前发布未提供该维度排名”。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotDashboardV3.test.tsx`
- **验收**：
  - fixture 中 category_rankings=['catA']、family_rankings=['famA']、product_rankings=['prodX']、exact_spu_rankings=['spuY']：产品家族列显示 famA 且不显示 prodX，精确 SPU 列显示 spuY，品类摘要显示 catA
  - family_rankings 为空时渲染显式不可用状态，不崩溃
  - 家族级映射提示使用 family_only_ids.length
- **测试**：
  - `src/pages/__tests__/SnapshotDashboardV3.test.tsx > V3 dashboard management story > binds the product-family column to family_rankings and the category summary to category_rankings`
  - `src/pages/__tests__/SnapshotDashboardV3.test.tsx > V3 dashboard management story > renders an explicit empty state when family rankings are unavailable`
- **完成定义**：两个用例通过；`grep -n '产品家族' SnapshotDashboard.tsx` 附近的列表项不再是 productRankings；npm run build 通过。

#### `L4-T12` 删除客户端现编样本量，改读投影 sample 字段

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：按契约 C4：brand-health.json 增加可选 sample（L2 生产）；brandHealth.ts 的 DATA_KEYS 支持可选 sample 并校验 total=post+comment。BrandHealthSnapshotCard 删除 sampleSize prop，改读 data.data.sample；有则渲染“{post} 帖 / {comment} 评论 / {total} VOC”，无则渲染“投影未提供样本分母”。SnapshotDashboard.tsx:516 删除 isMomcozyPost 计数调用。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/BrandHealthSnapshotCard.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/brandHealth.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/BrandHealthSnapshotCard.test.tsx`
- **验收**：
  - 无 sample 时副标题不含任何千分位数字
  - sample={post_vocs:1136, comment_context_vocs:2289, total_vocs:3425} 时渲染“1,136 帖 / 2,289 评论 / 3,425 VOC”
  - sample 的 total 与 post+comment 不等时校验抛错
  - SnapshotDashboard 不再为样本量调用 isMomcozyPost
- **测试**：
  - `src/features/redditSnapshot/__tests__/BrandHealthSnapshotCard.test.tsx > BrandHealthSnapshotCard > never fabricates a sample size from the client post filter`
  - `src/features/redditSnapshot/__tests__/BrandHealthSnapshotCard.test.tsx > BrandHealthSnapshotCard > renders the producer sample counts when sample is present`
  - `src/features/redditSnapshot/__tests__/brandHealth.test.ts > public V3 brand-health contract > rejects a sample block whose total does not equal posts plus comments`
- **完成定义**：三个用例通过；`grep -n 'sampleSize' src` 零命中；npm run build 通过。

#### `L4-T13` 分析页净情感观察分与品牌健康口碑消歧

- **严重度**：P3｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：SnapshotAnalytics.tsx:186 的卡片标题改为“Momcozy 与竞品帖内净情感观察分”，副标题增加“仅统计帖子情感（pos-neg）/posts；与品牌健康度·口碑健康（帖子+评论加权、pos+0.5*neutral）不是同一指标”，并提供到 /dashboard 的链接。公式（:33-38）不变。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotAnalytics.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotAnalytics.test.tsx`
- **验收**：
  - 页面出现新标题与交叉引用句
  - 页面不再单独用“口碑健康”指代该指标
  - 公式单测保持：2 pos / 1 neg / 1 neutral → 62.5
- **测试**：
  - `src/pages/__tests__/SnapshotAnalytics.test.tsx > SnapshotAnalytics > labels the net-sentiment score as a post-only observation score and cross-references brand health`
  - `src/pages/__tests__/SnapshotAnalytics.test.tsx > SnapshotAnalytics > keeps the brandObservationScore formula pinned`
- **完成定义**：两个用例通过；npm run build 通过；纯文案改动无数据契约变化。

#### `L4-T14` 搜索页显示标签字典版本与校验和前缀

- **严重度**：P3｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：在 SnapshotSearch.tsx:817-822 的“标签筛选”下增加说明文本：“词典 {manifest.tagging.dictionary_version} · {dictionary_sha256.slice(0,12)}”；未知 tag id 仍回退原始 id，并加 title 说明标签来自上方词典版本。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotSearch.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotSearchFilters.test.tsx`
- **验收**：
  - 夹具下说明包含 'dim_tag_v6.3_final' 与 sha 前 12 位
  - 未知 tag id 的选项文字回退为原始 id，说明仍渲染
- **测试**：
  - `src/pages/__tests__/SnapshotSearchFilters.test.tsx > SnapshotSearch operational filters > prints the tag dictionary version and checksum prefix beside the tag filter`
  - `src/pages/__tests__/SnapshotSearchFilters.test.tsx > SnapshotSearch operational filters > falls back to the raw tag id when the dictionary has no label`
- **完成定义**：两个用例通过；npm run build 通过。

#### `L4-T15` 洞察页解除 insights 门禁、删除 allowlist、改为守恒计数与双信任模式

- **严重度**：P1｜**类型**：refactor｜**工作量**：M｜**拓扑层**：0
- **描述**：按契约 C9/C10：页面以 base manifest schema 选择 V3 渲染；insights 只作为 provenance（新 prop insightsProvenance），失败不阻塞；casebook effect 改键 quarterInsightsState.data；删除 SnapshotInsightsV3Props.snapshot 与测试里的 unusedLegacySnapshot；删除 VALIDATED_PUBLIC_WRAPPERS 与 :1123-1124 断言；侧车改为 manifest_bound（files 含第三项时校验 bytes+sha）或 coherence_only（交叉绑定 release/manifest SHA）；78 字面量改为 manifest/receipt/insights 的计数守恒（含 assertStorylineSummary 增加 expectedTotal），TS 类型改 number。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotInsights.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/SnapshotInsightsV3.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/insightsV3.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/insightsV3.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/__tests__/SnapshotInsightsV3.test.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotInsightsGate.test.tsx`
- **验收**：
  - insights 端点返回 500 时 /dashboard/insights 仍渲染季度 VOC 20,741 与痛点排名，显示 provenance 警告，不出现 SnapshotErrorPage
  - 79 条 storyline 的 fixture 可通过（计数派生而非硬编码）
  - storyline_count 与 storylines.length 不一致时拒绝
  - 侧车 bundle_manifest_sha256 与 release 不一致时拒绝
  - grep 源码无“用 78 作为计数门禁”的字面量
- **测试**：
  - `src/features/redditSnapshot/__tests__/insightsV3.test.ts > V3 public insights contract > loads a 79-storyline payload because the count is derived, not hardcoded`
  - `src/features/redditSnapshot/__tests__/insightsV3.test.ts > V3 public insights contract > rejects a payload whose storyline_count disagrees with storylines.length`
  - `src/features/redditSnapshot/__tests__/insightsV3.test.ts > V3 public insights contract > accepts an unbound public sidecar as coherence_only trust`
  - `src/features/redditSnapshot/__tests__/insightsV3.test.ts > V3 public insights contract > rejects a sidecar whose bundle_manifest_sha256 differs from the release pointer`
  - `src/pages/__tests__/SnapshotInsightsGate.test.tsx > SnapshotInsights page gate > renders the quarter story when the insights dataset returns HTTP 500`
  - `src/pages/__tests__/SnapshotInsightsGate.test.tsx > SnapshotInsights page gate > does not render SnapshotErrorPage when only insights fails`
- **完成定义**：六个用例通过；insightsV3.test.ts 与 SnapshotInsightsV3.test.tsx 既有用例全绿（允许改掉 snapshot prop 一行）；npm run build 通过。

#### `L4-T16` 治理标签成熟度跟随数据，不再禁止晋级

- **严重度**：P2｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：删除 service.ts:1119-1120 与 :1451-1452 的 labels_provisional===true / semantic_validation_run===false 断言；保留“两个字段存在且为 boolean”的校验。baseTagMaturity 的四个分支 detail 都带 dictionary_version，并显示 semantic_validation_run 状态。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/service.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/governance/contracts.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/service.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/governance.test.tsx`
- **验收**：
  - labels_provisional=false 且 semantic_validation_run=true 的 manifest 被接受并渲染“已完成语义验证”
  - 缺字段或非布尔的 manifest 仍被拒绝
  - 两个断言删除后既有 V3 夹具测试全绿
- **测试**：
  - `src/features/redditSnapshot/__tests__/service.test.ts > Reddit static snapshot contract > accepts a promoted-tagging manifest and renders the verified maturity branch`
  - `src/features/redditSnapshot/__tests__/service.test.ts > Reddit static snapshot contract > still rejects a manifest whose tagging booleans are missing`
  - `src/features/redditSnapshot/__tests__/governance.test.tsx > Reddit VOC UI governance components > shows 已完成语义验证 when tagging is promoted`
- **完成定义**：三个用例通过；`grep -n 'labels_provisional === true' service.ts` 零命中；npm run build 通过。

#### `L4-T17` 证据链接携带发布代与数据边界，缺帖给出两代解释

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：0
- **描述**：按契约 C7：链接增加 at=<release.generated_at_utc> 与 asof=<data_as_of_utc>；SnapshotEvidenceLinkInput/Target 增加字段；新增 isEvidenceTargetStale(target,current,postPresent)。八个调用点传入 release 的生成时间与数据边界。SnapshotSearch.tsx:174-176 的 releaseMismatch 替换为中性血缘行（at/asof 与当前值），:695-701 的缺帖展示“未找到该证据帖子；该帖子可能已被新语料淘汰”并列出两代。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/evidenceLinks.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotSearch.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotInsights.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotWorkspace.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/OperationalReportSupplement.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/RiskThemePanel.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/personas/AggregatePersonaPanel.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/personasV3.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/evidenceLinks.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotSearchFilters.test.tsx`
- **验收**：
  - 链接同时含 at 与 asof，release/snapshot 参数保留用于人工阅读且不再参与判定
  - release 代不同但帖子仍存在时只显示中性血缘行（不告警）
  - 缺帖 + 链接边界早于当前边界时显示两代信息与淘汰解释
  - 无 asof 的旧链接视为未知，不告警
- **测试**：
  - `src/features/redditSnapshot/__tests__/evidenceLinks.test.ts > snapshot evidence links > carries both the release generation and the data boundary`
  - `src/features/redditSnapshot/__tests__/evidenceLinks.test.ts > snapshot evidence links > treats a link without asof as unknown rather than stale`
  - `src/pages/__tests__/SnapshotSearchFilters.test.tsx > SnapshotSearch operational filters > explains a missing evidence post with both generations`
- **完成定义**：三个用例通过；证据链接的 8 个构建点全部传入新参数（tsc 必填字段强制）；npm run build 通过。

#### `L4-T18` casebook dossier 渲染复核到期与逾期徽标

- **严重度**：P2｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：运营视图（CaseGallery.tsx:486-520）与抽屉（CaseDossierDrawer.tsx）显示“复核到期 {review_due_at}”与“生成于 {casebook.data.generated_at}”；当 now > review_due_at 时显示“已逾期 N 天”徽标（data-governance-status='provisional'）。不新增数据字段（casebook.ts:78 已有 review_due_at，data.generated_at 已有）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/CaseGallery.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/case-gallery/CaseDossierDrawer.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/CaseGallery.test.tsx`
- **验收**：
  - 运营视图与抽屉都显示复核到期日期
  - 过期 dossier 显示逾期徽标，未过期不显示
  - casebook 加载失败时保留现有错误提示，不渲染任何日期
- **测试**：
  - `src/pages/__tests__/CaseGallery.test.tsx > CaseGallery > shows the dossier review due date and an overdue badge in the operations view`
  - `src/pages/__tests__/CaseGallery.test.tsx > CaseGallery > omits the overdue badge for a dossier whose review date is in the future`
- **完成定义**：两个用例通过；npm run build 通过；无 JSON 契约变化。

#### `L4-T19` 辅助数据集缺失绑定时失败关闭（移除 7 月夹具回退）

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L4-T03`
- **描述**：删除 brandHealth.ts:278/281、quarterInsights.ts:700/703、casebook.ts:290/293 的 `?? 常量` 回退；当 options 未显式提供且 release.datasets[key] 缺失时，在 fetch 之前抛出命名错误（含数据集键）。常量重命名为 LEGACY_FIXTURE_* 并只允许测试导入；更新三处测试导入。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/brandHealth.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/quarterInsights.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/casebook.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/quarterInsights.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/casebook.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/__tests__/SnapshotInsightsV3.test.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotPages.test.tsx`
- **验收**：
  - release 删除 brand_health/quarter_insights/casebook 绑定时，loader 抛“current release 未绑定 <key> 数据集”，且 fetch 未被调用
  - 显式传 basePath+expectedManifestSha256 的测试路径仍可用
  - 生产形态指针（三绑定齐全）下三个 loader 行为不变
- **测试**：
  - `src/features/redditSnapshot/__tests__/brandHealth.test.ts > public V3 brand-health contract > fails closed when the release does not bind brand_health and no explicit fixture is passed`
  - `src/features/redditSnapshot/__tests__/quarterInsights.test.ts > public rolling-quarter insights contract > fails closed when the release does not bind quarter_insights`
  - `src/features/redditSnapshot/__tests__/casebook.test.ts > public governance casebook contract > fails closed when the release does not bind casebook`
- **完成定义**：三个用例通过；`grep -n 'LEGACY_FIXTURE_' src/features/redditSnapshot/*.ts` 只出现在常量定义；生产代码无 `?? 常量` 回退；npm run build 通过。

#### `L4-T20` 新鲜度条：60 秒数据年龄时钟、实时 recency、观测边界警示

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：按契约 C11：新增 formatDataAge / recencyStatusAt / recencyLabelAt。DataFreshnessBar 增加 60 秒本地时钟（卸载清理），渲染“数据距今 X”徽标，用 recencyLabelAt 替换 evidence.recencyLabel，并在 observationMax 晚于 dataAsOf 时渲染观测边界警示行。不改 DataFreshnessEvidence 的字段形状，不改抽屉结构。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/freshness.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/DataFreshnessBar.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/freshness.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/DataFreshnessBar.test.tsx`
- **验收**：
  - dataAsOf 比固定 now 早 2 小时时显示“数据距今 2小时0分钟”；前进 61 分钟后文字更新且不触发 fetch
  - observationMax 晚于 dataAsOf 时出现警示行；相等或更早时不出现
  - 非法/空 dataAsOf 返回“时效未知”，不产生 NaN
  - 既有 DataFreshnessBar 两个用例仍通过（标签与抽屉内容不变）
- **测试**：
  - `src/features/redditSnapshot/__tests__/freshness.test.ts > freshness clock > formats data age from a live clock and degrades to 时效未知 for invalid input`
  - `src/features/redditSnapshot/__tests__/freshness.test.ts > freshness clock > upgrades a fresh label to stale after the deadline without a refetch`
  - `src/features/redditSnapshot/__tests__/DataFreshnessBar.test.tsx > DataFreshnessBar > ticks the data age every minute without refetching`
  - `src/features/redditSnapshot/__tests__/DataFreshnessBar.test.tsx > DataFreshnessBar > warns when the newest observed event is later than the published boundary`
- **完成定义**：四个用例通过；既有 DataFreshnessBar 用例不改断言通过；npm run build 通过。

#### `L4-T21` 画像证据惰性化：persona-tags 19.5MB 仅在“加载证据”时请求

- **严重度**：P1｜**类型**：feature｜**工作量**：L｜**拓扑层**：1
- **依赖**：`L4-T06`
- **描述**：按契约 C6：把 loadRedditV3Personas 拆为 loadRedditV3PersonaCohorts（manifest/personas/cohort-bridge/atomic-catalog/avatars，~50KB；tags 可选省略）与 loadRedditV3PersonaAssignments（persona-tags.json，独立 release 键缓存，每会话至多一次）。V3RedditPersonasSnapshot.tags 改可选，保持旧测试构造的带 tags 快照仍可用。面板：未加载时拆分列显示“—”，并提供“加载证据（约 19.5MB）”按钮与体积提示；加载后填充 post/comment/thread 与证据链接；加载失败显示错误且不清空季度计数。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/personasV3.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/personas.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditPersonas.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/personas/AggregatePersonaPanel.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/SnapshotInsightsV3.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/personas.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/personas/__tests__/AggregatePersonaPanel.test.tsx`
- **验收**：
  - 首次进入洞察页时 persona-tags.json 请求数为 0
  - 点击“加载证据”后每会话恰好 1 次请求
  - 加载后证据链接生成且与季度计数一致；失败时计数与份额不变
  - personas.test.ts 既有 12 个用例（含 20.4KB 夹具）全绿
- **测试**：
  - `src/features/redditSnapshot/__tests__/personas.test.ts > V3 personas lazy evidence > loads cohort metadata without requesting persona-tags.json`
  - `src/features/redditSnapshot/__tests__/personas.test.ts > V3 personas lazy evidence > loads persona assignments exactly once on demand`
  - `src/components/personas/__tests__/AggregatePersonaPanel.test.tsx > AggregatePersonaPanel > shows a 加载证据 control until assignments are requested`
- **完成定义**：三个用例通过；personas.test.ts 与 AggregatePersonaPanel.test.tsx 既有用例全绿；npm run build 通过。

#### `L4-T22` Agent Studio：删除 07:05 文案，显示真实生成时间，刷新不整页重载

- **严重度**：P3｜**类型**：fix｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L4-T01`
- **描述**：删除 AgentStudio.tsx:87 与 :105 的“每日 07:05”；两个 fetch 捕获 response.headers.get('last-modified')；渲染“最近生成 {generated_at_utc ?? lastModified ?? 未提供}”与“Run {run_id}”；刷新按钮改为异步重取（先 refreshCurrentRelease 再读两个文档），不使用 window.location.reload；两个 doc 接口增加可选 generated_at_utc（契约 C12）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/AgentStudio.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/AgentStudio.test.tsx`
- **验收**：
  - 页面与错误态都不含“每日 07:05”
  - 响应头 last-modified 存在时页面显示该时间；body 有 generated_at_utc 时优先用它
  - 点击刷新触发两次新 fetch 且不调用 window.location.reload
  - 两者都缺失时显示“未提供”
- **测试**：
  - `src/pages/__tests__/AgentStudio.test.tsx > AgentStudio > shows a real generation time and never the static 07:05 claim`
  - `src/pages/__tests__/AgentStudio.test.tsx > AgentStudio > refreshes through the release pointer without a full page reload`
- **完成定义**：两个用例通过；`grep -R '每日 07:05' src/` 零命中；npm run build 通过。

#### `L4-T23` 删除硬编码判断句，改为数据派生句并接受 conclusions[]

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：按契约 C5 与 3.13：BrandHealthSnapshotCard.tsx:94 改为“品牌健康度为 {overall} 分；最高为 {strongest} {score} 分，最低为 {weakest} {score} 分”（并列按固定维度顺序）；SnapshotInsightsV3 的痛点摘要去掉“优先级高于适配舒适度与泌乳输出问题”，businessExplanation 改为排名前三的数据句，新品/地理块只引用当次 rankings 的 label/count；SnapshotDashboard 的固定主张移入口径说明。三个数据集的校验接受可选 conclusions[]；当 conclusion_id 命中且 gate.status='passed' 时原样渲染 text，否则回退数据派生句。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/BrandHealthSnapshotCard.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/SnapshotInsightsV3.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotDashboard.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/{reports,quarterInsights,brandHealth}.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/__tests__/SnapshotInsightsV3.test.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/BrandHealthSnapshotCard.test.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotDashboardV3.test.tsx`
- **验收**：
  - 四维分数相等时页面不出现“四维差异明显”，出现最强/最弱数据句
  - topPain 为 noise 时摘要与业务解释不含“适配舒适度”“泌乳输出”
  - topDriver 为任意字符串时页面只显示该字符串，不附带固定主题名
  - 提供 conclusions[]（gate passed）时按 conclusion_id 渲染其 text 原文
- **测试**：
  - `src/features/redditSnapshot/__tests__/BrandHealthSnapshotCard.test.tsx > BrandHealthSnapshotCard > derives the overall judgment from the four dimension scores`
  - `src/components/insights/__tests__/SnapshotInsightsV3.test.tsx > SnapshotInsightsV3 quarterly story > renders no hardcoded pain theme names when the ranking changes`
  - `src/pages/__tests__/SnapshotDashboardV3.test.tsx > V3 dashboard management story > keeps judgment sentences data-derived and free of hardcoded theme nouns`
  - `src/components/insights/__tests__/SnapshotInsightsV3.test.tsx > SnapshotInsightsV3 quarterly story > renders conclusions verbatim when the producer provides a passed conclusion`
- **完成定义**：四个用例通过；`grep -n '适配舒适度\|泌乳输出\|四维差异明显' src` 只在测试夹具中出现；npm run build 通过。

#### `L4-T24` 评论按字节区间读取：comment_index 双路径 + LRU + 回退确认

- **严重度**：P1｜**类型**：feature｜**工作量**：L｜**拓扑层**：0
- **描述**：按契约 C8：base manifest 接受可选 comment_index；EXPECTED_SNAPSHOT_FILES 在声明时允许 comments-index-public.json；新增索引校验与 Range 分片读取（要求 206；校验分片 SHA；fragment 首尾为 { }；按 '['+fragment+']' 解析；按 post_id 过滤；LRU(20)，键 dataSha:postId）。无索引时保留单文件路径：先 HEAD 取 content-length，>50MB 先确认，解析放入可注入工厂的 Worker 并在卸载时 abort。SnapshotSearch 的评论加载使用同一入口。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/service.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotSearch.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/service.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotSearchFilters.test.tsx`
- **验收**：
  - 索引存在时打开单帖最多 3 个 Range 请求，0 次全量 GET，返回评论与单文件路径结果一致
  - 分片 SHA 不匹配时抛错且不显示评论
  - 非 206（服务器不支持 Range）时回退单文件路径并给出大小确认
  - 无索引的旧 manifest 仍可打开帖子
  - 卸载时中止进行中的请求
- **测试**：
  - `src/features/redditSnapshot/__tests__/service.test.ts > comment byte-range index > fetches only the byte range for a post when comment_index is present`
  - `src/features/redditSnapshot/__tests__/service.test.ts > comment byte-range index > falls back to the monolith when comment_index is absent`
  - `src/features/redditSnapshot/__tests__/service.test.ts > comment byte-range index > rejects a shard whose sha256 does not match the index`
  - `src/features/redditSnapshot/__tests__/service.test.ts > comment byte-range index > aborts an in-flight comment fetch on unmount`
  - `src/pages/__tests__/SnapshotSearchFilters.test.tsx > SnapshotSearch operational filters > opens an evidence post without downloading the full comments file`
- **完成定义**：五个用例通过；无索引时既有评论测试全绿；npm run build 通过。生产端封装（comments-index-public.json）由 L1-P15 提供，本票以合成 manifest+fetch stub 验证。

#### `L4-T25` 洞察页与报表页改用摘要投影，不再下载 70MB 核心帖子

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L4-T15`
- **描述**：按契约 C10：SnapshotInsights 的 baseState 改为 useRedditSnapshotSummary；SnapshotInsightsV3Props.baseSnapshot 改为 RedditSnapshotSummary；SnapshotReports 的 base 改为 summary，RealReportView/OperationalReportSupplement 的 snapshot 类型降为 RedditSnapshotSummary（两者只读 release/manifest）。更新 SnapshotReportsV3.test 的 hook mock。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotInsights.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/insights/SnapshotInsightsV3.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotReports.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/RealReportView.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/OperationalReportSupplement.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/components/reports/__tests__/SnapshotReportsV3.test.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotInsightsGate.test.tsx`
- **验收**：
  - /dashboard/insights 不再请求 posts-public.json，总 JSON 传输（summary+quarter+persona cohorts+casebook）< 1MB
  - /dashboard/reports 不再请求 posts-public.json，页面数值与改造前一致
  - 两页的版本校验、freshness 条与证据链接行为不变
- **测试**：
  - `src/pages/__tests__/SnapshotInsightsGate.test.tsx > SnapshotInsights page gate > loads the page from the summary projection without requesting posts-public.json`
  - `src/components/reports/__tests__/SnapshotReportsV3.test.tsx > SnapshotReports V3 business story > renders from the summary projection without requesting posts-public.json`
- **完成定义**：两个用例通过；报告页既有渲染用例全绿；npm run build 通过。

#### `L4-T26` 证据陈旧判定收紧：仅缺帖 + 边界不同才告警

- **严重度**：P2｜**类型**：fix｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L4-T17`
- **描述**：把 isEvidenceTargetStale 的危险级判定改为：postPresent === false 且 target.releaseDataAsOfUtc 非空且早于 current.dataAsOfUtc。at 与当前 generated_at_utc 不同只显示中性血缘行，不告警。旧链接无 asof 视为 unknown。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/evidenceLinks.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/SnapshotSearch.tsx`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/evidenceLinks.test.ts`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotSearchFilters.test.tsx`
- **验收**：
  - 一天前生成、帖子仍在语料的链接不出现任何警告样式（只有中性血缘行）
  - 缺帖且链接边界早于当前边界 → 告警并显示两代
  - 缺帖但链接边界等于当前边界（同一代）→ 显示缺帖解释但不标“陈旧”
- **测试**：
  - `src/features/redditSnapshot/__tests__/evidenceLinks.test.ts > snapshot evidence links > does not flag a day-old link whose post is still present`
  - `src/pages/__tests__/SnapshotSearchFilters.test.tsx > SnapshotSearch operational filters > does not warn for a day-old link whose post is still present`
- **完成定义**：两个用例通过；SnapshotSearch 的警告样式只由新判定驱动；npm run build 通过。

### L5 — 可观测与治理层 (Observability & Governance)

#### `L5-T01` 早报卡片任何非 success 一律未验证并红标；回执优先取内存

- **严重度**：P0｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：修 L5-P1 的卡片语义（回执读取时序的另一半属 L6-P10，不在本票）。build_card(run_dir, public_root, run_id, *, receipt=None)：优先用传入的内存回执，缺省才读盘；读盘 FileNotFoundError 不再向上抛，降级为 receipt={'status':'unavailable','steps':[],'errors':[]}。verified 严格等于 receipt.get('status') == 'success'，删除 partial_1_step_errors 白名单（build_morning_brief_v4.py:254）。header_template 先判流水线：status != 'success' → 'red'，再叠加业务信号（:260-264）。trust_line：success 时保留「版本完整性已验证」；否则「版本完整性未验证 · 失败步骤：<step[,step]>」，失败步骤取 receipt['steps'] 中 status 不在 {ok,success,empty_success,partial,skipped_already_covered} 的条目并回退到 receipt['errors']（:500-524 的降级卡同样加这一行，不得静默）。
- **涉及文件**：
  - `tools/feishu-card/builders/build_morning_brief_v4.py`
  - `tests/test_morning_brief_card.py`
- **验收**：
  - receipt.status='partial_1_step_errors'（失败步骤 recompute_derivatives）时 card['header']['template'] != 'green'，且任一 markdown 元素的 content 含 'recompute_derivatives'
  - 只有 receipt.status=='success' 时卡片文本才含「已验证」
  - 传入 receipt 时不读盘：run_dir 下不存在 {run_id}-pipeline-receipt.json 也能构建成功
  - run_dir 缺回执且未传 receipt 时返回红标卡，文本含「未验证」，不抛异常
- **测试**：
  - `tests/test_morning_brief_card.py::test_card_is_red_and_unverified_when_receipt_status_is_partial`
  - `tests/test_morning_brief_card.py::test_card_never_reports_verified_for_partial_1_step_errors`
  - `tests/test_morning_brief_card.py::test_card_uses_in_memory_receipt_not_disk`
  - `tests/test_morning_brief_card.py::test_card_names_failed_step`
  - `tests/test_morning_brief_card.py::test_card_is_unverified_when_receipt_missing`
- **完成定义**：五个 pytest 用例绿；卡片渲染结果中 header.template 与 trust_line 由回执状态唯一决定；无网络调用。

#### `L5-T02` build_receipt 模块：每数据集 build.json + run 级回执，create-new 不可变

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：0
- **描述**：新增 scripts/build_receipt.py，实现契约中的 echo_agent_dataset_build_stamp_v1 与 echo_agent_build_receipt_v1。write_dataset_stamp 读 binding.manifest_path 的实际字节算 manifest_sha256，拒绝与指针 binding 不一致的入参；build_basis 为 'pipeline' 或 'external_manual_build'。write_build_receipt 写 data/reddit-voc/build-receipts/<run_id>.json，沿用 validate_reddit_daily_site_refresh.write_immutable（:214-230）的 create-new 语义：目标存在且字节不同 → BuildReceiptCollision('build_receipt_collision')，写入 0600 + fsync + os.replace。run_id 必须匹配 RUN_ID_PATTERN=^[a-z0-9][a-z0-9_-]{0,127}$（与 ref/UI/.../release.ts:6 同源），不匹配抛 ValueError。fixture 目录含 7 个 dataset 目录与 manifest。
- **涉及文件**：
  - `scripts/build_receipt.py`
  - `tests/test_build_receipt.py`
  - `tests/fixtures/build_receipt/minimal_public_root/`
- **验收**：
  - 对 fixture 的每个 dataset 调用 write_dataset_stamp 后，<dataset_dir>/build.json 的 manifest_sha256 == sha256(manifest 实际字节) == 指针 binding.public_manifest_sha256
  - write_build_receipt 的 receipt.datasets 键集等于 release.datasets 键集，且每项 manifest_sha256 与对应 build.json 一致
  - 同一 run_id 写两次不同字节 → BuildReceiptCollision，原文件字节不变
  - run_id='Daily Collect' 抛 ValueError；'daily_collect_20261029_190142_manual' 通过
  - 冻结数据集允许 generated_at_utc=null 且必须带 source_unavailable_reason
- **测试**：
  - `tests/test_build_receipt.py::test_stamp_manifest_sha_matches_manifest_bytes`
  - `tests/test_build_receipt.py::test_receipt_lists_every_release_dataset`
  - `tests/test_build_receipt.py::test_receipt_write_is_immutable_on_conflict`
  - `tests/test_build_receipt.py::test_run_id_must_match_client_safe_pattern`
  - `tests/test_build_receipt.py::test_frozen_dataset_stamp_allows_null_generated_at`
- **完成定义**：模块无第三方依赖、可被 scripts/ 与 tests/ 直接导入；五个用例绿；fixture 自包含且不读 ref/UI 公共树。

#### `L5-T03` 三个数据集目录校验器允许 build.json（否则下次重建必挂）

- **严重度**：P1｜**类型**：refactor｜**工作量**：S｜**拓扑层**：0
- **描述**：为 3.1 的 build.json 打开白名单，且不放宽其它检查。personas：把 :916-922 的文件清单比较抽成纯函数 _assert_declared_inventory(root, expected_names)，允许集合为 expected_names | {'manifest.json','build.json'}，未知文件仍抛 'persona snapshot contains undeclared files'。insights：build_reddit_insights_snapshot.py:1135-1140 的允许集合加 'build.json'。reports：_v3_assert_output_inventory（:2434-2470）增关键字参数 tolerated_files: set[str] = frozenset()，write_v3_public_reports_wrapper 的两处调用（:3480-3486 exact=False、:3497-3503 exact=True）传 {'build.json'}；未声明的其它文件仍抛错。
- **涉及文件**：
  - `src/reddit_voc/v3_persona_snapshot.py`
  - `scripts/build_reddit_insights_snapshot.py`
  - `scripts/build_reddit_reports_snapshot.py`
  - `tests/test_dataset_build_stamp_allowlist.py`
- **验收**：
  - personas 目录含 build.json 时 _assert_declared_inventory 不抛；含 extra.json 时仍抛 undeclared files
  - insights public 目录含 build.json 时 write_v3_public_insights_wrapper 不抛；含 extra.json 时抛 'public insights output contains undeclared entries'
  - _v3_assert_output_inventory(exact=True, tolerated_files={'build.json'}) 在目录含 build.json 时通过，含 other.json 时抛 undeclared files
- **测试**：
  - `tests/test_dataset_build_stamp_allowlist.py::test_persona_dataset_inventory_allows_build_stamp`
  - `tests/test_dataset_build_stamp_allowlist.py::test_persona_dataset_inventory_rejects_unknown_extra_file`
  - `tests/test_dataset_build_stamp_allowlist.py::test_insights_public_wrapper_allows_build_stamp`
  - `tests/test_dataset_build_stamp_allowlist.py::test_reports_output_inventory_tolerates_build_stamp_only`
- **完成定义**：四个用例绿；除 build.json 外没有任何其它文件被放行；原有 undeclared 错误文案保留。

#### `L5-T04` 流水线写入 7 份 build.json 与 run 回执（失败也留证）

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：1
- **依赖**：`L5-T02`
- **描述**：在 run_pipeline 中：所有步骤结束后、组装 receipt_doc 之前，调用 collect_dataset_stamps + write_dataset_stamp 为指针里的 7 个 dataset 各写一份 build.json（build_basis：base/quarter_insights/brand_health/reports 为 'pipeline'，personas/insights/casebook 为 'external_manual_build'）；run_id 取本次 _t1_bounds 的值，period_end_utc 取 T1Window.window_end_utc（T13 落地前用现有 _t1_bounds 的 window_end）。然后在 finally 中写 run 级回执：run 块来自 receipt_doc（status success 或 partial_N_step_errors），steps 块只保留 step/status/error 三个字段，release 块读当次落盘的 current-release.json（因此必须在 step4 之后）。回执写入失败不得吞掉：记录到 errors 并让进程返回非 0。
- **涉及文件**：
  - `scripts/run_daily_t1_pipeline.py`
  - `tests/test_pipeline_build_receipts.py`
- **验收**：
  - 用 fixture public root 跑 run_pipeline（skip_feishu=True、步骤桩化）后，7 个 dataset 目录都有 build.json 且 manifest_sha256 与 manifest 字节一致
  - 任一步骤抛错时 build-receipts/<run_id>.json 仍存在，run.status 为 partial_1_step_errors 且该步骤 error 非空
  - 同一 run_id 重跑不同结果不覆盖旧回执，进程报错且旧回执字节不变
  - 回执 release 块的 release_id/data_as_of_utc 与 current-release.json 完全一致
- **测试**：
  - `tests/test_pipeline_build_receipts.py::test_pipeline_writes_stamp_for_every_release_dataset`
  - `tests/test_pipeline_build_receipts.py::test_receipt_is_written_when_a_step_errors`
  - `tests/test_pipeline_build_receipts.py::test_receipt_collision_does_not_overwrite`
  - `tests/test_pipeline_build_receipts.py::test_receipt_release_block_matches_pointer`
- **完成定义**：四个用例绿；流水线在指针前写完所有 stamp；失败路径有回执；无 schema 变更波及客户端。

#### `L5-T05` 定时新鲜度监控 check_site_freshness.py：状态机 + 逐数据集自证 + 红卡/心跳/去重

- **严重度**：P0｜**类型**：feature｜**工作量**：M｜**拓扑层**：2
- **依赖**：`L5-T02`, `L5-T04`
- **描述**：新增监控脚本，复用 observe_reddit_data_release.classify（:51-117）与 expected_close（:41-48），不复用依赖 symlink 的 observe()（:184）。observe_site(public_root, *, now_utc=None, slo_minutes=90) 依次校验指针 schema/键集、取最新 build receipt、跑 classify、逐 dataset 校验 build.json 与 manifest sha、校验 receipt.release 与指针一致，输出 echo_agent_site_freshness_v1。failure 码：build_receipt_missing、build_stamp_missing:<key>、build_stamp_manifest_sha_mismatch:<key>、release_manifest_sha_mismatch:<key>、dataset_version_mismatch:<key>、build_stamp_run_mismatch:<key>、receipt_release_mismatch、pointer_freshness_invalid。build_alert_card 按 3.4 的规则选 header 颜色并用 FeishuBotClient.send_interactive_card（src/reddit_voc/feishu_bot.py:33）。--state-path 存 last_state/last_sent_at_utc/last_heartbeat_date：状态迁移才发；--heartbeat 每个上海日期最多一张绿卡。--fail-on-breach 时违约返回 2，无法评估返回 1。
- **涉及文件**：
  - `scripts/check_site_freshness.py`
  - `tests/test_check_site_freshness.py`
  - `tests/fixtures/freshness/`
- **验收**：
  - fixture 中新回执落后 expected_close 且无同周期尝试 → state='stalled'、exit 2
  - fixture 中回执覆盖同一周期 → state in {'fresh','partial'}、exit 0
  - 删除任一 dataset 的 build.json → exit 2 且 failures 含 'build_stamp_missing:<key>'
  - 把某 manifest 改一个字节但不动 binding → failures 含 release_manifest_sha_mismatch:<key>；只改 binding → 含 build_stamp_manifest_sha_mismatch:<key>
  - state='stalled' 时 build_alert_card 的 header.template == 'red'；state='fresh' 心跳卡 == 'green'
  - 同一 state 连续两次调用 should_notify 只发一次；跨日 --heartbeat 再发一次绿卡
- **测试**：
  - `tests/test_check_site_freshness.py::test_missing_build_receipt_after_deadline_is_stalled`
  - `tests/test_check_site_freshness.py::test_fresh_release_with_matching_receipt_is_fresh`
  - `tests/test_check_site_freshness.py::test_missing_build_stamp_is_failed_not_fresh`
  - `tests/test_check_site_freshness.py::test_manifest_sha_mismatch_is_failed_not_fresh`
  - `tests/test_check_site_freshness.py::test_partial_build_status_is_not_fresh`
  - `tests/test_check_site_freshness.py::test_feishu_card_header_is_red_for_stalled`
  - `tests/test_check_site_freshness.py::test_alert_is_deduped_per_state_transition`
  - `tests/test_check_site_freshness.py::test_heartbeat_is_sent_once_per_shanghai_day`
- **完成定义**：八个用例绿；脚本不读 symlink 台账；无凭据时不发网络请求；state 文件写在 public 树之外；--prune-keep 默认保留 90 份且不删最新。

#### `L5-T06` 新鲜度告警单元入库并在服务器装起来

- **严重度**：P0｜**类型**：ops｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L5-T05`
- **描述**：按 3.12 新增三个单元。timer 的 OnCalendar 全部晚于 08:00 Asia/Shanghai（08:37/10:37/13:37/16:37/19:37/22:37），Persistent=true。service 用 SuccessExitStatus=2（2 是已发卡的受控违约，不再触发 OnFailure），OnFailure=echo-agent-alert@%n.service。ADR-002 补一节：部署=按 sha256 复制文件（非 git），新单元与 config/reports_bundle_template_v3/ 必须进入部署清单。服务器安装与 systemctl list-timers 的文本证据作为 DoD 的一部分。
- **涉及文件**：
  - `config/systemd/echo-agent-freshness.service`
  - `config/systemd/echo-agent-freshness.timer`
  - `config/systemd/echo-agent-alert@.service`
  - `tests/test_systemd_units.py`
  - `docs/adr/ADR-002-data-freshness-parity.md`
- **验收**：
  - python 解析三个 unit 文件：timer 的每条 OnCalendar 的 HH:MM > 08:00（Asia/Shanghai）
  - service 的 [Unit] 含 OnFailure=echo-agent-alert@%n.service，[Service] 含 SuccessExitStatus=2 且 ExecStart 指向 /opt/echo-agent-bot/scripts/check_site_freshness.py
  - ExecStart 引用的脚本在仓库内存在且可编译
  - 服务器 systemctl list-timers --all 能看到 echo-agent-freshness（上线证据记录在 ticket 评论）
- **测试**：
  - `tests/test_systemd_units.py::test_freshness_timer_starts_after_daily_close`
  - `tests/test_systemd_units.py::test_freshness_unit_has_onfailure_and_success_exit_status`
  - `tests/test_systemd_units.py::test_execstart_script_exists`
  - `tests/test_systemd_units.py::test_units_are_lowercase_safe`
- **完成定义**：四个用例绿；服务器已 enable --now 且 list-timers 可见；ADR 段落已合入。

#### `L5-T07` 发布前门禁改为基于 build stamp，可在生产工件模型上运行

- **严重度**：P2｜**类型**：refactor｜**工作量**：S｜**拓扑层**：2
- **依赖**：`L5-T02`, `L5-T04`
- **描述**：删除 _center_id 的字符串全等（:84-94 与 :149-150），改为：每个 dataset 的 build.json 存在、stamp.manifest_sha256 == observed_sha、stamp.dataset_version == binding.dataset_version；派生数据集（brand_health/quarter_insights/reports）的 stamp.source_manifest_sha256['base'] == sha256(base manifest 实际字节)；freshness.center_snapshot_id 仍要求非空。为 committed dev fixture 生成 7 份 build.json（build_basis 按数据集，run_id 用 fixture 的 July run 标签），使现有 test_validates_current_daily_candidate 继续可跑。
- **涉及文件**：
  - `scripts/validate_reddit_daily_site_refresh.py`
  - `tests/test_validate_reddit_daily_site_refresh.py`
  - `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/<7 dataset dirs>/build.json`
- **验收**：
  - committed fixture 上 validate_daily_site_refresh 返回 passed_candidate_only 且 datasets 7 条
  - 删除 fixture 中任一份 build.json → 抛 build_stamp_missing:<key>
  - 把 brand_health 的 stamp.source_manifest_sha256['base'] 改错 → 抛 source_manifest_sha_mismatch:brand_health
  - freshness.center_snapshot_id 为空 → 仍抛 center_snapshot_id_invalid（不放宽）
- **测试**：
  - `tests/test_validate_reddit_daily_site_refresh.py::test_validates_current_daily_candidate`
  - `tests/test_validate_reddit_daily_site_refresh.py::test_rejects_missing_build_stamp`
  - `tests/test_validate_reddit_daily_site_refresh.py::test_rejects_derivative_dataset_with_wrong_base_source_sha`
  - `tests/test_validate_reddit_daily_site_refresh.py::test_rejects_a_non_24_hour_business_window`
- **完成定义**：四个用例绿；门禁不再依赖跨数据集 center-id 全等；fixture stamps 与 manifest 字节一致。

#### `L5-T08` 血缘槽位改名到它真正哈希的工件（brand-health + reports 锁步）

- **严重度**：P1｜**类型**：refactor｜**工作量**：M｜**拓扑层**：0
- **描述**：按 3.6 改名 9 个槽位与 4 个 manifest 镜像字段，同步改客户端 exactKeys（brandHealth.ts:223-232、:290-296；reports.ts:187-194、:1832-1888），删除 build_reports_bundle.py:26 的 sha256(b'') 回退（缺失返回 None，任一槽位 None 即抛错）。更新 tests/test_recompute_parity.py:116-166 的 source_hashes 字典与断言。迁移 committed brand-health fixture（改 source 键、重算 canonical 字节、manifest files sha、manifest sha 与 current-release.json 绑定）并更新 brandHealth.test.ts 的断言。同一发布窗口内完成，不做双形态。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `scripts/recompute_reports_bundle.py`
  - `scripts/build_reports_bundle.py`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/brandHealth.ts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reports.ts`
  - `tests/test_lineage_slot_names.py`
  - `tests/test_recompute_parity.py`
  - `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_brand_health_20260723_public_v1/brand-health.json`
  - `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_brand_health_20260723_public_v1/manifest.json`
- **验收**：
  - brand-health.json 的 source 键集等于 {aggregates_public_sha256, base_manifest_sha256, quarter_insights_sha256, reports_manifest_sha256, source_snapshot_id}，且每个 sha 等于其名字所指文件的 sha256
  - reports 的 source 与 receipt 键集等于 {base_manifest_sha256, tag_dictionary_sha256, aggregates_public_sha256, quarter_insights_sha256}（另加 source_snapshot_id / coverage_attestation_sha256），且每个 sha 可解引用
  - 缺失 tag-dictionary 时 build_reports_bundle 抛错而不是返回 e3b0c442…
  - 迁移后的 committed fixture 通过 validatePublicBrandHealthData 与 V3 reports 校验
- **测试**：
  - `tests/test_lineage_slot_names.py::test_every_source_slot_hashes_the_artifact_its_name_claims`
  - `tests/test_lineage_slot_names.py::test_missing_tag_dictionary_fails_closed`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts::rejects a source block whose slot names do not match the documented artifacts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reports.test.ts::validates the renamed lineage slots against the receipt`
- **完成定义**：pytest + vitest 绿；grep -R 'metrics_candidate_manifest_sha256' scripts/recompute_derivatives.py scripts/recompute_reports_bundle.py 无输出；committed fixture 与 current-release 绑定一致。

#### `L5-T09` finalize_lineage：brand-health / quarter-insights 引用本次最终 reports manifest

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：1
- **依赖**：`L5-T08`
- **描述**：新增 recompute_derivatives.finalize_lineage(public_root, release, *, reports_manifest_sha256, reports_receipt_sha256)。在 run_recompute 内、reports bundle 落盘与 receipt 写完之后调用；用 canonical_json_document（:210-223）重写 brand-health.json（source.reports_manifest_sha256、source.quarter_insights_sha256）与 quarter-insights.json（source.voc_manifest_sha256、source.voc_validation_receipt_sha256），同步两者 manifest 的 source 与 files，重算 manifest sha，返回 {dataset_key: manifest_sha256}。必须幂等（保留各自 generated_at_utc 原值）。reports 构建抛错时不得调用。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `scripts/run_daily_t1_pipeline.py`
  - `tests/test_lineage_finalization.py`
- **验收**：
  - 一次完整 run_recompute 后 brand-health.json.source.reports_manifest_sha256 == sha256(reports/public/manifest.json)，quarter-insights.json.source.voc_manifest_sha256 同值
  - 用未 finalize 的旧路径跑（对照 fixture）两值不等，证明断言可证伪
  - 连续两次 finalize_lineage 字节完全相同
  - reports 构建失败时 finalize 不执行，brand-health 仍指向旧的已存在 manifest
- **测试**：
  - `tests/test_lineage_finalization.py::test_brand_health_cites_final_reports_manifest_sha`
  - `tests/test_lineage_finalization.py::test_quarter_insights_cites_final_reports_manifest_sha`
  - `tests/test_lineage_finalization.py::test_finalize_is_idempotent`
  - `tests/test_lineage_finalization.py::test_finalize_preserves_canonical_bytes`
  - `tests/test_lineage_finalization.py::test_finalize_is_not_called_when_reports_build_fails`
- **完成定义**：五个用例绿；指针绑定由 step3_5 现有循环同步；两次运行字节不变。

#### `L5-T10` 让 deterministic_full_byte_replay / independent_validation_status 变成真的

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：按 3.7 落地：新增受控模板 config/reports_bundle_template_v3/（从当前 live bundle 逐字节生成并 commit）与 EXPECTED_TEMPLATE_SHA256；新增 validate_reports_bundle(files) 与 build_reports_bundle_verified(canonical_template_dir, live_template_dir, expected_template_sha256, **kwargs)。receipt 的 deterministic_full_byte_replay = checks.replay_byte_identical（= 模板指纹匹配 且 两次构建字节相同），independent_validation_status = passed iff 四项 checks 全真，否则 pending 并抛 ReportsBundleValidationError。recompute_derivatives:1107-1125 改为调用 verified 版本并按其顺序写入（content → index/history → receipt → manifest 最后）。
- **涉及文件**：
  - `scripts/recompute_reports_bundle.py`
  - `scripts/recompute_derivatives.py`
  - `config/reports_bundle_template_v3/`
  - `tests/test_reports_bundle_validation.py`
  - `tests/fixtures/reports_template/`
- **验收**：
  - canonical 与 live 模板一致时 checks.replay_byte_identical==true 且 receipt.deterministic_full_byte_replay==true
  - 改动 fixture 模板中任一进入产物的字节后重建，flag==false 且 build 抛 ReportsBundleValidationError，未写 live 目录
  - 手工把 manifest.files 中某条 sha 改错 → status='pending' 且抛错
  - receipt 含 checks 四键与 replay 三键；report_count==6；bundle_manifest_sha256==manifest.lineage_manifest_sha256
  - scripts/ 下 grep '"deterministic_full_byte_replay": True' 无输出
- **测试**：
  - `tests/test_reports_bundle_validation.py::test_replay_flag_is_true_when_canonical_and_live_templates_agree`
  - `tests/test_reports_bundle_validation.py::test_replay_flag_is_false_when_a_template_byte_changes`
  - `tests/test_reports_bundle_validation.py::test_build_raises_before_publish_on_failed_check`
  - `tests/test_reports_bundle_validation.py::test_status_is_pending_when_manifest_hash_wrong`
  - `tests/test_reports_bundle_validation.py::test_receipt_checks_block_has_all_four_flags`
- **完成定义**：五个用例绿；受控模板与常量入库；发布路径不再读自身输出作为模板；部署清单包含 config/reports_bundle_template_v3/。

#### `L5-T11` boundaries 声明与总分推导对齐，客户端复算总分

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：BRAND_HEALTH_BOUNDARIES['overall_score_derived_from_axes'] 改 True（recompute_derivatives.py:702），brandHealth.ts:18 类型与 :169 断言改 true，并新增 overall.score === roundHalfUpMean(dimensions) 断言（共享 half-up 实现，与 :789-792 同语义）。迁移 committed fixture（flip 边界、重算 canonical 字节与 manifest sha 与 release 绑定）。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/brandHealth.ts`
  - `tests/test_brand_health_boundary.py`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts`
  - `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_brand_health_20260723_public_v1/brand-health.json`
  - `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_brand_health_20260723_public_v1/manifest.json`
- **验收**：
  - brand-health.json 与 manifest.boundaries.overall_score_derived_from_axes 均为 true
  - 客户端 validatePublicBrandHealthData 在 overall != round_half_up(mean(dims)) 时抛错（改造后的 fixture 验证）
  - scripts/ 与 src/ 下 grep '"overall_score_derived_from_axes": False' 无输出
  - 四维为 null 时 overall 必须 null 且不触发均值断言
- **测试**：
  - `tests/test_brand_health_boundary.py::test_boundary_declares_overall_derived_from_axes_true`
  - `tests/test_brand_health_boundary.py::test_overall_equals_half_up_mean_of_four_dimensions`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts::recomputes overall as the half-up mean of the four dimensions`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts::rejects a manifest whose overall is not the mean of its dimensions`
- **完成定义**：pytest + vitest 绿；fixture 与指针绑定一致；旧 false 工件在新客户端下被拒绝（可证伪）。

#### `L5-T12` freshness 的 status / net_new / coverage 来自本次运行回执

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：0
- **描述**：新增 scripts/freshness_contract.py（derive_freshness_status / freshness_evidence_from_pipeline_receipt / FreshnessEvidenceRequired）。merge 回执增 permalink_repair 四个计数、updated_historical_posts（既有 post 记录 canonical 字节变化计数，新增行不计）与 coverage 三计数（full_posts/partial_posts/unresolved_continuations，按 3.9 定义）。advance_current_release_to_t1 的 run_id/status/net_new/coverage 改为必填，删除 :63 的内部 run_id 合成；CLI 增 --receipt。指针 freshness 键集不变。
- **涉及文件**：
  - `scripts/freshness_contract.py`
  - `scripts/run_daily_t1_pipeline.py`
  - `scripts/advance_daily_t1_release.py`
  - `tests/test_freshness_contract.py`
- **验收**：
  - 用当日真实回执 50/237 替换后，指针 net_new.posts==50、net_new.comments==237，不再出现 56/246
  - net_new.repaired_parent_links == merge 回执 permalink_repair.comments_repaired
  - coverage 三个值与 merge 回执完全相等（非重算）
  - 缺少 run_id/status/net_new/coverage 任一项时 advance 抛 FreshnessEvidenceRequired 且不写指针
  - status：partial_posts>0 → partial；partial_posts==0 且步骤全 ok → full；零新增 → empty_success
- **测试**：
  - `tests/test_freshness_contract.py::test_net_new_equals_merge_receipt_deltas`
  - `tests/test_freshness_contract.py::test_coverage_comes_from_merge_receipt`
  - `tests/test_freshness_contract.py::test_advance_refuses_without_run_evidence`
  - `tests/test_freshness_contract.py::test_status_full_when_no_partial_posts`
  - `tests/test_freshness_contract.py::test_status_empty_success_on_zero_delta`
  - `tests/test_freshness_contract.py::test_status_partial_when_partial_posts_present`
- **完成定义**：六个用例绿；指针 freshness 仍是 10/4/3 键；旧的 56/246 在任何测试 fixture 中都不再被写出。

#### `L5-T13` 单一 T-1 切割函数，四个调用点统一（含 8760 采样）

- **严重度**：P1｜**类型**：refactor｜**工作量**：S｜**拓扑层**：0
- **描述**：新增 src/reddit_voc/freshness.py 的 T1Window 与 compute_t1_window(now_utc=None)（3.10 语义）。_t1_bounds、calculate_t1_shanghai_window、_t1_anchor、build_reports_bundle.py:49 全部改为调用它；_t1_anchor 保持返回 datetime（period_end_date 正午 SHANGHAI）以兼容 tests/test_recompute_parity.py:46 的 patch。所有函数接受可注入 now_utc 以便测试，默认 datetime.now(timezone.utc)。
- **涉及文件**：
  - `src/reddit_voc/freshness.py`
  - `scripts/run_daily_t1_pipeline.py`
  - `scripts/advance_daily_t1_release.py`
  - `scripts/recompute_derivatives.py`
  - `scripts/build_reports_bundle.py`
  - `tests/test_t1_window.py`
- **验收**：
  - T1Window 对 2026-10-29T16:30Z（=10-30T00:30+08:00）给出 window_end=2026-10-28T23:00Z、period_end_date=2026-10-28
  - 8760 个逐小时样本上，_t1_bounds/calculate_t1_shanghai_window/_t1_anchor/build_reports_bundle 的 anchor 完全一致
  - advance 写出的 window_start/window_end/data_as_of 仍满足 23:00Z 边界与 end==data_as_of
  - _t1_anchor().date() 永远等于 period_end_date
  - build_reports_bundle 的日粒度 period_id 等于 daily:<period_end_date>:<period_end_date+1>
- **测试**：
  - `tests/test_t1_window.py::test_window_is_closed_23utc_to_23utc`
  - `tests/test_t1_window.py::test_period_end_date_is_shanghai_close_date_minus_one_day`
  - `tests/test_t1_window.py::test_recompute_anchor_matches_window_at_0030_shanghai`
  - `tests/test_t1_window.py::test_all_call_sites_agree_over_8760_hourly_samples`
- **完成定义**：四个用例绿；仓库内不存在第二处 now-1day 实现。

#### `L5-T14` base / reports manifest 与 agent-studio 产物的构建时间

- **严重度**：P1｜**类型**：feature｜**工作量**：S｜**拓扑层**：0
- **描述**：refresh_base_manifest（:868-914）末尾写 manifest['generated_at_utc']=RFC3339 Z（该字段已存在，客户端对顶层无 exactKeys）；build_reports_bundle 的 manifest 增 generated_at_utc（v3 客户端不 exact-key）；AgentBatchRunner.persist_artifacts（src/reddit_voc/agents/batch_runner.py:134-186）三个 payload 增 generated_at_utc。不给 aggregates-public.json 与 tag-dictionary 加字段。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `scripts/recompute_reports_bundle.py`
  - `src/reddit_voc/agents/batch_runner.py`
  - `tests/test_build_timestamps.py`
- **验收**：
  - 连续两次 refresh_base_manifest 用不同 now_utc，manifest.generated_at_utc 随之变化且为 Z 结尾的 RFC3339
  - reports manifest 含 generated_at_utc 且能被 validateV3ReportsManifestDispatch 接受（vitest 用 fixture 验证）
  - agent 三个 latest-*.json 含 generated_at_utc
  - aggregates-public.json 的键集不变（18 键）
  - base manifest 新增时间戳后 validate_reddit_v3_base_public_projection 的 aggregates 整对象比较不受影响
- **测试**：
  - `tests/test_build_timestamps.py::test_base_manifest_generated_at_advances`
  - `tests/test_build_timestamps.py::test_reports_manifest_carries_generated_at`
  - `tests/test_build_timestamps.py::test_aggregates_payload_keys_unchanged`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reports.test.ts::accepts a v3 manifest that carries generated_at_utc`
- **完成定义**：四个用例绿；base manifest 字节变化后指针绑定同步（由 step3_5 现有循环覆盖）。

#### `L5-T15` brand-health manifest 构建时间（生产者与客户端锁步）

- **严重度**：P1｜**类型**：feature｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L5-T11`
- **描述**：brand-health manifest 增 generated_at_utc（RFC3339 Z），同批在 brandHealth.ts:92-96 的 MANIFEST_KEYS 加入该键并在 :180-198 校验其为可解析 UTC 字符串；迁移 committed fixture 的 manifest 并更新 current-release 绑定。数据文件 brand-health.json 不加该字段（避免 DATA_KEYS 变更）。
- **涉及文件**：
  - `scripts/recompute_derivatives.py`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/brandHealth.ts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts`
  - `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_brand_health_20260723_public_v1/manifest.json`
- **验收**：
  - 新 manifest 通过 validatePublicBrandHealthManifest
  - 缺少 generated_at_utc 的旧 manifest 在新客户端下被拒绝（可证伪）
  - 迁移后的 fixture 与 current-release.json 的 public_manifest_sha256 一致
  - data 与 manifest 的 projection_id/source/lineage 断言仍通过
- **测试**：
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts::accepts a manifest with generated_at_utc`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/brandHealth.test.ts::rejects a manifest without generated_at_utc`
- **完成定义**：两个 vitest 用例绿；fixture 与绑定一致；生产者写出的 manifest 可被同一版客户端接受。

#### `L5-T16` 状态文案诚实化：哈希校验 ≠ 数据新鲜；Agent Studio 显示真实产出时间

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L5-T14`
- **描述**：freshness.ts:227-228 的 statusLabel 默认值改为「发布 manifest 哈希已校验」，保留 status='verified' 但语义收窄为哈希校验（在类型注释与抽屉文案中说明）；recencyLabel 不动（它已按 evidence 分支）。AgentStudio.tsx:87,105 删除「每日 07:05」，改为读取 latest-*.json 的 generated_at_utc 与 run_id 展示「最近一次产出：… · Run …」，字段缺失显示「产出时间未提供」。不实现缓存 TTL（L4-P1）。
- **涉及文件**：
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/freshness.ts`
  - `ref/UI/momcozy-reddit-workbench/src/pages/AgentStudio.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/freshness.test.ts`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/DataFreshnessBar.test.tsx`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/AgentStudio.test.tsx`
- **验收**：
  - createBaseDataFreshness 默认返回 statusLabel=='发布 manifest 哈希已校验'
  - DataFreshnessBar 渲染该文案，data-testid=data-freshness-bar 的 data-recency-status 仍来自 evidence.recencyStatus
  - 给定 base manifest.generated_at_utc 与 release.freshness.data_as_of_utc 相差 <=1 天，evidence.projectionGeneratedAtUtc 与 dataAsOf 的差 <= 86400s（用改造后的 fixture 验证，替换掉 98 天场景）
  - AgentStudio 在 latest-*.json 有 generated_at_utc 时展示该时间与 run_id，文本不含「每日 07:05」；缺失时展示「产出时间未提供」
- **测试**：
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/freshness.test.ts::labels the chip as a manifest-hash verification not a data freshness verdict`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/freshness.test.ts::evidence drawer projection time is within one day of data_as_of after the base manifest is rebuilt`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/DataFreshnessBar.test.tsx::renders the manifest-hash verification label`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/AgentStudio.test.tsx::shows the artifact generated_at_utc instead of a hardcoded 07:05 claim`
- **完成定义**：四个 vitest 用例绿；页面不再把「版本完整性已校验」当作数据新鲜度结论；Agent Studio 文案由数据驱动。

### L6 — 运行可靠性层 (Runtime Reliability)

#### `L6-T01` 文件级写前检查：可写位 + 可读性 + 完整目标清单

- **严重度**：P0｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：根因：_preflight_writability（run_daily_t1_pipeline.py:535-564）只对目录做 os.access(W_OK)，:550 虽把 current-release.json 列为文件目标，但 posts/comments/aggregates/lineage 文件、store SQLite 本体都只经由父目录判断；:559 推导的是 data/reddit-voc/lineage，不覆盖 <base_dataset_dir>/lineage；reports/public/current|archive 与 agent-studio 完全不在目标里。2026-10-29 07:17 root 属主 0700 的 lineage/product-entity-ledger.json 因此通过预检，运行在 recompute 中途 PermissionError。实现：新增 _collect_write_targets()，目标由 release.datasets 键驱动（每个 manifest 的 files 字典逐项 + 每个数据集自己的 lineage/*.json + reports public 四个顶层文件 + agent-studio/latest-*.json + store 文件本体 + generations root）；对已存在文件先查 mode 写位（无任何写位即 mode_denies_write，root 也不能豁免），再查 R_OK（代际复制需要读）与 W_OK；对不存在目标只查最近父目录 W_OK|X_OK。错误 payload 带 path/uid/mode/reason，uid 不同但可写只记 foreign_owner warning。调用点保持 :573（采集之前）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_daily_pipeline_preflight.py`
- **验收**：
  - 构造 tmp 站点树，把 posts-public.json chmod 0400 后运行 run_pipeline：在 step1_collect 之前抛 RuntimeError，文本前缀 pipeline_preflight_unwritable_targets 且含该文件绝对路径、uid、mode；step1 调用计数为 0。
  - 构造 base 数据集自己的 lineage/ 下 root-owned 0600 文件：预检以 reason=not_readable 失败（当前代码会漏检）。
  - store SQLite 文件本身不可写时失败；仅父目录不可写时也失败（parent_not_writable）。
  - 合法可写树上预检返回 {'checked': N>0, 'blocked': []}，run_pipeline 继续执行。
- **测试**：
  - `tests/test_daily_pipeline_preflight.py::test_rejects_readonly_file_in_writable_dir`
  - `tests/test_daily_pipeline_preflight.py::test_rejects_unreadable_file_in_writable_dir`
  - `tests/test_daily_pipeline_preflight.py::test_checks_base_lineage_subdir`
  - `tests/test_daily_pipeline_preflight.py::test_checks_store_sqlite_file`
  - `tests/test_daily_pipeline_preflight.py::test_accepts_writable_tree`
  - `tests/test_daily_pipeline_preflight.py::test_run_pipeline_fails_before_step1`
- **完成定义**：预检在采集前枚举全部真实写/读目标并逐个 stat；新增 6 个 pytest 用例全绿且不访问网络；生产同款 0400 文件能在运行前被指出。

#### `L6-T02` 编排层离线夹具与端到端骨架

- **严重度**：P3｜**类型**：test｜**工作量**：M｜**拓扑层**：1
- **依赖**：`L6-T01`
- **描述**：根因：没有任何测试导入 run_pipeline/run_recompute/advance_current_release_to_t1/_preflight_writability（对 tests/ 全量 grep 无命中）；test_recompute_parity.py 的 fixture 反而从生产 URL 拉快照（:27-37）。实现：新增 tests/pipeline_fixtures.py::make_site_root(tmp_path, *, posts=3, comments=2)，按 run_daily_t1_pipeline.py:211-239/:270-293 的字段集合成 3 帖/2 评（这些是 pipeline 自己写入的 dict，不是 July 导入），写 7 个 binding 与 current-release.json；reports 模板从仓库内 reddit_voc_reports_20260723_v3_47c49395e785_history2/public/{current,archive} 复制；随后调用真实 run_recompute 生成 aggregates/quarter/brand-health/reports，保证 fixture 与生产契约同源、不手写 schema。tests/test_daily_pipeline_harness.py 用 monkeypatch 替换 step1_collect/step2_agents 驱动 run_pipeline 端到端。该文件不依赖网络，后续所有 ticket 复用。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/tests/pipeline_fixtures.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_daily_pipeline_harness.py`
- **验收**：
  - make_site_root 产出的树能被真实 run_recompute 无异常处理，current-release.json 的 7 个 binding 的 public_manifest_sha256 均等于对应 manifest 字节 sha256。
  - 端到端 run_pipeline（mock 采集与 agents）退出码 0、指针前移、回执落盘。
  - 注入 merge 阶段的异常后，线上树递归 sha256 清单与指针字节完全不变（T08 前以 skipif 标记，T08 后转必过）。
  - 整个测试在无网络的 pytest 进程中通过。
- **测试**：
  - `tests/test_daily_pipeline_harness.py::test_fixture_tree_satisfies_release_contract`
  - `tests/test_daily_pipeline_harness.py::test_end_to_end_publish_on_fixture_corpus`
  - `tests/test_daily_pipeline_harness.py::test_fixture_build_is_offline`
- **完成定义**：tests/pipeline_fixtures.py 可被任意测试导入并秒级构造一棵真实契约的站点树；harness 两个正向用例全绿；离线证明写入测试注释与 CI 命令。

#### `L6-T03` 从 release binding 解析 base 数据集目录

- **严重度**：P1｜**类型**：refactor｜**工作量**：S｜**拓扑层**：2
- **依赖**：`L6-T02`
- **描述**：根因：recompute_derivatives.py:922 写死 reddit_voc_site_snapshot_20260723_v3_daily_001，而 merge 从 release binding 动态解析（run_daily_t1_pipeline.py:180-187）。base 版本一上调，merge 写新目录、recompute 读旧目录，静默混合代。实现：新增 scripts/release_paths.py（load_release/relocate_manifest_path/dataset_dir/manifest_path，负责把 data/reddit-voc/<v>/... 重定位到任意 data_root 并拒绝 .. 越界）；run_recompute 增加 data_root 关键字，把 :922、:928、:933-934、:993、:995、:1050、:1077、:1105 全部改为基于 data_root 的解析；回执新增 inputs.data_root、inputs.base_dataset_version、datasets、produced。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/release_paths.py`
  - `/Users/lute/Project/Echo-Agent/scripts/recompute_derivatives.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_recompute_base_binding.py`
- **验收**：
  - tmp 树放两个 base 目录 A/B，release 指向 A：run_recompute 的 receipt.inputs.posts 等于 A 的帖子数，B 目录内所有文件 sha256 不变。
  - dataset_dir 在 live 路径与 generation 路径下解析到同一逻辑数据集；含 .. 的 manifest_path 被拒绝。
  - CLI main() 行为不变（不传 data_root 时等于 public_root/data/reddit-voc）。
- **测试**：
  - `tests/test_recompute_base_binding.py::test_run_recompute_reads_base_version_from_release`
  - `tests/test_recompute_base_binding.py::test_unbound_dataset_dir_is_untouched`
  - `tests/test_recompute_base_binding.py::test_dataset_dir_helper_handles_generation_root`
  - `tests/test_recompute_base_binding.py::test_relocate_rejects_parent_traversal`
- **完成定义**：recompute 全流程无硬编码数据集版本；四个用例在 tmp 树上通过且不触网；receipt 新增字段与契约 C4 一致。

#### `L6-T04` 早报 builder 从 release binding 解析 quarter-insights

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：3
- **依赖**：`L6-T03`
- **描述**：根因：build_morning_brief_v4.py:78（以及 v1:75、v2:77、v3:76）写死 reddit_voc_quarter_insights_20260723_public_v1。quarter 版本一变化，早报要么静默读旧数据要么抛错，而 builder 异常会被 run_daily_t1_pipeline.py:499-501 吞掉并降级为 legacy 卡。实现：qi 路径 = dataset_dir(public_root/'data'/'reddit-voc', release['datasets']['quarter_insights']) / 'quarter-insights.json'；四个 builder 同步修正（其中 v1/v2/v3 未被 step5 引用，但保留同规则以免误部署）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/tools/feishu-card/builders/build_morning_brief_v4.py`
  - `/Users/lute/Project/Echo-Agent/tools/feishu-card/builders/build_morning_brief.py`
  - `/Users/lute/Project/Echo-Agent/tools/feishu-card/builders/build_morning_brief_v2.py`
  - `/Users/lute/Project/Echo-Agent/tools/feishu-card/builders/build_morning_brief_v3.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_morning_brief_paths.py`
- **验收**：
  - 把 quarter 目录改名为新版本并同步更新 binding，build_card 仍能构建且读到新版本数据。
  - 四个 builder 源码中不再出现硬编码 quarter 版本字面量（参数化 grep 守护）。
  - binding 缺失时抛出明确 KeyError，而不是静默读旧版本。
- **测试**：
  - `tests/test_morning_brief_paths.py::test_morning_brief_reads_quarter_path_from_release`
  - `tests/test_morning_brief_paths.py::test_builders_have_no_hardcoded_quarter_version`
- **完成定义**：早报 quarterly 段落来源完全由 release 决定；两个用例通过；v4 卡片在改名后的 fixture 树上构建成功。

#### `L6-T05` 真实 run 身份：run_id / run_kind / collector_run_id / release_id

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：0
- **描述**：根因：run_id = f"daily_collect_{sh_now:%Y%m%d}_0700"（run_daily_t1_pipeline.py:49）来自墙钟日期而非运行本身，19:01 重跑被记成 07:00 定时运行，回执路径 {run_id}-pipeline-receipt.json（:638）冲突并覆盖失败证据；advance 又独立合成 collector_run_id（advance_daily_t1_release.py:63），完全忽略 step4 收到的 run_id（:461-470）；release_id 从不变化。实现：run_id = daily_collect_%Y%m%d_%H%M%S（沿用 src/reddit_voc/cli.py:1393 的既有约定）；新增 run_kind（--run-kind 显式覆盖，默认与 07:05 CST 的 ±30 分钟判定）；step4 把 run_id 传给 advance_release_document 的 collector_run_id；commit 每次生成 reddit_voc_release_{yyyymmdd}_daily_v{seq}（同日递增、跨日归 v1），并断言匹配 ^[a-z0-9][a-z0-9_-]{0,127}$ 与 reddit_voc_release_ 前缀（release.ts:6/:160-162）。base manifest.generated_at_utc 属 L1-R6，本 ticket 仅在 refresh_base_manifest 预留可选 build_time 参数（缺省不改字节）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/scripts/advance_daily_t1_release.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_run_identity.py`
- **验收**：
  - 同一天 07:05 与 19:01 两次运行产生不同 run_id 与不同回执文件名；freshness.collector_run_id 分别等于各自回执的 run_id。
  - release_id 每次 commit 都变化且符合前端安全标识符与前缀。
  - run_kind 在 --run-kind manual 时为 manual，未传且以 07:05 为锚时判定为 scheduled。
  - 两次运行的回执不互相覆盖（旧文件仍在）。
- **测试**：
  - `tests/test_run_identity.py::test_two_runs_get_distinct_ids_and_receipts`
  - `tests/test_run_identity.py::test_collector_run_id_equals_pipeline_run_id`
  - `tests/test_run_identity.py::test_release_id_advances_per_commit`
  - `tests/test_run_identity.py::test_run_id_matches_release_safe_identifier`
  - `tests/test_run_identity.py::test_run_kind_defaults_and_override`
- **完成定义**：回执、日志与发布指针都能区分定时与人工运行；5 个用例通过；release_id 单调推进。

#### `L6-T06` 绑定同步白名单 + 版本一致性断言

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：3
- **依赖**：`L6-T03`, `L6-T05`
- **描述**：根因：step3_5_recompute_derivatives 遍历 release['datasets'] 的每一个 key，对每个存在的 manifest 重写 files[*].sha256/bytes，再把 manifest sha256 写回 current-release.json（run_daily_t1_pipeline.py:415-438），整个循环没有校验该数据集是否由本次运行产出、manifest.dataset_version 是否等于 binding。外部写入的 manifest（手工 personas 重建、半截写入）会在下一次运行被自动采纳进发布指针，SHA 绑定退化为“磁盘上是什么就绑什么”。实现：删除该循环，改为纯函数 _sync_bindings(release, produced, data_root)->list[str]，只处理 produced（recompute 回执新增的 datasets/produced），逐项断言 manifest 存在且合法、dataset_version 相等、路径重定位不越界；personas/insights/casebook 一律不重写不重绑；显式跳过 base.lineage_manifest_sha256（personas.ts:324 依赖）；reports lineage 仍走回执字段（保留 :442-448）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/scripts/recompute_derivatives.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_daily_pipeline_binding_sync.py`
- **验收**：
  - 两次运行之间手工替换 personas manifest（dataset_version 不同）：下一次运行后 current-release.json 中 personas 绑定逐字节不变，且该 manifest 未被重写。
  - 本次应产出的数据集 manifest 版本与 binding 不一致时抛 binding_dataset_version_mismatch:<key>，指针不变。
  - produced 之外的 key 即使磁盘上有新 manifest 也不进入绑定。
  - reports.lineage_manifest_sha256 仍随回执更新。
- **测试**：
  - `tests/test_daily_pipeline_binding_sync.py::test_rejects_foreign_manifest`
  - `tests/test_daily_pipeline_binding_sync.py::test_produced_version_mismatch_raises`
  - `tests/test_daily_pipeline_binding_sync.py::test_only_reports_lineage_updated`
  - `tests/test_daily_pipeline_binding_sync.py::test_missing_produced_manifest_raises`
  - `tests/test_daily_pipeline_binding_sync.py::test_base_lineage_sha_is_never_rewritten`
- **完成定义**：绑定同步只发生在本次产出的数据集上；五个用例通过；外部写入的 manifest 无法进入发布指针。

#### `L6-T07` 代际事务模块：复制种子、原子 symlink 切换、回滚与 gc

- **严重度**：P0｜**类型**：feature｜**工作量**：L｜**拓扑层**：3
- **依赖**：`L6-T02`, `L6-T03`
- **描述**：根因：仓库中不存在 staging 目录或代际边界；merge 在线上数据集目录里原地覆盖 posts/comments（run_daily_t1_pipeline.py:243、:297）并立即改写 base binding（:347-359），recompute 再原地覆盖派生集（recompute_derivatives.py:968、:1052、:1097-1098、:1122-1125）。:243 之后的任何失败都留下“新 base + 旧指标”被现网提供。实现：新增 scripts/daily_release_transaction.py，提供 ReleaseGeneration + begin_generation/stage_write/commit/restore/gc。默认复制种子（不用硬链接，因为 write_text 会截断共享 inode）；stage_write 一律 tmp+fsync+os.replace；commit 在代内写完整 current-release.json 后 fsync 文件与目录，再用 os.symlink + os.replace 单次切换 data/reddit-voc 目录项；拒绝覆盖真实目录（generation_live_root_not_symlink）；拒绝 dataset_version 变化（personas/insights 冻结约束）；begin 时检查磁盘 >= 2.5x 现场树；_assert_private 检查 root 不在 live 且所有文件 st_nlink==1。本 ticket 只交付模块与测试，不接流水线。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/daily_release_transaction.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_daily_release_transaction.py`
- **验收**：
  - commit 前后 os.readlink 值整体切换，且目标目录内容来自新代；旧代目录仍完整存在。
  - 在第一次 stage_write 后抛错：无论 commit 是否被调用，live 树与指针字节与运行前完全一致。
  - commit 拒绝把 data/reddit-voc 这个真实目录替换为符号链接（不 rmtree）。
  - 任一 binding 的 dataset_version 与上一代不同 → generation_dataset_version_changed:<key>。
  - gc(keep=2) 删除最老代但不删除当前链接目标；restore 把链接指回上一代且不动新代。
  - 磁盘不足时报 generation_insufficient_disk。
- **测试**：
  - `tests/test_daily_release_transaction.py::test_commit_switches_symlink_atomically`
  - `tests/test_daily_release_transaction.py::test_failed_build_leaves_live_tree_byte_identical`
  - `tests/test_daily_release_transaction.py::test_stage_write_does_not_inherit_live_inode`
  - `tests/test_daily_release_transaction.py::test_commit_refuses_to_replace_real_directory`
  - `tests/test_daily_release_transaction.py::test_commit_rejects_dataset_version_change`
  - `tests/test_daily_release_transaction.py::test_gc_keeps_current_and_previous`
  - `tests/test_daily_release_transaction.py::test_restore_returns_previous_generation`
  - `tests/test_daily_release_transaction.py::test_insufficient_disk_raises`
- **完成定义**：事务模块在 tmp 树上完成 8 个用例；不触碰线上路径；PIPELINE_GENERATION_MODE 尚未接线，仓库行为与今天一致。

#### `L6-T08` 事务接入流水线：step2/3/3.5/4 只写代目录，指针只替换一次

- **严重度**：P0｜**类型**：feature｜**工作量**：L｜**拓扑层**：4
- **依赖**：`L6-T05`, `L6-T06`, `L6-T07`
- **描述**：根因：P2 的爆炸半径来自“写入直接发生在线上树”。实现：新增 PIPELINE_GENERATION_MODE=off|symlink（默认 off，保证代码先上线、行为后启用）。symlink 模式下：collect 之后 begin_generation（在 step2 之前，使 agent-studio 写进新代）；step2_agents 增加 data_root 参数并删除 os.getenv('AGENT_PUBLIC_ROOT')（:118-121）；step3_merge_snapshot 用 release_paths.dataset_dir 解析 base 目录，指针改写写进 data_root/current-release.json；step3_5 调 run_recompute(public_root, data_root=data_root)，binding 同步用 _sync_bindings 写回代内指针；step4 只做内存推进并把 release doc 放入本地 holder；循环结束后 tx.commit(gen, doc)。旧的就地指针写（:356-359、:450-453）全部删除。off 模式保持逐字节等价于今天。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_daily_pipeline_transaction_wiring.py`
- **验收**：
  - symlink 模式下，merge 与 recompute 的所有写入都落在 <generations_root>/<gen>，public_root/data/reddit-voc 在 commit 之前是旧链接。
  - 整次成功运行中，live 的 current-release.json 只被替换一次（对 os.replace 计数 == 1）；7 个 binding 的 SHA 与文件字节一致。
  - 在 recompute 的第二个写盘点抛错：live 树递归 sha256 清单与指针字节与运行前完全一致，回执 status=failed。
  - off 模式跑同一 fixture，输出树与当前 HEAD 行为一致（对比基线快照）。
  - step2 在 symlink 模式下不再读取 AGENT_PUBLIC_ROOT。
- **测试**：
  - `tests/test_daily_pipeline_transaction_wiring.py::test_merge_and_recompute_write_only_into_generation`
  - `tests/test_daily_pipeline_transaction_wiring.py::test_pointer_written_exactly_once_per_run`
  - `tests/test_daily_pipeline_transaction_wiring.py::test_failure_at_recompute_leaves_live_tree_byte_identical`
  - `tests/test_daily_pipeline_transaction_wiring.py::test_generation_mode_off_keeps_legacy_paths`
  - `tests/test_daily_pipeline_transaction_wiring.py::test_agent_studio_written_into_generation`
- **完成定义**：symlink 模式下中途失败不会污染线上代；off 模式行为不变；5 个用例通过；EnvFile 只需一个变量即可切换两种模式。

#### `L6-T09` 通用步骤依赖门禁

- **严重度**：P1｜**类型**：feature｜**工作量**：S｜**拓扑层**：5
- **依赖**：`L6-T08`
- **描述**：根因：步骤循环捕获所有异常后继续（run_daily_t1_pipeline.py:617-622），唯一门禁是 if name == 'advance_pointer' and prerequisite_failures（:602-616）。merge_snapshot 抛错（包括 :332-339 的三个 release guard）时 recompute 仍在被拒绝/半写的 base 上运行，step3.5 仍重写派生绑定。实现：引入 STEP_REQUIRES = {recompute_derivatives: (merge_snapshot,), advance_pointer: POINTER_PREREQUISITES, post_publish_assert: (advance_pointer,)}；依赖状态不在 READY_STATUSES 时追加 {step, status: 'skipped_dependency_failed', failed_dependencies} 并 continue；保留 blocked_by_prerequisites 文案。feishu_push 不设依赖。collect 失败仍允许 merge（按时间窗从既有 SQLite 合并）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_daily_pipeline_gating.py`
- **验收**：
  - merge 抛错时 recompute 未被调用，回执含 skipped_dependency_failed 与 failed_dependencies=['merge_snapshot']。
  - collect 失败但 merge 可恢复时，merge 仍运行（恢复语义不回归）。
  - recompute 出错时 advance_pointer 为 blocked_by_prerequisites，指针不动。
  - 任一失败场景下 feishu_push 仍被执行（能发失败卡）。
- **测试**：
  - `tests/test_daily_pipeline_gating.py::test_recompute_skipped_when_merge_failed`
  - `tests/test_daily_pipeline_gating.py::test_collect_failure_still_allows_merge_recovery`
  - `tests/test_daily_pipeline_gating.py::test_advance_blocked_when_recompute_error`
  - `tests/test_daily_pipeline_gating.py::test_feishu_runs_after_failure`
- **完成定义**：上游失败不再驱动下游写入；4 个用例通过；人工恢复路径（collect 失败→merge）保留。

#### `L6-T10` 失败语义与退出码：非异常失败计入 failed

- **严重度**：P1｜**类型**：fix｜**工作量**：S｜**拓扑层**：5
- **依赖**：`L6-T08`
- **描述**：根因：回执 status 只在 errors 非空时非 success（run_daily_t1_pipeline.py:633），而 errors 只在步骤抛异常时写入（:617-622）。merge_snapshot: skipped_no_release（:178）、advance_pointer: blocked_by_prerequisites（:609-616）、feishu_push: failed_<code>（:529）、skipped_no_credentials（:488）都不会让进程非零退出。实现：定义 STEP_FAILURE_STATUSES = {error, failed, skipped_no_release, skipped_no_manifest, blocked_by_prerequisites, blocked_by_uncovered_window, blocked_pointer_regression, skipped_dependency_failed}；failed_steps 由 receipts 推导；status = success|failed|aborted_already_running；main() 返回 0/1/3。skipped_no_posts、skipped_no_credentials、skipped_by_kill_switch、skipped_already_covered 不算失败。飞书发送失败进 warnings（数据已发布），失败卡自身发不出去才算失败。回执 schema_version 升到 v2。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_daily_pipeline_status.py`
- **验收**：
  - merge_snapshot 返回 skipped_no_release（不抛异常）时 main() 返回非 0，回执 status=failed 且 failed_steps==['merge_snapshot']。
  - agents 返回 skipped_no_posts 时不构成失败（当日无新帖但语料仍可发布）。
  - feishu 发送失败但数据已发布：status=success，warnings 含 send_failed。
  - 回执 schema_version 为 echo_agent_daily_pipeline_receipt_v2。
- **测试**：
  - `tests/test_daily_pipeline_status.py::test_skipped_no_release_is_failure`
  - `tests/test_daily_pipeline_status.py::test_skipped_no_posts_is_not_failure`
  - `tests/test_daily_pipeline_status.py::test_feishu_send_failure_is_warning_when_data_published`
  - `tests/test_daily_pipeline_status.py::test_main_exit_code_nonzero_on_failed`
  - `tests/test_daily_pipeline_status.py::test_receipt_schema_is_v2`
- **完成定义**：“什么都没发布”的运行在 systemd 里是失败态；5 个用例通过；退出码 0/1/3 有明确契约。

#### `L6-T11` 失败告警卡 builder + step5 分支

- **严重度**：P1｜**类型**：feature｜**工作量**：S｜**拓扑层**：6
- **依赖**：`L6-T10`
- **描述**：根因：仓库里没有任何失败卡 builder（grep 只有 build_morning_brief*.py）；失败运行仍会发送一张普通卡（feishu_push 被无条件加入步骤列表 :593-594 且从不检查 errors）。实现：新增 build_failure_card(receipt_doc)->dict（红色 header、失败步骤列表、每条 error 前 200 字、run_id 与工作台链接、note 含 schema_version=echo_agent_pipeline_failure_card_v1），同文件提供 main() 供 systemd OnFailure 调用（--unit %i --output-dir <dir> [--dry-run]）。step5_feishu_push 在 receipt_doc['status'] != 'success' 时改发失败卡，不再发早报卡。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/tools/feishu-card/builders/build_pipeline_failure_card.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_pipeline_failure_card.py`
- **验收**：
  - 失败回执生成的卡片 header.template=='red'，标题含 report_date，正文含每个失败步骤名与 error 前 200 字。
  - 回执 status=success 时 step5 仍发明报卡。
  - CLI --dry-run 输出可解析的卡片 JSON 且不发送网络请求。
- **测试**：
  - `tests/test_pipeline_failure_card.py::test_card_lists_failed_steps_and_error_excerpt`
  - `tests/test_pipeline_failure_card.py::test_card_header_is_red_and_names_run_id`
  - `tests/test_pipeline_failure_card.py::test_cli_dry_run_emits_card`
- **完成定义**：失败运行在飞书上是一条醒目的红色卡；3 个用例通过；systemd 第二通道有可执行入口。

#### `L6-T12` 发布后断言 + 指针回滚

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：6
- **依赖**：`L6-T07`, `L6-T08`, `L6-T10`
- **描述**：根因：流水线步骤只有 collect/agents/merge/recompute/advance/feishu（run_daily_t1_pipeline.py:585-594），没有任何发布后校验；validate_public_site_projection.validate_public_projection（scripts/validate_public_site_projection.py:1247）存在但未接入且依赖 e2e/截图。实现：新增 assert_published_release(public_root, *, expected_release_id=None, expected_run_id=None)，只读已发布树，断言 manifest_binding_sha256、base_generation_binding、brand_health_matches_reports、brand_health_source_reports_sha（当前代或紧邻上一代——producer 的 slot 天然指向上一代 reports，见 recompute_derivatives.py:1087 vs :1107）、quarter_window_conservation、reports_manifest_contract、release_identity。作为 post_publish_assert 伪步骤在 commit 之后运行；失败时 tx.restore(gen) 回滚指针并抛错。冻结数据集只做 binding SHA 校验。前端测试用真实 loader 逐数据集校验（ECHO_PUBLIC_RELEASE_ROOT 门控，只读）。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/assert_published_release.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_assert_published_release.py`
  - `/Users/lute/Project/Echo-Agent/ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/publishedReleaseIntegrity.test.ts`
- **验收**：
  - 一致代树上 7 条断言全过（status=passed）。
  - 篡改 brand-health.json 的 overall.score：brand_health_matches_reports 失败，指针恢复为运行前字节，进程退出码非 0，并生成失败卡。
  - 任一 binding 的 sha 与 manifest 字节不符：manifest_binding_sha256 失败。
  - quarter 的 canonical_dataset_id 与 base binding 版本不符：base_generation_binding 失败。
  - brand-health.source.metrics_manifest_sha256 指向第三代之前的 reports manifest：brand_health_source_reports_sha 失败。
- **测试**：
  - `tests/test_assert_published_release.py::test_all_assertions_pass_on_consistent_generation`
  - `tests/test_assert_published_release.py::test_brand_health_score_must_equal_reports_row`
  - `tests/test_assert_published_release.py::test_manifest_sha_mismatch_fails`
  - `tests/test_assert_published_release.py::test_generation_id_mismatch_fails`
  - `tests/test_assert_published_release.py::test_pointer_restored_on_assertion_failure`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/publishedReleaseIntegrity.test.ts::served_tree_passes_real_loaders`
  - `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/publishedReleaseIntegrity.test.ts::mixed_generation_tree_is_rejected`
- **完成定义**：错误发布在流水线内被自动发现并回滚；5 个 Python 用例与 2 个前端契约用例通过；断言只编码跨文件等式，不复制 L2 公式。

#### `L6-T13` 回执先写后发卡 + public_root 贯通 + verified 语义

- **严重度**：P1｜**类型**：fix｜**工作量**：M｜**拓扑层**：6
- **依赖**：`L6-T04`, `L6-T05`, `L6-T10`
- **描述**：根因：build_card 读取 {run_id}-pipeline-receipt.json（build_morning_brief_v4.py:68），但回执要等步骤循环结束后才写（run_daily_t1_pipeline.py:637-639），而 feishu_push 在循环内执行（:593-594）。任意自然日首次运行时该文件不存在 → FileNotFoundError → 被 :500-501 捕获 → v4 早报静默降级为 legacy v0。同日重跑时文件存在但内容是上一次运行的回执，verified（:254）报告的是上一次状态。step5 还忽略管道传入的 public_root、重读 PIPELINE_PUBLIC_ROOT（:492）。实现：抽出 _build_receipt_doc；发布/断言完成后先写 final=false 回执并作为 receipt_doc 传给 step5；build_card(..., *, receipt=None) 优先用传入值、否则回退读文件；step5_feishu_push 增加 public_root 参数并删除环境变量重读；verified 改为 receipt['status']=='success'；发卡后重写 final=true 最终回执。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tools/feishu-card/builders/build_morning_brief_v4.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_morning_brief_card_receipt.py`
- **验收**：
  - outputs 目录只有三个 agent artifact、没有回执时，build_card 返回 v4 模板（不是 legacy header），且不读取不存在的文件。
  - 同日第二次运行不会把第一次运行的状态当作本次 verified。
  - step5 使用 pipeline 传入的 public_root；用 tmp 根运行时不读生产路径。
  - 回执存在 final=false 与 final=true 两次写入，最终值为 true。
- **测试**：
  - `tests/test_morning_brief_card_receipt.py::test_first_run_builds_v4_card_without_receipt_file`
  - `tests/test_morning_brief_card_receipt.py::test_card_uses_passed_receipt_status`
  - `tests/test_morning_brief_card_receipt.py::test_step5_uses_pipeline_public_root`
  - `tests/test_morning_brief_card_receipt.py::test_verified_requires_success_status`
  - `tests/test_morning_brief_card_receipt.py::test_final_receipt_written_after_feishu`
- **完成定义**：定时运行也能发出 owner 评审过的 v4 早报；“已验证”只在本运行成功时出现；5 个用例通过。

#### `L6-T14` 发布窗口门禁：捕获窗口 + 语料覆盖 + 不回退

- **严重度**：P1｜**类型**：feature｜**工作量**：M｜**拓扑层**：3
- **依赖**：`L6-T03`, `L6-T05`
- **描述**：根因：advance_current_release_to_t1 在调用时重新用 now 计算窗口（advance_daily_t1_release.py:26-36、:50），不使用运行开始时捕获的 window_start/window_end（run_daily_t1_pipeline.py:569）；22:50Z 起跑的人工重跑若跨过 23:00Z 会发布一个从未采集过的窗口。更严重：READY_STATUSES 含 empty_success 与 partial（:379），采集器在 ingested_threads==0 时返回 empty_success（src/reddit_voc/apify_collector.py:237），零 T-1 内容仍会前移指针。实现：拆出纯函数 advance_release_document，显式接收 data_as_of/window_start/window_end/collector_run_id；run_pipeline 原样传捕获值；前移前读合并后 base 计算 observed_max_event_utc（日期精度按当日 23:59:59Z），< window_start 则 status=blocked_by_uncovered_window 且指针字节不动；新 data_as_of < 旧值返回 blocked_pointer_regression；PIPELINE_ALLOW_UNCOVERED_WINDOW=1 只记 warning 且仍不前移。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/advance_daily_t1_release.py`
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_publish_gate.py`
- **验收**：
  - 语料最大事件早于 window_start_utc：advance_pointer 回执 blocked_by_uncovered_window，data_as_of_utc 与指针字节不变。
  - 把 now 固定在跨过 23:00Z 之后：发布的 data_as_of_utc 等于运行开始捕获的 window_end，而不是新墙钟边界。
  - 新 data_as_of 早于现有值时拒绝前移。
  - 07:05 CST 定时场景窗口稳定（window_end == 前一日 23:00Z）。
- **测试**：
  - `tests/test_publish_gate.py::test_advance_blocked_when_corpus_has_no_event_in_window`
  - `tests/test_publish_gate.py::test_window_uses_capture_not_wall_clock`
  - `tests/test_publish_gate.py::test_pointer_never_regresses`
  - `tests/test_publish_gate.py::test_scheduled_run_boundary_is_stable`
  - `tests/test_publish_gate.py::test_allow_uncovered_window_warns_but_does_not_advance`
- **完成定义**：指针不再能宣称未采集的窗口；5 个用例通过；empty_success 不再等价于“数据周期已更新”。

#### `L6-T15` 单写者锁

- **严重度**：P2｜**类型**：feature｜**工作量**：S｜**拓扑层**：1
- **依赖**：`L6-T01`
- **描述**：根因：run_pipeline 没有任何互斥机制（对 run_daily_t1_pipeline.py / recompute_derivatives.py / advance_daily_t1_release.py / lineage.py grep flock/fcntl/lockfile 均无结果）。systemd timer 只覆盖定时运行，人工重跑是常态（10-29 的 19:01 重跑），可能与长跑中的定时运行重叠，两者写同一批数据集与同一个 current-release.json。实现：run_pipeline 在任何写入之前 fcntl.flock(LOCK_EX|LOCK_NB) 锁住 os.getenv('PIPELINE_LOCK_PATH', public_root/'data'/'reddit-voc.lock')——放在 data/ 下、不在代际符号链接内；拿不到锁返回 {status:'aborted_already_running', lock_path}，main() 返回 3，零写入；try/finally 释放。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/scripts/run_daily_t1_pipeline.py`
  - `/Users/lute/Project/Echo-Agent/tests/test_daily_pipeline_lock.py`
- **验收**：
  - 持锁进程存在时第二次 run_pipeline 返回 aborted_already_running、退出码 3，所有 step 调用计数为 0。
  - 第一次运行抛异常后锁被释放，下一次运行可正常获取。
  - 锁文件路径不在 data/reddit-voc 符号链接内部（切换代不影响锁）。
- **测试**：
  - `tests/test_daily_pipeline_lock.py::test_second_run_aborts_before_collect`
  - `tests/test_daily_pipeline_lock.py::test_lock_released_on_failure`
  - `tests/test_daily_pipeline_lock.py::test_lock_path_outside_generation_symlink`
- **完成定义**：并发运行不可能交错写出单次运行从未产生的状态；3 个用例通过；退出码 3 有契约。

#### `L6-T16` systemd unit 入库

- **严重度**：P1｜**类型**：ops｜**工作量**：S｜**拓扑层**：6
- **依赖**：`L6-T10`
- **描述**：根因：systemd unit echo-agent-daily.service 只存在于服务器（docs/audit/radar-metrics-refresh-audit-20261029.md:64），仓库 config/systemd/ 只有 reddit-voc-data-shadow.{service,timer}，OnFailure/Restart/Environment 无法评审或复现。实现：提交三个 unit——service（Type=oneshot、User=ubuntu、UMask=0027、EnvironmentFile=/etc/echo-agent/pipeline.env、ExecStart 指向 scripts/run_daily_t1_pipeline.py 的绝对路径与三个参数、OnFailure=echo-agent-daily-alert@%n.service、TimeoutStartSec=3600）、timer（OnCalendar=*-*-* 07:05:00 Asia/Shanghai、Persistent=true、RandomizedDelaySec=0）、alert@（ExecStart 调用 build_pipeline_failure_card.py CLI）。测试用 configparser(interpolation=None) 解析并断言关键指令，防止有人只改服务器不改仓库。
- **涉及文件**：
  - `/Users/lute/Project/Echo-Agent/config/systemd/echo-agent-daily.service`
  - `/Users/lute/Project/Echo-Agent/config/systemd/echo-agent-daily.timer`
  - `/Users/lute/Project/Echo-Agent/config/systemd/echo-agent-daily-alert@.service`
  - `/Users/lute/Project/Echo-Agent/tests/test_systemd_units.py`
- **验收**：
  - timer 的 OnCalendar 精确为 07:05:00 Asia/Shanghai 且 Persistent=true。
  - service 声明 OnFailure 与 TimeoutStartSec=3600，ExecStart 的脚本路径存在于仓库。
  - alert@.service 的 ExecStart 指向 build_pipeline_failure_card.py 且支持 --unit %i。
  - unit 文件可被 configparser 无插值解析（%i 不报错）。
- **测试**：
  - `tests/test_systemd_units.py::test_daily_timer_schedule_and_persistence`
  - `tests/test_systemd_units.py::test_service_onfailure_and_timeout`
  - `tests/test_systemd_units.py::test_service_execstart_matches_repo_entrypoint`
  - `tests/test_systemd_units.py::test_alert_unit_invokes_failure_card_cli`
- **完成定义**：定时、超时与失败告警定义可在 PR 中评审；4 个解析用例通过；服务器 unit 与新文件逐行一致后才允许 daemon-reload。
