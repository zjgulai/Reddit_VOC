/** 核心类型定义 - 后端可扩展性基础 */

// ========== 通用 ==========
export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
  code?: string;
}

export type TimeRange = '7d' | '30d' | '90d';

// ========== Reddit 数据模型 ==========

/** 6种大疆标准意图分类 */
export type PostIntent =
  | 'Purchase Intent'
  | 'UGC'
  | 'Bug Report'
  | 'Comparison'
  | 'Question'
  | 'General';

/** Reddit 评论 */
export interface RedditComment {
  id: string;
  redditId: string;
  author: string;
  body: string;
  score: number;
  createdAt: string;
  permalink: string;
  sentiment: 'positive' | 'neutral' | 'negative';
  parentId?: string;
  replies?: RedditComment[];
}

/** Reddit 帖子完整模型 */
export interface RedditPost {
  id: string;
  redditId: string;
  title: string;
  author: string;
  subreddit: string;
  permalink: string;
  score: number;
  upvotes: number;
  upvoteRatio: number;
  comments: number;
  commentList: RedditComment[];
  createdAt: string;
  sentiment: 'positive' | 'neutral' | 'negative';
  intent: PostIntent;
  intentScore: number;
  url: string;
  content?: string;
}

/** 意图配置项 */
export interface IntentConfigItem {
  label: string;
  color: string;
  bg: string;
  actionLabel: string;
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
}

// ========== UGC 素材库 ==========
export type UGCCategory = 'product' | 'experience' | 'comparison' | 'lifestyle' | 'tip';
export type UGCMediaType = 'text' | 'image' | 'video' | 'gallery';
export type UGCSourceType = 'reddit_post' | 'reddit_comment' | 'cross_platform';

export interface UGCItem {
  id: string;
  title: string;
  content: string;
  author: string;
  subreddit: string;
  upvotes: number;
  comments: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  intentScore: number;
  createdAt: string;
  url: string;
  category: UGCCategory;
  tags: string[];
  isArchived: boolean;
  archivedAt?: string;
  mediaType: UGCMediaType;
  engagementRate: number; // 0-100
  quotedBy?: string[]; // 被引用/转载的站点
  autoArchiveReason: string; // 自动归档原因说明
}

export interface UGCFilters {
  category: UGCCategory | 'all';
  mediaType: UGCMediaType | 'all';
  timeRange: TimeRange;
  sentiment: 'positive' | 'neutral' | 'negative' | 'all';
  searchQuery: string;
  minEngagement: number;
}

export interface UGCStats {
  totalArchived: number;
  thisWeek: number;
  positiveRate: number;
  avgEngagement: number;
  topCategory: UGCCategory;
}

// ========== 看板 / 报告 ==========
export interface ReportSummary {
  totalPosts: number;
  newPosts: number;
  sentiment: {
    positive: number;
    neutral: number;
    negative: number;
  };
  topKeywords: { keyword: string; count: number }[];
  topSubreddits: { name: string; count: number }[];
  alerts: ReportAlert[];
  insights: ReportInsight[];
  period: 'daily' | 'weekly' | 'monthly';
  dateRange: { start: string; end: string };
}

export interface ReportAlert {
  id: string;
  type: 'negative_spike' | 'competitor_mention' | 'viral_post' | 'sentiment_drop';
  severity: 'critical' | 'warning' | 'info';
  title: string;
  description: string;
  subreddit?: string;
  postTitle?: string;
  time: string;
  resolved: boolean;
}

export interface ReportInsight {
  id: string;
  type: 'opportunity' | 'risk' | 'trend';
  title: string;
  description: string;
  confidence: number; // 0-100
  evidence: string[];
  action?: string;
}

// ========== 消息 / 通知 ==========
export interface NotificationItem {
  id: string;
  type: 'alert' | 'task' | 'insight' | 'system';
  title: string;
  description: string;
  subreddit?: string;
  postTitle?: string;
  severity?: 'critical' | 'warning' | 'info';
  read: boolean;
  time: string;
  action?: string;
  actionUrl?: string;
  metadata?: Record<string, unknown>;
}

export interface WebhookConfig {
  id: string;
  name: string;
  provider: 'dingtalk' | 'feishu';
  url: string;
  secret: string; // 钉钉签名校验 / 飞书验证 token
  enabled: boolean;
  channels: ('alert' | 'task' | 'insight' | 'system')[];
  severityFilter: ('critical' | 'warning' | 'info')[];
  createdAt: string;
  updatedAt: string;
}

export interface NotificationRule {
  id: string;
  name: string;
  description: string;
  type: 'sentiment' | 'intent' | 'mention' | 'competitor' | 'trend' | 'system';
  enabled: boolean;
  channels: ('app' | 'email' | 'feishu')[];
  threshold?: string;
  frequency: 'immediate' | 'hourly' | 'daily';
  conditions?: NotificationCondition[];
}

export interface NotificationCondition {
  field: string;
  operator: 'gt' | 'lt' | 'eq' | 'contains';
  value: string | number;
}

// ========== 搜索 ==========
export interface SearchConfig {
  id: string;
  name: string;
  keywords: string[];
  subreddits: string[];
  excludeKeywords: string[];
  minUpvotes: number;
  timeRange: 'day' | 'week' | 'month' | 'year' | 'all';
  sortBy: 'relevance' | 'new' | 'hot' | 'top';
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface SearchResult {
  id: string;
  title: string;
  content: string;
  author: string;
  subreddit: string;
  upvotes: number;
  comments: number;
  url: string;
  createdAt: string;
  sentiment: 'positive' | 'neutral' | 'negative';
  intentScore: number;
  keywords: string[];
}

// ========== 分析 ==========
export interface AnalyticsData {
  sentimentOverTime: TimeSeriesPoint[];
  mentionVolume: TimeSeriesPoint[];
  competitorComparison: CompetitorMetric[];
  topicClusters: TopicCluster[];
  subredditBreakdown: SubredditMetric[];
  keywordTrends: KeywordTrend[];
}

export interface TimeSeriesPoint {
  date: string;
  value: number;
  label?: string;
}

export interface CompetitorMetric {
  name: string;
  mentions: number;
  sentiment: number; // -1 to 1
  shareOfVoice: number; // percentage
  trend: 'up' | 'down' | 'stable';
}

export interface TopicCluster {
  id: string;
  name: string;
  size: number;
  keywords: string[];
  sentiment: number;
  posts: number;
  growthRate: number;
}

export interface SubredditMetric {
  name: string;
  posts: number;
  engagement: number;
  sentiment: number;
  growthRate: number;
  topPosts: string[];
}

export interface KeywordTrend {
  keyword: string;
  count: number;
  trend: 'up' | 'down' | 'stable';
  sentiment: number;
  relatedKeywords: string[];
}

// ========== 洞察 ==========
export interface InsightItem {
  id: string;
  type: 'opportunity' | 'risk' | 'trend' | 'action';
  title: string;
  description: string;
  confidence: number;
  source: string;
  subreddit?: string;
  postTitle?: string;
  evidence: string[];
  createdAt: string;
  status: 'new' | 'reviewing' | 'accepted' | 'dismissed';
  tags: string[];
}

export interface StrategyItem {
  id: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  status: 'todo' | 'in_progress' | 'done';
  dueDate?: string;
  assignee?: string;
  relatedInsights: string[];
}

// ========== 案例 ==========
export interface CaseItem {
  id: string;
  title: string;
  description: string;
  source: string;
  url: string;
  category: 'geo' | 'newproduct' | 'insight' | 'business';
  tags: string[];
  date: string;
  author?: string;
  readTime?: string;
}

// ========== 用户 / 设置 ==========
export interface UserProfile {
  id: string;
  name: string;
  email: string;
  avatar?: string;
  role: 'admin' | 'analyst' | 'viewer';
  settings: UserSettings;
  createdAt: string;
}

export interface UserSettings {
  theme: 'light' | 'dark' | 'system';
  language: 'zh' | 'en';
  notifications: {
    app: boolean;
    email: boolean;
    feishu: boolean;
  };
  defaultReportPeriod: 'daily' | 'weekly' | 'monthly';
  timezone: string;
}

// ========== 通用组件 Props ==========
export interface StatCardProps {
  label: string;
  value: string | number;
  change?: number;
  changeLabel?: string;
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  trend?: 'up' | 'down' | 'neutral';
}

export interface PostCardProps {
  id: string;
  title: string;
  author: string;
  subreddit: string;
  upvotes: number;
  comments: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  intentScore: number;
  createdAt: string;
  url: string;
  content?: string;
  redditId?: string;
  permalink?: string;
  score?: number;
  upvoteRatio?: number;
  commentList?: RedditComment[];
}

export interface SectionCardProps {
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  action?: { label: string; onClick: () => void };
}
