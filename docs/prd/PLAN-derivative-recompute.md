# 执行计划：方案A 指针诚实化回拨 + 方案B 派生数据集重算引擎

对应 ADR-002。分两阶段，先 A 后 B。

## Phase A（立即，预计 30 分钟）

### A1. 指针诚实化回拨
- **服务器**: 43.163.92.244 → `/opt/voc-report/html/data/reddit-voc/current-release.json`
- **动作**:
  - `freshness.data_as_of_utc` → `2026-07-22T23:00:00Z`（即北京 2026-07-23 07:00，派生数据集真实边界）
  - `window_start_utc` → `2026-07-21T23:00:00Z`、`window_end_utc` → `2026-07-22T23:00:00Z`
  - `collector_run_id` → `daily_collect_20260723_0700`（回拨到生成该投影的原始批次）
  - `status` 保持 `partial`
- **验收**: 公网拉取 current-release.json，确认四字段；页面状态条显示"数据截止 2026-07-23 07:00"，与趋势图 buckets (07-17~07-23) 自洽。

### A2. 流水线防回退保护
- 修改 `advance_daily_t1_release` 调用逻辑：在方案 B 引擎上线前，流水线 **跳过 Step 4 指针前移**（加 `--skip-pointer` 或检测开关），避免再次制造脱节。
- 部署到 43 服务器。

### A3. 验证
- 全部 7 个数据集 SHA 校验仍 OK（回拨不改 manifests）。
- 手动刷新 radar.luteos.com 首页截图级核对状态条文案。

## Phase B（主交付，预计 2-3 天）

### B1. 开发 `scripts/recompute_derivatives.py`（本地开发 + 测试）
- 输入：SQLite（全量 posts/comments/analysis）+ config/agent_settings.json
- 模块化函数，每个数据集一个 `recompute_xxx()`，schema 与 7 月版逐字段兼容：
  1. `recompute_aggregates()` — date_range / headline 计数 / sentiment / pain_points / coverage_grade / monthly_posts
  2. `recompute_quarter_insights()` — anchor=昨日；dashboard_windows 三窗口 daily buckets（post_vocs / comment_context_vocs / negative_vocs / classified_vocs / negative_rate）；themes 聚合
  3. `recompute_reports_daily()` — period_id=daily:{T-1}:{T}；indicators（观察量/推荐表达率/异常加速度/产品问题率/有效标签率/证据完整率）+ 6 期 sparkline + 同环比（真实历史桶）
  4. `recompute_brand_health()` — 四维评分投影（口径冻结：与 7 月版权重一致），更新 source_snapshot_id
- 每个函数输出重算回执（输入行数/输出行数/耗时/与上一版的 diff 摘要）。

### B2. 回归比对（关键质量门禁）
- 以 2026-07-23 为锚点日重跑一次重算引擎，输出与线上 7 月版逐字段 diff；
- 数值一致（或差异可解释，例如增量合并的 18 帖导致的小幅合法变化）才允许进入流水线；
- 编写 `tests/test_recompute_parity.py` 固化该比对。

### B3. 并入流水线
- 在 `run_daily_t1_pipeline.py` 的 merge_snapshot 与 advance_pointer 之间插入 `step3_5_recompute_derivatives`；
- 顺序强制：**先内容（数据集+manifests+bindings）→ 后指针**；
- 服务器部署 + 手动触发一次全链路实测；
- 解除 A2 的指针跳过保护。

### B4. 验收
- radar.luteos.com 概览趋势图 buckets 到昨天；报告页日报 period=T-1；健康度雷达基于最新快照；
- 搜索/概览/报告三页时间边界一致（T-1）；
- 飞书日报卡片推送的指标与页面一致。

## 关键文件

| 文件 | 动作 |
|---|---|
| `scripts/recompute_derivatives.py` | 新建（B1 核心） |
| `scripts/run_daily_t1_pipeline.py` | 修改（A2 保护 + B3 插入 step3.5） |
| `tests/test_recompute_parity.py` | 新建（B2 回归） |
| 43 服务器 `/opt/echo-agent-bot/scripts/` | 部署 |
| 43 服务器 `/opt/voc-report/html/data/reddit-voc/current-release.json` | A1 回拨 |

## 口径冻结（对照 7 月版，来自审计取证）

- post_voc = 治理品牌事实确认 brand=momcozy 的帖子
- comment_context_voc = 已关联评论（父帖确认品牌）
- 负面率 = negative / (positive+neutral+negative) 已分类
- 健康度四维 = 口碑健康/产品体验/推荐信任/风险韧性（7 月版权重）
- 滚动窗口 = 近7天/近30天/近183天（Asia/Shanghai 日切，anchor=最新业务日）
