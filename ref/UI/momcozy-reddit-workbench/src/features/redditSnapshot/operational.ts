import type {
  RedditSnapshotCore,
  SnapshotPost,
  SnapshotSentiment,
  SnapshotTagRule,
} from './types';

export const MOMCOZY_BRAND_BINDINGS = new Set([
  'momcozy_entity_reviewed',
  'momcozy_sentence_bound',
]);

export interface CountedLabel {
  id: string;
  label: string;
  value: number;
}

export interface OperationalPeriod {
  start: string;
  end: string;
}

export interface OperationalPeriodMetrics {
  start: string;
  end: string;
  allPosts: SnapshotPost[];
  momcozyPosts: SnapshotPost[];
  postCount: number;
  momcozyPostCount: number;
  linkedCommentCount: number;
  negativePosts: number;
  positivePosts: number;
  neutralPosts: number;
  negativeRate: number | null;
  positiveRate: number | null;
  netSentiment: number | null;
  highSeverityPosts: number;
  productBoundPosts: number;
  averageScore: number | null;
  topics: CountedLabel[];
  subreddits: CountedLabel[];
  products: CountedLabel[];
  tags: CountedLabel[];
  dailyPosts: Array<{ label: string; value: number }>;
}

export interface OperationalBrandScore {
  overall: number;
  dimensions: Array<{
    id: 'reputation' | 'product_experience' | 'recommendation_trust' | 'risk_resilience';
    label: string;
    score: number;
    help: string;
  }>;
  sampleSize: number;
}

function clamp(value: number, minimum = 0, maximum = 100): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function round(value: number, digits = 1): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

const BUSINESS_DATE_FORMATTER = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

export function businessCalendarDate(value: string): string {
  const parts = BUSINESS_DATE_FORMATTER.formatToParts(new Date(value));
  const year = parts.find((part) => part.type === 'year')?.value;
  const month = parts.find((part) => part.type === 'month')?.value;
  const day = parts.find((part) => part.type === 'day')?.value;
  if (!year || !month || !day) throw new Error(`无法转换业务日期：${value}`);
  return `${year}-${month}-${day}`;
}

function isWithinPeriod(value: string, period: OperationalPeriod): boolean {
  const date = businessCalendarDate(value);
  return date >= period.start && date < period.end;
}

function isMomcozyBrand(value: string): boolean {
  return value.trim().toLowerCase() === 'momcozy';
}

export function isMomcozyPost(post: SnapshotPost): boolean {
  return MOMCOZY_BRAND_BINDINGS.has(post.brand_binding ?? '')
    || post.mentioned_brands.some(isMomcozyBrand)
    || (post.product_bindings?.length ?? 0) > 0;
}

export function isHighValueContent(post: SnapshotPost): boolean {
  return isMomcozyPost(post)
    && post.content.trim().length > 0
    && (post.score >= 5 || post.linked_comment_count >= 5);
}

export function isPrioritySignal(post: SnapshotPost): boolean {
  return isMomcozyPost(post)
    && (post.analysis.sentiment_label === 'negative' || post.analysis.severity === 'high')
    && (post.score >= 5 || post.linked_comment_count >= 5);
}

export function tagNames(
  post: SnapshotPost,
  tagRules: ReadonlyMap<string, SnapshotTagRule>,
  limit = 4,
): string[] {
  return post.tagging.aspect_tag_ids
    .map((tagId) => tagRules.get(tagId)?.name_cn ?? tagId)
    .slice(0, limit);
}

function countLabels(
  values: Iterable<{ id: string; label: string }>,
  limit: number,
): CountedLabel[] {
  const counts = new Map<string, { label: string; value: number }>();
  for (const item of values) {
    const previous = counts.get(item.id);
    counts.set(item.id, {
      label: item.label,
      value: (previous?.value ?? 0) + 1,
    });
  }
  return [...counts.entries()]
    .map(([id, item]) => ({ id, ...item }))
    .sort((left, right) => right.value - left.value || left.label.localeCompare(right.label, 'zh-CN'))
    .slice(0, limit);
}

function sentimentCounts(posts: SnapshotPost[]): Record<SnapshotSentiment, number> {
  return posts.reduce<Record<SnapshotSentiment, number>>((counts, post) => {
    counts[post.analysis.sentiment_label] += 1;
    return counts;
  }, { positive: 0, neutral: 0, negative: 0 });
}

export function derivePeriodMetrics(
  snapshot: RedditSnapshotCore,
  period: OperationalPeriod,
): OperationalPeriodMetrics {
  const allPosts = snapshot.posts.filter((post) => isWithinPeriod(post.created_at_utc, period));
  const momcozyPosts = allPosts.filter(isMomcozyPost);
  const sentiments = sentimentCounts(momcozyPosts);
  const classified = sentiments.positive + sentiments.neutral + sentiments.negative;
  const dailyCounts = new Map<string, number>();
  for (const post of allPosts) {
    const date = businessCalendarDate(post.created_at_utc);
    dailyCounts.set(date, (dailyCounts.get(date) ?? 0) + 1);
  }

  return {
    start: period.start,
    end: period.end,
    allPosts,
    momcozyPosts,
    postCount: allPosts.length,
    momcozyPostCount: momcozyPosts.length,
    linkedCommentCount: momcozyPosts.reduce((sum, post) => sum + post.linked_comment_count, 0),
    negativePosts: sentiments.negative,
    positivePosts: sentiments.positive,
    neutralPosts: sentiments.neutral,
    negativeRate: classified > 0 ? sentiments.negative / classified : null,
    positiveRate: classified > 0 ? sentiments.positive / classified : null,
    netSentiment: classified > 0 ? (sentiments.positive - sentiments.negative) / classified : null,
    highSeverityPosts: momcozyPosts.filter((post) => post.analysis.severity === 'high').length,
    productBoundPosts: momcozyPosts.filter((post) => (post.product_bindings?.length ?? 0) > 0).length,
    averageScore: momcozyPosts.length > 0
      ? momcozyPosts.reduce((sum, post) => sum + post.score, 0) / momcozyPosts.length
      : null,
    topics: countLabels(momcozyPosts.map((post) => ({
      id: post.analysis.topic,
      label: post.analysis.topic,
    })), 8),
    subreddits: countLabels(momcozyPosts.map((post) => ({
      id: post.subreddit || 'unknown',
      label: post.subreddit ? `r/${post.subreddit}` : '未知社区',
    })), 8),
    products: countLabels(momcozyPosts.flatMap((post) => (
      post.product_bindings ?? []
    ).map((binding) => ({
      id: binding.exact_spu?.spu_id ?? binding.product_family?.id ?? binding.category.id,
      label: binding.exact_spu?.spu_name
        ?? binding.product_family?.name_cn
        ?? binding.category.name_cn,
    }))), 8),
    tags: countLabels(momcozyPosts.flatMap((post) => post.tagging.aspect_tag_ids.map((tagId) => ({
      id: tagId,
      label: snapshot.tagRulesById.get(tagId)?.name_cn ?? tagId,
    }))), 12),
    dailyPosts: [...dailyCounts.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([label, value]) => ({ label: label.slice(5), value })),
  };
}

export function deriveAllHistoryMetrics(snapshot: RedditSnapshotCore): OperationalPeriodMetrics {
  return derivePeriodMetrics(snapshot, {
    start: snapshot.aggregates.date_range.posts[0].slice(0, 10),
    end: '9999-12-31',
  });
}

export function compareRate(current: number | null, baseline: number | null): number | null {
  if (current === null || baseline === null || baseline === 0) return null;
  return (current - baseline) / Math.abs(baseline);
}

export function comparePoints(current: number | null, baseline: number | null): number | null {
  if (current === null || baseline === null) return null;
  return current - baseline;
}

function sentimentHealth(posts: SnapshotPost[]): number {
  if (posts.length === 0) return 50;
  const counts = sentimentCounts(posts);
  return clamp(50 + (50 * (counts.positive - counts.negative)) / posts.length);
}

export function deriveOperationalBrandScore(snapshot: RedditSnapshotCore): OperationalBrandScore {
  const momcozyPosts = snapshot.posts.filter(isMomcozyPost);
  const productPosts = momcozyPosts.filter((post) => (post.product_bindings?.length ?? 0) > 0);
  const reputation = sentimentHealth(momcozyPosts);
  const productExperience = sentimentHealth(productPosts.length > 0 ? productPosts : momcozyPosts);
  const recommendationPosts = momcozyPosts.filter((post) => post.tagging.matches.some((match) => {
    const rule = snapshot.tagRulesById.get(match.tag_id);
    const text = `${rule?.theme ?? ''} ${rule?.name_cn ?? ''}`;
    return /推荐|信任|忠诚/.test(text);
  }));
  const recommendationTrust = sentimentHealth(recommendationPosts.length > 0 ? recommendationPosts : momcozyPosts);
  const riskPenalty = momcozyPosts.length === 0 ? 0 : momcozyPosts.reduce((sum, post) => {
    const severityWeight = post.analysis.severity === 'high' ? 1 : post.analysis.severity === 'medium' ? 0.35 : 0.1;
    const sentimentWeight = post.analysis.sentiment_label === 'negative' ? 1 : post.analysis.sentiment_label === 'neutral' ? 0.2 : 0;
    return sum + (severityWeight * 0.55) + (sentimentWeight * 0.45);
  }, 0) / momcozyPosts.length;
  const riskResilience = clamp(100 * (1 - riskPenalty));
  const dimensions: OperationalBrandScore['dimensions'] = [
    {
      id: 'reputation',
      label: '口碑健康',
      score: round(reputation, 2),
      help: 'Momcozy 帖子净情感映射到 0–100：50 + 50×(正面−负面)/帖子数。中性保留在分母。',
    },
    {
      id: 'product_experience',
      label: '产品体验',
      score: round(productExperience, 2),
      help: '有品类、产品族或 SPU 绑定的 Momcozy 帖子，按同一净情感公式计算。',
    },
    {
      id: 'recommendation_trust',
      label: '推荐信任',
      score: round(recommendationTrust, 2),
      help: '命中推荐、信任或忠诚主题标签的 Momcozy 帖子，按同一净情感公式计算。',
    },
    {
      id: 'risk_resilience',
      label: '风险韧性',
      score: round(riskResilience, 2),
      help: '100 减去严重度与负面情感的加权观察惩罚；高严重度和负面权重最高。',
    },
  ];
  return {
    overall: round(dimensions.reduce((sum, item) => sum + item.score, 0) / dimensions.length, 2),
    dimensions,
    sampleSize: momcozyPosts.length,
  };
}

export function highValueContent(snapshot: RedditSnapshotCore): SnapshotPost[] {
  return snapshot.posts
    .filter(isHighValueContent)
    .sort((left, right) => (
      right.linked_comment_count - left.linked_comment_count
      || right.score - left.score
      || right.created_at_utc.localeCompare(left.created_at_utc)
    ));
}

export function prioritySignals(snapshot: RedditSnapshotCore): SnapshotPost[] {
  const severityRank: Record<string, number> = { high: 3, medium: 2, low: 1 };
  return snapshot.posts
    .filter(isPrioritySignal)
    .sort((left, right) => (
      (severityRank[right.analysis.severity] ?? 0) - (severityRank[left.analysis.severity] ?? 0)
      || Number(right.analysis.sentiment_label === 'negative') - Number(left.analysis.sentiment_label === 'negative')
      || right.linked_comment_count - left.linked_comment_count
      || right.score - left.score
    ));
}
