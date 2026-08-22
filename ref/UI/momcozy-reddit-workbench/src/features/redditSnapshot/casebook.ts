import { getReleaseDatasetBasePath, loadCurrentRelease } from './release';

export const CASEBOOK_PUBLIC_BASE_PATH = '/data/reddit-voc/reddit_voc_casebook_20260716_public_a1';
export const CASEBOOK_PUBLIC_MANIFEST_SHA256 = '8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126';
export const CASEBOOK_PUBLIC_MANIFEST_SCHEMA = 'reddit_voc_governance_casebook_public_manifest_v1';
export const CASEBOOK_PUBLIC_SCHEMA = 'reddit_voc_governance_casebook_public_v1';

export type CasebookStageId = 'insight' | 'evidence' | 'action' | 'monitor' | 'review';
export type CasebookStageStatus = 'evidence_backed' | 'review_required' | 'suggestion_only';

export interface PublicCasebookBoundaries {
  action_display_mode: 'suggestion_only';
  brand_control_confirmed: false;
  database_write: false;
  deploy: false;
  external_navigation: false;
  live_send: false;
  pii_removed: true;
  production_unchanged: true;
  provider_call: false;
  remote_write: false;
  robot_attribution_confirmed: false;
}

export interface PublicCasebookManifest {
  boundaries: PublicCasebookBoundaries;
  counts: {
    canonical_posts: 4;
    case_dossiers: 1;
    evidence_comments: 16;
    external_references: 1;
  };
  files: {
    'casebook.json': {
      bytes: number;
      media_type: 'application/json';
      sha256: string;
    };
  };
  generated_at: string;
  lifecycle_status: 'review_required';
  projection_id: string;
  schema_version: typeof CASEBOOK_PUBLIC_MANIFEST_SCHEMA;
  source_casebook_id: string;
  source_casebook_manifest_sha256: string;
  source_receipt_sha256: string;
  source_snapshot_id: string;
  status: 'ready';
}

export interface PublicCasebookStage {
  id: CasebookStageId;
  items: string[];
  label: '洞察' | '证据' | '行动' | '监测' | '复盘';
  status: CasebookStageStatus;
  summary: string;
}

export interface PublicCaseDossier {
  assessment: {
    assertion_status: 'subreddit_moderator_public_allegation';
    brand_control_confirmed: false;
    commercial_relation: 'C2';
    governance_authority: 'subreddit_moderator';
    integrity_level: 'I3';
    publication_boundary: 'risk_observation_not_brand_attribution';
  };
  brand_scope: 'Momcozy';
  business_question: string;
  case_id: string;
  evidence: {
    canonical_post_ids: string[];
    evidence_comment_ids: string[];
    external_reference_ids: string[];
  };
  lifecycle_status: 'review_required';
  product_scope: string;
  review_due_at: string;
  stages: PublicCasebookStage[];
  title: 'Momcozy 社区信任与疑似非自然推广治理事件';
}

export interface PublicCasebookData {
  boundaries: PublicCasebookBoundaries;
  dossiers: PublicCaseDossier[];
  generated_at: string;
  projection_id: string;
  schema_version: typeof CASEBOOK_PUBLIC_SCHEMA;
  source_casebook_id: string;
  source_snapshot_id: string;
}

export interface RedditPublicCasebook {
  manifest: PublicCasebookManifest;
  data: PublicCasebookData;
}

export interface LoadRedditCasebookOptions {
  basePath?: string;
  expectedManifestSha256?: string;
}

export class CasebookContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CasebookContractError';
  }
}

const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const MANIFEST_KEYS = [
  'boundaries', 'counts', 'files', 'generated_at', 'lifecycle_status', 'projection_id',
  'schema_version', 'source_casebook_id', 'source_casebook_manifest_sha256',
  'source_receipt_sha256', 'source_snapshot_id', 'status',
] as const;
const DATA_KEYS = [
  'boundaries', 'dossiers', 'generated_at', 'projection_id', 'schema_version',
  'source_casebook_id', 'source_snapshot_id',
] as const;
const BOUNDARY_KEYS = [
  'action_display_mode', 'brand_control_confirmed', 'database_write', 'deploy',
  'external_navigation', 'live_send', 'pii_removed', 'production_unchanged',
  'provider_call', 'remote_write', 'robot_attribution_confirmed',
] as const;
const DOSSIER_KEYS = [
  'assessment', 'brand_scope', 'business_question', 'case_id', 'evidence',
  'lifecycle_status', 'product_scope', 'review_due_at', 'stages', 'title',
] as const;
const ASSESSMENT_KEYS = [
  'assertion_status', 'brand_control_confirmed', 'commercial_relation',
  'governance_authority', 'integrity_level', 'publication_boundary',
] as const;
const EVIDENCE_KEYS = ['canonical_post_ids', 'evidence_comment_ids', 'external_reference_ids'] as const;
const STAGE_KEYS = ['id', 'items', 'label', 'status', 'summary'] as const;
const STAGE_ORDER: Array<{ id: CasebookStageId; label: PublicCasebookStage['label'] }> = [
  { id: 'insight', label: '洞察' },
  { id: 'evidence', label: '证据' },
  { id: 'action', label: '行动' },
  { id: 'monitor', label: '监测' },
  { id: 'review', label: '复盘' },
];
const FIXED_POST_IDS = ['t3_1kkvihg', 't3_1l2aofi', 't3_1n2q1do', 't3_1o1pqox'];
const FIXED_EXTERNAL_IDS = ['external_reddit_post:1u2gvn4'];

let casebookCache: RedditPublicCasebook | null = null;

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new CasebookContractError(message);
}

function record(value: unknown, label: string): Record<string, unknown> {
  assertContract(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `${label}必须是对象`);
  return value as Record<string, unknown>;
}

function exactKeys(value: unknown, expected: readonly string[], label: string): Record<string, unknown> {
  const result = record(value, label);
  const keys = Object.keys(result).sort();
  const wanted = [...expected].sort();
  assertContract(keys.length === wanted.length && keys.every((key, index) => key === wanted[index]), `${label}字段合同不一致`);
  return result;
}

function stringValue(value: unknown, label: string): string {
  assertContract(typeof value === 'string' && value.trim() !== '', `${label}必须是非空字符串`);
  return value;
}

function stringArray(value: unknown, label: string): string[] {
  assertContract(Array.isArray(value) && value.every((item) => typeof item === 'string' && item.trim() !== ''), `${label}必须是字符串数组`);
  return value;
}

function validateBoundaries(value: unknown): PublicCasebookBoundaries {
  const item = exactKeys(value, BOUNDARY_KEYS, 'casebook.boundaries');
  assertContract(
    item.action_display_mode === 'suggestion_only'
      && item.brand_control_confirmed === false
      && item.database_write === false
      && item.deploy === false
      && item.external_navigation === false
      && item.live_send === false
      && item.pii_removed === true
      && item.production_unchanged === true
      && item.provider_call === false
      && item.remote_write === false
      && item.robot_attribution_confirmed === false,
    'casebook.boundaries不安全',
  );
  return item as unknown as PublicCasebookBoundaries;
}

export function validatePublicCasebookManifest(value: unknown): PublicCasebookManifest {
  const item = exactKeys(value, MANIFEST_KEYS, 'casebook manifest');
  validateBoundaries(item.boundaries);
  const counts = exactKeys(item.counts, ['canonical_posts', 'case_dossiers', 'evidence_comments', 'external_references'], 'casebook manifest.counts');
  const files = exactKeys(item.files, ['casebook.json'], 'casebook manifest.files');
  const file = exactKeys(files['casebook.json'], ['bytes', 'media_type', 'sha256'], 'casebook manifest.files.casebook.json');
  assertContract(
    item.schema_version === CASEBOOK_PUBLIC_MANIFEST_SCHEMA
      && item.status === 'ready'
      && item.lifecycle_status === 'review_required'
      && counts.canonical_posts === 4
      && counts.case_dossiers === 1
      && counts.evidence_comments === 16
      && counts.external_references === 1
      && Number.isInteger(file.bytes) && Number(file.bytes) > 0
      && file.media_type === 'application/json'
      && typeof file.sha256 === 'string' && SHA256_PATTERN.test(file.sha256)
      && typeof item.source_casebook_manifest_sha256 === 'string' && SHA256_PATTERN.test(item.source_casebook_manifest_sha256)
      && typeof item.source_receipt_sha256 === 'string' && SHA256_PATTERN.test(item.source_receipt_sha256),
    'casebook manifest语义不一致',
  );
  [item.generated_at, item.projection_id, item.source_casebook_id, item.source_snapshot_id].forEach((entry, index) => stringValue(entry, `casebook manifest.identity[${index}]`));
  return item as unknown as PublicCasebookManifest;
}

function validateDossier(value: unknown): PublicCaseDossier {
  const item = exactKeys(value, DOSSIER_KEYS, 'casebook dossier');
  const assessment = exactKeys(item.assessment, ASSESSMENT_KEYS, 'casebook dossier.assessment');
  const evidence = exactKeys(item.evidence, EVIDENCE_KEYS, 'casebook dossier.evidence');
  assertContract(
    item.title === 'Momcozy 社区信任与疑似非自然推广治理事件'
      && item.brand_scope === 'Momcozy'
      && item.lifecycle_status === 'review_required'
      && assessment.assertion_status === 'subreddit_moderator_public_allegation'
      && assessment.brand_control_confirmed === false
      && assessment.commercial_relation === 'C2'
      && assessment.governance_authority === 'subreddit_moderator'
      && assessment.integrity_level === 'I3'
      && assessment.publication_boundary === 'risk_observation_not_brand_attribution',
    'casebook dossier风险边界不一致',
  );
  const postIds = stringArray(evidence.canonical_post_ids, 'casebook dossier.evidence.canonical_post_ids');
  const commentIds = stringArray(evidence.evidence_comment_ids, 'casebook dossier.evidence.evidence_comment_ids');
  const externalIds = stringArray(evidence.external_reference_ids, 'casebook dossier.evidence.external_reference_ids');
  assertContract(JSON.stringify(postIds) === JSON.stringify(FIXED_POST_IDS), 'casebook dossier规范帖子不一致');
  assertContract(commentIds.length === 16 && commentIds.every((id) => /^t1_[a-z0-9]+$/.test(id)), 'casebook dossier评论证据不一致');
  assertContract(JSON.stringify(externalIds) === JSON.stringify(FIXED_EXTERNAL_IDS), 'casebook dossier外部参考不一致');
  assertContract(Array.isArray(item.stages) && item.stages.length === STAGE_ORDER.length, 'casebook dossier阶段不完整');
  const stages = item.stages.map((value, index) => {
    const stage = exactKeys(value, STAGE_KEYS, `casebook dossier.stages[${index}]`);
    assertContract(stage.id === STAGE_ORDER[index].id && stage.label === STAGE_ORDER[index].label, 'casebook dossier阶段顺序不一致');
    assertContract(['evidence_backed', 'review_required', 'suggestion_only'].includes(String(stage.status)), 'casebook dossier阶段状态不一致');
    stringValue(stage.summary, `casebook dossier.stages[${index}].summary`);
    stringArray(stage.items, `casebook dossier.stages[${index}].items`);
    return stage as unknown as PublicCasebookStage;
  });
  assertContract(stages.some((stage) => stage.summary.includes('建议方案')), 'casebook dossier缺少建议方案边界');
  return { ...item, assessment, evidence, stages } as unknown as PublicCaseDossier;
}

export function validatePublicCasebookData(value: unknown): PublicCasebookData {
  const item = exactKeys(value, DATA_KEYS, 'casebook data');
  validateBoundaries(item.boundaries);
  assertContract(item.schema_version === CASEBOOK_PUBLIC_SCHEMA, 'casebook data schema不受支持');
  assertContract(Array.isArray(item.dossiers) && item.dossiers.length === 1, 'casebook data必须包含一个事件');
  const dossier = validateDossier(item.dossiers[0]);
  const serialized = JSON.stringify(item);
  assertContract(!serialized.includes('http://') && !serialized.includes('https://') && !serialized.includes('"author"') && !serialized.includes('"username"'), 'casebook data包含外链或身份字段');
  return { ...item, dossiers: [dossier] } as unknown as PublicCasebookData;
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

export async function loadRedditCasebook(
  options: LoadRedditCasebookOptions = {},
): Promise<RedditPublicCasebook> {
  if (casebookCache) return casebookCache;
  let releaseBasePath: string | undefined;
  let releaseManifestSha256: string | undefined;
  if (options.basePath === undefined && options.expectedManifestSha256 === undefined) {
    const release = await loadCurrentRelease();
    const binding = release.datasets.casebook;
    if (binding) {
      releaseBasePath = getReleaseDatasetBasePath(release, 'casebook');
      releaseManifestSha256 = binding.public_manifest_sha256;
    }
  }
  const basePath = (options.basePath ?? releaseBasePath ?? CASEBOOK_PUBLIC_BASE_PATH).replace(/\/$/, '');
  const expectedManifestSha256 = options.expectedManifestSha256
    ?? releaseManifestSha256
    ?? CASEBOOK_PUBLIC_MANIFEST_SHA256;
  assertContract(SHA256_PATTERN.test(expectedManifestSha256), 'casebook预期manifest SHA-256无效');
  const manifestText = await fetchText(`${basePath}/manifest.json`);
  assertContract(await sha256Hex(manifestText) === expectedManifestSha256, 'casebook manifest SHA-256不一致');
  const manifest = validatePublicCasebookManifest(JSON.parse(manifestText));
  const dataText = await fetchText(`${basePath}/casebook.json`);
  assertContract(new TextEncoder().encode(dataText).byteLength === manifest.files['casebook.json'].bytes, 'casebook.json字节数不一致');
  assertContract(await sha256Hex(dataText) === manifest.files['casebook.json'].sha256, 'casebook.json SHA-256不一致');
  const data = validatePublicCasebookData(JSON.parse(dataText));
  assertContract(data.projection_id === manifest.projection_id && data.source_casebook_id === manifest.source_casebook_id && data.source_snapshot_id === manifest.source_snapshot_id, 'casebook lineage不一致');
  casebookCache = { manifest, data };
  return casebookCache;
}

export function resetRedditCasebookCacheForTests(): void {
  casebookCache = null;
}
