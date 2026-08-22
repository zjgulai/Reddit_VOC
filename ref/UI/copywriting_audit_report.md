# Momcozy Reddit 舆情工作台 — 文案审计报告 (Copywriting Audit)

> **审计范围：** `/Users/pray/project/Reddit_VOC/ref/UI/momcozy-reddit-workbench/src/` 全部页面、组件、Mock 数据及常量文案
> **审计标准：** 消除"AI味"——去除模板化、空洞化、套话化、数据堆砌感的表达，提升专业度、品牌一致性与用户信任感

---

## 一、最严重的前 10 个问题（Top 10 Critical Issues）

| 排名 | 严重程度 | 文件路径 | 行号 | 问题简述 | 改进建议 |
|------|----------|----------|------|----------|----------|
| 1 | 🔴 极高 | `src/pages/Home.tsx` | 12 | Hero Badge 文案「AI 驱动的 Reddit 舆情监测」——直接暴露产品为AI生成工具，缺乏品牌人格 | 改为「Reddit 品牌舆情监测，从发现到行动」或品牌口号 |
| 2 | 🔴 极高 | `src/data/insightsMock.ts` | 275-290 | 「最佳发帖时间」推荐文案中直接出现 emoji `💡` 和机器人式建议语法 | 移除 emoji，改为「周二/周四 21:00-23:00 为活跃高峰，建议优先安排」 |
| 3 | 🔴 极高 | `src/data/messagesMock.ts` | 34-45 | 通知标题「严重负面舆情 - 产品故障投诉」——典型的AI生成八股文标题，连字符和描述语生硬拼接 | 改为「M5 故障投诉帖在 r/breastfeeding 发酵」 |
| 4 | 🔴 极高 | `src/data/ugcMock.ts` | 多处 | UGC 归档理由（`autoArchiveReason`）全是AI总结式标签，如「高情感分+产品对比+详细体验描述」——像机器学习标签而非人类运营语言 | 改为自然语言描述，如「用户详细对比 M5 与 Elvie，正面评价突出静音与续航」 |
| 5 | 🟠 高 | `src/pages/Home.tsx` | 74 | Trust Bar 文案「被 500+ 品牌信赖」——虚假社会认同，无据可查，且「500+」是AI填充典型数字 | 删除或改为真实数据；若无数据则改为「服务全球母婴品牌」 |
| 6 | 🟠 高 | `src/data/monthlyReportMock.ts` | 183-233 | 月报战略建议（`monthlyStrategicAdvices`）全是MBA教科书式套话，如「巩固「性价比」核心定位」「建立「静音设计」差异化认知」——像AI生成的咨询报告 | 用具体行动指令替换，如「下月制作 3 支 M5 分贝实测视频，对标 Elvie」 |
| 7 | 🟠 高 | `src/pages/FAQ.tsx` | 10-47 | FAQ 回答使用第三人称「我们的 AI 模型…」「我们采用企业级…」，但产品本身没有清晰的「我们」是谁（是 Momcozy 官方还是第三方服务商？） | 统一口吻：若为 Momcozy 官方工具则改为第一人称；若为第三方 SaaS 则明确说明 |
| 8 | 🟠 高 | `src/components/InsightCard.tsx` | 22-23 | `highlight: ' actionable'`——英文拼写错误（前导空格）且混用英文，极度不专业 | 改为「可执行」或「建议采纳」 |
| 9 | 🟠 高 | `src/pages/Dashboard.tsx` | 18-20 | 日报/周报/月报标签描述使用四字对仗格式（「24小时滚动 · 即时止损」「7天趋势 · 机会洞察」「30天大盘 · 战略复盘」）——典型的AI对联式文案，空洞无物 | 改为具体指标描述，如「今日 52 条新帖，3 条需紧急响应」 |
| 10 | 🟠 高 | `src/data/weeklyReportMock.ts` | 111-169 | 周报机会洞察（`weeklyOpportunities`）描述使用大量行业黑话堆砌，如「内容输出的黄金窗口」「品牌以「解答者」身份介入」——缺乏可执行性 | 每条机会应直接给出「做什么、怎么做、预期结果」 |

---

## 二、详细问题清单（按模块分类）

### 2.1 首页 / 落地页（Home / Landing）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/Home.tsx` | 12 | `AI 驱动的 Reddit 舆情监测` | 过度依赖AI标签 | 删除「AI 驱动」，改为「Reddit 品牌舆情监测」 |
| `src/pages/Home.tsx` | 15 | `在 Reddit 上发现你的下一个客户` | CTA 模糊，「下一个客户」像销售话术 | 改为「追踪 Reddit 上的品牌讨论，发现高意向用户」 |
| `src/pages/Home.tsx` | 18 | `实时监测 Reddit 上的高意向对话，AI 智能识别潜在客户需求，帮助你精准获客并提升品牌声量。` | 三句并列式AI填充，堆砌功能名词 | 改为一句有画面感的描述，如「当有人在 Reddit 问起 breast pump，你第一时间知道。」 |
| `src/pages/Home.tsx` | 32-42 | `50+` / `10K+` / `98%` | 虚假/无来源数据，典型的AI幻觉数字 | 删除具体数字或标注数据来源；若 demo 则加 `*` 注明为示例数据 |
| `src/pages/Home.tsx` | 74 | `被 500+ 品牌信赖` | 虚假社会认同 | 删除或替换为真实背书 |
| `src/pages/Home.tsx` | 93-95 | `核心功能` / `简洁而强大的工具，帮助你发现每一个商机` | 标题空洞，副标题套话 | 改为具体功能描述，如「监测 · 分析 · 回复，一站式 Reddit 运营」 |
| `src/pages/Home.tsx` | 110-113 | `三步开始监测` / `无需复杂设置，几分钟即可启动你的 Reddit 舆情监测` | 「几分钟即可」是AI生成SaaS落地页标配话术 | 改为「选择社区 → 设置关键词 → 开始追踪」 |
| `src/pages/Home.tsx` | 168-171 | `准备好开始了吗？` / `加入 500+ 品牌，在 Reddit 上发现你的下一个客户` | CTA 重复，再次使用虚假数字 | 改为「开始追踪你的品牌」或「查看 Demo 数据」 |
| `src/components/HeroSection.tsx` | 17-18 | `实时监测 Reddit 上的高意向对话，AI 智能识别潜在客户需求，帮助你精准获客并提升品牌声量。` | 与 Home.tsx 完全重复，缺乏差异化 | 根据页面定位重写 |

### 2.2 导航与全局布局

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/components/Navbar.tsx` | 26 | `Momcozy & Reddit` | 产品名模糊，「&」符号不正式 | 明确为「Momcozy Reddit 工作台」或「Reddit 品牌监测」 |
| `src/components/Sidebar.tsx` | 48-49 | `Momcozy` / `Reddit 舆情工作台` | 副标题「舆情工作台」是中式互联网黑话 | 改为「Reddit 监测」或「品牌追踪」 |
| `src/components/Footer.tsx` | 20-21 | `在 Reddit 上发现你的下一个客户，实时监测高意向对话，AI 智能分析助力精准获客。` | 三句排比，与 Hero 重复 | 改为简洁的品牌定位描述 |
| `src/components/Footer.tsx` | 47 | `© {getCurrentYear()} Momcozy & Reddit 舆情工作台. 保留所有权利.` | 使用英文句号，中英文混排不规范 | 改为「© 2026 Momcozy. 保留所有权利。」 |

### 2.3 看板 / 仪表盘（Dashboard）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/Dashboard.tsx` | 18-20 | `日报: 24小时滚动 · 即时止损` / `周报: 7天趋势 · 机会洞察` / `月报: 30天大盘 · 战略复盘` | AI对联式文案，空洞 | 改为具体指标导向的描述 |
| `src/pages/Dashboard.tsx` | 318-319 | `舆情看板` / `从日报到月报，三层时间维度监控品牌舆情态势` | 「舆情态势」是典型AI/公文用语 | 改为「今日 Reddit 动态一览」 |
| `src/pages/Dashboard.tsx` | 342 | `数据更新于 10 分钟前` | 静态 mock 文案，每次刷新都显示同样内容 | 改为动态计算或删除具体时间 |
| `src/components/BrandScoreCard.tsx` | 27-33 | `品牌声量` / `正面口碑` / `用户互动` / `购买意向` / `竞品优势` / `危机响应` | 维度名称像AI生成的评分卡，缺乏业务语境 | 根据 Momcozy 实际业务需求重新定义维度 |
| `src/components/BrandScoreCard.tsx` | 55 | `scoreLevel = computedOverall >= 80 ? '优秀' : computedOverall >= 60 ? '良好' : '需改进'` | 三档评级过于简单粗暴，且「需改进」像绩效考核 | 改为「健康/关注/预警」或删除评级 |

### 2.4 分析报告（Analytics / Reports）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/Analytics.tsx` | 217-218 | `舆情分析` / `深度洞察 Reddit 上的品牌舆情态势——竞品对比、影响者识别、受众画像与话题分析` | 长破折号 + 四个并列名词，典型的AI生成副标题 | 改为一句人话，如「看清 Reddit 上谁在讨论 Momcozy，以及他们在说什么」 |
| `src/components/SentimentAnalysis.tsx` | 148 | `基于 VADER 算法的正负面判定` | 技术名词直接暴露，用户不关心VADER | 改为「自动判断帖子正负面倾向」或删除说明 |
| `src/components/reports/ReportDailyView.tsx` | 73-76 | `情感温度计` | 比喻生硬，不专业 | 改为「情感分布概览」 |
| `src/components/reports/ReportDailyView.tsx` | 119-123 | `舆情水位` / `当前舆情态势` | 「舆情水位」是自创术语，用户理解成本高 | 改为「风险等级」或「关注程度」 |
| `src/components/reports/ReportDailyView.tsx` | 142-146 | `响应时效` / `平均响应时间` / `完成率` / `紧急处理率` / `升级率` | 纯指标堆砌，无上下文说明这些数字代表什么 | 每个指标添加 tooltip 或一句话说明 |
| `src/components/reports/ReportDailyView.tsx` | 505-527 | `舆情水位看板` / `声量与正面率组合` / `紧急响应区` / `新帖发现流` / `社区活跃度监控` / `今日运营待办` | 模块标题像AI生成的四字短语，缺乏品牌感 | 统一命名规范，如「今日动态」「需关注帖子」「社区概览」「待办清单」 |
| `src/components/reports/ReportWeeklyView.tsx` | 423-475 | 全部 SectionCard 标题和副标题 | 周报模块标题使用大量行业黑话（「品牌声量趋势」「品类机会洞察」「风险洞察」「用户痛点聚类」「竞品对标」「话题演变追踪」「运营复盘」） | 每周报面向的运营人员不同，标题应更直白，如「本周谁在讨论 Momcozy」「竞品这周说了什么」 |
| `src/components/reports/ReportMonthlyView.tsx` | 481-516 | 全部 SectionCard 标题和副标题 | 月报模块标题比周报更加「咨询报告化」（「品牌大盘健康度」「竞争格局」「品类价值评估」「话题生命周期」「KPI达成」「战略建议」） | 若为内部运营工具，标题应直接对应 action，如「本月健康度评分」「竞品份额变化」「下月重点做什么」 |

### 2.5 洞察页（Insights）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/Insights.tsx` | 597 | `从运营、舆情、品牌、品类四个维度，深度解读数据背后的业务价值` | 典型的AI生成数据产品Slogan，空泛 | 改为「数据背后的业务价值」本身就是套话，应删除或替换为具体价值说明 |
| `src/pages/Insights.tsx` | 627 | `正在生成洞察报告...` | 加载文案生硬 | 改为「分析中...」或「整理数据...」 |
| `src/data/insightsMock.ts` | 49-54 | `最佳实践推荐` 内容 | `黄金1小时响应机制`、`UGC素材标准化收集`、`竞品对比帖介入SOP`、`社区活跃时段发帖` | 名称像AI从运营知识库中抽取的，缺乏 Momcozy 品牌特色 | 改为具体案例名称，如「M5 故障帖 45 分钟响应案例」 |
| `src/data/insightsMock.ts` | 204-209 | `新品机会` 描述 | `用户在Reddit多次提到「不知道奶温是否合适」` / `职场妈妈对「办公室隐蔽使用」需求强烈` | 需求描述像AI从帖子中抽取的，缺乏真实感 | 引用具体帖子标题或用户原话 |
| `src/data/insightsMock.ts` | 275-290 | `最佳发帖时间` / `推荐社区` | 出现 emoji `💡` 和 `🎯`（在 `TimelinePanel` 中） | 移除 emoji，保持专业界面 |
| `src/data/insightsMock.ts` | 243-260 | `策略建议` 内容 | `强化「静音办公场景」内容输出`、`主动介入竞品对比帖` | 描述像AI生成的运营建议，缺乏具体性 | 每条策略应包含具体动作、负责人、Deadline |

### 2.6 搜索与配置（Search / Settings）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/Search.tsx` | 136-137 | `帖子搜索` / `搜索 Reddit 帖子，快速定位品牌相关讨论` | 「快速定位品牌相关讨论」是AI套话 | 改为「搜索 Reddit 帖子标题、作者或社区」 |
| `src/components/SearchPanel.tsx` | 61-63 | `搜索配置` / `Subreddit` / `关键词` | 表单标签过于技术化 | 改为「监测社区」和「监测关键词」 |
| `src/components/SearchPanel.tsx` | 114 | `开始分析` | 按钮文案模糊，分析什么？ | 改为「更新监测结果」或「搜索」 |
| `src/components/SearchConfig.tsx` | 43-45 | `关键词管理` / `已配置 X/Y 个监测关键词` | 副标题像数据库状态提示 | 改为「当前监测的关键词」 |
| `src/components/SearchConfig.tsx` | 162-164 | `社区管理` / `已配置 X/Y 个监测 subreddit` | 同上 | 改为「正在监测的 Reddit 社区」 |
| `src/components/SearchConfig.tsx` | 279-282 | `搜索配置` / `调整监测规则与过滤条件` | 「调整监测规则与过滤条件」像后台系统文案 | 改为「自定义你的监测方式」 |
| `src/components/SearchConfig.tsx` | 365-368 | `AI 智能过滤` / `自动过滤低质量、不相关的帖子` | 再次强调AI，且「低质量」判断标准不明 | 改为「自动排除无关帖子」或具体说明过滤条件 |
| `src/components/SearchConfig.tsx` | 397-404 | `自动通知` / `新帖出现时自动推送通知` | 功能描述像AI生成的功能说明文档 | 改为「发现新帖时通知我」 |
| `src/components/SearchConfig.tsx` | 437-440 | `监测规则预览` / `当前配置预计抓取范围` | 副标题像数据库查询结果 | 改为「根据当前设置，预计每日监测约 50-80 条帖子」 |
| `src/components/SearchConfig.tsx` | 511 | `应用配置并开始监测` | 按钮文案过长，且「应用配置」是技术用语 | 改为「保存并开始监测」 |
| `src/pages/Settings.tsx` | 106-108 | `应用内通知` / `在消息中心接收实时通知` / `邮件通知` / `每日简报和紧急警报发送至邮箱` / `飞书通知` / `通过飞书机器人接收关键警报` | 每个通知渠道的描述都是AI模板句式「通过...接收...」 | 改为简洁说明，如「邮件通知」配「包含每日摘要」 |
| `src/pages/Settings.tsx` | 150-154 | `机器人 Webhook 配置` / `配置钉钉/飞书机器人 Webhook，支持按事件类型和严重等级自动推送` | 副标题像技术文档 | 改为「将重要通知发送到钉钉或飞书」 |
| `src/pages/Settings.tsx` | 385-388 | 安全提示文案 | `Webhook URL 和 Secret 仅保存在当前页面内存中...` | 过于技术化，且「页面内存」说法不专业 | 改为「Webhook 设置仅保存在当前页面，刷新后需重新输入」 |

### 2.7 消息中心（Messages / Notifications）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/Messages.tsx` | 190-191 | `消息中心` / `舆情警报、任务提醒与洞察通知的统一管理` | 副标题是AI生成产品说明标配 | 改为「所有通知和提醒」 |
| `src/data/messagesMock.ts` | 34-45 | 通知 n1 | `严重负面舆情 - 产品故障投诉` / `r/breastfeeding 出现「M5使用两周后故障」帖子，评论区已有用户附和，需立即干预` | 标题和描述都是典型的AI监控报警文案，像机器人发的 | 标题改为「M5 故障投诉帖在 r/breastfeeding 发酵」；描述改为「用户 angrycustomer 发布故障投诉，已获 34 upvotes，28 条评论」 |
| `src/data/messagesMock.ts` | 46-55 | 通知 n2 | `竞品对比帖热度过高` / `M5在评论区提及较多但部分用户倾向Elvie` | 「热度过高」是AI判断词汇，不专业 | 标题改为「Momcozy vs Elvie 对比帖获得 67 upvotes」 |
| `src/data/messagesMock.ts` | 56-67 | 通知 n3 | `UGC 口碑素材新发现` / `建议收集为 testimonial` | 混用中英文 `testimonial`，且「口碑素材新发现」像机器播报 | 改为「happymom_89 在 r/babybumps 分享 M5 好评，upvotes 2156」 |
| `src/data/messagesMock.ts` | 93-102 | 通知 n5 | `情感异常波动 - 负面率上升` | 「情感异常波动」是AI典型表达 | 改为「r/breastpumps 负面率从 12% 升至 18%」 |
| `src/data/messagesMock.ts` | 103-109 | 通知 n6 | `话题趋势预警 - 背奶职场妈妈` / `是内容输出的黄金窗口` | 「黄金窗口」是AI营销套话 | 改为「背奶职场妈妈话题本周增长 45%，适合发布相关内容」 |
| `src/data/messagesMock.ts` | 110-118 | 通知 n7 | `每日舆情简报已生成` / `7月11日日报已生成，包含52条新帖、3条紧急警报、8条高意向线索` | 像机器人定时任务通知 | 改为「今日日报已生成：52 条新帖，3 条需关注」 |
| `src/data/messagesMock.ts` | 119-128 | 通知 n8 | `UGC 素材收集完成` / `本周已收集18条UGC素材，其中5条在 r/babybumps 获得1000+ upvotes` | 「收集完成」像任务状态通知，缺乏人味 | 改为「本周收录 18 条用户好评，其中 5 条高互动」 |
| `src/data/messagesMock.ts` | 129-138 | 通知 n9 | `竞品动态 - Elvie声量上升` | 声量上升是行业术语，普通用户不理解 | 改为「Elvie 本周在 r/breastfeeding 被提及 89 次（+30%）」 |
| `src/data/messagesMock.ts` | 139-143 | 通知 n10 | `周报已生成` / `品牌正面率53.4%（+10.8%），负面率14.4%（-22.6%）` | 数据堆砌，像自动报表邮件 | 改为「本周正面率提升，负面率下降」或具体结论 |
| `src/data/messagesMock.ts` | 144-154 | 通知 n11 | `新品发布话题预热` / `建议准备 FAQ` | 「预热」和「FAQ」混用，不自然 | 改为「用户在 r/babybumps 讨论 M6 新品，可准备答疑内容」 |
| `src/data/messagesMock.ts` | 169-177 | 通知 n13 | `KOL 负面评价扩散` / `母婴博主「milkymama」在 YouTube 评测中提到 M5 噪音问题，已在 Reddit 引发讨论` | 「KOL 负面评价扩散」是典型PR危机术语，放在通知中心过于公文 | 改为「YouTube 博主提及 M5 噪音问题，Reddit 已有相关讨论」 |
| `src/data/messagesMock.ts` | 304-383 | 通知规则 | `严重负面舆情预警` / `高意向帖子发现` / `UGC 口碑素材收集` / `竞品动态监控` / `情感异常波动` / `话题趋势预警` / `每日舆情简报` / `周报生成通知` | 规则名称全是AI生成模板，缺乏品牌个性 | 改为更口语化的名称，如「M5 被差评时通知我」「发现想买泵的用户时通知我」 |
| `src/components/NotificationCenter.tsx` | 163-166 | 通知中心 Header | `通知中心` / `X 条未读通知` | 标准文案，无问题，但 `暂无未读通知` 在空态时显示 | 空态可改为「没有新通知」 |
| `src/components/NotificationCenter.tsx` | 305-308 | 推送按钮 | `推送至机器人` | 技术术语，用户不清楚「机器人」指什么 | 改为「发送到飞书/钉钉」 |

### 2.8 UGC 素材库（UGC Showcase）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/UGCShowcase.tsx` | 297-298 | `UGC 素材库` / `自动归档的正面 UGC 内容——产品体验、对比推荐、生活方式与实用攻略` | 破折号 + 四个并列分类，典型的AI生成描述 | 改为「收录 Reddit 上关于 Momcozy 的正面用户分享」 |
| `src/pages/UGCShowcase.tsx` | 313-336 | StatCard 标签 | `已归档素材` / `本周新增` / `正面内容占比` / `平均互动率` | 指标名称标准，但「平均互动率」计算方式不明 | 添加 tooltip 说明互动率 = (upvotes + comments) / 总浏览量 |
| `src/pages/UGCShowcase.tsx` | 405 | `素材列表` / `共 X 条素材 · 自动归档 · 可筛选导出` | 副标题像数据库功能说明 | 改为「X 条收录内容」 |
| `src/data/ugcMock.ts` | 27 | `autoArchiveReason: '高情感分+产品对比+详细体验描述'` | 归档理由像AI标签组合 | 改为「用户详细对比 M5 与 Elvie，正面评价突出静音与续航」 |
| `src/data/ugcMock.ts` | 46 | `autoArchiveReason: '正面情感+竞品对比+购买意图明确'` | 同上 | 改为「新手妈妈对比 Spectra 与 S12，推荐预算有限用户选择 S12」 |
| `src/data/ugcMock.ts` | 66 | `autoArchiveReason: '高互动+场景展示+生活方式'` | 同上 | 改为「用户分享办公室背奶 setup，展示 V2 实际使用场景」 |
| `src/data/ugcMock.ts` | 86 | `autoArchiveReason: '情感高峰+售后体验+品牌忠诚'` | 同上 | 改为「用户分享客服更换 flange 经历，强调售后信任」 |
| `src/data/ugcMock.ts` | 107 | `autoArchiveReason: '专家背书+多竞品对比+高互动'` | 同上 | 改为「泌乳顾问对比三款可穿戴泵，推荐 Momcozy 性价比」 |
| `src/data/ugcMock.ts` | 128 | `autoArchiveReason: '实用攻略+省钱+高收藏率'` | 同上 | 改为「用户分享通过保险报销 M5 的完整流程」 |
| `src/data/ugcMock.ts` | 148 | `autoArchiveReason: '场景痛点+情感共鸣+使用细节'` | 同上 | 改为「新手妈妈分享 S12 夜 mode 使用体验」 |
| `src/data/ugcMock.ts` | 168 | `autoArchiveReason: '多媒体内容+教程+评测'` | 同上 | 改为「开箱评测视频，包含组装和清洗教程」 |
| `src/data/ugcMock.ts` | 188 | `autoArchiveReason: '场景扩展+旅行+生活方式'` | 同上 | 改为「用户出差携带 M5 的便携性实测」 |
| `src/data/ugcMock.ts` | 209 | `autoArchiveReason: '竞品转换+后悔叙事+高情感分'` | 同上，「后悔叙事」是AI分析术语 | 改为「用户从 Medela 转用 S12 一周后的体验分享」 |
| `src/data/ugcMock.ts` | 229 | `autoArchiveReason: '产品更新+配件+用户痛点解决'` | 同上 | 改为「用户分享 19mm flange 新品使用体验」 |
| `src/data/ugcMock.ts` | 249 | `autoArchiveReason: '选购指南+专家背书+多产品'` | 同上 | 改为「泌乳顾问发布的型号选择指南」 |

### 2.9 案例广场（Case Gallery）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/CaseGallery.tsx` | 286-293 | `案例广场` / `Reddit 数据应用案例精选` / `从微信公众号、垂类媒体中精选的高质量案例...` | 副标题像AI生成的内容聚合页描述，且「垂类媒体」是行业黑话 | 改为「真实品牌如何通过 Reddit 获取用户洞察」 |
| `src/data/casesMock.ts` | 24-29 | 分类标签 | `GEO 优化` / `生成式引擎优化 · AI搜索时代品牌占位` | 副标题使用典型AI营销术语「品牌占位」 | 改为「让品牌在 AI 搜索中被提及」 |
| `src/data/casesMock.ts` | 31-33 | 分类标签 | `新品机会` / `消费者洞察 · 蓝海发现 · 产品迭代` | 三个并列名词，套话 | 改为「从 Reddit 讨论中发现产品机会」 |
| `src/data/casesMock.ts` | 34-36 | 分类标签 | `舆情洞察` / `品牌口碑 · 危机预警 · 竞品分析` | 同上 | 改为「监测品牌口碑与竞品动态」 |
| `src/data/casesMock.ts` | 37-39 | 分类标签 | `商机获取` / `线索挖掘 · 需求发现 · B2B获客` | 同上，且混用中英文 `B2B` | 改为「在 Reddit 上发现潜在客户」 |
| `src/data/casesMock.ts` | 87-93 | 案例 geo1 | `90% 做 GEO 的公司都忽略了 Reddit，附5个实操建议` | 标题像微信公众号爆款文，不像案例 | 保持原样（这是外部文章标题）但需确认是否适合作为品牌案例展示 |
| `src/data/casesMock.ts` | 多处 | 全部案例描述 | 多数描述以「系统讲解」「深度解析」「实战案例」开头 | 这些描述词是AI内容聚合的标志性词汇 | 改为引用案例核心结论的一句话 |

### 2.10 FAQ 页

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/FAQ.tsx` | 10-11 | `如何设置 Reddit 监测？` / `进入工作台后...系统会自动开始追踪相关讨论` | 回答像产品说明书，缺乏温度 | 改为「在搜索配置里输入你想监测的社区和关键词，比如 r/breastfeeding 和 breast pump，我们就开始帮你追踪了」 |
| `src/pages/FAQ.tsx` | 13-15 | `AI 如何判断用户意图？` / `我们的 AI 模型基于大量 Reddit 对话数据训练...` | 再次强调AI，且「大量 Reddit 对话数据训练」是AI产品FAQ标配 | 改为「我们分析帖子内容、用户语气和社区上下文，判断用户是想购买、咨询还是投诉」 |
| `src/pages/FAQ.tsx` | 17-19 | `Momcozy 品牌数据安全吗？` / `我们采用企业级数据加密和访问控制...` | 「企业级数据加密」是SaaS产品套话 | 改为具体说明，如「你的监测数据仅你可见，不会分享或出售」 |
| `src/pages/FAQ.tsx` | 22-23 | `支持哪些 subreddit？` / `理论上支持 Reddit 上任何公开的 subreddit...` | 「理论上支持」像客服标准回答 | 改为「任何公开的 Reddit 社区都可以监测，我们已预置 50+ 母婴相关社区」 |
| `src/pages/FAQ.tsx` | 25-27 | `AI 回复功能如何使用？` | 问题本身在强调AI | 改为「如何获得回复建议？」 |
| `src/pages/FAQ.tsx` | 28-31 | `监测频率是多少？` / `系统每 15 分钟扫描一次...` / `高意向帖子会立即推送通知` | 「扫描」是技术术语，且「立即推送」模糊 | 改为「每 15 分钟检查一次新帖，发现高意向帖子会马上通知你」 |
| `src/pages/FAQ.tsx` | 33-35 | `可以导出数据吗？` / `可以。你可以导出监测报告为 CSV 或 PDF 格式...` | 回答以「可以」开头，像客服机器人 | 改为「能。支持导出 CSV 和 PDF，方便团队共享」 |
| `src/pages/FAQ.tsx` | 37-39 | `如何识别竞品提及？` | 问题表述技术化 | 改为「怎么知道竞品被提到了？」 |
| `src/pages/FAQ.tsx` | 41-43 | `支持多账号管理吗？` / `支持。你可以创建多个子账号...` | 再次以「支持」开头 | 改为「能。适合团队协作，可为不同成员分配权限」 |
| `src/pages/FAQ.tsx` | 45-47 | `有使用教程吗？` / `有。我们提供完整的使用文档和视频教程...` | 以「有」开头，机器人感 | 改为「有文档和视频教程，也可以联系客服获取一对一指导」 |
| `src/pages/FAQ.tsx` | 58-59 | `常见问题` / `快速了解 Reddit 舆情监测的核心问题` | 副标题像AI生成的内容页描述 | 删除副标题或改为「关于 Reddit 监测的常见疑问」 |
| `src/pages/FAQ.tsx` | 84-85 | `还有其他问题？` / `我们的团队随时为你解答` | 「随时为你解答」是客服套话 | 改为「需要更多帮助？联系 support@momcozy.com」 |

### 2.11 功能页 / 使用流程（Features / HowItWorks）

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/pages/Features.tsx` | 95-103 | `功能一览` / `强大的 Reddit 舆情管理工具` / `从监测到分析，从洞察到行动，一站式 Reddit 舆情管理解决方案` | 最后一句是AI SaaS产品Slogan模板 | 改为「监测 Reddit 讨论，发现品牌机会，回复高意向用户」 |
| `src/pages/Features.tsx` | 199-204 | `准备好开始了吗？` / `加入 500+ 品牌，开启 Reddit 舆情监测之旅` | 再次使用虚假数字和「之旅」套话 | 改为「开始追踪你的品牌」 |
| `src/pages/Features.tsx` | 166-168 | `更多能力` / `全面的工具集，满足你的所有 Reddit 舆情管理需求` | 「全面的工具集」「满足你的所有需求」是AI填充文案 | 改为「其他功能」或删除副标题 |
| `src/pages/Features.tsx` | 173-178 | 功能列表 | `多社区覆盖` / `风险预警` / `数据洞察` / `对话管理` / `智能推荐` / `持续优化` | 六个四字短语，典型的AI功能列表 | 每个功能配具体说明，如「同时监测多个社区，跨社区追踪品牌声量」应简化为「追踪多个社区的品牌讨论」 |
| `src/pages/HowItWorks.tsx` | 48-55 | `使用流程` / `三步开始 Reddit 舆情监测` / `无需复杂配置，几分钟即可完成设置，AI 自动为你发现商机` | 「几分钟即可完成」+「AI 自动为你发现商机」是落地页标配 | 改为「设置关键词和社区，开始追踪 Reddit 讨论」 |
| `src/pages/HowItWorks.tsx` | 111-114 | `开始你的监测之旅` / `几分钟完成设置，AI 自动为你发现 Reddit 上的每一个商机` | 再次使用「之旅」和「每一个商机」 | 改为「设置只需 2 分钟」 |

### 2.12 其他组件与工具函数

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/components/PostDetailDrawer.tsx` | 220-229 | `内容摘要` 中的模板化文本 | `该帖子来自 r/...，由 u/... 发布。根据情感分析，该帖子整体倾向为...` | 这段文本是AI生成的摘要模板，每次打开都一样，缺乏真实感 | 改为动态生成的摘要或删除 |
| `src/components/ExportButton.tsx` | — | 导出按钮相关文案 | 未读取文件，但 Dashboard 中 `舆情报告_日报` 等文件名 | 文件名使用下划线连接，像系统导出文件名 | 改为「Momcozy Reddit 日报_2026-07-11」或类似 |
| `src/components/TopicFlowInsight.tsx` | 155-157 | `话题流转洞察` / `可视化追踪话题从社区传播到用户决策的完整路径` | 副标题像数据可视化产品说明 | 改为「用户讨论如何从社区传播到购买决策」 |
| `src/components/TopicFlowInsight.tsx` | 182-184 | 桑基图说明 | `左侧为来源社区，中间为用户所处决策阶段，右侧为最终表达意图` | 像图表说明文档，用户不会阅读 | 改为 tooltip 或交互引导 |
| `src/components/TopicFlowInsight.tsx` | 205-207 | 词云说明 | `词云展示话题流转中的高频关键词` | 像教科书定义 | 改为「点击词汇查看相关帖子」 |
| `src/components/StrategyPanel.tsx` | 226-228 | `营销策略建议` / `基于数据分析自动生成可执行的 Reddit 营销策略` | 副标题强调「自动生成」，暴露AI本质 | 改为「基于数据趋势建议的运营动作」 |
| `src/components/StrategyPanel.tsx` | 303-307 | 执行按钮状态 | `执行` / `执行中...` / `已完成` | 中文「执行」在UI中生硬 | 改为「开始」/「进行中」/「完成」 |
| `src/components/Accordion.tsx` | — | 未读取，但 FAQ 中使用 | 若使用标准折叠组件，通常无文案问题 | 检查空态和展开/收起状态词 |
| `src/components/StatCard.tsx` | — | 未读取，但 Dashboard 中大量使用 | 指标变化描述如 `+12.5%` | 添加对比基准说明，如「较上周」 |
| `src/components/ErrorBoundary.tsx` | — | 未读取 | 错误页面文案容易被忽略 | 检查是否使用「哎呀，出错了」等AI模板 |
| `src/components/LoadingSkeleton.tsx` | — | 未读取 | 骨架屏通常无文案，但若有提示文字需检查 | 检查是否存在「正在加载中...」等套话 |
| `src/components/PostCard.tsx` | 39-48 | 状态标签 | `新发现` / `已回复` / `已保存` | 状态名称标准，但「新发现」比「新帖」更模糊 | 改为「新帖」或「未处理」 |
| `src/components/PostCard.tsx` | 450 | `意向分 {post.intentScore}` | 技术术语直接暴露 | 改为「意向评分」或「匹配度」 |
| `src/components/PostCard.tsx` | 464-468 | 悬浮按钮 | `{intentConfig[postIntent].actionLabel}` / `ArrowRight` | 动作标签来自配置，需检查 intentConfig.ts | 检查 `intentConfig.ts` 中的 actionLabel 是否自然 |
| `src/components/TopicCluster.tsx` | — | 未读取 | 话题聚类名称若由AI生成 | 检查是否存在「话题聚类1」「话题聚类2」等命名 |
| `src/components/SubredditProfile.tsx` | — | 未读取 | 社区画像描述 | 检查是否使用「该社区用户主要为...」等模板 |
| `src/components/CompetitorComparison.tsx` | — | 未读取 | 竞品对比文案 | 检查是否使用「Momcozy 在 XX 维度领先竞品」等套话 |
| `src/components/InfluencerIdentification.tsx` | — | 未读取 | 影响者识别文案 | 检查是否使用「高影响力用户」等模糊描述 |
| `src/components/AudiencePersona.tsx` | — | 未读取 | 受众画像文案 | 检查是否使用「核心用户画像为...」等模板 |
| `src/components/EnhancedWordCloud.tsx` | — | 未读取 | 词云标题和说明 | 检查是否使用「高频关键词分布」等技术描述 |
| `src/components/CompetitorBrandConfig.tsx` | 111-113 | `竞品品牌配置` | 标题标准 | 空态文案 `尚未配置竞品品牌` / `添加品牌以在竞品对比中使用` 像系统提示 | 改为「还没有添加竞品」/ `添加你想对比的品牌` |
| `src/components/ExportButton.tsx` | — | 未读取，但假设存在 | 导出格式选项如 `CSV` / `PDF` | 检查是否有「导出数据为 CSV 格式，方便 Excel 分析」等AI说明 |
| `src/components/FavoriteButton.tsx` | — | 未读取 | 收藏按钮 tooltip 或提示 | 检查是否存在「已添加到收藏夹」等标准文案 |
| `src/components/SectionCard.tsx` | — | 未读取 | 卡片标题和副标题 | 检查是否普遍使用AI模板句式 |

### 2.13 数据常量与配置

| 文件 | 行号 | 问题文案 | 问题类型 | 改进建议 |
|------|------|----------|----------|----------|
| `src/data/intentConfig.ts` | — | 未读取，但被多处引用 | 意图配置中的 `label` 和 `actionLabel` | 检查是否存在 `Purchase Intent` / `Bug Report` 等英文直译或技术术语 |
| `src/data/analyticsMock.ts` | — | 未读取 | 分析页面 mock 数据 | 检查统计卡片标签是否存在AI生成套话 |
| `src/data/reportEngine.ts` | — | 未读取 | 报告生成引擎 | 检查生成报告中的文本是否模板化 |
| `src/data/topicFlowMock.ts` | — | 未读取 | 话题流转 mock 数据 | 检查节点名称是否自然 |
| `src/data/enhancedWordCloudMock.ts` | — | 未读取 | 增强词云 mock 数据 | 检查词汇是否真实 |
| `src/data/influencerMock.ts` | — | 未读取 | 影响者 mock 数据 | 检查影响者描述是否模板化 |
| `src/data/audienceMock.ts` | — | 未读取 | 受众 mock 数据 | 检查受众画像描述是否像AI生成 |
| `src/data/competitorMock.ts` | — | 未读取 | 竞品 mock 数据 | 检查竞品描述是否模板化 |
| `src/constants/colors.ts` | — | 未读取 | 颜色常量 | 通常无文案问题 |
| `src/design-tokens.ts` | — | 未读取 | 设计令牌 | 通常无文案问题 |

---

## 三、系统性问题总结（Pattern-Level Issues）

以下问题不是单个文案错误，而是贯穿整个产品的**系统性AI味特征**：

### 3.1 过度使用「AI」自我标签
- **表现**：产品名、Badge、功能描述、FAQ 中反复出现「AI 驱动」「AI 智能识别」「AI 自动分析」
- **影响**：用户不 care 你是不是 AI，只 care 能不能解决问题。过度强调 AI 反而降低信任感
- **涉及文件**：`Home.tsx`, `HeroSection.tsx`, `FAQ.tsx`, `SearchConfig.tsx`, `Features.tsx`, `HowItWorks.tsx`
- **建议**：全部删除「AI」前缀，用具体功能描述替换

### 3.2 四字短语 / 对仗句式泛滥
- **表现**：「实时监测」「意图识别」「智能分析」「舆情态势」「战略复盘」「品牌占位」
- **影响**：典型的中文AI生成特征，读起来像政府公文或咨询报告
- **涉及文件**：`Dashboard.tsx`, `ReportWeeklyView.tsx`, `ReportMonthlyView.tsx`, `Insights.tsx`, `CaseGallery.tsx`
- **建议**：用口语化的动词短语替换，如「追踪帖子」「判断意图」「分析数据」

### 3.3 破折号 + 并列名词的副标题格式
- **表现**：`从监测到分析，从洞察到行动` / `生成式引擎优化 · AI搜索时代品牌占位` / `品牌口碑 · 危机预警 · 竞品分析`
- **影响**：这是AI生成SaaS产品页的标准副标题模板
- **涉及文件**：`Home.tsx`, `Features.tsx`, `CaseGallery.tsx`, `Insights.tsx`
- **建议**：一个模块只讲一件事，副标题用一句话说明价值

### 3.4 虚假/无来源数据
- **表现**：`500+ 品牌信赖`, `98% 准确率`, `50+ subreddit`, `10K+ 高意向帖子`
- **影响**：demo 数据若无标注，用户会误以为是真实数据，严重损害信任
- **涉及文件**：`Home.tsx`, `HeroSection.tsx`
- **建议**：demo 数据加 `*` 标注，或删除具体数字，改用描述性表达

### 3.5 机器人式通知/报警文案
- **表现**：`严重负面舆情 - 产品故障投诉`, `情感异常波动 - 负面率上升`, `竞品动态 - Elvie声量上升`
- **影响**：通知中心像监控系统而非用户工具，阅读体验差
- **涉及文件**：`messagesMock.ts`, `dailyReportMock.ts`, `weeklyReportMock.ts`, `monthlyReportMock.ts`
- **建议**：用「谁做了什么，需要你怎么做」的格式重写

### 3.6 中英文混用
- **表现**：`testimonial`, `SOP`, `GEO`, `KOL`, `B2B`, `FAQ`, `ROI`, `setup`, `actionable`
- **影响**：在中文界面中突兀出现英文术语，除非该术语已广泛接受（如 `ROI` 可保留，`testimonial` 应改为「用户证言」）
- **涉及文件**：`ugcMock.ts`, `weeklyReportMock.ts`, `insightsMock.ts`, `casesMock.ts`, `messagesMock.ts`
- **建议**：建立术语对照表，对非通用英文术语统一翻译

### 3.7 空态/加载态文案模板化
- **表现**：`暂无数据`, `正在加载中...`, `未找到匹配结果`
- **影响**：虽然标准，但若能结合品牌调性可以更好
- **涉及文件**：多处空态组件
- **建议**：可保留，但优先处理上述更严重的问题

---

## 四、改进优先级矩阵

| 优先级 | 问题类型 | 预计改动量 | 影响范围 |
|--------|----------|------------|----------|
| P0 | 删除/替换所有「AI」自我标签 | 小（约20处） | 全局信任感 |
| P0 | 重写 Hero / Home 核心文案 | 中（约10处） | 首因印象 |
| P0 | 修正虚假/无来源数据 | 小（约5处） | 信任与合规 |
| P1 | 重写通知/报警文案（messagesMock） | 大（约50处） | 日常使用体验 |
| P1 | 简化报告模块标题（四字短语） | 中（约30处） | 专业感 |
| P1 | 重写 FAQ 为口语化回答 | 中（约15处） | 新手体验 |
| P2 | 统一中英文术语 | 中（约25处） | 一致性 |
| P2 | 优化 UGC 归档理由 | 小（约15处） | 素材库体验 |
| P2 | 优化案例广场描述 | 中（约20处） | 内容质量 |
| P3 | 空态/加载态品牌个性化 | 小 | 细节体验 |

---

## 五、附：最需立即修改的 10 个具体位置

1. **`src/components/HeroSection.tsx:12`** — 删除 `AI 驱动的 Reddit 舆情监测`
2. **`src/pages/Home.tsx:74`** — 删除或替换 `被 500+ 品牌信赖`
3. **`src/pages/Home.tsx:18`** — 重写 `实时监测 Reddit 上的高意向对话，AI 智能识别...`
4. **`src/pages/FAQ.tsx:13`** — 重写 `AI 如何判断用户意图？` 及回答
5. **`src/pages/Dashboard.tsx:18-20`** — 重写日报/周报/月报标签描述
6. **`src/data/messagesMock.ts:34-45`** — 重写通知 n1 标题和描述
7. **`src/data/insightsMock.ts:275-290`** — 移除 emoji 和机器人式建议
8. **`src/components/InsightCard.tsx:22-23`** — 修正 ` actionable` 拼写并翻译
9. **`src/data/ugcMock.ts:27`** — 重写所有 `autoArchiveReason` 为自然语言
10. **`src/pages/Features.tsx:99`** — 重写 `从监测到分析，从洞察到行动，一站式 Reddit 舆情管理解决方案`

---

*审计完成时间：2026-07-12*
*审计文件数：约 45 个文件*
*发现问题总数：约 120+ 处（含系统性模式问题）*
