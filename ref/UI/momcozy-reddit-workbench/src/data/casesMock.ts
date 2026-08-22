// 案例广场人工策展 seed。该数组是 CaseGallery 的稳定基线，不是网络检索结果。

export type CaseCategory = 'geo' | 'newproduct' | 'insight' | 'business';
export type CaseSourceKind = 'curated_seed' | 'legacy_unverified' | 'approved_delta';
export type CaseVerificationStatus = 'curated' | 'pending' | 'verified';

export interface CaseItem {
  id: string;
  title: string;
  description: string;
  source: string;
  url: string;
  category: CaseCategory;
  tags: string[];
  date: string;
  /** 当前条目在版本化案例合同中的来源语义。 */
  sourceKind: CaseSourceKind;
  verificationStatus: CaseVerificationStatus;
  canonicalUrl?: string;
  contentHash?: string;
  updatedAt?: string;
  lastVerifiedAt?: string;
  provenance?: string;
  /** 仅供运行时目录分流；不写回 38 条 seed 或 12 条 legacy 原始合同。 */
  defaultEligible?: boolean;
  /** @deprecated 仅兼容旧缓存；新代码使用 sourceKind。 */
  sourceType?: 'manual' | 'web';
}

export interface CaseSearchResult {
  items: CaseItem[];
  total: number;
  query: string;
  category: CaseCategory | 'all';
  searchedAt: string;
}

export const caseCategories: Record<CaseCategory, { label: string; desc: string; color: string; bg: string }> = {
  geo: { label: 'GEO 优化', desc: '生成式引擎优化 · AI搜索时代品牌占位', color: 'text-status-info', bg: 'bg-status-infoBg' },
  newproduct: { label: '新品机会', desc: '消费者洞察 · 蓝海发现 · 产品迭代', color: 'text-status-success', bg: 'bg-status-successBg' },
  insight: { label: '舆情洞察', desc: '品牌口碑 · 危机预警 · 竞品分析', color: 'text-status-warning', bg: 'bg-status-warningBg' },
  business: { label: '商机获取', desc: '线索挖掘 · 需求发现 · B2B获客', color: 'text-primary', bg: 'bg-primary-light' },
};

/** 热门检索标签 —— 自动内容检索的快捷入口 */
export const hotSearchTags = [
  { label: 'GEO', count: 6 },
  { label: 'Reddit营销', count: 4 },
  { label: 'AI搜索', count: 5 },
  { label: '消费者洞察', count: 5 },
  { label: '舆情监控', count: 4 },
  { label: 'n8n', count: 3 },
  { label: 'B2B获客', count: 4 },
  { label: '自动化', count: 3 },
  { label: '出海', count: 2 },
  { label: '危机预警', count: 3 },
];

/** 确定性本地过滤；不访问网络，也不模拟延迟。 */
export function filterCases(
  items: CaseItem[],
  query: string,
  category: CaseCategory | 'all' = 'all',
  signal?: AbortSignal
): Promise<CaseSearchResult> {
  if (signal?.aborted) {
    return Promise.reject(new Error('Aborted'));
  }

  const normalizedQuery = query.trim().toLowerCase();
  const filtered = items.filter((c) => {
    if (!normalizedQuery) return true;
    const matchSearch =
      c.title.toLowerCase().includes(normalizedQuery) ||
      c.description.toLowerCase().includes(normalizedQuery) ||
      c.tags.some((t) => t.toLowerCase().includes(normalizedQuery)) ||
      c.source.toLowerCase().includes(normalizedQuery);
    return matchSearch;
  }).filter((c) => {
    if (category === 'all') return true;
    return c.category === category;
  });

  return Promise.resolve({
    items: filtered,
    total: filtered.length,
    query: normalizedQuery,
    category,
    searchedAt: new Date().toISOString(),
  });
}

type CuratedSeedInput = Omit<
  CaseItem,
  'sourceKind' | 'verificationStatus' | 'canonicalUrl' | 'updatedAt' | 'provenance'
>;

const curatedSeedData: CuratedSeedInput[] = [
  // ===== GEO 优化 =====
  {
    id: 'geo1',
    title: '90% 做 GEO 的公司都忽略了 Reddit，附5个实操建议',
    description: '深入解析 Reddit 在 GEO（生成式引擎优化）中的关键作用，提供5个可落地的 Reddit GEO 实操策略，帮助品牌在 AI 搜索时代占据用户心智。',
    source: 'CC跨境日记（微信公众号）',
    url: 'https://mp.weixin.qq.com/s?__biz=Mzk0OTQ0MDI2MQ==&mid=2247484131&idx=1&sn=b2de029280f8ddf5d65ab1b823130a5b',
    category: 'geo',
    tags: ['GEO', 'Reddit营销', 'AI搜索', '实操'],
    date: '2025-07-30',
  },
  {
    id: 'geo2',
    title: 'Vol.33 不只本土化和活人感，出海品牌布局 Reddit 真实案例拆解',
    description: '出海营销专家分享5个真实 Reddit 品牌案例：行车记录仪、E-bike、制冰机、电动滑板车、滑雪镜等品类的 Reddit 营销策略拆解。',
    source: '出海六边形（播客）',
    url: 'https://podcasts.apple.com/cn/podcast/vol-33-%E4%B8%8D%E5%8F%AA%E6%9C%AC%E5%9C%9F%E5%8C%96%E5%92%8C%E6%B4%BB%E4%BA%BA%E6%84%9F-%E5%87%BA%E6%B5%B7%E5%93%81%E7%89%8C%E5%B8%83%E5%B1%80reddit%E7%9C%9F%E5%AE%9E%E6%A1%88%E4%BE%8B%E6%8B%86%E8%A7%A3/id1668619765?i=1000724555320',
    category: 'geo',
    tags: ['出海营销', '案例拆解', '品牌定位'],
    date: '2025-09-02',
  },
  {
    id: 'geo3',
    title: 'GEO（生成式引擎优化）到底是什么？',
    description: '系统讲解 GEO 的定义、与 SEO 的差异、底层公式和落地5步法，特别指出 Reddit、Quora 等平台在 AI 语料构建中的重要性。',
    source: '数字游民9527（微信公众号）',
    url: 'http://mp.weixin.qq.com/s?__biz=MzI0OTc2Mjg0MQ==&mid=2247491754&idx=1&sn=816a7606db66fe126a47b22832ad5353',
    category: 'geo',
    tags: ['GEO教程', 'AI搜索', 'SEO对比', '入门'],
    date: '2025-08-18',
  },
  {
    id: 'geo4',
    title: '第一课：为什么选择在 Reddit 上营销？',
    description: '详解 Reddit 在 AI 时代的营销价值：潜在客户生成、搜索排名加速、实时增长机会发现、竞品监控，以及 GEO/AEO/LLMEO 等 AI 营销新范式。',
    source: '玩转ASO（微信公众号）',
    url: 'http://mp.weixin.qq.com/s?__biz=MzU2OTA4NjI0Nw==&mid=2247486713&idx=1&sn=399b9f6b075a849b47d40a31f43ee040',
    category: 'geo',
    tags: ['Reddit营销', 'AI时代', 'GEO', '入门'],
    date: '2025-09-07',
  },
  {
    id: 'geo5',
    title: 'GEO舆情监测工具：品牌在AI搜索中的口碑实时管理',
    description: '从关键词体系设计→实时爬取→AI语义分析→分级预警，完整链路教学。含真实案例：某新消费品牌通过GEO监测提前发现零星投诉信号，避免重大公关危机。',
    source: 'GEO实战（geoshizhan.com）',
    url: 'https://www.geoshizhan.com/geo%E8%88%86%E6%83%85%E7%9B%91%E6%B5%8B%E5%B7%A5%E5%85%B7%EF%BC%9A%E5%93%81%E7%89%8C%E5%9C%A8ai%E6%90%9C%E7%B4%A2%E4%B8%AD%E7%9A%84%E5%8F%A3%E7%A2%91%E5%AE%9E%E6%97%B6%E7%AE%A1%E7%90%86/',
    category: 'geo',
    tags: ['GEO舆情', 'AI搜索', '口碑管理', '危机预警'],
    date: '2026-05-16',
  },
  {
    id: 'geo6',
    title: 'GEO舆情监控：如何监测和管理品牌在AI搜索中的口碑',
    description: '深度解析GEO舆情监控体系：三层监控结构（品牌词/竞品词/行业热点）、四种典型危机场景及应对策略、舆情响应SOP、主动GEO护城河建设方法。',
    source: 'GEO实战（geoshizhan.com）',
    url: 'https://www.geoshizhan.com/geo-brand-reputation-monitoring-crisis-management/',
    category: 'geo',
    tags: ['GEO舆情', '品牌监控', '危机管理', 'SOP'],
    date: '2026-04-17',
  },

  // ===== 新品机会 =====
  {
    id: 'np1',
    title: '五类核心用户的不同行为模式：Ta们都在 Reddit 上做什么？',
    description: '深入分析 Reddit 五类核心用户行为，揭示 Dolphin Air Freshener 案例：创始人通过 Reddit 发现停产汽车香薰需求，重新生产并在社区定向推广，最终 75% 预购订单来自 Reddit 广告，浏览量增长 13 倍。',
    source: '新浪科技',
    url: 'https://cj.sina.cn/articles/view/6579451885/1882a77ed01901ksmg',
    category: 'newproduct',
    tags: ['消费者洞察', '蓝海发现', '选品', 'Reddit广告'],
    date: '2026-05-20',
  },
  {
    id: 'np2',
    title: '在 Reddit 上发现蓝海市场：如何通过社群讨论洞察海外采购需求？',
    description: '四步实操法：找对话题群 → 提取采购信号（吐槽/求助/分享） → 确认真需求 → 合规对接客户。附 Reddit 运营避坑指南。',
    source: '全球搜®',
    url: 'https://www.globalso.com/blog/discovering-a-blue-ocean-market-on-reddit-how-to-gain',
    category: 'newproduct',
    tags: ['蓝海市场', '采购需求', '外贸', '实操指南'],
    date: '2026-01-09',
  },
  {
    id: 'np3',
    title: '生成式 AI 驱动快消品产品创新：消费者洞察加速新品研发上市',
    description: '某国产护肤品牌（年销售额约20亿元）通过 AI 分析 350万条 社交媒体评论，识别出"敏感肌防晒"的未被满足需求，新品上市首月销售额达 1.2 亿元，超出预期 73%。',
    source: '博晓通',
    url: 'https://www.bxtdata.com/insights/8451/%E7%94%9F%E6%88%90%E5%BC%8FAI%E9%A9%B1%E5%8A%A8%E5%BF%AB%E6%B6%88%E5%93%81%E4%BA%A7%E5%93%81%E5%88%9B%E6%96%B0%E6%B6%88%E8%B4%B9%E8%80%85%E6%B4%9E%E5%AF%9F%E5%8A%A0%E9%80%9F%E6%96%B0%E5%93%81%E7%A0%94%E5%8F%91%E4%B8%8A%E5%B8%82',
    category: 'newproduct',
    tags: ['AI驱动创新', '消费者洞察', '新品研发', '快消品'],
    date: '2026-06-13',
  },
  {
    id: 'np4',
    title: '品牌如何突围"成分内卷"和"达人压榨"的双重夹击？',
    description: '对话循理品牌 K博：从欧莱雅研发背景出发，如何通过消费者洞察发现敏感肌晨间清洁的真实需求，开发洗脸水创新剂型，在红海清洁赛道中找到差异化机会。',
    source: '小宇宙播客',
    url: 'https://www.xiaoyuzhoufm.com/episode/687780c1f01740ccc77e35fa',
    category: 'newproduct',
    tags: ['产品创新', '消费者洞察', '差异化', '护肤'],
    date: '2025-07-16',
  },
  {
    id: 'np5',
    title: '我用n8n搭了个「Reddit商机雷达」，AI自动挖掘被忽略的真实需求',
    description: '7x24小时全自动 Reddit 商机发现系统：从数据收集→内容筛选→AI深度分析→洞察输出。核心逻辑：消极情绪越强 = 痛点越深 = 付费意愿越高。',
    source: 'CSDN / 饼干哥哥',
    url: 'https://adg.csdn.net/69525aa75b9f5f31781bace9.html',
    category: 'newproduct',
    tags: ['n8n', '自动化', '商机挖掘', 'AI分析'],
    date: '2025-07-12',
  },
  {
    id: 'np6',
    title: '出海赚美金：用n8n搭建「Reddit商机搜索与洞察」AI Agent',
    description: '用 n8n 搭建 AI Agent 自动到 Reddit 搜索内容，判断商业价值，生成洞察报告。输入一个行业趋势，自动分析 Reddit 讨论，输出商业价值分析报告。',
    source: 'AI TNT 新闻',
    url: 'https://m.aitntnews.com/newDetail.html?newId=14893',
    category: 'newproduct',
    tags: ['n8n', 'AI Agent', '自动化', '蓝海市场'],
    date: '2025-06-09',
  },

  // ===== 舆情洞察 =====
  {
    id: 'in1',
    title: '我给大疆做了一套 20 万的 Reddit 品牌舆情监控工作流',
    description: '完整的 Reddit 舆情监控方案：从关键词/社区分层监控 → AI 情感与意图分析 → 数据分流（紧急警报/常规简报/营销素材）→ 飞书通知推送，包含完整提示词和 n8n 工作流思路。',
    source: '技术博客',
    url: 'https://mp.weixin.qq.com/s?__biz=MjM5NDI4MTY3NA==&mid=2257496404&idx=1&sn=353fa13ac40fafaf2b1a8b2a1f9cf758',
    category: 'insight',
    tags: ['舆情监控', 'AI分析', '工作流', '大疆'],
    date: '2025-09-02',
  },
  {
    id: 'in2',
    title: '海外舆情监测工具哪家强？2025 出海品牌实测推荐',
    description: '实测 Brandwatch、Talkwalker、Meltwater、识微商情 四大工具，包含某消费电子品牌通过 Brandwatch 发现 Reddit 产品设计讨论，及时调整方案避免大规模召回的真实案例。',
    source: '识微舆情',
    url: 'https://m.civiw.com/research/20250828100204637',
    category: 'insight',
    tags: ['舆情工具', '出海品牌', '竞品分析', '危机预警'],
    date: '2025-08-28',
  },
  {
    id: 'in3',
    title: '品牌出海的"雷达"与"声纳"：舆情监测+海外社媒监控的成功案例解析',
    description: '某国际美妆品牌通过舆情监测捕捉东南亚市场产品成分负面讨论，24小时内通过官方澄清+KOL试用背书，不仅化解危机还提升了品牌透明度认可度。',
    source: '搜狐',
    url: 'https://www.sohu.com/a/936520933_120317870',
    category: 'insight',
    tags: ['品牌出海', '危机公关', '社媒监控', '东南亚'],
    date: '2025-09-19',
  },
  {
    id: 'in4',
    title: '词云能支持哪些业务分析？舆情监测与品牌洞察案例分享',
    description: '三个实战案例：乳业品牌"配方门"危机，两周后负面声量下降 60%；新消费品牌通过词云+情感分析发现产品痛点，复购率提升 15%；在线教育平台实时词云大屏，年内重大公关事故为 0。',
    source: 'FineReport',
    url: 'https://www.finereport.com/blog/article/69935e0168fee269e9a66843',
    category: 'insight',
    tags: ['词云分析', '情感分析', '危机应对', '实时监测'],
    date: '2026-02-16',
  },
  {
    id: 'in5',
    title: 'AI搜索里的品牌舆情：差评内容如何被AI"记住"并传播',
    description: '详解AI如何给品牌"定性"：三个信息来源、负面记忆固化机制。策略：用高质量正面内容覆盖负面引用，不是删除负面，而是让正面内容的权重超过负面。',
    source: 'GEO实战（geoshizhan.com）',
    url: 'https://www.geoshizhan.com/ai%E6%90%9C%E7%B4%A2%E9%87%8C%E7%9A%84%E5%93%81%E7%89%8C%E8%88%86%E6%83%85-%E5%B7%AE%E8%AF%84%E5%86%85%E5%AE%B9%E5%A6%82%E4%BD%95%E8%A2%ABai%E8%AE%B0%E4%BD%8F%E5%B9%B6%E4%BC%A0%E6%92%AD/',
    category: 'insight',
    tags: ['AI舆情', '品牌定性', '正面覆盖', 'GEO策略'],
    date: '2026-05-08',
  },
  {
    id: 'in6',
    title: '舆情监测挖掘行业数据，洞察市场潜在商机',
    description: '系统讲解商情监测全流程：数据收集（社交媒体/新闻/论坛/行业报告）→ 数据分析（清洗/整理/挖掘）→ 数据解读（策略制定/趋势预测/商机识别）。',
    source: '哔哩哔哩',
    url: 'https://www.bilibili.com/opus/798352816197337105',
    category: 'insight',
    tags: ['商情监测', '数据分析', '趋势预测', '商机识别'],
    date: '2025-06-15',
  },

  // ===== 商机获取 =====
  {
    id: 'bu1',
    title: 'B2B 潜在客户生成指南：策略、技巧、工具和想法',
    description: '系统讲解 B2B 潜在客户开发全流程：从定义 ICP 到多渠道获客，包含 Salesflare 团队从一次活动中获得 130+ 线索的真实案例。',
    source: 'Salesflare Blog',
    url: 'https://blog.salesflare.com/zh/b2b-%E6%BD%9C%E5%9C%A8%E5%AE%A2%E6%88%B7%E5%BC%80%E5%8F%91',
    category: 'business',
    tags: ['B2B获客', '潜在客户', '销售漏斗', 'LinkedIn'],
    date: '2025-12-10',
  },
  {
    id: 'bu2',
    title: '如何为 SaaS 生成 B2B 线索：12 个成功步骤',
    description: '12步 SaaS B2B 线索生成方法论，涵盖内容营销、SEO、社交媒体、推荐计划、付费广告等全渠道策略，附 Dropbox 推荐计划增长案例。',
    source: 'PayPro Global',
    url: 'https://payproglobal.com/zh/%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97/%E4%B8%BAsaas%E7%94%9F%E6%88%90b2b%E6%BD%9C%E5%9C%A8%E5%AE%A2%E6%88%B7/',
    category: 'business',
    tags: ['SaaS', '线索生成', '全渠道策略', '推荐计划'],
    date: '2026-04-14',
  },
  {
    id: 'bu3',
    title: 'AI+销售：从线索获客到商机成交的增长新范式',
    description: 'AI 时代 B2B 销售全链路升级：AI 超级漏斗自动化、GEO 重构获客逻辑、Openclaw 情报员、线索评级五步法、权利地图穿透决策链。',
    source: '搜狐',
    url: 'https://www.sohu.com/a/1018933178_121430528',
    category: 'business',
    tags: ['AI+销售', '智能工作流', '商机成交', 'B2B'],
    date: '2026-05-07',
  },
  {
    id: 'bu4',
    title: 'ToB 销售：从线索到商机',
    description: '详解销售漏斗管理、线索与商机的核心区别、主动获客 vs 被动获客的优劣，以及华为从运营商到企业网的商机拓展策略。',
    source: 'ToB 行业头条',
    url: 'https://so.html5.qq.com/page/real/search_news?docid=70000021_7846614d1b904352',
    category: 'business',
    tags: ['ToB销售', '线索管理', '商机培育', '华为案例'],
    date: '2024-04-09',
  },
  {
    id: 'bu5',
    title: '数据洞察案例分享：从数据中挖掘商机',
    description: '实战案例：通过消费者细分、趋势预测、情感分析、交叉销售与推荐，实现产品线优化、精准营销、库存管理优化和客户体验增强。',
    source: '天空采集',
    url: 'https://www.skycaiji.com/aigc/ai24706.html',
    category: 'business',
    tags: ['数据洞察', '消费者细分', '精准营销', '商机转化'],
    date: '2025-06-15',
  },
  {
    id: 'bu6',
    title: '商品评论点亮消费者决策路，抓取洞察新商机',
    description: '通过商品评论抓取技术深入了解消费者真实反馈，发现产品优化方向、新品创意灵感，以及建立客户互动与忠诚度的新渠道。',
    source: '百度百家号',
    url: 'http://www.baidu.com/link?url=rIVyG9p5m1ADydsx4jbZlubEXaZdaVuUm4ulP6K4eELgWOZJ7ZrJxvdKo9hBX8HPFfDJrqlsaL199q0R6EOVTuUbJEVphDU-hpXwHuxXTEO',
    category: 'business',
    tags: ['评论分析', '消费者洞察', '产品优化', '忠诚度'],
    date: '2024-06-28',
  },

  // ===== 新增：微信高质量文章 =====
  {
    id: 'in7',
    title: 'Reddit 营销新手必须避开的坑',
    description: '微思敦研习社分享 Reddit 营销入门避坑指南，帮助新手品牌避免常见错误，建立正确的社区参与策略与品牌传播路径。',
    source: '微思敦研习社（微信公众号）',
    url: 'https://mp.weixin.qq.com/s/Bh2QSfzadAYEmvmRoYxolw',
    category: 'insight',
    tags: ['Reddit营销', '新手入门', '避坑指南', '社区参与'],
    date: '2025-08-01',
  },
  {
    id: 'geo7',
    title: 'GEO优化，Reddit在AI搜索中的角色',
    description: '深入解析 Reddit 在 GEO（生成式引擎优化）中的战略价值，探讨如何在 AI 搜索时代利用 Reddit 社区内容提升品牌可见度与搜索占位。',
    source: 'SlowGrowth慢速生长（微信公众号）',
    url: 'https://mp.weixin.qq.com/s/11LqiC2drOr1sCpPa3NkCA',
    category: 'geo',
    tags: ['GEO', 'AI搜索', 'Reddit', '内容优化'],
    date: '2025-09-15',
  },
  {
    id: 'in8',
    title: 'Reddit社交聆听报告',
    description: 'OneSight 发布的 Reddit 社交聆听深度报告，涵盖社区洞察、品牌口碑分析、竞品监测方法论及实操工具推荐。',
    source: 'OneSight（微信公众号）',
    url: 'https://mp.weixin.qq.com/s/LXd3yOmETvpa7w8vKpxjkg',
    category: 'insight',
    tags: ['社交聆听', 'Reddit', '品牌口碑', '竞品监测'],
    date: '2025-10-20',
  },
  {
    id: 'geo8',
    title: 'Reddit在GEO时代的价值',
    description: '从 GEO 视角审视 Reddit 的品牌价值，分析 Reddit 社区内容如何影响 AI 搜索结果，以及品牌如何利用这一趋势进行内容布局。',
    source: '言书随手记（微信公众号）',
    url: 'https://mp.weixin.qq.com/s/UMYeNTmeVhB8kGC9SEI6Ig',
    category: 'geo',
    tags: ['GEO', 'Reddit', 'AI搜索', '品牌价值'],
    date: '2025-11-05',
  },

  // ===== 新增：Reddit 官方及权威来源 =====
  {
    id: 'bu7',
    title: 'Reddit Ads Help Center — 官方广告帮助中心',
    description: 'Reddit 官方广告帮助中心，提供广告投放全流程指南：创建广告账户、设置广告系列、管理预算、定位受众、优化广告效果。',
    source: 'Reddit Official (business.reddithelp.com)',
    url: 'https://business.reddithelp.com/s/',
    category: 'business',
    tags: ['Reddit广告', '官方指南', '广告投放', 'B2B获客'],
    date: '2026-01-01',
  },
  {
    id: 'bu8',
    title: 'Reddit Advertising — 官方广告平台',
    description: 'Reddit 官方广告平台入口，了解 Reddit 广告格式、定价、定位选项及成功案例，帮助品牌触达高参与度社区用户。',
    source: 'Reddit Official (reddit.com)',
    url: 'https://www.reddit.com/advertising',
    category: 'business',
    tags: ['Reddit广告', '官方平台', '社区营销', '品牌曝光'],
    date: '2026-01-01',
  },
  {
    id: 'in9',
    title: 'Reddit Marketing 101: How To Market Your Brand on Reddit',
    description: 'Shopify 官方 Reddit 营销指南，详解有机营销和付费广告策略，包含 Neuro 品牌通过 Reddit 社区成功众筹的真实案例。',
    source: 'Shopify Blog',
    url: 'https://www.shopify.com/sg/blog/reddit-marketing',
    category: 'insight',
    tags: ['Reddit营销', 'Shopify', '品牌案例', '有机营销'],
    date: '2025-11-21',
  },
  {
    id: 'in10',
    title: 'Reddit Marketing: 7-Step Strategy Guide',
    description: 'Brandwatch 发布的 Reddit 营销七步策略指南，涵盖社区选择、内容策略、互动技巧和效果监测，附社区增长和情感分析指标。',
    source: 'Brandwatch',
    url: 'https://www.brandwatch.com/blog/reddit-marketing/',
    category: 'insight',
    tags: ['Reddit营销', '策略指南', '社区增长', '情感分析'],
    date: '2025-04-03',
  },
  {
    id: 'in11',
    title: 'Reddit marketing: How to get it right—and wrong',
    description: 'Zapier 深度解析 Reddit 营销的正确与错误做法，包含 Reddit 在 Google 搜索中曝光率增长 1348% 的数据分析，以及有机营销和广告策略。',
    source: 'Zapier Blog',
    url: 'https://zapier.com/blog/reddit-marketing/',
    category: 'insight',
    tags: ['Reddit营销', 'SEO', 'Google搜索', '自动化'],
    date: '2024-09-05',
  },
  {
    id: 'in12',
    title: 'Reddit Community Engagement: A Complete Guide for 2024',
    description: '完整的 Reddit 社区参与指南，详解 80/20 法则（80% 价值贡献 + 20% 自我推广）、社区选择策略、AMA 运营和常见错误避免。',
    source: 'Pain on Social',
    url: 'https://painonsocial.com/blog/reddit-community-engagement',
    category: 'insight',
    tags: ['Reddit社区', '参与策略', 'AMA', '品牌建设'],
    date: '2024-10-30',
  },
  {
    id: 'geo9',
    title: 'Reddit Marketing in 2025: Why Brands Cannot Ignore the Community-First Channel',
    description: '深度分析 Reddit 成为有效营销渠道的原因：ChatGPT 数据引用来源、10亿+月活用户、社区真实性、精准利基定位、消费者洞察。附 B2B 思想领导和混合策略建议。',
    source: 'Adello',
    url: 'https://adello.com/reddit-marketing-in-2025-why-brands-cant-ignore-the-community-first-channel-anymore/',
    category: 'geo',
    tags: ['Reddit营销', '社区优先', 'ChatGPT', 'B2B策略'],
    date: '2026-01-21',
  },
  {
    id: 'bu9',
    title: 'How to advertise on Reddit in 2026: setup, targeting, and what converts',
    description: 'Launchcodex 发布的 Reddit 广告完整指南，含平台成本对比（Reddit CPC $0.59 vs Meta $1.33 vs Google $4-5）、行业基准数据、B2B SaaS 创意框架和像素重定向策略。',
    source: 'Launchcodex',
    url: 'https://launchcodex.com/blog/performance-marketing/how-to-advertise-on-reddit/',
    category: 'business',
    tags: ['Reddit广告', '成本对比', 'B2B获客', '行业基准'],
    date: '2026-05-14',
  },
  {
    id: 'bu10',
    title: 'Reddit Ads: Complete Guide for 2025',
    description: 'Reddit 广告管理器完整设置指南：从创建账户、构建广告系列结构、选择定位选项（subreddit/兴趣/人口统计）到监控 CTR、CPM、转化和互动指标。',
    source: 'LeadAdvisors',
    url: 'https://leadadvisors.com/blog/reddit-ads/',
    category: 'business',
    tags: ['Reddit广告', '广告管理器', '定位选项', '效果监测'],
    date: '2025-12-18',
  },

  // ===== 新增：微信公众号高质量文章（captcha 链接） =====
  {
    id: 'geo10',
    title: 'Reddit 数据驱动品牌增长实战指南',
    description: '微信公众号深度分享 Reddit 数据在品牌营销中的实战应用，涵盖社区运营、用户洞察、内容策略与数据监测的完整方法论。',
    source: '微信公众号',
    url: 'https://mp.weixin.qq.com/s/3HcpcwXCNxJlL3etncMGRw',
    category: 'geo',
    tags: ['Reddit数据', '品牌增长', '社区运营', '用户洞察'],
    date: '2025-10-10',
  },
];

/** 38 条人工策展存量。ID、URL 与内容保持为稳定 seed 合同。 */
export const seedCases: CaseItem[] = curatedSeedData.map((item) => ({
  ...item,
  sourceKind: 'curated_seed',
  verificationStatus: 'curated',
  canonicalUrl: item.url,
  updatedAt: `${item.date}T00:00:00.000Z`,
  provenance: 'manual_curated_seed',
}));

/** @deprecated 兼容既有导入；请使用 seedCases。 */
export const cases = seedCases;
