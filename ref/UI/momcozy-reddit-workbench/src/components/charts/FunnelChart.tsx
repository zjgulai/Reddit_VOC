import {
  FunnelChart as ReFunnelChart,
  Funnel,
  Tooltip,
  ResponsiveContainer,
  LabelList,
  Cell,
} from 'recharts';
import { useState, useCallback, useRef, useEffect } from 'react';
import { CHART_PALETTE } from '../../constants/colors';
import type { CustomTooltipProps } from './types';

export interface FunnelChartDatum {
  name: string;
  value: number;
  color?: string;
}

interface FunnelChartProps {
  data: FunnelChartDatum[];
  title?: string;
  height?: number;
  onDataClick?: (data: FunnelChartDatum) => void;
}

const DEFAULT_COLORS = CHART_PALETTE.slice(0, 6);

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    const p = payload[0];
    const name = p?.payload?.name as string;
    const value = p?.payload?.value as number;
    const total = p?.payload?.total as number | undefined;
    const percent = total && total > 0 ? Math.round((value / total) * 100) : undefined;
    const prevValue = p?.payload?.prevValue as number | undefined;
    const conversionRate = prevValue && prevValue > 0 ? Math.round((value / prevValue) * 100) : undefined;

    return (
      <div className="bg-white border border-border-divider rounded-card shadow-card-hover px-4 py-3 min-w-[140px]">
        <p className="text-caption text-foreground-muted mb-1">{name}</p>
        <p className="text-body font-semibold text-foreground">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </p>
        {percent !== undefined && (
          <p className="text-caption text-foreground-muted mt-1">
            占总比 {percent}%
          </p>
        )}
        {conversionRate !== undefined && (
          <p className="text-caption text-status-success mt-0.5">
            转化率 {conversionRate}%
          </p>
        )}
      </div>
    );
  }
  return null;
}

export default function FunnelChart({ data, title, height = 320, onDataClick }: FunnelChartProps) {
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

  const total = data.reduce((sum, d) => sum + d.value, 0);

  // Enrich data with total, prevValue for tooltip conversion rate, and color
  const enrichedData = data.map((d, i) => ({
    ...d,
    total,
    prevValue: i > 0 ? data[i - 1].value : undefined,
    fill: d.color || DEFAULT_COLORS[i % DEFAULT_COLORS.length],
  }));

  const handleClick = useCallback(
    (_props: unknown, index: number) => {
      setClickedIndex(index);
      const d = data[index];
      if (d && onDataClick) onDataClick(d);
      clickTimerRef.current = setTimeout(() => setClickedIndex(null), 600);
    },
    [data, onDataClick]
  );

  const handleMouseEnter = useCallback((_: unknown, index: number) => {
    setHoveredIndex(index);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setHoveredIndex(null);
  }, []);

  return (
    <div>
      {title && (
        <div className="text-body font-medium text-foreground mb-4">{title}</div>
      )}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ReFunnelChart>
            <Tooltip content={<CustomTooltip />} />
            <Funnel
              dataKey="value"
              data={enrichedData}
              isAnimationActive
              animationDuration={800}
              animationEasing="ease-out"
              onClick={handleClick}
              onMouseEnter={handleMouseEnter}
              onMouseLeave={handleMouseLeave}
            >
              {enrichedData.map((_entry: FunnelChartDatum, index: number) => {
                const isHovered = hoveredIndex === index;
                const isClicked = clickedIndex === index;
                const opacity = hoveredIndex === null ? 1 : isHovered ? 1 : 0.5;

                return (
                  <Cell
                    key={`cell-${index}`}
                    fillOpacity={isClicked ? 0.7 : opacity}
                    stroke={isClicked ? enrichedData[index].fill : '#fff'}
                    strokeWidth={isClicked ? 2 : 1}
                    style={{
                      transition: 'all 0.25s ease',
                      filter: isHovered ? 'brightness(1.08)' : 'none',
                      cursor: onDataClick ? 'pointer' : 'default',
                    }}
                  />
                );
              })}
              <LabelList
                position="inside"
                fill="#fff"
                stroke="none"
                dataKey="name"
                className="text-tiny"
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  pointerEvents: 'none',
                }}
              />
            </Funnel>
          </ReFunnelChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
