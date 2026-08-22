# Momcozy & Reddit 舆情工作台 — 对抗性审计报告

**审计维度**：数据模型与字段完整性（Reddit帖子/评论数据字段 vs 产品功能需求）  
**审计日期**：2026-07-11  
**审计范围**：`momcozy-reddit-workbench/src/` 全部 TypeScript 类型定义 + Mock 数据 + 组件 Props  
**参考文档**：
- PRD_v2.md（产品需求文档）
- Reddit Pulse 产品设计文档（为什么我会做一个 Reddit 品牌舆情分析工具）
- 大疆 Reddit 舆情监控工作流文档（20万工作流方案）
- Reddit API (PRAW) 官方数据模型规范

---

## 执行摘要

本次审计在 **282 行类型定义**、**13 个 Mock 数据文件**、**20+ 个组件** 中识别出 **25 项数据模型缺陷**。其中 **Critical 级 6 项**，**High 级 7 项**，**Medium 级 7 项**，**Low 级 5 项。核心问题集中在：与 Reddit 原始数据结构严重脱节、无法支撑真实舆情工作流的闭环、关键业务字段缺失导致数据血缘不可追溯。**

---

## 严重缺陷（Critical）— 6 项

### CR-001: 缺少 Reddit 原始帖子/评论 ID 与 Permalink 字段

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: SearchResult`, `data/dailyReportMock.ts: DailyNewPost`, `data/insightsMock.ts: HotPostAnalysis` |
| **问题** | 所有帖子数据模型均缺少 `redditPostId`（如 `t3_abc123`）和 `permalink`（如 `/r/breastfeeding/comments/xxx/...`）字段。 |
| **影响** | PostDetailDrawer 的「在 Reddit 中打开」按钮 (`href="#"`) 是死链接；Webhook 推送的飞书/钉钉消息无法直接跳转到原始帖子；用户无法验证数据来源。 |
| **业务依据** | 大疆工作流文档明确要求：「Reddit 链接：\[点击查看原帖\]」是飞书卡片的必含字段。 |
| **修复建议** | 在 `SearchResult` / `DailyNewPost` / `HotPostAnalysis` 中增加 `redditId: string` 和 `permalink: string` 字段，并确保所有 Mock 数据和 API 层映射该字段。 |

### CR-002: 评论（Comment）数据模型完全缺失

| 项目 | 内容 |
|------|------|
| **位置** | 全局缺失（`types/index.ts` 无 `Comment` 类型） |
| **问题** | 整个系统没有任何 `Comment` 接口定义。PostDetailDrawer 中的评论区域硬编码了 `mockComments` 数组，但无类型、无数据层、无 API 接口。 |
| **影响** | 无法展示评论情感分析（大疆文档的核心需求："看评论"）；无法识别评论区的口碑裂变和负面附和；无法追踪子评论的争议发展。 |
| **业务依据** | Reddit Pulse 文档强调："不是抓得越多越好，而是先尽量抓得准"——而评论是 Reddit 讨论的核心载体。大疆文档中「评论区已有用户附和」是负面舆情升级的关键信号。 |
| **修复建议** | 新增 `Comment` 接口：`id`, `redditId`, `body`, `author`, `score`, `createdAt`, `parentId` (用于 threading), `sentiment`, `sentimentConfidence`, `isEdited`。 |

### CR-003: 时间戳格式完全不兼容标准时间格式

| 项目 | 内容 |
|------|------|
| **位置** | 所有 Mock 数据文件（`dailyReportMock.ts`, `insightsMock.ts`, `messagesMock.ts` 等） |
| **问题** | 所有时间字段使用相对中文字符串：`'2小时前'`、`'3小时前'`、`'1天前'`。没有任何字段存储 Unix timestamp 或 ISO 8601 格式。 |
| **影响** | 无法按精确时间排序、筛选、聚合；无法计算「过去6小时内upvotes超过50」这类大疆工作流中的核心规则；时间序列图表（AreaChart/LineChart）的 X 轴数据本质上是字符串，无法正确处理跨时区。 |
| **业务依据** | PRD 2.1 层要求「品牌提及趋势」用时间序列分析；大疆工作流要求「黄金1小时」响应。 |
| **修复建议** | 所有时间字段统一改为 `createdAt: string` (ISO 8601) 或 `createdAt: number` (Unix timestamp)，前端用 `Intl.RelativeTimeFormat` 渲染相对时间。 |

### CR-004: 缺少 Reddit 原生评分（Score）与 Upvote Ratio 字段

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: SearchResult`, `data/dailyReportMock.ts: DailyNewPost` |
| **问题** | 模型只有 `upvotes: number` 和 `comments: number`，缺少 `score` (Reddit 的 score = upvotes - downvotes) 和 `upvoteRatio` (upvotes / total_votes)。 |
| **影响** | 无法识别「高 upvote 但低 ratio」的争议性帖子（这类帖子往往是负面舆情高风险）；无法准确计算真实用户反馈强度。 |
| **业务依据** | 大疆文档中的「负面帖子 upvotes 快速上升」规则需要区分真实的点赞 vs 争议性互动。 |
| **修复建议** | 增加 `score: number` 和 `upvoteRatio: number`（0~1）。 |

### CR-005: 作者画像字段完全缺失（Karma / 账户年龄 / 活跃度）

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: SearchResult` / `PostCardProps` |
| **问题** | 作者只有 `author: string`（用户名），没有 Karma 分布、账户创建时间、历史发帖 subreddit 等字段。 |
| **影响** | 无法识别 KOL vs 水军 vs 新注册小号（小号发负面帖是常见攻击手段）；无法支撑 InfluencerIdentification 模块的真实性校验。 |
| **业务依据** | 大疆工作流文档中的「飞书卡片：@对应负责人」依赖于判断用户可信度和影响力。 |
| **修复建议** | 新增 `authorKarma: number`, `authorAccountAge: number` (days), `authorTopSubreddits: string[]` 字段。 |

### CR-006: 帖子完整内容（selftext/body）字段缺失或命名不一致

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: SearchResult`（有 `content`），`data/dailyReportMock.ts: DailyNewPost`（无内容字段） |
| **问题** | `DailyNewPost` 没有 `content` 或 `body` 字段；`SearchResult` 有 `content` 但类型为 `string`，没有长度限制或截断标记。PostDetailDrawer 的「内容摘要」区域用模板字符串拼接，不展示真实内容。 |
| **影响** | 用户无法在详情抽屉中阅读帖子原文；AI 情感分析和意图分析无法基于完整内容执行（大疆工作流的核心：分析标题和**内容**）。 |
| **业务依据** | 大疆文档中的 AI 提示词明确要求：「请分析以下 Reddit 帖子的**标题和内容**」。 |
| **修复建议** | `DailyNewPost` 增加 `body: string` 字段；增加 `isBodyTruncated: boolean` 和 `bodyLength: number` 标记。 |

---

## 高优先级缺陷（High）— 7 项

### HI-001: 意图（Intent）分类与大疆工作流文档完全不匹配

| 项目 | 内容 |
|------|------|
| **位置** | `data/dailyReportMock.ts: DailyNewPost['intent']` |
| **当前值** | `'Purchase Intent' \| 'UGC' \| 'Bug Report' \| 'Comparison' \| 'Question' \| 'General'` |
| **大疆文档要求** | `Bug Report`, `Customer Service Issue`, `Feature Request`, `Positive Showcase`, `Newbie Question`, `Competitor Comparison` |
| **影响** | 大疆工作流中的「数据分流」规则（Switch 节点）完全无法映射：`Customer Service Issue` → 紧急警报 的规则无法执行；`Feature Request` → PM 关注的规则无法执行。 |
| **修复建议** | 统一采用大疆工作流的 6 类意图，并在 UI 中增加 `Customer Service Issue` 和 `Feature Request` 的显示和筛选支持。 |

### HI-002: 情感分析缺少置信度分数与多维度情感

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: SearchResult`, `data/dailyReportMock.ts` |
| **问题** | 情感只有 `'positive' \| 'neutral' \| 'negative'` 三档枚举，没有 `sentimentConfidence: number`（0~1），没有细粒度情感（愤怒、失望、兴奋、感激）。 |
| **影响** | 无法判断「中性但高置信度」与「负面但低置信度」的优先级差异；无法识别大疆文档中的「强烈负面」vs「中性求助」。 |
| **业务依据** | 大疆文档明确示例：「'Gimbal issue on a brand new Mini 4 Pro, ridiculous!' 是强烈负面」——需要区分强度。 |
| **修复建议** | 增加 `sentimentScore: number`（-1~1，如 VADER 的 compound score）、`sentimentConfidence: number`、`emotions: ('anger' \| 'disappointment' \| 'gratitude' \| 'excitement')[]`。 |

### HI-003: 帖子元数据字段缺失（编辑状态、置顶、标签、NSFW）

| 项目 | 内容 |
|------|------|
| **位置** | 所有帖子相关接口 |
| **缺失字段** | `isEdited: boolean`（帖子是否被编辑，编辑后内容可能改变舆情判断）、`isStickied: boolean`（置顶帖的讨论权重不同）、`linkFlairText: string`（用户自分类标签，如 "Help"、"Review"）、`over18: boolean`（NSFW 内容需过滤）。 |
| **影响** | 无法识别「编辑后反转情感」的帖子；无法过滤不适当内容；无法利用用户自分类标签进行意图预筛。 |
| **修复建议** | 在 `SearchResult` 和 `DailyNewPost` 中增加上述字段。 |

### HI-004: 搜索配置缺少 Reddit 原生高级搜索语法支持

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: SearchConfig` |
| **问题** | `SearchConfig` 只有 `keywords: string[]` 和 `subreddits: string[]`，无法表达 Reddit 的高级搜索语法。 |
| **影响** | 大疆文档中的核心搜索语法 `(DJI OR 大疆 OR Mavic OR Air OR Mini)` 和 `self:yes` 无法在系统中配置。 |
| **业务依据** | 大疆文档明确：「在 n8n 中，你可以使用 Reddit 的高级搜索语法」。 |
| **修复建议** | 增加 `searchQuery: string`（原生搜索语法）和 `searchSyntax: 'lucene' \| 'plain'` 字段。 |

### HI-005: 子版块（Subreddit）数据模型缺少 Reddit 原生关键字段

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: SubredditMetric` / `data/analyticsMock.ts: SubredditProfile` |
| **缺失字段** | `subredditType: string`（public/restricted/private，影响可抓取性）、`activeUserCount: number`（当前活跃用户，比 subscribers 更能反映社区热度）、`description: string`（社区描述，用于 AI 理解社区气质）、`createdUtc: number`（社区创建时间，判断社区成熟度）。 |
| **影响** | `SubredditProfile` 的 `vibe` 和 `quality` 字段是人工硬编码的，无法自动从真实数据推导；无法识别 restricted 社区（需要特殊权限才能抓取）。 |
| **修复建议** | 在 `SubredditProfile` 中补充上述字段，并保留 `vibe` 和 `quality` 作为 AI 分析后的增强字段。 |

### HI-006: 通知规则阈值字段不可解析（字符串陷阱）

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: NotificationRule.threshold: string` |
| **问题** | `threshold` 存储为自然语言字符串，如 `"upvotes > 50 in 6h"`、`"intentScore ≥ 80"`。没有结构化字段。 |
| **影响** | 前端无法基于这些规则执行本地筛选；后端无法直接解析执行；规则引擎需要额外的 NLP 解析层。 |
| **修复建议** | 改为结构化：`threshold: { field: 'upvotes', operator: 'gt', value: 50, timeWindow: '6h' }` 或引入 `NotificationCondition[]`。 |

### HI-007: 竞品数据模型缺少「监控关键词」字段（PRD 需求未落地）

| 项目 | 内容 |
|------|------|
| **位置** | `hooks/useCompetitorConfig.ts: CompetitorBrand` |
| **问题** | PRD 5.3 明确要求竞品配置支持「品牌关键词」，但 `CompetitorBrand` 只有 `id, name, color, enabled`。 |
| **影响** | 无法为大疆案例中的每个竞品配置不同的关键词组（如 Elvie 配 "Elvie OR Elvie Pump"）；竞品声量计算只能基于品牌名精确匹配。 |
| **修复建议** | 增加 `keywords: string[]` 和 `searchQuery: string` 字段。 |

---

## 中优先级缺陷（Medium）— 7 项

### ME-001: 数据血缘与来源追踪字段缺失

| 项目 | 内容 |
|------|------|
| **位置** | 所有数据接口 |
| **问题** | 没有任何字段记录数据的来源（PRAW API？第三方爬虫？手动导入？）、抓取时间、处理时间。 |
| **影响** | 无法调试数据延迟问题；无法判断数据新鲜度；无法审计数据质量。 |
| **修复建议** | 在核心数据接口上增加 `source: 'reddit_api' \| 'webhook' \| 'manual'`, `crawledAt: string`, `processedAt: string`。 |

### ME-002: 报告引擎的数据放大逻辑无依据（乘以倍数）

| 项目 | 内容 |
|------|------|
| **位置** | `data/reportEngine.ts: scaleOverview`, `scaleAlerts`, `scaleNewPosts` |
| **问题** | 周报/月报数据通过简单乘以 7 或 30 从日报推导，没有聚合真实数据。`scaleAlerts` 甚至将 `upvotes` 和 `comments` 也乘以倍数——这在业务上毫无意义（一个帖子的 upvotes 不会随时间线性增长）。 |
| **影响** | 周报/月报的统计数据严重失真，不具备决策参考价值。 |
| **修复建议** | 报告引擎应聚合真实时间窗口的数据，而不是线性放大。 |

### ME-003: 帖子详情抽屉的 URL 是死链，但类型系统未约束

| 项目 | 内容 |
|------|------|
| **位置** | `components/PostDetailDrawer.tsx: href="#"` |
| **问题** | 外部链接按钮使用 `href="#"`，但 TypeScript 编译器不报错，因为 `DailyNewPost` 没有 `url` 或 `permalink` 字段。 |
| **影响** | 用户体验断层，但类型系统无法捕获。 |
| **修复建议** | 在 `DailyNewPost` 中强制要求 `permalink: string`，并在组件中消费。 |

### ME-004: 词云数据缺少情感置信度与词频来源追踪

| 项目 | 内容 |
|------|------|
| **位置** | `data/analyticsMock.ts: WordCloudDatum` / `data/enhancedWordCloudMock.ts` |
| **问题** | 词云数据只有 `text` 和 `value`，没有 `sourcePostIds` 或 `sentimentConfidence`。 |
| **影响** | 点击词云词汇时无法高亮真实的来源帖子（PRD 5.1 要求：「点击词云词汇 → 高亮包含该词的热帖」）。 |
| **修复建议** | 增加 `sourcePostIds: string[]` 和 `sentimentConfidence: number`。 |

### ME-005: 桑基图数据是静态 Mock，无法与真实数据对接

| 项目 | 内容 |
|------|------|
| **位置** | `data/analyticsMock.ts: sankeyNodes/sankeyLinks`, `data/topicFlowMock.ts: topicFlowNodes/topicFlowLinks` |
| **问题** | 桑基图的三层结构（社区→话题→情感）是静态硬编码的，没有从真实帖子数据中自动聚合的接口。 |
| **影响** | 当新增 subreddit 或话题时，桑基图数据不会自动更新。 |
| **修复建议** | 定义聚合接口：`function aggregateSankey(posts: Post[], timeRange: TimeRange): { nodes, links }`。 |

### ME-006: 用户画像数据完全虚构，没有 Reddit 侧映射

| 项目 | 内容 |
|------|------|
| **位置** | `data/audienceMock.ts: PersonaSegment` |
| **问题** | `avgAge: '28-32'`、`avgPostsPerWeek: 4.2` 等数据是纯粹虚构的，没有与 Reddit 用户数据的任何映射字段。 |
| **影响** | 管理层基于这些「虚构数据」做出的决策没有数据支撑。 |
| **修复建议** | 增加数据来源标记：`dataSource: 'mock' \| 'inferred'`，并设计从 Reddit 用户活跃数据推导画像的方案。 |

### ME-007: 影响者数据缺少 Reddit 原生验证字段

| 项目 | 内容 |
|------|------|
| **位置** | `data/influencerMock.ts: InfluencerData` |
| **问题** | `isVerified` 是布尔值，但 Reddit 的验证是「 trophies + 用户 self-description」，没有 `trophies` 或 `verifiedEmail` 字段。 |
| **影响** | 无法区分 Reddit 官方认证用户（如 subreddit mod 的 moderator badge）与普通用户。 |
| **修复建议** | 增加 `trophies: string[]`, `isModerator: boolean`, `moderatedSubreddits: string[]`。 |

---

## 低优先级缺陷（Low）— 5 项

### LO-001: 类型定义重复，维护成本高

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: NotificationItem` vs `data/messagesMock.ts: Notification`；`types/index.ts: TopicCluster` vs `data/analyticsMock.ts: TopicCluster` |
| **问题** | 同一概念在多个文件中重复定义，字段名略有差异（如 `read` vs `read: boolean`）。 |
| **影响** | 修改一处需要同步修改多处，容易遗漏。 |
| **修复建议** | 统一引用 `types/index.ts` 中的定义，Mock 数据直接使用 `import type`。 |

### LO-002: 缺少 Awards/Gilded 数据（Reddit 内容质量指标）

| 项目 | 内容 |
|------|------|
| **位置** | 所有帖子接口 |
| **问题** | Reddit 的 `total_awards_received` 是衡量内容质量和社区认可的重要指标，但系统中完全缺失。 |
| **影响** | 无法区分「高 upvotes 但无 awards」的灌水帖和「高 upvotes 且高 awards」的精品内容。 |
| **修复建议** | 增加 `totalAwards: number`, `awardNames: string[]`（如 "Gold", "Platinum"）。 |

### LO-003: 帖子缺少「是否自发布」与媒体类型字段

| 项目 | 内容 |
|------|------|
| **位置** | 所有帖子接口 |
| **问题** | 缺少 `isSelf: boolean`（selftext vs 外链）和 `mediaType: 'text' \| 'image' \| 'video' \| 'link'`。 |
| **影响** | 无法针对图片/视频帖进行视觉舆情分析（如产品开箱图、故障视频）。 |
| **修复建议** | 增加 `isSelf` 和 `mediaType` 字段。 |

### LO-004: 搜索结果的 `intentScore` 无定义范围

| 项目 | 内容 |
|------|------|
| **位置** | `types/index.ts: SearchResult.intentScore: number` |
| **问题** | `intentScore` 是 `number` 类型，但没有说明范围（0-100？0-1？），Mock 数据中出现 92、45 等值。 |
| **影响** | 规则引擎无法统一阈值判断。 |
| **修复建议** | 明确为 `intentScore: number`（0-100），并在文档中说明计算方式（如基于关键词匹配 + 情感强度）。 |

### LO-005: 案例广场的 URL 缺少安全校验字段

| 项目 | 内容 |
|------|------|
| **位置** | `data/casesMock.ts: CaseItem.url` |
| **问题** | `url` 字段是纯字符串，没有 `isExternal: boolean`、安全校验状态或 `verifiedAt` 字段。 |
| **影响** | 无法防止 XSS 或钓鱼链接；无法标记链接失效。 |
| **修复建议** | 增加 `isExternal: boolean`（默认 true）、`lastVerifiedAt: string`、渲染时做 URL 协议校验。 |

---

## 审计结论与建议优先级

### 修复路线图（推荐）

| 阶段 | 时间 | 修复范围 | 目标 |
|------|------|----------|------|
| **Phase 1: 数据基础设施** | 1-2 天 | CR-001, CR-002, CR-003, CR-006, HI-001, HI-002 | 建立与 Reddit API 的数据桥梁，支撑真实数据接入 |
| **Phase 2: 分析能力补齐** | 2-3 天 | CR-004, CR-005, HI-003, HI-004, HI-005, HI-006 | 支撑大疆工作流中的意图分流、情感强度、高级搜索 |
| **Phase 3: 产品功能完善** | 2-3 天 | HI-007, ME-001, ME-002, ME-003, ME-004, ME-005 | 使周报/月报、词云联动、桑基图可基于真实数据运行 |
| **Phase 4: 质量提升** | 1-2 天 | ME-006, ME-007, LO-001~LO-005 | 提升数据可信度、减少维护成本 |

### 一句话总结

**当前代码是一个设计精良的 UI 原型（Frontend Prototype），但不是一个数据驱动的舆情分析系统（Data-Driven VOC System）。数据模型与 Reddit 原生结构之间存在 6 项 Critical 级断层，这意味着即使后端完成了 Reddit API 接入，前端也无法直接消费真实数据而不进行大规模重构。**

---

*审计人：资深产品经理 & 系统架构师*  
*审计方法论：对比 Reddit PRAW API 规范 + 大疆工作流文档 + PRD_v2 需求矩阵 + 代码静态分析*
