import {
  PieChart as RePieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Sector,
} from 'recharts';
import { useState, useCallback } from 'react';
import { CHART_PALETTE } from '../../constants/colors';
import type { CustomTooltipProps, ActiveShapeProps, PieEventData, LegendFormatterEntry } from './types';

interface PieChartProps {
  data: { name: string; value: number; color?: string }[];
  title?: string;
  showLegend?: boolean;
  innerRadius?: number;
  height?: number;
  onDataClick?: (data: { name: string; value: number; color?: string }) => void;
}

const DEFAULT_COLORS = CHART_PALETTE.slice(0, 6);

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    const p = payload[0];
    const name = p.name as string;
    const value = p.value as number;
    const total = p.payload?.total as number | undefined;
    const percent = total && total > 0 ? Math.round((value / total) * 100) : undefined;

    return (
      <div className="bg-white border border-border-divider rounded-card shadow-card-hover px-4 py-3 min-w-[120px]">
        <p className="text-caption text-foreground-muted mb-1">{name}</p>
        <p className="text-body font-semibold text-foreground">
          {value.toLocaleString()}
          {percent !== undefined && (
            <span className="text-caption text-foreground-muted ml-1">({percent}%)</span>
          )}
        </p>
      </div>
    );
  }
  return null;
}

function ActiveShape(props: ActiveShapeProps) {
  const {
    cx,
    cy,
    innerRadius,
    outerRadius,
    startAngle,
    endAngle,
    fill,
  } = props;

  return (
    <g>
      <Sector
        cx={cx}
        cy={cy}
        innerRadius={innerRadius}
        outerRadius={(outerRadius ?? 0) + 6}
        startAngle={startAngle}
        endAngle={endAngle}
        fill={fill}
        style={{ transition: 'all 0.25s ease' }}
      />
      <Sector
        cx={cx}
        cy={cy}
        innerRadius={innerRadius}
        outerRadius={(outerRadius ?? 0) + 12}
        startAngle={startAngle}
        endAngle={endAngle}
        fill={fill}
        opacity={0.12}
        style={{ pointerEvents: 'none' }}
      />
    </g>
  );
}

export default function PieChart({
  data,
  title,
  showLegend = true,
  innerRadius = 0.5,
  height = 280,
  onDataClick,
}: PieChartProps) {
  const parsedInnerRadius =
    typeof innerRadius === 'number' && innerRadius < 1 ? `${innerRadius * 100}%` : innerRadius;

  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const total = data.reduce((sum, d) => sum + d.value, 0);
  const enrichedData = data.map((d) => ({ ...d, total }));

  const onPieEnter = useCallback((_: PieEventData, index: number) => {
    setActiveIndex(index);
  }, []);

  const onPieLeave = useCallback(() => {
    setActiveIndex(null);
  }, []);

  const handleClick = useCallback((_: PieEventData, index: number) => {
    const d = data[index];
    if (d && onDataClick) onDataClick(d);
  }, [data, onDataClick]);

  return (
    <div>
      {title && (
        <div className="text-body font-medium text-foreground mb-4">{title}</div>
      )}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <RePieChart>
            <Pie
              data={enrichedData}
              cx="50%"
              cy="50%"
              innerRadius={parsedInnerRadius}
              outerRadius="80%"
              paddingAngle={2}
              dataKey="value"
              nameKey="name"
              animationDuration={800}
              animationEasing="ease-out"
              activeShape={ActiveShape}
              onMouseEnter={onPieEnter}
              onMouseLeave={onPieLeave}
              onClick={handleClick}
              style={{ cursor: 'pointer' }}
            >
              {enrichedData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.color || DEFAULT_COLORS[index % DEFAULT_COLORS.length]}
                  stroke="#fff"
                  strokeWidth={2}
                  style={{
                    transition: 'all 0.25s ease',
                    opacity: activeIndex === null || activeIndex === index ? 1 : 0.5,
                  }}
                />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            {showLegend && (
              <Legend
                verticalAlign="bottom"
                height={36}
                iconType="circle"
                iconSize={8}
                formatter={(value: string, entry: LegendFormatterEntry) => (
                  <span
                    style={{
                      color: entry.color || '#374151',
                      fontSize: '12px',
                      marginLeft: '4px',
                    }}
                  >
                    {value}
                  </span>
                )}
              />
            )}
          </RePieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
