---
title: Reddit VOC 真实日报周报月报实施计划
doc_type: implementation_plan
status: completed_local
created: 2026-07-14
updated: 2026-07-14
owner: codex
design_spec: ../specs/2026-07-14-reddit-voc-real-reports-design.md
production_boundary: production_unchanged
provider_call: false
database_write: false
live_send: false
webhook_send: false
deploy: false
commit: false
---

# Reddit VOC 真实日报、周报、月报实施计划

## 1. 目标

基于已验证的 `reddit_voc_site_snapshot_20260714_v1` 和
`reddit_voc_insights_20260714_v1`，生成可复算、可校验、可静态加载的日报、
周报、月报双口径数据，并用最小 UI 改动激活 `/dashboard/reports`。

当前批次只完成本地静态数据与网站验证，不连接实时数据，不修改生产数据库，
不触发 Provider、Webhook、DingTalk、定时任务、部署或 Git commit。

## 2. 完成标准

- 生成一个版本化报告数据集，包含滚动 `24h / 7d / 30d` 三份当前报告，
  以及昨日、上周、上月三份闭合日历归档报告。
- 每份报告的帖子与评论分别按自身 `created_at_utc` 入窗，窗口使用左闭右开
  `[start, end)`，本地时区固定为 `Asia/Shanghai`。
- 所有数字能从基础快照复算；报告 manifest 绑定基础 manifest、Insights manifest
  和所有报告文件的 SHA-256。
- 报告只能使用通过语义门禁的标签；held 标签、画像推断、市场份额、ROI、
  响应时长、NPS、转化率、预测和增长结论均 fail closed。
- 上月没有采集覆盖证据时显示 `coverage_gap`，不得解释为“零讨论”。
- `/dashboard` 保持现有真实概览；新增 `/dashboard/reports` 和一个“报告”导航项。
- 报告页缺文件、版本不匹配或 schema 不合法时显示错误，不回退 Mock。
- Python 数据测试、独立校验、前端测试、TypeScript build 和 HTTP smoke 通过。
- 浏览器可启动时完成桌面与移动视觉 QA；若仍被环境 SIGKILL，单独列为未验证。

## 3. 文件映射

### 新建

- `scripts/build_reddit_reports_snapshot.py`：确定性报告生成器。
- `scripts/validate_reddit_reports_snapshot.py`：与生成器独立的报告校验器。
- `tests/test_reddit_reports_snapshot.py`：窗口、计数、标签门禁与篡改测试。
- `data/processed/reddit_voc_reports_20260714/`：本地版本化报告产物。
- `ref/UI/momcozy-reddit-workbench/public/data/reddit-voc/reddit_voc_reports_20260714_v1/`：
  网站静态报告数据。
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/reports.ts`：
  报告 schema、fail-closed 加载与前端校验。
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/useRedditReports.ts`：
  静态报告加载 hook。
- `ref/UI/momcozy-reddit-workbench/src/components/reports/RealReportView.tsx`：
  复用现有报告视觉系统的真实指标视图。
- `ref/UI/momcozy-reddit-workbench/src/pages/SnapshotReports.tsx`：
  安全的静态报告页，不执行旧页面的推送和随机刷新副作用。
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/__tests__/reports.test.ts`：
  前端报告 schema 与 fail-closed 测试。

### 修改

- `ref/UI/momcozy-reddit-workbench/src/App.tsx`：新增 `/dashboard/reports`。
- `ref/UI/momcozy-reddit-workbench/src/components/Sidebar.tsx`：新增“报告”入口。
- `ref/UI/momcozy-reddit-workbench/src/features/redditSnapshot/SnapshotPageLayout.tsx`：
  增加移动端报告入口。
- `ref/UI/momcozy-reddit-workbench/src/pages/__tests__/SnapshotPages.test.tsx`：
  增加报告页路由与真实数据测试。
- 本设计稿与项目开发记录：同步实际实现、验证和边界。

旧 `Dashboard.tsx`、`reportEngine.ts`、`*ReportMock.ts`、Webhook 与通知逻辑不删除，
但新真实报告路由不得调用它们。这样保持原 UI 源码可回看，同时隔离自动推送、
随机 seed 和不受真实数据支持的模块。

## 4. 实施任务

### Task 1：实现报告数据契约与时间窗口

- 固定 `dataset_version=reddit_voc_reports_20260714_v1`。
- 使用基础 manifest 的 `generated_at_utc` 作为唯一当前窗口锚点。
- 计算滚动窗口与北京时区闭合日、周、月窗口。
- 每份报告包含 identity、window、headline、observed_timeline、communities、topics、
  pain_points、brand_mentions、promoted_signals、attention_items、evidence_posts、
  capabilities、interpretation_boundaries、runtime_boundaries。
- 对没有覆盖的上月归档生成显式覆盖缺口报告。

### Task 2：实现真实聚合与品牌归因

- 只统计 `include_in_voc_metrics=true` 的评论。
- 帖子与评论分别按时间入窗；评论的社区通过 `post_id` 关联父帖。
- 情感、主题和痛点直接来自已验证本地规则结果，保留分母。
- 品牌提及是样本提及数，不宣称市场份额。
- 推广标签仅允许 `L0-GEN-075`、`L0-GEN-103`。
- Momcozy 专属信号必须存在同句品牌与标签证据；实体共现、多品牌、竞品明确、
  通用品类分别标记，不混为 Momcozy 结论。
- `consumer_card` 只作为字典参考维度，不生成用户画像。

### Task 3：实现独立验证与测试

- 校验输入版本与 manifest hash 绑定。
- 校验六份报告路径、schema、哈希、窗口、计数和时间粒度。
- 从基础帖子/评论独立复算 headline、时间序列和主要排名。
- 拒绝 held 标签、未知标签、伪画像、趋势结论及不支持指标。
- 篡改任一报告文件、窗口或计数时测试必须失败。

### Task 4：最小化 UI 激活

- 保持 `/dashboard` 不变，新增 `/dashboard/reports`。
- 保留原来的三标签页、配色、卡片和导出风格。
- 仅展示真实支持的概览、观察时间线、社区、主题、痛点、品牌提及、
  通过门禁的标签信号、关注项和证据帖子。
- “刷新”只重新加载同一静态版本，不改变 seed。
- 隐藏市场份额、ROI、响应时长、NPS、转化率、高意向、UGC、KPI 达成和预测。
- 页面不得导入 Mock 报告服务或执行 Webhook/通知副作用。

### Task 5：验证与交接

- 运行 Python 测试和基础快照、Insights、reports 三个独立 validator。
- 运行前端定向测试、全量测试、TypeScript build。
- 启动静态站点执行 manifest/report HTTP smoke。
- 可行时执行桌面与移动浏览器视觉 QA。
- 更新设计稿实施状态与项目开发记录；如实列出未验证项。

## 5. 验证命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. uvx --from pytest pytest \
  tests/test_reddit_insights_snapshot.py tests/test_reddit_reports_snapshot.py -q

python3 scripts/validate_reddit_site_snapshot.py \
  --snapshot-dir data/processed/reddit_voc_site_snapshot_20260714

python3 scripts/validate_reddit_insights_snapshot.py \
  --base-snapshot-dir data/processed/reddit_voc_site_snapshot_20260714 \
  --overlay-dir data/processed/reddit_voc_insights_20260714

python3 scripts/validate_reddit_reports_snapshot.py \
  --snapshot-dir data/processed/reddit_voc_site_snapshot_20260714 \
  --insights-dir data/processed/reddit_voc_insights_20260714 \
  --reports-dir data/processed/reddit_voc_reports_20260714

npm test -- --run
npm run build
```

具体 Python 解释器优先沿用项目已验证 runtime；前端命令在
`ref/UI/momcozy-reddit-workbench` 执行。

## 6. 风险与停止条件

- 基础或 Insights SHA-256 不匹配：停止生成，禁止回退 Mock。
- 真实字段不足以支持某指标：隐藏该指标并记录 capability，不推算补齐。
- 上月无覆盖证据：输出 `coverage_gap`，不输出“0 条讨论”的业务结论。
- 同一验证路径连续三次失败：停止叠加 patch，重新审查数据契约或 UI 数据流。
- 任何步骤需要生产写入、外部调用、发送、部署或 commit：停止并重新取得授权。

## 7. 当前执行边界

`production unchanged`、`provider_call=false`、`database_write=false`、
`live_send=false`、`webhook_send=false`、`deploy=false`、`commit=false`。

## 8. 实施结果与验证

- 已完成版本化数据集 `reddit_voc_reports_20260714_v1`、六份报告、独立验证器、
  篡改/fail-closed/跨进程确定性测试及 UI public 静态副本。
- 已新增 `/dashboard/reports`、Sidebar 与移动导航入口；真实报告路由只读取静态
  manifest/index/report JSON，不导入旧 Mock、随机 seed、Webhook 或通知服务。
- current 日/周/月为 `8/37`、`83/392`、`85/395` 个帖子/VOC 评论；archive
  日/周为 `12/59`、`67/307`；archive 月报为明确 `coverage_gap`。
- 仅 `L0-GEN-075`、`L0-GEN-103` 进入报告，8 个 held 标签被排除；
  `consumer_card` 未被冒充为用户画像。
- Python 测试、三个 validator、前端全量 `91` 个测试、lint、build、HTTP smoke、
  Chromium 桌面与移动视觉/交互检查均通过。浏览器 console 无 error/warning，
  网络检查仅见静态 GET。
- 没有执行生产接入、Provider、数据库写入、真实发送、Webhook、部署、调度变更或
  Git commit；P1 held 标签修复、真实画像管线和实时接入不属于本计划完成范围。
