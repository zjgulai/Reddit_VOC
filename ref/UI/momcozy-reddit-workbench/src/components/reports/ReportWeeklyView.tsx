import {
  BarChart3,
  Lightbulb,
  AlertTriangle,
  GitCompare,
  Target,
  Calendar,
  TrendingUp,
  TrendingDown,
  Minus,
  CheckCircle,
  AlertCircle,
  XCircle,
  Flag,
  ArrowRight,
  Flame,
  Zap,
  Activity,
  Thermometer,
  Heart,
  MessageSquare,
  BarChart,
} from 'lucide-react';
import { useState, useMemo } from 'react';
import SectionCard from '../SectionCard';
import DetailModal from '../DetailModal';
import { LineChart, BarChart as BarChartComp } from '../charts';
import { BRAND_COLORS, CHART_PALETTE } from '../../constants/colors';
import { useCompetitorStore } from '../../stores';
import type { UnifiedReportData } from '../../data/reportEngine';
import type {
  WeeklyOpportunity,
  WeeklyRisk,
  WeeklyCompetitor,
  WeeklyReview,
  WeeklyPlan,
  WeeklyPainPoint,
  TopicEvolutionData,
  WeeklyBrandVoiceTrend,
} from '../../data/weeklyReportMock';
import {
  weeklyBrandVoiceTrends,
} from '../../data/weeklyReportMock';

// ========== 子组件 ==========

function BrandVoiceTrend({ brandVoiceTrend }: { brandVoiceTrend: WeeklyBrandVoiceTrend[] }) {
  const competitorBrands = useCompetitorStore((s) => s.brands);
  // 动态从数据中提取品牌名（排除 'day' 字段），并与 competitorStore 对齐
  const competitors = useMemo(() => {
    if (!brandVoiceTrend.length) return [];
    const dataBrands = Object.keys(brandVoiceTrend[0]).filter((k) => k !== 'day');
    const storeNames = new Set(competitorBrands.map((b) => b.name));
    // 优先使用数据中存在的品牌，但只保留在 competitorStore 中配置的品牌
    return dataBrands.filter((b) => storeNames.has(b));
  }, [brandVoiceTrend, competitorBrands]);
  const colors = CHART_PALETTE.slice(0, competitors.length);

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table className="w-full text-body-sm">
          <thead>
            <tr className="border-b border-border-divider">
              <th className="text-left py-3 px-2 text-caption font-medium text-foreground-muted">品牌</th>
              {brandVoiceTrend.map((d) => (
                <th key={d.day} className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">{d.day}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {competitors.map((name, idx) => (
              <tr key={name} className="border-b border-border-divider">
                <td className="py-3 px-2 font-medium text-foreground flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: colors[idx] }} />
                  {name}
                </td>
                {brandVoiceTrend.map((d) => (
                  <td key={d.day} className="py-3 px-2 text-right text-foreground-secondary">
                    {(d as unknown as Record<string, number>)[name]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="h-64">
        <LineChart
          data={brandVoiceTrend.map((d) => ({
            label: d.day,
            value: d.Momcozy,
          }))}
          title="Momcozy 7天声量趋势"
          color={BRAND_COLORS.primary}
          height={240}
        />
      </div>
    </div>
  );
}

function OpportunityHeatmap({ opportunities }: { opportunities: WeeklyOpportunity[] }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {opportunities.map((opp) => {
        const categoryConfig: Record<string, { label: string; icon: typeof Lightbulb; color: string; bg: string }> = {
          topic: { label: '话题爆发', icon: Lightbulb, color: 'text-status-success', bg: 'bg-status-successBg' },
          wordofmouth: { label: '口碑高产', icon: Heart, color: 'text-primary', bg: 'bg-primary-light' },
          conversion: { label: '转化机会', icon: Target, color: 'text-status-info', bg: 'bg-status-infoBg' },
          new_product: { label: '产品需求', icon: Zap, color: 'text-status-warning', bg: 'bg-status-warningBg' },
          blue_ocean: { label: '蓝海话题', icon: Zap, color: 'text-status-warning', bg: 'bg-status-warningBg' },
        };
        const CatIcon = categoryConfig[opp.category]?.icon || Lightbulb;
        return (
          <div key={opp.id} className="card p-5">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className={`w-8 h-8 rounded-icon flex items-center justify-center ${categoryConfig[opp.category]?.bg || 'bg-surface-tertiary'}`}>
                  <CatIcon className={`w-4 h-4 ${categoryConfig[opp.category]?.color || 'text-foreground-muted'}`} strokeWidth={1.5} />
                </div>
                <span className="text-tiny font-medium text-foreground-muted">{categoryConfig[opp.category]?.label || opp.category}</span>
              </div>
              <span className={`inline-flex items-center gap-1 text-tiny font-medium ${opp.impact === 'high' ? 'text-status-error' : opp.impact === 'medium' ? 'text-status-warning' : 'text-foreground-muted'}`}>
                <Zap className="w-3.5 h-3.5" strokeWidth={1.5} />
                {opp.impact === 'high' ? '高影响' : opp.impact === 'medium' ? '中影响' : '低影响'}
              </span>
            </div>
            <h4 className="text-body font-medium text-foreground">{opp.title}</h4>
            <p className="text-caption text-foreground-secondary mt-2">{opp.description}</p>
            <div className="grid grid-cols-2 gap-3 mt-3">
              <div className="bg-surface-tertiary rounded-lg p-2.5">
                <div className="text-tiny text-foreground-muted">热度分</div>
                <div className="flex items-center gap-2 mt-1">
                  <div className="h-1.5 flex-1 rounded-full bg-border-divider overflow-hidden">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${opp.heatScore}%` }} />
                  </div>
                  <span className="text-body-sm font-medium text-foreground">{opp.heatScore}</span>
                </div>
              </div>
              <div className="bg-surface-tertiary rounded-lg p-2.5">
                <div className="text-tiny text-foreground-muted">增长率</div>
                <div className="flex items-center gap-2 mt-1">
                  <div className="h-1.5 flex-1 rounded-full bg-border-divider overflow-hidden">
                    <div className="h-full rounded-full bg-status-info" style={{ width: `${Math.min(Math.abs(opp.growth), 100)}%` }} />
                  </div>
                  <span className="text-body-sm font-medium text-foreground">+{opp.growth}%</span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3 mt-3">
              <span className="inline-flex items-center gap-1 text-tiny font-medium text-status-success">
                <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} />
                +{opp.growth}%
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PainPointClustering({ painPoints }: { painPoints: WeeklyPainPoint[] }) {
  const severityWeight = { high: 3, medium: 2, low: 1 };
  const sorted = [...painPoints].sort((a, b) => severityWeight[b.severity] * b.frequency - severityWeight[a.severity] * a.frequency);
  return (
    <div className="space-y-4">
      {sorted.map((pp, idx) => (
        <div key={pp.id} className="card p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-full bg-primary-light flex items-center justify-center text-tiny font-semibold text-primary">
                {idx + 1}
              </div>
              <h4 className="text-body font-medium text-foreground">{pp.topic}</h4>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium bg-status-errorBg text-status-error">
                <Flame className="w-3.5 h-3.5" strokeWidth={1.5} />
                严重度 {pp.severity === 'high' ? '高' : pp.severity === 'medium' ? '中' : '低'}
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium bg-surface-tertiary text-foreground-muted">
                <MessageSquare className="w-3.5 h-3.5" strokeWidth={1.5} />
                {pp.frequency} 次
              </span>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 flex-wrap">
            {pp.affectedProducts.map((p) => (
              <span key={p} className="inline-flex items-center px-2 py-0.5 rounded-badge text-tiny bg-primary-light text-primary">{p}</span>
            ))}
          </div>
          <div className="mt-3 p-3 rounded-lg bg-status-successBg/50 border border-status-success/10">
            <div className="flex items-center gap-2 mb-1">
              <Lightbulb className="w-3.5 h-3.5 text-status-success" strokeWidth={1.5} />
              <span className="text-tiny font-medium text-status-success">建议方案</span>
            </div>
            <p className="text-caption text-foreground-secondary">{pp.solution}</p>
            <span className="inline-flex items-center gap-1 mt-1 text-tiny text-foreground-muted">
              实施难度：
              <span className={pp.severity === 'high' ? 'text-status-error' : pp.severity === 'medium' ? 'text-status-warning' : 'text-status-success'}>
                {pp.severity === 'high' ? '高' : pp.severity === 'medium' ? '中' : '低'}
              </span>
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function CompetitorBenchmarkEnhanced({ competitors }: { competitors: WeeklyCompetitor[] }) {
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table className="w-full text-body-sm">
          <thead>
            <tr className="border-b border-border-divider">
              <th className="text-left py-3 px-2 text-caption font-medium text-foreground-muted">品牌</th>
              <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">提及量</th>
              <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">正面率</th>
              <th className="text-left py-3 px-2 text-caption font-medium text-foreground-muted">热门话题</th>
              <th className="center py-3 px-2 text-caption font-medium text-foreground-muted">趋势</th>
              <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">差距</th>
              <th className="text-left py-3 px-2 text-caption font-medium text-foreground-muted">定位差异</th>
              <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">心智份额</th>
              <th className="text-right py-3 px-2 text-caption font-medium text-foreground-muted">价格敏感度</th>
            </tr>
          </thead>
          <tbody>
            {competitors.map((comp) => {
              const TrendIcon = comp.trend === 'up' ? TrendingUp : comp.trend === 'down' ? TrendingDown : Minus;
              return (
                <tr key={comp.name} className="border-b border-border-divider">
                  <td className="py-3 px-2 font-medium text-foreground">{comp.name}</td>
                  <td className="py-3 px-2 text-right text-foreground-secondary">{comp.mentions}</td>
                  <td className="py-3 px-2 text-right text-foreground-secondary">{comp.positiveRate}%</td>
                  <td className="py-3 px-2 text-foreground-secondary">{comp.topTopic}</td>
                  <td className="py-3 px-2 text-center">
                    <span className={`inline-flex items-center gap-1 text-tiny font-medium ${comp.trend === 'up' ? 'text-status-success' : comp.trend === 'down' ? 'text-status-error' : 'text-foreground-muted'}`}>
                      <TrendIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                    </span>
                  </td>
                  <td className="py-3 px-2 text-right">
                    <span className={`text-tiny font-medium ${comp.ourGap > 0 ? 'text-status-success' : 'text-status-error'}`}>
                      {comp.ourGap > 0 ? '+' : ''}{comp.ourGap}
                    </span>
                  </td>
                  <td className="py-3 px-2 text-foreground-secondary">{comp.brandPositioning}</td>
                  <td className="py-3 px-2 text-right text-foreground-secondary">{comp.mindShare}%</td>
                  <td className="py-3 px-2 text-right text-foreground-secondary">{comp.priceSensitivity}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TopicEvolutionWeekly({ topics }: { topics: TopicEvolutionData[] }) {
  const forecastConfig = {
    rising: { label: '上升', color: 'text-status-success', icon: TrendingUp },
    stable: { label: '平稳', color: 'text-status-info', icon: Activity },
    declining: { label: '下降', color: 'text-foreground-muted', icon: TrendingDown },
  };

  function getForecastTrend(prediction: number, day7: number): 'rising' | 'stable' | 'declining' {
    if (prediction > day7 * 1.05) return 'rising';
    if (prediction < day7 * 0.95) return 'declining';
    return 'stable';
  }

  return (
    <div className="space-y-4">
      {topics.map((topic) => {
        const trend = getForecastTrend(topic.prediction, topic.day7);
        const FIcon = forecastConfig[trend].icon;
        const data = [
          { name: '周一', value: topic.day1 },
          { name: '周二', value: topic.day2 },
          { name: '周三', value: topic.day3 },
          { name: '周四', value: topic.day4 },
          { name: '周五', value: topic.day5 },
          { name: '周六', value: topic.day6 },
          { name: '周日', value: topic.day7 },
        ];
        return (
          <div key={topic.topic} className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-body font-medium text-foreground">{topic.topic}</h4>
              <span className={`inline-flex items-center gap-1 text-tiny font-medium ${forecastConfig[trend].color}`}>
                <FIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                预测：{forecastConfig[trend].label}（置信度 {topic.predictionAccuracy}%）
              </span>
            </div>
            <div className="h-36">
              <BarChartComp data={data} height={140} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function WeeklyReviewEnhanced({ reviews }: { reviews: WeeklyReview[] }) {
  const statusConfig = {
    good: { icon: CheckCircle, color: 'text-status-success', label: '达标' },
    warning: { icon: AlertCircle, color: 'text-status-warning', label: '警告' },
    bad: { icon: XCircle, color: 'text-status-error', label: '未达标' },
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {reviews.map((review) => {
          const StatusIcon = statusConfig[review.status].icon;
          return (
            <div key={review.metric} className="card p-5 text-center">
              <div className="text-caption text-foreground-muted">{review.metric}</div>
              <div className="text-[22px] font-semibold text-foreground mt-2">{review.value}</div>
              <div className="text-tiny text-foreground-muted mt-1">目标 {review.target}</div>
              <div className={`inline-flex items-center gap-1 text-tiny font-medium mt-2 ${statusConfig[review.status].color}`}>
                <StatusIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                {statusConfig[review.status].label}
              </div>
            </div>
          );
        })}
      </div>

      {/* 运营效果增强指标 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-3">
            <Activity className="w-4 h-4 text-primary" strokeWidth={1.5} />
            <span className="text-body-sm font-medium text-foreground">社区运营效果</span>
          </div>
          <div className="space-y-2">
            {reviews.map((r) => (
              <div key={`eng-${r.metric}`} className="flex items-center justify-between">
                <span className="text-tiny text-foreground-muted">{r.metric}</span>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-20 rounded-full bg-surface-tertiary overflow-hidden">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${r.communityEffectiveness ?? 0}%` }} />
                  </div>
                  <span className="text-tiny text-foreground">{r.communityEffectiveness}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-3">
            <BarChart className="w-4 h-4 text-status-success" strokeWidth={1.5} />
            <span className="text-body-sm font-medium text-foreground">内容策略ROI</span>
          </div>
          <div className="space-y-2">
            {reviews.map((r) => (
              <div key={`roi-${r.metric}`} className="flex items-center justify-between">
                <span className="text-tiny text-foreground-muted">{r.metric}</span>
                <span className="text-tiny font-medium text-status-success">{r.contentROI}x</span>
              </div>
            ))}
          </div>
        </div>
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-3">
            <Heart className="w-4 h-4 text-status-info" strokeWidth={1.5} />
            <span className="text-body-sm font-medium text-foreground">用户参与度</span>
          </div>
          <div className="space-y-2">
            {reviews.map((r) => (
              <div key={`part-${r.metric}`} className="flex items-center justify-between">
                <span className="text-tiny text-foreground-muted">{r.metric}</span>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-20 rounded-full bg-surface-tertiary overflow-hidden">
                    <div className="h-full rounded-full bg-status-info" style={{ width: `${r.engagementRate ?? 0}%` }} />
                  </div>
                  <span className="text-tiny text-foreground">{r.engagementRate}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function NextWeekPlan({ plans }: { plans: WeeklyPlan[] }) {
  const priorityConfig = {
    high: { label: '高优先级', color: 'text-status-error', bg: 'bg-status-errorBg' },
    medium: { label: '中优先级', color: 'text-status-warning', bg: 'bg-status-warningBg' },
    low: { label: '低优先级', color: 'text-foreground-muted', bg: 'bg-surface-tertiary' },
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      {plans.map((plan) => (
        <div key={plan.id} className="card p-5">
          <span className={`inline-flex items-center px-2.5 py-1 rounded-badge text-tiny font-medium ${priorityConfig[plan.priority].bg} ${priorityConfig[plan.priority].color}`}>
            <Flag className="w-3.5 h-3.5 mr-1" strokeWidth={1.5} />
            {priorityConfig[plan.priority].label}
          </span>
          <h4 className="text-body font-medium text-foreground mt-3">{plan.action}</h4>
          <div className="text-caption text-foreground-secondary mt-2">
            {plan.community && <div>社区：{plan.community}</div>}
            {plan.topic && <div>话题：{plan.topic}</div>}
          </div>
          <div className="inline-flex items-center gap-1 text-tiny text-foreground-muted mt-3">
            <ArrowRight className="w-3.5 h-3.5" strokeWidth={1.5} />
            预期：{plan.expectedImpact}
          </div>
        </div>
      ))}
    </div>
  );
}

// ========== 主视图 ==========

export interface ReportWeeklyViewProps {
  data: UnifiedReportData;
}

export default function ReportWeeklyView({ data }: ReportWeeklyViewProps) {
  const [showOpportunitiesModal, setShowOpportunitiesModal] = useState(false);
  const [showRisksModal, setShowRisksModal] = useState(false);
  const [showPainPointsModal, setShowPainPointsModal] = useState(false);
  const [showTopicsModal, setShowTopicsModal] = useState(false);

  const opportunities = (data.weeklyOpportunities as WeeklyOpportunity[]);
  const risks = (data.weeklyRisks as WeeklyRisk[]);
  const painPoints = (data.painPoints as WeeklyPainPoint[]);
  const topics = (data.topicLifecycles as TopicEvolutionData[]);

  return (
    <div className="space-y-6">
      <SectionCard title="品牌声量趋势" subtitle="7天品牌声量曲线，对比主要竞品" tag="品牌" icon={<BarChart3 className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <BrandVoiceTrend brandVoiceTrend={data.brandVoiceTrend as typeof weeklyBrandVoiceTrends} />
      </SectionCard>

      <SectionCard
        title="品类机会洞察"
        subtitle="本周发现的增长机会 + 机会热力图"
        tag="品类"
        icon={<Lightbulb className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={opportunities.length > 4 ? { label: '查看全部', onClick: () => setShowOpportunitiesModal(true) } : undefined}
      >
        <OpportunityHeatmap opportunities={opportunities.slice(0, 4)} />
      </SectionCard>

      <SectionCard
        title="风险洞察"
        subtitle="本周需要关注的风险点"
        tag="舆情"
        icon={<AlertTriangle className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={risks.length > 4 ? { label: '查看全部', onClick: () => setShowRisksModal(true) } : undefined}
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {risks.slice(0, 4).map((risk) => (
            <div key={risk.id} className="card p-5">
              <div className="flex items-center gap-2 mb-2">
                <div className={`w-8 h-8 rounded-icon flex items-center justify-center ${risk.severity === 'high' ? 'bg-status-errorBg' : risk.severity === 'medium' ? 'bg-status-warningBg' : 'bg-surface-tertiary'}`}>
                  <AlertTriangle className={`w-4 h-4 ${risk.severity === 'high' ? 'text-status-error' : risk.severity === 'medium' ? 'text-status-warning' : 'text-foreground-muted'}`} strokeWidth={1.5} />
                </div>
                <span className={`text-tiny font-medium ${risk.severity === 'high' ? 'text-status-error' : risk.severity === 'medium' ? 'text-status-warning' : 'text-foreground-muted'}`}>
                  {risk.severity === 'high' ? '高风险' : risk.severity === 'medium' ? '中风险' : '低风险'}
                </span>
              </div>
              <h4 className="text-body font-medium text-foreground">{risk.title}</h4>
              <p className="text-caption text-foreground-secondary mt-2">{risk.description}</p>
              <div className="flex items-center gap-3 mt-3">
                <span className="inline-flex items-center gap-1 text-tiny font-medium text-status-error">
                  <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} />
                  +{risk.growth}%
                </span>
                <span className="text-tiny text-foreground-muted">影响区域：{risk.affectedArea}</span>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard
        title="用户痛点聚类"
        subtitle="按频率和严重程度排序的痛点 + 解决方案映射"
        tag="品类"
        icon={<Thermometer className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={painPoints.length > 5 ? { label: '查看全部', onClick: () => setShowPainPointsModal(true) } : undefined}
      >
        <PainPointClustering painPoints={painPoints.slice(0, 5)} />
      </SectionCard>

      <SectionCard title="竞品对标" subtitle="Momcozy vs 主要竞品 — 品牌定位、心智份额、价格敏感度" tag="品牌" icon={<GitCompare className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <CompetitorBenchmarkEnhanced competitors={data.weeklyCompetitors as WeeklyCompetitor[]} />
      </SectionCard>

      <SectionCard
        title="话题演变追踪"
        subtitle="核心话题7天生命周期变化 + 话题预测"
        tag="舆情"
        icon={<TrendingUp className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={topics.length > 4 ? { label: '查看全部', onClick: () => setShowTopicsModal(true) } : undefined}
      >
        <TopicEvolutionWeekly topics={topics.slice(0, 4)} />
      </SectionCard>

      <SectionCard title="运营复盘" subtitle="本周运营KPI + 社区运营效果、内容策略ROI、用户参与度" tag="运营" icon={<Target className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <WeeklyReviewEnhanced reviews={data.weeklyReviews as WeeklyReview[]} />
      </SectionCard>

      <SectionCard title="下周计划" subtitle="5 项重点行动计划" tag="运营" icon={<Calendar className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <NextWeekPlan plans={data.weeklyPlans as WeeklyPlan[]} />
      </SectionCard>

      {/* 全部机会洞察弹窗 */}
      <DetailModal
        open={showOpportunitiesModal}
        onClose={() => setShowOpportunitiesModal(false)}
        title="全部机会洞察"
        subtitle="本周发现的全部增长机会"
      >
        <OpportunityHeatmap opportunities={opportunities} />
      </DetailModal>

      {/* 全部风险洞察弹窗 */}
      <DetailModal
        open={showRisksModal}
        onClose={() => setShowRisksModal(false)}
        title="全部风险洞察"
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {risks.map((risk) => (
            <div key={risk.id} className="card p-5">
              <div className="flex items-center gap-2 mb-2">
                <div className={`w-8 h-8 rounded-icon flex items-center justify-center ${risk.severity === 'high' ? 'bg-status-errorBg' : risk.severity === 'medium' ? 'bg-status-warningBg' : 'bg-surface-tertiary'}`}>
                  <AlertTriangle className={`w-4 h-4 ${risk.severity === 'high' ? 'text-status-error' : risk.severity === 'medium' ? 'text-status-warning' : 'text-foreground-muted'}`} strokeWidth={1.5} />
                </div>
                <span className={`text-tiny font-medium ${risk.severity === 'high' ? 'text-status-error' : risk.severity === 'medium' ? 'text-status-warning' : 'text-foreground-muted'}`}>
                  {risk.severity === 'high' ? '高风险' : risk.severity === 'medium' ? '中风险' : '低风险'}
                </span>
              </div>
              <h4 className="text-body font-medium text-foreground">{risk.title}</h4>
              <p className="text-caption text-foreground-secondary mt-2">{risk.description}</p>
              <div className="flex items-center gap-3 mt-3">
                <span className="inline-flex items-center gap-1 text-tiny font-medium text-status-error">
                  <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} />
                  +{risk.growth}%
                </span>
                <span className="text-tiny text-foreground-muted">影响区域：{risk.affectedArea}</span>
              </div>
            </div>
          ))}
        </div>
      </DetailModal>

      {/* 全部用户痛点弹窗 */}
      <DetailModal
        open={showPainPointsModal}
        onClose={() => setShowPainPointsModal(false)}
        title="全部用户痛点"
      >
        <PainPointClustering painPoints={painPoints} />
      </DetailModal>

      {/* 全部话题演变弹窗 */}
      <DetailModal
        open={showTopicsModal}
        onClose={() => setShowTopicsModal(false)}
        title="全部话题演变"
      >
        <TopicEvolutionWeekly topics={topics} />
      </DetailModal>
    </div>
  );
}
