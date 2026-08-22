import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  createBaseDataFreshness,
  createReleaseTemporalContext,
  latestClosedShanghaiPeriod,
} from '../freshness';
import { validateCurrentRelease, type CurrentRelease } from '../release';
import type { RedditSnapshotSummary, SnapshotAggregates, SnapshotManifest } from '../types';

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(readFileSync(
  resolve(publicDirectory, 'data/reddit-voc/current-release.json'),
  'utf8',
)));
const baseDirectory = resolve(publicDirectory, 'data/reddit-voc', release.datasets.base.dataset_version);
const snapshot: RedditSnapshotSummary = {
  release,
  manifest: JSON.parse(readFileSync(resolve(baseDirectory, 'manifest-public.json'), 'utf8')) as SnapshotManifest,
  aggregates: JSON.parse(readFileSync(resolve(baseDirectory, 'aggregates-public.json'), 'utf8')) as SnapshotAggregates,
};

describe('release temporal context', () => {
  it('classifies an explicitly stale July pointer on the fixed 2026-08-09 Shanghai clock', () => {
    const staleRelease: CurrentRelease = {
      ...release,
      freshness: {
        ...release.freshness!,
        status: 'full',
        data_as_of_utc: '2026-07-22T23:00:00Z',
        window_start_utc: '2026-07-21T23:00:00Z',
        window_end_utc: '2026-07-22T23:00:00Z',
        collector_run_id: 'daily_collect_20260723_0700',
        source_batch_id: 'server_snapshot_20260706_20260723',
      },
    };
    const evidence = createBaseDataFreshness({ ...snapshot, release: staleRelease }, {
      now: '2026-08-09T04:43:00Z',
    });

    expect(evidence.status).toBe('verified');
    expect(evidence.recencyStatus).toBe('stalled');
    expect(evidence.recencyLabel).toBe('数据链路已停滞 17天5小时');
    expect(evidence.dataAsOf).toBe('2026-07-22T23:00:00Z');
    expect(evidence.currentTime).toBe('2026-08-09T04:43:00.000Z');
    expect(evidence.expectedPeriodEnd).toBe('2026-08-08T23:00:00.000Z');
    expect(evidence.deadline).toBe('2026-08-09T00:30:00.000Z');
    expect(evidence.lagSeconds).toBe(1_489_380);
    expect(evidence.collectorRunId).toBe('daily_collect_20260723_0700');
    expect(evidence.sourceBatchId).toBe('server_snapshot_20260706_20260723');
  });

  it('uses the same 07:00 Asia/Shanghai close and 90 minute awaiting window as the backend', () => {
    const observedAt = new Date('2026-08-09T00:00:00Z');
    expect(latestClosedShanghaiPeriod(observedAt).toISOString()).toBe('2026-08-08T23:00:00.000Z');

    const awaitingRelease: CurrentRelease = {
      ...release,
      freshness: {
        ...release.freshness!,
        status: 'full',
        data_as_of_utc: '2026-08-07T23:00:00Z',
        window_start_utc: '2026-08-06T23:00:00Z',
        window_end_utc: '2026-08-07T23:00:00Z',
      },
    };
    const context = createReleaseTemporalContext(awaitingRelease, null, { now: observedAt });
    expect(context.recencyStatus).toBe('awaiting');
    expect(context.deadlineUtc).toBe('2026-08-09T00:30:00.000Z');
  });

  it('keeps a current partial collection distinct from a fully fresh period', () => {
    const currentPartial: CurrentRelease = {
      ...release,
      freshness: {
        ...release.freshness!,
        data_as_of_utc: '2026-08-08T23:00:00Z',
        window_start_utc: '2026-08-07T23:00:00Z',
        window_end_utc: '2026-08-08T23:00:00Z',
        status: 'partial',
      },
    };
    const context = createReleaseTemporalContext(currentPartial, null, {
      now: '2026-08-09T00:10:00Z',
    });

    expect(context.recencyStatus).toBe('partial');
  });

  it('does not invent release freshness for a legacy pointer without the freshness contract', () => {
    const legacyRelease = { ...release, freshness: undefined } as CurrentRelease;
    const observationMax = '2026-07-22T22:52:13Z';
    const context = createReleaseTemporalContext(legacyRelease, observationMax, {
      now: '2026-08-09T04:43:00Z',
    });

    expect(context.recencyStatus).toBe('unavailable');
    expect(context.dataAsOfUtc).toBe(observationMax);
    expect(context.collectorRunId).toBeNull();
  });
});
