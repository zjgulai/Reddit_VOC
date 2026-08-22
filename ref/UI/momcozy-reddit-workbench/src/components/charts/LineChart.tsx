import {
  LineChart as ReLineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { useState, useCallback } from 'react';
import { BRAND_COLORS } from '../../constants/colors';
import type { CustomTooltipProps, RechartsMouseEvent, LineActiveDotProps } from './types';

interface LineChartProps {
  data: { label: string; value: number }[];
  title?: string;
  color?: string;
  height?: number;
  showDots?: boolean;
  onDataClick?: (data: { label: string; value: number }) => void;
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

export default function LineChart({
  data,
  title,
  color = BRAND_COLORS.primary,
  height = 280,
  showDots = true,
  onDataClick,
}: LineChartProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [clickedIndex, setClickedIndex] = useState<number | null>(null);

  const handleClick = useCallback(
    (_props: unknown, index: number) => {
      setClickedIndex(index);
      const d = data[index];
      if (d && onDataClick) onDataClick(d);
      setTimeout(() => setClickedIndex(null), 600);
    },
    [data, onDataClick]
  );

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

  const renderActiveDot = useCallback((props: LineActiveDotProps) => {
    const { cx = 0, cy = 0, index = 0 } = props;
    const isClicked = clickedIndex === index;
    return (
      <g>
        <circle
          cx={cx}
          cy={cy}
          r={isClicked ? 7 : 5}
          stroke="#fff"
          strokeWidth={isClicked ? 3 : 2}
          fill={color}
          style={{
            transition: 'all 0.2s ease',
            cursor: 'pointer',
            filter: isClicked ? 'drop-shadow(0 2px 4px rgba(0,0,0,0.15))' : 'none',
          }}
          onClick={(e) => handleClick(e, index)}
        />
        {isClicked && (
          <circle
            cx={cx}
            cy={cy}
            r={12}
            fill={color}
            opacity={0.15}
            style={{ pointerEvents: 'none' }}
          />
        )}
      </g>
    );
  }, [clickedIndex, color, handleClick]);

  return (
    <div>
      {title && (
        <div className="text-body font-medium text-foreground mb-4">{title}</div>
      )}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReLineChart
            data={data}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
          >
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
            <Line
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={activeIndex !== null ? 3 : 2}
              dot={
                showDots
                  ? {
                      r: 3,
                      stroke: '#fff',
                      strokeWidth: 1.5,
                      fill: color,
                    }
                  : false
              }
              activeDot={renderActiveDot}
              animationDuration={800}
              animationEasing="ease-out"
              style={{
                transition: 'stroke-width 0.2s ease',
              }}
            />
          </ReLineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
