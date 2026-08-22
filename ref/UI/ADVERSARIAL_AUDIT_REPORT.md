# 对抗性组件架构审计报告

**项目**: `momcozy-reddit-workbench`  
**审计范围**: `src/` 下全部 `.tsx/.ts` 文件  
**审计日期**: 2026-07-13  
**审计方法**: 静态代码分析 + 架构模式审查 + React 最佳实践对标  

---

## 1. 严重问题 (Critical)

### C1. Sidebar.tsx: 嵌套 `<button>` 导致非法 DOM 结构
- **文件**: `src/components/Sidebar.tsx:170-199`
- **问题**: `Collapse / Expand Toggle` 外层 `<button>` 内部又嵌套了一个同级的 `<button>`（第 182 行开始）。这是**无效的 HTML**——浏览器会自动修正这种嵌套，导致事件委托和 ARIA 状态不可预测。此外，第二个按钮缺少 `collapsed` 的条件样式，意味着在折叠状态下会渲染出两个重叠的切换按钮。
- **修复**: 删除外层 `<button>`，保留内层；将条件样式统一移到单个按钮上。

### C2. Dashboard.tsx: 渲染阶段同步调用外部 Store Setter
- **文件**: `src/pages/Dashboard.tsx:475-476, 492`
- **问题**: 在 `useEffect` 中通过 `useNotificationStore.getState().addItem(n)` 直接调用另一个 Zustand store 的 setter。虽然 Zustand 允许 getState() 访问，但在 React 的渲染/提交阶段（effect 执行期间）触发另一个组件的状态更新，在 **React StrictMode 下或未来并发特性下可能导致 tearing**——即 NotificationCenter 渲染了不一致的状态。
- **修复**: 将通知添加逻辑封装到 NotificationCenter 内部，或通过事件总线解耦；或确保在 `startTransition` 中执行。

### C3. Dashboard.tsx: `handleRefreshData` 竞态条件
- **文件**: `src/pages/Dashboard.tsx:400-404`
- **问题**: `setDataSeed(newSeed)` 后立即调用 `refreshAll()`，但 `refreshAll` 内部的闭包通过 `get()` 获取 `dataSeed`。由于 `setDataSeed` 和 `refreshAll` 都是同步调度，Zustand 的 set 是同步的，所以这里实际上能工作，但**架构上依赖了 implementation detail**。更危险的是，如果用户快速连续点击刷新，`refreshAll` 中的 `Promise.all` 会产生多个并行的生成任务，而 `isLoading`/`isRefreshing` 的覆盖逻辑可能导致最终状态不一致。
- **修复**: 在 `refreshAll` 中添加 inflight 请求取消机制（AbortController 或序号 token），并在 `handleRefreshData` 中防抖。

### C4. reportStore.ts: `refreshAll` 与 `refreshPeriod` 状态覆盖
- **文件**: `src/stores/reportStore.ts:66-137`
- **问题**: `refreshAll` 设置 `isLoading: true, isRefreshing: true`，而 `refreshPeriod` 只设置 `isLoading: true`。当两者同时执行时（如 Dashboard 切换 tab 时 `refreshPeriod` 触发，同时用户点击刷新触发 `refreshAll`），后者的 `set({ isLoading: false })` 会**覆盖前者**，导致 spinner 提前消失。此外 `refreshAll` 中对同步函数 `generateReportData` 使用 `Promise.resolve().then()` 是多余的，但这掩盖了真正的问题：所有三个报告生成是同步阻塞的，会冻结主线程。
- **修复**: 引入请求序号计数器，只有最新请求才能更新 loading 状态；将报告生成移入 Web Worker 或拆分为异步 chunk。

---

## 2. 高风险问题 (High)

### H1. Search.tsx: 状态爆炸 + 硬编码业务逻辑
- **文件**: `src/pages/Search.tsx`（约 800 行）
- **问题**: 同时管理两套完全独立的筛选状态（搜索结果筛选 + 存量筛选）。`brandKeywords` 在第 181-189 行硬编码：`['momcozy', 'elvie', 'spectra', 'medela', 'willow', 'lansinoh']`；`brandOptions` 和 `categoryOptions` 也是硬编码字符串数组。这意味着任何品牌增减都需要修改组件源码。
- **修复**: 提取为配置常量或从 API/配置中心获取；将两套筛选逻辑拆分为自定义 hook。

### H2. Dashboard.tsx: 单一组件职责严重超载
- **文件**: `src/pages/Dashboard.tsx`（750 行）
- **问题**: 该组件同时承担以下职责：
  1. Tab 导航和报告周期切换
  2. 搜索输入 UI
  3. 导出数据构建（`buildExportSections`，286 行纯数据转换逻辑）
  4. 竞品数据处理（雷达图、趋势图数据生成）
  5. Webhook 推送管理和轮询状态展示
  6. 通知中心的数据源管理（`notifItems`）
  7. 定时推送逻辑（`getScheduledPushSettings`）
  8. 自动触发 webhook 的副作用
  这违反了 SRP，导致该组件几乎无法单元测试。
- **修复**: 将 `buildExportSections` 移至 `services/exportBuilder.ts`；将 webhook/通知逻辑提取为 `useDashboardNotifications` hook；将竞品图表数据提取为 `useCompetitorChartData` hook。

### H3. `useAsync` Hook: 设计缺陷导致 stale closure
- **文件**: `src/hooks/index.ts:96-131`
- **问题**: 第 105 行 `// eslint-disable-next-line react-hooks/exhaustive-deps` 是**设计缺陷的遮羞布**。`deps` 数组由调用方传入，但 `asyncFn` 本身如果捕获了外部变量，调用方无法在 `deps` 中正确声明这些变量——因为 `asyncFn` 是在 render 中内联定义的。这本质上是一个无法正确使用的 API。此外，`cancelled` flag 只能在 resolve 后丢弃结果，**无法真正取消进行中的网络请求**（没有 AbortController 暴露）。
- **修复**: 重新设计 API 为 `useAsync(asyncFn, deps, { signal? })`，内部创建 `AbortController` 并在 cleanup 时 abort；移除 eslint-disable，要求调用方显式声明依赖。

### H4. InsightCard.tsx: 纯展示组件却完全硬编码数据
- **文件**: `src/components/InsightCard.tsx:3-25`
- **问题**: `insights` 数组在组件顶部完全写死，没有任何 props 注入能力。组件名为 "Card" 暗示可复用，但实际上是不可配置的死组件。
- **修复**: 接收 `insights: InsightItem[]` 作为 props，将硬编码数据上提到调用方。

### H5. BrandScoreCard.tsx / ReportMonthlyView.tsx: Magic Number 未注释
- **文件**: 
  - `src/components/BrandScoreCard.tsx`（strokeDasharray 计算）
  - `src/components/reports/ReportMonthlyView.tsx:65` — `strokeDasharray={`${(brandHealthScore || 0) * 2.64} 264`}`
- **问题**: `2.64` 来自 `2 * PI * 42 / 100 ≈ 2.6389`，`264` 来自 `2 * PI * 42 ≈ 263.89`。这些 magic number 没有任何注释，且是近似值。不同浏览器对 SVG 路径的舍入可能有 1px 偏差，导致圆环出现缝隙或重叠。BrandScoreCard 中使用的是 `3.27` 和 `326.73`（半径 52），同样无注释。
- **修复**: 提取为命名常量 `CIRCLE_CIRCUMFERENCE = 2 * Math.PI * radius`，在运行时计算。

### H6. SankeyChart / WordCloudChart: 缺少 ResizeObserver 回退
- **文件**: `src/components/charts/SankeyChart.tsx`, `src/components/charts/WordCloudChart.tsx`
- **问题**: `useEffect` 中直接 `new ResizeObserver()`，在不支持该 API 的旧版 Safari 中会抛出异常，导致整个组件树崩溃。虽然项目面向现代浏览器，但代码中没有任何 `typeof ResizeObserver !== 'undefined'` 的保护措施或 polyfill 提示。
- **修复**: 添加特性检测 + window resize 回退，或将 ResizeObserver 使用封装在 try-catch 中。

### H7. NotificationCenter: `useSearch` 接收不稳定引用
- **文件**: `src/components/NotificationCenter.tsx`（推断）
- **问题**: 如果 `notifications.filter((n) => !n.read)` 在每次渲染时创建新数组并传给 `useSearch`，则 `useSearch` 内部的 `useDebounce` 会在每次渲染时触发，因为 `items` 引用变化。
- **修复**: 在 NotificationCenter 内部用 `useMemo` 缓存过滤后的未读通知数组。

### H8. ExportButton.tsx: 内存泄漏风险
- **文件**: `src/components/ExportButton.tsx:357-365`
- **问题**: `timerRefs.current` 用 `Set` 存储 timeout ID，但 cleanup 只在组件卸载时执行。如果 `handleExport` 被连续调用（用户快速切换导出格式），前一次的 error/done 定时器不会被清理，Set 会无限增长。虽然增长极慢，但在长时间运行的 SPA 中是理论上的内存泄漏。
- **修复**: 在每次 `handleExport` 开始时清理所有已存在的定时器；或改用 `useRef<number | null>` 只跟踪最新一次调用的定时器。

---

## 3. 中风险问题 (Medium)

### M1. CompetitorComparison.tsx: `useMemo` 依赖数组无效
- **文件**: `src/components/CompetitorComparison.tsx`
- **问题**: `useMemo(() => enabledBrands(), [enabledBrands, brands])` 中，`enabledBrands` 是 store getter 函数（引用稳定），但 `brands` 是数组引用。由于 Zustand 默认不做结构共享，`brands` 每次 store 更新都会是新引用，导致 `useMemo` 实际上**从未缓存**。
- **修复**: 改用 `useCompetitorStore(s => s.brands.filter(b => b.enabled))`，让 Zustand 的 selector 机制处理订阅优化。

### M2. TopicCluster.tsx: `maxCount` 重复计算
- **文件**: `src/components/TopicCluster.tsx`
- **问题**: BubbleView 和 ListView 各自独立计算 `maxCount`，每次渲染都遍历两次数组。
- **修复**: 在父组件中计算一次 `maxCount` 后通过 props 传入。

### M3. ReportDailyView.tsx: FunnelChart 数据在渲染中过滤
- **文件**: `src/components/reports/ReportDailyView.tsx:659-671`
- **问题**: `data.newPosts.filter((p) => p.intent === 'Question')` 等过滤逻辑在 JSX 中直接执行，每次渲染遍历整个 `newPosts` 数组 3 次。
- **修复**: 用 `useMemo` 缓存漏斗数据。

### M4. CategoryInsightsPanel / SentimentInsightsPanel 等: 搜索过滤重复模式
- **文件**: `src/components/insights/*.tsx`
- **问题**: 四个 panel 都重复实现了相同的搜索过滤模式：`const q = searchQuery.toLowerCase(); const filteredX = q ? ...filter... : ...`。这是典型的 DRY 违反。四个 panel 还各自定义了相同的 `empty` JSX 片段。
- **修复**: 提取 `useSearchFilter<T>(items, searchQuery, fields)` hook 和 `<EmptySearchResult query={...} />` 组件。

### M5. ReportWeeklyView.tsx: 类型断言泛滥
- **文件**: `src/components/reports/ReportWeeklyView.tsx:426-429`
- **问题**: `(data.weeklyOpportunities as WeeklyOpportunity[])` 等四处类型断言，说明 `UnifiedReportData` 的类型定义没有正确区分各周期的字段。如果后端返回的数据结构不符，这些断言会在运行时静默失败。
- **修复**: 使用 discriminated union (`{ period: 'weekly'; data: WeeklyReportData }`) 或严格化 `UnifiedReportData` 的类型定义。

### M6. ReportMonthlyView.tsx / EnhancedStrategicAdvice: `as unknown as Record<string, ...>`
- **文件**: `src/components/reports/ReportMonthlyView.tsx:335-349, 361-365`
- **问题**: `(advice as unknown as Record<string, Record<string, string>>).resourceAllocation` 等类型体操表明数据结构未正确建模。这不是类型安全，是类型欺骗。
- **修复**: 正确定义 `StrategicAdvice` 类型，包含可选的 `resourceAllocation` 字段。

### M7. CaseCardGrid.tsx: tag click 事件处理在 `<a>` 内部
- **文件**: `src/components/case-gallery/CaseCardGrid.tsx:100-103`
- **问题**: tag 的 `onClick` 调用了 `e.preventDefault(); e.stopPropagation();`，但 tag 是 `<a>` 标签内部的 `<span>`。如果 `handleTagClick` 包含导航逻辑，这种事件拦截容易出错。
- **修复**: 将 tag 改为 `<button>`，或把卡片的整体点击和 tag 点击通过 CSS `pointer-events` 分离。

### M8. SearchBar.tsx: `onBlur` + `setTimeout` 反模式
- **文件**: `src/components/case-gallery/SearchBar.tsx:60`
- **问题**: `onBlur={() => setTimeout(() => setShowHistory(false), 200)}` 依赖 magic number 200ms 来允许点击历史项。如果用户在 200ms 内未点击，下拉框会消失；如果超过 200ms，用户可能点击到了已消失的 DOM。
- **修复**: 使用 `onMouseDown` + `useRef` 跟踪焦点状态，或改用 Radix UI / Headless UI 的 Popover 模式。

### M9. `timeRange` 类型不一致
- **文件**: 
  - `src/pages/Analytics.tsx`: `'7d' | '30d' | '90d'`
  - `src/components/TopicCluster.tsx`: `TimeRange`（来自 types）
  - `src/components/SentimentAnalysis.tsx`: 接收 `TimeRange` 后传给 `getSentimentOverview`
- **问题**: Analytics 使用了字面量联合类型，而 TopicCluster 使用导入类型，SentimentAnalysis 的 mock 数据函数可能未处理所有 case。类型不统一增加了重构风险。
- **修复**: 统一使用 `src/types/index.ts` 中定义的 `TimeRange`，并在所有消费处做 exhaustive check。

---

## 4. 低风险问题 / 技术债务 (Low)

### L1. hooks/index.ts: 多个 hook 共用一个入口文件
- **问题**: 文件已膨胀到 138 行，且同时导出内联 hook 和外部文件 hook。随着项目增长，这会成为 tree-shaking 和代码分割的障碍。
- **修复**: 每个 hook 独立文件，index.ts 只做 re-export。

### L2. `import.meta.env.VITE_USE_MOCK` 硬编码在多处
- **文件**: `src/services/insightService.ts:23`, 及其他 service 文件
- **问题**: 切换 mock/prod 需要在每个 service 文件中检查环境变量，没有统一的 API client 拦截层。
- **修复**: 在 `lib/api.ts` 中统一处理 mock 拦截。

### L3. BrandInsightsPanel: 竞品品牌硬编码
- **文件**: `src/components/insights/BrandInsightsPanel.tsx:108-116`
- **问题**: 品牌对比只显示 Momcozy/Elvie/Spectra，且标签和进度条都写死了这三个品牌。
- **修复**: 从 `data` 中动态提取竞品品牌列表。

### L4. PostDetailDrawer: 内容摘要为模板字符串生成
- **文件**: `src/components/PostDetailDrawer.tsx:221-230`
- **问题**: 帖子的"内容摘要"是写死的模板字符串拼接，不是真实内容摘要。这是展示层的造假。
- **修复**: 从 API 返回 `summary` 字段，或在前端做真实的内容截断。

### L5. ReportDailyView / ReportWeeklyView / ReportMonthlyView: 大量内联子组件
- **问题**: 三个报告视图文件都在同一个文件中定义了 5-8 个子组件。虽然这些是 presentational 组件，但导致文件体积过大（DailyView 736 行），且这些子组件无法被其他视图复用。
- **修复**: 将可复用的子组件（如 SentimentThermometer、PriorityMatrix）提取到独立文件。

### L6. Dashboard.tsx: `processedPeriodsRef` 的 Set 清理逻辑有漏洞
- **文件**: `src/pages/Dashboard.tsx:459-463`
- **问题**: `Set.values().next().value` 获取的是 Set 中插入的第一个元素，不是最旧的。虽然 Set 保持插入顺序，但这里的语义是"清理过期条目"，实际上删的是最早的——如果用户来回切换 tab，这个逻辑恰好能工作，但依赖了 Set 的有序性这一 ES2015+ 特性，且语义不清晰。
- **修复**: 使用 LRU Map 或带时间戳的清理策略。

### L7. 图表组件缺少错误边界
- **文件**: `src/components/charts/*.tsx`
- **问题**: recharts 在数据格式异常时会抛出渲染错误，导致整个页面白屏。没有 ErrorBoundary 包裹图表组件。
- **修复**: 在图表组件外层包裹轻量级 ErrorBoundary，降级为"图表渲染失败"提示。

### L8. `reports/shared.tsx` 导出模式不透明
- **问题**: `shared.tsx` 和 `index.ts` 的导出结构增加了理解成本，且 `shared.tsx` 的内容未在本次审计中读取。
- **修复**: 确保 shared.tsx 只包含真正跨视图复用的组件。

---

## 5. 架构层面的系统性问题

### S1. Mock 数据与生产代码深度耦合
- **表现**: 
  - `insightService.ts` 直接 `import` mock 数据文件
  - `ReportDailyView` 从 `getEnhancedWordCloudData()` mock 函数获取数据
  - `useReportStore` 的 `refreshAll` 动态导入 `reportEngine`（mock 生成器）
- **风险**: 移除 mock 时需要改动大量文件，无法通过环境变量干净切换。
- **建议**: 建立统一的 `MockAdapter` 层，在 `api.ts` 中根据环境变量决定是否拦截请求。

### S2. 缺少组件级别的 Error Boundary
- **表现**: 全局只有一个 `ErrorBoundary.tsx`，但图表、报告视图、洞察面板等复杂组件都可能独立出错。
- **风险**: 一个图表组件崩溃导致整个 Dashboard 不可用。
- **建议**: 在 Dashboard 的各区域卡片（SectionCard）级别添加错误边界。

### S3. 状态管理分散
- **表现**: 
  - Zustand store: reportStore, notificationStore, competitorStore
  - 本地 useState: Dashboard 的 `notifItems`, Search 的双套筛选状态
  - URL 状态: `useUrlParams` 只在部分页面使用
- **风险**: 同一业务实体（如通知）同时存在于 local state 和 global store 中，Dashboard.tsx 的第 475-476 行就是这种混乱的集中体现。
- **建议**: 通知数据应完全由 `notificationStore` 管理，Dashboard 只通过 hook 消费，不自行维护 `notifItems`。

### S4. 类型系统的信任危机
- **表现**: 大量 `as`, `as unknown as`, `|| '默认值'` 的类型断言和回退。
- **风险**: TypeScript 变成了 "AnyScript"，编译通过不代表运行安全。
- **建议**: 启用 `strict: true` 并清理所有 `as unknown`；在数据入口层（service/api）使用 zod/io-ts 做 runtime validation。

---

## 6. 修复优先级矩阵

| 优先级 | 问题 | 影响 | 修复工作量 |
|--------|------|------|-----------|
| P0 | C1 Sidebar 嵌套 button | DOM 结构错误，UI 异常 | 5 分钟 |
| P0 | C2/C3 Dashboard store 竞态 | 状态不一致，tearing | 2 小时 |
| P0 | C4 reportStore 状态覆盖 | 加载状态异常 | 1 小时 |
| P1 | H1 Search.tsx 硬编码 | 维护困难，无法配置 | 2 小时 |
| P1 | H2 Dashboard 职责超载 | 不可测试，不可维护 | 4 小时 |
| P1 | H3 useAsync 设计缺陷 | stale closure，无法取消 | 2 小时 |
| P1 | H5/H6 Magic number / ResizeObserver | 跨浏览器兼容性风险 | 1 小时 |
| P2 | H4, M1-M9 | 性能、DRY、类型安全 | 各 30 分钟 |
| P3 | L1-L8, S1-S4 | 技术债务，架构优化 | 持续 |

---

*报告结束。建议首先修复所有 Critical 级别问题，再进行 High 级别的重构。*
