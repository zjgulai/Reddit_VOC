---
title: Reddit VOC Plan B - UI 治理状态与正常态去警示
doc_type: implementation_plan
status: complete_local_source_validated
created: 2026-07-15
updated: 2026-07-15
owner: codex
depends_on: 2026-07-15-reddit-voc-candidate-closure-data.md
evidence_grade: L2_local_independent_source_validation
production_boundary: production_unchanged
deploy: false
remote_write: false
---

# Plan B：UI 治理状态与正常态去警示

## 1. 目标与设计约束

Plan B 在不改动既有核心布局、信息架构和网站专业调性的前提下，统一“系统错误、数据覆盖、
业务优先级、功能未启用”的视觉语义。它只消费 Plan A 的真实数据合同，不伪造或隐藏覆盖债务。

完成条件：

- 三个共用治理组件落地并复用现有 token/Lucide，不增加依赖；
- 正常态活动路由不再把 `verified/provisional/unavailable` 渲染成 error warning；
- 真实 fetch/manifest/hash/安全合同失败仍 fail closed 并显示明确错误；
- 受管状态组件具有稳定 `data-governance-status` 和 `aria-label`；
- artifact build 与 site deployment 为两个独立对象；
- 案例 `38+12+approved delta`、报告六态、A/B/C、产品三层、合成头像和采集后台外链保持；
- 13 条路由的 source-level contracts 和临时编译证明通过；最终不可变 dist、
  desktop/mobile same-dist E2E 与 promotable receipt 由 Plan C 唯一生成；
- 结束状态仍为 `production unchanged`。

## 2. 预期文件范围

新增：

- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/governance/GovernanceStatusBadge.tsx`
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/governance/DataScopeBar.tsx`
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/governance/ReleaseEvidenceCard.tsx`
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/governance/index.ts`
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/governance.test.tsx`

按需窄改：

- `src/features/redditSnapshot/types.ts`
- `src/features/redditSnapshot/release.ts`
- `src/features/redditSnapshot/service.ts`
- `src/features/redditSnapshot/SnapshotBoundaryPanel.tsx`
- `src/components/reports/RealReportView.tsx`
- `src/components/reports/RiskThemePanel.tsx`
- `src/components/case-gallery/CaseCardGrid.tsx`
- `src/components/personas/AggregatePersonaCard.tsx`
- `src/pages/SnapshotDashboard.tsx`
- `src/pages/SnapshotReports.tsx`
- `src/pages/SnapshotInsights.tsx`
- `src/pages/SnapshotAnalytics.tsx`
- `src/pages/SnapshotSearch.tsx`
- `src/pages/CaseGallery.tsx`
- `src/pages/ProductionFeatureGate.tsx`
- `src/pages/HowItWorks.tsx`
- `src/pages/Features.tsx`
- 相关 `src/pages/__tests__` 与 snapshot feature tests

除非真实数据维度需要，不移动主区块，不重做导航，不引入新的全局设计系统。
`AggregatePersonaPanel.tsx`、`ErrorBoundary.tsx` 和 `SnapshotPageLayout.tsx` 属于
error-scope allowlist；只有现有错误语义不符合下述 failure matrix 时才窄改。

## 3. Batch B1：基线 inventory 与类型合同

- 对活动路由逐项记录当前 `!`/Alert 图标、红点、黄色警示条和重复边界说明的组件来源。
- 将每项分类为 `failed`、`provisional`、`unavailable`、`verified` 或业务优先级 P0–P3。
- 只治理受管 UI；不得扫描或修改 Reddit 标题、正文、评论中的自然语言感叹号。
- Plan A 必须输出最终 `governance_status`，UI 不解析 reason 文本猜状态：样本/覆盖不足可为
  `provisional`，policy 未配置或能力未冻结为 `unavailable`，合同失败才是 `failed`。
- 扩展 release 类型以显式承载：

```text
artifact_build_state
site_deployment_state
data_scope
comparison_scope
tag_maturity
```

- 旧数据只有 build flags 时必须显示为历史 artifact evidence，不得据此推断当前部署失败。
- `artifact_build_state` 是不可变 build receipt。`site_deployment_state` 不复制旧 build flags；
  候选页面只从实际加载的 `current-release.json` 得到 `served_release_id`，仅表达当前服务身份。
  promotion/acceptance 只有存在独立、可校验、与 served release SHA 一致的 deployment source
  时才展示，否则为 `unavailable`，不能在候选 dist 中预写“已验收”。

## 4. Batch B2：共用组件 RED → GREEN

先补测试，再实现：

- `GovernanceStatusBadge`：四态语义、颜色、图标、`data-governance-status`、`aria-label`；
- `DataScopeBar`：每个受管数据页最多一次（dashboard/reports/analytics/insights/search），
  cases 使用 catalog status，营销页和 gated 空态不强塞；替换后删除/收拢旧的重复
  `SnapshotBoundaryPanel`，不能新旧并存；
- `ReleaseEvidenceCard`：默认展示 served release identity，可展开 artifact 副作用边界；
  acceptance 仅在独立 deployment source 可校验时展示；
- `failed` 才允许 error-status icon，其他三态禁止；
- 所有真错误使用 `data-ui-severity="error"`，业务风险使用
  `data-business-priority`，P0/P1 可保留业务颜色但不能使用系统错误三角；
- keyboard、screen reader 文本和颜色对比不依赖图标单独传义。

## 5. Batch B3：页面级最小替换

- `/dashboard`：quarantine 卡使用中性关联/隔离语义，保留“不进入指标”。
- `/dashboard/reports`：负面证据、痛点和关注项改为内容分析语义；保留风险等级和 reason。
- `/dashboard/insights`：hero/KPI/主题改用中性业务图标；按 Plan A
  `governance_status` 渲染，`provisional` 显示“仅观察”，`unavailable` 显示能力/策略未冻结。
- `/dashboard/analytics`：规则标签明确为规则提取/未晋级语义洞察。
- `/dashboard/search`：列表与详情的待语义复核合并为一次规则状态说明；每条规则 tag chip
  和 source maturity 继续保留可追溯。
- `/cases`：删除无条件红点；12 条 `legacy_unverified` 改用 History/待核验存量状态，
  保留 sourceKind、12 count、筛选来源和卡片标签。
- `/dashboard/messages`、`/dashboard/ugc-showcase`、`/dashboard/settings`：
  中性显示“功能状态 · 未启用”，仍禁止真实发送/写入。
- 营销页只删除纯装饰 warning，不提升任何能力 claim。

每完成一页同步补回归测试，避免全局搜索替换造成语义误伤。

## 6. Batch B4：失败注入、source receipt 与临时编译证明

自动测试必须覆盖下列 failure-scope matrix：

| 合同失败 | 允许影响范围 |
|---|---|
| release/Base/Reports/Insights manifest、fetch 或 SHA | 对应整页停止指标并显示 error |
| Personas manifest/fetch/SHA | 仅画像模块停止，洞察主线继续 |
| Cases legacy/approved delta manifest/fetch/index/hash | 拒绝增量，保留 38 条 seed-only |
| 单个头像 decode/resource | 该卡片使用 synthetic placeholder |

- 正常真实候选数据下，受管 `verified/provisional/unavailable` 无 error-status icon；
- 所有 failure scope 显示明确原因且不越过上述影响范围；
- current/archive 的 daily/weekly/monthly 六态；
- Momcozy category/product family/exact-SPU、竞品同样本、画像合成头像、案例、后台外链；
- artifact/deployment 双状态没有语义冲突；
- 13 路由的 unit/DOM source contracts 无登录控件或未知外部请求；如使用临时 dist 做
  浏览器反馈，它只属于 non-promotable preview，不能交付为 final same-dist evidence；
- 正常组件清单至少覆盖 dashboard quarantine、两个旧 boundary 收拢点、Insights Top8、
  Reports 六态、12 个 case cards、HowItWorks 和 Features 装饰 warning。

验证命令：

```bash
npm test -- --run
npm run lint
npm run build
```

实施时先检查 `npx/node/npm` 实际可用性并使用项目 lockfile；不安装新依赖。现有
`scripts/playwright_insights_e2e.js` 是接受 `page` 的 callback，不是 Node CLI；必须按
项目现有 Playwright CLI runner 先 navigate 到同一 dist URL 再执行 callback，并在实施
记录中保存实际 runner 命令。若产品化 wrapper，由 Plan C 单独实现并测试。

Plan B 最终只写 `<candidate-root>/frontend/source/frontend-source-manifest.json` 和
`candidate-ui-source-validation-receipt.json`；`npm run build` 产物仅为临时编译证明。
Plan C 重新冻结最终 source/toolchain，并唯一生成 promotable dist/container/E2E receipt。

## 7. 停止门与非目标

出现以下情况即停止：Plan A schema 未冻结、页面需要大幅重排才能承载数据、同一状态在不同
页面含义冲突、错误注入不再 fail closed、案例或报告既有内容丢失、测试三次仍不能定位根因。

Plan B 不授权生产部署、数据采集、数据库写入、调度变更、live send，也不删除覆盖事实、
reason code、待核验案例或真实系统错误。

## 8. 实施结果（2026-07-15）

- 已落地四态治理合同及三个共用组件；五个受管数据页各保留一个 `DataScopeBar`，
  Dashboard、Reports、V2 Insights 分别展示独立 `ReleaseEvidenceCard`。正常
  `verified/provisional/unavailable` 不再使用系统 error glyph，真实失败继续 fail closed；
  业务 P0/P1 与系统错误属性已分离。
- 本地 UI 已消费 Plan A 最终 pointer
  `reddit_voc_release_20260715_70a917e5bdf0`：Base 为 1,322 posts、16,591 stored
  comments、16,581 linked comments、10 quarantine、16,417 VOC comments；经营派生为
  42 risk themes、46 competitors、17 product scopes、323 persona assignments；六份
  daily/weekly/monthly 报告和案例 `38/12/0` 保持。
- 唯一可交接 Plan C 的 frontend candidate input 是
  `c04aec93775179be20f6b5538795c647b66a2a6df36c3a898fdc6b7119eb022e`；source manifest
  SHA 为 `32afe3adb5ed7b24c62d28a76856ca509432b441941c8befe4946630a2384e6d`，独立 source
  validation receipt SHA 为
  `340e4f65c753eff75031bd129654f9faa8699366e5f76c97726e6cb1c44853ab`。receipt-less
  `870855c1...885e` 已 superseded，禁止按目录扫描选取。
- 最终 source inventory 为 219 files / 31,942,539 bytes，其中 manifest-only public
  stage 为 27 files；Plan A public projection 仍为 21 files / 30,102,047 bytes。工作区中
  历史 v1/v2/A2 public 与 `.env.local` 未进入候选；Plan C 必须继续按 manifest-only stage
  消费，不能直接复制整个工作区 `public/`。
- 新鲜验证为 builder/validator 8/8、frontend 26 files / 166 tests、lint 0 errors + 5 个
  既有 warnings、TypeScript exit 0、临时 build 55 files / 32,628,328 bytes。builder 与
  独立 validator 同输入复跑均为 `no_change`；最终独立 artifact/UI 审计均为
  P0=0/P1=0/P2=0。
- 该 build 只属于 ephemeral non-promotable compilation proof。最终 dist、container、
  desktop/mobile same-dist E2E、四导出与 promotion packet 均未生成，归 Plan C 唯一负责。
  边界保持 `provider_call=false`、`database_write=false`、`remote_write=false`、
  `deploy=false`、`live_send=false`、`production unchanged`。
