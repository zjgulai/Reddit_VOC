# Momcozy Reddit 舆情工作台 —— Codex 交接文档

> **版本**: v1.0  
> **交接日期**: 2026-07-13  
> **前端项目路径**: `/Users/pray/project/Reddit_VOC/ref/UI/momcozy-reddit-workbench`  
> **技术栈**: React 19 + TypeScript + Vite + TailwindCSS + Zustand + Recharts

---

## 一、项目概述

Momcozy Reddit 舆情工作台是一个品牌舆情监控与分析的中台系统，数据来源于 Reddit 帖子和评论。系统提供三层时间维度的舆情监控（日报/周报/月报）、竞品对标、消息管理、搜索发现、洞察分析、案例广场等模块。

当前状态：
- ✅ 前端 UI 全部完成（13 个页面，74 个单元测试通过）
- ✅ 数据引擎和统一聚合管线完成（Mock 模式）
- ⏳ **待接入**: 真实 Reddit 数据采集后端
- ⏳ **待接入**: 后端 API 服务

---

## 二、Reddit 原始数据字段说明

### 2.1 帖子级字段（Reddit Post）

后端需要采集并提供以下 Reddit 帖子原始字段：

| 字段名 | 类型 | 说明 | 必填 |
|--------|------|------|------|
| `id` | string | 系统内部唯一标识 | ✅ |
| `redditId` | string | Reddit 原帖 ID（如 t3_xxx） | ✅ |
| `title` | string | 帖子标题 | ✅ |
| `author` | string | 发帖用户名（u/xxx） | ✅ |
| `subreddit` | string | 所属社区名称 | ✅ |
| `permalink` | string | Reddit 永久链接 | ✅ |
| `score` | number | Reddit 综合得分 | ✅ |
| `upvotes` | number | 点赞数 | ✅ |
| `upvoteRatio` | number | 点赞比例（0-1） | ✅ |
| `comments` | number | 评论数 | ✅ |
| `createdAt` | string (ISO8601) | 发帖时间 | ✅ |
| `sentiment` | 'positive' \| 'neutral' \| 'negative' | 情感分析结果 | ✅ |
| `intent` | PostIntent | 意图分类 | ✅ |
| `intentScore` | number | 意向评分（0-100） | ✅ |
| `content` | string | 帖子正文内容 | 可选 |
| `url` | string | 外部链接（如有） | 可选 |

### 2.2 评论级字段（Reddit Comment）

| 字段名 | 类型 | 说明 | 必填 |
|--------|------|------|------|
| `id` | string | 系统内部唯一标识 | ✅ |
| `redditId` | string | Reddit 评论 ID | ✅ |
| `author` | string | 评论用户名 | ✅ |
| `body` | string | 评论内容 | ✅ |
| `score` | number | 评论得分 | ✅ |
| `createdAt` | string (ISO8601) | 评论时间 | ✅ |
| `permalink` | string | 评论永久链接 | ✅ |
| `sentiment` | 'positive' \| 'neutral' \| 'negative' | 情感分析 | ✅ |
| `parentId` | string | 父评论 ID（一级评论为帖子 ID） | 可选 |
| `replies` | RedditComment[] | 嵌套回复 | 可选 |

### 2.3 意图分类枚举（PostIntent）

```typescript
type PostIntent =
  | 'Purchase Intent'   // 购买意向
  | 'UGC'               // 用户生成内容/晒单
  | 'Bug Report'        // 产品问题/故障报告
  | 'Comparison'        // 竞品对比
  | 'Question'          // 提问/求助
  | 'General';          // 一般讨论
```

### 2.4 业务价值标签（BusinessValueTag）

```typescript
type BusinessValueTag = 'high_intent' | 'ugc' | 'competitor' | 'crisis' | 'opportunity';
```

后端 NLP pipeline 需要为每篇帖子输出以上意图分类和情感分析结果。

---

## 三、各页面数据需求矩阵

### 3.1 Dashboard（舆情看板）/dashboard

| 模块 | 数据需求 | 后端接口 |
|------|----------|----------|
| 日报/周报/月报 Tab | `GET /reports/:period` | 返回 UnifiedReportData |
| 品牌评分卡 | 基于 overview 计算 | 前端计算 |
| 竞品雷达图 | `GET /analytics/competitors` | 竞品维度得分 |
| 竞品趋势图 | `GET /analytics/competitors?trend=7d/30d` | 时间序列数据 |
| 通知中心 | `GET /notifications` | 通知列表 |
| Webhook 推送 | `POST /webhooks/:id/push` | 推送通知到钉钉/飞书 |
| 数据导出 | 前端生成 CSV/PPTX/DOCX | 纯前端 |

**日报（DailyReportData）关键字段：**
- `overview`: 新帖数、正面率、负面率、紧急警报数、高意向数、UGC数、情感水位
- `sentimentTrend`: 24小时情感趋势（每小时一个点：positive/negative/neutral/volume）
- `alerts`: 紧急警报列表（critical/warning/info 三级）
- `newPosts`: 新帖发现列表（含业务价值标签）
- `communityStatus`: 社区活跃度状态
- `actionItems`: 运营待办清单
- `responseMetrics`: 响应时效指标
- `sentimentThermometer`: 情感温度计

**周报（WeeklyReportData）额外字段：**
- `weeklyTrends`: 趋势分析（本周vs上周）
- `weeklyOpportunities`: 机会洞察
- `weeklyRisks`: 风险洞察
- `weeklyCompetitors`: 竞品对标
- `weeklyReviews`: 运营复盘
- `weeklyPlans`: 下周计划
- `painPoints`: 用户痛点
- `topicLifecycles`: 话题生命周期
- `brandVoiceTrend`: 品牌声量趋势

**月报（MonthlyReportData）额外字段：**
- `monthlyBrandHealth`: 品牌健康度指标
- `monthlyBrandHealthTrend`: 品牌健康趋势
- `monthlyCompetitorShares`: 竞品讨论份额
- `monthlyCommunityROI`: 社区价值 ROI
- `monthlyTopicEvolution`: 话题演变
- `monthlyKPIs`: KPI 达成
- `monthlyStrategicAdvices`: 战略建议
- `brandHealthScore`: 品牌健康总分
- `brandHealthRadar`: 品牌雷达数据
- `competitiveMatrix`: 竞争矩阵
- `categoryMatrix`: 品类矩阵

### 3.2 Analytics（分析页）/dashboard/analytics

| 模块 | 数据需求 | 后端接口 |
|------|----------|----------|
| 情感总览 | `GET /analytics/overview` | 聚合指标 |
| 情感趋势 | `GET /analytics/sentiment` | 时间序列 |
| 竞品对比 | `GET /analytics/competitors` | 竞品数据 |
| 话题聚类 | `GET /analytics/topics` | 话题数据 |
| 词云 | `GET /analytics/keywords` | 高频关键词 |
| 桑基图 | `GET /analytics/topicFlow` | 话题流转 |

### 3.3 Insights（洞察页）/dashboard/insights

| 模块 | 数据需求 | 后端接口 |
|------|----------|----------|
| 舆情洞察 | `GET /insights?type=sentiment` | 情感相关洞察 |
| 品牌洞察 | `GET /insights?type=brand` | 品牌相关洞察 |
| 品类洞察 | `GET /insights?type=category` | 品类相关洞察 |
| 运营洞察 | `GET /insights?type=operation` | 运营建议 |
| 洞察卡片 | `GET /insights` | 全部洞察列表 |

### 3.4 Search（搜索页）/dashboard/search

| 模块 | 数据需求 | 后端接口 |
|------|----------|----------|
| 搜索结果列表 | `GET /search/:configId` | 搜索帖子 |
| 搜索配置 | `GET /search-configs` | 配置列表 |
| 关键词规则 | `GET /search-configs/:id/keywords` | 关键词管理 |
| Subreddit 规则 | `GET /search-configs/:id/subreddits` | 社区管理 |

### 3.5 Messages（消息页）/dashboard/messages

| 模块 | 数据需求 | 后端接口 |
|------|----------|----------|
| 消息列表 | `GET /notifications` | 通知/消息列表 |
| 标记已读 | `POST /notifications/:id/read` | 标记已读 |
| 帖子详情抽屉 | 复用 SearchPost / ReportNewPost | 统一数据模型 |

### 3.6 UGC Showcase（UGC展示）/dashboard/ugc-showcase

| 模块 | 数据需求 | 后端接口 |
|------|----------|----------|
| UGC 素材列表 | `GET /ugc` | UGC 内容 |
| UGC 统计 | `GET /ugc/stats` | 归档统计 |

### 3.7 Case Gallery（案例广场）/cases

**无需后端接口** —— 案例广场通过前端定时网络检索（微信公众号、Reddit 官方论坛等）获取高质量文章链接，以卡片形式展示，不做内容提取，保持原链接跳转。

### 3.8 Settings（设置页）/dashboard/settings

| 模块 | 数据需求 | 后端接口 |
|------|----------|----------|
| 用户配置 | `GET /user/settings` | 用户设置 |
| 通知规则 | `GET /notification-rules` | 规则列表 |
| Webhook 配置 | 本地存储 + `POST /webhooks` | 推送配置 |
| 竞品品牌配置 | 本地存储（Zustand）| 前端状态管理 |

---

## 四、后端 API 接口规范

### 4.1 已预留接口（src/lib/api.ts）

```typescript
// 报告
GET  /api/v1/reports/daily
GET  /api/v1/reports/weekly
GET  /api/v1/reports/monthly

// 通知
GET    /api/v1/notifications?page=&pageSize=&type=&read=
POST   /api/v1/notifications/:id/read
POST   /api/v1/notifications/read-all
GET    /api/v1/notification-rules
PATCH  /api/v1/notification-rules/:id

// 搜索
GET    /api/v1/search/:configId?page=&pageSize=
GET    /api/v1/search-configs
POST   /api/v1/search-configs
PATCH  /api/v1/search-configs/:id
DELETE /api/v1/search-configs/:id

// 分析
GET /api/v1/analytics/overview?startDate=&endDate=
GET /api/v1/analytics/sentiment?subreddit=&period=
GET /api/v1/analytics/competitors
GET /api/v1/analytics/topics

// 洞察
GET   /api/v1/insights?page=&pageSize=&type=&status=
PATCH /api/v1/insights/:id/status

// 用户
GET   /api/v1/user/profile
PATCH /api/v1/user/settings
```

### 4.2 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `VITE_API_BASE_URL` | 后端 API 基础路径 | `/api/v1` |
| `VITE_USE_MOCK` | 是否使用 Mock 数据 | `true` |

---

## 五、数据采集与处理方案

### 5.1 Reddit 数据采集

**采集维度（MECE）:**

1. **品牌关键词监听**
   - 主品牌: Momcozy
   - 产品型号: M5, M6, V2, S12 等
   - 通用词: breast pump, wearable pump, 静音, 便携
   - 竞品词: Elvie, Spectra, Willow, Medela, Haakaa, Lansinoh

2. **Subreddit 覆盖**
   - A类（核心）: breastfeeding, babybumps, breastpumps
   - B类（重要）: NewParents, Mommit, ExclusivelyPumping
   - C类（补充）: pregnant, workingmoms 等

3. **采集频率**
   - 实时流: 品牌关键词提及（5分钟轮询）
   - 定时采集: 全量帖子（每小时）
   - 评论采集: 高互动帖子（发布后24小时内跟踪）

### 5.2 NLP Pipeline 处理

```
原始帖子 → 清洗 → 情感分析 → 意图识别 → 业务价值标签 → 入库
                ↓
            评论树分析 → 情感聚合 → 热点追踪
```

**必需处理模块:**
1. **情感分析**: 输出 positive/neutral/negative 三分类 + 置信度
2. **意图识别**: 六分类（Purchase Intent / UGC / Bug Report / Comparison / Question / General）
3. **关键词提取**: TF-IDF / 主题模型，输出高频词云数据
4. **竞品提及检测**: 识别竞品品牌名，计算 Share of Voice
5. **紧急度评估**: 负面情感 + Bug Report + 高互动 = 紧急警报

### 5.3 数据聚合引擎

后端需要按以下维度预计算聚合指标：

| 聚合维度 | 说明 |
|----------|------|
| 时间维度 | 24h / 7d / 30d 滑动窗口 |
| 社区维度 | 按 subreddit 分组统计 |
| 情感维度 | 正面/负面/中性占比 |
| 意图维度 | 六类意图分布 |
| 竞品维度 | 各品牌提及量、正面率 |
| 话题维度 | 主题聚类、趋势演变 |

---

## 六、技术架构建议

### 6.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端（React SPA）                      │
│              momcozy-reddit-workbench                        │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTPS
┌─────────────────────▼───────────────────────────────────────┐
│                      Nginx / CDN                             │
│              静态资源托管 + 反向代理                          │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                     后端 API 服务                             │
│              Node.js / Python / Go                           │
│         ┌─────────────┬─────────────┬─────────────┐         │
│         │  报告生成器  │  搜索服务   │  通知服务   │         │
│         └─────────────┴─────────────┴─────────────┘         │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                     数据层                                   │
│    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│    │  PostgreSQL  │  │    Redis     │  │ Elasticsearch│    │
│    │  (主数据库)   │  │  (缓存/队列)  │  │  (全文搜索)   │    │
│    └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                   Reddit 数据采集                             │
│         ┌─────────────────────────────────────┐             │
│         │  PRAW / Reddit API / Pushshift      │             │
│         │  + 定时调度（Airflow / cron）        │             │
│         └─────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 腾讯云轻量服务器配置建议

**方案 A: 最小可用（MVP）**

| 组件 | 配置 | 月费用估算 |
|------|------|-----------|
| 轻量应用服务器 | 2核4G + 80G SSD | ¥68/月 |
| 操作系统 | Ubuntu 22.04 LTS | - |
| 部署架构 | Docker Compose 单机部署 | - |
| 数据库 | PostgreSQL 15（容器）| - |
| 缓存 | Redis 7（容器）| - |
| Nginx | 反向代理 + 静态托管 | - |

**方案 B: 生产级**

| 组件 | 配置 | 月费用估算 |
|------|------|-----------|
| 轻量应用服务器（前端）| 2核2G | ¥50/月 |
| 轻量应用服务器（后端）| 4核8G | ¥150/月 |
| 轻量数据库服务 | PostgreSQL 16 | ¥80/月 |
| 对象存储 COS | 静态资源 + 备份 | ¥20/月 |
| CDN | 全球加速 | ¥30/月 |

**推荐**: 先使用方案 A 跑通 MVP，数据量增长后再迁移到方案 B。

### 6.3 部署步骤

```bash
# 1. 服务器初始化
ssh ubuntu@<your-server-ip>
sudo apt update && sudo apt install -y docker docker-compose nginx

# 2. 克隆前端项目
git clone <repo-url> /opt/momcozy-reddit-workbench
cd /opt/momcozy-reddit-workbench

# 3. 构建前端
npm install
npm run build

# 4. 配置 Nginx
cp nginx.conf /etc/nginx/sites-available/momcozy
ln -s /etc/nginx/sites-available/momcozy /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 5. 启动后端服务（Docker Compose）
docker-compose up -d
```

---

## 七、剩余工作清单

### P0 - 阻塞上线

- [ ] **后端 API 服务开发** —— 实现 `src/lib/api.ts` 中定义的全部接口
- [ ] **Reddit 数据采集脚本** —— PRAW 或 Reddit API 接入，定时采集帖子
- [ ] **NLP Pipeline** —— 情感分析 + 意图识别 + 关键词提取
- [ ] **数据库设计与迁移** —— PostgreSQL 表结构设计

### P1 - 上线后迭代

- [ ] **用户认证系统** —— 当前已移除登录页，如需要多用户需接入
- [ ] **数据持久化** —— 当前报告数据为内存计算，需接入真实数据源
- [ ] **实时推送** —— WebSocket 或 Server-Sent Events 实时通知
- [ ] **案例广场自动检索** —— 定时任务检索微信公众号、Reddit 官方论坛等
- [ ] **数据导出后端支持** —— 当前导出为纯前端生成，大容量时建议后端生成

### P2 - 体验优化

- [ ] **首屏加载优化** —— 当前部分页面为懒加载，可进一步优化 bundle 拆分
- [ ] **移动端适配** —— 当前以桌面端为主，部分组件移动端体验待优化
- [ ] **暗黑模式** —— 已预留 CSS 变量，需补充完整调色板

---

## 八、关键文件索引

| 文件路径 | 说明 |
|----------|------|
| `src/App.tsx` | 路由配置 |
| `src/lib/api.ts` | API 客户端 + 接口定义 |
| `src/data/reportEngine.ts` | 报告数据引擎（核心） |
| `src/data/unifiedEngine.ts` | 统一数据聚合引擎 |
| `src/data/searchMock.ts` | 搜索 Mock 数据 + 原始帖子定义 |
| `src/types/index.ts` | 全局类型定义 |
| `src/stores/*.ts` | Zustand 状态管理 |
| `src/components/charts/*.tsx` | 图表组件库 |
| `src/services/reportService.ts` | 报告服务层 |
| `src/services/caseService.ts` | 案例广场服务 |

---

## 九、联系人

- **前端负责人**: Kimi Code CLI
- **项目路径**: `/Users/pray/project/Reddit_VOC/ref/UI/momcozy-reddit-workbench`
- **构建命令**: `npm run build`
- **测试命令**: `npm test`
- **Dev Server**: `npm run dev` (http://localhost:5173)
