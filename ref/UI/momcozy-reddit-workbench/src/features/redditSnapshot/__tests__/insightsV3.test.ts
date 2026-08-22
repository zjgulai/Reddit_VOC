import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  isV3InsightsSnapshot,
  loadRedditInsights,
  resetInsightsCacheForTests,
} from '../insights';
import {
  V3_INSIGHTS_CANDIDATE_MANIFEST_SCHEMA,
  V3_INSIGHTS_PUBLIC_MANIFEST_SCHEMA,
  V3InsightsContractError,
  validateV3InsightsSnapshot,
  type V3PublicInsightsData,
} from '../insightsV3';
import {
  resetCurrentReleaseCacheForTests,
  validateCurrentRelease,
  type CurrentRelease,
} from '../release';
import { isRiskInsightsData } from '../service';

const publicDirectory = resolve(process.cwd(), 'public');
const fallbackV3DatasetVersion = 'reddit_voc_insights_20260716_v3_1ab1c634f225';

function readJson<T>(directory: string, filename: string): T {
  return JSON.parse(readFileSync(resolve(directory, filename), 'utf8')) as T;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const baseRelease = validateCurrentRelease(JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
));
const currentManifest = readJson<{ schema_version: string }>(
  resolve(publicDirectory, 'data/reddit-voc', baseRelease.datasets.insights.dataset_version, 'public'),
  'manifest.json',
);
const isV3CurrentRelease = currentManifest.schema_version === V3_INSIGHTS_PUBLIC_MANIFEST_SCHEMA;
const artifactDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  isV3CurrentRelease ? baseRelease.datasets.insights.dataset_version : fallbackV3DatasetVersion,
  'public',
);
const legacyIt = isV3CurrentRelease ? it.skip : it;
const manifestRaw = readFileSync(resolve(artifactDirectory, 'manifest.json'), 'utf8');
const manifest = JSON.parse(manifestRaw) as {
  dataset_version: string;
  lineage_manifest_sha256: string;
};
const publicManifestSha256 = createHash('sha256').update(manifestRaw).digest('hex');

function v3Release(): CurrentRelease {
  const release = clone(baseRelease);
  release.datasets.insights = {
    dataset_version: manifest.dataset_version,
    manifest_path: `data/reddit-voc/${manifest.dataset_version}/public/manifest.json`,
    public_manifest_sha256: publicManifestSha256,
    lineage_manifest_sha256: manifest.lineage_manifest_sha256,
  };
  return release;
}

function validatedSnapshot() {
  return validateV3InsightsSnapshot(
    readJson(artifactDirectory, 'manifest.json'),
    readJson(artifactDirectory, 'validation-receipt.json'),
    readJson(artifactDirectory, 'public-validation-receipt.json'),
    readJson(artifactDirectory, 'insights.json'),
    v3Release(),
  );
}

function response(body: string): Response {
  return {
    ok: true,
    status: 200,
    text: async () => body,
  } as Response;
}

function createV3Fetch(tamperPath?: string) {
  const release = v3Release();
  const prefix = `/data/reddit-voc/${manifest.dataset_version}/public/`;
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    let body: string;
    if (pathname === '/data/reddit-voc/current-release.json') {
      body = JSON.stringify(release);
    } else if (pathname === `${prefix}manifest.json`) {
      body = manifestRaw;
    } else {
      expect(pathname.startsWith(prefix)).toBe(true);
      body = readFileSync(resolve(artifactDirectory, pathname.slice(prefix.length)), 'utf8');
    }
    if (pathname === tamperPath) body = `${body}\n`;
    return response(body);
  });
}

function createPublicTreeFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    return response(readFileSync(resolve(publicDirectory, pathname.slice(1)), 'utf8'));
  });
}

describe('V3 public insights contract', () => {
  afterEach(() => {
    resetInsightsCacheForTests();
    resetCurrentReleaseCacheForTests();
    vi.unstubAllGlobals();
  });

  it('validates the exact 78-story privacy-safe public wrapper and all three grains', () => {
    const snapshot = validatedSnapshot();

    expect(snapshot.manifest.schema_version).toBe('reddit_voc_insights_public_manifest_v3');
    expect(snapshot.manifest.storyline_count).toBe(78);
    expect(snapshot.insights.storylines).toHaveLength(78);
    expect(snapshot.insights.storylines.filter(({ grain }) => grain === 'daily')).toHaveLength(26);
    expect(snapshot.insights.storylines.filter(({ grain }) => grain === 'weekly')).toHaveLength(26);
    expect(snapshot.insights.storylines.filter(({ grain }) => grain === 'monthly')).toHaveLength(26);
    expect(snapshot.insights.storylines.filter(({ direction_claim_supported }) => direction_claim_supported)).toHaveLength(
      snapshot.insights.storyline_summary.direction_supported,
    );
    expect(snapshot.publicValidationReceipt.bundle_manifest_sha256).toBe(publicManifestSha256);
  });

  it('loads the pointer-selected V3 wrapper with manifest, embedded receipt, and public receipt integrity checks', async () => {
    const fetchMock = createV3Fetch();
    vi.stubGlobal('fetch', fetchMock);

    const snapshot = await loadRedditInsights();

    expect(isV3InsightsSnapshot(snapshot)).toBe(true);
    if (!isV3InsightsSnapshot(snapshot)) throw new Error('expected V3 insights snapshot');
    expect(snapshot.insights.analysis_frame.primary_brand).toBe('Momcozy');
    expect(snapshot.insights.storyline_count).toBe(78);
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it('fails closed when the public insights payload changes by one byte', async () => {
    const prefix = `/data/reddit-voc/${manifest.dataset_version}/public/`;
    vi.stubGlobal('fetch', createV3Fetch(`${prefix}insights.json`));

    await expect(loadRedditInsights()).rejects.toThrow(/V3 洞察文件 bytes 不一致：insights\.json/);
  });

  it('rejects a raw candidate manifest without falling back to V1/V2', async () => {
    const candidateManifest = clone(JSON.parse(manifestRaw) as Record<string, unknown>);
    candidateManifest.schema_version = V3_INSIGHTS_CANDIDATE_MANIFEST_SCHEMA;
    const candidateRaw = JSON.stringify(candidateManifest);
    const release = clone(baseRelease);
    const datasetVersion = 'reddit_voc_insights_20260716_v3_candidate';
    release.datasets.insights = {
      dataset_version: datasetVersion,
      manifest_path: `data/reddit-voc/${datasetVersion}/public/manifest.json`,
      public_manifest_sha256: createHash('sha256').update(candidateRaw).digest('hex'),
      lineage_manifest_sha256: createHash('sha256').update(candidateRaw).digest('hex'),
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const pathname = new URL(String(input), 'http://localhost').pathname;
      return response(pathname === '/data/reddit-voc/current-release.json' ? JSON.stringify(release) : candidateRaw);
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadRedditInsights()).rejects.toThrow(
      'V3 洞察 candidate 尚未通过 privacy-safe public wrapper 独立验证，禁止消费且不回退 V1/V2',
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('rejects a fabricated root cause when same-snapshot evidence is absent', () => {
    const insights = clone(readJson<V3PublicInsightsData>(artifactDirectory, 'insights.json'));
    const storyline = insights.storylines.find((item) => !item.sections.root_cause.supported);
    if (!storyline) throw new Error('expected unsupported root cause');
    storyline.sections.root_cause.statement = '推断为机器人推广导致';

    expect(() => validateV3InsightsSnapshot(
      readJson(artifactDirectory, 'manifest.json'),
      readJson(artifactDirectory, 'validation-receipt.json'),
      readJson(artifactDirectory, 'public-validation-receipt.json'),
      insights,
      v3Release(),
    )).toThrow(/对未确认根因进行了推断/);
  });

  it('rejects raw identifiers or URLs injected into the public projection', () => {
    const insights = clone(readJson<V3PublicInsightsData>(artifactDirectory, 'insights.json')) as unknown as Record<string, unknown>;
    (insights.storylines as Array<Record<string, unknown>>)[0].post_id = 't3_private';

    expect(() => validateV3InsightsSnapshot(
      readJson(artifactDirectory, 'manifest.json'),
      readJson(artifactDirectory, 'validation-receipt.json'),
      readJson(artifactDirectory, 'public-validation-receipt.json'),
      insights,
      v3Release(),
    )).toThrow(/包含隐私或原始内容字段：post_id/);
  });

  it('keeps unavailable values null rather than accepting a synthetic zero', () => {
    const insights = clone(readJson<V3PublicInsightsData>(artifactDirectory, 'insights.json'));
    const unavailable = insights.storylines.find((item) => item.sections.signal.status === 'unavailable');
    if (!unavailable) throw new Error('expected unavailable storyline');
    unavailable.sections.signal.value = '0';

    expect(() => validateV3InsightsSnapshot(
      readJson(artifactDirectory, 'manifest.json'),
      readJson(artifactDirectory, 'validation-receipt.json'),
      readJson(artifactDirectory, 'public-validation-receipt.json'),
      insights,
      v3Release(),
    )).toThrow(/不可用指标必须保持 null\/—/);
  });

  legacyIt('still dispatches the current V1/V2 public release through the legacy validator', async () => {
    vi.stubGlobal('fetch', createPublicTreeFetch());

    const snapshot = await loadRedditInsights();

    expect(isV3InsightsSnapshot(snapshot)).toBe(false);
    if (isV3InsightsSnapshot(snapshot)) throw new Error('expected legacy insights snapshot');
    expect(isRiskInsightsData(snapshot.insights)).toBe(true);
    expect(snapshot.manifest.dataset_version).toBe(baseRelease.datasets.insights.dataset_version);
  });

  it('uses the dedicated contract error type for semantic overclaims', () => {
    const insights = clone(readJson<V3PublicInsightsData>(artifactDirectory, 'insights.json'));
    insights.interpretation_boundaries.sales_causality_supported = true as false;

    expect(() => validateV3InsightsSnapshot(
      readJson(artifactDirectory, 'manifest.json'),
      readJson(artifactDirectory, 'validation-receipt.json'),
      readJson(artifactDirectory, 'public-validation-receipt.json'),
      insights,
      v3Release(),
    )).toThrowError(V3InsightsContractError);
  });
});
