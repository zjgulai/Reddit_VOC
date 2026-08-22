import type { PostIntent, RedditComment } from '../types';
import {
  dailyOverview as _dailyOverview,
  dailyAlerts as _dailyAlerts,
  dailyNewPosts as _dailyNewPosts,
  dailyCommunityStatus as _dailyCommunityStatus,
  dailyActionItems,
  dailyResponseMetrics,
  sentimentThermometer,
  type BusinessValueTag,
} from './dailyReportMock';

// 情感水位阈值常量（%）
const SENTIMENT_ALERT_THRESHOLD = 20;
const SENTIMENT_WATCH_THRESHOLD = 15;

import {
  weeklyTrends,
  weeklyOpportunities,
  weeklyRisks,
  weeklyCompetitors,
  weeklyReviews,
  weeklyPlans,
  weeklyOverview as _weeklyOverview,
  weeklyAlerts as _weeklyAlerts,
  weeklyNewPosts as _weeklyNewPosts,
  weeklyCommunityStatus as _weeklyCommunityStatus,
  weeklyActionItems,
  weeklyPainPoints,
  weeklyTopicEvolution,
  weeklyBrandVoiceTrends,
  weeklyContentStrategyROI,
  type WeeklyOpportunity,
  type WeeklyRisk,
  type WeeklyCompetitor,
  type WeeklyReview,
  type WeeklyPlan,
  type WeeklyPainPoint,
} from './weeklyReportMock';
import {
  monthlyBrandHealth,
  monthlyCompetitorShares,
  monthlyCommunityROI,
  monthlyTopicEvolution,
  monthlyKPIs,
  monthlyStrategicAdvices,
  monthlyOverview as _monthlyOverview,
  monthlyAlerts as _monthlyAlerts,
  monthlyNewPosts as _monthlyNewPosts,
  monthlyCommunityStatus as _monthlyCommunityStatus,
  monthlyActionItems,
  monthlyBrandHealthScore,
  monthlyBrandHealthRadar,
  monthlyBrandHealthTrend,
  monthlyCompetitiveMatrix,
  monthlyCategoryMatrix,
  monthlyKPITrend,
  type BrandHealthRadar,
  type CompetitiveMatrix,
  type CategoryMatrix,
} from './monthlyReportMock';

import {
  dailyStats, weeklyStats, monthlyStats,
  dailyAlerts as ueDailyAlerts, weeklyAlerts as ueWeeklyAlerts, monthlyAlerts as ueMonthlyAlerts,
  dailySubreddits, weeklySubreddits, monthlySubreddits,
  getPostsForRange,
  weeklySentimentTrendFromPosts, monthlySentimentTrendFromPosts,
  type ParsedPost,
} from './unifiedEngine';


// ========== 数据联动工具 ==========

/** 生成带随机扰动的数据，使日报/周报/月报有逻辑关联 */
let currentSeed = Date.now();

export function refreshSeed() {
  currentSeed = Date.now();
  return currentSeed;
}

export function getCurrentSeed() {
  return currentSeed;
}

/** 基于 seed 生成伪随机数 */
function seededRandom(seed: number): number {
  const x = Math.sin(seed * 9301 + 49297) % 1;
  return x < 0 ? x + 1 : x;
}

/** 生成每日情感趋势（24小时） */
function generateDailySentimentTrend(seed: number): SentimentTrendPoint[] {
  const hours = Array.from({ length: 24 }, (_, i) => `${i}:00`);
  return hours.map((label, i) => {
    const hour = i;
    const basePositive = hour >= 8 && hour <= 18 ? 55 : 48;
    const variance = Math.sin((hour / 24) * Math.PI * 2) * 5;
    const r1 = seededRandom(seed + i);
    const r2 = seededRandom(seed + i + 100);
    const r3 = seededRandom(seed + i + 200);
    const positive = Math.round(basePositive + variance + (r1 * 6 - 3));
    const negative = Math.round(12 + Math.sin((hour / 24) * Math.PI * 4) * 4 + (r2 * 4 - 2));
    const neutral = Math.max(0, 100 - positive - negative);
    const baseVolume = hour >= 8 && hour <= 22 ? 4 : 1;
    const volume = Math.round(baseVolume + (r3 * 3 - 1));
    return { label, positive, negative, neutral, volume };
  });
}





// ========== 类型定义 ==========

export type ReportPeriod = 'daily' | 'weekly' | 'monthly';

export interface ReportOverview {
  newPosts: number;
  newPostsTrend: number;
  positiveRate: number;
  negativeRate: number;
  neutralRate: number;
  alerts: number;
  highIntent: number;
  ugc: number;
  updatedAt: string;
  sentimentLevel?: string;
  sentimentLevelLabel?: string;
}

export interface SentimentTrendPoint {
  label: string;
  positive: number;
  negative: number;
  neutral: number;
  volume?: number;
}

export interface ReportAlert {
  id: string;
  level: 'critical' | 'warning' | 'info';
  title: string;
  subreddit: string;
  upvotes: number;
  comments: number;
  growth: number;
  summary: string;
  time: string;
  discoveredAt?: string;
  respondedAt?: string;
  resolvedAt?: string;
  impactEstimate?: { potentialLoss: number; affectedCustomers: number };
}

export interface ReportNewPost {
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
  redditId?: string;
  permalink?: string;
  score?: number;
  upvoteRatio?: number;
  commentList?: RedditComment[];
  businessValueTag?: BusinessValueTag;
}

export interface ReportCommunityStatus {
  name: string;
  displayName: string;
  newPosts: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  trend: 'up' | 'down' | 'stable';
  topPostUpvotes?: number;
  activityIndex?: number;
  brandMentionRate?: number;
  sentimentChangeSpeed?: number;
}

export type PriorityMatrix = 'urgent_important' | 'urgent_not_important' | 'not_urgent_important' | 'not_urgent_not_important';

export interface ReportActionItem {
  id: string;
  type: 'reply' | 'collect' | 'escalate' | 'monitor';
  title: string;
  urgency: 'high' | 'medium' | 'low';
  due: string;
  completed: boolean;
  priorityMatrix?: PriorityMatrix;
}

export { type WeeklyOpportunity, type WeeklyRisk, type WeeklyCompetitor, type WeeklyReview, type WeeklyPlan, type WeeklyPainPoint };

export interface MonthlyBrandHealth {
  metric: string;
  current: number;
  lastMonth: number;
  change: number;
  unit: string;
}

export interface MonthlyBrandHealthTrendPoint {
  label: string;
  value: number;
}

export interface MonthlyCompetitorShare {
  name: string;
  share: number;
  positiveRate: number;
  mentionGrowth: number;
  topTopic: string;
}

export interface MonthlyCommunityROI {
  name: string;
  displayName: string;
  posts: number;
  leads: number;
  conversionRate: number;
  quality: 'high' | 'medium' | 'low';
  roi: string;
}

export interface MonthlyTopicEvolution {
  topic: string;
  currentVolume: number;
  lastMonthVolume: number;
  growth: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  lifecycle: 'rising' | 'peak' | 'stable' | 'declining';
  forecast: string;
  predictionAccuracy?: number;
}

export interface MonthlyKPI {
  metric: string;
  value: string;
  target: string;
  achievement: number;
  status: 'good' | 'warning' | 'bad';
}

export interface MonthlyStrategicAdvice {
  id: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  expectedImpact: string;
  timeframe: string;
  resourceAllocation?: { budget: string; manpower: string; time: string };
  expectedROI?: number;
}

export { type BrandHealthRadar, type CompetitiveMatrix, type CategoryMatrix };

export interface BaseReportData {
  period: ReportPeriod;
  overview: ReportOverview;
  sentimentTrend: SentimentTrendPoint[];
  alerts: ReportAlert[];
  newPosts: ReportNewPost[];
  communityStatus: ReportCommunityStatus[];
  actionItems: ReportActionItem[];
}

export interface DailyReportData extends BaseReportData {
  period: 'daily';
  responseMetrics?: typeof dailyResponseMetrics;
  sentimentThermometer?: typeof sentimentThermometer;
}

export interface WeeklyReportData extends BaseReportData {
  period: 'weekly';
  weeklyTrends: typeof weeklyTrends;
  weeklyOpportunities: typeof weeklyOpportunities;
  weeklyRisks: typeof weeklyRisks;
  weeklyCompetitors: typeof weeklyCompetitors;
  weeklyReviews: typeof weeklyReviews;
  weeklyPlans: typeof weeklyPlans;
  painPoints?: typeof weeklyPainPoints;
  topicLifecycles?: typeof weeklyTopicEvolution;
  operationReviews?: typeof weeklyContentStrategyROI;
  brandVoiceTrend?: typeof weeklyBrandVoiceTrends;
}

export interface MonthlyReportData extends BaseReportData {
  period: 'monthly';
  monthlyBrandHealth: typeof monthlyBrandHealth;
  monthlyBrandHealthTrend: typeof monthlyBrandHealthTrend;
  monthlyCompetitorShares: typeof monthlyCompetitorShares;
  monthlyCommunityROI: typeof monthlyCommunityROI;
  monthlyTopicEvolution: typeof monthlyTopicEvolution;
  monthlyKPIs: typeof monthlyKPIs;
  monthlyStrategicAdvices: typeof monthlyStrategicAdvices;
  brandHealthScore?: number;
  brandHealthRadar?: typeof monthlyBrandHealthRadar;
  competitiveMatrix?: typeof monthlyCompetitiveMatrix;
  categoryMatrix?: typeof monthlyCategoryMatrix;
  kpiTrend?: typeof monthlyKPITrend;
  monthlyCategoryValues?: typeof monthlyCategoryMatrix;
}

export interface UnifiedReportData {
  period: ReportPeriod;
  overview: ReportOverview;
  sentimentTrend: SentimentTrendPoint[];
  alerts: ReportAlert[];
  newPosts: ReportNewPost[];
  communityStatus: ReportCommunityStatus[];
  actionItems: ReportActionItem[];
  weeklyTrends?: typeof weeklyTrends;
  weeklyOpportunities?: typeof weeklyOpportunities;
  weeklyRisks?: typeof weeklyRisks;
  weeklyCompetitors?: typeof weeklyCompetitors;
  weeklyReviews?: typeof weeklyReviews;
  weeklyPlans?: typeof weeklyPlans;
  monthlyBrandHealth?: typeof monthlyBrandHealth;
  monthlyBrandHealthTrend?: typeof monthlyBrandHealthTrend;
  monthlyCompetitorShares?: typeof monthlyCompetitorShares;
  monthlyCommunityROI?: typeof monthlyCommunityROI;
  monthlyTopicEvolution?: typeof monthlyTopicEvolution;
  monthlyKPIs?: typeof monthlyKPIs;
  monthlyStrategicAdvices?: typeof monthlyStrategicAdvices;
  responseMetrics?: typeof dailyResponseMetrics;
  sentimentThermometer?: typeof sentimentThermometer;
  painPoints?: typeof weeklyPainPoints;
  topicLifecycles?: typeof weeklyTopicEvolution;
  operationReviews?: typeof weeklyContentStrategyROI;
  brandVoiceTrend?: typeof weeklyBrandVoiceTrends;
  brandHealthScore?: number;
  brandHealthRadar?: typeof monthlyBrandHealthRadar;
  competitiveMatrix?: typeof monthlyCompetitiveMatrix;
  categoryMatrix?: typeof monthlyCategoryMatrix;
  kpiTrend?: typeof monthlyKPITrend;
  monthlyCategoryValues?: typeof monthlyCategoryMatrix;
}

// ========== 统一数据转换辅助函数 ==========

/** 将统一引擎的 stats 转为 ReportOverview */
function buildOverviewFromStats(
  stats: typeof dailyStats,
  _period: ReportPeriod,
  baseTrend: number
): ReportOverview {
  return {
    newPosts: stats.totalPosts,
    newPostsTrend: baseTrend,
    positiveRate: stats.positiveRate,
    negativeRate: stats.negativeRate,
    neutralRate: stats.neutralRate,
    alerts: stats.alerts,
    highIntent: stats.highIntentCount,
    ugc: stats.ugcCount,
    updatedAt: new Date().toLocaleString('zh-CN'),
    sentimentLevel: stats.negativeRate > SENTIMENT_ALERT_THRESHOLD ? 'alert' : stats.negativeRate > SENTIMENT_WATCH_THRESHOLD ? 'watch' : 'calm',
    sentimentLevelLabel: stats.negativeRate > SENTIMENT_ALERT_THRESHOLD ? '警戒' : stats.negativeRate > SENTIMENT_WATCH_THRESHOLD ? '关注' : '平稳',
  };
}

/** 将统一引擎的帖子转为 ReportNewPost */
function buildNewPostsFromUnified(posts: ParsedPost[]): ReportNewPost[] {
  return posts.map((p) => ({
    id: p.id,
    title: p.title,
    subreddit: p.subreddit,
    author: p.author,
    time: p.time,
    upvotes: p.upvotes,
    comments: p.comments,
    intentScore: p.intentScore,
    sentiment: p.sentiment,
    intent: p.intent,
    action: p.action,
  }));
}

/** 将统一引擎的 alerts 转为 ReportAlert */
function buildAlertsFromUnified(posts: ParsedPost[]): ReportAlert[] {
  return posts.map((p) => ({
    id: `ua_${p.id}`,
    level: p.sentiment === 'negative' && p.intent === 'Bug Report' ? 'critical'
      : p.sentiment === 'negative' ? 'warning' : 'info',
    title: p.title,
    subreddit: p.subreddit,
    upvotes: p.upvotes,
    comments: p.comments,
    growth: Math.round(p.upvotes / 10),
    summary: `${p.subreddit} 社区讨论，情感${p.sentiment === 'positive' ? '正面' : p.sentiment === 'negative' ? '负面' : '中性'}`,
    time: p.time,
  }));
}

/** 将统一引擎的子版块数据转为 ReportCommunityStatus */
function buildCommunityStatusFromUnified(
  subreddits: typeof dailySubreddits
): ReportCommunityStatus[] {
  return subreddits.map((s) => ({
    name: s.name,
    displayName: s.displayName,
    newPosts: s.postCount,
    sentiment: s.positive >= s.negative ? (s.positive > s.neutral ? 'positive' : 'neutral') : 'negative',
    trend: s.postCount > 5 ? 'up' : s.postCount > 2 ? 'stable' : 'down',
    topPostUpvotes: s.avgUpvotes * 2,
    activityIndex: Math.min(100, s.postCount * 10 + 30),
    brandMentionRate: Math.round(s.momcozyMentions / Math.max(1, s.postCount) * 100),
  }));
}

// ========== 数据聚合管线 ==========

export interface BrandScoreDatum {
  dimension: string;
  score: number;
  fullMark: number;
}

export function generateBrandScoreData(overview: ReportOverview): BrandScoreDatum[] {
  const { positiveRate, negativeRate, alerts, highIntent, ugc, newPosts } = overview;
  return [
    { dimension: '品牌声量', score: Math.min(100, Math.round(newPosts * 1.5)), fullMark: 100 },
    { dimension: '正面口碑', score: Math.min(100, Math.round(positiveRate * 1.4)), fullMark: 100 },
    { dimension: '用户互动', score: Math.min(100, Math.round(ugc * 10 + 5)), fullMark: 100 },
    { dimension: '购买意向', score: Math.min(100, Math.round(highIntent * 8 + 10)), fullMark: 100 },
    { dimension: '竞品优势', score: Math.min(100, Math.round((positiveRate - negativeRate + 100) / 2.5)), fullMark: 100 },
    { dimension: '危机响应', score: Math.max(0, Math.min(100, Math.round(100 - alerts * 5))), fullMark: 100 },
  ];
}

export function computeOverviewFromSentimentTrend(
  trend: SentimentTrendPoint[]
): { positiveRate: number; negativeRate: number; neutralRate: number } {
  const total = trend.length;
  if (total === 0) return { positiveRate: 0, negativeRate: 0, neutralRate: 0 };
  const avgPositive = trend.reduce((sum, t) => sum + t.positive, 0) / total;
  const avgNegative = trend.reduce((sum, t) => sum + t.negative, 0) / total;
  const avgNeutral = trend.reduce((sum, t) => sum + t.neutral, 0) / total;
  return {
    positiveRate: Math.round(avgPositive * 10) / 10,
    negativeRate: Math.round(avgNegative * 10) / 10,
    neutralRate: Math.round(avgNeutral * 10) / 10,
  };
}

/** 将统一引擎的 DailySentimentTrend 转为 ReportEngine 的 SentimentTrendPoint */
function convertSentimentTrend(
  trend: typeof weeklySentimentTrendFromPosts
): SentimentTrendPoint[] {
  return trend.map((d) => {
    const total = d.total || 1;
    return {
      label: d.date,
      positive: Math.round((d.positive / total) * 1000) / 10,
      negative: Math.round((d.negative / total) * 1000) / 10,
      neutral: Math.round((d.neutral / total) * 1000) / 10,
      volume: total,
    };
  });
}

// ========== 生成函数 ==========

export function generateReportData(period: ReportPeriod, seed?: number): UnifiedReportData {
  const s = seed ?? currentSeed;

  if (period === 'daily') {
    const dailyUePosts = getPostsForRange('24h');
    const dailyTrend = generateDailySentimentTrend(s);
    const computedDaily = computeOverviewFromSentimentTrend(dailyTrend);
    const dailyOverview = buildOverviewFromStats(dailyStats, 'daily', 11.3);
    return structuredClone({
      period: 'daily',
      overview: {
        ...dailyOverview,
        positiveRate: computedDaily.positiveRate,
        negativeRate: computedDaily.negativeRate,
        neutralRate: computedDaily.neutralRate,
      },
      sentimentTrend: dailyTrend,
      alerts: buildAlertsFromUnified(ueDailyAlerts),
      newPosts: buildNewPostsFromUnified(dailyUePosts),
      communityStatus: buildCommunityStatusFromUnified(dailySubreddits),
      actionItems: dailyActionItems,
      responseMetrics: dailyResponseMetrics,
      sentimentThermometer,
    }) as UnifiedReportData;
  }

  if (period === 'weekly') {
    const weeklyUePosts = getPostsForRange('7d');
    const weeklyTrend = convertSentimentTrend(weeklySentimentTrendFromPosts);
    const computedWeekly = computeOverviewFromSentimentTrend(weeklyTrend);
    const weeklyOverview = buildOverviewFromStats(weeklyStats, 'weekly', 9.3);
    return structuredClone({
      period: 'weekly',
      overview: {
        ...weeklyOverview,
        positiveRate: computedWeekly.positiveRate,
        negativeRate: computedWeekly.negativeRate,
        neutralRate: computedWeekly.neutralRate,
      },
      sentimentTrend: weeklyTrend,
      alerts: buildAlertsFromUnified(ueWeeklyAlerts),
      newPosts: buildNewPostsFromUnified(weeklyUePosts),
      communityStatus: buildCommunityStatusFromUnified(weeklySubreddits),
      actionItems: weeklyActionItems,
      weeklyTrends,
      weeklyOpportunities,
      weeklyRisks,
      weeklyCompetitors,
      weeklyReviews,
      weeklyPlans,
      painPoints: weeklyPainPoints,
      topicLifecycles: weeklyTopicEvolution,
      operationReviews: weeklyContentStrategyROI,
      brandVoiceTrend: weeklyBrandVoiceTrends,
    }) as UnifiedReportData;
  }

  // monthly
  const monthlyUePosts = getPostsForRange('30d');
  const monthlyTrend = convertSentimentTrend(monthlySentimentTrendFromPosts);
  const computedMonthly = computeOverviewFromSentimentTrend(monthlyTrend);
  const monthlyOverview = buildOverviewFromStats(monthlyStats, 'monthly', 11.7);
  return structuredClone({
    period: 'monthly',
    overview: {
      ...monthlyOverview,
      positiveRate: computedMonthly.positiveRate,
      negativeRate: computedMonthly.negativeRate,
      neutralRate: computedMonthly.neutralRate,
    },
    sentimentTrend: monthlyTrend,
    alerts: buildAlertsFromUnified(ueMonthlyAlerts),
    newPosts: buildNewPostsFromUnified(monthlyUePosts),
    communityStatus: buildCommunityStatusFromUnified(monthlySubreddits),
    actionItems: monthlyActionItems,
    monthlyBrandHealth,
    monthlyBrandHealthTrend: monthlyBrandHealthTrend,
    monthlyCompetitorShares,
    monthlyCommunityROI,
    monthlyTopicEvolution,
    monthlyKPIs,
    monthlyStrategicAdvices,
    brandHealthScore: monthlyBrandHealthScore,
    brandHealthRadar: monthlyBrandHealthRadar,
    competitiveMatrix: monthlyCompetitiveMatrix,
    categoryMatrix: monthlyCategoryMatrix,
    kpiTrend: monthlyKPITrend,
    monthlyCategoryValues: monthlyCategoryMatrix,
  }) as UnifiedReportData;
}

export function isDailyReport(data: UnifiedReportData): data is DailyReportData {
  return data.period === 'daily';
}

export function isWeeklyReport(data: UnifiedReportData): data is WeeklyReportData {
  return data.period === 'weekly';
}

export function isMonthlyReport(data: UnifiedReportData): data is MonthlyReportData {
  return data.period === 'monthly';
}

export function validateReportConsistency(
  daily: UnifiedReportData,
  weekly: UnifiedReportData,
  monthly: UnifiedReportData,
  _seed?: number
): {
  valid: boolean;
  issues: string[];
} {
  const issues: string[] = [];

  [daily, weekly, monthly].forEach((report) => {
    const { positiveRate, negativeRate, neutralRate } = report.overview;
    const sum = Math.round((positiveRate + negativeRate + neutralRate) * 10) / 10;
    if (sum !== 100) {
      issues.push(`${report.period} 情感率总和 ${sum} ≠ 100`);
    }
    if (report.sentimentTrend && report.sentimentTrend.length > 0) {
      const computed = computeOverviewFromSentimentTrend(report.sentimentTrend);
      const positiveDiff = Math.abs(computed.positiveRate - positiveRate);
      if (positiveDiff > 5) {
        issues.push(`${report.period} positiveRate (${positiveRate}) 与 sentimentTrend 计算值 (${computed.positiveRate}) 偏差 ${positiveDiff.toFixed(1)}%`);
      }
    }
  });

  // 检查跨周期数据关联合理性（使用非线性阈值，避免简单乘法检测）
  if (daily.overview.newPosts > 0) {
    const dailyWeeklyRatio = weekly.overview.newPosts / daily.overview.newPosts;
    if (dailyWeeklyRatio < 3 || dailyWeeklyRatio > 10) {
      issues.push(`weekly newPosts 与 daily 关联异常（比值 ${dailyWeeklyRatio.toFixed(2)}，超出 3-10 倍合理范围）`);
    }
  }

  if (weekly.overview.newPosts > 0) {
    const weeklyMonthlyRatio = monthly.overview.newPosts / weekly.overview.newPosts;
    if (weeklyMonthlyRatio < 3 || weeklyMonthlyRatio > 6) {
      issues.push(`monthly newPosts 与 weekly 关联异常（比值 ${weeklyMonthlyRatio.toFixed(2)}，超出 3-6 倍合理范围）`);
    }
  }

  return { valid: issues.length === 0, issues };
}

