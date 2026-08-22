import type { SnapshotSentiment } from './types';

export type SnapshotSeriesGrain = 'instant' | 'hour' | 'day' | 'week' | 'month';

const TOPIC_LABELS: Record<string, string> = {
  competitor_comparison: '竞品比较',
  troubleshooting: '问题排查',
  purchase_decision: '购买决策',
  product_evaluation: '产品评价',
  insurance: '保险',
  customer_service: '客户服务',
  other: '其他',
};

const PAIN_POINT_LABELS: Record<string, string> = {
  operations: '操作与使用',
  fit_comfort: '适配与舒适度',
  output_supply: '产量与奶量',
  support: '支持与售后',
  insurance: '保险',
  leakage: '漏液',
  family_scenario: '家庭场景',
  work_scenario: '工作场景',
  health: '健康',
};

export const SENTIMENT_LABELS: Record<SnapshotSentiment, string> = {
  positive: '正面',
  neutral: '中性',
  negative: '负面',
};

export function formatTopic(topic: string): string {
  return TOPIC_LABELS[topic] ?? topic;
}

export function formatPainPoint(point: string): string {
  return PAIN_POINT_LABELS[point] ?? point;
}

export function formatDateTime(value: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split('-');
    return `${year}/${month}/${day}`;
  }
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value));
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(value));
}

/**
 * Formats a precomputed series bucket without changing the meaning of a
 * floating calendar date. Day/week/month values are source-calendar labels,
 * not instants, so they must never pass through Date or a browser timezone.
 */
export function formatSeriesLabel(
  value: string,
  grain: SnapshotSeriesGrain,
  timezone = 'Asia/Shanghai',
): string {
  if (grain === 'day' || grain === 'week') {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      throw new RangeError(`${grain} series value must be YYYY-MM-DD`);
    }
    return value.slice(5);
  }
  if (grain === 'month') {
    if (!/^\d{4}-\d{2}$/.test(value)) {
      throw new RangeError('month series value must be YYYY-MM');
    }
    return value;
  }

  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) {
    throw new RangeError(`${grain} series value must be an ISO instant`);
  }
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: timezone,
  }).format(instant);
}

export function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function formatPseudonym(value: string | null | undefined): string {
  return value ?? '匿名用户（无可用作者）';
}
