// 日报 Mock 数据 —— 24小时滚动
import { formatDateTime, formatDate } from '../utils/date';
import type { PostIntent, RedditComment } from '../types';

export type SentimentLevel = 'calm' | 'watch' | 'alert' | 'crisis';

export interface ResponseMetrics {
  avgResponseTime: number; // 分钟
  completionRate: number; // %
  escalationRate: number; // %
}

export interface ImpactEstimate {
  potentialLoss: number; // 预估潜在损失（美元）
  affectedCustomers: number; // 影响客户数
}

export interface DailyAlert {
  id: string;
  level: 'critical' | 'warning' | 'info';
  title: string;
  subreddit: string;
  upvotes: number;
  comments: number;
  growth: number; // 最近2小时增长
  sentiment: 'positive' | 'negative' | 'neutral';
  intent: PostIntent;
  summary: string;
  url: string;
  time: string;
  // 新增字段
  discoveredAt: string;
  respondedAt?: string;
  resolvedAt?: string;
  impactEstimate: ImpactEstimate;
}

export type BusinessValueTag = 'high_intent' | 'ugc' | 'competitor' | 'crisis' | 'opportunity';

export interface DailyNewPost {
  id: string;
  title: string;
  subreddit: string;
  author: string;
  time: string;
  upvotes: number;
  comments: number;
  intentScore: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  intent: PostIntent;
  action: 'reply' | 'collect' | 'monitor' | 'escalate';
  // Reddit 扩展字段（可选，兼容现有数据）
  redditId?: string;
  permalink?: string;
  score?: number;
  upvoteRatio?: number;
  commentList?: RedditComment[];
  // 新增字段
  businessValueTag?: BusinessValueTag;
}

export interface DailyCommunityStatus {
  name: string;
  displayName: string;
  newPosts: number;
  topPostUpvotes: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  trend: 'up' | 'down' | 'stable';
  // 新增字段
  activityIndex: number; // 0-100 活跃度指数
  brandMentionRate: number; // % 品牌提及率
  sentimentChangeSpeed: number; // 情感变化速度（每小时变化百分点）
}

export interface DailyActionItem {
  id: string;
  type: 'reply' | 'collect' | 'monitor' | 'escalate';
  title: string;
  urgency: 'high' | 'medium' | 'low';
  due: string;
  completed: boolean;
  // 新增字段
  priorityMatrix: 'urgent_important' | 'urgent_not_important' | 'not_urgent_important' | 'not_urgent_not_important';
}

export interface SentimentThermometer {
  positive: number;
  negative: number;
  neutral: number;
  level: SentimentLevel;
  trend24h: number; // 24小时变化
  previousPositive: number;
  previousNegative: number;
  previousNeutral: number;
}

export const sentimentThermometer: SentimentThermometer = {
  positive: 58,
  negative: 14,
  neutral: 28,
  level: 'watch',
  trend24h: -3,
  previousPositive: 61,
  previousNegative: 12,
  previousNeutral: 27,
};

export const dailyResponseMetrics: ResponseMetrics = {
  avgResponseTime: 147, // 2小时27分钟
  completionRate: 67,
  escalationRate: 13,
};

export const dailyOverview = {
  newPosts: 53,
  newPostsTrend: 11, // vs 昨天同期
  positiveRate: 57,
  negativeRate: 15,
  neutralRate: 28,
  alerts: 3,
  highIntent: 7,
  ugc: 6,
  updatedAt: formatDateTime(),
  sentimentLevel: 'watch' as SentimentLevel,
};

export const dailyAlerts: DailyAlert[] = [
  {
    id: 'a1',
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
    id: 'a2',
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
    id: 'a3',
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
];

/** 生成 Reddit 评论 */
function makeComment(
  id: string,
  redditId: string,
  author: string,
  body: string,
  score: number,
  sentiment: 'positive' | 'neutral' | 'negative' = 'positive',
  replies?: RedditComment[]
): RedditComment {
  return {
    id,
    redditId,
    author,
    body,
    score,
    createdAt: formatDate(),
    permalink: `/r/breastfeeding/comments/${redditId}/${id}/`,
    sentiment,
    replies,
  };
}

export const dailyNewPosts: DailyNewPost[] = [
  {
    id: 'd1',
    redditId: 't3_1d1',
    title: 'momcozy m5 for work?? need something QUIET lol',
    subreddit: 'breastfeeding',
    author: 'u/throwaway_pump22',
    time: '2小时前',
    permalink: '/r/breastfeeding/comments/1d1/quiet_wearable_pump/',
    upvotes: 1247,
    score: 1180,
    upvoteRatio: 0.94,
    comments: 186,
    intentScore: 92,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    action: 'reply',
    businessValueTag: 'high_intent',
    commentList: [
      makeComment('c1', 't1_c1', 'u/Fit_Ant_8317', 'I got the Momcozy M5 last month and it has been amazing for my work schedule. Super quiet and comfortable.', 45, 'positive'),
      makeComment('c2', 't1_c2', 'u/throwaway_pump22', "Thanks for the recommendation! I'm definitely considering it now. How long does the battery last?", 12, 'neutral'),
      makeComment('c3', 't1_c3', 'u/pumping_pro_94', 'Battery lasts about 3-4 sessions for me. Make sure to get the charging dock, it\'s worth it.', 28, 'positive'),
    ],
  },
  {
    id: 'd2',
    redditId: 't3_1d2',
    title: 'OMG momcozy pump actually works?? my LC was skeptical',
    subreddit: 'babybumps',
    author: 'u/Ok-Consideration-441',
    time: '6小时前',
    permalink: '/r/babybumps/comments/1d2/game_changer/',
    upvotes: 2156,
    score: 2050,
    upvoteRatio: 0.95,
    comments: 312,
    intentScore: 45,
    sentiment: 'positive',
    intent: 'UGC',
    action: 'collect',
    businessValueTag: 'ugc',
    commentList: [
      makeComment('c4', 't1_c4', 'u/Witty_Web_7392', 'This is exactly what I needed to hear! Which model did you get?', 34, 'positive'),
      makeComment('c5', 't1_c5', 'u/Ok-Consideration-441', 'I got the M5! The wearable feature is a lifesaver for my commute.', 56, 'positive'),
    ],
  },
  {
    id: 'd3',
    redditId: 't3_1d3',
    title: 'is momcozy worth it?? honest opinions only no shills',
    subreddit: 'breastfeeding',
    author: 'u/x7k9m2p',
    time: '12小时前',
    permalink: '/r/breastfeeding/comments/1d3/worth_the_price/',
    upvotes: 678,
    score: 620,
    upvoteRatio: 0.91,
    comments: 98,
    intentScore: 88,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    action: 'reply',
    businessValueTag: 'high_intent',
    commentList: [
      makeComment('c6', 't1_c6', 'u/a3b8c1d4', 'Absolutely worth it. I compared it to Elvie and the price-to-performance is much better.', 42, 'positive'),
      makeComment('c7', 't1_c7', 'u/throwaway_2024', 'I had issues with suction after 3 months, so your mileage may vary.', 15, 'negative'),
    ],
  },
  {
    id: 'd4',
    redditId: 't3_1d4',
    title: 'current pump sucks (literally doesnt) need recs ASAP',
    subreddit: 'breastfeeding',
    author: 'u/FTM_2024_june',
    time: '14小时前',
    permalink: '/r/breastfeeding/comments/1d4/looking_for_alternatives/',
    upvotes: 543,
    score: 510,
    upvoteRatio: 0.94,
    comments: 76,
    intentScore: 78,
    sentiment: 'negative',
    intent: 'Purchase Intent',
    action: 'reply',
    businessValueTag: 'opportunity',
    commentList: [
      makeComment('c8', 't1_c8', 'u/qwerty_uiop', 'Switch to Momcozy M5! I was in the same boat and never looked back.', 38, 'positive'),
      makeComment('c9', 't1_c9', 'u/FTM_2024_june', 'That\'s encouraging. What made you switch specifically?', 8, 'neutral'),
    ],
  },
  {
    id: 'd5',
    redditId: 't3_1d5',
    title: 'M5 vs Elvie - which actually better for EP?? cant decide 😩',
    subreddit: 'breastfeeding',
    author: 'u/mom_of_3_under_5',
    time: '4小时前',
    permalink: '/r/breastfeeding/comments/1d5/m5_vs_elvie/',
    upvotes: 892,
    score: 850,
    upvoteRatio: 0.95,
    comments: 143,
    intentScore: 85,
    sentiment: 'neutral',
    intent: 'Comparison',
    action: 'reply',
    businessValueTag: 'competitor',
    commentList: [
      makeComment('c10', 't1_c10', 'u/nightshift_rn', 'Elvie is more expensive but has better app integration.', 22, 'neutral'),
      makeComment('c11', 't1_c11', 'u/m5fan_42', 'M5 wins on price and battery life. The app is getting better too.', 35, 'positive'),
      makeComment('c12', 't1_c12', 'u/EP_survivor_2019', 'I\'ve used both. For exclusive pumping, M5 is more reliable day-to-day.', 48, 'positive'),
    ],
  },
  {
    id: 'd6',
    redditId: 't3_1d6',
    title: 'M5 died after 2 weeks. wtaf momcozy??',
    subreddit: 'breastfeeding',
    author: 'u/throwaway_rant_99',
    time: '3小时前',
    permalink: '/r/breastfeeding/comments/1d6/stopped_working/',
    upvotes: 34,
    score: 18,
    upvoteRatio: 0.53,
    comments: 28,
    intentScore: 60,
    sentiment: 'negative',
    intent: 'Bug Report',
    action: 'escalate',
    businessValueTag: 'crisis',
    commentList: [
      makeComment('c13', 't1_c13', 'u/same_here_77', 'Same happened to me! Contacted support and they sent a replacement.', 12, 'negative'),
      makeComment('c14', 't1_c14', 'u/momcozy_support_01', 'Hi, we\'re sorry to hear this. Please DM us your order number and we\'ll prioritize a replacement.', 8, 'neutral'),
    ],
  },
];

export const dailyCommunityStatus: DailyCommunityStatus[] = [
  { name: 'breastfeeding', displayName: 'r/breastfeeding', newPosts: 18, topPostUpvotes: 1247, sentiment: 'positive', trend: 'up', activityIndex: 82, brandMentionRate: 34, sentimentChangeSpeed: 2.3 },
  { name: 'babybumps', displayName: 'r/babybumps', newPosts: 12, topPostUpvotes: 2156, sentiment: 'positive', trend: 'stable', activityIndex: 76, brandMentionRate: 28, sentimentChangeSpeed: 0.8 },
  { name: 'NewParents', displayName: 'r/NewParents', newPosts: 8, topPostUpvotes: 234, sentiment: 'neutral', trend: 'up', activityIndex: 64, brandMentionRate: 22, sentimentChangeSpeed: 1.5 },
  { name: 'breastpumps', displayName: 'r/breastpumps', newPosts: 7, topPostUpvotes: 189, sentiment: 'negative', trend: 'down', activityIndex: 58, brandMentionRate: 45, sentimentChangeSpeed: -3.2 },
  { name: 'Mommit', displayName: 'r/Mommit', newPosts: 5, topPostUpvotes: 123, sentiment: 'neutral', trend: 'stable', activityIndex: 45, brandMentionRate: 18, sentimentChangeSpeed: 0.4 },
  { name: 'pregnant', displayName: 'r/pregnant', newPosts: 2, topPostUpvotes: 45, sentiment: 'positive', trend: 'up', activityIndex: 38, brandMentionRate: 12, sentimentChangeSpeed: 1.1 },
];

export const dailyActionItems: DailyActionItem[] = [
  { id: 'act1', type: 'reply', title: '回复「静音办公场景」高意向帖子（3条）', urgency: 'high', due: '2小时内', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'act2', type: 'reply', title: '回复「M5 vs Elvie」对比帖中的品牌劣势', urgency: 'high', due: '4小时内', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'act3', type: 'escalate', title: '处理「M5故障」投诉帖子，转客服团队', urgency: 'high', due: '立即', completed: false, priorityMatrix: 'urgent_important' },
  { id: 'act4', type: 'collect', title: '收集 UGC 素材（happymom_89 等2条）', urgency: 'medium', due: '今日', completed: true, priorityMatrix: 'not_urgent_important' },
  { id: 'act5', type: 'reply', title: '回复「新手选泵」求助类帖子（5条）', urgency: 'medium', due: '今日', completed: false, priorityMatrix: 'not_urgent_important' },
  { id: 'act6', type: 'monitor', title: '关注「吸力弱」讨论趋势', urgency: 'medium', due: '持续', completed: false, priorityMatrix: 'not_urgent_not_important' },
];

// 注意：intentConfig 已迁移至 ./intentConfig.ts，请从该文件导入

