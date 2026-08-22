# Momcozy & Reddit 舆情工作台 — 交互审计报告

**审计日期**: 2026-07-12  
**审计范围**: 全站 React + TypeScript + Tailwind 组件、页面、数据层、配置层  
**审计人**: AI Code CLI  

---

## 1. 问题总览

| 类别 | 问题数 | 严重程度 |
|------|--------|----------|
| 虚荣指标与空洞数据 | 12 | 🔴 Critical |
| 模板化页面结构 | 8 | 🔴 Critical |
| 假交互/无功能按钮 | 14 | 🔴 Critical |
| 设计系统混乱 | 6 | 🟠 High |
| 过度视觉堆砌 | 10 | 🟠 High |
| AI 文案模板化 | 7 | 🟡 Medium |
| Mock 数据不真实 | 5 | 🟡 Medium |
| 图表滥用 | 4 | 🟡 Medium |
| 代码重复与耦合 | 6 | 🟡 Medium |
| 可访问性缺失 | 3 | 🟢 Low |

---

## 2. 问题详情（按文件精确标注）

### 2.1 虚荣指标与空洞数据（🔴 Critical）

#### P1: 首页 Hero 区展示完全无来源的虚假数据
- **文件**: `src/components/HeroSection.tsx`
- **行号**: 31-44
- **问题**: "50+ subreddit""10K+ 高意向帖子""98% 准确率" 三个数字没有任何数据来源、没有更新机制、没有说明口径。这是典型的 AI 生成的"看起来专业的数字"。
- **改进**: 要么对接真实数据，要么改为非数字化的价值陈述（如"覆盖核心母婴社区"）。

#### P2: Trust Bar 的品牌名称是竞品而非合作方
- **文件**: `src/pages/Home.tsx`
- **行号**: 76-83
- **问题**: 声称"被 500+ 品牌信赖"，但列出的 Medela、Lansinoh、Spectra、Haakaa、Elvie 全部是 Momcozy 的竞品。这是一个严重的品牌逻辑错误。
- **改进**: 删除此条，或替换为真实的客户/合作品牌。

#### P3: "500+ 品牌" 文案在全站重复出现，无依据
- **文件**: `src/pages/Home.tsx:74`, `src/pages/Home.tsx:170`, `src/pages/Features.tsx:202`
- **问题**: 三个 CTA 区域都写了"加入 500+ 品牌"，这是一个凭空捏造的数字。
- **改进**: 删除具体数字，改为"已有品牌团队在使用"。

#### P4: 数据看板所有"更新于 10 分钟前"是静态文案
- **文件**: `src/pages/Dashboard.tsx:342`, `src/pages/Analytics.tsx:222`, `src/pages/UGCShowcase.tsx:306`, `src/pages/Messages.tsx:196`, `src/pages/Insights.tsx:600`
- **问题**: 全站 5 处"数据更新于 10 分钟前"都是硬编码字符串，不会随时间变化，也不反映真实数据状态。
- **改进**: 接入真实数据时间戳，或删除此信息。

#### P5: 品牌评分仪表盘数据纯属编造的"好看数字"
- **文件**: `src/components/BrandScoreCard.tsx`
- **行号**: 27-34
- **问题**: 默认数据 `score: 78, 82, 65, 71, 58, 85` 是人为挑选的"看起来有波动但总体良好"的数字，没有计算逻辑。
- **改进**: 提供真实的评分算法，或删除此组件。

#### P6: 转化率漏斗数据凭空捏造
- **文件**: `src/data/analyticsMock.ts`
- **行号**: 477-482
- **问题**: 品牌曝光→点击浏览→互动参与→购买意向→实际转化 这五层数据（12500→6800→3200→980→245）没有任何业务模型支撑，只是按约 50% 递减的"整齐数字"。
- **改进**: 基于真实业务数据建模，或删除此图表。

---

### 2.2 模板化页面结构（🔴 Critical）

#### P7: 5 个 Dashboard 内页结构完全复制粘贴
- **文件**: `src/pages/Dashboard.tsx`, `src/pages/Search.tsx`, `src/pages/Analytics.tsx`, `src/pages/Insights.tsx`, `src/pages/UGCShowcase.tsx`, `src/pages/Messages.tsx`, `src/pages/Settings.tsx`
- **问题**: 所有页面遵循完全相同的模板：
  ```
  <div class="flex min-h-screen">
    <Sidebar />
    <main>
      <header class="sticky top-0 z-40 bg-white/80 backdrop-blur-xl...">
        <div class="flex items-center justify-between px-6 py-3.5">
          <div class="relative w-72"><input placeholder="搜索..." /></div>
          <div class="flex items-center gap-3">
            <button class="relative w-9 h-9 rounded-icon..."><Bell /></button>
            <div class="w-9 h-9 rounded-full bg-primary-light"><span>M</span></div>
          </div>
        </div>
      </header>
      <div class="p-6 space-y-6">
        <PageHeader icon={...} title={...} subtitle={...} />
        ...
      </div>
    </main>
  </div>
  ```
  这种从 AI 代码生成器常见的"看起来规范"实则懒惰的结构，导致用户无法通过页面布局快速识别自己所在的功能模块。
- **改进**: 提取公共布局组件（如 `DashboardLayout`），但不同功能模块应拥有差异化的首屏信息架构。

#### P8: 顶部搜索栏在所有页面均无实际功能
- **文件**: `src/pages/Dashboard.tsx:283-292`, `src/pages/Analytics.tsx:166-175`, `src/pages/Insights.tsx:562-572`, `src/pages/Search.tsx:103-114`, `src/pages/UGCShowcase.tsx:246-255`, `src/pages/Messages.tsx:151-163`
- **问题**: 搜索框的 `value` 与 `onChange` 只是本地 state，没有连接任何搜索逻辑或后端 API。在 Search 页面本身也有这个搜索框，但真正的搜索逻辑却在 `SearchPanel` 组件里——这是反直觉的重复。
- **改进**: 统一搜索入口，删除顶部伪搜索栏，或在搜索页面中让顶部搜索框真正驱动结果。

---

### 2.3 假交互/无功能按钮（🔴 Critical）

#### P9: 回复帖子按钮完全无功能
- **文件**: `src/components/PostDetailDrawer.tsx`
- **行号**: 273-276
- **问题**: `<button className="btn-primary flex-1">回复帖子</button>` 没有任何 onClick 处理，点击无反应。这是核心功能（AI 回复）的入口。
- **改进**: 接入真实的回复流程，或暂时显示"即将上线"的不可用状态。

#### P10: 分享链接按钮无功能
- **文件**: `src/components/PostDetailDrawer.tsx:277-280`
- **问题**: 同上，按钮无功能。

#### P11: "查看详情"按钮在全站 10+ 处无功能
- **文件**: `src/pages/Analytics.tsx:257`, `src/pages/Analytics.tsx:277`, `src/pages/Insights.tsx:多个 SectionCard`
- **问题**: `action={{ label: '查看详情' }}` 作为一个流行的 AI 生成模式，在所有 SectionCard 中被放置，但绝大多数没有 `onClick`。
- **改进**: 删除无功能的 action，或添加真实跳转。

#### P12: "查看全部"按钮在 UGC 素材库无功能
- **文件**: `src/pages/UGCShowcase.tsx:407`
- **问题**: `action={{ label: '查看全部', onClick: () => {} }}` 是空函数。

#### P13: 导出按钮在 Dashboard 中引用的数据是局部 mock
- **文件**: `src/pages/Dashboard.tsx:323-339`
- **问题**: ExportButton 的 `data` prop 硬编码了 `reportData.newPosts.map(...)` 的字段映射，但如果切换 daily/weekly/monthly tab，导出的数据格式不会变化，这是不真实的。
- **改进**: 根据当前 tab 导出对应报告的数据结构。

#### P14: 素材库筛选标签点击无响应
- **文件**: `src/pages/UGCShowcase.tsx:403-408`
- **问题**: 分类筛选、媒体类型筛选、情感筛选均依赖本地 state，但结果列表只是对 mock 数据做前端过滤，没有真实后端交互。

#### P15: Insights 页面所有 Tab 内容切换只是 500ms 假加载
- **文件**: `src/pages/Insights.tsx:549-552`
- **问题**: `useAsync` 里 `await new Promise((resolve) => setTimeout(resolve, 500));` 是唯一逻辑，纯粹是为了"有加载动画"而延迟。这是 AI 生成代码的典型痕迹——制造无意义的延迟来模拟异步。
- **改进**: 删除假加载，真实数据切换应瞬间完成。

#### P16: 设置页「通知渠道」开关只是本地 state，无持久化
- **文件**: `src/pages/Settings.tsx:48-52`
- **问题**: 三个开关的状态只保存在组件 state 中，刷新页面即丢失，也没有调用任何 API。
- **改进**: 接入用户配置 API，或至少使用 localStorage。

#### P17: Webhook 配置的 Secret 说明自相矛盾
- **文件**: `src/pages/Settings.tsx:385-388`
- **问题**: 提示文字说"不会上传到服务器或持久化到本地存储"，但 `useWebhookConfig` hook 实际上使用了 localStorage 持久化。这是文案与代码逻辑不一致。

#### P18: 案例广场「自动检索」功能只是 400ms 的 setTimeout
- **文件**: `src/pages/CaseGallery.tsx:122-154`
- **问题**: `fetchCases` 函数本质上是一个 `setTimeout(() => resolve(mockData), 400)` 的包装，加上 AbortController 的复杂仪式感。

#### P19: 消息中心「推送至机器人」没有真实的 Webhook 调用
- **文件**: `src/components/NotificationCenter.tsx:290-310`
- **问题**: 虽然表面上实现了 `onPushWebhook` 回调，但按钮本身在演示环境中没有实际目的地。

#### P20: 消息中心通知规则开关没有后端同步
- **文件**: `src/pages/Messages.tsx:448-462`
- **问题**: `toggleRule` 只更新本地 state，没有 API 调用。

#### P21: 自动刷新机制是前端 setInterval 轮询本地数据
- **文件**: `src/hooks/useAutoRefresh.ts`, `src/pages/CaseGallery.tsx:162-175`
- **问题**: 所谓的"自动检索"只是每隔 N 分钟重新调用一次 mock 数据生成器。

#### P22: 发送 Webhook 通知在 Dashboard 自动触发，但无真实接收方
- **文件**: `src/pages/Dashboard.tsx:254-266`
- **问题**: 在 `useEffect` 中自动调用 `sendNotification` 推送关键告警，但 Webhook 如果没有配置，这个逻辑会在控制台报错，且用户无从知晓。

---

### 2.4 设计系统混乱（🟠 High）

#### P23: 设计令牌在三个地方重复定义，互相冲突
- **文件1**: `src/design-tokens.ts` — 完整的手写 Token 对象
- **文件2**: `tailwind.config.js` — 几乎完全相同的 colors / fontSize / borderRadius 定义
- **文件3**: `src/index.css` — 再次用 CSS 变量定义了 `:root { --primary: #F8A67B ... }`
- **问题**: 这是 AI 生成代码的典型特征——"看起来做了设计系统"，但实际上每个地方都重新写了一遍。例如 `fontSize` 在 tailwind 里定义了 `text-display`（40px），在 CSS 里根本不存在这个 token，在 design-tokens.ts 里 `display` 的 size 是 `40px` 但 key 名不同。
- **改进**: 保留 tailwind.config.js 作为单一数据源，删除 `design-tokens.ts`（目前没有任何文件 import 它），删除 CSS 变量中的重复定义。

#### P24: 颜色硬编码在 20+ 处直接写死
- **文件**: `src/components/charts/WordCloudChart.tsx:98`, `src/components/charts/SankeyChart.tsx:391`, `src/data/analyticsMock.ts:390-405`, `src/data/insightsMock.ts:342-353`, `src/data/insightsMock.ts:424-428`
- **问题**: 虽然有了 `CHART_PALETTE` 和 `BRAND_COLORS`，但词云、桑基图、insightsMock 里到处是直接写死的 `#4CAF50`、`#FF9800`、`#2196F3` 等 Material Design 风格颜色，与品牌调性（暖珊瑚、金色）完全不搭。
- **改进**: 统一使用 `constants/colors.ts` 中定义的颜色。

#### P25: 「glass」类名在 Tailwind 中未定义但被使用
- **文件**: `src/pages/Insights.tsx:560`
- **问题**: `className="glass border-b..."` 中的 `glass` 在 tailwind.config.js 中没有定义，会静默失效。这是复制粘贴后忘记清理的痕迹。
- **改进**: 删除 `glass` 或替换为 `bg-white/80 backdrop-blur-xl`。

#### P26: 同时使用了 Tailwind 的 `space-y-6` 和自定义的 `.card` 的 `p-6` 的 spacing 逻辑，导致内边距计算混乱
- **文件**: 所有页面
- **问题**: 卡片的间距有时用 `space-y-6`（父容器），有时用 `gap-6`（grid），有时用 `mb-6`（子元素），没有统一规则。这导致同一页面内不同区域的间距不一致。
- **改进**: 统一使用 `gap`（flex/grid）或 `space-y`（单一方向），禁止混用。

#### P27: 部分组件同时用 CSS 变量和 Tailwind 的 arbitrary value
- **文件**: `src/index.css`
- **问题**: 例如 `--primary: #F8A67B` 在 CSS 中定义，但组件里同时用 `text-primary`（Tailwind 的 `colors.primary.DEFAULT`）和 `text-[#F8A67B]`（arbitrary value）。
- **改进**: 统一使用 Tailwind 的 design token，删除 CSS 变量的颜色定义。

#### P28: 图标尺寸使用不一致
- **文件**: `src/components/Navbar.tsx`, `src/components/Sidebar.tsx`, 所有页面
- **问题**: 图标尺寸有时用 `w-5 h-5`，有时用 `w-[18px] h-[18px]`，有时用 `w-4 h-4`。虽然差异不大，但反映了 AI 生成代码中不同 prompt 结果合并时的不一致性。
- **改进**: 统一使用 Tailwind 的 `w-5 h-5` 标准尺寸。

---

### 2.5 过度视觉堆砌（🟠 High）

#### P29: 每个卡片都有 3 层阴影和 hover 上浮效果
- **文件**: `src/index.css` 94-102
- **问题**: `.card` 的默认 shadow 是 `0 0 0 1px rgba(0,0,0,0.03), 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.02)`，hover 时又变成 `0 0 0 1px rgba(0,0,0,0.05), 0 4px 12px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.03)` 还加上 `transform: translateY(-2px)`。在密集的数据看板中，这会导致严重的视觉疲劳。
- **改进**: 统一为单层阴影，减少 hover 位移幅度（或完全移除）。

#### P30: 动画过度使用
- **文件**: `src/index.css` 191-208, 所有页面
- **问题**: 全局定义了 `fade-in`、`slide-up`、`slide-in-right`、`stagger-1..5` 等动画，但 Home 页面几乎每段内容都加了 `animate-fade-in stagger-X`。用户快速滚动时会被这些无意义的入场动画干扰。
- **改进**: 只在首屏 Hero 区域保留动画，其他内容静态展示。

#### P31: 词云、桑基图、雷达图、漏斗图是纯粹的"视觉噪音"
- **文件**: `src/components/charts/WordCloudChart.tsx`, `src/components/charts/SankeyChart.tsx`, `src/components/charts/FunnelChart.tsx`, `src/components/BrandScoreCard.tsx`
- **问题**: 这些图表在以下场景中均没有提供比简单表格/列表更直观的信息：
  - 桑基图：展示"社区→话题→情感"的流向，但数据是 mock 的，且节点太少（5个社区→6个话题→3个情感），用桑基图反而不如直接看列表清晰。
  - 词云：用螺旋算法放置文本，但每个词的 `sentimentConfidence` 字段没有对应的视觉编码（如颜色应该表示情感，但实际颜色是随机的）。
  - 漏斗图：5层数据用漏斗图，但用户真正关心的是各层转化率，一个带转化率的表格更直接。
  - 雷达图：6个维度的品牌评分，但每个维度是独立计算的，雷达图暗示了它们之间有某种关系，实际上并没有。
- **改进**: 删除或替换为更直接的表达方式（表格、柱状图、文字说明）。

#### P32: 阴影、圆角、backdrop-blur 在几乎每个容器上都叠加
- **文件**: `src/index.css`, `src/pages/Dashboard.tsx:280`, `src/components/PostDetailDrawer.tsx:90`
- **问题**: sticky header 用 `backdrop-blur-xl`，卡片用 `backdrop-blur`（虽然 `.card` 本身没有定义这个类），通知面板用 `backdrop-blur`。这种"毛玻璃"效果在 2024 年已严重过时，且性能开销大。
- **改进**: 删除所有 backdrop-blur，使用纯色背景即可。

#### P33: 每个 SectionCard 的标题区都带一个圆角图标背景
- **文件**: `src/components/SectionCard.tsx:18`
- **问题**: `w-9 h-9 rounded-icon bg-primary-light flex items-center justify-center` 这个模式在 Analytics 页面重复出现了 8 次。这是一种"为了有图标而放图标"的过度设计。
- **改进**: 部分 SectionCard 可以去掉图标，让标题本身传达层级。

#### P34: Toast / 提示信息全站只有「10 分钟前」一种形式
- **文件**: 所有页面
- **问题**: 没有真正的全局 Toast 系统，没有 loading state 的统一管理，没有错误提示的 UI 组件。所有操作反馈都依赖 console.warn 或页面内的小型文字提示。
- **改进**: 添加全局 Toast 组件，统一操作反馈。

#### P35: 状态徽章（badge）的样式在全站不统一
- **文件**: `src/components/PostCard.tsx:38-49`, `src/pages/UGCShowcase.tsx:81-85`, `src/pages/Insights.tsx:162-165`
- **问题**: 同样是表示"正面/负面/中性"的情感标签，在 PostCard 里用 `.badge`，在 UGCShowcase 里用内联 `bg-status-successBg text-status-success`，在 Insights 里又不同。没有统一的 `SentimentBadge` 组件。
- **改进**: 提取 `SentimentBadge`、`StatusBadge` 等原子组件。

#### P36: 骨架屏（Skeleton）与真实内容的差异过大
- **文件**: `src/components/DailyReport.tsx:14-73`
- **问题**: ReportSkeleton 使用 `shimmer` 动画的占位条，但 shimmer 的配色（`#FAFAFA → #F5F5F5`）与真实内容的卡片阴影差异很大，导致加载完成时的"闪变"感很强。
- **改进**: 骨架屏的结构应与真实内容尽可能接近，且不要使用动画 shimmer。

#### P37: 404 页面使用超大字号装饰性数字
- **文件**: `src/pages/NotFound.tsx:9`
- **问题**: `text-[80px] font-bold text-primary/10` 的 404 数字是 AI 生成落地页的典型痕迹——"为了好看而好看"，但对用户没有帮助。
- **改进**: 简洁的错误信息 + 返回按钮即可，不需要 80px 的半透明装饰数字。

#### P38: 搜索框的 focus 态触发白色背景变化
- **文件**: `src/pages/Dashboard.tsx:289`
- **问题**: `focus:bg-white` 在已经是白色/浅色背景的页面中，会造成轻微的闪烁感，且没有必要。
- **改进**: 删除 focus 背景色变化，改为 focus 边框色变化。

---

### 2.6 AI 文案模板化（🟡 Medium）

#### P39: 副标题文案高度重复、空泛
- **文件**: `src/pages/Home.tsx:95`, `src/pages/Home.tsx:112`, `src/pages/Home.tsx:148`
- **问题**: "简洁而强大的工具，帮助你发现每一个商机""无需复杂设置，几分钟即可启动你的 Reddit 舆情监测""快速了解 Reddit 舆情监测的核心问题"——这些是典型的 AI 套话，没有具体信息。
- **改进**: 改为具体的功能描述，如"自动追踪 12 个核心社区的每日讨论"。

#### P40: FAQ 的回答过于冗长且没有差异化
- **文件**: `src/data/searchMock.ts`（实际是 FAQ 的文案）
- **问题**: 每个 FAQ 答案都是"我们的 AI 模型基于大量数据训练..."的标准模板，缺乏 Momcozy 品牌的真实语气。
- **改进**: 用更简洁、口语化的方式回答，体现品牌个性。

#### P41: 功能页插图是 CSS 绘制的抽象几何图形
- **文件**: `src/pages/Features.tsx:24-82`
- **问题**: 三个 feature 的 illustration 都是 `<div className="rounded-full bg-surface-secondary">` 加几个小圆点的组合，这是 AI 无法生成真实插图时的典型 fallback。用户看到这些会立刻识别出"AI 做的"。
- **改进**: 使用真实的产品截图，或删除插图，或请设计师提供 SVG。

#### P42: Home 页面 Hero 右侧的"对话气泡"是纯 CSS 绘制的假 UI
- **文件**: `src/components/HeroSection.tsx:54-82`
- **问题**: 用 `div` + `bg-border/50` 的圆条模拟聊天内容，配合没有实际内容的占位符。这是典型的"为了有图而画图"。
- **改进**: 使用真实的产品截图或录屏，或完全去掉右侧视觉区。

#### P43: 洞察页面所有卡片标题都是「XX分析」「XX洞察」的堆砌
- **文件**: `src/pages/Insights.tsx`
- **问题**: "运营效率指标""团队工作负载""最佳实践推荐""情感趋势""预警历史""负面传播路径"——标题+副标题的格式完全一致，没有信息层次。
- **改进**: 根据信息重要性区分标题层级，部分次要信息可以折叠。

#### P44: 设置页面的文案是操作手册而非 UI 标签
- **文件**: `src/pages/Settings.tsx:241-244`, `src/pages/Settings.tsx:265-269`
- **问题**: input 的 helper text 是"从钉钉群设置 → 智能群助手 → 机器人管理 → 获取 Webhook URL"，这种详细的操作说明不应该常驻在 UI 中，而是放在文档里。
- **改进**: helper text 改为"如何获取 Webhook URL？"链接到文档。

#### P45: 案例广场的描述是"从微信公众号、垂类媒体中精选"——完全不符合产品定位
- **文件**: `src/pages/CaseGallery.tsx:290`
- **问题**: 一个 Reddit 舆情监测工具，声称案例来自"微信公众号、垂类媒体"，这是完全矛盾的。而且该页面没有展示任何真实的 Reddit 帖子数据。
- **改进**: 如果确实是案例广场，应该展示真实的 Reddit 帖子分析案例。

---

### 2.7 Mock 数据不真实（🟡 Medium）

#### P46: 所有时间戳都是"2小时前""3小时前"等相对时间，没有真实日期
- **文件**: `src/data/dailyReportMock.ts:210-328`, `src/data/searchMock.ts:83-96`
- **问题**: 没有使用真实日期，全部使用相对时间字符串，这让数据的可信度极低。
- **改进**: 使用真实日期（如 `2026-07-10`），并显示为相对时间（通过 date-fns 等库计算）。

#### P47: Reddit 帖子数据全部是英文，但 UI 是全中文
- **文件**: `src/data/dailyReportMock.ts:207-337`
- **问题**: 一个面向中国运营团队的工具，展示给用户的帖子标题却是全英文 Reddit 内容（如 "Looking for a quiet wearable breast pump for work"）。这是典型的 AI 用英文训练数据生成 mock 的问题。
- **改进**: 如果用户是中文运营团队，应提供翻译后的标题或至少标注原文/译文。

#### P48: 所有用户昵称都是英文+数字的 Reddit 风格
- **文件**: `src/data/dailyReportMock.ts`
- **问题**: `newmom2024`、`happymom_89`、`budgetmom2024` 等，这不是中国用户团队的语境。
- **改进**: 提供真实的中文语境下的用户画像。

#### P49: 数据增长率过于整齐（都是 12.5%、8.3%、3.2%）
- **文件**: `src/data/analyticsMock.ts:14-31`, `src/data/insightsMock.ts:34-40`
- **问题**: 所有 change 值都是 x.x 格式，且集中在 0-15% 范围内，没有真实数据的波动性（如 -1.7%、+23.4%）。
- **改进**: 使用更真实的随机数据生成器。

#### P50: 周报/月报数据是日报的线性乘法
- **文件**: `src/data/reportEngine.ts:472-482`
- **问题**: 代码中甚至有一个 `validateReportConsistency` 函数来检测 weekly newPosts 是否等于 daily * 7，这本身说明数据生成逻辑是有问题的。
- **改进**: 周报/月报应有独立的、非线性叠加的数据模型。

---

### 2.8 图表滥用（🟡 Medium）

#### P51: 桑基图在 Analytics 和 Insights 中各出现一次，数据完全相同但标题不同
- **文件**: `src/pages/Analytics.tsx:278-286`, `src/pages/Insights.tsx:293-300`, `src/pages/Messages.tsx:500-513`
- **问题**: 三个页面都放了桑基图，但数据和节点基本一样。这是为了"每个页面都有图表"而填充。
- **改进**: 删除重复的图表，每个页面只保留最相关的 1-2 个。

#### P52: 词云在 Analytics 和 Insights 中重复
- **文件**: `src/pages/Analytics.tsx:294-298`, `src/pages/Insights.tsx:303-308`, `src/pages/Messages.tsx:516-525`
- **问题**: 同上。关键词词云在三个页面出现，且内容几乎没有差异。
- **改进**: 只在搜索/分析页面保留词云，其他页面删除。

#### P53: 漏斗图在 Analytics 和 Insights 中重复
- **文件**: `src/pages/Analytics.tsx:258-263`, `src/pages/Insights.tsx:413-436`
- **问题**: 漏斗图数据完全一样，只是标题不同。
- **改进**: 保留一个即可。

#### P54: 雷达图在 BrandScoreCard 和 Insights 中重复
- **文件**: `src/components/BrandScoreCard.tsx:117-138`, `src/pages/Insights.tsx:321-329`
- **问题**: 品牌雷达图在 Dashboard 和 Insights 的品牌洞察页都出现，但数据不同（一个是 `defaultData`，一个是 `brandVoiceInsights`），会让用户困惑。
- **改进**: 统一品牌评分的数据源。

---

### 2.9 代码重复与耦合（🟡 Medium）

#### P55: 同样的 `formatTime` 函数在 3 个文件中重复定义
- **文件**: `src/pages/Dashboard.tsx:268-272`, `src/pages/CaseGallery.tsx:88-92`, `src/hooks/useWebhookPoller.ts`
- **问题**: `formatTime(seconds)` 把秒转成 `m:ss` 的函数被复制了多次。
- **改进**: 提取到 `utils/date.ts`。

#### P56: `sentimentConfig` 在多个文件中重复定义
- **文件**: `src/components/PostDetailDrawer.tsx:31-35`, `src/pages/Insights.tsx:181-185`, `src/data/intentConfig.ts`
- **问题**: 情感标签的配置（positive/negative/neutral 的颜色和图标）被重复定义了至少 3 次。
- **改进**: 统一到一个 `constants/sentiment.ts` 文件中。

#### P57: 顶部导航栏（Header）在 CaseGallery 页面被复制了一份
- **文件**: `src/pages/CaseGallery.tsx:252-277`
- **问题**: CaseGallery 没有使用全局的 `Navbar` 组件，而是内联写了一个几乎一样的 nav。这是代码合并时的痕迹。
- **改进**: 使用统一的 `Navbar` 或提取公共的 `TopNav` 组件。

#### P58: `useAsync` 的 `500ms` 假延迟在 Dashboard 和 Insights 中重复
- **文件**: `src/pages/Dashboard.tsx:223-226`, `src/pages/Insights.tsx:549-552`, `src/pages/Analytics.tsx:152-155`
- **问题**: 三个页面都用了 `await new Promise((resolve) => setTimeout(resolve, 500));` 来模拟数据加载，这是无意义的延迟。
- **改进**: 删除所有假延迟。

#### P59: `useAutoRefresh` 的倒计时功能在 CaseGallery 中重复了 Dashboard 的 webhook 倒计时逻辑
- **文件**: `src/pages/CaseGallery.tsx:88-92`, `src/pages/Dashboard.tsx:268-272`, `src/hooks/useWebhookPoller.ts`
- **问题**: 两套倒计时的实现逻辑（格式化、显示）分散在不同地方。
- **改进**: 提取为 `useCountdown` hook。

#### P60: `buildExportSections` 函数在 Dashboard 中硬编码了所有报告格式
- **文件**: `src/pages/Dashboard.tsx:23-184`
- **问题**: 这个函数长达 160 行，直接把 daily/weekly/monthly 的所有导出表格结构写在页面组件里。这违反了组件单一职责原则。
- **改进**: 提取到 `utils/export.ts` 或按报告类型拆分为独立文件。

---

### 2.10 可访问性缺失（🟢 Low）

#### P61: 大量交互元素缺少 `aria-label`
- **文件**: `src/components/PostDetailDrawer.tsx` 的按钮区, `src/pages/UGCShowcase.tsx` 的筛选按钮
- **问题**: 虽然部分元素有 aria-label，但大量图标按钮（如 bookmark、reply、share）没有标签，屏幕阅读器无法识别。

#### P62: 颜色对比度在某些组合下可能不足
- **文件**: `src/index.css` 的 `.badge` 类
- **问题**: `background-color: #FFF5EE` 配 `color: #F8A67B`（暖橙色在暖米色背景上），对比度可能低于 WCAG AA 标准（4.5:1）。
- **改进**: 使用更暗的文字色或更深的背景色。

#### P63: 自定义 Select / 下拉组件没有键盘导航
- **文件**: `src/components/ExportButton.tsx`, `src/components/NotificationCenter.tsx`
- **问题**: 下拉菜单可以通过 Escape 关闭，但无法通过上下箭头选择项目。

---

## 3. Top 10 最严重问题（按影响排序）

### #1 全站核心操作按钮都是假交互（🔴 Critical）
- **涉及文件**: `PostDetailDrawer.tsx`, `SectionCard.tsx`, `UGCShowcase.tsx`, `Settings.tsx`, `Messages.tsx`
- **影响**: 用户点击"回复帖子""分享链接""查看详情""推送至机器人"等核心操作无任何响应，这是毁灭性的信任打击。用户会认为整个产品都是不可用的。
- **建议**: 立即为所有按钮添加真实的 onClick 处理，或者将无功能的按钮置为 `disabled` 状态并显示 `title="即将上线"`。

### #2 Trust Bar 列出竞品当作"信赖品牌"（🔴 Critical）
- **文件**: `src/pages/Home.tsx:76-83`
- **影响**: 这是品牌层面的严重错误。Momcozy 的官网展示 Medela、Elvie 等竞品作为"被信赖的品牌"，会让专业用户立刻质疑产品的真实性。
- **建议**: 立即删除整个 Trust Bar 区域，或替换为真实的合作方/客户 logo。

### #3 设计令牌在三个地方重复定义，维护成本极高（🔴 Critical）
- **文件**: `design-tokens.ts`, `tailwind.config.js`, `src/index.css`
- **影响**: 任何颜色调整需要改 3 个文件，且极易遗漏。这是典型的 AI 生成代码"看起来有设计系统"实则无维护性。
- **建议**: 以 `tailwind.config.js` 为唯一数据源，删除其他重复定义。如果 design-tokens.ts 是为了被 JS 代码引用，应写一个 build step 将 tailwind config 同步到 JS 对象，或者使用 Tailwind 的 CSS variables 方案。

### #4 所有 Dashboard 内页结构完全复制粘贴，没有信息架构差异（🔴 Critical）
- **文件**: `Dashboard.tsx`, `Search.tsx`, `Analytics.tsx`, `Insights.tsx`, `UGCShowcase.tsx`, `Messages.tsx`, `Settings.tsx`
- **影响**: 7 个页面布局完全一致，用户无法通过视觉快速判断自己在哪个模块。这种"安全但无聊"的模板是 AI 代码的显著特征。
- **建议**: 提取 `DashboardLayout` 组件，但每个页面的首屏应有不同的信息密度和布局。例如：Analytics 页面首屏应是时间轴趋势，Search 页面首屏应是搜索条件面板。

### #5 首页 Hero 区展示无来源的虚荣指标（🟠 High）
- **文件**: `src/components/HeroSection.tsx:31-44`
- **影响**: "98% 准确率""10K+ 高意向帖子"等数字没有数据来源，在 B2B 产品中是严重的不诚信表现。专业用户会立即识别这是编造的。
- **建议**: 删除具体数字，或改为可验证的指标（如"实时追踪 Reddit 公开讨论"）。

### #6 词云/桑基图/漏斗图/雷达图是纯粹的视觉噪音（🟠 High）
- **文件**: `WordCloudChart.tsx`, `SankeyChart.tsx`, `FunnelChart.tsx`, `BrandScoreCard.tsx`
- **影响**: 这些图表占据大量屏幕空间，但提供的信息密度远低于表格或文字。用户看这些图表时需要花费更多认知成本去解读，而获取的信息却更少。这是"为了数据可视化而可视化"的 AI 设计痕迹。
- **建议**: 删除漏斗图和桑基图，将词云替换为排序后的关键词列表，雷达图替换为并列的进度条。

### #7 500ms 假加载延迟遍布全站（🟠 High）
- **文件**: `Dashboard.tsx`, `Analytics.tsx`, `Insights.tsx`, `CaseGallery.tsx`
- **影响**: 用户每次切换 tab 都会看到"加载中..."，但实际上数据早已在内存中。这种刻意的延迟是制造"系统很复杂"的假象，严重损害用户体验。
- **建议**: 立即删除所有 `setTimeout(..., 500)` 的延迟。数据切换应瞬间完成。

### #8 导出功能（PDF/PPT/Word）依赖重型库但生成的是简陋表格（🟠 High）
- **文件**: `src/components/ExportButton.tsx`
- **影响**: 代码依赖 `jspdf`、`html2canvas`、`pptxgenjs`、`docx` 四个重型库，但生成的 PDF/PPT/Word 只是简单 HTML 表格的截图。文件体积大，但输出质量低。且 `jsPDF` 和 `html2canvas` 不在 package.json 的 dependencies 中（从代码中 import 但 package.json 没有声明）。
- **建议**: 删除 PDF/PPT/Word 导出，只保留 CSV 导出。对于需要美观报告的场景，应该由后端生成 PDF。

### #9 Mock 数据全部使用英文，但 UI 和受众都是中文（🟠 High）
- **文件**: `dailyReportMock.ts`, `searchMock.ts`, `messagesMock.ts`, `ugcMock.ts`
- **影响**: 一个面向中国运营团队、全中文 UI 的工具，展示的数据源却是英文 Reddit 帖子。这让用户感觉产品是为演示而做的，不是为真实工作流设计的。
- **建议**: 提供中英双语对照的 mock 数据，或至少显示中文翻译。

### #10 FAQ 和营销文案是典型的 AI 套话堆砌（🟡 Medium）
- **文件**: `src/pages/Home.tsx`, `src/pages/FAQ.tsx`, `src/pages/Features.tsx`
- **影响**: 文案缺乏品牌个性，读起来像任意 SaaS 产品的通用描述。例如"简洁而强大的工具，帮助你发现每一个商机"——这句话可以套用在任何 CRM、邮件营销、或数据分析工具上。
- **建议**: 重写文案，使用具体的产品术语和 Momcozy 的品牌语境。例如：不要写"AI 智能识别"，而是写"自动识别 6 种购买意图：直接购买、竞品对比、使用求助..."

---

## 4. 改进优先级建议

| 优先级 | 行动项 | 预计工作量 |
|--------|--------|------------|
| P0 | 删除或禁用所有无功能按钮（#1） | 1-2 天 |
| P0 | 删除 Trust Bar 的竞品 logo（#2） | 10 分钟 |
| P0 | 统一设计令牌到 tailwind.config.js（#3） | 1 天 |
| P0 | 删除全站 500ms 假延迟（#7） | 30 分钟 |
| P1 | 重构 Dashboard 布局，区分模块信息架构（#4） | 2-3 天 |
| P1 | 删除或替换视觉噪音图表（#6） | 1-2 天 |
| P1 | 重写虚荣指标和营销文案（#5, #10） | 1-2 天 |
| P1 | 简化导出功能为 CSV only（#8） | 半天 |
| P2 | 重写 mock 数据为中文语境（#9） | 1-2 天 |
| P2 | 提取 Badge、Sentiment、Header 等公共组件 | 1-2 天 |

---

## 5. 总结

本项目的"AI 味"主要来源于以下几个方面：

1. **过度追求"视觉丰富"**：在每个页面都堆砌图表、阴影、动画、图标，但没有考虑信息密度和认知负荷。
2. **数据与交互"看起来能用"实则不能**：大量按钮、搜索框、开关、导出功能都是前端 state 的自嗨，没有真实的后端交互。
3. **模板化页面结构**：7 个 dashboard 内页是 Ctrl+C/Ctrl+V 的产物，没有任何针对功能场景的信息架构设计。
4. **设计系统的形式大于内容**：虽然写了 design-tokens.ts，但根本没有被使用，而是同时在 tailwind 和 CSS 中重复定义。
5. **文案空洞**：使用了大量 SaaS 产品的通用套话，没有 Momcozy 品牌的真实语气和产品细节。

**建议**：先完成 P0 级别的修复（禁用假功能、删除竞品 logo、统一设计令牌、删除假延迟），然后着手 P1 级别的信息架构重构。在重构之前，不建议继续添加新功能。
