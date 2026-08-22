import {
  Activity,
  PieChart as PieChartIcon,
  TrendingUp,
  TrendingDown,
  CheckCircle,
  AlertCircle,
  XCircle,
  Flag,
  Lightbulb,
  Target,
  BarChart3,
  Crosshair,
  Layers,
  Award,
  DollarSign,
  Gauge,
  Zap,
  Calendar,
} from 'lucide-react';
import SectionCard from '../SectionCard';
import { PieChart, LineChart, RadarChart } from '../charts';
import { CHART_PALETTE, BRAND_COLORS } from '../../constants/colors';
import type { UnifiedReportData } from '../../data/reportEngine';
import { useState } from 'react';
import DetailModal from '../DetailModal';

// ========== 子组件 ==========

/** 品牌大盘健康度 */
function BrandHealthDashboard({
  brandHealthScore,
  brandHealthRadar,
  brandHealthTrend,
}: {
  brandHealthScore?: number;
  brandHealthRadar?: { dimension: string; value: number; benchmark: number }[];
  brandHealthTrend?: { label: string; value: number }[];
}) {
  const radarData = brandHealthRadar?.map((d) => ({
    subject: d.dimension,
    value: d.value,
    fullMark: 100,
  })) || [];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 健康度评分 */}
        <div className="card p-5 flex flex-col items-center justify-center">
          <div className="flex items-center gap-2 mb-4">
            <Award className="w-5 h-5 text-primary" strokeWidth={1.5} />
            <h4 className="text-body font-medium text-foreground">品牌健康度评分</h4>
          </div>
          <div className="relative w-32 h-32 flex items-center justify-center">
            <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="#F0F0F0" strokeWidth="8" />
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke={BRAND_COLORS.primary}
                strokeWidth="8"
                strokeDasharray={`${(brandHealthScore || 0) * 2.64} 264`}
                strokeLinecap="round"
                className="transition-all duration-1000"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-[28px] font-bold text-foreground">{brandHealthScore}</span>
              <span className="text-tiny text-foreground-muted">/100</span>
            </div>
          </div>
          <div className="mt-3 text-caption text-foreground-muted text-center">
            行业基准: 70 | Momcozy 领先 <span className="text-status-success font-medium">+{(brandHealthScore || 0) - 70}分</span>
          </div>
        </div>

        {/* 雷达图 */}
        <div className="lg:col-span-2 card p-5">
          <RadarChart
            data={radarData}
            title="品牌健康度雷达"
            height={260}
            color={BRAND_COLORS.primary}
            fillOpacity={0.2}
          />
        </div>
      </div>

      {/* 6个月趋势 */}
      {brandHealthTrend && (
        <LineChart
          data={brandHealthTrend}
          title="6个月品牌健康度趋势"
          color={BRAND_COLORS.primary}
          height={240}
        />
      )}
    </div>
  );
}

/** 竞争格局 + 竞争态势矩阵 */
function CompetitiveLandscapeEnhanced({
  competitorShares,
  competitiveMatrix,
}: {
  competitorShares: UnifiedReportData['monthlyCompetitorShares'];
  competitiveMatrix?: { name: string; marketShare: number; growthRate: number; quadrant: string }[];
}) {
  if (!competitorShares) return null;

  const colors = CHART_PALETTE.slice(0, 5);
  const pieData = competitorShares.map((c, i) => ({
    name: c.name,
    value: c.share,
    color: colors[i % colors.length],
  }));

  const quadrantConfig: Record<string, { label: string; color: string; bg: string }> = {
    star: { label: '明星', color: 'text-status-success', bg: 'bg-status-successBg' },
    question: { label: '问号', color: 'text-status-info', bg: 'bg-status-infoBg' },
    'cash-cow': { label: '现金牛', color: 'text-status-warning', bg: 'bg-status-warningBg' },
    dog: { label: '瘦狗', color: 'text-foreground-muted', bg: 'bg-surface-tertiary' },
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row gap-6">
        <div className="flex-shrink-0 w-full lg:w-48">
          <PieChart data={pieData} showLegend={false} innerRadius={0} height={160} />
          <div className="mt-3 space-y-1">
            {competitorShares.map((c, i) => (
              <div key={c.name} className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: colors[i % colors.length] }} />
                <span className="text-tiny text-foreground-secondary">{c.name} {c.share}%</span>
              </div>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-x-auto">
          <table className="w-full text-body-sm">
            <thead>
              <tr className="border-b border-border-divider">
                <th className="text-left py-3 px-2 text-caption font-medium text-foreground-muted">品牌</th>
                <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">讨论份额</th>
                <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">正面率</th>
                <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">月环比</th>
                <th className="text-left py-3 px-2 text-caption font-medium text-foreground-muted">热门话题</th>
              </tr>
            </thead>
            <tbody>
              {competitorShares.map((comp) => (
                <tr key={comp.name} className="border-b border-border-divider hover:bg-surface-tertiary/50 transition-colors">
                  <td className="py-3 px-2 font-medium text-foreground">{comp.name}</td>
                  <td className="py-3 px-2 text-right text-foreground-secondary">{comp.share}%</td>
                  <td className="py-3 px-2 text-right text-foreground-secondary">{comp.positiveRate}%</td>
                  <td className="py-3 px-2 text-right">
                    <span className={`text-tiny font-medium ${comp.mentionGrowth > 0 ? 'text-status-success' : 'text-status-error'}`}>
                      {comp.mentionGrowth > 0 ? '+' : ''}{comp.mentionGrowth}%
                    </span>
                  </td>
                  <td className="py-3 px-2 text-foreground-secondary">{comp.topTopic}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 竞争态势矩阵 */}
      {competitiveMatrix && (
        <div className="bg-surface-tertiary rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Crosshair className="w-4 h-4 text-primary" strokeWidth={1.5} />
            <span className="text-body-sm font-medium text-foreground">竞争态势矩阵（市场份额 vs 增长率）</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {competitiveMatrix.map((item) => {
              const config = quadrantConfig[item.quadrant] || quadrantConfig.dog;
              return (
                <div key={item.name} className={`bg-white rounded-lg p-3 border ${item.quadrant === 'star' ? 'border-status-success/30' : 'border-border-divider'}`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-body-sm font-medium text-foreground">{item.name}</span>
                    <span className={`text-tiny font-medium ${config.color} ${config.bg} px-2 py-0.5 rounded-badge`}>
                      {config.label}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-tiny">
                    <div>
                      <span className="text-foreground-muted">份额</span>
                      <div className="font-medium text-foreground">{item.marketShare}%</div>
                    </div>
                    <div>
                      <span className="text-foreground-muted">增长</span>
                      <div className={`font-medium ${item.growthRate > 0 ? 'text-status-success' : 'text-status-error'}`}>
                        {item.growthRate > 0 ? '+' : ''}{item.growthRate}%
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/** 品类矩阵图 */
function CategoryMatrixView({ categoryMatrix }: { categoryMatrix?: { category: string; volume: number; growthRate: number; conversionRate: number; roi: number }[] }) {
  if (!categoryMatrix) return null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        {categoryMatrix.map((cat) => (
          <div key={cat.category} className="card p-4 hover:shadow-card-hover transition-all duration-300">
            <div className="text-body-sm font-medium text-foreground mb-2">{cat.category}</div>
            <div className="space-y-2">
              <div className="flex justify-between text-tiny">
                <span className="text-foreground-muted">声量</span>
                <span className="font-medium text-foreground">{cat.volume}</span>
              </div>
              <div className="flex justify-between text-tiny">
                <span className="text-foreground-muted">增长</span>
                <span className={`font-medium ${cat.growthRate > 0 ? 'text-status-success' : 'text-status-error'}`}>
                  {cat.growthRate > 0 ? '+' : ''}{cat.growthRate}%
                </span>
              </div>
              <div className="flex justify-between text-tiny">
                <span className="text-foreground-muted">转化</span>
                <span className="font-medium text-foreground">{cat.conversionRate}%</span>
              </div>
              <div className="flex justify-between text-tiny">
                <span className="text-foreground-muted">ROI</span>
                <span className="font-medium text-primary">{cat.roi}x</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 话题生命周期 + 预测准确率 */
function EnhancedTopicEvolution({ monthlyTopicEvolution }: { monthlyTopicEvolution: UnifiedReportData['monthlyTopicEvolution'] }) {
  if (!monthlyTopicEvolution) return null;

  const lifecycleConfig = {
    rising: { label: '上升期', icon: TrendingUp, color: 'text-status-success' },
    peak: { label: '峰值期', icon: Zap, color: 'text-status-error' },
    stable: { label: '平稳期', icon: Activity, color: 'text-status-info' },
    declining: { label: '衰退期', icon: TrendingDown, color: 'text-foreground-muted' },
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {monthlyTopicEvolution.map((topic) => {
        const LifeIcon = lifecycleConfig[topic.lifecycle].icon;
        return (
          <div key={topic.topic} className="card p-5 hover:shadow-card-hover transition-all duration-300">
            <div className="flex items-center justify-between">
              <h4 className="text-body font-medium text-foreground">{topic.topic}</h4>
              <span className={`inline-flex items-center gap-1 text-tiny font-medium ${lifecycleConfig[topic.lifecycle].color}`}>
                <LifeIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                {lifecycleConfig[topic.lifecycle].label}
              </span>
            </div>
            <div className="flex items-center gap-4 mt-3">
              <div>
                <div className="text-caption text-foreground-muted">本月</div>
                <div className="text-h4 text-foreground">{topic.currentVolume}</div>
              </div>
              <div>
                <div className="text-caption text-foreground-muted">上月</div>
                <div className="text-h4 text-foreground">{topic.lastMonthVolume}</div>
              </div>
              <div>
                <div className="text-caption text-foreground-muted">增长率</div>
                <div className={`text-h4 font-medium ${topic.growth > 0 ? 'text-status-success' : 'text-status-error'}`}>
                  {topic.growth > 0 ? '+' : ''}{topic.growth}%
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 mt-3">
              <span className={`inline-flex items-center px-2.5 py-1 rounded-badge text-tiny font-medium ${
                topic.sentiment === 'positive' ? 'bg-status-successBg text-status-success' :
                topic.sentiment === 'negative' ? 'bg-status-errorBg text-status-error' :
                'bg-surface-tertiary text-foreground-muted'
              }`}>
                {topic.sentiment === 'positive' ? '正面' : topic.sentiment === 'negative' ? '负面' : '中性'}
              </span>
              <span className="inline-flex items-center gap-1 text-tiny text-foreground-muted">
                <Gauge className="w-3.5 h-3.5" strokeWidth={1.5} />
                预测准确率 {(topic as unknown as Record<string, number>).predictionAccuracy || 0}%
              </span>
            </div>
            <div className="mt-2 text-tiny text-foreground-secondary bg-surface-tertiary rounded-lg px-3 py-2">
              {topic.forecast}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** 战略建议增强 */
function EnhancedStrategicAdvice({ monthlyStrategicAdvices }: { monthlyStrategicAdvices: UnifiedReportData['monthlyStrategicAdvices'] }) {
  if (!monthlyStrategicAdvices) return null;

  const priorityConfig = {
    high: { label: '高优先级', color: 'text-status-error', bg: 'bg-status-errorBg' },
    medium: { label: '中优先级', color: 'text-status-warning', bg: 'bg-status-warningBg' },
    low: { label: '低优先级', color: 'text-foreground-muted', bg: 'bg-surface-tertiary' },
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      {monthlyStrategicAdvices.map((advice) => (
        <div key={advice.id} className="card p-5 hover:shadow-card-hover transition-all duration-300">
          <span className={`inline-flex items-center px-2.5 py-1 rounded-badge text-tiny font-medium ${priorityConfig[advice.priority].bg} ${priorityConfig[advice.priority].color}`}>
            <Flag className="w-3.5 h-3.5 mr-1" strokeWidth={1.5} />
            {priorityConfig[advice.priority].label}
          </span>
          <h4 className="text-body font-medium text-foreground mt-3">{advice.title}</h4>
          <p className="text-caption text-foreground-secondary mt-2">{advice.description}</p>

          {/* 资源分配建议 */}
          {(advice as unknown as Record<string, Record<string, string>>).resourceAllocation && (
            <div className="mt-3 bg-surface-tertiary rounded-lg p-2 space-y-1">
              <div className="flex justify-between text-tiny">
                <span className="text-foreground-muted">预算</span>
                <span className="font-medium text-foreground">{(advice as unknown as Record<string, Record<string, string>>).resourceAllocation.budget}</span>
              </div>
              <div className="flex justify-between text-tiny">
                <span className="text-foreground-muted">人力</span>
                <span className="font-medium text-foreground">{(advice as unknown as Record<string, Record<string, string>>).resourceAllocation.manpower}</span>
              </div>
              <div className="flex justify-between text-tiny">
                <span className="text-foreground-muted">时间</span>
                <span className="font-medium text-foreground">{(advice as unknown as Record<string, Record<string, string>>).resourceAllocation.time}</span>
              </div>
            </div>
          )}

          <div className="flex items-center gap-3 mt-3 flex-wrap">
            <span className="inline-flex items-center gap-1 text-tiny text-foreground-muted">
              <Lightbulb className="w-3.5 h-3.5" strokeWidth={1.5} />
              预期：{advice.expectedImpact}
            </span>
            <span className="inline-flex items-center gap-1 text-tiny text-foreground-muted">
              <Calendar className="w-3.5 h-3.5" strokeWidth={1.5} />
              {advice.timeframe}
            </span>
            {(advice as unknown as Record<string, number>).expectedROI && (
              <span className="inline-flex items-center gap-1 text-tiny text-status-success font-medium">
                <DollarSign className="w-3.5 h-3.5" strokeWidth={1.5} />
                ROI {(advice as unknown as Record<string, number>).expectedROI}x
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** KPI 达成 + 趋势 */
function EnhancedKPIReview({
  monthlyKPIs,
  kpiTrend,
}: {
  monthlyKPIs: UnifiedReportData['monthlyKPIs'];
  kpiTrend?: { label: string; achievement: number }[];
}) {
  const statusConfig = {
    good: { icon: CheckCircle, color: 'text-status-success', label: '达标' },
    warning: { icon: AlertCircle, color: 'text-status-warning', label: '警告' },
    bad: { icon: XCircle, color: 'text-status-error', label: '未达标' },
  };

  return (
    <div className="space-y-6">
      {/* KPI 趋势图 */}
      {kpiTrend && (
        <LineChart
          data={kpiTrend.map((d) => ({ label: d.label, value: d.achievement }))}
          title="KPI 达成率趋势（6个月）"
          color={BRAND_COLORS.primary}
          height={240}
        />
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {monthlyKPIs?.map((kpi) => {
          const StatusIcon = statusConfig[kpi.status].icon;
          return (
            <div key={kpi.metric} className="card p-5 hover:shadow-card-hover transition-all duration-300">
              <div className="text-caption text-foreground-muted">{kpi.metric}</div>
              <div className="text-[22px] font-semibold text-foreground mt-2">{kpi.value}</div>
              <div className="text-tiny text-foreground-muted mt-1">目标 {kpi.target}</div>
              <div className="mt-3">
                <div className="flex items-center justify-between text-tiny mb-1">
                  <span className="text-foreground-muted">达成率</span>
                  <span className={`font-medium ${statusConfig[kpi.status].color}`}>{kpi.achievement}%</span>
                </div>
                <div className="h-2 rounded-full bg-surface-tertiary overflow-hidden">
                  <div className={`h-full rounded-full ${
                    kpi.status === 'good' ? 'bg-status-success' :
                    kpi.status === 'warning' ? 'bg-status-warning' :
                    'bg-status-error'
                  }`} style={{ width: `${Math.min(kpi.achievement, 100)}%` }} />
                </div>
              </div>
              <div className={`inline-flex items-center gap-1 text-tiny font-medium mt-2 ${statusConfig[kpi.status].color}`}>
                <StatusIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                {statusConfig[kpi.status].label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CommunityValue({ monthlyCommunityROI }: { monthlyCommunityROI: UnifiedReportData['monthlyCommunityROI'] }) {
  if (!monthlyCommunityROI) return null;
  const qualityConfig = {
    high: { label: '高', color: 'text-status-success' },
    medium: { label: '中', color: 'text-status-warning' },
    low: { label: '低', color: 'text-status-error' },
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-body-sm">
        <thead>
          <tr className="border-b border-border-divider">
            <th className="text-left py-3 px-2 text-caption font-medium text-foreground-muted">社区</th>
            <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">帖子数</th>
            <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">线索数</th>
            <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">转化率</th>
            <th className="text-center py-3 px-2 text-caption font-medium text-foreground-muted">质量评级</th>
            <th className="text-left py-3 px-2 text-caption font-medium text-foreground-muted">ROI</th>
          </tr>
        </thead>
        <tbody>
          {monthlyCommunityROI.map((comm) => (
            <tr key={comm.name} className="border-b border-border-divider hover:bg-surface-tertiary/50 transition-colors">
              <td className="py-3 px-2 font-medium text-foreground">{comm.displayName}</td>
              <td className="py-3 px-2 text-right text-foreground-secondary">{comm.posts}</td>
              <td className="py-3 px-2 text-right text-foreground-secondary">{comm.leads}</td>
              <td className="py-3 px-2 text-right text-foreground-secondary">{comm.conversionRate}%</td>
              <td className="py-3 px-2 text-center">
                <span className={`inline-flex items-center gap-1 text-tiny font-medium ${qualityConfig[comm.quality].color}`}>
                  <Zap className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {qualityConfig[comm.quality].label}
                </span>
              </td>
              <td className="py-3 px-2 text-foreground-secondary">{comm.roi}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ========== 主视图 ==========

export interface ReportMonthlyViewProps {
  data: UnifiedReportData;
}

export default function ReportMonthlyView({ data }: ReportMonthlyViewProps) {
  const [showCompetitorModal, setShowCompetitorModal] = useState(false);
  const [showCommunityModal, setShowCommunityModal] = useState(false);
  const [showTopicsModal, setShowTopicsModal] = useState(false);
  const [showKPIModal, setShowKPIModal] = useState(false);
  const [showAdviceModal, setShowAdviceModal] = useState(false);

  return (
    <div className="space-y-6 animate-fade-in">
      <SectionCard title="品牌大盘健康度" subtitle="品牌健康度评分与6个月趋势" tag="品牌" icon={<Gauge className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <BrandHealthDashboard
          brandHealthScore={data.brandHealthScore}
          brandHealthRadar={data.brandHealthRadar}
          brandHealthTrend={data.monthlyBrandHealthTrend}
        />
      </SectionCard>

      <SectionCard title="竞争格局" subtitle="市场份额与竞争态势矩阵" tag="品牌" icon={<PieChartIcon className="w-5 h-5 text-primary" strokeWidth={1.5} />} action={{ label: '查看全部', onClick: () => setShowCompetitorModal(true) }}>
        <CompetitiveLandscapeEnhanced
          competitorShares={data.monthlyCompetitorShares}
          competitiveMatrix={data.competitiveMatrix}
        />
      </SectionCard>

      <SectionCard title="社区价值" subtitle="各社区 ROI 与质量评级" tag="运营" icon={<BarChart3 className="w-5 h-5 text-primary" strokeWidth={1.5} />} action={{ label: '查看全部', onClick: () => setShowCommunityModal(true) }}>
        <CommunityValue monthlyCommunityROI={data.monthlyCommunityROI} />
      </SectionCard>

      <SectionCard title="品类价值评估" subtitle="各品类声量、增长率、转化率、ROI" tag="品类" icon={<Layers className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <CategoryMatrixView categoryMatrix={data.categoryMatrix} />
      </SectionCard>

      <SectionCard title="话题生命周期" subtitle="核心话题月度生命周期与预测准确率" tag="舆情" icon={<TrendingUp className="w-5 h-5 text-primary" strokeWidth={1.5} />} action={data.monthlyTopicEvolution && data.monthlyTopicEvolution.length > 4 ? { label: '查看全部', onClick: () => setShowTopicsModal(true) } : undefined}>
        <EnhancedTopicEvolution monthlyTopicEvolution={data.monthlyTopicEvolution?.slice(0, 4)} />
      </SectionCard>

      <SectionCard title="KPI达成" subtitle="月度 KPI 达成率与趋势" tag="运营" icon={<Target className="w-5 h-5 text-primary" strokeWidth={1.5} />} action={data.monthlyKPIs && data.monthlyKPIs.length > 6 ? { label: '查看全部', onClick: () => setShowKPIModal(true) } : undefined}>
        <EnhancedKPIReview monthlyKPIs={data.monthlyKPIs?.slice(0, 6)} kpiTrend={data.kpiTrend} />
      </SectionCard>

      <SectionCard title="战略建议" subtitle="基于数据的战略方向与资源分配建议" tag="运营" icon={<Lightbulb className="w-5 h-5 text-primary" strokeWidth={1.5} />} action={data.monthlyStrategicAdvices && data.monthlyStrategicAdvices.length > 5 ? { label: '查看全部', onClick: () => setShowAdviceModal(true) } : undefined}>
        <EnhancedStrategicAdvice monthlyStrategicAdvices={data.monthlyStrategicAdvices?.slice(0, 5)} />
      </SectionCard>

      <DetailModal open={showCompetitorModal} onClose={() => setShowCompetitorModal(false)} title="竞争格局详情">
        <CompetitiveLandscapeEnhanced
          competitorShares={data.monthlyCompetitorShares}
          competitiveMatrix={data.competitiveMatrix}
        />
      </DetailModal>

      <DetailModal open={showCommunityModal} onClose={() => setShowCommunityModal(false)} title="社区价值详情">
        <CommunityValue monthlyCommunityROI={data.monthlyCommunityROI} />
      </DetailModal>

      <DetailModal open={showTopicsModal} onClose={() => setShowTopicsModal(false)} title="全部话题生命周期">
        <EnhancedTopicEvolution monthlyTopicEvolution={data.monthlyTopicEvolution} />
      </DetailModal>

      <DetailModal open={showKPIModal} onClose={() => setShowKPIModal(false)} title="全部KPI详情">
        <EnhancedKPIReview monthlyKPIs={data.monthlyKPIs} kpiTrend={data.kpiTrend} />
      </DetailModal>

      <DetailModal open={showAdviceModal} onClose={() => setShowAdviceModal(false)} title="全部战略建议">
        <EnhancedStrategicAdvice monthlyStrategicAdvices={data.monthlyStrategicAdvices} />
      </DetailModal>
    </div>
  );
}
