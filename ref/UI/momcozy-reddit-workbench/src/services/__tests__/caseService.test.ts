import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { seedCases, type CaseItem } from '../../data/casesMock';
import { legacyUnverifiedCases } from '../caseSearchService';
import {
  CASE_CATALOG_MANIFEST_PATH,
  canonicalizeCaseUrl,
  isNavigableCaseUrl,
  mergeCaseCatalog,
  resetCaseCatalogCacheForTests,
  searchCases,
  validateCaseCatalogIndex,
  validateCaseCatalogManifest,
} from '../caseService';

const publicDirectory = resolve(process.cwd(), 'public');
const manifestPath = resolve(publicDirectory, 'data/cases/manifest.v1.json');
const indexPath = resolve(publicDirectory, 'data/cases/case-index.v1.json');

function sha256(content: string): string {
  return createHash('sha256').update(content).digest('hex');
}

function publicFetch(overrides: Record<string, string> = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    if (pathname in overrides) {
      const body = overrides[pathname];
      return {
        ok: true,
        status: 200,
        json: async () => JSON.parse(body) as unknown,
        text: async () => body,
      } as Response;
    }
    const body = readFileSync(resolve(publicDirectory, pathname.slice(1)), 'utf8');
    return {
      ok: true,
      status: 200,
      json: async () => JSON.parse(body) as unknown,
      text: async () => body,
    } as Response;
  });
}

function approvedCase(overrides: Partial<CaseItem> = {}): CaseItem {
  return {
    id: 'delta-approved-1',
    title: '已审核的 Reddit 案例增量',
    description: '由离线审核流程批准的版本化案例。',
    source: 'Reddit_VOC 审核台账',
    url: 'https://example.com/reddit-case',
    category: 'insight',
    tags: ['Reddit', '审核增量'],
    date: '2026-07-15',
    sourceKind: 'approved_delta',
    verificationStatus: 'verified',
    canonicalUrl: 'https://example.com/reddit-case',
    contentHash: `sha256:${'a'.repeat(64)}`,
    updatedAt: '2026-07-15T00:00:00.000Z',
    lastVerifiedAt: '2026-07-15T00:00:00.000Z',
    provenance: 'manual_review_ledger:case-1',
    ...overrides,
  };
}

beforeEach(() => {
  resetCaseCatalogCacheForTests();
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-07-16T00:00:00.000Z'));
});

afterEach(() => {
  resetCaseCatalogCacheForTests();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('CaseGallery versioned catalog contract', () => {
  it('pins all 38 curated seed items and all 12 legacy items to manifest SHA contracts', () => {
    const manifestRaw = readFileSync(manifestPath, 'utf8');
    const indexRaw = readFileSync(indexPath, 'utf8');
    const manifest = validateCaseCatalogManifest(JSON.parse(manifestRaw));
    const index = validateCaseCatalogIndex(JSON.parse(indexRaw), manifest.datasetVersion);

    expect(seedCases).toHaveLength(38);
    expect(new Set(seedCases.map((item) => item.id)).size).toBe(38);
    expect(seedCases.every((item) => item.sourceKind === 'curated_seed')).toBe(true);
    expect(legacyUnverifiedCases).toHaveLength(12);
    expect(legacyUnverifiedCases.every((item) => item.sourceKind === 'legacy_unverified')).toBe(true);
    expect(legacyUnverifiedCases.every((item) => item.verificationStatus === 'pending')).toBe(true);
    expect(index.approvedDelta).toHaveLength(0);
    expect(sha256(JSON.stringify(seedCases))).toBe(manifest.seed.contentSha256);
    expect(sha256(JSON.stringify(legacyUnverifiedCases))).toBe(manifest.legacyUnverified.contentSha256);
    expect(sha256(JSON.stringify(index.approvedDelta))).toBe(manifest.approvedDelta.contentSha256);
    expect(sha256(indexRaw)).toBe(manifest.index.sha256);
  });

  it('loads only the same-origin manifest and versioned index, with no search API call', async () => {
    const fetchMock = publicFetch();
    vi.stubGlobal('fetch', fetchMock);

    const first = await searchCases('', 'all');
    const second = await searchCases('Reddit', 'all');

    expect(first.items).toHaveLength(33);
    expect(first.items.every((item) => item.defaultEligible === true)).toBe(true);
    expect(first.items.every((item) => item.verificationStatus === 'curated')).toBe(true);
    expect(first.items.every((item) => item.lastVerifiedAt === undefined)).toBe(true);
    expect(first.items.every((item) => isNavigableCaseUrl(item.url))).toBe(true);
    for (const reviewOnlyId of ['geo1', 'geo2', 'geo3', 'geo4', 'in1']) {
      expect(first.items.some((item) => item.id === reviewOnlyId)).toBe(false);
    }
    expect(first.items.some((item) => item.sourceKind === 'legacy_unverified')).toBe(false);
    expect(first.meta).toMatchObject({
      status: 'verified_index',
      seedCount: 38,
      legacyUnverifiedCount: 12,
      approvedDeltaCount: 0,
      freshness: 'fresh',
    });
    expect(second.items.length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      CASE_CATALOG_MANIFEST_PATH,
      '/data/cases/case-index.v1.json',
    ]);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/api/'))).toBe(false);
  });

  it('fails closed to the 33 navigable curated seed items when the delta index is unavailable', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === CASE_CATALOG_MANIFEST_PATH) {
        const body = readFileSync(manifestPath, 'utf8');
        return { ok: true, status: 200, json: async () => JSON.parse(body) } as Response;
      }
      return { ok: false, status: 404 } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await searchCases('', 'all');

    expect(result.items).toHaveLength(33);
    expect(result.items.every((item) => item.sourceKind === 'curated_seed')).toBe(true);
    expect(result.items.every((item) => item.verificationStatus === 'curated')).toBe(true);
    expect(result.items.every((item) => item.defaultEligible === true)).toBe(true);
    for (const reviewOnlyId of ['geo1', 'geo2', 'geo3', 'geo4', 'in1']) {
      expect(result.items.some((item) => item.id === reviewOnlyId)).toBe(false);
    }
    expect(result.meta).toMatchObject({
      status: 'seed_only',
      seedCount: 38,
      legacyUnverifiedCount: 0,
      approvedDeltaCount: 0,
      fallbackReason: '案例 index HTTP 404',
    });
  });

  it('fails closed when the index SHA contract is tampered', async () => {
    const tamperedIndex = JSON.stringify({
      schemaVersion: 1,
      datasetVersion: 'case_catalog_20260715_v1',
      approvedDelta: [approvedCase()],
    });
    vi.stubGlobal('fetch', publicFetch({ '/data/cases/case-index.v1.json': tamperedIndex }));

    const result = await searchCases('', 'all');

    expect(result.meta.status).toBe('seed_only');
    expect(result.meta.fallbackReason).toBe('案例 index SHA-256 不一致');
    expect(result.items).toHaveLength(33);
  });

  it('routes all 12 legacy items and five link-review seed items to the review view', async () => {
    vi.stubGlobal('fetch', publicFetch());

    const review = await searchCases('', 'all', undefined, { view: 'review' });

    expect(review.items).toHaveLength(17);
    expect(review.items.filter((item) => item.sourceKind === 'legacy_unverified')).toHaveLength(12);
    for (const reviewOnlyId of ['geo1', 'geo2', 'geo3', 'geo4', 'in1']) {
      expect(review.items.some((item) => item.id === reviewOnlyId)).toBe(true);
    }
    expect(review.items.every((item) => item.defaultEligible === false)).toBe(true);
  });

  it('deduplicates deterministically by canonical URL, content hash and ID', () => {
    const approved = approvedCase();
    const sameUrl = {
      ...legacyUnverifiedCases[0],
      id: 'legacy-same-url',
      url: 'http://www.example.com/reddit-case/?utm_source=legacy#section',
      canonicalUrl: 'http://www.example.com/reddit-case/?utm_source=legacy#section',
    };
    const sameHash = {
      ...legacyUnverifiedCases[1],
      id: 'legacy-same-hash',
      contentHash: approved.contentHash,
    };
    const sameId = {
      ...legacyUnverifiedCases[2],
      id: approved.id,
    };

    expect(canonicalizeCaseUrl(sameUrl.url)).toBe('https://example.com/reddit-case');
    expect(mergeCaseCatalog([], [sameUrl, sameHash, sameId], [approved])).toEqual([approved]);
    expect(mergeCaseCatalog([], [sameUrl, sameHash, sameId], [approved])).toEqual([approved]);
  });

  it('never lets an approved delta overwrite a curated seed URL', () => {
    const duplicateSeedUrl = approvedCase({
      id: 'delta-duplicate-seed',
      url: `${seedCases[0].url}&utm_source=delta`,
      canonicalUrl: `${seedCases[0].url}&utm_source=delta`,
    });

    const merged = mergeCaseCatalog(seedCases, [], [duplicateSeedUrl]);

    expect(merged).toHaveLength(38);
    expect(merged[0]).toEqual(seedCases[0]);
    expect(merged.some((item) => item.id === duplicateSeedUrl.id)).toBe(false);
  });

  it('keeps non-navigable approved entries out of the default reference view', async () => {
    const manifestRaw = readFileSync(manifestPath, 'utf8');
    const manifest = JSON.parse(manifestRaw) as Record<string, unknown>;
    const invalidApproved = approvedCase({ url: 'javascript:alert(1)', canonicalUrl: 'javascript:alert(1)' });
    const indexRaw = JSON.stringify({
      schemaVersion: 1,
      datasetVersion: 'case_catalog_20260715_v1',
      approvedDelta: [invalidApproved],
    });
    const approvedRaw = JSON.stringify([invalidApproved]);
    const nextManifest = {
      ...manifest,
      approvedDelta: {
        ...(manifest.approvedDelta as Record<string, unknown>),
        count: 1,
        contentSha256: sha256(approvedRaw),
      },
      index: {
        ...(manifest.index as Record<string, unknown>),
        sha256: sha256(indexRaw),
      },
    };
    vi.stubGlobal('fetch', publicFetch({
      [CASE_CATALOG_MANIFEST_PATH]: JSON.stringify(nextManifest),
      '/data/cases/case-index.v1.json': indexRaw,
    }));

    const reference = await searchCases('', 'all');
    expect(reference.items.some((item) => item.id === invalidApproved.id)).toBe(false);
    expect(isNavigableCaseUrl(invalidApproved.url)).toBe(false);
  });
});
