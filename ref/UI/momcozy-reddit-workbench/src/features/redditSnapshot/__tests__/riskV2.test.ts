import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { CurrentRelease } from '../release';
import { validateCurrentRelease } from '../release';
import type {
  InsightsManifest,
  InsightsSemanticAudit,
  RedditSnapshotCore,
  RiskInsightsData,
  RiskObservedCount,
  RiskShareMetric,
  RiskTheme,
  SnapshotAggregates,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../types';
import { SnapshotContractError, validateInsightsOverlay, validateSnapshotCore } from '../service';
import type {
  RedditReport,
  ReportDescriptor,
  ReportIndex,
  ReportManifest,
  RiskRedditReport,
} from '../reports';
import { ReportsContractError, validateReportsSnapshot } from '../reports';

const publicDirectory = resolve(process.cwd(), 'public');
const currentRelease = validateCurrentRelease(JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
));
const baseDirectory = resolve(publicDirectory, 'data/reddit-voc', currentRelease.datasets.base.dataset_version);

function readBase<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(baseDirectory, filename), 'utf8')) as T;
}

function baseCore(): RedditSnapshotCore {
  return validateSnapshotCore(
    readBase<SnapshotManifest>('manifest-public.json'),
    readBase<SnapshotAggregates>('aggregates-public.json'),
    readBase<SnapshotPost[]>('posts-public.json'),
    readBase<SnapshotTagDictionary>('tag-dictionary-public.json'),
    currentRelease,
  );
}

const HASH = 'a'.repeat(64);
const INSIGHTS_VERSION = 'reddit_voc_insights_20260715_synthetic';
const REPORTS_VERSION = 'reddit_voc_reports_20260715_synthetic';

function v2Release(): CurrentRelease {
  return {
    ...currentRelease,
    datasets: {
      ...currentRelease.datasets,
      insights: {
        dataset_version: INSIGHTS_VERSION,
        manifest_path: `data/reddit-voc/${INSIGHTS_VERSION}/public/manifest.json`,
        public_manifest_sha256: HASH,
        lineage_manifest_sha256: HASH,
      },
      reports: {
        dataset_version: REPORTS_VERSION,
        manifest_path: `data/reddit-voc/${REPORTS_VERSION}/public/manifest.json`,
        public_manifest_sha256: HASH,
        lineage_manifest_sha256: HASH,
      },
    },
  };
}

function shareMetric(value = 1): RiskShareMetric {
  return {
    metric: 'negative_momcozy_observed_entities_over_classified_momcozy_observed_entities',
    numerator: 1,
    denominator: 1,
    value,
    value_status: 'observed',
    observation_status: 'comparable',
    reason_codes: [],
  };
}

function emptyShareMetric(): RiskShareMetric {
  return {
    metric: 'negative_momcozy_observed_entities_over_classified_momcozy_observed_entities',
    numerator: 0,
    denominator: 0,
    value: null,
    value_status: 'denominator_zero',
    observation_status: 'comparable',
    reason_codes: [],
  };
}

function countMetric(value = 1): RiskObservedCount {
  return {
    metric: 'momcozy_brand_bound_observed_entity_count',
    value,
    unit: 'observed_entity',
    value_status: 'observed',
    observation_status: 'comparable',
    reason_codes: [],
  };
}

const unsupportedCombined = {
  supported: false as const,
  reason: 'posts_and_comments_are_separate_entities_no_weighting_contract',
  value: null,
};

function theme(): RiskTheme {
  return {
    risk_theme_id: 'risk-p0',
    tag_id: 'risk-p0',
    name_cn: '关键故障',
    name_en: 'Critical failure',
    theme: '产品风险',
    risk_level: '高风险',
    effective_priority: 'P0',
    evidence_gate: {
      status: 'passed',
      policy_version: 'risk-theme-gate-reviewed-v1',
      reason_codes: [],
      semantic_status: 'promoted',
    },
    observed_entities: { post: 1, comment: 0 },
    distinct_posts: 1,
    communities: 1,
    brand_binding_rate: 1,
    brand_binding_counts: {
      brand_unbound: 0,
      competitor_sentence_bound: 0,
      momcozy_entity_reviewed: 0,
      momcozy_sentence_bound: 1,
      multi_brand_context: 0,
    },
    sentence_bound_rate: 1,
    event_window: { first_utc: '2026-07-14T00:00:00Z', last_utc: '2026-07-14T00:00:00Z' },
    evidence_refs: [{
      entity_type: 'post',
      entity_id: 'post-1',
      post_id: 'post-1',
    }],
    evidence_ref_count_total: 1,
    evidence_refs_truncated: false,
    product_scope_ids: { category: ['breast_pump'], product_family: ['m9'], spu_exact: ['SPU000168'] },
    problem_type: '产品性能',
    intent_type: '投诉',
    story_line: '核心体验问题',
  };
}

const productAnalysis = {
  schema_version: 'reddit_voc_product_analysis_v1' as const,
  decision_subject: 'momcozy' as const,
  scope_order: ['category', 'product_family', 'spu_exact'] as ['category', 'product_family', 'spu_exact'],
  category: [{
    scope_id: 'breast_pump',
    scope_name_en: 'Breast Pump',
    scope_name_cn: '吸奶器',
    binding_level: 'category' as const,
    metrics: { post: shareMetric(), comment: emptyShareMetric(), combined: unsupportedCombined },
    risk_priority_assignments: { P0: 1, P1: 0, P2: 0, P3: 0, insufficient: 0 },
  }],
  product_family: [],
  spu_exact: [],
  coverage: { momcozy_observed_entities: 1, bound_entities: 1, unbound_entities: 0, binding_rate: 1 },
  interpretation_boundary: 'multi_product_entities_can_appear_in_more_than_one_scope_but_each_entity_is_deduplicated_within_a_scope',
};

function shareComparison(entityType: 'post' | 'comment', metric = entityType === 'post' ? shareMetric() : emptyShareMetric()) {
  return {
    metric_name: 'negative_evidence_share' as const,
    comparison_type: 'day_over_day',
    entity_type: entityType,
    comparison_status: 'comparable' as const,
    reason_codes: [],
    current: metric,
    baseline: metric,
    absolute_delta: metric.value === null ? null : 0,
    relative_delta: metric.value === null ? null : 0,
    delta_reason: metric.value === null ? 'current_denominator_zero' : null,
    direction_claim_supported: metric.value !== null,
  };
}

function countComparison(entityType: 'post' | 'comment', metric = countMetric(entityType === 'post' ? 1 : 0)) {
  return {
    metric_name: 'observed_count' as const,
    comparison_type: 'day_over_day',
    entity_type: entityType,
    comparison_status: 'comparable' as const,
    reason_codes: [],
    current: metric,
    baseline: metric,
    absolute_delta: 0,
    relative_delta: metric.value === 0 ? null : 0,
    delta_reason: metric.value === 0 ? 'baseline_value_zero_relative_delta_undefined' : null,
    direction_claim_supported: true,
  };
}

function legacyReportShareComparison(
  entityType: 'post' | 'comment',
  metric = entityType === 'post' ? shareMetric() : emptyShareMetric(),
) {
  return { ...shareComparison(entityType, metric), direction_claim_supported: false };
}

function legacyReportCountComparison(
  entityType: 'post' | 'comment',
  metric = countMetric(entityType === 'post' ? 1 : 0),
) {
  return { ...countComparison(entityType, metric), direction_claim_supported: false };
}

function v2Insights(core: RedditSnapshotCore) {
  const release = v2Release();
  const manifest: InsightsManifest = {
    schema_version: 'reddit_voc_insights_manifest_v1',
    contract_extension: 'reddit_voc_insights_manifest_v2',
    dataset_version: INSIGHTS_VERSION,
    delivery_mode: 'versioned_static_insights_overlay',
    base_dataset_version: core.manifest.dataset_version,
    base_manifest_sha256: release.datasets.base.lineage_manifest_sha256,
    reports_dataset_version: REPORTS_VERSION,
    dictionary_version: core.tagDictionary.dictionary_version,
    dictionary_sha256: core.tagDictionary.dictionary_sha256,
    semantic_governance_version: 'semantic-review-v2',
    status: 'passed',
    audit_summary: {
      audited_tags: 1,
      reviewed_assignments: null,
      promoted_tags: 1,
      held_tags: 0,
      promoted_tag_ids: ['risk-p0'],
      held_tag_ids: [],
      status: 'passed',
    },
    files: {
      'insights.json': { bytes: 1, sha256: HASH },
      'semantic-audit.json': { bytes: 1, sha256: HASH },
    },
    boundaries: {
      scope: 'momcozy_risk_command_center_and_report_booklets',
      labels_outside_promoted_set_provisional: true,
      independent_human_review: false,
      production_unchanged: true,
      provider_call: false,
      database_write: false,
      live_send: false,
      deploy: false,
    },
  };
  const audit = {
    schema_version: 'reddit_voc_tag_semantic_audit_v2',
    audit_version: 'semantic-review-v2',
    base_dataset_version: core.manifest.dataset_version,
    base_manifest_sha256: release.datasets.base.lineage_manifest_sha256,
    dictionary_version: core.tagDictionary.dictionary_version,
    dictionary_sha256: core.tagDictionary.dictionary_sha256,
    summary: {
      promoted_tags: 1,
      held_tags: 0,
      promoted_tag_ids: ['risk-p0'],
      held_tag_ids: [],
      status: 'governance_projection_no_raw_samples',
    },
    boundaries: {
      raw_review_samples_included: false,
      production_unchanged: true,
      provider_call: false,
      database_write: false,
      live_send: false,
    },
  } as unknown as InsightsSemanticAudit;
  const dailyComparisons = {
    post: shareComparison('post'),
    comment: shareComparison('comment'),
  };
  const insights: RiskInsightsData = {
    schema_version: 'reddit_voc_insights_v2',
    dataset_version: INSIGHTS_VERSION,
    base_dataset_version: core.manifest.dataset_version,
    generated_at_utc: '2026-07-15T00:30:00Z',
    headline: { status: 'unavailable', reason: 'legacy_insights_not_supplied' },
    signals: [],
    reference_dimensions: {},
    held_tags: [],
    interpretation_boundaries: {
      market_share_supported: false,
      roi_supported: false,
      nps_supported: false,
      response_time_supported: false,
      posts_and_comments_separate_by_default: true,
      combined_view_supported: false,
      competitors_are_context_only: true,
      consumer_card_is_reference_not_user_identity: true,
    },
    boundaries: manifest.boundaries,
    legacy_compatibility: {
      status: 'not_supplied',
      preserved_fields: ['headline', 'signals', 'reference_dimensions', 'held_tags'],
      legacy_brand_binding_mapping_applied: false,
    },
    input_contract: {
      status: 'passed',
      required_event_time_field: 'event_created_at_utc',
      brand_binding_values: ['brand_unbound', 'competitor_sentence_bound', 'momcozy_entity_reviewed', 'momcozy_sentence_bound', 'multi_brand_context'],
      post_count: 1,
      comment_count: 0,
      comment_coverage_counts: { thread_complete: 1 },
      promoted_tag_ids: ['risk-p0'],
      held_tag_ids: [],
    },
    risk_command_center: {
      schema_version: 'reddit_voc_risk_command_center_v1',
      decision_subject: { brand_id: 'momcozy', brand_role: 'primary', competitors_role: 'comparison_context_only' },
      window: {
        start_utc: '2026-06-14T16:00:00Z', end_utc: '2026-07-14T16:00:00Z',
        start_local: '2026-06-15T00:00:00+08:00', end_local: '2026-07-15T00:00:00+08:00',
        timezone: 'Asia/Shanghai', interval: '[start,end)', is_closed: true, window_mode: 'rolling_30_closed_days',
      },
      primary_kpis: {
        high_priority_risk_themes: { value: 1, status: 'governed', included_priorities: ['P0', 'P1'], unit: 'distinct_governed_risk_theme' },
        negative_evidence_share: { post: shareMetric(), comment: emptyShareMetric(), combined: unsupportedCombined },
        risk_momentum: { source_report: 'daily', previous_period: dailyComparisons, year_over_year: dailyComparisons, interpretation_boundary: 'direction_is_supported_only_when_comparison_status_is_comparable' },
      },
      priority_distribution: { P0: 1, P1: 0, P2: 0, P3: 0, insufficient: 0 },
      risk_themes: [theme()],
      competitor_context: [],
      evidence_boundaries: {
        default_priority_inherited_from_dictionary: true,
        risk_level_to_priority_mapping_applied: false,
        arbitrary_score_supported: false,
        posts_and_comments_separate_by_default: true,
        combined_view_supported: false,
        actions_are_recommendations_only: true,
      },
    },
    product_analysis: productAnalysis,
    report_booklets: { schema_version: 'reddit_voc_report_booklets_v2', dataset_version: REPORTS_VERSION, timezone: 'Asia/Shanghai', index: {} },
    control_evidence: {
      schema_version: 'reddit_voc_control_evidence_v1',
      evidence_level: 'offline_snapshot_contract_build',
      base_dataset_version: core.manifest.dataset_version,
      base_manifest_sha256: release.datasets.base.lineage_manifest_sha256,
      base_generated_at_utc: core.manifest.generated_at_utc,
      source_cutoffs: null,
      semantic_governance_version: 'semantic-review-v2',
      coverage_ledger_version: 'coverage-ledger-v1',
      risk_gate_policy_version: 'risk-theme-gate-reviewed-v1',
      risk_gate_policy_status: 'frozen',
      recommendations_only: true,
      external_action_ledger_available: false,
      action_completion_supported: false,
      release_switch_executed: false,
      production_unchanged: true,
      provider_call: false,
      database_write: false,
      live_send: false,
      deploy: false,
    },
  };
  return { release, manifest, audit, insights };
}

function sentimentSummary(negative: number) {
  const denominator = negative;
  return {
    denominator,
    counts: { positive: 0, neutral: 0, negative },
    shares: {
      positive: { numerator: 0, denominator, value: denominator ? 0 : null },
      neutral: { numerator: 0, denominator, value: denominator ? 0 : null },
      negative: { numerator: negative, denominator, value: denominator ? 1 : null },
    },
  };
}

function reportForDescriptor(descriptor: ReportDescriptor): RiskRedditReport {
  const shareComparisons = { post: legacyReportShareComparison('post'), comment: legacyReportShareComparison('comment') };
  const countComparisons = { post: legacyReportCountComparison('post'), comment: legacyReportCountComparison('comment') };
  const productPeriodRow = {
    scope_id: 'breast_pump', scope_name_en: 'Breast Pump', scope_name_cn: '吸奶器', binding_level: 'category' as const,
    current: {
      post: { observed_count: countMetric(), negative_evidence_share: shareMetric() },
      comment: { observed_count: countMetric(0), negative_evidence_share: emptyShareMetric() },
    },
    period_comparisons: {
      previous_period: {
        post: { observed_count: legacyReportCountComparison('post'), negative_evidence_share: legacyReportShareComparison('post') },
        comment: { observed_count: legacyReportCountComparison('comment'), negative_evidence_share: legacyReportShareComparison('comment') },
      },
      year_over_year: {
        post: { observed_count: legacyReportCountComparison('post'), negative_evidence_share: legacyReportShareComparison('post') },
        comment: { observed_count: legacyReportCountComparison('comment'), negative_evidence_share: legacyReportShareComparison('comment') },
      },
    },
    trend: { point_count: 0, points: [], direction_claim_supported: false },
  };
  return {
    schema_version: 'reddit_voc_report_v1',
    contract_extension: 'reddit_voc_risk_report_v2',
    identity: { dataset_version: REPORTS_VERSION, report_id: descriptor.report_id, period: descriptor.period, window_mode: 'calendar_closed', display_name: descriptor.display_name },
    window: {
      start_utc: descriptor.start_utc, end_utc: descriptor.end_utc,
      start_local: '2026-07-14T00:00:00+08:00', end_local: '2026-07-15T00:00:00+08:00',
      timezone: 'Asia/Shanghai', as_of_utc: '2026-07-15T00:30:00Z', is_closed: true,
      bucket_grain: descriptor.period === 'daily' ? 'hour' : 'day', coverage_status: 'complete', comparison_status: 'comparable',
    },
    headline: {
      posts: 1, voc_comments: 0, observed_entities: 1,
      post_sentiment: sentimentSummary(1), comment_sentiment: sentimentSummary(0),
      quarantined_comments_in_base_snapshot: 0, quarantined_comments_counted: 0,
    },
    observed_timeline: [], communities: [], topics: [], pain_points: [], brand_mentions: [],
    promoted_signals: [], attention_items: [], evidence_posts: [],
    capabilities: { supported: ['observed_entity_counts'], conditionally_supported: ['period_comparison_when_coverage_gate_passes'], unsupported: ['market_share'] },
    interpretation_boundaries: {
      counts_are_observed_entities_not_users: true,
      comments_use_own_event_created_at_window: true,
      posts_and_comments_separate_by_default: true,
      combined_view_supported: false,
      brand_metric_label: 'sample_brand_bound_observed_entities',
      market_share_supported: false, roi_supported: false, nps_supported: false, trend_claim_supported: false,
      momcozy_specific_requires_controlled_binding: true, competitors_are_context_only: true, legacy_brand_binding_mapping_applied: false,
    },
    runtime_boundaries: { delivery_mode: 'versioned_static_snapshot', production_unchanged: true, provider_call: false, database_write: false, live_send: false, webhook_send: false, deploy: false, schedule_change: false },
    momcozy_metrics: {
      observed_count: { post: countMetric(), comment: countMetric(0), combined: unsupportedCombined },
      negative_evidence_share: { post: shareMetric(), comment: emptyShareMetric(), combined: unsupportedCombined },
      risk_theme_count: 1, high_priority_risk_theme_count: 1,
    },
    risk_themes: [theme()], product_analysis: productAnalysis,
    product_period_analysis: {
      schema_version: 'reddit_voc_product_period_metrics_v1', decision_subject: 'momcozy', period: descriptor.period,
      scope_order: ['category', 'product_family', 'spu_exact'], category: [productPeriodRow], product_family: [], spu_exact: [],
      metric_definitions: { observed_count: 'momcozy_brand_bound_observed_entities_by_entity_type', negative_evidence_share: 'negative_over_classified_momcozy_brand_bound_observed_entities_by_entity_type' },
      interpretation_boundary: 'posts_and_comments_are_separate',
    },
    competitor_context: [],
    period_comparisons: { previous_period: shareComparisons, year_over_year: shareComparisons },
    observed_count_comparisons: { previous_period: countComparisons, year_over_year: countComparisons },
    trend: {
      period: descriptor.period, point_count: 0, points: [], direction_claim_supported: false,
      direction_claim_supported_by_metric: { negative_evidence_share: false, observed_count: false },
      interpretation_boundary: 'trend_points_are_observations',
    },
  };
}

function v2Reports() {
  const paths = {
    current: { daily: 'current/daily.json', weekly: 'current/weekly.json', monthly: 'current/monthly.json' },
    archive: { daily: 'archive/daily-2026-07-13.json', weekly: 'archive/weekly-2026-07-06_2026-07-12.json', monthly: 'archive/monthly-2026-06.json' },
  } as const;
  const descriptor = (period: 'daily' | 'weekly' | 'monthly', path: string, collection: 'current' | 'archive'): ReportDescriptor => ({
    report_id: `${collection}-${period}-synthetic`, period, window_mode: 'calendar_closed', display_name: `${period} synthetic`, path,
    start_utc: '2026-07-13T16:00:00Z', end_utc: '2026-07-14T16:00:00Z', coverage_status: 'complete', comparison_status: 'comparable', posts: 1, voc_comments: 0,
  });
  const index: ReportIndex = {
    schema_version: 'reddit_voc_report_index_v1', contract_extension: 'reddit_voc_report_index_v2', dataset_version: REPORTS_VERSION,
    as_of_utc: '2026-07-15T00:30:00Z', timezone: 'Asia/Shanghai',
    current: {
      daily: descriptor('daily', paths.current.daily, 'current'),
      weekly: descriptor('weekly', paths.current.weekly, 'current'),
      monthly: descriptor('monthly', paths.current.monthly, 'current'),
    },
    archive: {
      daily: descriptor('daily', paths.archive.daily, 'archive'),
      weekly: descriptor('weekly', paths.archive.weekly, 'archive'),
      monthly: descriptor('monthly', paths.archive.monthly, 'archive'),
    },
  };
  const reportPaths = [...Object.values(paths.current), ...Object.values(paths.archive)];
  const manifest: ReportManifest = {
    schema_version: 'reddit_voc_reports_manifest_v1', contract_extension: 'reddit_voc_reports_manifest_v2', dataset_version: REPORTS_VERSION,
    delivery_mode: 'versioned_static_reports', generated_at_utc: index.as_of_utc,
    base_dataset_version: currentRelease.datasets.base.dataset_version, base_manifest_sha256: currentRelease.datasets.base.lineage_manifest_sha256,
    insights_dataset_version: INSIGHTS_VERSION, insights_manifest_sha256: HASH,
    dictionary_version: 'dim_tag_v6.3_final', dictionary_sha256: HASH, report_count: 6,
    promoted_tag_ids: ['risk-p0'], held_tag_ids_excluded: [], status: 'passed',
    files: Object.fromEntries(['report-index.json', ...reportPaths].map((path) => [path, { bytes: 1, sha256: HASH }])),
    boundaries: {
      production_unchanged: true, provider_call: false, database_write: false, live_send: false, webhook_send: false, deploy: false, schedule_change: false,
      independent_human_review: false, consumer_card_is_reference_not_persona_id: true, persona_tags_generated: false,
      market_share_supported: false, roi_supported: false, trend_claim_supported: false,
    },
  };
  const descriptors = [...Object.values(index.current), ...Object.values(index.archive)];
  const reports = Object.fromEntries(descriptors.map((row) => [row.path, reportForDescriptor(row)])) as Record<string, RedditReport>;
  return { release: v2Release(), manifest, index, reports };
}

describe('Reddit VOC v2 synthetic public contracts', () => {
  it('accepts the Momcozy risk story without depending on private action fields', () => {
    const core = baseCore();
    const fixture = v2Insights(core);
    const result = validateInsightsOverlay(core, fixture.manifest, fixture.audit, fixture.insights, fixture.release);

    expect(result.insights.schema_version).toBe('reddit_voc_insights_v2');
    expect(fixture.insights.risk_command_center.risk_themes[0].effective_priority).toBe('P0');
    expect(fixture.insights.product_analysis.scope_order).toEqual(['category', 'product_family', 'spu_exact']);
  });

  it('fails closed if an internal dictionary priority leaks into the public risk theme', () => {
    const core = baseCore();
    const fixture = v2Insights(core);
    (fixture.insights.risk_command_center.risk_themes[0] as unknown as Record<string, unknown>).dictionary_default_priority = 'P0';

    expect(() => validateInsightsOverlay(core, fixture.manifest, fixture.audit, fixture.insights, fixture.release))
      .toThrowError(SnapshotContractError);
    expect(() => validateInsightsOverlay(core, fixture.manifest, fixture.audit, fixture.insights, fixture.release))
      .toThrow(/公开投影包含内部字段/);
  });

  it('derives all six closed report paths from the v2 index', () => {
    const fixture = v2Reports();
    const snapshot = validateReportsSnapshot(fixture.manifest, fixture.index, fixture.reports, fixture.release);

    expect(snapshot.current.daily.identity.window_mode).toBe('calendar_closed');
    expect(snapshot.archive.monthly.product_period_analysis?.scope_order).toEqual(['category', 'product_family', 'spu_exact']);
  });

  it('rejects an unavailable comparison that silently carries a delta', () => {
    const fixture = v2Reports();
    const report = fixture.reports['current/daily.json'] as RiskRedditReport;
    report.period_comparisons.year_over_year.post.comparison_status = 'unavailable';
    report.period_comparisons.year_over_year.post.reason_codes = ['baseline_coverage_missing'];
    report.period_comparisons.year_over_year.post.direction_claim_supported = false;

    expect(() => validateReportsSnapshot(fixture.manifest, fixture.index, fixture.reports, fixture.release))
      .toThrowError(ReportsContractError);
    expect(() => validateReportsSnapshot(fixture.manifest, fixture.index, fixture.reports, fixture.release))
      .toThrow(/不可比较状态缺少 null\/reason 边界/);
  });

  it('keeps V2 report direction claims fail-closed even when a comparison is marked comparable', () => {
    const fixture = v2Reports();
    const report = fixture.reports['current/daily.json'] as RiskRedditReport;
    report.observed_count_comparisons.previous_period.post.direction_claim_supported = true;

    expect(() => validateReportsSnapshot(fixture.manifest, fixture.index, fixture.reports, fixture.release))
      .toThrowError(ReportsContractError);
    expect(() => validateReportsSnapshot(fixture.manifest, fixture.index, fixture.reports, fixture.release))
      .toThrow(/V2 报告错误开放比较方向/);
  });
});
