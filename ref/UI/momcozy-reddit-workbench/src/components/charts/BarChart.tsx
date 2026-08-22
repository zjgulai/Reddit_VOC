import {
  BarChart as ReBarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { useState, useCallback, useRef, useEffect } from 'react';
import { CHART_PALETTE } from '../../constants/colors';
import type { CustomTooltipProps } from './types';

interface BarChartProps {
  data: { name: string; value: number; color?: string }[];
  title?: string;
  height?: number;
  onDataClick?: (data: { name: string; value: number; color?: string }) => void;
}

const DEFAULT_COLORS = CHART_PALETTE.slice(0, 6);

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

export default function BarChart({ data, title, height = 280, onDataClick }: BarChartProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [clickedIndex, setClickedIndex] = useState<number | null>(null);
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (clickTimerRef.current) {
        clearTimeout(clickTimerRef.current);
        clickTimerRef.current = null;
      }
    };
  }, []);

  const handleClick = useCallback(
    (_props: unknown, index: number) => {
      setClickedIndex(index);
      const d = data[index];
      if (d && onDataClick) onDataClick(d);
      clickTimerRef.current = setTimeout(() => setClickedIndex(null), 600);
    },
    [data, onDataClick]
  );

  return (
    <div>
      {title && (
        <div className="text-body font-medium text-foreground mb-4">{title}</div>
      )}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReBarChart
            data={data}
            margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
            onMouseLeave={() => setHoveredIndex(null)}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 12, fill: '#6B7280' }}
              axisLine={{ stroke: '#E5E7EB' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 12, fill: '#6B7280' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)', radius: 4 }} />
            <Bar
              dataKey="value"
              radius={[4, 4, 0, 0]}
              animationDuration={800}
              animationEasing="ease-out"
              onMouseEnter={(_, index) => setHoveredIndex(index)}
            >
              {data.map((entry, index) => {
                const baseColor = entry.color || DEFAULT_COLORS[index % DEFAULT_COLORS.length];
                const isHovered = hoveredIndex === index;
                const isClicked = clickedIndex === index;
                const opacity = hoveredIndex === null ? 1 : isHovered ? 1 : 0.5;

                return (
                  <Cell
                    key={`cell-${index}`}
                    fill={baseColor}
                    fillOpacity={isClicked ? 0.7 : opacity}
                    stroke={isClicked ? baseColor : 'transparent'}
                    strokeWidth={isClicked ? 2 : 0}
                    style={{
                      transition: 'all 0.25s ease',
                      filter: isHovered ? 'brightness(1.1)' : 'none',
                      cursor: 'pointer',
                    }}
                    onClick={(e) => handleClick(e, index)}
                  />
                );
              })}
            </Bar>
          </ReBarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
