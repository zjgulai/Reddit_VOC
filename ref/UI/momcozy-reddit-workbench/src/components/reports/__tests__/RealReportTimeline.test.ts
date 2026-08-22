import { describe, expect, it } from 'vitest';
import { formatReportTimelineLabel, formatReportTrendLabel } from '../RealReportView';

describe('real report timeline labels', () => {
  it('does not turn day-precision daily buckets into repeated midnight labels', () => {
    expect(formatReportTimelineLabel('2026-07-14T00:00:00+08:00', 'day')).toBe('07-14');
    expect(formatReportTimelineLabel('2026-07-15T00:00:00+08:00', 'day')).toBe('07-15');
  });

  it('keeps hour buckets as Asia/Shanghai time', () => {
    expect(formatReportTimelineLabel('2026-07-15T00:30:00Z', 'hour')).toBe('08:30');
  });

  it('formats daily, weekly, and monthly trend points at their actual grain', () => {
    expect(formatReportTrendLabel('2026-07-15T00:00:00+08:00', 'daily')).toBe('07-15');
    expect(formatReportTrendLabel('2026-07-13T00:00:00+08:00', 'weekly')).toBe('07-13');
    expect(formatReportTrendLabel('2026-07-01T00:00:00+08:00', 'monthly')).toBe('2026-07');
  });
});
