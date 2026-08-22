// 洞察页 Mock 数据 —— 四维度：运营洞察、舆情洞察、品牌洞察、品类洞察

export type InsightStatus = 'new' | 'reviewing' | 'accepted' | 'dismissed';
export type ExecutionStatus = 'pending' | 'executing' | 'completed';

// ========== 运营洞察 ==========

export interface OperationInsight {
  id: string;
  title: string;
  value: number;
  target: number;
  unit: string;
  trend: 'up' | 'down' | 'stable';
  change: number;
}

export interface TeamWorkload {
  member: string;
  tasksAssigned: number;
  tasksCompleted: number;
  avgResponseTime: number; // 分钟
  efficiency: number; // 0-100
}

export interface BestPractice {
  id: string;
  title: string;
  description: string;
  impact: 'high' | 'medium' | 'low';
  appliedCount: number;
}

export const operationInsights: OperationInsight[] = [
  { id: 'op1', title: '平均响应速度', value: 42, target: 30, unit: '分钟', trend: 'down', change: -12 },
  { id: 'op2', title: '待办处理率', value: 78, target: 85, unit: '%', trend: 'up', change: 5 },
  { id: 'op3', title: '紧急事项处理率', value: 92, target: 90, unit: '%', trend: 'up', change: 3 },
  { id: 'op4', title: 'UGC素材收集', value: 18, target: 15, unit: '条/周', trend: 'up', change: 20 },
  { id: 'op5', title: '团队工作饱和度', value: 82, target: 80, unit: '%', trend: 'stable', change: 0 },
];

export const teamWorkloads: TeamWorkload[] = [
  { member: '运营A', tasksAssigned: 24, tasksCompleted: 20, avgResponseTime: 38, efficiency: 88 },
  { member: '运营B', tasksAssigned: 28, tasksCompleted: 22, avgResponseTime: 45, efficiency: 82 },
  { member: '运营C', tasksAssigned: 20, tasksCompleted: 18, avgResponseTime: 35, efficiency: 90 },
  { member: '运营D', tasksAssigned: 18, tasksCompleted: 14, avgResponseTime: 52, efficiency: 75 },
];

export const bestPractices: BestPractice[] = [
  { id: 'bp1', title: '黄金1小时响应机制', description: '负面帖子在1小时内响应，可将情感恶化率降低60%', impact: 'high', appliedCount: 45 },
  { id: 'bp2', title: 'UGC素材标准化收集', description: '建立UGC收集模板和授权流程，提升素材复用率', impact: 'medium', appliedCount: 32 },
  { id: 'bp3', title: '竞品对比帖介入SOP', description: '专业参数对比+真实用户证言，建立专家形象', impact: 'high', appliedCount: 28 },
  { id: 'bp4', title: '社区活跃时段发帖', description: '在目标社区活跃高峰时段发布内容，提升曝光率', impact: 'medium', appliedCount: 38 },
];

// ========== 舆情洞察 ==========

export interface SentimentInsight {
  id: string;
  date: string;
  positive: number;
  negative: number;
  neutral: number;
  alertCount: number;
}

export interface WarningHistory {
  id: string;
  title: string;
  level: 'critical' | 'warning' | 'info';
  date: string;
  status: 'resolved' | 'pending' | 'escalated';
  responseTime: string;
}

export interface NegativeSpread {
  source: string;
  spreadPath: string[];
  affectedPosts: number;
  containmentTime: string;
}

export interface CrisisReview {
  id: string;
  title: string;
  date: string;
  severity: 'high' | 'medium' | 'low';
  responseTime: string;
  resolution: string;
  lesson: string;
}

export const sentimentTrendHistory: SentimentInsight[] = [
  { id: 's1', date: '7.6', positive: 52, negative: 12, neutral: 36, alertCount: 1 },
  { id: 's2', date: '7.7', positive: 54, negative: 15, neutral: 31, alertCount: 2 },
  { id: 's3', date: '7.8', positive: 56, negative: 14, neutral: 30, alertCount: 1 },
  { id: 's4', date: '7.9', positive: 51, negative: 16, neutral: 33, alertCount: 3 },
  { id: 's5', date: '7.10', positive: 55, negative: 13, neutral: 32, alertCount: 1 },
  { id: 's6', date: '7.11', positive: 58, negative: 11, neutral: 31, alertCount: 0 },
  { id: 's7', date: '7.12', positive: 53, negative: 14, neutral: 33, alertCount: 2 },
];

export const warningHistory: WarningHistory[] = [
  { id: 'w1', title: 'M5故障投诉集中爆发', level: 'critical', date: '7月9日', status: 'resolved', responseTime: '45分钟' },
  { id: 'w2', title: '竞品Elvie静音话题上升', level: 'warning', date: '7月8日', status: 'pending', responseTime: '2小时' },
  { id: 'w3', title: 'r/breastpumps负面率上升', level: 'warning', date: '7月7日', status: 'resolved', responseTime: '1.5小时' },
  { id: 'w4', title: '吸力不足讨论增多', level: 'info', date: '7月10日', status: 'escalated', responseTime: '4小时' },
];

export const negativeSpreads: NegativeSpread[] = [
  { source: 'breastfeeding故障帖', spreadPath: ['breastfeeding', 'babybumps', 'Mommit'], affectedPosts: 5, containmentTime: '6小时' },
  { source: 'Elvie对比帖', spreadPath: ['breastfeeding', 'breastpumps'], affectedPosts: 3, containmentTime: '12小时' },
];

export const crisisReviews: CrisisReview[] = [
  { id: 'c1', title: 'M5故障投诉集中爆发复盘', date: '7月9日', severity: 'high', responseTime: '45分钟', resolution: '客服团队介入，优先处理退货和换货', lesson: '建立品控问题快速响应通道，30分钟内必须响应' },
];

// ========== 品牌洞察 ==========

export interface BrandVoiceInsight {
  dimension: string;
  momcozy: number;
  elvie: number;
  spectra: number;
  medela: number;
}

export interface BrandPositioning {
  attribute: string;
  momcozy: number;
  elvie: number;
  spectra: number;
}

export interface MindShareTrend {
  date: string;
  momcozy: number;
  elvie: number;
  spectra: number;
}

export const brandVoiceInsights: BrandVoiceInsight[] = [
  { dimension: '性价比', momcozy: 85, elvie: 45, spectra: 62, medela: 58 },
  { dimension: '静音设计', momcozy: 68, elvie: 88, spectra: 55, medela: 50 },
  { dimension: '便携性', momcozy: 72, elvie: 78, spectra: 48, medela: 52 },
  { dimension: '吸力', momcozy: 65, elvie: 70, spectra: 82, medela: 75 },
  { dimension: '品牌信任', momcozy: 58, elvie: 72, spectra: 68, medela: 82 },
  { dimension: '售后服务', momcozy: 70, elvie: 75, spectra: 70, medela: 80 },
];

export const brandPositioning: BrandPositioning[] = [
  { attribute: '价格亲民', momcozy: 92, elvie: 35, spectra: 55 },
  { attribute: '技术创新', momcozy: 70, elvie: 88, spectra: 65 },
  { attribute: '用户口碑', momcozy: 82, elvie: 78, spectra: 72 },
  { attribute: '售后服务', momcozy: 68, elvie: 75, spectra: 70 },
];

export const mindShareTrends: MindShareTrend[] = [
  { date: '2月', momcozy: 28, elvie: 32, spectra: 18 },
  { date: '3月', momcozy: 30, elvie: 31, spectra: 17 },
  { date: '4月', momcozy: 32, elvie: 30, spectra: 18 },
  { date: '5月', momcozy: 33, elvie: 31, spectra: 16 },
  { date: '6月', momcozy: 34, elvie: 32, spectra: 16 },
  { date: '7月', momcozy: 35, elvie: 28, spectra: 15 },
];

// ========== 品类洞察 ==========

export interface ProductOpportunity {
  id: string;
  title: string;
  description: string;
  demandScore: number; // 0-100
  competitionScore: number; // 0-100
  potentialROI: number;
}

export interface UserPainPoint {
  id: string;
  painPoint: string;
  frequency: number;
  severity: number;
  productCategory: string;
}

export interface ProductFeedback {
  id: string;
  product: string;
  feedback: string;
  sentiment: 'positive' | 'neutral' | 'negative';
  source: string;
  upvotes: number;
}

export interface MarketGap {
  id: string;
  gap: string;
  demandEvidence: string;
  competitiveDensity: 'low' | 'medium' | 'high';
  estimatedMarketSize: string;
}

export const productOpportunities: ProductOpportunity[] = [
  { id: 'po1', title: '智能温感吸奶器', description: '用户在Reddit多次提到「不知道奶温是否合适」，智能温感功能可满足该需求', demandScore: 78, competitionScore: 35, potentialROI: 4.2 },
  { id: 'po2', title: '超静音便携款', description: '职场妈妈对「办公室隐蔽使用」需求强烈，现有产品静音指标不足', demandScore: 88, competitionScore: 55, potentialROI: 3.8 },
  { id: 'po3', title: '大容量背奶包', description: '长途通勤妈妈需要更大容量、更长保温时间的背奶包', demandScore: 65, competitionScore: 40, potentialROI: 3.2 },
  { id: 'po4', title: '可拆洗一体式内衣', description: '用户反馈哺乳内衣清洗麻烦，可拆洗设计可提升复购率', demandScore: 72, competitionScore: 45, potentialROI: 3.5 },
];

export const userPainPoints: UserPainPoint[] = [
  { id: 'up1', painPoint: '吸奶器噪音大', frequency: 45, severity: 7, productCategory: '吸奶器' },
  { id: 'up2', painPoint: '背奶包保温时间短', frequency: 32, severity: 6, productCategory: '背奶包' },
  { id: 'up3', painPoint: '哺乳内衣承托力不足', frequency: 28, severity: 5, productCategory: '哺乳内衣' },
  { id: 'up4', painPoint: '储奶袋密封性差', frequency: 22, severity: 6, productCategory: '储奶袋' },
  { id: 'up5', painPoint: '吸奶器配件难买', frequency: 38, severity: 7, productCategory: '吸奶器' },
];

export const productFeedbacks: ProductFeedback[] = [
  { id: 'pf1', product: 'M5吸奶器', feedback: '吸力足够，但噪音在办公室还是能被听到', sentiment: 'neutral', source: 'r/breastfeeding', upvotes: 156 },
  { id: 'pf2', product: 'M5吸奶器', feedback: '用了3个月，电池续航依然很好，推荐', sentiment: 'positive', source: 'r/babybumps', upvotes: 234 },
  { id: 'pf3', product: '背奶包', feedback: '夏天保温时间只有4小时，不够一天通勤', sentiment: 'negative', source: 'r/breastfeeding', upvotes: 89 },
  { id: 'pf4', product: '哺乳内衣', feedback: '舒适度很好，但承托力对大胸妈妈不够', sentiment: 'neutral', source: 'r/babybumps', upvotes: 112 },
];

export const marketGaps: MarketGap[] = [
  { id: 'mg1', gap: '智能IoT吸奶器', demandEvidence: '用户多次询问「能否连接App查看数据」', competitiveDensity: 'low', estimatedMarketSize: '$50M' },
  { id: 'mg2', gap: '环保可降解储奶袋', demandEvidence: '环保意识强的妈妈群体增长', competitiveDensity: 'low', estimatedMarketSize: '$20M' },
  { id: 'mg3', gap: '男士育儿包（Dadchelor包）', demandEvidence: '爸爸参与育儿比例上升，男性背奶需求被忽视', competitiveDensity: 'low', estimatedMarketSize: '$15M' },
];

// ========== 策略相关（供 StrategyPanel 使用） ==========

export interface StrategyItem {
  id: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  category: 'content' | 'community' | 'timing' | 'product';
  executionStatus: ExecutionStatus;
}

export const strategyItems: StrategyItem[] = [
  {
    id: 's1',
    title: '强化「静音办公场景」内容输出',
    description: '基于热帖分析，职场背奶是核心痛点。制作系列内容：办公室使用技巧、背奶包搭配、同事不发现的秘诀等',
    priority: 'high',
    category: 'content',
    executionStatus: 'pending',
  },
  {
    id: 's2',
    title: '主动介入竞品对比帖',
    description: 'M5 vs Elvie 等对比帖中，官方以专业视角提供客观参数对比，建立「行业专家」形象而非「推销员」形象',
    priority: 'high',
    category: 'community',
    executionStatus: 'executing',
  },
];

export interface BestTiming {
  day: string;
  score: number;
  time: string;
}

export interface RecommendedSubreddit {
  name: string;
  priority: 'P0' | 'P1' | 'P2';
  reason: string;
}

export const bestTiming = {
  weekdays: [
    { day: '周一', score: 65, time: '21:00-23:00' },
    { day: '周二', score: 92, time: '21:00-23:00' },
    { day: '周三', score: 78, time: '20:00-22:00' },
    { day: '周四', score: 88, time: '21:00-23:00' },
    { day: '周五', score: 72, time: '19:00-21:00' },
    { day: '周六', score: 55, time: '14:00-16:00' },
    { day: '周日', score: 60, time: '15:00-17:00' },
  ] as BestTiming[],
  recommendedSubreddits: [
    { name: 'breastfeeding', priority: 'P0', reason: '核心目标社区，高活跃度' },
    { name: 'babybumps', priority: 'P0', reason: '新手妈妈聚集，转化潜力高' },
    { name: 'NewParents', priority: 'P1', reason: '新手父母社区，内容教育机会' },
    { name: 'breastpumps', priority: 'P1', reason: '垂直品类社区，专业用户' },
    { name: 'Mommit', priority: 'P2', reason: '妈妈经验分享社区' },
  ] as RecommendedSubreddit[],
};

export interface TimelineItem {
  week: string;
  title: string;
  tasks: string[];
  goal: string;
}

export const timeline: TimelineItem[] = [
  {
    week: '第1周',
    title: '内容优化与发布',
    tasks: ['制作3篇「静音办公」主题内容', '在r/breastfeeding发布选泵指南', '收集UGC素材10条'],
    goal: '提升品牌正面提及率5%',
  },
  {
    week: '第2周',
    title: '社区互动与口碑',
    tasks: ['回复所有高意向帖子', '参与竞品对比讨论', '收集用户反馈并整理'],
    goal: '高意向转化率提升8%',
  },
  {
    week: '第3周',
    title: '危机监控与响应',
    tasks: ['建立负面预警机制', '优化客服响应SOP', '制作危机处理手册'],
    goal: '负面响应时间压缩至2小时',
  },
  {
    week: '第4周',
    title: '数据复盘与迭代',
    tasks: ['分析本月数据趋势', '优化内容策略', '制定下月计划'],
    goal: '整体运营效率提升10%',
  },
];

// ========== 桑基图数据：情感 → 意图 → 社区流向 ==========

export interface SentimentSankeyNode {
  id: string;
  name: string;
  color?: string;
}

export interface SentimentSankeyLink {
  source: string;
  target: string;
  value: number;
}

export const sentimentSankeyNodes: SentimentSankeyNode[] = [
  { id: 'positive', name: '正面情感', color: '#4CAF50' },
  { id: 'negative', name: '负面情感', color: '#E85D4E' },
  { id: 'neutral', name: '中性情感', color: '#FFB74D' },
  { id: 'purchase', name: '购买意向', color: '#2196F3' },
  { id: 'seek', name: '信息搜寻', color: '#9C27B0' },
  { id: 'complaint', name: '投诉反馈', color: '#F44336' },
  { id: 'review', name: '产品评价', color: '#00BCD4' },
  { id: 'breastfeeding', name: 'r/breastfeeding', color: '#FF9800' },
  { id: 'babybumps', name: 'r/babybumps', color: '#8BC34A' },
  { id: 'breastpumps', name: 'r/breastpumps', color: '#03A9F4' },
  { id: 'Mommit', name: 'r/Mommit', color: '#E91E63' },
];

export const sentimentSankeyLinks: SentimentSankeyLink[] = [
  // 正面 → 意图
  { source: 'positive', target: 'purchase', value: 45 },
  { source: 'positive', target: 'review', value: 38 },
  { source: 'positive', target: 'seek', value: 22 },
  // 负面 → 意图
  { source: 'negative', target: 'complaint', value: 35 },
  { source: 'negative', target: 'seek', value: 18 },
  { source: 'negative', target: 'review', value: 12 },
  // 中性 → 意图
  { source: 'neutral', target: 'seek', value: 55 },
  { source: 'neutral', target: 'purchase', value: 15 },
  { source: 'neutral', target: 'review', value: 20 },
  // 购买意向 → 社区
  { source: 'purchase', target: 'breastfeeding', value: 32 },
  { source: 'purchase', target: 'babybumps', value: 18 },
  { source: 'purchase', target: 'breastpumps', value: 10 },
  // 信息搜寻 → 社区
  { source: 'seek', target: 'breastfeeding', value: 42 },
  { source: 'seek', target: 'babybumps', value: 28 },
  { source: 'seek', target: 'breastpumps', value: 15 },
  { source: 'seek', target: 'Mommit', value: 10 },
  // 投诉反馈 → 社区
  { source: 'complaint', target: 'breastfeeding', value: 20 },
  { source: 'complaint', target: 'breastpumps', value: 15 },
  { source: 'complaint', target: 'Mommit', value: 8 },
  // 产品评价 → 社区
  { source: 'review', target: 'breastfeeding', value: 30 },
  { source: 'review', target: 'breastpumps', value: 25 },
  { source: 'review', target: 'babybumps', value: 15 },
];

// ========== 词云数据：高频关键词 ==========

export interface SentimentWordCloudItem {
  text: string;
  value: number;
  color?: string;
  sourcePostIds?: string[];
  sentimentConfidence?: number;
}

export const sentimentWordCloudData: SentimentWordCloudItem[] = [
  { text: '静音', value: 78, color: '#4CAF50', sentimentConfidence: 0.85, sourcePostIds: ['p1', 'p2', 'p3'] },
  { text: '吸力', value: 65, color: '#4CAF50', sentimentConfidence: 0.72, sourcePostIds: ['p4', 'p5'] },
  { text: '续航', value: 52, color: '#2196F3', sentimentConfidence: 0.68, sourcePostIds: ['p6'] },
  { text: '价格', value: 48, color: '#FFB74D', sentimentConfidence: 0.55, sourcePostIds: ['p7', 'p8'] },
  { text: '便携', value: 45, color: '#4CAF50', sentimentConfidence: 0.80, sourcePostIds: ['p9', 'p10'] },
  { text: '售后', value: 42, color: '#F44336', sentimentConfidence: 0.62, sourcePostIds: ['p11'] },
  { text: '温感', value: 38, color: '#2196F3', sentimentConfidence: 0.75, sourcePostIds: ['p12'] },
  { text: '背奶', value: 35, color: '#4CAF50', sentimentConfidence: 0.78, sourcePostIds: ['p13', 'p14'] },
  { text: '职场', value: 32, color: '#2196F3', sentimentConfidence: 0.70, sourcePostIds: ['p15'] },
  { text: '清洗', value: 30, color: '#F44336', sentimentConfidence: 0.60, sourcePostIds: ['p16'] },
  { text: '噪音', value: 28, color: '#F44336', sentimentConfidence: 0.65, sourcePostIds: ['p17'] },
  { text: '配件', value: 25, color: '#FFB74D', sentimentConfidence: 0.58, sourcePostIds: ['p18'] },
  { text: '充电', value: 22, color: '#2196F3', sentimentConfidence: 0.72, sourcePostIds: ['p19'] },
  { text: '尺寸', value: 20, color: '#FFB74D', sentimentConfidence: 0.55, sourcePostIds: ['p20'] },
  { text: '材质', value: 18, color: '#4CAF50', sentimentConfidence: 0.76, sourcePostIds: ['p21'] },
];

// ========== 漏斗图数据：用户需求转化漏斗 ==========

export interface FunnelDatum {
  name: string;
  value: number;
  color?: string;
}

export const categoryFunnelData: FunnelDatum[] = [
  { name: 'Reddit 相关讨论', value: 12580, color: '#2196F3' },
  { name: '提及 Momcozy', value: 3240, color: '#4CAF50' },
  { name: '表达购买意向', value: 680, color: '#FF9800' },
  { name: '咨询产品细节', value: 240, color: '#9C27B0' },
  { name: '最终转化反馈', value: 85, color: '#E85D4E' },
];
