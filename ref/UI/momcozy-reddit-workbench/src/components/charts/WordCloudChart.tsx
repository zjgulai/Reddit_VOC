import { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { CHART_PALETTE } from '../../constants/colors';

export interface WordCloudItem {
  text: string;
  value: number;
  color?: string;
  /** 来源帖子 ID 列表（点击词云可追踪到具体帖子） */
  sourcePostIds?: string[];
  /** 情感分析置信度 0-1 */
  sentimentConfidence?: number;
}

interface WordCloudChartProps {
  data: WordCloudItem[];
  title?: string;
  height?: number;
  onWordClick?: (item: WordCloudItem) => void;
}

const DEFAULT_COLORS = CHART_PALETTE.slice(0, 10);

/** Compute a spiral layout for word cloud */
function computeLayout(
  items: WordCloudItem[],
  width: number,
  height: number,
  padding = 4
): Array<WordCloudItem & { x: number; y: number; fontSize: number; width: number; height: number; color: string }> {
  if (!items.length || width <= 0 || height <= 0) return [];

  const maxVal = Math.max(...items.map((d) => d.value));
  const minVal = Math.min(...items.map((d) => d.value));
  const valRange = maxVal - minVal || 1;

  const minFont = 12;
  const maxFont = Math.min(48, height * 0.18);

  // Sort descending so larger words are placed first
  const sorted = [...items].sort((a, b) => b.value - a.value);

  const placed: Array<{
    x: number; y: number; w: number; h: number;
    text: string; value: number; fontSize: number; color: string;
  }> = [];

  const centerX = width / 2;
  const centerY = height / 2;

  for (let idx = 0; idx < sorted.length; idx++) {
    const item = sorted[idx];
    const fontSize = minFont + ((item.value - minVal) / valRange) * (maxFont - minFont);
    // Estimate text size: each char roughly 0.6 * fontSize width
    const textWidth = item.text.length * fontSize * 0.6;
    const textHeight = fontSize * 1.2;

    let bestX = centerX;
    let bestY = centerY;
    let found = false;

    // Try spiral from center
    const maxRadius = Math.min(width, height) / 2;
    const angleStep = 0.5;
    const radiusStep = 2;

    for (let angle = 0; angle < 1000; angle += angleStep) {
      const radius = radiusStep * angle;
      if (radius > maxRadius) break;

      const x = centerX + radius * Math.cos(angle) - textWidth / 2;
      const y = centerY + radius * Math.sin(angle) * 0.8 - textHeight / 2;

      const rect = {
        x: x - padding,
        y: y - padding,
        w: textWidth + padding * 2,
        h: textHeight + padding * 2,
      };

      // Check bounds
      if (rect.x < 0 || rect.x + rect.w > width || rect.y < 0 || rect.y + rect.h > height) {
        continue;
      }

      // Check overlap
      const overlap = placed.some((p) =>
        rect.x < p.x + p.w && rect.x + rect.w > p.x &&
        rect.y < p.y + p.h && rect.y + rect.h > p.y
      );

      if (!overlap) {
        bestX = x;
        bestY = y;
        found = true;
        break;
      }
    }

    if (!found) {
      // Fallback: place anywhere that fits
      bestX = centerX - textWidth / 2 + (Math.random() - 0.5) * width * 0.6;
      bestY = centerY - textHeight / 2 + (Math.random() - 0.5) * height * 0.6;
    }

    placed.push({
      x: bestX,
      y: bestY + textHeight * 0.75, // baseline offset for SVG text
      w: textWidth + padding * 2,
      h: textHeight + padding * 2,
      text: item.text,
      value: item.value,
      fontSize,
      color: item.color || DEFAULT_COLORS[idx % DEFAULT_COLORS.length],
    });
  }

  return placed.map((p) => ({
    text: p.text,
    value: p.value,
    x: p.x + p.w / 2 - padding,
    y: p.y,
    fontSize: p.fontSize,
    width: p.w,
    height: p.h,
    color: p.color,
  }));
}

export default function WordCloudChart({ data, title, height = 320, onWordClick }: WordCloudChartProps) {
  const [hoveredText, setHoveredText] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);
  const [containerWidth, setContainerWidth] = useState(800);
  const containerDivRef = useRef<HTMLDivElement | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  useEffect(() => {
    const node = containerDivRef.current;
    if (!node) return;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    resizeObserver.observe(node);
    setContainerWidth(node.clientWidth);
    resizeObserverRef.current = resizeObserver;

    return () => {
      resizeObserver.disconnect();
      resizeObserverRef.current = null;
    };
  }, []);

  const layout = useMemo(() => {
    return computeLayout(data, containerWidth, height);
  }, [data, containerWidth, height]);

  const hoveredItem = useMemo(() => {
    return data.find((d) => d.text === hoveredText) || null;
  }, [hoveredText, data]);

  const handleClick = useCallback(
    (item: WordCloudItem) => {
      if (onWordClick) onWordClick(item);
    },
    [onWordClick]
  );

  const handleMouseMove = useCallback((e: React.MouseEvent<SVGTextElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setTooltipPos({ x: e.clientX - rect.left + 12, y: e.clientY - rect.top - 8 });
  }, []);

  return (
    <div className="relative">
      {title && (
        <div className="text-body font-medium text-foreground mb-4">{title}</div>
      )}
      <div ref={containerDivRef} style={{ height, width: '100%' }} className="relative">
        <svg width={containerWidth} height={height} style={{ display: 'block' }}>
          {layout.map((item) => {
            const isHovered = hoveredText === item.text;
            return (
              <text
                key={item.text}
                x={item.x}
                y={item.y}
                textAnchor="middle"
                dominantBaseline="middle"
                fill={item.color}
                fontSize={item.fontSize}
                fontWeight={isHovered ? 700 : 600}
                style={{
                  cursor: 'pointer',
                  transition: 'all 0.25s ease',
                  filter: isHovered ? 'brightness(1.15)' : 'none',
                  opacity: hoveredText && !isHovered ? 0.45 : 1,
                  userSelect: 'none',
                }}
                onMouseEnter={() => setHoveredText(item.text)}
                onMouseLeave={() => { setHoveredText(null); setTooltipPos(null); }}
                onMouseMove={handleMouseMove}
                onClick={() => handleClick(item)}
              >
                {item.text}
              </text>
            );
          })}
        </svg>

        {/* Tooltip */}
        {hoveredItem && tooltipPos && (
          <div
            className="absolute z-10 pointer-events-none bg-white rounded-xl shadow-elevated border border-border-divider px-3 py-2 text-tiny animate-fade-in"
            style={{
              left: Math.min(tooltipPos.x, containerWidth - 180),
              top: Math.max(tooltipPos.y - 60, 0),
              minWidth: 140,
            }}
          >
            <div className="font-semibold text-foreground mb-0.5">{hoveredItem.text}</div>
            <div className="text-foreground-muted">频次: {hoveredItem.value}</div>
            {typeof hoveredItem.sentimentConfidence === 'number' && (
              <div className="text-foreground-muted">
                置信度: {(hoveredItem.sentimentConfidence * 100).toFixed(0)}%
              </div>
            )}
            {hoveredItem.sourcePostIds && hoveredItem.sourcePostIds.length > 0 && (
              <div className="text-foreground-muted">
                来源帖子: {hoveredItem.sourcePostIds.length} 条
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
