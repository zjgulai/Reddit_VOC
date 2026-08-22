// 搜索配置页 Mock 数据 - 真实+虚拟混合数据集

export type KeywordType = 'brand' | 'product' | 'competitor' | 'general';
export type SubredditTier = 'A' | 'B' | 'C';

export interface KeywordRule {
  id: string;
  label: string;
  type: KeywordType;
  active: boolean;
  matchCount: number;
  createdAt: string;
}

export interface SubredditRule {
  id: string;
  name: string;
  displayName: string;
  subscribers: number;
  active: boolean;
  postCount: number;
  lastFetched: string;
  tier: SubredditTier;
}

export interface SearchConfig {
  timeRange: '7d' | '30d' | '90d' | 'custom';
  aiFilter: boolean;
  minUpvotes: number;
  autoNotify: boolean;
  keywordTypeFilter: KeywordType[];
  subredditTierFilter: SubredditTier[];
}

import type { PostIntent } from '../types';

export interface SearchPost {
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
  status: 'new' | 'replied' | 'saved';
}

export const keywordRules: KeywordRule[] = [
  { id: 'k1', label: 'Momcozy', type: 'brand', active: true, matchCount: 186, createdAt: '2026-06-01' },
  { id: 'k2', label: 'M5', type: 'product', active: true, matchCount: 89, createdAt: '2026-06-01' },
  { id: 'k3', label: 'M6', type: 'product', active: true, matchCount: 34, createdAt: '2026-06-15' },
  { id: 'k4', label: 'Elvie', type: 'competitor', active: true, matchCount: 67, createdAt: '2026-06-01' },
  { id: 'k5', label: 'Spectra', type: 'competitor', active: false, matchCount: 23, createdAt: '2026-06-10' },
  { id: 'k6', label: 'breast pump', type: 'general', active: true, matchCount: 312, createdAt: '2026-06-01' },
  { id: 'k7', label: 'wearable pump', type: 'general', active: true, matchCount: 156, createdAt: '2026-06-05' },
  { id: 'k8', label: 'Willow', type: 'competitor', active: false, matchCount: 18, createdAt: '2026-06-20' },
  { id: 'k9', label: '静音', type: 'general', active: true, matchCount: 45, createdAt: '2026-07-01' },
  { id: 'k10', label: '便携', type: 'general', active: true, matchCount: 78, createdAt: '2026-07-01' },
];

function generateLastFetched(): string {
  const mins = Math.floor(Math.random() * 45) + 1;
  return `${mins} 分钟前`;
}

export const subredditRules: SubredditRule[] = [
  { id: 's1', name: 'breastfeeding', displayName: 'r/breastfeeding', subscribers: 185000, active: true, postCount: 142, lastFetched: generateLastFetched(), tier: 'A' },
  { id: 's2', name: 'babybumps', displayName: 'r/babybumps', subscribers: 720000, active: true, postCount: 78, lastFetched: generateLastFetched(), tier: 'A' },
  { id: 's3', name: 'NewParents', displayName: 'r/NewParents', subscribers: 145000, active: true, postCount: 65, lastFetched: generateLastFetched(), tier: 'B' },
  { id: 's4', name: 'Mommit', displayName: 'r/Mommit', subscribers: 210000, active: false, postCount: 33, lastFetched: '1 小时前', tier: 'B' },
  { id: 's5', name: 'breastpumps', displayName: 'r/breastpumps', subscribers: 8500, active: true, postCount: 30, lastFetched: generateLastFetched(), tier: 'A' },
  { id: 's6', name: 'pregnant', displayName: 'r/pregnant', subscribers: 420000, active: false, postCount: 0, lastFetched: '3 天前', tier: 'C' },
];

export const searchConfig: SearchConfig = {
  timeRange: '30d',
  aiFilter: true,
  minUpvotes: 5,
  autoNotify: true,
  keywordTypeFilter: ['brand', 'product', 'competitor', 'general'],
  subredditTierFilter: ['A', 'B', 'C'],
};

export const searchPosts: SearchPost[] = [
  { id: 'c5', title: 'Haakaa vs electric pump for early morning sessions', subreddit: 'breastfeeding', author: 'earlybird', time: '5小时前', upvotes: 30, comments: 10, intentScore: 70, sentiment: 'neutral', intent: 'Comparison', action: 'reply', status: 'saved' },
  { id: 'r14', title: 'About to give up breast feeding my 6 month old because of biting…', subreddit: 'babybumps', author: 'user_4851', time: '12小时前', upvotes: 35, comments: 7, intentScore: 69, sentiment: 'positive', intent: 'UGC', action: 'reply', status: 'saved' },
  { id: 'm2', title: 'Just got my Momcozy M6! First impressions', subreddit: 'babybumps', author: 'newmom_sarah', time: '5小时前', upvotes: 149, comments: 59, intentScore: 86, sentiment: 'positive', intent: 'UGC', action: 'collect', status: 'replied' },
  { id: 'r11', title: 'I thought I was going to last a lot longer', subreddit: 'NewParents', author: 'user_8096', time: '2天前', upvotes: 22, comments: 14, intentScore: 43, sentiment: 'positive', intent: 'General', action: 'monitor', status: 'replied' },
  { id: 'r9', title: 'OUCH!!!', subreddit: 'NewParents', author: 'user_4364', time: '2天前', upvotes: 17, comments: 15, intentScore: 60, sentiment: 'negative', intent: 'General', action: 'escalate', status: 'saved' },
  { id: 'm7', title: 'Momcozy customer service refused my warranty claim', subreddit: 'Mommit', author: 'angry_customer', time: '2天前', upvotes: 64, comments: 69, intentScore: 67, sentiment: 'negative', intent: 'Bug Report', action: 'escalate', status: 'saved' },
  { id: 'm14', title: 'Momcozy M5 stopped working after 4 months', subreddit: 'breastfeeding', author: 'broken_pump', time: '1天前', upvotes: 67, comments: 49, intentScore: 60, sentiment: 'negative', intent: 'Bug Report', action: 'escalate', status: 'replied' },
  { id: 'r8', title: 'Chest pain PLEASE HELP', subreddit: 'breastfeeding', author: 'user_2443', time: '2小时前', upvotes: 19, comments: 5, intentScore: 70, sentiment: 'negative', intent: 'General', action: 'escalate', status: 'new' },
  { id: 'r4', title: 'Long night stretches and milk supply', subreddit: 'babybumps', author: 'turbulent_waterss', time: '1天前', upvotes: 12, comments: 7, intentScore: 49, sentiment: 'neutral', intent: 'General', action: 'collect', status: 'new' },
  { id: 'm5', title: 'Momcozy M5 battery life - real world usage', subreddit: 'breastpumps', author: 'workingmom_lisa', time: '2小时前', upvotes: 152, comments: 29, intentScore: 83, sentiment: 'positive', intent: 'UGC', action: 'collect', status: 'new' },
  { id: 'r2', title: 'Exclusively pumping', subreddit: 'Mommit', author: 'Aggressive-Range-706', time: '3小时前', upvotes: 14, comments: 14, intentScore: 64, sentiment: 'neutral', intent: 'Question', action: 'reply', status: 'saved' },
  { id: 'm15', title: 'Best pump for oversupply? Considering Momcozy', subreddit: 'breastfeeding', author: 'oversupply_mom', time: '15分钟前', upvotes: 42, comments: 6, intentScore: 60, sentiment: 'neutral', intent: 'Question', action: 'monitor', status: 'new' },
  { id: 'r5', title: 'Joint pain unlike anything I\'ve experienced before??!!', subreddit: 'Mommit', author: 'Historical-Young-464', time: '15分钟前', upvotes: 6, comments: 0, intentScore: 71, sentiment: 'positive', intent: 'General', action: 'monitor', status: 'new' },
  { id: 'r15', title: '10.5 mo old still wants dream feed help', subreddit: 'Mommit', author: 'user_1449', time: '5小时前', upvotes: 35, comments: 2, intentScore: 63, sentiment: 'positive', intent: 'General', action: 'escalate', status: 'new' },
  { id: 'c4', title: 'Medela Freestyle Flex leaking from flange', subreddit: 'breastpumps', author: 'medela_user', time: '2小时前', upvotes: 30, comments: 12, intentScore: 58, sentiment: 'negative', intent: 'Bug Report', action: 'escalate', status: 'new' },
  { id: 'm6', title: 'Medela vs Momcozy M5 suction strength comparison', subreddit: 'breastfeeding', author: 'sciencemom', time: '5小时前', upvotes: 15, comments: 7, intentScore: 73, sentiment: 'neutral', intent: 'Comparison', action: 'monitor', status: 'replied' },
  { id: 'r10', title: 'Normal? Or not?', subreddit: 'babybumps', author: 'user_3556', time: '30分钟前', upvotes: 37, comments: 3, intentScore: 68, sentiment: 'positive', intent: 'General', action: 'monitor', status: 'saved' },
  { id: 'm4', title: 'Is Momcozy worth it for exclusive pumping?', subreddit: 'ExclusivelyPumping', author: 'EP_journey', time: '30分钟前', upvotes: 88, comments: 20, intentScore: 76, sentiment: 'neutral', intent: 'Purchase Intent', action: 'reply', status: 'new' },
  { id: 'r7', title: 'Breastfeeding and pierced nipples worries', subreddit: 'Mommit', author: 'user_3414', time: '12小时前', upvotes: 46, comments: 15, intentScore: 51, sentiment: 'neutral', intent: 'Question', action: 'monitor', status: 'new' },
  { id: 'c3', title: 'Willow Go vs Elvie Stride for working moms', subreddit: 'Mommit', author: 'working_pumper', time: '3小时前', upvotes: 24, comments: 18, intentScore: 61, sentiment: 'neutral', intent: 'Comparison', action: 'monitor', status: 'replied' },
  { id: 'm8', title: 'Traveling with Momcozy M5 - TSA experience', subreddit: 'NewParents', author: 'travelmom_jen', time: '2天前', upvotes: 115, comments: 65, intentScore: 90, sentiment: 'positive', intent: 'UGC', action: 'collect', status: 'replied' },
  { id: 'r6', title: 'Should I stop Slinda (Drospirenone)? Period and supply/letdown issues', subreddit: 'babybumps', author: 'user_8707', time: '2小时前', upvotes: 6, comments: 13, intentScore: 43, sentiment: 'negative', intent: 'General', action: 'escalate', status: 'new' },
  { id: 'r1', title: 'new to breastfeeding', subreddit: 'Mommit', author: 'garfiez', time: '2小时前', upvotes: 18, comments: 6, intentScore: 49, sentiment: 'neutral', intent: 'General', action: 'reply', status: 'replied' },
  { id: 'c1', title: 'Elvie Pump review: Love the freedom but pricey', subreddit: 'breastpumps', author: 'elvie_fan', time: '5小时前', upvotes: 22, comments: 31, intentScore: 67, sentiment: 'positive', intent: 'UGC', action: 'escalate', status: 'replied' },
  { id: 'm3', title: 'Momcozy M5 leaking issue - anyone else?', subreddit: 'breastfeeding', author: 'frustrated_pumper', time: '3小时前', upvotes: 44, comments: 51, intentScore: 68, sentiment: 'negative', intent: 'Bug Report', action: 'escalate', status: 'saved' },
  { id: 'r13', title: 'Nursing bras and dresses', subreddit: 'Mommit', author: 'user_1306', time: '3小时前', upvotes: 36, comments: 13, intentScore: 56, sentiment: 'neutral', intent: 'General', action: 'escalate', status: 'replied' },
  { id: 'm10', title: 'Momcozy M5 flanges sizing guide I wish I had known', subreddit: 'breastfeeding', author: 'size_matters', time: '30分钟前', upvotes: 119, comments: 78, intentScore: 75, sentiment: 'positive', intent: 'UGC', action: 'collect', status: 'new' },
  { id: 'r3', title: 'Milk supply reduced or not ?', subreddit: 'NewParents', author: 'HakunaMatata-03', time: '2小时前', upvotes: 1, comments: 1, intentScore: 73, sentiment: 'neutral', intent: 'General', action: 'collect', status: 'replied' },
  { id: 'm11', title: 'Returning my Willow - switching to Momcozy', subreddit: 'babybumps', author: 'willow_dropout', time: '12小时前', upvotes: 254, comments: 49, intentScore: 88, sentiment: 'positive', intent: 'Purchase Intent', action: 'reply', status: 'saved' },
  { id: 'm1', title: 'Momcozy M5 vs Elvie Stride: 30-day honest comparison', subreddit: 'breastpumps', author: 'pumpingmama2024', time: '12小时前', upvotes: 92, comments: 68, intentScore: 70, sentiment: 'neutral', intent: 'Comparison', action: 'monitor', status: 'new' },
  { id: 'm13', title: 'Lansinoh vs Momcozy - which has better suction?', subreddit: 'breastpumps', author: 'comparison_queen', time: '2天前', upvotes: 13, comments: 52, intentScore: 73, sentiment: 'neutral', intent: 'Comparison', action: 'monitor', status: 'replied' },
  { id: 'm12', title: 'Momcozy M6 noise level at work - too loud?', subreddit: 'Mommit', author: 'officeworker_mom', time: '2天前', upvotes: 9, comments: 60, intentScore: 55, sentiment: 'neutral', intent: 'Question', action: 'monitor', status: 'saved' },
  { id: 'm9', title: 'Spectra S1 or Momcozy M6? Help me choose', subreddit: 'breastpumps', author: 'decision_fatigue', time: '3小时前', upvotes: 92, comments: 13, intentScore: 80, sentiment: 'neutral', intent: 'Comparison', action: 'monitor', status: 'new' },
  { id: 'r12', title: 'Painful breast tissue', subreddit: 'NewParents', author: 'user_1751', time: '2天前', upvotes: 23, comments: 5, intentScore: 67, sentiment: 'positive', intent: 'UGC', action: 'monitor', status: 'saved' },
  { id: 'c2', title: 'Spectra S2 settings for maximum output?', subreddit: 'breastfeeding', author: 'spectra_user', time: '2天前', upvotes: 109, comments: 8, intentScore: 51, sentiment: 'neutral', intent: 'Question', action: 'collect', status: 'replied' }
];

export const typeConfig: Record<KeywordType, { label: string; color: string; bg: string; border: string }> = {
  brand: { label: '品牌词', color: 'text-primary', bg: 'bg-primary-light', border: 'border-primary' },
  product: { label: '产品词', color: 'text-status-info', bg: 'bg-status-infoBg', border: 'border-status-info' },
  competitor: { label: '竞品词', color: 'text-status-error', bg: 'bg-status-errorBg', border: 'border-status-error' },
  general: { label: '通用词', color: 'text-foreground-muted', bg: 'bg-surface-tertiary', border: 'border-border' },
};

export const tierConfig: Record<SubredditTier, { label: string; color: string; bg: string; border: string }> = {
  A: { label: 'A类', color: 'text-status-success', bg: 'bg-status-successBg', border: 'border-status-success' },
  B: { label: 'B类', color: 'text-status-info', bg: 'bg-status-infoBg', border: 'border-status-info' },
  C: { label: 'C类', color: 'text-foreground-muted', bg: 'bg-surface-tertiary', border: 'border-foreground-muted' },
};