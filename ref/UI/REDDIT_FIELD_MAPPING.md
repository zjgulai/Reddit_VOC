# Reddit 字段映射文档

> **版本**: v1.0  
> **适用项目**: Momcozy Reddit VOC Workbench  
> **技术栈**: Vite + React 18 + TypeScript + Tailwind CSS + Recharts  
> **关联文件**: `src/types/index.ts`, `src/lib/api.ts`, `src/data/*Mock.ts`

---

## 1. 字段来源分类说明

| 分类标识 | 全称 | 说明 |
|---------|------|------|
| 🔴 R | Reddit API 原生 | 直接来自 Reddit API（PRAW / Pushshift / Official API）的原始字段 |
| 🟡 N | NLP 后处理 | 经 NLP 管道（情感分析、意图识别、关键词提取）生成的字段 |
| 🟢 D | 后端派生 | 由后端基于原始数据计算、聚合或推导出的字段 |

---

## 2. 各页面字段映射详表

### 2.1 Dashboard（舆情看板）

#### 2.1.1 日报（Daily Report）

| 展示字段 | 数据源字段 | 来源 | 类型 | 说明 |
|---------|-----------|------|------|------|
| 新帖数 | `newPosts` | 🟢 D | `number` | 统计周期内新增帖子数量 |
| 正面率 | `positiveRate` | 🟢 D | `number` | 正面情感帖子占比 (%) |
| 负面率 | `negativeRate` | 🟢 D | `number` | 负面情感帖子占比 (%) |
| 紧急警报 | `alerts` | 🟢 D | `number` | 触发阈值的高风险帖子数 |
| 高意向 | `highIntent` | 🟢 D | `number` | `intentScore >= 80` 的帖子数 |
| UGC | `ugc` | 🟢 D | `number` | `intent === 'UGC'` 的帖子数 |
| 警报等级 | `level` | 🟢 D | `enum` | `critical` / `warning` / `info`，基于情感+增长综合评分 |
| 警报标题 | `title` | 🔴 R | `string` | Reddit 帖子 `title` |
| 社区 | `subreddit` | 🔴 R | `string` | 子版块名称 |
| 点赞 | `upvotes` | 🔴 R | `number` | Reddit `ups`（或 `score`） |
| 评论 | `comments` | 🔴 R | `number` | Reddit `num_comments` |
| 意向分 | `intentScore` | 🟡 N | `number` | NLP 意图识别置信度 0-100 |
| 情感 | `sentiment` | 🟡 N | `enum` | `positive` / `neutral` / `negative` |
| 意图 | `intent` | 🟡 N | `enum` | 6 大意图分类 |
| 时间 | `time` / `createdAt` | 🔴 R | `string` | `created_utc` 格式化后的相对时间 |
| 趋势 | `trend` | 🟢 D | `enum` | `up` / `down` / `stable`，基于近期数据对比 |
| 行动事项 | `type`, `urgency`, `due` | 🟢 D | `enum` | 后端根据规则生成的待办 |
| 品牌综合得分 | `overallScore` | 🟢 D | `number` | 多维度加权计算的品牌健康度 0-100 |
| 情感温度计 | `sentimentLevel` | 🟢 D | `enum` | `calm` / `watch` / `alert` / `crisis` |

#### 2.1.2 周报（Weekly Report）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 趋势指标 | `metric`, `current`, `previous`, `change` | 🟢 D | 周环比统计 |
| 机会洞察标题 | `title` | 🟢 D | 后端聚类分析生成 |
| 影响度 | `impact` | 🟢 D | 基于提及量+情感综合评分 |
| 增长率 | `growth` | 🟢 D | 周环比增长率 |
| 竞品品牌 | `name` | 🔴 R | 帖子中提及的竞品品牌名 |
| 提及量 | `mentions` | 🟢 D | 统计周期内提及次数 |
| 热门话题 | `topTopic` | 🟡 N | NLP 关键词聚类结果 |

#### 2.1.3 月报（Monthly Report）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 品牌健康指标 | `metric`, `current`, `lastMonth`, `change` | 🟢 D | 月环比品牌健康度 |
| 讨论份额 | `share` | 🟢 D | 品牌提及量 / 品类总提及量 |
| 月环比 | `mentionGrowth` | 🟢 D | 提及量月度增长率 |
| 社区 ROI | `roi`, `conversionRate`, `quality` | 🟢 D | 基于线索数+转化率的派生指标 |
| 话题生命周期 | `lifecycle` | 🟢 D | `emerging` / `growing` / `mature` / `declining` |
| 战略建议优先级 | `priority` | 🟢 D | 基于影响面+紧迫性的排序 |

---

### 2.2 Analytics（舆情分析）

#### 2.2.1 统计卡片（Stat Cards）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 总互动量 | `value`（互动量） | 🟢 D | `score + comments` 聚合 |
| 正面率 | `value`（正面率） | 🟢 D | 正面帖子数 / 总帖子数 |
| 关键词数 | `value`（关键词数） | 🟡 N | NLP 提取的唯一关键词数量 |
| 活跃用户数 | `value`（活跃用户数） | 🟢 D | 去重后的 `author` 数量 |
| 变化率 | `change` | 🟢 D | 环比变化百分比 |
| 趋势方向 | `trend` | 🟢 D | `up` / `down` / `neutral` |

#### 2.2.2 情感分析（SentimentAnalysis）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 情感分布饼图 | `positive`, `neutral`, `negative` | 🟡 N | NLP 情感分析结果聚合 |
| 情感得分 | `sentimentScore` | 🟡 N | -1 ~ +1 的连续情感值（可选） |
| 情感趋势时序 | `sentimentOverTime[]` | 🟡 N | 按日期聚合的情感分布 |

#### 2.2.3 话题聚类（TopicCluster）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 话题名称 | `name` | 🟡 N | NLP 主题建模（LDA/BERTopic）结果 |
| 话题规模 | `size` | 🟢 D | 归属该话题的帖子数 |
| 关键词 | `keywords[]` | 🟡 N | 话题代表性关键词 |
| 话题情感 | `sentiment` | 🟡 N | 话题内帖子的平均情感 |
| 增长率 | `growthRate` | 🟢 D | 话题提及量周环比 |

#### 2.2.4 社区画像（SubredditProfile）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 社区名称 | `name` | 🔴 R | `subreddit.display_name` |
| 帖子数 | `posts` | 🟢 D | 该社区内目标帖子数 |
| 互动率 | `engagement` | 🟢 D | `(comments + score) / posts` |
| 情感得分 | `sentiment` | 🟡 N | 社区内帖子平均情感 |
| 增长趋势 | `growthRate` | 🟢 D | 社区提及量环比 |

#### 2.2.5 竞品对标（CompetitorComparison）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 品牌名称 | `name` | 🔴 R / 🟢 D | 帖子中识别的竞品名称 |
| 提及量 | `mentions` | 🟢 D | 统计周期内提及次数 |
| 情感 | `sentiment` | 🟡 N | 提及该品牌的帖子平均情感 (-1~1) |
| 声量份额 | `shareOfVoice` | 🟢 D | 品牌提及量 / 品类总提及量 (%) |
| 趋势 | `trend` | 🟢 D | `up` / `down` / `stable` |

#### 2.2.6 关键词词云 & 桑基图

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 关键词 | `keyword` / `text` | 🟡 N | NLP 关键词提取结果 |
| 权重/频次 | `count` / `value` | 🟢 D | 关键词出现频次 |
| 桑基节点 | `nodes[].name` | 🟡 N + 🟢 D | 社区→话题→情感的流转节点 |
| 桑基流量 | `links[].value` | 🟢 D | 流转路径上的帖子数量 |

---

### 2.3 Insights（深度洞察）

#### 2.3.1 运营洞察（Operation）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 运营指标值 | `value` | 🟢 D | 如响应率、完成率等运营 KPI |
| 目标值 | `target` | 🟢 D | 预设目标阈值 |
| 变化率 | `change` | 🟢 D | 环比变化 (%) |
| 趋势 | `trend` | 🟢 D | `up` / `down` / `stable` |
| 团队效率 | `efficiency` | 🟢 D | 后端计算的综合效率指标 |

#### 2.3.2 舆情洞察（Sentiment）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 情感堆叠柱状图 | `positive`, `negative`, `neutral` | 🟡 N | 每日情感分布聚合 |
| 预警等级 | `level` | 🟢 D | `critical` / `warning` / `info` |
| 响应时间 | `responseTime` | 🟢 D | 从发现到响应的时长 |
| 处理状态 | `status` | 🟢 D | `resolved` / `pending` / `escalated` |
| 负面传播路径 | `spreadPath[]` | 🟡 N | NLP 识别的话题传播链路 |
| 遏制时间 | `containmentTime` | 🟢 D | 从爆发到控制的时间 |
| 危机严重度 | `severity` | 🟢 D | 基于影响面+传播速度的评级 |

#### 2.3.3 品牌洞察（Brand）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 品牌雷达维度 | `dimension` | 🟡 N | NLP 识别的品牌属性维度 |
| 品牌得分 | `momcozy` | 🟢 D | 该维度下的品牌认知得分 |
| 竞品得分 | `elvie`, `spectra` | 🟢 D | 竞品在同一维度的得分 |
| 心智份额 | `mindShare` | 🟢 D | 品牌在品类讨论中的占比 |

#### 2.3.4 品类洞察（Category）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 转化漏斗阶段 | `name` | 🟢 D | 如「讨论→意向→购买」等阶段 |
| 阶段数值 | `value` | 🟢 D | 该阶段的用户/帖子数量 |
| 转化率 | `conversionRate` | 🟢 D | 相邻阶段间的转化比例 |
| 新品机会 ROI | `potentialROI` | 🟢 D | 基于需求度/竞争度的预估 ROI |
| 需求度 | `demandScore` | 🟡 N | NLP 需求强度识别 |
| 竞争度 | `competitionScore` | 🟢 D | 市场已有解决方案的饱和度 |
| 痛点提及频次 | `frequency` | 🟢 D | 该痛点被提及的次数 |
| 严重度 | `severity` | 🟡 N | NLP 痛点评分 |
| 市场空白竞争密度 | `competitiveDensity` | 🟢 D | `low` / `medium` / `high` |

---

### 2.4 Search（帖子搜索）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 帖子标题 | `title` | 🔴 R | Reddit `title` |
| 帖子内容 | `content` / `body` | 🔴 R | Reddit `selftext` 或评论内容 |
| 作者 | `author` | 🔴 R | Reddit `author` |
| 社区 | `subreddit` | 🔴 R | Reddit `subreddit` |
| 点赞数 | `upvotes` | 🔴 R | Reddit `ups` |
| 评论数 | `comments` | 🔴 R | Reddit `num_comments` |
| 链接 | `url` / `permalink` | 🔴 R | Reddit `permalink` |
| 发布时间 | `createdAt` / `time` | 🔴 R | `created_utc` 格式化 |
| 情感 | `sentiment` | 🟡 N | NLP 情感分析 |
| 意图 | `intent` | 🟡 N | NLP 意图分类 |
| 意向分 | `intentScore` | 🟡 N | NLP 意图置信度 |
| 关键词 | `keywords[]` | 🟡 N | NLP 关键词提取 |
| 帖子状态 | `status` | 🟢 D | `new` / `replied` / `saved`，用户操作状态 |
| 匹配度 | `matchScore` | 🟢 D | 搜索相关性评分（可选） |

#### 搜索筛选器参数

| 筛选条件 | 对应字段 | 说明 |
|---------|---------|------|
| 帖子状态 | `status` | 用户操作状态筛选 |
| 最小意向分 | `minIntentScore` | `intentScore >= threshold` |
| 社区筛选 | `subreddit` | 精确匹配 |
| 关键词搜索 | `title`, `content` | 全文检索 |
| 时间范围 | `timeRange` | `created_utc` 范围筛选 |
| 情感筛选 | `sentiment` | 情感类型筛选 |
| 意图筛选 | `intent` | 意图类型筛选 |

---

### 2.5 Messages（消息中心）

#### 2.5.1 通知列表

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 通知标题 | `title` | 🟢 D | 后端根据规则生成的通知标题 |
| 通知描述 | `description` | 🟢 D | 通知详情描述 |
| 通知类型 | `type` | 🟢 D | `alert` / `task` / `insight` / `system` |
| 严重等级 | `severity` | 🟢 D | `critical` / `warning` / `info` |
| 关联社区 | `subreddit` | 🔴 R | 触发通知的帖子所属社区 |
| 关联帖子 | `postTitle` | 🔴 R | 触发通知的帖子标题 |
| 时间 | `time` | 🟢 D | 通知生成时间 |
| 已读状态 | `read` | 🟢 D | 用户阅读状态 |
| 操作链接 | `actionUrl` | 🟢 D | 跳转链接 |

#### 2.5.2 通知规则

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 规则名称 | `name` | 🟢 D | 用户配置的规则名 |
| 规则类型 | `type` | 🟢 D | `sentiment` / `intent` / `mention` / `competitor` / `trend` |
| 阈值 | `threshold` | 🟢 D | 触发阈值配置 |
| 通知渠道 | `channels[]` | 🟢 D | `app` / `email` / `feishu` |
| 通知频率 | `frequency` | 🟢 D | `immediate` / `hourly` / `daily` |
| 启用状态 | `enabled` | 🟢 D | 规则开关状态 |

---

### 2.6 UGCShowcase（UGC 素材库）

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 素材标题 | `title` | 🔴 R | Reddit 帖子 `title` |
| 素材内容 | `content` | 🔴 R | Reddit `selftext` / 评论正文 |
| 作者 | `author` | 🔴 R | Reddit `author` |
| 社区 | `subreddit` | 🔴 R | Reddit `subreddit` |
| 点赞数 | `upvotes` | 🔴 R | Reddit `ups` |
| 评论数 | `comments` | 🔴 R | Reddit `num_comments` |
| 发布时间 | `createdAt` | 🔴 R | `created_utc` |
| 链接 | `url` | 🔴 R | Reddit `permalink` |
| 情感 | `sentiment` | 🟡 N | NLP 情感分析 |
| 意向分 | `intentScore` | 🟡 N | NLP 意图置信度 |
| 互动率 | `engagementRate` | 🟢 D | `(upvotes + comments) / 基准值 * 100`，标准化到 0-100 |
| 分类 | `category` | 🟡 N | `product` / `experience` / `comparison` / `lifestyle` / `tip` |
| 媒体类型 | `mediaType` | 🔴 R | `text` / `image` / `video` / `gallery`，基于 Reddit `post_hint` |
| 标签 | `tags[]` | 🟡 N | NLP 关键词提取后人工/自动标注 |
| 归档状态 | `isArchived` | 🟢 D | 用户/系统自动归档标记 |
| 归档原因 | `autoArchiveReason` | 🟢 D | 自动归档的规则说明 |
| 被引用站点 | `quotedBy[]` | 🟢 D | 外部站点转载追踪 |
| 统计-已归档素材 | `totalArchived` | 🟢 D | 累计归档数量 |
| 统计-本周新增 | `thisWeek` | 🟢 D | 本周新增归档数 |
| 统计-正面占比 | `positiveRate` | 🟢 D | 正面素材 / 总素材 (%) |
| 统计-平均互动率 | `avgEngagement` | 🟢 D | 所有素材 `engagementRate` 平均值 |

---

### 2.7 CaseGallery（案例广场）

> **注意**: 案例广场的数据来源与 Reddit 数据不同，主要展示精选的运营案例文章，字段结构相对独立。

| 展示字段 | 数据源字段 | 来源 | 说明 |
|---------|-----------|------|------|
| 案例标题 | `title` | 🟢 D | 案例文章标题 |
| 案例描述 | `description` | 🟢 D | 案例摘要 |
| 来源 | `source` | 🟢 D | 文章来源/平台 |
| 分类 | `category` | 🟢 D | `geo` / `newproduct` / `insight` / `business` |
| 标签 | `tags[]` | 🟢 D | 案例标签 |
| 发布日期 | `date` | 🟢 D | 文章发布日期 |
| 作者 | `author` | 🟢 D | 文章作者（可选） |
| 阅读时间 | `readTime` | 🟢 D | 预估阅读时长（可选） |
| 案例链接 | `url` | 🟢 D | 原文链接 |
| 热门检索标签 | `hotSearchTags[]` | 🟢 D | 热门搜索关键词及频次 |
| 分类计数 | `categoryCounts` | 🟢 D | 各分类下的案例数量 |

---

## 3. Codex 后端 API 端点清单

以下端点基于 `src/lib/api.ts` 中已预留的接口定义，并补充 Reddit 数据获取和 NLP 分析专用端点。

### 3.1 现有预留端点

| 端点 | 方法 | 用途 | 关联页面 |
|------|------|------|---------|
| `/reports/daily` | GET | 获取日报数据 | Dashboard |
| `/reports/weekly` | GET | 获取周报数据 | Dashboard |
| `/reports/monthly` | GET | 获取月报数据 | Dashboard |
| `/notifications` | GET | 获取通知列表 | Messages |
| `/notifications/{id}/read` | POST | 标记已读 | Messages |
| `/notifications/read-all` | POST | 全部已读 | Messages |
| `/notification-rules` | GET / PATCH | 通知规则管理 | Messages |
| `/search/{configId}` | GET | 执行搜索配置 | Search |
| `/search-configs` | GET / POST / PATCH / DELETE | 搜索配置 CRUD | Search |
| `/analytics/overview` | GET | 分析概览 | Analytics |
| `/analytics/sentiment` | GET | 情感分析数据 | Analytics |
| `/analytics/competitors` | GET | 竞品对比数据 | Analytics |
| `/analytics/topics` | GET | 话题聚类数据 | Analytics |
| `/insights` | GET | 洞察列表 | Insights |
| `/insights/{id}/status` | PATCH | 更新洞察状态 | Insights |
| `/user/profile` | GET | 用户资料 | Settings |
| `/user/settings` | PATCH | 更新设置 | Settings |

### 3.2 需新增的 Reddit 专用端点

| 端点 | 方法 | 用途 | 关联页面 |
|------|------|------|---------|
| `/api/v1/reddit/fetch` | POST | 从 Reddit 获取原始帖子数据 | Search, Dashboard |
| `/api/v1/reddit/posts/{id}` | GET | 获取单帖详情（含评论） | Search, PostDetail |
| `/api/v1/reddit/comments` | GET | 获取帖子评论树 | PostDetail |
| `/api/v1/nlp/analyze` | POST | 对帖子进行 NLP 分析 | Search, Analytics |
| `/api/v1/nlp/batch-analyze` | POST | 批量 NLP 分析 | Dashboard, Analytics |
| `/api/v1/ugc/items` | GET / POST | UGC 素材库 CRUD | UGCShowcase |
| `/api/v1/ugc/stats` | GET | UGC 统计数据 | UGCShowcase |
| `/api/v1/cases` | GET | 案例广场数据 | CaseGallery |

---

## 4. API 请求/响应格式规范

### 4.1 `POST /api/v1/reddit/fetch`

> **用途**: 从 Reddit 获取指定条件的原始帖子数据，供前端展示和后续 NLP 分析。

#### Request

```json
{
  "subreddits": ["breastfeeding", "babybumps", "breastpumps", "NewParents"],
  "timeRange": {
    "from": "2024-01-01T00:00:00Z",
    "to": "2024-01-31T23:59:59Z"
  },
  "keywords": {
    "include": ["momcozy", "wearable pump", "M5"],
    "exclude": ["spam", "promotion"]
  },
  "filters": {
    "minScore": 5,
    "minComments": 1,
    "sortBy": "new",
    "limit": 100,
    "includeComments": true,
    "commentDepth": 2
  },
  "brands": ["Momcozy", "Elvie", "Spectra", "Willow"],
  "options": {
    "deduplicate": true,
    "languageFilter": "en"
  }
}
```

#### Response

```json
{
  "success": true,
  "data": {
    "posts": [
      {
        "id": "post_001",
        "redditId": "t3_1d1",
        "title": "momcozy m5 for work?? need something QUIET lol",
        "author": "u/throwaway_pump22",
        "subreddit": "breastfeeding",
        "permalink": "/r/breastfeeding/comments/1d1/quiet_wearable_pump/",
        "score": 1180,
        "upvotes": 1247,
        "upvoteRatio": 0.94,
        "comments": 186,
        "createdAt": "2024-01-15T08:30:00Z",
        "url": "https://reddit.com/r/breastfeeding/comments/1d1/quiet_wearable_pump/",
        "content": "I'm going back to work soon and need a quiet pump...",
        "media": {
          "type": "text",
          "thumbnail": null
        },
        "commentList": [
          {
            "id": "c1",
            "redditId": "t1_c1",
            "author": "u/Fit_Ant_8317",
            "body": "I got the Momcozy M5 last month and it has been amazing...",
            "score": 45,
            "createdAt": "2024-01-15T09:00:00Z",
            "permalink": "/r/breastfeeding/comments/1d1/quiet_wearable_pump/c1",
            "sentiment": "positive",
            "parentId": "t3_1d1",
            "replies": []
          }
        ],
        "raw": {
          "created_utc": 1705307400,
          "is_self": true,
          "selftext": "I'm going back to work soon and need a quiet pump...",
          "num_crossposts": 0,
          "pinned": false,
          "spoiler": false
        }
      }
    ],
    "pagination": {
      "total": 156,
      "page": 1,
      "pageSize": 100,
      "hasMore": true,
      "cursor": "eyJwYWdlIjoyfQ=="
    },
    "meta": {
      "fetchedAt": "2024-01-31T12:00:00Z",
      "source": "reddit_api",
      "subredditsQueried": ["breastfeeding", "babybumps", "breastpumps", "NewParents"],
      "queryTimeMs": 2340
    }
  }
}
```

#### 字段映射说明

| Response 字段 | Reddit API 原始字段 | 说明 |
|--------------|-------------------|------|
| `redditId` | `id` (Reddit) | Reddit 原生帖子 ID，前缀 `t3_` |
| `score` | `score` | Reddit 得分（upvotes - downvotes） |
| `upvotes` | `ups` | 点赞数 |
| `upvoteRatio` | `upvote_ratio` | 点赞比例 |
| `comments` | `num_comments` | 评论数 |
| `createdAt` | `created_utc` | Unix 时间戳转 ISO 8601 |
| `permalink` | `permalink` | Reddit 相对链接 |
| `content` | `selftext` | 帖子正文（自帖） |
| `media.type` | `post_hint` | 媒体类型推断 |

---

### 4.2 `POST /api/v1/nlp/analyze`

> **用途**: 对 Reddit 帖子进行 NLP 分析，返回情感、意图、关键词等后处理字段。

#### Request

```json
{
  "posts": [
    {
      "id": "post_001",
      "redditId": "t3_1d1",
      "title": "momcozy m5 for work?? need something QUIET lol",
      "content": "I'm going back to work soon and need a quiet pump...",
      "comments": [
        {
          "id": "c1",
          "body": "I got the Momcozy M5 last month and it has been amazing..."
        }
      ]
    }
  ],
  "analysisTypes": ["sentiment", "intent", "keywords", "entities", "topics"],
  "options": {
    "language": "en",
    "sentimentModel": "multilingual",
    "intentModel": "momcozy-custom-v2",
    "extractComments": true,
    "minConfidence": 0.6
  }
}
```

#### Response

```json
{
  "success": true,
  "data": {
    "results": [
      {
        "id": "post_001",
        "redditId": "t3_1d1",
        "sentiment": {
          "overall": "neutral",
          "score": 0.15,
          "title": "neutral",
          "content": "neutral",
          "comments": "positive"
        },
        "intent": {
          "primary": "Purchase Intent",
          "score": 92,
          "allScores": {
            "Purchase Intent": 92,
            "UGC": 15,
            "Bug Report": 3,
            "Comparison": 8,
            "Question": 45,
            "General": 22
          }
        },
        "keywords": [
          { "word": "momcozy", "count": 2, "type": "brand" },
          { "word": "quiet", "count": 1, "type": "feature" },
          { "word": "work", "count": 1, "type": "scenario" },
          { "word": "M5", "count": 1, "type": "product" }
        ],
        "entities": {
          "brands": ["Momcozy"],
          "products": ["M5"],
          "competitors": [],
          "scenarios": ["back to work"]
        },
        "topics": [
          { "id": "topic_01", "name": "workplace pumping", "confidence": 0.89 }
        ],
        "engagement": {
          "engagementRate": 78.5,
          "predictedReach": 5200,
          "viralScore": 42
        },
        "language": "en",
        "analyzedAt": "2024-01-31T12:05:00Z"
      }
    ],
    "meta": {
      "totalAnalyzed": 1,
      "analysisTimeMs": 1560,
      "modelsUsed": ["sentiment-v3", "intent-momcozy-v2", "keyword-extractor-v1"]
    }
  }
}
```

#### 字段映射说明

| Response 字段 | 类型 | 说明 | 映射到前端字段 |
|--------------|------|------|--------------|
| `sentiment.overall` | `enum` | 帖子整体情感 | `sentiment` |
| `sentiment.score` | `number` | 连续情感值 -1~+1 | 图表/细分分析 |
| `intent.primary` | `enum` | 主要意图分类 | `intent` |
| `intent.score` | `number` | 意图置信度 0-100 | `intentScore` |
| `intent.allScores` | `object` | 各意图分数分布 | 详情展示 |
| `keywords[].word` | `string` | 提取关键词 | `keywords[]` / `tags[]` |
| `keywords[].type` | `enum` | 关键词类型 | 分类标注 |
| `entities.brands` | `string[]` | 识别品牌 | 竞品分析 |
| `entities.products` | `string[]` | 识别产品 | 产品分析 |
| `engagement.engagementRate` | `number` | 互动率评分 | `engagementRate` |
| `engagement.viralScore` | `number` | 传播潜力分 | 预警/优先级判断 |

---

## 5. 核心数据模型字段总览

### 5.1 RedditPost（完整模型）

```typescript
interface RedditPost {
  // === Reddit API 原生字段 ===
  id: string;                    // 内部 ID
  redditId: string;              // Reddit 原生 ID (t3_xxx)
  title: string;                 // 🔴 R: title
  author: string;                // 🔴 R: author
  subreddit: string;             // 🔴 R: subreddit
  permalink: string;             // 🔴 R: permalink
  score: number;                 // 🔴 R: score
  upvotes: number;               // 🔴 R: ups
  upvoteRatio: number;           // 🔴 R: upvote_ratio
  comments: number;              // 🔴 R: num_comments
  createdAt: string;             // 🔴 R: created_utc (ISO 8601)
  url: string;                   // 🔴 R: url / permalink 拼接
  content?: string;              // 🔴 R: selftext

  // === NLP 后处理字段 ===
  sentiment: 'positive' | 'neutral' | 'negative';  // 🟡 N
  intent: PostIntent;                              // 🟡 N
  intentScore: number;                             // 🟡 N

  // === 关联数据 ===
  commentList: RedditComment[];  // 🔴 R + 🟡 N
}
```

### 5.2 RedditComment（评论模型）

```typescript
interface RedditComment {
  id: string;                    // 内部 ID
  redditId: string;              // 🔴 R: Reddit 评论 ID (t1_xxx)
  author: string;                // 🔴 R: author
  body: string;                  // 🔴 R: body
  score: number;                 // 🔴 R: score
  createdAt: string;             // 🔴 R: created_utc
  permalink: string;             // 🔴 R: permalink
  sentiment: 'positive' | 'neutral' | 'negative';  // 🟡 N
  parentId?: string;             // 🔴 R: parent_id
  replies?: RedditComment[];     // 🔴 R: replies (树形结构)
}
```

### 5.3 UGCItem（UGC 素材模型）

```typescript
interface UGCItem {
  // === Reddit 基础字段 ===
  id: string;
  title: string;                 // 🔴 R
  content: string;               // 🔴 R
  author: string;                // 🔴 R
  subreddit: string;             // 🔴 R
  upvotes: number;               // 🔴 R
  comments: number;              // 🔴 R
  createdAt: string;             // 🔴 R
  url: string;                   // 🔴 R

  // === NLP 字段 ===
  sentiment: 'positive' | 'neutral' | 'negative';  // 🟡 N
  intentScore: number;                           // 🟡 N
  tags: string[];                                // 🟡 N

  // === 派生/管理字段 ===
  category: UGCCategory;         // 🟡 N / 🟢 D
  mediaType: UGCMediaType;       // 🔴 R / 🟢 D
  engagementRate: number;        // 🟢 D
  isArchived: boolean;           // 🟢 D
  archivedAt?: string;           // 🟢 D
  autoArchiveReason: string;     // 🟢 D
  quotedBy?: string[];           // 🟢 D
}
```

---

## 6. 数据流架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         Reddit API                               │
│  (PRAW / Pushshift / Official API)                              │
└────────────────────────┬────────────────────────────────────────┘
                         │ 原生字段: title, author, score, etc.
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    POST /api/v1/reddit/fetch                     │
│                         数据获取层                                │
└────────────────────────┬────────────────────────────────────────┘
                         │ RedditPost 原始数据
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    POST /api/v1/nlp/analyze                      │
│                         NLP 处理层                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ 情感分析     │  │ 意图识别     │  │ 关键词提取   │             │
│  │ sentiment   │  │ intent      │  │ keywords    │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└────────────────────────┬────────────────────────────────────────┘
                         │ RedditPost + NLP 字段
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         后端派生层                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ 聚合统计     │  │ 趋势计算     │  │ 规则引擎     │             │
│  │ engagement  │  │ trend       │  │ alerts      │             │
│  │ rate, ROI   │  │ growthRate  │  │ actionItems │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└────────────────────────┬────────────────────────────────────────┘
                         │ 完整数据模型
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      前端展示层 (React)                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Dashboard│ │ Analytics│ │ Insights │ │  Search  │          │
│  │ Messages │ │UGCShowcase│ │CaseGallery│ │          │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 字段变更日志

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2024-01 | 初始版本，覆盖 Dashboard/Analytics/Insights/Search/Messages/UGCShowcase/CaseGallery 全部 7 个页面 |

---

## 8. 附录：Reddit API 字段对照表

| Reddit API 字段 | 本项目字段 | 说明 |
|----------------|-----------|------|
| `id` | `redditId` | Reddit 原生 ID（含前缀 t3_/t1_） |
| `title` | `title` | 帖子标题 |
| `author` | `author` | 作者用户名 |
| `subreddit` | `subreddit` | 子版块名称（不含 r/） |
| `permalink` | `permalink` | 相对链接 |
| `score` | `score` | 净得分 |
| `ups` | `upvotes` | 点赞数 |
| `upvote_ratio` | `upvoteRatio` | 点赞比例 |
| `num_comments` | `comments` | 评论数 |
| `created_utc` | `createdAt` | 创建时间（Unix → ISO） |
| `selftext` | `content` | 自帖正文 |
| `url` | `url` | 外部链接（非自帖时） |
| `post_hint` | `mediaType` | 媒体类型推断 |
| `body` | `body` | 评论正文 |
| `parent_id` | `parentId` | 父评论/帖子 ID |
| `replies` | `replies` | 嵌套评论回复 |

---

*本文档由 Task H 生成，作为前后端数据契约参考。*
