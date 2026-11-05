import type { CurrentRelease, ReleaseDatasetKey } from '../release';
import type {
  InsightsManifest,
  RedditSnapshotCore,
  RedditSnapshotSummary,
  RiskComparisonStatus,
} from '../types';
import type {
  ReportCoverageStatus,
  ReportDescriptor,
  ReportManifest,
  V3CurrentReport,
  V3ReportIndex,
  V3ReportsManifest,
} from '../reports';
import type {
  ArtifactBuildState,
  GovernanceState,
  GovernanceStatus,
  SiteDeploymentState,
  UiGovernanceContract,
} from './GovernanceStatusBadge';

export class GovernanceContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GovernanceContractError';
  }
}

function state(status: GovernanceStatus, label: string, detail: string): GovernanceState {
  return { status, label, detail };
}

function assertNever(value: never, label: string): never {
  throw new GovernanceContractError(`${label}不受支持：${String(value)}`);
}

export function mapReportCoverageStatus(status: ReportCoverageStatus): GovernanceStatus {
  switch (status) {
    case 'complete':
      return 'verified';
    case 'partial':
    case 'observed_records_present_but_collection_coverage_unverified':
      return 'provisional';
    case 'coverage_gap':
    case 'coverage_missing':
    case 'unavailable':
      return 'unavailable';
    default:
      return assertNever(status, '报告覆盖状态');
  }
}

export function mapComparisonStatus(status: RiskComparisonStatus): GovernanceStatus {
  switch (status) {
    case 'comparable':
      return 'verified';
    case 'provisional_observed_sample':
      return 'provisional';
    case 'unavailable':
      return 'unavailable';
    default:
      return assertNever(status, '报告比较状态');
  }
}

export function mapInsightsStatus(status: string): GovernanceStatus {
  switch (status) {
    case 'passed':
      return 'verified';
    case 'passed_with_scope_limits':
    case 'passed_with_comparison_coverage_limits':
    case 'passed_provisional_risk_threshold':
      return 'provisional';
    default:
      throw new GovernanceContractError(`洞察状态不受支持：${status}`);
  }
}

export function mapHighPriorityStatus(status: string): GovernanceStatus {
  switch (status) {
    case 'governed':
      return 'verified';
    case 'unavailable_unfrozen_evidence_threshold':
      return 'unavailable';
    default:
      throw new GovernanceContractError(`高优先级风险状态不受支持：${status}`);
  }
}

function artifactBuildState(
  release: CurrentRelease,
  key: ReleaseDatasetKey,
  boundaries: ArtifactBuildState['side_effect_boundaries'],
): ArtifactBuildState {
  const binding = release.datasets[key];
  if (binding === undefined) {
    throw new GovernanceContractError(`current release 缺少数据集：${key}`);
  }
  return {
    status: 'verified',
    label: '构建产物已校验',
    detail: `${key} manifest 已按 current release 绑定的 SHA-256 完整性校验。`,
    release_id: release.release_id,
    evidence_source: `${binding.manifest_path}#sha256=${binding.public_manifest_sha256}`,
    side_effect_boundaries: boundaries,
  };
}

export function siteDeploymentState(release: CurrentRelease): SiteDeploymentState {
  return {
    status: 'verified',
    label: '当前服务身份',
    detail: '仅证明浏览器从同源 current-release.json 读取到的 served release identity。',
    served_release_id: release.release_id,
    independent_deployment_source: null,
    promotion_state: state('unavailable', '生产提升', '没有独立、可校验的 deployment source。'),
    acceptance_state: state('unavailable', '生产验收', '没有与 served release 绑定的独立验收来源。'),
  };
}

function baseDataScope(core: RedditSnapshotSummary): GovernanceState {
  const full = core.aggregates.coverage_grade.full ?? 0;
  const partial = core.aggregates.coverage_grade.partial ?? 0;
  const postOnly = core.aggregates.coverage_grade.post_only ?? 0;
  // source_observed 是覆盖口径的第四类（无关联评论、仅作来源观察的帖子）；
  // 漏掉它会让拆分合计远小于帖子总数，与数据证据抽屉自相矛盾。
  const sourceObserved = core.aggregates.coverage_grade.source_observed ?? 0;
  const incomplete = partial + postOnly;
  return state(
    incomplete > 0 ? 'provisional' : 'verified',
    '数据范围',
    `${core.manifest.canonical_counts.posts.toLocaleString('zh-CN')} 帖子 · ${core.manifest.canonical_counts.linked_comments.toLocaleString('zh-CN')} 关联评论；完整帖子与评论 ${full.toLocaleString('zh-CN')} / 部分评论上下文 ${partial.toLocaleString('zh-CN')} / 仅帖子 ${postOnly.toLocaleString('zh-CN')} / 来源观察 ${sourceObserved.toLocaleString('zh-CN')}。`,
  );
}

function baseTagMaturity(core: RedditSnapshotSummary): GovernanceState {
  const { labels_provisional: provisional, semantic_validation_run: validationRun } = core.manifest.tagging;
  if (provisional && !validationRun) {
    return state('provisional', '标签成熟度', `${core.manifest.tagging.dictionary_version} 规则提取；未完成复核的标签仅用于主题探索。`);
  }
  if (!provisional && validationRun) {
    return state('verified', '标签成熟度', `${core.manifest.tagging.dictionary_version} 已完成语义验证。`);
  }
  if (!provisional && !validationRun) {
    return state('unavailable', '标签成熟度', '当前数据未提供可确认的标签成熟度。');
  }
  throw new GovernanceContractError('Base 标签成熟度字段组合冲突');
}

export function createBaseGovernanceContract(
  release: CurrentRelease,
  core: RedditSnapshotSummary,
): UiGovernanceContract {
  return {
    artifact_build_state: artifactBuildState(release, 'base', {
      production_unchanged: core.manifest.production_unchanged,
      provider_call: core.manifest.provider_call,
      database_write: false,
      live_send: core.manifest.live_send,
    }),
    site_deployment_state: siteDeploymentState(release),
    data_scope: baseDataScope(core),
    comparison_scope: state('unavailable', '对比范围', '基础快照不提供市场份额、ROI 或跨期方向结论。'),
    tag_maturity: baseTagMaturity(core),
  };
}

export function createInsightsGovernanceContract(
  release: CurrentRelease,
  core: RedditSnapshotCore,
  manifest: InsightsManifest,
): UiGovernanceContract {
  const maturity = mapInsightsStatus(manifest.status);
  return {
    artifact_build_state: artifactBuildState(release, 'insights', {
      production_unchanged: manifest.boundaries.production_unchanged,
      provider_call: manifest.boundaries.provider_call,
      database_write: manifest.boundaries.database_write,
      live_send: manifest.boundaries.live_send,
    }),
    site_deployment_state: siteDeploymentState(release),
    data_scope: baseDataScope(core),
    comparison_scope: state(
      maturity === 'verified' ? 'verified' : 'provisional',
      '对比范围',
      'Momcozy 为决策主干，竞品仅作同样本观察对照，不解释为市场份额或销量。',
    ),
    tag_maturity: state(
      maturity,
      '标签成熟度',
      `${manifest.audit_summary.promoted_tags} 个已确认标签进入洞察 · ${manifest.audit_summary.held_tags} 个待复核标签保留在口径说明中。`,
    ),
  };
}

function reportTagMaturity(manifest: ReportManifest): GovernanceState {
  if (!manifest.status) {
    return state('unavailable', '标签成熟度', '历史报告 manifest 未提供显式语义治理状态。');
  }
  const status = mapInsightsStatus(manifest.status);
  return state(status, '标签成熟度', `${manifest.promoted_tag_ids.length} 个已确认标签进入报告；待复核标签不进入业务结论。`);
}

export function createReportGovernanceContract(
  release: CurrentRelease,
  manifest: ReportManifest,
  descriptor: ReportDescriptor,
): UiGovernanceContract {
  const coverageStatus = mapReportCoverageStatus(descriptor.coverage_status);
  const comparisonStatus = descriptor.comparison_status
    ? mapComparisonStatus(descriptor.comparison_status)
    : 'unavailable';
  return {
    artifact_build_state: artifactBuildState(release, 'reports', {
      production_unchanged: manifest.boundaries.production_unchanged,
      provider_call: manifest.boundaries.provider_call,
      database_write: manifest.boundaries.database_write,
      live_send: manifest.boundaries.live_send,
    }),
    site_deployment_state: siteDeploymentState(release),
    data_scope: state(
      coverageStatus,
      '数据范围',
      `${descriptor.display_name} · ${descriptor.posts.toLocaleString('zh-CN')} 帖子 / ${descriptor.voc_comments.toLocaleString('zh-CN')} VOC 评论。`,
    ),
    comparison_scope: state(
      comparisonStatus,
      '对比范围',
      descriptor.comparison_status
        ? `环比和同比按相同统计周期计算；是否展示方向由每个指标的数据条件决定。`
        : '历史报告未提供受控比较状态。',
    ),
    tag_maturity: reportTagMaturity(manifest),
  };
}

export function createV3ReportGovernanceContract(
  release: CurrentRelease,
  manifest: V3ReportsManifest,
  index: V3ReportIndex,
  report: V3CurrentReport,
): UiGovernanceContract {
  const scalarIndicators = report.indicators.filter((indicator) => (
    indicator.current.status !== 'unavailable'
      && (typeof indicator.current.value === 'number' || typeof indicator.current.value === 'string')
      && String(indicator.current.value).trim() !== ''
      && Number.isFinite(Number(indicator.current.value))
  ));
  const availableComparisons = scalarIndicators.reduce((count, indicator) => (
    count
      + (indicator.comparisons.period_over_period.status !== 'unavailable' ? 1 : 0)
      + (indicator.comparisons.year_over_year.status !== 'unavailable' ? 1 : 0)
  ), 0);
  return {
    artifact_build_state: artifactBuildState(release, 'reports', {
      production_unchanged: manifest.boundaries.production_unchanged,
      provider_call: manifest.boundaries.provider_call,
      database_write: manifest.boundaries.database_write,
      live_send: manifest.boundaries.live_send,
    }),
    site_deployment_state: siteDeploymentState(release),
    data_scope: state(
      'verified',
      '数据范围',
      `${report.entry_label} · ${report.period.start} 至 ${report.period.end}；${manifest.comparison_contract_proven
        ? `数据所有者确认完整性 ${manifest.completeness_percent}%`
        : '日历周期已闭合，但历史采集覆盖未获完整性证明'}。`,
    ),
    comparison_scope: state(
      'verified',
      '对比范围',
      `${availableComparisons}/${scalarIndicators.length * 2} 项标量同环比可用；${manifest.comparison_contract_proven
        ? '比较基于所有者确认的完整范围'
        : '当前为同源同口径观测值，不代表全量市场趋势'}。`,
    ),
    tag_maturity: state(
      'verified',
      '指标成熟度',
      `报告索引锚定至 ${index.as_of_date}（周期结束日期，不含当日），数据已完成版本、文件大小与完整性校验。`,
    ),
  };
}
