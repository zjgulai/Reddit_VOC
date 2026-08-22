import { describe, expect, it } from 'vitest';
import { formatDateTime, formatSeriesLabel } from '../format';

describe('Reddit V3 series formatter', () => {
  it('does not invent a time for a floating calendar date', () => {
    expect(formatDateTime('2025-07-01')).toBe('2025/07/01');
  });

  it('keeps floating day labels invariant across timezones', () => {
    expect(formatSeriesLabel('2026-07-15', 'day', 'UTC')).toBe('07-15');
    expect(formatSeriesLabel('2026-07-15', 'day', 'Asia/Shanghai')).toBe('07-15');
  });

  it('formats a week from its literal source-calendar start and a month literally', () => {
    expect(formatSeriesLabel('2026-07-13', 'week', 'America/Los_Angeles')).toBe('07-13');
    expect(formatSeriesLabel('2026-07', 'month', 'UTC')).toBe('2026-07');
  });

  it('converts only instant/hour buckets to the requested timezone', () => {
    expect(formatSeriesLabel('2026-07-15T00:30:00Z', 'hour', 'UTC')).toBe('00:30');
    expect(formatSeriesLabel('2026-07-15T00:30:00Z', 'hour', 'Asia/Shanghai')).toBe('08:30');
  });

  it('fails closed when a floating calendar label has the wrong precision', () => {
    expect(() => formatSeriesLabel('2026-07-15T00:00:00Z', 'day')).toThrow(
      'day series value must be YYYY-MM-DD',
    );
  });
});
