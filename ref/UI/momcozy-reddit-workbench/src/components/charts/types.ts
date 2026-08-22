/**
 * Recharts 通用类型定义
 * 收敛图表组件中使用的 any 类型，提供类型安全
 */

import type { TooltipContentProps, SectorProps, PieSectorDataItem, LegendPayload, ActiveDotProps } from 'recharts';

export type ValueType = number | string | ReadonlyArray<number | string>;
export type NameType = number | string;

/**
 * Tooltip Payload 基础类型（兼容 Recharts 内部 Payload 结构）
 */
interface PayloadBase<V, N> {
  value?: V;
  name?: N;
  dataKey?: string | number;
  payload?: unknown;
  color?: string;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
}

/**
 * Tooltip Payload 单项类型
 * 泛型 T 为 payload 中的数据对象类型
 */
export interface TooltipPayloadItem<T = unknown> extends PayloadBase<ValueType, NameType> {
  payload?: T;
}

/**
 * Tooltip 自定义内容组件的 Props
 * 泛型 T 为 payload 中的数据对象类型
 */
export type CustomTooltipProps<T = unknown> = Partial<Pick<TooltipContentProps<ValueType, NameType>, 'active' | 'payload' | 'label'>> & {
  payload?: TooltipPayloadItem<T>[];
};

/**
 * Recharts 鼠标移动事件状态
 * 用于 AreaChart、LineChart、SentimentTrendChart 的 onMouseMove
 */
export interface RechartsMouseEvent {
  activeTooltipIndex?: number | string | null;
  isTooltipActive?: boolean;
}

/**
 * PieChart 的 ActiveShape 组件 Props
 */
export interface ActiveShapeProps extends SectorProps {}

/**
 * PieChart 事件处理函数的数据类型
 */
export type PieEventData = PieSectorDataItem;

/**
 * Legend 的 formatter 条目类型
 */
export type LegendFormatterEntry = LegendPayload;

/**
 * LineChart 的 ActiveDot 渲染 Props
 */
export type LineActiveDotProps = ActiveDotProps;

/**
 * BarChart / LineChart 点击事件处理 Props
 */
export type ChartClickProps = unknown;

/**
 * FunnelChart 的 enriched data 类型
 */
export interface FunnelEnrichedData extends Record<string, unknown> {
  fill?: string;
}
