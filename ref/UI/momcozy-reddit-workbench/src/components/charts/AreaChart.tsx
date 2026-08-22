import {
  AreaChart as ReAreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { useState, useCallback } from 'react';
import { BRAND_COLORS } from '../../constants/colors';
import type { CustomTooltipProps, RechartsMouseEvent } from './types';

interface AreaChartProps {
  data: { label: string; value: number }[];
  title?: string;
  color?: string;
  height?: number;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    const value = payload[0].value;
    return (
      <div className="bg-white border border-border-divider rounded-card shadow-card-hover px-4 py-3">
        <p className="text-caption text-foreground-muted mb-1">{label}</p>
        <p className="text-body font-semibold text-foreground">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </p>
      </div>
    );
  }
  return null;
}

export default function AreaChart({
  data,
  title,
  color = BRAND_COLORS.primary,
  height = 280,
}: AreaChartProps) {
  const gradientId = `areaGradient-${color.replace('#', '')}`;
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const handleMouseMove = useCallback((state: RechartsMouseEvent) => {
    if (state && typeof state.activeTooltipIndex === 'number') {
      setActiveIndex(state.activeTooltipIndex);
    } else {
      setActiveIndex(null);
    }
  }, []);

  const handleMouseLeave = useCallback(() => {
    setActiveIndex(null);
  }, []);

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
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.4} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
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
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              fill={`url(#${gradientId})`}
              strokeWidth={activeIndex !== null ? 3 : 2}
              fillOpacity={1}
              animationDuration={800}
              animationEasing="ease-out"
              activeDot={{
                r: 5,
                stroke: '#fff',
                strokeWidth: 2,
                fill: color,
              }}
              dot={{
                r: 3,
                stroke: '#fff',
                strokeWidth: 1.5,
                fill: color,
              }}
            />
          </ReAreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
