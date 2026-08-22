# Momcozy & Reddit 舆情工作台 — 产品需求文档（PRD）v2.0

## 一、产品概述

### 1.1 定位
Momcozy & Reddit 舆情工作台是一款面向品牌方的 Reddit 舆情监控与洞察工具，帮助品牌方实时追踪品牌在 Reddit 上的声量、情感、话题趋势，并通过数据可视化提供可执行的业务洞察。

### 1.2 核心用户
- 品牌市场部：监控品牌声誉、竞品动态
- 产品经理：挖掘用户痛点、发现产品机会
- 客服团队：及时响应负面舆情
- 管理层：获取品牌健康度概览

---

## 二、洞察方法论：叙事故事线

### 2.1 第一层：品牌健康度监控（Dashboard）
**核心问题：品牌目前在 Reddit 上的整体状态如何？**

| 洞察维度 | 对应图表 | 分析方法 | 业务决策 |
|----------|----------|----------|----------|
| 品牌提及趋势 | AreaChart / LineChart | 观察提及量随时间变化 | 判断营销活动效果、识别异常波动 |
| 情感分布 | PieChart | 正面/中性/负面占比 | 评估品牌声誉，识别危机 |
| 品牌综合评分 | RadarChart (BrandScoreCard) | 六维雷达图综合评估 | 管理层快速了解品牌健康度 |
| 日报/周报/月报 | ComposedChart + 数据卡片 | 滚动时间窗口分析 | 周期性经营复盘 |

**叙事逻辑：**
1. 先看综合评分（雷达图）→ 品牌整体健康度
2. 再看时间趋势（折线图）→ 近期波动原因
3. 最后看情感分布（饼图）→ 问题出在正面还是负面

### 2.2 第二层：深度分析（Analytics）
**核心问题：用户具体在讨论什么？情感背后的原因是什么？**

| 洞察维度 | 对应图表 | 分析方法 | 业务决策 |
|----------|----------|----------|----------|
| 情感分析 | PieChart + 情感趋势 | 情感随时间变化 | 识别情感突变点，及时响应 |
| 话题聚类 | WordCloudChart + TopicCluster | 高频关键词 + 话题分类 | 发现热点话题、用户关注点 |
| 社区画像 | SubredditProfile | 各社区的讨论特征 | 找到核心社区，精准投放 |
| 关键词词云 | EnhancedWordCloud | 按情感/分类着色 | 快速识别品牌印象关键词 |
| 社区-话题-情感流转 | SankeyChart | 三层桑基图 | 了解话题如何在社区间传播 |

**叙事逻辑：**
1. 先看话题聚类（词云）→ 用户在讨论什么
2. 再看情感分布（饼图）→ 这些话题的情感倾向
3. 最后看社区流转（桑基图）→ 话题从哪里来、到哪里去

### 2.3 第三层：竞争与受众（Analytics - 新增模块）
**核心问题：与竞品相比，我们的优势和劣势在哪里？目标受众是谁？**

| 洞察维度 | 对应图表 | 分析方法 | 业务决策 |
|----------|----------|----------|----------|
| 竞品对比 | CompetitorComparison | 多品牌对比柱状图 + 雷达图 | 制定差异化策略 |
| 影响者识别 | InfluencerIdentification | 类型分布饼图 + 影响力评分 | 找到社区KOL合作 |
| 受众画像 | AudiencePersona | 用户画像卡片 + 行为特征雷达 | 精准营销、产品定位 |

**叙事逻辑：**
1. 先看竞品对比（柱状图）→ 我们在行业中的位置
2. 再看影响者（表格/卡片）→ 谁在为竞品/我们发声
3. 最后看受众画像（雷达图）→ 我们的用户长什么样

### 2.4 第四层：策略与行动（Insights）
**核心问题：基于以上分析，我们应该采取什么行动？**

| 洞察维度 | 对应图表 | 分析方法 | 业务决策 |
|----------|----------|----------|----------|
| 热帖深度分析 | HotPostAnalysis + PostDetailDrawer | 热帖内容解读 | 学习成功案例、避免失败教训 |
| 策略建议 | StrategyPanel | 基于数据的行动建议 | 直接输出可执行策略 |
| 话题流转洞察 | SankeyChart + WordCloudChart | 话题传播路径分析 | 找到传播节点，放大正面声量 |

**叙事逻辑：**
1. 先看热帖分析（详情抽屉）→ 什么内容能引起共鸣
2. 再看话题流转（桑基图）→ 话题如何传播
3. 最后看策略建议（卡片）→ 具体行动方案

### 2.5 第五层：案例与学习（CaseGallery）
**核心问题：行业其他人怎么用 Reddit 数据？**

| 洞察维度 | 对应展示 | 分析方法 | 业务决策 |
|----------|----------|----------|----------|
| 行业案例 | 链接卡片 | 分类陈列高质量文章 | 学习行业最佳实践 |
| 搜索发现 | SearchPanel | 关键词搜索 + 筛选 | 快速定位关注内容 |

---

## 三、图表组件 - 洞察方法映射表

| 图表组件 | 技术实现 | 适用洞察场景 | 所在页面 | 数据输入 |
|----------|----------|-------------|----------|----------|
| **PieChart** | Recharts Pie | 情感分布、占比分析 | Dashboard, Analytics | 情感分类数据 |
| **LineChart** | Recharts Line | 时间趋势、波动分析 | Dashboard | 时间序列数据 |
| **AreaChart** | Recharts Area | 累积趋势、总量变化 | Dashboard | 时间序列数据 |
| **BarChart** | Recharts Bar | 对比分析、排名 | Analytics, Dashboard | 分类对比数据 |
| **StackedBarChart** | Recharts Bar (stacked) | 多维度累积对比 | Analytics | 多维度时间数据 |
| **RadarChart** | Recharts Radar | 多维度综合评估 | Dashboard(BrandScore), Analytics(Competitor) | 多维评分数据 |
| **ComposedChart** | Recharts Composed | 混合指标展示 | Dashboard(日报) | 多指标时间数据 |
| **ScatterChart** | Recharts Scatter | 相关性分析、异常检测 | Analytics | XY坐标数据 |
| **WordCloudChart** | 自定义 SVG | 关键词聚类、高频词展示 | Analytics, Insights | 词频数据 |
| **SankeyChart** | 自定义 SVG | 流转分析、传播路径 | Analytics, Insights | 节点+链接数据 |
| **ExportButton** | 自定义组件 | 数据导出CSV/PDF | Dashboard, Analytics, Insights | 当前页面数据 |
| **PostDetailDrawer** | 自定义抽屉 | 帖子详情查看 | Dashboard, Insights, Messages | 帖子ID |
| **NotificationCenter** | 自定义下拉 | 实时通知聚合 | Dashboard(顶部栏) | 通知事件流 |
| **BrandScoreCard** | RadarChart + 环形 | 品牌健康度评分 | Dashboard(日报) | 六维评分数据 |
| **CompetitorComparison** | BarChart + RadarChart | 竞品对比分析 | Analytics | 多品牌数据 |
| **InfluencerIdentification** | PieChart + 卡片/表格 | 影响者发现 | Analytics | 用户影响力数据 |
| **AudiencePersona** | RadarChart + 面积图 | 受众画像分析 | Analytics | 用户画像数据 |
| **EnhancedWordCloud** | WordCloud + 筛选 | 品牌印象关键词 | Analytics | 带情感的词频数据 |

---

## 四、页面功能矩阵

| 页面 | 核心功能 | 包含图表/组件 | 目标用户 |
|------|----------|--------------|----------|
| **Dashboard** | 品牌健康度概览 | StatCard, AreaChart, LineChart, PieChart, RadarChart(BrandScore), ComposedChart, DailyReport, NotificationCenter | 管理层、市场部 |
| **Analytics** | 深度数据分析 | SentimentAnalysis(PieChart), TopicCluster(WordCloud), SubredditProfile, CompetitorComparison, InfluencerIdentification, AudiencePersona, EnhancedWordCloud, SankeyChart, StackedBarChart, ScatterChart | 数据分析师、产品经理 |
| **Insights** | 策略与热帖 | HotPostAnalysis, StrategyPanel, PostDetailDrawer, SankeyChart(新增), WordCloudChart(新增) | 市场部、运营 |
| **Messages** | 消息与提醒 | 消息列表, PostDetailDrawer(新增) | 客服、运营 |
| **Search** | 帖子搜索 | SearchPanel, PostCard | 全员 |
| **CaseGallery** | 案例学习 | 链接卡片, 搜索历史, 热门标签 | 全员 |
| **Settings** | 系统配置 | 通知渠道, 竞品配置(新增), Webhook配置(新增) | 管理员 |

---

## 五、新增需求规格

### 5.1 桑基图/词云在 Insights 页面展示（需求1）
- **目标**：在 Insights 的热帖分析模块中，增加"话题流转洞察"和"关键词云"子模块
- **组件**：复用现有的 SankeyChart 和 WordCloudChart
- **数据**：复用 analyticsMock.ts 中的 sankeyNodes/sankeyLinks 和 keywordWordCloud
- **交互**：点击桑基图节点 → 筛选相关热帖；点击词云词汇 → 高亮包含该词的热帖
- **位置**：Insights 页面"热帖分析"标签下，位于热帖列表上方

### 5.2 Messages 页面集成帖子详情抽屉（需求4）
- **目标**：在消息列表中点击帖子标题/内容时，打开 PostDetailDrawer
- **组件**：复用现有的 PostDetailDrawer
- **集成位置**：Messages 页面每条消息的标题/内容区域
- **数据**：使用消息中关联的 postId 从 mock 数据获取详情

### 5.3 竞品品牌可配置（需求6）
- **目标**：在 Settings 页面新增"竞品品牌配置"模块，支持添加/删除/编辑竞品
- **配置项**：品牌名称、品牌关键词、监控状态
- **影响**：Analytics 页面的 CompetitorComparison 组件读取该配置
- **存储**：localStorage 持久化
- **默认竞品**：Elvie, Spectra, Willow, Medela（可配置为最多9个）

### 5.4 通知中心 Webhook 集成（需求5）
- **目标**：支持配置钉钉/飞书机器人 webhook，将关键事件推送到 IM
- **配置项**：
  - 通知渠道选择（钉钉/飞书）
  - Webhook URL
  - 触发规则（新提及、情感突变、提及激增、每日简报）
  - 签名密钥（可选，用于安全验证）
- **集成位置**：Settings 页面新增"Webhook 配置"卡片
- **推送时机**：前端定时轮询（每5分钟），当检测到触发条件时调用 webhook

### 5.5 案例广场定时网络检索（需求2）
- **目标**：通过定时网络检索发现高质量的 Reddit 分析相关文章，以链接卡片形式展示
- **检索源**：微信公众号、知乎、Medium、行业博客
- **检索关键词**：Reddit sentiment analysis, Reddit brand monitoring, Reddit market research, GEO Reddit, Reddit VOC
- **展示形式**：链接卡片（标题、摘要、来源、发布时间、标签）
- **更新频率**：手动触发或定时（每24小时）
- **技术方案**：前端通过 kimi_search_v2 模拟检索，后端实际部署时接真实搜索引擎API

---

## 六、开发优先级

### Phase 1：基础架构（1-2天）
1. ✅ 编写本 PRD 文档
2. 竞品品牌可配置（Settings 页面 + 数据层）

### Phase 2：UI增强（1-2天）
3. 桑基图/词云在 Insights 页面展示
4. Messages 页面集成帖子详情抽屉

### Phase 3：系统集成（2-3天）
5. 通知中心 Webhook 集成（钉钉/飞书）
6. 案例广场定时网络检索

---

*文档版本：v2.0*
*编写日期：2026-07-11*
*作者：Momcozy VOC 产品团队*
