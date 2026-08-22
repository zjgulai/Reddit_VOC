import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import {
  ReportsContractError,
  V3_REPORTS_MANIFEST_SCHEMA,
  isV3ReportsSnapshot,
  loadRedditReports,
  loadV3HistoricalReport,
  resetReportsCacheForTests,
  validateReportsSnapshot,
  validateV3CurrentReport,
} from '../reports';
import type {
  RedditReport,
  RedditReportsSnapshot,
  ReportIndex,
  ReportManifest,
  RiskRedditReport,
  V3CurrentReport,
} from '../reports';
import { isRiskReport } from '../reports';
import {
  resetCurrentReleaseCacheForTests,
  validateCurrentRelease,
} from '../release';

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
));
const reportsDatasetVersion = release.datasets.reports.dataset_version;
const reportsDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  reportsDatasetVersion,
  'public',
);
const currentReportsManifest = JSON.parse(
  readFileSync(resolve(reportsDirectory, 'manifest.json'), 'utf8'),
) as { schema_version?: unknown };
const isV3CurrentRelease = currentReportsManifest.schema_version === V3_REPORTS_MANIFEST_SCHEMA;
const fallbackV3DatasetVersion = 'reddit_voc_reports_20260716_v3_1ab1c634f225';
const v3ReportsPublicDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  isV3CurrentRelease ? reportsDatasetVersion : fallbackV3DatasetVersion,
  'public',
);
const hasV3PublicFixture = existsSync(resolve(v3ReportsPublicDirectory, 'manifest.json'));
const legacyIt = isV3CurrentRelease ? it.skip : it;
const v3It = hasV3PublicFixture ? it : it.skip;
const hasV3HistoryFixture = hasV3PublicFixture
  && (JSON.parse(readFileSync(
    resolve(v3ReportsPublicDirectory, 'business-history-index.json'),
    'utf8',
  )) as { history_entry_count: number }).history_entry_count > 0;
const v3HistoryIt = hasV3HistoryFixture ? it : it.skip;

function readJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(reportsDirectory, filename), 'utf8')) as T;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function createPublicFetch(tamperPath?: string) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    const original = readFileSync(resolve(publicDirectory, pathname.slice(1)), 'utf8');
    const body = pathname === tamperPath ? `${original}\n` : original;
    return {
      ok: true,
      status: 200,
      text: async () => body,
    } as Response;
  });
}

function createV3PublicFetch(tamperPath?: string) {
  const publicManifest = readFileSync(resolve(v3ReportsPublicDirectory, 'manifest.json'));
  const publicManifestSha256 = createHash('sha256').update(publicManifest).digest('hex');
  const publicManifestValue = JSON.parse(publicManifest.toString('utf8')) as {
    dataset_version: string;
    lineage_manifest_sha256: string;
  };
  const v3Release = clone(release);
  v3Release.datasets.reports = {
    dataset_version: publicManifestValue.dataset_version,
    manifest_path: `data/reddit-voc/${publicManifestValue.dataset_version}/public/manifest.json`,
    public_manifest_sha256: publicManifestSha256,
    lineage_manifest_sha256: publicManifestValue.lineage_manifest_sha256,
  };
  const prefix = `/data/reddit-voc/${publicManifestValue.dataset_version}/public/`;
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    let body: string;
    if (pathname === '/data/reddit-voc/current-release.json') {
      body = JSON.stringify(v3Release);
    } else {
      if (!pathname.startsWith(prefix)) throw new Error(`unexpected report path: ${pathname}`);
      const relativePath = pathname.slice(prefix.length);
      body = relativePath === 'manifest.json'
        ? publicManifest.toString('utf8')
        : readFileSync(resolve(v3ReportsPublicDirectory, relativePath), 'utf8');
    }
    if (pathname === tamperPath) body = `${body}\n`;
    return {
      ok: true,
      status: 200,
      text: async () => body,
    } as Response;
  });
}

let manifest: ReportManifest;
let index: ReportIndex;
let reportsByPath: Record<string, RedditReport>;
let snapshot: RedditReportsSnapshot;

beforeAll(() => {
  if (isV3CurrentRelease) return;
  manifest = readJson<ReportManifest>('manifest.json');
  index = readJson<ReportIndex>('report-index.json');
  reportsByPath = Object.fromEntries(
    Object.keys(manifest.files)
      .filter((filename) => filename !== 'report-index.json')
      .map((filename) => [filename, readJson<RedditReport>(filename)]),
  );
  snapshot = validateReportsSnapshot(manifest, index, reportsByPath, release);
});

describe('real static report contract', () => {
  afterEach(() => {
    resetReportsCacheForTests();
    resetCurrentReleaseCacheForTests();
    vi.unstubAllGlobals();
  });

  legacyIt('loads the exact public daily, weekly, and monthly files with integrity checks', async () => {
    const fetchMock = createPublicFetch();
    vi.stubGlobal('fetch', fetchMock);

    const loaded = await loadRedditReports();

    expect(isV3ReportsSnapshot(loaded)).toBe(false);
    if (isV3ReportsSnapshot(loaded)) throw new Error('expected legacy report snapshot');
    expect(loaded.current.daily.headline).toMatchObject({ posts: 75, voc_comments: 509 });
    expect(fetchMock).toHaveBeenCalledTimes(9);
    const paths = fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost').pathname);
    expect(paths.filter((path) => path === '/data/reddit-voc/current-release.json')).toHaveLength(1);
    expect(paths.filter((path) => path.startsWith(
      `/data/reddit-voc/${reportsDatasetVersion}/public/`,
    ))).toHaveLength(8);
  });

  legacyIt('fails closed before parsing when the pointer-bound report manifest changes', async () => {
    vi.stubGlobal('fetch', createPublicFetch(
      `/data/reddit-voc/${reportsDatasetVersion}/public/manifest.json`,
    ));

    await expect(loadRedditReports()).rejects.toThrow('发布 manifest SHA-256 不一致：reports');
  });

  v3It('detects a pointer-selected V3 candidate and refuses consumption without silently falling back', async () => {
    const publicManifest = JSON.parse(
      readFileSync(resolve(v3ReportsPublicDirectory, 'manifest.json'), 'utf8'),
    ) as Record<string, unknown>;
    const candidateManifest = Buffer.from(JSON.stringify({
      ...publicManifest,
      schema_version: 'reddit_voc_reports_manifest_v3',
    }));
    const candidateManifestSha256 = createHash('sha256').update(candidateManifest).digest('hex');
    const candidateDatasetVersion = 'reddit_voc_reports_20260716_v3_a1';
    const candidateRelease = clone(release);
    candidateRelease.datasets.reports = {
      dataset_version: candidateDatasetVersion,
      manifest_path: `data/reddit-voc/${candidateDatasetVersion}/public/manifest.json`,
      public_manifest_sha256: candidateManifestSha256,
      lineage_manifest_sha256: candidateManifestSha256,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const pathname = new URL(String(input), 'http://localhost').pathname;
      const body = pathname === '/data/reddit-voc/current-release.json'
        ? JSON.stringify(candidateRelease)
        : candidateManifest.toString('utf8');
      return {
        ok: true,
        status: 200,
        text: async () => body,
      } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadRedditReports()).rejects.toThrow(
      'V3 报告 candidate 尚未通过 public wrapper 独立验证，禁止消费且不回退 V1/V2',
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  v3It('loads only the validated V3 bootstrap and exposes current plus indexed history entries', async () => {
    const fetchMock = createV3PublicFetch();
    vi.stubGlobal('fetch', fetchMock);

    const loaded = await loadRedditReports();

    expect(isV3ReportsSnapshot(loaded)).toBe(true);
    if (!isV3ReportsSnapshot(loaded)) throw new Error('expected V3 report snapshot');
    expect(loaded.manifest.status).toBe('validated_candidate');
    expect(loaded.index.business_entry_count).toBe(
      loaded.index.current_entry_count + (loaded.historyIndex?.history_entry_count ?? 0),
    );
    expect(loaded.historyIndex?.history_entry_count).toBe(
      (loaded.historyIndex?.reports.daily.length ?? 0)
      + (loaded.historyIndex?.reports.weekly.length ?? 0)
      + (loaded.historyIndex?.reports.monthly.length ?? 0),
    );
    expect(Object.keys(loaded.current).sort()).toEqual(['daily', 'monthly', 'weekly']);
    expect(loaded.current.daily.indicators.find(({ metric_id }) => metric_id === 'RV-BR-01')?.current.display).toBeTruthy();
    expect(loaded).not.toHaveProperty('archive');
    expect(fetchMock).toHaveBeenCalledTimes(11);
    expect(fetchMock.mock.calls.some(([input]) => (
      new URL(String(input), 'http://localhost').pathname.includes('/history/')
    ))).toBe(false);
  });

  v3It('accepts labeled provisional comparisons for a closed observed historical report', () => {
    const report = readJson<V3CurrentReport>('current/daily.json');
    report.artifact_role = 'historical_observed_calendar_period_unattested';
    report.entry_label = '历史已观测周期（覆盖未证明）';
    report.business_entry_visible = true;
    delete report.comparison_archive_path;
    report.comparison_contract_proven = false;
    report.comparison_contract_basis = 'not_owner_attested';
    report.completeness_percent = null;
    report.coverage_attestation = null;
    report.data_owner_coverage_attestation_sha256 = null;
    if (report.period_activity) {
      report.period_activity.period_complete = false;
      report.period_activity.comparison_contract_proven = false;
      report.period_activity.data_owner_coverage_attestation_sha256 = null;
    }
    report.indicators.forEach((indicator) => {
      indicator.current.period_complete = false;
      indicator.current.comparison_contract_proven = false;
      indicator.current.data_owner_coverage_attestation_sha256 = null;
      indicator.direction = null;
      indicator.line_color = 'gray';
      Object.entries(indicator.comparisons).forEach(([kind, comparison]) => {
        if (comparison.status === 'unavailable') return;
        comparison.status = 'provisional';
        comparison.line_color = 'blue';
        comparison.comparison_basis = 'exact_period';
        comparison.display_label = kind === 'period_over_period' ? '环比（观测口径）' : '同比（观测口径）';
        comparison.reason_codes = ['owner_attestation_missing_observed_same_profile'];
      });
      if (indicator.sparkline.status !== 'unavailable') {
        indicator.sparkline.status = 'provisional';
        indicator.sparkline.line_color = 'blue';
        indicator.sparkline.reason_codes = ['owner_attestation_missing_observed_same_profile'];
      }
      indicator.sparkline.trend_claim_supported = false;
    });

    expect(validateV3CurrentReport(report)).toBe(report);
    expect(report.comparison_contract_proven).toBe(false);
    expect(report.completeness_percent).toBeNull();
    expect(report.indicators.every((indicator) => (
      Object.values(indicator.comparisons).every((comparison) => (
        comparison.status === 'unavailable' || comparison.status === 'provisional'
      ))
      && indicator.sparkline.trend_claim_supported === false
    ))).toBe(true);
    expect(report.indicators.some((indicator) => (
      Object.values(indicator.comparisons).some((comparison) => comparison.status === 'provisional')
    ))).toBe(true);
  });

  v3HistoryIt('loads one descriptor-bound history report lazily, verifies it, and caches it', async () => {
    const fetchMock = createV3PublicFetch();
    vi.stubGlobal('fetch', fetchMock);
    const loaded = await loadRedditReports();
    if (!isV3ReportsSnapshot(loaded) || !loaded.historyIndex) throw new Error('expected V3 history index');
    const entry = loaded.historyIndex.reports.daily[0];
    const callsBeforeHistory = fetchMock.mock.calls.length;

    const first = await loadV3HistoricalReport(loaded, 'daily', entry.period.period_id);

    expect(first.period).toEqual(entry.period);
    expect(first.artifact_role).toBe(
      loaded.manifest.comparison_contract_proven
        ? 'historical_complete_calendar_period'
        : 'historical_observed_calendar_period_unattested',
    );
    expect(fetchMock.mock.calls).toHaveLength(callsBeforeHistory + 1);
    expect(new URL(String(fetchMock.mock.calls.at(-1)?.[0]), 'http://localhost').pathname)
      .toContain(`/${entry.artifact_path}`);

    const second = await loadV3HistoricalReport(loaded, 'daily', entry.period.period_id);
    expect(second).toBe(first);
    expect(fetchMock.mock.calls).toHaveLength(callsBeforeHistory + 1);
  });

  v3HistoryIt('fails closed when one descriptor-bound history report is tampered', async () => {
    const historyIndex = JSON.parse(
      readFileSync(resolve(v3ReportsPublicDirectory, 'business-history-index.json'), 'utf8'),
    ) as { reports: { daily: Array<{ artifact_path: string; period: { period_id: string } }> } };
    const entry = historyIndex.reports.daily[0];
    const publicManifest = JSON.parse(
      readFileSync(resolve(v3ReportsPublicDirectory, 'manifest.json'), 'utf8'),
    ) as { dataset_version: string };
    const tamperPath = `/data/reddit-voc/${publicManifest.dataset_version}/public/${entry.artifact_path}`;
    vi.stubGlobal('fetch', createV3PublicFetch(tamperPath));
    const loaded = await loadRedditReports();
    if (!isV3ReportsSnapshot(loaded)) throw new Error('expected V3 report snapshot');

    await expect(loadV3HistoricalReport(loaded, 'daily', entry.period.period_id))
      .rejects.toThrow(/真实报告文件 (?:bytes|SHA-256) 不一致/);
  });

  v3It('rejects an unknown period id before issuing any history request', async () => {
    const fetchMock = createV3PublicFetch();
    vi.stubGlobal('fetch', fetchMock);
    const loaded = await loadRedditReports();
    if (!isV3ReportsSnapshot(loaded)) throw new Error('expected V3 report snapshot');
    const callsBeforeHistory = fetchMock.mock.calls.length;

    expect(() => loadV3HistoricalReport(loaded, 'daily', 'daily:2099-01-01'))
      .toThrow('该历史周期不属于当前报告数据版本');
    expect(fetchMock.mock.calls).toHaveLength(callsBeforeHistory);
  });

  v3It('fails closed on a tampered V3 file and never probes the legacy dataset', async () => {
    const publicManifest = JSON.parse(
      readFileSync(resolve(v3ReportsPublicDirectory, 'manifest.json'), 'utf8'),
    ) as { dataset_version: string };
    const tamperPath = `/data/reddit-voc/${publicManifest.dataset_version}/public/current/daily.json`;
    const fetchMock = createV3PublicFetch(tamperPath);
    vi.stubGlobal('fetch', fetchMock);

    await expect(loadRedditReports()).rejects.toThrow(/真实报告文件 (?:bytes|SHA-256) 不一致：current\/daily\.json/);
    const paths = fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost').pathname);
    expect(paths
      .filter((path) => path !== '/data/reddit-voc/current-release.json')
      .every((path) => path.startsWith(
        `/data/reddit-voc/${publicManifest.dataset_version}/public/`,
      ))).toBe(true);
  });

  legacyIt('validates all current and archive reports with real counts', () => {
    expect(snapshot.manifest.dataset_version).toBe(reportsDatasetVersion);
    expect([
      snapshot.current.daily.headline,
      snapshot.current.weekly.headline,
      snapshot.current.monthly.headline,
      snapshot.archive.daily.headline,
      snapshot.archive.weekly.headline,
      snapshot.archive.monthly.headline,
    ].map(({ posts, voc_comments }) => ({ posts, voc_comments }))).toEqual([
      { posts: 75, voc_comments: 509 },
      { posts: 146, voc_comments: 2845 },
      { posts: 250, voc_comments: 2304 },
      { posts: 28, voc_comments: 350 },
      { posts: 88, voc_comments: 849 },
      { posts: 103, voc_comments: 660 },
    ]);
    expect(snapshot.current.daily.identity.display_name).toBe(index.current.daily.display_name);
    expect(snapshot.archive.monthly.identity.display_name).toBe(index.archive.monthly.display_name);
    expect(snapshot.archive.monthly.window.coverage_status).toBe('partial');
    expect(snapshot.archive.monthly.window.comparison_status).toBe('provisional_observed_sample');
  });

  legacyIt('rejects private risk field injection in the public report projection', () => {
    const tamperedReports = clone(reportsByPath);
    const weekly = tamperedReports[index.current.weekly.path] as RiskRedditReport;
    (weekly.risk_themes[0] as unknown as Record<string, unknown>).dictionary_default_priority = 'P0';

    expect(() => validateReportsSnapshot(manifest, index, tamperedReports, release)).toThrowError(
      ReportsContractError,
    );
    expect(() => validateReportsSnapshot(manifest, index, tamperedReports, release)).toThrow(
      /公开风险主题包含内部字段/,
    );
  });

  legacyIt('rejects static report side-effect overclaims', () => {
    const tamperedReports = clone(reportsByPath);
    tamperedReports[index.current.monthly.path].runtime_boundaries.webhook_send = true;

    expect(() => validateReportsSnapshot(manifest, index, tamperedReports, release)).toThrow(
      /报告静态副作用边界异常/,
    );
  });

  legacyIt('rejects an index/headline count mismatch', () => {
    const tamperedReports = clone(reportsByPath);
    tamperedReports[index.current.daily.path].headline.posts += 1;

    expect(() => validateReportsSnapshot(manifest, index, tamperedReports, release)).toThrow(
      /headline 与 index 不一致/,
    );
  });

  legacyIt('keeps public risk evidence ID-only and private action fields absent', () => {
    for (const report of [...Object.values(snapshot.current), ...Object.values(snapshot.archive)]) {
      expect(isRiskReport(report)).toBe(true);
      if (!isRiskReport(report)) continue;
      for (const theme of report.risk_themes) {
        for (const evidence of theme.evidence_refs) {
          expect(Object.keys(evidence).sort()).toEqual(['entity_id', 'entity_type', 'post_id']);
        }
        expect(theme).not.toHaveProperty('business_impact');
        expect(theme).not.toHaveProperty('dept_owner');
        expect(theme).not.toHaveProperty('suggested_action');
      }
    }
  });
});
