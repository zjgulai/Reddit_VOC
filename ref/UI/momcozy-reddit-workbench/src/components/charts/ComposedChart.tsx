import { BRAND_COLORS } from '../../constants/colors';
import { useId } from 'react';
import {
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ComposedChart as ReComposedChart,
} from 'recharts';

interface ComposedChartProps {
  data: { label: string; barValue: number; lineValue: number; barValue2?: number }[];
  title?: string;
  height?: number;
  barColor?: string;
  secondBarColor?: string;
  lineColor?: string;
  barName?: string;
  secondBarName?: string;
  lineName?: string;
  leftAxisLabel?: string;
  rightAxisLabel?: string;
  ariaLabel?: string;
}

export default function ComposedChart({
  data,
  title,
  height = 280,
  barColor = BRAND_COLORS.primary,
  secondBarColor = BRAND_COLORS.secondary,
  lineColor = BRAND_COLORS.secondary,
  barName = '数量',
  secondBarName,
  lineName = '增长率',
  leftAxisLabel,
  rightAxisLabel,
  ariaLabel,
}: ComposedChartProps) {
  const gradientId = useId().replaceAll(':', '');
  const hasSecondBar = Boolean(secondBarName) && data.some((item) => item.barValue2 !== undefined);

  return (
    <div>
      {title && <div className="text-body font-medium text-foreground mb-4">{title}</div>}
      <div
        style={{ height }}
        role="img"
        aria-label={ariaLabel ?? `${barName}与${lineName}双坐标趋势图`}
        className="rounded-card bg-gradient-to-b from-primary-light/25 to-white px-1 pt-3"
        data-testid="dual-axis-trend-chart"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ReComposedChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 4 }}>
            <defs>
              <linearGradient id={`${gradientId}-primary`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={barColor} stopOpacity={0.95} />
                <stop offset="100%" stopColor={barColor} stopOpacity={0.42} />
              </linearGradient>
              <linearGradient id={`${gradientId}-secondary`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={secondBarColor} stopOpacity={0.82} />
                <stop offset="100%" stopColor={secondBarColor} stopOpacity={0.28} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="4 4" stroke="#EDEDED" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#6B6B6B' }} tickLine={false} axisLine={{ stroke: '#EDEDED' }} />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 11, fill: '#6B6B6B' }}
              tickLine={false}
              axisLine={false}
              width={leftAxisLabel ? 48 : 36}
              label={leftAxisLabel ? { value: leftAxisLabel, angle: -90, position: 'insideLeft', fill: '#9A9A9A', fontSize: 11 } : undefined}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 11, fill: '#6B6B6B' }}
              tickLine={false}
              axisLine={false}
              width={rightAxisLabel ? 48 : 36}
              label={rightAxisLabel ? { value: rightAxisLabel, angle: 90, position: 'insideRight', fill: '#9A9A9A', fontSize: 11 } : undefined}
            />
            <Tooltip
              cursor={{ fill: '#FFF5EE', opacity: 0.55 }}
              contentStyle={{ borderRadius: 12, borderColor: '#EDEDED', boxShadow: '0 8px 24px rgba(0,0,0,0.08)' }}
            />
            <Legend iconType="circle" wrapperStyle={{ paddingTop: 8, fontSize: 12 }} />
            <Bar
              yAxisId="left"
              dataKey="barValue"
              name={barName}
              fill={`url(#${gradientId}-primary)`}
              radius={[6, 6, 0, 0]}
              maxBarSize={42}
            />
            {hasSecondBar && (
              <Bar
                yAxisId="left"
                dataKey="barValue2"
                name={secondBarName}
                fill={`url(#${gradientId}-secondary)`}
                radius={[6, 6, 0, 0]}
                maxBarSize={42}
              />
            )}
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="lineValue"
              name={lineName}
              stroke={lineColor}
              strokeWidth={2.5}
              dot={{ r: 3.5, fill: '#FFFFFF', stroke: lineColor, strokeWidth: 2 }}
              activeDot={{ r: 5, fill: lineColor, stroke: '#FFFFFF', strokeWidth: 2 }}
            />
          </ReComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
