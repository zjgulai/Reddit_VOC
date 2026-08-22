import type {
  InsightsAuditSummary,
  InsightsData,
  InsightsManifest,
  InsightsSemanticAudit,
  RiskInsightsData,
  RiskShareMetric,
  RiskTheme,
  RedditInsightsSnapshot,
  RedditSnapshotCore,
  RedditSnapshotSummary,
  SnapshotAggregates,
  SnapshotComment,
  SnapshotCommentTranslation,
  SnapshotCoverageGrade,
  SnapshotManifest,
  SnapshotPost,
  SnapshotPostTranslation,
  SnapshotProductBinding,
  SnapshotProductCoverage,
  SnapshotProductResolution,
  SnapshotTagDictionary,
} from './types';
import {
  fetchVerifiedReleaseManifest,
  getReleaseDatasetBasePath,
  loadCurrentRelease,
  type CurrentRelease,
} from './release';

export const SNAPSHOT_MANIFEST_SCHEMA_V1 = 'reddit_voc_site_snapshot_manifest_v1';
export const SNAPSHOT_MANIFEST_SCHEMA_V2 = 'reddit_voc_site_snapshot_manifest_v2';
export const SNAPSHOT_MANIFEST_SCHEMA_V3 = 'reddit_voc_site_snapshot_manifest_v3';
export const SNAPSHOT_MANIFEST_SCHEMA = SNAPSHOT_MANIFEST_SCHEMA_V1;
export const INSIGHTS_MANIFEST_SCHEMA = 'reddit_voc_insights_manifest_v1';
export const RISK_INSIGHTS_SCHEMA = 'reddit_voc_insights_v2';

const SNAPSHOT_MANIFEST_SCHEMAS = new Set([
  SNAPSHOT_MANIFEST_SCHEMA_V1,
  SNAPSHOT_MANIFEST_SCHEMA_V2,
  SNAPSHOT_MANIFEST_SCHEMA_V3,
]);
const LEGACY_SNAPSHOT_COVERAGE_GRADES = ['full', 'partial', 'post_only'] as const;
const V3_SNAPSHOT_COVERAGE_GRADES = [...LEGACY_SNAPSHOT_COVERAGE_GRADES, 'source_observed'] as const;
const PRODUCT_RESOLVER_VERSION = 'product-entity-resolver-v1';
const PRODUCT_LEDGER_VERSION = 'momcozy-product-entity-ledger-2026-07-15.v1';
const PRODUCT_LEDGER_SHA256 = 'cc66f565d64c19d0624baf9821ff4e765c692c8d85b8a4d7368214ab555451ab';

const EXPECTED_PROMOTED_TAG_IDS = new Set(['L0-GEN-075', 'L0-GEN-103']);
const EXPECTED_SNAPSHOT_FILES = new Set([
  'aggregates-public.json',
  'comments-public.json',
  'posts-public.json',
  'tag-dictionary-public.json',
]);
const TRANSLATION_SIDECAR_FILES = [
  'post-translations-public.json',
  'comment-translations-public.json',
] as const;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const SAFE_AUTHORIZATION_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{2,127}$/;

interface PostTranslationRow {
  post_id: string;
  title_zh: string;
  content_zh: string;
  title_input_sha256: string;
  content_input_sha256: string;
  title_quality_status: 'deterministic_passed_unreviewed';
  content_quality_status: 'deterministic_passed_unreviewed';
}

interface CommentTranslationRow {
  comment_id: string;
  post_id: string;
  zh: string;
  input_sha256: string;
  provider: 'deepseek';
  quality_status: 'deterministic_passed_unreviewed';
}

interface TranslationSidecar<T> {
  schema_version: 'reddit_voc_public_translations_v1';
  dataset_version: string;
  source_dataset_version: string;
  generated_at_utc: string;
  provider: 'deepseek';
  model: 'deepseek-v4-flash';
  quality_gate: 'deterministic_contract_v1';
  semantic_validation: 'not_run';
  independent_human_review: false;
  entity_type: 'post' | 'comment';
  items: T[];
}

export class SnapshotContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SnapshotContractError';
  }
}

let corePromise: Promise<RedditSnapshotCore> | null = null;
let summaryPromise: Promise<RedditSnapshotSummary> | null = null;
let commentsPromise: Promise<SnapshotComment[]> | null = null;
let insightsPromise: Promise<RedditInsightsSnapshot> | null = null;

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new SnapshotContractError(message);
}

async function sha256Text(raw: string): Promise<string> {
  assertContract(globalThis.crypto?.subtle, '当前浏览器不支持数据文件完整性校验');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function fetchVerifiedJson<T>(
  basePath: string,
  filename: string,
  integrity: { bytes: number; sha256: string },
  label: string,
): Promise<T> {
  const response = await fetch(`${basePath}/${filename}`, { cache: 'force-cache' });
  if (!response.ok) {
    throw new SnapshotContractError(`${label}加载失败：${filename}（HTTP ${response.status}）`);
  }
  const raw = await response.text();
  assertContract(new TextEncoder().encode(raw).byteLength === integrity.bytes, `${label}bytes 不一致：${filename}`);
  assertContract((await sha256Text(raw)) === integrity.sha256, `${label}SHA-256 不一致：${filename}`);
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new SnapshotContractError(`${label}不是有效 JSON：${filename}`);
  }
}

function assertSnapshotFileManifest(manifest: SnapshotManifest): void {
  const filenames = Object.keys(manifest.files);
  const expectedFiles = new Set(EXPECTED_SNAPSHOT_FILES);
  if (manifest.translations) {
    TRANSLATION_SIDECAR_FILES.forEach((filename) => expectedFiles.add(filename));
  }
  assertContract(
    filenames.length === expectedFiles.size
      && filenames.every((filename) => expectedFiles.has(filename)),
    '快照公开文件集合异常',
  );
  for (const filename of filenames) {
    const integrity = manifest.files[filename];
    assertContract(Number.isInteger(integrity.bytes) && integrity.bytes > 0, `快照文件 bytes 异常：${filename}`);
    assertContract(/^[a-f0-9]{64}$/.test(integrity.sha256), `快照文件 SHA-256 异常：${filename}`);
  }
}

function assertBoundaryContract(boundaries: InsightsManifest['boundaries'], label: string): void {
  assertContract(boundaries.scope === 'top_10_aspect_tags_stratified_assignment_review', `${label}复核范围异常`);
  assertContract(boundaries.labels_outside_promoted_set_provisional === true, `${label}未保持未晋级标签边界`);
  assertContract(boundaries.independent_human_review === false, `${label}错误声称独立人工复核`);
  assertContract(boundaries.production_unchanged === true, `${label}缺少 production unchanged 边界`);
  assertContract(
    boundaries.provider_call === false && boundaries.database_write === false && boundaries.live_send === false,
    `${label}外部副作用边界异常`,
  );
}

export function isRiskInsightsData(insights: InsightsData): insights is RiskInsightsData {
  return insights.schema_version === RISK_INSIGHTS_SCHEMA;
}

function assertSameSummary(
  actual: InsightsAuditSummary,
  expected: InsightsAuditSummary,
  label: string,
): void {
  const fields = ['audited_tags', 'reviewed_assignments', 'promoted_tags', 'held_tags', 'status'] as const;
  for (const field of fields) {
    assertContract(actual[field] === expected[field], `${label}${field} 不一致`);
  }
  assertContract(
    new Set(actual.promoted_tag_ids).size === actual.promoted_tag_ids.length
      && actual.promoted_tag_ids.length === expected.promoted_tag_ids.length
      && actual.promoted_tag_ids.every((tagId) => expected.promoted_tag_ids.includes(tagId)),
    `${label}晋级标签集合不一致`,
  );
  assertContract(
    new Set(actual.held_tag_ids).size === actual.held_tag_ids.length
      && actual.held_tag_ids.length === expected.held_tag_ids.length
      && actual.held_tag_ids.every((tagId) => expected.held_tag_ids.includes(tagId)),
    `${label}暂缓标签集合不一致`,
  );
}

function assertInsightsManifest(
  core: RedditSnapshotCore,
  manifest: InsightsManifest,
  release: CurrentRelease,
): void {
  const binding = release.datasets.insights;
  assertContract(manifest.schema_version === INSIGHTS_MANIFEST_SCHEMA, '洞察 manifest schema 不受支持');
  assertContract(manifest.dataset_version === binding.dataset_version, '洞察版本与 current release 不一致');
  assertContract(manifest.delivery_mode === 'versioned_static_insights_overlay', '洞察交付模式异常');
  if (manifest.contract_extension === 'reddit_voc_insights_manifest_v2') {
    assertContract(
      manifest.status === 'passed'
        || manifest.status === 'passed_with_comparison_coverage_limits'
        || manifest.status === 'passed_provisional_risk_threshold',
      'v2 洞察覆盖层门禁状态异常',
    );
  } else {
    assertContract(manifest.status === 'passed_with_scope_limits', '洞察覆盖层未通过有限范围门禁');
  }
  assertContract(
    core.manifest.dataset_version === release.datasets.base.dataset_version,
    '基础快照版本与 current release 不一致',
  );
  assertContract(manifest.base_dataset_version === core.manifest.dataset_version, '洞察与基础快照版本不一致');
  assertContract(
    manifest.base_manifest_sha256 === release.datasets.base.lineage_manifest_sha256,
    '洞察未绑定 current release 基础 lineage',
  );
  assertContract(manifest.dictionary_version === core.tagDictionary.dictionary_version, '洞察字典版本不一致');
  assertContract(manifest.dictionary_sha256 === core.tagDictionary.dictionary_sha256, '洞察字典哈希不一致');
  assertContract(Boolean(manifest.files) && typeof manifest.files === 'object', '洞察 manifest files 异常');
  assertContract(
    Object.keys(manifest.files).sort().join(',') === 'insights.json,semantic-audit.json',
    '洞察文件集合异常',
  );
  for (const filename of ['insights.json', 'semantic-audit.json']) {
    const integrity = manifest.files[filename];
    assertContract(Boolean(integrity), `洞察文件完整性声明缺失：${filename}`);
    assertContract(integrity.bytes > 0, `洞察文件字节数异常：${filename}`);
    assertContract(/^[a-f0-9]{64}$/.test(integrity.sha256), `洞察文件哈希异常：${filename}`);
  }
  if (manifest.contract_extension === 'reddit_voc_insights_manifest_v2') {
    assertContract(manifest.boundaries.scope === 'momcozy_risk_command_center_and_report_booklets', 'v2 洞察范围异常');
    assertContract(manifest.boundaries.production_unchanged === true, 'v2 洞察缺少 production unchanged');
    assertContract(
      manifest.boundaries.provider_call === false
        && manifest.boundaries.database_write === false
        && manifest.boundaries.live_send === false
        && manifest.boundaries.deploy === false,
      'v2 洞察外部副作用边界异常',
    );
    assertContract(manifest.audit_summary.reviewed_assignments === null, 'v2 洞察错误声称原始人工复核量');
  } else {
    assertBoundaryContract(manifest.boundaries, 'manifest');
  }
}

const RISK_PRIORITIES = new Set(['P0', 'P1', 'P2', 'P3', 'insufficient']);
const CONTROLLED_BINDINGS = new Set([
  'brand_unbound',
  'competitor_sentence_bound',
  'momcozy_entity_reviewed',
  'momcozy_sentence_bound',
  'multi_brand_context',
]);
const PUBLIC_RISK_THEME_FORBIDDEN_FIELDS = [
  'biz_action',
  'business_impact',
  'dept_owner',
  'dictionary_default_priority',
  'strategy_package',
  'suggested_action',
] as const;

function assertNonNegativeInteger(value: unknown, label: string): asserts value is number {
  assertContract(Number.isInteger(value) && Number(value) >= 0, `${label}必须是非负整数`);
}

function assertRiskShare(metric: RiskShareMetric, label: string): void {
  assertContract(
    metric.metric === 'negative_momcozy_observed_entities_over_classified_momcozy_observed_entities',
    `${label}指标名称异常`,
  );
  assertContract(metric.value === null || (metric.value >= 0 && metric.value <= 1), `${label}占比异常`);
  if (metric.denominator !== null) assertNonNegativeInteger(metric.denominator, `${label}分母`);
  if (metric.numerator !== null) assertNonNegativeInteger(metric.numerator, `${label}分子`);
}

function assertCombinedUnsupported(metric: { supported: false; reason: string; value: null }, label: string): void {
  assertContract(metric.supported === false && metric.value === null && Boolean(metric.reason), `${label}错误合并帖子与评论`);
}

function assertPublicRiskTheme(theme: RiskTheme, label: string): void {
  assertContract(Boolean(theme.risk_theme_id) && theme.risk_theme_id === theme.tag_id, `${label}ID 异常`);
  assertContract(RISK_PRIORITIES.has(theme.effective_priority), `${label}优先级异常`);
  assertContract(
    (theme.evidence_gate.status === 'passed') === (theme.effective_priority !== 'insufficient'),
    `${label}证据门禁与优先级不一致`,
  );
  assertContract(theme.evidence_refs.length <= 20, `${label}证据引用超过公开上限`);
  assertContract(theme.evidence_ref_count_total >= theme.evidence_refs.length, `${label}证据引用总数异常`);
  const evidenceKeys = new Set<string>();
  theme.evidence_refs.forEach((evidence) => {
    const key = `${evidence.entity_type}:${evidence.entity_id}`;
    assertContract(!evidenceKeys.has(key), `${label}证据引用重复`);
    evidenceKeys.add(key);
    assertContract(Boolean(evidence.post_id), `${label}证据引用缺少帖子检索 ID`);
    assertContract(Object.keys(evidence).sort().join(',') === 'entity_id,entity_type,post_id', `${label}公开证据引用字段集合异常`);
  });
  const record = theme as unknown as Record<string, unknown>;
  PUBLIC_RISK_THEME_FORBIDDEN_FIELDS.forEach((field) => {
    assertContract(!(field in record), `${label}公开投影包含内部字段：${field}`);
  });
}

function validateRiskInsightsOverlay(
  core: RedditSnapshotCore,
  manifest: InsightsManifest,
  audit: InsightsSemanticAudit,
  insights: RiskInsightsData,
): RedditInsightsSnapshot {
  assertContract(audit.schema_version === 'reddit_voc_tag_semantic_audit_v2', 'v2 语义治理投影 schema 不受支持');
  assertContract(audit.audit_version === manifest.semantic_governance_version, 'v2 语义治理版本不一致');
  assertContract(audit.base_dataset_version === manifest.base_dataset_version, 'v2 语义治理基础版本不一致');
  assertContract(audit.base_manifest_sha256 === manifest.base_manifest_sha256, 'v2 语义治理基础哈希不一致');
  assertContract(audit.dictionary_version === manifest.dictionary_version && audit.dictionary_sha256 === manifest.dictionary_sha256, 'v2 语义治理字典绑定不一致');
  assertContract(audit.boundaries.raw_review_samples_included === false, 'v2 语义治理公开投影包含原始复核样本');
  const auditRecord = audit as unknown as Record<string, unknown>;
  assertContract(!('tags' in auditRecord) && !('reviewer' in auditRecord) && !('quality_gate' in auditRecord), 'v2 语义治理投影越过公开边界');
  assertContract(audit.summary.promoted_tags === manifest.audit_summary.promoted_tags, 'v2 晋级标签数不一致');
  assertContract(audit.summary.held_tags === manifest.audit_summary.held_tags, 'v2 暂缓标签数不一致');
  assertContract(
    audit.summary.promoted_tag_ids.join(',') === manifest.audit_summary.promoted_tag_ids.join(','),
    'v2 晋级标签集合不一致',
  );
  assertContract(
    audit.summary.held_tag_ids.join(',') === manifest.audit_summary.held_tag_ids.join(','),
    'v2 暂缓标签集合不一致',
  );

  assertContract(insights.dataset_version === manifest.dataset_version, 'v2 洞察实体版本不一致');
  assertContract(insights.base_dataset_version === manifest.base_dataset_version, 'v2 洞察基础版本不一致');
  assertContract(insights.boundaries.scope === 'momcozy_risk_command_center_and_report_booklets', 'v2 洞察范围异常');
  assertContract(insights.boundaries.production_unchanged === true && insights.boundaries.deploy === false, 'v2 洞察运行边界异常');
  assertContract(
    insights.interpretation_boundaries.market_share_supported === false
      && insights.interpretation_boundaries.roi_supported === false
      && insights.interpretation_boundaries.nps_supported === false
      && insights.interpretation_boundaries.response_time_supported === false
      && insights.interpretation_boundaries.posts_and_comments_separate_by_default === true
      && insights.interpretation_boundaries.combined_view_supported === false
      && insights.interpretation_boundaries.competitors_are_context_only === true
      && insights.interpretation_boundaries.consumer_card_is_reference_not_user_identity === true,
    'v2 洞察解释边界异常',
  );
  assertContract(insights.input_contract.status === 'passed', 'v2 输入契约未通过');
  assertContract(insights.input_contract.required_event_time_field === 'event_created_at_utc', 'v2 事件时间字段异常');
  assertContract(
    insights.input_contract.brand_binding_values.length === CONTROLLED_BINDINGS.size
      && insights.input_contract.brand_binding_values.every((binding) => CONTROLLED_BINDINGS.has(binding)),
    'v2 主体绑定枚举异常',
  );
  assertNonNegativeInteger(insights.input_contract.post_count, 'v2 输入帖子数');
  assertNonNegativeInteger(insights.input_contract.comment_count, 'v2 输入评论数');

  const command = insights.risk_command_center;
  assertContract(command.decision_subject.brand_id === 'momcozy' && command.decision_subject.brand_role === 'primary', 'v2 洞察主干不是 Momcozy');
  assertContract(command.decision_subject.competitors_role === 'comparison_context_only', 'v2 竞品角色异常');
  assertCombinedUnsupported(command.primary_kpis.negative_evidence_share.combined, 'v2 风险中心负面占比');
  assertRiskShare(command.primary_kpis.negative_evidence_share.post, 'v2 风险中心帖子负面占比');
  assertRiskShare(command.primary_kpis.negative_evidence_share.comment, 'v2 风险中心评论负面占比');
  assertContract(command.primary_kpis.high_priority_risk_themes.value === null || Number.isInteger(command.primary_kpis.high_priority_risk_themes.value), 'v2 高优先级风险数异常');
  Object.entries(command.priority_distribution).forEach(([priority, value]) => {
    assertContract(RISK_PRIORITIES.has(priority), `v2 风险优先级枚举异常：${priority}`);
    assertNonNegativeInteger(value, `v2 ${priority} 风险数`);
  });
  command.risk_themes.forEach((theme, index) => assertPublicRiskTheme(theme, `v2 风险主题 ${index}`));
  assertContract(new Set(command.risk_themes.map((theme) => theme.risk_theme_id)).size === command.risk_themes.length, 'v2 风险主题 ID 重复');

  const product = insights.product_analysis;
  assertContract(product.decision_subject === 'momcozy' && product.scope_order.join(',') === 'category,product_family,spu_exact', 'v2 产品分析主干或层级异常');
  (['category', 'product_family', 'spu_exact'] as const).forEach((level) => {
    const rows = product[level];
    assertContract(new Set(rows.map((row) => row.scope_id)).size === rows.length, `v2 ${level} 产品范围重复`);
    rows.forEach((row) => {
      assertContract(row.binding_level === level, `v2 ${level} 绑定层级异常`);
      assertCombinedUnsupported(row.metrics.combined, `v2 ${level}/${row.scope_id}`);
      assertRiskShare(row.metrics.post, `v2 ${level}/${row.scope_id}/帖子`);
      assertRiskShare(row.metrics.comment, `v2 ${level}/${row.scope_id}/评论`);
    });
  });
  command.competitor_context.forEach((competitor) => {
    assertContract(competitor.comparison_role === 'same_observed_sample_context', `v2 竞品 ${competitor.brand_id} 比较角色异常`);
    assertContract(competitor.interpretation_boundary === 'comparison_is_not_market_share_sov_penetration_or_sales', `v2 竞品 ${competitor.brand_id} 解释边界异常`);
  });

  const control = insights.control_evidence;
  assertContract(control.base_dataset_version === core.manifest.dataset_version, 'v2 C 控制证据基础版本不一致');
  assertContract(control.recommendations_only === true && control.action_completion_supported === false, 'v2 C 控制证据错误支持执行完成');
  assertContract(control.release_switch_executed === false && control.production_unchanged === true, 'v2 C 控制证据错误声称发布切换');
  assertContract(
    control.provider_call === false && control.database_write === false && control.live_send === false && control.deploy === false,
    'v2 C 控制证据外部副作用异常',
  );
  return { core, manifest, audit, insights };
}

export function validateInsightsOverlay(
  core: RedditSnapshotCore,
  manifest: InsightsManifest,
  audit: InsightsSemanticAudit,
  insights: InsightsData,
  release: CurrentRelease,
): RedditInsightsSnapshot {
  assertInsightsManifest(core, manifest, release);

  if (manifest.contract_extension === 'reddit_voc_insights_manifest_v2') {
    assertContract(isRiskInsightsData(insights), 'v2 manifest 未绑定 v2 洞察实体');
    return validateRiskInsightsOverlay(core, manifest, audit, insights);
  }
  assertContract(!isRiskInsightsData(insights), 'v1 manifest 错误绑定 v2 洞察实体');

  assertContract(audit.schema_version === 'reddit_voc_tag_semantic_audit_v1', '语义复核 schema 不受支持');
  assertContract(audit.audit_version === manifest.dataset_version, '语义复核版本不一致');
  assertContract(audit.base_dataset_version === manifest.base_dataset_version, '语义复核基础版本不一致');
  assertContract(audit.base_manifest_sha256 === manifest.base_manifest_sha256, '语义复核基础哈希不一致');
  assertContract(audit.dictionary_version === manifest.dictionary_version, '语义复核字典版本不一致');
  assertContract(audit.dictionary_sha256 === manifest.dictionary_sha256, '语义复核字典哈希不一致');
  assertContract(Boolean(audit.sample_sha256) && /^[a-f0-9]{64}$/.test(audit.sample_sha256), '语义复核样本哈希异常');
  assertContract(Boolean(audit.reviewer) && audit.reviewer.independent_human_review === false, '语义复核错误声称独立人工审核');
  assertContract(Boolean(audit.quality_gate), '语义复核缺少质量门禁');
  assertContract(Array.isArray(audit.tags), '语义复核缺少标签样本');
  assertSameSummary(audit.summary, manifest.audit_summary, 'audit/manifest ');
  assertBoundaryContract(audit.boundaries as InsightsManifest['boundaries'], 'audit');

  const summary = manifest.audit_summary;
  assertContract(summary.audited_tags === 10, '当前洞察版本应复核 10 个标签');
  assertContract(summary.reviewed_assignments === 100, '当前洞察版本应包含 100 条复核');
  assertContract(summary.promoted_tags === 2 && summary.held_tags === 8, '洞察晋级/暂缓数量异常');
  assertContract(
    summary.promoted_tag_ids.length === EXPECTED_PROMOTED_TAG_IDS.size
      && summary.promoted_tag_ids.every((tagId) => EXPECTED_PROMOTED_TAG_IDS.has(tagId)),
    '洞察晋级标签不是当前发布集合',
  );
  assertContract(audit.tags.length === summary.audited_tags, '语义复核标签数不一致');
  assertContract(
    audit.tags.reduce((total, tag) => total + tag.samples.length, 0) === summary.reviewed_assignments,
    '语义复核样本数不一致',
  );
  const auditPromoted = audit.tags.filter((tag) => tag.promotion_status === 'promoted');
  const auditHeld = audit.tags.filter((tag) => tag.promotion_status === 'held');
  assertContract(auditPromoted.every((tag) => Object.values(tag.gate_checks).every(Boolean)), '晋级标签存在失败门禁');
  assertContract(auditHeld.every((tag) => Object.values(tag.gate_checks).some((passed) => !passed)), '暂缓标签意外通过全部门禁');
  assertContract(
    audit.tags.every((tag) => tag.samples.every((sample) => sample.review.reason_code !== 'pending')),
    '语义复核仍有 pending 决策',
  );

  assertContract(insights.schema_version === 'reddit_voc_insights_v1', '洞察 schema 不受支持');
  assertContract(insights.dataset_version === manifest.dataset_version, '洞察实体版本不一致');
  assertContract(insights.base_dataset_version === manifest.base_dataset_version, '洞察实体基础版本不一致');
  assertBoundaryContract(insights.boundaries, 'insights');
  assertContract(insights.headline.audited_tags === summary.audited_tags, '洞察复核标签数不一致');
  assertContract(insights.headline.reviewed_assignments === summary.reviewed_assignments, '洞察复核分配数不一致');
  assertContract(insights.headline.promoted_tags === summary.promoted_tags, '洞察晋级数不一致');
  assertContract(insights.headline.held_tags === summary.held_tags, '洞察暂缓数不一致');

  const signalIds = new Set(insights.signals.map((signal) => signal.tag_id));
  const heldIds = new Set(insights.held_tags.map((tag) => tag.tag_id));
  assertContract(
    signalIds.size === summary.promoted_tag_ids.length
      && summary.promoted_tag_ids.every((tagId) => signalIds.has(tagId)),
    '页面洞察包含未晋级标签或缺少晋级标签',
  );
  assertContract(
    heldIds.size === summary.held_tag_ids.length && summary.held_tag_ids.every((tagId) => heldIds.has(tagId)),
    '页面暂缓标签集合不一致',
  );
  const baseTags = new Map(core.aggregates.tagging.top_tags.map((tag) => [tag.tag_id, tag]));
  for (const signal of insights.signals) {
    const baseTag = baseTags.get(signal.tag_id);
    assertContract(baseTag, `洞察标签不在基础快照高频标签中：${signal.tag_id}`);
    assertContract(signal.matched_posts === baseTag.post_entities, `洞察帖子计数漂移：${signal.tag_id}`);
    assertContract(signal.matched_comments === baseTag.comment_entities, `洞察评论计数漂移：${signal.tag_id}`);
    assertContract(signal.matched_entities === baseTag.total_entities, `洞察实体计数漂移：${signal.tag_id}`);
    assertContract(signal.evidence_examples.length > 0, `洞察标签缺少证据：${signal.tag_id}`);
    assertContract(signal.dictionary_reference.consumer_card.length > 0, `洞察标签缺少 consumer_card：${signal.tag_id}`);
    assertContract(signal.dictionary_reference.aipl_node.length > 0, `洞察标签缺少 AIPL：${signal.tag_id}`);
  }
  assertContract(
    insights.headline.promoted_rule_assignments
      === insights.signals.reduce((total, signal) => total + signal.matched_entities, 0),
    '洞察规则分配总数不一致',
  );
  assertContract(insights.held_tags.every((tag) => tag.failed_checks.length > 0), '暂缓标签缺少失败检查');

  const referenceFields = ['consumer_card', 'aipl_node', 'story_lines', 'intent_type', 'problem_type'] as const;
  for (const field of referenceFields) {
    const expected = new Map<string, number>();
    for (const signal of insights.signals) {
      const value = signal.dictionary_reference[field];
      expected.set(value, (expected.get(value) ?? 0) + signal.matched_entities);
    }
    const actual = insights.reference_dimensions[field];
    assertContract(actual && Object.keys(actual).length === expected.size, `画像参考维度异常：${field}`);
    for (const [value, count] of expected) {
      assertContract(actual[value] === count, `画像参考维度计数漂移：${field}/${value}`);
    }
  }

  const interpretation = insights.interpretation_boundaries;
  assertContract(interpretation.counts_are_rule_matched_entities_not_users === true, '洞察错误把实体数解释为用户数');
  assertContract(
    interpretation.promoted_means_sample_gate_passed_not_full_population_human_review === true,
    '洞察错误声称全量人工复核',
  );
  assertContract(interpretation.consumer_card_is_reference_not_persona_id === true, '洞察画像参考边界缺失');
  assertContract(interpretation.persona_tags_generated === false, '洞察错误声称已生成用户画像标签');
  assertContract(
    interpretation.market_share_supported === false
      && interpretation.roi_supported === false
      && interpretation.trend_claim_supported === false,
    '洞察包含当前版本不支持的业务推断',
  );

  return { core, manifest, audit, insights };
}

async function loadInsightsUncached(): Promise<RedditInsightsSnapshot> {
  const releasePromise = loadCurrentRelease();
  const corePromise = loadRedditSnapshot();
  const release = await releasePromise;
  const [core, manifest] = await Promise.all([
    corePromise,
    fetchVerifiedReleaseManifest<InsightsManifest>(release, 'insights'),
  ]);
  const basePath = getReleaseDatasetBasePath(release, 'insights');
  assertInsightsManifest(core, manifest, release);
  const [auditFile, insightsFile] = await Promise.all([
    fetchVerifiedJson<InsightsSemanticAudit>(
      basePath,
      'semantic-audit.json',
      manifest.files['semantic-audit.json'],
      '洞察数据文件',
    ),
    fetchVerifiedJson<InsightsData>(
      basePath,
      'insights.json',
      manifest.files['insights.json'],
      '洞察数据文件',
    ),
  ]);
  return validateInsightsOverlay(core, manifest, auditFile, insightsFile, release);
}

export function loadRedditInsights(): Promise<RedditInsightsSnapshot> {
  insightsPromise ??= loadInsightsUncached();
  return insightsPromise;
}

function assertExactObjectKeys(value: unknown, expected: readonly string[], label: string): asserts value is Record<string, unknown> {
  assertContract(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `${label}必须是对象`);
  const actual = Object.keys(value as Record<string, unknown>).sort();
  assertContract(actual.join(',') === [...expected].sort().join(','), `${label}字段集合异常`);
}

function assertNonEmptyString(value: unknown, label: string): asserts value is string {
  assertContract(typeof value === 'string' && value.trim().length > 0, `${label}必须是非空字符串`);
}

function assertCountMap(value: unknown, label: string): asserts value is Record<string, number> {
  assertContract(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `${label}必须是计数字典`);
  Object.entries(value as Record<string, unknown>).forEach(([key, count]) => {
    assertNonEmptyString(key, `${label}键`);
    assertNonNegativeInteger(count, `${label}.${key}`);
  });
}

function sumCounts(value: Record<string, number>): number {
  return Object.values(value).reduce((total, count) => total + count, 0);
}

function mergeCountMaps(left: Record<string, number>, right: Record<string, number>): Record<string, number> {
  const merged: Record<string, number> = { ...left };
  Object.entries(right).forEach(([key, count]) => {
    merged[key] = (merged[key] ?? 0) + count;
  });
  return merged;
}

const PRODUCT_COVERAGE_FIELDS = [
  'input_record_count',
  'bound_record_count',
  'unbound_record_count',
  'multi_binding_record_count',
  'binding_count',
  'exact_spu_binding_count',
  'family_only_binding_count',
  'category_only_binding_count',
  'taxonomy_blocked_binding_count',
  'category_binding_counts',
  'family_binding_counts',
  'is_conserved',
] as const;

function assertProductCoverage(value: unknown, layer: string): SnapshotProductCoverage {
  const label = `v2 产品覆盖账本：${layer}`;
  assertExactObjectKeys(value, PRODUCT_COVERAGE_FIELDS, label);
  const coverage = value as unknown as SnapshotProductCoverage;
  const numericFields = PRODUCT_COVERAGE_FIELDS.filter(
    (field) => field !== 'category_binding_counts' && field !== 'family_binding_counts' && field !== 'is_conserved',
  );
  numericFields.forEach((field) => assertNonNegativeInteger(coverage[field], `${label}.${field}`));
  assertCountMap(coverage.category_binding_counts, `${label}.category_binding_counts`);
  assertCountMap(coverage.family_binding_counts, `${label}.family_binding_counts`);
  assertContract(coverage.is_conserved === true, `v2 产品覆盖账本未声明守恒：${layer}`);
  assertContract(
    coverage.input_record_count === coverage.bound_record_count + coverage.unbound_record_count
      && coverage.binding_count === coverage.exact_spu_binding_count
        + coverage.family_only_binding_count
        + coverage.category_only_binding_count
      && coverage.binding_count === sumCounts(coverage.category_binding_counts)
      && coverage.binding_count === sumCounts(coverage.family_binding_counts) + coverage.category_only_binding_count
      && coverage.multi_binding_record_count <= coverage.bound_record_count
      && coverage.taxonomy_blocked_binding_count <= coverage.family_only_binding_count,
    `v2 产品覆盖账本不守恒：${layer}`,
  );
  return coverage;
}

function addProductCoverage(
  posts: SnapshotProductCoverage,
  comments: SnapshotProductCoverage,
): SnapshotProductCoverage {
  return {
    input_record_count: posts.input_record_count + comments.input_record_count,
    bound_record_count: posts.bound_record_count + comments.bound_record_count,
    unbound_record_count: posts.unbound_record_count + comments.unbound_record_count,
    multi_binding_record_count: posts.multi_binding_record_count + comments.multi_binding_record_count,
    binding_count: posts.binding_count + comments.binding_count,
    exact_spu_binding_count: posts.exact_spu_binding_count + comments.exact_spu_binding_count,
    family_only_binding_count: posts.family_only_binding_count + comments.family_only_binding_count,
    category_only_binding_count: posts.category_only_binding_count + comments.category_only_binding_count,
    taxonomy_blocked_binding_count: posts.taxonomy_blocked_binding_count + comments.taxonomy_blocked_binding_count,
    category_binding_counts: mergeCountMaps(posts.category_binding_counts, comments.category_binding_counts),
    family_binding_counts: mergeCountMaps(posts.family_binding_counts, comments.family_binding_counts),
    is_conserved: true,
  };
}

function assertCountMapsEqual(actual: Record<string, number>, expected: Record<string, number>, label: string): void {
  const keys = new Set([...Object.keys(actual), ...Object.keys(expected)]);
  assertContract([...keys].every((key) => actual[key] === expected[key]), label);
}

function assertProductCoverageEqual(
  actual: SnapshotProductCoverage,
  expected: SnapshotProductCoverage,
  layer: string,
): void {
  const numericFields = PRODUCT_COVERAGE_FIELDS.filter(
    (field) => field !== 'category_binding_counts' && field !== 'family_binding_counts' && field !== 'is_conserved',
  );
  assertContract(
    numericFields.every((field) => actual[field] === expected[field]),
    `v2 产品覆盖账本不一致：${layer}`,
  );
  assertCountMapsEqual(
    actual.category_binding_counts,
    expected.category_binding_counts,
    `v2 产品覆盖账本不一致：${layer}`,
  );
  assertCountMapsEqual(
    actual.family_binding_counts,
    expected.family_binding_counts,
    `v2 产品覆盖账本不一致：${layer}`,
  );
}

function validateProductDimension(
  value: unknown,
  fields: readonly string[],
  label: string,
): Record<string, unknown> {
  assertExactObjectKeys(value, fields, label);
  fields.forEach((field) => assertNonEmptyString(value[field], `${label}.${field}`));
  return value;
}

function validateProductBinding(value: unknown, label: string): SnapshotProductBinding {
  assertExactObjectKeys(value, [
    'brand_id',
    'category',
    'product_family',
    'exact_spu',
    'binding_level',
    'match_type',
    'matched_alias',
    'governance_status',
    'governance_reason',
  ], label);
  const binding = value as unknown as SnapshotProductBinding;
  assertContract(binding.brand_id === 'momcozy', `${label}.brand_id 异常`);
  validateProductDimension(binding.category, ['id', 'name_en', 'name_cn'], `${label}.category`);
  if (binding.product_family !== null) {
    validateProductDimension(binding.product_family, ['id', 'name_en', 'name_cn'], `${label}.product_family`);
  }
  if (binding.exact_spu !== null) {
    validateProductDimension(binding.exact_spu, ['spu_id', 'spu_name'], `${label}.exact_spu`);
  }
  assertContract(['category', 'product_family', 'spu_exact'].includes(binding.binding_level), `${label}.binding_level 异常`);
  assertContract(['category_context', 'contextual_alias', 'strong_name'].includes(binding.match_type), `${label}.match_type 异常`);
  assertContract(
    ['category_only', 'family_only', 'exact_spu_approved', 'taxonomy_blocked'].includes(binding.governance_status),
    `${label}.governance_status 异常`,
  );
  assertNonEmptyString(binding.matched_alias, `${label}.matched_alias`);
  assertContract(binding.governance_reason === null || typeof binding.governance_reason === 'string', `${label}.governance_reason 异常`);
  assertContract(
    (binding.binding_level === 'category' && binding.product_family === null && binding.exact_spu === null)
      || (binding.binding_level === 'product_family' && binding.product_family !== null && binding.exact_spu === null)
      || (binding.binding_level === 'spu_exact' && binding.product_family !== null && binding.exact_spu !== null),
    `${label}产品层级结构异常`,
  );
  return binding;
}

function recomputeProductCoverage(
  rows: Array<{ product_bindings?: SnapshotProductBinding[] }>,
  layer: string,
): SnapshotProductCoverage {
  const categoryBindingCounts: Record<string, number> = {};
  const familyBindingCounts: Record<string, number> = {};
  let boundRecordCount = 0;
  let multiBindingRecordCount = 0;
  let bindingCount = 0;
  let exactSpuBindingCount = 0;
  let familyOnlyBindingCount = 0;
  let categoryOnlyBindingCount = 0;
  let taxonomyBlockedBindingCount = 0;

  rows.forEach((row, rowIndex) => {
    assertContract(Array.isArray(row.product_bindings), `v2 ${layer}[${rowIndex}] 缺少 product_bindings`);
    const bindings = row.product_bindings.map((binding, bindingIndex) => (
      validateProductBinding(binding, `v2 ${layer}[${rowIndex}].product_bindings[${bindingIndex}]`)
    ));
    const identities = new Set<string>();
    bindings.forEach((binding) => {
      const identity = `${binding.category.id}:${binding.product_family?.id ?? ''}:${binding.exact_spu?.spu_id ?? ''}`;
      assertContract(!identities.has(identity), `v2 ${layer}[${rowIndex}] 产品绑定重复`);
      identities.add(identity);
      bindingCount += 1;
      exactSpuBindingCount += Number(binding.binding_level === 'spu_exact');
      familyOnlyBindingCount += Number(binding.binding_level === 'product_family');
      categoryOnlyBindingCount += Number(binding.binding_level === 'category');
      taxonomyBlockedBindingCount += Number(binding.governance_status === 'taxonomy_blocked');
      categoryBindingCounts[binding.category.id] = (categoryBindingCounts[binding.category.id] ?? 0) + 1;
      if (binding.product_family) {
        familyBindingCounts[binding.product_family.id] = (familyBindingCounts[binding.product_family.id] ?? 0) + 1;
      }
    });
    boundRecordCount += Number(bindings.length > 0);
    multiBindingRecordCount += Number(bindings.length > 1);
  });

  return {
    input_record_count: rows.length,
    bound_record_count: boundRecordCount,
    unbound_record_count: rows.length - boundRecordCount,
    multi_binding_record_count: multiBindingRecordCount,
    binding_count: bindingCount,
    exact_spu_binding_count: exactSpuBindingCount,
    family_only_binding_count: familyOnlyBindingCount,
    category_only_binding_count: categoryOnlyBindingCount,
    taxonomy_blocked_binding_count: taxonomyBlockedBindingCount,
    category_binding_counts: categoryBindingCounts,
    family_binding_counts: familyBindingCounts,
    is_conserved: true,
  };
}

function assertV2ManifestContract(manifest: SnapshotManifest): SnapshotProductResolution {
  const semantic = manifest.semantic_boundaries;
  assertContract(
    semantic.created_at_utc_is_reddit_event_time === true
      && semantic.canonical_event_time_field === 'event_created_at_utc',
    'v2 事件时间合同异常',
  );
  const mapping = semantic.comment_coverage_status_mapping;
  assertExactObjectKeys(mapping, LEGACY_SNAPSHOT_COVERAGE_GRADES, 'v2 评论覆盖映射');
  assertContract(
    mapping.full === 'thread_complete'
      && mapping.partial === 'observed_first_page'
      && mapping.post_only === 'post_only',
    'v2 评论覆盖映射异常',
  );
  assertContract(
    semantic.thread_complete_means_no_observed_more_node_not_absolute_reddit_completeness === true,
    'v2 完整线程解释边界异常',
  );
  assertContract(
    semantic.global_product_category_imputed === false
      && semantic.product_category_resolution_status === 'governed_product_entity_resolver_v1'
      && semantic.product_category_analysis_supported === true
      && semantic.product_family_analysis_supported === true
      && semantic.exact_spu_analysis_supported_only_for_approved_bindings === true,
    'v2 产品分析边界异常',
  );
  assertContract(semantic.product_entity_ledger_sha256 === PRODUCT_LEDGER_SHA256, 'v2 产品实体 ledger 哈希不一致');
  assertContract(manifest.tagging.spu_rule_gate === 'governed_product_entity_ledger', 'v2 产品标签门禁异常');
  const resolution = manifest.tagging.product_entity_resolution;
  assertExactObjectKeys(resolution, [
    'status',
    'resolver_version',
    'ledger_version',
    'ledger_sha256',
    'coverage',
    'observed_tag_contexts',
  ], 'v2 产品实体 resolver');
  assertContract(
    resolution.status === 'resolved'
      && resolution.resolver_version === PRODUCT_RESOLVER_VERSION
      && resolution.ledger_version === PRODUCT_LEDGER_VERSION,
    'v2 产品实体 resolver 版本异常',
  );
  assertContract(
    resolution.ledger_sha256 === PRODUCT_LEDGER_SHA256
      && resolution.ledger_sha256 === semantic.product_entity_ledger_sha256,
    'v2 产品实体 ledger 哈希不一致',
  );
  assertExactObjectKeys(resolution.coverage, ['posts', 'comments', 'combined'], 'v2 产品覆盖账本');
  const posts = assertProductCoverage(resolution.coverage.posts, 'posts');
  const comments = assertProductCoverage(resolution.coverage.comments, 'comments');
  const combined = assertProductCoverage(resolution.coverage.combined, 'combined');
  assertContract(posts.input_record_count === manifest.canonical_counts.posts, 'v2 产品覆盖帖子输入数异常');
  assertContract(comments.input_record_count === manifest.canonical_counts.linked_comments, 'v2 产品覆盖评论输入数异常');
  assertContract(
    combined.input_record_count === manifest.canonical_counts.posts + manifest.canonical_counts.linked_comments,
    'v2 产品覆盖合并输入数异常',
  );
  assertProductCoverageEqual(combined, addProductCoverage(posts, comments), 'combined');
  assertContract(Array.isArray(resolution.observed_tag_contexts) && resolution.observed_tag_contexts.length > 0, 'v2 标签上下文缺失');
  resolution.observed_tag_contexts.forEach((context, index) => {
    assertExactObjectKeys(context, ['product_line', 'voc_category', 'spu_ids'], `v2 标签上下文[${index}]`);
    assertNonEmptyString(context.product_line, `v2 标签上下文[${index}].product_line`);
    assertNonEmptyString(context.voc_category, `v2 标签上下文[${index}].voc_category`);
    assertContract(Array.isArray(context.spu_ids), `v2 标签上下文[${index}].spu_ids 异常`);
    context.spu_ids.forEach((spuId) => assertNonEmptyString(spuId, `v2 标签上下文[${index}].spu_ids`));
  });
  return resolution;
}

function assertV2EventTime(createdAtUtc: string, eventCreatedAtUtc: unknown, label: string): void {
  assertContract(
    typeof eventCreatedAtUtc === 'string' && eventCreatedAtUtc === createdAtUtc,
    `v2 ${label}事件时间字段异常`,
  );
}

function assertTranslationManifestContract(manifest: SnapshotManifest): void {
  const translation = manifest.translations;
  if (!translation) {
    assertContract(
      manifest.provider_call === false && manifest.boundaries?.provider_call === false,
      '无翻译侧车的 Base 错误声明 Provider 调用',
    );
    return;
  }
  assertContract(
    manifest.provider_call === true
      && manifest.boundaries?.provider_call === true
      && manifest.promotable === false
      && manifest.status === 'validated_local_translation_candidate'
      && manifest.consumption_status === 'eligible_for_frontend_candidate_consumption',
    '翻译候选 Provider 或候选边界异常',
  );
  assertContract(
    translation.schema_version === 'reddit_voc_translation_extension_v1'
      && translation.provider === 'deepseek'
      && translation.model === 'deepseek-v4-flash'
      && translation.provider_call === true
      && SAFE_AUTHORIZATION_ID_PATTERN.test(translation.provider_authorization_id)
      && translation.source_dataset_version.startsWith('reddit_voc_site_snapshot_')
      && translation.source_dataset_version !== manifest.dataset_version
      && SHA256_PATTERN.test(translation.source_public_manifest_sha256)
      && SHA256_PATTERN.test(translation.translation_prompt_sha256)
      && SHA256_PATTERN.test(translation.translation_terms_sha256)
      && SHA256_PATTERN.test(translation.checkpoint_sha256)
      && SHA256_PATTERN.test(translation.provider_attempt_log_sha256)
      && translation.quality_gate === 'deterministic_contract_v1'
      && translation.semantic_validation === 'not_run'
      && translation.independent_human_review === false,
    '翻译候选来源或质量合同异常',
  );
  const coverage = translation.coverage;
  const commentsTotal = coverage.comments_total ?? coverage.comments;
  const commentsStatus = coverage.comments_status ?? 'complete';
  const commentsUnavailableReason = coverage.comments_unavailable_reason ?? null;
  assertContract(
    Number.isInteger(coverage.posts)
      && coverage.posts === manifest.canonical_counts.posts
      && coverage.post_titles === coverage.posts
      && coverage.post_contents === coverage.posts
      && (coverage.post_translation_status ?? 'complete') === 'complete'
      && Number.isInteger(coverage.comments)
      && coverage.comments >= 0
      && coverage.comments <= commentsTotal
      && commentsTotal === manifest.canonical_counts.linked_comments
      && (
        commentsStatus === 'complete'
          ? coverage.comments === commentsTotal && commentsUnavailableReason === null
          : commentsStatus === 'partial'
            && coverage.comments < commentsTotal
            && commentsUnavailableReason === 'provider_http_402_balance_blocked'
      )
      && coverage.translated_items === coverage.posts * 2 + coverage.comments
      && Number.isInteger(translation.provider_attempts)
      && translation.provider_attempts > 0,
    '翻译候选覆盖计数异常',
  );
  for (const value of Object.values(translation.usage)) {
    assertNonNegativeInteger(value, '翻译候选 Token 使用量');
  }
  assertContract(
    translation.usage.total_tokens
      === translation.usage.prompt_tokens + translation.usage.completion_tokens,
    '翻译候选 Token 使用量不守恒',
  );
}

function assertV3ManifestContract(manifest: SnapshotManifest, release: CurrentRelease): void {
  assertNonEmptyString(manifest.source_snapshot_id, 'v3 Base source snapshot');
  const hasTranslations = Boolean(manifest.translations);
  assertContract(
    hasTranslations
      ? manifest.status === 'validated_local_translation_candidate'
        && manifest.consumption_status === 'eligible_for_frontend_candidate_consumption'
        && manifest.promotable === false
      : manifest.status === 'validated_candidate'
        && manifest.consumption_status === 'eligible_for_current_release_candidate_binding'
        && manifest.promotable === true,
    'v3 Base 候选消费状态异常',
  );
  assertContract(
    manifest.privacy_safe_projection === true,
    'v3 Base 隐私门禁异常',
  );
  const comparisonReasons = manifest.comparison_unavailable_reason_codes ?? [];
  assertContract(Array.isArray(comparisonReasons), 'v3 Base 比较不可用原因异常');
  if (manifest.comparison_contract_proven === true) {
    const attestation = manifest.coverage_attestation;
    assertContract(
      manifest.comparison_contract_basis === 'owner_attested_dataset_scope_window'
        && manifest.completeness_percent === 100
        && manifest.completeness_basis === 'data_owner_declaration'
        && typeof manifest.data_owner_coverage_attestation_sha256 === 'string'
        && /^[a-f0-9]{64}$/.test(manifest.data_owner_coverage_attestation_sha256)
        && comparisonReasons.length === 0
        && attestation !== null
        && attestation !== undefined
        && attestation.attestation_basis === 'data_owner_declaration'
        && attestation.completeness_percent === 100
        && attestation.evidence_class === 'owner_attested_not_crawler_proof'
        && attestation.scope === 'canonical_observation_pool'
        && attestation.source_snapshot_id === manifest.source_snapshot_id,
      'v3 Base 数据所有者完整性合同异常',
    );
  } else if (manifest.comparison_contract_proven === false) {
    assertContract(
      manifest.comparison_contract_proven === false
        && manifest.comparison_contract_basis === 'not_owner_attested'
        && manifest.completeness_percent === null
        && manifest.completeness_basis === 'not_owner_attested'
        && manifest.coverage_attestation === null
        && manifest.data_owner_coverage_attestation_sha256 === null
        && comparisonReasons.length === 1
        && comparisonReasons[0]
          === 'historical_collection_coverage_not_owner_attested_complete',
      'v3 Base 未证明覆盖合同异常',
    );
  } else {
    assertContract(
      manifest.completeness_percent === 100
        && manifest.completeness_basis === 'data_owner_declaration'
        && comparisonReasons.length === 0,
      'v3 Base legacy 完整性合同异常',
    );
  }
  assertContract(
    manifest.lineage_manifest_sha256 === release.datasets.base.lineage_manifest_sha256,
    'v3 Base canonical lineage 与 current release 不一致',
  );
  assertExactObjectKeys(manifest.inputs, [
    'canonical_dataset_id',
    'canonical_manifest_sha256',
    'canonical_validation_receipt_sha256',
    'tag_dictionary_sha256',
  ], 'v3 Base inputs');
  const expectedCanonicalDatasetId = manifest.source_snapshot_id.endsWith('_canonical_v2')
    ? manifest.source_snapshot_id
    : `${manifest.source_snapshot_id}_canonical_v1`;
  assertContract(
    manifest.inputs.canonical_dataset_id === expectedCanonicalDatasetId
      && manifest.inputs.canonical_manifest_sha256 === manifest.lineage_manifest_sha256
      && /^[a-f0-9]{64}$/.test(manifest.inputs.canonical_validation_receipt_sha256)
      && /^[a-f0-9]{64}$/.test(manifest.inputs.tag_dictionary_sha256),
    'v3 Base input lineage 异常',
  );
  assertExactObjectKeys(manifest.boundaries, [
    'database_write',
    'deploy',
    'live_send',
    'production_unchanged',
    'provider_call',
    'remote_write',
  ], 'v3 Base boundaries');
  assertContract(
    manifest.boundaries.database_write === false
      && manifest.boundaries.deploy === false
      && manifest.boundaries.live_send === false
      && manifest.boundaries.production_unchanged === true
      && manifest.boundaries.provider_call === Boolean(manifest.translations)
      && manifest.boundaries.remote_write === false,
    'v3 Base 副作用边界异常',
  );
  assertTranslationManifestContract(manifest);
  assertContract(
    manifest.database_write === false
      && manifest.deploy === false
      && manifest.remote_write === false,
    'v3 Base 顶层副作用兼容字段异常',
  );
  assertNonNegativeInteger(manifest.canonical_counts.comments_jsonl, 'v3 Base comments_jsonl');
  assertNonNegativeInteger(manifest.canonical_counts.unresolved_parent_comments, 'v3 Base 待关联评论');
  assertContract(
    manifest.canonical_counts.comments_jsonl
      === manifest.canonical_counts.linked_comments + manifest.canonical_counts.unresolved_parent_comments,
    'v3 Base linked + 待关联评论不守恒',
  );
  assertContract(
    manifest.canonical_counts.stored_comments
      === manifest.canonical_counts.comments_jsonl + manifest.canonical_counts.quarantined_comments,
    'v3 Base stored comments 不守恒',
  );
  assertExactObjectKeys(manifest.projection_counts, [
    'public_posts',
    'public_linked_comments',
    'ledger_only_unresolved_parent_comments',
    'ledger_only_quarantined_comments',
  ], 'v3 Base projection counts');
  assertContract(
    manifest.projection_counts.public_posts === manifest.canonical_counts.posts
      && manifest.projection_counts.public_linked_comments === manifest.canonical_counts.linked_comments
      && manifest.projection_counts.ledger_only_unresolved_parent_comments
        === manifest.canonical_counts.unresolved_parent_comments
      && manifest.projection_counts.ledger_only_quarantined_comments
        === manifest.canonical_counts.quarantined_comments,
    'v3 Base 公开投影计数不守恒',
  );
  assertExactObjectKeys(manifest.time_precision, ['posts', 'comments', 'day_precision_midnight_imputed'], 'v3 Base time precision');
  assertCountMap(manifest.time_precision.posts, 'v3 Base 帖子时间精度');
  assertCountMap(manifest.time_precision.comments, 'v3 Base 评论时间精度');
  assertContract(
    sumCounts(manifest.time_precision.posts) === manifest.canonical_counts.posts
      && sumCounts(manifest.time_precision.comments) === manifest.canonical_counts.linked_comments
      && manifest.time_precision.day_precision_midnight_imputed === false,
    'v3 Base 时间精度计数不守恒',
  );
  assertContract(
    manifest.privacy.author_display === 'suppressed'
      && manifest.privacy.author_linkage_excluded === true
      && manifest.privacy.stable_pseudonym_exposed === false,
    'v3 Base 作者关联未完全抑制',
  );
  assertContract(
    manifest.semantic_boundaries.unresolved_parent_business_label === '待关联评论'
      && manifest.semantic_boundaries.unresolved_parent_comments_in_public_detail === false
      && manifest.semantic_boundaries.quarantined_comments_in_public_detail === false
      && manifest.semantic_boundaries.day_precision_midnight_imputed === false
      && manifest.semantic_boundaries.day_precision_display_contract === 'YYYY-MM-DD'
      && manifest.semantic_boundaries.metric_eligibility_owned_by_governed_metrics_dataset === true,
    'v3 Base 业务或时间边界异常',
  );
}

function assertV3EventTime(entity: SnapshotPost | SnapshotComment, label: string): void {
  if (entity.event_time_precision === 'day') {
    assertContract(/^\d{4}-\d{2}-\d{2}$/.test(entity.created_at_utc), `v3 ${label}日精度日期异常`);
    assertContract(
      entity.source_calendar_date === entity.created_at_utc
        && entity.event_created_at_utc === null,
      `v3 ${label}伪造了日精度时刻`,
    );
    return;
  }
  assertContract(
    entity.event_time_precision === 'instant'
      && typeof entity.event_created_at_utc === 'string'
      && entity.event_created_at_utc === entity.created_at_utc
      && entity.source_calendar_date === null
      && entity.created_at_utc.includes('T'),
    `v3 ${label}时刻精度合同异常`,
  );
}

export function validateSnapshotCore(
  manifest: SnapshotManifest,
  aggregates: SnapshotAggregates,
  posts: SnapshotPost[],
  tagDictionary: SnapshotTagDictionary,
  release: CurrentRelease,
): RedditSnapshotCore {
  assertContract(SNAPSHOT_MANIFEST_SCHEMAS.has(manifest.schema_version), '快照 manifest schema 不受支持');
  const isV2 = manifest.schema_version === SNAPSHOT_MANIFEST_SCHEMA_V2;
  const isV3 = manifest.schema_version === SNAPSHOT_MANIFEST_SCHEMA_V3;
  assertContract(manifest.dataset_version === release.datasets.base.dataset_version, '快照版本与 current release 不一致');
  assertContract(manifest.delivery_mode === 'versioned_static_snapshot', '快照交付模式不是版本化静态快照');
  assertContract(manifest.all_checks_passed === true, '快照上游校验未通过');
  assertContract(manifest.production_unchanged === true, '快照缺少 production unchanged 边界');
  assertContract(
    manifest.provider_call === Boolean(manifest.translations) && manifest.live_send === false,
    '快照外部调用边界异常',
  );
  assertContract(manifest.privacy.author_display === 'suppressed', '公开快照未隐藏作者关联字段');
  assertContract(manifest.privacy.raw_author_fields_present === false, '快照包含不允许公开的原始作者字段');
  assertContract(manifest.tagging.labels_provisional === true, '标签状态必须保持为待语义复核');
  assertContract(manifest.tagging.semantic_validation_run === false, '当前版本不应声称已完成语义复核');
  assertContract(manifest.semantic_boundaries.market_share_supported === false, '当前版本不支持市场份额指标');
  assertContract(manifest.semantic_boundaries.roi_supported === false, '当前版本不支持 ROI 指标');
  assertSnapshotFileManifest(manifest);
  if (isV3) assertV3ManifestContract(manifest, release);
  const productResolution = isV2 ? assertV2ManifestContract(manifest) : null;

  assertContract(
    aggregates.schema_version
      === (isV3 ? 'reddit_voc_site_aggregates_v3' : 'reddit_voc_site_aggregates_v1'),
    'aggregates schema 不受支持',
  );
  assertContract(Array.isArray(posts), 'posts.json 必须是数组');
  assertContract(posts.length === manifest.canonical_counts.posts, '帖子数组数量与 manifest 不一致');
  assertContract(aggregates.headline.unique_posts === posts.length, '聚合帖子数与实体数组不一致');
  assertContract(
    aggregates.headline.linked_comments === manifest.canonical_counts.linked_comments,
    '聚合关联评论数与 manifest 不一致',
  );
  assertContract(
    aggregates.headline.quarantined_comments === manifest.canonical_counts.quarantined_comments,
    '聚合隔离评论数与 manifest 不一致',
  );
  if (isV3) {
    assertContract(
      aggregates.headline.stored_comments === manifest.canonical_counts.stored_comments
        && aggregates.headline.unresolved_parent_comments
          === manifest.canonical_counts.unresolved_parent_comments,
      'v3 Base 聚合评论状态与 manifest 不一致',
    );
    assertContract(
      aggregates.time_precision?.day_precision_midnight_imputed === false
        && JSON.stringify(aggregates.time_precision) === JSON.stringify(manifest.time_precision),
      'v3 Base 聚合时间精度与 manifest 不一致',
    );
  }
  const coverageGrades = isV3
    ? V3_SNAPSHOT_COVERAGE_GRADES
    : LEGACY_SNAPSHOT_COVERAGE_GRADES;
  const aggregateCoverageGrades = Object.keys(aggregates.coverage_grade);
  assertContract(
    aggregateCoverageGrades.every((grade) => coverageGrades.includes(grade as never)),
    '聚合结构覆盖等级不受支持',
  );
  aggregateCoverageGrades.forEach((grade) => (
    assertNonNegativeInteger(aggregates.coverage_grade[grade as SnapshotCoverageGrade], `聚合结构覆盖计数：${grade}`)
  ));
  assertContract(
    coverageGrades.reduce(
      (total, grade) => total + (aggregates.coverage_grade[grade] ?? 0),
      0,
    ) === posts.length,
    '帖子结构覆盖计数不守恒',
  );

  const postIds = new Set<string>();
  const observedCoverageGrades: Record<SnapshotCoverageGrade, number> = {
    full: 0,
    partial: 0,
    post_only: 0,
    source_observed: 0,
  };
  for (const post of posts) {
    assertContract(typeof post.post_id === 'string' && post.post_id.length > 0, '帖子缺少 post_id');
    assertContract(!postIds.has(post.post_id), `帖子 ID 重复：${post.post_id}`);
    assertContract(
      post.author_pseudonym === undefined
        || post.author_pseudonym === null
        || post.author_pseudonym.startsWith('anon_'),
      `帖子作者字段不是稳定假名或空值：${post.post_id}`,
    );
    assertContract(
      coverageGrades.includes(post.structural_coverage_grade as never),
      `帖子结构覆盖等级不受支持：${post.post_id}`,
    );
    observedCoverageGrades[post.structural_coverage_grade] += 1;
    assertContract(post.analysis.provider_call === false, `帖子分析外部调用边界异常：${post.post_id}`);
    assertContract(post.tagging.semantic_validation_status === 'not_run', `帖子标签状态异常：${post.post_id}`);
    if (isV3) {
      assertContract(post.schema_version === 'reddit_voc_public_post_v3', `v3 帖子 schema 异常：${post.post_id}`);
      assertContract(
        post.author_pseudonym === null
          && post.author_pseudonym_status === 'suppressed_for_public_projection',
        `v3 帖子作者关联未抑制：${post.post_id}`,
      );
      assertV3EventTime(post, `帖子 ${post.post_id} `);
      assertContract(
        post.structural_coverage_grade !== 'source_observed'
          || (post.count_completeness_status === 'source_rows_only'
            && post.comment_coverage_status === 'source_rows_only'),
        `v3 来源行帖子覆盖状态异常：${post.post_id}`,
      );
      assertContract(
        typeof post.brand_binding === 'string' && CONTROLLED_BINDINGS.has(post.brand_binding),
        `v3 帖子主体绑定异常：${post.post_id}`,
      );
    }
    if (isV2) {
      assertV2EventTime(post.created_at_utc, post.event_created_at_utc, `帖子 ${post.post_id} `);
      assertContract(
        post.comment_coverage_status
          === manifest.semantic_boundaries.comment_coverage_status_mapping?.[post.structural_coverage_grade],
        `v2 帖子评论覆盖映射异常：${post.post_id}`,
      );
      assertContract(
        typeof post.brand_binding === 'string' && CONTROLLED_BINDINGS.has(post.brand_binding),
        `v2 帖子主体绑定异常：${post.post_id}`,
      );
    }
    postIds.add(post.post_id);
  }
  coverageGrades.forEach((grade) => {
    assertContract(
      observedCoverageGrades[grade] === (aggregates.coverage_grade[grade] ?? 0),
      `帖子结构覆盖聚合漂移：${grade}`,
    );
  });
  if (productResolution) {
    assertProductCoverageEqual(
      productResolution.coverage.posts,
      recomputeProductCoverage(posts, 'posts'),
      'posts',
    );
  }

  assertContract(tagDictionary.schema_version === 'reddit_voc_public_tag_dictionary_v1', '公开标签字典 schema 不受支持');
  assertContract(tagDictionary.dictionary_version === manifest.tagging.dictionary_version, '标签字典版本与 manifest 不一致');
  if (isV3) {
    assertContract(
      tagDictionary.dictionary_sha256 === manifest.inputs?.tag_dictionary_sha256
        && tagDictionary.dictionary_sha256 === manifest.tagging.dictionary_sha256,
      'v3 Base 标签字典 SHA 不一致',
    );
  }
  assertContract(Array.isArray(tagDictionary.rules), '标签字典 rules 必须是数组');

  const tagRulesById = new Map(tagDictionary.rules.map((rule) => [rule.tag_id, rule]));
  for (const post of posts) {
    for (const tagId of post.tagging.tag_ids) {
      assertContract(tagRulesById.has(tagId), `帖子引用了字典中不存在的标签：${tagId}`);
    }
  }

  return { release, manifest, aggregates, posts, tagDictionary, tagRulesById };
}

function assertTranslationSidecarEnvelope<T>(
  manifest: SnapshotManifest,
  sidecar: TranslationSidecar<T>,
  entityType: 'post' | 'comment',
): void {
  const translation = manifest.translations;
  assertContract(Boolean(translation), '翻译侧车缺少 manifest 合同');
  assertContract(
    sidecar.schema_version === 'reddit_voc_public_translations_v1'
      && sidecar.dataset_version === manifest.dataset_version
      && sidecar.source_dataset_version === translation?.source_dataset_version
      && typeof sidecar.generated_at_utc === 'string'
      && !Number.isNaN(Date.parse(sidecar.generated_at_utc))
      && sidecar.provider === 'deepseek'
      && sidecar.model === 'deepseek-v4-flash'
      && sidecar.quality_gate === 'deterministic_contract_v1'
      && sidecar.semantic_validation === 'not_run'
      && sidecar.independent_human_review === false
      && sidecar.entity_type === entityType
      && Array.isArray(sidecar.items),
    `${entityType} 翻译侧车合同异常`,
  );
}

function enrichPostsWithTranslations(
  manifest: SnapshotManifest,
  posts: SnapshotPost[],
  sidecar: TranslationSidecar<PostTranslationRow>,
): SnapshotPost[] {
  assertTranslationSidecarEnvelope(manifest, sidecar, 'post');
  assertContract(
    sidecar.items.length === manifest.translations?.coverage.posts
      && sidecar.items.length === posts.length,
    '帖子翻译覆盖不完整',
  );
  const rows = new Map<string, PostTranslationRow>();
  sidecar.items.forEach((row, index) => {
    assertExactObjectKeys(row, [
      'post_id',
      'title_zh',
      'content_zh',
      'title_input_sha256',
      'content_input_sha256',
      'title_quality_status',
      'content_quality_status',
    ], `帖子翻译 ${index}`);
    assertContract(
      typeof row.post_id === 'string'
        && !rows.has(row.post_id)
        && typeof row.title_zh === 'string'
        && typeof row.content_zh === 'string'
        && SHA256_PATTERN.test(row.title_input_sha256)
        && SHA256_PATTERN.test(row.content_input_sha256)
        && row.title_quality_status === 'deterministic_passed_unreviewed'
        && row.content_quality_status === 'deterministic_passed_unreviewed',
      `帖子翻译 ${index} 字段异常`,
    );
    rows.set(row.post_id, row);
  });
  return posts.map((post) => {
    const row = rows.get(post.post_id);
    assertContract(row !== undefined, `帖子缺少中文翻译：${post.post_id}`);
    assertContract(
      (!post.title || Boolean(row.title_zh.trim()))
        && (!post.content || Boolean(row.content_zh.trim())),
      `帖子中文翻译为空：${post.post_id}`,
    );
    const translation: SnapshotPostTranslation = {
      title_zh: row.title_zh,
      content_zh: row.content_zh,
      title_input_sha256: row.title_input_sha256,
      content_input_sha256: row.content_input_sha256,
      title_quality_status: row.title_quality_status,
      content_quality_status: row.content_quality_status,
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      semantic_validation: 'not_run',
      independent_human_review: false,
    };
    return { ...post, translation };
  });
}

function enrichCommentsWithTranslations(
  manifest: SnapshotManifest,
  comments: SnapshotComment[],
  sidecar: TranslationSidecar<CommentTranslationRow>,
): SnapshotComment[] {
  assertTranslationSidecarEnvelope(manifest, sidecar, 'comment');
  assertContract(
    sidecar.items.length === manifest.translations?.coverage.comments,
    '评论翻译覆盖计数异常',
  );
  const rows = new Map<string, CommentTranslationRow>();
  sidecar.items.forEach((row, index) => {
    assertExactObjectKeys(row, [
      'comment_id',
      'post_id',
      'zh',
      'input_sha256',
      'provider',
      'quality_status',
    ], `评论翻译 ${index}`);
    assertContract(
      typeof row.comment_id === 'string'
        && typeof row.post_id === 'string'
        && !rows.has(row.comment_id)
        && typeof row.zh === 'string'
        && SHA256_PATTERN.test(row.input_sha256)
        && row.provider === 'deepseek'
        && row.quality_status === 'deterministic_passed_unreviewed',
      `评论翻译 ${index} 字段异常`,
    );
    rows.set(row.comment_id, row);
  });
  return comments.map((comment) => {
    const row = rows.get(comment.comment_id);
    if (row === undefined) return comment;
    assertContract(
      row.post_id === comment.post_id,
      `评论错绑中文翻译：${comment.comment_id}`,
    );
    assertContract(!comment.body || Boolean(row.zh.trim()), `评论中文翻译为空：${comment.comment_id}`);
    const translation: SnapshotCommentTranslation = {
      body_zh: row.zh,
      input_sha256: row.input_sha256,
      quality_status: row.quality_status,
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      semantic_validation: 'not_run',
      independent_human_review: false,
    };
    return { ...comment, translation };
  });
}

async function loadCoreUncached(): Promise<RedditSnapshotCore> {
  const { release, manifest, aggregates } = await loadRedditSnapshotSummary();
  const basePath = getReleaseDatasetBasePath(release, 'base');

  const [posts, tagDictionary, postTranslations] = await Promise.all([
    fetchVerifiedJson<SnapshotPost[]>(
      basePath,
      'posts-public.json',
      manifest.files['posts-public.json'],
      '真实数据文件',
    ),
    fetchVerifiedJson<SnapshotTagDictionary>(
      basePath,
      'tag-dictionary-public.json',
      manifest.files['tag-dictionary-public.json'],
      '真实数据文件',
    ),
    manifest.translations
      ? fetchVerifiedJson<TranslationSidecar<PostTranslationRow>>(
          basePath,
          'post-translations-public.json',
          manifest.files['post-translations-public.json'],
          '帖子中文翻译',
        )
      : Promise.resolve(null),
  ]);
  const core = validateSnapshotCore(manifest, aggregates, posts, tagDictionary, release);
  return postTranslations
    ? { ...core, posts: enrichPostsWithTranslations(manifest, core.posts, postTranslations) }
    : core;
}

function validateSnapshotSummary(
  release: CurrentRelease,
  manifest: SnapshotManifest,
  aggregates: SnapshotAggregates,
): RedditSnapshotSummary {
  assertContract(SNAPSHOT_MANIFEST_SCHEMAS.has(manifest.schema_version), '快照 manifest schema 不受支持');
  assertContract(manifest.dataset_version === release.datasets.base.dataset_version, '快照版本与 current release 不一致');
  assertSnapshotFileManifest(manifest);
  assertContract(manifest.delivery_mode === 'versioned_static_snapshot', '快照交付模式不是版本化静态快照');
  assertContract(manifest.all_checks_passed === true, '快照上游校验未通过');
  assertContract(manifest.production_unchanged === true, '快照缺少 production unchanged 边界');
  assertContract(
    manifest.provider_call === Boolean(manifest.translations) && manifest.live_send === false,
    '快照外部调用边界异常',
  );
  assertContract(manifest.privacy.author_display === 'suppressed', '公开快照未隐藏作者关联字段');
  assertContract(manifest.privacy.raw_author_fields_present === false, '快照包含不允许公开的原始作者字段');
  assertContract(manifest.tagging.labels_provisional === true, '标签状态必须保持为待语义复核');
  assertContract(manifest.tagging.semantic_validation_run === false, '当前版本不应声称已完成语义复核');
  assertContract(manifest.semantic_boundaries.market_share_supported === false, '当前版本不支持市场份额指标');
  assertContract(manifest.semantic_boundaries.roi_supported === false, '当前版本不支持 ROI 指标');
  const isV3 = manifest.schema_version === SNAPSHOT_MANIFEST_SCHEMA_V3;
  if (isV3) assertV3ManifestContract(manifest, release);
  assertContract(
    aggregates.schema_version === (isV3 ? 'reddit_voc_site_aggregates_v3' : 'reddit_voc_site_aggregates_v1'),
    'aggregates schema 不受支持',
  );
  assertContract(aggregates.headline.unique_posts === manifest.canonical_counts.posts, '聚合帖子数与 manifest 不一致');
  assertContract(aggregates.headline.linked_comments === manifest.canonical_counts.linked_comments, '聚合关联评论数与 manifest 不一致');
  const coverageTotal = Object.values(aggregates.coverage_grade).reduce((total, value) => total + (value ?? 0), 0);
  assertContract(coverageTotal === manifest.canonical_counts.posts, '帖子结构覆盖计数不守恒');
  return { release, manifest, aggregates };
}

async function loadSummaryUncached(): Promise<RedditSnapshotSummary> {
  const release = await loadCurrentRelease();
  const manifest = await fetchVerifiedReleaseManifest<SnapshotManifest>(release, 'base');
  const basePath = getReleaseDatasetBasePath(release, 'base');
  const aggregates = await fetchVerifiedJson<SnapshotAggregates>(
    basePath,
    'aggregates-public.json',
    manifest.files['aggregates-public.json'],
    '真实数据文件',
  );
  return validateSnapshotSummary(release, manifest, aggregates);
}

export function loadRedditSnapshotSummary(): Promise<RedditSnapshotSummary> {
  summaryPromise ??= loadSummaryUncached();
  return summaryPromise;
}

export function loadRedditSnapshot(): Promise<RedditSnapshotCore> {
  corePromise ??= loadCoreUncached();
  return corePromise;
}

async function loadCommentsUncached(): Promise<SnapshotComment[]> {
  const [release, core] = await Promise.all([loadCurrentRelease(), loadRedditSnapshot()]);
  const basePath = getReleaseDatasetBasePath(release, 'base');
  const [comments, commentTranslations] = await Promise.all([
    fetchVerifiedJson<SnapshotComment[]>(
      basePath,
      'comments-public.json',
      core.manifest.files['comments-public.json'],
      '真实数据文件',
    ),
    core.manifest.translations
      ? fetchVerifiedJson<TranslationSidecar<CommentTranslationRow>>(
          basePath,
          'comment-translations-public.json',
          core.manifest.files['comment-translations-public.json'],
          '评论中文翻译',
        )
      : Promise.resolve(null),
  ]);
  const validated = validateSnapshotComments(core, comments);
  return commentTranslations
    ? enrichCommentsWithTranslations(core.manifest, validated, commentTranslations)
    : validated;
}

export function validateSnapshotComments(
  core: RedditSnapshotCore,
  comments: SnapshotComment[],
): SnapshotComment[] {
  assertContract(Array.isArray(comments), 'comments.json 必须是数组');
  assertContract(comments.length === core.manifest.canonical_counts.linked_comments, '评论数组数量与 manifest 不一致');

  const postIds = new Set(core.posts.map((post) => post.post_id));
  const commentIds = new Set<string>();
  const isV2 = core.manifest.schema_version === SNAPSHOT_MANIFEST_SCHEMA_V2;
  const isV3 = core.manifest.schema_version === SNAPSHOT_MANIFEST_SCHEMA_V3;
  const productResolution = isV2 ? assertV2ManifestContract(core.manifest) : null;
  for (const comment of comments) {
    assertContract(!commentIds.has(comment.comment_id), `评论 ID 重复：${comment.comment_id}`);
    assertContract(postIds.has(comment.post_id), `评论关联了不存在的帖子：${comment.comment_id}`);
    assertContract(
      comment.author_pseudonym === undefined
        || comment.author_pseudonym === null
        || comment.author_pseudonym.startsWith('anon_'),
      `评论作者字段不是稳定假名或空值：${comment.comment_id}`,
    );
    assertContract(comment.analysis.provider_call === false, `评论分析外部调用边界异常：${comment.comment_id}`);
    assertContract(comment.tagging.semantic_validation_status === 'not_run', `评论标签状态异常：${comment.comment_id}`);
    if (isV3) {
      assertContract(comment.schema_version === 'reddit_voc_public_comment_v3', `v3 评论 schema 异常：${comment.comment_id}`);
      assertContract(
        comment.author_pseudonym === null
          && comment.author_pseudonym_status === 'suppressed_for_public_projection',
        `v3 评论作者关联未抑制：${comment.comment_id}`,
      );
      assertV3EventTime(comment, `评论 ${comment.comment_id} `);
      assertContract(
        comment.metric_eligibility_status === 'source_explicit'
          ? typeof comment.include_in_voc_metrics === 'boolean'
          : comment.metric_eligibility_status === 'determined_in_governed_metrics_not_base_projection'
            && comment.include_in_voc_metrics === null,
        `v3 评论指标资格状态异常：${comment.comment_id}`,
      );
      assertContract(
        typeof comment.brand_binding === 'string' && CONTROLLED_BINDINGS.has(comment.brand_binding),
        `v3 评论主体绑定异常：${comment.comment_id}`,
      );
    }
    if (isV2) {
      assertV2EventTime(comment.created_at_utc, comment.event_created_at_utc, `评论 ${comment.comment_id} `);
      assertContract(
        typeof comment.brand_binding === 'string' && CONTROLLED_BINDINGS.has(comment.brand_binding),
        `v2 评论主体绑定异常：${comment.comment_id}`,
      );
    }
    for (const tagId of comment.tagging.tag_ids) {
      assertContract(core.tagRulesById.has(tagId), `评论引用了字典中不存在的标签：${tagId}`);
    }
    commentIds.add(comment.comment_id);
  }
  if (productResolution) {
    const commentCoverage = recomputeProductCoverage(comments, 'comments');
    assertProductCoverageEqual(productResolution.coverage.comments, commentCoverage, 'comments');
    assertProductCoverageEqual(
      productResolution.coverage.combined,
      recomputeProductCoverage([...core.posts, ...comments], 'combined'),
      'combined',
    );
  }
  return comments;
}

export async function loadCommentsForPost(postId: string): Promise<SnapshotComment[]> {
  commentsPromise ??= loadCommentsUncached();
  const comments = await commentsPromise;
  return comments
    .filter((comment) => comment.post_id === postId)
    .sort((left, right) => right.score - left.score || left.created_at_utc.localeCompare(right.created_at_utc));
}

export function resetSnapshotCacheForTests(): void {
  corePromise = null;
  commentsPromise = null;
  insightsPromise = null;
}
