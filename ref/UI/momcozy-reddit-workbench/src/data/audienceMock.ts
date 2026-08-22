// 受众画像 Mock 数据
// 用于 /dashboard/analytics 页面的受众画像模块

export interface PersonaSegment {
  id: string;
  name: string;
  percentage: number;
  description: string;
  topConcerns: string[];
  activityPattern: string;
  sentiment: number;
  color: string;
  avgAge: string;
  avgPostsPerWeek: number;
}

export const personaSegments: PersonaSegment[] = [
  {
    id: '1',
    name: '新手准妈妈',
    percentage: 32,
    description: '怀孕中或产后初期，积极寻找产品和建议',
    topConcerns: ['安全性', '易用性', '价格', '品牌口碑'],
    activityPattern: '晚间活跃 (20:00-23:00)',
    sentiment: 0.68,
    color: '#C45A6C',
    avgAge: '28-32',
    avgPostsPerWeek: 4.2,
  },
  {
    id: '2',
    name: '职场背奶妈妈',
    percentage: 28,
    description: '已返回职场，需要便携、安静的解决方案',
    topConcerns: ['便携性', '静音', '续航', '隐蔽性'],
    activityPattern: '午休时间活跃 (12:00-14:00)',
    sentiment: 0.55,
    color: '#4A7FB5',
    avgAge: '30-35',
    avgPostsPerWeek: 3.8,
  },
  {
    id: '3',
    name: '经验分享者',
    percentage: 22,
    description: '有一定经验，乐于分享和推荐产品',
    topConcerns: ['性价比', '耐用性', '配件', '售后'],
    activityPattern: '周末活跃',
    sentiment: 0.72,
    color: '#2D8A5E',
    avgAge: '30-38',
    avgPostsPerWeek: 6.5,
  },
  {
    id: '4',
    name: '问题求助者',
    percentage: 12,
    description: '遇到具体问题，寻求社区帮助',
    topConcerns: ['故障解决', '使用技巧', '清洗方法', '配件更换'],
    activityPattern: '随时可能发帖求助',
    sentiment: 0.35,
    color: '#D4940A',
    avgAge: '26-34',
    avgPostsPerWeek: 2.1,
  },
  {
    id: '5',
    name: '价格敏感型',
    percentage: 6,
    description: '关注促销和性价比，预算有限',
    topConcerns: ['价格', '保险覆盖', '二手市场', '优惠活动'],
    activityPattern: '促销期间活跃',
    sentiment: 0.48,
    color: '#9A5AB5',
    avgAge: '24-30',
    avgPostsPerWeek: 1.8,
  },
];

export interface AudienceDemographics {
  momStage: { name: string; value: number; color?: string }[];
  interests: { name: string; value: number }[];
  painPoints: { name: string; value: number; sentiment: number }[];
  activityByHour: { hour: string; value: number }[];
  deviceUsage: { name: string; value: number; color?: string }[];
}

export const audienceDemographics: AudienceDemographics = {
  momStage: [
    { name: '孕期', value: 28, color: '#C45A6C' },
    { name: '产后0-3月', value: 35, color: '#4A7FB5' },
    { name: '产后3-6月', value: 22, color: '#2D8A5E' },
    { name: '产后6-12月', value: 12, color: '#D4940A' },
    { name: '1岁以上', value: 3, color: '#9A9A9A' },
  ],
  interests: [
    { name: '母婴用品', value: 92 },
    { name: '育儿知识', value: 85 },
    { name: '职场平衡', value: 68 },
    { name: '健康生活', value: 62 },
    { name: '产品评测', value: 55 },
    { name: 'DIY手工', value: 28 },
  ],
  painPoints: [
    { name: '吸力不够', value: 45, sentiment: -0.4 },
    { name: '噪音问题', value: 38, sentiment: -0.3 },
    { name: '清洗麻烦', value: 35, sentiment: -0.2 },
    { name: '续航焦虑', value: 32, sentiment: -0.35 },
    { name: '漏奶', value: 28, sentiment: -0.5 },
    { name: '配件贵', value: 25, sentiment: -0.25 },
  ],
  activityByHour: [
    { hour: '00', value: 8 },
    { hour: '02', value: 4 },
    { hour: '04', value: 3 },
    { hour: '06', value: 12 },
    { hour: '08', value: 25 },
    { hour: '10', value: 35 },
    { hour: '12', value: 48 },
    { hour: '14', value: 38 },
    { hour: '16', value: 30 },
    { hour: '18', value: 42 },
    { hour: '20', value: 58 },
    { hour: '22', value: 45 },
  ],
  deviceUsage: [
    { name: '手机', value: 68, color: '#C45A6C' },
    { name: '电脑', value: 24, color: '#4A7FB5' },
    { name: '平板', value: 8, color: '#2D8A5E' },
  ],
};

export interface AudienceRadarDimension {
  dimension: string;
  score: number;
  fullMark: number;
}

export const audienceRadarData: AudienceRadarDimension[] = [
  { dimension: '价格敏感度', score: 72, fullMark: 100 },
  { dimension: '品牌忠诚度', score: 58, fullMark: 100 },
  { dimension: '信息分享欲', score: 85, fullMark: 100 },
  { dimension: '购买决策速度', score: 45, fullMark: 100 },
  { dimension: '社区活跃度', score: 78, fullMark: 100 },
  { dimension: '专业依赖度', score: 62, fullMark: 100 },
];

export function getPersonaSegments(timeRange: '7d' | '30d' | '90d'): PersonaSegment[] {
  const shifts: Record<string, Record<string, number>> = {
    '7d': { '新手准妈妈': 32, '职场背奶妈妈': 28, '经验分享者': 22, '问题求助者': 12, '价格敏感型': 6 },
    '30d': { '新手准妈妈': 30, '职场背奶妈妈': 30, '经验分享者': 24, '问题求助者': 10, '价格敏感型': 6 },
    '90d': { '新手准妈妈': 28, '职场背奶妈妈': 32, '经验分享者': 26, '问题求助者': 9, '价格敏感型': 5 },
  };
  const map = shifts[timeRange] ?? shifts['7d'];
  return personaSegments.map((p) => ({
    ...p,
    percentage: map[p.name] ?? p.percentage,
    avgPostsPerWeek: Math.round(p.avgPostsPerWeek * (timeRange === '90d' ? 1.3 : timeRange === '30d' ? 1.15 : 1) * 10) / 10,
  }));
}

export function getAudienceDemographics(timeRange: '7d' | '30d' | '90d'): AudienceDemographics {
  const multipliers: Record<string, number> = { '7d': 1, '30d': 1.15, '90d': 1.3 };
  const m = multipliers[timeRange] ?? 1;
  return {
    momStage: audienceDemographics.momStage,
    interests: audienceDemographics.interests.map((i) => ({ ...i, value: Math.min(100, Math.round(i.value * m)) })),
    painPoints: audienceDemographics.painPoints.map((p) => ({ ...p, value: Math.round(p.value * m) })),
    activityByHour: audienceDemographics.activityByHour.map((a) => ({ ...a, value: Math.round(a.value * m) })),
    deviceUsage: audienceDemographics.deviceUsage,
  };
}
