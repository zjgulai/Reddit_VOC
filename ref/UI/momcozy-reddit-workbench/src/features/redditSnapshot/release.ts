export const CURRENT_RELEASE_SCHEMA = 'reddit_voc_current_release_v1';
export const CURRENT_RELEASE_SCHEMA_V2 = 'reddit_voc_current_release_v2';

const CURRENT_RELEASE_RELATIVE_PATH = 'data/reddit-voc/current-release.json';
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const SAFE_IDENTIFIER_PATTERN = /^[a-z0-9][a-z0-9_-]{0,127}$/;
const CORE_DATASET_KEYS = ['base', 'insights', 'reports', 'personas'] as const;
const AUXILIARY_DATASET_KEYS = ['brand_health', 'quarter_insights', 'casebook'] as const;
const DATASET_KEYS = [...CORE_DATASET_KEYS, ...AUXILIARY_DATASET_KEYS] as const;

export type ReleaseDatasetKey = (typeof DATASET_KEYS)[number];
export type CoreReleaseDatasetKey = (typeof CORE_DATASET_KEYS)[number];
export type AuxiliaryReleaseDatasetKey = (typeof AUXILIARY_DATASET_KEYS)[number];

export interface ReleaseDatasetBinding {
  dataset_version: string;
  manifest_path: string;
  public_manifest_sha256: string;
  lineage_manifest_sha256: string;
}

export interface CurrentRelease {
  schema_version: typeof CURRENT_RELEASE_SCHEMA | typeof CURRENT_RELEASE_SCHEMA_V2;
  release_id: string;
  generated_at_utc: string;
  datasets: Record<CoreReleaseDatasetKey, ReleaseDatasetBinding>
    & Partial<Record<AuxiliaryReleaseDatasetKey, ReleaseDatasetBinding>>;
  freshness?: {
    status: 'full' | 'partial' | 'empty_success';
    timezone: 'Asia/Shanghai';
    data_as_of_utc: string;
    window_start_utc: string;
    window_end_utc: string;
    collector_run_id: string;
    source_batch_id: string;
    center_snapshot_id: string;
    net_new: {
      posts: number;
      comments: number;
      updated_historical_posts: number;
      repaired_parent_links: number;
    };
    coverage: {
      full_posts: number;
      partial_posts: number;
      unresolved_continuations: number;
    };
  };
  cases: {
    dataset_version: string;
    manifest_path: 'data/cases/manifest.v1.json';
    public_manifest_sha256: string;
    index_path: 'data/cases/case-index.v1.json';
    index_sha256: string;
    stock_content_preserved: true;
    approved_delta_count: number;
  };
  boundaries: {
    case_gallery_stock_preserved: true;
    collector_isolation_required: true;
    login_required: false;
  };
}

export class ReleaseContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ReleaseContractError';
  }
}

let releasePromise: Promise<CurrentRelease> | null = null;

function assertContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new ReleaseContractError(message);
}

function assertRecord(value: unknown, label: string): asserts value is Record<string, unknown> {
  assertContract(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `${label}必须是对象`);
}

function assertExactKeys(value: Record<string, unknown>, expected: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  assertContract(
    actual.length === wanted.length && actual.every((key, index) => key === wanted[index]),
    `${label}字段集合异常`,
  );
}

function requireSafeIdentifier(value: unknown, label: string, prefix?: string): string {
  assertContract(typeof value === 'string' && SAFE_IDENTIFIER_PATTERN.test(value), `${label}不是安全版本名`);
  if (prefix) assertContract(value.startsWith(prefix), `${label}前缀异常`);
  return value;
}

function requireSha256(value: unknown, label: string): string {
  assertContract(typeof value === 'string' && SHA256_PATTERN.test(value), `${label}不是有效 SHA-256`);
  return value;
}

function expectedManifestPath(key: ReleaseDatasetKey, version: string): string {
  switch (key) {
    case 'base':
      return `data/reddit-voc/${version}/manifest-public.json`;
    case 'insights':
    case 'reports':
      return `data/reddit-voc/${version}/public/manifest.json`;
    case 'personas':
      return `data/reddit-voc/${version}/manifest.json`;
    case 'brand_health':
    case 'quarter_insights':
    case 'casebook':
      return `data/reddit-voc/${version}/manifest.json`;
  }
}

function validateDatasetBinding(value: unknown, key: ReleaseDatasetKey): ReleaseDatasetBinding {
  assertRecord(value, `current release datasets.${key}`);
  assertExactKeys(value, [
    'dataset_version',
    'manifest_path',
    'public_manifest_sha256',
    'lineage_manifest_sha256',
  ], `current release datasets.${key}`);
  const prefix = key === 'base' ? 'reddit_voc_site_snapshot_' : `reddit_voc_${key}_`;
  const datasetVersion = requireSafeIdentifier(
    value.dataset_version,
    `current release datasets.${key}.dataset_version`,
    prefix,
  );
  assertContract(
    value.manifest_path === expectedManifestPath(key, datasetVersion),
    `current release datasets.${key}.manifest_path 与版本不一致`,
  );
  return {
    dataset_version: datasetVersion,
    manifest_path: value.manifest_path,
    public_manifest_sha256: requireSha256(
      value.public_manifest_sha256,
      `current release datasets.${key}.public_manifest_sha256`,
    ),
    lineage_manifest_sha256: requireSha256(
      value.lineage_manifest_sha256,
      `current release datasets.${key}.lineage_manifest_sha256`,
    ),
  };
}

export function validateCurrentRelease(value: unknown): CurrentRelease {
  assertRecord(value, 'current release');
  const isV2 = value.schema_version === CURRENT_RELEASE_SCHEMA_V2;
  assertExactKeys(value, [
    'schema_version',
    'release_id',
    'generated_at_utc',
    'datasets',
    'cases',
    'boundaries',
    ...(isV2 ? ['freshness'] : []),
  ], 'current release');
  assertContract(
    value.schema_version === CURRENT_RELEASE_SCHEMA || isV2,
    'current release schema 不受支持',
  );
  const releaseId = requireSafeIdentifier(value.release_id, 'current release release_id', 'reddit_voc_release_');
  assertContract(
    typeof value.generated_at_utc === 'string'
      && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value.generated_at_utc)
      && !Number.isNaN(Date.parse(value.generated_at_utc)),
    'current release generated_at_utc 无效',
  );

  const datasetsValue = value.datasets;
  assertRecord(datasetsValue, 'current release datasets');
  const expectedDatasetKeys = isV2 ? DATASET_KEYS : CORE_DATASET_KEYS;
  assertExactKeys(datasetsValue, expectedDatasetKeys, 'current release datasets');
  const datasets = Object.fromEntries(
    expectedDatasetKeys.map((key) => [key, validateDatasetBinding(datasetsValue[key], key)]),
  ) as CurrentRelease['datasets'];

  let freshness: CurrentRelease['freshness'];
  if (isV2) {
    assertRecord(value.freshness, 'current release freshness');
    assertExactKeys(value.freshness, [
      'status',
      'timezone',
      'data_as_of_utc',
      'window_start_utc',
      'window_end_utc',
      'collector_run_id',
      'source_batch_id',
      'center_snapshot_id',
      'net_new',
      'coverage',
    ], 'current release freshness');
    assertContract(
      value.freshness.status === 'full'
        || value.freshness.status === 'partial'
        || value.freshness.status === 'empty_success',
      'current release freshness.status 无效',
    );
    assertContract(value.freshness.timezone === 'Asia/Shanghai', 'current release freshness.timezone 无效');
    for (const field of ['data_as_of_utc', 'window_start_utc', 'window_end_utc'] as const) {
      const timestamp = value.freshness[field];
      assertContract(
        typeof timestamp === 'string'
          && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(timestamp)
          && !Number.isNaN(Date.parse(timestamp)),
        `current release freshness.${field} 无效`,
      );
    }
    assertContract(
      Date.parse(value.freshness.window_start_utc as string)
        < Date.parse(value.freshness.window_end_utc as string)
        && value.freshness.window_end_utc === value.freshness.data_as_of_utc,
      'current release freshness 窗口无效',
    );
    const collectorRunId = requireSafeIdentifier(
      value.freshness.collector_run_id,
      'current release freshness.collector_run_id',
    );
    const sourceBatchId = requireSafeIdentifier(
      value.freshness.source_batch_id,
      'current release freshness.source_batch_id',
    );
    const centerSnapshotId = requireSafeIdentifier(
      value.freshness.center_snapshot_id,
      'current release freshness.center_snapshot_id',
    );
    assertRecord(value.freshness.net_new, 'current release freshness.net_new');
    assertExactKeys(value.freshness.net_new, [
      'posts',
      'comments',
      'updated_historical_posts',
      'repaired_parent_links',
    ], 'current release freshness.net_new');
    assertRecord(value.freshness.coverage, 'current release freshness.coverage');
    assertExactKeys(value.freshness.coverage, [
      'full_posts',
      'partial_posts',
      'unresolved_continuations',
    ], 'current release freshness.coverage');
    const requireNonNegativeInteger = (candidate: unknown, label: string): number => {
      assertContract(Number.isInteger(candidate) && Number(candidate) >= 0, `${label} 无效`);
      return Number(candidate);
    };
    freshness = {
      status: value.freshness.status,
      timezone: 'Asia/Shanghai',
      data_as_of_utc: value.freshness.data_as_of_utc as string,
      window_start_utc: value.freshness.window_start_utc as string,
      window_end_utc: value.freshness.window_end_utc as string,
      collector_run_id: collectorRunId,
      source_batch_id: sourceBatchId,
      center_snapshot_id: centerSnapshotId,
      net_new: {
        posts: requireNonNegativeInteger(value.freshness.net_new.posts, 'current release freshness.net_new.posts'),
        comments: requireNonNegativeInteger(value.freshness.net_new.comments, 'current release freshness.net_new.comments'),
        updated_historical_posts: requireNonNegativeInteger(
          value.freshness.net_new.updated_historical_posts,
          'current release freshness.net_new.updated_historical_posts',
        ),
        repaired_parent_links: requireNonNegativeInteger(
          value.freshness.net_new.repaired_parent_links,
          'current release freshness.net_new.repaired_parent_links',
        ),
      },
      coverage: {
        full_posts: requireNonNegativeInteger(
          value.freshness.coverage.full_posts,
          'current release freshness.coverage.full_posts',
        ),
        partial_posts: requireNonNegativeInteger(
          value.freshness.coverage.partial_posts,
          'current release freshness.coverage.partial_posts',
        ),
        unresolved_continuations: requireNonNegativeInteger(
          value.freshness.coverage.unresolved_continuations,
          'current release freshness.coverage.unresolved_continuations',
        ),
      },
    };
  }

  assertRecord(value.cases, 'current release cases');
  assertExactKeys(value.cases, [
    'dataset_version',
    'manifest_path',
    'public_manifest_sha256',
    'index_path',
    'index_sha256',
    'stock_content_preserved',
    'approved_delta_count',
  ], 'current release cases');
  const casesVersion = requireSafeIdentifier(
    value.cases.dataset_version,
    'current release cases.dataset_version',
    'case_catalog_',
  );
  assertContract(value.cases.manifest_path === 'data/cases/manifest.v1.json', 'current release cases manifest_path 异常');
  assertContract(value.cases.index_path === 'data/cases/case-index.v1.json', 'current release cases index_path 异常');
  assertContract(value.cases.stock_content_preserved === true, 'current release 未保持案例广场存量内容');
  assertContract(
    Number.isInteger(value.cases.approved_delta_count) && Number(value.cases.approved_delta_count) >= 0,
    'current release cases.approved_delta_count 无效',
  );

  assertRecord(value.boundaries, 'current release boundaries');
  assertExactKeys(value.boundaries, [
    'case_gallery_stock_preserved',
    'collector_isolation_required',
    'login_required',
  ], 'current release boundaries');
  assertContract(value.boundaries.case_gallery_stock_preserved === true, 'current release 未保留案例广场存量内容');
  assertContract(value.boundaries.collector_isolation_required === true, 'current release 缺少采集器隔离要求');
  assertContract(value.boundaries.login_required === false, 'current release 错误启用登录要求');

  return {
    schema_version: isV2 ? CURRENT_RELEASE_SCHEMA_V2 : CURRENT_RELEASE_SCHEMA,
    release_id: releaseId,
    generated_at_utc: value.generated_at_utc,
    datasets,
    ...(freshness ? { freshness } : {}),
    cases: {
      dataset_version: casesVersion,
      manifest_path: 'data/cases/manifest.v1.json',
      public_manifest_sha256: requireSha256(
        value.cases.public_manifest_sha256,
        'current release cases.public_manifest_sha256',
      ),
      index_path: 'data/cases/case-index.v1.json',
      index_sha256: requireSha256(value.cases.index_sha256, 'current release cases.index_sha256'),
      stock_content_preserved: true,
      approved_delta_count: Number(value.cases.approved_delta_count),
    },
    boundaries: {
      case_gallery_stock_preserved: true,
      collector_isolation_required: true,
      login_required: false,
    },
  };
}

function publicUrl(relativePath: string): string {
  const baseUrl = import.meta.env.BASE_URL.endsWith('/')
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`;
  return `${baseUrl}${relativePath}`;
}

export function getReleaseDatasetBasePath(release: CurrentRelease, key: ReleaseDatasetKey): string {
  const binding = release.datasets[key];
  assertContract(binding !== undefined, `current release 缺少数据集：${key}`);
  const manifestPath = binding.manifest_path;
  return publicUrl(manifestPath.slice(0, manifestPath.lastIndexOf('/')));
}

async function sha256Text(raw: string): Promise<string> {
  assertContract(globalThis.crypto?.subtle, '当前浏览器不支持发布完整性校验');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function loadCurrentReleaseUncached(): Promise<CurrentRelease> {
  const response = await fetch(publicUrl(CURRENT_RELEASE_RELATIVE_PATH), { cache: 'no-cache' });
  if (!response.ok) {
    throw new ReleaseContractError(`current release 加载失败（HTTP ${response.status}）`);
  }
  const raw = await response.text();
  let value: unknown;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    throw new ReleaseContractError('current release 不是有效 JSON');
  }
  return validateCurrentRelease(value);
}

export function loadCurrentRelease(): Promise<CurrentRelease> {
  releasePromise ??= loadCurrentReleaseUncached();
  return releasePromise;
}

export async function fetchVerifiedReleaseManifest<T>(
  release: CurrentRelease,
  key: ReleaseDatasetKey,
  forceReload = false,
): Promise<T> {
  const binding = release.datasets[key];
  assertContract(binding !== undefined, `current release 缺少数据集：${key}`);
  const response = await fetch(publicUrl(binding.manifest_path), {
    cache: forceReload ? 'reload' : 'no-cache',
  });
  if (!response.ok) {
    throw new ReleaseContractError(`发布 manifest 加载失败：${key}（HTTP ${response.status}）`);
  }
  const raw = await response.text();
  assertContract(
    (await sha256Text(raw)) === binding.public_manifest_sha256,
    `发布 manifest SHA-256 不一致：${key}`,
  );
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new ReleaseContractError(`发布 manifest 不是有效 JSON：${key}`);
  }
}

export function resetCurrentReleaseCacheForTests(): void {
  releasePromise = null;
}
