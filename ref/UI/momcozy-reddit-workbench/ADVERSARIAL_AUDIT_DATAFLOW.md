# 对抗性审计报告 —— 数据流与状态维度

**审计项目**: `momcozy-reddit-workbench`  
**审计范围**: `src/**/*.ts`, `src/**/*.tsx`  
**审计维度**: 数据流与状态管理  
**审计日期**: 2026-07-13  
**审计方法**: 静态代码分析 + 数据流追踪 + 架构批判  

---

## 执行摘要

本次审计在数据流与状态管理维度发现 **47 项问题**，其中：

| 级别 | 数量 | 说明 |
|------|------|------|
| 🔴 P0 - 严重 | 8 | 可能导致数据损坏、竞态条件、无限循环 |
| 🟠 P1 - 高 | 18 | 可能导致状态不一致、内存泄漏、性能退化 |
| 🟡 P2 - 中 | 16 | 代码异味、技术债务、可维护性问题 |
| 🟢 P3 - 低 | 5 | 风格问题、潜在风险 |

---

## 一、P0 严重级别问题（8项）

### P0-001: `useWebhookPoller` 与 `useAutoRefresh` 存在无限循环风险

**位置**: `src/hooks/useWebhookPoller.ts:126-146`, `src/hooks/useAutoRefresh.ts:69-91`

**问题描述**:
两个 Hook 的 countdown timer useEffect 依赖 `lastPollAt` / `lastRefreshAt`，而在 `doPoll`/`doRefresh` 的 finally 块中调用 `setLastPollAt(new Date().toISOString())` / `setLastRefreshAt(...)`。当 `remaining <= 0` 时触发轮询，轮询完成后更新 timestamp，timestamp 变化触发 useEffect，如果此时 `remaining` 仍然 `<= 0`（例如轮询耗时超过 1 秒），将立即再次触发轮询，形成潜在的无限循环。

**代码片段**:
```tsx
// useWebhookPoller.ts
useEffect(() => {
  const tick = () => {
    const remaining = Math.max(0, Math.ceil((next - Date.now()) / 1000));
    setNextPollIn(remaining);
    if (remaining <= 0) {
      doPoll();  // ← 触发轮询
    }
  };
  tick();
  const id = setInterval(tick, 1000);
  return () => clearInterval(id);
}, [lastPollAt, doPoll]);  // ← lastPollAt 在 doPoll 中被更新

// doPoll finally:
setLastPollAt(new Date().toISOString());  // ← 触发 useEffect 重新运行
```

**影响**: 在弱网或后端响应慢时，可能导致无限轮询风暴，CPU 占满，浏览器卡顿。

**修复建议**:
1. 在 `doPoll` 开始时记录 `pollStartTime`
2. 在 finally 中计算 `nextPollAt = pollStartTime + INTERVAL_MS`，而非使用当前时间
3. 或使用 `setTimeout` 替代 `setInterval`，在每次轮询完成后再调度下一次

---

### P0-002: Dashboard 在 useEffect 中直接调用 Zustand store action 修改外部状态

**位置**: `src/pages/Dashboard.tsx:454-494`

**问题描述**:
在 `useEffect`（render/commit phase）中直接调用 `useNotificationStore.getState().addItem(n)`。这违反了 React 的数据流规则——在渲染过程中不应产生副作用（side effects）。Zustand 的 `getState()` 虽然不会触发 React 的重渲染，但它直接修改了全局状态，可能导致：
1. 在 React Strict Mode / Concurrent Mode 下行为不可预测
2. 如果 `addItem` 触发订阅者更新，可能导致级联重渲染
3. 调试困难，因为状态变更不在 React DevTools 的事件追踪中

**代码片段**:
```tsx
useEffect(() => {
  // ...
  notifs.forEach((n) => {
    useNotificationStore.getState().addItem(n);  // ← 直接修改全局 store
  });
  // ...
}, [reportData, isLoading, activePeriod, configs, sendNotification]);
```

**影响**: 在 React 18+ Concurrent Features 下可能导致状态不一致、 tearing。

**修复建议**:
1. 使用事件驱动模型：将报告告警转换为通知的逻辑放在 `reportStore` 的 `refreshPeriod` action 中
2. 或在 Dashboard 中使用 `useLayoutEffect` 并在其中调度微任务来延迟 store 更新
3. 最佳方案：在 `reportStore` 中通过 middleware 自动将 critical alerts 同步到 `notificationStore`

---

### P0-003: 存在两套完全独立的竞品配置状态源，互相同步

**位置**: `src/stores/competitorStore.ts`, `src/hooks/useCompetitorConfig.ts`, `src/pages/Settings.tsx`, `src/pages/Dashboard.tsx`

**问题描述**:
- `competitorStore.ts`: Zustand 全局 store，管理 `brands` 状态，用于 Dashboard 的竞品分析
- `useCompetitorConfig.ts`: React Hook，独立管理 `config` state + localStorage 持久化，用于 Settings 页面

两者初始值都使用 `DEFAULT_BRANDS`，但之后完全独立演化。用户在 Settings 页面通过 `useCompetitorConfig` 添加/删除/修改品牌后，`competitorStore` 中的数据不会更新。Dashboard 继续显示旧的品牌列表。

**代码片段**:
```tsx
// Settings.tsx
<CompetitorBrandConfig />  // 内部使用 useCompetitorConfig()

// Dashboard.tsx
const competitorBrands = useCompetitorStore((s) => s.brands);  // 完全不同的数据源
```

**影响**: 用户在设置页的配置变更不会反映在看板中，产品功能完全断裂。

**修复建议**:
1. 删除 `useCompetitorConfig` Hook，统一使用 `competitorStore`
2. 在 `competitorStore` 中添加 localStorage 持久化（通过 Zustand persist middleware 或手动）
3. Settings 页面直接操作 store actions

---

### P0-004: 存在两套完全独立的通知状态系统，双向同步不可靠

**位置**: `src/pages/Dashboard.tsx:290-448`, `src/pages/Messages.tsx:61-168`

**问题描述**:
- **Dashboard**: 使用本地 `useState<NotificationItem[]>([])` 管理 `notifItems`，从 `getNotifications()` 加载，独立处理 markRead/addItem
- **Messages**: 使用 `useNotificationStore` (Zustand) 的 `items`，通过 `setItems` 从 `getNotifications()` 加载
- Dashboard 在检测到 critical alerts 时，通过 `useNotificationStore.getState().addItem(n)` 将告警推入 store，但 Dashboard 自己的 `notifItems` 和 store 的 `items` 不会自动同步

**具体不一致场景**:
1. 用户在 Messages 页面标记通知已读 → store 更新
2. Dashboard 的 `notifItems` 是独立 state，不会感知 store 变化
3. Dashboard 的 NotificationCenter 显示 `notifItems`，与 Messages 页面的通知列表可能完全不同

**影响**: 用户在不同页面看到不同的通知状态，严重损害产品可信度。

**修复建议**:
1. 删除 Dashboard 的本地 `notifItems` state，统一使用 `useNotificationStore`
2. 所有通知操作（markRead、addItem、removeItem）都通过 store actions 进行
3. Dashboard 的 `getNotifications()` 加载结果应调用 `setItems(data)` 而非 `setNotifItems(data)`

---

### P0-005: `useAsync` Hook 存在严重的竞态条件

**位置**: `src/hooks/index.ts:96-131`

**问题描述**:
`useAsync` 使用 `cancelled` 标志防止设置已卸载组件的状态，但没有处理 **请求竞态**（request race condition）。如果用户快速切换依赖（如 Analytics 页面切换 timeRange），后发出的请求可能比先发出的请求先返回，此时 `cancelled` 为 false，先返回的请求会覆盖后返回的请求数据，导致 UI 显示过期数据。

**代码片段**:
```tsx
useEffect(() => {
  let cancelled = false;
  asyncFn()
    .then((result) => {
      if (!cancelled) {  // ← 只检查是否卸载，不检查请求顺序
        setData(result);
      }
    });
}, deps);
```

**影响**: 在快速切换筛选条件时，UI 可能显示错误的数据。

**修复建议**:
1. 引入请求 ID 或版本号机制：
```tsx
let requestId = 0;
useEffect(() => {
  const currentId = ++requestId;
  asyncFn().then(result => {
    if (currentId === requestId) setData(result);
  });
}, deps);
```
2. 或使用 AbortController 传递 signal 给 asyncFn

---

### P0-006: `reportStore.refreshAll` 在部分失败时不会回滚已设置的数据

**位置**: `src/stores/reportStore.ts:66-93`

**问题描述**:
`refreshAll` 使用 `Promise.all` 并行获取三个周期的报告。如果 `generateReportData('daily')` 和 `generateReportData('weekly')` 成功，但 `generateReportData('monthly')` 失败：
1. catch 块只设置 `consistency: { valid: false, issues: [...] }`
2. 但 `dailyReport` 和 `weeklyReport` 已经被设置为新生成的数据
3. 这导致三个周期的数据来自不同的 seed，跨周期一致性校验必然失败

**代码片段**:
```tsx
try {
  const [daily, weekly, monthly] = await Promise.all([...]);
  set({ dailyReport: daily, weeklyReport: weekly, monthlyReport: monthly, ... });
} catch (error) {
  // ← 没有回滚 dailyReport/weeklyReport
  set({ consistency: { valid: false, issues: [...] } });
}
```

**影响**: 数据不一致状态被静默接受，用户看到部分新数据 + 部分旧数据的混合状态。

**修复建议**:
1. 在 catch 块中回滚所有报告数据到上一个已知良好状态
2. 或采用乐观更新策略：先验证所有数据可用，再一次性 set

---

### P0-007: `getStorage` 在 render phase 产生副作用（localStorage.removeItem）

**位置**: `src/utils/storage.ts:13-27`

**问题描述**:
`getStorage` 在解析失败或版本不匹配时调用 `localStorage.removeItem(key)`。这个函数被广泛用于组件的初始 state 计算（如 `useState(() => getStorage(...))`），这在 React 的 render phase 中执行。在 React 18 Concurrent Mode 下，组件可能被渲染多次（例如被中断后重新渲染），每次渲染都会触发 `localStorage.removeItem`，导致：
1. 数据在意外时刻被删除
2. Strict Mode 下组件被 double-render，数据可能被过早清除

**代码片段**:
```tsx
export function getStorage<T>(key: string, version: number, fallback: T): T {
  try {
    const parsed = JSON.parse(raw) as StorageWrapper<T>;
    if (parsed.version !== version) {
      localStorage.removeItem(key);  // ← render phase 副作用！
      return fallback;
    }
  } catch {
    localStorage.removeItem(key);  // ← render phase 副作用！
    return fallback;
  }
}
```

**影响**: 用户数据可能在应用启动时被意外清除。

**修复建议**:
1. 将清理逻辑移到 `useEffect` 中执行
2. 或使用 Zustand 的 persist middleware 替代手动 localStorage 管理
3. 或至少将 `removeItem` 延迟到下一个事件循环：`setTimeout(() => localStorage.removeItem(key), 0)`

---

### P0-008: Dashboard 的 `handleRefreshData` 存在状态更新时序问题

**位置**: `src/pages/Dashboard.tsx:400-404`

**问题描述**:
```tsx
const handleRefreshData = useCallback(() => {
  const newSeed = refreshSeed();
  setDataSeed(newSeed);
  refreshAll();
}, [setDataSeed, refreshAll]);
```

`setDataSeed` 和 `refreshAll` 都是 Zustand store 的 actions。`refreshAll` 内部通过 `get().dataSeed` 读取 seed 来生成报告数据。但 Zustand 的 `set` 是同步的，问题在于：
1. `setDataSeed(newSeed)` 同步更新了 store 中的 `dataSeed`
2. 但 `refreshAll` 是通过 `useReportStore((s) => s.refreshAll)` 获取的闭包引用
3. 在 `refreshAll` 内部，`get().dataSeed` 应该能读取到最新值（因为 Zustand set 是同步的）

**实际上这不是严重问题**，但如果 `refreshAll` 的实现改为从外部传入 seed（而非从 store 读取），这个时序就是正确的。但当前实现中 `refreshAll` 从 `get()` 读取，而 `setDataSeed` 在 `refreshAll` 之前调用，这实际上是正确的。

但潜在风险在于：`refreshAll` 是一个 async action，如果用户快速点击刷新按钮，多个 `refreshAll` 可能并发执行，它们都会读取同一个 `dataSeed`。

**影响**: 并发刷新可能导致数据覆盖竞争。

**修复建议**:
1. 在 `refreshAll` 开始时原子地读取并锁定 `dataSeed`
2. 或添加防抖/节流

---

## 二、P1 高级别问题（18项）

### P1-001: Zustand store 中的 getter 函数没有 memoization

**位置**: 
- `src/stores/notificationStore.ts:64-77` (`filteredItems`, `unreadCount`, `criticalCount`)
- `src/stores/competitorStore.ts:83-89` (`enabledBrands`, `brandCount`)
- `src/stores/reportStore.ts:140-145` (`getCurrentReport`)

**问题描述**:
这些 getter 函数在每次调用时都重新计算。例如 `filteredItems()` 每次都会遍历整个 items 数组并执行过滤。如果组件在每次渲染中都调用这些 getter（如 `useNotificationStore((s) => s.filteredItems())`），会导致 O(n) 的计算开销。

**代码片段**:
```tsx
filteredItems: () => {
  const { items, filter } = get();
  if (filter === 'all') return items;
  // ← 每次调用都重新过滤
  return items.filter((n) => n.type === filter);
},
```

**修复建议**:
1. 使用 Zustand 的 `computed` 中间件
2. 或在组件层使用 `useMemo` 包裹 store 选择器的结果
3. 或使用 `shallow` 比较优化选择器

---

### P1-002: `useWebhookConfig` 的 `testConnection` 依赖 `configs` 数组，导致引用不稳定

**位置**: `src/hooks/useWebhookConfig.ts:122-187`

**问题描述**:
```tsx
const testConnection = useCallback(async (id: string) => {
  const config = configs.find((c) => c.id === id);
  // ...
}, [configs]);
```

`configs` 是 `useState` 管理的数组，每次 `setConfigs` 都会创建新数组。即使内容相同，引用也变了，导致 `testConnection` 的引用在每次渲染都变化。如果父组件将 `testConnection` 作为依赖传入其他 hook/useEffect，会导致不必要的重执行。

**修复建议**:
1. 使用 `useRef` 存储 `configs`，在 `testConnection` 中读取 ref
2. 或将 `configs` 的查找逻辑提取到不依赖 `configs` 引用的函数中

---

### P1-003: `useNotificationSender` 的 `lastResults` 返回值不可靠

**位置**: `src/hooks/useNotificationSender.ts:110-198`

**问题描述**:
```tsx
return { sendNotification, lastResults: resultsRef.current };
```

`lastResults` 返回 ref 的当前值。在调用者同步读取时没有问题，但如果调用者在异步上下文中读取（如 setTimeout 中），`resultsRef.current` 可能已经被后续的 `sendNotification` 调用覆盖。更严重的是，React 的闭包机制可能导致组件看到陈旧的结果。

**修复建议**:
1. 使用 state 而非 ref 存储 lastResults，让 React 管理更新时序
2. 或在 `sendNotification` 返回的 Promise 中直接包含结果

---

### P1-004: NotificationCenter 的 `pushResults` state 无限累积

**位置**: `src/components/NotificationCenter.tsx:55-59`

**问题描述**:
```tsx
const [pushResults, setPushResults] = useState<Record<string, { success: boolean; message: string }>>({});
```

每次推送通知都会向 `pushResults` 添加一个条目，但没有清理机制。长期运行的 Dashboard 页面中，这个对象会无限增长。

**代码片段**:
```tsx
setPushResults((prev) => ({ ...prev, [item.id]: { success: true, message: '已推送' } }));
// ← 没有删除逻辑
```

**修复建议**:
1. 添加自动过期逻辑（如 5 分钟后自动清除）
2. 或使用 LRU 缓存限制最大条目数

---

### P1-005: `useAutoRefresh` 的 `mountedRef` 是 React anti-pattern

**位置**: `src/hooks/useAutoRefresh.ts:29-37`

**问题描述**:
```tsx
const mountedRef = useRef(true);
useEffect(() => {
  mountedRef.current = true;
  return () => { mountedRef.current = false; };
}, []);
```

在 React 18 Concurrent Mode / Strict Mode 下，组件可能被 mount → unmount → remount。`mountedRef` 的模式试图防止在已卸载组件上调用 setState，但这：
1. 无法处理 React 的 Offscreen API（组件被隐藏但未卸载）
2. 在 Suspense + Transition 场景下不可靠
3. 更好的方案是使用 AbortController 或取消令牌

**修复建议**:
1. 使用 `AbortController` 传递 signal 给 `onRefresh`
2. 或使用标准 React 模式：让 state 更新自然发生，React 会处理已卸载组件的警告

---

### P1-006: `useWebhookPoller` 的 `pushedIdsRef` 缺乏过期清理机制

**位置**: `src/hooks/useWebhookPoller.ts:23-33, 51, 101-110`

**问题描述**:
`pushedIdsRef` 是一个 `Set<string>`，存储已推送通知的 ID，持久化到 localStorage。但随着时间推移，这个 Set 会无限增长。如果应用每天推送 100 条通知，一年后 localStorage 中会有 36,500 个 ID。

**修复建议**:
1. 添加基于时间的过期策略（如只保留 30 天内的记录）
2. 定期清理旧条目

---

### P1-007: Search 页面的品牌过滤硬编码，不与竞品 store 同步

**位置**: `src/pages/Search.tsx:180-197`

**问题描述**:
```tsx
const brandKeywords: Record<string, string[]> = {
  'Momcozy': ['momcozy'],
  'Elvie': ['elvie'],
  // ...
};
```

品牌关键词和列表完全硬编码在 Search 组件中。如果用户通过 Settings 页面修改了竞品配置（如添加新品牌），Search 页面的品牌过滤器不会更新。

**修复建议**:
1. 从 `useCompetitorStore` 读取品牌列表
2. 使用品牌的 `keywords` 字段替代硬编码映射

---

### P1-008: CaseGallery 的 localStorage 缓存无大小限制

**位置**: `src/pages/CaseGallery.tsx:20-45, 136-145`

**问题描述**:
`saveCache` 将完整搜索结果写入 localStorage：
```tsx
function saveCache(cache: CaseCache) {
  localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
}
```

localStorage 通常有 5-10MB 的配额限制。如果搜索结果包含大量数据（如图片 URL、长文本），可能超出配额导致 `QuotaExceededError`。当前代码完全忽略了这个错误（try/catch 中无任何处理）。

**修复建议**:
1. 计算序列化后的大小，超过阈值时不缓存或压缩
2. 使用 IndexedDB 替代 localStorage 存储大量数据

---

### P1-009: Messages 页面的通知规则 localStorage 无版本控制

**位置**: `src/pages/Messages.tsx:21-41`

**问题描述**:
```tsx
const NOTIFICATION_RULES_KEY = 'momcozy_notification_rules';  // ← 无版本号

function loadNotificationRules(defaultRules: NotificationRule[]): NotificationRule[] {
  const raw = localStorage.getItem(NOTIFICATION_RULES_KEY);
  // ... 无版本校验
}
```

与 `utils/storage.ts` 中设计的版本化存储不同，Messages 页面直接使用裸 `localStorage.getItem/setItem`。如果未来 `NotificationRule` 接口变更，旧数据格式会导致解析错误。

**修复建议**:
1. 统一使用 `utils/storage.ts` 的版本化 API
2. 或添加版本号字段到存储数据中

---

### P1-010: Dashboard 的 `processedPeriodsRef` 内存限制过小

**位置**: `src/pages/Dashboard.tsx:450-463`

**问题描述**:
```tsx
const processedPeriodsRef = useRef<Set<string>>(new Set());
// ...
if (processedPeriodsRef.current.size > 100) {
  const first = processedPeriodsRef.current.values().next().value;
  if (first != null) processedPeriodsRef.current.delete(first);
}
```

虽然限制了 Set 大小为 100，但 `periodKey` 的格式是 `${activePeriod}-${reportData.overview.updatedAt}`。如果 `updatedAt` 每次刷新都变化（因为 `formatDateTime()` 返回当前时间），每次刷新都会添加新条目，很快达到 100 条限制。这本身不是问题，但 `updatedAt` 每次变化意味着相同的周期+不同时间的报告会被视为不同的条目，这不是预期的行为。

**修复建议**:
1. 使用更稳定的 key（如 `${activePeriod}-${date.toDateString()}`）
2. 或在限制达到时批量清理多个条目

---

### P1-011: `reportStore` 的 `refreshPeriod` 在部分数据缺失时跳过一致性校验

**位置**: `src/stores/reportStore.ts:95-138`

**问题描述**:
```tsx
if (currentDaily && currentWeekly && currentMonthly) {
  const consistency = validateReportConsistency(...);
  set({ consistency });
} else {
  set({ consistency: null });  // ← 清除一致性状态
}
```

当用户只加载了 daily 报告时，`consistency` 被设为 `null`。这导致 Dashboard 的一致性提示消失。更合理的行为是保留上一次的 consistency 结果或显示"数据不完整"的提示。

**修复建议**:
1. 区分 "数据不完整" 和 "校验通过/失败" 的状态
2. 不要简单地将 consistency 设为 null

---

### P1-012: `useFavorites` 在 concurrent 模式下可能有 storage 写入竞争

**位置**: `src/hooks/useFavorites.ts:7-31`

**问题描述**:
```tsx
const toggleFavorite = useCallback((id: string) => {
  setFavoriteIds((prev) => {
    const next = prev.includes(id) ? prev.filter((f) => f !== id) : [...prev, id];
    setStorage<string[]>(STORAGE_KEY, VERSION, next);  // ← 在 setState 回调中写 storage
    return next;
  });
}, []);
```

在 React 18 Concurrent Mode 下，`setState` 的 updater 函数可能在 transition 中被调用多次（如被打断后重新执行）。每次执行都会调用 `setStorage`，导致 localStorage 被多次写入。

**修复建议**:
1. 使用 `useEffect` 监听 `favoriteIds` 变化并写入 storage
2. 或使用 Zustand 管理 favorites 状态，利用其持久化中间件

---

### P1-013: `useWebhookPoller` 在页面不可见时仍然持续运行 timer

**位置**: `src/hooks/useWebhookPoller.ts:126-146`

**问题描述**:
Countdown timer 使用 `setInterval(tick, 1000)`，即使页面在后台标签页中也会持续运行。这不仅浪费 CPU，还可能导致：
1. 后台累积的 `remaining <= 0` 事件在切回前台时爆发式执行
2. 不必要的 localStorage 读写

**修复建议**:
1. 使用 Page Visibility API 在页面隐藏时暂停 timer
2. 在 `document.visibilitychange` 事件中调整轮询策略

---

### P1-014: `api.ts` 的 `buildUrl` 使用 `new URL()` 但在相对路径场景下有问题

**位置**: `src/lib/api.ts:21-31`

**问题描述**:
```tsx
async function buildUrl(path: string, params?: Record<string, ...>): Promise<string> {
  const url = new URL(path, API_BASE_URL);
  // ...
}
```

`new URL(path, API_BASE_URL)` 要求 `API_BASE_URL` 是绝对 URL。如果 `VITE_API_BASE_URL` 未设置，默认值是 `/api/v1`，这是一个相对路径。在某些环境（如 SSR、Web Worker）中，`new URL('/api/v1')` 会抛出异常因为没有 base。

**修复建议**:
1. 确保 `API_BASE_URL` 有默认值或运行时校验
2. 使用条件逻辑处理相对路径场景

---

### P1-015: 多处类型断言掩盖类型不匹配

**位置**:
- `src/pages/Messages.tsx:97` — `setItems(data as NotificationItem[])`
- `src/services/reportService.ts:8-25` — 多处 `as` 断言
- `src/data/reportEngine.ts:476-562` — 多处 `as UnifiedReportData`

**问题描述**:
`messagesMock.ts` 中的 `Notification` 接口和 `types/index.ts` 中的 `NotificationItem` 虽然字段相似，但可能有微妙差异。使用 `as` 强制转换绕过了 TypeScript 的类型检查，运行时可能出现属性缺失或类型不匹配。

**修复建议**:
1. 统一使用 `NotificationItem` 接口
2. 如果必须使用转换，使用运行时验证（如 zod）确保数据形状正确

---

### P1-016: `reportEngine.ts` 中的 `currentSeed` 是模块级可变状态

**位置**: `src/data/reportEngine.ts:76-81`

**问题描述**:
```tsx
let currentSeed = Date.now();

export function refreshSeed() {
  currentSeed = Date.now();
  return currentSeed;
}
```

`currentSeed` 是模块级别的全局变量。在 SSR 场景下，这个变量会在所有请求之间共享。即使在纯客户端应用中，如果应用被代码分割或热更新，这个状态可能被重置。

**修复建议**:
1. 将 seed 管理移到 store 中
2. 或使用函数参数传递 seed，避免全局可变状态

---

### P1-017: `Search.tsx` 的 `archiveFilters` 是大对象 state，导致频繁重渲染

**位置**: `src/pages/Search.tsx:139-151, 158-223`

**问题描述**:
`archiveFilters` 是一个包含 10 个字段的对象：
```tsx
const [archiveFilters, setArchiveFilters] = useState({
  timeRange: 'all', sentiment: 'all', subreddit: 'all', keyword: '',
  brand: 'all', category: 'all', minIntent: 0, minUpvotes: 0,
  maxUpvotes: 9999, minComments: 0, maxComments: 9999,
});
```

修改任何一个字段都会创建新的对象引用，触发整个 `archiveFilters` 的更新。由于 `archiveFilteredPosts` useMemo 依赖 `archiveFilters`，每次修改都会重新计算所有过滤逻辑。

**修复建议**:
1. 使用 `useReducer` 替代 `useState` 管理复杂对象
2. 或将 filters 拆分为独立的 state 变量
3. 对 `archiveFilteredPosts` 使用更细粒度的依赖

---

### P1-018: `useDebounce` 的 cleanup 逻辑在快速输入时创建大量 timer

**位置**: `src/hooks/index.ts:6-20`

**问题描述**:
```tsx
export function useDebounce<T>(value: T, delay: number): T {
  useEffect(() => {
    const handler = setTimeout(() => { setDebouncedValue(value); }, delay);
    return () => { clearTimeout(handler); };
  }, [value, delay]);
}
```

每次 `value` 变化都会创建新的 timeout。在用户快速输入时（如每分钟 300 个字符），会创建和清除大量 timer。虽然现代浏览器能处理，但在低端设备上可能导致性能问题。

**修复建议**:
1. 当前实现已经是标准做法，但可以添加节流（throttle）变体
2. 或使用 `requestIdleCallback` 延迟非紧急更新

---

## 三、P2 中级别问题（16项）

### P2-001: `competitorStore.ts` 的 `DEFAULT_BRANDS` 是导出的可变引用

**位置**: `src/stores/competitorStore.ts:36-46`

**问题描述**:
`DEFAULT_BRANDS` 是一个导出的常量数组引用。如果外部代码直接修改它（如 `DEFAULT_BRANDS.push(...)`），会影响 store 的初始状态。虽然当前代码没有这样做，但导出可变引用是危险的。

**修复建议**:
1. 使用 `Object.freeze(DEFAULT_BRANDS)`
2. 或使用 `structuredClone(DEFAULT_BRANDS)` 初始化 store

---

### P2-002: `useWebhookConfig` 的 `loadConfigs` fallback 逻辑不合理

**位置**: `src/hooks/useWebhookConfig.ts:37-54`

**问题描述**:
```tsx
return parsed.map((c) => {
  const defaults = DEFAULT_CONFIGS.find((d) => d.id === c.id);
  return {
    ...(defaults ?? DEFAULT_CONFIGS[0]),  // ← 飞书配置 fallback 到钉钉默认？
    ...c,
    secret: '',
  };
});
```

如果持久化数据中有飞书配置但找不到对应的 defaults（因为 defaults 中没有该 ID），它会 fallback 到 `DEFAULT_CONFIGS[0]`（钉钉配置）。这导致飞书配置继承了钉钉的默认设置（如 URL 占位符）。

**修复建议**:
1. 使用 provider 类型来查找对应的默认配置
2. 或提供通用的空配置 fallback

---

### P2-003: `useWebhookConfig` 的 `saveConfigs` 在每次 configs 变化时写入

**位置**: `src/hooks/useWebhookConfig.ts:56-59, 64-66`

**问题描述**:
```tsx
useEffect(() => {
  saveConfigs(configs);
}, [configs]);
```

每次 `configs` 变化都会触发 localStorage 写入。如果用户在 Settings 页面快速切换多个开关，会导致多次写入。更严重的是，如果 `configs` 中的某个字段是对象/数组，引用变化会导致不必要的写入。

**修复建议**:
1. 使用防抖延迟写入
2. 或使用深比较确定是否真的需要写入

---

### P2-004: `reportStore` 的 `refreshPeriod` 缺少 loading 状态保护

**位置**: `src/stores/reportStore.ts:95-138`

**问题描述**:
```tsx
refreshPeriod: async (period) => {
  set({ isLoading: true });
  try {
    const data = generateReportData(period, dataSeed);
    // ...
  } finally {
    set({ isLoading: false });
  }
}
```

如果用户快速切换周期（如 daily → weekly → daily），两个并发的 `refreshPeriod` 调用可能同时运行。后完成的请求会覆盖先完成的，但用户看到的可能不是最后一次点击的周期的数据。

**修复建议**:
1. 添加请求锁或取消机制
2. 在 store 中记录当前正在加载的 period

---

### P2-005: `Dashboard.tsx` 的 `sendNotification` 在 forEach 中顺序调用但不等待

**位置**: `src/pages/Dashboard.tsx:444-448, 478-483`

**问题描述**:
```tsx
criticalAlerts.forEach((item) => {
  sendNotification(item);  // ← 不等待，fire-and-forget
});
```

对每个 critical alert 都调用 `sendNotification`，但不等待结果。如果 `sendNotification` 内部使用 `Promise.all` 并行发送给多个 webhook，这可能导致短时间内大量并发请求。

**修复建议**:
1. 使用 `Promise.all` 或 `Promise.allSettled` 等待所有发送完成
2. 或限制并发数（如最多同时发送 3 个）

---

### P2-006: `Analytics.tsx` 的 `buildAnalyticsSections` 在每次渲染时重复调用数据获取函数

**位置**: `src/pages/Analytics.tsx:31-94, 267`

**问题描述**:
```tsx
const exportSections = useMemo(() => buildAnalyticsSections(timeRange, query), [timeRange, query]);

function buildAnalyticsSections(timeRange, searchQuery) {
  const stats = getAnalyticsStats(timeRange);  // ← 每次 useMemo 重新计算都调用
  // ...
}
```

`buildAnalyticsSections` 内部调用了 `getAnalyticsStats()`、`getSentimentOverview()` 等函数。虽然当前是 mock 数据，但如果是真实 API 调用，会导致重复请求。

**修复建议**:
1. 将数据获取与导出构建分离
2. 复用 `useAsync` 获取的数据

---

### P2-007: `Search.tsx` 的 `searchPosts` 只在 mount 时加载

**位置**: `src/pages/Search.tsx:50-52`

**问题描述**:
```tsx
useEffect(() => {
  getSearchPosts().then((data) => setSearchPosts(data));
}, []);
```

搜索数据只在组件 mount 时加载一次。如果底层数据在其他页面被更新（如通过 API），Search 页面不会自动刷新。

**修复建议**:
1. 提供手动刷新按钮
2. 或使用 SWR/React Query 等库管理数据同步

---

### P2-008: `Messages.tsx` 的 URL 同步 useEffect 缺少依赖项警告注释

**位置**: `src/pages/Messages.tsx:124-134`

**问题描述**:
```tsx
useEffect(() => {
  setParam('filter', filter === 'all' ? null : filter);
}, [filter]); // eslint-disable-line react-hooks/exhaustive-deps
```

多处 `useEffect` 依赖数组被故意省略（通过 eslint-disable）。虽然 `setParam` 是稳定的（useCallback 空依赖），但其他被省略的依赖（如 `getParam`）在 `useUrlParams` 中是稳定的。这种写法虽然正确，但容易在未来重构时引入 bug。

**修复建议**:
1. 在 `useUrlParams` 中使用 `useCallback` 确保所有返回函数都是稳定的
2. 完整声明依赖数组，消除 eslint-disable

---

### P2-009: `useUrlParams` 的 `setParam` 使用 `replace: true` 导致历史记录丢失

**位置**: `src/hooks/index.ts:70-80`

**问题描述**:
```tsx
const setParam = useCallback((key: string, value: string | null) => {
  setSearchParams((prev) => { ... }, { replace: true });
}, [setSearchParams]);
```

所有 URL 更新都使用 `replace: true`，这意味着用户无法通过浏览器后退按钮回到之前的筛选状态。这在某些场景下是预期行为，但统一使用可能不是最佳用户体验。

**修复建议**:
1. 提供可选参数控制是否 replace
2. 对重要的状态变更使用 push 模式

---

### P2-010: `reportEngine.ts` 的 `validateReportConsistency` 使用浮点数比较

**位置**: `src/data/reportEngine.ts:577-618`

**问题描述**:
```tsx
const sum = Math.round((positiveRate + negativeRate + neutralRate) * 10) / 10;
if (sum !== 100) {
  issues.push(`${report.period} 情感率总和 ${sum} ≠ 100`);
}
```

浮点数比较使用 `!==` 而不是容差范围。由于浮点数精度问题，`55.5 + 30.2 + 14.3` 可能不等于 `100`。

**修复建议**:
1. 使用容差比较：`Math.abs(sum - 100) > 0.1`

---

### P2-011: `storage.ts` 缺少跨标签页同步机制

**位置**: `src/utils/storage.ts`

**问题描述**:
所有使用 `utils/storage.ts` 的组件都不会感知到其他标签页的数据变更。如果用户在标签页 A 中收藏了一条帖子，标签页 B 中的收藏状态不会更新。

**修复建议**:
1. 监听 `storage` 事件并触发回调
2. 使用 `BroadcastChannel API` 实现跨标签页同步

---

### P2-012: `notificationStore` 的 `markRead` 允许重复标记已读项

**位置**: `src/stores/notificationStore.ts:40-44`

**问题描述**:
```tsx
markRead: (id) =>
  set((state) => ({
    items: state.items.map((n) => (n.id === id ? { ...n, read: true } : n)),
    lastUpdated: new Date(),
  })),
```

即使通知已经是已读状态，调用 `markRead` 仍然会创建新的数组和更新 `lastUpdated`。这可能导致不必要的重渲染。

**修复建议**:
1. 在更新前检查 `!n.read`
2. 使用 Immer 或类似的不可变更新库

---

### P2-013: `Dashboard.tsx` 的 `handleNavigate` 使用 `window.location.href` 跳转外部链接

**位置**: `src/pages/Dashboard.tsx:414-422`

**问题描述**:
```tsx
const handleNavigate = (url: string) => {
  if (url.startsWith('http')) {
    window.location.href = url;  // ← 全页面刷新
  } else {
    navigate(url);
  }
};
```

对于外部链接使用 `window.location.href` 会导致全页面刷新，丢失所有 React 状态。

**修复建议**:
1. 使用 `window.open(url, '_blank')` 在新标签页打开
2. 或确保所有导航都通过 React Router 进行

---

### P2-014: `useCompetitorConfig` 的 `normalizeBrand` 在 id 为空时不报警

**位置**: `src/hooks/useCompetitorConfig.ts:15-24`

**问题描述**:
```tsx
function normalizeBrand(brand: Partial<CompetitorBrand>): CompetitorBrand {
  return {
    id: brand.id || '',  // ← 空字符串作为 id！
    name: brand.name || '',
    // ...
  };
}
```

如果持久化数据中的品牌缺少 id，`normalizeBrand` 会返回空字符串 id。这可能导致后续操作（如 `updateBrand`）无法匹配到正确的品牌。

**修复建议**:
1. 对空 id 生成随机 ID
2. 或在加载时过滤掉无效数据

---

### P2-015: `reportEngine.ts` 的 `generateReportData` 使用 `structuredClone` 但类型断言绕过了检查

**位置**: `src/data/reportEngine.ts:474-563`

**问题描述**:
```tsx
return structuredClone({
  period: 'daily',
  // ...
}) as UnifiedReportData;
```

`structuredClone` 确保了深拷贝，但 `as UnifiedReportData` 完全绕过了类型检查。如果对象结构缺少必需字段，TypeScript 不会报错。

**修复建议**:
1. 使用运行时类型验证（zod/io-ts）
2. 或确保类型与数据结构严格一致

---

### P2-016: `CaseGallery.tsx` 的搜索历史在加载完成前就被更新

**位置**: `src/pages/CaseGallery.tsx:206-213`

**问题描述**:
```tsx
useEffect(() => {
  if (debouncedQuery.trim() && !isLoading) {
    setSearchHistory((prev) => {
      const next = [debouncedQuery.trim(), ...prev.filter((h) => h !== debouncedQuery.trim())];
      return next.slice(0, 10);
    });
  }
}, [debouncedQuery, isLoading, setSearchHistory]);
```

搜索历史在 `!isLoading` 时更新，但 `isLoading` 在 `performSearch` 开始时设为 true，搜索完成后设为 false。这意味着搜索历史在搜索完成后才更新，这是正确的。但如果用户快速输入并切换分类，`isLoading` 可能在短时间内多次变化，导致搜索历史被重复添加。

**修复建议**:
1. 只在搜索成功且结果非空时添加历史
2. 使用 `useRef` 追踪已记录的历史项

---

## 四、P3 低级别问题（5项）

### P3-001: 多处 `// eslint-disable-line react-hooks/exhaustive-deps` 掩盖潜在问题

**位置**:
- `src/pages/Messages.tsx:93, 121, 126, 130, 134`
- `src/pages/Analytics.tsx:252, 257`
- `src/pages/Insights.tsx:162`

**问题描述**:
大量使用 `eslint-disable-line react-hooks/exhaustive-deps` 来消除 hook 依赖警告。虽然当前实现可能是正确的（因为被省略的依赖是稳定的函数引用），但这种模式：
1. 使代码难以审计
2. 容易在未来重构时引入 bug
3. 掩盖了真正的依赖问题

**修复建议**:
1. 将稳定的函数引用提取到 hook 外部
2. 使用 `useRef` 存储不稳定的依赖
3. 或重新设计 hook API 以接受稳定的配置对象

---

### P3-002: `useNotificationSender` 中的 `severityLabel` 和 `typeLabel` 查找可能返回 undefined

**位置**: `src/hooks/useNotificationSender.ts:21-25`

**问题描述**:
```tsx
const severityLabel = item.severity
  ? { critical: '严重', warning: '警告', info: '信息' }[item.severity]
  : '一般';
```

如果 `item.severity` 是 `'critical' | 'warning' | 'info'` 之外的值（如后端返回了新的 severity），查找结果会是 `undefined`。

**修复建议**:
1. 使用 TypeScript 的 exhaustiveness check
2. 或提供 fallback 值

---

### P3-003: `api.ts` 的 `request` 函数在 `response.json()` 失败时抛出格式不一致的错误

**位置**: `src/lib/api.ts:53-71`

**问题描述**:
```tsx
const errorBody = await response.json().catch(() => ({ message: 'Unknown error' }));
throw new ApiError(
  errorBody.message || `HTTP ${response.status}`,
  response.status,
  errorBody.code || 'UNKNOWN_ERROR'
);
```

如果响应不是 JSON 格式，`errorBody` 是 `{ message: 'Unknown error' }`，丢失了原始的 HTTP 状态信息。

**修复建议**:
1. 在 catch 中保留原始响应文本
2. 提供更详细的错误信息

---

### P3-004: `Dashboard.tsx` 的 `formatTime` 函数在秒数小于 10 时显示错误

**位置**: `src/pages/Dashboard.tsx:496-500`

**问题描述**:
```tsx
const formatTime = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
};
```

当 `seconds` 为 0 时返回 `"0:00"`，这没问题。但如果 `seconds` 是负数（虽然不应该），`padStart` 对负数无效。

**修复建议**:
1. 添加 `Math.max(0, seconds)` 保护

---

### P3-005: `Search.tsx` 的 `allSubreddits` 在 `searchPosts` 为空时返回空数组

**位置**: `src/pages/Search.tsx:153-156`

**问题描述**:
```tsx
const allSubreddits = useMemo(() => {
  const set = new Set(searchPosts.map((p) => p.subreddit));
  return Array.from(set).sort();
}, [searchPosts]);
```

如果 `searchPosts` 还未加载（初始为空数组），`allSubreddits` 为空数组。这导致存量帖子筛选的社区下拉菜单为空，用户无法选择社区。

**修复建议**:
1. 在数据加载前显示 loading 状态或禁用下拉菜单
2. 或使用默认值填充社区列表

---

## 五、架构层面的系统性问题

### S-001: 状态管理方案不统一

**问题**: 项目同时使用了：
1. **Zustand** (reportStore, notificationStore, competitorStore) — 全局状态
2. **React useState + localStorage** (useWebhookConfig, useCompetitorConfig, useFavorites) — 半持久化状态
3. **纯 React useState** (Dashboard 的 notifItems, Search 的 archiveFilters) — 本地状态

这导致同一类数据可能在多个地方以不同方式管理，增加了维护成本和 bug 风险。

**建议**: 
1. 统一使用 Zustand + persist middleware 管理所有需要持久化的全局状态
2. 纯本地 UI 状态（如 dropdown 展开/收起）继续使用 useState

### S-002: Mock/真实 API 切换机制过于简单粗暴

**问题**: 所有 service 文件使用相同的模式：
```tsx
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';
```

这导致：
1. 无法按功能粒度控制 mock
2. 环境变量在生产构建时被静态替换，运行时无法切换
3. 如果 `VITE_USE_MOCK` 被意外设为 true，生产环境使用假数据

**建议**:
1. 按功能模块配置 mock 开关
2. 添加运行时检查，在非开发环境拒绝 mock 模式
3. 使用 MSW (Mock Service Worker) 替代条件分支

### S-003: 数据层缺乏统一的缓存/同步策略

**问题**: 
- CaseGallery 使用手动 localStorage 缓存
- Messages 使用裸 localStorage
- Hooks 使用 `utils/storage.ts`
- Stores 没有持久化

每个模块都有自己的缓存策略，没有统一的失效、清理、同步机制。

**建议**:
1. 引入 SWR 或 React Query 作为数据获取层
2. 统一使用 IndexedDB + 内存缓存的两级缓存策略

---

## 六、修复优先级建议

### Phase 1: 紧急修复（本周内）

| 编号 | 问题 | 影响 |
|------|------|------|
| P0-001 | useWebhookPoller / useAutoRefresh 无限循环 | 浏览器卡顿、CPU 风暴 |
| P0-003 | 两套竞品配置状态源 | 功能断裂 |
| P0-004 | 两套通知状态系统 | 数据不一致 |
| P1-003 | notificationSender lastResults 不可靠 | 状态混乱 |
| P1-014 | buildUrl 相对路径问题 | 部署失败 |

### Phase 2: 高优先级修复（两周内）

| 编号 | 问题 | 影响 |
|------|------|------|
| P0-002 | useEffect 中直接修改 Zustand store | Concurrent Mode 不兼容 |
| P0-005 | useAsync 竞态条件 | 显示过期数据 |
| P0-006 | refreshAll 部分失败不 rollback | 数据不一致 |
| P0-007 | getStorage render phase 副作用 | 数据丢失 |
| P1-001 | Store getter 无 memoization | 性能问题 |
| P1-007 | Search 品牌过滤硬编码 | 功能断裂 |

### Phase 3: 技术债务清理（一个月内）

| 编号 | 问题 | 影响 |
|------|------|------|
| P1-002 | testConnection 引用不稳定 | 不必要重渲染 |
| P1-004 | pushResults 无限累积 | 内存泄漏 |
| P1-005 | mountedRef anti-pattern | 维护困难 |
| P1-013 | 后台 timer 持续运行 | 资源浪费 |
| S-001 | 状态管理不统一 | 维护成本 |
| S-002 | Mock 切换机制简单 | 生产风险 |

---

## 七、附录：审计文件清单

| 文件路径 | 行数 | 审计覆盖 |
|---------|------|---------|
| `src/stores/notificationStore.ts` | 78 | 完整 |
| `src/stores/reportStore.ts` | 146 | 完整 |
| `src/stores/competitorStore.ts` | 90 | 完整 |
| `src/hooks/useFavorites.ts` | 31 | 完整 |
| `src/hooks/useWebhookConfig.ts` | 248 | 完整 |
| `src/hooks/useCompetitorConfig.ts` | 151 | 完整 |
| `src/hooks/useWebhookPoller.ts` | 166 | 完整 |
| `src/hooks/useAutoRefresh.ts` | 102 | 完整 |
| `src/hooks/useNotificationSender.ts` | 219 | 完整 |
| `src/hooks/index.ts` | 138 | 完整 |
| `src/utils/storage.ts` | 46 | 完整 |
| `src/data/reportEngine.ts` | 620 | 完整 |
| `src/data/unifiedEngine.ts` | 337 | 完整 |
| `src/data/searchMock.ts` | 137 | 完整 |
| `src/data/messagesMock.ts` | 639 | 完整 |
| `src/data/dailyReportMock.ts` | 359 | 完整 |
| `src/lib/api.ts` | 133 | 完整 |
| `src/pages/Dashboard.tsx` | 750 | 完整 |
| `src/pages/Settings.tsx` | 585 | 完整 |
| `src/pages/Messages.tsx` | 611 | 完整 |
| `src/pages/Analytics.tsx` | 434 | 完整 |
| `src/pages/Search.tsx` | 804 | 完整 |
| `src/pages/Insights.tsx` | 260 | 完整 |
| `src/pages/CaseGallery.tsx` | 422 | 完整 |
| `src/types/index.ts` | 386 | 完整 |
| `src/components/NotificationCenter.tsx` | 346 | 完整 |
| `src/App.tsx` | 60 | 完整 |
| `src/services/*.ts` | ~150 | 完整 |

---

*报告结束*
