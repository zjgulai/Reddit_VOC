# Reddit Momcozy 品牌 VOC 舆情监控系统 — 完整方案与执行计划

> ⚠️ **重要更新 (2026-07-07)**：本方案已经过对抗性审计，原始方案的 `.json` 采集方法已失效（Reddit 于 2026-05-28 关闭了未认证 .json 端点）。请阅读 **[对抗性审计报告](Reddit_VOC_Adversarial_Audit.md)** 获取修正方案。核心变更：采集层从 `.json` 端点切换为 RSS 端点（短期），并规划 OAuth API 升级路径（长期）。
>
> 目标：每天北京时间 04:00，抓取过去 24h 内 Reddit 上关于 Momcozy 品牌及可穿戴吸奶器品类的新帖子+评论，结构化后做轻量舆情分析，通过钉钉 Webhook 推送。

---

## 一、任务全景拆解（第一性原理）

整个系统可拆为 5 层管道：

```
[定时触发] → [数据采集] → [结构化清洗] → [舆情分析] → [推送交付]
   cron         PRAW          pandas         VADER         钉钉Webhook
```

每条管道有独立的输入/输出契约，可单独测试、独立演进。

---

## 二、数据采集 — 对象：核心 Subreddit（已核验 + 补充）

### 2.1 文档中已列出的 Subreddit（优先级排序）

基于文档第 4 章 + 网络调研交叉验证，以下 subreddits 与 Momcozy/可穿戴泵讨论高度相关：

| 优先级 | Subreddit | 规模 | 相关性 | 采集策略 |
|--------|-----------|------|--------|----------|
| **P0** | r/ExclusivelyPumping | ~50k | ★★★★★ 泵奶主阵地，大量选型/对比帖 | 全量 `new` 帖按关键词过滤 |
| **P0** | r/breastfeeding | ~206k | ★★★★☆ 高频 pump 话题 | 全量 `new` 帖按关键词过滤 |
| **P1** | r/workingmoms | ~141k | ★★★★☆ 复工泵奶场景 | 全量 `new` 帖按关键词过滤 |
| **P1** | r/NewParents | ~460k | ★★★☆☆ 高互动方法贴 | 全量 `new` 帖按关键词过滤 |
| **P1** | r/BabyBumps | ~523k | ★★★☆☆ 购买决策/保险选泵 | 全量 `new` 帖按关键词过滤 |
| **P2** | r/beyondthebump | ~300k | ★★★☆☆ 产后泵奶经验 | 全量 `new` 帖按关键词过滤 |
| **P2** | r/FormulaFeeders | ~40k | ★★☆☆☆ 转奶/混合喂养 | 按需采集（仅当提及 pump） |
| **P3** | r/BreastPumping | ~4k | ★★★★☆ 垂直但体量小 | 全量 `new` 帖 |
| **P3** | r/Parenting | ~8.2M | ★★☆☆☆ 话题分散 | 仅 Reddit 搜索针对性抓取 |

### 2.2 额外补充的 Subreddit（调研发现）

| Subreddit | 规模 | 相关性 | 说明 |
|-----------|------|--------|------|
| r/HumansPumpingMilk | ~3k | ★★★★☆ | 泵奶垂直社区，虽小但相关度高 |
| r/breastpumps | ~10k | ★★★★★ | 专门讨论吸奶器，品牌讨论集中 |
| r/Mommit | ~200k | ★★★☆☆ | 妈妈群体，偶尔 pump 讨论 |
| r/pregnant | ~200k | ★★☆☆☆ | 孕期决策阶段 |

### 2.3 采集优先级最终建议

**第一阶段（MVP）：** P0 + P1 = 5 个 subreddits
- r/ExclusivelyPumping, r/breastfeeding, r/workingmoms, r/NewParents, r/BabyBumps

**第二阶段（扩展）：** 加上 r/beyondthebump, r/breastpumps, r/BreastPumping

**第三阶段（全覆盖）：** 加上剩余 subreddits + Reddit 全站搜索兜底

---

## 三、数据采集 — 关键词：三层关键词体系

### 3.1 品牌层（Momcozy 显性提及）

**精确品牌名：**
```
momcozy, Momcozy, MOMCOZY
```

**产品型号（必须与品牌/品类共现）：**
```
M5, M6, M9, S9, S9 Pro, S12, S12 Pro, V1, V2, V2 Pro, M5 Pro
```

**常见变体/拼写错误（调研确认）：**
```
mom cozy, momcozie, momcozi, mom cozie, mom cozy pump
```

### 3.2 品类层（可穿戴/免手吸奶器通用表达）

**核心品类词（英语常用）：**
```
wearable breast pump, wearable pump, hands-free pump, hands free pump,
hands-free breast pump, in-bra pump, cordless breast pump,
wireless breast pump, portable breast pump, all-in-one pump
```

**缩略/口语化表达（Reddit 常见）：**
```
wearables (指 wearable pumps 的简称), hands free (不带 pump),
portable pump, on-the-go pump, discreet pump
```

### 3.3 竞品层（用于品类舆情 + 横评识别）

```
Elvie, Willow, Medela, Lansinoh, Spectra, Philips Avent, eufy,
Motif, Freemie, Fraupow, Tommee Tippee, YOUHA, Zomee, imani,
MomMed, TSRETE, Baby Buddha, Pumpables, Bellababy, Legendairy Milk
```

### 3.4 场景/痛点层（用于过滤高价值帖子）

```
output, supply, emptying, leak, spill, flange, insert, elastic nipples,
noise, cleaning, parts, warranty, customer service, clogged duct,
mastitis, pumping at work, pumping bra, fridge hack, return to work
```

### 3.5 关键词匹配策略

采用**二级筛选**，平衡召回率与精确率：

**L1 — 宽召回（帖子级）：** 在 subreddit `new` 帖中，标题或正文命中任一关键词即纳入候选
- 品类词 OR 品牌词 OR (型号词 AND pump)

**L2 — 精过滤（评论级）：** 对候选帖的评论进行品牌/品类关键词二次匹配
- 确保评论内容与监控目标相关

---

## 四、数据采集 — 方法：技术方案对比与推荐

### 4.1 三种可行方案对比

| 维度 | 方案A: PRAW (官方API) | 方案B: .json 端点 | 方案C: Pushshift替代 (Arctic Shift) |
|------|----------------------|-------------------|--------------------------------------|
| **认证** | OAuth2 (需注册 Reddit App) | 无需认证 | 无需认证 |
| **速率限制** | 100 QPM (OAuth) | ~10-60 RPM (IP-based) | 无实时限制 (月更数据) |
| **时间精度** | 实时，秒级 | 实时，秒级 | **月更，非实时** ❌ |
| **历史数据** | 仅 ~1000 帖/列表 | 仅 ~1000 帖/列表 | 数十亿条 |
| **稳定性** | 官方维护，最稳定 | 非官方接口，可能变动 | 社区维护，有延迟 |
| **部署复杂度** | 中等（需注册App） | 低 | 高（需下载Parquet大文件） |
| **适合场景** | ✅ **日常定时监控** | ✅ **轻量采集** | ❌ 不适合日常监控 |

### 4.2 最终选择：方案 B — .json 公共端点（已确认）

**决策依据：**
1. **零注册成本**：无需创建 Reddit App，无需 OAuth 流程
2. **数据完全够用**：.json 端点返回的数据结构与官方 API 一致（id, title, selftext, created_utc, author, score, num_comments, permalink 等字段齐全）
3. **速率限制可接受**：无认证 ~10-60 RPM per IP，配合 1-2s 请求间隔，对每天一次的采集完全够用
4. **实现简洁**：纯 `requests` + `time.sleep` 即可，依赖最少

**注意事项：**
- 必须设置合法的 `User-Agent` 头（格式：`"VOCMonitor/1.0 (by /u/YOUR_USERNAME)"`）
- 请求间隔 ≥ 2 秒，避免触发 IP 级别限流
- 如果未来采集量增长超过 1000 帖/天，再考虑迁移到 PRAW OAuth

### 4.3 采集算法设计

```
算法：每日定时采集流程（基于 .json 公共端点）

输入：subreddits 列表, keywords 字典, 时间窗口 T (24h = 86400s)
输出：帖子+评论结构化数据

对于每个 subreddit：
    1. GET https://www.reddit.com/r/{subreddit}/new.json?limit=100
       请求头：User-Agent: VOCMonitor/1.0 (by /u/YOUR_USERNAME)
    2. 解析 JSON → data.children 数组
    3. 对于每个帖子 post：
        a. 如果 post.data.created_utc < now - T：跳过（超出时间窗口）
        b. 如果 post.data.created_utc >= now - T 且 标题/正文命中 L1 关键词：
            i.   记录帖子元数据
            ii.  GET https://www.reddit.com/r/{subreddit}/comments/{post_id}.json
                 （该端点返回 [帖子对象, 评论列表]）
            iii. 递归遍历评论树（data.children → replies.data.children）
            iv.  对于每个评论 comment：
                 - 如果 comment.data.created_utc >= now - T（新创建的评论）
                 - 记录评论元数据
            v.   time.sleep(2)  # 请求间隔 ≥2s
        c. 去重：使用 post.id + comment.id 在 SQLite 中 UPSERT
    sleep(2)  # subreddit 切换间隔
```

### 4.4 .json 端点关键 URL 映射

```
# 获取 subreddit 最新帖子（按时间倒序）
https://www.reddit.com/r/{subreddit}/new.json?limit=100

# 获取帖子详情 + 全部评论（返回数组：[post_obj, comment_listing]）
https://www.reddit.com/r/{subreddit}/comments/{post_id}.json

# 分页：使用 after 参数
https://www.reddit.com/r/{subreddit}/new.json?limit=100&after={after_token}

# 搜索（全站兜底）
https://www.reddit.com/search.json?q=momcozy&sort=new&t=day&limit=100
```

### 4.5 认证相关

无需 Reddit App 注册。只需：
1. 设置合法的 `User-Agent` HTTP 头（Reddit 强制要求）
2. 格式：`VOCMonitor/1.0 (by /u/YOUR_REDDIT_USERNAME)`
3. 请求间隔 ≥ 2 秒

**⚠️ 注意**：如果未来发现 IP 被限流（HTTP 429 Too Many Requests），可以：
- 增加 sleep 间隔到 3-5s
- 注册 Reddit App 获取 OAuth 凭证（升级到 100 QPM）
- 使用 `X-Ratelimit-*` 响应头动态调整节奏

---

## 五、结构化数据格式

### 5.1 帖子表 (posts)

```sql
CREATE TABLE IF NOT EXISTS posts (
    id              TEXT PRIMARY KEY,          -- Reddit post ID (如 "1bqyegy")
    subreddit       TEXT NOT NULL,             -- 如 "ExclusivelyPumping"
    title           TEXT NOT NULL,             -- 帖子标题
    selftext        TEXT,                      -- 帖子正文（Markdown）
    author          TEXT,                      -- 作者用户名
    created_utc     REAL NOT NULL,             -- Unix 时间戳
    score           INTEGER,                   -- 赞数
    num_comments    INTEGER,                   -- 评论数
    permalink       TEXT NOT NULL,             -- 固定链接
    url             TEXT,                      -- 帖子 URL
    flair           TEXT,                      -- 帖子标签（如 "Review"）
    matched_kw      TEXT,                      -- 命中的关键词（逗号分隔）
    fetched_at      REAL DEFAULT (unixepoch()) -- 抓取时间
);
```

### 5.2 评论表 (comments)

```sql
CREATE TABLE IF NOT EXISTS comments (
    id              TEXT PRIMARY KEY,          -- Reddit comment ID
    post_id         TEXT NOT NULL,             -- 所属帖子 ID
    parent_id       TEXT,                      -- 父评论 ID（t1_xxx 或 t3_xxx）
    body            TEXT NOT NULL,             -- 评论正文（Markdown）
    author          TEXT,                      -- 作者用户名
    created_utc     REAL NOT NULL,             -- Unix 时间戳
    score           INTEGER,                   -- 赞数
    depth           INTEGER DEFAULT 0,         -- 评论深度
    is_submitter    BOOLEAN DEFAULT 0,         -- 是否为帖子作者
    matched_kw      TEXT,                      -- 命中的关键词
    fetched_at      REAL DEFAULT (unixepoch()),
    FOREIGN KEY (post_id) REFERENCES posts(id)
);
```

### 5.3 运行日志表 (runs)

```sql
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      REAL NOT NULL,
    finished_at     REAL,
    posts_fetched   INTEGER DEFAULT 0,
    comments_fetched INTEGER DEFAULT 0,
    posts_matched   INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running',  -- running/success/failed
    error_message   TEXT
);
```

### 5.4 每日输出：结构化 Excel/CSV 报表

采集完成后，生成两个 Sheet：

**Sheet 1 — 帖子清单：**
| post_id | subreddit | title | selftext | author | created_utc | score | num_comments | permalink | matched_kw | sentiment |

**Sheet 2 — 评论清单：**
| comment_id | post_id | body | author | created_utc | score | depth | matched_kw | sentiment_label | sentiment_score |

---

## 六、舆情分析与洞察引擎

### 6.1 轻量级情感分析

**推荐：VADER (Valence Aware Dictionary and sEntiment Reasoner)**

选择理由：
- 专为社交媒体/短文本优化，Reddit 评论属于典型场景
- 零训练成本，开箱即用
- 正确处理表情符号、程度修饰词、俚语
- 速度极快（纯规则+词典）
- 准确率 75-82%，满足舆情监控需求

**实现：**
```python
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()

def analyze_sentiment(text):
    scores = analyzer.polarity_scores(text)
    compound = scores['compound']
    if compound >= 0.05:
        return 'positive', compound
    elif compound <= -0.05:
        return 'negative', compound
    else:
        return 'neutral', compound
```

### 6.2 舆情分析维度

每条帖子和评论标注以下维度：

| 维度 | 说明 | 取值 |
|------|------|------|
| **情感标签** | VADER compound 分箱 | positive / neutral / negative |
| **情感得分** | VADER compound 原始值 | [-1.0, 1.0] |
| **主题分类** | 基于关键词规则匹配 | 产品评价 / 购买决策 / 使用技巧 / 售后问题 / 竞品对比 / 其他 |
| **品牌归属** | 关联到哪个品牌 | Momcozy / 竞品名 / 多品牌 |
| **痛点标记** | 是否涉及已知痛点 | 产量不足 / 漏奶 / 噪音 / 清洗 / 法兰不适 / 售后 / 其他 |

### 6.3 每日舆情摘要模板

```markdown
# 📊 Momcozy Reddit VOC 日报
**日期**：2026-07-07 | **采集时段**：过去 24h

## 📈 概览
- 相关帖子：X 篇 | 相关评论：Y 条
- 情感分布：😊 正面 A% | 😐 中性 B% | 😟 负面 C%
- 提及 Momcozy 的帖子：M 篇 | 评论：N 条

## 🔥 热门帖子 Top 5
| # | Subreddit | 标题 | 评论数 | 情感 | 链接 |
|---|-----------|------|--------|------|------|

## 📝 Momcozy 提及摘要
- 正面高频词：...
- 负面高频词：...
- 竞品对比中出现频率最高的竞品：...

## ⚠️ 预警信号（如适用）
- [负面] ...
```

---

## 七、钉钉 Webhook 推送

### 7.1 技术参数

| 参数 | 值 |
|------|-----|
| 请求方式 | POST |
| 端点 | `https://oapi.dingtalk.com/robot/send?access_token=ACCESS_TOKEN` |
| 消息类型 | `msgtype: "markdown"` |
| 频率限制 | 每分钟 20 条 |
| 安全方式 | 推荐：加签（HMAC-SHA256） |

### 7.2 推送策略

由于钉钉 Markdown 消息有长度限制且每分钟 20 条，采用**单条聚合推送**策略：

1. **主消息（日报摘要）**：包含概览 + Top 帖子 + 舆情摘要 + 预警
2. **如果帖子数 > 10**：摘要消息 + 附件为结构化 CSV 文件（通过文件上传或外部链接）
3. **如果出现强烈负面信号**：单独发送预警消息（@相关人员）

### 7.3 消息内容结构

```markdown
# 📊 Momcozy Reddit VOC 日报 — 2026-07-07

> 采集时段：2026-07-06 04:00 ~ 2026-07-07 04:00 (北京时间)
> 监控范围：r/ExclusivelyPumping, r/breastfeeding, r/workingmoms, r/NewParents, r/BabyBumps

## 📈 数据概览

| 指标 | 数值 |
|------|------|
| 相关帖子 | 12 |
| 相关评论 | 87 |
| 正面率 | 45% |
| Momcozy 提及 | 5 帖 / 23 评 |

## 🔥 Top 3 帖子

1. **[Best wearable pump for elastic nipples?]** — r/ExclusivelyPumping (34评, 😊正)
   [查看帖子](https://reddit.com/...)
2. ...
3. ...

## ⚠️ 关注信号
- 1 条负面评论提及 M5 漏奶问题
- 与 Eufy S1 Pro 对比中 Momcozy 被提及 3 次

---
*下份报告时间：2026-07-08 04:00*
```

---

## 八、系统架构与调度

### 8.1 整体架构

```
┌──────────────────────────────────────────────────┐
│              调度层（macOS cron）                   │
│         每天 04:00 CST 自动触发                    │
│         crontab: 0 4 * * * cd ... && python main.py│
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│              采集层（requests + .json）             │
│  Reddit .json 端点 → subreddit/new.json           │
│  → keyword filter → post comments                 │
│  → 写入 SQLite（UPSERT 去重）                      │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│              分析层（VADER）                        │
│  情感分析(正/负/中) → 主题分类 → 品牌归属 → 预警判定 │
└──────────────────┬───────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────┐
│             交付层（requests → 钉钉 Webhook）       │
│  生成 Markdown 日报 → HMAC-SHA256 签名 → POST 推送  │
│  生成 CSV 附件 → 保存在 outputs/ 目录               │
└──────────────────────────────────────────────────┘
```

### 8.2 技术栈（已确认）

| 组件 | 方案 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | 系统自带或 brew 安装 |
| Reddit 采集 | requests + .json 端点 | 零认证，2s 间隔 |
| 数据存储 | SQLite（本地 data/ 目录） | 零配置，单文件 |
| 情感分析 | vaderSentiment | 三分类(正/负/中) |
| HTTP 推送 | requests | 钉钉 Webhook POST |
| 调度 | macOS crontab | 每天 04:00 CST |
| 日志 | Python logging → logs/ 目录 | 文件轮转 |

### 8.3 macOS cron 调度配置

```bash
# 编辑 crontab
crontab -e

# 添加以下行：每天北京时间 04:00 执行
0 4 * * * cd /Users/pray/project/Reddit_VOC && /usr/bin/python3 main.py >> logs/cron.log 2>&1
```

**注意事项：**
- macOS 上 cron 需要给予终端/ Python 完全磁盘访问权限（系统设置 → 隐私与安全性）
- Python 路径可用 `which python3` 确认
- 首次部署后手动运行一次验证 `python3 main.py`

### 8.4 项目文件结构

```
Reddit_VOC/
├── main.py                 # 主入口，编排全流程
├── config.py               # 配置文件（subreddits, keywords, webhook_url）
├── .env                    # 敏感信息（webhook_url, webhook_secret, reddit_username）
├── collector/
│   ├── __init__.py
│   ├── fetcher.py           # .json 端点请求 + 重试 + 限流
│   └── scraper.py           # 核心采集逻辑（帖子→评论树→关键词过滤）
├── storage/
│   ├── __init__.py
│   ├── database.py          # SQLite CRUD
│   └── schema.sql           # 建表语句
├── analyzer/
│   ├── __init__.py
│   ├── sentiment.py        # VADER 情感分析
│   ├── classifier.py       # 主题/品牌分类（规则引擎）
│   └── insights.py         # 摘要生成 + 预警判定
├── notifier/
│   ├── __init__.py
│   ├── dingtalk.py         # 钉钉 Webhook 推送（HMAC-SHA256 签名）
│   └── templates.py         # 日报 Markdown 模板
├── tests/
│   ├── test_scraper.py     # 采集逻辑单元测试
│   ├── test_sentiment.py   # 情感分析测试
│   └── test_dingtalk.py    # 推送集成测试
├── logs/                    # 运行日志（自动轮转）
├── data/                    # SQLite 数据库文件
├── outputs/                 # 每日 CSV 输出
├── requirements.txt         # pip install -r requirements.txt
└── README.md                # 运行说明
```

### 8.5 依赖清单 (requirements.txt)

```
requests>=2.31.0
vaderSentiment>=3.3.2
python-dotenv>=1.0.0
```

仅需 3 个核心依赖，极度精简。`sqlite3`, `json`, `logging`, `hmac`, `hashlib` 均为 Python 标准库。

---

## 九、已确认的关键决策 ✅

| 决策项 | 选择 | 理由 |
|--------|------|------|
| **API 方式** | .json 公共端点 | 零注册成本，纯 requests 实现 |
| **部署环境** | macOS 本机 cron | 零成本，本地可控 |
| **评论深度** | 全部评论树 | 避免遗漏嵌套回复中的高价值讨论 |
| **情感分析** | VADER 三分类 | 轻量快速，满足日常监控需求 |
| **数据存储** | SQLite 本地 | 零配置，单文件 |
| **推送方式** | 单条 Markdown 聚合 | 控制在钉钉 20/min 限制内 |
| **时间窗口** | 过去 24h (created_utc) | 新创建帖子+新创建评论，排除旧帖新评 |

---

## 十、可被 Codex 执行的开发-测试-验收计划

### Phase 1: 基础搭建（Day 1-2）

| # | 任务 | 验收标准 | 预估时间 |
|---|------|----------|----------|
| 1.1 | 项目初始化：文件结构 + requirements.txt + .env 模板 | 能 `pip install -r requirements.txt` 成功 | 0.5h |
| 1.2 | Reddit App 注册 + PRAW 连接配置 | `reddit_client.py` 能成功获取 r/ExclusivelyPumping 的 hot 帖子 | 0.5h |
| 1.3 | SQLite 数据库 + Schema 创建 | 能执行 `schema.sql` 建表，插入一条测试数据 | 0.5h |
| 1.4 | 配置文件（subreddits 列表、三层关键词字典） | `config.py` 包含完整的 subreddit 和 keyword 定义 | 0.5h |

### Phase 2: 核心采集（Day 2-3）

| # | 任务 | 验收标准 | 预估时间 |
|---|------|----------|----------|
| 2.1 | subreddit.new() 帖子采集 + 时间窗口过滤 | 运行后能获取 5 个 P0/P1 subreddit 过去 24h 的帖子，存入 posts 表 | 2h |
| 2.2 | L1 关键词过滤（帖子级） | 仅命中关键词的帖子被保留，日志输出过滤量 | 1h |
| 2.3 | 评论采集 + replace_more 展开 | 能获取每个匹配帖子的所有评论，存入 comments 表 | 2h |
| 2.4 | 去重与增量逻辑 | 同一天多次运行不会产生重复数据 | 1h |
| 2.5 | 运行日志 + 错误处理 | runs 表记录每次执行状态，API 异常有重试和日志 | 1h |

### Phase 3: 分析引擎（Day 3-4）

| # | 任务 | 验收标准 | 预估时间 |
|---|------|----------|----------|
| 3.1 | VADER 情感分析集成 | 对采集的评论进行情感标注，输出正/负/中性 + score | 1h |
| 3.2 | 主题分类器（规则引擎） | 根据关键词将帖子/评论分到：产品评价/购买决策/使用技巧/售后问题/竞品对比 | 1.5h |
| 3.3 | 品牌归属标注 | 识别帖子/评论提及的品牌（Momcozy vs 竞品） | 1h |
| 3.4 | 痛点标记 | 识别并标记已知痛点（漏奶/产量/噪音/清洗等） | 1h |
| 3.5 | 日报摘要生成 | 生成包含概览统计 + Top 帖子 + 预警信号的 Markdown 摘要 | 1.5h |

### Phase 4: 推送交付（Day 4）

| # | 任务 | 验收标准 | 预估时间 |
|---|------|----------|----------|
| 4.1 | 钉钉 Webhook 签名与连接 | 能发送测试消息到钉钉群 | 1h |
| 4.2 | Markdown 日报模板 | 日报消息格式美观、信息完整 | 1.5h |
| 4.3 | CSV 导出 + 链接生成 | 完整数据集可导出为 CSV | 0.5h |
| 4.4 | 预警逻辑 | 当负面评论比例 >30% 或出现"mastitis/clogged duct/supply drop"等严重痛点时触发预警 | 1h |

### Phase 5: 集成测试（Day 5）

| # | 任务 | 验收标准 | 预估时间 |
|---|------|----------|----------|
| 5.1 | 端到端测试：手动执行一次完整流程 | 从采集到推送全链路跑通，钉钉群收到日报 | 2h |
| 5.2 | 时间窗口边界测试 | 验证 24h 窗口边界（刚好 24h 前的帖子被排除，23h59min 的帖子被包含） | 1h |
| 5.3 | 异常场景测试 | API 限流/超时/网络断连时能正确重试和记录错误 | 1h |
| 5.4 | 空数据场景 | 当 24h 内无匹配帖时，日报显示"今日无相关讨论"而非报错 | 0.5h |

### Phase 6: 部署与监控（Day 5-6）

| # | 任务 | 验收标准 | 预估时间 |
|---|------|----------|----------|
| 6.1 | Cron/GitHub Actions 配置 | 每天 04:00 CST 自动触发 | 0.5h |
| 6.2 | 首次自动化运行验证 | 等待到调度时间，确认自动推送成功 | 实测 |
| 6.3 | 运行监控（连续 3 天观察） | 连续 3 天正常运行，无异常 | 3 天观察期 |
| 6.4 | 关键词与 subreddit 调优 | 根据 3 天实际数据调整关键词和 subreddit 范围 | 1h |

---

## 十一、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Reddit API 限流/封禁 | 采集中断 | 1) 请求间隔 ≥1s 2) 指数退避重试 3) 监控 X-Ratelimit-* 头 |
| 关键词误匹配/漏匹配 | 数据质量差 | 持续观察采集结果，建立停用词/排除规则 |
| 钉钉 Webhook 限流 (20/min) | 推送失败 | 聚合为单条消息，避免分条发送 |
| 时间窗口偏差（UTC vs CST） | 采集窗口不准 | 统一使用 UTC+8 转换，单元测试覆盖 |
| Momcozy 讨论量过低 | 日报内容空洞 | 设置最低阈值（如 < 3 条时精简推送） |
| API Key 泄露 | 安全风险 | 使用 .env + .gitignore，不上传代码仓库 |

---

## 十二、后续迭代方向（V2+）

1. **引入 LLM 做深度评论摘要**：对每日 Top 评论做 GPT/Claude 摘要
2. **趋势追踪**：7 日/30 日滚动情感趋势图
3. **竞品对比报告**：定期生成 Momcozy vs Elvie/Willow/Eufy 的 Reddit 声量对比
4. **多平台扩展**：加入 TikTok/YouTube/Instagram 评论区监控
5. **邮件/飞书多渠道推送**

---

*文档版本：v1.0 | 生成日期：2026-07-07 | 基于深度网络调研 + 项目文档*
