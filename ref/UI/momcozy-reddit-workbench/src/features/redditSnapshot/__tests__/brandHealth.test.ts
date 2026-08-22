import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  loadRedditBrandHealth,
  resetRedditBrandHealthCacheForTests,
  validatePublicBrandHealthData,
  validatePublicBrandHealthManifest,
} from '../brandHealth';

const publicDirectory = resolve(process.cwd(), 'public');
const currentRelease = JSON.parse(readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'));
const brandHealthBinding = currentRelease.datasets.brand_health;
const brandHealthBasePath = `/${brandHealthBinding.manifest_path.replace(/\/manifest\.json$/, '')}`;
const brandHealthDirectory = resolve(publicDirectory, brandHealthBasePath.slice(1));

function createFetch(tamperPath?: string) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    const original = readFileSync(resolve(publicDirectory, pathname.slice(1)), 'utf8');
    const body = pathname === tamperPath
      ? (pathname.endsWith('/manifest.json')
        ? `${original} `
        : original.replace(/"score":(\d+\.\d+)/, (_match, raw: string) => `"score":${(Number(raw) + 0.01).toFixed(2)}`))
      : original;
    return { ok: true, status: 200, text: async () => body } as Response;
  });
}

afterEach(() => {
  resetRedditBrandHealthCacheForTests();
  vi.unstubAllGlobals();
});

describe('public V3 brand-health contract', () => {
  it('loads the pinned privacy-safe projection with finite formal scores', async () => {
    const manifest = validatePublicBrandHealthManifest(JSON.parse(readFileSync(resolve(brandHealthDirectory, 'manifest.json'), 'utf8')));
    const data = validatePublicBrandHealthData(JSON.parse(readFileSync(resolve(brandHealthDirectory, 'brand-health.json'), 'utf8')));
    vi.stubGlobal('fetch', createFetch());

    const loaded = await loadRedditBrandHealth();

    expect(manifest.source_metrics_manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(data.dimensions).toHaveLength(4);
    expect(loaded.data.dimensions).toEqual(data.dimensions);
    expect(loaded.data.overall).toEqual(data.overall);
    expect(loaded.data.overall.status).toBe('provisional');
    expect(data.dimensions.every((item) => Number.isFinite(item.score))).toBe(true);
  });

  it('rejects an out-of-range overall score before rendering', () => {
    const data = JSON.parse(readFileSync(resolve(brandHealthDirectory, 'brand-health.json'), 'utf8'));
    data.overall = { reason_codes: [], score: 100.01, status: 'available' };

    expect(() => validatePublicBrandHealthData(data)).toThrow('score必须在0到100之间');
  });

  it('fails closed when the manifest or data bytes change', async () => {
    vi.stubGlobal('fetch', createFetch(`${brandHealthBasePath}/brand-health.json`));
    await expect(loadRedditBrandHealth()).rejects.toThrow('brand-health.json SHA-256不一致');

    resetRedditBrandHealthCacheForTests();
    vi.stubGlobal('fetch', createFetch(`${brandHealthBasePath}/manifest.json`));
    await expect(loadRedditBrandHealth()).rejects.toThrow('brand health manifest SHA-256不一致');
    expect(brandHealthBinding.public_manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
  });
});
