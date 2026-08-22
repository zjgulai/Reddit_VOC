import { loadRedditInsights } from './service';
import type { RedditInsightsSnapshot } from './types';
import {
  fetchVerifiedReleaseManifest,
  getReleaseDatasetBasePath,
  loadCurrentRelease,
  type CurrentRelease,
} from './release';
import {
  loadRedditV3Personas,
  resetV3PersonaRuntimeForTests,
  V3_PERSONAS_MANIFEST_SCHEMA,
  type V3PersonaManifest,
  type V3RedditPersonasSnapshot,
} from './personasV3';

export * from './personasV3';

export const PERSONAS_MANIFEST_SCHEMA = 'reddit_voc_personas_manifest_v1';
export const PERSONAS_SCHEMA = 'reddit_voc_personas_v1';
export const PERSONA_TAGS_SCHEMA = 'reddit_voc_persona_tags_v1';

export const PERSONA_SOURCE_STRATA = [
  'tencent_production_primary',
  'tencent_isolated_staging',
  'tencent_v2_search_hydrated',
  'tencent_existing_post_comment_hydration',
  'historical_canonical',
  'imported_archive',
] as const;

const PERSONA_SOURCE_STRATUM_SET = new Set<string>(PERSONA_SOURCE_STRATA);

const DICTIONARY_VERSION = 'dim_tag_v6.3_final';
const DICTIONARY_SHA256 = '22664c9c446ddfa17446852079f507ab75b5af3d4dde6e4e3f3e44c195582e14';

interface FileIntegrity {
  bytes: number;
  sha256: string;
  media_type: 'application/json' | 'image/svg+xml';
  width?: number;
  height?: number;
}

export interface PersonaBoundaries {
  production_unchanged: boolean;
  provider_call: boolean;
  database_write: boolean;
  live_send: boolean;
  webhook_send: boolean;
  deploy: boolean;
  schedule_change: boolean;
  independent_human_review: boolean;
  counts_are_content_entities_not_users: boolean;
  author_level_personas: boolean;
  public_author_identifiers: boolean;
  consumer_card_is_reference_not_persona_id: boolean;
  persona_tags_generated: boolean;
  population_share_supported: boolean;
  synthetic_avatars: boolean;
  real_user_image: boolean;
  derived_from_reddit_media: boolean;
  identity_claim: boolean;
}

export interface PersonaManifest {
  schema_version: string;
  dataset_version: string;
  delivery_mode: string;
  generated_at_utc: string;
  base_dataset_version: string;
  base_manifest_sha256: string;
  insights_dataset_version: string;
  insights_manifest_sha256: string;
  dictionary_version: string;
  dictionary_sha256: string;
  config_version: string;
  config_sha256: string;
  tag_repair: {
    applied: boolean;
    schema_version: string | null;
    dataset_version: string | null;
    manifest_sha256: string | null;
    status: string;
  };
  persona_count: number;
  assignment_count: number;
  source_tag_ids: string[];
  files: Record<string, FileIntegrity>;
  boundaries: PersonaBoundaries;
}

export interface PersonaMetrics {
  matched_entities: number;
  matched_posts: number;
  matched_comments: number;
  distinct_pseudonyms: number;
  threads: number;
}

export interface PersonaDictionaryReference {
  consumer_card: string;
  aipl_node: string;
  story_lines: string[];
  intent_type: string[];
  problem_type: string[];
}

export interface PersonaAvatar {
  asset_path: string;
  asset_sha256: string;
  media_type: 'image/svg+xml';
  width: 512;
  height: 512;
  synthetic: boolean;
  real_user_image: boolean;
  derived_from_reddit_media: boolean;
  identity_claim: boolean;
  alt_text: string;
}

export interface AggregatePersona {
  persona_id: string;
  persona_kind: 'content_evidence_cohort';
  name_cn: string;
  status: 'promoted';
  definition: string;
  source_tag_ids: string[];
  evidence_logic: string;
  metrics: PersonaMetrics;
  dictionary_reference: PersonaDictionaryReference;
  avatar: PersonaAvatar;
  coverage_status: 'observed_corpus_only';
  population_share_supported: false;
}

export interface PersonasInterpretationBoundaries {
  counts_are_content_entities_not_users: boolean;
  distinct_pseudonyms_are_not_people: boolean;
  author_level_personas: boolean;
  consumer_card_is_reference_not_persona_id: boolean;
  population_share_supported: boolean;
  demographics_supported: boolean;
  activity_pattern_supported: boolean;
  brand_preference_supported: boolean;
  synthetic_avatars: boolean;
  real_user_image: boolean;
  derived_from_reddit_media: boolean;
  identity_claim: boolean;
}

export interface PersonasData {
  schema_version: string;
  dataset_version: string;
  generated_at_utc: string;
  persona_count: number;
  personas: AggregatePersona[];
  interpretation_boundaries: PersonasInterpretationBoundaries;
}

export interface PersonaAssignment {
  persona_id: string;
  evidence_id: string;
  entity_type: 'post' | 'comment';
  entity_id: string;
  post_id: string;
  tag_id: string;
  evidence_keywords: string[];
  source_stratum: string;
  assignment_status: 'rule_match_under_promoted_tag';
  semantic_gate_scope: 'tag_level_stratified_sample';
  human_validated_assignment: false;
}

export interface PersonaTagsBoundaries {
  assignments_are_content_entities_not_users: boolean;
  human_validated_assignment: boolean;
  tag_gate_is_stratified_sample_not_full_population_review: boolean;
  public_author_identifiers: boolean;
  author_level_personas: boolean;
}

export interface PersonaTagsData {
  schema_version: string;
  dataset_version: string;
  grain: 'persona_id_x_evidence_id';
  assignment_count: number;
  assignments: PersonaAssignment[];
  boundaries: PersonaTagsBoundaries;
}

export interface PersonaAvatarAsset {
  url: string | null;
  error: string | null;
}

export interface ValidatedPersonasOverlay {
  manifest: PersonaManifest;
  data: PersonasData;
  tags: PersonaTagsData;
}

export interface RedditPersonasSnapshot extends ValidatedPersonasOverlay {
  releaseId: string;
  avatarAssets: Readonly<Record<string, PersonaAvatarAsset>>;
}

export type AnyRedditPersonasSnapshot = RedditPersonasSnapshot | V3RedditPersonasSnapshot;

export class PersonasContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PersonasContractError';
  }
}

let personasPromise: Promise<AnyRedditPersonasSnapshot> | null = null;
let activeAvatarUrls: string[] = [];

function isV3PersonaManifest(
  manifest: PersonaManifest | V3PersonaManifest,
): manifest is V3PersonaManifest {
  return manifest.schema_version === V3_PERSONAS_MANIFEST_SCHEMA;
}

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new PersonasContractError(message);
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isSha256(value: unknown): value is string {
  return typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
}

function assertExactKeys(value: object, expected: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  assertContract(
    actual.length === wanted.length && actual.every((key, index) => key === wanted[index]),
    `${label}字段集合异常`,
  );
}

function assertManifestBoundaries(boundaries: PersonaBoundaries): void {
  assertExactKeys(boundaries, [
    'production_unchanged',
    'provider_call',
    'database_write',
    'live_send',
    'webhook_send',
    'deploy',
    'schedule_change',
    'independent_human_review',
    'counts_are_content_entities_not_users',
    'author_level_personas',
    'public_author_identifiers',
    'consumer_card_is_reference_not_persona_id',
    'persona_tags_generated',
    'population_share_supported',
    'synthetic_avatars',
    'real_user_image',
    'derived_from_reddit_media',
    'identity_claim',
  ], '画像 manifest boundaries');
  assertContract(boundaries.production_unchanged === true, '画像 manifest 缺少 production unchanged');
  assertContract(
    boundaries.provider_call === false
      && boundaries.database_write === false
      && boundaries.live_send === false
      && boundaries.webhook_send === false
      && boundaries.deploy === false
      && boundaries.schedule_change === false,
    '画像 manifest 外部副作用边界异常',
  );
  assertContract(boundaries.independent_human_review === false, '画像错误声称独立人工审核');
  assertContract(boundaries.counts_are_content_entities_not_users === true, '画像错误把内容实体解释为用户');
  assertContract(boundaries.author_level_personas === false, '画像错误支持作者级画像');
  assertContract(boundaries.public_author_identifiers === false, '画像公开了作者标识');
  assertContract(boundaries.consumer_card_is_reference_not_persona_id === true, 'consumer_card 画像边界缺失');
  assertContract(boundaries.persona_tags_generated === true, '画像 manifest 未声明独立 persona-tags 产物');
  assertContract(boundaries.population_share_supported === false, '画像错误支持总体人群占比');
  assertContract(boundaries.synthetic_avatars === true, '画像头像未声明为合成资产');
  assertContract(
    boundaries.real_user_image === false
      && boundaries.derived_from_reddit_media === false
      && boundaries.identity_claim === false,
    '画像头像身份边界异常',
  );
}

function validateManifest(
  manifest: PersonaManifest,
  insights: RedditInsightsSnapshot,
  release: CurrentRelease,
): void {
  assertExactKeys(manifest, [
    'schema_version',
    'dataset_version',
    'delivery_mode',
    'generated_at_utc',
    'base_dataset_version',
    'base_manifest_sha256',
    'insights_dataset_version',
    'insights_manifest_sha256',
    'dictionary_version',
    'dictionary_sha256',
    'config_version',
    'config_sha256',
    'tag_repair',
    'persona_count',
    'assignment_count',
    'source_tag_ids',
    'files',
    'boundaries',
  ], '画像 manifest');
  assertContract(manifest.schema_version === PERSONAS_MANIFEST_SCHEMA, '画像 manifest schema 不受支持');
  assertContract(manifest.dataset_version === release.datasets.personas.dataset_version, '画像数据版本与 current release 不一致');
  assertContract(manifest.delivery_mode === 'versioned_static_evidence_personas', '画像 delivery mode 异常');
  assertContract(manifest.base_dataset_version === release.datasets.base.dataset_version, '画像基础快照版本不一致');
  assertContract(
    manifest.base_manifest_sha256 === release.datasets.base.lineage_manifest_sha256,
    '画像基础 lineage 哈希绑定不一致',
  );
  assertContract(manifest.insights_dataset_version === release.datasets.insights.dataset_version, '画像 Insights 版本不一致');
  assertContract(
    manifest.insights_manifest_sha256 === release.datasets.insights.lineage_manifest_sha256,
    '画像 Insights lineage 哈希绑定不一致',
  );
  assertContract(manifest.dictionary_version === DICTIONARY_VERSION, '画像字典版本不一致');
  assertContract(manifest.dictionary_sha256 === DICTIONARY_SHA256, '画像字典哈希不一致');
  assertContract(manifest.base_dataset_version === insights.core.manifest.dataset_version, '画像未绑定当前基础快照');
  assertContract(manifest.insights_dataset_version === insights.manifest.dataset_version, '画像未绑定当前 Insights');
  assertContract(manifest.dictionary_version === insights.manifest.dictionary_version, '画像未绑定当前 Insights 字典');
  assertContract(manifest.dictionary_sha256 === insights.manifest.dictionary_sha256, '画像未绑定当前 Insights 字典哈希');
  if (insights.insights.schema_version === 'reddit_voc_insights_v2') {
    assertContract(insights.manifest.contract_extension === 'reddit_voc_insights_manifest_v2', '画像 v2 lineage 未绑定 Insights v2 manifest');
    assertContract(manifest.base_dataset_version === insights.insights.base_dataset_version, '画像 v2 lineage 基础数据版本漂移');
  }
  assertContract(typeof manifest.config_version === 'string' && manifest.config_version.length > 0, '画像 config version 缺失');
  assertContract(isSha256(manifest.config_sha256), '画像 config SHA-256 异常');
  assertContract(isNonNegativeInteger(manifest.persona_count) && manifest.persona_count > 0, '画像数量异常');
  assertContract(isNonNegativeInteger(manifest.assignment_count), '画像 assignment 数量异常');
  assertContract(
    manifest.source_tag_ids.length > 0
      && new Set(manifest.source_tag_ids).size === manifest.source_tag_ids.length
      && manifest.source_tag_ids.every((tagId) => typeof tagId === 'string' && tagId.length > 0),
    '画像来源标签集合异常',
  );
  const promotedTagIds = insights.insights.schema_version === 'reddit_voc_insights_v2'
    ? new Set(insights.insights.input_contract?.promoted_tag_ids ?? [])
    : new Set(insights.insights.signals.map((signal) => signal.tag_id));
  assertContract(
    manifest.source_tag_ids.every((tagId) => promotedTagIds.has(tagId)),
    '画像来源标签未被当前 Insights 晋级集合覆盖',
  );
  const filePaths = Object.keys(manifest.files);
  assertContract(Boolean(manifest.files['personas.json']) && Boolean(manifest.files['persona-tags.json']), '画像 manifest 缺少治理 JSON');
  assertContract(filePaths.length === manifest.persona_count + 2, '画像 manifest 文件数与画像数不守恒');
  assertContract(
    filePaths.filter((path) => path !== 'personas.json' && path !== 'persona-tags.json')
      .every((path) => /^assets\/[a-z0-9][a-z0-9-]*\.svg$/.test(path)),
    '画像 manifest 包含非受控头像路径',
  );
  assertManifestBoundaries(manifest.boundaries);

  for (const [path, integrity] of Object.entries(manifest.files)) {
    assertContract(isNonNegativeInteger(integrity.bytes) && integrity.bytes > 0, `画像文件字节数异常：${path}`);
    assertContract(isSha256(integrity.sha256), `画像文件 SHA-256 异常：${path}`);
    if (path.endsWith('.json')) {
      assertExactKeys(integrity, ['bytes', 'sha256', 'media_type'], `画像文件完整性 ${path}`);
      assertContract(integrity.media_type === 'application/json', `画像 JSON media type 异常：${path}`);
      assertContract(integrity.width === undefined && integrity.height === undefined, `画像 JSON 错误包含尺寸：${path}`);
    } else {
      assertExactKeys(integrity, ['bytes', 'sha256', 'media_type', 'width', 'height'], `画像文件完整性 ${path}`);
      assertContract(integrity.media_type === 'image/svg+xml', `画像头像 media type 异常：${path}`);
      assertContract(integrity.width === 512 && integrity.height === 512, `画像头像尺寸声明异常：${path}`);
    }
  }

  const repair = manifest.tag_repair;
  assertExactKeys(repair, ['applied', 'schema_version', 'dataset_version', 'manifest_sha256', 'status'], '画像 tag repair');
  assertContract(typeof repair.applied === 'boolean' && typeof repair.status === 'string' && repair.status.length > 0, '画像 tag repair 状态异常');
  if (repair.applied) {
    assertContract(Boolean(repair.schema_version && repair.dataset_version), '画像 tag repair 版本缺失');
    assertContract(isSha256(repair.manifest_sha256), '画像 tag repair manifest SHA-256 异常');
  }
}

function assertInterpretationBoundaries(boundaries: PersonasInterpretationBoundaries): void {
  assertExactKeys(boundaries, [
    'counts_are_content_entities_not_users',
    'distinct_pseudonyms_are_not_people',
    'author_level_personas',
    'consumer_card_is_reference_not_persona_id',
    'population_share_supported',
    'demographics_supported',
    'activity_pattern_supported',
    'brand_preference_supported',
    'synthetic_avatars',
    'real_user_image',
    'derived_from_reddit_media',
    'identity_claim',
  ], '画像 interpretation boundaries');
  assertContract(boundaries.counts_are_content_entities_not_users === true, '画像错误把实体计数解释为用户');
  assertContract(boundaries.distinct_pseudonyms_are_not_people === true, '画像错误把不同伪名解释为真实人数');
  assertContract(boundaries.author_level_personas === false, '画像错误支持作者级画像');
  assertContract(boundaries.consumer_card_is_reference_not_persona_id === true, '画像错误把 consumer_card 当作 persona_id');
  assertContract(boundaries.population_share_supported === false, '画像错误支持总体占比');
  assertContract(
    boundaries.demographics_supported === false
      && boundaries.activity_pattern_supported === false
      && boundaries.brand_preference_supported === false,
    '画像包含当前不支持的人口或行为推断',
  );
  assertContract(boundaries.synthetic_avatars === true, '画像头像未声明为合成资产');
  assertContract(
    boundaries.real_user_image === false
      && boundaries.derived_from_reddit_media === false
      && boundaries.identity_claim === false,
    '画像头像身份声明异常',
  );
}

function validatePersona(
  persona: AggregatePersona,
  manifest: PersonaManifest,
  signalById: ReadonlyMap<string, RedditInsightsSnapshot['insights']['signals'][number]>,
  promotedTagIds: ReadonlySet<string>,
  validateLegacySignalCounts: boolean,
): void {
  assertExactKeys(persona, [
    'persona_id',
    'persona_kind',
    'name_cn',
    'status',
    'definition',
    'source_tag_ids',
    'evidence_logic',
    'metrics',
    'dictionary_reference',
    'avatar',
    'coverage_status',
    'population_share_supported',
  ], `画像 ${persona.persona_id}`);
  assertContract(persona.persona_kind === 'content_evidence_cohort', `画像类型异常：${persona.persona_id}`);
  assertContract(persona.status === 'promoted', `画像未通过门禁：${persona.persona_id}`);
  assertContract(persona.name_cn.length > 0 && persona.definition.length > 0, `画像名称或定义缺失：${persona.persona_id}`);
  assertContract(persona.evidence_logic === 'ANY promoted tag', `画像证据逻辑异常：${persona.persona_id}`);
  assertContract(persona.coverage_status === 'observed_corpus_only', `画像覆盖状态异常：${persona.persona_id}`);
  assertContract(persona.population_share_supported === false, `画像错误支持总体占比：${persona.persona_id}`);
  assertContract(persona.source_tag_ids.length === 1, `画像来源标签数量异常：${persona.persona_id}`);
  const sourceTagId = persona.source_tag_ids[0];
  assertContract(/^[A-Z0-9][A-Z0-9-]{2,127}$/.test(persona.persona_id), `画像 ID 异常：${persona.persona_id}`);
  assertContract(manifest.source_tag_ids.includes(sourceTagId), `画像引用未晋级标签或不在 manifest：${persona.persona_id}`);
  assertContract(promotedTagIds.has(sourceTagId), `画像引用未晋级标签：${sourceTagId}`);
  const signal = signalById.get(sourceTagId);
  if (validateLegacySignalCounts) assertContract(signal, `画像引用未晋级标签：${sourceTagId}`);

  const metrics = persona.metrics;
  assertExactKeys(metrics, [
    'matched_entities',
    'matched_posts',
    'matched_comments',
    'distinct_pseudonyms',
    'threads',
  ], `画像 metrics ${persona.persona_id}`);
  for (const [key, value] of Object.entries(metrics)) {
    assertContract(isNonNegativeInteger(value), `画像指标无效：${persona.persona_id}/${key}`);
  }
  assertContract(metrics.matched_entities === metrics.matched_posts + metrics.matched_comments, `画像实体计数不一致：${persona.persona_id}`);
  if (validateLegacySignalCounts && signal) {
    assertContract(metrics.matched_entities === signal.matched_entities, `画像与 Insights 实体计数不一致：${persona.persona_id}`);
    assertContract(metrics.matched_posts === signal.matched_posts, `画像与 Insights 帖子计数不一致：${persona.persona_id}`);
    assertContract(metrics.matched_comments === signal.matched_comments, `画像与 Insights 评论计数不一致：${persona.persona_id}`);
  }
  assertContract(metrics.distinct_pseudonyms >= 10, `画像不同伪名参与者低于公开阈值：${persona.persona_id}`);
  assertContract(metrics.threads > 0 && metrics.threads <= metrics.matched_entities, `画像线程计数异常：${persona.persona_id}`);

  const reference = persona.dictionary_reference;
  assertExactKeys(reference, ['consumer_card', 'aipl_node', 'story_lines', 'intent_type', 'problem_type'], `画像字典参考 ${persona.persona_id}`);
  assertContract(Boolean(reference.consumer_card) && Boolean(reference.aipl_node), `画像字典参考缺失：${persona.persona_id}`);
  assertContract(reference.story_lines.length > 0 && reference.intent_type.length > 0 && reference.problem_type.length > 0, `画像字典多值参考缺失：${persona.persona_id}`);
  if (signal) {
    assertContract(reference.consumer_card === signal.dictionary_reference.consumer_card, `画像 consumer_card 漂移：${persona.persona_id}`);
    assertContract(reference.aipl_node === signal.dictionary_reference.aipl_node, `画像 AIPL 漂移：${persona.persona_id}`);
  }

  const avatar = persona.avatar;
  assertExactKeys(avatar, [
    'asset_path',
    'asset_sha256',
    'media_type',
    'width',
    'height',
    'synthetic',
    'real_user_image',
    'derived_from_reddit_media',
    'identity_claim',
    'alt_text',
  ], `画像头像 ${persona.persona_id}`);
  assertContract(/^assets\/[a-z0-9][a-z0-9-]*\.svg$/.test(avatar.asset_path), `画像头像路径异常：${persona.persona_id}`);
  const integrity = manifest.files[avatar.asset_path];
  assertContract(Boolean(integrity), `画像头像未列入 manifest：${persona.persona_id}`);
  assertContract(avatar.asset_sha256 === integrity.sha256, `画像头像 SHA-256 绑定不一致：${persona.persona_id}`);
  assertContract(avatar.media_type === 'image/svg+xml' && integrity.media_type === avatar.media_type, `画像头像 media type 不一致：${persona.persona_id}`);
  assertContract(avatar.width === 512 && avatar.height === 512, `画像头像尺寸异常：${persona.persona_id}`);
  assertContract(avatar.synthetic === true, `画像头像未声明为合成资产：${persona.persona_id}`);
  assertContract(
    avatar.real_user_image === false
      && avatar.derived_from_reddit_media === false
      && avatar.identity_claim === false,
    `画像头像身份边界异常：${persona.persona_id}`,
  );
  assertContract(avatar.alt_text.length > 0 && avatar.alt_text.includes('非真实用户'), `画像头像替代文本异常：${persona.persona_id}`);
}

function validateAssignments(
  tags: PersonaTagsData,
  manifest: PersonaManifest,
  personas: PersonasData,
  insights: RedditInsightsSnapshot,
): void {
  assertExactKeys(tags, [
    'schema_version',
    'dataset_version',
    'grain',
    'assignment_count',
    'assignments',
    'boundaries',
  ], 'persona-tags');
  assertContract(tags.schema_version === PERSONA_TAGS_SCHEMA, 'persona-tags schema 不受支持');
  assertContract(tags.dataset_version === manifest.dataset_version, 'persona-tags 数据版本不一致');
  assertContract(tags.grain === 'persona_id_x_evidence_id', 'persona-tags 粒度异常');
  assertContract(tags.assignment_count === manifest.assignment_count, 'persona-tags assignment 数量与 manifest 不一致');
  assertContract(tags.assignments.length === tags.assignment_count, 'persona-tags assignment 数组数量不一致');
  const boundaries = tags.boundaries;
  assertExactKeys(boundaries, [
    'assignments_are_content_entities_not_users',
    'human_validated_assignment',
    'tag_gate_is_stratified_sample_not_full_population_review',
    'public_author_identifiers',
    'author_level_personas',
  ], 'persona-tags boundaries');
  assertContract(boundaries.assignments_are_content_entities_not_users === true, 'persona-tags 错误把 assignment 解释为用户');
  assertContract(boundaries.human_validated_assignment === false, 'persona-tags 错误声称逐条人工验证');
  assertContract(boundaries.tag_gate_is_stratified_sample_not_full_population_review === true, 'persona-tags 缺少标签门禁范围边界');
  assertContract(boundaries.public_author_identifiers === false && boundaries.author_level_personas === false, 'persona-tags 作者隐私边界异常');

  const personaById = new Map(personas.personas.map((persona) => [persona.persona_id, persona]));
  const postIds = new Set(insights.core.posts.map((post) => post.post_id));
  const promotedTagIds = insights.insights.schema_version === 'reddit_voc_insights_v2'
    ? new Set(insights.insights.input_contract?.promoted_tag_ids ?? [])
    : new Set(insights.insights.signals.map((signal) => signal.tag_id));
  const assignmentKeys = new Set<string>();
  const assignmentsByPersona = new Map<string, PersonaAssignment[]>();
  for (const assignment of tags.assignments) {
    assertExactKeys(assignment, [
      'persona_id',
      'evidence_id',
      'entity_type',
      'entity_id',
      'post_id',
      'tag_id',
      'evidence_keywords',
      'source_stratum',
      'assignment_status',
      'semantic_gate_scope',
      'human_validated_assignment',
    ], `persona assignment ${assignment.evidence_id}`);
    const persona = personaById.get(assignment.persona_id);
    assertContract(persona, `persona assignment 引用了未知画像：${assignment.persona_id}`);
    assertContract(persona.source_tag_ids.includes(assignment.tag_id), `persona assignment 标签与画像不一致：${assignment.evidence_id}`);
    assertContract(manifest.source_tag_ids.includes(assignment.tag_id), `persona assignment 标签不在 manifest：${assignment.evidence_id}`);
    assertContract(promotedTagIds.has(assignment.tag_id), `persona assignment 标签未被 Insights 晋级：${assignment.evidence_id}`);
    assertContract(postIds.has(assignment.post_id), `persona assignment 引用了未知帖子：${assignment.evidence_id}`);
    assertContract(
      assignment.entity_type === 'post' || assignment.entity_type === 'comment',
      `persona assignment 实体类型异常：${assignment.evidence_id}`,
    );
    assertContract(assignment.evidence_id === `${assignment.entity_type}:${assignment.entity_id}`, `persona assignment evidence_id 异常：${assignment.evidence_id}`);
    if (assignment.entity_type === 'post') {
      assertContract(assignment.entity_id === assignment.post_id, `persona 帖子 assignment 父帖不一致：${assignment.evidence_id}`);
    }
    assertContract(assignment.assignment_status === 'rule_match_under_promoted_tag', `persona assignment 状态异常：${assignment.evidence_id}`);
    assertContract(assignment.semantic_gate_scope === 'tag_level_stratified_sample', `persona assignment 门禁范围异常：${assignment.evidence_id}`);
    assertContract(assignment.human_validated_assignment === false, `persona assignment 错误声称逐条人工验证：${assignment.evidence_id}`);
    assertContract(
      Array.isArray(assignment.evidence_keywords)
        && assignment.evidence_keywords.length > 0
        && assignment.evidence_keywords.every((keyword) => typeof keyword === 'string' && keyword.length > 0),
      `persona assignment 缺少证据词：${assignment.evidence_id}`,
    );
    assertContract(
      PERSONA_SOURCE_STRATUM_SET.has(assignment.source_stratum),
      `persona assignment 来源层不受治理：${assignment.evidence_id}`,
    );
    const uniqueKey = `${assignment.persona_id}|${assignment.evidence_id}`;
    assertContract(!assignmentKeys.has(uniqueKey), `persona assignment 重复：${uniqueKey}`);
    assignmentKeys.add(uniqueKey);
    const group = assignmentsByPersona.get(assignment.persona_id) ?? [];
    group.push(assignment);
    assignmentsByPersona.set(assignment.persona_id, group);
  }

  for (const persona of personas.personas) {
    const assignments = assignmentsByPersona.get(persona.persona_id) ?? [];
    const postCount = assignments.filter((assignment) => assignment.entity_type === 'post').length;
    const commentCount = assignments.filter((assignment) => assignment.entity_type === 'comment').length;
    const threadCount = new Set(assignments.map((assignment) => assignment.post_id)).size;
    assertContract(assignments.length === persona.metrics.matched_entities, `画像 assignment 实体计数不一致：${persona.persona_id}`);
    assertContract(postCount === persona.metrics.matched_posts, `画像 assignment 帖子计数不一致：${persona.persona_id}`);
    assertContract(commentCount === persona.metrics.matched_comments, `画像 assignment 评论计数不一致：${persona.persona_id}`);
    assertContract(threadCount === persona.metrics.threads, `画像 assignment 线程计数不一致：${persona.persona_id}`);
  }
  assertContract(
    personas.personas.reduce((total, persona) => total + persona.metrics.matched_entities, 0) === manifest.assignment_count,
    '画像实体指标与 persona-tags assignment 总数不守恒',
  );
}

export function validatePersonasOverlay(
  insights: RedditInsightsSnapshot,
  manifest: PersonaManifest,
  data: PersonasData,
  tags: PersonaTagsData,
  release: CurrentRelease,
): ValidatedPersonasOverlay {
  validateManifest(manifest, insights, release);
  assertExactKeys(data, [
    'schema_version',
    'dataset_version',
    'generated_at_utc',
    'persona_count',
    'personas',
    'interpretation_boundaries',
  ], '画像数据');
  assertContract(data.schema_version === PERSONAS_SCHEMA, '画像数据 schema 不受支持');
  assertContract(data.dataset_version === manifest.dataset_version, '画像实体数据版本不一致');
  assertContract(data.generated_at_utc === manifest.generated_at_utc, '画像实体生成时间不一致');
  assertContract(data.persona_count === manifest.persona_count, '画像实体数量与 manifest 不一致');
  assertContract(data.personas.length === data.persona_count, '画像数组数量不一致');
  assertInterpretationBoundaries(data.interpretation_boundaries);

  const personaIds = data.personas.map((persona) => persona.persona_id);
  assertContract(new Set(personaIds).size === personaIds.length, '画像 persona_id 重复');
  const avatarPaths = data.personas.map((persona) => persona.avatar.asset_path);
  assertContract(new Set(avatarPaths).size === avatarPaths.length, '画像头像路径重复');
  const manifestAvatarPaths = Object.keys(manifest.files).filter((path) => path.endsWith('.svg')).sort();
  assertContract(
    [...avatarPaths].sort().join(',') === manifestAvatarPaths.join(','),
    '画像头像路径文件与 persona 实体不守恒',
  );
  const signalById = new Map(insights.insights.signals.map((signal) => [signal.tag_id, signal]));
  const promotedTagIds = insights.insights.schema_version === 'reddit_voc_insights_v2'
    ? new Set(insights.insights.input_contract?.promoted_tag_ids ?? [])
    : new Set(signalById.keys());
  data.personas.forEach((persona) => validatePersona(
    persona,
    manifest,
    signalById,
    promotedTagIds,
    insights.insights.schema_version !== 'reddit_voc_insights_v2',
  ));
  validateAssignments(tags, manifest, data, insights);
  return { manifest, data, tags };
}

async function sha256Bytes(bytes: Uint8Array): Promise<string> {
  assertContract(globalThis.crypto?.subtle, '当前浏览器不支持画像文件完整性校验');
  const digestBytes = new Uint8Array(bytes.byteLength);
  digestBytes.set(bytes);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', digestBytes.buffer);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function fetchBytes(basePath: string, path: string): Promise<{ bytes: Uint8Array; mediaType: string | null }> {
  const response = await fetch(`${basePath}/${path}`, { cache: 'force-cache' });
  if (!response.ok) {
    throw new PersonasContractError(`画像文件加载失败：${path}（HTTP ${response.status}）`);
  }
  return {
    bytes: new Uint8Array(await response.arrayBuffer()),
    mediaType: response.headers.get('content-type')?.split(';')[0].trim() ?? null,
  };
}

async function fetchVerifiedJson<T>(basePath: string, path: string, integrity: FileIntegrity): Promise<T> {
  const { bytes, mediaType } = await fetchBytes(basePath, path);
  assertContract(bytes.byteLength === integrity.bytes, `画像文件 bytes 不一致：${path}`);
  assertContract((await sha256Bytes(bytes)) === integrity.sha256, `画像文件 SHA-256 不一致：${path}`);
  assertContract(mediaType === null || mediaType === 'application/json', `画像 JSON Content-Type 异常：${path}`);
  try {
    return JSON.parse(new TextDecoder().decode(bytes)) as T;
  } catch {
    throw new PersonasContractError(`画像文件不是有效 JSON：${path}`);
  }
}

function assertSafeSvg(bytes: Uint8Array, path: string): void {
  const text = new TextDecoder().decode(bytes);
  assertContract(/<svg(?:\s|>)/i.test(text), `画像头像不是有效 SVG：${path}`);
  assertContract(
    !/<(?:script|foreignObject|image|text)\b|\son[a-z]+\s*=|javascript:|(?:xlink:)?href\s*=/i.test(text),
    `画像头像包含不允许的元素、事件或引用：${path}`,
  );
}

async function loadAvatar(
  basePath: string,
  persona: AggregatePersona,
  manifest: PersonaManifest,
): Promise<PersonaAvatarAsset> {
  const path = persona.avatar.asset_path;
  const integrity = manifest.files[path];
  try {
    const { bytes, mediaType } = await fetchBytes(basePath, path);
    assertContract(bytes.byteLength === integrity.bytes, `画像头像 bytes 不一致：${path}`);
    assertContract((await sha256Bytes(bytes)) === integrity.sha256, `画像头像 SHA-256 不一致：${path}`);
    assertContract(mediaType === null || mediaType === 'image/svg+xml', `画像头像 Content-Type 异常：${path}`);
    assertSafeSvg(bytes, path);
    assertContract(typeof URL.createObjectURL === 'function', '当前浏览器不支持已验证头像对象 URL');
    const blobBytes = new Uint8Array(bytes.byteLength);
    blobBytes.set(bytes);
    const url = URL.createObjectURL(new Blob([blobBytes.buffer], { type: 'image/svg+xml' }));
    activeAvatarUrls.push(url);
    return { url, error: null };
  } catch (error: unknown) {
    return {
      url: null,
      error: error instanceof Error ? error.message : `画像头像校验失败：${path}`,
    };
  }
}

async function loadPersonasUncached(): Promise<AnyRedditPersonasSnapshot> {
  const release = await loadCurrentRelease();
  const manifest = await fetchVerifiedReleaseManifest<PersonaManifest | V3PersonaManifest>(release, 'personas');
  const basePath = getReleaseDatasetBasePath(release, 'personas');
  if (isV3PersonaManifest(manifest)) {
    return loadRedditV3Personas({
      basePath,
      expectedManifestSha256: release.datasets.personas.public_manifest_sha256,
      releaseId: release.release_id,
    });
  }

  const insights = await loadRedditInsights();
  validateManifest(manifest, insights, release);
  const [data, tags] = await Promise.all([
    fetchVerifiedJson<PersonasData>(basePath, 'personas.json', manifest.files['personas.json']),
    fetchVerifiedJson<PersonaTagsData>(basePath, 'persona-tags.json', manifest.files['persona-tags.json']),
  ]);
  const validated = validatePersonasOverlay(insights, manifest, data, tags, release);
  const avatarEntries = await Promise.all(
    data.personas.map(async (persona) => [persona.persona_id, await loadAvatar(basePath, persona, manifest)] as const),
  );
  return { ...validated, releaseId: release.release_id, avatarAssets: Object.fromEntries(avatarEntries) };
}

export function loadRedditPersonas(): Promise<AnyRedditPersonasSnapshot> {
  personasPromise ??= loadPersonasUncached();
  return personasPromise;
}

export function resetPersonasCacheForTests(): void {
  if (typeof URL.revokeObjectURL === 'function') {
    activeAvatarUrls.forEach((url) => URL.revokeObjectURL(url));
  }
  activeAvatarUrls = [];
  personasPromise = null;
  resetV3PersonaRuntimeForTests();
}
