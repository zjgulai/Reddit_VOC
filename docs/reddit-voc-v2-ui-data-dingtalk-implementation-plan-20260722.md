---
title: Momcozy Reddit VOC V2.0 UI、数据日更与钉钉周期报告落地方案
doc_type: product_design_and_engineering_plan
status: owner_decisions_confirmed_implementation_started
created: 2026-07-22
updated: 2026-07-22
owner: product_owner
project: Reddit_VOC
production_boundary: production_unchanged
provider_call: false
database_write: false
remote_write: false
deploy: false
schedule_change: false
live_send: false
---

# Momcozy Reddit VOC V2.0 UI、数据日更与钉钉周期报告落地方案

## 1. 文档定位

本文是以下三份既有成果的 V2.0 落地补充，不替代其已确认的数据与产品边界：

- `docs/reddit-voc-product-v2.0-spec.md`：统一采集、SourceBatch、中心融合和发布合同；
- `docs/reddit-voc-project-retrospective-design-manual-roadmap-20260721.html`：项目复盘、设计逻辑、使用手册和模块路线图；
- 当前生产洞察站：`https://reddit.lute-tlz-dddd.top/`。

本次把三个原本分散的问题收敛为一个闭环：

1. 保留已有产品骨架，重建一致、可读、可维护的 UI 和交互系统；
2. 让每天采集的新 Reddit 数据真正进入中心数据、报告、洞察、画像和生产站；
3. 从同一数据 release 生成日报、周报、月报经营摘要图，并通过服务端安全链路推送钉钉。

## 2. 第一性原则与成功标准

### 2.1 第一性原则

1. **UI 的目的不是展示组件，而是缩短“判断—原因—行动—证据”的路径。**
2. **采集成功不等于洞察站更新。** 新数据只有完成不可变批次、中心去重、指标投影、候选验证和数据指针切换，才算到站。
3. **网站、截图、导出和钉钉必须使用同一个 data release。** 不允许四处分别计算。
4. **代码发布与数据发布是两种风险。** UI 代码继续受控提升；通过验证的日常数据应独立、原子、可回滚地发布。
5. **周期报告不是同一页面换标题。** 日报负责行动，周报负责诊断，月报负责取舍。
6. **失败不能伪装成功。** 旧截图、旧数据、空产物、PIL 降级图和未知发送状态都不能被当作本期成功。
7. **不碰无关生产环境。** V2.0 只在 Reddit VOC 洞察站和其专属数据发布链内实施，不修改共享 Nginx、TLS、DNS 或其他 Docker。

### 2.2 V2.0 上线成功标准

- 生产页在每天闭合批次后 90 分钟内展示最新通过验证的数据 release；
- 概览、日报、周报、月报、分析、洞察、画像使用同一中心与指标 release；
- 页面常驻显示 `data_as_of`、采集 run、中心 release、投影 release 和覆盖状态；
- 日报、周报、月报分别生成一张可在钉钉手机端阅读的经营摘要图；
- `failed` 不发布、不发送；`partial` 可以发布，但页面和消息显著标注覆盖状态；
- 相同 batch 重放为 `no_change`，相同周期与目标群不会重复发送；
- 任一 manifest、SHA、期次或血缘不一致时，生产数据指针保持不变。

## 3. 2026-07-22 新鲜度核查结论

### 3.1 已验证事实

截至 2026-07-22 11:04 Asia/Shanghai：

| 层级 | 状态 | 最新事实 |
|---|---|---|
| 采集后台 | 已更新 | `daily_collect_20260722_0700` 已产生 12 帖、61 评论、73 分析项；9 帖 full、3 帖 partial |
| 7/20—7/22 增量 | 已存在 | 44 个唯一帖子、183 条嵌入评论；44 帖与当前中心帖子交集为 0 |
| 日报产物 | 已生成 | HTML、XLSX、CSV、PNG 均已生成 |
| 当日钉钉 | 已发送 | 2026-07-22 约 08:04 返回 `status=sent`、HTTP 200 |
| 中心数据 | 未更新 | 仍为 `reddit_voc_center_20260718_v3_canonical_v2` |
| Reports / Insights / Personas | 未更新 | 仍引用 7 月 18 日中心；日报到 7 月 18 日、周报到 7 月 13 日、月报到 6 月 30 日 |
| 生产洞察站 | 未更新 | `release=e8bea154…a3b`；data release 仍为 `reddit_voc_release_20260719_v3_center_refresh_003` |

当前生产中心仍为 3,535 帖、27,316 存量评论，其中 20,363 条已关联、6,953 条待父帖关联、0 条隔离。

### 3.2 根因

- `scripts/server_daily_collect.sh` 只完成采集和日报产物；
- `scripts/run_v2_daily_pipeline.sh` 已存在，但尚未接入生产调度；
- V2 中心到完整 V3 `Base/Reports/Insights/Personas` 的自动桥接未完成；
- 采集后台当前公开制品没有 SourceBatch、canonical、candidate 或 current-data release；
- 当前站点将前端代码与数据绑定为同一次整站 release，无法承担真正的每日数据更新。

结论：**今天的 Reddit 数据已经被采集并进入旧日报链，但没有进入生产洞察站。**

## 4. awesome-design-md 的正确用法

`awesome-design-md` 的价值不是复制某个品牌模板，而是用一份可执行的 `DESIGN.md` 固化：视觉氛围、颜色角色、字体层级、组件与状态、布局、层级与阴影、Do/Don't、响应式和实现规则。

V2.0 采用项目自己的设计方向：

> **Momcozy Warm Intelligence**：温暖但不幼态，专业但不冷硬，数据密集但保持平静；暖珊瑚只承担品牌与重点，真实证据和经营结论成为视觉主角。

借鉴方式：

- 借鉴 Claude 的暖米色画布、编辑式留白与克制强调色；
- 借鉴企业数据产品的扁平层级、细边框、精确数字和稳定业务色；
- 借鉴结构化工作台的清晰导航、模块状态和一致组件协议；
- 不复制任何外部品牌的字体、Logo、组件造型或页面布局。

## 5. 现有骨架：保留与修复

### 5.1 必须保留

- 暖珊瑚、暖灰底、白色内容面的 Momcozy 视觉骨架；
- 左侧工作台导航和无登录访问；
- “概览 → 报告 → 洞察/分析 → 搜索证据 → 行动”的产品路径；
- 日报、周报、月报各自的业务故事线；
- 概览时间窗口、品牌健康度、帖子/VOC/负面率双轴趋势；
- 洞察页“用户画像置顶 + 用户痛点 / 舆情洞察 / 新品机会 / GEO 机会”结构；
- 指标 `?` 公式解释、卡内趋势线、上升红/下降绿；
- URL 可恢复筛选、原帖下钻、案例广场存量内容；
- 当前 V3 的 `OperationalReportSupplement` 真实报告路径，不恢复旧演示数据模型。

### 5.2 当前必须修复的设计债务

1. **Token 三源漂移**：`design-system.md` 使用 `#C45A6C`，源码主色使用 `#F8A67B`，Tailwind 与 TypeScript 图表色板不同。
2. **主色对比度不足**：浅珊瑚不适合承载普通白字按钮和小字号链接。
3. **静态卡片伪交互**：全局 hover 上浮让所有数据面看似可点击。
4. **数据新鲜度不可见**：只有“真实数据·已验证”，没有数据截至时间、run、release 与本次状态。
5. **移动端模块不可达**：案例、高价值内容、舆情信号、指标口径和采集后台缺少统一入口。
6. **洞察页形成第二套视觉系统**：任意圆角、渐变、半透明和阴影过多。
7. **超宽屏阅读失控**：缺少稳定的最大内容宽度。
8. **指标帮助组件分裂**：点击区域、键盘行为和公式内容不一致。
9. **报告归档交互不真实**：“最新完整周期”单选项没有选择价值，且缺少历史周期选择器。

## 6. V2.0 DESIGN.md 合同

### 6.1 单一事实源

实施时在前端根目录建立正式 `DESIGN.md`。设计 Token 只保留一个源文件，Tailwind、CSS 变量、图表和导出色板由该源派生，不再手工维护多份色值。

建议角色色：

| 角色 | 建议值 | 用途 |
|---|---:|---|
| `canvas-warm` | `#FAF8F5` | 页面底色 |
| `surface` | `#FFFFFF` | 主内容面 |
| `surface-soft` | `#F5F1EC` | 次级分组 |
| `ink` | `#1D1B19` | 标题与主文字 |
| `text-secondary` | `#625D58` | 正文 |
| `hairline` | `#E7E0D9` | 边框与分隔 |
| `coral-500` | `#F0A07A` | 图表、浅色品牌块 |
| `coral-700` | `#B84F37` | 按钮、链接、Focus |
| `coral-soft` | `#FFF1EA` | 选中背景 |
| `negative` | `#C64E4B` | 负面与风险 |
| `positive` | `#17825D` | 正面或下降改善 |
| `warning` | `#A66B00` | 警告 |
| `competitor` | `#56677A` | 竞品固定对照 |

业务色必须按角色固定：Momcozy 始终暖珊瑚；竞品始终低饱和冷灰蓝；正、负、中性不能因数组顺序改变。

### 6.2 字体、数字与密度

- 继续使用现有系统字体栈，避免中文衬线 fallback 破坏一致性；
- 层级：Display 32、Page 24、Section 20、Card 16、Body 14–15、Caption 12–13；
- KPI 使用等宽数字特性，数字与单位分层；
- 一屏只允许一个主结论，次级解释默认收拢；
- 间距采用 `4/8/12/16/24/32/48`；内容最大宽度 1440px。

### 6.3 卡片与层级

- `surface-card`：静态，无位移、无默认阴影；
- `interactive-card`：明确可点击，使用边框/底色变化，不依赖上浮；
- `overlay`：只用于 Drawer、Popover、Modal，可使用阴影；
- 标准卡片圆角 12px，重点面板 16px，Badge 全圆；
- 一个首屏最多一个暖色强调面，不连续使用大面积渐变。

### 6.4 交互合同

- 所有可点击项拥有 hover、focus、pressed、disabled；
- 指标 `?` 统一为一个组件：可点击、Tab、Enter/Space、Esc、点击外部关闭，实际触控区不小于 44px；
- Tab、筛选、时间窗口写入 URL，可复制与恢复；
- 图表必须提供业务问题、图例、单位、公式入口、证据下钻与空值规则；
- 动画只用于状态变化，截图模式和 `prefers-reduced-motion` 下关闭。

## 7. 页面级 V2.0 方案

### 7.1 全局框架

新增“数据新鲜度条”，常驻展示：

```text
数据截至 2026-07-22 07:00 · 本批 partial · 12 新帖 / 61 新评论
中心 reddit_voc_center_… · 投影 reddit_voc_release_… · 更新于 08:xx
```

状态规则：

- `fresh`：绿色文本，不使用整块绿色底；
- `partial`：琥珀色，点击显示覆盖缺口；
- `stale`：红色并显示上一成功期次；
- `failed`：不切数据，显示“本次更新失败，当前仍为上一通过版本”。

当前实现边界（2026-07-22）：页面已先接入证据型状态条，显示业务截至/最新观测事件、中心与投影版本、覆盖声明、采集 run 和结构债务。现有 release 没有 freshness SLA 状态与 collector run ID，因此只表达“版本与完整性已校验 / 观察口径 / 未提供”，不根据日期自行推导 fresh/stale。四态必须由 Gate 3/4 的 data publisher 在不可变 release 中显式提供后再启用。

桌面保留侧栏；移动端使用“核心五项底栏 + 更多菜单”覆盖所有生产模块。全局内容容器居中，最大宽度 1440px。

### 7.2 概览

首屏顺序固定为：

1. 数据新鲜度条；
2. 近 1 周 / 近 1 月 / 近半年窗口；
3. 帖子、VOC、负面占比、主要竞对四个 KPI；
4. 窗口品牌健康度与全历史基准并列；
5. 帖子/VOC 柱 + 负面率线的双轴趋势；
6. 痛点、风险、新品、GEO 四个决策入口；
7. 三项优先行动与证据下钻。

删减重复风险列表、重复图标和常驻展开的数据边界。健康度必须明确“窗口分”和“全历史基准”，不能让用户误认为总分随顶部 Tab 同口径变化。

当前实现边界：现有 7/30/183 天窗口只提供帖子、评论上下文 VOC、分类量、负面量、负面率和竞对，没有健康度四维输入。V2.0 当前只展示正式的全历史健康度并注明不随窗口切换；窗口健康度需新增正式投影与校验合同，禁止把全历史 `72.54` 复制到三个窗口。

### 7.3 日报：行动指挥

- 周期：上一完整自然日或已确认的 07:00—07:00 业务日，二者必须最终统一；
- KPI：新帖、活跃历史帖新增评论、总 VOC、负面占比；
- 主要异常：P0/P1 风险、增长最快痛点、重点品类/SPU；
- 今日行动：最多 3 项；证据：最多 5 条；
- 小时趋势只在原始时间精度确实为小时级时展示；
- `failed` 不生成业务日报，`empty success` 生成“本期无新增事件”。

### 7.4 周报：结构诊断

- 上一完整 ISO 周；
- WoW、可计算的 YoY、4/12 周趋势；
- 品类/SPU 驱动、社区与竞品对比；
- 用户痛点迁移、风险结构、上周行动复盘；
- 输出下周资源优先级，而非重复日报清单。

### 7.5 月报：战略取舍

- 上一完整自然月；
- 品牌健康及贡献拆解、MoM、YoY；
- 品类组合、SPU 机会、竞品差异；
- 风险与内容合规复盘、画像变化；
- 新品与 GEO 机会；
- 下月战略建议、责任域与验证指标。

### 7.6 洞察

- 将大面积数据口径面板收敛为可展开范围条；
- 用户画像作为首个内容模块；
- 保留四个主 Tab；
- 每个 Tab 使用同一协议：`管理问题 → 核心判断 → 数据证据 → 业务解释 → P0/P1/P2 行动 → 案例方法`；
- 案例用独立底色并标注“方法参照，不是本期数据”；
- 所有洞察统一为最近一个季度的数据 release，分母常驻。

### 7.7 分析、搜索、案例与信号

- 分析：增加页面级时间/品牌/品类/SPU 过滤器；区分经营诊断与数据探索；所有图表可下钻；
- 搜索：桌面采用筛选栏 + 结果 + 证据抽屉；移动端使用筛选 Bottom Sheet；帖子/评论粒度明确切换；
- 案例广场：保留存量与三视图，只接批准增量；修复无效页头搜索；
- 高价值内容：使用列表与可复用性/安全性/互动/证据完整度四维评分；
- 舆情信号：使用风险排序或时间线，不继续堆同质卡片；处理状态只能来自正式业务状态。

## 8. 每日数据到站架构

### 8.1 推荐架构

```text
07:00 新帖 + 活跃历史帖新增评论采集
  → immutable SourceBatch + validation receipt
  → single-writer canonical fusion
  → V2 center → V3 bridge
  → Base / Reports / Insights / Personas / Brand Health / Quarter 重建
  → data candidate validation
  → 版本化数据目录
  → 原子切换 current-data pointer
  → 页面新鲜度确认
  → 周期截图与钉钉发送
```

### 8.2 代码 release 与数据 release 分离

**推荐方案 A：**

- UI 镜像和前端代码继续使用精确 promotion packet，由人工受控提升；
- 数据 release 通过全部自动校验后，由 Reddit VOC 专属 publisher 原子切换；
- 洞察站只读挂载 `/opt/reddit-voc-insights-data/releases/<data_release_id>`；
- `/data-current/current-release.json` 指向当前通过版本；
- publisher 只写 Reddit VOC 专属数据目录，不写采集器、不重启洞察站、不修改共享 Nginx；
- 回滚只把数据指针切回上一通过版本。

**备选方案 B：** 每日仍生成整站 candidate 并等待人工 promotion。它保留最严格人工控制，但无法稳定满足“每天更新”，不建议作为 V2.0 常态。

### 8.3 运行门禁

| 条件 | 数据发布 | 报告发送 |
|---|---|---|
| `passed/full` | 允许 | 允许 |
| `partial` 且守恒/血缘通过 | 允许，显著标注 | 允许，显著标注 |
| `empty success` | 允许 | 发送“无新增事件” |
| `failed` | 不切换 | 不发业务报告，发独立告警 |
| manifest/SHA/lineage 不一致 | 不切换 | 不发送 |
| period 未闭合 | 不切换 | 不发送 |
| 与当前输入相同 | `no_change` | 不重复发送 |

需要修复现有缺陷：2026-07-19 采集失败且 0 数据时仍发送了钉钉消息。V2.0 必须把采集终态与业务发送门禁绑定。

### 8.4 调度实现

- 不把 V2.0 数据桥接塞进现有 collector cron；
- 新增 Reddit VOC 洞察站专属 one-shot pipeline 和独立 systemd timer；
- timer 只是 watchdog，真正触发条件是 source batch 和目标 period 已通过；
- 使用全局单写锁、batch consumption ledger、超时和可重入 checkpoint；
- 连续两个真实日周期先 shadow 对账，验证无差异后再允许自动切数据指针。

## 9. 日报、周报、月报截图与钉钉

### 9.1 当前能力与缺口

已具备：

- 日报 HTML/XLSX/CSV/PNG 产物；
- 服务端 Markdown payload、URL HEAD 检查、冻结 bytes、hash-chain ledger；
- `attempting`、`unknown_delivery_state`、重复发送防护和精确重试边界；
- 三周期真实报告页面和完整周期合同。

缺口：

- 当前日报 PNG 是独立 PIL/HTML 长图，不是洞察站真实 UI；
- 当前 prepared 钉钉正文不包含 PNG，现状是“生成截图”而非“推送截图”；
- 周报、月报没有 PNG、period bundle、outbox、调度与发送身份；
- 生产固定入口仍编码了旧 owner 决策，自动发送尚未启用；
- 浏览器端 webhook/localStorage 代码不能用于生产定时发送。

### 9.2 统一截图模式

在真实报告页新增无导航、无交互的确定性入口：

```text
/dashboard/reports?period=daily&capture=poster
/dashboard/reports?period=weekly&capture=poster
/dashboard/reports?period=monthly&capture=poster
```

截图模式必须：

- 隐藏侧栏、顶部导航、刷新、导出、Tooltip 和交互提示；
- 禁止动画、自动轮询、hover 依赖和骨架屏；
- 只读取绑定 release 的静态数据，不调用 webhook、Provider 或数据库；
- 设定 `data-report-capture-root` 与 `data-report-ready=true`；
- 在图内写明 grain、period、data release、report dataset、前端 release、覆盖状态和数据截止时间；
- 使用固定 `zh-CN`、Asia/Shanghai、light mode 和 Chromium；
- 截取指定节点，不使用无限 full-page；
- Playwright 失败即失败，不静默发送 PIL 替代图或上一期截图。

### 9.3 报告图片策略

首版推荐每个周期只推送：**一张经营摘要图 + 一段结论 + 完整报告链接**。

| 周期 | 建议画布 | 信息重点 |
|---|---:|---|
| 日报 | 1440 × 1800 | 当日状态、异常、风险、三项行动 |
| 周报 | 1440 × 2000 | 同环比、驱动、竞品、下周优先级 |
| 月报 | 1440 × 2200 | 健康度、品类/SPU、风险、机会、战略取舍 |

不再使用 4,000px 以上的整页长截图作为群消息主体。详细证据留在完整报告链接中。

### 9.4 不可变周期报告包

```json
{
  "grain": "daily|weekly|monthly",
  "period_id": "...",
  "data_release_id": "...",
  "reports_dataset_version": "...",
  "frontend_release_sha256": "...",
  "coverage_status": "full|partial|empty_success",
  "image_sha256": "...",
  "message_body_sha256": "...",
  "destination_fingerprint": "...",
  "capture_status": "validated"
}
```

发送前检查公开 PNG 和完整报告 URL 的 HTTP 200、bytes、SHA、期次和 release。幂等键为：

```text
grain + period_id + data_release_id + destination_fingerprint
```

已开始外部请求后超时必须进入 `unknown_delivery_state`，禁止自动重发。

### 9.5 推荐发送节奏

时间不是硬触发，而是 release-ready 后的期望时间：

- 日报：每日预计 08:30，最晚 09:00；
- 周报：周一 09:00，上一个完整 ISO 周；
- 月报：每月 1 日 09:30，上一个完整自然月；
- 若每月 1 日同时是周一，保持 09:00 / 09:30 错峰；
- 数据未完成时延迟并告警，不发送旧报告冒充本期。

## 10. 实施阶段

### Phase 0：设计与发布决策冻结（1—2 天）

- 确认代码/数据双 release；
- 确认深珊瑚交互色；
- 确认截图“一图 + 链接”、发送时间、目标群和授权周期；
- 确认旧日报推送迁移策略；
- 冻结 `DESIGN.md`、数据发布合同和周期报告包 schema。

### Phase 1：设计系统与全局框架（3—5 天）

- 统一 token 单一事实源；
- 修复对比度、卡片层级、最大宽度和移动导航；
- 建立新鲜度条和统一指标帮助组件；
- 建立桌面/平板/390px/截图模式视觉基线。

### Phase 2：核心页面精修（5—8 天）

- 概览首屏重排；
- 日/周/月三套信息架构；
- 洞察视觉收敛与统一叙事卡；
- 分析过滤与下钻；
- 搜索、案例、内容、信号的专用组件。

### Phase 3：每日数据到站（5—8 天）

- 完成 SourceBatch → center → V3 bridge；
- 同源重建所有 surface；
- 构建数据 candidate 和独立 validator；
- 实现版本化数据目录、current-data pointer 和回滚；
- 两个真实日周期 shadow 对账。

### Phase 4：周期截图与钉钉（4—6 天）

- capture mode、Playwright 引擎、图片与 manifest 门禁；
- 通用 periodic report bundle；
- Markdown 引用公开 HTTPS PNG；
- 周/月 outbox、ledger identity 和调度；
- 替换失败仍发送、重复发送和旧图发送漏洞。

### Phase 5：开发—测试—验收—上线（3—5 天 + 观察期）

- unit、integration、data contract、same-dist E2E、视觉回归、导出和安全检查；
- 本地 dry-run 与只读 candidate smoke；
- 一次明确授权的钉钉测试群发送；
- UI 代码使用受控 promotion；数据自动切换另行明确授权；
- 观察 3 个日报、1 个周报、1 个月报周期后关闭上线观察。

## 11. 验收矩阵

### 11.1 UI 与交互

- 全站只有一个正式 token 源；
- 没有未经登记的业务色、圆角和阴影；
- 静态卡片无 hover 位移；
- 390px 可进入所有生产模块；
- 关键交互均支持键盘和可见 Focus；
- 时间、筛选和 Tab 可通过 URL 恢复；
- 概览首屏完成“状态—变化—行动”；
- 日/周/月不是同一组件换标题。

### 11.2 数据

- post/comment accounting 守恒；
- 同 batch 重放 `no_change`；
- 所有 surface 绑定同一个 data release；
- 采集到生产数据 P95 小于 90 分钟；
- 失败保持上一 release，partial 明示覆盖；
- 6,953 条待关联评论债务继续显式保留，不因日更被吞掉。

### 11.3 截图与钉钉

- 三周期各生成合规 PNG 与 manifest；
- 图中文字、图例、日期和单位在钉钉手机端可读；
- 截图、页面和导出数字一致；
- 图片无侧栏、滚动条、骨架屏、截断和旧数据；
- 相同期次和目标最多成功一次；
- `failed` 不发送，`unknown` 不自动重发；
- webhook/secret 只存在 repo 外 mode-600 环境，不进入前端、日志或报告包。

### 11.4 生产隔离

- 只变更 Reddit VOC 洞察站代码、专属数据目录和专属调度；
- 采集器、共享 Nginx、TLS、DNS 和其他 Docker 身份、配置、健康与重启次数不变；
- UI 回滚和 data pointer 回滚均经过演练。

## 12. 主要风险与处置

| 风险 | 处置 |
|---|---|
| 日报采集结束时间不稳定 | release-ready 事件驱动，时钟只作 watchdog |
| partial 被误读为完整 | 页面、截图和消息同时显示覆盖状态与缺口 |
| 日报出现双重推送 | 新链 7 天 shadow；切换日只启用一个 authoritative sender |
| 图片过长、手机不可读 | 固定经营摘要画布，详细内容通过报告链接承接 |
| UI 与截图两套样式 | screenshot 复用真实报告组件，不继续扩展 PIL 视觉模板 |
| 每日数据发布污染代码发布 | app release 与 data release 独立，分别授权、验证和回滚 |
| 自动发送扩大外部副作用 | bounded schedule policy、目标指纹、幂等键和可撤销授权 |

## 13. 需要产品 Owner 确认的决策

> 2026-07-22 Owner 已确认 D1—D6，以下决策全部冻结并进入实施。

### D1：数据发布模式

推荐采用“UI 代码人工受控提升 + 验证通过的数据 release 每日自动原子切换”。若不接受，则每日数据只能停在 candidate 等待人工 promotion。

### D2：旧日报推送迁移

推荐新旧链先 shadow 7 天；新链不外发，只比对数据和图片。通过后关闭旧链的钉钉发送分支，保留其采集与原始产物，避免每天收到两份日报。

### D3：截图和推送节奏

推荐每周期“一张经营摘要图 + 结论 + 完整报告链接”；日报预计 08:30、周一 09:00、每月 1 日 09:30。数据未就绪则延迟，不发旧报告。

### D4：自动发送授权

推荐使用可撤销、最长 30 天的 bounded schedule policy，并绑定目标群指纹。若坚持逐期人工 permit，可降低外部副作用，但不能实现稳定无人值守推送。

### D5：品牌交互色

推荐保留 `#F8A67B` 作为品牌资产/图表色，新增 `#B84F37` 作为按钮、链接和 Focus 交互色，以解决文字和白字按钮对比度不足。

### D6：目标钉钉群

日报、周报、月报发送到同一个管理群。仓库和文档只记录不可逆的 destination fingerprint，不记录 webhook。

## 14. 当前边界

### 14.1 2026-07-22 Gate 2 报告实现检查点

- 日报、周报、月报继续消费当前 V3 真实报告与 Base 数据，没有恢复旧 Mock 模型；帖子周期归属已统一为 Asia/Shanghai 自然日。
- 日报当前完整自然日可召回 6 条 Momcozy 相关新帖，证据列表固定为 5 条；异常加速度、环比、同比只在报告已有可计算值时出现。
- 日/周/月使用各自的 4/4/5 步叙事路径，分别承接今日行动、下周资源和下月指标，不再只是同一套卡片换标题。
- 无意义的“最新完整周期”单选按钮已删除。该检查点当时只有三个业务入口，内部 archive 明确 `business_entry_visible=false`，因此当时不伪造归档选择器；后续 14.2 已以独立业务历史合同补齐。
- 全量前端通过 204 项测试，46 项旧合同测试按既有门禁跳过；lint 只有 7 条既有 Fast Refresh warning；typecheck 和 build 通过。
- 报告页 12 个 desktop/tablet/390px/reduced-motion 视图通过；13 路由 desktop/390px same-dist E2E receipt SHA 为 `f1efb17f4ac3add2ce43c668a3661dfa369be1075d0abc8ad34d9ffe4eb27844`。
- 该检查点仍缺四类上游业务数据；其中活跃历史帖新增评论拆分、月度健康四维贡献和多个业务可见历史报告周期已在后续批次补齐。周行动回写账本仍未提供，UI 继续显示真实空状态。

### 14.2 2026-07-23 业务历史报告检查点

- 新增独立 `reddit_voc_business_history_index_v1`，包含最近 14 个完整日报、12 个完整周报、12 个完整月报；与 3 个最新完整周期合计 41 个业务入口。
- 3 个 internal comparison archive 继续保持 `business_entry_visible=false`，因此业务入口 41 个、报告文档 44 份；没有混用业务历史与内部同环比基期。
- 正式 candidate manifest 声明 46 个文件；公开 manifest 增加嵌入验证 receipt 后声明 47 个文件。前端 bootstrap 固定为 9 个报告文件，不预取 38 份历史正文。
- 前端仅接受已通过 `business-history-index` 与 manifest SHA 绑定的 `period_id`；选择历史周期时懒加载一份报告，URL 使用 `period` + `period_id` 支持刷新与返回。
- 历史零观察周期不采用当前页的扩窗背景；页面周期标题、治理范围、导出文件名和报告故事均取当前实际选中的历史报告。
- 修订后的正式版本为不可变 `reddit_voc_reports_20260723_v3_382d621ae075_history2`；candidate manifest SHA 为 `3240005aec33b9e519674797eb5265c9f8a1ce7e94011446fdce3b9d71ead2c6`，公开 manifest SHA 为 `637a955282fa4eed78efee682a967978702104a1de2c9cd52ce522d0ed62e72f`，本地 current-release SHA 为 `5207fcdc85c0e21c555b16a87e43718e3a8ad93caa8582f383bc5ce42af55669`。`history1` 不再作为当前本地版本，避免同版本不同 manifest。
- 真实周期指标确定性重放、公开隐私投影、49 项相关 Python 与 dist 审计测试、前端全量 212 项测试（46 项既有合同门禁跳过）、lint/typecheck/build、真实 dist audit 和 Chrome 桌面/390px 深链验收通过。首屏 history 请求 0，选择和深链各 1；横向溢出 0，浏览器错误 0。历史加载中/失败时禁止导出，递归未声明文件、祖先 symlink 以及周期 ID/日期跨度/路径不一致均 fail-closed。
- 发布流程边界：裸 `vite build` 会把 `public/data` 中为回滚保留的历史版本一并复制进 `dist`，它不是最终可发布投影。正式发布脚本必须继续执行 `audit_insights_dist.py --prepare-dist` 收敛到 current-release 精确文件集，并在收敛后再次执行只读 dist audit；禁止直接上传裸 build 目录。

### 14.3 副作用边界

本轮只修改本地代码、测试、候选 dist 与本地验收产物，没有修改生产、调度、数据库、Docker 运行环境或钉钉发送状态。任何真实部署、数据自动切换、旧日报发送关闭或钉钉测试发送，都需要在对应阶段取得精确授权。

### 14.4 2026-07-23 `history2` 受控提升候选

- `history2` 已完成不可变 linux/amd64 候选构建；release SHA 为 `ebaa5443906628145f9fbe05777d4218b1ec6d53b78e9d7f4f86fa8fbe9df313`，release manifest SHA 为 `eed2e50b16f71c910c344e395bb4b78365e6d12139604df59e69bb089cf44181`，transfer TGZ SHA 为 `59381d040b9d74fb293e0704f74e2e0ba2cfc8c6c279e59bb759044611d3f22a`。
- 构建门禁通过前端 212 项测试、46 项既有合同跳过、lint（0 error、7 条既有 Fast Refresh warning）、typecheck、production build、三轮精确 public projection audit 和 115 文件隔离 Docker context 对账。
- 同一不可变 dist 的 13 路由 × desktop/mobile E2E 已通过，强化版回执 SHA 为 `a423f31fe195f6d55d5c1c67a425b16e3fd53a63e668484fb53d88c086d56758`。验收不再只数选项：日报、周报、月报分别真实选择一个历史周期，逐一核对唯一 history JSON 请求、选择值、页面 `data-period-id`、URL `period_id`，并另验日报直接深链；同时保持无旧“闭合期”术语、无 `00:00` 日报横轴标签和无外部请求。
- 本地只读容器 smoke 回执 SHA 为 `f97a37e599eb4e675c9ccdc6926ea230e6de04f2b4d6410924c4520f0d2799bd`；CSV/PDF/PPTX/DOCX 四导出实际生成并验证，最终回执 SHA 为 `337cfad82828d249605f794ca0a982987ce0a3a88093ba1fc01bc5722d2eb1f5`。回环地址证据正确标记为 `L2_local_container_readonly_browser_download_acceptance`，状态同步改为 `passed_local_readonly_export_acceptance`；公网 L3 仅允许非回环 HTTPS。安全聚合回执 SHA 为 `abb0fe2a7e3989a77425d42b68457a18607a597c54b78fa753b06c1ad362e24c`，除 release manifest、compose、`SHA256SUMS`、dist sums、镜像 tar 与 smoke 交叉绑定外，还强制五项格式/业务内容校验及报告身份绑定全部为真。
- 最终原子候选 ID 为 `096fd5dd6d85f765d7efbf2b31a0a38e4e8c6d30f28eb0dba4ceb5e45201e127`，candidate input SHA 仍为 `4bffdb761d45223c4ab444724a119750b98c5ff957258683e96265a8acf55cb9`，candidate UI receipt SHA 为 `791d71949a1e8e43c1f71b4b4bd9efcb9a70e798f4f58be539ff437b32c12379`。独立 registry 复验为 5 entries / 5 commits / 0 failed / 0 blocked / 0 pending；早期候选保留为追加式审计历史，但不再是最终授权依据。
- 最终生产只读基线于 `2026-07-22T19:30:32Z` 验证当前 release 仍为 `e8bea1546862cd9de974ae40429f9b58e0e4b50eef72f6743840b95e19086a3b`，采集器、翻译服务、洞察容器、cron、共享 Nginx、数据库和 58 个运行容器的清单在双观测窗口内保持稳定；基线回执 SHA 为 `b3a1f2d5aeb2336e4d3f349494155ad84d0c141685062c34e9986d876754ad46`。
- 当前唯一能通过最新 validator 的未授权 promotion packet SHA 为 `ec3458cbd1a4d045222d5a1a5df8e54084b43383d9cb683c8aabf5c6211c2507`。它把 candidate UI receipt 提升为第 21 项直接绑定制品，从而闭合 E2E、smoke、export、security 与最终候选证据链；状态仍是 `ready_for_owner_authorization`、`promotion_authorized=false`、`consumed=false`、`deploy=false`、`remote_write=false`。包在 `2026-07-22T21:30:58Z`（北京时间 `2026-07-23 05:30:58`）过期。旧 packet `b1f7d535...` 与中间 packet `0b32371e...` 均被最新 validator 以 `artifacts_unexpected_fields` 机器拒绝，不得再授权或复用。
- 历史 V3 许可证兼容不是通用降级开关：仅三组已存在许可证按 `authorization_id + permit SHA + packet SHA + release SHA` 四元组精确白名单读取旧 20 工件包；新建许可证始终执行当前 21 工件合同。使用未列入白名单的授权 ID 为旧包构造许可证会在落盘前以 `artifacts_unexpected_fields` 失败，且不产生许可证文件。
- 最终回归把三组历史 V3 四元组逐一重开，并把旧 20 工件包新建许可证失败且不落盘固化为自动测试；发布控制定向测试为 32 项通过，完整聚焦回归为 118 项通过、2 个子测试通过。
- 本检查点没有上传制品、远端 `docker load`、启动 18339 候选、切换 production current、修改采集器/cron/共享 Nginx/TLS/DNS/其他 Docker，也没有钉钉发送或 Provider 调用。

### 14.5 2026-07-23 `history2` 受控生产提升完成

- 原 packet `ec3458cbd1a4...1c2507` 在授权到达时已经过期，validator 以 `packet_expired` 停止且未产生远端副作用；刷新 L3 基线后生成并由 Owner 精确授权 packet `91a5a9143a45...184d717` 与同一 release `ebaa54439066...9df313`。
- 一次性 authorization ID 为 `reddit_voc_promotion_db834fe7f741c0fb5def8957`，permit SHA 为 `afa01f74fcaf...9530b755`，九参数执行合同 SHA 为 `8699fe35301a...637220b9`。远端 runner 在同一 `.deploy.lock` 内验证精确制品、回滚 current、采集静稳和不干扰边界，完成 18339 候选 smoke 后仅对洞察站执行 CAS 切换。
- 远端 promotion receipt SHA 为 `f34148b00c16...7035c49c`；公网 HTTP 验收为 13 个业务路由 200、8 个公开工件 200、20 个敏感路径 404，回执 SHA 为 `ee2ec6ece804...83399fc`；Playwright CLI 0.1.17 完成桌面/移动端 26 页真实公网验收，零浏览器错误、零同源 HTTP 失败、零外部请求，回执 SHA 为 `2093e8c6e897...925ee894`。
- 最终 production acceptance SHA 为 `f4faf9b94329...ee3ff22`，promotion consumption SHA 为 `9c0f26442fe0...7d564fc5`，均可重新打开验证。生产 current、容器 release label、内部 `/release.json` 和数据 pointer 均为 `ebaa54439066...9df313` / `reddit_voc_release_20260723_business_history_002`。
- 切换后 collector 与 translation 的容器 ID/重启次数保持不变，cron SHA、共享 Nginx SHA 和数据库 marker 保持不变；运行容器数仍为 58，18339 候选容器和监听均为 0。未修改采集器、cron、共享 Nginx、TLS、DNS、其他 Docker、数据库、Provider、调度或钉钉发送。
