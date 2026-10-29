import { getReleaseDatasetBasePath, loadCurrentRelease, releaseGenerationKey } from './release';
import { ReleaseKeyedCache } from './releaseKeyedCache';

export const BRAND_HEALTH_PUBLIC_BASE_PATH = '/data/reddit-voc/reddit_voc_brand_health_20260719_center_refresh_003';
export const BRAND_HEALTH_PUBLIC_MANIFEST_SHA256 = 'a162120439ba80b2444f15ffbd46f1e7cd3d900ff4801f6947faaf10c243ec86';
export const BRAND_HEALTH_PUBLIC_MANIFEST_SCHEMA = 'reddit_voc_brand_health_public_manifest_v1';
export const BRAND_HEALTH_PUBLIC_SCHEMA = 'reddit_voc_brand_health_public_v1';

export type BrandHealthStatus = 'available' | 'provisional' | 'unavailable';
export type BrandHealthDimensionId = 'reputation' | 'product_experience' | 'recommendation_trust' | 'risk_resilience';

export interface PublicBrandHealthBoundaries {
  contains_authors: false;
  contains_entity_ids: false;
  contains_source_text: false;
  database_write: false;
  deploy: false;
  live_send: false;
  overall_score_derived_from_axes: false;
  pii_removed: true;
  production_unchanged: true;
  provider_call: false;
  remote_write: false;
}

export interface PublicBrandHealthDimension {
  dimension_id: BrandHealthDimensionId;
  label: '口碑健康' | '产品体验' | '推荐信任' | '风险韧性';
  reason_codes: string[];
  score: number | null;
  status: BrandHealthStatus;
}

export interface PublicBrandHealthData {
  boundaries: PublicBrandHealthBoundaries;
  brand_name: 'Momcozy';
  comparison_side: 'qualified_organic';
  dimensions: PublicBrandHealthDimension[];
  overall: {
    reason_codes: string[];
    score: number | null;
    status: BrandHealthStatus;
  };
  period: 'all_observed_history';
  projection_id: string;
  schema_version: typeof BRAND_HEALTH_PUBLIC_SCHEMA;
  source: {
    brand_health_sha256: string;
    facts_manifest_sha256: string;
    metrics_manifest_sha256: string;
    metrics_validation_receipt_sha256: string;
    snapshot_id: string;
  };
}

export interface PublicBrandHealthManifest {
  boundaries: PublicBrandHealthBoundaries;
  comparison_side: 'qualified_organic';
  files: {
    'brand-health.json': {
      bytes: number;
      media_type: 'application/json';
      sha256: string;
    };
  };
  projection_id: string;
  schema_version: typeof BRAND_HEALTH_PUBLIC_MANIFEST_SCHEMA;
  source_brand_health_sha256: string;
  source_metrics_manifest_sha256: string;
  source_metrics_validation_receipt_sha256: string;
  source_snapshot_id: string;
  status: 'ready';
}

export interface RedditPublicBrandHealth {
  data: PublicBrandHealthData;
  manifest: PublicBrandHealthManifest;
}

export interface LoadRedditBrandHealthOptions {
  basePath?: string;
  expectedManifestSha256?: string;
}

export class BrandHealthContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BrandHealthContractError';
  }
}

const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const MANIFEST_KEYS = [
  'boundaries', 'comparison_side', 'files', 'projection_id', 'schema_version',
  'source_brand_health_sha256', 'source_metrics_manifest_sha256',
  'source_metrics_validation_receipt_sha256', 'source_snapshot_id', 'status',
] as const;
const DATA_KEYS = [
  'boundaries', 'brand_name', 'comparison_side', 'dimensions', 'overall', 'period',
  'projection_id', 'schema_version', 'source',
] as const;
const BOUNDARY_KEYS = [
  'contains_authors', 'contains_entity_ids', 'contains_source_text', 'database_write',
  'deploy', 'live_send', 'overall_score_derived_from_axes', 'pii_removed',
  'production_unchanged', 'provider_call', 'remote_write',
] as const;
const DIMENSION_KEYS = ['dimension_id', 'label', 'reason_codes', 'score', 'status'] as const;
const DIMENSION_ORDER: Array<{ id: BrandHealthDimensionId; label: PublicBrandHealthDimension['label'] }> = [
  { id: 'reputation', label: '口碑健康' },
  { id: 'product_experience', label: '产品体验' },
  { id: 'recommendation_trust', label: '推荐信任' },
  { id: 'risk_resilience', label: '风险韧性' },
];

const brandHealthCache = new ReleaseKeyedCache<RedditPublicBrandHealth>();

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new BrandHealthContractError(message);
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

function nonEmptyString(value: unknown, label: string): string {
  assertContract(typeof value === 'string' && value.trim() !== '', `${label}必须是非空字符串`);
  return value;
}

function sha256Value(value: unknown, label: string): string {
  const result = nonEmptyString(value, label);
  assertContract(SHA256_PATTERN.test(result), `${label}必须是SHA-256`);
  return result;
}

function reasonCodes(value: unknown, status: unknown, label: string): string[] {
  assertContract(Array.isArray(value) && value.every((item) => typeof item === 'string' && item.length > 0), `${label}.reason_codes无效`);
  assertContract(status === 'available' || value.length > 0, `${label}非正式可用状态必须说明原因`);
  return value;
}

function score(value: unknown, status: unknown, label: string): number | null {
  if (status === 'unavailable') {
    assertContract(value === null, `${label}不可计算时必须为null`);
    return null;
  }
  assertContract(status === 'available' || status === 'provisional', `${label}.status无效`);
  assertContract(typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100, `${label}.score必须在0到100之间`);
  return value;
}

function validateBoundaries(value: unknown): PublicBrandHealthBoundaries {
  const item = exactKeys(value, BOUNDARY_KEYS, 'brand health boundaries');
  assertContract(
    item.contains_authors === false
      && item.contains_entity_ids === false
      && item.contains_source_text === false
      && item.database_write === false
      && item.deploy === false
      && item.live_send === false
      && item.overall_score_derived_from_axes === false
      && item.pii_removed === true
      && item.production_unchanged === true
      && item.provider_call === false
      && item.remote_write === false,
    'brand health boundaries不安全',
  );
  return item as unknown as PublicBrandHealthBoundaries;
}

export function validatePublicBrandHealthManifest(value: unknown): PublicBrandHealthManifest {
  const item = exactKeys(value, MANIFEST_KEYS, 'brand health manifest');
  validateBoundaries(item.boundaries);
  const files = exactKeys(item.files, ['brand-health.json'], 'brand health manifest.files');
  const file = exactKeys(files['brand-health.json'], ['bytes', 'media_type', 'sha256'], 'brand health manifest.files.brand-health.json');
  assertContract(
    item.schema_version === BRAND_HEALTH_PUBLIC_MANIFEST_SCHEMA
      && item.status === 'ready'
      && item.comparison_side === 'qualified_organic'
      && Number.isInteger(file.bytes) && Number(file.bytes) > 0
      && file.media_type === 'application/json',
    'brand health manifest语义不一致',
  );
  sha256Value(file.sha256, 'brand health data hash');
  sha256Value(item.source_brand_health_sha256, 'source brand health hash');
  sha256Value(item.source_metrics_manifest_sha256, 'source metrics manifest hash');
  sha256Value(item.source_metrics_validation_receipt_sha256, 'source metrics receipt hash');
  nonEmptyString(item.projection_id, 'brand health projection_id');
  nonEmptyString(item.source_snapshot_id, 'brand health source_snapshot_id');
  return item as unknown as PublicBrandHealthManifest;
}

export function validatePublicBrandHealthData(value: unknown): PublicBrandHealthData {
  const item = exactKeys(value, DATA_KEYS, 'brand health data');
  validateBoundaries(item.boundaries);
  assertContract(
    item.schema_version === BRAND_HEALTH_PUBLIC_SCHEMA
      && item.brand_name === 'Momcozy'
      && item.comparison_side === 'qualified_organic'
      && item.period === 'all_observed_history',
    'brand health data语义不一致',
  );
  assertContract(Array.isArray(item.dimensions) && item.dimensions.length === DIMENSION_ORDER.length, 'brand health必须有四个维度');
  const dimensions = item.dimensions.map((value, index) => {
    const dimension = exactKeys(value, DIMENSION_KEYS, `brand health dimensions[${index}]`);
    const expected = DIMENSION_ORDER[index];
    assertContract(dimension.dimension_id === expected.id && dimension.label === expected.label, 'brand health维度顺序不一致');
    const validatedScore = score(dimension.score, dimension.status, `brand health ${expected.id}`);
    const validatedReasons = reasonCodes(dimension.reason_codes, dimension.status, `brand health ${expected.id}`);
    return { ...dimension, reason_codes: validatedReasons, score: validatedScore } as PublicBrandHealthDimension;
  });
  const overall = exactKeys(item.overall, ['reason_codes', 'score', 'status'], 'brand health overall');
  const overallScore = score(overall.score, overall.status, 'brand health overall');
  const overallReasons = reasonCodes(overall.reason_codes, overall.status, 'brand health overall');
  const source = exactKeys(
    item.source,
    ['brand_health_sha256', 'facts_manifest_sha256', 'metrics_manifest_sha256', 'metrics_validation_receipt_sha256', 'snapshot_id'],
    'brand health source',
  );
  sha256Value(source.brand_health_sha256, 'brand health source.brand_health_sha256');
  sha256Value(source.facts_manifest_sha256, 'brand health source.facts_manifest_sha256');
  sha256Value(source.metrics_manifest_sha256, 'brand health source.metrics_manifest_sha256');
  sha256Value(source.metrics_validation_receipt_sha256, 'brand health source.metrics_validation_receipt_sha256');
  nonEmptyString(source.snapshot_id, 'brand health source.snapshot_id');
  const serialized = JSON.stringify(item);
  assertContract(
    !serialized.includes('included_entity_ids')
      && !serialized.includes('excluded_entity_ids')
      && !serialized.includes('member_ids')
      && !serialized.includes('"author"')
      && !serialized.includes('"username"')
      && !serialized.includes('http://')
      && !serialized.includes('https://'),
    'brand health data包含身份、原文或外链字段',
  );
  return {
    ...item,
    dimensions,
    overall: { reason_codes: overallReasons, score: overallScore, status: overall.status },
    source,
  } as unknown as PublicBrandHealthData;
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

export async function loadRedditBrandHealth(
  options: LoadRedditBrandHealthOptions = {},
): Promise<RedditPublicBrandHealth> {
  // An explicit basePath is a fixture/offline path, not the published release; it
  // must not be memoized under a release key or a test could poison production.
  const isReleaseBound = options.basePath === undefined
    && options.expectedManifestSha256 === undefined;
  if (!isReleaseBound) return loadBrandHealthUncached(options);
  const release = await loadCurrentRelease();
  return brandHealthCache.get(
    releaseGenerationKey(release),
    () => loadBrandHealthUncached(options),
  );
}

async function loadBrandHealthUncached(
  options: LoadRedditBrandHealthOptions,
): Promise<RedditPublicBrandHealth> {
  let releaseBasePath: string | undefined;
  let releaseManifestSha256: string | undefined;
  if (options.basePath === undefined && options.expectedManifestSha256 === undefined) {
    const release = await loadCurrentRelease();
    const binding = release.datasets.brand_health;
    if (binding) {
      releaseBasePath = getReleaseDatasetBasePath(release, 'brand_health');
      releaseManifestSha256 = binding.public_manifest_sha256;
    }
  }
  const basePath = (options.basePath ?? releaseBasePath ?? BRAND_HEALTH_PUBLIC_BASE_PATH).replace(/\/$/, '');
  const expectedManifestSha256 = options.expectedManifestSha256
    ?? releaseManifestSha256
    ?? BRAND_HEALTH_PUBLIC_MANIFEST_SHA256;
  assertContract(SHA256_PATTERN.test(expectedManifestSha256), 'brand health预期manifest SHA-256无效');
  const manifestText = await fetchText(`${basePath}/manifest.json`);
  assertContract(await sha256Hex(manifestText) === expectedManifestSha256, 'brand health manifest SHA-256不一致');
  const manifest = validatePublicBrandHealthManifest(JSON.parse(manifestText));
  const dataText = await fetchText(`${basePath}/brand-health.json`);
  assertContract(new TextEncoder().encode(dataText).byteLength === manifest.files['brand-health.json'].bytes, 'brand-health.json字节数不一致');
  assertContract(await sha256Hex(dataText) === manifest.files['brand-health.json'].sha256, 'brand-health.json SHA-256不一致');
  const data = validatePublicBrandHealthData(JSON.parse(dataText));
  assertContract(
    data.projection_id === manifest.projection_id
      && data.source.brand_health_sha256 === manifest.source_brand_health_sha256
      && data.source.metrics_manifest_sha256 === manifest.source_metrics_manifest_sha256
      && data.source.metrics_validation_receipt_sha256 === manifest.source_metrics_validation_receipt_sha256
      && data.source.snapshot_id === manifest.source_snapshot_id,
    'brand health lineage不一致',
  );
  return { data, manifest };
}

export function resetRedditBrandHealthCacheForTests(): void {
  brandHealthCache.clear();
}
