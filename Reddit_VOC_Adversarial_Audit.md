# Reddit Momcozy VOC 监控系统 — 对抗性审计报告与修正方案

> 审计日期：2026-07-07 | 审计方法：逐层假设攻击 + 网络验证 | 严重程度：🔴🔴🟡🟢

---

## 0. 审计摘要

**原方案存在一个致命缺陷和一个高风险假设。**

致命缺陷：`.json` 公共端点已于 2026 年 5 月 28 日被 Reddit 关闭（距今天仅 6 周），所有未认证请求返回 403。原方案的核心采集方法完全失效。

高风险假设：macOS cron 调度的可靠性假设未经验证；关键词系统的精确率/召回率边界未定义；时间窗口的 UTC/CST 转换未考虑夏令时。

**审计结论：方案必须重构采集层。** 建议采用 RSS 作为当前过渡方案，同时建立通往 OAuth API 的升级路径。

---

## 1. 攻击面 1：采集方法 — 🔴 致命

### 1.1 原方案假设

> 使用 `requests.get("https://www.reddit.com/r/{sub}/new.json")` 获取帖子，`.json` 端点零认证。

### 1.2 审计发现：此方法已彻底失效

| 验证点 | 状态 | 证据 |
|--------|------|------|
| `.json` 端点可用性 | ❌ 已关闭 | 2026-05-28 r/modnews 公告，全部未认证 .json 返回 403 |
| `.json` 端点响应 | ❌ HTTP 403 | "blocked by network security"，无视 User-Agent |
| 旧帖 .json 是否受影响 | ❌ 全部 | 包括 old.reddit.com/*.json 同样被封 |
| User-Agent 绕过 | ❌ 无效 | Reddit 使用 TLS 指纹识别，generic HTTP 客户端直接拒绝 |
| 住宅代理绕过 | ❌ 无效 | 此阻断是端点级的，非 IP 级 |

**影响：原始 P0 需求"每天 04:00 自动采集"完全无法执行。** 如果不重建采集层，整个项目为零。

### 1.3 替代方案可行性矩阵

| 替代方案 | 可用性 | 数据完整度 | 稳定性 | 零成本 | 推荐度 |
|----------|--------|-----------|--------|--------|--------|
| **RSS 订阅 (.rss)** | ✅ 仍工作 | ⚠️ 中等 | 🟡 有被关风险 | ✅ | ⭐⭐⭐⭐ |
| **OAuth API (PRAW)** | ✅ 官方 | ✅ 完整 | ✅ 最稳定 | ⚠️ 需注册 | ⭐⭐⭐⭐⭐ |
| **old.reddit.com HTML** | ✅ 仍工作 | ⚠️ 中等 | 🟡 脆弱 | ✅ | ⭐⭐⭐ |
| **Apify/第三方服务** | ✅ | ✅ 完整 | ✅ | ❌ 付费 | ⭐⭐⭐ |
| **Arctic Shift** | ✅ | ❌ 月更 | ✅ | ✅ | ⭐（不适配） |

### 1.4 推荐方案：RSS 优先 + OAuth 升级路径

**第一阶段（当前可行，立即部署）：RSS 端点**

```
# 获取 subreddit 新帖
GET https://www.reddit.com/r/{subreddit}/new/.rss
→ 返回 ~25 条最近帖子（含标题、正文、作者、时间戳、链接）

# 获取帖子评论（扁平列表）
GET https://www.reddit.com/r/{subreddit}/comments/{post_id}/{slug}/.rss
→ 返回 ~100 条评论（扁平列表，无嵌套）

# 搜索（需限定 subreddit）
GET https://www.reddit.com/r/{subreddit}/search.rss?q={query}&restrict_sr=on&sort=new
```

**RSS 的限制与缓解：**

| 限制 | 严重程度 | 缓解措施 |
|------|---------|----------|
| ~25 条/次，无分页 | 🟡 中等 | 对 5 个 P0 subreddits 分别请求，每日总量 ~125 条帖，足够覆盖 24h 窗口 |
| 无 upvote score | 🟡 中等 | 使用评论数（RSS 中可通过解析获取）作为替代参与度指标 |
| 评论扁平无嵌套 | 🟡 中等 | 通过 parent_id（RSS 的 `<link>` 或 `<id>` 可推导）手动重建部分嵌套关系 |
| 全局搜索被限 | 🟡 中等 | 改为逐 subreddit 搜索 + 全站搜索尝试。如果全站搜索不可用，仅靠 subreddit 级搜索也能覆盖 P0 需求 |
| RSS 限流（1次/分钟全局） | 🔴 高 | 加入个性化 RSS 凭证（`user=` + `feed=` 参数），间隔 ≥60s |
| 无 subreddit subscriber 数量 | 🟢 低 | 不影响舆情分析核心需求 |
| Reddit 可能后续关闭 RSS | 🟡 中等 | 方案已预留 OAuth 升级路径（见下） |

**第二阶段（稳定性升级）：注册 Reddit OAuth App → PRAW**

RSS 被 Reddit 标记为"下一个关闭目标"，OAuth API 是唯一长期稳定的路径。升级触发条件：
- RSS 开始不稳定（频繁 429 / 空响应）
- Reddit 宣布关闭 RSS
- 采集需求扩展到更多 subreddits

注意：self-service app 注册已于 2025 年 11 月结束，现需 pre-approval。需通过 Reddit 的 Responsible Builder Policy 审核流程。

---

## 2. 攻击面 2：时间窗口逻辑 — 🟡 中等风险

### 2.1 原方案假设

> 每天 04:00 CST 执行，采集 `created_utc` 在过去 86400 秒内的帖子。

### 2.2 问题清单

| 问题 | 风险 | 说明 |
|------|------|------|
| **CST 与北京时间混用** | 🟡 | 中国时区正式名称为 CST (China Standard Time, UTC+8)。但 CST 在北美也指 Central Standard Time (UTC-6)。代码中应使用 `Asia/Shanghai` 消除歧义 |
| **夏令时** | 🟢 | 中国不使用夏令时，对采集窗口无影响 |
| **时间窗口边界模糊** | 🟡 | 如果 04:00 执行但采集耗时 10 分钟（RSS 有限流），则边界帖可能跨越两天。需要固定 `now = 04:00 CST` 而非 `time.time()` |
| **UTC 转 CST 精度** | 🟢 | `created_utc` 是 float，精度足够 |
| **RSS 中时间字段** | 🟡 | RSS 用 `<updated>` 字段（ISO 8601），需额外解析。与 JSON 的 `created_utc` 字段不同 |

### 2.3 修正

```python
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

# 固定执行时间基准，避免采集延迟导致边界偏移
EXECUTION_TIME = datetime.now(CST).replace(hour=4, minute=0, second=0, microsecond=0)
WINDOW_START = EXECUTION_TIME - timedelta(hours=24)  # 昨天 04:00 CST
# 换算为 UTC timestamp 用于比较 RSS 中的时间
WINDOW_START_UTC = WINDOW_START.astimezone(timezone.utc)
```

---

## 3. 攻击面 3：关键词系统 — 🟡 中等风险

### 3.1 误匹配（False Positive）风险

| 场景 | 示例 | 影响 |
|------|------|------|
| 品牌名出现在非品牌上下文中 | "mom cozy" 可能指"妈妈舒适"而非品牌名 | 低，wholesome 语境仍可能是品牌相关内容 |
| 型号缩写冲突 | "M5" 也指 BMW M5 车型、"S9" 也指 Samsung S9 手机 | 🔴 高！在 r/Parenting 等通用 subreddit 中可能出现 |
| 品类词过于宽泛 | "portable" 可能在非泵奶语境出现 | 🟡 中等 |
| wearable 多义 | "wearable" 也指 Apple Watch / 智能穿戴设备 | 🟡 中等 |

### 3.2 漏匹配（False Negative）风险

| 场景 | 示例 | 影响 |
|------|------|------|
| 拼写变体 | momcozi, mom cozy, momcozyy | 🟡 需建立模糊匹配规则 |
| 简称/代称 | "MC" (指 Momcozy), "the m5 one" | 🔴 可能遗漏有价值的讨论 |
| 无品牌提及的品类讨论 | "any good wearable pumps under $100?"（暗指 Momcozy 价位） | 🟡 品类舆情会被品类关键词覆盖 |
| 图片/视频帖子 | 标题空、正文空，关键词匹配失效 | 🟡 依赖评论区文字 |

### 3.3 修正建议

```python
# 风险缓解措施：

# 1. 型号缩写加限定（需与 pump 或 breast 共现）
MODEL_QUALIFIED = {
    "M5": ["pump", "breast", "momcozy", "wearable", "nursing", "milk"],
    "M6": ["pump", "breast", "momcozy", "wearable", "nursing", "milk"],
    "S9": ["pump", "breast", "momcozy", "wearable", "nursing", "milk"],
    # ...
}

# 2. 添加排除规则（False Positive 降噪）
EXCLUDE_PHRASES = [
    "BMW M5", "Samsung S9", "Galaxy S9",  # 型号名冲突
]

# 3. 模糊匹配（编辑距离 ≤ 1）
def fuzzy_match(text, target, max_distance=1):
    # 针对如 "momcozi", "mom cozie" 等变体
    pass

# 4. Subreddit 加权（降低通用 subreddit 中的关键字权重阈值）
SUBREDDIT_CONTEXT = {
    "ExclusivelyPumping": 1.0,  # 高相关性，直接匹配
    "breastfeeding": 0.9,
    "Parenting": 0.3,          # 低相关性，需要更强的信号
}
```

---

## 4. 攻击面 4：RSS 数据解析 — 🟡 中等风险

### 4.1 RSS 字段映射问题

| 原始方案字段 (JSON) | RSS 对应字段 | 是否可用 | 备注 |
|---------------------|-------------|----------|------|
| `id` | `<id>` | ✅ | 格式 `t3_xxxxx`，可提取 post ID |
| `title` | `<title>` | ✅ | |
| `selftext` | `<content>` / `<description>` | ✅ | |
| `author` | `<author><name>` | ✅ | |
| `created_utc` | `<updated>` | ⚠️ | ISO 8601 格式，非 UTC timestamp，需转换 |
| `score` | ❌ | ❌ 不可用 | RSS 不含评分数据 |
| `num_comments` | ❌ | ❌ 不可用 | 无直接字段，需通过评论 RSS 间接计数 |
| `permalink` | `<link>` | ✅ | |
| `subreddit` | `<category>` | ⚠️ | 需解析 |
| `flair` | ❌ | ❌ 不可用 | |

### 4.2 需要调整的数据 schema

原方案中的 `score`（点赞数）在 RSS 模式下不可用。需替换为替代指标：
- **comment_count**：通过评论 RSS 的实际返回数计算（而非 Reddit 官方的 num_comments）
- **RSS 无 score 则舆情分析只能用文本情感，缺乏"高赞负面"这种组合信号**

### 4.3 RSS 评论获取注意事项

```
GET /r/{sub}/comments/{post_id}/{slug}/.rss
```
- 评论是扁平 `<entry>` 列表
- `<link>` 字段可推导 parent 关系（格式：`/r/{sub}/comments/{post_id}/{slug}/{comment_id}`）
- **无 depth 字段**（原方案需要）
- 最多约 100 条评论

---

## 5. 攻击面 5：macOS cron 调度 — 🟡 中等风险

| 问题 | 风险 | 说明 |
|------|------|------|
| **系统休眠** | 🔴 | macOS 默认合盖/空闲后休眠，cron 不执行。需设置 `pmset` 或使用 `caffeinate` |
| **权限隔离 (TCC)** | 🔴 | macOS 安全框架可能阻止 cron 访问网络或文件。需在"系统设置→隐私→完全磁盘访问权限"中授权 `/usr/sbin/cron` |
| **Python 路径漂移** | 🟡 | brew 更新可能改变 python3 路径。建议使用绝对路径或 `#!/usr/bin/env python3` shebang |
| **环境变量缺失** | 🟡 | cron 不加载 shell profile，需在 crontab 中显式设置 PATH 和 HOME |
| **日志积累** | 🟢 | `>> logs/cron.log 2>&1` 会无限增长，需 logrotate |

### 修正的 crontab 配置

```bash
# 完整的 crontab 条目
PATH=/usr/local/bin:/usr/bin:/bin
HOME=/Users/pray

# 每天北京时间 04:00 执行
0 4 * * * cd /Users/pray/project/Reddit_VOC && /usr/local/bin/python3 main.py >> logs/cron_$(date +\%Y\%m\%d).log 2>&1
```

---

## 6. 攻击面 6：钉钉推送 — 🟢 低风险

| 检查项 | 状态 | 说明 |
|--------|------|------|
| Markdown 长度限制 | 🟢 | 钉钉没有明确的 Markdown body 硬限制，但建议控制在 20KB 以内 |
| 速率限制 (20/min) | 🟢 | 每天只发 1 条聚合消息，远低于限制 |
| HMAC-SHA256 签名 | 🟢 | 有成熟方案，Python stdlib 可用 |
| 网络安全 | 🟢 | 钉钉 Webhook 是标准 HTTPS POST |
| 特殊字符转义 | 🟡 | Markdown 消息中的特殊字符（`>` `#` `*` 等）需注意，特别是 Reddit 评论包含的 Markdown 语法 |

---

## 7. 攻击面 7：异常处理与状态一致性 — 🟡 中等风险

| 场景 | 原方案覆盖 | 风险 | 修正 |
|------|-----------|------|------|
| 部分 subreddit 采集失败 | ❌ | 日报数据不完整但无感知 | 每个 subreddit 独立 try/except，失败的不影响其他；日报中注明"x/5 个 subreddits 采集成功" |
| 网络完全断连 | ⚠️ | 可能有错误日志但无重试 | 添加 3 次重试 + 指数退避（30s, 60s, 120s） |
| RSS 返回空（新帖不足 25 条不报错，但无数据） | ❌ | 若 Reddit 实际有帖但 RSS 不返回 | 添加 RSS 返回条目计数，与预期对比 |
| SQLite 写入失败 | ❌ | 磁盘满等导致静默丢失 | `INSERT` 前后添加 try/except + 记录到 runs 表 |
| 重复运行 | ❌ | cron 配置错误可能导致同一天跑两次 | 在 runs 表检查当天是否已有成功记录 |
| 钉钉推送失败 | ⚠️ | 如果 Webhook 失败，数据已采集但未送达 | 推送失败后保留数据，下一天补推摘要 |

---

## 8. 攻击面 8：情感分析 — 🟢 低风险（但有限制）

| 问题 | 风险 | 说明 |
|------|------|------|
| VADER 对医疗/哺乳术语的准确率 | 🟡 | "supply dropped" / "mastitis" 可能被中性化，而非识别为负面 |
| 讽刺/反讽 | 🟡 | "Oh great, another pump that leaks everywhere" — VADER 可能判为正向 |
| Reddit 特有的俚语/缩写 | 🟡 | "FTM" / "EP" / "LO" 等 VADER 不认识，但不影响核心情感判断 |
| 短评论偏中性 | 🟢 | "Works great!" 可正确识别；可以接受短评论准确性 |
| RSS 无 score | 🔴 | 原方案依赖赞数辅助判断评论重要性。**RSS 无 score 是最关键的舆情分析降级！**高赞评论被扁平化，失去了社区投票信号 |

**RSS 无 score 的缓解：**
- 评论数替代：如果某帖子有大量评论（通过评论 RSS 计数），即使无 score 也可识别为"热门"
- 文本强度：VADER compound 绝对值 > 0.5 的强情感评论标记为"关键评论"
- 当升级到 OAuth API 后，可以补全 score 信号

---

## 9. 修正后的完整方案

### 9.1 技术栈更新

| 组件 | 原方案 ❌ | 修正方案 ✅ |
|------|----------|--------------|
| 数据采集 | `requests` + `.json` 端点 | **Phase 1:** `requests` + `.rss` 端点；**Phase 2:** PRAW + OAuth API |
| 数据解析 | `json.loads()` | `xml.etree.ElementTree` 或 `feedparser` |
| 帖子识别 | `created_utc` timestamp 过滤 | `<updated>` ISO 8601 时间过滤 |
| 评论结构 | JSON 嵌套树 (`replies.data.children`) | RSS 扁平 `<entry>` 列表，通过 `<link>` 重建层级 |
| 参与度指标 | `score` / `num_comments` | 评论数（通过 RSS 计数）替代 |
| 情感分析 | VADER（不变） | VADER（不变）+ 增强：对 RSS 丢失 score 信号做文本强度补偿 |
| 存储 | SQLite（不变） | SQLite（不变，schema 中 score 改为可选字段） |
| 推送 | 钉钉 Webhook（不变） | 钉钉 Webhook（不变） |

### 9.2 RSS 环境下的新依赖

```txt
# requirements.txt (修正版)
requests>=2.31.0
feedparser>=6.0.11       # RSS/Atom 解析（新增）
vaderSentiment>=3.3.2
python-dotenv>=1.0.0
```

### 9.3 新增的 fallback 机制

```python
# 主采集器伪代码

def collect_daily():
    results = {"posts": [], "comments": [], "errors": [], "method": None}
    
    # 尝试 RSS（当前唯一可行的零认证方案）
    try:
        results["method"] = "RSS"
        for sub in SUBREDDITS:
            try:
                feed = fetch_rss(f"https://www.reddit.com/r/{sub}/new/.rss")
                recent_posts = filter_by_time(feed.entries, WINDOW_START_UTC)
                matched_posts = keyword_filter(recent_posts)
                for post in matched_posts:
                    comments_feed = fetch_rss(post.comments_rss_url)
                    # ...
                results["posts"].extend(matched_posts)
            except Exception as e:
                results["errors"].append(f"{sub}: {e}")
                continue  # 一个 subreddit 失败不影响其他
    except Exception as e:
        results["errors"].append(f"RSS: {e}")
    
    # Phase 2 备用：如果 OAuth 凭证可用，用 API 补充 score 数据
    if OAUTH_AVAILABLE:
        # 交叉验证：用 PRAW 获取今日已采集帖子的 scores
        enrich_with_scores(results["posts"])
    
    return results
```

### 9.4 修正后的执行计划

| Phase | 任务 | 变化 | 预估时间 |
|-------|------|------|----------|
| **1.1** | 项目初始化 + 依赖安装 | 新增 `feedparser` | 0.5h |
| **1.2** | RSS 端点连接验证 | 🆕 改为测试 `.rss` 端点而非 `.json` | 0.5h |
| **1.3** | SQLite schema（score 改为可选） | 修改 schema | 0.5h |
| **2.1** | RSS 帖子采集 + 时间过滤 | 🆕 改为 XML 解析 + ISO 8601 | 2h |
| **2.2** | RSS 评论采集 | 🆕 扁平列表解析 + 链接推导层级 | 2h |
| **2.3** | 关键词匹配（增强版，含型号限定） | 改进 | 1.5h |
| **2.4** | 去重与增量 + 错误处理增强 | 新增：重复运行检查、部分失败标记 | 1.5h |
| **3.x** | 分析与推送（不变） | VADER + 钉钉 | 3.5h |
| **4.x** | 测试 + 部署 | 新增 macOS 权限配置 | 2h |
| **5.x** | 观察期 + 调优 | 连续 3 天 + RSS 稳定性监控 | 3d |
| **6** | OAuth API 升级 | 申请 Reddit App → PRAW 迁移 | 未来 |

---

## 10. 风险热图

| 风险 | 概率 | 影响 | 风险等级 | 缓解状态 |
|------|------|------|----------|----------|
| .json 端点不可用 | **100%** | 致命 | 🔴🔴🔴 | ✅ 已转向 RSS |
| RSS 被 Reddit 关闭 | **30-50%** (6 个月内) | 高 | 🔴🔴 | ⚠️ 预留 OAuth 路径 |
| RSS 限流过严 | **20%** | 中 | 🟡 | ✅ 加入个性化凭证参数 |
| macOS 休眠打断 cron | **40%** | 中 | 🟡 | ✅ 配置 caffeinate / pmset |
| 关键词误匹配（M5=BMW） | **30%** | 低 | 🟡 | ✅ 型号限定+排除规则 |
| RSS 无 score 降低舆情质量 | **100%** | 中 | 🟡 | ⚠️ 文本强度补偿，无完美替代 |
| 钉钉推送失败 | **5%** | 低 | 🟢 | ✅ 重试+摘要补推 |
| 时间窗口偏差 | **10%** | 低 | 🟢 | ✅ 固定基准时间 |
| 网络断连 | **5%** | 中 | 🟢 | ✅ 3次重试+指数退避 |

---

## 11. 最终建议

**立即行动（本周）：**
1. 以 RSS 方案构建 MVP，这仍然是当前唯一可行的零认证路径
2. 第一时间验证 RSS 端点的实际可用性（尤其是限流情况）
3. 确保 macOS cron 权限配置正确

**短期行动（2 周内）：**
1. 申请 Reddit OAuth App（Responsible Builder Policy 流程）
2. 观察 RSS 稳定性，收集限流数据

**中期行动（1 个月内）：**
1. 迁移到 OAuth API → PRAW（恢复 score 数据）
2. 拓展到更多 subreddits

**不接受方案：**
- ❌ 等待 .json 端点恢复（不会恢复，这是 Reddit 商业化战略的核心）  
- ❌ 使用 Arctic Shift 月更数据（无法满足每日监控需求）
- ❌ 仅靠 old.reddit.com HTML 爬取（需要住宅代理，维护成本高且不做运维的情况下极易被封）

---

*审计报告版本：v1.0 | 审计日期：2026-07-07 | 基于实时网络验证*
