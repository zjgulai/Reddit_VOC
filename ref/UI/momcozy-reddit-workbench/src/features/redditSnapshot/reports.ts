import type {
  CompetitorContext,
  ControlledBrandBinding,
  InsightsDictionaryReference,
  ProductAnalysis,
  RiskComparison,
  RiskComparisonStatus,
  RiskEntityType,
  RiskMetricByEntity,
  RiskObservedCount,
  RiskShareMetric,
  RiskTheme,
  RiskWindow,
  SnapshotSentiment,
} from './types';
import {
  fetchVerifiedReleaseManifest,
  getReleaseDatasetBasePath,
  loadCurrentRelease,
  releaseGenerationKey,
  type CurrentRelease,
} from './release';
import { ReleaseKeyedCache } from './releaseKeyedCache';

export const REPORTS_MANIFEST_SCHEMA = 'reddit_voc_reports_manifest_v1';
export const REPORTS_INDEX_SCHEMA = 'reddit_voc_report_index_v1';
export const REPORT_SCHEMA = 'reddit_voc_report_v1';
export const RISK_REPORT_EXTENSION = 'reddit_voc_risk_report_v2';
export const V3_REPORT_SCHEMA = 'reddit_voc_report_v3';
export const V3_REPORTS_MANIFEST_SCHEMA = 'reddit_voc_reports_public_manifest_v3';
export const V3_REPORT_INDEX_SCHEMA = 'reddit_voc_report_index_v3';
const V3_REPORTS_CANDIDATE_MANIFEST_SCHEMA = 'reddit_voc_reports_manifest_v3';

const PROMOTED_TAG_IDS = new Set(['L0-GEN-075', 'L0-GEN-103']);
const REQUIRED_UNSUPPORTED = new Set([
  'market_share',
  'roi',
  'response_time',
  'nps',
  'conversion_rate',
  'high_intent',
  'ugc_attribution',
  'kpi_attainment',
  'forecast',
  'trend_claim',
  'persona_population',
]);
const EXPECTED_REPORT_PATHS = [
  'current/daily.json',
  'current/weekly.json',
  'current/monthly.json',
  'archive/daily-2026-07-13.json',
  'archive/weekly-2026-07-06_2026-07-12.json',
  'archive/monthly-2026-06.json',
] as const;

export type ReportPeriod = 'daily' | 'weekly' | 'monthly';
export type ReportCollection = 'current' | 'archive';
export type ReportWindowMode = 'rolling' | 'calendar_closed';
export type ReportCoverageStatus =
  | 'observed_records_present_but_collection_coverage_unverified'
  | 'coverage_gap'
  | 'complete'
  | 'partial'
  | 'unavailable'
  | 'coverage_missing';
export type ReportBrandBinding =
  | 'momcozy_sentence_bound'
  | 'momcozy_entity_cooccurrence'
  | 'multi_brand'
  | 'competitor_explicit'
  | 'category_general'
  | ControlledBrandBinding;
type V3ComparisonContractBasis = 'owner_attested_dataset_scope_window' | 'not_owner_attested';
const V3_UNATTESTED_COVERAGE_REASON = 'historical_collection_coverage_not_owner_attested_complete';

interface FileIntegrity {
  bytes: number;
  sha256: string;
}

export interface ReportManifest {
  schema_version: string;
  contract_extension?: 'reddit_voc_reports_manifest_v2';
  dataset_version: string;
  delivery_mode: string;
  generated_at_utc: string;
  base_dataset_version: string;
  base_manifest_sha256: string;
  insights_dataset_version: string;
  insights_manifest_sha256: string;
  dictionary_version: string;
  dictionary_sha256: string;
  report_count: number;
  promoted_tag_ids: string[];
  held_tag_ids_excluded: string[];
  status?: 'passed' | 'passed_with_comparison_coverage_limits' | 'passed_provisional_risk_threshold';
  files: Record<string, FileIntegrity>;
  boundaries: {
    production_unchanged: boolean;
    provider_call: boolean;
    database_write: boolean;
    live_send: boolean;
    webhook_send: boolean;
    deploy: boolean;
    schedule_change: boolean;
    independent_human_review: boolean;
    consumer_card_is_reference_not_persona_id: boolean;
    persona_tags_generated: boolean;
    market_share_supported: boolean;
    roi_supported: boolean;
    trend_claim_supported: boolean;
  };
}

export interface V3ReportsManifest {
  artifact_stage: 'reports_public_candidate';
  boundaries: {
    database_write: false;
    deploy: false;
    live_send: false;
    production_unchanged: true;
    provider_call: false;
    remote_write: false;
  };
  comparison_contract_basis: V3ComparisonContractBasis;
  comparison_contract_proven: boolean;
  comparison_unavailable_reason_codes: string[];
  completeness_percent: 100 | null;
  contract_extensions: [
    'reddit_voc_period_activity_v1',
    'reddit_voc_brand_health_dimension_contribution_v1',
    'reddit_voc_action_review_v1',
    'reddit_voc_business_history_index_v1',
  ];
  consumption_status: 'eligible_for_frontend_candidate_consumption';
  coverage_attestation: V3ReportCoverageAttestation | null;
  data_owner_coverage_attestation_sha256: string | null;
  dataset_version: string;
  files: Record<string, FileIntegrity>;
  fixture_only: false;
  business_entry_count: 3 | 41;
  history_report_count: 0 | 38;
  independent_validation_status: 'passed';
  lineage_manifest_sha256: string;
  privacy_safe_projection: true;
  promotable: true;
  report_count: 6 | 44;
  schema_version: typeof V3_REPORTS_MANIFEST_SCHEMA;
  source_snapshot_id: string;
  status: 'validated_candidate';
  summary: {
    current_available: number;
    current_provisional: number;
    current_unavailable: number;
    period_over_period_available: number;
    period_over_period_provisional: number;
    period_over_period_unavailable: number;
    trend_observed: number;
    trend_supported: number;
    year_over_year_available: number;
    year_over_year_provisional: number;
    year_over_year_unavailable: number;
  };
  validation_receipt_sha256: string;
}

export interface V3ReportsValidationReceipt {
  boundaries: V3ReportsManifest['boundaries'];
  bundle_manifest_sha256: string;
  comparison_contract_basis: V3ComparisonContractBasis;
  comparison_contract_proven: boolean;
  completeness_percent: 100 | null;
  coverage_attestation: V3ReportCoverageAttestation | null;
  data_owner_coverage_attestation_sha256: string | null;
  deterministic_full_byte_replay: true;
  metrics_candidate_manifest_sha256: string;
  metrics_input_manifest_sha256: string;
  metrics_validation_receipt_sha256: string;
  promotable: true;
  business_entry_count: 3 | 41;
  history_report_count: 0 | 38;
  report_count: 6 | 44;
  schema_version: 'reddit_voc_reports_validation_receipt_v3';
  status: 'passed_candidate_only';
  summary: V3ReportsManifest['summary'];
}

export interface V3ReportSource {
  coverage_attestation_sha256: string | null;
  metrics_candidate_manifest_sha256: string;
  metrics_input_manifest_sha256: string;
  metrics_validation_receipt_sha256: string;
  periodized_metrics_sha256: string;
  source_snapshot_id: string;
}

export interface V3ReportIndexEntry {
  artifact_path: `current/${ReportPeriod}.json`;
  entry_label: '最新完整周期' | '最新闭合周期（覆盖未证明）';
  grain: ReportPeriod;
  period: V3CurrentReport['period'];
}

export interface V3ReportIndex {
  archive_policy: 'internal_comparison_storage_not_a_business_entry';
  as_of_date: string;
  business_entry_count: 3 | 41;
  business_history_index_path: 'business-history-index.json';
  comparison_contract_basis: V3ComparisonContractBasis;
  comparison_contract_proven: boolean;
  comparison_unavailable_reason_codes: string[];
  completeness_percent: 100 | null;
  coverage_attestation: V3ReportCoverageAttestation | null;
  data_owner_coverage_attestation_sha256: string | null;
  dataset_version: string;
  fixture_only: false;
  current_entry_count: 3;
  history_entry_count: 0 | 38;
  reports: Record<ReportPeriod, V3ReportIndexEntry>;
  schema_version: typeof V3_REPORT_INDEX_SCHEMA;
  source: V3ReportSource;
}

export interface V3BusinessHistoryEntry {
  artifact_path: string;
  artifact_sha256: string;
  entry_label: '历史完整周期' | '历史已观测周期（覆盖未证明）';
  grain: ReportPeriod;
  period: V3CurrentReport['period'];
}

export interface V3BusinessHistoryIndex {
  as_of_date: string;
  coverage_attestation: V3ReportCoverageAttestation | null;
  data_owner_coverage_attestation_sha256: string | null;
  dataset_version: string;
  history_entry_count: 0 | 38;
  latest_complete_period_excluded: true;
  limits: { daily: 14; weekly: 12; monthly: 12 };
  order: 'newest_first';
  reports: Record<ReportPeriod, V3BusinessHistoryEntry[]>;
  schema_version: 'reddit_voc_business_history_index_v1';
  source: V3ReportSource;
  total_business_entry_count: 3 | 41;
}

interface V3ArchiveReport {
  artifact_role: 'internal_comparison_archive';
  boundaries: V3ReportsManifest['boundaries'];
  business_entry_visible: false;
  comparison_contract_basis: V3ComparisonContractBasis;
  comparison_contract_proven: boolean;
  completeness_percent: 100 | null;
  coverage_attestation: V3ReportCoverageAttestation | null;
  data_owner_coverage_attestation_sha256: string | null;
  fixture_only: false;
  grain: ReportPeriod;
  schema_version: typeof V3_REPORT_SCHEMA;
  source: V3ReportSource;
}

export interface ReportDescriptor {
  report_id: string;
  period: ReportPeriod;
  window_mode: ReportWindowMode;
  display_name: string;
  path: string;
  start_utc: string;
  end_utc: string;
  coverage_status: ReportCoverageStatus;
  comparison_status?: RiskComparisonStatus;
  posts: number;
  voc_comments: number;
}

export interface ReportIndex {
  schema_version: string;
  contract_extension?: 'reddit_voc_report_index_v2';
  dataset_version: string;
  as_of_utc: string;
  timezone: string;
  current: Record<ReportPeriod, ReportDescriptor>;
  archive: Record<ReportPeriod, ReportDescriptor>;
}

export interface ReportShare {
  numerator: number;
  denominator: number;
  value: number | null;
}

export interface ReportSentimentSummary {
  denominator: number;
  counts: Record<SnapshotSentiment, number>;
  shares: Record<SnapshotSentiment, ReportShare>;
}

export interface ReportTimelinePoint {
  bucket_start_utc: string;
  bucket_end_utc: string;
  bucket_start_local: string;
  posts: number;
  voc_comments: number;
  observed_entities: number;
  sentiment_counts: Record<SnapshotSentiment, number>;
}

export interface ReportCommunity {
  subreddit: string;
  posts: number;
  voc_comments: number;
  observed_entities: number;
  sentiment_counts: Record<SnapshotSentiment, number>;
  negative_share: ReportShare;
}

export interface ReportTopic {
  topic: string;
  post_entities: number;
  share: ReportShare;
}

export interface ReportPainPoint {
  pain_point: string;
  post_entities: number;
  comment_entities: number;
  total_entities: number;
  share: ReportShare;
}

export interface ReportBrandMention {
  brand: string;
  sample_mention_posts: number;
  sample_mention_share: ReportShare;
  metric_label: 'sample_mention_posts';
}

export interface ReportSignalEvidence {
  entity_type: 'post' | 'comment';
  entity_id: string;
  post_id: string;
  created_at_utc: string;
  subreddit: string;
  binding_type: ReportBrandBinding;
  brands: string[];
  evidence_keywords: string[];
  context_excerpt: string;
  permalink: string;
}

export interface ReportPromotedSignal {
  tag_id: string;
  name_cn: string;
  name_en: string;
  theme: string;
  matched_posts: number;
  matched_comments: number;
  matched_entities: number;
  binding_counts: Record<ReportBrandBinding, number>;
  momcozy_specific_entities: number;
  dictionary_reference: InsightsDictionaryReference;
  evidence: ReportSignalEvidence[];
}

export interface ReportAttentionItem {
  attention_id: string;
  post_id: string;
  title: string;
  subreddit: string;
  created_at_utc: string;
  sentiment: SnapshotSentiment;
  severity: string;
  score: number;
  linked_comment_count: number;
  reason_codes: string[];
  permalink: string;
  priority_score: number;
}

export interface ReportEvidencePost {
  post_id: string;
  title: string;
  subreddit: string;
  created_at_utc: string;
  sentiment: SnapshotSentiment;
  severity: string;
  topic: string;
  score: number;
  linked_comment_count: number;
  mentioned_brands: string[];
  permalink: string;
  content_excerpt: string;
}

export interface ProductMetricPair {
  observed_count: RiskObservedCount;
  negative_evidence_share: RiskShareMetric;
}

export interface ProductPeriodScope {
  scope_id: string;
  scope_name_en: string;
  scope_name_cn: string;
  binding_level: 'category' | 'product_family' | 'spu_exact';
  current: Record<RiskEntityType, ProductMetricPair>;
  period_comparisons: Record<
    'previous_period' | 'year_over_year',
    Record<RiskEntityType, {
      observed_count: RiskComparison<RiskObservedCount>;
      negative_evidence_share: RiskComparison<RiskShareMetric>;
    }>
  >;
  trend: {
    point_count: number;
    points: ProductTrendPoint[];
    direction_claim_supported: boolean;
  };
}

export interface ProductTrendPoint {
  window: RiskWindow;
  metrics: Record<RiskEntityType, ProductMetricPair>;
  coverage_status: ReportCoverageStatus;
  change_from_previous: Record<
    RiskEntityType,
    {
      observed_count: RiskComparison<RiskObservedCount>;
      negative_evidence_share: RiskComparison<RiskShareMetric>;
    }
  > | null;
}

export interface ProductPeriodAnalysis {
  schema_version: 'reddit_voc_product_period_metrics_v1';
  decision_subject: 'momcozy';
  period: ReportPeriod;
  scope_order: ['category', 'product_family', 'spu_exact'];
  category: ProductPeriodScope[];
  product_family: ProductPeriodScope[];
  spu_exact: ProductPeriodScope[];
  metric_definitions: Record<'observed_count' | 'negative_evidence_share', string>;
  interpretation_boundary: string;
}

export interface ReportTrendPoint {
  window: RiskWindow;
  post: RiskShareMetric;
  comment: RiskShareMetric;
  negative_evidence_share: Record<RiskEntityType, RiskShareMetric>;
  observed_count: Record<RiskEntityType, RiskObservedCount>;
  coverage_status: ReportCoverageStatus;
  change_from_previous: Record<RiskEntityType, RiskComparison<RiskShareMetric>> | null;
  observed_count_change_from_previous: Record<RiskEntityType, RiskComparison<RiskObservedCount>> | null;
}

export interface ReportTrend {
  period: ReportPeriod;
  point_count: number;
  points: ReportTrendPoint[];
  direction_claim_supported: boolean;
  direction_claim_supported_by_metric: {
    negative_evidence_share: boolean;
    observed_count: boolean;
  };
  interpretation_boundary: string;
}

export interface RedditReport {
  schema_version: string;
  contract_extension?: 'reddit_voc_risk_report_v2';
  identity: {
    dataset_version: string;
    report_id: string;
    period: ReportPeriod;
    window_mode: ReportWindowMode;
    display_name: string;
  };
  window: {
    start_utc: string;
    end_utc: string;
    start_local: string;
    end_local: string;
    timezone: string;
    as_of_utc: string;
    is_closed: boolean;
    bucket_grain: 'hour' | 'day';
    coverage_status: ReportCoverageStatus;
    comparison_status: 'coverage_unverified' | RiskComparisonStatus;
  };
  headline: {
    posts: number;
    voc_comments: number;
    observed_entities: number;
    post_sentiment: ReportSentimentSummary;
    comment_sentiment: ReportSentimentSummary;
    quarantined_comments_in_base_snapshot: number;
    quarantined_comments_counted: number;
  };
  observed_timeline: ReportTimelinePoint[];
  communities: ReportCommunity[];
  topics: ReportTopic[];
  pain_points: ReportPainPoint[];
  brand_mentions: ReportBrandMention[];
  promoted_signals: ReportPromotedSignal[];
  attention_items: ReportAttentionItem[];
  evidence_posts: ReportEvidencePost[];
  capabilities: {
    supported: string[];
    conditionally_supported: string[];
    unsupported: string[];
  };
  interpretation_boundaries: {
    counts_are_observed_entities_not_users: boolean;
    comments_use_own_created_at_window?: boolean;
    comments_use_own_event_created_at_window?: boolean;
    posts_and_comments_separate_by_default?: boolean;
    combined_view_supported?: boolean;
    brand_metric_label: string;
    brand_counts_are_nonexclusive?: boolean;
    market_share_supported: boolean;
    roi_supported: boolean;
    trend_claim_supported: boolean;
    nps_supported?: boolean;
    comparison_status?: string;
    consumer_card_is_reference_not_persona_id?: boolean;
    persona_tags_generated?: boolean;
    momcozy_specific_requires_sentence_binding?: boolean;
    momcozy_specific_requires_controlled_binding?: boolean;
    competitors_are_context_only?: boolean;
    legacy_brand_binding_mapping_applied?: boolean;
    held_tags_in_business_findings?: number;
  };
  runtime_boundaries: {
    delivery_mode: string;
    production_unchanged: boolean;
    provider_call: boolean;
    database_write: boolean;
    live_send: boolean;
    webhook_send: boolean;
    deploy: boolean;
    schedule_change: boolean;
  };
  momcozy_metrics?: {
    observed_count: RiskMetricByEntity<RiskObservedCount>;
    negative_evidence_share: RiskMetricByEntity<RiskShareMetric>;
    risk_theme_count: number;
    high_priority_risk_theme_count: number | null;
  };
  risk_themes?: RiskTheme[];
  product_analysis?: ProductAnalysis;
  product_period_analysis?: ProductPeriodAnalysis;
  competitor_context?: CompetitorContext[];
  period_comparisons?: Record<
    'previous_period' | 'year_over_year',
    Record<RiskEntityType, RiskComparison<RiskShareMetric>>
  >;
  observed_count_comparisons?: Record<
    'previous_period' | 'year_over_year',
    Record<RiskEntityType, RiskComparison<RiskObservedCount>>
  >;
  trend?: ReportTrend;
}

export interface RiskRedditReport extends RedditReport {
  contract_extension: 'reddit_voc_risk_report_v2';
  momcozy_metrics: NonNullable<RedditReport['momcozy_metrics']>;
  risk_themes: RiskTheme[];
  product_analysis: ProductAnalysis;
  product_period_analysis: ProductPeriodAnalysis;
  competitor_context: CompetitorContext[];
  period_comparisons: NonNullable<RedditReport['period_comparisons']>;
  observed_count_comparisons: NonNullable<RedditReport['observed_count_comparisons']>;
  trend: ReportTrend;
}

export function isRiskReport(report: RedditReport): report is RiskRedditReport {
  return report.contract_extension === RISK_REPORT_EXTENSION;
}

export type V3ReportDirection = 'up' | 'down' | 'flat';
export type V3ReportMetricStatus = 'available' | 'provisional' | 'unavailable';

export interface V3ReportMetricRow {
  comparison_contract_proven: boolean;
  coverage_profile_hash: string;
  data_owner_coverage_attestation_sha256: string | null;
  evidence_ids: string[];
  grain: ReportPeriod;
  metric_id: string;
  metric_policy_version: string;
  name_cn: string;
  observed_time_precision: string;
  observed_voc_type: string;
  period_complete: boolean;
  period_id: string;
  retrieval_contract_hash: string;
  scope: string;
  source_calendar_date: string;
  source_selection_profile_hash: string;
  status: V3ReportMetricStatus;
  time_precision: 'calendar_day_assignment_v1' | 'iso_week_assignment_v1' | 'calendar_month_assignment_v1';
  unavailable_reason_codes: string[];
  unit: 'count' | 'inherit' | 'log_delta2' | 'percent' | 'pp' | 'rank' | 'ratio' | 'score';
  value: string | number | null;
  voc_type: string;
  display: string | number;
}

export interface V3ReportComparison {
  baseline_period_id: string | null;
  baseline_status: V3ReportMetricStatus;
  comparison_basis?: 'exact_period' | 'seven_day_proxy';
  current_period_id?: string | null;
  direction: V3ReportDirection | null;
  display: string;
  display_label?: string;
  line_color: 'red' | 'green' | 'blue' | 'gray';
  profile_hashes: {
    baseline: Record<'source_selection_profile_hash' | 'coverage_profile_hash' | 'retrieval_contract_hash', string | null>;
    current: Record<'source_selection_profile_hash' | 'coverage_profile_hash' | 'retrieval_contract_hash', string | null>;
  };
  reason_codes: string[];
  status: V3ReportMetricStatus;
  unit: string;
  value: string | null;
}

export interface V3ReportSparkline {
  direction: V3ReportDirection | null;
  line_color: 'red' | 'green' | 'blue' | 'gray';
  points: Array<{ label: string; value: string | number | null }>;
  reason_codes: string[];
  status: V3ReportMetricStatus;
  trend_claim_supported: boolean;
}

export interface V3ReportIndicator {
  comparison_help: { symbol: '?'; text: string };
  comparisons: {
    period_over_period: V3ReportComparison;
    year_over_year: V3ReportComparison;
  };
  current: V3ReportMetricRow;
  direction: V3ReportDirection | null;
  line_color: 'red' | 'green' | 'blue' | 'gray';
  metric_id: string;
  name_cn: string;
  sparkline: V3ReportSparkline;
}

export interface V3ReportCoverageAttestation {
  attestation_basis: 'data_owner_declaration';
  completeness_percent: 100;
  coverage_window: {
    end_calendar_date_inclusive: string;
    start_calendar_date_inclusive: string;
  };
  evidence_class: 'owner_attested_not_crawler_proof';
  scope: string;
  source_snapshot_id: string;
}

export interface V3PeriodActivityCounts {
  active_historical_post_count: number;
  comments_on_current_period_posts: number;
  comments_on_historical_posts: number;
  new_comment_count: number;
  new_post_count: number;
  unresolved_parent_comment_count: number;
}

export interface V3PeriodActivity {
  all_observed: V3PeriodActivityCounts;
  comparison_contract_proven: boolean;
  coverage_profile_hash: string;
  data_owner_coverage_attestation_sha256: string | null;
  grain: ReportPeriod;
  momcozy: V3PeriodActivityCounts;
  period_complete: boolean;
  period_id: string;
  retrieval_contract_hash: string;
  scope_contract: {
    all_observed: 'canonical_observation_pool';
    momcozy: 'governed_brand_fact_equals_momcozy';
  };
  source_calendar_date: string;
  source_selection_profile_hash: string;
  time_precision: 'calendar_day_assignment_v1' | 'iso_week_assignment_v1' | 'calendar_month_assignment_v1';
}

export type V3BrandHealthDimensionId =
  | 'reputation'
  | 'product_experience'
  | 'recommendation_trust'
  | 'risk_resilience';

export interface V3BrandHealthRow {
  comparison_side: 'raw_observed' | 'qualified_organic';
  display: string | number;
  status: V3ReportMetricStatus;
  value: string | number | null;
}

export interface V3BrandHealthDimensionRow {
  comparison_side: 'raw_observed' | 'qualified_organic';
  contribution_points: string | null;
  dimension_id: V3BrandHealthDimensionId;
  dimension_value: string | null;
  grain: ReportPeriod;
  period_id: string;
  status: V3ReportMetricStatus;
  unavailable_reason_codes: string[];
  unit: 'index_points';
  weight_percent: '25.00';
}

export interface V3ActionReview {
  completion_supported: false;
  items: [];
  ledger_available: false;
  reason_codes: ['action_ledger_not_supplied'];
  schema_version: 'reddit_voc_action_review_v1';
  status: 'unavailable';
}

export interface V3CurrentReport {
  action_review?: V3ActionReview;
  artifact_role: 'latest_complete_calendar_period' | 'latest_closed_calendar_period_unattested' | 'historical_complete_calendar_period' | 'historical_observed_calendar_period_unattested';
  business_entry_visible?: true;
  boundaries: {
    database_write: false;
    deploy: false;
    live_send: false;
    production_unchanged: true;
    provider_call: false;
    remote_write: false;
  };
  comparison_contract_basis: 'owner_attested_dataset_scope_window' | string;
  comparison_contract_proven: boolean;
  comparison_archive_path?: string;
  completeness_percent: 100 | null;
  coverage_attestation: V3ReportCoverageAttestation | null;
  data_owner_coverage_attestation_sha256: string | null;
  entry_label: '最新完整周期' | '最新闭合周期（覆盖未证明）' | '历史完整周期' | '历史已观测周期（覆盖未证明）';
  fixture_only: boolean;
  grain: ReportPeriod;
  indicators: V3ReportIndicator[];
  brand_health: {
    dimension_rows: V3BrandHealthDimensionRow[];
    metric_id: 'brand_health_index_v2';
    rows: V3BrandHealthRow[];
    scope: 'momcozy';
  };
  period: {
    end: string;
    grain: ReportPeriod;
    is_complete: true;
    period_id: string;
    start: string;
  };
  period_activity?: V3PeriodActivity;
  schema_version: typeof V3_REPORT_SCHEMA;
  source: V3ReportSource;
}

export type DisplayableRedditReport = RedditReport | V3CurrentReport;

export function isV3Report(report: DisplayableRedditReport): report is V3CurrentReport {
  return report.schema_version === V3_REPORT_SCHEMA;
}

export interface RedditReportsSnapshot {
  release: CurrentRelease;
  manifest: ReportManifest;
  index: ReportIndex;
  current: Record<ReportPeriod, RedditReport>;
  archive: Record<ReportPeriod, RedditReport>;
}

export interface V3RedditReportsSnapshot {
  release: CurrentRelease;
  manifest: V3ReportsManifest;
  index: V3ReportIndex;
  historyIndex?: V3BusinessHistoryIndex;
  current: Record<ReportPeriod, V3CurrentReport>;
}

export type AnyRedditReportsSnapshot = RedditReportsSnapshot | V3RedditReportsSnapshot;

export function isV3ReportsSnapshot(
  snapshot: AnyRedditReportsSnapshot,
): snapshot is V3RedditReportsSnapshot {
  return snapshot.manifest.schema_version === V3_REPORTS_MANIFEST_SCHEMA;
}

export class ReportsContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ReportsContractError';
  }
}

const reportsCache = new ReleaseKeyedCache<AnyRedditReportsSnapshot>();
const historicalReportPromises = new Map<string, Promise<V3CurrentReport>>();

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new ReportsContractError(message);
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function assertUniqueExact(actual: string[], expected: Set<string>, message: string): void {
  assertContract(new Set(actual).size === actual.length, `${message}包含重复值`);
  assertContract(actual.length === expected.size && actual.every((value) => expected.has(value)), message);
}

const V3_PROFILE_HASH_FIELDS = [
  'source_selection_profile_hash',
  'coverage_profile_hash',
  'retrieval_contract_hash',
] as const;

function isFiniteNumeric(value: unknown): boolean {
  if (typeof value === 'number') return Number.isFinite(value);
  return typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value));
}

function reportPeriodLastInclusiveDate(report: V3CurrentReport): string | null {
  const end = Date.parse(`${report.period.end}T00:00:00Z`);
  if (!Number.isFinite(end)) return null;
  return new Date(end - 86_400_000).toISOString().slice(0, 10);
}

function v3ReportHasOwnerConfirmedCoverage(report: V3CurrentReport): boolean {
  const attestation = report.coverage_attestation;
  const lastInclusive = reportPeriodLastInclusiveDate(report);
  return report.fixture_only === false
    && report.comparison_contract_proven === true
    && report.comparison_contract_basis === 'owner_attested_dataset_scope_window'
    && report.completeness_percent === 100
    && typeof report.data_owner_coverage_attestation_sha256 === 'string'
    && /^[a-f0-9]{64}$/.test(report.data_owner_coverage_attestation_sha256)
    && attestation !== null
    && attestation.attestation_basis === 'data_owner_declaration'
    && attestation.completeness_percent === 100
    && attestation.evidence_class === 'owner_attested_not_crawler_proof'
    && attestation.source_snapshot_id === report.source.source_snapshot_id
    && typeof attestation.scope === 'string'
    && attestation.scope.length > 0
    && /^\d{4}-\d{2}-\d{2}$/.test(attestation.coverage_window.start_calendar_date_inclusive)
    && /^\d{4}-\d{2}-\d{2}$/.test(attestation.coverage_window.end_calendar_date_inclusive)
    && attestation.coverage_window.start_calendar_date_inclusive <= report.period.start
    && lastInclusive !== null
    && attestation.coverage_window.end_calendar_date_inclusive >= lastInclusive
    && report.period.is_complete === true
    && report.indicators.length > 0
    && report.indicators.every((indicator) => (
      indicator.current.comparison_contract_proven === true
      && indicator.current.period_complete === true
      && indicator.current.data_owner_coverage_attestation_sha256
        === report.data_owner_coverage_attestation_sha256
    ));
}

function assertStringArray(value: unknown, label: string): asserts value is string[] {
  assertContract(
    Array.isArray(value)
      && value.every((item) => typeof item === 'string' && item.length > 0)
      && new Set(value).size === value.length,
    `${label}异常`,
  );
}

function assertV3Comparison(
  comparison: V3ReportComparison,
  current: V3ReportMetricRow,
  label: string,
): void {
  assertStringArray(comparison.reason_codes, `${label}原因码`);
  if (comparison.status === 'unavailable') {
    assertContract(
      comparison.display === '—'
        && comparison.value === null
        && comparison.direction === null
        && comparison.line_color === 'gray'
        && comparison.reason_codes.length > 0,
      `${label}不可用状态没有 fail-closed`,
    );
    return;
  }

  assertContract(current.status !== 'unavailable' && current.value !== null, `${label}当前值不可用`);
  assertContract(
    comparison.direction === 'up' || comparison.direction === 'down' || comparison.direction === 'flat',
    `${label}方向异常`,
  );
  const observedOnly = current.comparison_contract_proven !== true;
  const proxyWindow = comparison.comparison_basis === 'seven_day_proxy';
  const expectedColor = observedOnly || proxyWindow
    ? 'blue'
    : comparison.direction === 'up'
      ? 'red'
      : comparison.direction === 'down'
        ? 'green'
        : 'gray';
  assertContract(
    comparison.display !== '—'
      && comparison.value !== null
      && comparison.line_color === expectedColor
      && (comparison.status === 'provisional'
        ? comparison.reason_codes.length > 0
        : comparison.reason_codes.length === 0),
    `${label}可比较载荷异常`,
  );
  if (observedOnly) {
    assertContract(
      comparison.status === 'provisional'
        && comparison.reason_codes.includes('owner_attestation_missing_observed_same_profile')
        && (comparison.comparison_basis === 'exact_period' || comparison.comparison_basis === 'seven_day_proxy')
        && typeof comparison.display_label === 'string'
        && (
          comparison.display_label.includes('观测')
          || comparison.display_label === '同比（7日替代窗口）'
        ),
      `${label}观察比较缺少证据标签`,
    );
  }
  if (proxyWindow) {
    assertContract(
      comparison.status === 'provisional'
        && comparison.line_color === 'blue'
        && comparison.display_label === '同比（7日替代窗口）'
        && comparison.reason_codes.includes('exact_daily_yoy_unavailable_used_seven_day_proxy'),
      `${label}替代窗口缺少证据标签`,
    );
  }
  V3_PROFILE_HASH_FIELDS.forEach((field) => {
    assertContract(
      comparison.profile_hashes.current[field] === current[field]
        && comparison.profile_hashes.baseline[field] === current[field],
      `${label}${field}不一致`,
    );
  });
}

function assertV3Sparkline(
  sparkline: V3ReportSparkline,
  current: V3ReportMetricRow,
  label: string,
): void {
  assertStringArray(sparkline.reason_codes, `${label}原因码`);
  assertContract(Array.isArray(sparkline.points), `${label}点集异常`);
  sparkline.points.forEach((point) => {
    assertContract(typeof point.label === 'string' && point.label.length > 0, `${label}标签异常`);
    assertContract(point.value === null || isFiniteNumeric(point.value), `${label}数值异常`);
  });
  if (sparkline.status === 'unavailable') {
    assertContract(
      sparkline.direction === null
        && sparkline.line_color === 'gray'
        && sparkline.trend_claim_supported === false
        && sparkline.reason_codes.length > 0,
      `${label}不可用状态没有 fail-closed`,
    );
    return;
  }

  assertContract(
    sparkline.direction === 'up' || sparkline.direction === 'down' || sparkline.direction === 'flat',
    `${label}方向异常`,
  );
  const observedOnly = current.comparison_contract_proven !== true;
  const expectedColor = observedOnly
    ? 'blue'
    : sparkline.direction === 'up'
      ? 'red'
      : sparkline.direction === 'down'
        ? 'green'
        : 'gray';
  assertContract(sparkline.line_color === expectedColor, `${label}颜色异常`);
  if (observedOnly) {
    assertContract(
      sparkline.status === 'provisional'
        && sparkline.reason_codes.includes('owner_attestation_missing_observed_same_profile')
        && sparkline.trend_claim_supported === false,
      `${label}观察趋势缺少证据标签`,
    );
  }
  if (sparkline.status === 'provisional') {
    assertContract(
      sparkline.reason_codes.length > 0 && sparkline.trend_claim_supported === false,
      `${label}观察趋势必须保留说明且不支持正式方向结论`,
    );
  }
  if (sparkline.trend_claim_supported) {
    let contiguous = 0;
    let maximumContiguous = 0;
    sparkline.points.forEach((point) => {
      if (point.value === null) {
        contiguous = 0;
      } else {
        contiguous += 1;
        maximumContiguous = Math.max(maximumContiguous, contiguous);
      }
    });
    assertContract(maximumContiguous >= 3, `${label}趋势方向缺少连续完整周期`);
  }
}

export function validateV3CurrentReport(report: V3CurrentReport): V3CurrentReport {
  assertContract(report.schema_version === V3_REPORT_SCHEMA, 'V3 报告 schema 不受支持');
  const isHistoricalComplete = report.artifact_role === 'historical_complete_calendar_period';
  const isHistoricalObserved = report.artifact_role === 'historical_observed_calendar_period_unattested';
  const isHistorical = isHistoricalComplete || isHistoricalObserved;
  const isUnattestedCurrent = report.artifact_role === 'latest_closed_calendar_period_unattested';
  assertContract(
    report.artifact_role === 'latest_complete_calendar_period' || isUnattestedCurrent || isHistorical,
    'V3 报告业务角色异常',
  );
  assertContract(
    isHistorical
      ? report.entry_label === (isHistoricalComplete ? '历史完整周期' : '历史已观测周期（覆盖未证明）')
        && report.business_entry_visible === true
        && report.comparison_archive_path === undefined
      : report.entry_label === (isUnattestedCurrent ? '最新闭合周期（覆盖未证明）' : '最新完整周期')
        && report.comparison_archive_path === `archive/${report.grain}.json`,
    'V3 报告业务入口异常',
  );
  assertContract(report.period.is_complete === true, 'V3 报告周期未闭合');
  assertContract(report.period.grain === report.grain, 'V3 报告周期粒度不一致');
  assertContract(
    isHistoricalComplete ? report.comparison_contract_proven === true
      : isHistoricalObserved ? report.comparison_contract_proven === false
        : true,
    'V3 历史报告角色与覆盖证明状态不一致',
  );
  if (report.comparison_contract_proven) {
    assertContract(v3ReportHasOwnerConfirmedCoverage(report), 'V3 报告缺少数据所有者 100% 完整性强绑定');
  } else {
    assertContract(
      (isUnattestedCurrent || isHistoricalObserved)
        && report.comparison_contract_basis === 'not_owner_attested'
        && report.completeness_percent === null
        && report.coverage_attestation === null
        && report.data_owner_coverage_attestation_sha256 === null,
      'V3 报告未证明覆盖状态不一致',
    );
  }
  assertContract(
    report.boundaries.production_unchanged === true
      && report.boundaries.provider_call === false
      && report.boundaries.database_write === false
      && report.boundaries.remote_write === false
      && report.boundaries.live_send === false
      && report.boundaries.deploy === false,
    'V3 报告静态副作用边界异常',
  );
  assertContract(Array.isArray(report.indicators) && report.indicators.length > 0, 'V3 报告指标为空');
  assertContract(
    report.brand_health?.metric_id === 'brand_health_index_v2'
      && report.brand_health.scope === 'momcozy'
      && Array.isArray(report.brand_health.rows)
      && report.brand_health.rows.length === 2,
    'V3 品牌健康总分合同异常',
  );
  const dimensionRows = report.brand_health.dimension_rows;
  const expectedDimensions = new Set([
    'reputation',
    'product_experience',
    'recommendation_trust',
    'risk_resilience',
  ]);
  assertContract(Array.isArray(dimensionRows) && dimensionRows.length === 8, 'V3 品牌健康四维集合异常');
  const dimensionKeys = new Set<string>();
  dimensionRows.forEach((row) => {
    assertContract(
      (row.comparison_side === 'raw_observed' || row.comparison_side === 'qualified_organic')
        && expectedDimensions.has(row.dimension_id)
        && row.grain === report.grain
        && row.period_id === report.period.period_id
        && row.unit === 'index_points'
        && row.weight_percent === '25.00',
      'V3 品牌健康四维行合同异常',
    );
    const key = `${row.comparison_side}:${row.dimension_id}`;
    assertContract(!dimensionKeys.has(key), 'V3 品牌健康四维行重复');
    dimensionKeys.add(key);
    if (row.status === 'unavailable') {
      assertContract(
        row.dimension_value === null
          && row.contribution_points === null
          && row.unavailable_reason_codes.length > 0,
        'V3 不可用品牌健康维度携带了数值',
      );
    } else {
      assertContract(
        isFiniteNumeric(row.dimension_value) && isFiniteNumeric(row.contribution_points),
        'V3 可用品牌健康维度缺少数值',
      );
      const dimensionValue = Number(row.dimension_value);
      const contribution = Number(row.contribution_points);
      assertContract(
        dimensionValue >= 0
          && dimensionValue <= 100
          && contribution.toFixed(2) === (Math.round((dimensionValue / 4) * 100) / 100).toFixed(2),
        'V3 品牌健康维度贡献公式异常',
      );
    }
  });
  if (report.grain === 'weekly') {
    assertContract(
      report.action_review?.schema_version === 'reddit_voc_action_review_v1'
        && report.action_review.status === 'unavailable'
        && report.action_review.ledger_available === false
        && report.action_review.completion_supported === false
        && report.action_review.items.length === 0
        && report.action_review.reason_codes.length === 1
        && report.action_review.reason_codes[0] === 'action_ledger_not_supplied',
      'V3 周报行动复盘空状态合同异常',
    );
  } else {
    assertContract(report.action_review === undefined, 'V3 非周报不应包含行动复盘合同');
  }
  if (report.period_activity) {
    const activity = report.period_activity;
    const expectedTimePrecision = {
      daily: 'calendar_day_assignment_v1',
      weekly: 'iso_week_assignment_v1',
      monthly: 'calendar_month_assignment_v1',
    }[report.grain];
    assertContract(
      activity.grain === report.grain
        && activity.period_id === report.period.period_id
        && activity.period_complete === report.comparison_contract_proven
        && activity.comparison_contract_proven === report.comparison_contract_proven
        && activity.data_owner_coverage_attestation_sha256 === report.data_owner_coverage_attestation_sha256
        && activity.time_precision === expectedTimePrecision
        && activity.scope_contract.all_observed === 'canonical_observation_pool'
        && activity.scope_contract.momcozy === 'governed_brand_fact_equals_momcozy',
      'V3 报告活动拆分周期或口径异常',
    );
    (['all_observed', 'momcozy'] as const).forEach((scope) => {
      const counts = activity[scope];
      Object.values(counts).forEach((value) => {
        assertContract(isNonNegativeInteger(value), `V3 报告${scope}活动计数异常`);
      });
      assertContract(
        counts.new_comment_count
          === counts.comments_on_current_period_posts
          + counts.comments_on_historical_posts
          + counts.unresolved_parent_comment_count,
        `V3 报告${scope}评论活动不守恒`,
      );
      assertContract(
        counts.active_historical_post_count <= counts.comments_on_historical_posts,
        `V3 报告${scope}历史活跃帖子计数异常`,
      );
    });
  }
  const metricIds = new Set<string>();
  report.indicators.forEach((indicator, index) => {
    const label = `V3 指标 ${index}`;
    const expectedTimePrecision = {
      daily: 'calendar_day_assignment_v1',
      weekly: 'iso_week_assignment_v1',
      monthly: 'calendar_month_assignment_v1',
    }[report.grain];
    assertContract(indicator.metric_id === indicator.current.metric_id, `${label} ID 不一致`);
    assertContract(indicator.name_cn === indicator.current.name_cn, `${label}名称不一致`);
    assertContract(indicator.current.grain === report.grain, `${label}粒度不一致`);
    assertContract(indicator.current.period_id === report.period.period_id, `${label}周期不一致`);
    assertContract(indicator.current.time_precision === expectedTimePrecision, `${label}时间归属合同不一致`);
    assertContract(Boolean(indicator.current.observed_time_precision), `${label}观察时间精度缺失`);
    assertContract(Boolean(indicator.current.observed_voc_type), `${label}观察 VOC 类型缺失`);
    assertContract(indicator.current.voc_type === 'post_voc+comment_context_voc', `${label}VOC 口径异常`);
    assertContract(
      report.comparison_contract_proven
        ? typeof indicator.current.data_owner_coverage_attestation_sha256 === 'string'
          && /^[a-f0-9]{64}$/.test(indicator.current.data_owner_coverage_attestation_sha256)
        : indicator.current.data_owner_coverage_attestation_sha256 === null,
      `${label}coverage attestation SHA 异常`,
    );
    assertContract(indicator.current.period_complete === report.comparison_contract_proven, `${label}覆盖完整标志不一致`);
    assertContract(
      indicator.current.comparison_contract_proven === report.comparison_contract_proven,
      `${label}comparison contract 与报告级声明不一致`,
    );
    if (report.data_owner_coverage_attestation_sha256 !== null) {
      assertContract(
        indicator.current.data_owner_coverage_attestation_sha256
          === report.data_owner_coverage_attestation_sha256,
        `${label}coverage attestation SHA 不一致`,
      );
    }
    assertContract(!metricIds.has(indicator.metric_id), `${label}重复`);
    metricIds.add(indicator.metric_id);
    assertContract(indicator.comparison_help.symbol === '?' && Boolean(indicator.comparison_help.text), `${label}说明缺失`);
    assertStringArray(indicator.current.evidence_ids, `${label}证据 ID`);
    assertStringArray(indicator.current.unavailable_reason_codes, `${label}不可用原因码`);
    assertContract(
      (indicator.current.status === 'unavailable') === (indicator.current.value === null),
      `${label}当前值与状态不一致`,
    );
    V3_PROFILE_HASH_FIELDS.forEach((field) => {
      assertContract(/^[a-f0-9]{64}$/.test(indicator.current[field]), `${label}${field}异常`);
    });
    assertV3Comparison(indicator.comparisons.period_over_period, indicator.current, `${label}环比`);
    assertV3Comparison(indicator.comparisons.year_over_year, indicator.current, `${label}同比`);
    assertV3Sparkline(indicator.sparkline, indicator.current, `${label}趋势`);
    if (indicator.current.comparison_contract_proven !== true) {
      assertContract(
        Object.values(indicator.comparisons).every((comparison) => (
          comparison.status === 'unavailable' || comparison.status === 'provisional'
        ))
          && indicator.sparkline.status !== 'available'
          && indicator.sparkline.trend_claim_supported === false,
        `${label}未证明覆盖却发布正式比较结论`,
      );
    }
  });
  return report;
}

export interface HistoricalCompletenessPresentation {
  supported: boolean;
  label: string;
  detail: string;
}

const LEGACY_COVERAGE_LABELS: Record<ReportCoverageStatus, string> = {
  observed_records_present_but_collection_coverage_unverified: '历史采集覆盖未验证',
  coverage_gap: '历史采集存在覆盖缺口',
  complete: 'V1/V2 报告未绑定数据所有者完整性确认',
  partial: '历史采集覆盖不完整',
  unavailable: '历史采集完整性不可用',
  coverage_missing: '历史采集覆盖证据缺失',
};

export function historicalCompletenessPresentation(
  report: DisplayableRedditReport,
): HistoricalCompletenessPresentation {
  if (isV3Report(report)) {
    const supported = v3ReportHasOwnerConfirmedCoverage(report);
    if (supported) {
      return {
        supported: true,
        label: '历史采集完整性：数据所有者确认100%',
        detail: '当前报告已绑定完整统计周期和一致的数据范围；页面直接使用已校验的报告结果。',
      };
    }
    if (report.fixture_only) {
      return {
        supported: false,
        label: '历史采集完整性：不可用',
        detail: '当前内容是测试夹具，不属于可消费的真实报告版本。',
      };
    }
    return {
      supported: false,
      label: '已观测周期：同环比与趋势可用（覆盖未证明）',
      detail: '日报、周报、月报按同源同口径展示观测级同环比与六期趋势；全量采集完整性和正式市场趋势结论仍保持关闭。',
    };
  }
  return {
    supported: false,
    label: '历史采集完整性：不可用',
    detail: LEGACY_COVERAGE_LABELS[report.window.coverage_status],
  };
}

function assertSentimentSummary(summary: ReportSentimentSummary, label: string): void {
  assertContract(isNonNegativeInteger(summary.denominator), `${label}分母无效`);
  const countTotal = (['positive', 'neutral', 'negative'] as const).reduce((sum, key) => {
    const count = summary.counts[key];
    assertContract(isNonNegativeInteger(count), `${label}${key} 计数无效`);
    const share = summary.shares[key];
    assertContract(share.numerator === count && share.denominator === summary.denominator, `${label}${key} 分母不一致`);
    assertContract(
      share.value === (summary.denominator ? Number((count / summary.denominator).toFixed(6)) : null),
      `${label}${key} 比例不一致`,
    );
    return sum + count;
  }, 0);
  assertContract(countTotal === summary.denominator, `${label}情感计数与分母不一致`);
}

function assertFalseBoundaries(report: RedditReport): void {
  const interpretation = report.interpretation_boundaries;
  assertContract(interpretation.market_share_supported === false, '报告错误支持市场份额');
  assertContract(interpretation.roi_supported === false, '报告错误支持 ROI');
  assertContract(interpretation.trend_claim_supported === false, '报告错误支持趋势结论');
  assertContract(interpretation.comparison_status === 'coverage_unverified', '报告跨期比较边界异常');
  assertContract(interpretation.consumer_card_is_reference_not_persona_id === true, 'consumer_card 画像边界缺失');
  assertContract(interpretation.persona_tags_generated === false, '报告错误声称已生成画像标签');
  assertContract(interpretation.held_tags_in_business_findings === 0, 'held 标签进入了业务发现');
  const runtime = report.runtime_boundaries;
  assertContract(runtime.production_unchanged === true, '报告缺少 production unchanged 边界');
  assertContract(
    runtime.provider_call === false
      && runtime.database_write === false
      && runtime.live_send === false
      && runtime.webhook_send === false
      && runtime.deploy === false
      && runtime.schedule_change === false,
    '报告静态运行副作用边界异常',
  );
}

function validateLegacyReport(
  report: RedditReport,
  descriptor: ReportDescriptor,
  manifest: ReportManifest,
): RedditReport {
  assertContract(report.schema_version === REPORT_SCHEMA, `报告 schema 不受支持：${descriptor.path}`);
  assertContract(report.identity.dataset_version === manifest.dataset_version, `报告版本不一致：${descriptor.path}`);
  assertContract(report.identity.report_id === descriptor.report_id, `报告 ID 不一致：${descriptor.path}`);
  assertContract(report.identity.period === descriptor.period, `报告周期不一致：${descriptor.path}`);
  assertContract(report.identity.window_mode === descriptor.window_mode, `报告窗口模式不一致：${descriptor.path}`);
  assertContract(report.window.start_utc === descriptor.start_utc && report.window.end_utc === descriptor.end_utc, `报告窗口不一致：${descriptor.path}`);
  assertContract(report.window.as_of_utc === manifest.generated_at_utc, `报告 as-of 不一致：${descriptor.path}`);
  assertContract(report.window.timezone === 'Asia/Shanghai', `报告时区不一致：${descriptor.path}`);
  assertContract(report.window.coverage_status === descriptor.coverage_status, `报告覆盖状态不一致：${descriptor.path}`);
  assertContract(report.window.comparison_status === 'coverage_unverified', `报告错误支持跨期比较：${descriptor.path}`);
  assertContract(Date.parse(report.window.start_utc) < Date.parse(report.window.end_utc), `报告时间窗口无效：${descriptor.path}`);

  const { headline } = report;
  assertContract(
    isNonNegativeInteger(headline.posts)
      && isNonNegativeInteger(headline.voc_comments)
      && headline.posts === descriptor.posts
      && headline.voc_comments === descriptor.voc_comments,
    `报告 headline 与 index 不一致：${descriptor.path}`,
  );
  assertContract(headline.observed_entities === headline.posts + headline.voc_comments, `报告实体总数不一致：${descriptor.path}`);
  assertContract(headline.quarantined_comments_counted === 0, `隔离评论进入报告：${descriptor.path}`);
  assertSentimentSummary(headline.post_sentiment, `${descriptor.path} 帖子`);
  assertSentimentSummary(headline.comment_sentiment, `${descriptor.path} 评论`);
  assertContract(headline.post_sentiment.denominator === headline.posts, `帖子情感分母不一致：${descriptor.path}`);
  assertContract(headline.comment_sentiment.denominator === headline.voc_comments, `评论情感分母不一致：${descriptor.path}`);

  const timelinePosts = report.observed_timeline.reduce((sum, point) => sum + point.posts, 0);
  const timelineComments = report.observed_timeline.reduce((sum, point) => sum + point.voc_comments, 0);
  assertContract(timelinePosts === headline.posts && timelineComments === headline.voc_comments, `时间序列计数不一致：${descriptor.path}`);
  report.observed_timeline.forEach((point, index) => {
    assertContract(point.observed_entities === point.posts + point.voc_comments, `时间桶实体数不一致：${descriptor.path}`);
    if (index > 0) {
      assertContract(report.observed_timeline[index - 1].bucket_end_utc === point.bucket_start_utc, `时间桶不连续：${descriptor.path}`);
    }
  });
  if (report.observed_timeline.length) {
    assertContract(report.observed_timeline[0].bucket_start_utc === report.window.start_utc, `时间序列起点不一致：${descriptor.path}`);
    assertContract(report.observed_timeline.at(-1)?.bucket_end_utc === report.window.end_utc, `时间序列终点不一致：${descriptor.path}`);
  }

  assertContract(report.communities.reduce((sum, row) => sum + row.posts, 0) === headline.posts, `社区帖子计数不一致：${descriptor.path}`);
  assertContract(report.communities.reduce((sum, row) => sum + row.voc_comments, 0) === headline.voc_comments, `社区评论计数不一致：${descriptor.path}`);
  assertContract(report.topics.reduce((sum, row) => sum + row.post_entities, 0) === headline.posts, `主题帖子计数不一致：${descriptor.path}`);
  report.brand_mentions.forEach((row) => {
    assertContract(row.metric_label === 'sample_mention_posts', `品牌指标错误声称份额：${descriptor.path}`);
    assertContract(row.sample_mention_share.denominator === headline.posts, `品牌样本提及分母不一致：${descriptor.path}`);
  });

  assertUniqueExact(report.promoted_signals.map((signal) => signal.tag_id), PROMOTED_TAG_IDS, `报告晋级标签集合异常：${descriptor.path}`);
  report.promoted_signals.forEach((signal) => {
    const bindingTotal = Object.values(signal.binding_counts).reduce((sum, value) => sum + value, 0);
    assertContract(signal.matched_entities === signal.matched_posts + signal.matched_comments, `标签实体计数不一致：${signal.tag_id}`);
    assertContract(bindingTotal === signal.matched_entities, `标签主体绑定计数不一致：${signal.tag_id}`);
    assertContract(
      signal.momcozy_specific_entities === signal.binding_counts.momcozy_sentence_bound,
      `Momcozy 专属标签证据越界：${signal.tag_id}`,
    );
    assertContract(Boolean(signal.dictionary_reference.consumer_card), `标签缺少 consumer_card 参考映射：${signal.tag_id}`);
  });
  assertUniqueExact(report.capabilities.unsupported, REQUIRED_UNSUPPORTED, `不支持能力集合异常：${descriptor.path}`);
  assertFalseBoundaries(report);

  if (report.window.coverage_status === 'coverage_gap') {
    assertContract(headline.observed_entities === 0, `覆盖缺口报告错误包含记录：${descriptor.path}`);
  } else {
    assertContract(headline.observed_entities > 0, `有覆盖记录状态但报告为空：${descriptor.path}`);
  }
  return report;
}

const COMPARISON_STATUSES = new Set<RiskComparisonStatus>([
  'comparable',
  'provisional_observed_sample',
  'unavailable',
]);
const PUBLIC_RISK_THEME_FORBIDDEN_FIELDS = [
  'biz_action',
  'business_impact',
  'dept_owner',
  'dictionary_default_priority',
  'strategy_package',
  'suggested_action',
] as const;

function assertUnsupportedCombined(metric: { supported: false; reason: string; value: null }, label: string): void {
  assertContract(metric.supported === false && metric.value === null && Boolean(metric.reason), `${label}错误合并帖子与评论`);
}

function assertRiskMetric(metric: RiskObservedCount | RiskShareMetric, label: string): void {
  assertContract(typeof metric.metric === 'string' && typeof metric.value_status === 'string', `${label}指标结构异常`);
  assertContract(metric.value === null || Number.isFinite(metric.value), `${label}指标值异常`);
  if ('denominator' in metric) {
    assertContract(metric.denominator === null || isNonNegativeInteger(metric.denominator), `${label}分母异常`);
    assertContract(metric.numerator === null || isNonNegativeInteger(metric.numerator), `${label}分子异常`);
  }
}

function assertComparison(comparison: RiskComparison, label: string): void {
  assertContract(COMPARISON_STATUSES.has(comparison.comparison_status), `${label}比较状态异常`);
  assertContract(Array.isArray(comparison.reason_codes), `${label}比较原因异常`);
  assertRiskMetric(comparison.current, `${label}当前期`);
  if (comparison.baseline) assertRiskMetric(comparison.baseline, `${label}基期`);
  if (comparison.comparison_status === 'unavailable') {
    assertContract(
      comparison.absolute_delta === null
        && comparison.relative_delta === null
        && comparison.direction_claim_supported === false
        && comparison.reason_codes.length > 0,
      `${label}不可比较状态缺少 null/reason 边界`,
    );
  }
  if (comparison.comparison_status !== 'comparable') {
    assertContract(comparison.direction_claim_supported === false, `${label}未通过覆盖门禁却声称方向结论`);
  }
}

function assertRiskTheme(theme: RiskTheme, label: string): void {
  assertContract(Boolean(theme.risk_theme_id) && theme.risk_theme_id === theme.tag_id, `${label}风险主题 ID 异常`);
  assertContract(['P0', 'P1', 'P2', 'P3', 'insufficient'].includes(theme.effective_priority), `${label}优先级异常`);
  assertContract(theme.evidence_gate.status === 'passed' || theme.evidence_gate.status === 'insufficient', `${label}证据门禁异常`);
  assertContract(
    (theme.evidence_gate.status === 'passed') === (theme.effective_priority !== 'insufficient'),
    `${label}证据门禁与有效优先级不一致`,
  );
  assertContract(theme.evidence_refs.length <= 20, `${label}证据引用超过公开上限`);
  assertContract(theme.evidence_ref_count_total >= theme.evidence_refs.length, `${label}证据引用总数异常`);
  if (theme.evidence_refs_truncated) {
    assertContract(theme.evidence_ref_count_total > theme.evidence_refs.length, `${label}证据截断标志异常`);
  }
  const keys = new Set<string>();
  theme.evidence_refs.forEach((evidence, index) => {
    const key = `${evidence.entity_type}:${evidence.entity_id}`;
    assertContract(!keys.has(key), `${label}证据引用重复`);
    keys.add(key);
    assertContract(Boolean(evidence.post_id), `${label}证据引用 ${index} 缺少帖子检索 ID`);
    assertContract(Object.keys(evidence).sort().join(',') === 'entity_id,entity_type,post_id', `${label}公开证据引用字段集合异常`);
  });
  const record = theme as unknown as Record<string, unknown>;
  PUBLIC_RISK_THEME_FORBIDDEN_FIELDS.forEach((field) => {
    assertContract(!(field in record), `${label}公开风险主题包含内部字段：${field}`);
  });
}

function validateRiskReport(
  report: RiskRedditReport,
  descriptor: ReportDescriptor,
  manifest: ReportManifest,
): RiskRedditReport {
  assertContract(report.schema_version === REPORT_SCHEMA, `报告 schema 不受支持：${descriptor.path}`);
  assertContract(report.identity.dataset_version === manifest.dataset_version, `报告版本不一致：${descriptor.path}`);
  assertContract(report.identity.report_id === descriptor.report_id, `报告 ID 不一致：${descriptor.path}`);
  assertContract(report.identity.period === descriptor.period && report.product_period_analysis.period === descriptor.period, `报告周期不一致：${descriptor.path}`);
  assertContract(report.identity.window_mode === 'calendar_closed' && descriptor.window_mode === 'calendar_closed', `v2 报告必须使用闭合日历期：${descriptor.path}`);
  assertContract(report.window.is_closed === true, `v2 报告窗口未闭合：${descriptor.path}`);
  assertContract(report.window.start_utc === descriptor.start_utc && report.window.end_utc === descriptor.end_utc, `报告窗口不一致：${descriptor.path}`);
  assertContract(report.window.coverage_status === descriptor.coverage_status, `报告覆盖状态不一致：${descriptor.path}`);
  assertContract(report.window.comparison_status === descriptor.comparison_status, `报告比较状态不一致：${descriptor.path}`);
  assertContract(COMPARISON_STATUSES.has(report.window.comparison_status as RiskComparisonStatus), `报告比较状态异常：${descriptor.path}`);
  assertContract(report.window.timezone === 'Asia/Shanghai' && Date.parse(report.window.start_utc) < Date.parse(report.window.end_utc), `报告时间边界异常：${descriptor.path}`);

  const { headline } = report;
  assertContract(headline.posts === descriptor.posts && headline.voc_comments === descriptor.voc_comments, `报告 headline 与 index 不一致：${descriptor.path}`);
  assertContract(headline.observed_entities === headline.posts + headline.voc_comments, `报告实体总数不一致：${descriptor.path}`);
  assertContract(headline.quarantined_comments_counted === 0, `隔离评论进入报告：${descriptor.path}`);
  assertSentimentSummary(headline.post_sentiment, `${descriptor.path} 帖子`);
  assertSentimentSummary(headline.comment_sentiment, `${descriptor.path} 评论`);

  assertContract(report.interpretation_boundaries.posts_and_comments_separate_by_default === true, `报告缺少帖子评论分离边界：${descriptor.path}`);
  assertContract(report.interpretation_boundaries.combined_view_supported === false, `报告错误支持帖子评论合并：${descriptor.path}`);
  assertContract(report.interpretation_boundaries.market_share_supported === false && report.interpretation_boundaries.roi_supported === false, `报告包含不支持的市场推断：${descriptor.path}`);
  assertContract(report.interpretation_boundaries.trend_claim_supported === false, `V2 报告错误开放趋势结论：${descriptor.path}`);
  const runtime = report.runtime_boundaries;
  assertContract(runtime.production_unchanged === true, `报告缺少 production unchanged：${descriptor.path}`);
  assertContract(
    runtime.provider_call === false && runtime.database_write === false && runtime.live_send === false
      && runtime.webhook_send === false && runtime.deploy === false && runtime.schedule_change === false,
    `报告静态副作用边界异常：${descriptor.path}`,
  );

  assertUnsupportedCombined(report.momcozy_metrics.observed_count.combined, `${descriptor.path} Momcozy 观察量`);
  assertUnsupportedCombined(report.momcozy_metrics.negative_evidence_share.combined, `${descriptor.path} Momcozy 负面占比`);
  (['post', 'comment'] as const).forEach((entityType) => {
    assertRiskMetric(report.momcozy_metrics.observed_count[entityType], `${descriptor.path} ${entityType}观察量`);
    assertRiskMetric(report.momcozy_metrics.negative_evidence_share[entityType], `${descriptor.path} ${entityType}负面占比`);
    (['previous_period', 'year_over_year'] as const).forEach((comparisonPeriod) => {
      const negativeComparison = report.period_comparisons[comparisonPeriod][entityType];
      const countComparison = report.observed_count_comparisons[comparisonPeriod][entityType];
      assertComparison(negativeComparison, `${descriptor.path} ${comparisonPeriod}/${entityType}/负面占比`);
      assertComparison(countComparison, `${descriptor.path} ${comparisonPeriod}/${entityType}/观察量`);
      assertContract(
        negativeComparison.direction_claim_supported === false
          && countComparison.direction_claim_supported === false,
        `V2 报告错误开放比较方向：${descriptor.path}`,
      );
    });
  });
  report.risk_themes.forEach((theme, index) => assertRiskTheme(theme, `${descriptor.path} 风险主题 ${index}`));
  assertContract(new Set(report.risk_themes.map((theme) => theme.risk_theme_id)).size === report.risk_themes.length, `报告风险主题重复：${descriptor.path}`);
  assertContract(report.product_analysis.decision_subject === 'momcozy' && report.product_period_analysis.decision_subject === 'momcozy', `报告产品主干不是 Momcozy：${descriptor.path}`);
  assertContract(report.product_period_analysis.scope_order.join(',') === 'category,product_family,spu_exact', `报告产品层级顺序异常：${descriptor.path}`);
  (['category', 'product_family', 'spu_exact'] as const).forEach((level) => {
    report.product_period_analysis[level].forEach((row) => {
      assertContract(row.trend.direction_claim_supported === false, `V2 产品指标错误开放趋势方向：${descriptor.path}`);
      (['previous_period', 'year_over_year'] as const).forEach((comparisonPeriod) => {
        (['post', 'comment'] as const).forEach((entityType) => {
          const comparisons = row.period_comparisons[comparisonPeriod][entityType];
          assertContract(
            comparisons.observed_count.direction_claim_supported === false
              && comparisons.negative_evidence_share.direction_claim_supported === false,
            `V2 产品指标错误开放比较方向：${descriptor.path}`,
          );
        });
      });
    });
  });
  assertContract(report.trend.point_count === report.trend.points.length, `报告趋势点数不一致：${descriptor.path}`);
  assertContract(
    report.trend.direction_claim_supported === false
      && report.trend.direction_claim_supported_by_metric.negative_evidence_share === false
      && report.trend.direction_claim_supported_by_metric.observed_count === false,
    `V2 报告错误开放趋势方向：${descriptor.path}`,
  );
  report.trend.points.forEach((point, pointIndex) => {
    (['post', 'comment'] as const).forEach((entityType) => {
      assertRiskMetric(point.negative_evidence_share[entityType], `${descriptor.path} 趋势 ${pointIndex}/${entityType}/负面占比`);
      assertRiskMetric(point.observed_count[entityType], `${descriptor.path} 趋势 ${pointIndex}/${entityType}/观察量`);
    });
  });
  return report;
}

function validateReport(
  report: RedditReport,
  descriptor: ReportDescriptor,
  manifest: ReportManifest,
): RedditReport {
  return isRiskReport(report)
    ? validateRiskReport(report, descriptor, manifest)
    : validateLegacyReport(report, descriptor, manifest);
}

function isV3ReportsManifest(value: unknown): value is V3ReportsManifest {
  return Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
    && (value as { schema_version?: unknown }).schema_version === V3_REPORTS_MANIFEST_SCHEMA;
}

function isV3ReportsCandidateManifest(value: unknown): boolean {
  return Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
    && (value as { schema_version?: unknown }).schema_version === V3_REPORTS_CANDIDATE_MANIFEST_SCHEMA;
}

const V3_REPORT_BOOTSTRAP_PATHS = new Set([
  'report-index.json',
  'business-history-index.json',
  'validation-receipt.json',
  'current/daily.json',
  'current/weekly.json',
  'current/monthly.json',
  'archive/daily.json',
  'archive/weekly.json',
  'archive/monthly.json',
]);

function assertSha256(value: unknown, label: string): asserts value is string {
  assertContract(typeof value === 'string' && /^[a-f0-9]{64}$/.test(value), `${label} SHA-256 异常`);
}

function assertV3StaticBoundaries(
  boundaries: V3ReportsManifest['boundaries'],
  label: string,
): void {
  assertContract(
    boundaries.production_unchanged === true
      && boundaries.provider_call === false
      && boundaries.database_write === false
      && boundaries.remote_write === false
      && boundaries.live_send === false
      && boundaries.deploy === false,
    `${label}静态副作用边界异常`,
  );
}

function assertV3CoverageAttestation(
  attestation: V3ReportCoverageAttestation,
  expectedSourceSnapshotId: string,
  label: string,
): void {
  assertContract(
    attestation.attestation_basis === 'data_owner_declaration'
      && attestation.completeness_percent === 100
      && attestation.evidence_class === 'owner_attested_not_crawler_proof'
      && attestation.source_snapshot_id === expectedSourceSnapshotId
      && Boolean(attestation.scope)
      && /^\d{4}-\d{2}-\d{2}$/.test(attestation.coverage_window.start_calendar_date_inclusive)
      && /^\d{4}-\d{2}-\d{2}$/.test(attestation.coverage_window.end_calendar_date_inclusive)
      && attestation.coverage_window.start_calendar_date_inclusive
        <= attestation.coverage_window.end_calendar_date_inclusive,
    `${label}数据所有者完整性声明异常`,
  );
}

function assertV3ManifestCoverageContract(manifest: V3ReportsManifest): void {
  const comparisonReasons = manifest.comparison_unavailable_reason_codes ?? [];
  assertStringArray(comparisonReasons, 'V3 报告 comparison unavailable reason codes');
  if (manifest.comparison_contract_proven) {
    assertContract(
      manifest.comparison_contract_basis === 'owner_attested_dataset_scope_window'
        && manifest.completeness_percent === 100
        && manifest.data_owner_coverage_attestation_sha256 !== null
        && comparisonReasons.length === 0,
      'V3 报告已证明覆盖合同异常',
    );
    assertSha256(manifest.data_owner_coverage_attestation_sha256, 'V3 报告 coverage attestation');
    assertContract(manifest.coverage_attestation !== null, 'V3 报告缺少 coverage attestation');
    assertV3CoverageAttestation(manifest.coverage_attestation, manifest.source_snapshot_id, 'V3 报告 manifest ');
    return;
  }
  assertContract(
    manifest.comparison_contract_basis === 'not_owner_attested'
      && manifest.completeness_percent === null
      && manifest.coverage_attestation === null
      && manifest.data_owner_coverage_attestation_sha256 === null
      && comparisonReasons.length === 1
      && comparisonReasons[0] === V3_UNATTESTED_COVERAGE_REASON,
    'V3 报告未证明覆盖合同异常',
  );
}

function assertSameJson(actual: unknown, expected: unknown, label: string): void {
  assertContract(JSON.stringify(actual) === JSON.stringify(expected), `${label}不一致`);
}

export function validateV3ReportsManifestDispatch(
  manifest: V3ReportsManifest,
  release: CurrentRelease,
): V3ReportsManifest {
  assertContract(manifest.schema_version === V3_REPORTS_MANIFEST_SCHEMA, 'V3 报告 manifest schema 不受支持');
  assertContract(manifest.dataset_version === release.datasets.reports.dataset_version, 'V3 报告版本与 current release 不一致');
  assertContract(
    manifest.lineage_manifest_sha256 === release.datasets.reports.lineage_manifest_sha256,
    'V3 报告 lineage manifest 与 current release 不一致',
  );
  assertContract(manifest.fixture_only === false, 'V3 fixture 报告不能进入发布加载链');
  assertV3StaticBoundaries(manifest.boundaries, 'V3 报告 manifest ');
  assertContract(
    manifest.artifact_stage === 'reports_public_candidate'
      && manifest.status === 'validated_candidate'
      && manifest.consumption_status === 'eligible_for_frontend_candidate_consumption'
      && manifest.independent_validation_status === 'passed'
      && manifest.promotable === true
      && manifest.privacy_safe_projection === true,
    'V3 报告 public wrapper 未通过消费门禁',
  );
  assertV3ManifestCoverageContract(manifest);
  const expectedHistoryCount = manifest.history_report_count;
  assertContract(
    expectedHistoryCount === 38 || (!manifest.comparison_contract_proven && expectedHistoryCount === 0),
    'V3 报告历史访问状态异常',
  );
  const expectedReportCount = 6 + expectedHistoryCount;
  const expectedBusinessEntryCount = 3 + expectedHistoryCount;
  assertContract(
    manifest.report_count === expectedReportCount
      && manifest.history_report_count === expectedHistoryCount
      && manifest.business_entry_count === expectedBusinessEntryCount
      && JSON.stringify(manifest.contract_extensions) === JSON.stringify([
        'reddit_voc_period_activity_v1',
        'reddit_voc_brand_health_dimension_contribution_v1',
        'reddit_voc_action_review_v1',
        'reddit_voc_business_history_index_v1',
      ]),
    'V3 报告历史扩展合同异常',
  );
  const filePaths = Object.keys(manifest.files);
  assertContract(
    new Set(filePaths).size === filePaths.length
      && filePaths.length === V3_REPORT_BOOTSTRAP_PATHS.size + expectedHistoryCount,
    'V3 报告文件集合不一致',
  );
  V3_REPORT_BOOTSTRAP_PATHS.forEach((path) => {
    assertContract(Boolean(manifest.files[path]), `V3 报告 bootstrap 文件缺失：${path}`);
  });
  const historyCounts: Record<ReportPeriod, number> = { daily: 0, weekly: 0, monthly: 0 };
  filePaths.forEach((path) => {
    if (V3_REPORT_BOOTSTRAP_PATHS.has(path)) return;
    const match = /^history\/(daily|weekly|monthly)\/[0-9_-]+\.json$/.exec(path);
    assertContract(Boolean(match), `V3 报告公开路径异常：${path}`);
    historyCounts[match![1] as ReportPeriod] += 1;
  });
  assertContract(
    expectedHistoryCount > 0
      ? historyCounts.daily === 14 && historyCounts.weekly === 12 && historyCounts.monthly === 12
      : historyCounts.daily === 0 && historyCounts.weekly === 0 && historyCounts.monthly === 0,
    'V3 报告历史文件数量异常',
  );
  Object.entries(manifest.files).forEach(([path, integrity]) => {
    assertContract(
      integrity.bytes > 0 && /^[a-f0-9]{64}$/.test(integrity.sha256),
      `V3 报告文件完整性声明异常：${path}`,
    );
  });
  assertSha256(manifest.validation_receipt_sha256, 'V3 报告 validation receipt');
  assertContract(
    manifest.files['validation-receipt.json'].sha256 === manifest.validation_receipt_sha256,
    'V3 报告 manifest 未绑定 embedded validation receipt',
  );
  return manifest;
}

function validateManifest(manifest: ReportManifest, release: CurrentRelease): void {
  assertContract(manifest.schema_version === REPORTS_MANIFEST_SCHEMA, '报告 manifest schema 不受支持');
  assertContract(manifest.dataset_version === release.datasets.reports.dataset_version, '报告数据版本与 current release 不一致');
  assertContract(manifest.delivery_mode === 'versioned_static_reports', '报告 delivery mode 异常');
  assertContract(manifest.base_dataset_version === release.datasets.base.dataset_version, '报告基础快照版本不一致');
  assertContract(
    manifest.base_manifest_sha256 === release.datasets.base.lineage_manifest_sha256,
    '报告基础 lineage 哈希绑定不一致',
  );
  assertContract(manifest.insights_dataset_version === release.datasets.insights.dataset_version, '报告 Insights 版本不一致');
  assertContract(
    manifest.insights_manifest_sha256 === release.datasets.insights.lineage_manifest_sha256,
    '报告 Insights lineage 哈希绑定不一致',
  );
  assertContract(manifest.report_count === 6, '报告数量不一致');
  if (manifest.contract_extension === 'reddit_voc_reports_manifest_v2') {
    assertContract(
      manifest.status === 'passed'
        || manifest.status === 'passed_with_comparison_coverage_limits'
        || manifest.status === 'passed_provisional_risk_threshold',
      'v2 报告门禁状态异常',
    );
    assertContract(Object.keys(manifest.files).length === 7 && Boolean(manifest.files['report-index.json']), 'v2 报告文件数量异常');
    Object.entries(manifest.files).forEach(([path, integrity]) => {
      assertContract(
        path === 'report-index.json'
          || /^(current\/(daily|weekly|monthly)\.json|archive\/(daily|weekly|monthly)-[0-9_-]+\.json)$/.test(path),
        `v2 报告公开路径异常：${path}`,
      );
      assertContract(integrity.bytes > 0 && /^[a-f0-9]{64}$/.test(integrity.sha256), `v2 报告文件完整性声明异常：${path}`);
    });
    const boundaries = manifest.boundaries;
    assertContract(boundaries.production_unchanged === true, 'v2 报告 manifest 缺少 production unchanged');
    assertContract(
      boundaries.provider_call === false && boundaries.database_write === false
        && boundaries.live_send === false && boundaries.webhook_send === false
        && boundaries.deploy === false && boundaries.schedule_change === false
        && boundaries.market_share_supported === false && boundaries.roi_supported === false
        && boundaries.trend_claim_supported === false,
      'v2 报告 manifest 副作用或指标边界异常',
    );
    return;
  }
  assertUniqueExact(manifest.promoted_tag_ids, PROMOTED_TAG_IDS, 'manifest 晋级标签集合不一致');
  assertContract(manifest.held_tag_ids_excluded.length === 8, 'manifest held 标签排除数不一致');
  assertContract(new Set(manifest.held_tag_ids_excluded).size === 8, 'manifest held 标签排除集合重复');
  assertUniqueExact(Object.keys(manifest.files), new Set(['report-index.json', ...EXPECTED_REPORT_PATHS]), 'manifest 文件集合不一致');
  const boundaries = manifest.boundaries;
  assertContract(boundaries.production_unchanged === true, '报告 manifest 缺少 production unchanged');
  assertContract(boundaries.consumer_card_is_reference_not_persona_id === true, '报告 manifest 缺少画像参考边界');
  assertContract(
    boundaries.provider_call === false
      && boundaries.database_write === false
      && boundaries.live_send === false
      && boundaries.webhook_send === false
      && boundaries.deploy === false
      && boundaries.schedule_change === false
      && boundaries.persona_tags_generated === false
      && boundaries.market_share_supported === false
      && boundaries.roi_supported === false
      && boundaries.trend_claim_supported === false,
    '报告 manifest 副作用或能力边界异常',
  );
}

function validateIndex(index: ReportIndex, manifest: ReportManifest): void {
  assertContract(index.schema_version === REPORTS_INDEX_SCHEMA, '报告 index schema 不受支持');
  assertContract(index.dataset_version === manifest.dataset_version, '报告 index 版本不一致');
  assertContract(index.as_of_utc === manifest.generated_at_utc, '报告 index as-of 不一致');
  assertContract(index.timezone === 'Asia/Shanghai', '报告 index 时区不一致');
  const periods: ReportPeriod[] = ['daily', 'weekly', 'monthly'];
  assertContract(Object.keys(index.current).length === 3 && Object.keys(index.archive).length === 3, '报告 index 周期数量不一致');
  if (manifest.contract_extension === 'reddit_voc_reports_manifest_v2') {
    assertContract(index.contract_extension === 'reddit_voc_report_index_v2', 'v2 报告 index extension 异常');
    periods.forEach((period) => {
      const current = index.current[period];
      const archive = index.archive[period];
      assertContract(current.period === period && current.window_mode === 'calendar_closed', `当前${period}报告不是闭合期`);
      assertContract(archive.period === period && archive.window_mode === 'calendar_closed', `归档${period}报告不是闭合期`);
      assertContract(COMPARISON_STATUSES.has(current.comparison_status as RiskComparisonStatus), `当前${period}比较状态异常`);
      assertContract(COMPARISON_STATUSES.has(archive.comparison_status as RiskComparisonStatus), `归档${period}比较状态异常`);
    });
    const paths = periods.flatMap((period) => [index.current[period].path, index.archive[period].path]);
    assertContract(new Set(paths).size === 6, 'v2 报告 index 路径重复');
    assertContract(paths.every((path) => Boolean(manifest.files[path])), 'v2 报告 index 路径未被 manifest 约束');
    assertUniqueExact(Object.keys(manifest.files), new Set(['report-index.json', ...paths]), 'v2 manifest/index 文件集合不一致');
    return;
  }
  periods.forEach((period) => {
    assertContract(index.current[period].period === period && index.current[period].window_mode === 'rolling', `当前${period}报告索引异常`);
    assertContract(index.archive[period].period === period && index.archive[period].window_mode === 'calendar_closed', `归档${period}报告索引异常`);
  });
  const paths = periods.flatMap((period) => [index.current[period].path, index.archive[period].path]);
  assertUniqueExact(paths, new Set(EXPECTED_REPORT_PATHS), '报告 index 文件集合不一致');
}

function reportPaths(index: ReportIndex): string[] {
  return (['daily', 'weekly', 'monthly'] as const).flatMap((period) => [
    index.current[period].path,
    index.archive[period].path,
  ]);
}

function validateV3ReportsReceipt(
  receipt: V3ReportsValidationReceipt,
  manifest: V3ReportsManifest,
): V3ReportsValidationReceipt {
  assertContract(
    receipt.schema_version === 'reddit_voc_reports_validation_receipt_v3'
      && receipt.status === 'passed_candidate_only'
      && receipt.promotable === true
      && receipt.deterministic_full_byte_replay === true
      && receipt.report_count === manifest.report_count
      && receipt.history_report_count === manifest.history_report_count
      && receipt.business_entry_count === manifest.business_entry_count,
    'V3 报告 embedded validation receipt 未通过消费门禁',
  );
  assertContract(
    receipt.bundle_manifest_sha256 === manifest.lineage_manifest_sha256,
    'V3 报告 receipt 未绑定 lineage candidate manifest',
  );
  assertV3StaticBoundaries(receipt.boundaries, 'V3 报告 receipt ');
  assertContract(
    receipt.comparison_contract_proven === manifest.comparison_contract_proven
      && receipt.comparison_contract_basis === manifest.comparison_contract_basis
      && receipt.completeness_percent === manifest.completeness_percent
      && receipt.data_owner_coverage_attestation_sha256
        === manifest.data_owner_coverage_attestation_sha256,
    'V3 报告 receipt comparison contract 不一致',
  );
  if (receipt.coverage_attestation !== null) {
    assertV3CoverageAttestation(receipt.coverage_attestation, manifest.source_snapshot_id, 'V3 报告 receipt ');
  }
  assertSameJson(receipt.coverage_attestation, manifest.coverage_attestation, 'V3 报告 receipt coverage attestation');
  assertSameJson(receipt.summary, manifest.summary, 'V3 报告 receipt summary');
  assertSha256(receipt.metrics_candidate_manifest_sha256, 'V3 报告 metrics candidate manifest');
  assertSha256(receipt.metrics_input_manifest_sha256, 'V3 报告 metrics input manifest');
  assertSha256(receipt.metrics_validation_receipt_sha256, 'V3 报告 metrics validation receipt');
  return receipt;
}

function validateV3ReportSource(
  source: V3ReportSource,
  manifest: V3ReportsManifest,
  receipt: V3ReportsValidationReceipt,
  label: string,
): void {
  assertContract(source.source_snapshot_id === manifest.source_snapshot_id, `${label}source snapshot 不一致`);
  assertContract(
    source.coverage_attestation_sha256 === manifest.data_owner_coverage_attestation_sha256,
    `${label}coverage attestation SHA 不一致`,
  );
  assertContract(
    source.metrics_candidate_manifest_sha256 === receipt.metrics_candidate_manifest_sha256
      && source.metrics_input_manifest_sha256 === receipt.metrics_input_manifest_sha256
      && source.metrics_validation_receipt_sha256 === receipt.metrics_validation_receipt_sha256,
    `${label}metrics lineage 不一致`,
  );
  assertSha256(source.periodized_metrics_sha256, `${label}periodized metrics`);
}

function validateV3ReportIndex(
  index: V3ReportIndex,
  manifest: V3ReportsManifest,
  receipt: V3ReportsValidationReceipt,
): V3ReportIndex {
  assertContract(index.schema_version === V3_REPORT_INDEX_SCHEMA, 'V3 报告 index schema 不受支持');
  assertContract(index.dataset_version === manifest.dataset_version, 'V3 报告 index 版本不一致');
  assertContract(
    index.fixture_only === false
      && index.archive_policy === 'internal_comparison_storage_not_a_business_entry'
      && index.business_entry_count === manifest.business_entry_count
      && index.current_entry_count === 3
      && index.history_entry_count === manifest.history_report_count
      && index.business_history_index_path === 'business-history-index.json',
    'V3 报告 index 业务入口合同异常',
  );
  assertContract(
    /^\d{4}-\d{2}-\d{2}$/.test(index.as_of_date)
      && index.comparison_contract_proven === manifest.comparison_contract_proven
      && index.comparison_contract_basis === manifest.comparison_contract_basis
      && index.completeness_percent === manifest.completeness_percent
      && index.data_owner_coverage_attestation_sha256
        === manifest.data_owner_coverage_attestation_sha256,
    'V3 报告 index 完整周期合同异常',
  );
  assertSameJson(index.comparison_unavailable_reason_codes, manifest.comparison_unavailable_reason_codes, 'V3 报告 index comparison unavailable reasons');
  if (index.coverage_attestation !== null) {
    assertV3CoverageAttestation(index.coverage_attestation, manifest.source_snapshot_id, 'V3 报告 index ');
  }
  assertSameJson(index.coverage_attestation, manifest.coverage_attestation, 'V3 报告 index coverage attestation');
  assertUniqueExact(Object.keys(index.reports), new Set<ReportPeriod>(['daily', 'weekly', 'monthly']), 'V3 报告 index 周期集合不一致');
  (['daily', 'weekly', 'monthly'] as const).forEach((period) => {
    const entry = index.reports[period];
    assertContract(
      entry.grain === period
        && entry.entry_label === (manifest.comparison_contract_proven ? '最新完整周期' : '最新闭合周期（覆盖未证明）')
        && entry.artifact_path === `current/${period}.json`
        && entry.period.grain === period
        && entry.period.is_complete === true
        && entry.period.start < entry.period.end,
      `V3 ${period} 报告 index 入口异常`,
    );
  });
  validateV3ReportSource(index.source, manifest, receipt, 'V3 报告 index ');
  return index;
}

function validateV3BusinessHistoryIndex(
  historyIndex: V3BusinessHistoryIndex,
  index: V3ReportIndex,
  manifest: V3ReportsManifest,
  receipt: V3ReportsValidationReceipt,
): V3BusinessHistoryIndex {
  assertContract(
    historyIndex.schema_version === 'reddit_voc_business_history_index_v1'
      && historyIndex.dataset_version === manifest.dataset_version
      && historyIndex.as_of_date === index.as_of_date
      && historyIndex.order === 'newest_first'
      && historyIndex.latest_complete_period_excluded === true
      && historyIndex.history_entry_count === manifest.history_report_count
      && historyIndex.total_business_entry_count === manifest.business_entry_count
      && historyIndex.limits.daily === 14
      && historyIndex.limits.weekly === 12
      && historyIndex.limits.monthly === 12,
    'V3 业务历史 index 主合同异常',
  );
  assertSameJson(historyIndex.coverage_attestation, index.coverage_attestation, 'V3 业务历史 coverage attestation');
  assertSameJson(historyIndex.source, index.source, 'V3 业务历史 source');
  assertContract(
    historyIndex.data_owner_coverage_attestation_sha256
      === manifest.data_owner_coverage_attestation_sha256,
    'V3 业务历史 coverage SHA 不一致',
  );
  validateV3ReportSource(historyIndex.source, manifest, receipt, 'V3 业务历史 index ');
  const paths = new Set<string>();
  const periodIds = new Set<string>();
  (['daily', 'weekly', 'monthly'] as const).forEach((grain) => {
    const entries = historyIndex.reports[grain];
    const expectedEntries = manifest.history_report_count > 0 ? historyIndex.limits[grain] : 0;
    assertContract(entries.length === expectedEntries, `V3 ${grain} 历史数量异常`);
    let expectedEnd = index.reports[grain].period.start;
    entries.forEach((entry) => {
      assertContract(
        entry.grain === grain
          && entry.entry_label === (
            manifest.comparison_contract_proven
              ? '历史完整周期'
              : '历史已观测周期（覆盖未证明）'
          )
          && entry.period.grain === grain
          && entry.period.is_complete === true
          && entry.period.end === expectedEnd
          && entry.period.start < entry.period.end
          && /^history\/(daily|weekly|monthly)\/[0-9_-]+\.json$/.test(entry.artifact_path)
          && entry.artifact_path.startsWith(`history/${grain}/`)
          && /^[a-f0-9]{64}$/.test(entry.artifact_sha256)
          && manifest.files[entry.artifact_path]?.sha256 === entry.artifact_sha256
          && !paths.has(entry.artifact_path)
          && !periodIds.has(entry.period.period_id),
        `V3 ${grain} 历史入口不连续或绑定异常`,
      );
      paths.add(entry.artifact_path);
      periodIds.add(entry.period.period_id);
      expectedEnd = entry.period.start;
    });
  });
  assertUniqueExact(
    Object.keys(manifest.files),
    new Set([...V3_REPORT_BOOTSTRAP_PATHS, ...paths]),
    'V3 manifest 与业务历史 index 文件集合不一致',
  );
  return historyIndex;
}

function validateV3CurrentReportBinding(
  report: V3CurrentReport,
  period: ReportPeriod,
  index: V3ReportIndex,
  manifest: V3ReportsManifest,
  receipt: V3ReportsValidationReceipt,
): V3CurrentReport {
  validateV3CurrentReport(report);
  const entry = index.reports[period];
  const expectedCurrentRole = manifest.comparison_contract_proven
    ? 'latest_complete_calendar_period'
    : 'latest_closed_calendar_period_unattested';
  const expectedEntryLabel = manifest.comparison_contract_proven
    ? '最新完整周期'
    : '最新闭合周期（覆盖未证明）';
  assertContract(
    report.artifact_role === expectedCurrentRole
      && report.entry_label === expectedEntryLabel
      && report.grain === period,
    `V3 ${period} 当前报告角色或粒度不一致`,
  );
  assertSameJson(report.period, entry.period, `V3 ${period} 报告周期与 index `);
  assertContract(
    report.data_owner_coverage_attestation_sha256 === manifest.data_owner_coverage_attestation_sha256,
    `V3 ${period} 报告 coverage attestation SHA 不一致`,
  );
  assertSameJson(report.coverage_attestation, manifest.coverage_attestation, `V3 ${period} 报告 coverage attestation`);
  validateV3ReportSource(report.source, manifest, receipt, `V3 ${period} 报告 `);
  assertSameJson(report.source, index.source, `V3 ${period} 报告 source 与 index `);
  return report;
}

function validateV3ArchiveReport(
  report: V3ArchiveReport,
  period: ReportPeriod,
  index: V3ReportIndex,
  manifest: V3ReportsManifest,
  receipt: V3ReportsValidationReceipt,
): void {
  assertContract(
    report.schema_version === V3_REPORT_SCHEMA
      && report.artifact_role === 'internal_comparison_archive'
      && report.business_entry_visible === false
      && report.grain === period
      && report.fixture_only === false
      && report.comparison_contract_proven === manifest.comparison_contract_proven
      && report.comparison_contract_basis === manifest.comparison_contract_basis
      && report.completeness_percent === manifest.completeness_percent
      && report.data_owner_coverage_attestation_sha256
        === manifest.data_owner_coverage_attestation_sha256,
    `V3 ${period} archive 业务可见性或完整性合同异常`,
  );
  assertV3StaticBoundaries(report.boundaries, `V3 ${period} archive `);
  assertSameJson(report.coverage_attestation, manifest.coverage_attestation, `V3 ${period} archive coverage attestation`);
  validateV3ReportSource(report.source, manifest, receipt, `V3 ${period} archive `);
  assertSameJson(report.source, index.source, `V3 ${period} archive source 与 index `);
}

export function validateV3ReportsSnapshot(
  manifest: V3ReportsManifest,
  receipt: V3ReportsValidationReceipt,
  index: V3ReportIndex,
  historyIndex: V3BusinessHistoryIndex,
  currentReports: Record<ReportPeriod, V3CurrentReport>,
  archiveReports: Record<ReportPeriod, V3ArchiveReport>,
  release: CurrentRelease,
): V3RedditReportsSnapshot {
  validateV3ReportsManifestDispatch(manifest, release);
  validateV3ReportsReceipt(receipt, manifest);
  validateV3ReportIndex(index, manifest, receipt);
  validateV3BusinessHistoryIndex(historyIndex, index, manifest, receipt);
  (['daily', 'weekly', 'monthly'] as const).forEach((period) => {
    validateV3CurrentReportBinding(currentReports[period], period, index, manifest, receipt);
    validateV3ArchiveReport(archiveReports[period], period, index, manifest, receipt);
  });
  return { release, manifest, index, historyIndex, current: currentReports };
}

export function validateReportsSnapshot(
  manifest: ReportManifest,
  index: ReportIndex,
  reportsByPath: Record<string, RedditReport>,
  release: CurrentRelease,
): RedditReportsSnapshot {
  validateManifest(manifest, release);
  validateIndex(index, manifest);
  assertUniqueExact(Object.keys(reportsByPath), new Set(reportPaths(index)), '已加载报告文件集合不一致');
  const current = {} as Record<ReportPeriod, RedditReport>;
  const archive = {} as Record<ReportPeriod, RedditReport>;
  (['daily', 'weekly', 'monthly'] as const).forEach((period) => {
    current[period] = validateReport(reportsByPath[index.current[period].path], index.current[period], manifest);
    archive[period] = validateReport(reportsByPath[index.archive[period].path], index.archive[period], manifest);
  });
  return { release, manifest, index, current, archive };
}

async function sha256Text(raw: string): Promise<string> {
  assertContract(globalThis.crypto?.subtle, '当前浏览器不支持报告文件完整性校验');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function fetchVerifiedJson<T>(
  basePath: string,
  filename: string,
  expectedIntegrity?: FileIntegrity,
  forceReload = false,
): Promise<T> {
  const response = await fetch(`${basePath}/${filename}`, {
    cache: forceReload ? 'reload' : 'no-cache',
  });
  if (!response.ok) {
    throw new ReportsContractError(`真实报告文件加载失败：${filename}（HTTP ${response.status}）`);
  }
  const raw = await response.text();
  if (expectedIntegrity) {
    assertContract(
      new TextEncoder().encode(raw).byteLength === expectedIntegrity.bytes,
      `真实报告文件 bytes 不一致：${filename}`,
    );
    assertContract(
      (await sha256Text(raw)) === expectedIntegrity.sha256,
      `真实报告文件 SHA-256 不一致：${filename}`,
    );
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new ReportsContractError(`真实报告文件不是有效 JSON：${filename}`);
  }
}

async function loadV3ReportsUncached(
  manifest: V3ReportsManifest,
  release: CurrentRelease,
  forceReload: boolean,
): Promise<V3RedditReportsSnapshot> {
  validateV3ReportsManifestDispatch(manifest, release);
  const basePath = getReleaseDatasetBasePath(release, 'reports');
  const paths = [...V3_REPORT_BOOTSTRAP_PATHS];
  const values = await Promise.all(paths.map((path) =>
    fetchVerifiedJson<unknown>(basePath, path, manifest.files[path], forceReload),
  ));
  const byPath = Object.fromEntries(paths.map((path, index) => [path, values[index]]));
  const current = Object.fromEntries((['daily', 'weekly', 'monthly'] as const).map((period) => [
    period,
    byPath[`current/${period}.json`] as V3CurrentReport,
  ])) as Record<ReportPeriod, V3CurrentReport>;
  const archive = Object.fromEntries((['daily', 'weekly', 'monthly'] as const).map((period) => [
    period,
    byPath[`archive/${period}.json`] as V3ArchiveReport,
  ])) as Record<ReportPeriod, V3ArchiveReport>;
  return validateV3ReportsSnapshot(
    manifest,
    byPath['validation-receipt.json'] as V3ReportsValidationReceipt,
    byPath['report-index.json'] as V3ReportIndex,
    byPath['business-history-index.json'] as V3BusinessHistoryIndex,
    current,
    archive,
    release,
  );
}

async function loadReportsUncached(forceReload = false): Promise<AnyRedditReportsSnapshot> {
  const release = await loadCurrentRelease();
  const manifestValue = await fetchVerifiedReleaseManifest<unknown>(release, 'reports', forceReload);
  if (isV3ReportsManifest(manifestValue)) {
    return loadV3ReportsUncached(manifestValue, release, forceReload);
  }
  if (isV3ReportsCandidateManifest(manifestValue)) {
    throw new ReportsContractError('V3 报告 candidate 尚未通过 public wrapper 独立验证，禁止消费且不回退 V1/V2');
  }
  const manifest = manifestValue as ReportManifest;
  validateManifest(manifest, release);
  const basePath = getReleaseDatasetBasePath(release, 'reports');
  const index = await fetchVerifiedJson<ReportIndex>(
    basePath,
    'report-index.json',
    manifest.files['report-index.json'],
    forceReload,
  );
  validateIndex(index, manifest);
  const paths = reportPaths(index);
  const reports = await Promise.all(paths.map((path) =>
    fetchVerifiedJson<RedditReport>(basePath, path, manifest.files[path], forceReload),
  ));
  const reportsByPath = Object.fromEntries(
    paths.map((path, indexPosition) => [path, reports[indexPosition]]),
  );
  return validateReportsSnapshot(manifest, index, reportsByPath, release);
}

export function loadRedditReports(): Promise<AnyRedditReportsSnapshot> {
  return loadCurrentRelease().then((release) => (
    reportsCache.get(releaseGenerationKey(release), () => loadReportsUncached())
  ));
}

export function reloadRedditReports(): Promise<AnyRedditReportsSnapshot> {
  // An explicit reload must both drop the historical promises and force the
  // release-keyed cache to re-fetch, otherwise the button appears to do nothing
  // until the pointer TTL expires.
  historicalReportPromises.clear();
  reportsCache.clear();
  return loadCurrentRelease().then((release) => (
    reportsCache.get(releaseGenerationKey(release), () => loadReportsUncached(true))
  ));
}

export function loadV3HistoricalReport(
  snapshot: V3RedditReportsSnapshot,
  grain: ReportPeriod,
  periodId: string,
): Promise<V3CurrentReport> {
  assertContract(Boolean(snapshot.historyIndex), '当前报告数据版本未提供业务历史索引');
  const entry = snapshot.historyIndex!.reports[grain].find(
    (candidate) => candidate.period.period_id === periodId,
  );
  assertContract(Boolean(entry), '该历史周期不属于当前报告数据版本');
  const cacheKey = `${snapshot.manifest.dataset_version}:${entry!.artifact_path}`;
  const cached = historicalReportPromises.get(cacheKey);
  if (cached) return cached;
  const promise = fetchVerifiedJson<V3CurrentReport>(
    getReleaseDatasetBasePath(snapshot.release, 'reports'),
    entry!.artifact_path,
    snapshot.manifest.files[entry!.artifact_path],
  ).then((report) => {
    validateV3CurrentReport(report);
    assertContract(
      report.artifact_role === (
        snapshot.manifest.comparison_contract_proven
          ? 'historical_complete_calendar_period'
          : 'historical_observed_calendar_period_unattested'
      )
        && report.business_entry_visible === true
        && report.grain === grain,
      'V3 历史报告角色或粒度异常',
    );
    assertSameJson(report.period, entry!.period, 'V3 历史报告周期与 index ');
    assertSameJson(report.source, snapshot.index.source, 'V3 历史报告 source 与 index ');
    assertSameJson(
      report.coverage_attestation,
      snapshot.index.coverage_attestation,
      'V3 历史报告 coverage attestation',
    );
    return report;
  }).catch((error) => {
    historicalReportPromises.delete(cacheKey);
    throw error;
  });
  historicalReportPromises.set(cacheKey, promise);
  return promise;
}

export function resetReportsCacheForTests(): void {
  reportsCache.clear();
  historicalReportPromises.clear();
}
