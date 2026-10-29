/**
 * Contract harness for a pipeline-generated reports bundle.
 *
 * Set ECHO_REPORTS_BUNDLE_DIR to the directory produced by
 * `scripts/build_reports_bundle.py` (containing manifest.json, report-index.json,
 * validation-receipt.json, business-history-index.json, current/*, archive/*).
 * The test stubs fetch to serve those bytes and then runs the real loader, so the
 * whole frozen v3 contract is exercised before anything is deployed.
 *
 * Without the env var the suite is skipped — CI keeps running unchanged.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { resetCurrentReleaseCacheForTests } from '../release';
import { loadRedditReports, resetReportsCacheForTests } from '../reports';

const bundleDir = process.env.ECHO_REPORTS_BUNDLE_DIR
  ? resolve(process.env.ECHO_REPORTS_BUNDLE_DIR)
  : null;

const datasetVersion = 'reddit_voc_reports_20260723_v3_47c49395e785_history2';
const basePath = `/data/reddit-voc/${datasetVersion}/public`;

function readBundleFile(path: string): Uint8Array {
  return new Uint8Array(readFileSync(join(bundleDir!, path)));
}

function buildRelease(): unknown {
  const manifestBytes = readBundleFile('manifest.json');
  const manifest = JSON.parse(new TextDecoder().decode(manifestBytes)) as {
    lineage_manifest_sha256: string;
  };
  const sha = createHashHex(manifestBytes);
  const fixturePath = resolve(process.cwd(), 'public/data/reddit-voc/current-release.json');
  const release = JSON.parse(readFileSync(fixturePath, 'utf8')) as {
    datasets: Record<string, Record<string, unknown>>;
  };
  release.datasets.reports = {
    ...release.datasets.reports,
    dataset_version: datasetVersion,
    manifest_path: `data/reddit-voc/${datasetVersion}/public/manifest.json`,
    public_manifest_sha256: sha,
    lineage_manifest_sha256: manifest.lineage_manifest_sha256,
  };
  return release;
}

function createHashHex(bytes: Uint8Array): string {
  return createHash('sha256').update(Buffer.from(bytes)).digest('hex');
}

describe.skipIf(!bundleDir)('generated reports bundle', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetReportsCacheForTests();
    resetCurrentReleaseCacheForTests();
  });

  it('passes the frozen v3 contract end to end', async () => {
    const release = buildRelease();
    const routes: Record<string, Uint8Array> = {
      '/data/reddit-voc/current-release.json': new TextEncoder().encode(JSON.stringify(release)),
    };
    const files = [
      'manifest.json',
      'report-index.json',
      'validation-receipt.json',
      'business-history-index.json',
      'current/daily.json',
      'current/weekly.json',
      'current/monthly.json',
      'archive/daily.json',
      'archive/weekly.json',
      'archive/monthly.json',
    ];
    files.forEach((path) => {
      routes[`${basePath}/${path}`] = readBundleFile(path);
    });

    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
      const payload = routes[path];
      if (!payload) {
        return new Response('not found', { status: 404 });
      }
      return new Response(payload as unknown as BodyInit, {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }));

    const snapshot = await loadRedditReports();
    const current = (snapshot as { current: Record<string, { artifact_role?: string; grain?: string }> }).current;
    expect(current.daily.artifact_role).toBe('latest_closed_calendar_period_unattested');
    expect(current.weekly.grain).toBe('weekly');
    expect(current.monthly.grain).toBe('monthly');
  });
});
