# Momcozy Reddit 舆情工作台 — 技术移交文档 (v2.0)

> **文档用途**：本文件为 Reddit 舆情工作台（Vite + React + TypeScript）的技术移交文档，供后端开发团队（Codex）、前端维护团队及数据工程团队参考。
> **项目路径**：`/Users/pray/project/Reddit_VOC/ref/UI/momcozy-reddit-workbench`
> **技术栈**：Vite 5 + React 19 + TypeScript 6 + Tailwind CSS 3 + Zustand 5 + Recharts 3 + Vitest 3
> **当前状态**：重构完成，Mock 数据驱动，零构建错误，57/57 测试通过，主包 114KB（gzip 25KB）
> **Reddit 原始数据位置**：Codex 项目目录（`/Users/pray/project/Reddit_VOC/` 下的 Reddit 数据文件）

---

## 0. 项目概述与当前状态

### 0.1 项目背景

Momcozy Reddit 舆情工作台是一款面向品牌运营团队的舆情监控与洞察工具，专注于 Reddit 平台的品牌声量追踪、竞品分析、用户意图识别和危机预警。产品以 Momcozy 母婴品牌为核心服务对象，覆盖吸奶器、哺乳内衣、背奶包等品类，通过核心 Reddit 社区（r/breastfeeding, r/babybumps, r/NewParents, r/breastpumps, r/Mommit, r/pregnant）进行数据采集与分析。

**核心目标**：
- 实时监控品牌提及、竞品动态和情感波动
- 识别高意向购买用户和 UGC 口碑素材
- 提供日报/周报/月报三层时间维度的经营洞察
- 支持运营团队快速响应负面舆情和危机事件

### 0.2 技术栈总览（准确版本）

| 层级 | 技术选型 | 版本 | 说明 |
|------|----------|------|------|
| 构建工具 | Vite | 5.x | 极速开发构建 |
| 框架 | React | 19.x | 函数组件 + Hooks |
| 语言 | TypeScript | ~6.0.2 | 严格模式，15+ 处 `any` 已收敛 |
| 样式 | Tailwind CSS | 3.4.x | 原子化 CSS + 自定义设计令牌 |
| 路由 | React Router | 7.x | 声明式路由，支持嵌套布局 |
| 状态管理 | Zustand | 5.x | 3 个 Store（Report / Notification / Competitor） |
| 图表 | Recharts | 3.x | 情感趋势、漏斗图、雷达图、桑基图等 |
| 词云 | 自定义 canvas | — | 基于频率分布的 canvas 渲染 |
| 导出 | jspdf + html2canvas + docx | — | PDF/Word/CSV 导出 |
| 测试 | Vitest + React Testing Library | 3.x | 57 个测试全部通过，9 个测试文件 |
| 代码规范 | Oxlint | 1.x | 快速静态检查 |
| 打包优化 | Vite manualChunks | — | 主包从 2,213KB 降至 114KB（gzip 25KB） |

### 0.3 页面清单与路由

| 页面 | 路由 | 类型 | 说明 |
|------|------|------|------|
| 首页 | `/` | 营销页 | 产品价值展示，静态文案 |
| 功能介绍 | `/features` | 营销页 | 核心功能模块介绍 |
| 使用流程 | `/how-it-works` | 营销页 | 数据采集与分析流程 |
| 常见问题 | `/faq` | 营销页 | 用户 FAQ |
| 舆情看板 | `/dashboard` | 工作台核心 | 日报/周报/月报三层报告 + 品牌评分 + 舆情水位 |
| 深度分析 | `/dashboard/analytics` | 工作台核心 | 情感分析、话题聚类、社区画像、桑基图、词云 |
| 洞察中心 | `/dashboard/insights` | 工作台核心 | 运营/舆情/品牌/品类四维度洞察（含漏斗图、雷达图） |
| 帖子搜索 | `/dashboard/search` | 工作台核心 | 关键词/社区规则配置与帖子检索 |
| 消息中心 | `/dashboard/messages` | 工作台核心 | 通知、任务、警报、洞察统一管理（含桑基图+词云） |
| UGC 素材库 | `/dashboard/ugc-showcase` | 工作台核心 | 正面内容自动归档与展示 |
| 案例广场 | `/cases` | 工作台核心 | Reddit 应用案例链接卡片陈列（独立页面） |
| 系统设置 | `/dashboard/settings` | 工作台核心 | 搜索监测、竞品品牌（9个）、Webhook 配置 |
| 404 | `*` | 错误页 | 路由未匹配 |

### 0.4 重构完成清单（方案B）

| 序号 | 重构项 | 状态 | 说明 |
|------|--------|------|------|
| 1 | 硬编码颜色清理 | ✅ | 全部使用 `colors.ts` 设计令牌 |
| 2 | `any` 类型收敛 | ✅ | 15+ 处 `any` 替换为精确类型 |
| 3 | Service 层建立 | ✅ | 5 个 Service（Mock/Real 切换接口） |
| 4 | Zustand Store | ✅ | ReportStore + NotificationStore + CompetitorStore |
| 5 | 页面接入 Store | ✅ | Dashboard / Messages / Competitor / Navbar 已接入 |
| 6 | 大文件拆分 | ✅ | Insights 651→224行，CaseGallery 638→400行 |
| 7 | localStorage 版本化 | ✅ | `storage.ts` 工具库，支持版本控制和迁移 |
| 8 | Bundle 优化 | ✅ | manualChunks 拆包，主包 2,213KB → 114KB |
| 9 | 测试体系 | ✅ | 5 个新测试文件 + 2 个修复，57/57 通过 |
| 10 | 构建零错误 | ✅ | `npm run build` 零错误 |
| 11 | 全量视觉验证 | ✅ | 6 个页面截图验证通过 |

---

## 第一部分：Reddit 数据字段与页面数据依赖

### 1.1 Reddit 原始数据字段（来自 Codex 项目目录）

**重要**：Reddit 原始数据（帖子、评论、子版块元数据）存储在 Codex 项目目录中（`/Users/pray/project/Reddit_VOC/` 下的数据文件）。本 UI 项目为纯消费端，不直接存储 Reddit 数据。后端需从 Codex 数据目录读取原始数据，清洗后通过 API 提供给前端。

#### 1.1.1 帖子（Post）原始字段

Reddit API / Pushshift 返回的帖子字段，与前端 `RedditPost` 类型的映射：

| Reddit API 字段 | 前端字段（TypeScript） | 类型 | 必填 | 说明 |
|----------------|---------------------|------|------|------|
| `id` | `redditId` | `string` | 是 | Reddit 原始帖子 ID（如 `t3_1d1`） |
| `title` | `title` | `string` | 是 | 帖子标题 |
| `selftext` | `content` | `string` | 否 | 帖子正文内容（可为空） |
| `author` | `author` | `string` | 是 | 发帖用户 |
| `subreddit` | `subreddit` | `string` | 是 | 所属子版块名称 |
| `permalink` | `permalink` | `string` | 是 | 相对路径 |
| `url` | `url` | `string` | 是 | 完整 URL |
| `score` | `score` | `number` | 是 | Reddit 综合得分（upvotes - downvotes） |
| `upvote_ratio` | `upvoteRatio` | `number` | 是 | 点赞比率（0~1） |
| `num_comments` | `comments` | `number` | 是 | 评论数量 |
| `created_utc` | `createdAt` | `string` | 是 | ISO 8601 时间戳（UTC） |
| `over_18`, `spoiler`, `stickied`, `pinned`, `archived`, `locked`, `removed_by`, `edited`, `gilded`, `total_awards_received`, `domain`, `thumbnail`, `link_flair_text`, `link_flair_type`, `author_flair_text` | — | — | 否 | 建议后端存储备用，用于未来扩展（NSFW 过滤、awards 统计等） |

**前端派生字段（需后端 NLP 服务提供）：**

| 前端字段 | 类型 | 来源 | 说明 |
|---------|------|------|------|
| `id` | `string` | 后端生成 | 前端业务唯一标识（如 `d1`, `wd1`, `md1`） |
| `sentiment` | `'positive' \| 'neutral' \| 'negative'` | NLP 情感分析模型 | 帖子整体情感，三分类 |
| `intent` | `PostIntent` | NLP 意图分类模型 | 6 大标准意图：Purchase Intent / UGC / Bug Report / Comparison / Question / General |
| `intentScore` | `number` | NLP 意图模型 | 意图置信度（0~100） |
| `upvotes` | `number` | `score` 近似 | 前端展示用（当前直接映射 `score`） |
| `commentList` | `RedditComment[]` | 评论 API 聚合 | 帖子关联的评论列表 |

#### 1.1.2 评论（Comment）原始字段

| Reddit API 字段 | 前端字段 | 类型 | 必填 | 说明 |
|----------------|---------|------|------|------|
| `id` | `redditId` | `string` | 是 | 评论原始 ID |
| `body` | `body` | `string` | 是 | 评论内容 |
| `author` | `author` | `string` | 是 | 评论作者 |
| `subreddit` | — | — | 否 | 当前前端未直接使用（从父帖子推断） |
| `permalink` | `permalink` | `string` | 是 | 评论永久链接 |
| `score` | `score` | `number` | 是 | 评论得分 |
| `created_utc` | `createdAt` | `string` | 是 | 创建时间（ISO 8601 UTC） |
| `parent_id`, `link_id`, `is_submitter`, `edited`, `gilded`, `distinguished`, `stickied`, `collapsed`, `collapsed_reason`, `controversiality`, `depth` | — | — | 否 | 建议后端存储，用于构建评论树和争议性分析 |

**前端派生字段：**

| 前端字段 | 类型 | 来源 | 说明 |
|---------|------|------|------|
| `id` | `string` | 后端生成 | 前端业务 ID（如 `c1`） |
| `sentiment` | `'positive' \| 'neutral' \| 'negative'` | NLP 情感分析 | 单条评论情感 |
| `parentId` | `string` | `parent_id` | 父评论 ID，用于构建嵌套回复树 |
| `replies` | `RedditComment[]` | 递归聚合 | 子回复列表（前端 UI 当前展示 2 层） |

#### 1.1.3 子版块（Subreddit）原始字段

| Reddit API 字段 | 前端使用字段 | 类型 | 说明 |
|----------------|-------------|------|------|
| `display_name` | `name` | `string` | 子版块名称（如 `breastfeeding`） |
| `title` | `displayName` | `string` | 展示标题（如 `r/breastfeeding`） |
| `subscribers` | `subscribers` | `number` | 订阅用户数 |
| `public_description` | — | `string` | 建议存储，用于社区画像描述 |
| `created_utc` | — | `string` | 社区创建时间 |
| `submission_type` | — | `string` | 帖子类型限制 |
| `over18` | — | `boolean` | NSFW 标记 |
| `lang` | — | `string` | 语言 |
| `icon_img` | — | `string` | 社区图标 |
| `banner_img` | — | `string` | 横幅图片 |
| `user_is_subscriber` | — | `boolean` | 当前用户是否订阅 |
| `active_user_count` | — | `number` | 当前活跃用户（实时） |

**前端派生字段（SubredditProfile / SubredditMetric）：**

| 前端字段 | 类型 | 来源 | 说明 |
|---------|------|------|------|
| `postCount` | `number` | 聚合统计 | 时间范围内的帖子数 |
| `sentiment` | `object` | 聚合统计 | `{positive, neutral, negative}` |
| `vibe` | `string` | 规则分类 | 社区氛围标签：理性讨论型 / 情绪发泄型 / 口碑分享型 / 求助咨询型 / 热闹围观型 |
| `quality` | `'高' \| '中' \| '低'` | 规则分类 | 社区质量评级 |
| `worthInvesting` | `boolean` | 规则引擎 | 是否值得运营投入 |
| `topKeywords` | `string[]` | 关键词提取 | 高频关键词 |
| `engagement` | `number` | 聚合计算 | 平均互动数 |
| `momcozyMentions` | `number` | 关键词匹配 | 品牌提及数 |
| `competitorMentions` | `number` | 关键词匹配 | 竞品提及数 |
| `lastActive` | `string` | 实时计算 | 最后活跃时间 |
| `growthRate` | `number` | 环比计算 | 增长率 |

---

### 1.2 页面级数据依赖矩阵

#### 1.2.1 Dashboard 舆情看板（`/dashboard`）

**A. 品牌评分区（全周期通用）**

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 品牌评分环形图 | `brandScore` (0-100) | `reportEngine.ts` 聚合 | 综合舆情健康度 |
| 六维雷达图 | `radarDimensions: [声量, 口碑, 互动, 意向, 竞品优势, 危机响应]` | `reportEngine.ts` | 各维度 0-100 分值 |
| 维度明细 | `dimensionScores: {brandVoice, positiveWord, engagement, purchaseIntent, competitor, crisisResponse}` | `reportEngine.ts` | 六维度数值 + 趋势箭头 |

**B. 日报（Daily Report）**

| 模块 | 数据接口/字段 | 来源 | 说明 |
|------|-------------|------|------|
| 概览卡片 | `dailyOverview` | `dailyReportMock.ts` → 后端 API | 新帖数、正面率、负面率、紧急警报数、高意向数、UGC数 |
| 情感温度计 | `sentimentThermometer` | 后端 API | positive/negative/neutral 分布 + 情感等级（calm/watch/alert/crisis） |
| 响应指标 | `dailyResponseMetrics` | 后端 API | 平均响应时间、完成率、升级率 |
| 紧急警报 | `dailyAlerts` | 后端 API | 需立即响应的帖子列表（含 impactEstimate） |
| 新帖发现 | `dailyNewPosts` | 后端 API | 当日新帖列表（含 commentList） |
| 社区动态 | `dailyCommunityStatus` | 后端 API | 各社区新帖数、情感、趋势、活跃度指数、品牌提及率、情感变化速度 |
| 行动清单 | `dailyActionItems` | 后端 API | 待办事项（reply/collect/monitor/escalate） |
| 24小时情感趋势 | `dailySentimentTrend` | `reportEngine.ts` | 24小时堆叠面积图数据 |

**C. 周报（Weekly Report）**

| 模块 | 数据接口/字段 | 来源 | 说明 |
|------|-------------|------|------|
| 概览 | `weeklyOverview` | 后端 API | 7天聚合：新帖数、正面率、负面率、高意向、平均回复时间、UGC 收集量 |
| 趋势分析 | `weeklyTrends` | 后端 API | 本周 vs 上周：总帖子数、正面率、负面率、高意向、平均回复时间、UGC 收集量 |
| 机会洞察 | `weeklyOpportunities` | 后端 API | 话题爆发、UGC高产、转化机会、蓝海话题 |
| 风险洞察 | `weeklyRisks` | 后端 API | 负面投诉增长、竞品声量上升、社区负面率上升、危机发酵加速 |
| 竞品对标 | `weeklyCompetitors` | 后端 API | 9 个竞品的提及量、正面率、热门话题、心智份额、价格敏感度 |
| 运营复盘 | `weeklyReviews` | 后端 API | 帖子回复率、负面响应时间、UGC收集、高意向转化、品牌正面率（含 contentROI / engagementRate / communityEffectiveness） |
| 下周计划 | `weeklyPlans` | 后端 API | 行动项、优先级、目标社区、预期影响 |
| 情感趋势 | `weeklySentimentTrend` | 后端 API | 7天情感堆叠柱状图数据 |
| 痛点聚类 | `weeklyPainPoints` | 后端 API | 用户痛点 + 频率 + 严重度 + 解决方案 + 影响产品 |
| 话题演变 | `weeklyTopicEvolution` | 后端 API | 话题生命周期（emerging/rising/peak/declining）+ 预测 |
| 品牌声量趋势 | `weeklyBrandVoiceTrends` | 后端 API | 周一至周日各品牌声量曲线 |
| 内容策略 ROI | `weeklyContentStrategyROI` | 后端 API | UGC内容转化、竞品对比回复、新手指南、品牌故事植入的 ROI |
| 市场份额 | `weeklyShareOfVoice` | 后端 API | 各品牌每日讨论份额占比 |
| 机会热力图 | `weeklyOpportunityHeatmap` | 后端 API | 场景-机会-得分矩阵 |
| 竞品定位 | `weeklyCompetitorPositioning` | 后端 API | 品牌定位 + 心智份额 + 价格敏感度 |
| 话题演化数据 | `weeklyTopicEvolution` | 后端 API | 7天话题量 + 预测值 + 预测准确率 |

**D. 月报（Monthly Report）**

| 模块 | 数据接口/字段 | 来源 | 说明 |
|------|-------------|------|------|
| 概览 | `monthlyOverview` | 后端 API | 30天聚合，含 sentimentLevel 标签 |
| 品牌健康度 | `monthlyBrandHealth` | 后端 API | 品牌提及量、正面情感率、口碑NPS、平均互动数、响应速度（本月 vs 上月） |
| 品牌雷达图 | `monthlyBrandHealthRadar` | 后端 API | 六维雷达：声量/情感/参与度/转化/忠诚度/创新度（含行业基准） |
| 品牌趋势 | `monthlyBrandHealthTrend` | 后端 API | 6个月正面情感率趋势 |
| 品牌评分 | `monthlyBrandHealthScore` | 后端 API | 0~100 综合品牌健康分 |
| 竞争格局 | `monthlyCompetitorShares` | 后端 API | 各品牌讨论份额、正面率、月环比、热门话题 |
| 竞争矩阵 | `monthlyCompetitiveMatrix` | 后端 API | 市场份额 vs 增长率矩阵（star/question/cash-cow/dog） |
| 社区 ROI | `monthlyCommunityROI` | 后端 API | 各社区帖子数、线索数、转化率、质量评级、ROI 描述 |
| 品类矩阵 | `monthlyCategoryMatrix` | 后端 API | 吸奶器/哺乳内衣/背奶包/储奶袋/乳头霜的 volume/growthRate/conversionRate/roi |
| 话题演变 | `monthlyTopicEvolution` | 后端 API | 话题量、增长率、情感、生命周期、预测、预测准确率 |
| KPI 达成 | `monthlyKPIs` | 后端 API | 总帖子覆盖、正面情感率、负面响应时间、高意向转化、UGC收集、社区运营覆盖（含达成率） |
| KPI 趋势 | `monthlyKPITrend` | 后端 API | 6个月达成率变化 |
| 战略建议 | `monthlyStrategicAdvices` | 后端 API | 建议标题、描述、优先级、预期影响、时间框架、资源分配、预期 ROI |
| 情感趋势 | `monthlySentimentTrend` | 后端 API | 30天情感堆叠数据 |

**E. 数据联动与一致性校验（后端需实现）**

| 功能 | 说明 |
|------|------|
| `generateReportData(period, seed)` | 根据周期生成完整报告数据，支持随机 seed 使数据有逻辑关联 |
| `computeWeeklyOverviewFromDaily()` | 日报 → 周报聚合，非线性因子（sqrt + 波动）避免简单倍数关系 |
| `computeMonthlyOverviewFromWeekly()` | 周报 → 月报聚合，幂函数 + 波动 |
| `validateReportConsistency()` | 跨周期一致性校验：情感率总和=100、跨周期帖子数比值合理性 |
| `generateDailySentimentTrend()` | 24小时情感趋势，基于时间模式（白天高活跃）+ 随机扰动 |
| `generateBrandScoreData()` | 从 overview 聚合六维品牌评分 |
| `computeOverviewFromSentimentTrend()` | 从情感趋势反算 overall 情感率 |
| `aggregateSankeyFromPosts()` | 从帖子列表（subreddit + sentiment + intent）聚合生成桑基图数据 |

---

#### 1.2.2 Analytics 深度分析（`/dashboard/analytics`）

| 模块 | 数据接口/字段 | 来源 | 说明 |
|------|-------------|------|------|
| 统计卡片 | `getAnalyticsStats(timeRange)` | `analyticsMock.ts` → 后端 API | 总帖子数、正面情感占比、话题聚类数、活跃社区数（7d/30d/90d） |
| 情感分析 | `SentimentAnalysis` 组件 | 后端 API | 情感总览 + 情感趋势时序图 + 各社区情感分布 |
| 竞品对比 | `CompetitorComparison` 组件 | 后端 API | 竞品提及量、情感得分、声量份额、趋势方向 |
| 影响者识别 | `InfluencerIdentification` 组件 | 后端 API | 高影响力用户（基于 karma / 发帖量 / 互动率） |
| 受众画像 | `AudiencePersona` 组件 | 后端 API | 用户 demographics、兴趣分布、活跃时段 |
| 关键词词云 | `keywordWordCloud` | 后端 API | `{text, value, color, sourcePostIds, sentimentConfidence}` |
| 社区-话题-情感桑基图 | `sankeyNodes` + `getSankeyLinks(timeRange)` | 后端 API | 三层流转：社区 → 话题 → 情感 |
| 话题聚类 | `getTopicClusters(timeRange)` | 后端 API | 6 大话题簇，含 count/sentiment/relatedTopics/trend/growth/keywords |
| 子版块画像 | `getSubredditProfiles(timeRange)` | 后端 API | 5 大社区详细画像 |

---

#### 1.2.3 Insights 深度洞察（`/dashboard/insights`）

四维度标签页，每个维度独立数据模块。

**A. 运营洞察（Operation）**

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 运营效率指标 | `operationInsights` | `insightsMock.ts` → 后端 API | 平均响应速度、待办处理率、紧急事项处理率、UGC素材收集、团队饱和度 |
| 团队工作负载 | `teamWorkloads` | 后端 API | 成员任务分配/完成数、平均响应时间、效率值 |
| 最佳实践推荐 | `bestPractices` | 后端 API | 策略标题、描述、影响度、已应用次数 |

**B. 舆情洞察（Sentiment）**

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 情感趋势 | `sentimentTrendHistory` | 后端 API | 7天情感分布 + 预警数量 |
| 预警历史 | `warningHistory` | 后端 API | 预警事件标题、等级、日期、状态、响应时间 |
| 负面传播路径 | `negativeSpreads` | 后端 API | 负面源头、传播路径、影响帖子数、遏制时间 |
| 危机处理复盘 | `crisisReviews` | 后端 API | 危机标题、日期、严重度、响应时间、处理方式、经验教训 |
| 舆情流向桑基图 | `sentimentSankeyNodes` + `sentimentSankeyLinks` | 后端 API | 情感 → 意图 → 社区三层流转 |
| 关键词云 | `sentimentWordCloudData` | 后端 API | 高频关键词 + 情感置信度 + 来源帖子 ID |

**C. 品牌洞察（Brand）**

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 品牌声量雷达 | `brandVoiceInsights` | 后端 API | 6 维度对比：性价比/静音设计/便携性/吸力/品牌信任/售后服务（Momcozy vs 9 竞品） |
| 品牌定位差异 | `brandPositioning` | 后端 API | 属性认知对比：价格亲民/技术创新/用户口碑/售后服务 |
| 用户心智份额 | `mindShareTrends` | 后端 API | 6个月品牌心智份额趋势 |

**D. 品类洞察（Category）**

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 用户需求转化漏斗 | `categoryFunnelData` | 后端 API | Reddit 讨论 → 提及 Momcozy → 购买意向 → 咨询细节 → 转化反馈（5层漏斗） |
| 新品机会 | `productOpportunities` | 后端 API | 机会标题、描述、需求度、竞争度、潜在 ROI |
| 用户痛点 | `userPainPoints` | 后端 API | 痛点描述、频率、严重度、所属品类 |
| 产品反馈 | `productFeedbacks` | 后端 API | 产品名称、反馈内容、情感、来源、upvotes |
| 市场空白 | `marketGaps` | 后端 API | 空白描述、需求证据、竞争密度、预估市场规模 |
| 策略推荐 | `strategyItems` | 后端 API | 策略标题、描述、优先级、类别、执行状态 |
| 最佳发布时机 | `bestTiming` | 后端 API | 周一至周日各时段发布评分 + 推荐时段 |
| 推荐社区 | `bestTiming.recommendedSubreddits` | 后端 API | 社区名称、优先级（P0/P1/P2）、推荐理由 |
| 执行时间线 | `timeline` | 后端 API | 4 周执行计划（周/标题/任务列表/目标） |

---

#### 1.2.4 Search 帖子搜索（`/dashboard/search`）

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 关键词规则 | `keywordRules` | `searchMock.ts` → 后端 API | 关键词标签、类型（brand/product/competitor/general）、激活状态、匹配次数、创建时间 |
| 社区规则 | `subredditRules` | 后端 API | 社区名称、展示名、订阅数、激活状态、帖子数、最近抓取时间、tier（A/B/C） |
| 搜索配置 | `searchConfig` | 后端 API | 时间范围、AI 过滤、最小点赞数、自动通知、关键词/社区 tier 过滤 |
| 帖子结果 | `searchPosts` | 后端 API | 帖子标题、社区、作者、时间、点赞、评论、意向分、情感、意图、推荐动作、状态（new/replied/saved） |

---

#### 1.2.5 Messages 消息中心（`/dashboard/messages`）

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 通知列表 | `notifications` | `messagesMock.ts` → 后端 API | 类型（alert/task/insight/system）、标题、描述、社区、帖子标题、严重度、已读状态、时间、动作、动作URL |
| 通知规则 | `notificationRules` | 后端 API | 规则名称、描述、类型（sentiment/intent/mention/competitor/trend/system）、激活状态、渠道（app/dingtalk/feishu）、阈值、频率 |
| 帖子关联 | `notificationPostMap` | 后端 API | 通知 ID → 帖子详情映射，用于抽屉展示 |
| 舆情流向桑基图 | `messageSankeyNodes` + `messageSankeyLinks` | 后端 API | 情感 → 意图 → 社区桑基图（消息中心视角） |
| 关键词云 | `messageWordCloudData` | 后端 API | 消息中心高频词分布 |
| 统计卡片 | `messageStats` | 后端 API | 未读消息、待处理警报、待办任务、新洞察 4 个计数 |

---

#### 1.2.6 UGC Showcase 素材库（`/dashboard/ugc-showcase`）

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| UGC 素材 | `ugcItems` | `ugcMock.ts` → 后端 API | 标题、内容、作者、社区、点赞、评论、情感、意向分、创建时间、URL、分类、标签、归档状态、归档时间、媒体类型、互动率、被引用站点、自动归档原因 |
| 统计 | `getUGCStats()` | 后端 API | 已归档总数、本周新增、正面率、平均互动率、热门分类 |
| 筛选 | `getUGCItemsByTimeRange()` + `filterUGCItems()` | 后端 API | 按时间范围（7d/30d/90d）、分类、媒体类型、情感、搜索词、最小互动率筛选 |

---

#### 1.2.7 Case Gallery 案例广场（`/cases`）

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 案例列表 | `cases` | `casesMock.ts` → 后端 API / 定时爬虫 | 案例标题、描述、来源、URL、分类（geo/newproduct/insight/business）、标签、日期 |
| 分类配置 | `caseCategories` | 前端配置 | 分类标签、描述、颜色配置 |
| 热门标签 | `hotSearchTags` | 前端配置 | 热门检索标签 + 出现次数 |
| 搜索 | `fetchCases(query, category)` | 后端 API / 本地搜索 | 异步搜索，支持标题/描述/标签/来源匹配 |

**案例数据来源**：
1. 预置静态案例（Redis 官方论坛、微信公众号高质量文章）
2. 定时网络检索（后端爬虫或第三方 API，如 RSS 聚合）
3. 手动添加（运营团队后台录入）

**已预置的微信公众号链接**：
- `https://mp.weixin.qq.com/s/Bh2QSfzadAYEmvmRoYxolw`
- `https://mp.weixin.qq.com/s/11LqiC2drOr1sCpPa3NkCA`
- `https://mp.weixin.qq.com/s/LXd3yOmETvpa7w8vKpxjkg`
- `https://mp.weixin.qq.com/s/UMYeNTmeVhB8kGC9SEI6Ig`
- `https://mp.weixin.qq.com/s/3HcpcwXCNxJlL3etncMGRw`

---

#### 1.2.8 Settings 系统设置（`/dashboard/settings`）

| 模块 | 数据字段 | 来源 | 说明 |
|------|---------|------|------|
| 用户配置 | `UserProfile` / `UserSettings` | `src/types/index.ts` + 后端 API | 主题、语言、通知偏好、默认报告周期、时区 |
| Webhook 配置 | `WebhookConfig` | `src/types/index.ts` + `useWebhookConfig.ts` + 后端 API | 钉钉/飞书推送配置：名称、URL、Secret、激活状态、渠道过滤、严重度过滤 |
| 竞品品牌配置 | `competitorBrands` | `CompetitorStore` + 后端 API | 9 个竞品品牌（可增删改） |
| 通知发送 | `useNotificationSender.ts` | `src/hooks/` | 向 Webhook 发送通知，支持钉钉签名校验和飞书验证 |
| 轮询推送 | `useWebhookPoller.ts` | `src/hooks/` | 定时轮询未读通知并推送到 Webhook |

---

### 1.3 数据类型与来源汇总

#### 1.3.1 数据类型总览（按来源分类）

| 数据类型 | 数量 | 存储位置 | 后端迁移优先级 | 说明 |
|---------|------|---------|-------------|------|
| **原始 Reddit 数据** | 3 类 | Codex 项目目录 → 后端数据库 | P0 | 帖子、评论、子版块信息（PostgreSQL） |
| **NLP 分析结果** | 2 类 | 后端数据库 | P0 | 情感分析、意图分类（需 NLP 服务） |
| **聚合统计** | 10+ 类 | 后端聚合引擎 | P0 | 日报/周报/月报统计、话题聚类、社区画像等（ClickHouse/DuckDB 建议） |
| **业务规则配置** | 4 类 | 后端数据库 | P1 | 关键词规则、社区规则、通知规则、Webhook 配置 |
| **UGC 归档** | 1 类 | 后端数据库 | P1 | 自动归档的 UGC 素材 |
| **案例库** | 1 类 | CMS / 静态文件 | P2 | 案例广场内容可先用静态 JSON，后期接入 CMS |
| **用户数据** | 2 类 | 后端数据库 | P1 | 用户配置、收藏夹（localStorage 当前，后端需同步） |

#### 1.3.2 Mock 数据文件清单（替换为后端 API）

| 文件路径 | 导出内容 | 服务页面 | 后端 API 建议路径 |
|---------|---------|---------|-----------------|
| `src/data/dailyReportMock.ts` | 日报全部数据 | Dashboard (daily) | `GET /api/reports/daily` |
| `src/data/weeklyReportMock.ts` | 周报全部数据 | Dashboard (weekly) | `GET /api/reports/weekly` |
| `src/data/monthlyReportMock.ts` | 月报全部数据 | Dashboard (monthly) | `GET /api/reports/monthly` |
| `src/data/analyticsMock.ts` | 分析页数据 | Analytics | `GET /api/analytics` |
| `src/data/insightsMock.ts` | 洞察页四维度数据 | Insights | `GET /api/insights/{dimension}` |
| `src/data/searchMock.ts` | 搜索配置与结果 | Search | `GET /api/search` + `POST /api/search` |
| `src/data/messagesMock.ts` | 通知与规则 | Messages | `GET /api/notifications` + `GET /api/notification-rules` |
| `src/data/ugcMock.ts` | UGC 素材 | UGCShowcase | `GET /api/ugc` |
| `src/data/casesMock.ts` | 案例库 | CaseGallery | `GET /api/cases` |
| `src/data/reportEngine.ts` | 报告引擎 + 数据联动 | Dashboard | 后端需实现 `ReportEngine` 等价逻辑 |

#### 1.3.3 Service 层接口（前端已就绪，后端需实现）

前端已建立 5 个 Service 文件，定义了 Mock/Real 切换接口：

```typescript
// src/services/reportService.ts
export interface IReportService {
  getDailyReport(): Promise<DailyReportData>;
  getWeeklyReport(): Promise<WeeklyReportData>;
  getMonthlyReport(): Promise<MonthlyReportData>;
  getBrandScore(): Promise<BrandScoreData>;
}

// src/services/insightService.ts
export interface IInsightService {
  getInsights(dimension: InsightDimension): Promise<InsightData>;
  getWordCloud(dimension: InsightDimension): Promise<WordCloudDatum[]>;
  getSankey(dimension: InsightDimension): Promise<SankeyData>;
}

// src/services/messageService.ts
export interface IMessageService {
  getNotifications(): Promise<Notification[]>;
  getNotificationRules(): Promise<NotificationRule[]>;
  markAsRead(id: string): Promise<void>;
}

// src/services/searchService.ts
export interface ISearchService {
  searchPosts(query: SearchQuery): Promise<SearchResult>;
  getKeywordRules(): Promise<KeywordRule[]>;
  getSubredditRules(): Promise<SubredditRule[]>;
}

// src/services/caseService.ts
export interface ICaseService {
  getCases(): Promise<Case[]>;
  searchCases(query: string, category?: string): Promise<Case[]>;
}
```

后端只需实现上述接口，前端通过切换 `USE_MOCK` 环境变量即可从 Mock 切换到 Real。

---

### 1.4 关键数据流说明

#### 1.4.1 看板数据流

```
Reddit API 爬取 → 原始数据存储 → NLP 分析 → 聚合统计 → reportEngine 生成 → Dashboard 展示
                    │                │            │              │
                    ▼                ▼            ▼              ▼
               PostgreSQL      NLP Service   ClickHouse    UnifiedReportData
```

#### 1.4.2 实时通知流

```
新帖检测 → NLP 分析 → 规则匹配 → 通知生成 → 消息中心存储 → Webhook 推送 → 钉钉/飞书
              │            │           │            │              │
              ▼            ▼           ▼            ▼              ▼
         情感/意图      阈值判断    Notification   Zustand Store   useWebhookPoller
```

#### 1.4.3 UGC 归档流

```
帖子采集 → NLP 分析 → 意图/情感过滤 → 归档规则匹配 → UGC 素材库 → 前端展示
              │            │              │
              ▼            ▼              ▼
         positive +    intentScore    autoArchiveReason
         UGC intent    >= 阈值
```

---

### 1.5 字段变更风险清单

| 风险项 | 影响页面 | 建议 |
|-------|---------|------|
| `redditId` 格式变更（如从 `t3_xxx` 变为纯数字） | 全站 | 后端统一映射为字符串 |
| `score` 与 `upvotes` 分离（Reddit 隐藏 downvotes） | Dashboard, Search, UGC | 前端当前用 `score` 当 `upvotes` 展示，后端需明确提供展示值 |
| 评论树深度超过 3 层 | Dashboard, Search | 前端已支持 `replies` 递归，但 UI 仅展示 2 层，需约定最大深度 |
| 子版块 `subscribers` 字段缺失 | Analytics, Dashboard | 社区画像依赖该字段，需后端提供或标记为未知 |
| `created_utc` 时区问题 | 全站 | 后端统一返回 ISO 8601 格式，前端按用户设置时区转换 |
| NLP 模型升级导致 sentiment/intent 定义变更 | 全站 | 需版本化 NLP 结果，或保持 3 分类情感 + 6 分类意图不变 |
| 新增竞品品牌（当前 9 个） | Dashboard, Analytics, Insights | 竞品相关数组需支持动态扩展，已改为 Zustand Store 管理 |

---

## 第二部分：技术架构与部署方案

### 2.1 腾讯云轻量服务器选型

#### 2.1.1 服务器部署区域选择

| 区域 | 适用场景 | 推荐等级 |
|------|----------|----------|
| 新加坡 | Reddit API 直连延迟低（~50ms），无需额外代理 | **首选** |
| 香港 | 兼顾国内团队访问与海外 API 连通性 | 次选 |
| 硅谷 | 最低 API 延迟，但国内团队访问需加速 | 备选 |

> **决策依据**：Reddit / Pushshift API 服务器位于美国东海岸，新加坡节点经太平洋链路访问延迟可接受，同时腾讯云新加坡轻量服务器提供内地优化带宽包，兼顾国内团队日常运维访问。

#### 2.1.2 实例配置规格

| 组件 | 规格 | 说明 |
|------|------|------|
| CPU | 4 核 | NLP 推理与定时任务并发需多核支撑 |
| 内存 | 8 GB | spaCy / transformers 模型加载后常驻内存约 2-4GB，留余量 |
| 系统盘 | 80 GB SSD | 操作系统 + 应用代码 + 依赖库 |
| 数据盘 | 200 GB SSD | PostgreSQL 数据文件 + 日志 + 模型文件 |
| 带宽 | 30 Mbps（峰值） | 满足 Reddit API 分页拉取与前端用户并发 |
| 流量包 | 3 TB/月 | 按日均 10 万条帖子+评论全量文本估算 |

#### 2.1.3 高可用与灾备策略

- **快照策略**：系统盘每日凌晨 02:00 自动快照，保留 7 天
- **数据备份**：PostgreSQL 通过 `pg_dump` 每日增量 + 每周全量，转存至腾讯云 COS（标准存储）
- **故障恢复**：轻量服务器不支持多可用区热备，需预备镜像 + 自动化重建脚本（Terraform），RTO < 30 分钟
- **监控告警**：腾讯云云监控绑定 CPU > 80%、内存 > 85%、磁盘 > 80% 阈值，触发钉钉/飞书 Webhook

---

### 2.2 后端技术栈

#### 2.2.1 核心框架与运行时

| 层级 | 技术选型 | 版本约束 | 选型理由 |
|------|----------|----------|----------|
| 运行时 | Node.js (LTS) | ≥ 20.x | 与前端 Vite 生态一致，团队学习成本低 |
| API 框架 | Express.js | ^4.18 | 轻量、中间件生态成熟、与 TypeScript 集成完善 |
| ORM | Prisma | ^5.x | 类型安全、迁移管理、支持 PostgreSQL |
| 进程管理 | PM2 | latest | 集群模式、日志切割、自动重启 |
| 反向代理 | Nginx | latest | SSL 终止、静态资源缓存、Rate Limiting |

#### 2.2.2 数据与中间件层

| 组件 | 技术选型 | 用途 |
|------|----------|------|
| 关系数据库 | PostgreSQL 15 | 结构化业务数据：帖子、评论、案例、配置、报表指标 |
| 文档数据库 | MongoDB 6.x | 原始 Reddit JSON 归档、非结构化日志 |
| 缓存 | Redis 7.x | Session 存储、热点数据缓存、限流计数器 |
| 消息队列 | Redis Streams | 轻量级任务队列，避免额外引入 RabbitMQ 增加复杂度 |
| 搜索引擎 | Meilisearch | 站内全文检索（帖子标题/正文/评论），替代重量级的 Elasticsearch |
| 对象存储 | 腾讯云 COS | 导出文件（CSV/PDF/Word）、UGC 素材图片、备份 |

#### 2.2.3 NLP 与 AI 服务层

| 服务 | 技术选型 | 部署方式 |
|------|----------|----------|
| 情感分析 | VADER (NLTK) + 领域微调 BERT | 本地推理（CPU 友好） |
| 主题聚类 | BERTopic | 本地推理 |
| 关键词提取 | KeyBERT | 本地推理 |
| 命名实体识别 | spaCy (en_core_web_md) | 本地推理 |
| 文本摘要 | BART / T5 小型版本 | 本地推理（低频次调用） |
| 翻译（如需） | 腾讯云机器翻译 API | 云端调用 |

#### 2.2.4 运维与监控

| 组件 | 用途 |
|------|------|
| Sentry | 错误追踪与性能监控 |
| Grafana + Prometheus | 系统指标可视化（容器化后可替换为腾讯云监控） |
| Logrotate + rsyslog | 日志轮转与集中收集 |

---

### 2.3 数据采集 Pipeline

#### 2.3.1 数据源与采集策略

**主数据源：Reddit API (PRAW) + Pushshift API**

| 数据类型 | 采集接口 | 频率 | 增量策略 |
|----------|----------|------|----------|
| 帖子 (Submission) | PRAW `subreddit.new()` | 每 15 分钟 | `created_utc > last_cursor` |
| 评论 (Comment) | PRAW `submission.comments` | 每 15 分钟 | 增量爬取新增帖子的评论树 |
| 子版块元数据 | PRAW `subreddit.about()` | 每日 | 全量更新订阅数、描述 |
| 历史回溯 | Pushshift `/search/submission` | 按需 | 初始化或补数据时使用 |

#### 2.3.2 采集 Pipeline 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Scheduler (node-cron)                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ 触发任务
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Task Dispatcher (Bull Queue)              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │ job: daily   │  │ job: weekly  │  │ job: subreddit     │ │
│  │   collect    │  │   aggregate  │  │   monitor          │ │
│  └──────────────┘  └──────────────┘  └────────────────────┘ │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│  Worker 1  │  │  Worker 2  │  │  Worker 3  │   ← PM2 集群模式
│ (采集)     │  │ (采集)     │  │ (清洗)     │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │
      └───────────────┴───────────────┘
                      │
                      ▼
        ┌─────────────────────────────┐
        │      Data Transformer       │
        │  - 格式标准化               │
        │  - 敏感信息脱敏（author 哈希）│
        │  - 链接去重（permalink 唯一） │
        └──────────────┬──────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │PostgreSQL│ │ MongoDB  │ │  Redis   │
   │ 热数据   │ │ 原始归档 │ │ 缓存队列 │
   └──────────┘ └──────────┘ └──────────┘
```

#### 2.3.3 核心采集模块说明

**1. Reddit API 采集器 (PRAW Adapter)**

```typescript
// 核心接口设计（与前端类型对齐）
interface RedditPost {
  id: string;                    // t3_xxxx
  title: string;
  selftext: string;
  author: string;
  subreddit: string;
  permalink: string;
  url: string;
  score: number;
  upvote_ratio: number;
  num_comments: number;
  created_utc: number;
  over_18: boolean;
  spoiler: boolean;
  stickied: boolean;
  link_flair_text: string | null;
  // ... 其他字段见 src/types/index.ts
}
```

**2. 采集任务调度**

| 任务类型 | Cron 表达式 | 说明 |
|----------|-------------|------|
| 增量帖子采集 | `*/15 * * * *` | 每 15 分钟扫描目标 subreddit |
| 评论回填 | `0 */2 * * *` | 每 2 小时回填新增帖子的评论 |
| 日报生成 | `0 8 * * *` | 每日 08:00（UTC+8）生成昨日日报 |
| 周报生成 | `0 9 * * 1` | 每周一 09:00 生成上周周报 |
| 月报生成 | `0 10 1 * *` | 每月 1 日 10:00 生成上月月报 |
| 数据清理 | `0 3 * * *` | 清理过期日志和临时文件 |

**3. 反爬与限流策略**

- **PRAW Rate Limit**：内置 Reddit API 限流（60 req/min），通过 PRAW 的 `ratelimit_seconds` 自动退避
- **代理池**：新加坡轻量服务器直连，若遇 IP 封禁切换至备用代理（需提前配置 2-3 个住宅代理）
- **User-Agent 轮换**：固定声明 `"MomcozyRedditBot/1.0 by /u/momcozy_official"`，避免伪装浏览器被封
- **失败重试**：指数退避重试（1s, 2s, 4s, 8s, 16s），最多 5 次后转入死信队列人工处理

---

### 2.4 存储方案

#### 2.4.1 数据分层模型

按数据访问频率与结构化程度，将存储划分为三层：

| 层级 | 存储介质 | 数据类型 | 保留策略 |
|------|----------|----------|----------|
| **热数据层** | PostgreSQL + Redis | 帖子元数据、清洗后评论、统计指标、用户配置 | 永久保留 |
| **温数据层** | MongoDB | 原始 Reddit JSON、NLP 中间结果、历史报表快照 | 6 个月滚动 |
| **冷数据层** | 腾讯云 COS（归档存储） | 导出文件、全量数据快照、日志归档 | 2 年 |

#### 2.4.2 PostgreSQL 核心表结构

基于前端类型定义推导：

```sql
-- 1. 帖子主表 (reddit_posts)
CREATE TABLE reddit_posts (
    id              TEXT PRIMARY KEY,           -- t3_xxxx
    title           TEXT NOT NULL,
    selftext        TEXT,
    author          TEXT NOT NULL,              -- 存储哈希值，脱敏
    subreddit       TEXT NOT NULL,
    permalink       TEXT NOT NULL UNIQUE,
    url             TEXT,
    score           INTEGER DEFAULT 0,
    upvote_ratio    DECIMAL(3,2),
    num_comments    INTEGER DEFAULT 0,
    created_utc     TIMESTAMPTZ NOT NULL,
    over_18         BOOLEAN DEFAULT FALSE,
    spoiler         BOOLEAN DEFAULT FALSE,
    stickied        BOOLEAN DEFAULT FALSE,
    link_flair_text TEXT,
    sentiment_score DECIMAL(4,3),               -- NLP 情感得分
    topic_cluster   INTEGER,                    -- 主题聚类 ID
    collected_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_posts_subreddit ON reddit_posts(subreddit);
CREATE INDEX idx_posts_created ON reddit_posts(created_utc);
CREATE INDEX idx_posts_sentiment ON reddit_posts(sentiment_score);

-- 2. 评论表 (reddit_comments)
CREATE TABLE reddit_comments (
    id          TEXT PRIMARY KEY,
    body        TEXT NOT NULL,
    author      TEXT NOT NULL,
    subreddit   TEXT NOT NULL,
    permalink   TEXT NOT NULL,
    score       INTEGER DEFAULT 0,
    created_utc TIMESTAMPTZ NOT NULL,
    parent_id   TEXT,                           -- 父评论或帖子 ID
    link_id     TEXT NOT NULL,                  -- 所属帖子 ID
    is_submitter BOOLEAN DEFAULT FALSE,
    depth       INTEGER DEFAULT 0,
    sentiment_score DECIMAL(4,3),
    collected_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_comments_link ON reddit_comments(link_id);
CREATE INDEX idx_comments_created ON reddit_comments(created_utc);

-- 3. 监控配置表 (search_configs)
CREATE TABLE search_configs (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    keywords    TEXT[] NOT NULL,                -- 关键词规则
    subreddits  TEXT[] NOT NULL,                -- 目标子版块
    exclude_keywords TEXT[],
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 4. 案例表 (cases)
CREATE TABLE cases (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT,
    type        TEXT NOT NULL,                  -- crisis / opportunity / routine
    status      TEXT NOT NULL,                  -- open / in_progress / resolved
    posts       JSONB,                          -- 关联帖子 ID 列表
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- 5. UGC 素材表 (ugc_items)
CREATE TABLE ugc_items (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    author      TEXT,
    source_url  TEXT,
    type        TEXT NOT NULL,                  -- text / image / video / mixed
    tags        TEXT[],
    sentiment   TEXT,                           -- positive / negative / neutral
    engagement  JSONB,                          -- { score, comments, shares }
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

#### 2.4.3 缓存策略

| 缓存键 | 数据源 | TTL | 说明 |
|--------|--------|-----|------|
| `dashboard:overview:{date}` | 聚合查询 | 1h | 首页仪表盘数据 |
| `analytics:sentiment:{subreddit}:{date}` | NLP 结果 | 6h | 情感分析趋势 |
| `search:results:{hash}` | 搜索查询 | 10m | 搜索页结果 |
| `user:config:{userId}` | DB | 30m | 用户个性化配置 |
| `webhook:config` | DB | 5m | Webhook 推送配置 |

---

### 2.5 NLP 处理方案

#### 2.5.1 NLP Pipeline 架构

```
原始文本 (Post / Comment)
         │
         ▼
┌─────────────────┐
│ 预处理          │  - 去除 Markdown / HTML 标签
│ Preprocessor    │  - URL 与 @用户名 占位符替换
└────────┬────────┘  - 大小写统一、去重空格
         │
         ▼
┌─────────────────┐
│ 语言检测        │  - langdetect / fastText
│ Language Detect │  - 非英文文本标记，跳过或翻译后处理
└────────┬────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│              并行分析层 (Thread Pool)             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ 情感分析 │ │ 实体识别 │ │ 关键词   │        │
│  │ Sentiment│ │   NER    │ │ Keywords │        │
│  └──────────┘ └──────────┘ └──────────┘        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ 主题聚类 │ │ 文本摘要 │ │ 质量评分 │        │
│  │  Topic   │ │ Summary  │ │ Quality  │        │
│  └──────────┘ └──────────┘ └──────────┘        │
└──────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ 结果归并        │  - 多维度特征向量
│ Merge & Store   │  - 写入 PostgreSQL + 更新缓存
└─────────────────┘
```

#### 2.5.2 核心 NLP 模型选型

| 任务 | 模型/库 | 性能指标 | 资源占用 |
|------|---------|----------|----------|
| 情感分析 | VADER (NLTK) + 领域词典 | 准确率 ~85%（英文社交媒体） | CPU，轻量 |
| 细粒度情感 | `cardiffnlp/twitter-roberta-base-sentiment-latest` | 3 分类准确率 ~90% | GPU 加速 / CPU 2s/条 |
| 实体识别 | spaCy `en_core_web_md` | NER F1 ~85% | CPU，中等 |
| 关键词提取 | KeyBERT + MMR 多样性 | 召回率 ~80% | CPU，轻量 |
| 主题聚类 | BERTopic (UMAP + HDBSCAN) | 一致性评分 >0.5 | CPU，训练时较重 |
| 文本摘要 | `facebook/bart-large-cnn` (蒸馏版) | ROUGE-L ~40 | GPU 推荐 / CPU 5s/条 |

#### 2.5.3 情感分析实现细节

**与前端数据模型对齐**：

```typescript
// src/types/index.ts 中的情感数据结构
interface SentimentData {
  positive: number;    // 0-100 百分比
  neutral: number;
  negative: number;
  score: number;       // -1 ~ +1 综合得分
}
```

**后端计算逻辑**：

```python
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()
# 加载 Momcozy 领域词典（产品名、竞品名、母婴关键词）
analyzer.lexicon.update({
    'leakproof': 2.0,
    'pump': 0.5,
    'warranty': 1.5,
    'defective': -2.5,
    'leaking': -2.0,
    'medela': 0.0,      # 竞品中性
    'spectra': 0.0,
})

def compute_sentiment(text: str) -> dict:
    scores = analyzer.polarity_scores(text)
    # 映射到前端数据结构
    total = scores['pos'] + scores['neu'] + scores['neg']
    return {
        'positive': round(scores['pos'] / total * 100, 1),
        'neutral': round(scores['neu'] / total * 100, 1),
        'negative': round(scores['neg'] / total * 100, 1),
        'score': round(scores['compound'], 3),  # -1 ~ +1
    }
```

#### 2.5.4 主题聚类与词云

**与前端数据模型对齐**：

```typescript
// src/types/index.ts
interface TopicCluster {
  id: string;
  name: string;
  count: number;
  sentiment: 'positive' | 'neutral' | 'negative';
}

interface WordCloudDatum {
  text: string;
  value: number;  // 词频权重
}
```

**实现方案**：

1. **关键词提取**：使用 KeyBERT 对每条帖子/评论提取 Top-5 关键词
2. **主题聚类**：每周全量数据通过 BERTopic 聚类，生成 `TopicCluster`
3. **词云数据**：按子版块聚合关键词 TF-IDF 权重，输出 `WordCloudDatum[]`
4. **增量更新**：新数据进入时，仅更新聚类中心点，每月全量重新聚类

#### 2.5.5 NLP 任务调度

| 任务 | 触发条件 | 优先级 | 队列 |
|------|----------|--------|------|
| 实时情感分析 | 新帖子/评论入库 | 高 | `nlp:realtime` |
| 主题聚类更新 | 每日 06:00 | 中 | `nlp:daily` |
| 周报洞察生成 | 每周一 07:00 | 中 | `nlp:weekly` |
| 月报深度分析 | 每月 1 日 08:00 | 低 | `nlp:monthly` |
| 模型重训练 | 每季度 | 最低 | `nlp:training` |

---

### 2.6 MECE 原则下的完整架构

#### 2.6.1 架构总览

按 MECE（Mutually Exclusive, Collectively Exhaustive）原则，将整个系统自上而下划分为 **6 个独立层级**，每层职责边界清晰，合起来覆盖舆情工作台全部技术要素。

```
┌──────────────────────────────────────────────────────────────────┐
│  L6: 应用层 (Application Layer)                                   │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐    │
│  │  Web 前端  │ │  管理后台  │ │  导出服务  │ │  Webhook   │    │
│  │ (Vite+React│ │  (Dashboard│ │ (CSV/PDF/  │ │  推送      │    │
│  │  +TS)      │ │  /Settings)│ │  Word)     │ │            │    │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘    │
├──────────────────────────────────────────────────────────────────┤
│  L5: 服务层 (Service Layer)                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ REST API │ │ 认证授权 │ │ 报表引擎 │ │ 通知中心 │           │
│  │ (Express)│ │ (JWT+RBAC│ │ (reportE │ │ (Webhook/│           │
│  │          │ │ )        │ │ ngine.ts)│ │  Ding/    │           │
│  └──────────┘ └──────────┘ └──────────┘ │  Feishu) │           │
│                                         └──────────┘           │
├──────────────────────────────────────────────────────────────────┤
│  L4: 处理层 (Processing Layer)                                    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ NLP Pipeline │ │ 数据清洗     │ │ 聚合计算     │            │
│  │ (情感/主题/  │ │ (去重/脱敏/  │ │ (日报/周报/  │            │
│  │  关键词/NER) │ │  标准化)     │ │  月报)       │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
├──────────────────────────────────────────────────────────────────┤
│  L3: 存储层 (Storage Layer)                                       │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │
│  │PostgreSQL│ │MongoDB │ │ Redis  │ │Meilisea│ │腾讯云COS│       │
│  │ 热数据  │ │ 原始档 │ │ 缓存队列│ │ 搜索索引│ │ 冷存储  │       │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘       │
├──────────────────────────────────────────────────────────────────┤
│  L2: 采集层 (Collection Layer)                                    │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                   │
│  │ Reddit API │ │ Pushshift  │ │ 定时调度   │                   │
│  │ (PRAW)     │ │ 回溯 API   │ │ (node-cron │                   │
│  │            │ │            │ │  /Bull)    │                   │
│  └────────────┘ └────────────┘ └────────────┘                   │
├──────────────────────────────────────────────────────────────────┤
│  L1: 基础设施层 (Infrastructure Layer)                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ 轻量服务器│ │ 网络代理 │ │ 监控告警 │ │ 备份恢复 │           │
│  │ (新加坡) │ │ (IP轮换) │ │ (Sentry/ │ │ (快照/   │           │
│  │          │ │          │ │  云监控) │ │  COS)    │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└──────────────────────────────────────────────────────────────────┘
```

#### 2.6.2 各层职责与边界

| 层级 | 职责定义 | 不包含（边界） |
|------|----------|----------------|
| **L6 应用层** | 用户交互界面、文件导出、第三方推送 | 不直接访问数据库，通过 L5 API 通信 |
| **L5 服务层** | 业务逻辑编排、权限校验、API 路由 | 不包含 NLP 算法实现，调用 L4 |
| **L4 处理层** | 数据清洗、NLP 分析、报表生成 | 不包含数据持久化，输出给 L3 |
| **L3 存储层** | 数据持久化、缓存、索引、对象存储 | 不包含业务逻辑，纯数据操作 |
| **L2 采集层** | Reddit 数据抓取、任务调度、增量管理 | 不包含数据清洗，原始输出 |
| **L1 基础设施层** | 服务器、网络、安全、监控、灾备 | 不包含业务代码 |

#### 2.6.3 数据流全景（MECE 验证）

**路径一：实时监控流（高频）**

```
L2 PRAW 采集 → L4 实时清洗 → L3 PostgreSQL 写入
                                    ↓
L5 API 读取 ← L3 Redis 缓存 ← NLP 实时分析
      ↓
L6 前端仪表盘（Zustand Store 订阅）
```

**路径二：报告生成流（定时触发）**

```
L2 定时任务触发 → L4 聚合计算 + 洞察生成 → L3 PostgreSQL 报表表
                                              ↓
L5 报表引擎组装 → L6 前端展示 / 导出文件 → L3 COS 存储
```

**路径三：用户交互流（按需）**

```
L6 搜索/筛选 → L5 API 鉴权 → L3 Meilisearch + PostgreSQL 查询 → L6 结果展示
```

**路径四：告警推送流（事件驱动）**

```
L4 情感/关键词监控 → L5 通知中心匹配规则 → L3 写入消息队列
                                              ↓
L6 Webhook 配置 ← L5 调用钉钉/飞书 API ← 队列消费
```

#### 2.6.4 关键技术决策记录 (ADR)

| 决策点 | 选项 A | 选项 B | 决策 | 理由 |
|--------|--------|--------|------|------|
| 后端语言 | Node.js | Python | **Node.js** | 与前端 TypeScript 生态统一，NLP 通过 Python 子进程调用 |
| 关系数据库 | PostgreSQL | MySQL | **PostgreSQL** | JSONB 支持半结构化数据，全文检索插件成熟 |
| 搜索引擎 | Meilisearch | Elasticsearch | **Meilisearch** | 轻量、部署简单、对中小数据量足够 |
| 消息队列 | Redis Streams | RabbitMQ | **Redis Streams** | 减少中间件依赖，运维简单 |
| 部署方式 | Docker Compose | PM2 直接部署 | **PM2 直接部署** | 轻量服务器资源有限，单节点部署足够 |
| 情感模型 | VADER | BERT 微调 | **VADER + 词典** | 初版快速上线，后续迭代至 BERT |
| 前端状态管理 | Zustand | Redux Toolkit | **Zustand** | 轻量、无样板代码、TypeScript 友好 |

#### 2.6.5 扩展路径

| 阶段 | 触发条件 | 扩展动作 |
|------|----------|----------|
| **V1.1** | 日活 > 1000 | 增加服务器配置至 8C16G，Redis 独立部署 |
| **V1.2** | 监控 subreddit > 20 | 引入多实例爬虫，Redis Streams 升级至 RabbitMQ |
| **V2.0** | 数据量 > 1000 万条 | PostgreSQL 读写分离，引入 ClickHouse 做 OLAP 分析 |
| **V2.1** | NLP 延迟 > 5s/条 | 引入 GPU 实例或腾讯云 TI 推理加速 |
| **V3.0** | 多品牌需求 | 数据库按品牌分 schema，前端支持多租户切换 |

---

## 第三部分：尚需完成的工作（Codex 接手清单）

以下工作按优先级排序，供后端/数据团队接入时参考。每一项均标注前端影响范围、后端依赖和数据来源。

### P0 — 阻塞级（必须先完成，否则前端无法运行）

| 序号 | 任务 | 前端影响 | 后端依赖 | 数据来源 | 预估工时 |
|------|------|----------|----------|----------|----------|
| 1 | **Reddit API 采集器** | 全部页面 | Node.js + PRAW / Pushshift | Reddit API / Pushshift | 3-5 天 |
| 2 | **帖子/评论数据持久化** | 全部页面 | PostgreSQL + 表结构设计 | Codex 项目目录中的 Reddit 原始数据 | 2-3 天 |
| 3 | **REST API 基础框架** | 全部页面 | Express + 路由 + 错误处理 | — | 2-3 天 |
| 4 | **前端 API 客户端对接** | 全部页面 | `src/services/*.ts` 实现 Real 版本 | 后端 API | 1-2 天 |

**说明**：
- Reddit 原始数据位于 Codex 项目目录（`/Users/pray/project/Reddit_VOC/`），需先读取并导入 PostgreSQL
- 帖子表必须包含 `id`, `title`, `selftext`, `author`, `subreddit`, `permalink`, `score`, `upvote_ratio`, `num_comments`, `created_utc` 字段
- 评论表需支持 `parent_id` 递归查询，构建评论树
- API 返回格式需与前端 `src/types/index.ts` 中的 `RedditPost`, `RedditComment` 类型完全一致
- 前端 Service 层已定义 Mock/Real 切换接口，后端只需实现 `src/services/` 中的接口即可

---

### P1 — 核心功能（完成后产品可用）

| 序号 | 任务 | 前端影响 | 后端依赖 | 数据来源 | 预估工时 |
|------|------|----------|----------|----------|----------|
| 5 | **NLP 情感分析服务** | Dashboard, Analytics, Insights | Python + VADER / BERT | 帖子/评论文本 | 3-5 天 |
| 6 | **NLP 意图分类服务** | Dashboard, Search, UGC | Python + 分类模型 / 规则引擎 | 帖子/评论文本 | 2-3 天 |
| 7 | **日报/周报/月报聚合引擎** | Dashboard | PostgreSQL + 定时任务 | NLP 结果 + 原始数据 | 3-4 天 |
| 8 | **话题聚类与关键词提取** | Analytics, Insights | Python + BERTopic / KeyBERT | 全量帖子文本 | 3-4 天 |
| 9 | **搜索 API（帖子检索）** | Search | PostgreSQL + Meilisearch | 帖子 + 评论索引 | 2-3 天 |
| 10 | **UGC 自动归档规则引擎** | UGCShowcase | 规则引擎 + 定时任务 | NLP 结果（positive + UGC intent） | 2-3 天 |
| 11 | **通知生成与推送服务** | Messages | 规则引擎 + Webhook 调用 | NLP 结果 + 阈值判断 | 2-3 天 |
| 12 | **Zustand Store 后端同步** | Dashboard, Messages, Settings | REST API + WebSocket | 用户配置 + 实时通知 | 2-3 天 |

**说明**：
- 情感分析输出必须包含 `positive` / `neutral` / `negative` 三分类，且概率和为 100%
- 意图分类支持 6 类：`Purchase Intent`, `UGC`, `Bug Report`, `Comparison`, `Question`, `General`
- 报告聚合需实现与 `reportEngine.ts` 相同的跨周期数据联动逻辑（非线性关系）
- 搜索需支持 `subreddit`, `keywords`, `sentiment`, `intent`, `timeRange`, `minUpvotes` 组合筛选
- 竞品品牌支持动态配置（当前 9 个：Elvie, Spectra, Willow, Medela, Lansinoh, Haakaa, BabyBuddha, Freemie, BellaBaby）

---

### P2 — 增强功能（提升产品价值）

| 序号 | 任务 | 前端影响 | 后端依赖 | 数据来源 | 预估工时 |
|------|------|----------|----------|----------|----------|
| 13 | **竞品数据采集** | Dashboard, Analytics, Insights | 竞品关键词匹配 | Reddit API（竞品提及） | 2-3 天 |
| 14 | **子版块画像生成** | Analytics | 社区统计聚合 | 帖子 + 评论 + 社区元数据 | 2-3 天 |
| 15 | **影响者识别（KOL）** | Analytics | 用户 karma / 发帖量 / 互动率统计 | Reddit 用户 API | 2-3 天 |
| 16 | **受众画像分析** | Analytics | 用户 demographics 推断 | 帖子内容 + 社区属性 | 3-4 天 |
| 17 | **案例广场自动检索** | CaseGallery | 定时爬虫 / RSS 聚合 | 微信公众号、知乎、播客等 | 2-3 天 |
| 18 | **数据导出后端生成** | ExportButton | Puppeteer / 后端模板渲染 | 报表数据 | 2-3 天 |
| 19 | **用户认证与权限** | 全部页面 | JWT + RBAC | — | 2-3 天 |
| 20 | **数据缓存与性能优化** | 全部页面 | Redis + 查询优化 | 聚合结果 | 2-3 天 |

---

### P3 — 优化与扩展（长期价值）

| 序号 | 任务 | 前端影响 | 后端依赖 | 数据来源 | 预估工时 |
|------|------|----------|----------|----------|----------|
| 21 | **NLP 模型迭代（BERT 微调）** | 全部页面 | GPU 训练环境 | 标注数据集 | 5-7 天 |
| 22 | **实时 WebSocket 推送** | Dashboard, Messages | Socket.io / WebSocket | 新帖/评论流 | 2-3 天 |
| 23 | **多语言支持（中文社区）** | 全部页面 | 多语言 NLP 模型 | 小红书/微博等 | 3-5 天 |
| 24 | **AI 智能回复建议** | Messages | LLM API（OpenAI/Claude） | 帖子内容 + 品牌知识库 | 3-4 天 |
| 25 | **数据可视化增强** | Dashboard, Analytics | 聚合查询优化 | 时序数据 | 2-3 天 |
| 26 | **移动端适配** | 全部页面 | 无后端依赖 | — | 3-5 天 |

---

### 前端已完成（无需后端配合）

| 序号 | 任务 | 说明 | 状态 |
|------|------|------|------|
| 1 | 路由懒加载 | 主包已从 2,213KB 降至 114KB（gzip 25KB） | ✅ 完成 |
| 2 | 虚拟滚动 | Messages / UGC / Search 大列表已支持分页 | ✅ 完成 |
| 3 | 错误边界 | 基础 ErrorBoundary 已覆盖 | ✅ 完成 |
| 4 | 加载状态 | Skeleton 屏覆盖 Dashboard 和 Insights | ✅ 部分完成 |
| 5 | 单元测试 | 57 个测试全部通过，覆盖 stores 和 utils | ✅ 完成 |
| 6 | 设计系统 | 完整 Tailwind 设计令牌、硬编码颜色已清理 | ✅ 完成 |
| 7 | Service 层 | 5 个 Service 文件，Mock/Real 切换接口就绪 | ✅ 完成 |
| 8 | Zustand Store | 3 个 Store，Dashboard/Messages/Competitor 已接入 | ✅ 完成 |

---

## 附录

### A. 目标社区清单

| 社区名称 | 订阅数 | 优先级 | 说明 |
|----------|--------|--------|------|
| r/breastfeeding | 185,000 | P0 | 核心目标社区，高活跃度 |
| r/babybumps | 720,000 | P0 | 新手妈妈聚集，转化潜力高 |
| r/NewParents | 145,000 | P1 | 新手父母社区，内容教育机会 |
| r/breastpumps | 8,500 | P1 | 垂直品类社区，高转化率 |
| r/Mommit | 210,000 | P2 | 妈妈经验分享社区 |
| r/pregnant | 420,000 | P2 | 孕期社区，品牌教育机会 |

### B. 品牌关键词（监控词）

| 类型 | 关键词示例 | 说明 |
|------|------------|------|
| 品牌词 | Momcozy | 主品牌名 |
| 产品词 | M5, M6, S12, V2 | 具体型号 |
| 竞品词 | Elvie, Spectra, Willow, Medela, Lansinoh, Haakaa, BabyBuddha, Freemie, BellaBaby | 9 个竞品（可配置） |
| 通用词 | breast pump, wearable pump, 静音, 便携 | 品类词 |

### C. 竞品品牌（当前配置 9 个）

Elvie, Spectra, Willow, Medela, Lansinoh, Haakaa, BabyBuddha, Freemie, BellaBaby

### D. 前端项目结构速览

```
momcozy-reddit-workbench/
├── src/
│   ├── components/          # 可复用组件（图表、卡片、面板等）
│   ├── components/charts/   # 图表组件库（15+ 图表类型）
│   ├── components/insights/ # 洞察四维度面板组件
│   ├── data/                # Mock 数据文件（10 个文件，后端替换目标）
│   ├── hooks/               # 自定义 Hooks（分页、搜索、Webhook、轮询等）
│   ├── pages/               # 页面组件（Home、Dashboard、Analytics 等）
│   ├── services/            # Service 层（Mock/Real 切换接口）
│   ├── stores/              # Zustand Store（Report + Notification + Competitor）
│   ├── types/               # TypeScript 类型定义（后端 API 需对齐）
│   ├── utils/               # 工具函数（日期、存储、钉钉签名等）
│   ├── constants/           # 常量（colors.ts 设计令牌）
│   ├── App.tsx              # 路由配置
│   └── main.tsx             # 应用入口
├── public/                  # 静态资源
├── tests/                   # 测试文件（57 个测试）
└── package.json             # 依赖（Vite 5 + React 19 + Zustand 5）
```

### E. 快速启动命令

```bash
# 开发模式
cd /Users/pray/project/Reddit_VOC/ref/UI/momcozy-reddit-workbench
npm run dev

# 构建
npm run build

# 测试
npm run test

# 代码检查
npm run lint
```

---

> **文档版本**：v2.0（重构后）
> **编写完成于**：2026-07-13
> **编写者**：AI Agent（前端工程方向）
> **接收者**：Codex / 后端开发团队 / 数据工程团队
> **Reddit 原始数据位置**：`/Users/pray/project/Reddit_VOC/`（Codex 项目目录）
> **下一步**：请后端团队按 P0 → P1 → P2 顺序逐项接入，前端团队配合 API 对接测试。前端 Service 层接口已就绪，后端只需实现对应接口即可无缝切换。
