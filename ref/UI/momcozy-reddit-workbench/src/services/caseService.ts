import {
  filterCases,
  hotSearchTags,
  caseCategories,
  seedCases,
  type CaseCategory,
  type CaseItem,
  type CaseSearchResult,
} from '../data/casesMock';
import { legacyUnverifiedCases } from './caseSearchService';

export const CASE_CATALOG_MANIFEST_PATH = '/data/cases/manifest.v1.json';

interface CaseCatalogSliceContract {
  version: string;
  count: number;
  contentSha256: string;
}

export interface CaseCatalogManifest {
  schemaVersion: 1;
  datasetVersion: string;
  generatedAt: string;
  freshness: {
    mode: 'static';
    asOf: string;
    staleAfter: string;
  };
  provenance: {
    process: 'manual_seed_plus_approved_static_delta';
    networkSearch: false;
    owner: string;
  };
  seed: CaseCatalogSliceContract & { source: 'bundled_seed' };
  legacyUnverified: CaseCatalogSliceContract & { source: 'bundled_legacy_snapshot' };
  approvedDelta: CaseCatalogSliceContract & { source: 'versioned_static_index' };
  index: {
    path: string;
    sha256: string;
  };
}

export interface CaseCatalogIndex {
  schemaVersion: 1;
  datasetVersion: string;
  approvedDelta: CaseItem[];
}

export interface CaseCatalogMeta {
  status: 'verified_index' | 'seed_only';
  datasetVersion: string;
  generatedAt: string | null;
  asOf?: string | null;
  staleAfter?: string | null;
  freshness: 'fresh' | 'stale' | 'unknown';
  seedCount: number;
  legacyUnverifiedCount: number;
  approvedDeltaCount: number;
  fallbackReason?: string;
}

export type CaseCatalogSearchResult = CaseSearchResult & { meta: CaseCatalogMeta };
export type CaseCatalogView = 'reference' | 'review';

interface LoadedCaseCatalog {
  items: CaseItem[];
  meta: CaseCatalogMeta;
}

const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const CONTENT_HASH_PATTERN = /^sha256:[a-f0-9]{64}$/;
const CASE_CATEGORIES = new Set<CaseCategory>(['geo', 'newproduct', 'insight', 'business']);
const TRACKING_PARAMS = new Set(['fbclid', 'gclid', 'mc_cid', 'mc_eid']);
/** 2026-07-16 只读 HTTP 检查遇到 500 或微信验证码跳转；内容保留在待复核区。 */
const SEED_REVIEW_ONLY_IDS = new Set(['geo1', 'geo2', 'geo3', 'geo4', 'in1']);

let catalogCache: LoadedCaseCatalog | null = null;

function assertRecord(value: unknown, label: string): asserts value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} 必须是对象`);
  }
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`${label} 必须是非空字符串`);
  }
  return value;
}

function requireDate(value: unknown, label: string): string {
  const date = requireString(value, label);
  if (Number.isNaN(Date.parse(date))) {
    throw new Error(`${label} 不是有效日期`);
  }
  return date;
}

function requireSha256(value: unknown, label: string): string {
  const digest = requireString(value, label).toLowerCase();
  if (!SHA256_PATTERN.test(digest)) {
    throw new Error(`${label} 不是有效 SHA-256`);
  }
  return digest;
}

function validateSliceContract(
  value: unknown,
  label: string,
  expectedSource: CaseCatalogManifest['seed']['source'] | CaseCatalogManifest['legacyUnverified']['source'] | CaseCatalogManifest['approvedDelta']['source'],
): CaseCatalogSliceContract {
  assertRecord(value, label);
  if (value.source !== expectedSource) {
    throw new Error(`${label}.source 不受支持`);
  }
  if (!Number.isInteger(value.count) || Number(value.count) < 0) {
    throw new Error(`${label}.count 必须是非负整数`);
  }
  return {
    version: requireString(value.version, `${label}.version`),
    count: Number(value.count),
    contentSha256: requireSha256(value.contentSha256, `${label}.contentSha256`),
  };
}

export function validateCaseCatalogManifest(value: unknown): CaseCatalogManifest {
  assertRecord(value, '案例 manifest');
  if (value.schemaVersion !== 1) throw new Error('案例 manifest schemaVersion 不受支持');

  assertRecord(value.freshness, '案例 manifest.freshness');
  if (value.freshness.mode !== 'static') throw new Error('案例 manifest 仅支持 static freshness');

  assertRecord(value.provenance, '案例 manifest.provenance');
  if (
    value.provenance.process !== 'manual_seed_plus_approved_static_delta'
    || value.provenance.networkSearch !== false
  ) {
    throw new Error('案例 manifest provenance 不受支持');
  }

  assertRecord(value.index, '案例 manifest.index');
  const indexPath = requireString(value.index.path, '案例 manifest.index.path');
  if (!indexPath.startsWith('/data/cases/') || !indexPath.endsWith('.json')) {
    throw new Error('案例 manifest.index.path 必须指向同源静态 JSON');
  }

  const seed = validateSliceContract(value.seed, '案例 manifest.seed', 'bundled_seed');
  const legacyUnverified = validateSliceContract(
    value.legacyUnverified,
    '案例 manifest.legacyUnverified',
    'bundled_legacy_snapshot',
  );
  const approvedDelta = validateSliceContract(
    value.approvedDelta,
    '案例 manifest.approvedDelta',
    'versioned_static_index',
  );

  return {
    schemaVersion: 1,
    datasetVersion: requireString(value.datasetVersion, '案例 manifest.datasetVersion'),
    generatedAt: requireDate(value.generatedAt, '案例 manifest.generatedAt'),
    freshness: {
      mode: 'static',
      asOf: requireDate(value.freshness.asOf, '案例 manifest.freshness.asOf'),
      staleAfter: requireDate(value.freshness.staleAfter, '案例 manifest.freshness.staleAfter'),
    },
    provenance: {
      process: 'manual_seed_plus_approved_static_delta',
      networkSearch: false,
      owner: requireString(value.provenance.owner, '案例 manifest.provenance.owner'),
    },
    seed: { ...seed, source: 'bundled_seed' },
    legacyUnverified: { ...legacyUnverified, source: 'bundled_legacy_snapshot' },
    approvedDelta: { ...approvedDelta, source: 'versioned_static_index' },
    index: {
      path: indexPath,
      sha256: requireSha256(value.index.sha256, '案例 manifest.index.sha256'),
    },
  };
}

function validateApprovedCase(value: unknown, index: number): CaseItem {
  const label = `approvedDelta[${index}]`;
  assertRecord(value, label);
  if (!CASE_CATEGORIES.has(value.category as CaseCategory)) {
    throw new Error(`${label}.category 不受支持`);
  }
  if (value.sourceKind !== 'approved_delta' || value.verificationStatus !== 'verified') {
    throw new Error(`${label} 必须是已验证增量`);
  }
  if (!Array.isArray(value.tags) || !value.tags.every((tag) => typeof tag === 'string' && tag.trim())) {
    throw new Error(`${label}.tags 必须是非空字符串数组`);
  }

  const url = requireString(value.url, `${label}.url`);
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(url);
  } catch {
    throw new Error(`${label}.url 无效`);
  }
  if (parsedUrl.protocol !== 'https:') throw new Error(`${label}.url 必须使用 HTTPS`);

  const contentHash = requireString(value.contentHash, `${label}.contentHash`).toLowerCase();
  if (!CONTENT_HASH_PATTERN.test(contentHash)) {
    throw new Error(`${label}.contentHash 必须是 sha256:<digest>`);
  }

  return {
    id: requireString(value.id, `${label}.id`),
    title: requireString(value.title, `${label}.title`),
    description: requireString(value.description, `${label}.description`),
    source: requireString(value.source, `${label}.source`),
    url,
    category: value.category as CaseCategory,
    tags: value.tags as string[],
    date: requireDate(value.date, `${label}.date`),
    sourceKind: 'approved_delta',
    verificationStatus: 'verified',
    canonicalUrl: requireString(value.canonicalUrl ?? url, `${label}.canonicalUrl`),
    contentHash,
    updatedAt: requireDate(value.updatedAt, `${label}.updatedAt`),
    lastVerifiedAt: requireDate(value.lastVerifiedAt, `${label}.lastVerifiedAt`),
    provenance: requireString(value.provenance, `${label}.provenance`),
  };
}

export function validateCaseCatalogIndex(value: unknown, datasetVersion: string): CaseCatalogIndex {
  assertRecord(value, '案例 index');
  if (value.schemaVersion !== 1) throw new Error('案例 index schemaVersion 不受支持');
  if (value.datasetVersion !== datasetVersion) throw new Error('案例 index 与 manifest 版本不一致');
  if (!Array.isArray(value.approvedDelta)) throw new Error('案例 index.approvedDelta 必须是数组');
  return {
    schemaVersion: 1,
    datasetVersion,
    approvedDelta: value.approvedDelta.map(validateApprovedCase),
  };
}

async function sha256Hex(content: string): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error('当前环境不支持 SHA-256 校验');
  const bytes = new TextEncoder().encode(content);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function stableContentHash(item: CaseItem): string {
  const normalized = [item.title, item.description, item.source, item.category, item.date]
    .join('\u001f')
    .normalize('NFKC')
    .trim()
    .toLowerCase();
  let hash = 0x811c9dc5;
  for (let index = 0; index < normalized.length; index += 1) {
    hash ^= normalized.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

export function canonicalizeCaseUrl(value: string): string {
  try {
    const url = new URL(value);
    url.hash = '';
    if (url.protocol === 'http:' || url.protocol === 'https:') url.protocol = 'https:';
    url.hostname = url.hostname.toLowerCase().replace(/^www\./, '');
    for (const key of Array.from(url.searchParams.keys())) {
      if (key.toLowerCase().startsWith('utm_') || TRACKING_PARAMS.has(key.toLowerCase())) {
        url.searchParams.delete(key);
      }
    }
    url.searchParams.sort();
    if (url.pathname.length > 1) url.pathname = url.pathname.replace(/\/+$/, '');
    return url.toString();
  } catch {
    return value.trim().toLowerCase();
  }
}

export function isNavigableCaseUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === 'https:' || url.protocol === 'http:') && url.hostname.trim() !== '';
  } catch {
    return false;
  }
}

function caseIdentityKeys(item: CaseItem): string[] {
  return [
    `id:${item.id.trim().toLowerCase()}`,
    `url:${canonicalizeCaseUrl(item.canonicalUrl ?? item.url)}`,
    `content:${item.contentHash?.toLowerCase() ?? stableContentHash(item)}`,
  ];
}

/** seed 优先；approved delta 优先于 legacy。每个来源内部保持确定性顺序。 */
export function mergeCaseCatalog(
  seed: CaseItem[],
  legacyUnverified: CaseItem[],
  approvedDelta: CaseItem[],
): CaseItem[] {
  const approvedSorted = approvedDelta.slice().sort((left, right) =>
    right.date.localeCompare(left.date) || left.id.localeCompare(right.id));
  const legacySorted = legacyUnverified.slice().sort((left, right) =>
    right.date.localeCompare(left.date) || left.id.localeCompare(right.id));
  const candidates = [...seed, ...approvedSorted, ...legacySorted];
  const seen = new Set<string>();
  const merged: CaseItem[] = [];

  for (const item of candidates) {
    const keys = caseIdentityKeys(item);
    if (keys.some((key) => seen.has(key))) continue;
    merged.push(item);
    keys.forEach((key) => seen.add(key));
  }
  return merged;
}

function seedOnlyCatalog(reason: string): LoadedCaseCatalog {
  const curatedSeed = seedCases
    .map((item) => ({
      ...item,
      verificationStatus: (
        !SEED_REVIEW_ONLY_IDS.has(item.id) && isNavigableCaseUrl(item.url)
          ? 'curated'
          : 'pending'
      ) as CaseItem['verificationStatus'],
      defaultEligible: !SEED_REVIEW_ONLY_IDS.has(item.id) && isNavigableCaseUrl(item.url),
    }));
  return {
    items: curatedSeed,
    meta: {
      status: 'seed_only',
      datasetVersion: 'case_seed_bundled_v1',
      generatedAt: null,
      freshness: 'unknown',
      seedCount: curatedSeed.length,
      legacyUnverifiedCount: 0,
      approvedDeltaCount: 0,
      fallbackReason: reason,
    },
  };
}

function decorateCatalogItems(
  seed: CaseItem[],
  legacyUnverified: CaseItem[],
  approvedDelta: CaseItem[],
): CaseItem[] {
  const governedSeed = seed.map((item) => {
    const defaultEligible = !SEED_REVIEW_ONLY_IDS.has(item.id) && isNavigableCaseUrl(item.url);
    return {
      ...item,
      verificationStatus: defaultEligible ? 'curated' as const : 'pending' as const,
      defaultEligible,
    };
  });
  const governedLegacy = legacyUnverified.map((item) => ({
    ...item,
    verificationStatus: 'pending' as const,
    defaultEligible: false,
  }));
  const governedApproved = approvedDelta.map((item) => ({
    ...item,
    defaultEligible: item.verificationStatus === 'verified' && isNavigableCaseUrl(item.url),
  }));
  return mergeCaseCatalog(governedSeed, governedLegacy, governedApproved);
}

async function loadCaseCatalog(signal?: AbortSignal, forceRefresh = false): Promise<LoadedCaseCatalog> {
  if (!forceRefresh && catalogCache) return catalogCache;
  if (signal?.aborted) throw new Error('Aborted');

  try {
    const manifestResponse = await fetch(CASE_CATALOG_MANIFEST_PATH, {
      signal,
      cache: 'no-cache',
      headers: { Accept: 'application/json' },
    });
    if (!manifestResponse.ok) throw new Error(`案例 manifest HTTP ${manifestResponse.status}`);
    const manifest = validateCaseCatalogManifest(await manifestResponse.json());

    const indexResponse = await fetch(manifest.index.path, {
      signal,
      cache: 'no-cache',
      headers: { Accept: 'application/json' },
    });
    if (!indexResponse.ok) throw new Error(`案例 index HTTP ${indexResponse.status}`);
    const indexText = await indexResponse.text();

    const [indexDigest, seedDigest, legacyDigest] = await Promise.all([
      sha256Hex(indexText),
      sha256Hex(JSON.stringify(seedCases)),
      sha256Hex(JSON.stringify(legacyUnverifiedCases)),
    ]);
    if (indexDigest !== manifest.index.sha256) throw new Error('案例 index SHA-256 不一致');
    if (seedDigest !== manifest.seed.contentSha256) throw new Error('案例 seed SHA-256 不一致');
    if (legacyDigest !== manifest.legacyUnverified.contentSha256) {
      throw new Error('案例 legacy_unverified SHA-256 不一致');
    }
    if (manifest.seed.count !== seedCases.length || manifest.legacyUnverified.count !== legacyUnverifiedCases.length) {
      throw new Error('案例 bundled count 与 manifest 不一致');
    }

    const index = validateCaseCatalogIndex(JSON.parse(indexText), manifest.datasetVersion);
    const approvedDigest = await sha256Hex(JSON.stringify(index.approvedDelta));
    if (approvedDigest !== manifest.approvedDelta.contentSha256) {
      throw new Error('案例 approved delta SHA-256 不一致');
    }
    if (manifest.approvedDelta.count !== index.approvedDelta.length) {
      throw new Error('案例 approved delta count 与 manifest 不一致');
    }

    const items = decorateCatalogItems(seedCases, legacyUnverifiedCases, index.approvedDelta);
    const loaded: LoadedCaseCatalog = {
      items,
      meta: {
        status: 'verified_index',
        datasetVersion: manifest.datasetVersion,
        generatedAt: manifest.generatedAt,
        asOf: manifest.freshness.asOf,
        staleAfter: manifest.freshness.staleAfter,
        freshness: Date.now() > Date.parse(manifest.freshness.staleAfter) ? 'stale' : 'fresh',
        seedCount: items.filter((item) => item.sourceKind === 'curated_seed').length,
        legacyUnverifiedCount: items.filter((item) => item.sourceKind === 'legacy_unverified').length,
        approvedDeltaCount: items.filter((item) => item.sourceKind === 'approved_delta').length,
      },
    };
    catalogCache = loaded;
    return loaded;
  } catch (error) {
    if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
      throw new Error('Aborted');
    }
    const reason = error instanceof Error ? error.message : '案例增量索引不可用';
    const fallback = seedOnlyCatalog(reason);
    catalogCache = fallback;
    return fallback;
  }
}

export async function searchCases(
  query: string,
  category: CaseCategory | 'all' = 'all',
  signal?: AbortSignal,
  options: { refresh?: boolean; view?: CaseCatalogView } = {},
): Promise<CaseCatalogSearchResult> {
  const catalog = await loadCaseCatalog(signal, options.refresh === true);
  const view = options.view ?? 'reference';
  const visibleItems = catalog.items.filter((item) => (
    view === 'reference' ? item.defaultEligible === true : item.defaultEligible === false
  ));
  const result = await filterCases(visibleItems, query, category, signal);
  return { ...result, meta: catalog.meta };
}

export function resetCaseCatalogCacheForTests(): void {
  catalogCache = null;
}

export { hotSearchTags, caseCategories };
export type { CaseCategory, CaseItem, CaseSearchResult };
