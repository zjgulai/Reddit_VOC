# radar.luteos.com 指标与结论自动刷新 V2.0 方案

- 版本：V2.0（基于 2026-10-29 深度审计，248 项检查 / 16 项修正）
- 语料基线：25,873 帖 / 100,778 关联评论，`data_as_of_utc=2026-10-28T23:00:00Z`
- MECE 归并：78 项输入问题 → 77 项 canonical（L1=15, L2=16, L3=6, L4=18, L5=10, L6=12）
- 票据总量：105 张

---

## 一、MECE 归属论证

**切分规则（工件接缝）**：L1 拥有语料/数据集字节与生产者前置条件；L2 拥有 quarter_insights / brand_health / reports 的**数值**；L3 拥有**结论句文本**、inputs 与门禁；L4 拥有 React 消费端、加载器、缓存、校验器、标签、渲染；L5 拥有构建回执、时间戳、血缘校验与新鲜度监控；L6 拥有编排、锁、preflight、代际事务、退出码、run 身份、发布后断言。

> 一个车道可以**引用**另一车道的契约，但不能**拥有**那次编辑。

### 被吸收的 4 处重复（每项单一归属）

| 原归属 | 迁往 | 理由 |
|---|---|---|
| L2-P5（coverage source_observed） | **L4** | 同一缺陷同一修法（`governance/contracts.ts:123-133`；`service.ts:1463` 已有四档守恒断言），L2-R5 删除 |
| L4-P13（硬编码判断句） | **L3** | 同一批代码行（`BrandHealthSnapshotCard.tsx:94`、`SnapshotInsightsV3.tsx:110/123-124`、`SnapshotDashboard.tsx:166`），L3 拥有句子文本，L4 只留查表接线 |
| L5-P5（collector_run_id 标签） | **L6** | 同一缺陷（`run_daily_t1_pipeline.py:49`；`advance_daily_t1_release.py:63`），L5-R2 删除 |
| L5-P12（缓存永不失效） | **L4** | 同一缺陷（`release.ts:380-383`；`service.ts:103-106/1481-1489`；`brandHealth.ts:267`） |

### 六车道问题分布

| 车道 | 问题数 | P0 | P1 | P2 | P3 | 票据数 |
|---|---|---|---|---|---|---|
| L1 — 数据生产层 (Data Production) | 13 | 1 | 7 | 4 | 1 | 14 |
| 计算正确性层 (Computation Correctness) | 16 | 3 | 9 | 3 | 1 | 20 |
| L3 — 结论生成层（Conclusion Generation） | 7 | 0 | 5 | 2 | 0 | 13 |
| L4 — 交付与消费层 (Delivery & Consumption) | 18 | 2 | 11 | 2 | 3 | 26 |
| 可观测与治理层 (Observability & Governance) | 12 | 2 | 6 | 4 | 0 | 16 |
| 运行可靠性层 (Runtime Reliability) | 12 | 2 | 8 | 1 | 1 | 16 |

---

## 二、五波执行划分

### Wave 1 — 止血：可信发布、失败可见、缓存收敛

**车道**：L6 — 运行可靠性层 (Runtime Reliability), L5 — 可观测与治理层 (Observability & Governance), L4 — 交付与消费层 (Delivery & Consumption), L1 — 数据生产层 (Data Production)

**目标**：Tickets: L6-R11 lock, L6-R1 file-level preflight, L6-R9 real run_id + release_id, L6-R2 generation dir + atomic symlink swap (fallback: deferred base visibility), L6-R3 dependency gate, L6-R5 binding whitelist, L6-R6 minimal manifest-SHA assertion + rollback, L6-R8 failure status/exit codes/systemd; L5-R4 card verified==success + red header; L4-R1 release-keyed cache + TTL + rejection eviction + pointer-first reload; L4-R6 minimal cohort-count rendering + honest badge; L1-R7 attested-reports guard. Goal: unattended failure cannot publish silently, mixed-generation serving is structurally impossible, open browsers converge without F5, and the two ongoing lie/data-loss defects stop.

**退出标准**：

- chmod 0400 on posts-public.json -> run fails with pipeline_preflight_unwritable_targets before step1_collect; step1 count 0; pointer sha unchanged.
- Raise after merge, before recompute -> live tree and pointer byte-identical; status=failed; red failure card names the step; no '已验证'.
- Successful run replaces current-release.json exactly once; all 7 dataset manifest SHAs match their bytes; frozen personas/insights/casebook bindings unchanged.
- Two same-day runs get distinct run_id and receipt files; freshness.collector_run_id == pipeline run_id; release_id advances.
- Concurrent second run exits 3 aborted_already_running, zero writes, lock released after exception.
- Open /dashboard tab converges within 10 min or on focus; one coalesced pointer request; rejected first fetch retried.
- Attested reports bundle (comparison_contract_proven=true) stays byte-identical; receipt says skipped_attested_dataset; 38 orphan history files archived, not deleted.
- /dashboard/insights#user-personas shows 320/77/91/80/0/0/187/0 summing to 100.00%; no non-zero cohort shows 0.00%; badge only when denominator known.
- Wave-1 pytest + npm build + cache vitest green without network.

### Wave 2 — 数字口径：每个数字要么按定义计算，要么显式不可用

**车道**：L2 — 计算正确性层 (Computation Correctness), L1 — 数据生产层 (Data Production), L4 — 交付与消费层 (Delivery & Consumption)

**目标**：Tickets: L2-R1 monthly baseline, L2-R2 RV-BR-05/04 unavailable + independent competitor_context_share, L2-R3 product_binding rankings, L2-R4 canonical GEO, L2-R6 sample counts, L2-R7 dimension definitions + product-bound/50-50 + proxies, L2-R8 report brand_health rows, L2-R9 bot count order + moderation unavailable, L2-R10 shared event_business_date, L2-R11 brand normalization, L2-R12 observation_window, L2-R13 YoY, L2-R14 rolling window, L2-R15 comment denominators, L2-R16 cohort mapping; L1-R4 tag new rows/eligibility/dictionary, L1-R5 product bindings, L1-R12 record_authority, L1-R13 content_entity containment, L1-P14 is_bot producer; L4-R7/R8/R9/R10/R14/R15/R17/R18 consumer fixes. Goal: every number either matches its definition or says unavailable with a reason.

**退出标准**：

- Monthly anchor 2026-10-29 -> baseline monthly:2026-08-01:2026-09-01; six consecutive period_ids; Aug 17/Sep 21 -> +23.5%; skipped month raises.
- RV-BR-05 unavailable with reason code (or canonical pair difference); no row with unit=percent and name_cn=竞品语境占比; frontend never says '净情感差'.
- GEO rankings ids subset of {competitor_comparison, purchase_decision}; comparison_decision_posts == distinct decision posts (112); 2 posts x 2 competitors = 2, not 4.
- new_product rankings contain only product_binding ids; zero quarter bindings -> unavailable, empty rankings; no '问题排查/产品评价' as family/SPU; 产品家族 reads family_rankings.
- 15:59:59Z in daily 10-28, 16:00:00Z not; reports/quarter/client agree on Asia/Shanghai business day.
- Data scope lists 933/1,094/7,955/15,891 and 合计 25,873; decremented fixture fails conservation.
- New rows: 'Momcozy S9 Pro' -> family s9-pro; comment include_in_voc_metrics=null + governed-pending; post non-empty aspect_tag_ids; record_authority='governed_base'; is_bot populated or detection_status explicit.
- brand-health sample 1,136/2,289/3,425; report rows value/display/status; periodBrandHealth non-null 75.42; monthly says all-observed-history.
- eufy + eufy S1 -> one row (797); 50+ competitor ids resolve; three comment populations shown; 16,822 no longer called the analysis denominator.
- aggregates publishes observation_window; page warns '含边界后 X 帖/Y 评论'; raw_observed no longer duplicates qualified=available.
- Wave-2 pytest + npm build + vitest green; four exact-key validators remain compatible (two-form acceptance).

### Wave 3 — 溯源与监控：工件自证、血缘可解引用、缺失可告警

**车道**：L5 — 可观测与治理层 (Observability & Governance), L1 — 数据生产层 (Data Production), L6 — 运行可靠性层 (Runtime Reliability), L4 — 交付与消费层 (Delivery & Consumption)

**目标**：Tickets: L5-R1 build receipt + timestamps (no timestamp on aggregates: validate_reddit_v3_base_public_projection.py:578 compares the whole object), L5-R3 scheduled monitor + Feishu, L5-R5 finalize_lineage, L5-R6 slot renames, L5-R7 real replay flags, L5-R8 boundaries true, L5-R9 freshness evidence, L5-R10 single T-1 window, L5-R11 honest labels, L5-R12 systemd; L1-R6 base identity/lineage (minus ds_dir), L1-R11 governed-binding rename, L1-R9 casebook 180d; L6-R4 base dir from pointer, L6-R6 full assertions, L6-R7 window gate; L4-R19 dossier badge, L4-R5 maturity follows data, L4-R11 evidence at=. Goal: every artifact states when/from-what it was built; every lineage hash resolves; a missed build is detected even if the pipeline never runs.

**退出标准**：

- Every dataset has a build receipt; manifest_sha256 == sha256(bytes); missing receipt -> exit 2 build_stamp_missing:<key>.
- brand-health.source.reports_manifest_sha256 == sha256(final reports manifest) and quarter same; finalize idempotent.
- deterministic_full_byte_replay true only when two builds are byte-identical; changed template byte -> false and build fails before publish.
- No literal replay True / boundaries False remains; boundaries true; client recomputes overall = half-up mean of four dims.
- Every source slot hashes the artifact its name claims; missing metrics dataset fails closed; no sha256(b'') fallback.
- Monitor: stalled -> exit 2 red card; healthy -> exit 0 heartbeat; partial -> not fresh; same state deduped.
- Four T-1 call sites agree over 8,760 hourly samples incl 2026-10-30T00:30+08:00.
- Uncovered window -> blocked_by_uncovered_window, data_as_of unchanged; captured window used, not wall clock.
- Base generated_at advances; lineage_mode present; lineage_manifest_sha256 hashes daily lineage; quarter source has no governed_signal_*.
- Casebook review_due = generated_at + 180d; operations view shows overdue badge; weekly warns at 30/7/0 days.
- Freshness bar ticks data age + observation warning; chip says manifest-hash verified; Agent Studio shows real time, no '每日 07:05'.

### Wave 4 — 结论与画像：判断句数据化，画像回到当前语料

**车道**：L3 — 结论生成层 (Conclusion Generation), L1 — 数据生产层 (Data Production), L4 — 交付与消费层 (Delivery & Consumption)

**目标**：Tickets: L3-R1 conclusions[] across quarter/brand-health/reports + frontend lookup, L3-R2 ranking templates, L3-R3 sample gates (30 VOCs, 10 posts, 100 for advice, 14 days), L3-R4 semantic gate, L3-R5 no sparkline fallback, L3-R6 drivers block, L3-R7 unavailable+reason; L1-R1 voc_id bridge + quarter v2, L1-R2 weekly V3 chain + receipt + deploy manifest + timer, L1-R3 real persona receipt, L1-R8 insights demotion, L1-R10 v1 canonical base binding; L4-R2 clock, L4-R3 fail closed, L4-R4 remove insights gate/allowlist, L4-R6 full lazy personas, L4-R16 Agent Studio. Goal: every judgment sentence is a versioned data product with inputs and a gate; personas rebuild weekly from the served base; insights stops gating the page.

**退出标准**：

- Every business sentence on 3 pages resolves to a conclusion_id; DOM text == sentence; full-site Playwright scan finds no orphan.
- render(template_id, inputs) == sentence for 100% of conclusions; hand-edit fails.
- Ranking flip: no self-comparison, no stale 2nd/3rd names, no Unspecified/None Observed.
- 21-VOC monthly: zero advice passed; explicit sample-insufficient message; claims readable with low-sample marker.
- Zero drivers: no imperative/action sentence.
- Missing input -> '不可用 + reason_code'; brand-health sentence present when valid; no silent disappearance.
- /dashboard/insights renders quarter headline + pain ranking with insights 500 + provenance warning; no SnapshotErrorPage; no literal 78 count gate.
- Weekly personas chain: canonical base SHA == served manifest SHA; validator receipt passed; chain receipt ok; 14 files byte-identical across runs; deploy manifest complete.
- Served personas dataset passes its validator; no undeclared lineage/ file; quarter cites a real personas validation receipt (or explicit pending accepted by L4).
- Insights loads 0 bytes persona-tags until 加载证据; then exactly one request; eight shares equal quarter payload, labelled period-scoped.
- Two-form acceptance: conclusions absent -> old copy renders; present -> strict; no 500 during skew.

### Wave 5 — 覆盖与规模化：评论按需、历史回填、遗留清理

**车道**：L1 — 数据生产层 (Data Production), L4 — 交付与消费层 (Delivery & Consumption), L2 — 计算正确性层 (Computation Correctness), L5 — 可观测与治理层 (Observability & Governance), L6 — 运行可靠性层 (Runtime Reliability)

**目标**：Tickets: L1-P15/L4-R12 comment index + byte range + LRU + fallback, L4-R12b insights uses summary, L1 backfill job for tags/product bindings (opt-in, idempotent), L2-R12b strict T-1 only if compliance requires, L2-R13b finish YoY, L4-R11b staleness on data_as_of, L5 retention/gc, L6-R12 standing orchestration harness, remaining P3 (L4-P16/P17/P18, L2-P14/P16, L1-P11). Goal: close payload/coverage gaps that cannot safely ship earlier and retire P3 debt without destabilizing Waves 1-4.

**退出标准**：

- comment_index: one post -> <=3 Range requests, 0 full GETs, comments equal monolith; bad shard rejected; fallback works.
- Insights total JSON <1MB, no posts-public request.
- Backfill job idempotent, per-row dictionary_version, zero-byte rerun, commits separately.
- YoY either seven_day_proxy provisional or no '7 日替代窗口' copy; no promised-proxy-yet-dash cells.
- Evidence staleness uses data_as_of; day-old link to unchanged corpus does not warn.
- All P3 items closed with a test or deferred with owner+date.
- Orchestration harness runs offline on 3-post/2-comment fixture in CI; failure injection leaves previous release serving.
- Retention keeps current+previous generation and 30 receipts; gc never removes live target.

---

## 三、跨切面决策

### 决策 1：What to do with the insights attested chain and the 10-entry VALIDATED_PUBLIC_WRAPPERS gate.

**选项**：
- A. Automate the 9-stage attested chain monthly and publish the result into datasets.insights.
- B. Demote insights: freeze the artifact, remove the page hard gate, trust the release pointer plus an internal coherence check, and stop adding allowlist entries.
- C. Keep the current frozen artifact and hand-maintained allowlist.

**推荐**：B. Demote now; keep the frozen artifact and its SHA binding, remove the hard gate and allowlist, and render a provisional provenance badge. Revisit automation only if the storylines get a rendered surface.

**理由**：SnapshotInsightsV3 declares snapshot but never destructures it (SnapshotInsightsV3.tsx:428-433; the page passes it at :539), so the dataset's only runtime effect is the gate and type switch. The 78 storylines are individually validated (insightsV3.ts:943/979/1060) but nothing renders them. The chain is 9 stages and the cited attestation 046693af is not in the repo (config/analytics has only 0716/0719/0723 files), so the published build cannot be replayed. Automating it would cost 4-6h per run and still render nothing; C keeps a fail-closed dependency on an unused artifact and requires a frontend edit per rebuild. B removes the false dependency and preserves the pointer's SHA binding.

### 决策 2：How personas get back to the current corpus.

**选项**：
- A. Weekly in-repo V3 chain: canonical (base-bound) -> validate -> facts -> validate -> governed signals -> validate -> personas -> validate, with a chain receipt and a systemd timer.
- B. Keep personas frozen and render only quarter-insights cohort counts in the panel.
- C. Rebuild the V1 personas snapshot on the daily base.

**推荐**：B in Wave 1 to stop the visible lie, then A in Wave 4 for corpus binding and evidence-level assignment filtering. Do not rebuild V1.

**理由**：The V3 builder requires a canonical bundle, a facts bundle plus validation receipt, a governed-signal snapshot plus receipt, the static reference manifest, the 82-row dictionary and the 8-cohort config (build_reddit_v3_personas_snapshot.py:873-895), so it cannot run at 07:40 without the whole chain. V1 dropped the base binding (personasV3.ts MANIFEST_KEYS:269-292 has no base_dataset_version/base_manifest_sha256, while personas.ts:304-331 required them). B fixes the visible 0.00% immediately from data already served (quarter cohorts sum to 755 with a conservation assert at quarterInsights.ts:605-614) but cannot prove which corpus personas came from.

### 决策 3：How to make publishing atomic.

**选项**：
- A. Staging generation directory plus a single atomic symlink swap of data/reddit-voc (hardlink seed, write-new-inode, fsync, gc keep 2-3).
- B. Bump the base dataset_version every day and bind it only at commit.
- C. Defer base visibility: write a sibling directory and swap the pointer's manifest_path at the end.

**推荐**：A, with C as the documented fallback if nginx -T shows disable_symlinks. Never B.

**理由**：Frozen personas and insights require base_dataset_version equality with release.datasets.base.dataset_version (personas.ts:322-325; insightsV3.ts:575-577), so B breaks those panels every day. A keeps the version string stable while isolating generations, and one os.replace of a directory entry is the only single-operation swap. C is a viable fallback when nginx disallows symlinks but still needs a directory indirection. There is no staging mechanism today; ADR-002 5.1 only ordered writes, and merge overwrites the live base in place (run_daily_t1_pipeline.py:243/297/347).

### 决策 4：Where conclusion sentences live.

**选项**：
- A. Server-side conclusions[] in each dataset, with template_id/inputs/gate/dataset_version, and a thin frontend lookup.
- B. Keep TSX templates but drive every clause from data in the client.
- C. Keep TSX templates as-is and only fix the obviously false clauses.

**推荐**：A for all business claims; TSX keeps only static methodology copy. Ship the producer first with a two-form client acceptance window.

**理由**：A makes render(template_id, inputs) == sentence testable and gives cross-page identity under one dataset_version; the sample/semantics gate sits next to the inputs. B can be data-driven but the gate and inputs remain client-side and un-attestable, and the same sentence can diverge across pages. C leaves the audit's core defect (conclusions are not a data product) in place. The existing frontend already has exact-key validation patterns and a forbidden-key list (quarterInsights.ts:278-281), so A can be added additively with a fallback when conclusions is absent.

### 决策 5：How honest to make brand health.

**选项**：
- A. Implement the canonical v3 formulas (50/50 grain, product-bound product_experience, recommendation closed-set, P0/P1/P2 risk weights).
- B. Fix what public data supports (product-bound product_experience, 50/50 grain) and declare the rest as explicit proxies in the payload; flip boundaries to true.
- C. Keep the lean formulas and only change the UI copy to match them.

**推荐**：B. Emit definition {id, formula_id, numerator_scope, denominator_scope, grain_weighting, is_proxy, proxy_for} per dimension, set overall_score_basis, set overall_score_derived_from_axes=true, and let the client recompute the mean.

**理由**：A needs recommendation closed-set classification and priority weights that the public base does not carry (v3_indicators.py:1002-1074 vs recompute_derivatives.py:731-795). C leaves the published numbers inconsistent with the published definition. B is reproducible from the current corpus (product-bound product_experience 94.81 with n=283; 50/50 risk 72.26, reputation 58.58, recommendation 70.08) and makes every proxy visible instead of pretending.

### 决策 6：Whether to retag historical rows.

**选项**：
- A. Retag all 25,873 posts and 100,778 comments in one pass.
- B. Tag only new rows from their own text, keep per-row dictionary_version, and run a separate opt-in backfill job.
- C. Leave tagging frozen and only rebuild the public dictionary.

**推荐**：B. New rows only in Wave 2; historical backfill is a separate Wave 5 job with an idempotent receipt.

**理由**：A changes attested July bytes, adds runtime and disk, and makes byte determinism hard. C leaves 8,404 new posts and 42,482 new comments permanently untagged and ineligible. B fixes the forward path, makes version mixing visible per row, and keeps the historical corpus stable for conservation checks. With empty product contexts only 403 of 2,346 rules fire, so B also documents the dependency on L1-R5.

### 决策 7：What to do with events after the published boundary.

**选项**：
- A. Disclose: publish observation_window {data_as_of_utc, observation_max_utc, events_after_data_as_of} and warn in the UI.
- B. Truncate merge to the T-1 close and rebuild manifest/counts from the truncated corpus.
- C. Leave the data as-is and say nothing.

**推荐**：A. Only implement B if a compliance requirement appears; then it needs a manifest+file truncation in the same pass, not just a filter.

**理由**：C is the current lie (52 posts / 255 comments after 10-28T23:00Z while the headline claims T-1). B breaks canonical_counts vs file rows and removes evidence posts from search, and the merge window is intentionally 2000-2100. A keeps the whole-corpus contract, makes the boundary visible, and is reversible.

### 决策 8：How release/run identity should work.

**选项**：
- A. Advance release_id per publish and use generated_at_utc as the cache/evidence generation key.
- B. Keep release_id invariant and use only generated_at_utc.
- C. Use dataset_version as the change token.

**推荐**：A. L6-R9 owns run_id/collector_run_id/release_id mechanics; L4 uses generated_at_utc for cache and evidence; dataset_version stays stable.

**理由**：release_id is currently invariant by design (reddit_voc_release_20260723_daily_v2) and evidence links compare it, so releaseMismatch can never fire (SnapshotSearch.tsx:174-176). Current collector_run_id is a calendar label that overwrites the failed morning attempt in SQLite and in the receipt filename (run_daily_t1_pipeline.py:49/638; storage.py ON CONFLICT). C is wrong because dataset_version is a directory name that must stay stable for frozen datasets. A gives both a human-readable generation id and a monotonic cache key.

### 决策 9：What to do with the fabricated personas validation receipt while the weekly chain does not exist.

**选项**：
- A. Keep writing the current receipt (rebuild_status=frozen_snapshot_upstream_engine_out_of_repo, all_checks_passed=true) inside the dataset tree.
- B. Return null and add persona_validation_status='not_validated_frozen_snapshot', accepted by L4 as a provisional state.
- C. Re-run the real validator against the frozen 10-28 directory.

**推荐**：B, shipped together with L4 acceptance. Restore a real reddit_voc_personas_validation_v3 receipt when the weekly chain lands in Wave 4.

**理由**：A is the current defect: lineage.py:190-197 writes the receipt into the immutable dataset directory and hardcodes all_checks_passed=true without running a check; the V3 validator rejects undeclared files/dirs (v3_persona_snapshot.py:921-929), so the daily pipeline makes the dataset fail its own validator. C is likely to fail because the directory already contains lineage/lineage-personas-receipt.json and may have non-0600 modes. B is honest and preserves the client's sha256 requirement only if the contract is extended; returning a bare null would break the source slot (recompute_derivatives.py:1032-1034).

---

## 四、非目标

- No implementation of canonical RV-BR-05 net-sentiment pair difference or RV-BR-04 recommendation closed-set in V2.0. Until L1 emits competitor pair-symmetry and recommendation classification fields, both report rows stay unavailable with reason codes.
- No automation of the 9-stage attested insights chain in V2.0. The insights dataset is frozen and demoted from a page gate; it is not rebuilt on a schedule and no new VALIDATED_PUBLIC_WRAPPERS entries are added.
- No scheduled casebook rebuild. Casebook becomes an immutable historical method reference with a 180-day review cadence, a Feishu reminder and an overdue badge.
- No full historical retag / re-bind / re-authority backfill in V2.0. New rows are tagged and bound from their own text; any historical backfill is a separate, opt-in, idempotent job with per-row dictionary_version.
- No strict T-1 truncation of the corpus in V2.0. The default is to publish observation_window and disclose post-boundary events; truncation is a conditional follow-up only if compliance requires it.
- No migration of the publish read path from legacy reddit_threads/reddit_comments to content_entity in V2.0. Only the containment assertion (SQL EXCEPT preflight) ships.
- No frontend visual redesign, page information-architecture change, chart-library swap or new component system. Only data binding, labels, empty/unavailable states and cache behavior change.
- No change to release-guard semantics, SHA-binding rules, POINTER_PREREQUISITES or the release pointer schema beyond additive fields explicitly named in the waves.
- No new dataset types. personas/insights/casebook remain the same contracts; the only new artifact is the comment byte-range index.
- No change to nginx/systemd/deployment mechanics beyond installing the new units and the generation root (with a preflight and a non-symlink fallback).
- The release-bound case catalog (public/data/cases/manifest.v1.json, 38 seed + 12 legacy) and the bundled casesMock seed remain out of scope; only the casebook dossier badge is in scope.
- Feishu morning-brief editorial content, card layout and Top-3 idea quality are out of scope; only the card's run-status truthfulness (verified/red/failure) is in scope.

## 五、主要风险

- Symlink generation swap vs nginx disable_symlinks: a misconfigured nginx returns 403/404 for the whole data tree. Mitigate with a pre-deploy nginx -T assertion and a fallback to deferred base visibility (new directory bound only at commit).
- Lockstep JSON contract changes across producer and four frontend exact-key validators (quarterInsights.ts, brandHealth.ts, reports.ts, insightsV3.ts): a partial deploy yields page-wide 500s. Mitigate with additive fields, two-form acceptance windows and one schema bump per artifact, producer-first for additive changes and consumer-first for stricter validators.
- Personas weekly chain runtime and disk: ADR-004 M-B took 2h35m at 17k/58k; 26k/101k is estimated 4-6h and GBs. The lean server may also hit ModuleNotFoundError because deployment is a sha256-matched file copy, not git. Mitigate with a generated deploy manifest, free-space preflight, singleton lock and a workstation fallback.
- Changing tag eligibility / record_authority / product bindings changes headline counts and can trip whole-object conservation assertions (validate_reddit_v3_base_public_projection.py compares aggregates as a whole object). Mitigate by mutating only rows with run_id, never rewriting July rows, and regenerating aggregates from the same corpus in one pass.
- Brand-health numbers move (75.42 -> about 73.9 after product-bound + 50/50 grain) and RV-BR metrics go unavailable: stakeholder trust dips. Mitigate with owner sign-off, a before/after note in the card and a single release with the UI copy change.
- The generation transaction changes the write root; any out-of-repo script still writing data/reddit-voc directly will write into the current generation or the wrong path and silently lose data. Mitigate with the single-writer lock, a write-outside-generation assertion and a documented path contract.
- Conclusions producer/consumer skew: if the frontend ships before conclusions[] exists it must fall back; if it ships after, exact-key validation can reject. Mitigate with the two-form acceptance window and an explicit absence fallback.
- Evidence staleness keyed on release.generated_at_utc changes every day even when the post data did not, causing warning fatigue on every link older than one publish. Mitigate by comparing data_as_of_utc for the stale verdict and keeping at= only for audit display.
- Persona double-fix: quarter cohort counts and persona-tags assignments can disagree if both are rendered. Mitigate with one display source (quarter cohort counts) until the voc_id bridge lands, then use assignments only for evidence.
- The 200MB comments index adds a daily reorder/rewrite cost and a new artifact; a malformed index or missing Range support breaks evidence viewing. Mitigate with the dual-path monolith fallback, shard sha verification, LRU(20) and a content-length confirmation gate.
- Frozen personas/insights bind to the base dataset_version string (personas.ts:322-325 and insightsV3.ts:575-577 require equality). Any base version bump or pointer-schema change breaks them. Mitigate by never bumping the base version daily and binding the weekly chain via canonical base_public_manifest_sha256 + chain receipt.
- The interim persona receipt contract (null + persona_validation_status=not_validated_frozen_snapshot) must ship with L4 or the insights page fails closed on a missing sha256. Mitigate by treating the receipt change and the client acceptance as one release unit.
- Wave 1 ships before the 10-28 frozen datasets are re-validated; if the transaction or pointer schema changes land first, the frozen datasets must still pass their existing SHA checks. Mitigate with a pre-deploy binding audit and a rollback pointer.