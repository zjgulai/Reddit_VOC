// 统一数据引擎 —— 从 searchMock.ts 的帖子计算所有聚合指标
// 解决各页面数据孤岛问题，确保 Dashboard/Analytics/Search 数据一致

import { searchPosts } from './searchMock';
import type { SearchPost } from './searchMock';
import type { PostIntent } from '../types';

// ===== 时间解析 =====

export interface ParsedPost extends SearchPost {
  date: Date; // 模拟绝对时间
  hour: number;
}

function parseRelativeTime(timeStr: string, baseDate: Date = new Date('2026-07-13T12:00:00')): Date {
  const d = new Date(baseDate);
  const match = timeStr.match(/(\d+)\s*(分钟|小时|天)前/);
  if (!match) return d;
  const value = parseInt(match[1], 10);
  const unit = match[2];
  if (unit === '分钟') d.setMinutes(d.getMinutes() - value);
  else if (unit === '小时') d.setHours(d.getHours() - value);
  else if (unit === '天') d.setDate(d.getDate() - value);
  return d;
}

const BASE_DATE = new Date('2026-07-13T12:00:00');

/** 所有帖子带上绝对时间 */
export const parsedPosts: ParsedPost[] = searchPosts.map((p) => {
  const date = parseRelativeTime(p.time, BASE_DATE);
  return { ...p, date, hour: date.getHours() };
});

// ===== 时间范围过滤 =====

export type TimeRange = '24h' | '7d' | '30d';

export function filterPostsByRange(posts: ParsedPost[], range: TimeRange): ParsedPost[] {
  const now = BASE_DATE.getTime();
  const msMap: Record<TimeRange, number> = {
    '24h': 24 * 60 * 60 * 1000,
    '7d': 7 * 24 * 60 * 60 * 1000,
    '30d': 30 * 24 * 60 * 60 * 1000,
  };
  const cutoff = now - msMap[range];
  return posts.filter((p) => p.date.getTime() >= cutoff);
}

// ===== 聚合计算 =====

export interface AggregatedStats {
  totalPosts: number;
  positive: number;
  neutral: number;
  negative: number;
  positiveRate: number;
  negativeRate: number;
  neutralRate: number;
  avgUpvotes: number;
  avgComments: number;
  avgIntentScore: number;
  highIntentCount: number; // intentScore >= 70
  ugcCount: number; // intent === 'UGC'
  bugReportCount: number; // intent === 'Bug Report'
  alerts: number; // sentiment === 'negative' && intentScore >= 60
  subreddits: string[];
  topSubreddit: { name: string; count: number } | null;
  intents: Record<PostIntent, number>;
  hourlyDistribution: Record<number, number>;
}

export function aggregatePosts(posts: ParsedPost[]): AggregatedStats {
  const total = posts.length;
  if (total === 0) {
    return {
      totalPosts: 0, positive: 0, neutral: 0, negative: 0,
      positiveRate: 0, negativeRate: 0, neutralRate: 0,
      avgUpvotes: 0, avgComments: 0, avgIntentScore: 0,
      highIntentCount: 0, ugcCount: 0, bugReportCount: 0, alerts: 0,
      subreddits: [], topSubreddit: null,
      intents: {} as Record<PostIntent, number>,
      hourlyDistribution: {},
    };
  }

  const positive = posts.filter((p) => p.sentiment === 'positive').length;
  const neutral = posts.filter((p) => p.sentiment === 'neutral').length;
  const negative = posts.filter((p) => p.sentiment === 'negative').length;

  const intentCounts = {} as Record<string, number>;
  const subredditCounts: Record<string, number> = {};
  const hourlyDist: Record<number, number> = {};

  let totalUpvotes = 0;
  let totalComments = 0;
  let totalIntentScore = 0;
  let highIntent = 0;
  let ugc = 0;
  let bugs = 0;
  let alerts = 0;

  for (const p of posts) {
    totalUpvotes += p.upvotes;
    totalComments += p.comments;
    totalIntentScore += p.intentScore;

    if (p.intentScore >= 70) highIntent++;
    if (p.intent === 'UGC') ugc++;
    if (p.intent === 'Bug Report') bugs++;
    if (p.sentiment === 'negative' && p.intentScore >= 60) alerts++;

    intentCounts[p.intent] = (intentCounts[p.intent] || 0) + 1;
    subredditCounts[p.subreddit] = (subredditCounts[p.subreddit] || 0) + 1;
    hourlyDist[p.hour] = (hourlyDist[p.hour] || 0) + 1;
  }

  const topSubredditEntry = Object.entries(subredditCounts).sort((a, b) => b[1] - a[1])[0];

  return {
    totalPosts: total,
    positive,
    neutral,
    negative,
    positiveRate: Math.round((positive / total) * 1000) / 10,
    negativeRate: Math.round((negative / total) * 1000) / 10,
    neutralRate: Math.round((neutral / total) * 1000) / 10,
    avgUpvotes: Math.round(totalUpvotes / total),
    avgComments: Math.round(totalComments / total),
    avgIntentScore: Math.round(totalIntentScore / total),
    highIntentCount: highIntent,
    ugcCount: ugc,
    bugReportCount: bugs,
    alerts,
    subreddits: Object.keys(subredditCounts),
    topSubreddit: topSubredditEntry ? { name: topSubredditEntry[0], count: topSubredditEntry[1] } : null,
    intents: intentCounts as Record<PostIntent, number>,
    hourlyDistribution: hourlyDist,
  };
}

// ===== 预计算各时间范围指标 =====

export const dailyStats = aggregatePosts(filterPostsByRange(parsedPosts, '24h'));
export const weeklyStats = aggregatePosts(filterPostsByRange(parsedPosts, '7d'));
export const monthlyStats = aggregatePosts(filterPostsByRange(parsedPosts, '30d'));
export const allStats = aggregatePosts(parsedPosts);

// ===== 子版块画像（从真实帖子聚合） =====

export interface SubredditAgg {
  name: string;
  displayName: string;
  postCount: number;
  avgUpvotes: number;
  avgComments: number;
  positive: number;
  neutral: number;
  negative: number;
  topIntent: PostIntent | null;
  momcozyMentions: number;
}

export function aggregateBySubreddit(posts: ParsedPost[]): SubredditAgg[] {
  const map = new Map<string, {
    posts: ParsedPost[];
    positive: number;
    neutral: number;
    negative: number;
    momcozyCount: number;
  }>();

  for (const p of posts) {
    const existing = map.get(p.subreddit) || { posts: [], positive: 0, neutral: 0, negative: 0, momcozyCount: 0 };
    existing.posts.push(p);
    if (p.sentiment === 'positive') existing.positive++;
    else if (p.sentiment === 'neutral') existing.neutral++;
    else existing.negative++;
    if (p.title.toLowerCase().includes('momcozy')) existing.momcozyCount++;
    map.set(p.subreddit, existing);
  }

  return Array.from(map.entries()).map(([name, data]) => {
    const intentCounts: Record<string, number> = {};
    for (const p of data.posts) {
      intentCounts[p.intent] = (intentCounts[p.intent] || 0) + 1;
    }
    const topIntent = Object.entries(intentCounts).sort((a, b) => b[1] - a[1])[0]?.[0] as PostIntent | null;
    const totalUpvotes = data.posts.reduce((s, p) => s + p.upvotes, 0);
    const totalComments = data.posts.reduce((s, p) => s + p.comments, 0);

    return {
      name,
      displayName: `r/${name}`,
      postCount: data.posts.length,
      avgUpvotes: Math.round(totalUpvotes / data.posts.length),
      avgComments: Math.round(totalComments / data.posts.length),
      positive: data.positive,
      neutral: data.neutral,
      negative: data.negative,
      topIntent,
      momcozyMentions: data.momcozyCount,
    };
  }).sort((a, b) => b.postCount - a.postCount);
}

export const dailySubreddits = aggregateBySubreddit(filterPostsByRange(parsedPosts, '24h'));
export const weeklySubreddits = aggregateBySubreddit(filterPostsByRange(parsedPosts, '7d'));
export const monthlySubreddits = aggregateBySubreddit(filterPostsByRange(parsedPosts, '30d'));

// ===== 情感趋势（按天聚合） =====

export interface DailySentimentTrend {
  date: string;
  positive: number;
  neutral: number;
  negative: number;
  total: number;
}

export function buildSentimentTrend(posts: ParsedPost[]): DailySentimentTrend[] {
  const dayMap = new Map<string, { positive: number; neutral: number; negative: number }>();

  for (const p of posts) {
    const key = `${p.date.getMonth() + 1}月${p.date.getDate()}日`;
    const existing = dayMap.get(key) || { positive: 0, neutral: 0, negative: 0 };
    if (p.sentiment === 'positive') existing.positive++;
    else if (p.sentiment === 'neutral') existing.neutral++;
    else existing.negative++;
    dayMap.set(key, existing);
  }

  return Array.from(dayMap.entries())
    .map(([date, d]) => ({
      date,
      positive: d.positive,
      neutral: d.neutral,
      negative: d.negative,
      total: d.positive + d.neutral + d.negative,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export const weeklySentimentTrendFromPosts = buildSentimentTrend(filterPostsByRange(parsedPosts, '7d'));
export const monthlySentimentTrendFromPosts = buildSentimentTrend(filterPostsByRange(parsedPosts, '30d'));

// ===== 话题聚类（从意图聚合） =====

export interface TopicClusterFromPosts {
  name: string;
  count: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  keywords: string[];
}

const INTENT_TOPIC_MAP: Record<string, { name: string; keywords: string[] }> = {
  'Purchase Intent': { name: '购买意向', keywords: ['推荐', '选购', '值得买', '预算'] },
  'Comparison': { name: '竞品对比', keywords: ['对比', 'vs', '哪个好', '差距'] },
  'UGC': { name: '用户口碑', keywords: ['体验', '好用', '满意', '推荐'] },
  'Bug Report': { name: '故障投诉', keywords: ['问题', '故障', '售后', '维修'] },
  'Question': { name: '求助问答', keywords: ['怎么', '求助', '建议', '新手'] },
  'General': { name: '一般讨论', keywords: ['讨论', '分享', '交流'] },
};

export function buildTopicClusters(posts: ParsedPost[]): TopicClusterFromPosts[] {
  const map = new Map<string, { count: number; positive: number; neutral: number; negative: number }>();

  for (const p of posts) {
    const topic = INTENT_TOPIC_MAP[p.intent] || { name: '其他', keywords: [] };
    const existing = map.get(topic.name) || { count: 0, positive: 0, neutral: 0, negative: 0 };
    existing.count++;
    if (p.sentiment === 'positive') existing.positive++;
    else if (p.sentiment === 'neutral') existing.neutral++;
    else existing.negative++;
    map.set(topic.name, existing);
  }

  return Array.from(map.entries()).map(([name, data]) => {
    const intentKey = Object.entries(INTENT_TOPIC_MAP).find(([, v]) => v.name === name)?.[0] || '';
    const keywords = INTENT_TOPIC_MAP[intentKey]?.keywords || ['讨论'];
    let sentiment: 'positive' | 'neutral' | 'negative' = 'neutral';
    if (data.positive > data.neutral && data.positive > data.negative) sentiment = 'positive';
    else if (data.negative > data.positive && data.negative > data.neutral) sentiment = 'negative';

    return { name, count: data.count, sentiment, keywords };
  }).sort((a, b) => b.count - a.count);
}

export const weeklyTopicClusters = buildTopicClusters(filterPostsByRange(parsedPosts, '7d'));
export const monthlyTopicClusters = buildTopicClusters(filterPostsByRange(parsedPosts, '30d'));

// ===== 竞品提及统计 =====

export function countCompetitorMentions(posts: ParsedPost[]): Record<string, number> {
  const competitors = ['Elvie', 'Spectra', 'Willow', 'Medela', 'Lansinoh', 'Haakaa'];
  const counts: Record<string, number> = {};
  for (const c of competitors) counts[c] = 0;
  for (const p of posts) {
    for (const c of competitors) {
      if (p.title.toLowerCase().includes(c.toLowerCase())) counts[c]++;
    }
  }
  return counts;
}

export const weeklyCompetitorMentions = countCompetitorMentions(filterPostsByRange(parsedPosts, '7d'));
export const monthlyCompetitorMentions = countCompetitorMentions(filterPostsByRange(parsedPosts, '30d'));

// ===== 高价值帖子（警报） =====

export function getAlertPosts(posts: ParsedPost[]): ParsedPost[] {
  return posts
    .filter((p) => p.sentiment === 'negative' && (p.intent === 'Bug Report' || p.upvotes >= 50))
    .sort((a, b) => b.upvotes - a.upvotes);
}

export const dailyAlerts = getAlertPosts(filterPostsByRange(parsedPosts, '24h'));
export const weeklyAlerts = getAlertPosts(filterPostsByRange(parsedPosts, '7d'));
export const monthlyAlerts = getAlertPosts(filterPostsByRange(parsedPosts, '30d'));

// ===== 便捷导出 =====

export function getStatsForRange(range: TimeRange): AggregatedStats {
  if (range === '24h') return dailyStats;
  if (range === '7d') return weeklyStats;
  return monthlyStats;
}

export function getSubredditsForRange(range: TimeRange): SubredditAgg[] {
  if (range === '24h') return dailySubreddits;
  if (range === '7d') return weeklySubreddits;
  return monthlySubreddits;
}

export function getPostsForRange(range: TimeRange): ParsedPost[] {
  return filterPostsByRange(parsedPosts, range);
}
