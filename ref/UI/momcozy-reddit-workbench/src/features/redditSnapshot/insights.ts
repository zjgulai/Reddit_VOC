import {
  loadRedditInsights as loadLegacyRedditInsights,
  resetSnapshotCacheForTests,
} from './service';
import type { RedditInsightsSnapshot } from './types';
import {
  isV3InsightsCandidateManifest,
  isV3InsightsPublicManifest,
  loadRedditV3Insights,
  V3InsightsContractError,
  type V3RedditInsightsSnapshot,
} from './insightsV3';
import {
  fetchVerifiedReleaseManifest,
  loadCurrentRelease,
} from './release';

export * from './insightsV3';

export type AnyRedditInsightsSnapshot = RedditInsightsSnapshot | V3RedditInsightsSnapshot;

let insightsPromise: Promise<AnyRedditInsightsSnapshot> | null = null;

async function loadInsightsUncached(forceReload = false): Promise<AnyRedditInsightsSnapshot> {
  const release = await loadCurrentRelease();
  const manifestValue = await fetchVerifiedReleaseManifest<unknown>(release, 'insights', forceReload);
  if (isV3InsightsPublicManifest(manifestValue)) {
    return loadRedditV3Insights(manifestValue, release, forceReload);
  }
  if (isV3InsightsCandidateManifest(manifestValue)) {
    throw new V3InsightsContractError(
      'V3 洞察 candidate 尚未通过 privacy-safe public wrapper 独立验证，禁止消费且不回退 V1/V2',
    );
  }
  return loadLegacyRedditInsights();
}

export function loadRedditInsights(): Promise<AnyRedditInsightsSnapshot> {
  insightsPromise ??= loadInsightsUncached();
  return insightsPromise;
}

export function reloadRedditInsights(): Promise<AnyRedditInsightsSnapshot> {
  insightsPromise = loadInsightsUncached(true);
  return insightsPromise;
}

export function resetInsightsCacheForTests(): void {
  insightsPromise = null;
  resetSnapshotCacheForTests();
}
