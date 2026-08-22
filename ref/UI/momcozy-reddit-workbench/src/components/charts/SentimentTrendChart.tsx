import {
  AreaChart as ReAreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { useState, useCallback } from 'react';
import { SENTIMENT_COLORS } from '../../constants/colors';
import type { RechartsMouseEvent } from './types';

export interface SentimentTrendDataPoint {
  label: string;
  positive: number;
  negative: number;
  neutral: number;
}

interface SentimentTrendChartProps {
  data: SentimentTrendDataPoint[];
  title?: string;
  height?: number;
  showLegend?: boolean;
  colors?: {
    positive?: string;
    negative?: string;
    neutral?: string;
  };
}

const DEFAULT_COLORS = {
  positive: SENTIMENT_COLORS.positive,
  negative: SENTIMENT_COLORS.negative,
  neutral: SENTIMENT_COLORS.neutral,
};

interface TooltipPayloadItem {
  color: string;
  dataKey: string;
  name: string;
  value: number;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const total = payload.reduce((sum, entry) => sum + (entry.value || 0), 0);

  return (
    <div className="bg-white border border-border-divider rounded-card shadow-card-hover px-4 py-3 min-w-[180px]">
      <p className="text-caption text-foreground-muted mb-2 font-medium">{label}</p>
      <div className="space-y-1.5">
        {payload.map((entry) => {
          const percent = total > 0 ? Math.round((entry.value / total) * 100) : 0;
          return (
            <div key={entry.dataKey} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: entry.color }}
                />
                <span className="text-tiny text-foreground-secondary">
                  {entry.name}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-tiny font-semibold text-foreground">
                  {entry.value}
                </span>
                <span className="text-[11px] text-foreground-muted w-8 text-right">
                  {percent}%
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 pt-2 border-t border-border-divider">
        <div className="flex items-center justify-between">
          <span className="text-tiny text-foreground-muted">总计</span>
          <span className="text-tiny font-semibold text-foreground">{total}</span>
        </div>
      </div>
    </div>
  );
}

function CustomLegend({ payload }: { payload?: Array<{ color: string; value: string }> }) {
  if (!payload) return null;
  const labelMap: Record<string, string> = {
    positive: '正面',
    negative: '负面',
    neutral: '中性',
  };
  return (
    <div className="flex items-center justify-center gap-4 mt-3">
      {payload.map((entry) => (
        <div key={entry.value} className="flex items-center gap-1.5">
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-tiny text-foreground-muted">
            {labelMap[entry.value] || entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function SentimentTrendChart({
  data,
  title,
  height = 280,
  showLegend = true,
  colors: customColors,
}: SentimentTrendChartProps) {
  const colors = { ...DEFAULT_COLORS, ...customColors };
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const handleMouseMove = useCallback(
    (state: RechartsMouseEvent) => {
      if (state && typeof state.activeTooltipIndex === 'number') {
        setActiveIndex(state.activeTooltipIndex);
      } else {
        setActiveIndex(null);
      }
    },
    []
  );

  const handleMouseLeave = useCallback(() => {
    setActiveIndex(null);
  }, []);

  const gradientIds = {
    positive: `grad-positive-${colors.positive.replace('#', '')}`,
    negative: `grad-negative-${colors.negative.replace('#', '')}`,
    neutral: `grad-neutral-${colors.neutral.replace('#', '')}`,
  };

  return (
    <div>
      {title && (
        <div className="text-body font-medium text-foreground mb-4">{title}</div>
      )}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReAreaChart
            data={data}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
          >
            <defs>
              <linearGradient id={gradientIds.positive} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.positive} stopOpacity={0.35} />
                <stop offset="100%" stopColor={colors.positive} stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id={gradientIds.neutral} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.neutral} stopOpacity={0.35} />
                <stop offset="100%" stopColor={colors.neutral} stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id={gradientIds.negative} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.negative} stopOpacity={0.35} />
                <stop offset="100%" stopColor={colors.negative} stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 12, fill: '#6B7280' }}
              axisLine={{ stroke: '#E5E7EB' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 12, fill: '#6B7280' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} />
            {showLegend && <Legend content={<CustomLegend />} />}
            <Area
              type="monotone"
              dataKey="positive"
              name="positive"
              stackId="1"
              stroke={colors.positive}
              fill={`url(#${gradientIds.positive})`}
              strokeWidth={activeIndex !== null ? 3 : 2}
              animationDuration={800}
              animationEasing="ease-out"
              activeDot={{
                r: 5,
                stroke: '#fff',
                strokeWidth: 2,
                fill: colors.positive,
              }}
              dot={{
                r: 3,
                stroke: '#fff',
                strokeWidth: 1.5,
                fill: colors.positive,
              }}
            />
            <Area
              type="monotone"
              dataKey="neutral"
              name="neutral"
              stackId="1"
              stroke={colors.neutral}
              fill={`url(#${gradientIds.neutral})`}
              strokeWidth={activeIndex !== null ? 3 : 2}
              animationDuration={800}
              animationEasing="ease-out"
              activeDot={{
                r: 5,
                stroke: '#fff',
                strokeWidth: 2,
                fill: colors.neutral,
              }}
              dot={{
                r: 3,
                stroke: '#fff',
                strokeWidth: 1.5,
                fill: colors.neutral,
              }}
            />
            <Area
              type="monotone"
              dataKey="negative"
              name="negative"
              stackId="1"
              stroke={colors.negative}
              fill={`url(#${gradientIds.negative})`}
              strokeWidth={activeIndex !== null ? 3 : 2}
              animationDuration={800}
              animationEasing="ease-out"
              activeDot={{
                r: 5,
                stroke: '#fff',
                strokeWidth: 2,
                fill: colors.negative,
              }}
              dot={{
                r: 3,
                stroke: '#fff',
                strokeWidth: 1.5,
                fill: colors.negative,
              }}
            />
          </ReAreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
