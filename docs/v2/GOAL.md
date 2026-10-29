# V2.0 目标定义（Goal）

## 北极星

> radar.luteos.com 成为业务方可以不经复核直接用于产品与内容决策的可信仪表盘：每个展示值要么能按已发布定义从当日语料复算、要么显式标注不可用及原因，每句判断都由带 inputs/gate 的版本化结论驱动，任何一次无人值守发布失败都会在 30 分钟内红卡告警并保持上一代可服务，而不是让页面继续展示混合代际的旧结论。

---

## 一、KPI 记分卡

| # | KPI | 基线 | 目标 | 度量方式 |
|---|---|---|---|---|
| K1 | **自动刷新断裂天数（无人值守连续成功）** | 断裂 1 天 / 连续无人值守成功 0 天：2026-10-29 07:05 定时运行于 07:17:38 因 PermissionError 失败，当日 19:01 人工重跑才恢复；同日 root 属主问题已出现两次（audit P0-1；run_daily_t1_pipeline.py:49 仍把 run_id 合成为 daily_collect_YYYYMMDD_0700）。 | 断裂 0 天 / 连续无人值守成功 ≥14 个自然日（Asia/Shanghai）：每日 07:05 运行 status=success、run_kind=scheduled、run_id 每日唯一、人工干预 0 次。 | 扫描 /opt/echo-agent-bot/outputs/*-pipeline-receipt.json，按 report_date 取最近 14 天，断言 status=='success' && run_kind=='scheduled' && run_id 两两不同；输出 /opt/echo-agent-bot/outputs/closure/unattended-streak.json。单条自动检查：jq -e '[.days[]] \| length==14 and all(.status=="success" and .run_kind=="scheduled")' unattended-streak.json。CI 对应 pytest tests/test_run_identity.py::test_two_runs_get_distinct_ids_and_receipts tests/test_daily_pipeline_status.py::test_main_exit_code_nonzero_on_failed -q。L6-T05 落地前 run_kind 不存在，该 KPI 记为未测量。 |
| K2 | **混合代际发布暴露时长** | 约 732 分钟（2026-10-29 07:17:38 merge 后失败至 19:30 恢复）：新 base 已写入 live 树、pointer 仍指向旧报告，站点呈现『新 base + 旧指标』（audit P0-1；run_daily_t1_pipeline.py:243/297/347 原地改写）。 | 0 分钟：失败构建对 live 树零字节改动，pointer 每次运行只写一次。 | 故障注入（merge 成功后、recompute 前抛错）后用 diff -r 比较运行前快照与 live 树，断言 0 差异、pointer sha256 不变、receipt status=failed；pytest tests/test_daily_pipeline_transaction_wiring.py::test_failure_at_recompute_leaves_live_tree_byte_identical tests/test_daily_release_transaction.py::test_commit_switches_symlink_atomically -q；产物 /opt/echo-agent-bot/outputs/wave1/failure-injection-receipt.json {live_tree_diff:[], pointer_sha_before==pointer_sha_after}。单条自动检查：len(live_tree_diff)==0。 |
| K3 | **硬编码判断句数量（审计点名禁语）** | 9 处：8 条审计点名禁语在 4 个组件的出现次数（BrandHealthSnapshotCard.tsx 1、SnapshotInsightsV3.tsx 3、SnapshotDashboard.tsx 3、OperationalReportSupplement.tsx 2；audit P1-3）。 | 0 处：四个组件的业务判断句全部改为 conclusions[] 查表渲染，TSX 只保留静态方法说明。 | cd ref/UI/momcozy-reddit-workbench && grep -rnE '四维差异明显\|需将优势与短板分开管理\|优先级高于适配舒适度\|操作与可靠性是当前最大的体验摩擦\|适配舒适度与泌乳输出紧随其后\|构成问题库\|不把家族证据冒充\|净情感差' src --include='*.tsx' \| wc -l，断言输出 0。单条自动检查：npm test -- noHardcodedJudgements.test.ts（src/features/redditSnapshot/__tests__/noHardcodedJudgements.test.ts::no banned judgement phrase remains in the four conclusion components）。 |
| K4 | **结论句数据化覆盖率** | 0%：conclusions[] 尚不存在，页面业务判断句由 TSX 模板直接生成（audit P1-3；L3-T02/T03/T04/T05 未实现）。 | 100%：/dashboard、/dashboard/reports、/dashboard/insights 的每条业务判断句（summary/解释/行动/决策入口槽位）携带 conclusion_id，DOM 文本与 render(template_id, inputs) 逐字相等，orphan=0。 | node scripts/playwright_daily_release_e2e.js --scan conclusions（L3-T12）输出 /opt/echo-agent-bot/outputs/closure/conclusion-scan.json {pages:3,sentences:N,orphans:0}；pytest tests/test_conclusions.py::test_template_render_round_trip_matches_sentence tests/test_conclusions.py::test_conclusion_ids_unique_and_versioned_per_dataset -q；vitest conclusions.test.ts::same dataset version yields byte-identical sentences across pages。单条自动检查：jq -e '.pages==3 and .orphans==0' conclusion-scan.json。 |
| K5 | **数据集内部可自证新鲜度比例** | 0/7：release 绑定的 7 个数据集（base/insights/reports/personas/brand_health/quarter_insights/casebook，release.ts:7-9）均无 build.json；brand-health manifest 无 generated_at_utc；base generated_at 不随运行推进（L5-T02/T14/T15 未实现）。 | 7/7：每个数据集目录有 build.json，manifest_sha256 == sha256(manifest bytes)，run_id == 当次 pipeline run_id。 | find /opt/voc-report/html/data/reddit-voc -name build.json \| wc -l，断言 7；python scripts/check_site_freshness.py --once --json 输出 {datasets:7,receipt_ok:7,manifest_sha_mismatch:0} 且 exit 0；pytest tests/test_build_receipt.py::test_stamp_manifest_sha_matches_manifest_bytes tests/test_pipeline_build_receipts.py::test_pipeline_writes_stamp_for_every_release_dataset -q。单条自动检查：check_site_freshness exit==0 && receipt_ok==7。 |
| K6 | **跨页数值一致断言通过率** | 2/8。通过：①/dashboard 治理范围 25,873 帖/100,778 评论 == canonical_counts；②insights 季度 20,741 帖/755 VOC == quarter_insights。失败：③完整度四档合计 9,982 ≠ 25,873（source_observed 15,891/61.4% 被 governance/contracts.ts:123-133 丢弃）；④/reports periodBrandHealth=null ≠ /dashboard 75.42（producer 只写 score，reports.ts:696-700 要求 value/display）；⑤品牌健康样本 2,280 ≠ 投影 1,136+2,289=3,425（SnapshotDashboard.tsx:516 客户端 isMomcozyPost 估算）；⑥画像 8×0.00% ≠ quarter cohort 755；⑦月报环比 -97.7% ≠ +23.5%（recompute_reports_bundle.py:123-131 对 monthly 用 start-1day）；⑧周报周期结束 2026-10-29 ≠ 2026-10-26（SnapshotReports.tsx:614 绑定 index.as_of_date）。 | 8/8 全绿：每个数字要么按定义复算，要么显式 unavailable+reason_code。 | L6-T12 发布后断言（scripts/assert_published_release.py，测试 tests/test_assert_published_release.py）输出 /opt/echo-agent-bot/outputs/<run_id>-publish-assertions.json，checks[] 固定为上述 8 条，all_pass=true 且 exit 0；浏览器侧 Playwright 读取 DOM 复算 ④⑤⑥⑦⑧ 的渲染值。单条自动检查：jq -e '.checks\|length==8 and all(.pass)' publish-assertions.json。 |
| K7 | **用户画像真实覆盖率** | 8/8 组均显示 0.00% · 0 条，页面仍标『合计 100.00%』；quarter_insights 实际 cohort 合计 755。根因：每日 assignment_id=sha256(kind:post_id:comment_id:topic)（recompute_derivatives.py:582-583）与 persona 快照的 canonical JSON 身份（v3_persona_inference.py:1694-1708）交集=0（audit P0-2）。 | Wave 1：按 quarter cohort 计数渲染 320/77/91/80/0/0/187/0，合计 755 且显示 100.00%，任何 count>0 的组不得显示 0.00%；Wave 4：persona-tags 证据与 quarter assignment 的 voc_id 交集 >0，八组计数与 quarter 守恒。 | Playwright 读取 /dashboard/insights#user-personas 的 8 个 cohort 行，断言 sum(count)==755 && sum(pct)==100.00 && 每个 count>0 的行 pct>0；vitest AggregatePersonaPanel.test.tsx::renders quarter cohort counts when the persona assignment id space is disjoint；桥接后 pytest tests/test_quarter_persona_scope.py::test_main_voc_ids_use_persona_namespace -q；产物 /opt/echo-agent-bot/outputs/wave1/personas-panel.json。单条自动检查：sum(count)==755。 |
| K8 | **缺失构建发现时延** | 未接入监控；2026-10-29 07:17:38 失败至 19:01 人工重跑，发现/恢复时延约 11 小时 43 分钟，期间无自动告警（audit P0-1）。 | ≤30 分钟（07:35 Asia/Shanghai 截止后），红色卡片、按状态转移去重、每日 1 次心跳。 | 在 staging 副本删除 1 个 build.json，07:35 后运行 python scripts/check_site_freshness.py --once，断言 exit==2、state=='stalled'、alert_sent==true、card.header.template=='red'；pytest tests/test_check_site_freshness.py::test_missing_build_receipt_after_deadline_is_stalled tests/test_check_site_freshness.py::test_alert_is_deduped_per_state_transition -q；产物 /opt/echo-agent-bot/outputs/closure/monitor-drill.json。单条自动检查：drill.detected_within_minutes <= 30。 |
| K9 | **打开页面发布收敛时间** | 永不收敛：release.ts:381-382 releasePromise、service.ts:103-106 summary/core/comments/insights、brandHealth.ts:267 brandHealthCache 均为模块级单例，跨 07:05 发布必须手动 F5（audit P2）。 | ≤10 分钟或标签页重新聚焦时自动收敛；pointer 请求合并为 1 次；首次请求被拒绝后下一次调用重试。 | Playwright 双上下文演练：保持 /dashboard 打开，替换 pointer.generated_at_utc 后不 reload，断言 600s 内 data_as_of 更新且 pointer 请求数==1；vitest useReleaseAwareData.test.tsx::loads on mount, refetches when the tab becomes visible, and polls on the interval + release.test.ts::refetches the pointer after the TTL and keeps the same release object when the generation is unchanged；产物 /opt/echo-agent-bot/outputs/closure/cache-convergence.json。单条自动检查：converged_without_reload==true。 |
| K10 | **评论证据单帖传输量** | 约 200MB/次：/dashboard/search 打开证据需下载 comments-public.json 全量（audit §4.5）。 | ≤3 个 Range 请求/帖、0 次全量 GET、单帖传输 ≤1MB；索引缺失时回退全量且内容 sha 一致。 | Playwright 打开一条证据并记录 network log，断言 full_gets==0 && range_requests<=3 && transferred_bytes<=1048576；pytest tests/test_comments_index.py::test_range_count_per_post_at_most_three tests/test_comments_index.py::test_ranges_slice_exact_rows -q；vitest service.test.ts::fetches only the byte range for a post when comment_index is present；产物 /opt/echo-agent-bot/outputs/wave5/comment-range-proof.json。单条自动检查：full_gets==0 && range_requests<=3。 |
| K11 | **审计头条缺陷关闭率（程序完成度）** | 0/7：P0-1 自动刷新断裂、P0-2 画像 0.00%、P0-3 topic 当 SPU、P1-1 完整度漏计 61.4%、P1-2 月报环比跳月、P1-3 结论硬编码、P2 缓存永不失效，均无 V2.0 关闭证据。 | 7/7：每项由至少一个命名通过的测试关闭；77 项 canonical 问题中 P0/P1 100% 测试关闭，P2/P3 关闭或记录 owner+due。 | 新增 tests/test_audit_closure.py 读取 docs/audit/v2-closure-matrix.json：每条 {audit_id,ticket_id,test_node_id,status,owner,due}；断言 P0/P1 status=='closed' 且 test_node_id 可被 pytest --collect-only 解析并在完整套件中通过；输出 /opt/echo-agent-bot/outputs/closure/audit-closure-matrix.json。单条自动检查：jq -e '[.items[]\|select(.severity=="P0" or .severity=="P1")]\|all(.status=="closed")'。 |

---

## 二、里程碑与退出闸门

### M1-W1 — 止血：可信发布、失败可见、缓存收敛（Wave 1）

**退出闸门**：在 10-28 冻结数据集仍通过原 SHA 校验的前提下：①chmod 0400 目标文件后运行在 step1 之前 exit=2 且零写入；②merge 后注入异常，live 树与 pointer 字节级不变、receipt=failed、Feishu 红卡点名失败步骤且不出现『已验证』；③成功运行 pointer 恰好替换一次，7 个 binding SHA 与字节一致；④同日两次运行 run_id/receipt 不同、release_id 前进、collector_run_id==pipeline run_id；⑤并发第二次运行 exit=3 aborted_already_running 且锁释放；⑥打开中的 /dashboard ≤10 分钟或聚焦时自动收敛；⑦attested reports bundle 字节不变、38 个孤儿 history 归档不删除；⑧/dashboard/insights#user-personas 显示 320/77/91/80/0/0/187/0 且合计 100.00%，非零组不显示 0.00%；⑨Wave-1 pytest + npm build + cache vitest 离线全绿。

**证明物**：
- /opt/echo-agent-bot/outputs/wave1/preflight-readonly.json — chmod 0400 后 exit=2 pipeline_preflight_unwritable_targets，step1_collect 未运行，pointer sha256 不变
- /opt/echo-agent-bot/outputs/wave1/failure-injection-receipt.json — status=failed, failed_step=recompute, live_tree_diff=[], pointer_sha_unchanged=true
- /opt/echo-agent-bot/outputs/wave1/feishu-failure-card.json — header.template=red，标题含 run_id 与失败步骤，正文无『已验证』
- /opt/echo-agent-bot/outputs/wave1/double-run.json — 同日两次 run_id 不同、receipt 文件不同、freshness.collector_run_id==pipeline run_id、release_id 前进
- /opt/echo-agent-bot/outputs/wave1/lock.json — 并发第二次 exit=3 aborted_already_running，零写入，异常后锁释放
- /opt/echo-agent-bot/outputs/wave1/cache-convergence.json — 600s 内 data_as_of 更新，pointer 请求合并为 1
- /opt/echo-agent-bot/outputs/wave1/attested-reports-sha.txt — comparison_contract_proven=true bundle 字节不变；38 个孤儿 history 移入 archive/ 非删除
- /opt/echo-agent-bot/outputs/wave1/personas-panel.json — 320/77/91/80/0/0/187/0，合计 100.00%
- pytest node ids: tests/test_daily_pipeline_preflight.py::test_rejects_readonly_file_in_writable_dir；tests/test_daily_pipeline_transaction_wiring.py::test_failure_at_recompute_leaves_live_tree_byte_identical；tests/test_daily_pipeline_lock.py::test_second_run_aborts_before_collect；tests/test_run_identity.py::test_two_runs_get_distinct_ids_and_receipts；tests/test_morning_brief_card.py::test_card_is_red_and_unverified_when_receipt_status_is_partial；tests/test_recompute_reports_guard.py::test_attested_manifest_is_skipped
- vitest node ids: AggregatePersonaPanel.test.tsx::renders quarter cohort counts when the persona assignment id space is disjoint；release.test.ts::refetches the pointer after the TTL and keeps the same release object when the generation is unchanged；useReleaseAwareData.test.tsx::loads on mount, refetches when the tab becomes visible, and polls on the interval

### M2-W2 — 数字口径：每个数字按定义计算或显式不可用（Wave 2）

**退出闸门**：①月报锚定 2026-10-29 时基线为 monthly:2026-08-01:2026-09-01，六期连续且 8 月环比 +23.5%，跳月即失败；②RV-BR-05/04 保持注册表身份并标 unavailable+reason_code，页面永不出现『净情感差』；③GEO ranking ids ⊂ {competitor_comparison,purchase_decision}，comparison_decision_posts==distinct decision posts（2 帖×2 竞品=2 不是 4）；④new_product rankings 只含 product_binding ids，零绑定→unavailable 空榜，产品家族读 family_rankings；⑤15:59:59Z 属 10-28、16:00:00Z 不属，reports/quarter/client 对上海业务日一致；⑥数据范围显示 933/1,094/7,955/15,891 且合计 25,873，fixture 减一即守恒失败；⑦新行 Momcozy S9 Pro→family s9-pro，评论 include_in_voc_metrics=null+governed-pending，post aspect_tag_ids 非空，record_authority=governed_base，is_bot 为 null 或 detection_status 显式；⑧品牌健康 sample 1,136 帖/2,289 评论/3,425 VOC，report row 有 value/display/status，periodBrandHealth 非 null 且与 overall 一致；⑨eufy+eufy S1 合一（797），50+ 竞品 id 可解析，三种评论分母展示，16,822 不再被称为分析分母；⑩aggregates 发布 observation_window 且页面警示『含边界后 X 帖/Y 评论』；⑪Wave-2 pytest + npm build + vitest 全绿，四个 exact-key 校验器双形态兼容。

**证明物**：
- /opt/echo-agent-bot/outputs/wave2/publish-assertions.json — 8/8 cross-page checks pass（见 K6）
- reports bundle manifest — monthly period_id=monthly:2026-08-01:2026-09-01，period_chain 连续 6 期，MoM=+23.5%
- brand-health.json — dimensions[].definition{formula_id,numerator_scope,denominator_scope,grain_weighting,is_proxy,proxy_for}；overall_score_basis=half_up_mean_of_axes；overall_score_derived_from_axes=true；sample{post_vocs:1136,comment_context_vocs:2289,classified_vocs,total_vocs:3425}
- quarter_insights.json — new_product.rankings[].id ⊂ product_bindings ids；family_rankings 独立；零绑定 → status=unavailable + reason_code=no_product_bindings
- reports bundle — RV-BR-05/RV-BR-04 status=unavailable + reason_code；无 unit=percent 且 name_cn=竞品语境占比 的行
- aggregates — observation_window{data_as_of_utc,observation_max_utc,events_after_data_as_of{posts:52,comments:255}}
- browser assertions — /dashboard 四档 933+1,094+7,955+15,891=25,873；/dashboard/reports 无『净情感差』；周报周期结束=2026-10-26
- pytest node ids: tests/test_recompute_reports_bundle.py::test_monthly_previous_period_is_immediately_preceding_month；tests/test_recompute_reports_bundle.py::test_rv_br_05_is_unavailable_not_redefined；tests/test_recompute_derivatives_metrics.py::test_new_product_rankings_use_product_bindings；tests/test_brand_health_lean.py::test_dimension_carries_definition_and_proxy_flags；tests/test_site_aggregates.py::test_headline_publishes_comment_populations

### M3-W3 — 溯源与监控：工件自证、血缘可解引用、缺失可告警（Wave 3）

**退出闸门**：①7/7 release 数据集有 build.json 且 manifest_sha256==sha256(bytes)，缺回执 exit=2 build_stamp_missing:<key>；②brand-health.source.reports_manifest_sha256==sha256(final reports manifest)，quarter 同，finalize 幂等；③deterministic_full_byte_replay 仅在两次构建字节相同时为 true，模板字节变更→false 且发布前失败；④无字面 replay True / boundaries False，boundaries=true，客户端复算 overall==half-up mean；⑤每个 source slot 哈希其名称声称的工件，缺失 metrics 数据集 fail-closed，无 sha256(b'') 回退；⑥monitor：stalled→exit 2 红卡，healthy→exit 0 心跳，partial→not fresh，同状态去重；⑦四个 T-1 调用点在 8,760 个整点样本上一致（含 2026-10-30T00:30+08:00）；⑧未覆盖窗口→blocked_by_uncovered_window 且 data_as_of 不变，窗口用捕获时间而非墙钟；⑨base generated_at 前进，lineage_mode 存在，lineage_manifest_sha256 哈希日更 lineage，quarter source 无 governed_signal_*；⑩casebook review_due=generated_at+180d，operations 视图显示逾期徽标，周链 30/7/0 天告警；⑪freshness bar 显示数据年龄+观测边界警示，chip 写 manifest-hash verified，Agent Studio 显示真实时间且无『每日 07:05』。

**证明物**：
- 7 × /opt/voc-report/html/data/reddit-voc/<dataset>/build.json — {schema_version:'echo_agent_build_receipt_v1',run_id,manifest_sha256,generated_at_utc}，manifest_sha256==sha256(manifest bytes)
- /opt/echo-agent-bot/outputs/<run_id>-pipeline-receipt.json schema v2 — build_receipts[] 覆盖 7 个 release dataset
- /opt/echo-agent-bot/outputs/freshness/freshness-<date>.json — {state:'stalled',deadline:'07:35',alert_sent:true,detected_within_minutes:<=30}
- /opt/echo-agent-bot/outputs/closure/monitor-drill.json + feishu-card-red.json — header.template=red，deduped
- pytest node ids: tests/test_build_receipt.py::test_stamp_manifest_sha_matches_manifest_bytes；tests/test_lineage_finalization.py::test_brand_health_cites_final_reports_manifest_sha；tests/test_reports_bundle_validation.py::test_replay_flag_is_false_when_a_template_byte_changes；tests/test_brand_health_boundary.py::test_overall_equals_half_up_mean_of_four_dimensions；tests/test_check_site_freshness.py::test_missing_build_receipt_after_deadline_is_stalled
- browser assertions — /cases operations 视图显示 dossier 复核到期与逾期徽标；/dashboard freshness chip 文案为 manifest-hash verified 而非『数据新鲜』；Agent Studio 显示 artifact generated_at_utc，无『每日 07:05』

### M4-W4 — 结论与画像：判断句数据化，画像回到当前语料（Wave 4）

**退出闸门**：①3 个页面上每条业务判断句解析到 conclusion_id，DOM 文本==sentence，全站 Playwright 扫描 orphan=0；②100% conclusions 满足 render(template_id,inputs)==sentence，手改失败；③排名翻转：无自比、无残留第二/第三名、无 Unspecified/None Observed；④21-VOC 月报零建议通过、显式样本不足提示、低样本标记可读；⑤零 drivers 不生成祈使/行动句；⑥缺失输入→『不可用+reason_code』，有效时品牌健康句存在，不静默消失；⑦/dashboard/insights 在 insights 500 时仍渲染 quarter headline+痛点排名+provenance warning，无 SnapshotErrorPage、无字面 78 计数门禁；⑧周级 personas 链：served base manifest SHA==canonical base SHA、validator passed、chain receipt ok、14 文件跨运行字节一致、部署清单完整；⑨被服务 personas 数据集通过自身 validator，无未声明 lineage/ 文件，quarter 引用真实 personas 回执或 L4 接受的显式 pending；⑩insights 在点击『加载证据』前加载 0 字节 persona-tags，点击后恰好 1 次请求，八组份额==quarter payload 且标 period-scoped；⑪双形态接受：conclusions 缺失→旧文案渲染，存在→严格校验，skew 期间无 500。

**证明物**：
- quarter_insights.json / brand-health.json / reports bundle conclusions[] — 每条 {conclusion_id,template_id,inputs,gate,sentence,dataset_version}，覆盖所有必需槽位
- /opt/echo-agent-bot/outputs/weekly/personas-chain-receipt.json — base_manifest_sha256==served base manifest sha，validator passed，14 files 跨运行字节一致
- /opt/echo-agent-bot/outputs/closure/conclusion-scan.json — {pages:3,sentences:N,orphans:0,banned_phrases:0}
- /opt/echo-agent-bot/outputs/wave4/insights-500-drill.json + .png — insights HTTP 500 时页面仍渲染 quarter headline+痛点排名+provenance warning，无 SnapshotErrorPage
- pytest node ids: tests/test_conclusions.py::test_template_render_round_trip_matches_sentence；tests/test_conclusions.py::test_zero_observed_never_emits_directive；tests/test_weekly_personas_chain.py::test_chain_receipt_binds_base_manifest；tests/test_quarter_persona_scope.py::test_main_voc_ids_use_persona_namespace
- vitest node ids: SnapshotInsightsV3.test.tsx::renders theme sentences verbatim from quarter conclusions；SnapshotReportsV3.test.tsx::monthly 21-VOC bundle renders the sample-insufficient notice and no advice

### M5-W5 — 覆盖与规模化：评论按需、历史回填、遗留清理（Wave 5）

**退出闸门**：①评论索引：1 帖 ≤3 个 Range 请求、0 次全量 GET、评论==单文件、坏 shard 拒绝、回退可用；②insights 总 JSON <1MB、不请求 posts-public；③历史回填幂等（二次运行 0 字节变更）、逐行 dictionary_version、单独提交；④同比要么 7 日代理 provisional 要么删除『7 日替代窗口』文案，无『承诺代理却显示 dash』的格子；⑤证据陈旧按 data_as_of 判定，1 天前且语料未变的链接不告警；⑥所有 P3 项有测试关闭或 owner+date 延期；⑦离线 3 帖/2 评论夹具在 CI 端到端发布，故障注入后上一代仍可服务；⑧retention 保留 current+previous generation 与 30 份回执，gc 永不删除 live target。

**证明物**：
- /opt/echo-agent-bot/outputs/wave5/comment-range-proof.json — {range_requests:<=3,full_gets:0,transferred_bytes:<=1048576,sha_match:true}
- /opt/echo-agent-bot/outputs/wave5/backfill-receipt.json — rerun_delta_bytes=0，rows_with_dictionary_version=100%，separate commit
- pytest node ids: tests/test_comments_index.py::test_ranges_slice_exact_rows；tests/test_comments_index.py::test_range_count_per_post_at_most_three；tests/test_daily_pipeline_harness.py::test_end_to_end_publish_on_fixture_corpus
- vitest node id: service.test.ts::fetches only the byte range for a post when comment_index is present
- /opt/echo-agent-bot/outputs/wave5/retention-list.json — current+previous generation、30 receipts，gc 未删除 live target
- browser assertions — /dashboard/insights 总 transfer <1MB 且无 posts-public.json 请求；/dashboard/search 证据打开 full_gets=0

### M6-CLOSURE — 闭环：连续 14 天无人值守全绿并签收

**退出闸门**：连续 14 个自然日（Asia/Shanghai）的 07:05 无人值守发布全部成功、零人工干预、零混合代际；窗口内 ≥2 次周级 personas 链、≥1 次月报 rollover；K1–K11 全部达到 target；审计 7 项头条缺陷 7/7 由命名测试关闭，77 项 canonical 问题 P0/P1 100% 关闭、P2/P3 关闭或 owner+due；owner 在 docs/audit/v2-closure-signoff.md 签收。

**证明物**：
- /opt/echo-agent-bot/outputs/closure/unattended-streak.json — 14/14 status=success, run_kind=scheduled, run_id 唯一, report_date 连续, manual_interventions=0
- /opt/echo-agent-bot/outputs/closure/kpi-snapshot.json — K1–K11 全部达到 target 并带测量值/测量时间
- /opt/echo-agent-bot/outputs/closure/build-receipt-audit.json — 7/7 manifest_sha256==sha256(bytes)
- /opt/echo-agent-bot/outputs/closure/conclusion-scan.json — pages=3, orphans=0, banned_phrases=0
- /opt/echo-agent-bot/outputs/closure/personas-chain-2x.json — 2 次连续周链，base_manifest_sha256 匹配，14 文件跨运行字节一致
- /opt/echo-agent-bot/outputs/closure/monitor-drill.json — 07:35 后 ≤30 分钟红卡、去重、exit=2
- /Users/lute/Project/Echo-Agent/docs/audit/v2-closure-matrix.json — 7/7 头条缺陷 test-closed；77 项 canonical 问题 P0/P1 100% closed，P2/P3 closed|deferred+owner+due
- /Users/lute/Project/Echo-Agent/docs/audit/v2-closure-signoff.md — owner 签收与日期

---

## 三、闭环定义

闭环 = 在最后一次代码/配置/部署变更之后，连续 14 个自然日（Asia/Shanghai）的 07:05 无人值守发布会话全部为绿，且以下 A–E 五组信号在每一天、每一份被服务工件上都成立；14 天中任何一次人工重跑、手改 pointer、手工修权限/文件、任一页面出现无法从被服务数据集复算的数字、或监控在失败时沉默，都立即重置连续计数。A 发布链：每份 pipeline receipt status=success、run_kind=scheduled、run_id 唯一；pointer 每次运行恰好写一次，release_id 前进，collector_run_id==pipeline run_id；7/7 release 数据集 build.json 的 manifest_sha256==sha256(manifest bytes)；故障注入证明失败运行对 live 树零字节改动。B 数字：assert_published_release 的 8/8 跨页断言通过；完整度四档合计==canonical_counts.posts；品牌健康 sample==投影 sample（1,136 帖+2,289 评论=3,425 VOC 基线）；月报环比基线==上一个完整自然月（14 天窗口须至少跨过一个月末）；所有 unavailable 指标带 reason_code，页面无裸 0、无同名改义。C 结论：/dashboard、/dashboard/reports、/dashboard/insights 的 Playwright conclusion_identity_scan 结果 pages=3、orphans=0、banned_phrases=0；100% conclusions 满足 render(template_id,inputs)==sentence；排名翻转、样本不足、输入缺失三种演练均输出一致或显式不可用。D 画像与数据集：窗口内 ≥2 次周级 personas 链均绑定被服务 base 的 manifest SHA、通过真实 validator、14 个文件跨运行字节一致；/dashboard/insights#user-personas 八组计数合计 755 且 100.00%；insights 返回 500 时页面仍渲染 quarter 结论；casebook 逾期徽标可见；tag-dictionary 版本/校验和前缀可见。E 监控：freshness monitor 每日心跳 1 次且全绿；一次 staging 演练在 07:35 截止后 ≤30 分钟发出红色卡片、按状态转移去重、exit=2。另需：审计 7 项头条缺陷 7/7 由命名通过的测试关闭；77 项 canonical 问题中 P0/P1 100% 测试关闭，P2/P3 关闭或记录 owner+due；owner 在 docs/audit/v2-closure-signoff.md 签收。以上全部满足才算闭环；任一不满足即未闭环。