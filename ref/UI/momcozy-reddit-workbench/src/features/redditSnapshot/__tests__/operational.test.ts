import { describe, expect, it } from 'vitest';
import { businessCalendarDate } from '../operational';

describe('businessCalendarDate', () => {
  it('assigns instant events to the Asia/Shanghai business day', () => {
    expect(businessCalendarDate('2026-07-17T15:59:59.999Z')).toBe('2026-07-17');
    expect(businessCalendarDate('2026-07-17T16:00:00.000Z')).toBe('2026-07-18');
    expect(businessCalendarDate('2026-07-17T22:30:11.975+00:00')).toBe('2026-07-18');
  });
});
