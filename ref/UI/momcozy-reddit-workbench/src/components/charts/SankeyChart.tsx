import { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { CHART_PALETTE } from '../../constants/colors';

export interface SankeyNode {
  id: string;
  name: string;
  color?: string;
}

export interface SankeyLink {
  source: string;
  target: string;
  value: number;
}

interface SankeyChartProps {
  nodes: SankeyNode[];
  links: SankeyLink[];
  title?: string;
  height?: number;
  nodeWidth?: number;
  nodePadding?: number;
  onNodeClick?: (node: SankeyNode) => void;
  onLinkClick?: (link: SankeyLink & { sourceName: string; targetName: string }) => void;
}

const DEFAULT_NODE_COLORS = CHART_PALETTE.slice(0, 10);

/** Simple sankey layout: distribute nodes into columns, then compute y positions */
function computeSankeyLayout(
  nodes: SankeyNode[],
  links: SankeyLink[],
  width: number,
  height: number,
  nodeWidth: number,
  nodePadding: number
) {
  if (!nodes.length || !links.length || width <= 0 || height <= 0) {
    return { nodeRects: [] as Array<SankeyNode & { x: number; y: number; w: number; h: number; color: string; column: number }>, linkPaths: [] as Array<{ d: string; fill: string; opacity: number; sourceId: string; targetId: string; value: number; sourceName: string; targetName: string }> };
  }

  // Build adjacency
  const incoming = new Map<string, SankeyLink[]>();
  const outgoing = new Map<string, SankeyLink[]>();
  const nodeSet = new Set(nodes.map((n) => n.id));

  for (const link of links) {
    if (!nodeSet.has(link.source) || !nodeSet.has(link.target)) continue;
    if (!outgoing.has(link.source)) outgoing.set(link.source, []);
    if (!incoming.has(link.target)) incoming.set(link.target, []);
    outgoing.get(link.source)!.push(link);
    incoming.get(link.target)!.push(link);
  }

  // Assign columns by BFS from sources
  const columnMap = new Map<string, number>();
  const sources = nodes.filter((n) => !incoming.has(n.id));
  const queue = [...sources];
  for (const s of sources) columnMap.set(s.id, 0);

  while (queue.length) {
    const curr = queue.shift()!;
    const col = columnMap.get(curr.id)!;
    for (const link of outgoing.get(curr.id) || []) {
      const next = link.target;
      if (!columnMap.has(next) || columnMap.get(next)! < col + 1) {
        columnMap.set(next, col + 1);
        queue.push(nodes.find((n) => n.id === next)!);
      }
    }
  }

  // Ensure all nodes have a column
  let maxCol = 0;
  for (const n of nodes) {
    if (!columnMap.has(n.id)) {
      columnMap.set(n.id, 0);
    }
    maxCol = Math.max(maxCol, columnMap.get(n.id)!);
  }

  // Group by column
  const columns: SankeyNode[][] = Array.from({ length: maxCol + 1 }, () => []);
  for (const n of nodes) {
    columns[columnMap.get(n.id)!].push(n);
  }

  // Compute total value per node
  const nodeValue = new Map<string, number>();
  for (const n of nodes) {
    const outVal = (outgoing.get(n.id) || []).reduce((s, l) => s + l.value, 0);
    const inVal = (incoming.get(n.id) || []).reduce((s, l) => s + l.value, 0);
    nodeValue.set(n.id, Math.max(outVal, inVal, 1));
  }

  // Compute column x positions. The first and last columns draw their text
  // labels OUTSIDE the node rect (anchor end/start), so reserve a label gutter
  // on each side -- without it, long community/sentiment names extend past the
  // SVG edge and get clipped entirely (2026-11-05 audit: first/last column
  // labels invisible at 1280px).
  const labelGutter = 92;
  const usableWidth = width - nodeWidth - labelGutter * 2;
  const colSpacing = columns.length > 1 ? usableWidth / (columns.length - 1) : usableWidth;

  // Compute node heights proportional to values
  const totalValues = columns.map((col) => col.reduce((s, n) => s + nodeValue.get(n.id)!, 0));
  const maxTotal = Math.max(...totalValues, 1);

  // Scale: we want the tallest column to fit within height with padding
  const availableHeightPerColumn = height - nodePadding * 2;
  const scale = availableHeightPerColumn / maxTotal;

  const nodeRects: Array<SankeyNode & { x: number; y: number; w: number; h: number; color: string; column: number }> = [];

  for (let c = 0; c < columns.length; c++) {
    const colNodes = columns[c];
    const colTotal = colNodes.reduce((s, n) => s + nodeValue.get(n.id)!, 0);
    const colHeight = colTotal * scale;
    const startY = (height - colHeight) / 2;

    let y = startY;
    for (const n of colNodes) {
      const h = Math.max(nodeValue.get(n.id)! * scale, 8);
      const color = n.color || DEFAULT_NODE_COLORS[c % DEFAULT_NODE_COLORS.length];
      nodeRects.push({
        ...n,
        x: labelGutter + c * colSpacing,
        y,
        w: nodeWidth,
        h,
        color,
        column: c,
      });
      y += h + nodePadding;
    }
  }

  const nodeRectMap = new Map(nodeRects.map((r) => [r.id, r]));

  // Build link paths
  const linkPaths: Array<{
    d: string;
    fill: string;
    opacity: number;
    sourceId: string;
    targetId: string;
    value: number;
    sourceName: string;
    targetName: string;
  }> = [];

  // Track cumulative y offsets for each node's outgoing/incoming links
  const sourceOffsets = new Map<string, number>();
  const targetOffsets = new Map<string, number>();

  for (const link of links) {
    const sourceRect = nodeRectMap.get(link.source);
    const targetRect = nodeRectMap.get(link.target);
    if (!sourceRect || !targetRect) continue;

    const srcH = link.value * scale;
    const tgtH = link.value * scale;

    const srcOff = sourceOffsets.get(link.source) || 0;
    const tgtOff = targetOffsets.get(link.target) || 0;

    const x0 = sourceRect.x + sourceRect.w;
    const x1 = targetRect.x;

    const curvature = 0.5;
    const xi = x0 + (x1 - x0) * curvature;

    // Top path
    const d = [
      `M ${x0} ${sourceRect.y + srcOff}`,
      `C ${xi} ${sourceRect.y + srcOff}, ${xi} ${targetRect.y + tgtOff}, ${x1} ${targetRect.y + tgtOff}`,
      `L ${x1} ${targetRect.y + tgtOff + tgtH}`,
      `C ${xi} ${targetRect.y + tgtOff + tgtH}, ${xi} ${sourceRect.y + srcOff + srcH}, ${x0} ${sourceRect.y + srcOff + srcH}`,
      'Z',
    ].join(' ');

    linkPaths.push({
      d,
      fill: sourceRect.color,
      opacity: 0.25,
      sourceId: link.source,
      targetId: link.target,
      value: link.value,
      sourceName: sourceRect.name,
      targetName: targetRect.name,
    });

    sourceOffsets.set(link.source, srcOff + srcH);
    targetOffsets.set(link.target, tgtOff + tgtH);
  }

  return { nodeRects, linkPaths };
}

export default function SankeyChart({
  nodes,
  links,
  title,
  height = 360,
  nodeWidth = 16,
  nodePadding = 12,
  onNodeClick,
  onLinkClick,
}: SankeyChartProps) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [hoveredLink, setHoveredLink] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; content: React.ReactNode } | null>(null);
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

  const { nodeRects, linkPaths } = useMemo(() => {
    return computeSankeyLayout(nodes, links, containerWidth, height, nodeWidth, nodePadding);
  }, [nodes, links, containerWidth, height, nodeWidth, nodePadding]);

  const hoveredNodeLinks = useMemo(() => {
    if (!hoveredNode) return new Set<string>();
    const set = new Set<string>();
    for (const link of links) {
      if (link.source === hoveredNode || link.target === hoveredNode) {
        set.add(`${link.source}→${link.target}`);
      }
    }
    return set;
  }, [hoveredNode, links]);

  const handleNodeEnter = useCallback((nr: typeof nodeRects[0], e: React.MouseEvent) => {
    setHoveredNode(nr.id);
    const totalValue = links
      .filter((l) => l.source === nr.id || l.target === nr.id)
      .reduce((s, l) => s + l.value, 0);
    setTooltip({
      x: e.nativeEvent.offsetX + 12,
      y: e.nativeEvent.offsetY - 8,
      content: (
        <div>
          <div className="font-semibold text-foreground mb-0.5">{nr.name}</div>
          <div className="text-foreground-muted">关联流量: {totalValue}</div>
        </div>
      ),
    });
  }, [links]);

  const handleLinkEnter = useCallback((lp: typeof linkPaths[0], e: React.MouseEvent) => {
    const key = `${lp.sourceId}→${lp.targetId}`;
    setHoveredLink(key);
    setTooltip({
      x: e.nativeEvent.offsetX + 12,
      y: e.nativeEvent.offsetY - 8,
      content: (
        <div>
          <div className="font-semibold text-foreground mb-0.5">{lp.sourceName} → {lp.targetName}</div>
          <div className="text-foreground-muted">流量: {lp.value}</div>
        </div>
      ),
    });
  }, []);

  const handleMouseLeave = useCallback(() => {
    setHoveredNode(null);
    setHoveredLink(null);
    setTooltip(null);
  }, []);

  return (
    <div className="relative">
      {title && (
        <div className="text-body font-medium text-foreground mb-4">{title}</div>
      )}
      <div ref={containerDivRef} style={{ height, width: '100%' }} className="relative">
        <svg width={containerWidth} height={height} style={{ display: 'block' }}>
          {/* Links */}
          {linkPaths.map((lp, i) => {
            const key = `${lp.sourceId}→${lp.targetId}`;
            const isHovered = hoveredLink === key || hoveredNodeLinks.has(key);
            const dimmed = (hoveredLink || hoveredNode) && !isHovered;
            return (
              <path
                key={i}
                d={lp.d}
                fill={lp.fill}
                opacity={dimmed ? 0.06 : isHovered ? 0.5 : lp.opacity}
                style={{
                  cursor: onLinkClick ? 'pointer' : 'default',
                  transition: 'opacity 0.25s ease',
                }}
                onMouseEnter={(e) => handleLinkEnter(lp, e)}
                onMouseLeave={handleMouseLeave}
                onClick={() => {
                  if (onLinkClick) {
                    onLinkClick({
                      source: lp.sourceId,
                      target: lp.targetId,
                      value: lp.value,
                      sourceName: lp.sourceName,
                      targetName: lp.targetName,
                    });
                  }
                }}
              />
            );
          })}

          {/* Nodes */}
          {nodeRects.map((nr) => {
            const isHovered = hoveredNode === nr.id;
            const dimmed = hoveredNode && !isHovered && !hoveredNodeLinks.has(`${nr.id}→`) && !hoveredNodeLinks.has(`→${nr.id}`);
            return (
              <g
                key={nr.id}
                style={{
                  cursor: onNodeClick ? 'pointer' : 'default',
                  transition: 'opacity 0.25s ease',
                  opacity: dimmed ? 0.3 : 1,
                }}
                onMouseEnter={(e) => handleNodeEnter(nr, e)}
                onMouseLeave={handleMouseLeave}
                onClick={() => {
                  if (onNodeClick) onNodeClick(nr);
                }}
              >
                <rect
                  x={nr.x}
                  y={nr.y}
                  width={nr.w}
                  height={nr.h}
                  rx={3}
                  fill={nr.color}
                  style={{
                    filter: isHovered ? 'brightness(1.1)' : 'none',
                    transition: 'all 0.25s ease',
                  }}
                />
                {/* Label */}
                <text
                  x={nr.column === 0 ? nr.x - 6 : nr.x + nr.w + 6}
                  y={nr.y + nr.h / 2}
                  textAnchor={nr.column === 0 ? 'end' : 'start'}
                  dominantBaseline="middle"
                  className="text-caption"
                  style={{
                    fontSize: 11,
                    fill: '#6B6B6B',
                    fontWeight: isHovered ? 600 : 400,
                    pointerEvents: 'none',
                    userSelect: 'none',
                  }}
                >
                  {nr.name}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Tooltip */}
        {tooltip && (
          <div
            className="absolute z-10 pointer-events-none bg-white rounded-xl shadow-elevated border border-border-divider px-3 py-2 text-tiny animate-fade-in"
            style={{
              left: Math.min(tooltip.x, containerWidth - 180),
              top: Math.max(tooltip.y - 40, 0),
              minWidth: 140,
            }}
          >
            {tooltip.content}
          </div>
        )}
      </div>
    </div>
  );
}
