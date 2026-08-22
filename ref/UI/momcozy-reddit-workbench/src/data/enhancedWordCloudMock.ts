// 增强词云 Mock 数据
// 用于 /dashboard/analytics 页面的增强词云模块

export type WordCloudSentiment = 'positive' | 'neutral' | 'negative';
export type WordCloudCategory = 'product' | 'brand' | 'feature' | 'emotion' | 'scenario';

export interface EnhancedWordCloudItem {
  text: string;
  value: number;
  sentiment: WordCloudSentiment;
  category: WordCloudCategory;
  /** 来源帖子 ID 列表（点击词云可追踪到具体帖子） */
  sourcePostIds: string[];
  /** 情感分析置信度 0-1 */
  sentimentConfidence: number;
}

export const enhancedWordCloudData: EnhancedWordCloudItem[] = [
  // Brand
  { text: 'Momcozy', value: 156, sentiment: 'positive', category: 'brand', sourcePostIds: ['d1', 'd2', 'd3', 'd5', 'd6'], sentimentConfidence: 0.92 },
  { text: 'Elvie', value: 76, sentiment: 'neutral', category: 'brand', sourcePostIds: ['d3', 'd5'], sentimentConfidence: 0.85 },
  { text: 'Spectra', value: 72, sentiment: 'positive', category: 'brand', sourcePostIds: ['d5'], sentimentConfidence: 0.78 },
  { text: 'Willow', value: 52, sentiment: 'neutral', category: 'brand', sourcePostIds: ['d3'], sentimentConfidence: 0.72 },
  { text: 'Medela', value: 31, sentiment: 'positive', category: 'brand', sourcePostIds: ['d4'], sentimentConfidence: 0.68 },
  { text: 'Haakaa', value: 24, sentiment: 'positive', category: 'brand', sourcePostIds: ['d2'], sentimentConfidence: 0.65 },
  // Product
  { text: 'M5', value: 68, sentiment: 'positive', category: 'product', sourcePostIds: ['d1', 'd3', 'd5', 'd6'], sentimentConfidence: 0.88 },
  { text: 'S12', value: 45, sentiment: 'positive', category: 'product', sourcePostIds: ['d2', 'd4'], sentimentConfidence: 0.76 },
  { text: 'V2', value: 32, sentiment: 'neutral', category: 'product', sourcePostIds: ['d3'], sentimentConfidence: 0.70 },
  { text: 'pump', value: 128, sentiment: 'neutral', category: 'product', sourcePostIds: ['d1', 'd2', 'd3', 'd4', 'd5', 'd6'], sentimentConfidence: 0.82 },
  { text: 'flange', value: 35, sentiment: 'neutral', category: 'product', sourcePostIds: ['d4', 'd6'], sentimentConfidence: 0.74 },
  { text: 'valve', value: 18, sentiment: 'negative', category: 'product', sourcePostIds: ['d6'], sentimentConfidence: 0.80 },
  // Feature
  { text: 'wearable', value: 98, sentiment: 'positive', category: 'feature', sourcePostIds: ['d1', 'd2'], sentimentConfidence: 0.90 },
  { text: 'quiet', value: 65, sentiment: 'positive', category: 'feature', sourcePostIds: ['d1', 'd4'], sentimentConfidence: 0.86 },
  { text: 'portable', value: 62, sentiment: 'positive', category: 'feature', sourcePostIds: ['d2', 'd5'], sentimentConfidence: 0.84 },
  { text: 'hands free', value: 45, sentiment: 'positive', category: 'feature', sourcePostIds: ['d2', 'd5'], sentimentConfidence: 0.79 },
  { text: 'suction', value: 42, sentiment: 'neutral', category: 'feature', sourcePostIds: ['d4', 'd5', 'd6'], sentimentConfidence: 0.77 },
  { text: 'battery', value: 38, sentiment: 'neutral', category: 'feature', sourcePostIds: ['d1', 'd6'], sentimentConfidence: 0.75 },
  { text: 'app', value: 28, sentiment: 'neutral', category: 'feature', sourcePostIds: ['d5'], sentimentConfidence: 0.71 },
  { text: 'LED', value: 15, sentiment: 'positive', category: 'feature', sourcePostIds: ['d2'], sentimentConfidence: 0.66 },
  // Emotion
  { text: 'comfortable', value: 58, sentiment: 'positive', category: 'emotion', sourcePostIds: ['d1', 'd2'], sentimentConfidence: 0.87 },
  { text: 'recommend', value: 87, sentiment: 'positive', category: 'emotion', sourcePostIds: ['d1', 'd2', 'd3'], sentimentConfidence: 0.91 },
  { text: 'love', value: 48, sentiment: 'positive', category: 'emotion', sourcePostIds: ['d2'], sentimentConfidence: 0.93 },
  { text: 'frustrated', value: 22, sentiment: 'negative', category: 'emotion', sourcePostIds: ['d6'], sentimentConfidence: 0.85 },
  { text: 'disappointed', value: 18, sentiment: 'negative', category: 'emotion', sourcePostIds: ['d6'], sentimentConfidence: 0.88 },
  { text: 'amazing', value: 35, sentiment: 'positive', category: 'emotion', sourcePostIds: ['d2', 'd3'], sentimentConfidence: 0.89 },
  { text: 'pain', value: 18, sentiment: 'negative', category: 'emotion', sourcePostIds: ['d4'], sentimentConfidence: 0.82 },
  { text: 'leaking', value: 15, sentiment: 'negative', category: 'emotion', sourcePostIds: ['d6'], sentimentConfidence: 0.79 },
  // Scenario
  { text: 'work', value: 55, sentiment: 'neutral', category: 'scenario', sourcePostIds: ['d1', 'd5'], sentimentConfidence: 0.83 },
  { text: 'night', value: 42, sentiment: 'neutral', category: 'scenario', sourcePostIds: ['d4'], sentimentConfidence: 0.76 },
  { text: 'travel', value: 28, sentiment: 'positive', category: 'scenario', sourcePostIds: ['d2'], sentimentConfidence: 0.73 },
  { text: 'cleaning', value: 35, sentiment: 'negative', category: 'scenario', sourcePostIds: ['d6'], sentimentConfidence: 0.81 },
  { text: 'insurance', value: 28, sentiment: 'neutral', category: 'scenario', sourcePostIds: ['d3'], sentimentConfidence: 0.69 },
  { text: 'returning', value: 22, sentiment: 'neutral', category: 'scenario', sourcePostIds: ['d3'], sentimentConfidence: 0.67 },
  { text: 'tips', value: 14, sentiment: 'positive', category: 'scenario', sourcePostIds: ['d1', 'd4'], sentimentConfidence: 0.64 },
  { text: 'FTM', value: 12, sentiment: 'neutral', category: 'scenario', sourcePostIds: ['d1'], sentimentConfidence: 0.62 },
];

export const wordCloudCategories: { key: WordCloudCategory | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'brand', label: '品牌' },
  { key: 'product', label: '产品' },
  { key: 'feature', label: '功能' },
  { key: 'emotion', label: '情感' },
  { key: 'scenario', label: '场景' },
];

export const sentimentColorMap: Record<WordCloudSentiment, string> = {
  positive: '#2D8A5E',
  neutral: '#6B6B6B',
  negative: '#C45A6C',
};

export function getEnhancedWordCloudData(timeRange: '7d' | '30d' | '90d'): EnhancedWordCloudItem[] {
  const multipliers: Record<string, number> = { '7d': 1, '30d': 3.6, '90d': 10.6 };
  const m = multipliers[timeRange] ?? 1;
  return enhancedWordCloudData.map((d) => ({
    ...d,
    value: Math.round(d.value * m),
  }));
}
