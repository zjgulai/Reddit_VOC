import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  fetchVerifiedReleaseManifest,
  loadCurrentRelease,
  resetCurrentReleaseCacheForTests,
  validateCurrentRelease,
} from '../release';

const publicDirectory = resolve(process.cwd(), 'public');
const pointerPath = resolve(publicDirectory, 'data/reddit-voc/current-release.json');
const pointerRaw = readFileSync(pointerPath, 'utf8');
const release = validateCurrentRelease(JSON.parse(pointerRaw));

function sha256(raw: string): string {
  return createHash('sha256').update(raw).digest('hex');
}

function publicFetch(overrides: Record<string, string> = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    const raw = overrides[pathname]
      ?? readFileSync(resolve(publicDirectory, pathname.slice(1)), 'utf8');
    return {
      ok: true,
      status: 200,
      text: async () => raw,
    } as Response;
  });
}

afterEach(() => {
  resetCurrentReleaseCacheForTests();
  vi.unstubAllGlobals();
});

describe('current Reddit VOC release pointer', () => {
  it('accepts a v2 pointer that binds all data-dependent page projections and explicit freshness', () => {
    const v2 = validateCurrentRelease(JSON.parse(pointerRaw));

    expect(v2.schema_version).toBe('reddit_voc_current_release_v2');
    expect(v2.datasets.brand_health?.dataset_version).toMatch(/^reddit_voc_brand_health_/);
    expect(v2.datasets.quarter_insights?.dataset_version).toMatch(/^reddit_voc_quarter_insights_/);
    expect(v2.datasets.casebook?.dataset_version).toMatch(/^reddit_voc_casebook_/);
    expect(v2.freshness?.status).toBe('partial');
    expect(v2.freshness?.net_new.posts).toBeGreaterThan(0);
  });

  it('rejects a v2 pointer whose freshness window or net-new ledger is invalid', () => {
    const baseV2 = {
      ...release,
      schema_version: 'reddit_voc_current_release_v2',
      datasets: {
        ...release.datasets,
        brand_health: {
          dataset_version: 'reddit_voc_brand_health_fixture',
          manifest_path: 'data/reddit-voc/reddit_voc_brand_health_fixture/manifest.json',
          public_manifest_sha256: 'a'.repeat(64),
          lineage_manifest_sha256: 'a'.repeat(64),
        },
        quarter_insights: {
          dataset_version: 'reddit_voc_quarter_insights_fixture',
          manifest_path: 'data/reddit-voc/reddit_voc_quarter_insights_fixture/manifest.json',
          public_manifest_sha256: 'b'.repeat(64),
          lineage_manifest_sha256: 'b'.repeat(64),
        },
        casebook: {
          dataset_version: 'reddit_voc_casebook_fixture',
          manifest_path: 'data/reddit-voc/reddit_voc_casebook_fixture/manifest.json',
          public_manifest_sha256: 'c'.repeat(64),
          lineage_manifest_sha256: 'c'.repeat(64),
        },
      },
      freshness: {
        status: 'full',
        timezone: 'Asia/Shanghai',
        data_as_of_utc: '2026-07-22T23:00:00Z',
        window_start_utc: '2026-07-22T23:00:00Z',
        window_end_utc: '2026-07-22T23:00:00Z',
        collector_run_id: 'daily_collect_20260723_0700',
        source_batch_id: 'daily_collect_20260723_0700',
        center_snapshot_id: 'reddit_voc_center_20260723_v3',
        net_new: {
          posts: -1,
          comments: 0,
          updated_historical_posts: 0,
          repaired_parent_links: 0,
        },
        coverage: {
          full_posts: 12,
          partial_posts: 0,
          unresolved_continuations: 0,
        },
      },
    };
    expect(() => validateCurrentRelease(baseV2)).toThrow(/freshness 窗口无效/);
  });

  it('pins every public manifest while keeping public and lineage hashes semantically separate', () => {
    for (const binding of Object.values(release.datasets)) {
      const raw = readFileSync(resolve(publicDirectory, binding.manifest_path), 'utf8');
      expect(sha256(raw)).toBe(binding.public_manifest_sha256);
      expect(binding.lineage_manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
    }
    expect(release.datasets.base.public_manifest_sha256)
      .not.toBe(release.datasets.base.lineage_manifest_sha256);
    expect(release.datasets.insights.public_manifest_sha256)
      .not.toBe(release.datasets.insights.lineage_manifest_sha256);

    const caseManifestRaw = readFileSync(resolve(publicDirectory, release.cases.manifest_path), 'utf8');
    const caseManifest = JSON.parse(caseManifestRaw) as {
      datasetVersion: string;
      approvedDelta: { count: number };
      index: { path: string; sha256: string };
    };
    expect(sha256(caseManifestRaw)).toBe(release.cases.public_manifest_sha256);
    expect(caseManifest.datasetVersion).toBe(release.cases.dataset_version);
    expect(caseManifest.index.path).toBe(`/${release.cases.index_path}`);
    expect(caseManifest.index.sha256).toBe(release.cases.index_sha256);
    expect(caseManifest.approvedDelta.count).toBe(release.cases.approved_delta_count);
    expect(release.cases.stock_content_preserved).toBe(true);
    expect(release.boundaries).toEqual({
      case_gallery_stock_preserved: true,
      collector_isolation_required: true,
      login_required: false,
    });
  });

  it('deduplicates concurrent pointer requests at module scope', async () => {
    const fetchMock = publicFetch();
    vi.stubGlobal('fetch', fetchMock);

    const first = loadCurrentRelease();
    const second = loadCurrentRelease();

    expect(first).toBe(second);
    await expect(Promise.all([first, second])).resolves.toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('fails closed on invalid pointer JSON before requesting any dataset', async () => {
    const pointerUrl = '/data/reddit-voc/current-release.json';
    const fetchMock = publicFetch({ [pointerUrl]: '{' });
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadCurrentRelease()).rejects.toThrow('current release 不是有效 JSON');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost').pathname).toBe(pointerUrl);
  });

  it('rejects pointer traversal and unexpected fields before any dataset request', () => {
    expect(() => validateCurrentRelease({
      ...release,
      datasets: {
        ...release.datasets,
        base: {
          ...release.datasets.base,
          dataset_version: '../snapshot',
          manifest_path: 'data/reddit-voc/../snapshot/manifest-public.json',
        },
      },
    })).toThrow(/不是安全版本名/);

    expect(() => validateCurrentRelease({ ...release, ungoverned_path: '/tmp/data.json' }))
      .toThrow(/字段集合异常/);
  });

  it('verifies manifest bytes before attempting to parse a tampered manifest', async () => {
    const manifestPath = `/${release.datasets.base.manifest_path}`;
    vi.stubGlobal('fetch', publicFetch({ [manifestPath]: '{' }));

    const loadedRelease = await loadCurrentRelease();
    await expect(fetchVerifiedReleaseManifest(loadedRelease, 'base'))
      .rejects.toThrow('发布 manifest SHA-256 不一致：base');
  });
});
