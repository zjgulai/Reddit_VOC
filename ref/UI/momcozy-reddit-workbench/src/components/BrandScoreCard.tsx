import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from 'recharts';
import { Star, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { BRAND_COLORS, SENTIMENT_COLORS, NEUTRAL_COLORS } from '../constants/colors';
import MetricHelpPopover from './MetricHelpPopover';
import type { MetricHelpContent } from './MetricHelpPopover';

export interface BrandScoreData {
  dimension: string;
  score: number | null;
  fullMark: number;
  help?: string | MetricHelpContent;
}

interface BrandScoreCardProps {
  brandName?: string;
  overallScore: number | null;
  trend?: 'up' | 'down' | 'stable' | 'unavailable';
  change?: number | null;
  data?: BrandScoreData[];
  title?: string;
  subtitle?: string;
  help?: string | MetricHelpContent;
  comparisonLabel?: string;
  changeSuffix?: '%' | '分';
  scoreStatusLabel?: string;
}

const trendConfig = {
  up: { icon: TrendingUp, color: 'text-status-error', label: '上升' },
  down: { icon: TrendingDown, color: 'text-status-success', label: '下降' },
  stable: { icon: Minus, color: 'text-foreground-muted', label: '平稳' },
  unavailable: { icon: Minus, color: 'text-foreground-muted', label: '不可比' },
};

function helpContent(help: string | MetricHelpContent | undefined): MetricHelpContent {
  if (help && typeof help !== 'string') return help;
  return {
    definition: help ?? '该指标来自当前已发布的数据投影。',
    formula: '计算公式以当前发布口径为准；不在浏览器中临时补算。',
  };
}

export default function BrandScoreCard({
  brandName = 'Momcozy',
  overallScore,
  trend = 'unavailable',
  change = null,
  data = [],
  title = '品牌健康度指数',
  subtitle = `${brandName} 四维受治理指标，不含样本能见度`,
  help = '该指数只描述当前 Reddit 观察样本，不代表市场份额、销售结果或 NPS。',
  comparisonLabel,
  changeSuffix = '%',
  scoreStatusLabel,
}: BrandScoreCardProps) {
  const TrendIcon = trendConfig[trend].icon;
  const scoreLevel = overallScore === null ? '当前不可计算' : overallScore >= 80 ? '优秀' : overallScore >= 60 ? '良好' : '需改进';
  const scoreLevelColor = overallScore === null ? 'text-foreground-muted' : overallScore >= 80 ? 'text-status-success' : overallScore >= 60 ? 'text-status-warning' : 'text-status-error';
  const scoreForRing = overallScore ?? 0;
  const hasDimensions = data.length > 0;
  const overallHelp = helpContent(help);

  return (
    <div className="card p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-icon bg-primary-light flex items-center justify-center">
            <Star className="w-5 h-5 text-primary" strokeWidth={1.5} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-h3 text-foreground">{title}</h3>
              <MetricHelpPopover label={title} align="left" {...overallHelp} />
            </div>
            <p className="text-caption text-foreground-muted">{subtitle}</p>
          </div>
        </div>
        {change !== null && trend !== 'unavailable' && (
          <div className="text-right">
            <span className={`inline-flex items-center gap-0.5 text-tiny font-medium px-2 py-1 rounded-badge ${trendConfig[trend].color} bg-surface-tertiary`}>
              <TrendIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
              {`${trend === 'up' ? '+' : trend === 'down' ? '-' : ''}${Math.abs(change)}${changeSuffix}`}
            </span>
            {comparisonLabel && <p className="mt-1 text-tiny text-foreground-muted">{comparisonLabel}</p>}
          </div>
        )}
      </div>

      <div className={`flex flex-col gap-6 ${hasDimensions ? 'lg:flex-row' : ''}`}>
        {/* Left: Overall Score */}
        <div className={`flex flex-col items-center justify-center flex-shrink-0 ${hasDimensions ? 'lg:w-48' : ''}`}>
          <div className="relative w-32 h-32 flex items-center justify-center">
            <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
              <circle
                cx="60"
                cy="60"
                r="52"
                fill="none"
                stroke={NEUTRAL_COLORS.gray100}
                strokeWidth="8"
              />
              <circle
                cx="60"
                cy="60"
                r="52"
                fill="none"
                stroke={overallScore === null ? NEUTRAL_COLORS.gray300 : overallScore >= 80 ? SENTIMENT_COLORS.positive : overallScore >= 60 ? SENTIMENT_COLORS.neutral : BRAND_COLORS.primary}
                strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={`${scoreForRing * 3.27} 326.73`}
                className="transition-all duration-1000"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span
                className="text-[32px] font-bold text-foreground leading-none"
                data-testid="brand-health-overall-score"
                data-score={overallScore ?? undefined}
              >
                {overallScore ?? '—'}
              </span>
              <span className="text-tiny text-foreground-muted mt-1">满分 100</span>
            </div>
          </div>
          <span className={`text-body-sm font-medium mt-3 ${scoreStatusLabel ? 'text-foreground-secondary' : scoreLevelColor}`}>
            {scoreStatusLabel ?? scoreLevel}
          </span>
        </div>

        {hasDimensions && (
          /* Right: Radar Chart + Dimensions */
          <div className="flex-1 min-w-0">
            <div
              className="h-[270px] w-full rounded-card bg-gradient-to-b from-primary-light/45 to-white px-2 py-1"
              role="img"
              aria-label={`${brandName} 品牌健康四维雷达`}
              data-testid="brand-health-radar"
              data-radar-grid="circle"
            >
              <span className="sr-only" data-testid="brand-health-radar-grid" data-grid-type="circle">圆形坐标网格</span>
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={data} cx="50%" cy="50%" outerRadius="68%">
                  <defs>
                    <linearGradient id="brand-health-radar-fill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={BRAND_COLORS.primary} stopOpacity={0.34} />
                      <stop offset="100%" stopColor={BRAND_COLORS.secondary} stopOpacity={0.08} />
                    </linearGradient>
                  </defs>
                  <PolarGrid
                    gridType="circle"
                    stroke={NEUTRAL_COLORS.gray300}
                    strokeOpacity={0.9}
                  />
                  <PolarAngleAxis
                    dataKey="dimension"
                    tick={{ fontSize: 12, fill: NEUTRAL_COLORS.gray700, fontFamily: 'inherit', fontWeight: 600 }}
                  />
                  <PolarRadiusAxis
                    angle={30}
                    domain={[0, 100]}
                    axisLine={false}
                    tick={{ fontSize: 10, fill: NEUTRAL_COLORS.gray400 }}
                    tickCount={5}
                  />
                  <Radar
                    name={brandName}
                    dataKey="score"
                    stroke={BRAND_COLORS.primary}
                    fill="url(#brand-health-radar-fill)"
                    fillOpacity={1}
                    strokeWidth={2.5}
                    dot={{ r: 3.5, fill: BRAND_COLORS.primary, stroke: NEUTRAL_COLORS.white, strokeWidth: 2 }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>

            {/* Dimension List */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-4">
              {data.map((item, index) => (
                <div key={item.dimension} className="flex items-center justify-between px-3 py-2 rounded-icon bg-surface-tertiary">
                  <span className="flex items-center gap-1 text-tiny text-foreground-secondary">
                    {item.dimension}
                    {item.help && (
                      <MetricHelpPopover label={item.dimension} align={index < 2 ? 'left' : 'right'} {...helpContent(item.help)} />
                    )}
                  </span>
                  <span
                    className={`text-tiny font-semibold ${
                    item.score === null ? 'text-foreground-muted' : item.score >= 80 ? 'text-status-success' : item.score >= 60 ? 'text-foreground' : 'text-status-error'
                    }`}
                    data-dimension-score={item.score ?? undefined}
                  >
                    {item.score ?? '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
