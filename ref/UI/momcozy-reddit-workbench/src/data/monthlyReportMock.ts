// 月报 Mock 数据 —— 30天聚合
import { formatDateTime } from '../utils/date';
import type { SentimentLevel } from './dailyReportMock';

export interface MonthlyBrandHealth {
  metric: string;
  current: number;
  lastMonth: number;
  change: number;
  unit: string;
}

export interface MonthlyCompetitorShare {
  name: string;
  share: number; // 讨论量占比
  positiveRate: number;
  mentionGrowth: number; // 月环比
  topTopic: string;
}

export interface MonthlyCommunityROI {
  name: string;
  displayName: string;
  posts: number;
  leads: number;
  conversionRate: number;
  quality: 'high' | 'medium' | 'low';
  roi: string; // 描述
}

export interface MonthlyTopicEvolution {
  topic: string;
  currentVolume: number;
  lastMonthVolume: number;
  growth: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  lifecycle: 'rising' | 'peak' | 'stable' | 'declining';
  forecast: string;
  predictionAccuracy?: number; // 话题预测准确率
}

export interface MonthlyKPI {
  metric: string;
  value: string;
  target: string;
  achievement: number; // 达成率
  status: 'good' | 'warning' | 'bad';
}

export interface MonthlyStrategicAdvice {
  id: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  expectedImpact: string;
  timeframe: string;
  // 战略建议增强
  resourceAllocation?: {
    budget: string;
    manpower: string;
    time: string;
  };
  expectedROI?: number; // 预期ROI
}

// 品牌健康度雷达图数据
export interface BrandHealthRadar {
  dimension: string;
  value: number; // 0-100
  benchmark: number; // 行业基准
}

// 竞争态势矩阵
export interface CompetitiveMatrix {
  name: string;
  marketShare: number; // 市场份额
  growthRate: number; // 增长率
  quadrant: 'star' | 'question' | 'cash-cow' | 'dog';
}

// 品类矩阵
export interface CategoryMatrix {
  category: string;
  volume: number;
  growthRate: number;
  conversionRate: number;
  roi: number;
}

export const monthlyBrandHealth: MonthlyBrandHealth[] = [
  { metric: '品牌提及量', current: 1248, lastMonth: 1086, change: 14.9, unit: '次' },
  { metric: '正面情感率', current: 53.4, lastMonth: 48.2, change: 10.8, unit: '%' },
  { metric: '负面情感率', current: 14.4, lastMonth: 18.6, change: -22.6, unit: '%' },
  { metric: '口碑NPS', current: 39, lastMonth: 30, change: 30.0, unit: '分' },
  { metric: '平均互动数', current: 18.5, lastMonth: 16.2, change: 14.2, unit: '条/帖' },
  { metric: '响应速度', current: 4.2, lastMonth: 6.8, change: -38.2, unit: '小时' },
];

// 品牌健康度评分与雷达图
export const monthlyBrandHealthScore = 78; // 0-100

export const monthlyBrandHealthRadar: BrandHealthRadar[] = [
  { dimension: '声量', value: 82, benchmark: 70 },
  { dimension: '情感', value: 78, benchmark: 72 },
  { dimension: '参与度', value: 85, benchmark: 68 },
  { dimension: '转化', value: 72, benchmark: 65 },
  { dimension: '忠诚度', value: 76, benchmark: 70 },
  { dimension: '创新度', value: 68, benchmark: 62 },
];

// 6个月品牌健康度趋势
export const monthlyBrandHealthTrend = [
  { label: '2月', value: 42 },
  { label: '3月', value: 45 },
  { label: '4月', value: 48 },
  { label: '5月', value: 50 },
  { label: '6月', value: 52 },
  { label: '7月', value: 53.4 },
];

export const monthlyCompetitorShares: MonthlyCompetitorShare[] = [
  { name: 'Momcozy', share: 35.2, positiveRate: 53, mentionGrowth: 14.9, topTopic: '性价比' },
  { name: 'Elvie', share: 28.5, positiveRate: 72, mentionGrowth: 18.3, topTopic: '静音设计' },
  { name: 'Spectra', share: 15.8, positiveRate: 68, mentionGrowth: 5.2, topTopic: '医院级吸力' },
  { name: 'Medela', share: 12.3, positiveRate: 60, mentionGrowth: -2.1, topTopic: '品牌信任' },
  { name: 'Willow', share: 8.2, positiveRate: 65, mentionGrowth: -8.5, topTopic: '便携性' },
];

// 竞争态势矩阵（市场份额 vs 增长率）
export const monthlyCompetitiveMatrix: CompetitiveMatrix[] = [
  { name: 'Momcozy', marketShare: 35.2, growthRate: 14.9, quadrant: 'star' },
  { name: 'Elvie', marketShare: 28.5, growthRate: 18.3, quadrant: 'star' },
  { name: 'Spectra', marketShare: 15.8, growthRate: 5.2, quadrant: 'cash-cow' },
  { name: 'Medela', marketShare: 12.3, growthRate: -2.1, quadrant: 'dog' },
  { name: 'Willow', marketShare: 8.2, growthRate: -8.5, quadrant: 'dog' },
];

export const monthlyCommunityROI: MonthlyCommunityROI[] = [
  { name: 'breastfeeding', displayName: 'r/breastfeeding', posts: 142, leads: 38, conversionRate: 26.8, quality: 'high', roi: '每帖产出0.27线索，核心转化社区' },
  { name: 'babybumps', displayName: 'r/babybumps', posts: 78, leads: 22, conversionRate: 28.2, quality: 'high', roi: '每帖产出0.28线索，口碑传播社区' },
  { name: 'NewParents', displayName: 'r/NewParents', posts: 65, leads: 12, conversionRate: 18.5, quality: 'medium', roi: '每帖产出0.18线索，转化待提升' },
  { name: 'breastpumps', displayName: 'r/breastpumps', posts: 30, leads: 18, conversionRate: 60.0, quality: 'high', roi: '每帖产出0.6线索，垂直高转化社区' },
  { name: 'Mommit', displayName: 'r/Mommit', posts: 33, leads: 5, conversionRate: 15.2, quality: 'low', roi: '每帖产出0.15线索，活跃度低' },
];

// 品类矩阵
export const monthlyCategoryMatrix: CategoryMatrix[] = [
  { category: '吸奶器', volume: 542, growthRate: 18.5, conversionRate: 28.2, roi: 4.2 },
  { category: '哺乳内衣', volume: 186, growthRate: 32.1, conversionRate: 15.6, roi: 3.8 },
  { category: '背奶包', volume: 124, growthRate: 45.2, conversionRate: 12.4, roi: 2.9 },
  { category: '储奶袋', volume: 98, growthRate: 8.5, conversionRate: 22.1, roi: 3.5 },
  { category: '乳头霜', volume: 76, growthRate: 15.3, conversionRate: 18.9, roi: 3.1 },
];

export const monthlyTopicEvolution: MonthlyTopicEvolution[] = [
  { topic: '产品对比与选购', currentVolume: 89, lastMonthVolume: 62, growth: 43.5, sentiment: 'positive', lifecycle: 'rising', forecast: '预计下月继续增长，建议持续投入内容', predictionAccuracy: 92 },
  { topic: '使用体验分享', currentVolume: 76, lastMonthVolume: 68, growth: 11.8, sentiment: 'positive', lifecycle: 'stable', forecast: '保持现有内容节奏，产出稳定', predictionAccuracy: 88 },
  { topic: '背奶/职场妈妈', currentVolume: 62, lastMonthVolume: 38, growth: 63.2, sentiment: 'positive', lifecycle: 'rising', forecast: '话题快速上升，建议加大投入', predictionAccuracy: 85 },
  { topic: '价格与性价比', currentVolume: 48, lastMonthVolume: 52, growth: -7.7, sentiment: 'neutral', lifecycle: 'stable', forecast: '讨论量小幅下降，关注竞品价格动态', predictionAccuracy: 90 },
  { topic: '问题求助与故障', currentVolume: 41, lastMonthVolume: 48, growth: -14.6, sentiment: 'negative', lifecycle: 'declining', forecast: '负面投诉减少，产品改进成效显现', predictionAccuracy: 94 },
  { topic: '新手妈妈科普', currentVolume: 32, lastMonthVolume: 22, growth: 45.5, sentiment: 'positive', lifecycle: 'rising', forecast: '新手需求增长，建议制作科普系列', predictionAccuracy: 87 },
];

export const monthlyKPIs: MonthlyKPI[] = [
  { metric: '总帖子覆盖', value: '1,248', target: '1,000', achievement: 124.8, status: 'good' },
  { metric: '正面情感率', value: '53.4%', target: '55%', achievement: 97.1, status: 'warning' },
  { metric: '负面响应时间', value: '4.2小时', target: '<4小时', achievement: 95.2, status: 'warning' },
  { metric: '高意向转化', value: '56', target: '60', achievement: 93.3, status: 'warning' },
  { metric: 'UGC素材收集', value: '72', target: '50', achievement: 144.0, status: 'good' },
  { metric: '社区运营覆盖', value: '6', target: '5', achievement: 120.0, status: 'good' },
];

// KPI 趋势（6个月达成率变化）
export const monthlyKPITrend = [
  { label: '2月', achievement: 88 },
  { label: '3月', achievement: 92 },
  { label: '4月', achievement: 95 },
  { label: '5月', achievement: 98 },
  { label: '6月', achievement: 102 },
  { label: '7月', achievement: 112 },
];

export const monthlyStrategicAdvices: MonthlyStrategicAdvice[] = [
  {
    id: 'sa1',
    title: '巩固「性价比」核心定位',
    description: 'Momcozy在Reddit的讨论份额中「性价比」是最强标签。建议持续强化该认知，同时在竞品价格上升期加大传播力度',
    priority: 'high',
    expectedImpact: '在价格敏感用户中建立品牌首选心智',
    timeframe: '下月',
    resourceAllocation: { budget: '$8K', manpower: '2人', time: '4周' },
    expectedROI: 3.5,
  },
  {
    id: 'sa2',
    title: '建立「静音设计」差异化认知',
    description: '竞品Elvie在「静音设计」话题上快速增长。Momcozy需要在该维度建立差异化认知，避免在该赛道被竞品超越',
    priority: 'high',
    expectedImpact: '在职场背奶场景建立与Elvie的差异化优势',
    timeframe: '下月-2月',
    resourceAllocation: { budget: '$12K', manpower: '3人', time: '8周' },
    expectedROI: 2.8,
  },
  {
    id: 'sa3',
    title: '深耕垂直社区 r/breastpumps',
    description: '该社区转化率最高（60%），但覆盖量不足。建议加大在该社区的投入，包括专业内容输出和运营介入',
    priority: 'medium',
    expectedImpact: '提升垂直社区覆盖量和线索产出',
    timeframe: '下月',
    resourceAllocation: { budget: '$5K', manpower: '1人', time: '4周' },
    expectedROI: 4.2,
  },
  {
    id: 'sa4',
    title: '拓展孕期社区教育（r/babybumps）',
    description: '该社区正向口碑传播效应强，适合品牌教育。建议制作新手妈妈选泵指南系列内容',
    priority: 'medium',
    expectedImpact: '在孕期阶段建立品牌认知，提升后续转化率',
    timeframe: '2-3月',
    resourceAllocation: { budget: '$6K', manpower: '2人', time: '6周' },
    expectedROI: 3.0,
  },
  {
    id: 'sa5',
    title: '优化客服响应SOP',
    description: '当前负面响应时间为4.2小时，目标<4小时。需要建立更快速的响应机制，确保黄金1小时内完成负面干预',
    priority: 'high',
    expectedImpact: '将负面投诉发酵时间从6小时压缩到2小时',
    timeframe: '下月',
    resourceAllocation: { budget: '$3K', manpower: '1人', time: '2周' },
    expectedROI: 5.5,
  },
];

// 月报基础数据 —— 使用非线性独立基准，避免日报/周报简单乘法
export const monthlyOverview = {
  newPosts: 1156,
  newPostsTrend: 11.7,
  positiveRate: 49.5,
  negativeRate: 16.2,
  neutralRate: 34.3,
  alerts: 34,
  highIntent: 189,
  ugc: 71,
  updatedAt: formatDateTime(),
  sentimentLevel: 'watch' as SentimentLevel,
  sentimentLevelLabel: '关注',
};

export const monthlyAlerts: import('./dailyReportMock').DailyAlert[] = [
  {
    id: 'ma1',
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
    impactEstimate: { potentialLoss: 2400, affectedCustomers: 12 },
  },
  {
    id: 'ma2',
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
    impactEstimate: { potentialLoss: 1200, affectedCustomers: 5 },
  },
  {
    id: 'ma3',
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
    id: 'ma4',
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
    id: 'ma5',
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
    impactEstimate: { potentialLoss: 1200, affectedCustomers: 5 },
  },
  {
    id: 'ma6',
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
    impactEstimate: { potentialLoss: 2400, affectedCustomers: 12 },
  },
  {
    id: 'ma7',
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
    id: 'ma8',
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
    impactEstimate: { potentialLoss: 1200, affectedCustomers: 5 },
  },
  {
    id: 'ma9',
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
    id: 'ma10',
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
    impactEstimate: { potentialLoss: 1200, affectedCustomers: 5 },
  },
  {
    id: 'ma11',
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
    id: 'ma12',
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
    impactEstimate: { potentialLoss: 1200, affectedCustomers: 5 },
  },
  {
    id: 'ma13',
    level: 'critical',
    title: 'Momcozy M5 heating issue during long pumping sessions',
    subreddit: 'breastfeeding',
    upvotes: 42,
    comments: 35,
    growth: 19,
    sentiment: 'negative',
    intent: 'Bug Report',
    summary: '长时间使用发热投诉，需产品团队关注',
    url: '#',
    time: '1天前',
    discoveredAt: '1天前',
    impactEstimate: { potentialLoss: 2400, affectedCustomers: 12 },
  },
  {
    id: 'ma14',
    level: 'warning',
    title: 'Price increase on Momcozy M5 — still worth it?',
    subreddit: 'breastfeeding',
    upvotes: 89,
    comments: 62,
    growth: 14,
    sentiment: 'neutral',
    intent: 'Comparison',
    summary: '价格上涨讨论，需关注用户价格敏感度',
    url: '#',
    time: '2天前',
    discoveredAt: '2天前',
    impactEstimate: { potentialLoss: 1200, affectedCustomers: 5 },
  },
  {
    id: 'ma15',
    level: 'info',
    title: 'First time mom pump guide 2026 edition',
    subreddit: 'NewParents',
    upvotes: 234,
    comments: 145,
    growth: 8,
    sentiment: 'positive',
    intent: 'Question',
    summary: '新手妈妈指南帖，适合品牌内容合作',
    url: '#',
    time: '3天前',
    discoveredAt: '3天前',
    impactEstimate: { potentialLoss: 0, affectedCustomers: 0 },
  },
];

export const monthlyNewPosts: import('./dailyReportMock').DailyNewPost[] = [
  {
    id: 'md1',
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
    id: 'md2',
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
    id: 'md3',
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
    id: 'md4',
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
    businessValueTag: 'high_intent',
  },
  {
    id: 'md5',
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
    id: 'md6',
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
    id: 'md7',
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
    id: 'md8',
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
    id: 'md9',
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
    id: 'md10',
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
  {
    id: 'md11',
    title: 'Momcozy M5 battery life — real world test results',
    subreddit: 'breastpumps',
    author: 'testermom',
    time: '5天前',
    upvotes: 789,
    comments: 123,
    intentScore: 65,
    sentiment: 'positive',
    intent: 'UGC',
    action: 'collect',
    businessValueTag: 'ugc',
  },
  {
    id: 'md12',
    title: 'Returning to work — pump recommendations for office use?',
    subreddit: 'breastfeeding',
    author: 'officemom2024',
    time: '6天前',
    upvotes: 567,
    comments: 98,
    intentScore: 88,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    action: 'reply',
    businessValueTag: 'high_intent',
  },
];

export const monthlyCommunityStatus: import('./dailyReportMock').DailyCommunityStatus[] = [
  { name: 'breastfeeding', displayName: 'r/breastfeeding', newPosts: 542, topPostUpvotes: 1247, sentiment: 'positive', trend: 'up', activityIndex: 92, brandMentionRate: 28, sentimentChangeSpeed: 1.2 },
  { name: 'babybumps', displayName: 'r/babybumps', newPosts: 318, topPostUpvotes: 2156, sentiment: 'positive', trend: 'stable', activityIndex: 85, brandMentionRate: 22, sentimentChangeSpeed: 0.4 },
  { name: 'NewParents', displayName: 'r/NewParents', newPosts: 245, topPostUpvotes: 345, sentiment: 'neutral', trend: 'up', activityIndex: 68, brandMentionRate: 15, sentimentChangeSpeed: 0.8 },
  { name: 'breastpumps', displayName: 'r/breastpumps', newPosts: 128, topPostUpvotes: 567, sentiment: 'negative', trend: 'down', activityIndex: 72, brandMentionRate: 35, sentimentChangeSpeed: 2.1 },
  { name: 'Mommit', displayName: 'r/Mommit', newPosts: 142, topPostUpvotes: 234, sentiment: 'neutral', trend: 'stable', activityIndex: 55, brandMentionRate: 12, sentimentChangeSpeed: 0.3 },
  { name: 'pregnant', displayName: 'r/pregnant', newPosts: 78, topPostUpvotes: 89, sentiment: 'positive', trend: 'up', activityIndex: 48, brandMentionRate: 8, sentimentChangeSpeed: 0.5 },
];

export const monthlyActionItems: import('./dailyReportMock').DailyActionItem[] = [
  { id: 'mact1', type: 'reply', title: '回复「静音办公场景」高意向帖子（45条）', urgency: 'high', due: '本月', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'mact2', type: 'reply', title: '回复「M5 vs Elvie」对比帖中的品牌劣势', urgency: 'high', due: '本月', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'mact3', type: 'escalate', title: '处理「M5故障」投诉帖子，转产品团队', urgency: 'high', due: '立即', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'mact4', type: 'collect', title: '收集 UGC 素材（本月73条）', urgency: 'medium', due: '本月', completed: true, priorityMatrix: 'not_urgent_important' },
  { id: 'mact5', type: 'reply', title: '回复「新手选泵」求助类帖子（38条）', urgency: 'medium', due: '本月', completed: false, priorityMatrix: 'not_urgent_important' },
  { id: 'mact6', type: 'monitor', title: '关注「吸力弱」讨论月度趋势', urgency: 'medium', due: '持续', completed: false, priorityMatrix: 'not_urgent_not_important' },
  { id: 'mact7', type: 'reply', title: '制作「背奶职场妈妈」月度内容系列', urgency: 'high', due: '本月', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'mact8', type: 'escalate', title: '处理售后退款投诉，优化客服SOP', urgency: 'high', due: '本月', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'mact9', type: 'reply', title: '发布「性价比」品牌认知强化内容', urgency: 'high', due: '下月', completed: false, priorityMatrix: 'not_urgent_important' },
  { id: 'mact10', type: 'monitor', title: '追踪「静音设计」竞品动态', urgency: 'medium', due: '持续', completed: false, priorityMatrix: 'not_urgent_not_important' },
];

export const monthlySentimentTrend = [
  { label: '1日', positive: 50, negative: 15, neutral: 35, volume: 38 },
  { label: '2日', positive: 52, negative: 14, neutral: 34, volume: 42 },
  { label: '3日', positive: 51, negative: 16, neutral: 33, volume: 40 },
  { label: '4日', positive: 53, negative: 13, neutral: 34, volume: 45 },
  { label: '5日', positive: 55, negative: 12, neutral: 33, volume: 48 },
  { label: '6日', positive: 54, negative: 14, neutral: 32, volume: 46 },
  { label: '7日', positive: 56, negative: 11, neutral: 33, volume: 50 },
  { label: '8日', positive: 52, negative: 15, neutral: 33, volume: 44 },
  { label: '9日', positive: 53, negative: 14, neutral: 33, volume: 47 },
  { label: '10日', positive: 55, negative: 13, neutral: 32, volume: 49 },
  { label: '11日', positive: 57, negative: 12, neutral: 31, volume: 52 },
  { label: '12日', positive: 54, negative: 14, neutral: 32, volume: 48 },
  { label: '13日', positive: 52, negative: 15, neutral: 33, volume: 45 },
  { label: '14日', positive: 53, negative: 14, neutral: 33, volume: 46 },
  { label: '15日', positive: 55, negative: 13, neutral: 32, volume: 50 },
  { label: '16日', positive: 56, negative: 12, neutral: 32, volume: 53 },
  { label: '17日', positive: 54, negative: 14, neutral: 32, volume: 49 },
  { label: '18日', positive: 52, negative: 15, neutral: 33, volume: 46 },
  { label: '19日', positive: 53, negative: 14, neutral: 33, volume: 47 },
  { label: '20日', positive: 55, negative: 13, neutral: 32, volume: 51 },
  { label: '21日', positive: 57, negative: 11, neutral: 32, volume: 55 },
  { label: '22日', positive: 54, negative: 14, neutral: 32, volume: 50 },
  { label: '23日', positive: 52, negative: 15, neutral: 33, volume: 46 },
  { label: '24日', positive: 53, negative: 14, neutral: 33, volume: 48 },
  { label: '25日', positive: 55, negative: 13, neutral: 32, volume: 52 },
  { label: '26日', positive: 56, negative: 12, neutral: 32, volume: 54 },
  { label: '27日', positive: 54, negative: 14, neutral: 32, volume: 50 },
  { label: '28日', positive: 52, negative: 15, neutral: 33, volume: 46 },
  { label: '29日', positive: 53, negative: 14, neutral: 33, volume: 48 },
  { label: '30日', positive: 55, negative: 13, neutral: 32, volume: 51 },
];

// 兼容导出 —— 供 reportEngine.ts 使用
export const monthlyCategoryValues = monthlyCategoryMatrix;
