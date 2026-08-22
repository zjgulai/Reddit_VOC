import type { CurrentRelease } from './release';
import type { RedditSnapshotSummary } from './types';

export type FreshnessEvidenceStatus = 'verified' | 'provisional' | 'unavailable';
export type ReleaseRecencyStatus =
  | 'fresh'
  | 'partial'
  | 'awaiting'
  | 'stalled'
  | 'stale'
  | 'failed'
  | 'rollback'
  | 'unavailable';
export type CoverageEvidenceStatus = 'complete' | 'partial' | 'owner-attested' | 'unavailable';

export interface ReleaseTemporalContext {
  timezone: 'Asia/Shanghai';
  currentTimeUtc: string;
  dataAsOfUtc: string | null;
  observationMaxUtc: string | null;
  expectedPeriodEndUtc: string;
  deadlineUtc: string;
  lagSeconds: number | null;
  recencyStatus: ReleaseRecencyStatus;
  collectorRunId: string | null;
  sourceBatchId: string | null;
  releaseWindowStartUtc: string | null;
  releaseWindowEndUtc: string | null;
}

export interface DataFreshnessEvidence {
  status: FreshnessEvidenceStatus;
  statusLabel: string;
  recencyStatus: ReleaseRecencyStatus;
  recencyLabel: string;
  coverageStatus: CoverageEvidenceStatus;
  coverageLabel: string;
  currentTime: string;
  currentTimeLabel: string;
  dataAsOfLabel: string;
  dataAsOf: string | null;
  dataAsOfBasis: string;
  observationMax: string | null;
  expectedPeriodEnd: string;
  deadline: string;
  lagSeconds: number | null;
  collectorRunId: string | null;
  sourceBatchId: string | null;
  releaseId: string;
  releaseGeneratedAtUtc: string;
  centerSnapshotId: string | null;
  projectionDatasetVersion: string;
  projectionGeneratedAtUtc: string | null;
  projectionAsOfLabel: string | null;
  projectionAsOf: string | null;
  projectionAsOfBasis: string | null;
  completenessPercent: number | null;
  completenessBasis: string | null;
  evidenceClass: string | null;
  releaseWindowStart: string | null;
  releaseWindowEnd: string | null;
  coverageWindowStart: string | null;
  coverageWindowEnd: string | null;
  structuralCoverage?: {
    full: number;
    partial: number;
    postOnly: number;
    sourceObserved: number;
    unresolvedParentComments: number;
  };
}

export interface BaseFreshnessOverrides {
  status?: FreshnessEvidenceStatus;
  statusLabel?: string;
  projectionAsOfLabel?: string;
  projectionAsOf?: string | null;
  projectionAsOfBasis?: string;
  projectionDatasetVersion?: string;
  projectionGeneratedAtUtc?: string | null;
  completenessPercent?: number | null;
  completenessBasis?: string | null;
  evidenceClass?: string | null;
  coverageWindowStart?: string | null;
  coverageWindowEnd?: string | null;
  now?: Date | string | number;
  sloMinutes?: number;
}

function latestTimestamp(values: Array<string | null | undefined>): string | null {
  const valid = values.filter((value): value is string => (
    typeof value === 'string' && Number.isFinite(Date.parse(value))
  ));
  return valid.sort((left, right) => Date.parse(right) - Date.parse(left))[0] ?? null;
}

function toDate(value: Date | string | number): Date {
  const parsed = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  if (Number.isNaN(parsed.getTime())) throw new Error('当前时间无效');
  return parsed;
}

/** Mirrors scripts/observe_reddit_data_release.py for the evidence available in the public release. */
export function latestClosedShanghaiPeriod(observedAt: Date): Date {
  const close = new Date(observedAt);
  close.setUTCHours(23, 0, 0, 0);
  if (close.getTime() > observedAt.getTime()) close.setUTCDate(close.getUTCDate() - 1);
  return close;
}

export function createReleaseTemporalContext(
  release: CurrentRelease,
  observationMaxUtc: string | null,
  options: { now?: Date | string | number; sloMinutes?: number } = {},
): ReleaseTemporalContext {
  const observedAt = toDate(options.now ?? Date.now());
  const sloMinutes = options.sloMinutes ?? 90;
  if (!Number.isFinite(sloMinutes) || sloMinutes <= 0) throw new Error('SLO 分钟数必须为正数');

  const expectedPeriodEnd = latestClosedShanghaiPeriod(observedAt);
  const deadline = new Date(expectedPeriodEnd.getTime() + sloMinutes * 60_000);
  const releaseFreshness = release.freshness;
  const dataAsOfUtc = releaseFreshness?.data_as_of_utc ?? observationMaxUtc;
  const dataAsOfMs = dataAsOfUtc ? Date.parse(dataAsOfUtc) : Number.NaN;
  const hasDataAsOf = Number.isFinite(dataAsOfMs);
  const isCurrentPeriod = hasDataAsOf && dataAsOfMs === expectedPeriodEnd.getTime();

  let recencyStatus: ReleaseRecencyStatus;
  if (!releaseFreshness || !hasDataAsOf) {
    recencyStatus = 'unavailable';
  } else if (dataAsOfMs > expectedPeriodEnd.getTime()) {
    recencyStatus = 'failed';
  } else if (isCurrentPeriod && releaseFreshness.status === 'partial') {
    recencyStatus = 'partial';
  } else if (isCurrentPeriod) {
    recencyStatus = 'fresh';
  } else if (observedAt.getTime() <= deadline.getTime()) {
    recencyStatus = 'awaiting';
  } else {
    // The public bundle contains no current-period attempt receipt. Match the backend's
    // fail-closed branch: after the deadline, absence of a current attempt is stalled.
    recencyStatus = 'stalled';
  }

  return {
    timezone: 'Asia/Shanghai',
    currentTimeUtc: observedAt.toISOString(),
    dataAsOfUtc: hasDataAsOf ? dataAsOfUtc : null,
    observationMaxUtc,
    expectedPeriodEndUtc: expectedPeriodEnd.toISOString(),
    deadlineUtc: deadline.toISOString(),
    lagSeconds: hasDataAsOf ? Math.max(0, Math.floor((observedAt.getTime() - dataAsOfMs) / 1000)) : null,
    recencyStatus,
    collectorRunId: releaseFreshness?.collector_run_id ?? null,
    sourceBatchId: releaseFreshness?.source_batch_id ?? null,
    releaseWindowStartUtc: releaseFreshness?.window_start_utc ?? null,
    releaseWindowEndUtc: releaseFreshness?.window_end_utc ?? null,
  };
}

function formatLag(seconds: number | null): string {
  if (seconds === null) return '时效未知';
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days > 0) return `${days}天${hours}小时`;
  if (hours > 0) return `${hours}小时${minutes}分钟`;
  return `${minutes}分钟`;
}

function recencyLabel(context: ReleaseTemporalContext): string {
  switch (context.recencyStatus) {
    case 'fresh': return '数据周期已更新';
    case 'partial': return '当前周期部分完成';
    case 'awaiting': return '等待当前周期发布';
    case 'stalled': return `数据链路已停滞 ${formatLag(context.lagSeconds)}`;
    case 'stale': return `数据发布已滞后 ${formatLag(context.lagSeconds)}`;
    case 'failed': return '数据时效校验失败';
    case 'rollback': return '当前版本来自回滚';
    case 'unavailable': return '新鲜度证据未提供';
  }
}

function coverageStatus(
  snapshot: RedditSnapshotSummary,
  completenessPercent: number | null,
  completenessBasis: string | null,
): CoverageEvidenceStatus {
  if (snapshot.release.freshness?.status === 'partial') return 'partial';
  if (completenessPercent === null) return 'unavailable';
  if (completenessBasis === 'data_owner_declaration') return 'owner-attested';
  return completenessPercent >= 100 ? 'complete' : 'partial';
}

function coverageLabel(status: CoverageEvidenceStatus, completenessPercent: number | null): string {
  switch (status) {
    case 'complete': return '覆盖完整';
    case 'partial': return '覆盖部分完成';
    case 'owner-attested': return `覆盖由所有者声明${completenessPercent === null ? '' : ` ${completenessPercent}%`}`;
    case 'unavailable': return '覆盖证据未提供';
  }
}

export function createBaseDataFreshness(
  snapshot: RedditSnapshotSummary,
  overrides: BaseFreshnessOverrides = {},
): DataFreshnessEvidence {
  const manifest = snapshot.manifest;
  const coverage = snapshot.aggregates.coverage_grade;
  const latestObservedEvent = latestTimestamp([
    snapshot.aggregates.date_range.posts[1],
    snapshot.aggregates.date_range.comments[1],
  ]);
  const temporal = createReleaseTemporalContext(snapshot.release, latestObservedEvent, {
    now: overrides.now,
    sloMinutes: overrides.sloMinutes,
  });
  const completenessPercent = overrides.completenessPercent === undefined
    ? manifest.completeness_percent ?? null
    : overrides.completenessPercent;
  const completenessBasis = overrides.completenessBasis === undefined
    ? manifest.completeness_basis ?? null
    : overrides.completenessBasis;
  const resolvedCoverageStatus = coverageStatus(snapshot, completenessPercent, completenessBasis);

  return {
    status: overrides.status ?? 'verified',
    statusLabel: overrides.statusLabel ?? '版本完整性已校验',
    recencyStatus: temporal.recencyStatus,
    recencyLabel: recencyLabel(temporal),
    coverageStatus: resolvedCoverageStatus,
    coverageLabel: coverageLabel(resolvedCoverageStatus, completenessPercent),
    currentTime: temporal.currentTimeUtc,
    currentTimeLabel: '当前北京时间',
    dataAsOfLabel: snapshot.release.freshness ? '发布数据截至' : '最新观测事件',
    dataAsOf: temporal.dataAsOfUtc,
    dataAsOfBasis: snapshot.release.freshness
      ? '来自 current release freshness.data_as_of_utc，表示已发布数据周期边界'
      : '旧版 release 未提供 freshness；暂以 Base 聚合 date_range 上界作为观测时间',
    observationMax: temporal.observationMaxUtc,
    expectedPeriodEnd: temporal.expectedPeriodEndUtc,
    deadline: temporal.deadlineUtc,
    lagSeconds: temporal.lagSeconds,
    collectorRunId: temporal.collectorRunId,
    sourceBatchId: temporal.sourceBatchId,
    releaseId: snapshot.release.release_id,
    releaseGeneratedAtUtc: snapshot.release.generated_at_utc,
    centerSnapshotId: snapshot.release.freshness?.center_snapshot_id ?? manifest.source_snapshot_id ?? null,
    projectionDatasetVersion: overrides.projectionDatasetVersion ?? manifest.dataset_version,
    projectionGeneratedAtUtc: overrides.projectionGeneratedAtUtc === undefined
      ? manifest.generated_at_utc
      : overrides.projectionGeneratedAtUtc,
    projectionAsOfLabel: overrides.projectionAsOfLabel ?? null,
    projectionAsOf: overrides.projectionAsOf === undefined ? null : overrides.projectionAsOf,
    projectionAsOfBasis: overrides.projectionAsOfBasis ?? null,
    completenessPercent,
    completenessBasis,
    evidenceClass: overrides.evidenceClass ?? null,
    releaseWindowStart: temporal.releaseWindowStartUtc,
    releaseWindowEnd: temporal.releaseWindowEndUtc,
    coverageWindowStart: overrides.coverageWindowStart ?? null,
    coverageWindowEnd: overrides.coverageWindowEnd ?? null,
    structuralCoverage: {
      full: coverage.full ?? 0,
      partial: coverage.partial ?? 0,
      postOnly: coverage.post_only ?? 0,
      sourceObserved: coverage.source_observed ?? 0,
      unresolvedParentComments: manifest.canonical_counts.unresolved_parent_comments ?? 0,
    },
  };
}
