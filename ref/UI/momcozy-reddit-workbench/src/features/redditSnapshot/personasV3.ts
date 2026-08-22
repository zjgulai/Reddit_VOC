import { buildSnapshotEvidenceHref } from './evidenceLinks';

export const V3_PERSONAS_MANIFEST_SCHEMA = 'reddit_voc_personas_manifest_v3';
export const V3_PERSONAS_SCHEMA = 'reddit_voc_personas_v3';
export const V3_PERSONA_TAGS_SCHEMA = 'reddit_voc_persona_cohort_assignments_v1';
export const V3_PERSONA_COHORT_BRIDGE_SCHEMA = 'reddit_voc_persona_cohort_bridge_v1';
export const V3_PERSONA_ATOMIC_CATALOG_SCHEMA = 'reddit_voc_persona_atomic_catalog_v1';

export const V3_PERSONA_COHORT_NAMES = {
  competitor_comparer: '竞品比较者',
  fit_output_optimizer: '舒适适配与产出关注者',
  operations_troubleshooter: '操作与故障求助者',
  product_evaluator: '产品评估者',
  purchase_decision: '选购决策者',
  recommendation_expression: '推荐表达群',
  scenario_adapter: '工作与家庭场景适配者',
  service_support_seeker: '服务支持需求者',
} as const;

export type V3PersonaCohortId = keyof typeof V3_PERSONA_COHORT_NAMES;

export interface V3PersonaFileIntegrity {
  bytes: number;
  sha256: string;
  media_type: 'application/json' | 'application/x-ndjson' | 'image/svg+xml';
  rows?: number;
  width?: number;
  height?: number;
}

export interface V3PersonaManifestCounts {
  analysis_ready_vocs: number;
  atomic_persona_catalog: number;
  automation_classification_rows: number;
  automation_excluded_vocs: number;
  cohort_assignments: number;
  governed_signal_comment_facts_dropped: number;
  governed_signal_comment_vocs_dropped_no_direct_evidence: number;
  governed_signal_facts_injected: number;
  governed_signal_promoted_facts_loaded: number;
  governed_signal_vocs_injected: number;
  persona_atomic_facts: number;
  persona_atomic_facts_held: number;
  persona_atomic_facts_promoted: number;
  persona_cohorts: number;
  unique_assigned_content_entities: number;
}

export interface V3PersonaManifestBoundaries {
  author_level_personas: false;
  counts_are_content_entities_not_users: true;
  database_write: false;
  demographics_supported: false;
  deploy: false;
  live_send: false;
  population_share_supported: false;
  production_unchanged: true;
  provider_call: false;
  real_user_images: false;
  remote_write: false;
}

export interface V3PersonaManifest {
  schema_version: typeof V3_PERSONAS_MANIFEST_SCHEMA;
  snapshot_id: string;
  delivery_mode: 'versioned_static_content_entity_personas_v3';
  generated_at_utc: string;
  source_facts_manifest_sha256: string;
  source_facts_validation_receipt_sha256: string;
  automation_manifest_sha256: string;
  automation_classifications_sha256: string;
  reference_manifest_sha256: string;
  persona_dictionary_sha256: string;
  cohort_config_sha256: string;
  governed_signal_manifest_sha256: string;
  governed_signal_snapshot_id: string;
  governed_signal_source_snapshot_id: string;
  governed_signal_validation_receipt_sha256: string;
  status: 'candidate_built';
  consumption_status: 'eligible_for_downstream_consumption';
  promotable: true;
  upstream: {
    consumption_status: 'eligible_for_downstream_consumption';
    promotable: true;
  };
  counts: V3PersonaManifestCounts;
  files: Record<string, V3PersonaFileIntegrity>;
  boundaries: V3PersonaManifestBoundaries;
}

export interface V3PersonaAvatar {
  alt_text: string;
  asset_path: string;
  asset_sha256: string;
  derived_from_reddit_media: false;
  fallback_asset_path: string;
  fallback_asset_sha256: string;
  height: 512;
  identity_claim: false;
  media_type: 'image/svg+xml';
  real_user_image: false;
  synthetic: true;
  width: 512;
}

export type V3PersonaAvailability =
  | 'stable_observed_sample'
  | 'directional_observed_sample'
  | 'unavailable_insufficient_observed_sample';

export interface V3PersonaCohort {
  assignment_count: number;
  avatar: V3PersonaAvatar;
  cohort_id: V3PersonaCohortId;
  comment_count: number;
  coverage_scope: 'observed_content_entities_only';
  definition: string;
  name_cn: string;
  persona_atomic_tag_count: number;
  population_share_supported: false;
  post_count: number;
  status: V3PersonaAvailability;
  thread_count: number;
  unique_entity_count: number;
}

export interface V3PersonasData {
  schema_version: typeof V3_PERSONAS_SCHEMA;
  snapshot_id: string;
  generated_at_utc: string;
  persona_cohort_count: 8;
  personas: V3PersonaCohort[];
  interpretation_boundaries: {
    counts_are_assignments_and_content_entities_not_users: true;
    parent_persona_inheritance: false;
    population_share_supported: false;
    unavailable_means_insufficient_observed_evidence: true;
  };
}

export interface V3PersonaAssignment {
  assignment_id: string;
  cohort_id: V3PersonaCohortId;
  entity_id: string;
  evidence_grade: 'governed_rule_observation' | 'promoted_tag_evidence';
  evidence_scope: Array<'cross_context' | 'current_comment_body' | 'post_body' | 'post_title'>;
  parent_post_id: string;
  persona_tag_ids: string[];
  schema_version: 'reddit_voc_persona_cohort_assignment_v1';
  scope: 'category_context' | 'momcozy_direct' | 'momcozy_multi';
  snapshot_id: string;
  source_entity_type: 'comment' | 'post';
  source_stratum: 'governed_v3_voc';
  thread_id: string;
  voc_id: string;
  voc_tag_ids: string[];
  voc_type: 'comment_context_voc' | 'post_voc';
}

export interface V3PersonaTagsData {
  schema_version: typeof V3_PERSONA_TAGS_SCHEMA;
  snapshot_id: string;
  grain: 'cohort_id_x_voc_id';
  assignment_count: number;
  unique_entity_count: number;
  post_count: number;
  comment_count: number;
  assignments: V3PersonaAssignment[];
  boundaries: {
    author_level_personas: false;
    counts_are_content_entities_not_users: true;
    explicit_automation_excluded: true;
  };
}

export interface V3PersonaTriggerPath {
  path_id: string;
  required_brand_roles_any: string[];
  required_problem_ids_any: string[];
  required_scenario_ids_any: string[];
  required_topic_ids_any: string[];
  required_voc_tag_ids_any: string[];
  requires_bridge_match: boolean;
}

export interface V3PersonaCohortBridgeRow {
  avatar: V3PersonaAvatar;
  bridge_edge_count: number;
  cohort_id: V3PersonaCohortId;
  definition: string;
  name_cn: string;
  persona_tag_ids: string[];
  trigger_paths: V3PersonaTriggerPath[];
}

export interface V3PersonaCohortBridge {
  schema_version: typeof V3_PERSONA_COHORT_BRIDGE_SCHEMA;
  snapshot_id: string;
  config_version: string;
  config_sha256: string;
  cohort_count: 8;
  bridge_edge_count: number;
  unbridged_persona_tag_ids: string[];
  cohorts: V3PersonaCohortBridgeRow[];
}

export interface V3PersonaAtomicReference {
  definition: string;
  dimension: string;
  hit_rate_tier: string;
  keyword_count: number;
  lifecycle_stage: string;
  persona_id: string;
  persona_name: string;
  semantic_pattern: string;
  sub_dimension: string;
}

export interface V3PersonaAtomicCatalog {
  schema_version: typeof V3_PERSONA_ATOMIC_CATALOG_SCHEMA;
  snapshot_id: string;
  atomic_persona_count: 82;
  dictionary_sha256: string;
  atomic_personas: V3PersonaAtomicReference[];
  boundaries: {
    dictionary_closed_set: true;
    facts_are_content_evidence_not_people: true;
  };
}

export interface V3PersonaAvatarAsset {
  url: string | null;
  error: string | null;
  isFallback: boolean;
}

export interface ValidatedV3PersonasOverlay {
  manifest: V3PersonaManifest;
  data: V3PersonasData;
  tags: V3PersonaTagsData;
  bridge: V3PersonaCohortBridge;
  catalog: V3PersonaAtomicCatalog;
}

export interface V3RedditPersonasSnapshot extends ValidatedV3PersonasOverlay {
  releaseId: string;
  avatarAssets: Readonly<Record<V3PersonaCohortId, V3PersonaAvatarAsset>>;
}

export interface LoadRedditV3PersonasOptions {
  basePath: string;
  expectedManifestSha256: string;
  releaseId: string;
}

export class V3PersonasContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'V3PersonasContractError';
  }
}

const COHORT_IDS = Object.keys(V3_PERSONA_COHORT_NAMES) as V3PersonaCohortId[];
const COHORT_ID_SET = new Set<string>(COHORT_IDS);
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const PERSONA_ID_PATTERN = /^PER-[A-Z]+-[0-9]{3}$/;
const REDDIT_ID_PATTERN = /^[a-z0-9]+$/;
const SAFE_ASSET_PATTERN = /^assets\/persona-[a-z0-9-]+\.svg$/;
const MANIFEST_KEYS = [
  'automation_classifications_sha256',
  'automation_manifest_sha256',
  'boundaries',
  'cohort_config_sha256',
  'consumption_status',
  'counts',
  'delivery_mode',
  'files',
  'generated_at_utc',
  'governed_signal_manifest_sha256',
  'governed_signal_snapshot_id',
  'governed_signal_source_snapshot_id',
  'governed_signal_validation_receipt_sha256',
  'persona_dictionary_sha256',
  'promotable',
  'reference_manifest_sha256',
  'schema_version',
  'snapshot_id',
  'source_facts_manifest_sha256',
  'source_facts_validation_receipt_sha256',
  'status',
  'upstream',
] as const;
const COUNT_KEYS = [
  'analysis_ready_vocs',
  'atomic_persona_catalog',
  'automation_classification_rows',
  'automation_excluded_vocs',
  'cohort_assignments',
  'governed_signal_comment_facts_dropped',
  'governed_signal_comment_vocs_dropped_no_direct_evidence',
  'governed_signal_facts_injected',
  'governed_signal_promoted_facts_loaded',
  'governed_signal_vocs_injected',
  'persona_atomic_facts',
  'persona_atomic_facts_held',
  'persona_atomic_facts_promoted',
  'persona_cohorts',
  'unique_assigned_content_entities',
] as const;

let activeV3AvatarUrls: string[] = [];

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new V3PersonasContractError(message);
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  assertContract(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `${label}必须是对象`);
  return value as Record<string, unknown>;
}

function assertExactKeys(value: unknown, expected: readonly string[], label: string): void {
  const record = requireRecord(value, label);
  const actual = Object.keys(record).sort();
  const wanted = [...expected].sort();
  assertContract(
    actual.length === wanted.length && actual.every((key, index) => key === wanted[index]),
    `${label}字段集合异常`,
  );
}

function requireString(value: unknown, label: string): string {
  assertContract(typeof value === 'string' && value.length > 0, `${label}必须是非空字符串`);
  return value;
}

function requireSha256(value: unknown, label: string): string {
  const text = requireString(value, label);
  assertContract(SHA256_PATTERN.test(text), `${label}不是有效 SHA-256`);
  return text;
}

function requireInteger(value: unknown, label: string, minimum = 0): number {
  assertContract(Number.isInteger(value) && Number(value) >= minimum, `${label}不是有效整数`);
  return Number(value);
}

function requireStringArray(value: unknown, label: string): string[] {
  assertContract(Array.isArray(value), `${label}必须是数组`);
  const result = value as unknown[];
  assertContract(result.every((item) => typeof item === 'string' && item.length > 0), `${label}包含无效字符串`);
  assertContract(new Set(result).size === result.length, `${label}包含重复值`);
  return result as string[];
}

function requireUtcTimestamp(value: unknown, label: string): string {
  const text = requireString(value, label);
  assertContract(
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(text)
      && !Number.isNaN(Date.parse(text)),
    `${label}必须是 UTC 时间`,
  );
  return text;
}

function stableValue(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableValue).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableValue(item)}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function assertV3ManifestBoundaries(value: unknown): void {
  assertExactKeys(value, [
    'author_level_personas',
    'counts_are_content_entities_not_users',
    'database_write',
    'demographics_supported',
    'deploy',
    'live_send',
    'population_share_supported',
    'production_unchanged',
    'provider_call',
    'real_user_images',
    'remote_write',
  ], 'V3 画像 manifest boundaries');
  const boundaries = value as V3PersonaManifestBoundaries;
  assertContract(boundaries.production_unchanged === true, 'V3 画像未声明 production unchanged');
  assertContract(boundaries.counts_are_content_entities_not_users === true, 'V3 画像错误把内容实体解释为用户');
  assertContract(
    boundaries.author_level_personas === false
      && boundaries.demographics_supported === false
      && boundaries.population_share_supported === false
      && boundaries.real_user_images === false,
    'V3 画像包含作者、人口或真实头像越界主张',
  );
  assertContract(
    boundaries.database_write === false
      && boundaries.deploy === false
      && boundaries.live_send === false
      && boundaries.provider_call === false
      && boundaries.remote_write === false,
    'V3 画像外部副作用边界异常',
  );
}

function validateFileIntegrity(path: string, value: unknown, counts: V3PersonaManifestCounts): V3PersonaFileIntegrity {
  const isSvg = path.endsWith('.svg');
  const isJsonl = path === 'persona-atomic-facts.jsonl';
  assertExactKeys(
    value,
    isSvg ? ['bytes', 'height', 'media_type', 'sha256', 'width'] : ['bytes', 'media_type', 'rows', 'sha256'],
    `V3 画像文件完整性 ${path}`,
  );
  const integrity = value as V3PersonaFileIntegrity;
  requireInteger(integrity.bytes, `V3 画像文件 bytes ${path}`, 1);
  requireSha256(integrity.sha256, `V3 画像文件 SHA-256 ${path}`);
  if (isSvg) {
    assertContract(SAFE_ASSET_PATTERN.test(path), `V3 画像头像路径异常：${path}`);
    assertContract(
      integrity.media_type === 'image/svg+xml' && integrity.width === 512 && integrity.height === 512,
      `V3 画像头像元数据异常：${path}`,
    );
  } else {
    assertContract(
      integrity.media_type === (isJsonl ? 'application/x-ndjson' : 'application/json'),
      `V3 画像文件 media type 异常：${path}`,
    );
    assertContract(
      integrity.rows === (isJsonl ? counts.persona_atomic_facts : 1),
      `V3 画像文件 rows 异常：${path}`,
    );
  }
  return integrity;
}

export function validateV3PersonaManifest(value: unknown): V3PersonaManifest {
  assertExactKeys(value, MANIFEST_KEYS, 'V3 画像 manifest');
  const manifest = value as V3PersonaManifest;
  assertContract(manifest.schema_version === V3_PERSONAS_MANIFEST_SCHEMA, 'V3 画像 manifest schema 不受支持');
  assertContract(manifest.delivery_mode === 'versioned_static_content_entity_personas_v3', 'V3 画像 delivery mode 异常');
  requireString(manifest.snapshot_id, 'V3 画像 snapshot_id');
  requireUtcTimestamp(manifest.generated_at_utc, 'V3 画像 generated_at_utc');
  for (const key of [
    'source_facts_manifest_sha256',
    'source_facts_validation_receipt_sha256',
    'automation_manifest_sha256',
    'automation_classifications_sha256',
    'reference_manifest_sha256',
    'persona_dictionary_sha256',
    'cohort_config_sha256',
    'governed_signal_manifest_sha256',
    'governed_signal_validation_receipt_sha256',
  ] as const) {
    requireSha256(manifest[key], `V3 画像 lineage ${key}`);
  }
  requireString(manifest.governed_signal_snapshot_id, 'V3 画像 governed signal snapshot');
  requireString(manifest.governed_signal_source_snapshot_id, 'V3 画像 governed source snapshot');
  assertContract(
    manifest.status === 'candidate_built'
      && manifest.consumption_status === 'eligible_for_downstream_consumption'
      && manifest.promotable === true,
    'V3 画像候选不具备下游消费资格',
  );
  assertExactKeys(manifest.upstream, ['consumption_status', 'promotable'], 'V3 画像 upstream');
  assertContract(
    manifest.upstream.consumption_status === 'eligible_for_downstream_consumption'
      && manifest.upstream.promotable === true,
    'V3 画像 upstream 未通过消费门禁',
  );
  assertExactKeys(manifest.counts, COUNT_KEYS, 'V3 画像 counts');
  for (const key of COUNT_KEYS) requireInteger(manifest.counts[key], `V3 画像 counts.${key}`);
  assertContract(manifest.counts.atomic_persona_catalog === 82, 'V3 画像原子引用必须为 82');
  assertContract(manifest.counts.persona_cohorts === 8, 'V3 画像 cohort 必须为 8');
  assertContract(
    manifest.counts.persona_atomic_facts
      === manifest.counts.persona_atomic_facts_held + manifest.counts.persona_atomic_facts_promoted,
    'V3 画像原子事实状态不守恒',
  );
  assertV3ManifestBoundaries(manifest.boundaries);

  const files = requireRecord(manifest.files, 'V3 画像 manifest files');
  const requiredDocuments = [
    'persona-atomic-catalog.json',
    'persona-atomic-facts.jsonl',
    'persona-cohort-bridge.json',
    'persona-tags.json',
    'personas.json',
  ];
  assertContract(requiredDocuments.every((path) => Boolean(files[path])), 'V3 画像 manifest 缺少治理文档');
  const assetPaths = Object.keys(files).filter((path) => path.endsWith('.svg'));
  assertContract(Object.keys(files).length === 14 && assetPaths.length === 9, 'V3 画像 manifest 文件集合异常');
  assertContract(
    Object.keys(files).every((path) => requiredDocuments.includes(path) || SAFE_ASSET_PATTERN.test(path)),
    'V3 画像 manifest 包含未治理文件',
  );
  for (const [path, integrity] of Object.entries(files)) validateFileIntegrity(path, integrity, manifest.counts);
  return manifest;
}

function validateAvatar(value: unknown, label: string): V3PersonaAvatar {
  assertExactKeys(value, [
    'alt_text',
    'asset_path',
    'asset_sha256',
    'derived_from_reddit_media',
    'fallback_asset_path',
    'fallback_asset_sha256',
    'height',
    'identity_claim',
    'media_type',
    'real_user_image',
    'synthetic',
    'width',
  ], label);
  const avatar = value as V3PersonaAvatar;
  assertContract(SAFE_ASSET_PATTERN.test(avatar.asset_path), `${label}主头像路径异常`);
  assertContract(SAFE_ASSET_PATTERN.test(avatar.fallback_asset_path), `${label}回退头像路径异常`);
  requireSha256(avatar.asset_sha256, `${label}主头像 SHA-256`);
  requireSha256(avatar.fallback_asset_sha256, `${label}回退头像 SHA-256`);
  assertContract(
    avatar.media_type === 'image/svg+xml'
      && avatar.width === 512
      && avatar.height === 512
      && avatar.synthetic === true
      && avatar.real_user_image === false
      && avatar.derived_from_reddit_media === false
      && avatar.identity_claim === false,
    `${label}头像身份边界异常`,
  );
  assertContract(avatar.alt_text.includes('非真实用户'), `${label}替代文本缺少合成画像披露`);
  return avatar;
}

function validateCatalog(value: unknown, manifest: V3PersonaManifest): V3PersonaAtomicCatalog {
  assertExactKeys(value, [
    'atomic_persona_count',
    'atomic_personas',
    'boundaries',
    'dictionary_sha256',
    'schema_version',
    'snapshot_id',
  ], 'V3 画像原子目录');
  const catalog = value as V3PersonaAtomicCatalog;
  assertContract(catalog.schema_version === V3_PERSONA_ATOMIC_CATALOG_SCHEMA, 'V3 画像原子目录 schema 异常');
  assertContract(catalog.snapshot_id === manifest.snapshot_id, 'V3 画像原子目录 snapshot 漂移');
  assertContract(catalog.dictionary_sha256 === manifest.persona_dictionary_sha256, 'V3 画像字典 SHA-256 漂移');
  assertContract(catalog.atomic_persona_count === 82 && catalog.atomic_personas.length === 82, 'V3 画像原子引用必须为 82');
  assertExactKeys(catalog.boundaries, ['dictionary_closed_set', 'facts_are_content_evidence_not_people'], 'V3 画像原子目录 boundaries');
  assertContract(
    catalog.boundaries.dictionary_closed_set === true
      && catalog.boundaries.facts_are_content_evidence_not_people === true,
    'V3 画像原子目录边界异常',
  );
  const ids = new Set<string>();
  for (const item of catalog.atomic_personas) {
    assertExactKeys(item, [
      'definition',
      'dimension',
      'hit_rate_tier',
      'keyword_count',
      'lifecycle_stage',
      'persona_id',
      'persona_name',
      'semantic_pattern',
      'sub_dimension',
    ], `V3 画像原子 ${item.persona_id}`);
    assertContract(PERSONA_ID_PATTERN.test(item.persona_id), `V3 画像原子 ID 异常：${item.persona_id}`);
    assertContract(!ids.has(item.persona_id), `V3 画像原子 ID 重复：${item.persona_id}`);
    ids.add(item.persona_id);
    for (const key of ['definition', 'dimension', 'hit_rate_tier', 'lifecycle_stage', 'persona_name', 'semantic_pattern', 'sub_dimension'] as const) {
      requireString(item[key], `V3 画像原子 ${item.persona_id}.${key}`);
    }
    requireInteger(item.keyword_count, `V3 画像原子 ${item.persona_id}.keyword_count`, 1);
  }
  return catalog;
}

function validateBridge(
  value: unknown,
  manifest: V3PersonaManifest,
  catalog: V3PersonaAtomicCatalog,
): V3PersonaCohortBridge {
  assertExactKeys(value, [
    'bridge_edge_count',
    'cohort_count',
    'cohorts',
    'config_sha256',
    'config_version',
    'schema_version',
    'snapshot_id',
    'unbridged_persona_tag_ids',
  ], 'V3 画像 cohort bridge');
  const bridge = value as V3PersonaCohortBridge;
  assertContract(bridge.schema_version === V3_PERSONA_COHORT_BRIDGE_SCHEMA, 'V3 画像 cohort bridge schema 异常');
  assertContract(bridge.snapshot_id === manifest.snapshot_id, 'V3 画像 cohort bridge snapshot 漂移');
  assertContract(bridge.config_sha256 === manifest.cohort_config_sha256, 'V3 画像 cohort config SHA-256 漂移');
  requireString(bridge.config_version, 'V3 画像 cohort config version');
  assertContract(bridge.cohort_count === 8 && bridge.cohorts.length === 8, 'V3 画像 cohort bridge 必须为 8');
  const catalogIds = new Set(catalog.atomic_personas.map((item) => item.persona_id));
  const cohortIds = new Set<string>();
  const bridgedIds = new Set<string>();
  let edgeCount = 0;
  for (const row of bridge.cohorts) {
    assertExactKeys(row, [
      'avatar',
      'bridge_edge_count',
      'cohort_id',
      'definition',
      'name_cn',
      'persona_tag_ids',
      'trigger_paths',
    ], `V3 画像 cohort bridge ${row.cohort_id}`);
    assertContract(COHORT_ID_SET.has(row.cohort_id), `V3 画像 cohort ID 异常：${row.cohort_id}`);
    assertContract(!cohortIds.has(row.cohort_id), `V3 画像 cohort 重复：${row.cohort_id}`);
    cohortIds.add(row.cohort_id);
    assertContract(row.name_cn === V3_PERSONA_COHORT_NAMES[row.cohort_id], `V3 画像 cohort 业务名漂移：${row.cohort_id}`);
    requireString(row.definition, `V3 画像 cohort 定义 ${row.cohort_id}`);
    validateAvatar(row.avatar, `V3 画像 cohort bridge 头像 ${row.cohort_id}`);
    const personaTagIds = requireStringArray(row.persona_tag_ids, `V3 画像 cohort 原子引用 ${row.cohort_id}`);
    assertContract(personaTagIds.length > 0, `V3 画像 cohort 缺少原子引用：${row.cohort_id}`);
    assertContract(personaTagIds.every((id) => catalogIds.has(id)), `V3 画像 cohort 引用了目录外原子：${row.cohort_id}`);
    assertContract(row.bridge_edge_count === personaTagIds.length, `V3 画像 cohort bridge edge 不守恒：${row.cohort_id}`);
    edgeCount += row.bridge_edge_count;
    personaTagIds.forEach((id) => bridgedIds.add(id));
    assertContract(Array.isArray(row.trigger_paths) && row.trigger_paths.length > 0, `V3 画像 cohort 缺少触发路径：${row.cohort_id}`);
    const pathIds = new Set<string>();
    for (const path of row.trigger_paths) {
      assertExactKeys(path, [
        'path_id',
        'required_brand_roles_any',
        'required_problem_ids_any',
        'required_scenario_ids_any',
        'required_topic_ids_any',
        'required_voc_tag_ids_any',
        'requires_bridge_match',
      ], `V3 画像触发路径 ${row.cohort_id}`);
      requireString(path.path_id, `V3 画像触发路径 ID ${row.cohort_id}`);
      assertContract(!pathIds.has(path.path_id), `V3 画像触发路径重复：${row.cohort_id}/${path.path_id}`);
      pathIds.add(path.path_id);
      for (const key of [
        'required_brand_roles_any',
        'required_problem_ids_any',
        'required_scenario_ids_any',
        'required_topic_ids_any',
        'required_voc_tag_ids_any',
      ] as const) requireStringArray(path[key], `V3 画像触发路径 ${row.cohort_id}.${key}`);
      assertContract(typeof path.requires_bridge_match === 'boolean', `V3 画像触发路径 bridge 状态异常：${row.cohort_id}`);
    }
  }
  assertContract(cohortIds.size === COHORT_IDS.length, 'V3 画像 cohort ID 集合不完整');
  assertContract(edgeCount === bridge.bridge_edge_count, 'V3 画像 cohort bridge 总边数不守恒');
  const unbridged = requireStringArray(bridge.unbridged_persona_tag_ids, 'V3 未桥接画像原子');
  assertContract(unbridged.every((id) => catalogIds.has(id) && !bridgedIds.has(id)), 'V3 未桥接画像原子集合异常');
  assertContract(
    new Set([...bridgedIds, ...unbridged]).size === catalog.atomic_persona_count,
    'V3 82 个画像原子未被 bridge/unbridged 完整对账',
  );
  return bridge;
}

function validatePersonas(
  value: unknown,
  manifest: V3PersonaManifest,
  bridge: V3PersonaCohortBridge,
): V3PersonasData {
  assertExactKeys(value, [
    'generated_at_utc',
    'interpretation_boundaries',
    'persona_cohort_count',
    'personas',
    'schema_version',
    'snapshot_id',
  ], 'V3 画像数据');
  const data = value as V3PersonasData;
  assertContract(data.schema_version === V3_PERSONAS_SCHEMA, 'V3 画像数据 schema 异常');
  assertContract(data.snapshot_id === manifest.snapshot_id, 'V3 画像数据 snapshot 漂移');
  assertContract(data.generated_at_utc === manifest.generated_at_utc, 'V3 画像数据生成时间漂移');
  assertContract(data.persona_cohort_count === 8 && data.personas.length === 8, 'V3 画像 cohort 数量必须为 8');
  assertExactKeys(data.interpretation_boundaries, [
    'counts_are_assignments_and_content_entities_not_users',
    'parent_persona_inheritance',
    'population_share_supported',
    'unavailable_means_insufficient_observed_evidence',
  ], 'V3 画像 interpretation boundaries');
  assertContract(
    data.interpretation_boundaries.counts_are_assignments_and_content_entities_not_users === true
      && data.interpretation_boundaries.parent_persona_inheritance === false
      && data.interpretation_boundaries.population_share_supported === false
      && data.interpretation_boundaries.unavailable_means_insufficient_observed_evidence === true,
    'V3 画像解释边界异常',
  );
  const bridgeById = new Map(bridge.cohorts.map((row) => [row.cohort_id, row]));
  const cohortIds = new Set<string>();
  let assignmentCount = 0;
  for (const cohort of data.personas) {
    assertExactKeys(cohort, [
      'assignment_count',
      'avatar',
      'cohort_id',
      'comment_count',
      'coverage_scope',
      'definition',
      'name_cn',
      'persona_atomic_tag_count',
      'population_share_supported',
      'post_count',
      'status',
      'thread_count',
      'unique_entity_count',
    ], `V3 画像 cohort ${cohort.cohort_id}`);
    assertContract(COHORT_ID_SET.has(cohort.cohort_id), `V3 画像 cohort ID 异常：${cohort.cohort_id}`);
    assertContract(!cohortIds.has(cohort.cohort_id), `V3 画像 cohort 重复：${cohort.cohort_id}`);
    cohortIds.add(cohort.cohort_id);
    const bridgeRow = bridgeById.get(cohort.cohort_id);
    assertContract(bridgeRow !== undefined, `V3 画像 cohort 缺少 bridge：${cohort.cohort_id}`);
    assertContract(cohort.name_cn === V3_PERSONA_COHORT_NAMES[cohort.cohort_id], `V3 画像 cohort 业务名漂移：${cohort.cohort_id}`);
    assertContract(cohort.definition === bridgeRow.definition, `V3 画像 cohort 定义与 bridge 漂移：${cohort.cohort_id}`);
    assertContract(stableValue(cohort.avatar) === stableValue(bridgeRow.avatar), `V3 画像 cohort 头像与 bridge 漂移：${cohort.cohort_id}`);
    validateAvatar(cohort.avatar, `V3 画像 cohort 头像 ${cohort.cohort_id}`);
    for (const key of ['assignment_count', 'comment_count', 'persona_atomic_tag_count', 'post_count', 'thread_count', 'unique_entity_count'] as const) {
      requireInteger(cohort[key], `V3 画像 cohort ${cohort.cohort_id}.${key}`);
    }
    assertContract(cohort.assignment_count === cohort.post_count + cohort.comment_count, `V3 画像帖子评论拆分不守恒：${cohort.cohort_id}`);
    assertContract(cohort.unique_entity_count === cohort.assignment_count, `V3 画像内容实体粒度不守恒：${cohort.cohort_id}`);
    assertContract(cohort.thread_count <= cohort.unique_entity_count, `V3 画像线程数异常：${cohort.cohort_id}`);
    assertContract(cohort.persona_atomic_tag_count === bridgeRow.persona_tag_ids.length, `V3 画像原子引用数漂移：${cohort.cohort_id}`);
    assertContract(cohort.coverage_scope === 'observed_content_entities_only', `V3 画像覆盖 scope 异常：${cohort.cohort_id}`);
    assertContract(cohort.population_share_supported === false, `V3 画像错误支持人口占比：${cohort.cohort_id}`);
    assertContract([
      'stable_observed_sample',
      'directional_observed_sample',
      'unavailable_insufficient_observed_sample',
    ].includes(cohort.status), `V3 画像可用性状态异常：${cohort.cohort_id}`);
    assignmentCount += cohort.assignment_count;
  }
  assertContract(cohortIds.size === COHORT_IDS.length, 'V3 画像 cohort 集合不完整');
  assertContract(assignmentCount === manifest.counts.cohort_assignments, 'V3 画像 cohort assignment 总数与 manifest 漂移');
  return data;
}

function validateTags(
  value: unknown,
  manifest: V3PersonaManifest,
  data: V3PersonasData,
  bridge: V3PersonaCohortBridge,
  catalog: V3PersonaAtomicCatalog,
): V3PersonaTagsData {
  assertExactKeys(value, [
    'assignment_count',
    'assignments',
    'boundaries',
    'comment_count',
    'grain',
    'post_count',
    'schema_version',
    'snapshot_id',
    'unique_entity_count',
  ], 'V3 persona-tags');
  const tags = value as V3PersonaTagsData;
  assertContract(tags.schema_version === V3_PERSONA_TAGS_SCHEMA, 'V3 persona-tags schema 异常');
  assertContract(tags.snapshot_id === manifest.snapshot_id, 'V3 persona-tags snapshot 漂移');
  assertContract(tags.grain === 'cohort_id_x_voc_id', 'V3 persona-tags 粒度异常');
  for (const key of ['assignment_count', 'comment_count', 'post_count', 'unique_entity_count'] as const) {
    requireInteger(tags[key], `V3 persona-tags.${key}`);
  }
  assertContract(tags.assignment_count === tags.assignments.length, 'V3 persona-tags assignment 数组不守恒');
  assertContract(tags.assignment_count === tags.post_count + tags.comment_count, 'V3 persona-tags 帖子评论拆分不守恒');
  assertContract(tags.assignment_count === manifest.counts.cohort_assignments, 'V3 persona-tags assignment 与 manifest 漂移');
  assertContract(tags.unique_entity_count === manifest.counts.unique_assigned_content_entities, 'V3 persona-tags 内容实体与 manifest 漂移');
  assertExactKeys(tags.boundaries, [
    'author_level_personas',
    'counts_are_content_entities_not_users',
    'explicit_automation_excluded',
  ], 'V3 persona-tags boundaries');
  assertContract(
    tags.boundaries.author_level_personas === false
      && tags.boundaries.counts_are_content_entities_not_users === true
      && tags.boundaries.explicit_automation_excluded === true,
    'V3 persona-tags 边界异常',
  );

  const catalogIds = new Set(catalog.atomic_personas.map((item) => item.persona_id));
  const bridgeById = new Map(bridge.cohorts.map((row) => [row.cohort_id, new Set(row.persona_tag_ids)]));
  const assignmentIds = new Set<string>();
  const grainKeys = new Set<string>();
  const uniqueEntities = new Set<string>();
  const byCohort = new Map<V3PersonaCohortId, V3PersonaAssignment[]>();
  let postCount = 0;
  let commentCount = 0;
  for (const assignment of tags.assignments) {
    assertExactKeys(assignment, [
      'assignment_id',
      'cohort_id',
      'entity_id',
      'evidence_grade',
      'evidence_scope',
      'parent_post_id',
      'persona_tag_ids',
      'schema_version',
      'scope',
      'snapshot_id',
      'source_entity_type',
      'source_stratum',
      'thread_id',
      'voc_id',
      'voc_tag_ids',
      'voc_type',
    ], `V3 persona assignment ${assignment.assignment_id}`);
    requireSha256(assignment.assignment_id, 'V3 persona assignment ID');
    assertContract(!assignmentIds.has(assignment.assignment_id), `V3 persona assignment ID 重复：${assignment.assignment_id}`);
    assignmentIds.add(assignment.assignment_id);
    assertContract(COHORT_ID_SET.has(assignment.cohort_id), `V3 persona assignment cohort 异常：${assignment.cohort_id}`);
    const grainKey = `${assignment.cohort_id}|${assignment.voc_id}`;
    assertContract(!grainKeys.has(grainKey), `V3 persona assignment 粒度重复：${grainKey}`);
    grainKeys.add(grainKey);
    assertContract(assignment.schema_version === 'reddit_voc_persona_cohort_assignment_v1', 'V3 persona assignment schema 异常');
    assertContract(assignment.snapshot_id === manifest.snapshot_id, 'V3 persona assignment snapshot 漂移');
    assertContract(assignment.source_stratum === 'governed_v3_voc', 'V3 persona assignment 来源层异常');
    assertContract(['category_context', 'momcozy_direct', 'momcozy_multi'].includes(assignment.scope), 'V3 persona assignment scope 异常');
    assertContract(['governed_rule_observation', 'promoted_tag_evidence'].includes(assignment.evidence_grade), 'V3 persona assignment 证据等级异常');
    assertContract(REDDIT_ID_PATTERN.test(assignment.parent_post_id), 'V3 persona assignment 父帖 ID 异常');
    assertContract(assignment.thread_id === assignment.parent_post_id, 'V3 persona assignment 线程与父帖不一致');
    const evidenceScope = requireStringArray(assignment.evidence_scope, `V3 persona assignment evidence_scope ${assignment.assignment_id}`);
    assertContract(evidenceScope.every((scope) => ['cross_context', 'current_comment_body', 'post_body', 'post_title'].includes(scope)), 'V3 persona assignment evidence_scope 异常');
    if (assignment.source_entity_type === 'post') {
      assertContract(
        assignment.voc_type === 'post_voc'
          && assignment.voc_id === `post:${assignment.parent_post_id}`
          && assignment.entity_id === `t3_${assignment.parent_post_id}`,
        'V3 帖子画像 canonical identity 异常',
      );
      assertContract(evidenceScope.includes('post_title') || evidenceScope.includes('post_body'), 'V3 帖子画像缺少当前帖子证据');
      postCount += 1;
    } else {
      assertContract(assignment.source_entity_type === 'comment', 'V3 persona assignment 实体类型异常');
      const commentId = assignment.entity_id.replace(/^t1_/, '');
      assertContract(
        REDDIT_ID_PATTERN.test(commentId)
          && assignment.voc_type === 'comment_context_voc'
          && assignment.voc_id === `comment:${commentId}`
          && assignment.entity_id === `t1_${commentId}`,
        'V3 评论画像 canonical identity 异常',
      );
      assertContract(evidenceScope.includes('current_comment_body'), 'V3 评论画像缺少 current_comment_body 评论正文证据');
      commentCount += 1;
    }
    const personaTagIds = requireStringArray(assignment.persona_tag_ids, `V3 persona assignment persona_tag_ids ${assignment.assignment_id}`);
    const bridgeIds = bridgeById.get(assignment.cohort_id);
    assertContract(bridgeIds !== undefined, `V3 persona assignment 缺少 cohort bridge：${assignment.cohort_id}`);
    assertContract(personaTagIds.every((id) => catalogIds.has(id) && bridgeIds.has(id)), `V3 persona assignment 原子引用越界：${assignment.assignment_id}`);
    requireStringArray(assignment.voc_tag_ids, `V3 persona assignment voc_tag_ids ${assignment.assignment_id}`);
    uniqueEntities.add(assignment.entity_id);
    const group = byCohort.get(assignment.cohort_id) ?? [];
    group.push(assignment);
    byCohort.set(assignment.cohort_id, group);
  }
  assertContract(postCount === tags.post_count && commentCount === tags.comment_count, 'V3 persona-tags 帖子评论复算失败');
  assertContract(uniqueEntities.size === tags.unique_entity_count, 'V3 persona-tags 内容实体去重复算失败');
  for (const cohort of data.personas) {
    const rows = byCohort.get(cohort.cohort_id) ?? [];
    const rowPosts = rows.filter((row) => row.source_entity_type === 'post').length;
    const rowComments = rows.filter((row) => row.source_entity_type === 'comment').length;
    const rowThreads = new Set(rows.map((row) => row.thread_id)).size;
    assertContract(rows.length === cohort.assignment_count, `V3 cohort assignment 复算失败：${cohort.cohort_id}`);
    assertContract(rowPosts === cohort.post_count && rowComments === cohort.comment_count, `V3 cohort 帖子评论复算失败：${cohort.cohort_id}`);
    assertContract(rowThreads === cohort.thread_count, `V3 cohort 线程复算失败：${cohort.cohort_id}`);
  }
  return tags;
}

function assertManifestAssetBindings(
  manifest: V3PersonaManifest,
  data: V3PersonasData,
): void {
  const expectedPaths = new Set<string>();
  for (const cohort of data.personas) {
    expectedPaths.add(cohort.avatar.asset_path);
    expectedPaths.add(cohort.avatar.fallback_asset_path);
    const primary = manifest.files[cohort.avatar.asset_path];
    const fallback = manifest.files[cohort.avatar.fallback_asset_path];
    assertContract(Boolean(primary) && primary.sha256 === cohort.avatar.asset_sha256, `V3 画像主头像 manifest 绑定异常：${cohort.cohort_id}`);
    assertContract(Boolean(fallback) && fallback.sha256 === cohort.avatar.fallback_asset_sha256, `V3 画像回退头像 manifest 绑定异常：${cohort.cohort_id}`);
  }
  const manifestPaths = Object.keys(manifest.files).filter((path) => path.endsWith('.svg'));
  assertContract(
    expectedPaths.size === 9
      && expectedPaths.size === manifestPaths.length
      && manifestPaths.every((path) => expectedPaths.has(path)),
    'V3 画像头像文件集合与 cohort 不守恒',
  );
}

export function validateV3PersonasOverlay(
  manifestValue: unknown,
  personasValue: unknown,
  tagsValue: unknown,
  bridgeValue: unknown,
  catalogValue: unknown,
): ValidatedV3PersonasOverlay {
  const manifest = validateV3PersonaManifest(manifestValue);
  const catalog = validateCatalog(catalogValue, manifest);
  const bridge = validateBridge(bridgeValue, manifest, catalog);
  const data = validatePersonas(personasValue, manifest, bridge);
  const tags = validateTags(tagsValue, manifest, data, bridge, catalog);
  assertManifestAssetBindings(manifest, data);
  return { manifest, data, tags, bridge, catalog };
}

async function sha256Bytes(bytes: Uint8Array): Promise<string> {
  assertContract(globalThis.crypto?.subtle, '当前浏览器不支持 V3 画像完整性校验');
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', copy.buffer);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

function joinPublicPath(basePath: string, path: string): string {
  return `${basePath.replace(/\/$/, '')}/${path}`;
}

async function fetchBytes(basePath: string, path: string): Promise<{ bytes: Uint8Array; mediaType: string | null }> {
  const response = await fetch(joinPublicPath(basePath, path), { cache: 'force-cache' });
  if (!response.ok) throw new V3PersonasContractError(`V3 画像文件加载失败：${path}（HTTP ${response.status}）`);
  return {
    bytes: new Uint8Array(await response.arrayBuffer()),
    mediaType: response.headers.get('content-type')?.split(';')[0].trim() ?? null,
  };
}

async function fetchVerifiedJson<T>(
  basePath: string,
  path: string,
  integrity: V3PersonaFileIntegrity,
): Promise<T> {
  const { bytes, mediaType } = await fetchBytes(basePath, path);
  assertContract(bytes.byteLength === integrity.bytes, `V3 画像文件 bytes 不一致：${path}`);
  assertContract((await sha256Bytes(bytes)) === integrity.sha256, `V3 画像文件 SHA-256 不一致：${path}`);
  assertContract(mediaType === null || mediaType === 'application/json', `V3 画像 JSON Content-Type 异常：${path}`);
  try {
    return JSON.parse(new TextDecoder().decode(bytes)) as T;
  } catch {
    throw new V3PersonasContractError(`V3 画像文件不是有效 JSON：${path}`);
  }
}

function assertSafeSvg(bytes: Uint8Array, path: string): void {
  const text = new TextDecoder().decode(bytes);
  const withoutSvgNamespace = text.replace(/\sxmlns=["']http:\/\/www\.w3\.org\/2000\/svg["']/i, '');
  assertContract(/<svg(?:\s|>)/i.test(text), `V3 画像头像不是有效 SVG：${path}`);
  assertContract(
    !/<!doctype|<!entity|<\?xml-stylesheet|<(?:script|foreignObject|image|text)\b|\son[a-z]+\s*=|javascript:|data:|https?:\/\/|(?:xlink:)?href\s*=|url\s*\(/i.test(withoutSvgNamespace),
    `V3 画像头像包含不允许的元素、事件或引用：${path}`,
  );
}

async function loadSvgObjectUrl(
  basePath: string,
  path: string,
  integrity: V3PersonaFileIntegrity,
): Promise<string> {
  const { bytes, mediaType } = await fetchBytes(basePath, path);
  assertContract(bytes.byteLength === integrity.bytes, `V3 画像头像 bytes 不一致：${path}`);
  assertContract((await sha256Bytes(bytes)) === integrity.sha256, `V3 画像头像 SHA-256 不一致：${path}`);
  assertContract(mediaType === null || mediaType === 'image/svg+xml', `V3 画像头像 Content-Type 异常：${path}`);
  assertSafeSvg(bytes, path);
  assertContract(typeof URL.createObjectURL === 'function', '当前浏览器不支持已验证 V3 画像对象 URL');
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  const url = URL.createObjectURL(new Blob([copy.buffer], { type: 'image/svg+xml' }));
  activeV3AvatarUrls.push(url);
  return url;
}

export async function loadRedditV3Personas(
  options: LoadRedditV3PersonasOptions,
): Promise<V3RedditPersonasSnapshot> {
  const basePath = requireString(options.basePath, 'V3 画像 basePath');
  assertContract(
    !basePath.includes('://')
      && !basePath.startsWith('data:')
      && !basePath.startsWith('blob:')
      && !basePath.split('/').includes('..'),
    'V3 画像 basePath 必须是站内受控静态路径',
  );
  const expectedManifestSha256 = requireSha256(options.expectedManifestSha256, 'V3 画像 manifest SHA-256');
  assertContract(typeof options.releaseId === 'string' && options.releaseId.length > 0, 'V3 画像 releaseId 必须是非空字符串');
  const manifestBytes = await fetchBytes(basePath, 'manifest.json');
  assertContract(
    (await sha256Bytes(manifestBytes.bytes)) === expectedManifestSha256,
    'V3 画像 manifest SHA-256 不一致',
  );
  assertContract(
    manifestBytes.mediaType === null || manifestBytes.mediaType === 'application/json',
    'V3 画像 manifest Content-Type 异常',
  );
  let rawManifest: unknown;
  try {
    rawManifest = JSON.parse(new TextDecoder().decode(manifestBytes.bytes)) as unknown;
  } catch {
    throw new V3PersonasContractError('V3 画像 manifest 不是有效 JSON');
  }
  const manifest = validateV3PersonaManifest(rawManifest);
  const [data, tags, bridge, catalog] = await Promise.all([
    fetchVerifiedJson<V3PersonasData>(basePath, 'personas.json', manifest.files['personas.json']),
    fetchVerifiedJson<V3PersonaTagsData>(basePath, 'persona-tags.json', manifest.files['persona-tags.json']),
    fetchVerifiedJson<V3PersonaCohortBridge>(basePath, 'persona-cohort-bridge.json', manifest.files['persona-cohort-bridge.json']),
    fetchVerifiedJson<V3PersonaAtomicCatalog>(basePath, 'persona-atomic-catalog.json', manifest.files['persona-atomic-catalog.json']),
  ]);
  const validated = validateV3PersonasOverlay(manifest, data, tags, bridge, catalog);
  const fallbackPath = data.personas[0].avatar.fallback_asset_path;
  assertContract(
    data.personas.every((cohort) => cohort.avatar.fallback_asset_path === fallbackPath),
    'V3 画像 fallback 头像不唯一',
  );
  const fallbackUrl = await loadSvgObjectUrl(basePath, fallbackPath, manifest.files[fallbackPath]);
  const entries = await Promise.all(data.personas.map(async (cohort) => {
    try {
      const url = await loadSvgObjectUrl(basePath, cohort.avatar.asset_path, manifest.files[cohort.avatar.asset_path]);
      return [cohort.cohort_id, { url, error: null, isFallback: false }] as const;
    } catch (error: unknown) {
      return [cohort.cohort_id, {
        url: fallbackUrl,
        error: error instanceof Error ? error.message : `V3 画像头像校验失败：${cohort.avatar.asset_path}`,
        isFallback: true,
      }] as const;
    }
  }));
  return {
    ...validated,
    releaseId: options.releaseId,
    avatarAssets: Object.fromEntries(entries) as Record<V3PersonaCohortId, V3PersonaAvatarAsset>,
  };
}

export function buildV3PersonaEvidenceHref(
  assignment: V3PersonaAssignment,
  snapshotId: string,
  releaseId: string,
): string {
  return buildSnapshotEvidenceHref({
    postId: assignment.parent_post_id,
    commentId: assignment.source_entity_type === 'comment' ? assignment.entity_id : null,
    releaseId,
    snapshotId,
    source: 'personas',
  });
}

export function resetV3PersonaRuntimeForTests(): void {
  if (typeof URL.revokeObjectURL === 'function') {
    activeV3AvatarUrls.forEach((url) => URL.revokeObjectURL(url));
  }
  activeV3AvatarUrls = [];
}
