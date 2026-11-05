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

const NAMED_HTML_ENTITIES: Record<string, string> = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
  nbsp: ' ',
};

const HTML_ENTITY_PATTERN = /&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g;

/**
 * Reddit 原始抓取把 HTML 实体原样留在正文里（`&#32; submitted by &#32;`、
 * `&amp;`、`&#39;`）。数据字节被 manifest SHA 锁定不能改写，展示层统一解码。
 * 未知实体原样保留，避免把无害文本误转。仅接受完整的实体形式；独立的 & 不受影响。
 */
export function decodeHtmlEntities(value: string): string {
  if (!value.includes('&')) return value;
  return value.replace(HTML_ENTITY_PATTERN, (match, body: string) => {
    if (body[0] === '#') {
      const code = body[1] === 'x' || body[1] === 'X'
        ? Number.parseInt(body.slice(2), 16)
        : Number.parseInt(body.slice(1), 10);
      if (!Number.isFinite(code) || code < 0x20 || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) {
        return match;
      }
      return String.fromCodePoint(code);
    }
    return NAMED_HTML_ENTITIES[body.toLowerCase()] ?? match;
  });
}
