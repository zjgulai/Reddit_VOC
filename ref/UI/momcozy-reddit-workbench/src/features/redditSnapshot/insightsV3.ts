import {
  getReleaseDatasetBasePath,
  type CurrentRelease,
} from './release';

export const V3_INSIGHTS_PUBLIC_MANIFEST_SCHEMA = 'reddit_voc_insights_public_manifest_v3';
export const V3_INSIGHTS_PUBLIC_SCHEMA = 'reddit_voc_insights_public_v3';
export const V3_INSIGHTS_STORYLINE_SCHEMA = 'reddit_voc_storyline_public_v3';
export const V3_INSIGHTS_CANDIDATE_MANIFEST_SCHEMA = 'reddit_voc_insights_manifest_v3';

export type V3InsightGrain = 'daily' | 'weekly' | 'monthly';
export type V3InsightDirection = 'up' | 'down' | 'flat' | null;
export type V3InsightStatus = 'available' | 'provisional' | 'unavailable';
export type V3InsightComparisonSide = 'raw_observed' | 'momcozy' | 'not_applicable' | 'current';
export type V3ComparisonContractBasis = 'owner_attested_dataset_scope_window' | 'not_owner_attested';

interface FileIntegrity {
  bytes: number;
  sha256: string;
}

export interface V3InsightsBoundaries {
  database_write: false;
  deploy: false;
  live_send: false;
  production_unchanged: true;
  provider_call: false;
  remote_write: false;
}

export interface V3InsightsCoverageAttestation {
  attestation_basis: 'data_owner_declaration';
  completeness_percent: 100;
  coverage_window: {
    end_calendar_date_inclusive: string;
    start_calendar_date_inclusive: string;
  };
  evidence_class: 'owner_attested_not_crawler_proof';
  scope: 'canonical_observation_pool';
  source_snapshot_id: string;
}

export interface V3InsightsStorylineSummary {
  direction_supported: number;
  direction_unavailable: number;
  total: number;
}

export interface V3InsightsPublicManifest {
  artifact_stage: 'insights_public_candidate';
  boundaries: V3InsightsBoundaries;
  comparison_contract_basis: V3ComparisonContractBasis;
  comparison_contract_proven: boolean;
  comparison_unavailable_reason_codes: string[];
  completeness_percent: 100 | null;
  consumption_status: 'eligible_for_frontend_candidate_consumption';
  coverage_attestation: V3InsightsCoverageAttestation | null;
  data_owner_coverage_attestation_sha256: string | null;
  dataset_version: string;
  files: Record<'insights.json' | 'validation-receipt.json', FileIntegrity>;
  fixture_only: false;
  independent_validation_status: 'passed';
  lineage_manifest_sha256: string;
  privacy_safe_projection: true;
  promotable: true;
  schema_version: typeof V3_INSIGHTS_PUBLIC_MANIFEST_SCHEMA;
  source_snapshot_id: string;
  status: 'validated_candidate';
  storyline_count: 78;
  storyline_summary: V3InsightsStorylineSummary;
  validation_receipt_sha256: string;
}

export interface V3InsightsValidationReceipt {
  boundaries: V3InsightsBoundaries;
  bundle_manifest_sha256: string;
  comparison_contract_basis: V3ComparisonContractBasis;
  comparison_contract_proven: boolean;
  completeness_percent: 100 | null;
  data_owner_coverage_attestation_sha256: string | null;
  deterministic_full_byte_replay: true;
  metrics_candidate_manifest_sha256: string;
  metrics_input_manifest_sha256: string;
  metrics_validation_receipt_sha256: string;
  promotable: true;
  report_manifest_sha256: string;
  report_validation_receipt_sha256: string;
  schema_version: 'reddit_voc_insights_validation_receipt_v3';
  status: 'passed_candidate_only';
  storyline_count: 78;
  storyline_summary: V3InsightsStorylineSummary;
}

export interface V3InsightsPublicValidationReceipt {
  boundaries: V3InsightsBoundaries;
  bundle_manifest_sha256: string;
  comparison_contract_basis: V3ComparisonContractBasis;
  comparison_contract_proven: boolean;
  completeness_percent: 100 | null;
  data_owner_coverage_attestation_sha256: string | null;
  deterministic_full_byte_replay: true;
  lineage_manifest_sha256: string;
  privacy_safe_projection: true;
  promotable: true;
  schema_version: 'reddit_voc_insights_public_validation_receipt_v3';
  status: 'passed_candidate_only';
  storyline_count: 78;
  validation_receipt_sha256: string;
}

export interface V3InsightSignalSection {
  direction: V3InsightDirection;
  metric_id: string;
  period_id: string;
  scope: 'canonical_observation_pool';
  status: V3InsightStatus;
  unit: string;
  value: string | unknown[] | null;
  voc_type: 'post_voc+comment_context_voc';
}

export interface V3InsightStoryline {
  analysis_frame: {
    comparison_brand_role: 'competitor_union';
    comparison_metric_ids: ['RV-BR-05', 'RV-PS-04'];
    primary_brand: 'Momcozy';
    unavailable_comparison_policy?: 'retain_null_value_and_reason_codes';
  };
  comparison_side: V3InsightComparisonSide;
  direction_claim_supported: boolean;
  grain: V3InsightGrain;
  metric_id: string;
  period_id: string;
  schema_version: typeof V3_INSIGHTS_STORYLINE_SCHEMA;
  sections: {
    action: {
      approval_status: 'proposed';
      owner_role: 'VOC Insights';
      priority: 'P1' | 'P2';
    };
    counter_intuitive: {
      reason_codes: string[];
      statement: string;
      supported: boolean;
    };
    impact: {
      sales_causality_supported: false;
      statement: string;
    };
    monitoring: {
      cadence: V3InsightGrain;
      metric_id: string;
      review_date: string;
    };
    root_cause: {
      evidence_count: number;
      statement: string;
      supported: boolean;
    };
    signal: V3InsightSignalSection;
  };
}

export interface V3BrandHealthRow {
  comparison_contract_proven: boolean;
  comparison_side: 'raw_observed' | 'qualified_organic';
  coverage_profile_hash: string;
  data_owner_coverage_attestation_sha256: string | null;
  display: string;
  grain: V3InsightGrain;
  metric_id: 'brand_health_index_v2';
  metric_policy_version: string;
  observed_time_precision: 'instant' | 'mixed';
  period_complete: boolean;
  period_id: string;
  retrieval_contract_hash: string;
  scope: 'momcozy';
  source_calendar_date: string;
  source_selection_profile_hash: string;
  status: V3InsightStatus;
  time_precision: string;
  unavailable_reason_codes: string[];
  unit: 'index';
  value: string | null;
  voc_type: 'post_voc+comment_context_voc';
}

export interface V3BrandHealthPeriod {
  dimension_rows?: unknown[];
  metric_id: 'brand_health_index_v2';
  rows: V3BrandHealthRow[];
  scope: 'momcozy';
}

export interface V3PublicInsightsData {
  analysis_frame: {
    comparison_brand_role: 'competitor_union';
    comparison_metric_ids: ['RV-BR-05', 'RV-PS-04'];
    primary_brand: 'Momcozy';
  };
  boundaries: V3InsightsBoundaries;
  brand_health: Record<V3InsightGrain, V3BrandHealthPeriod>;
  comparison_contract_basis: V3ComparisonContractBasis;
  comparison_contract_proven: boolean;
  comparison_unavailable_reason_codes: string[];
  completeness_percent: 100 | null;
  coverage_attestation: V3InsightsCoverageAttestation | null;
  data_owner_coverage_attestation_sha256: string | null;
  dataset_version: string;
  fixture_only: false;
  interpretation_boundaries: {
    brand_health_null_when_classification_coverage_insufficient: true;
    direction_requires_precomputed_comparable_complete_periods: true;
    front_end_recomputation_supported: false;
    root_cause_requires_same_snapshot_evidence: true;
    sales_causality_supported: false;
    unavailable_metric_direction_supported: false;
  };
  lineage_schema_version: 'reddit_voc_insights_v3';
  privacy_safe_projection: true;
  schema_version: typeof V3_INSIGHTS_PUBLIC_SCHEMA;
  source: {
    coverage_attestation_sha256: string | null;
    metrics_candidate_manifest_sha256: string;
    metrics_input_manifest_sha256: string;
    metrics_validation_receipt_sha256: string;
    report_manifest_sha256: string;
    report_validation_receipt_sha256: string;
    source_snapshot_id: string;
  };
  storyline_count: 78;
  storyline_summary: V3InsightsStorylineSummary;
  storylines: V3InsightStoryline[];
}

export interface V3RedditInsightsSnapshot {
  release: CurrentRelease;
  manifest: V3InsightsPublicManifest;
  receipt: V3InsightsValidationReceipt;
  publicValidationReceipt: V3InsightsPublicValidationReceipt;
  insights: V3PublicInsightsData;
}

export class V3InsightsContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'V3InsightsContractError';
  }
}

export const V3_INSIGHT_METRIC_CATALOG = {
  'RV-BR-01': { name_cn: '观察量', unit: 'count', comparison_side: 'raw_observed', family: '品牌表现' },
  'RV-BR-02': { name_cn: '负向率', unit: 'percent', comparison_side: 'raw_observed', family: '品牌表现' },
  'RV-BR-03': { name_cn: '净情感', unit: 'pp', comparison_side: 'raw_observed', family: '品牌表现' },
  'RV-BR-04': { name_cn: '推荐表达率', unit: 'percent', comparison_side: 'raw_observed', family: '品牌表现' },
  'RV-BR-05': { name_cn: '竞品净情感差', unit: 'pp', comparison_side: 'momcozy', family: '品牌表现' },
  'RV-CI-01': { name_cn: '显式 bot/template 排除率', unit: 'percent', comparison_side: 'not_applicable', family: '内容治理' },
  'RV-CI-02': { name_cn: '商业披露率', unit: 'percent', comparison_side: 'not_applicable', family: '内容治理' },
  'RV-CI-03': { name_cn: '疑似传播 cluster 数', unit: 'count', comparison_side: 'not_applicable', family: '内容治理' },
  'RV-CI-04': { name_cn: '外部治理事件数', unit: 'count', comparison_side: 'not_applicable', family: '内容治理' },
  'RV-CI-05': { name_cn: '已确认不当干预数', unit: 'count', comparison_side: 'not_applicable', family: '内容治理' },
  'RV-CI-06': { name_cn: 'raw-qualified 敏感性差', unit: 'inherit', comparison_side: 'raw_observed', family: '内容治理' },
  'RV-CI-07': { name_cn: '归属复核积压', unit: 'count', comparison_side: 'not_applicable', family: '内容治理' },
  'RV-DH-01': { name_cn: '根帖关联率', unit: 'percent', comparison_side: 'not_applicable', family: '数据健康' },
  'RV-DH-02': { name_cn: '文本完整率', unit: 'percent', comparison_side: 'not_applicable', family: '数据健康' },
  'RV-DH-03': { name_cn: '有效标签率', unit: 'percent', comparison_side: 'not_applicable', family: '数据健康' },
  'RV-DH-04': { name_cn: 'SPU 绑定率', unit: 'percent', comparison_side: 'not_applicable', family: '数据健康' },
  'RV-DH-05': { name_cn: '证据完整率', unit: 'percent', comparison_side: 'not_applicable', family: '数据健康' },
  'RV-IN-01': { name_cn: '紧急度', unit: 'score', comparison_side: 'raw_observed', family: '诊断洞察' },
  'RV-IN-02': { name_cn: '标签关联 lift', unit: 'ratio', comparison_side: 'raw_observed', family: '诊断洞察' },
  'RV-IN-03': { name_cn: '画像差', unit: 'pp', comparison_side: 'raw_observed', family: '诊断洞察' },
  'RV-IN-04': { name_cn: '线程放大', unit: 'ratio', comparison_side: 'raw_observed', family: '诊断洞察' },
  'RV-IN-05': { name_cn: '异常加速度', unit: 'log_delta2', comparison_side: 'current', family: '诊断洞察' },
  'RV-PS-01': { name_cn: '产品 scope 占比', unit: 'percent', comparison_side: 'momcozy', family: '产品与品类' },
  'RV-PS-02': { name_cn: '产品问题率', unit: 'percent', comparison_side: 'momcozy', family: '产品与品类' },
  'RV-PS-03': { name_cn: '产品问题排行', unit: 'rank', comparison_side: 'momcozy', family: '产品与品类' },
  'RV-PS-04': { name_cn: '产品竞品问题差', unit: 'pp', comparison_side: 'momcozy', family: '产品与品类' },
} as const satisfies Record<string, {
  name_cn: string;
  unit: string;
  comparison_side: V3InsightComparisonSide;
  family: string;
}>;

export type V3InsightMetricId = keyof typeof V3_INSIGHT_METRIC_CATALOG;

const METRIC_IDS = Object.keys(V3_INSIGHT_METRIC_CATALOG) as V3InsightMetricId[];
const METRIC_ID_SET = new Set<string>(METRIC_IDS);
const GRAINS: V3InsightGrain[] = ['daily', 'weekly', 'monthly'];
const EXPECTED_PUBLIC_FILES = new Set(['insights.json', 'validation-receipt.json']);
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const PERIOD_PATTERN = /^(daily|weekly|monthly):(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})$/;
const UNATTESTED_COVERAGE_REASON = 'historical_collection_coverage_not_owner_attested_complete';

const PRIVACY_FORBIDDEN_KEYS = new Set([
  'author',
  'body',
  'comment_id',
  'comment_ids',
  'content',
  'entity_id',
  'entity_ids',
  'evidence_id',
  'evidence_ids',
  'member_id',
  'member_ids',
  'permalink',
  'post_id',
  'post_ids',
  'reddit_id',
  'storyline_id',
  'title',
  'url',
  'user_id',
]);

const PUBLIC_VALIDATION_SIDECAR = 'public-validation-receipt.json';
const VALIDATED_PUBLIC_WRAPPERS: Readonly<Record<string, FileIntegrity>> = {
  // 2026-10-28 rebuild: 17,469/58,296 corpus, owner-attested comparisons.
  'e4f7d11a43e1b6fc5c75f696aca81f19aaf909e2e070bb31dc9eb133f086bd47': {
    bytes: 868,
    sha256: '2c4d8e3375213dbcd6598d4f8b29a938f11319ce8f7563c82d6b1ed99c3b5a5d',
  },
  '9c0d84009e25090e14a278e3d953908f255e65a33707f627bbb476d134c5354a': {
    bytes: 633,
    sha256: 'a9d97d0778f2e1ada156a411835ffad03f2b159dd7c29433b0958cba8939517a',
  },
  '82e44dcf995372167b08f4e2ec92267b1d113db90ce95867d1e72949fa8124a3': {
    bytes: 633,
    sha256: '32d3e5fbdbc2d7ebe61f27d5518aaa7aa5beff84f71134f07b655d18cae5357c',
  },
  'e92d8b4e8a65a451af48cdbc3fe946198187b9239fa3e8f04c9b25b82fb4be2f': {
    bytes: 633,
    sha256: 'fbf155db5abba51d5578479f4b2d9933c1ebe68218c528a054a499d31da2e5b1',
  },
  '8c6b0d3f1fa27857cc31d74870e7da985da669f02fcb89fec00d32bb56ddd348': {
    bytes: 633,
    sha256: 'f7fefc4176da485104e7cd858ae26b2664aef62f20036b02d2b9a6be0ea3c30d',
  },
  '0449f1d6412eec301415f322feb0b6a525d568a2d8267851b29fa077447446aa': {
    bytes: 633,
    sha256: 'dfdbca2be18152d0d593c82ab646f204d782274210a74d1a2e5ced211bcf7ca4',
  },
  'e43ac17c0dda5e8f481d35e7426c17c83acf6115c4af76457ee0ac7009702024': {
    bytes: 791,
    sha256: 'f1a5977eab86db1b1af56f54064e67f1578616d754faa58c1d4a85a004e821cf',
  },
  'a3d4e5377d878219e377520f4fa87553226e13465dca075035fe8c225b1f8705': {
    bytes: 791,
    sha256: '06995826ee20d1e72e21e5d6a4b022894666bc604d9ab9309cbae7326463e9ae',
  },
  'cc466e9c3e7f554b3848e3b4bca5b8f995f71030b9b748ad506495f5d02c3868': {
    bytes: 791,
    sha256: '221f2a1e6bab17ff62ee1da5b50bf6107361a50ac1070162bba15ee91c6ab103',
  },
  'ff106e7980ed90f478f059e267251d8d79bef941bdad2609bd6565d1e49f6abd': {
    bytes: 791,
    sha256: '44756e395dbc4a8e1fb46963b6e4c592aa5843a44a29a7486ce404d097ae6b12',
  },
};

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new V3InsightsContractError(message);
}

function assertRecord(value: unknown, label: string): asserts value is Record<string, unknown> {
  assertContract(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `${label}必须是对象`);
}

function assertExactKeys(value: unknown, expected: readonly string[], label: string): asserts value is Record<string, unknown> {
  assertRecord(value, label);
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  assertContract(
    actual.length === wanted.length && actual.every((key, index) => key === wanted[index]),
    `${label}字段集合异常`,
  );
}

function assertSha256(value: unknown, label: string): asserts value is string {
  assertContract(typeof value === 'string' && SHA256_PATTERN.test(value), `${label} SHA-256 异常`);
}

function assertNonNegativeInteger(value: unknown, label: string): asserts value is number {
  assertContract(Number.isInteger(value) && Number(value) >= 0, `${label}必须是非负整数`);
}

function assertStringArray(value: unknown, label: string): asserts value is string[] {
  assertContract(Array.isArray(value) && value.every((item) => typeof item === 'string'), `${label}必须是字符串数组`);
}

function assertSameJson(actual: unknown, expected: unknown, label: string): void {
  assertContract(JSON.stringify(actual) === JSON.stringify(expected), `${label}不一致`);
}

function assertStaticBoundaries(value: unknown, label: string): asserts value is V3InsightsBoundaries {
  assertExactKeys(value, [
    'database_write',
    'deploy',
    'live_send',
    'production_unchanged',
    'provider_call',
    'remote_write',
  ], label);
  const boundaries = value as unknown as V3InsightsBoundaries;
  assertContract(
    boundaries.production_unchanged === true
      && boundaries.database_write === false
      && boundaries.deploy === false
      && boundaries.live_send === false
      && boundaries.provider_call === false
      && boundaries.remote_write === false,
    `${label}静态副作用边界异常`,
  );
}

function assertCoverageAttestation(
  value: unknown,
  sourceSnapshotId: string,
  label: string,
): asserts value is V3InsightsCoverageAttestation {
  assertExactKeys(value, [
    'attestation_basis',
    'completeness_percent',
    'coverage_window',
    'evidence_class',
    'scope',
    'source_snapshot_id',
  ], label);
  const attestation = value as unknown as V3InsightsCoverageAttestation;
  assertExactKeys(attestation.coverage_window, [
    'end_calendar_date_inclusive',
    'start_calendar_date_inclusive',
  ], `${label}.coverage_window`);
  const start = attestation.coverage_window.start_calendar_date_inclusive;
  const end = attestation.coverage_window.end_calendar_date_inclusive;
  assertContract(
    attestation.attestation_basis === 'data_owner_declaration'
      && attestation.completeness_percent === 100
      && attestation.evidence_class === 'owner_attested_not_crawler_proof'
      && attestation.scope === 'canonical_observation_pool'
      && attestation.source_snapshot_id === sourceSnapshotId
      && DATE_PATTERN.test(start)
      && DATE_PATTERN.test(end)
      && start <= end,
    `${label}数据所有者完整性声明异常`,
  );
}

function assertCoverageContract(
  value: {
    comparison_contract_basis: unknown;
    comparison_contract_proven: unknown;
    comparison_unavailable_reason_codes: unknown;
    completeness_percent: unknown;
    coverage_attestation: unknown;
    data_owner_coverage_attestation_sha256: unknown;
    source_snapshot_id: string;
  },
  label: string,
): void {
  const comparisonReasons = value.comparison_unavailable_reason_codes ?? [];
  assertStringArray(comparisonReasons, `${label}.comparison_unavailable_reason_codes`);
  if (value.comparison_contract_proven === true) {
    assertContract(
      value.comparison_contract_basis === 'owner_attested_dataset_scope_window'
        && value.completeness_percent === 100
        && comparisonReasons.length === 0,
      `${label}已证明覆盖合同异常`,
    );
    assertSha256(value.data_owner_coverage_attestation_sha256, `${label}.coverage attestation`);
    assertCoverageAttestation(value.coverage_attestation, value.source_snapshot_id, `${label}.coverage`);
    return;
  }
  assertContract(
    value.comparison_contract_proven === false
      && value.comparison_contract_basis === 'not_owner_attested'
      && value.completeness_percent === null
      && value.coverage_attestation === null
      && value.data_owner_coverage_attestation_sha256 === null
      && comparisonReasons.length === 1
      && comparisonReasons[0] === UNATTESTED_COVERAGE_REASON,
    `${label}未证明覆盖合同异常`,
  );
}

function assertStorylineSummary(
  value: unknown,
  label: string,
): asserts value is V3InsightsStorylineSummary {
  assertExactKeys(value, ['direction_supported', 'direction_unavailable', 'total'], label);
  const summary = value as unknown as V3InsightsStorylineSummary;
  assertNonNegativeInteger(summary.direction_supported, `${label}.direction_supported`);
  assertNonNegativeInteger(summary.direction_unavailable, `${label}.direction_unavailable`);
  assertNonNegativeInteger(summary.total, `${label}.total`);
  assertContract(
    summary.total === 78
      && summary.direction_supported + summary.direction_unavailable === summary.total,
    `${label}故事线方向统计不守恒`,
  );
}

function assertPrivacySafe(value: unknown, path = 'V3 public insights'): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertPrivacySafe(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === 'object') {
    Object.entries(value as Record<string, unknown>).forEach(([key, child]) => {
      assertContract(!PRIVACY_FORBIDDEN_KEYS.has(key), `${path}包含隐私或原始内容字段：${key}`);
      assertPrivacySafe(child, `${path}.${key}`);
    });
    return;
  }
  if (typeof value === 'string') {
    assertContract(!/https?:\/\/|www\./i.test(value), `${path}包含外链`);
  }
}

export function isV3InsightsPublicManifest(value: unknown): value is V3InsightsPublicManifest {
  return Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
    && (value as { schema_version?: unknown }).schema_version === V3_INSIGHTS_PUBLIC_MANIFEST_SCHEMA;
}

export function isV3InsightsCandidateManifest(value: unknown): boolean {
  return Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
    && (value as { schema_version?: unknown }).schema_version === V3_INSIGHTS_CANDIDATE_MANIFEST_SCHEMA;
}

export function isV3InsightsSnapshot(value: unknown): value is V3RedditInsightsSnapshot {
  return Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
    && isV3InsightsPublicManifest((value as { manifest?: unknown }).manifest);
}

export function validateV3InsightsManifest(
  value: unknown,
  release: CurrentRelease,
): V3InsightsPublicManifest {
  const hasComparisonReasons = Boolean(value)
    && typeof value === 'object'
    && Object.hasOwn(value as object, 'comparison_unavailable_reason_codes');
  assertExactKeys(value, [
    'artifact_stage',
    'boundaries',
    'comparison_contract_basis',
    'comparison_contract_proven',
    ...(hasComparisonReasons ? ['comparison_unavailable_reason_codes'] : []),
    'completeness_percent',
    'consumption_status',
    'coverage_attestation',
    'data_owner_coverage_attestation_sha256',
    'dataset_version',
    'files',
    'fixture_only',
    'independent_validation_status',
    'lineage_manifest_sha256',
    'privacy_safe_projection',
    'promotable',
    'schema_version',
    'source_snapshot_id',
    'status',
    'storyline_count',
    'storyline_summary',
    'validation_receipt_sha256',
  ], 'V3 洞察 public manifest');
  const manifest = value as unknown as V3InsightsPublicManifest;
  assertContract(manifest.schema_version === V3_INSIGHTS_PUBLIC_MANIFEST_SCHEMA, 'V3 洞察 public manifest schema 不受支持');
  assertContract(manifest.dataset_version === release.datasets.insights.dataset_version, 'V3 洞察版本与 current release 不一致');
  assertContract(
    manifest.lineage_manifest_sha256 === release.datasets.insights.lineage_manifest_sha256,
    'V3 洞察 lineage manifest 与 current release 不一致',
  );
  assertContract(
    manifest.artifact_stage === 'insights_public_candidate'
      && manifest.status === 'validated_candidate'
      && manifest.consumption_status === 'eligible_for_frontend_candidate_consumption'
      && manifest.independent_validation_status === 'passed'
      && manifest.promotable === true
      && manifest.privacy_safe_projection === true
      && manifest.fixture_only === false,
    'V3 洞察 public wrapper 未通过前端消费门禁',
  );
  assertCoverageContract(manifest, 'V3 洞察 manifest');
  assertSha256(manifest.lineage_manifest_sha256, 'V3 洞察 lineage manifest');
  assertSha256(manifest.validation_receipt_sha256, 'V3 洞察 embedded validation receipt');
  assertStaticBoundaries(manifest.boundaries, 'V3 洞察 manifest boundaries');
  assertStorylineSummary(manifest.storyline_summary, 'V3 洞察 manifest storyline summary');
  assertContract(manifest.storyline_count === 78, 'V3 洞察 manifest 故事线数量异常');
  assertExactKeys(manifest.files, [...EXPECTED_PUBLIC_FILES], 'V3 洞察 manifest files');
  Object.entries(manifest.files).forEach(([path, integrity]) => {
    assertExactKeys(integrity, ['bytes', 'sha256'], `V3 洞察 manifest file ${path}`);
    assertContract(Number.isInteger(integrity.bytes) && integrity.bytes > 0, `V3 洞察文件 bytes 异常：${path}`);
    assertSha256(integrity.sha256, `V3 洞察文件 ${path}`);
  });
  assertContract(
    manifest.files['validation-receipt.json'].sha256 === manifest.validation_receipt_sha256,
    'V3 洞察 manifest 未绑定 embedded validation receipt',
  );
  return manifest;
}

function validateEmbeddedReceipt(
  value: unknown,
  manifest: V3InsightsPublicManifest,
): V3InsightsValidationReceipt {
  assertExactKeys(value, [
    'boundaries',
    'bundle_manifest_sha256',
    'comparison_contract_basis',
    'comparison_contract_proven',
    'completeness_percent',
    'data_owner_coverage_attestation_sha256',
    'deterministic_full_byte_replay',
    'metrics_candidate_manifest_sha256',
    'metrics_input_manifest_sha256',
    'metrics_validation_receipt_sha256',
    'promotable',
    'report_manifest_sha256',
    'report_validation_receipt_sha256',
    'schema_version',
    'status',
    'storyline_count',
    'storyline_summary',
  ], 'V3 洞察 embedded receipt');
  const receipt = value as unknown as V3InsightsValidationReceipt;
  assertContract(
    receipt.schema_version === 'reddit_voc_insights_validation_receipt_v3'
      && receipt.status === 'passed_candidate_only'
      && receipt.promotable === true
      && receipt.deterministic_full_byte_replay === true
      && receipt.storyline_count === 78,
    'V3 洞察 embedded receipt 未通过消费门禁',
  );
  assertContract(receipt.bundle_manifest_sha256 === manifest.lineage_manifest_sha256, 'V3 洞察 embedded receipt 未绑定 lineage');
  assertContract(
    receipt.comparison_contract_proven === manifest.comparison_contract_proven
      && receipt.comparison_contract_basis === manifest.comparison_contract_basis
      && receipt.completeness_percent === manifest.completeness_percent
      && receipt.data_owner_coverage_attestation_sha256 === manifest.data_owner_coverage_attestation_sha256,
    'V3 洞察 embedded receipt 比较合同不一致',
  );
  assertStaticBoundaries(receipt.boundaries, 'V3 洞察 embedded receipt boundaries');
  assertStorylineSummary(receipt.storyline_summary, 'V3 洞察 embedded receipt storyline summary');
  assertSameJson(receipt.storyline_summary, manifest.storyline_summary, 'V3 洞察 receipt/manifest 故事线统计');
  [
    receipt.metrics_candidate_manifest_sha256,
    receipt.metrics_input_manifest_sha256,
    receipt.metrics_validation_receipt_sha256,
    receipt.report_manifest_sha256,
    receipt.report_validation_receipt_sha256,
  ].forEach((sha, index) => assertSha256(sha, `V3 洞察 embedded receipt lineage ${index}`));
  return receipt;
}

function validatePublicValidationReceipt(
  value: unknown,
  manifest: V3InsightsPublicManifest,
  release: CurrentRelease,
): V3InsightsPublicValidationReceipt {
  const hasComparisonContract = Boolean(value)
    && typeof value === 'object'
    && Object.hasOwn(value as object, 'comparison_contract_proven');
  assertExactKeys(value, [
    'boundaries',
    'bundle_manifest_sha256',
    ...(hasComparisonContract ? [
      'comparison_contract_basis',
      'comparison_contract_proven',
      'completeness_percent',
      'data_owner_coverage_attestation_sha256',
    ] : []),
    'deterministic_full_byte_replay',
    'lineage_manifest_sha256',
    'privacy_safe_projection',
    'promotable',
    'schema_version',
    'status',
    'storyline_count',
    'validation_receipt_sha256',
  ], 'V3 洞察 public validation receipt');
  const receipt = value as unknown as V3InsightsPublicValidationReceipt;
  assertContract(
    receipt.schema_version === 'reddit_voc_insights_public_validation_receipt_v3'
      && receipt.status === 'passed_candidate_only'
      && receipt.promotable === true
      && receipt.deterministic_full_byte_replay === true
      && receipt.privacy_safe_projection === true
      && receipt.storyline_count === 78,
    'V3 洞察 public validation receipt 未通过消费门禁',
  );
  assertContract(receipt.bundle_manifest_sha256 === release.datasets.insights.public_manifest_sha256, 'V3 洞察 public receipt 未绑定 public manifest');
  assertContract(receipt.lineage_manifest_sha256 === manifest.lineage_manifest_sha256, 'V3 洞察 public receipt 未绑定 lineage manifest');
  assertContract(receipt.validation_receipt_sha256 === manifest.validation_receipt_sha256, 'V3 洞察 public receipt 未绑定 embedded receipt');
  if (hasComparisonContract) {
    assertContract(
      receipt.comparison_contract_proven === manifest.comparison_contract_proven
        && receipt.comparison_contract_basis === manifest.comparison_contract_basis
        && receipt.completeness_percent === manifest.completeness_percent
        && receipt.data_owner_coverage_attestation_sha256 === manifest.data_owner_coverage_attestation_sha256,
      'V3 洞察 public receipt 比较合同不一致',
    );
  } else {
    assertContract(manifest.comparison_contract_proven === true, '未证明覆盖的 V3 洞察 public receipt 缺少比较合同');
  }
  assertStaticBoundaries(receipt.boundaries, 'V3 洞察 public validation receipt boundaries');
  return receipt;
}

function validateBrandHealthRow(
  value: unknown,
  grain: V3InsightGrain,
  manifest: V3InsightsPublicManifest,
  label: string,
): V3BrandHealthRow {
  assertExactKeys(value, [
    'comparison_contract_proven',
    'comparison_side',
    'coverage_profile_hash',
    'data_owner_coverage_attestation_sha256',
    'display',
    'grain',
    'metric_id',
    'metric_policy_version',
    'observed_time_precision',
    'period_complete',
    'period_id',
    'retrieval_contract_hash',
    'scope',
    'source_calendar_date',
    'source_selection_profile_hash',
    'status',
    'time_precision',
    'unavailable_reason_codes',
    'unit',
    'value',
    'voc_type',
  ], label);
  const row = value as unknown as V3BrandHealthRow;
  assertContract(
    row.metric_id === 'brand_health_index_v2'
      && row.grain === grain
      && row.scope === 'momcozy'
      && ['available', 'provisional', 'unavailable'].includes(row.status)
      && row.unit === 'index'
      && row.period_complete === manifest.comparison_contract_proven
      && row.comparison_contract_proven === manifest.comparison_contract_proven
      && ['raw_observed', 'qualified_organic'].includes(row.comparison_side)
      && ['instant', 'mixed'].includes(row.observed_time_precision)
      && row.voc_type === 'post_voc+comment_context_voc',
    `${label}状态或口径异常`,
  );
  if (row.status === 'unavailable') {
    assertContract(row.value === null && row.display === '—', `${label}不可用评分必须保持 —`);
  } else {
    assertContract(
      typeof row.value === 'string'
        && row.value.trim() !== ''
        && Number.isFinite(Number(row.value))
        && row.display === row.value,
      `${label}可计算评分值异常`,
    );
  }
  assertContract(row.data_owner_coverage_attestation_sha256 === manifest.data_owner_coverage_attestation_sha256, `${label}coverage SHA 漂移`);
  [row.coverage_profile_hash, row.retrieval_contract_hash, row.source_selection_profile_hash]
    .forEach((sha, index) => assertSha256(sha, `${label} profile ${index}`));
  assertContract(DATE_PATTERN.test(row.source_calendar_date), `${label}source calendar date 异常`);
  assertContract(PERIOD_PATTERN.test(row.period_id) && row.period_id.startsWith(`${grain}:`), `${label}period ID 异常`);
  assertStringArray(row.unavailable_reason_codes, `${label}不可用原因`);
  if (row.status === 'available') {
    assertContract(row.unavailable_reason_codes.length === 0, `${label}可用评分仍包含限制原因码`);
  } else {
    assertContract(row.unavailable_reason_codes.length > 0, `${label}受限评分缺少原因码`);
  }
  return row;
}

function validateStoryline(
  value: unknown,
  label: string,
): V3InsightStoryline {
  assertExactKeys(value, [
    'analysis_frame',
    'comparison_side',
    'direction_claim_supported',
    'grain',
    'metric_id',
    'period_id',
    'schema_version',
    'sections',
  ], label);
  const storyline = value as unknown as V3InsightStoryline;
  assertContract(storyline.schema_version === V3_INSIGHTS_STORYLINE_SCHEMA, `${label}schema 异常`);
  assertContract(GRAINS.includes(storyline.grain), `${label}grain 异常`);
  assertContract(METRIC_ID_SET.has(storyline.metric_id), `${label}metric ID 未注册`);
  const metric = V3_INSIGHT_METRIC_CATALOG[storyline.metric_id as V3InsightMetricId];
  assertContract(storyline.comparison_side === metric.comparison_side, `${label}comparison side 与指标目录不一致`);
  const periodMatch = PERIOD_PATTERN.exec(storyline.period_id);
  assertContract(Boolean(periodMatch) && periodMatch?.[1] === storyline.grain && periodMatch[2] < periodMatch[3], `${label}period ID 异常`);

  const frameKeys = storyline.analysis_frame.unavailable_comparison_policy === undefined
    ? ['comparison_brand_role', 'comparison_metric_ids', 'primary_brand']
    : ['comparison_brand_role', 'comparison_metric_ids', 'primary_brand', 'unavailable_comparison_policy'];
  assertExactKeys(storyline.analysis_frame, frameKeys, `${label}.analysis_frame`);
  assertContract(
    storyline.analysis_frame.primary_brand === 'Momcozy'
      && storyline.analysis_frame.comparison_brand_role === 'competitor_union'
      && JSON.stringify(storyline.analysis_frame.comparison_metric_ids) === JSON.stringify(['RV-BR-05', 'RV-PS-04'])
      && (storyline.analysis_frame.unavailable_comparison_policy === undefined
        || storyline.analysis_frame.unavailable_comparison_policy === 'retain_null_value_and_reason_codes'),
    `${label}Momcozy 主干或竞品角色异常`,
  );

  assertExactKeys(storyline.sections, [
    'action',
    'counter_intuitive',
    'impact',
    'monitoring',
    'root_cause',
    'signal',
  ], `${label}.sections`);
  const { action, counter_intuitive: counter, impact, monitoring, root_cause: root, signal } = storyline.sections;
  assertExactKeys(action, ['approval_status', 'owner_role', 'priority'], `${label}.action`);
  assertContract(
    action.approval_status === 'proposed'
      && action.owner_role === 'VOC Insights'
      && ['P1', 'P2'].includes(action.priority),
    `${label}行动建议状态异常`,
  );
  assertExactKeys(counter, ['reason_codes', 'statement', 'supported'], `${label}.counter_intuitive`);
  assertStringArray(counter.reason_codes, `${label}.counter_intuitive.reason_codes`);
  assertContract(typeof counter.statement === 'string' && counter.statement.length > 0, `${label}反直觉陈述为空`);
  assertContract(counter.supported === storyline.direction_claim_supported, `${label}反直觉与方向门禁不一致`);
  assertContract(counter.supported ? counter.reason_codes.length === 0 : true, `${label}已支持反直觉结论仍包含失败原因`);

  assertExactKeys(impact, ['sales_causality_supported', 'statement'], `${label}.impact`);
  assertContract(
    impact.sales_causality_supported === false
      && typeof impact.statement === 'string'
      && impact.statement.length > 0,
    `${label}影响评估越界`,
  );
  assertExactKeys(monitoring, ['cadence', 'metric_id', 'review_date'], `${label}.monitoring`);
  assertContract(
    monitoring.cadence === storyline.grain
      && monitoring.metric_id === storyline.metric_id
      && DATE_PATTERN.test(monitoring.review_date),
    `${label}监控口径异常`,
  );

  assertExactKeys(root, ['evidence_count', 'statement', 'supported'], `${label}.root_cause`);
  assertNonNegativeInteger(root.evidence_count, `${label}.root_cause.evidence_count`);
  if (root.supported) {
    assertContract(
      root.evidence_count > 0
        && root.statement === `由 ${root.evidence_count} 条受治理内容证据支持`,
      `${label}根因证据陈述不守恒`,
    );
  } else {
    assertContract(root.evidence_count === 0 && root.statement === '根因未确认', `${label}对未确认根因进行了推断`);
  }

  assertExactKeys(signal, [
    'direction',
    'metric_id',
    'period_id',
    'scope',
    'status',
    'unit',
    'value',
    'voc_type',
  ], `${label}.signal`);
  assertContract(
    signal.metric_id === storyline.metric_id
      && signal.period_id === storyline.period_id
      && signal.scope === 'canonical_observation_pool'
      && signal.voc_type === 'post_voc+comment_context_voc'
      && signal.unit === metric.unit
      && ['available', 'provisional', 'unavailable'].includes(signal.status)
      && [null, 'up', 'down', 'flat'].includes(signal.direction),
    `${label}信号口径异常`,
  );
  if (signal.status === 'unavailable') {
    assertContract(
      signal.value === null && signal.direction === null && storyline.direction_claim_supported === false,
      `${label}不可用指标必须保持 null/— 且不得发布方向`,
    );
  } else if (signal.unit === 'rank') {
    assertContract(Array.isArray(signal.value), `${label}ranking 指标值类型异常`);
  } else {
    assertContract(
      typeof signal.value === 'string'
        && signal.value.trim() !== ''
        && Number.isFinite(Number(signal.value)),
      `${label}可用标量指标值异常`,
    );
  }
  if (storyline.direction_claim_supported) {
    assertContract(signal.status !== 'unavailable' && signal.direction !== null, `${label}方向结论缺少可比信号`);
  }
  assertSameJson(storyline.analysis_frame, {
    comparison_brand_role: 'competitor_union',
    comparison_metric_ids: ['RV-BR-05', 'RV-PS-04'],
    primary_brand: 'Momcozy',
    unavailable_comparison_policy: 'retain_null_value_and_reason_codes',
  }, `${label}analysis frame`);
  return storyline;
}

export function validateV3PublicInsightsData(
  value: unknown,
  manifest: V3InsightsPublicManifest,
  receipt: V3InsightsValidationReceipt,
): V3PublicInsightsData {
  const hasComparisonReasons = Boolean(value)
    && typeof value === 'object'
    && Object.hasOwn(value as object, 'comparison_unavailable_reason_codes');
  assertExactKeys(value, [
    'analysis_frame',
    'boundaries',
    'brand_health',
    'comparison_contract_basis',
    'comparison_contract_proven',
    ...(hasComparisonReasons ? ['comparison_unavailable_reason_codes'] : []),
    'completeness_percent',
    'coverage_attestation',
    'data_owner_coverage_attestation_sha256',
    'dataset_version',
    'fixture_only',
    'interpretation_boundaries',
    'lineage_schema_version',
    'privacy_safe_projection',
    'schema_version',
    'source',
    'storyline_count',
    'storyline_summary',
    'storylines',
  ], 'V3 public insights');
  assertPrivacySafe(value);
  const insights = value as unknown as V3PublicInsightsData;
  assertContract(
    insights.schema_version === V3_INSIGHTS_PUBLIC_SCHEMA
      && insights.lineage_schema_version === 'reddit_voc_insights_v3'
      && insights.dataset_version === manifest.dataset_version
      && insights.fixture_only === false
      && insights.privacy_safe_projection === true
      && insights.comparison_contract_proven === manifest.comparison_contract_proven
      && insights.comparison_contract_basis === manifest.comparison_contract_basis,
    'V3 public insights 身份或消费状态异常',
  );
  assertExactKeys(insights.analysis_frame, ['comparison_brand_role', 'comparison_metric_ids', 'primary_brand'], 'V3 public insights analysis frame');
  assertContract(
    insights.analysis_frame.primary_brand === 'Momcozy'
      && insights.analysis_frame.comparison_brand_role === 'competitor_union'
      && JSON.stringify(insights.analysis_frame.comparison_metric_ids) === JSON.stringify(['RV-BR-05', 'RV-PS-04']),
    'V3 public insights 未保持 Momcozy 主干与竞品对照角色',
  );
  assertStaticBoundaries(insights.boundaries, 'V3 public insights boundaries');
  assertSameJson(insights.boundaries, manifest.boundaries, 'V3 public insights/manifest boundaries');
  assertCoverageContract({ ...insights, source_snapshot_id: manifest.source_snapshot_id }, 'V3 public insights');
  assertSameJson(
    insights.comparison_unavailable_reason_codes ?? [],
    manifest.comparison_unavailable_reason_codes ?? [],
    'V3 public insights/manifest 比较不可用原因',
  );
  assertSameJson(insights.coverage_attestation, manifest.coverage_attestation, 'V3 public insights/manifest coverage');
  assertContract(
    insights.data_owner_coverage_attestation_sha256 === manifest.data_owner_coverage_attestation_sha256,
    'V3 public insights coverage SHA 漂移',
  );
  assertStorylineSummary(insights.storyline_summary, 'V3 public insights storyline summary');
  assertSameJson(insights.storyline_summary, manifest.storyline_summary, 'V3 public insights/manifest 故事线统计');
  assertContract(insights.storyline_count === 78 && insights.storylines.length === 78, 'V3 public insights 故事线数量异常');

  assertExactKeys(insights.interpretation_boundaries, [
    'brand_health_null_when_classification_coverage_insufficient',
    'direction_requires_precomputed_comparable_complete_periods',
    'front_end_recomputation_supported',
    'root_cause_requires_same_snapshot_evidence',
    'sales_causality_supported',
    'unavailable_metric_direction_supported',
  ], 'V3 public insights interpretation boundaries');
  const interpretation = insights.interpretation_boundaries;
  assertContract(
    interpretation.brand_health_null_when_classification_coverage_insufficient === true
      && interpretation.direction_requires_precomputed_comparable_complete_periods === true
      && interpretation.front_end_recomputation_supported === false
      && interpretation.root_cause_requires_same_snapshot_evidence === true
      && interpretation.sales_causality_supported === false
      && interpretation.unavailable_metric_direction_supported === false,
    'V3 public insights 解释边界异常',
  );

  assertExactKeys(insights.source, [
    'coverage_attestation_sha256',
    'metrics_candidate_manifest_sha256',
    'metrics_input_manifest_sha256',
    'metrics_validation_receipt_sha256',
    'report_manifest_sha256',
    'report_validation_receipt_sha256',
    'source_snapshot_id',
  ], 'V3 public insights source');
  assertContract(
    insights.source.source_snapshot_id === manifest.source_snapshot_id
      && insights.source.coverage_attestation_sha256 === manifest.data_owner_coverage_attestation_sha256
      && insights.source.metrics_candidate_manifest_sha256 === receipt.metrics_candidate_manifest_sha256
      && insights.source.metrics_input_manifest_sha256 === receipt.metrics_input_manifest_sha256
      && insights.source.metrics_validation_receipt_sha256 === receipt.metrics_validation_receipt_sha256
      && insights.source.report_manifest_sha256 === receipt.report_manifest_sha256
      && insights.source.report_validation_receipt_sha256 === receipt.report_validation_receipt_sha256,
    'V3 public insights source lineage 漂移',
  );

  assertExactKeys(insights.brand_health, GRAINS, 'V3 public insights brand health');
  GRAINS.forEach((grain) => {
    const period = insights.brand_health[grain];
    assertRecord(period, `V3 brand health ${grain}`);
    const periodKeys = Object.keys(period).sort();
    const expectedPeriodKeys = (
      Object.hasOwn(period, 'dimension_rows')
        ? ['dimension_rows', 'metric_id', 'rows', 'scope']
        : ['metric_id', 'rows', 'scope']
    ).sort();
    assertContract(
      periodKeys.length === expectedPeriodKeys.length
        && periodKeys.every((key, index) => key === expectedPeriodKeys[index]),
      `V3 brand health ${grain}字段集合异常`,
    );
    if (Object.hasOwn(period, 'dimension_rows')) {
      assertContract(
        Array.isArray(period.dimension_rows) && period.dimension_rows.length === 8,
        `V3 brand health ${grain}维度双口径不完整`,
      );
      assertPrivacySafe(period.dimension_rows, `V3 brand health ${grain}.dimension_rows`);
    }
    assertContract(
      period.metric_id === 'brand_health_index_v2'
        && period.scope === 'momcozy'
        && Array.isArray(period.rows)
        && period.rows.length === 2,
      `V3 brand health ${grain}口径异常`,
    );
    const sides = period.rows.map((row, index) => validateBrandHealthRow(
      row,
      grain,
      manifest,
      `V3 brand health ${grain}[${index}]`,
    ).comparison_side).sort();
    assertContract(sides.join(',') === 'qualified_organic,raw_observed', `V3 brand health ${grain}双口径不完整`);
  });

  const uniqueGrainMetric = new Set<string>();
  let supportedDirections = 0;
  insights.storylines.forEach((storylineValue, index) => {
    const storyline = validateStoryline(storylineValue, `V3 storyline[${index}]`);
    const key = `${storyline.grain}:${storyline.metric_id}`;
    assertContract(!uniqueGrainMetric.has(key), `V3 故事线粒度重复：${key}`);
    uniqueGrainMetric.add(key);
    if (storyline.direction_claim_supported) supportedDirections += 1;
  });
  assertContract(uniqueGrainMetric.size === METRIC_IDS.length * GRAINS.length, 'V3 故事线 grain × metric 不守恒');
  GRAINS.forEach((grain) => METRIC_IDS.forEach((metricId) => {
    assertContract(uniqueGrainMetric.has(`${grain}:${metricId}`), `V3 故事线缺失：${grain}/${metricId}`);
  }));
  assertContract(supportedDirections === insights.storyline_summary.direction_supported, 'V3 故事线方向支持计数漂移');
  return insights;
}

export function validateV3InsightsSnapshot(
  manifestValue: unknown,
  embeddedReceiptValue: unknown,
  publicValidationReceiptValue: unknown,
  insightsValue: unknown,
  release: CurrentRelease,
): V3RedditInsightsSnapshot {
  const manifest = validateV3InsightsManifest(manifestValue, release);
  const receipt = validateEmbeddedReceipt(embeddedReceiptValue, manifest);
  const publicValidationReceipt = validatePublicValidationReceipt(publicValidationReceiptValue, manifest, release);
  const insights = validateV3PublicInsightsData(insightsValue, manifest, receipt);
  return { release, manifest, receipt, publicValidationReceipt, insights };
}

async function sha256Text(raw: string): Promise<string> {
  assertContract(globalThis.crypto?.subtle, '当前浏览器不支持 V3 洞察完整性校验');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function fetchVerifiedJson<T>(
  basePath: string,
  filename: string,
  integrity: FileIntegrity,
  forceReload: boolean,
): Promise<T> {
  const response = await fetch(`${basePath}/${filename}`, {
    cache: forceReload ? 'reload' : 'no-cache',
  });
  if (!response.ok) {
    throw new V3InsightsContractError(`V3 洞察文件加载失败：${filename}（HTTP ${response.status}）`);
  }
  const raw = await response.text();
  assertContract(new TextEncoder().encode(raw).byteLength === integrity.bytes, `V3 洞察文件 bytes 不一致：${filename}`);
  assertContract((await sha256Text(raw)) === integrity.sha256, `V3 洞察文件 SHA-256 不一致：${filename}`);
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new V3InsightsContractError(`V3 洞察文件不是有效 JSON：${filename}`);
  }
}

export async function loadRedditV3Insights(
  manifestValue: unknown,
  release: CurrentRelease,
  forceReload = false,
): Promise<V3RedditInsightsSnapshot> {
  const manifest = validateV3InsightsManifest(manifestValue, release);
  const publicValidationIntegrity = VALIDATED_PUBLIC_WRAPPERS[release.datasets.insights.public_manifest_sha256];
  assertContract(Boolean(publicValidationIntegrity), 'V3 洞察 public manifest 未进入受控验证 allowlist');
  const basePath = getReleaseDatasetBasePath(release, 'insights');
  const [insights, receipt, publicValidationReceipt] = await Promise.all([
    fetchVerifiedJson<unknown>(basePath, 'insights.json', manifest.files['insights.json'], forceReload),
    fetchVerifiedJson<unknown>(basePath, 'validation-receipt.json', manifest.files['validation-receipt.json'], forceReload),
    fetchVerifiedJson<unknown>(basePath, PUBLIC_VALIDATION_SIDECAR, publicValidationIntegrity, forceReload),
  ]);
  return validateV3InsightsSnapshot(manifest, receipt, publicValidationReceipt, insights, release);
}
