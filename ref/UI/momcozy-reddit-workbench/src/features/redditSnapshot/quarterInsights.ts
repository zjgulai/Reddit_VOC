import { getReleaseDatasetBasePath, loadCurrentRelease, releaseGenerationKey } from './release';
import { ReleaseKeyedCache } from './releaseKeyedCache';

export const QUARTER_INSIGHTS_PUBLIC_BASE_PATH = '/data/reddit-voc/reddit_voc_quarter_insights_20260719_center_refresh_003';
export const QUARTER_INSIGHTS_PUBLIC_MANIFEST_SHA256 = 'fd27b784e5ad31219bfc8e62a1b5ca1e1284c839227d95fef8cb2eb28c991867';
export const QUARTER_INSIGHTS_PUBLIC_MANIFEST_SCHEMA = 'reddit_voc_quarter_insights_public_manifest_v1';
export const QUARTER_INSIGHTS_PUBLIC_SCHEMA = 'reddit_voc_quarter_insights_public_v1';
export const QUARTER_INSIGHTS_DATASET_VERSION = 'reddit_voc_quarter_insights_20260719_center_refresh_003';
const QUARTER_INSIGHTS_DATASET_VERSION_PATTERN = /^reddit_voc_quarter_insights_[a-z0-9_]+$/;

export interface PublicQuarterInsightsBoundaries {
  author_fields_excluded: true;
  automation_comment_count_corrected_from_utc_boundary_undercount: true;
  automation_comments_are_not_brand_attribution: true;
  brand_bot_attribution_confirmed: false;
  case_references_are_method_only: true;
  counts_are_content_entities_not_users: true;
  database_write: false;
  deploy: false;
  live_send: false;
  market_share_supported: false;
  population_share_supported: false;
  private_paths_excluded: true;
  production_unchanged: true;
  provider_call: false;
  quarter_moderation_claim_evidence_is_allowlisted_not_total: true;
  rankings_are_non_exclusive: true;
  remote_write: false;
  source_text_excluded: true;
}

export interface PublicQuarterInsightsPeriod {
  anchor_date: string;
  days: 90;
  end_date: string;
  inclusive: true;
  start_date: string;
  timezone: 'Asia/Shanghai';
}

export interface PublicQuarterInsightsSource {
  canonical_dataset_id: string;
  canonical_manifest_sha256: string;
  canonical_validation_receipt_sha256: string;
  casebook_public_manifest_sha256: string;
  casebook_public_projection_id: string;
  governed_signal_manifest_sha256: string;
  governed_signal_snapshot_id: string;
  governed_signal_validation_receipt_sha256: string;
  persona_manifest_sha256: string;
  persona_snapshot_id: string;
  persona_validation_receipt_sha256: string;
  product_ledger_sha256: string;
  source_snapshot_id: string;
  voc_dataset_id: string;
  voc_manifest_sha256: string;
  voc_validation_receipt_sha256: string;
}

export interface QuarterInsightRanking {
  count: number;
  id: string;
  label: string;
}

export interface QuarterInsightEvidence {
  comment_id: string | null;
  post_id: string;
  reason: string;
}

export type QuarterPersonaCohortId =
  | 'scenario_adapter'
  | 'product_evaluator'
  | 'purchase_decision'
  | 'competitor_comparer'
  | 'recommendation_expression'
  | 'service_support_seeker'
  | 'operations_troubleshooter'
  | 'fit_output_optimizer';

export interface QuarterDashboardMetric {
  classified_vocs: number;
  comment_context_vocs: number;
  negative_rate: number | null;
  negative_vocs: number;
  post_vocs: number;
  total_vocs: number;
}

export interface QuarterDashboardBucket extends QuarterDashboardMetric {
  bucket: string;
}

export interface QuarterDashboardWindow {
  bucket_grain: 'day' | 'month';
  buckets: QuarterDashboardBucket[];
  days: 7 | 30 | 183;
  end_date: string;
  id: 'rolling_7_days' | 'rolling_30_days' | 'rolling_183_days';
  momcozy: QuarterDashboardMetric;
  start_date: string;
  top_competitor: {
    id: string;
    label: string;
    voc_count: number;
  };
}

export interface PublicQuarterInsightsData {
  boundaries: PublicQuarterInsightsBoundaries;
  case_references: Record<'pain' | 'reputation' | 'new_product' | 'geo', {
    id: string | null;
    role: 'historical_governance_method_reference' | 'no_approved_local_case';
  }>;
  counts: {
    analysis_comment_context_vocs: number;
    analysis_post_vocs: number;
    canonical_posts: number;
    competitor_union_vocs: number;
    linked_comment_context_vocs: number;
    momcozy: {
      comment_context_vocs: number;
      post_vocs: number;
      sentiment: {
        classified: number;
        missing: number;
        negative: number;
        negative_rate: number;
        negative_rate_denominator: 'classified';
        negative_rate_unit: 'percent';
        neutral: number;
        positive: number;
      };
      total_vocs: number;
    };
    momcozy_competitor_overlap_vocs: number;
    periodic_comments: number;
    unresolved_parent_comments: number;
  };
  dashboard_windows: QuarterDashboardWindow[];
  dataset_version: string;
  generated_at_utc: string;
  period: PublicQuarterInsightsPeriod;
  personas: {
    category_context_assignment_count: number;
    category_context_unique_entities: number;
    cohorts: Array<{ assignment_count: number; cohort_id: QuarterPersonaCohortId }>;
    date_basis: 'content_entity_event_date';
    main_assignment_count: number;
    main_assignment_ids: string[];
    main_scope: ['momcozy_direct', 'momcozy_multi'];
    main_unique_entities: number;
  };
  schema_version: typeof QUARTER_INSIGHTS_PUBLIC_SCHEMA;
  source: PublicQuarterInsightsSource;
  themes: {
    geo: {
      comparison_decision_posts: number;
      evidence: QuarterInsightEvidence[];
      method: string;
      rankings: QuarterInsightRanking[];
    };
    new_product: {
      category_rankings: QuarterInsightRanking[];
      evidence: QuarterInsightEvidence[];
      exact_spu_rankings: QuarterInsightRanking[];
      family_only_ids: string[];
      family_rankings: QuarterInsightRanking[];
      method: string;
      product_rankings: QuarterInsightRanking[];
    };
    pain: {
      evidence: QuarterInsightEvidence[];
      method: string;
      rankings: QuarterInsightRanking[];
    };
    reputation: {
      automation_comments: number;
      evidence: QuarterInsightEvidence[];
      high_severity_vocs: number;
      method: string;
      negative_vocs: number;
      quarter_moderation_claim_evidence_count: number;
      rankings: QuarterInsightRanking[];
    };
  };
}

export interface PublicQuarterInsightsManifest {
  boundaries: PublicQuarterInsightsBoundaries;
  dataset_version: string;
  files: {
    'quarter-insights.json': {
      bytes: number;
      media_type: 'application/json';
      sha256: string;
    };
  };
  generated_at_utc: string;
  period: PublicQuarterInsightsPeriod;
  schema_version: typeof QUARTER_INSIGHTS_PUBLIC_MANIFEST_SCHEMA;
  source: PublicQuarterInsightsSource;
  status: 'ready';
}

export interface RedditPublicQuarterInsights {
  data: PublicQuarterInsightsData;
  manifest: PublicQuarterInsightsManifest;
}

export type RedditQuarterInsightsData = PublicQuarterInsightsData;

export interface LoadRedditQuarterInsightsOptions {
  basePath?: string;
  expectedManifestSha256?: string;
}

export class QuarterInsightsContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'QuarterInsightsContractError';
  }
}

const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const PRIVATE_HOME_PATH_PATTERN = /[/\\]Users[/\\]/i;
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const POST_ID_PATTERN = /^[a-z0-9]+$/;
const COMMENT_ID_PATTERN = /^t1_[a-z0-9]+$/;
const BOUNDARY_KEYS = [
  'author_fields_excluded',
  'automation_comment_count_corrected_from_utc_boundary_undercount',
  'automation_comments_are_not_brand_attribution',
  'brand_bot_attribution_confirmed',
  'case_references_are_method_only',
  'counts_are_content_entities_not_users',
  'database_write',
  'deploy',
  'live_send',
  'market_share_supported',
  'population_share_supported',
  'private_paths_excluded',
  'production_unchanged',
  'provider_call',
  'quarter_moderation_claim_evidence_is_allowlisted_not_total',
  'rankings_are_non_exclusive',
  'remote_write',
  'source_text_excluded',
] as const;
const SOURCE_KEYS = [
  'canonical_dataset_id',
  'canonical_manifest_sha256',
  'canonical_validation_receipt_sha256',
  'casebook_public_manifest_sha256',
  'casebook_public_projection_id',
  'governed_signal_manifest_sha256',
  'governed_signal_snapshot_id',
  'governed_signal_validation_receipt_sha256',
  'persona_manifest_sha256',
  'persona_snapshot_id',
  'persona_validation_receipt_sha256',
  'product_ledger_sha256',
  'source_snapshot_id',
  'voc_dataset_id',
  'voc_manifest_sha256',
  'voc_validation_receipt_sha256',
] as const;
const COHORT_ORDER: QuarterPersonaCohortId[] = [
  'scenario_adapter',
  'product_evaluator',
  'purchase_decision',
  'competitor_comparer',
  'recommendation_expression',
  'service_support_seeker',
  'operations_troubleshooter',
  'fit_output_optimizer',
];
const FORBIDDEN_KEYS = new Set([
  'author', 'authors', 'body', 'content', 'entity_id', 'permalink', 'source_path',
  'source_text', 'text', 'title', 'url', 'username',
]);

const quarterInsightsCache = new ReleaseKeyedCache<RedditPublicQuarterInsights>();

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new QuarterInsightsContractError(message);
}

function record(value: unknown, label: string): Record<string, unknown> {
  assertContract(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `${label}必须是对象`);
  return value as Record<string, unknown>;
}

function exactKeys(value: unknown, expected: readonly string[], label: string): Record<string, unknown> {
  const result = record(value, label);
  const actual = Object.keys(result).sort();
  const wanted = [...expected].sort();
  assertContract(actual.length === wanted.length && actual.every((key, index) => key === wanted[index]), `${label}字段合同不一致`);
  return result;
}

function nonEmptyString(value: unknown, label: string): string {
  assertContract(typeof value === 'string' && value.trim() !== '', `${label}必须是非空字符串`);
  return value;
}

function nonNegativeInteger(value: unknown, label: string): number {
  assertContract(Number.isInteger(value) && Number(value) >= 0, `${label}必须是非负整数`);
  return Number(value);
}

function sha256Value(value: unknown, label: string): string {
  const result = nonEmptyString(value, label);
  assertContract(SHA256_PATTERN.test(result), `${label}必须是SHA-256`);
  return result;
}

function scanForPrivateContent(value: unknown, label = 'quarter insights'): void {
  if (Array.isArray(value)) {
    value.forEach((item) => scanForPrivateContent(item, label));
    return;
  }
  if (value && typeof value === 'object') {
    Object.entries(value as Record<string, unknown>).forEach(([key, nested]) => {
      assertContract(!FORBIDDEN_KEYS.has(key.toLowerCase()), `${label}包含隐私或原文字段：${key}`);
      scanForPrivateContent(nested, label);
    });
    return;
  }
  if (typeof value === 'string') {
    assertContract(
      !value.includes('http://')
        && !value.includes('https://')
        && !value.includes('file://')
        && !PRIVATE_HOME_PATH_PATTERN.test(value)
        && !value.includes('tmp/'),
      `${label}包含外链或私有路径`,
    );
  }
}

function validateBoundaries(value: unknown): PublicQuarterInsightsBoundaries {
  const item = exactKeys(value, BOUNDARY_KEYS, 'quarter insights boundaries');
  assertContract(
    item.author_fields_excluded === true
      && item.automation_comment_count_corrected_from_utc_boundary_undercount === true
      && item.automation_comments_are_not_brand_attribution === true
      && item.brand_bot_attribution_confirmed === false
      && item.case_references_are_method_only === true
      && item.counts_are_content_entities_not_users === true
      && item.database_write === false
      && item.deploy === false
      && item.live_send === false
      && item.market_share_supported === false
      && item.population_share_supported === false
      && item.private_paths_excluded === true
      && item.production_unchanged === true
      && item.provider_call === false
      && item.quarter_moderation_claim_evidence_is_allowlisted_not_total === true
      && item.rankings_are_non_exclusive === true
      && item.remote_write === false
      && item.source_text_excluded === true,
    'quarter insights side-effect或解释边界不安全',
  );
  return item as unknown as PublicQuarterInsightsBoundaries;
}

function validatePeriod(value: unknown): PublicQuarterInsightsPeriod {
  const item = exactKeys(value, ['anchor_date', 'days', 'end_date', 'inclusive', 'start_date', 'timezone'], 'quarter insights period');
  for (const field of ['anchor_date', 'start_date', 'end_date'] as const) {
    assertContract(typeof item[field] === 'string' && ISO_DATE_PATTERN.test(item[field] as string), `quarter insights period.${field}无效`);
  }
  assertContract(
    item.days === 90
      && item.inclusive === true
      && item.timezone === 'Asia/Shanghai'
      && item.anchor_date === item.end_date,
    'quarter insights必须绑定最近完整90日业务窗口',
  );
  const start = Date.parse(`${item.start_date}T00:00:00Z`);
  const end = Date.parse(`${item.end_date}T00:00:00Z`);
  assertContract((end - start) / 86_400_000 + 1 === item.days, 'quarter insights日期与天数不守恒');
  return item as unknown as PublicQuarterInsightsPeriod;
}

function validateSource(value: unknown): PublicQuarterInsightsSource {
  const item = exactKeys(value, SOURCE_KEYS, 'quarter insights source');
  SOURCE_KEYS.forEach((key) => {
    if (key.endsWith('_sha256')) sha256Value(item[key], `quarter insights source.${key}`);
    else nonEmptyString(item[key], `quarter insights source.${key}`);
  });
  return item as unknown as PublicQuarterInsightsSource;
}

function validateRankings(value: unknown, label: string): QuarterInsightRanking[] {
  assertContract(Array.isArray(value) && value.length > 0, `${label}必须是非空数组`);
  const ids = new Set<string>();
  return value.map((row, index) => {
    const item = exactKeys(row, ['count', 'id', 'label'], `${label}[${index}]`);
    const id = nonEmptyString(item.id, `${label}[${index}].id`);
    assertContract(!ids.has(id), `${label}的id必须唯一`);
    ids.add(id);
    return {
      count: nonNegativeInteger(item.count, `${label}[${index}].count`),
      id,
      label: nonEmptyString(item.label, `${label}[${index}].label`),
    };
  });
}

function validateEvidence(value: unknown, label: string): QuarterInsightEvidence[] {
  assertContract(Array.isArray(value) && value.length > 0, `${label}必须是非空数组`);
  return value.map((row, index) => {
    const item = exactKeys(row, ['comment_id', 'post_id', 'reason'], `${label}[${index}]`);
    const postId = nonEmptyString(item.post_id, `${label}[${index}].post_id`);
    assertContract(POST_ID_PATTERN.test(postId), `${label}[${index}].post_id无效`);
    assertContract(item.comment_id === null || (typeof item.comment_id === 'string' && COMMENT_ID_PATTERN.test(item.comment_id)), `${label}[${index}].comment_id无效`);
    return {
      comment_id: item.comment_id as string | null,
      post_id: postId,
      reason: nonEmptyString(item.reason, `${label}[${index}].reason`),
    };
  });
}

function roundedRate(negative: number, classified: number): number | null {
  return classified === 0 ? null : Math.round((negative * 10_000) / classified) / 100;
}

function validateDashboardMetric(value: unknown, label: string): QuarterDashboardMetric {
  const item = exactKeys(
    value,
    ['classified_vocs', 'comment_context_vocs', 'negative_rate', 'negative_vocs', 'post_vocs', 'total_vocs'],
    label,
  );
  const metric = {
    classified_vocs: nonNegativeInteger(item.classified_vocs, `${label}.classified_vocs`),
    comment_context_vocs: nonNegativeInteger(item.comment_context_vocs, `${label}.comment_context_vocs`),
    negative_rate: item.negative_rate as number | null,
    negative_vocs: nonNegativeInteger(item.negative_vocs, `${label}.negative_vocs`),
    post_vocs: nonNegativeInteger(item.post_vocs, `${label}.post_vocs`),
    total_vocs: nonNegativeInteger(item.total_vocs, `${label}.total_vocs`),
  };
  assertContract(metric.total_vocs === metric.post_vocs + metric.comment_context_vocs, `${label}帖子与评论VOC不守恒`);
  assertContract(metric.negative_vocs <= metric.classified_vocs && metric.classified_vocs <= metric.total_vocs, `${label}情感计数不守恒`);
  assertContract(metric.negative_rate === roundedRate(metric.negative_vocs, metric.classified_vocs), `${label}负面占比公式不一致`);
  return metric;
}

function validateDashboardWindows(
  value: unknown,
  period: PublicQuarterInsightsPeriod,
): QuarterDashboardWindow[] {
  assertContract(Array.isArray(value) && value.length === 3, 'quarter insights必须有三个概览时间窗口');
  const expected = [
    { id: 'rolling_7_days', days: 7, grain: 'day' },
    { id: 'rolling_30_days', days: 30, grain: 'day' },
    { id: 'rolling_183_days', days: 183, grain: 'month' },
  ] as const;
  return value.map((row, index) => {
    const item = exactKeys(row, ['bucket_grain', 'buckets', 'days', 'end_date', 'id', 'momcozy', 'start_date', 'top_competitor'], `dashboard_windows[${index}]`);
    const wanted = expected[index];
    const expectedStart = new Date(`${period.end_date}T00:00:00Z`);
    expectedStart.setUTCDate(expectedStart.getUTCDate() - wanted.days + 1);
    const expectedStartDate = expectedStart.toISOString().slice(0, 10);
    assertContract(
      item.id === wanted.id
        && item.days === wanted.days
        && item.start_date === expectedStartDate
        && item.end_date === period.end_date
        && item.bucket_grain === wanted.grain,
      `dashboard_windows[${index}]时间合同不一致`,
    );
    const momcozy = validateDashboardMetric(item.momcozy, `dashboard_windows[${index}].momcozy`);
    const top = exactKeys(item.top_competitor, ['id', 'label', 'voc_count'], `dashboard_windows[${index}].top_competitor`);
    assertContract(Array.isArray(item.buckets) && item.buckets.length > 0, `dashboard_windows[${index}].buckets不能为空`);
    const buckets = item.buckets.map((bucket, bucketIndex) => {
      const bucketItem = exactKeys(
        bucket,
        ['bucket', 'classified_vocs', 'comment_context_vocs', 'negative_rate', 'negative_vocs', 'post_vocs', 'total_vocs'],
        `dashboard_windows[${index}].buckets[${bucketIndex}]`,
      );
      const metric = validateDashboardMetric(
        {
          classified_vocs: bucketItem.classified_vocs,
          comment_context_vocs: bucketItem.comment_context_vocs,
          negative_rate: bucketItem.negative_rate,
          negative_vocs: bucketItem.negative_vocs,
          post_vocs: bucketItem.post_vocs,
          total_vocs: bucketItem.total_vocs,
        },
        `dashboard_windows[${index}].buckets[${bucketIndex}]`,
      );
      const bucketLabel = nonEmptyString(bucketItem.bucket, `dashboard_windows[${index}].buckets[${bucketIndex}].bucket`);
      assertContract(wanted.grain === 'day' ? ISO_DATE_PATTERN.test(bucketLabel) : /^\d{4}-\d{2}$/.test(bucketLabel), `dashboard_windows[${index}] bucket日期无效`);
      return { bucket: bucketLabel, ...metric };
    });
    assertContract(buckets.reduce((sum, bucket) => sum + bucket.total_vocs, 0) === momcozy.total_vocs, `dashboard_windows[${index}]桶合计与摘要不一致`);
    return {
      bucket_grain: item.bucket_grain,
      buckets,
      days: item.days,
      end_date: item.end_date,
      id: item.id,
      momcozy,
      start_date: item.start_date,
      top_competitor: {
        id: nonEmptyString(top.id, `dashboard_windows[${index}].top_competitor.id`),
        label: nonEmptyString(top.label, `dashboard_windows[${index}].top_competitor.label`),
        voc_count: nonNegativeInteger(top.voc_count, `dashboard_windows[${index}].top_competitor.voc_count`),
      },
    } as QuarterDashboardWindow;
  });
}

export function validatePublicQuarterInsightsManifest(value: unknown): PublicQuarterInsightsManifest {
  scanForPrivateContent(value, 'quarter insights manifest');
  const item = exactKeys(value, ['boundaries', 'dataset_version', 'files', 'generated_at_utc', 'period', 'schema_version', 'source', 'status'], 'quarter insights manifest');
  const boundaries = validateBoundaries(item.boundaries);
  const period = validatePeriod(item.period);
  const source = validateSource(item.source);
  const files = exactKeys(item.files, ['quarter-insights.json'], 'quarter insights manifest.files');
  const file = exactKeys(files['quarter-insights.json'], ['bytes', 'media_type', 'sha256'], 'quarter insights manifest.files.quarter-insights.json');
  assertContract(
    item.schema_version === QUARTER_INSIGHTS_PUBLIC_MANIFEST_SCHEMA
      && typeof item.dataset_version === 'string'
      && QUARTER_INSIGHTS_DATASET_VERSION_PATTERN.test(item.dataset_version)
      && typeof item.generated_at_utc === 'string'
      && /(?:Z|\+00:00)$/.test(item.generated_at_utc)
      && Number.isFinite(Date.parse(item.generated_at_utc))
      && item.status === 'ready'
      && Number.isInteger(file.bytes) && Number(file.bytes) > 0
      && file.media_type === 'application/json',
    'quarter insights manifest身份或文件合同不一致',
  );
  sha256Value(file.sha256, 'quarter insights data hash');
  return { ...item, boundaries, period, source } as unknown as PublicQuarterInsightsManifest;
}

export function validatePublicQuarterInsightsData(value: unknown): PublicQuarterInsightsData {
  scanForPrivateContent(value);
  const item = exactKeys(
    value,
    ['boundaries', 'case_references', 'counts', 'dashboard_windows', 'dataset_version', 'generated_at_utc', 'period', 'personas', 'schema_version', 'source', 'themes'],
    'quarter insights data',
  );
  const boundaries = validateBoundaries(item.boundaries);
  const period = validatePeriod(item.period);
  const source = validateSource(item.source);
  assertContract(
    item.schema_version === QUARTER_INSIGHTS_PUBLIC_SCHEMA
      && typeof item.dataset_version === 'string'
      && QUARTER_INSIGHTS_DATASET_VERSION_PATTERN.test(item.dataset_version)
      && typeof item.generated_at_utc === 'string'
      && /(?:Z|\+00:00)$/.test(item.generated_at_utc)
      && Number.isFinite(Date.parse(item.generated_at_utc)),
    'quarter insights data身份不一致',
  );

  const counts = exactKeys(
    item.counts,
    ['analysis_comment_context_vocs', 'analysis_post_vocs', 'canonical_posts', 'competitor_union_vocs', 'linked_comment_context_vocs', 'momcozy', 'momcozy_competitor_overlap_vocs', 'periodic_comments', 'unresolved_parent_comments'],
    'quarter insights counts',
  );
  const numericCounts = Object.fromEntries(
    Object.entries(counts)
      .filter(([key]) => key !== 'momcozy')
      .map(([key, count]) => [key, nonNegativeInteger(count, `quarter insights counts.${key}`)]),
  ) as Record<string, number>;
  assertContract(numericCounts.canonical_posts >= numericCounts.analysis_post_vocs, '季度帖子分析池不得大于观测帖子');
  assertContract(numericCounts.analysis_comment_context_vocs === numericCounts.linked_comment_context_vocs, '季度评论分析池与已关联评论不一致');
  assertContract(numericCounts.periodic_comments === numericCounts.linked_comment_context_vocs + numericCounts.unresolved_parent_comments, '季度评论总量不守恒');
  const momcozy = exactKeys(counts.momcozy, ['comment_context_vocs', 'post_vocs', 'sentiment', 'total_vocs'], 'quarter insights counts.momcozy');
  const momcozyPost = nonNegativeInteger(momcozy.post_vocs, 'quarter insights counts.momcozy.post_vocs');
  const momcozyComments = nonNegativeInteger(momcozy.comment_context_vocs, 'quarter insights counts.momcozy.comment_context_vocs');
  const momcozyTotal = nonNegativeInteger(momcozy.total_vocs, 'quarter insights counts.momcozy.total_vocs');
  assertContract(momcozyTotal === momcozyPost + momcozyComments, 'Momcozy帖子与评论VOC不守恒');
  const sentiment = exactKeys(momcozy.sentiment, ['classified', 'missing', 'negative', 'negative_rate', 'negative_rate_denominator', 'negative_rate_unit', 'neutral', 'positive'], 'quarter insights counts.momcozy.sentiment');
  const positive = nonNegativeInteger(sentiment.positive, 'quarter insights sentiment.positive');
  const neutral = nonNegativeInteger(sentiment.neutral, 'quarter insights sentiment.neutral');
  const negative = nonNegativeInteger(sentiment.negative, 'quarter insights sentiment.negative');
  const missing = nonNegativeInteger(sentiment.missing, 'quarter insights sentiment.missing');
  const classified = nonNegativeInteger(sentiment.classified, 'quarter insights sentiment.classified');
  assertContract(classified === positive + neutral + negative && momcozyTotal === classified + missing, 'Momcozy情感计数不守恒');
  assertContract(
    sentiment.negative_rate_denominator === 'classified'
      && sentiment.negative_rate_unit === 'percent'
      && sentiment.negative_rate === roundedRate(negative, classified),
    'Momcozy负面占比口径不一致',
  );
  assertContract(numericCounts.momcozy_competitor_overlap_vocs <= Math.min(momcozyTotal, numericCounts.competitor_union_vocs), '品牌与竞品重叠计数越界');

  const personas = exactKeys(item.personas, ['category_context_assignment_count', 'category_context_unique_entities', 'cohorts', 'date_basis', 'main_assignment_count', 'main_assignment_ids', 'main_scope', 'main_unique_entities'], 'quarter insights personas');
  const mainCount = nonNegativeInteger(personas.main_assignment_count, 'quarter insights personas.main_assignment_count');
  const mainUnique = nonNegativeInteger(personas.main_unique_entities, 'quarter insights personas.main_unique_entities');
  const categoryCount = nonNegativeInteger(personas.category_context_assignment_count, 'quarter insights personas.category_context_assignment_count');
  const categoryUnique = nonNegativeInteger(personas.category_context_unique_entities, 'quarter insights personas.category_context_unique_entities');
  assertContract(mainUnique <= mainCount && categoryUnique <= categoryCount, '画像唯一内容实体数不得大于赋值数');
  assertContract(personas.date_basis === 'content_entity_event_date', '画像必须按内容实体自身事件日期筛选');
  assertContract(Array.isArray(personas.main_scope) && personas.main_scope.join(',') === 'momcozy_direct,momcozy_multi', '画像主范围不一致');
  assertContract(Array.isArray(personas.main_assignment_ids), '画像assignment allowlist必须是数组');
  const assignmentIds = personas.main_assignment_ids.map((value, index) => sha256Value(value, `quarter insights personas.main_assignment_ids[${index}]`));
  assertContract(assignmentIds.length === mainCount && new Set(assignmentIds).size === mainCount, '画像assignment数量或唯一性不一致');
  assertContract(assignmentIds.every((value, index) => index === 0 || assignmentIds[index - 1] < value), '画像assignment allowlist必须严格排序');
  assertContract(Array.isArray(personas.cohorts) && personas.cohorts.length === COHORT_ORDER.length, '画像cohort不完整');
  const cohorts = personas.cohorts.map((row, index) => {
    const cohort = exactKeys(row, ['assignment_count', 'cohort_id'], `quarter insights personas.cohorts[${index}]`);
    assertContract(cohort.cohort_id === COHORT_ORDER[index], '画像cohort顺序不一致');
    return {
      assignment_count: nonNegativeInteger(cohort.assignment_count, `quarter insights personas.cohorts[${index}].assignment_count`),
      cohort_id: cohort.cohort_id as QuarterPersonaCohortId,
    };
  });
  assertContract(cohorts.reduce((sum, cohort) => sum + cohort.assignment_count, 0) === mainCount, '画像cohort赋值数与主赋值数不守恒');

  const themes = exactKeys(item.themes, ['geo', 'new_product', 'pain', 'reputation'], 'quarter insights themes');
  const pain = exactKeys(themes.pain, ['evidence', 'method', 'rankings'], 'quarter insights themes.pain');
  validateRankings(pain.rankings, 'quarter insights themes.pain.rankings');
  validateEvidence(pain.evidence, 'quarter insights themes.pain.evidence');
  nonEmptyString(pain.method, 'quarter insights themes.pain.method');
  const reputation = exactKeys(themes.reputation, ['automation_comments', 'evidence', 'high_severity_vocs', 'method', 'negative_vocs', 'quarter_moderation_claim_evidence_count', 'rankings'], 'quarter insights themes.reputation');
  const reputationCounts = {
    automation_comments: nonNegativeInteger(reputation.automation_comments, 'quarter insights reputation.automation_comments'),
    high_severity_vocs: nonNegativeInteger(reputation.high_severity_vocs, 'quarter insights reputation.high_severity_vocs'),
    negative_vocs: nonNegativeInteger(reputation.negative_vocs, 'quarter insights reputation.negative_vocs'),
    quarter_moderation_claim_evidence_count: nonNegativeInteger(reputation.quarter_moderation_claim_evidence_count, 'quarter insights reputation.quarter_moderation_claim_evidence_count'),
  };
  const reputationRankings = validateRankings(reputation.rankings, 'quarter insights themes.reputation.rankings');
  const reputationRankingMap = new Map(reputationRankings.map((ranking) => [ranking.id, ranking.count]));
  Object.entries(reputationCounts).forEach(([key, count]) => assertContract(reputationRankingMap.get(key) === count, `quarter insights reputation.${key}与排名不一致`));
  validateEvidence(reputation.evidence, 'quarter insights themes.reputation.evidence');
  nonEmptyString(reputation.method, 'quarter insights themes.reputation.method');
  const newProduct = exactKeys(themes.new_product, ['category_rankings', 'evidence', 'exact_spu_rankings', 'family_only_ids', 'family_rankings', 'method', 'product_rankings'], 'quarter insights themes.new_product');
  validateRankings(newProduct.category_rankings, 'quarter insights themes.new_product.category_rankings');
  validateRankings(newProduct.exact_spu_rankings, 'quarter insights themes.new_product.exact_spu_rankings');
  validateRankings(newProduct.family_rankings, 'quarter insights themes.new_product.family_rankings');
  validateRankings(newProduct.product_rankings, 'quarter insights themes.new_product.product_rankings');
  assertContract(Array.isArray(newProduct.family_only_ids) && newProduct.family_only_ids.every((value) => typeof value === 'string' && value.length > 0), 'family_only_ids无效');
  validateEvidence(newProduct.evidence, 'quarter insights themes.new_product.evidence');
  nonEmptyString(newProduct.method, 'quarter insights themes.new_product.method');
  const geo = exactKeys(themes.geo, ['comparison_decision_posts', 'evidence', 'method', 'rankings'], 'quarter insights themes.geo');
  const geoCount = nonNegativeInteger(geo.comparison_decision_posts, 'quarter insights themes.geo.comparison_decision_posts');
  const geoRankings = validateRankings(geo.rankings, 'quarter insights themes.geo.rankings');
  assertContract(geoRankings.reduce((sum, ranking) => sum + ranking.count, 0) === geoCount, 'GEO问题总量与排名不守恒');
  validateEvidence(geo.evidence, 'quarter insights themes.geo.evidence');
  nonEmptyString(geo.method, 'quarter insights themes.geo.method');

  const caseReferences = exactKeys(item.case_references, ['geo', 'new_product', 'pain', 'reputation'], 'quarter insights case_references');
  Object.entries(caseReferences).forEach(([themeId, value]) => {
    const reference = exactKeys(value, ['id', 'role'], `quarter insights case_references.${themeId}`);
    assertContract(reference.id === null || (typeof reference.id === 'string' && SHA256_PATTERN.test(reference.id)), `quarter insights case_references.${themeId}.id无效`);
    assertContract(reference.role === 'historical_governance_method_reference' || reference.role === 'no_approved_local_case', `quarter insights case_references.${themeId}.role无效`);
    assertContract(reference.role === 'historical_governance_method_reference' ? reference.id !== null : reference.id === null, `quarter insights case_references.${themeId}角色与ID不一致`);
  });

  const dashboardWindows = validateDashboardWindows(item.dashboard_windows, period);
  return {
    ...item,
    boundaries,
    dashboard_windows: dashboardWindows,
    period,
    source,
  } as unknown as PublicQuarterInsightsData;
}

async function sha256Hex(value: string): Promise<string> {
  assertContract(Boolean(globalThis.crypto?.subtle), '当前环境不支持SHA-256');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function fetchText(path: string): Promise<string> {
  const response = await fetch(path, { cache: 'no-cache', headers: { Accept: 'application/json' } });
  assertContract(response.ok, `${path}加载失败：HTTP ${response.status}`);
  return response.text();
}

function parseJson(raw: string, label: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    throw new QuarterInsightsContractError(`${label}不是有效JSON`);
  }
}

export async function loadRedditQuarterInsights(
  options: LoadRedditQuarterInsightsOptions = {},
): Promise<RedditPublicQuarterInsights> {
  // An explicit basePath is a fixture/offline path, not the published release; it
  // must not be memoized under a release key or a test could poison production.
  const isReleaseBound = options.basePath === undefined
    && options.expectedManifestSha256 === undefined;
  if (!isReleaseBound) return loadQuarterInsightsUncached(options);
  const release = await loadCurrentRelease();
  return quarterInsightsCache.get(
    releaseGenerationKey(release),
    () => loadQuarterInsightsUncached(options),
  );
}

async function loadQuarterInsightsUncached(
  options: LoadRedditQuarterInsightsOptions,
): Promise<RedditPublicQuarterInsights> {
  let releaseBasePath: string | undefined;
  let releaseManifestSha256: string | undefined;
  if (options.basePath === undefined && options.expectedManifestSha256 === undefined) {
    const release = await loadCurrentRelease();
    const binding = release.datasets.quarter_insights;
    if (binding) {
      releaseBasePath = getReleaseDatasetBasePath(release, 'quarter_insights');
      releaseManifestSha256 = binding.public_manifest_sha256;
    }
  }
  const basePath = (options.basePath ?? releaseBasePath ?? QUARTER_INSIGHTS_PUBLIC_BASE_PATH).replace(/\/$/, '');
  const expectedManifestSha256 = options.expectedManifestSha256
    ?? releaseManifestSha256
    ?? QUARTER_INSIGHTS_PUBLIC_MANIFEST_SHA256;
  assertContract(SHA256_PATTERN.test(expectedManifestSha256), 'quarter insights预期manifest SHA-256无效');
  const manifestText = await fetchText(`${basePath}/manifest.json`);
  assertContract(await sha256Hex(manifestText) === expectedManifestSha256, 'quarter insights manifest SHA-256不一致');
  const manifest = validatePublicQuarterInsightsManifest(parseJson(manifestText, 'quarter insights manifest'));
  const dataText = await fetchText(`${basePath}/quarter-insights.json`);
  assertContract(new TextEncoder().encode(dataText).byteLength === manifest.files['quarter-insights.json'].bytes, 'quarter-insights.json字节数不一致');
  assertContract(await sha256Hex(dataText) === manifest.files['quarter-insights.json'].sha256, 'quarter-insights.json SHA-256不一致');
  const data = validatePublicQuarterInsightsData(parseJson(dataText, 'quarter-insights.json'));
  assertContract(
    data.dataset_version === manifest.dataset_version
      && data.generated_at_utc === manifest.generated_at_utc
      && JSON.stringify(data.period) === JSON.stringify(manifest.period)
      && JSON.stringify(data.boundaries) === JSON.stringify(manifest.boundaries)
      && JSON.stringify(data.source) === JSON.stringify(manifest.source),
    'quarter insights manifest与data lineage不一致',
  );
  return { data, manifest };
}

export function resetRedditQuarterInsightsCacheForTests(): void {
  quarterInsightsCache.clear();
}
