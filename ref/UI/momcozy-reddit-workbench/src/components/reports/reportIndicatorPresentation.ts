import type { V3ReportIndicator } from '../../features/redditSnapshot/reports';

const UNIT_LABELS: Record<string, string> = {
  count: '条',
  percent: '%',
  pp: 'pp',
  score: '分',
};

export function numericReportValue(value: unknown): number | null {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (String(value).trim() === '') return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

export function isDisplayableReportIndicator(indicator: V3ReportIndicator): boolean {
  return indicator.current.status !== 'unavailable'
    && numericReportValue(indicator.current.value) !== null;
}

export function formatReportIndicatorValue(indicator: V3ReportIndicator): string {
  const value = numericReportValue(indicator.current.value);
  if (value === null) return '';
  const display = typeof indicator.current.display === 'string' || typeof indicator.current.display === 'number'
    ? String(indicator.current.display)
    : value.toLocaleString('zh-CN');
  return `${display}${UNIT_LABELS[indicator.current.unit] ?? ''}`;
}
