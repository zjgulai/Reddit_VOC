// Reddit 舆情分析 Mock 数据
// 用于 /dashboard/analytics 页面的情感分析、话题聚类、子版块画像模块

import {
  allStats, weeklyStats, monthlyStats,
  weeklyTopicClusters, monthlyTopicClusters,
  weeklySubreddits, monthlySubreddits,
  weeklySentimentTrendFromPosts, monthlySentimentTrendFromPosts,
  parsedPosts, filterPostsByRange,
} from './unifiedEngine';

export interface AnalyticsStatItem {
  label: string;
  value: string;
  change: number;
  trend: 'up' | 'down' | 'neutral';
}

export function getAnalyticsStats(timeRange: '7d' | '30d' | '90d'): AnalyticsStatItem[] {
  const stats = timeRange === '30d' ? monthlyStats : timeRange === '90d' ? allStats : weeklyStats;
  return [
    { label: '总帖子数', value: String(stats.totalPosts), change: 11.3, trend: 'up' },
    { label: '正面情感占比', value: `${stats.positiveRate}%`, change: 3.1, trend: 'up' },
    { label: '话题聚类', value: String(Object.keys(stats.intents).length), change: 0, trend: 'neutral' },
    { label: '活跃社区', value: String(stats.subreddits.length), change: -2.3, trend: 'down' },
  ];
}

export interface SentimentData {
  positive: number;
  neutral: number;
  negative: number;
  total: number;
}

export interface SentimentTrendPoint {
  date: string;
  positive: number;
  neutral: number;
  negative: number;
  total: number;
}

export interface TopicCluster {
  id: string;
  name: string;
  count: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  relatedTopics: string[];
  trend: 'up' | 'down' | 'stable';
  growth: number;
  keywords: string[];
}

export interface SubredditProfile {
  name: string;
  displayName: string;
  subscribers: number;
  postCount: number;
  sentiment: {
    positive: number;
    neutral: number;
    negative: number;
  };
  vibe: '理性讨论型' | '情绪发泄型' | '口碑分享型' | '求助咨询型' | '热闹围观型';
  quality: '高' | '中' | '低';
  worthInvesting: boolean;
  topKeywords: string[];
  engagement: number; // 平均互动数
  momcozyMentions: number;
  competitorMentions: number;
  lastActive: string;
}

// ===== 情感分析数据 =====
export const sentimentOverview: SentimentData = {
  positive: 187,
  neutral: 111,
  negative: 49,
  total: 347,
};

export const sentimentTrend7d: SentimentTrendPoint[] = [
  { date: '07-04', positive: 23, neutral: 13, negative: 8, total: 44 },
  { date: '07-05', positive: 27, neutral: 17, negative: 7, total: 51 },
  { date: '07-06', positive: 25, neutral: 19, negative: 9, total: 53 },
  { date: '07-07', positive: 31, neutral: 11, negative: 6, total: 48 },
  { date: '07-08', positive: 26, neutral: 21, negative: 7, total: 54 },
  { date: '07-09', positive: 33, neutral: 14, negative: 5, total: 52 },
  { date: '07-10', positive: 24, neutral: 18, negative: 9, total: 51 },
];

export const sentimentTrend30d: SentimentTrendPoint[] = [
  { date: '06-11', positive: 19, neutral: 11, negative: 11, total: 41 },
  { date: '06-15', positive: 21, neutral: 13, negative: 9, total: 43 },
  { date: '06-19', positive: 23, neutral: 15, negative: 8, total: 46 },
  { date: '06-23', positive: 24, neutral: 16, negative: 7, total: 47 },
  { date: '06-27', positive: 27, neutral: 19, negative: 6, total: 52 },
  { date: '07-01', positive: 25, neutral: 15, negative: 10, total: 50 },
  { date: '07-05', positive: 31, neutral: 15, negative: 7, total: 53 },
  { date: '07-10', positive: 25, neutral: 16, negative: 9, total: 50 },
];

export const sentimentTrend90d: SentimentTrendPoint[] = [
  { date: '04-12', positive: 15, neutral: 9, negative: 9, total: 33 },
  { date: '04-19', positive: 17, neutral: 11, negative: 8, total: 36 },
  { date: '04-26', positive: 19, neutral: 12, negative: 5, total: 36 },
  { date: '05-03', positive: 21, neutral: 12, negative: 6, total: 39 },
  { date: '05-10', positive: 23, neutral: 13, negative: 7, total: 43 },
  { date: '05-17', positive: 25, neutral: 14, negative: 6, total: 45 },
  { date: '05-24', positive: 24, neutral: 15, negative: 8, total: 47 },
  { date: '05-31', positive: 26, neutral: 13, negative: 7, total: 46 },
  { date: '06-07', positive: 27, neutral: 16, negative: 4, total: 47 },
  { date: '06-14', positive: 29, neutral: 15, negative: 5, total: 49 },
  { date: '06-21', positive: 28, neutral: 18, negative: 5, total: 51 },
  { date: '06-28', positive: 30, neutral: 14, negative: 6, total: 50 },
  { date: '07-05', positive: 31, neutral: 17, negative: 5, total: 53 },
  { date: '07-10', positive: 25, neutral: 16, negative: 9, total: 50 },
];

export function getSentimentTrend(timeRange: '7d' | '30d' | '90d'): SentimentTrendPoint[] {
  const trend = timeRange === '30d' ? monthlySentimentTrendFromPosts : weeklySentimentTrendFromPosts;
  return trend.map((d) => ({
    date: d.date,
    positive: Math.round((d.positive / d.total) * 100),
    neutral: Math.round((d.neutral / d.total) * 100),
    negative: Math.round((d.negative / d.total) * 100),
    total: d.total,
  }));
}

export function getSentimentOverview(timeRange: '7d' | '30d' | '90d'): SentimentData {
  const stats = timeRange === '30d' ? monthlyStats : timeRange === '90d' ? allStats : weeklyStats;
  return {
    positive: stats.positive,
    neutral: stats.neutral,
    negative: stats.negative,
    total: stats.totalPosts,
  };
}

export const sentimentBySubreddit = [
  { name: 'breastfeeding', positive: 86, neutral: 44, negative: 13 },
  { name: 'babybumps', positive: 43, neutral: 27, negative: 9 },
  { name: 'NewParents', positive: 29, neutral: 21, negative: 16 },
  { name: 'Mommit', positive: 17, neutral: 11, negative: 6 },
  { name: 'breastpumps', positive: 14, neutral: 6, negative: 11 },
];

export function getSentimentBySubreddit(timeRange: '7d' | '30d' | '90d') {
  const multipliers: Record<string, number> = { '7d': 1, '30d': 3.6, '90d': 10.6 };
  const m = multipliers[timeRange] ?? 1;
  return sentimentBySubreddit.map((s) => ({
    name: s.name,
    positive: Math.round(s.positive * m),
    neutral: Math.round(s.neutral * m),
    negative: Math.round(s.negative * m),
  }));
}

// ===== 话题聚类数据 =====
export const topicClusters: TopicCluster[] = [
  {
    id: '1',
    name: '产品对比与选购',
    count: 87,
    sentiment: 'positive',
    relatedTopics: ['breast pump推荐', 'Momcozy vs Elvie', '静音设计'],
    trend: 'up',
    growth: 33,
    keywords: ['推荐', '对比', '选购', '哪个好', '值得买'],
  },
  {
    id: '2',
    name: '使用体验分享',
    count: 74,
    sentiment: 'positive',
    relatedTopics: ['真实体验', '使用感受', '便携性'],
    trend: 'stable',
    growth: 7,
    keywords: ['体验', '感受', '好用', '方便', '满意'],
  },
  {
    id: '3',
    name: '背奶/职场妈妈',
    count: 63,
    sentiment: 'neutral',
    relatedTopics: ['上班背奶', ' wearable pump', '办公室'],
    trend: 'up',
    growth: 46,
    keywords: ['上班', '背奶', 'wearable', '职场', '便携'],
  },
  {
    id: '4',
    name: '价格与性价比',
    count: 47,
    sentiment: 'neutral',
    relatedTopics: ['价格', '预算', '性价比', '优惠活动'],
    trend: 'down',
    growth: -11,
    keywords: ['价格', '多少钱', '性价比', '预算', '便宜'],
  },
  {
    id: '5',
    name: '问题求助与故障',
    count: 42,
    sentiment: 'negative',
    relatedTopics: ['吸力不够', '漏奶', '怎么清洗'],
    trend: 'stable',
    growth: 4,
    keywords: ['问题', '求助', '故障', '怎么办', '维修'],
  },
  {
    id: '6',
    name: '新手妈妈科普',
    count: 31,
    sentiment: 'positive',
    relatedTopics: ['初乳', '泌乳', '怎么选'],
    trend: 'up',
    growth: 21,
    keywords: ['新手', '第一次', '怎么', '科普', '建议'],
  },
];

export function getTopicClusters(timeRange: '7d' | '30d' | '90d'): TopicCluster[] {
  const clusters = timeRange === '30d' ? monthlyTopicClusters : weeklyTopicClusters;
  return clusters.map((c, idx) => ({
    id: String(idx + 1),
    name: c.name,
    count: c.count,
    sentiment: c.sentiment,
    relatedTopics: c.keywords,
    trend: c.sentiment === 'positive' ? 'up' : c.sentiment === 'negative' ? 'down' : 'stable',
    growth: 0,
    keywords: c.keywords,
  }));
}

// ===== 子版块画像数据 =====
function generateLastActive(): string {
  const mins = Math.floor(Math.random() * 45) + 3;
  return `${mins} 分钟前`;
}

export const subredditProfiles: SubredditProfile[] = [
  {
    name: 'breastfeeding',
    displayName: 'r/breastfeeding',
    subscribers: 185000,
    postCount: 141,
    sentiment: { positive: 86, neutral: 44, negative: 13 },
    vibe: '理性讨论型',
    quality: '高',
    worthInvesting: true,
    topKeywords: ['breast pump', 'recommendation', 'Momcozy', 'Elvie', 'Spectra'],
    engagement: 24.3,
    momcozyMentions: 37,
    competitorMentions: 68,
    lastActive: generateLastActive(),
  },
  {
    name: 'babybumps',
    displayName: 'r/babybumps',
    subscribers: 720000,
    postCount: 79,
    sentiment: { positive: 43, neutral: 27, negative: 9 },
    vibe: '口碑分享型',
    quality: '高',
    worthInvesting: true,
    topKeywords: ['registry', 'recommend', 'first time', 'Momcozy', 'pumping'],
    engagement: 17.8,
    momcozyMentions: 23,
    competitorMentions: 30,
    lastActive: '5 分钟前',
  },
  {
    name: 'NewParents',
    displayName: 'r/NewParents',
    subscribers: 145000,
    postCount: 64,
    sentiment: { positive: 29, neutral: 21, negative: 16 },
    vibe: '求助咨询型',
    quality: '中',
    worthInvesting: true,
    topKeywords: ['help', 'advice', 'newborn', 'feeding', 'pump'],
    engagement: 15.2,
    momcozyMentions: 11,
    competitorMentions: 19,
    lastActive: '1 小时前',
  },
  {
    name: 'Mommit',
    displayName: 'r/Mommit',
    subscribers: 210000,
    postCount: 34,
    sentiment: { positive: 17, neutral: 11, negative: 6 },
    vibe: '热闹围观型',
    quality: '中',
    worthInvesting: false,
    topKeywords: ['rant', 'vent', 'tired', 'anyone else', 'pump'],
    engagement: 31.7,
    momcozyMentions: 9,
    competitorMentions: 13,
    lastActive: '30 分钟前',
  },
  {
    name: 'breastpumps',
    displayName: 'r/breastpumps',
    subscribers: 8500,
    postCount: 29,
    sentiment: { positive: 14, neutral: 6, negative: 11 },
    vibe: '理性讨论型',
    quality: '高',
    worthInvesting: true,
    topKeywords: ['review', 'comparison', 'Momcozy M5', 'suction', 'settings'],
    engagement: 12.4,
    momcozyMentions: 19,
    competitorMentions: 10,
    lastActive: '2 小时前',
  },
];

export function getSubredditProfiles(timeRange: '7d' | '30d' | '90d'): SubredditProfile[] {
  const subs = timeRange === '30d' ? monthlySubreddits : weeklySubreddits;
  const vibeMap: Record<string, SubredditProfile['vibe']> = {
    breastfeeding: '理性讨论型',
    babybumps: '口碑分享型',
    NewParents: '求助咨询型',
    Mommit: '热闹围观型',
    breastpumps: '理性讨论型',
  };
  const qualityMap: Record<string, SubredditProfile['quality']> = {
    breastfeeding: '高',
    babybumps: '高',
    NewParents: '中',
    Mommit: '中',
    breastpumps: '高',
  };
  return subs.map((s) => ({
    name: s.name,
    displayName: s.displayName,
    subscribers: s.postCount * 1000,
    postCount: s.postCount,
    sentiment: {
      positive: s.positive,
      neutral: s.neutral,
      negative: s.negative,
    },
    vibe: vibeMap[s.name] || '理性讨论型',
    quality: qualityMap[s.name] || '中',
    worthInvesting: s.momcozyMentions > 0,
    topKeywords: ['breast pump', 'Momcozy', 'recommend', 'quiet', 'portable'],
    engagement: s.avgComments + s.avgUpvotes,
    momcozyMentions: s.momcozyMentions,
    competitorMentions: 0,
    lastActive: '5 分钟前',
  }));
}

// ===== 关键词词云数据 =====
export interface WordCloudDatum {
  text: string;
  value: number;
  color?: string;
  /** 来源帖子 ID 列表 */
  sourcePostIds?: string[];
  /** 情感分析置信度 0-1 */
  sentimentConfidence?: number;
}

export const keywordWordCloud: WordCloudDatum[] = [
  { text: 'Momcozy', value: 156, color: '#C45A6C', sourcePostIds: ['d1', 'd2', 'd3', 'd5', 'd6'], sentimentConfidence: 0.92 },
  { text: 'breast pump', value: 128, sourcePostIds: ['d1', 'd2', 'd3', 'd4', 'd5', 'd6'], sentimentConfidence: 0.82 },
  { text: 'wearable', value: 98, sourcePostIds: ['d1', 'd2'], sentimentConfidence: 0.90 },
  { text: 'recommend', value: 87, sourcePostIds: ['d1', 'd2', 'd3'], sentimentConfidence: 0.91 },
  { text: 'Elvie', value: 76, color: '#4A7FB5', sourcePostIds: ['d3', 'd5'], sentimentConfidence: 0.85 },
  { text: 'Spectra', value: 72, color: '#4A7FB5', sourcePostIds: ['d5'], sentimentConfidence: 0.78 },
  { text: 'quiet', value: 65, sourcePostIds: ['d1', 'd4'], sentimentConfidence: 0.86 },
  { text: 'portable', value: 62, sourcePostIds: ['d2', 'd5'], sentimentConfidence: 0.84 },
  { text: 'comfortable', value: 58, sourcePostIds: ['d1', 'd2'], sentimentConfidence: 0.87 },
  { text: 'price', value: 55, sourcePostIds: ['d3', 'd5'], sentimentConfidence: 0.73 },
  { text: 'insurance', value: 48, sourcePostIds: ['d3'], sentimentConfidence: 0.69 },
  { text: 'hands free', value: 45, sourcePostIds: ['d2', 'd5'], sentimentConfidence: 0.79 },
  { text: 'suction', value: 42, sourcePostIds: ['d4', 'd5', 'd6'], sentimentConfidence: 0.77 },
  { text: 'battery', value: 38, sourcePostIds: ['d1', 'd6'], sentimentConfidence: 0.75 },
  { text: 'cleaning', value: 35, sourcePostIds: ['d6'], sentimentConfidence: 0.81 },
  { text: 'flange', value: 32, sourcePostIds: ['d4', 'd6'], sentimentConfidence: 0.74 },
  { text: 'M5', value: 30, color: '#C45A6C', sourcePostIds: ['d1', 'd3', 'd5', 'd6'], sentimentConfidence: 0.88 },
  { text: 'S12', value: 28, color: '#C45A6C', sourcePostIds: ['d2', 'd4'], sentimentConfidence: 0.76 },
  { text: 'work', value: 25, sourcePostIds: ['d1', 'd5'], sentimentConfidence: 0.83 },
  { text: 'returning', value: 22, sourcePostIds: ['d3'], sentimentConfidence: 0.67 },
  { text: 'night', value: 20, sourcePostIds: ['d4'], sentimentConfidence: 0.76 },
  { text: 'pain', value: 18, sourcePostIds: ['d4'], sentimentConfidence: 0.82 },
  { text: 'leaking', value: 15, sourcePostIds: ['d6'], sentimentConfidence: 0.79 },
  { text: 'tips', value: 14, sourcePostIds: ['d1', 'd4'], sentimentConfidence: 0.64 },
  { text: 'FTM', value: 12, sourcePostIds: ['d1'], sentimentConfidence: 0.62 },
];

// ===== 桑基图数据：社区 → 话题 → 情感 =====
export interface SankeyNodeDatum {
  id: string;
  name: string;
  color?: string;
}

export interface SankeyLinkDatum {
  source: string;
  target: string;
  value: number;
}

export const sankeyNodes: SankeyNodeDatum[] = [
  // 社区层 (column 0)
  { id: 'breastfeeding', name: 'breastfeeding', color: '#C45A6C' },
  { id: 'babybumps', name: 'babybumps', color: '#4A7FB5' },
  { id: 'NewParents', name: 'NewParents', color: '#2D8A5E' },
  { id: 'Mommit', name: 'Mommit', color: '#D4940A' },
  { id: 'breastpumps', name: 'breastpumps', color: '#9A5AB5' },
  // 话题层 (column 1)
  { id: 'product_compare', name: '产品对比' },
  { id: 'experience', name: '使用体验' },
  { id: 'back_to_work', name: '背奶/职场' },
  { id: 'price', name: '价格/性价比' },
  { id: 'troubleshoot', name: '问题求助' },
  { id: 'newbie', name: '新手科普' },
  // 情感层 (column 2)
  { id: 'positive', name: '正面', color: '#2D8A5E' },
  { id: 'neutral', name: '中性', color: '#D4940A' },
  { id: 'negative', name: '负面', color: '#C45A6C' },
];

export const sankeyLinks: SankeyLinkDatum[] = [
  // breastfeeding → topics
  { source: 'breastfeeding', target: 'product_compare', value: 42 },
  { source: 'breastfeeding', target: 'experience', value: 38 },
  { source: 'breastfeeding', target: 'back_to_work', value: 28 },
  { source: 'breastfeeding', target: 'price', value: 18 },
  { source: 'breastfeeding', target: 'troubleshoot', value: 10 },
  { source: 'breastfeeding', target: 'newbie', value: 6 },
  // babybumps → topics
  { source: 'babybumps', target: 'product_compare', value: 22 },
  { source: 'babybumps', target: 'experience', value: 18 },
  { source: 'babybumps', target: 'back_to_work', value: 14 },
  { source: 'babybumps', target: 'price', value: 12 },
  { source: 'babybumps', target: 'newbie', value: 12 },
  // NewParents → topics
  { source: 'NewParents', target: 'product_compare', value: 15 },
  { source: 'NewParents', target: 'experience', value: 12 },
  { source: 'NewParents', target: 'troubleshoot', value: 18 },
  { source: 'NewParents', target: 'newbie', value: 10 },
  { source: 'NewParents', target: 'price', value: 10 },
  // Mommit → topics
  { source: 'Mommit', target: 'experience', value: 8 },
  { source: 'Mommit', target: 'troubleshoot', value: 12 },
  { source: 'Mommit', target: 'back_to_work', value: 8 },
  { source: 'Mommit', target: 'price', value: 5 },
  // breastpumps → topics
  { source: 'breastpumps', target: 'product_compare', value: 10 },
  { source: 'breastpumps', target: 'experience', value: 8 },
  { source: 'breastpumps', target: 'troubleshoot', value: 6 },
  { source: 'breastpumps', target: 'price', value: 4 },
  { source: 'breastpumps', target: 'back_to_work', value: 2 },
  // topics → sentiment
  { source: 'product_compare', target: 'positive', value: 68 },
  { source: 'product_compare', target: 'neutral', value: 18 },
  { source: 'product_compare', target: 'negative', value: 3 },
  { source: 'experience', target: 'positive', value: 72 },
  { source: 'experience', target: 'neutral', value: 10 },
  { source: 'experience', target: 'negative', value: 2 },
  { source: 'back_to_work', target: 'positive', value: 38 },
  { source: 'back_to_work', target: 'neutral', value: 12 },
  { source: 'back_to_work', target: 'negative', value: 2 },
  { source: 'price', target: 'neutral', value: 42 },
  { source: 'price', target: 'positive', value: 5 },
  { source: 'price', target: 'negative', value: 2 },
  { source: 'troubleshoot', target: 'negative', value: 38 },
  { source: 'troubleshoot', target: 'neutral', value: 8 },
  { source: 'troubleshoot', target: 'positive', value: 2 },
  { source: 'newbie', target: 'positive', value: 28 },
  { source: 'newbie', target: 'neutral', value: 8 },
  { source: 'newbie', target: 'negative', value: 2 },
];

// 辅助：根据时间范围调整桑基图数据
export function getSankeyLinks(timeRange: '7d' | '30d' | '90d'): SankeyLinkDatum[] {
  const multipliers: Record<string, number> = { '7d': 1, '30d': 3.6, '90d': 10.6 };
  const m = multipliers[timeRange] ?? 1;
  return sankeyLinks.map((link) => ({
    ...link,
    value: Math.round(link.value * m),
  }));
}

// ========== 桑基图聚合接口：从真实帖子数据生成桑基图 ==========

/** 子版块颜色映射 */
const SUBREDDIT_SANKEY_COLORS: Record<string, string> = {
  breastfeeding: '#C45A6C',
  babybumps: '#4A7FB5',
  NewParents: '#2D8A5E',
  Mommit: '#D4940A',
  breastpumps: '#9A5AB5',
};

/** 话题节点配置 */
const TOPIC_NODES: SankeyNodeDatum[] = [
  { id: 'product_compare', name: '产品对比' },
  { id: 'experience', name: '使用体验' },
  { id: 'back_to_work', name: '背奶/职场' },
  { id: 'price', name: '价格/性价比' },
  { id: 'troubleshoot', name: '问题求助' },
  { id: 'newbie', name: '新手科普' },
];

/** 情感节点配置 */
const SENTIMENT_NODES: SankeyNodeDatum[] = [
  { id: 'positive', name: '正面', color: '#2D8A5E' },
  { id: 'neutral', name: '中性', color: '#D4940A' },
  { id: 'negative', name: '负面', color: '#C45A6C' },
];

/** 意图 → 话题映射（简化规则） */
const INTENT_TO_TOPIC: Record<string, string> = {
  'Purchase Intent': 'product_compare',
  'Comparison': 'product_compare',
  'UGC': 'experience',
  'Bug Report': 'troubleshoot',
  'Question': 'newbie',
  'General': 'experience',
};

/**
 * 从帖子数据聚合生成「社区→话题→情感」桑基图数据
 * @param posts 包含 subreddit / sentiment / intent 的帖子数组
 * @returns { nodes, links } 桑基图数据
 */
export function aggregateSankeyFromPosts(
  posts: Array<{ subreddit: string; sentiment: 'positive' | 'neutral' | 'negative'; intent: string }>
): { nodes: SankeyNodeDatum[]; links: SankeyLinkDatum[] } {
  const subredditSet = new Set<string>();
  const linkCounts = new Map<string, number>();

  for (const post of posts) {
    const subreddit = post.subreddit;
    const topicId = INTENT_TO_TOPIC[post.intent] || 'experience';
    const sentimentId = post.sentiment;

    subredditSet.add(subreddit);

    // 社区 → 话题
    const link1Key = `${subreddit}→${topicId}`;
    linkCounts.set(link1Key, (linkCounts.get(link1Key) || 0) + 1);

    // 话题 → 情感
    const link2Key = `${topicId}→${sentimentId}`;
    linkCounts.set(link2Key, (linkCounts.get(link2Key) || 0) + 1);
  }

  // 构建节点列表
  const nodes: SankeyNodeDatum[] = [];

  // 社区层
  for (const sr of subredditSet) {
    nodes.push({
      id: sr,
      name: sr,
      color: SUBREDDIT_SANKEY_COLORS[sr] || '#6B6B6B',
    });
  }

  // 话题层（只包含实际用到的）
  const usedTopics = new Set<string>();
  for (const key of linkCounts.keys()) {
    const [src, tgt] = key.split('→');
    if (TOPIC_NODES.some((n) => n.id === src)) usedTopics.add(src);
    if (TOPIC_NODES.some((n) => n.id === tgt)) usedTopics.add(tgt);
  }
  for (const topic of TOPIC_NODES) {
    if (usedTopics.has(topic.id)) nodes.push(topic);
  }

  // 情感层（只包含实际用到的）
  const usedSentiments = new Set<string>();
  for (const key of linkCounts.keys()) {
    const [, tgt] = key.split('→');
    if (SENTIMENT_NODES.some((n) => n.id === tgt)) usedSentiments.add(tgt);
  }
  for (const sentiment of SENTIMENT_NODES) {
    if (usedSentiments.has(sentiment.id)) nodes.push(sentiment);
  }

  // 构建连线
  const links: SankeyLinkDatum[] = [];
  for (const [key, value] of linkCounts.entries()) {
    const [source, target] = key.split('→');
    links.push({ source, target, value });
  }

  return { nodes, links };
}

// ========== 从真实帖子生成桑基图数据 ==========

export function getSankeyDataFromPosts(timeRange: '7d' | '30d' | '90d'): { nodes: SankeyNodeDatum[]; links: SankeyLinkDatum[] } {
  const range = timeRange === '30d' ? '30d' : timeRange === '90d' ? '30d' : '7d';
  const posts = filterPostsByRange(parsedPosts, range);
  return aggregateSankeyFromPosts(posts);
}

// ========== 停用词与词云生成 ==========

const STOP_WORDS = new Set(['the','a','an','is','are','was','were','be','been','being','have','has','had','do','does','did','will','would','could','should','may','might','must','shall','can','need','dare','ought','used','to','of','in','for','on','with','at','by','from','as','into','through','during','before','after','above','below','between','under','again','further','then','once','here','there','when','where','why','how','all','each','few','more','most','other','some','such','no','nor','not','only','own','same','so','than','too','very','just','and','but','if','or','because','until','while','this','that','these','those','i','me','my','myself','we','our','ours','ourselves','you','your','yours','yourself','yourselves','he','him','his','himself','she','her','hers','herself','it','its','itself','they','them','their','theirs','themselves','what','which','who','whom','whose','am','about','up','out','down','off','over','my','im','i','got','get','like','dont','didnt','doesnt','wasnt','werent','hasnt','havent','hadnt','isnt','arent','s','t','re','ve','d','ll','m','o','u','y']);

/** 从帖子标题提取词频 */
function extractWords(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z\s]/g, ' ')
    .split(/\s+/)
    .filter(w => w.length > 2 && !STOP_WORDS.has(w));
}

const WORD_COLORS: Record<string, string> = {
  momcozy: '#C45A6C', elvie: '#4A7FB5', spectra: '#4A7FB5', medela: '#4A7FB5', willow: '#4A7FB5',
  lansinoh: '#4A7FB5', haakaa: '#4A7FB5', m5: '#C45A6C', s12: '#C45A6C', m6: '#C45A6C',
};

export function getKeywordWordCloudFromPosts(timeRange: '7d' | '30d' | '90d'): WordCloudDatum[] {
  const range = timeRange === '30d' ? '30d' : timeRange === '90d' ? '30d' : '7d';
  const posts = filterPostsByRange(parsedPosts, range);
  const wordCounts = new Map<string, { count: number; postIds: string[]; confidenceSum: number }>();

  for (const post of posts) {
    const words = extractWords(post.title);
    for (const word of words) {
      const existing = wordCounts.get(word) || { count: 0, postIds: [], confidenceSum: 0 };
      existing.count++;
      existing.postIds.push(post.id);
      existing.confidenceSum += (post.sentiment === 'positive' ? 0.85 : post.sentiment === 'negative' ? 0.7 : 0.75);
      wordCounts.set(word, existing);
    }
  }

  return Array.from(wordCounts.entries())
    .map(([text, data]) => ({
      text,
      value: data.count,
      color: WORD_COLORS[text] || undefined,
      sourcePostIds: data.postIds.slice(0, 5),
      sentimentConfidence: Math.round((data.confidenceSum / data.count) * 100) / 100,
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 25);
}
