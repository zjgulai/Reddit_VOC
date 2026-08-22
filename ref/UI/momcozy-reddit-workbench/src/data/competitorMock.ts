// 竞品对比 Mock 数据 — 支持动态品牌配置
// 用于 /dashboard/analytics 页面的竞品对比模块

import { DEFAULT_BRANDS, type CompetitorBrand } from '../stores/competitorStore';

export interface CompetitorMetric {
  name: string;
  mentions: number;
  sentiment: number; // -1 to 1
  shareOfVoice: number; // percentage
  trend: 'up' | 'down' | 'stable';
  topKeywords: string[];
  color: string;
  engagement: number;
  positiveMentions: number;
  negativeMentions: number;
}

export interface CompetitorDimension {
  dimension: string;
  scores: Record<string, number>; // brand name -> score
}

export interface CompetitorTrendPoint {
  date: string;
  values: Record<string, number>; // brand name -> value
}

// ========== 基准数据（按品牌名称索引）==========

const BASE_METRICS: Record<
  string,
  Omit<CompetitorMetric, 'name' | 'color'>
> = {
  Momcozy: {
    mentions: 156,
    sentiment: 0.62,
    shareOfVoice: 38.5,
    trend: 'up',
    topKeywords: ['wearable', 'quiet', 'comfortable', 'portable', 'affordable'],
    engagement: 24.3,
    positiveMentions: 98,
    negativeMentions: 18,
  },
  Elvie: {
    mentions: 89,
    sentiment: 0.48,
    shareOfVoice: 22.1,
    trend: 'stable',
    topKeywords: ['smart', 'app', 'discreet', 'expensive', 'innovative'],
    engagement: 28.7,
    positiveMentions: 48,
    negativeMentions: 22,
  },
  Spectra: {
    mentions: 76,
    sentiment: 0.71,
    shareOfVoice: 18.9,
    trend: 'up',
    topKeywords: ['hospital grade', 'powerful', 'settings', 'bulky', 'effective'],
    engagement: 19.4,
    positiveMentions: 55,
    negativeMentions: 8,
  },
  Willow: {
    mentions: 52,
    sentiment: 0.35,
    shareOfVoice: 12.9,
    trend: 'down',
    topKeywords: ['hands free', 'leak', 'pricey', 'design', 'app'],
    engagement: 22.1,
    positiveMentions: 22,
    negativeMentions: 18,
  },
  Medela: {
    mentions: 31,
    sentiment: 0.55,
    shareOfVoice: 7.6,
    trend: 'stable',
    topKeywords: ['classic', 'reliable', 'parts', 'insurance', 'brand'],
    engagement: 15.8,
    positiveMentions: 20,
    negativeMentions: 5,
  },
};

const BASE_DIMENSIONS: { dimension: string; scores: Record<string, number> }[] = [
  { dimension: '提及量', scores: { Momcozy: 82.4, Elvie: 61.3, Spectra: 53.8, Willow: 39.2, Medela: 25.7 } },
  { dimension: '正面情感', scores: { Momcozy: 77.1, Elvie: 65.8, Spectra: 86.9, Willow: 58.5, Medela: 71.3 } },
  { dimension: '互动率', scores: { Momcozy: 71.4, Elvie: 81.2, Spectra: 57.3, Willow: 65.9, Medela: 47.1 } },
  { dimension: '声量占比', scores: { Momcozy: 86.7, Elvie: 62.5, Spectra: 54.1, Willow: 41.3, Medela: 24.4 } },
  { dimension: '增长趋势', scores: { Momcozy: 90.5, Elvie: 55.8, Spectra: 72.6, Willow: 36.4, Medela: 49.3 } },
  { dimension: '性价比讨论', scores: { Momcozy: 83.9, Elvie: 46.2, Spectra: 61.7, Willow: 38.8, Medela: 56.1 } },
];

const BASE_TREND_7D: { date: string; values: Record<string, number> }[] = [
  { date: '07-04', values: { Momcozy: 18, Elvie: 12, Spectra: 10, Willow: 8, Medela: 4 } },
  { date: '07-05', values: { Momcozy: 22, Elvie: 14, Spectra: 11, Willow: 7, Medela: 5 } },
  { date: '07-06', values: { Momcozy: 20, Elvie: 11, Spectra: 12, Willow: 9, Medela: 4 } },
  { date: '07-07', values: { Momcozy: 24, Elvie: 13, Spectra: 10, Willow: 8, Medela: 3 } },
  { date: '07-08', values: { Momcozy: 26, Elvie: 12, Spectra: 13, Willow: 6, Medela: 5 } },
  { date: '07-09', values: { Momcozy: 28, Elvie: 15, Spectra: 11, Willow: 7, Medela: 4 } },
  { date: '07-10', values: { Momcozy: 18, Elvie: 12, Spectra: 9, Willow: 7, Medela: 6 } },
];

const BASE_TREND_30D: { date: string; values: Record<string, number> }[] = [
  { date: '06-11', values: { Momcozy: 14, Elvie: 10, Spectra: 8, Willow: 6, Medela: 3 } },
  { date: '06-15', values: { Momcozy: 16, Elvie: 11, Spectra: 9, Willow: 7, Medela: 4 } },
  { date: '06-19', values: { Momcozy: 18, Elvie: 12, Spectra: 10, Willow: 8, Medela: 4 } },
  { date: '06-23', values: { Momcozy: 20, Elvie: 13, Spectra: 11, Willow: 7, Medela: 5 } },
  { date: '06-27', values: { Momcozy: 22, Elvie: 14, Spectra: 12, Willow: 8, Medela: 5 } },
  { date: '07-01', values: { Momcozy: 24, Elvie: 13, Spectra: 11, Willow: 9, Medela: 4 } },
  { date: '07-05', values: { Momcozy: 22, Elvie: 14, Spectra: 10, Willow: 8, Medela: 5 } },
  { date: '07-10', values: { Momcozy: 18, Elvie: 12, Spectra: 9, Willow: 7, Medela: 6 } },
];

const BASE_TREND_90D: { date: string; values: Record<string, number> }[] = [
  { date: '04-12', values: { Momcozy: 12, Elvie: 8, Spectra: 7, Willow: 5, Medela: 3 } },
  { date: '04-19', values: { Momcozy: 14, Elvie: 9, Spectra: 8, Willow: 6, Medela: 3 } },
  { date: '04-26', values: { Momcozy: 15, Elvie: 10, Spectra: 9, Willow: 6, Medela: 4 } },
  { date: '05-03', values: { Momcozy: 16, Elvie: 11, Spectra: 9, Willow: 7, Medela: 4 } },
  { date: '05-10', values: { Momcozy: 17, Elvie: 12, Spectra: 10, Willow: 7, Medela: 4 } },
  { date: '05-17', values: { Momcozy: 18, Elvie: 12, Spectra: 11, Willow: 6, Medela: 5 } },
  { date: '05-24', values: { Momcozy: 19, Elvie: 13, Spectra: 10, Willow: 7, Medela: 4 } },
  { date: '05-31', values: { Momcozy: 20, Elvie: 13, Spectra: 11, Willow: 8, Medela: 5 } },
  { date: '06-07', values: { Momcozy: 18, Elvie: 12, Spectra: 10, Willow: 7, Medela: 4 } },
  { date: '06-14', values: { Momcozy: 19, Elvie: 13, Spectra: 11, Willow: 6, Medela: 5 } },
  { date: '06-21', values: { Momcozy: 20, Elvie: 14, Spectra: 12, Willow: 7, Medela: 5 } },
  { date: '06-28', values: { Momcozy: 21, Elvie: 13, Spectra: 11, Willow: 8, Medela: 4 } },
  { date: '07-05', values: { Momcozy: 22, Elvie: 14, Spectra: 10, Willow: 7, Medela: 5 } },
  { date: '07-10', values: { Momcozy: 18, Elvie: 12, Spectra: 9, Willow: 7, Medela: 6 } },
];

// ========== 生成辅助函数 ==========

/** 确定性伪随机数（基于字符串种子） */
function seededRandom(seed: string): number {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    const char = seed.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash = hash & hash;
  }
  const x = Math.sin(hash) * 10000;
  return x - Math.floor(x);
}

/** 为未知品牌生成合理的随机数据 */
function generateFallbackMetrics(name: string): Omit<CompetitorMetric, 'name' | 'color'> {
  const rand = (offset: string, min: number, max: number) =>
    min + seededRandom(name + offset) * (max - min);

  const mentions = Math.round(rand('m', 20, 180));
  const positiveMentions = Math.round(mentions * rand('p', 0.4, 0.85));
  const negativeMentions = mentions - positiveMentions;
  const sentiment = rand('s', -0.2, 0.9);

  const trends: Array<'up' | 'down' | 'stable'> = ['up', 'down', 'stable'];
  const trend = trends[Math.floor(rand('t', 0, 3))];

  const keywords = [
    'wearable', 'smart', 'quiet', 'comfortable', 'portable', 'affordable',
    'app', 'design', 'battery', 'easy', 'lightweight', 'powerful',
  ];
  const topKeywords = Array.from({ length: 5 }, (_, i) =>
    keywords[Math.floor(rand(`k${i}`, 0, keywords.length))]
  );

  return {
    mentions,
    sentiment: Math.round(sentiment * 100) / 100,
    shareOfVoice: Math.round(rand('v', 5, 40) * 10) / 10,
    trend,
    topKeywords: [...new Set(topKeywords)],
    engagement: Math.round(rand('e', 10, 35) * 10) / 10,
    positiveMentions: Math.max(0, positiveMentions),
    negativeMentions: Math.max(0, negativeMentions),
  };
}

/** 根据品牌配置生成竞品指标数据 */
export function generateCompetitorMetrics(brands: CompetitorBrand[]): CompetitorMetric[] {
  return brands.map((brand) => {
    const base = BASE_METRICS[brand.name] || generateFallbackMetrics(brand.name);
    return {
      ...base,
      name: brand.name,
      color: brand.color,
    };
  });
}

/** 根据品牌配置生成维度对比数据 */
export function generateCompetitorDimensions(brands: CompetitorBrand[]): CompetitorDimension[] {
  const brandNames = brands.map((b) => b.name);
  return BASE_DIMENSIONS.map((dim) => {
    const scores: Record<string, number> = {};
    brandNames.forEach((name) => {
      scores[name] = dim.scores[name] ?? Math.round(seededRandom(name + dim.dimension) * 100);
    });
    return {
      dimension: dim.dimension,
      scores,
    };
  });
}

/** 根据品牌配置生成趋势数据 */
export function generateCompetitorTrend(
  days: '7d' | '30d' | '90d',
  brands: CompetitorBrand[]
): CompetitorTrendPoint[] {
  const base = days === '7d' ? BASE_TREND_7D : days === '30d' ? BASE_TREND_30D : BASE_TREND_90D;
  const brandNames = brands.map((b) => b.name);

  return base.map((point) => {
    const values: Record<string, number> = {};
    brandNames.forEach((name) => {
      values[name] =
        point.values[name] ??
        Math.round(seededRandom(name + point.date) * 30 + 5);
    });
    return { date: point.date, values };
  });
}

// ========== 向后兼容：保留默认静态导出（基于全部默认品牌）==========

export const competitors = generateCompetitorMetrics(DEFAULT_BRANDS);
export const competitorDimensions = generateCompetitorDimensions(DEFAULT_BRANDS);
export const competitorTrend7d = generateCompetitorTrend('7d', DEFAULT_BRANDS);
export const competitorTrend30d = generateCompetitorTrend('30d', DEFAULT_BRANDS);
