// 周报 Mock 数据 —— 7天聚合
import { formatDateTime } from '../utils/date';
export interface WeeklyTrend {
  metric: string;
  current: number;
  previous: number;
  change: number; // 百分比
  unit: string;
}

export interface WeeklyOpportunity {
  id: string;
  title: string;
  description: string;
  growth: number; // 周度增长
  category: 'topic' | 'wordofmouth' | 'conversion' | 'new_product' | 'blue_ocean';
  impact: 'high' | 'medium' | 'low';
  heatScore: number; // 0-100 热力值
  unmetNeed?: string; // 未被满足的需求
}

export interface WeeklyRisk {
  id: string;
  title: string;
  description: string;
  growth: number; // 负面增长
  severity: 'high' | 'medium' | 'low';
  affectedArea: string;
}

export interface WeeklyCompetitor {
  name: string;
  mentions: number;
  positiveRate: number;
  topTopic: string;
  trend: 'up' | 'down' | 'stable';
  ourGap: number; // 与Momcozy的提及量差距
  // 新增字段
  brandPositioning: string; // 品牌定位差异
  mindShare: number; // 用户心智份额 %
  priceSensitivity: number; // 价格敏感度讨论占比 %
}

export interface WeeklyPainPoint {
  id: string;
  topic: string;
  frequency: number; // 提及次数
  severity: 'high' | 'medium' | 'low';
  solution: string; // 建议解决方案
  affectedProducts: string[];
}

export interface WeeklyTopicEvolution {
  topic: string;
  volume: number[]; // 7天数据
  sentiment: 'positive' | 'neutral' | 'negative';
  lifecycle: 'emerging' | 'rising' | 'peak' | 'declining';
  prediction: string;
  predictionConfidence: number; // 0-100
}

export interface WeeklyReview {
  metric: string;
  value: string;
  target: string;
  status: 'good' | 'warning' | 'bad';
  // 新增字段
  contentROI: number; // 内容策略ROI
  engagementRate: number; // 用户参与度 %
  communityEffectiveness: number; // 社区运营效果 0-100
}

export interface WeeklyPlan {
  id: string;
  action: string;
  priority: 'high' | 'medium' | 'low';
  community?: string;
  topic?: string;
  expectedImpact: string;
}

export interface WeeklyBrandVoiceTrend {
  day: string; // 周一到周日
  Momcozy: number;
  Medela: number;
  Elvie: number;
  Spectra: number;
  Willow: number;
  Lansinoh: number;
}

export const weeklyBrandVoiceTrends: WeeklyBrandVoiceTrend[] = [
  { day: '周一', Momcozy: 142, Medela: 98, Elvie: 112, Spectra: 45, Willow: 28, Lansinoh: 22 },
  { day: '周二', Momcozy: 156, Medela: 102, Elvie: 108, Spectra: 48, Willow: 26, Lansinoh: 24 },
  { day: '周三', Momcozy: 148, Medela: 95, Elvie: 118, Spectra: 52, Willow: 30, Lansinoh: 20 },
  { day: '周四', Momcozy: 162, Medela: 100, Elvie: 115, Spectra: 50, Willow: 32, Lansinoh: 21 },
  { day: '周五', Momcozy: 138, Medela: 88, Elvie: 105, Spectra: 44, Willow: 24, Lansinoh: 18 },
  { day: '周六', Momcozy: 128, Medela: 82, Elvie: 98, Spectra: 38, Willow: 22, Lansinoh: 16 },
  { day: '周日', Momcozy: 135, Medela: 86, Elvie: 102, Spectra: 42, Willow: 25, Lansinoh: 19 },
];

export const weeklyTrends: WeeklyTrend[] = [
  { metric: '总帖子数', current: 348, previous: 312, change: 11.5, unit: '条' },
  { metric: '正面情感占比', current: 53.4, previous: 48.2, change: 10.8, unit: '%' },
  { metric: '负面情感占比', current: 14.4, previous: 18.6, change: -22.6, unit: '%' },
  { metric: '高意向线索', current: 56, previous: 42, change: 33.3, unit: '条' },
  { metric: '平均回复时间', current: 4.2, previous: 6.8, change: -38.2, unit: '小时' },
  { metric: 'UGC素材收集', current: 18, previous: 12, change: 50.0, unit: '条' },
];

export const weeklyOpportunities: WeeklyOpportunity[] = [
  {
    id: 'o1',
    title: '「背奶职场妈妈」话题爆发',
    description: 'r/breastfeeding 和 r/babybumps 上关于「背奶/职场妈妈」的讨论量增长 45%，情感偏正面，是内容输出的黄金窗口',
    growth: 45,
    category: 'topic',
    impact: 'high',
    heatScore: 92,
    unmetNeed: '需要更多关于「如何在办公室隐蔽使用」的实操指南',
  },
  {
    id: 'o2',
    title: 'UGC口碑内容高产',
    description: '本周收集到 18 条真实用户好评素材，其中 5 条在 r/babybumps 获得 1000+ upvotes，可转化为品牌 testimonial',
    growth: 50,
    category: 'wordofmouth',
    impact: 'high',
    heatScore: 88,
  },
  {
    id: 'o3',
    title: '「新手妈妈」转化机会',
    description: 'r/NewParents 上关于「新手选泵」的求助帖量增长 28%，适合品牌以「解答者」身份介入，提供选泵指南',
    growth: 28,
    category: 'conversion',
    impact: 'medium',
    heatScore: 76,
    unmetNeed: '缺乏针对新手妈妈的「选泵决策树」内容',
  },
  {
    id: 'o4',
    title: 'r/breastpumps 垂直社区活跃',
    description: '垂直社区讨论量增长 15%，用户购买意图明确，适合进行精准产品推荐和参数科普',
    growth: 15,
    category: 'conversion',
    impact: 'medium',
    heatScore: 68,
  },
  {
    id: 'o5',
    title: '「智能吸奶」功能需求上升',
    description: '用户在讨论中频繁提及「希望有App连接记录吸奶量」的功能，目前竞品中仅Elvie和Willow提供',
    growth: 62,
    category: 'new_product',
    impact: 'high',
    heatScore: 85,
    unmetNeed: 'App连接 + 数据记录功能',
  },
  {
    id: 'o6',
    title: '「夜间静音」蓝海话题',
    description: '关于「夜间不吵醒宝宝」的讨论在 r/NewParents 快速增长，但品牌介入较少，存在蓝海机会',
    growth: 38,
    category: 'blue_ocean',
    impact: 'medium',
    heatScore: 72,
    unmetNeed: '夜间静音使用场景的内容和教程',
  },
];

export const weeklyRisks: WeeklyRisk[] = [
  {
    id: 'r1',
    title: '「吸力不够」负面投诉增长',
    description: '本周关于M5吸力的负面讨论增长 22%，涉及「吸力弱」「不够力」等关键词，可能源于固件更新或用户预期偏差',
    growth: 22,
    severity: 'high',
    affectedArea: '产品体验',
  },
  {
    id: 'r2',
    title: '竞品Elvie在r/breastfeeding声量上升',
    description: 'Elvie本周在r/breastfeeding的提及量增长30%，话题聚焦「静音设计」，正在建立该话题的心智优势',
    growth: 30,
    severity: 'medium',
    affectedArea: '竞争态势',
  },
  {
    id: 'r3',
    title: 'r/breastpumps社区负面率上升',
    description: '该社区本周负面率从12%升至18%，主要话题为「故障」和「售后」，需关注社区运营策略',
    growth: 50,
    severity: 'medium',
    affectedArea: '社区口碑',
  },
  {
    id: 'r4',
    title: '「故障投诉」帖子发酵速度加快',
    description: '本周3个负面帖在6小时内upvotes超过50，说明负面传播速度正在加快，响应时间需从4小时压缩到2小时',
    growth: 40,
    severity: 'high',
    affectedArea: '危机响应',
  },
];

export const weeklyCompetitors: WeeklyCompetitor[] = [
  { name: 'Elvie', mentions: 89, positiveRate: 72, topTopic: '静音设计', trend: 'up', ourGap: -97, brandPositioning: '高端科技，App智能', mindShare: 28, priceSensitivity: 12 },
  { name: 'Spectra', mentions: 34, positiveRate: 68, topTopic: '医院级吸力', trend: 'stable', ourGap: -152, brandPositioning: '医疗专业，医院推荐', mindShare: 18, priceSensitivity: 22 },
  { name: 'Willow', mentions: 18, positiveRate: 65, topTopic: '便携性', trend: 'down', ourGap: -168, brandPositioning: '极致便携，可穿戴', mindShare: 8, priceSensitivity: 8 },
  { name: 'Medela', mentions: 45, positiveRate: 60, topTopic: '品牌信任', trend: 'stable', ourGap: -141, brandPositioning: '传统大牌，信任背书', mindShare: 22, priceSensitivity: 18 },
  { name: 'Lansinoh', mentions: 12, positiveRate: 58, topTopic: '性价比', trend: 'down', ourGap: -174, brandPositioning: '入门亲民，配件丰富', mindShare: 5, priceSensitivity: 35 },
];

export const weeklyPainPoints: WeeklyPainPoint[] = [
  { id: 'pp1', topic: '吸力不足 / 不够力', frequency: 28, severity: 'high', solution: '制作吸力测试科普视频，强调M5吸力数据与医院级对比', affectedProducts: ['M5'] },
  { id: 'pp2', topic: '使用噪音大', frequency: 22, severity: 'medium', solution: '在办公场景内容中强调静音优势，提供分贝对比数据', affectedProducts: ['M5', 'S12'] },
  { id: 'pp3', topic: 'App连接不稳定', frequency: 18, severity: 'high', solution: '技术团队优化App稳定性，同时在社区主动分享使用技巧', affectedProducts: ['M5'] },
  { id: 'pp4', topic: '配件难买 / 贵', frequency: 15, severity: 'medium', solution: '推出配件套装优惠，增加配件购买渠道透明度', affectedProducts: ['M5', 'S12'] },
  { id: 'pp5', topic: '清洗不便', frequency: 12, severity: 'low', solution: '制作清洗教程短视频，强调可拆卸设计和清洗便利性', affectedProducts: ['M5'] },
  { id: 'pp6', topic: '电池续航短', frequency: 10, severity: 'medium', solution: '在内容中强调实际使用场景续航（3-4次），推荐充电配件', affectedProducts: ['M5'] },
];

export const weeklyTopicEvolutions: WeeklyTopicEvolution[] = [
  { topic: '产品对比与选购', volume: [12, 15, 18, 22, 20, 16, 14], sentiment: 'positive', lifecycle: 'rising', prediction: '预计下周继续增长，增长率为15%', predictionConfidence: 82 },
  { topic: '使用体验分享', volume: [18, 16, 14, 15, 12, 10, 11], sentiment: 'positive', lifecycle: 'peak', prediction: '即将进入平稳期，保持现有内容节奏', predictionConfidence: 75 },
  { topic: '背奶/职场妈妈', volume: [8, 10, 12, 15, 18, 14, 12], sentiment: 'positive', lifecycle: 'rising', prediction: '快速增长期，建议加大投入', predictionConfidence: 88 },
  { topic: '价格与性价比', volume: [14, 12, 10, 8, 7, 6, 5], sentiment: 'neutral', lifecycle: 'declining', prediction: '讨论量下降，关注竞品促销动态', predictionConfidence: 70 },
  { topic: '问题求助与故障', volume: [10, 12, 14, 16, 18, 15, 12], sentiment: 'negative', lifecycle: 'rising', prediction: '负面投诉需紧急干预，预计下周达到峰值', predictionConfidence: 78 },
];

export const weeklyReviews: WeeklyReview[] = [
  { metric: '帖子回复率', value: '78%', target: '80%', status: 'warning', contentROI: 3.2, engagementRate: 12.5, communityEffectiveness: 76 },
  { metric: '负面响应时间', value: '4.2小时', target: '<4小时', status: 'good', contentROI: 4.8, engagementRate: 18.2, communityEffectiveness: 82 },
  { metric: 'UGC素材收集', value: '18条', target: '15条', status: 'good', contentROI: 5.5, engagementRate: 22.0, communityEffectiveness: 88 },
  { metric: '高意向转化', value: '12条', target: '15条', status: 'bad', contentROI: 2.1, engagementRate: 8.5, communityEffectiveness: 62 },
  { metric: '品牌正面率', value: '53.4%', target: '55%', status: 'warning', contentROI: 3.8, engagementRate: 14.0, communityEffectiveness: 74 },
];

// 周报基础数据 —— 使用非线性独立基准，避免日报简单乘法
export const weeklyOverview = {
  newPosts: 293,
  newPostsTrend: 9.3,
  positiveRate: 51.2,
  negativeRate: 15.8,
  neutralRate: 33.0,
  alerts: 9,
  highIntent: 47,
  ugc: 17,
  updatedAt: formatDateTime(),
};

export const weeklyAlerts: import('./dailyReportMock').DailyAlert[] = [
  {
    id: 'wa1',
    level: 'critical',
    title: 'My Momcozy M5 just stopped working after 2 weeks — terrible quality',
    subreddit: 'breastfeeding',
    upvotes: 34,
    comments: 28,
    growth: 18,
    sentiment: 'negative',
    intent: 'Bug Report',
    summary: '用户投诉M5使用两周后故障，评论区已有其他用户附和',
    url: '#',
    time: '3小时前',
    discoveredAt: '3小时前',
    respondedAt: '2小时前',
    impactEstimate: { potentialLoss: 2400, affectedCustomers: 12 },
  },
  {
    id: 'wa2',
    level: 'warning',
    title: 'Momcozy vs Elvie — which one is actually better?',
    subreddit: 'breastfeeding',
    upvotes: 67,
    comments: 42,
    growth: 12,
    sentiment: 'neutral',
    intent: 'Comparison',
    summary: '直接竞品对比帖，M5在评论区提及较多但部分用户倾向Elvie',
    url: '#',
    time: '5小时前',
    discoveredAt: '5小时前',
    respondedAt: '4小时前',
    impactEstimate: { potentialLoss: 1800, affectedCustomers: 8 },
  },
  {
    id: 'wa3',
    level: 'warning',
    title: 'Suction on Momcozy M5 is way too weak compared to my hospital pump',
    subreddit: 'breastpumps',
    upvotes: 23,
    comments: 19,
    growth: 8,
    sentiment: 'negative',
    intent: 'Comparison',
    summary: '用户对比M5吸力与医院级泵，评论区出现负面讨论',
    url: '#',
    time: '6小时前',
    discoveredAt: '6小时前',
    impactEstimate: { potentialLoss: 1200, affectedCustomers: 5 },
  },
  {
    id: 'wa4',
    level: 'info',
    title: 'Looking for a quiet wearable breast pump for work — any recommendations?',
    subreddit: 'breastfeeding',
    upvotes: 124,
    comments: 86,
    growth: 6,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    summary: '高意向求助帖，适合品牌介入推荐',
    url: '#',
    time: '1天前',
    discoveredAt: '1天前',
    impactEstimate: { potentialLoss: 0, affectedCustomers: 0 },
  },
  {
    id: 'wa5',
    level: 'warning',
    title: 'Is Spectra S1 still worth it in 2026?',
    subreddit: 'breastpumps',
    upvotes: 45,
    comments: 32,
    growth: 4,
    sentiment: 'neutral',
    intent: 'Comparison',
    summary: '竞品Spectra讨论帖，需关注Momcozy是否被提及',
    url: '#',
    time: '2天前',
    discoveredAt: '2天前',
    impactEstimate: { potentialLoss: 800, affectedCustomers: 3 },
  },
  {
    id: 'wa6',
    level: 'critical',
    title: 'Momcozy customer service is ignoring my refund request',
    subreddit: 'Mommit',
    upvotes: 56,
    comments: 41,
    growth: 22,
    sentiment: 'negative',
    intent: 'Bug Report',
    summary: '售后投诉帖，发酵速度快，需紧急介入',
    url: '#',
    time: '4小时前',
    discoveredAt: '4小时前',
    respondedAt: '3小时前',
    impactEstimate: { potentialLoss: 3200, affectedCustomers: 15 },
  },
  {
    id: 'wa7',
    level: 'info',
    title: 'What pump do you recommend for exclusive pumping?',
    subreddit: 'NewParents',
    upvotes: 89,
    comments: 67,
    growth: 5,
    sentiment: 'neutral',
    intent: 'Question',
    summary: '新手妈妈选泵求助，适合内容输出',
    url: '#',
    time: '1天前',
    discoveredAt: '1天前',
    impactEstimate: { potentialLoss: 0, affectedCustomers: 0 },
  },
  {
    id: 'wa8',
    level: 'warning',
    title: 'Elvie pump noise level vs Momcozy — real comparison',
    subreddit: 'breastfeeding',
    upvotes: 78,
    comments: 53,
    growth: 15,
    sentiment: 'neutral',
    intent: 'Comparison',
    summary: '竞品直接对比帖，Elvie静音优势被强调',
    url: '#',
    time: '12小时前',
    discoveredAt: '12小时前',
    impactEstimate: { potentialLoss: 1600, affectedCustomers: 7 },
  },
  {
    id: 'wa9',
    level: 'info',
    title: 'Best breast pump for working moms in 2026?',
    subreddit: 'babybumps',
    upvotes: 156,
    comments: 98,
    growth: 9,
    sentiment: 'positive',
    intent: 'Purchase Intent',
    summary: '高意向购买帖，适合品牌介入',
    url: '#',
    time: '2天前',
    discoveredAt: '2天前',
    impactEstimate: { potentialLoss: 0, affectedCustomers: 0 },
  },
  {
    id: 'wa10',
    level: 'warning',
    title: 'Willow 3.0 leaks every time I use it — alternatives?',
    subreddit: 'breastfeeding',
    upvotes: 34,
    comments: 27,
    growth: 7,
    sentiment: 'negative',
    intent: 'Comparison',
    summary: '竞品负面帖，Momcozy可间接获益',
    url: '#',
    time: '3天前',
    discoveredAt: '3天前',
    impactEstimate: { potentialLoss: -600, affectedCustomers: -2 },
  },
  {
    id: 'wa11',
    level: 'info',
    title: 'How to clean wearable breast pump properly?',
    subreddit: 'breastpumps',
    upvotes: 67,
    comments: 45,
    growth: 3,
    sentiment: 'neutral',
    intent: 'Question',
    summary: '使用教程类需求，适合内容输出',
    url: '#',
    time: '4天前',
    discoveredAt: '4天前',
    impactEstimate: { potentialLoss: 0, affectedCustomers: 0 },
  },
  {
    id: 'wa12',
    level: 'warning',
    title: 'Medela vs Momcozy — hospital grade suction comparison',
    subreddit: 'breastpumps',
    upvotes: 45,
    comments: 38,
    growth: 11,
    sentiment: 'neutral',
    intent: 'Comparison',
    summary: '专业参数对比帖，需以专业形象介入',
    url: '#',
    time: '5小时前',
    discoveredAt: '5小时前',
    impactEstimate: { potentialLoss: 1000, affectedCustomers: 4 },
  },
];

export const weeklyNewPosts: import('./dailyReportMock').DailyNewPost[] = [
  {
    id: 'wd1',
    title: 'Looking for a quiet wearable breast pump for work — any recommendations?',
    subreddit: 'breastfeeding',
    author: 'newmom2024',
    time: '2小时前',
    upvotes: 1247,
    comments: 186,
    intentScore: 92,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    action: 'reply',
    businessValueTag: 'high_intent',
  },
  {
    id: 'wd2',
    title: "Just got my Momcozy pump and it's been a game changer!",
    subreddit: 'babybumps',
    author: 'happymom_89',
    time: '6小时前',
    upvotes: 2156,
    comments: 312,
    intentScore: 45,
    sentiment: 'positive',
    intent: 'UGC',
    action: 'collect',
    businessValueTag: 'ugc',
  },
  {
    id: 'wd3',
    title: 'Is Momcozy worth the price? Honest reviews please.',
    subreddit: 'breastfeeding',
    author: 'budgetmom2024',
    time: '12小时前',
    upvotes: 678,
    comments: 98,
    intentScore: 88,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    action: 'reply',
    businessValueTag: 'high_intent',
  },
  {
    id: 'wd4',
    title: 'Struggling with my current pump — looking for alternatives',
    subreddit: 'breastfeeding',
    author: 'tiredmomma',
    time: '14小时前',
    upvotes: 543,
    comments: 76,
    intentScore: 78,
    sentiment: 'negative',
    intent: 'Purchase Intent',
    action: 'reply',
    businessValueTag: 'opportunity',
  },
  {
    id: 'wd5',
    title: 'Momcozy M5 vs Elvie — which one is better for exclusive pumping?',
    subreddit: 'breastfeeding',
    author: 'pumpingmomma',
    time: '4小时前',
    upvotes: 892,
    comments: 143,
    intentScore: 85,
    sentiment: 'neutral',
    intent: 'Comparison',
    action: 'reply',
    businessValueTag: 'competitor',
  },
  {
    id: 'wd6',
    title: 'My Momcozy M5 just stopped working after 2 weeks — terrible quality',
    subreddit: 'breastfeeding',
    author: 'angrycustomer',
    time: '3小时前',
    upvotes: 34,
    comments: 28,
    intentScore: 60,
    sentiment: 'negative',
    intent: 'Bug Report',
    action: 'escalate',
    businessValueTag: 'crisis',
  },
  {
    id: 'wd7',
    title: 'Back to work pumping setup — what works best?',
    subreddit: 'breastfeeding',
    author: 'workingmom2024',
    time: '1天前',
    upvotes: 456,
    comments: 89,
    intentScore: 82,
    sentiment: 'neutral',
    intent: 'Question',
    action: 'reply',
    businessValueTag: 'high_intent',
  },
  {
    id: 'wd8',
    title: 'Love my Momcozy M5! 3 months in and still going strong',
    subreddit: 'babybumps',
    author: 'loyaluser_22',
    time: '2天前',
    upvotes: 1234,
    comments: 156,
    intentScore: 40,
    sentiment: 'positive',
    intent: 'UGC',
    action: 'collect',
    businessValueTag: 'ugc',
  },
  {
    id: 'wd9',
    title: 'Elvie vs Momcozy suction test — side by side',
    subreddit: 'breastpumps',
    author: 'techmom_99',
    time: '1天前',
    upvotes: 567,
    comments: 134,
    intentScore: 75,
    sentiment: 'neutral',
    intent: 'Comparison',
    action: 'monitor',
    businessValueTag: 'competitor',
  },
  {
    id: 'wd10',
    title: 'New mom here — what should I look for in a breast pump?',
    subreddit: 'NewParents',
    author: 'firsttimemom',
    time: '3天前',
    upvotes: 345,
    comments: 67,
    intentScore: 90,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    action: 'reply',
    businessValueTag: 'high_intent',
  },
];

export const weeklyCommunityStatus: import('./dailyReportMock').DailyCommunityStatus[] = [
  { name: 'breastfeeding', displayName: 'r/breastfeeding', newPosts: 142, topPostUpvotes: 1247, sentiment: 'positive', trend: 'up', activityIndex: 84, brandMentionRate: 32, sentimentChangeSpeed: 1.8 },
  { name: 'babybumps', displayName: 'r/babybumps', newPosts: 78, topPostUpvotes: 2156, sentiment: 'positive', trend: 'stable', activityIndex: 78, brandMentionRate: 26, sentimentChangeSpeed: 0.6 },
  { name: 'NewParents', displayName: 'r/NewParents', newPosts: 65, topPostUpvotes: 345, sentiment: 'neutral', trend: 'up', activityIndex: 68, brandMentionRate: 20, sentimentChangeSpeed: 1.2 },
  { name: 'breastpumps', displayName: 'r/breastpumps', newPosts: 30, topPostUpvotes: 567, sentiment: 'negative', trend: 'down', activityIndex: 62, brandMentionRate: 48, sentimentChangeSpeed: -2.8 },
  { name: 'Mommit', displayName: 'r/Mommit', newPosts: 33, topPostUpvotes: 234, sentiment: 'neutral', trend: 'stable', activityIndex: 48, brandMentionRate: 16, sentimentChangeSpeed: 0.3 },
  { name: 'pregnant', displayName: 'r/pregnant', newPosts: 18, topPostUpvotes: 89, sentiment: 'positive', trend: 'up', activityIndex: 42, brandMentionRate: 10, sentimentChangeSpeed: 0.9 },
];

export const weeklyActionItems: import('./dailyReportMock').DailyActionItem[] = [
  { id: 'wact1', type: 'reply', title: '回复「静音办公场景」高意向帖子（12条）', urgency: 'high', due: '今日', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'wact2', type: 'reply', title: '回复「M5 vs Elvie」对比帖中的品牌劣势', urgency: 'high', due: '今日', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'wact3', type: 'escalate', title: '处理「M5故障」投诉帖子，转客服团队', urgency: 'high', due: '立即', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'wact4', type: 'collect', title: '收集 UGC 素材（本周19条）', urgency: 'medium', due: '本周', completed: true, priorityMatrix: 'not_urgent_important' },
  { id: 'wact5', type: 'reply', title: '回复「新手选泵」求助类帖子（15条）', urgency: 'medium', due: '本周', completed: false, priorityMatrix: 'not_urgent_important' },
  { id: 'wact6', type: 'monitor', title: '关注「吸力弱」讨论趋势', urgency: 'medium', due: '持续', completed: false, priorityMatrix: 'not_urgent_not_important' },
  { id: 'wact7', type: 'reply', title: '制作「背奶职场妈妈」内容系列', urgency: 'high', due: '本周', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'wact8', type: 'escalate', title: '处理售后退款投诉，转客服团队', urgency: 'high', due: '立即', completed: false, priorityMatrix: 'urgent_important' },
];

export const weeklySentimentTrend = [
  { label: '周一', positive: 52, negative: 12, neutral: 36, volume: 48 },
  { label: '周二', positive: 54, negative: 15, neutral: 31, volume: 52 },
  { label: '周三', positive: 56, negative: 14, neutral: 30, volume: 55 },
  { label: '周四', positive: 51, negative: 16, neutral: 33, volume: 49 },
  { label: '周五', positive: 55, negative: 13, neutral: 32, volume: 53 },
  { label: '周六', positive: 58, negative: 11, neutral: 31, volume: 47 },
  { label: '周日', positive: 53, negative: 14, neutral: 33, volume: 44 },
];

export const weeklyPlans: WeeklyPlan[] = [
  { id: 'p1', action: '制作「背奶职场妈妈」内容系列', priority: 'high', community: 'breastfeeding, babybumps', topic: '背奶/职场', expectedImpact: '覆盖核心目标人群，提升品牌好感度' },
  { id: 'p2', action: '介入竞品对比帖，提供客观参数', priority: 'high', community: 'breastfeeding', topic: '竞品对比', expectedImpact: '在M5 vs Elvie讨论中建立专业形象' },
  { id: 'p3', action: '制作「吸力测试」科普内容', priority: 'high', community: 'breastpumps', topic: '吸力', expectedImpact: '回应用户关切，降低负面投诉' },
  { id: 'p4', action: '在r/NewParents发布选泵指南', priority: 'medium', community: 'NewParents', topic: '新手选泵', expectedImpact: '捕获新手妈妈转化机会' },
  { id: 'p5', action: '优化客服响应SOP，目标2小时', priority: 'medium', expectedImpact: '缩短负面响应时间，降低发酵风险' },
];

// ========== 周报增强数据 ==========

export interface ShareOfVoiceData {
  label: string;
  momcozy: number;
  elvie: number;
  spectra: number;
  medela: number;
  willow: number;
  lansinoh: number;
}

export const weeklyShareOfVoice: ShareOfVoiceData[] = [
  { label: '周一', momcozy: 28, elvie: 22, spectra: 12, medela: 18, willow: 8, lansinoh: 12 },
  { label: '周二', momcozy: 30, elvie: 21, spectra: 13, medela: 17, willow: 7, lansinoh: 12 },
  { label: '周三', momcozy: 32, elvie: 20, spectra: 12, medela: 16, willow: 8, lansinoh: 12 },
  { label: '周四', momcozy: 29, elvie: 23, spectra: 11, medela: 18, willow: 7, lansinoh: 12 },
  { label: '周五', momcozy: 31, elvie: 22, spectra: 12, medela: 17, willow: 6, lansinoh: 12 },
  { label: '周六', momcozy: 33, elvie: 20, spectra: 13, medela: 16, willow: 8, lansinoh: 10 },
  { label: '周日', momcozy: 30, elvie: 21, spectra: 12, medela: 17, willow: 8, lansinoh: 12 },
];

export interface OpportunityHeatmapItem {
  category: string;
  opportunity: string;
  score: number;
  trend: 'up' | 'down' | 'stable';
}

export const weeklyOpportunityHeatmap: OpportunityHeatmapItem[] = [
  { category: '背奶场景', opportunity: '职场妈妈内容', score: 92, trend: 'up' },
  { category: '静音设计', opportunity: '差异化传播', score: 85, trend: 'up' },
  { category: 'UGC口碑', opportunity: 'testimonial收集', score: 88, trend: 'stable' },
  { category: '新手科普', opportunity: '选泵指南', score: 76, trend: 'up' },
  { category: '价格敏感', opportunity: '性价比计算', score: 72, trend: 'stable' },
  { category: '竞品对比', opportunity: '参数科普', score: 80, trend: 'up' },
];

export interface PainPointCluster {
  id: string;
  category: string;
  frequency: number;
  severity: number;
  solution: string;
}

export const weeklyPainPointClusters: PainPointCluster[] = [
  { id: 'pp1', category: '吸力不足', frequency: 24, severity: 7.2, solution: '制作吸力测试科普内容' },
  { id: 'pp2', category: '故障投诉', frequency: 18, severity: 8.5, solution: '优化客服SOP，建立快速响应' },
  { id: 'pp3', category: '售后退款', frequency: 12, severity: 7.8, solution: '优化退款流程，主动关怀' },
  { id: 'pp4', category: '噪音问题', frequency: 15, severity: 6.5, solution: '强调静音优势，对比实测' },
  { id: 'pp5', category: '配件价格', frequency: 10, severity: 5.5, solution: '推出配件套餐优惠' },
];

export interface CompetitorPositioning {
  name: string;
  positioning: string;
  mindShare: number;
  priceSensitivity: number;
}

export const weeklyCompetitorPositioning: CompetitorPositioning[] = [
  { name: 'Elvie', positioning: '高端科技+静音设计', mindShare: 28, priceSensitivity: 65 },
  { name: 'Spectra', positioning: '医院级专业吸力', mindShare: 18, priceSensitivity: 72 },
  { name: 'Medela', positioning: '传统品牌信任', mindShare: 22, priceSensitivity: 58 },
  { name: 'Willow', positioning: '极致便携性', mindShare: 8, priceSensitivity: 78 },
  { name: 'Lansinoh', positioning: '性价比入门', mindShare: 12, priceSensitivity: 85 },
];

export interface TopicEvolutionData {
  topic: string;
  day1: number;
  day2: number;
  day3: number;
  day4: number;
  day5: number;
  day6: number;
  day7: number;
  prediction: number;
  predictionAccuracy: number;
}

export const weeklyTopicEvolution: TopicEvolutionData[] = [
  { topic: '背奶职场', day1: 12, day2: 18, day3: 25, day4: 32, day5: 28, day6: 35, day7: 42, prediction: 45, predictionAccuracy: 92 },
  { topic: 'M5故障', day1: 8, day2: 12, day3: 15, day4: 14, day5: 18, day6: 16, day7: 20, prediction: 18, predictionAccuracy: 85 },
  { topic: 'Elvie对比', day1: 15, day2: 18, day3: 20, day4: 22, day5: 25, day6: 28, day7: 30, prediction: 32, predictionAccuracy: 88 },
  { topic: '新手选泵', day1: 10, day2: 12, day3: 14, day4: 16, day5: 18, day6: 20, day7: 22, prediction: 24, predictionAccuracy: 90 },
];

export interface ContentStrategyROI {
  metric: string;
  value: string;
  roi: number;
}

export const weeklyContentStrategyROI: ContentStrategyROI[] = [
  { metric: 'UGC内容转化', value: '18条', roi: 3.2 },
  { metric: '竞品对比回复', value: '12条', roi: 2.8 },
  { metric: '新手指南发布', value: '5篇', roi: 4.1 },
  { metric: '品牌故事植入', value: '8篇', roi: 2.5 },
];

// 兼容导出 —— 供 reportEngine.ts 使用
