// 话题流转洞察 Mock 数据 —— 用于桑基图 + 词云 + 帖子详情联动

import type { DailyNewPost } from './dailyReportMock';

// ========== 桑基图数据：话题从社区 → 用户意图的流转 ==========
export interface TopicFlowNode {
  id: string;
  name: string;
  color?: string;
}

export interface TopicFlowLink {
  source: string;
  target: string;
  value: number;
}

export const topicFlowNodes: TopicFlowNode[] = [
  // 来源社区（左侧）
  { id: 'src_breastfeeding', name: 'r/breastfeeding', color: '#C45A6C' },
  { id: 'src_babybumps', name: 'r/babybumps', color: '#4A7FB5' },
  { id: 'src_newparents', name: 'r/NewParents', color: '#2D8A5E' },
  { id: 'src_breastpumps', name: 'r/breastpumps', color: '#D4940A' },
  { id: 'src_mommit', name: 'r/Mommit', color: '#9A5AB5' },
  // 中间阶段
  { id: 'stage_awareness', name: '认知阶段', color: '#5A9A9A' },
  { id: 'stage_consideration', name: '考虑阶段', color: '#B55A4A' },
  { id: 'stage_purchase', name: '购买阶段', color: '#8A5AC4' },
  // 意图结果（右侧）
  { id: 'intent_ugc', name: '口碑分享', color: '#2D8A5E' },
  { id: 'intent_purchase', name: '购买意向', color: '#C45A6C' },
  { id: 'intent_compare', name: '竞品对比', color: '#D4940A' },
  { id: 'intent_bug', name: 'Bug报告', color: '#6B6B6B' },
  { id: 'intent_question', name: '求助提问', color: '#4A7FB5' },
];

export const topicFlowLinks: TopicFlowLink[] = [
  // breastfeeding → 阶段
  { source: 'src_breastfeeding', target: 'stage_awareness', value: 42 },
  { source: 'src_breastfeeding', target: 'stage_consideration', value: 68 },
  { source: 'src_breastfeeding', target: 'stage_purchase', value: 35 },
  // babybumps → 阶段
  { source: 'src_babybumps', target: 'stage_awareness', value: 56 },
  { source: 'src_babybumps', target: 'stage_consideration', value: 28 },
  { source: 'src_babybumps', target: 'stage_purchase', value: 14 },
  // NewParents → 阶段
  { source: 'src_newparents', target: 'stage_awareness', value: 18 },
  { source: 'src_newparents', target: 'stage_consideration', value: 12 },
  { source: 'src_newparents', target: 'stage_purchase', value: 8 },
  // breastpumps → 阶段
  { source: 'src_breastpumps', target: 'stage_awareness', value: 10 },
  { source: 'src_breastpumps', target: 'stage_consideration', value: 22 },
  { source: 'src_breastpumps', target: 'stage_purchase', value: 15 },
  // Mommit → 阶段
  { source: 'src_mommit', target: 'stage_awareness', value: 8 },
  { source: 'src_mommit', target: 'stage_consideration', value: 6 },
  { source: 'src_mommit', target: 'stage_purchase', value: 4 },
  // 阶段 → 意图
  { source: 'stage_awareness', target: 'intent_question', value: 78 },
  { source: 'stage_awareness', target: 'intent_ugc', value: 56 },
  { source: 'stage_consideration', target: 'intent_compare', value: 62 },
  { source: 'stage_consideration', target: 'intent_purchase', value: 48 },
  { source: 'stage_consideration', target: 'intent_question', value: 26 },
  { source: 'stage_purchase', target: 'intent_purchase', value: 52 },
  { source: 'stage_purchase', target: 'intent_bug', value: 18 },
  { source: 'stage_purchase', target: 'intent_ugc', value: 16 },
];

// ========== 词云数据：话题流转中的高频关键词 ==========
export interface TopicKeyword {
  text: string;
  value: number;
  color?: string;
}

export const topicFlowKeywords: TopicKeyword[] = [
  { text: 'wearable', value: 95 },
  { text: 'quiet', value: 88 },
  { text: 'M5', value: 82 },
  { text: 'office', value: 76 },
  { text: 'Elvie', value: 72 },
  { text: 'portable', value: 68 },
  { text: 'suction', value: 64 },
  { text: 'battery', value: 60 },
  { text: 'price', value: 58 },
  { text: 'comfortable', value: 55 },
  { text: 'handsfree', value: 52 },
  { text: 'discreet', value: 48 },
  { text: 'pumping', value: 45 },
  { text: 'milk', value: 42 },
  { text: 'work', value: 40 },
  { text: 'review', value: 38 },
  { text: 'recommendation', value: 36 },
  { text: 'comparison', value: 34 },
  { text: 'warranty', value: 32 },
  { text: 'cleaning', value: 30 },
  { text: 'flange', value: 28 },
  { text: 'charging', value: 26 },
  { text: 'leak', value: 24 },
  { text: 'noise', value: 22 },
  { text: 'budget', value: 20 },
];

// ========== 关联帖子（用于 PostDetailDrawer） ==========
export const topicFlowPosts: DailyNewPost[] = [
  {
    id: 'tf1',
    redditId: 't3_tf1',
    title: 'Looking for a quiet wearable breast pump for work — any recommendations?',
    subreddit: 'breastfeeding',
    author: 'newmom2024',
    time: '2小时前',
    permalink: '/r/breastfeeding/comments/tf1/quiet_wearable_pump/',
    upvotes: 1247,
    score: 1180,
    upvoteRatio: 0.94,
    comments: 186,
    commentList: [],
    intentScore: 92,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    action: 'reply',
  },
  {
    id: 'tf2',
    redditId: 't3_tf2',
    title: 'Just got my Momcozy pump and it\'s been a game changer!',
    subreddit: 'babybumps',
    author: 'happymom_89',
    time: '6小时前',
    permalink: '/r/babybumps/comments/tf2/game_changer/',
    upvotes: 2156,
    score: 2050,
    upvoteRatio: 0.95,
    comments: 312,
    commentList: [],
    intentScore: 45,
    sentiment: 'positive',
    intent: 'UGC',
    action: 'collect',
  },
  {
    id: 'tf3',
    redditId: 't3_tf3',
    title: 'Momcozy M5 vs Elvie — which one is better for exclusive pumping?',
    subreddit: 'breastfeeding',
    author: 'pumpingmomma',
    time: '4小时前',
    permalink: '/r/breastfeeding/comments/tf3/m5_vs_elvie/',
    upvotes: 892,
    score: 850,
    upvoteRatio: 0.95,
    comments: 143,
    commentList: [],
    intentScore: 85,
    sentiment: 'neutral',
    intent: 'Comparison',
    action: 'reply',
  },
  {
    id: 'tf4',
    redditId: 't3_tf4',
    title: 'My Momcozy M5 just stopped working after 2 weeks — terrible quality',
    subreddit: 'breastfeeding',
    author: 'angrycustomer',
    time: '3小时前',
    permalink: '/r/breastfeeding/comments/tf4/stopped_working/',
    upvotes: 34,
    score: 18,
    upvoteRatio: 0.53,
    comments: 28,
    commentList: [],
    intentScore: 60,
    sentiment: 'negative',
    intent: 'Bug Report',
    action: 'escalate',
  },
  {
    id: 'tf5',
    redditId: 't3_tf5',
    title: 'How do I clean the Momcozy M5 flange properly?',
    subreddit: 'NewParents',
    author: 'cleanfreak',
    time: '8小时前',
    permalink: '/r/NewParents/comments/tf5/cleaning_flange/',
    upvotes: 156,
    score: 145,
    upvoteRatio: 0.93,
    comments: 42,
    commentList: [],
    intentScore: 72,
    sentiment: 'neutral',
    intent: 'Question',
    action: 'reply',
  },
  {
    id: 'tf6',
    redditId: 't3_tf6',
    title: 'Is the Momcozy M5 worth the price for occasional pumping?',
    subreddit: 'breastpumps',
    author: 'budgetmom',
    time: '10小时前',
    permalink: '/r/breastpumps/comments/tf6/worth_price/',
    upvotes: 321,
    score: 300,
    upvoteRatio: 0.93,
    comments: 67,
    commentList: [],
    intentScore: 80,
    sentiment: 'neutral',
    intent: 'Purchase Intent',
    action: 'reply',
  },
];

// 节点/关键词 → 帖子 ID 映射
export const nodeToPostIds: Record<string, string[]> = {
  src_breastfeeding: ['tf1', 'tf3', 'tf4'],
  src_babybumps: ['tf2'],
  src_newparents: ['tf5'],
  src_breastpumps: ['tf6'],
  src_mommit: [],
  stage_awareness: ['tf2', 'tf5'],
  stage_consideration: ['tf3', 'tf6'],
  stage_purchase: ['tf1', 'tf4'],
  intent_ugc: ['tf2'],
  intent_purchase: ['tf1', 'tf6'],
  intent_compare: ['tf3'],
  intent_bug: ['tf4'],
  intent_question: ['tf5'],
  // 关键词映射
  wearable: ['tf1', 'tf3'],
  quiet: ['tf1'],
  M5: ['tf1', 'tf3', 'tf4', 'tf6'],
  office: ['tf1'],
  Elvie: ['tf3'],
  portable: ['tf1', 'tf6'],
  suction: ['tf3'],
  battery: ['tf1'],
  price: ['tf6'],
  comfortable: ['tf2'],
  handsfree: ['tf1'],
  discreet: ['tf1'],
  pumping: ['tf3', 'tf6'],
  milk: ['tf5'],
  work: ['tf1'],
  review: ['tf6'],
  recommendation: ['tf1'],
  comparison: ['tf3'],
  warranty: ['tf4'],
  cleaning: ['tf5'],
  flange: ['tf5'],
  charging: ['tf1'],
  leak: ['tf4'],
  noise: ['tf1'],
  budget: ['tf6'],
};

// ========== 聚合接口：从真实帖子数据生成桑基图 ==========

/** 意图 → 决策阶段映射 */
const INTENT_TO_STAGE: Record<string, string> = {
  'Question': 'stage_awareness',
  'Comparison': 'stage_consideration',
  'Purchase Intent': 'stage_purchase',
  'UGC': 'stage_awareness',      // UGC 通常来自已购买用户的认知阶段
  'Bug Report': 'stage_purchase', // Bug 报告来自已购买用户
  'General': 'stage_awareness',
};

/** 意图 → 最终意图节点映射 */
const INTENT_TO_FINAL: Record<string, string> = {
  'Question': 'intent_question',
  'Comparison': 'intent_compare',
  'Purchase Intent': 'intent_purchase',
  'UGC': 'intent_ugc',
  'Bug Report': 'intent_bug',
  'General': 'intent_question',
};

/** 阶段节点配置 */
const STAGE_NODES: TopicFlowNode[] = [
  { id: 'stage_awareness', name: '认知阶段', color: '#5A9A9A' },
  { id: 'stage_consideration', name: '考虑阶段', color: '#B55A4A' },
  { id: 'stage_purchase', name: '购买阶段', color: '#8A5AC4' },
];

/** 意图节点配置 */
const INTENT_NODES: TopicFlowNode[] = [
  { id: 'intent_ugc', name: '口碑分享', color: '#2D8A5E' },
  { id: 'intent_purchase', name: '购买意向', color: '#C45A6C' },
  { id: 'intent_compare', name: '竞品对比', color: '#D4940A' },
  { id: 'intent_bug', name: 'Bug报告', color: '#6B6B6B' },
  { id: 'intent_question', name: '求助提问', color: '#4A7FB5' },
];

/** 社区颜色映射 */
const SUBREDDIT_COLORS: Record<string, string> = {
  breastfeeding: '#C45A6C',
  babybumps: '#4A7FB5',
  NewParents: '#2D8A5E',
  breastpumps: '#D4940A',
  Mommit: '#9A5AB5',
};

/**
 * 从帖子数据聚合生成话题流转桑基图数据
 * @param posts DailyNewPost 数组
 * @returns { nodes, links } 桑基图数据
 */
export function aggregateTopicFlow(posts: DailyNewPost[]): {
  nodes: TopicFlowNode[];
  links: TopicFlowLink[];
  nodeToPostIds: Record<string, string[]>;
} {
  const subredditSet = new Set<string>();
  const linkCounts = new Map<string, number>();
  const nodePostMap: Record<string, string[]> = {};

  for (const post of posts) {
    const subreddit = post.subreddit;
    const stageId = INTENT_TO_STAGE[post.intent] || 'stage_awareness';
    const finalId = INTENT_TO_FINAL[post.intent] || 'intent_question';

    subredditSet.add(subreddit);

    // 社区 → 阶段
    const link1Key = `src_${subreddit}→${stageId}`;
    linkCounts.set(link1Key, (linkCounts.get(link1Key) || 0) + 1);

    // 阶段 → 意图
    const link2Key = `${stageId}→${finalId}`;
    linkCounts.set(link2Key, (linkCounts.get(link2Key) || 0) + 1);

    // 记录帖子映射
    const srcKey = `src_${subreddit}`;
    if (!nodePostMap[srcKey]) nodePostMap[srcKey] = [];
    nodePostMap[srcKey].push(post.id);

    if (!nodePostMap[stageId]) nodePostMap[stageId] = [];
    nodePostMap[stageId].push(post.id);

    if (!nodePostMap[finalId]) nodePostMap[finalId] = [];
    nodePostMap[finalId].push(post.id);
  }

  // 构建节点列表
  const nodes: TopicFlowNode[] = [];

  // 社区层
  for (const sr of subredditSet) {
    nodes.push({
      id: `src_${sr}`,
      name: `r/${sr}`,
      color: SUBREDDIT_COLORS[sr] || '#6B6B6B',
    });
  }

  // 阶段层（只包含实际用到的）
  const usedStages = new Set<string>();
  for (const key of linkCounts.keys()) {
    const [src] = key.split('→');
    if (src.startsWith('stage_')) usedStages.add(src);
    const [, tgt] = key.split('→');
    if (tgt.startsWith('stage_')) usedStages.add(tgt);
  }
  for (const stage of STAGE_NODES) {
    if (usedStages.has(stage.id)) nodes.push(stage);
  }

  // 意图层（只包含实际用到的）
  const usedIntents = new Set<string>();
  for (const key of linkCounts.keys()) {
    const [, tgt] = key.split('→');
    if (tgt.startsWith('intent_')) usedIntents.add(tgt);
  }
  for (const intent of INTENT_NODES) {
    if (usedIntents.has(intent.id)) nodes.push(intent);
  }

  // 构建连线
  const links: TopicFlowLink[] = [];
  for (const [key, value] of linkCounts.entries()) {
    const [source, target] = key.split('→');
    links.push({ source, target, value });
  }

  return { nodes, links, nodeToPostIds: nodePostMap };
}
