// 影响者识别 Mock 数据
// 用于 /dashboard/analytics 页面的影响者识别模块

export interface InfluencerData {
  id: string;
  username: string;
  displayName: string;
  postCount: number;
  totalEngagement: number;
  avgSentiment: number; // -1 to 1
  topSubreddits: string[];
  influenceScore: number; // 0-100
  trend: 'up' | 'down' | 'stable';
  isVerified: boolean;
  avatar?: string;
  topTopics: string[];
  followerEstimate: number;
  lastActive: string;
}

export const influencers: InfluencerData[] = [
  {
    id: '1',
    username: 'NewMom_Jessica',
    displayName: 'Jessica L.',
    postCount: 42,
    totalEngagement: 3840,
    avgSentiment: 0.72,
    topSubreddits: ['breastfeeding', 'NewParents', 'babybumps'],
    influenceScore: 94,
    trend: 'up',
    isVerified: true,
    topTopics: ['产品推荐', '使用体验', '新手妈妈'],
    followerEstimate: 12500,
    lastActive: '2 小时前',
  },
  {
    id: '2',
    username: 'WorkingMom_Amy',
    displayName: 'Amy Chen',
    postCount: 38,
    totalEngagement: 3120,
    avgSentiment: 0.65,
    topSubreddits: ['breastfeeding', 'Mommit', 'workingmoms'],
    influenceScore: 88,
    trend: 'up',
    isVerified: true,
    topTopics: ['背奶经验', '职场妈妈', '产品对比'],
    followerEstimate: 9800,
    lastActive: '5 小时前',
  },
  {
    id: '3',
    username: 'LactationConsultant_Mary',
    displayName: 'Dr. Mary Johnson',
    postCount: 56,
    totalEngagement: 4560,
    avgSentiment: 0.81,
    topSubreddits: ['breastfeeding', 'NewParents', 'breastpumps'],
    influenceScore: 96,
    trend: 'stable',
    isVerified: true,
    topTopics: ['专业建议', '医学科普', '产品评测'],
    followerEstimate: 22000,
    lastActive: '1 小时前',
  },
  {
    id: '4',
    username: 'PumpReview_Guru',
    displayName: 'Pump Review Guru',
    postCount: 28,
    totalEngagement: 2150,
    avgSentiment: 0.45,
    topSubreddits: ['breastpumps', 'breastfeeding', 'babybumps'],
    influenceScore: 76,
    trend: 'stable',
    isVerified: false,
    topTopics: ['产品评测', '对比分析', '选购指南'],
    followerEstimate: 5600,
    lastActive: '1 天前',
  },
  {
    id: '5',
    username: 'FTM_Sarah2024',
    displayName: 'Sarah (FTM)',
    postCount: 35,
    totalEngagement: 1890,
    avgSentiment: 0.58,
    topSubreddits: ['babybumps', 'NewParents', 'Mommit'],
    influenceScore: 71,
    trend: 'up',
    isVerified: false,
    topTopics: ['新手体验', '待产准备', '真实分享'],
    followerEstimate: 3200,
    lastActive: '3 小时前',
  },
  {
    id: '6',
    username: 'BreastfeedingAdvocate',
    displayName: 'BF Advocate',
    postCount: 48,
    totalEngagement: 2780,
    avgSentiment: 0.69,
    topSubreddits: ['breastfeeding', 'Mommit', 'NewParents'],
    influenceScore: 82,
    trend: 'up',
    isVerified: false,
    topTopics: ['母乳喂养', '倡导分享', '社区互助'],
    followerEstimate: 7400,
    lastActive: '6 小时前',
  },
];

export interface InfluencerSegment {
  name: string;
  count: number;
  avgInfluenceScore: number;
  description: string;
}

export const influencerSegments: InfluencerSegment[] = [
  { name: '专家型', count: 2, avgInfluenceScore: 92, description: '专业人士，内容权威性高' },
  { name: '经验型', count: 3, avgInfluenceScore: 84, description: '真实用户，分享体验为主' },
  { name: '评测型', count: 1, avgInfluenceScore: 76, description: '专注产品评测与对比' },
];

export function getInfluencers(timeRange: '7d' | '30d' | '90d'): InfluencerData[] {
  const multipliers: Record<string, number> = { '7d': 1, '30d': 3.6, '90d': 10.6 };
  const m = multipliers[timeRange] ?? 1;
  return influencers.map((inf) => ({
    ...inf,
    postCount: Math.round(inf.postCount * m),
    totalEngagement: Math.round(inf.totalEngagement * m),
    followerEstimate: Math.round(inf.followerEstimate * (timeRange === '90d' ? 1.5 : timeRange === '30d' ? 1.2 : 1)),
  }));
}

export function getInfluencerSegments(timeRange: '7d' | '30d' | '90d'): InfluencerSegment[] {
  const multipliers: Record<string, number> = { '7d': 1, '30d': 3.6, '90d': 10.6 };
  const m = multipliers[timeRange] ?? 1;
  return influencerSegments.map((seg) => ({
    ...seg,
    count: Math.round(seg.count * m),
    avgInfluenceScore: Math.round(seg.avgInfluenceScore * (timeRange === '90d' ? 1.15 : timeRange === '30d' ? 1.05 : 1)),
  }));
}
