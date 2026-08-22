import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  loadRedditQuarterInsights,
  resetRedditQuarterInsightsCacheForTests,
  validatePublicQuarterInsightsData,
  validatePublicQuarterInsightsManifest,
} from '../quarterInsights';

const publicDirectory = resolve(process.cwd(), 'public');
const currentRelease = JSON.parse(readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'));
const quarterBinding = currentRelease.datasets.quarter_insights;
const quarterBasePath = `/${quarterBinding.manifest_path.replace(/\/manifest\.json$/, '')}`;
const quarterDirectory = resolve(publicDirectory, quarterBasePath.slice(1));

function createFetch(tamperPath?: string) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    const original = readFileSync(resolve(publicDirectory, pathname.slice(1)), 'utf8');
    const body = pathname === tamperPath
      ? (pathname.endsWith('/manifest.json')
        ? `${original} `
        : original.replace(/"periodic_comments":(\d+)/, (_match, raw: string) => `"periodic_comments":${Number(raw) + 1}`))
      : original;
    return { ok: true, status: 200, text: async () => body } as Response;
  });
}

function readData() {
  return JSON.parse(readFileSync(resolve(quarterDirectory, 'quarter-insights.json'), 'utf8'));
}

afterEach(() => {
  resetRedditQuarterInsightsCacheForTests();
  vi.unstubAllGlobals();
});

describe('public rolling-quarter insights contract', () => {
  it('loads the pinned governed quarter projection and its formal scopes', async () => {
    const manifest = validatePublicQuarterInsightsManifest(JSON.parse(readFileSync(resolve(quarterDirectory, 'manifest.json'), 'utf8')));
    const data = validatePublicQuarterInsightsData(readData());
    vi.stubGlobal('fetch', createFetch());

    const loaded = await loadRedditQuarterInsights();

    expect(manifest.period).toEqual(data.period);
    expect(data.period).toMatchObject({ days: 90, inclusive: true, timezone: 'Asia/Shanghai' });
    expect(data.counts.momcozy.total_vocs).toBe(
      data.counts.momcozy.post_vocs + data.counts.momcozy.comment_context_vocs,
    );
    expect(data.personas.main_assignment_ids.length).toBeGreaterThan(0);
    expect(data.personas.cohorts.reduce((sum, cohort) => sum + cohort.assignment_count, 0)).toBe(
      data.personas.main_assignment_ids.length,
    );
    expect(data.themes.geo.comparison_decision_posts).toBeGreaterThan(0);
    expect(loaded.data.boundaries.production_unchanged).toBe(true);
  });

  it('rejects count conservation and negative-rate formula drift', () => {
    const comments = readData();
    comments.counts.unresolved_parent_comments += 1;
    expect(() => validatePublicQuarterInsightsData(comments)).toThrow('季度评论总量不守恒');

    const sentiment = readData();
    sentiment.counts.momcozy.sentiment.negative_rate = 5.79;
    expect(() => validatePublicQuarterInsightsData(sentiment)).toThrow('Momcozy负面占比口径不一致');
  });

  it('rejects a wrong period or an inconsistent persona allowlist', () => {
    const period = readData();
    period.period.start_date = '2026-04-19';
    expect(() => validatePublicQuarterInsightsData(period)).toThrow('quarter insights日期与天数不守恒');

    const personas = readData();
    personas.personas.main_assignment_ids.pop();
    expect(() => validatePublicQuarterInsightsData(personas)).toThrow('画像assignment数量或唯一性不一致');
  });

  it('rejects unsafe side-effect claims and privacy-sensitive fields', () => {
    const unsafe = readData();
    unsafe.boundaries.deploy = true;
    expect(() => validatePublicQuarterInsightsData(unsafe)).toThrow('side-effect或解释边界不安全');

    const privateData = readData();
    privateData.themes.pain.evidence[0].author = 'hidden-user';
    expect(() => validatePublicQuarterInsightsData(privateData)).toThrow('隐私或原文字段：author');

    const privatePath = readData();
    privatePath.themes.pain.evidence[0].reason = '/Users/hidden/private.json';
    expect(() => validatePublicQuarterInsightsData(privatePath)).toThrow('包含外链或私有路径');
  });

  it('fails closed when manifest or data bytes change', async () => {
    vi.stubGlobal('fetch', createFetch(`${quarterBasePath}/quarter-insights.json`));
    await expect(loadRedditQuarterInsights()).rejects.toThrow('quarter-insights.json SHA-256不一致');

    resetRedditQuarterInsightsCacheForTests();
    vi.stubGlobal('fetch', createFetch(`${quarterBasePath}/manifest.json`));
    await expect(loadRedditQuarterInsights()).rejects.toThrow('quarter insights manifest SHA-256不一致');
    expect(quarterBinding.public_manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
  });
});
