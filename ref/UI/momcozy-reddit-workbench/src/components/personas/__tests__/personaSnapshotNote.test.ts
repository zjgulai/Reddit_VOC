import { describe, expect, it } from 'vitest';
import { personaSnapshotDate, quarterStartDate } from '../AggregatePersonaPanel';
import type { AnyRedditPersonasSnapshot } from '../AggregatePersonaPanel';

function snapshotWith(generatedAt: string): AnyRedditPersonasSnapshot {
  return {
    manifest: { generated_at_utc: generatedAt },
  } as unknown as AnyRedditPersonasSnapshot;
}

describe('persona snapshot staleness note', () => {
  it('extracts the snapshot date and the quarter start date', () => {
    expect(personaSnapshotDate(snapshotWith('2026-07-23T15:00:00+00:00'))).toBe('2026-07-23');
    expect(quarterStartDate('最近一个季度（2026-07-29 至 2026-10-26）')).toBe('2026-07-29');
    expect(quarterStartDate(undefined)).toBeNull();
  });

  it('flags a snapshot that predates the quarter and clears one that does not', () => {
    const stale = personaSnapshotDate(snapshotWith('2026-07-23T15:00:00+00:00'))!;
    const fresh = personaSnapshotDate(snapshotWith('2026-10-20T15:00:00+00:00'))!;
    const quarterStart = quarterStartDate('最近一个季度（2026-07-29 至 2026-10-26）')!;
    expect(stale < quarterStart).toBe(true);
    expect(fresh < quarterStart).toBe(false);
  });
});
