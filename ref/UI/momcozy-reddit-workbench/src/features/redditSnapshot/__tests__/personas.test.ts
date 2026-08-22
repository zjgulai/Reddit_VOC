import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import {
  PersonasContractError,
  V3_PERSONAS_MANIFEST_SCHEMA,
  buildV3PersonaEvidenceHref,
  loadRedditV3Personas,
  loadRedditPersonas,
  resetPersonasCacheForTests,
  validateV3PersonasOverlay,
  validatePersonasOverlay,
} from '../personas';
import type {
  PersonaManifest,
  RedditPersonasSnapshot,
  PersonaTagsData,
  PersonasData,
  V3PersonaAtomicCatalog,
  V3PersonaCohortBridge,
  V3PersonaManifest,
  V3PersonaTagsData,
  V3PersonasData,
} from '../personas';
import {
  loadRedditInsights,
  resetSnapshotCacheForTests,
  validateInsightsOverlay,
  validateSnapshotCore,
} from '../service';
import {
  resetCurrentReleaseCacheForTests,
  validateCurrentRelease,
} from '../release';
import type {
  InsightsData,
  InsightsManifest,
  InsightsSemanticAudit,
  RedditInsightsSnapshot,
  SnapshotAggregates,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../types';

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
));
const snapshotDatasetVersion = release.datasets.base.dataset_version;
const insightsDatasetVersion = release.datasets.insights.dataset_version;
const personasDatasetVersion = release.datasets.personas.dataset_version;
const snapshotDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  snapshotDatasetVersion,
);
const insightsDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  insightsDatasetVersion,
  'public',
);
const personasDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  personasDatasetVersion,
);
const currentPersonasManifest = JSON.parse(
  readFileSync(resolve(personasDirectory, 'manifest.json'), 'utf8'),
) as { schema_version?: unknown };
const isV3CurrentRelease = currentPersonasManifest.schema_version === V3_PERSONAS_MANIFEST_SCHEMA;
const fallbackV3DatasetVersion = 'reddit_voc_personas_20260716_candidate_a4';
const v3PersonasDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  isV3CurrentRelease ? personasDatasetVersion : fallbackV3DatasetVersion,
);
const hasV3PublicFixture = existsSync(resolve(v3PersonasDirectory, 'manifest.json'));
const legacyDescribe = isV3CurrentRelease ? describe.skip : describe;
const v3Describe = hasV3PublicFixture ? describe : describe.skip;

function readJson<T>(directory: string, filename: string): T {
  return JSON.parse(readFileSync(resolve(directory, filename), 'utf8')) as T;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function arrayBufferOf(bytes: Uint8Array): ArrayBuffer {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

function createPublicFetch(options?: { tamperPath?: string; missingPath?: string }) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    if (pathname === options?.missingPath) {
      return { ok: false, status: 404 } as Response;
    }
    const absolutePath = resolve(publicDirectory, pathname.slice(1));
    const original = readFileSync(absolutePath);
    const bytes = pathname === options?.tamperPath
      ? Buffer.concat([original, Buffer.from('\n<!-- tampered -->\n')])
      : original;
    const mediaType = pathname.endsWith('.svg') ? 'image/svg+xml' : 'application/json';
    return {
      ok: true,
      status: 200,
      headers: { get: (name: string) => name.toLowerCase() === 'content-type' ? mediaType : null },
      json: async () => JSON.parse(bytes.toString('utf8')) as unknown,
      text: async () => bytes.toString('utf8'),
      arrayBuffer: async () => arrayBufferOf(bytes),
    } as Response;
  });
}

let insightsSnapshot: RedditInsightsSnapshot;
let manifest: PersonaManifest;
let personas: PersonasData;
let personaTags: PersonaTagsData;

beforeAll(() => {
  if (isV3CurrentRelease) return;
  const core = validateSnapshotCore(
    readJson<SnapshotManifest>(snapshotDirectory, 'manifest-public.json'),
    readJson<SnapshotAggregates>(snapshotDirectory, 'aggregates-public.json'),
    readJson<SnapshotPost[]>(snapshotDirectory, 'posts-public.json'),
    readJson<SnapshotTagDictionary>(snapshotDirectory, 'tag-dictionary-public.json'),
    release,
  );
  insightsSnapshot = validateInsightsOverlay(
    core,
    readJson<InsightsManifest>(insightsDirectory, 'manifest.json'),
    readJson<InsightsSemanticAudit>(insightsDirectory, 'semantic-audit.json'),
    readJson<InsightsData>(insightsDirectory, 'insights.json'),
    release,
  );
  manifest = readJson<PersonaManifest>(personasDirectory, 'manifest.json');
  personas = readJson<PersonasData>(personasDirectory, 'personas.json');
  personaTags = readJson<PersonaTagsData>(personasDirectory, 'persona-tags.json');
});

afterEach(() => {
  resetPersonasCacheForTests();
  resetSnapshotCacheForTests();
  resetCurrentReleaseCacheForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

legacyDescribe('real static evidence persona contract', () => {
  it('validates the exact public persona overlay and its evidence cohorts', () => {
    const snapshot = validatePersonasOverlay(insightsSnapshot, manifest, personas, personaTags, release);

    expect(snapshot.manifest.dataset_version).toBe(personasDatasetVersion);
    expect(snapshot.data.personas.map((persona) => persona.persona_id).sort()).toEqual([
      'PER-BEHAVIOR-ADVOCATE-001',
      'PER-SCENE-WORK-001',
    ]);
    expect(snapshot.tags.assignments).toHaveLength(snapshot.manifest.assignment_count);
    expect(snapshot.manifest.assignment_count).toBe(323);
    expect(snapshot.data.personas.reduce((sum, persona) => sum + persona.metrics.matched_entities, 0)).toBe(323);
    expect(snapshot.data.personas.every((persona) => persona.avatar.synthetic)).toBe(true);
    expect(snapshot.data.personas.every((persona) => persona.metrics.distinct_pseudonyms >= 10)).toBe(true);
  });

  it('loads JSON and only creates blob URLs from verified local SVG bytes', async () => {
    const fetchMock = createPublicFetch();
    const createObjectURL = vi.fn((blob: Blob) => `blob:verified-${blob.size}`);
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });

    const snapshot = await loadRedditPersonas();

    expect(snapshot.data.personas).toHaveLength(2);
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(Object.values(snapshot.avatarAssets).every((asset) => asset.url?.startsWith('blob:verified-'))).toBe(true);
    expect(Object.values(snapshot.avatarAssets).every((asset) => asset.error === null)).toBe(true);
    const paths = fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost').pathname);
    expect(paths).toContain(`/data/reddit-voc/${personasDatasetVersion}/manifest.json`);
    expect(paths).toContain(`/data/reddit-voc/${personasDatasetVersion}/personas.json`);
    expect(paths).toContain(`/data/reddit-voc/${personasDatasetVersion}/persona-tags.json`);
    expect(paths.filter((path) => path.endsWith('.svg'))).toHaveLength(2);
    expect((await loadRedditInsights()).manifest.dataset_version).toBe(insightsDatasetVersion);
  });

  it('fails the persona module closed when a governed JSON file is tampered', async () => {
    vi.stubGlobal('fetch', createPublicFetch({
      tamperPath: `/data/reddit-voc/${personasDatasetVersion}/personas.json`,
    }));

    await expect(loadRedditPersonas()).rejects.toThrow(/(?:bytes|SHA-256).*personas\.json|personas\.json.*(?:bytes|SHA-256)/);
  });

  it('fails closed before parsing when the pinned manifest bytes change', async () => {
    vi.stubGlobal('fetch', createPublicFetch({
      tamperPath: `/data/reddit-voc/${personasDatasetVersion}/manifest.json`,
    }));

    await expect(loadRedditPersonas()).rejects.toThrow('发布 manifest SHA-256 不一致：personas');
  });

  it('keeps verified text personas but blocks a single tampered avatar', async () => {
    const createObjectURL = vi.fn(() => 'blob:verified-avatar');
    vi.stubGlobal('fetch', createPublicFetch({
      tamperPath: `/data/reddit-voc/${personasDatasetVersion}/assets/persona-work-scenario.svg`,
    }));
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });

    const snapshot = await loadRedditPersonas();
    const legacySnapshot = snapshot as RedditPersonasSnapshot;

    expect(legacySnapshot.data.personas).toHaveLength(2);
    expect(legacySnapshot.avatarAssets['PER-SCENE-WORK-001'].url).toBeNull();
    expect(legacySnapshot.avatarAssets['PER-SCENE-WORK-001'].error).toMatch(/(?:bytes|SHA-256)/);
    expect(legacySnapshot.avatarAssets['PER-BEHAVIOR-ADVOCATE-001'].url).toBe('blob:verified-avatar');
    expect(createObjectURL).toHaveBeenCalledTimes(1);
  });

  it('keeps verified text personas but reports a single missing avatar', async () => {
    vi.stubGlobal('fetch', createPublicFetch({
      missingPath: `/data/reddit-voc/${personasDatasetVersion}/assets/persona-explicit-advocate.svg`,
    }));
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:verified-avatar') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });

    const snapshot = await loadRedditPersonas();
    const legacySnapshot = snapshot as RedditPersonasSnapshot;

    expect(legacySnapshot.avatarAssets['PER-BEHAVIOR-ADVOCATE-001'].url).toBeNull();
    expect(legacySnapshot.avatarAssets['PER-BEHAVIOR-ADVOCATE-001'].error).toContain('HTTP 404');
    expect(legacySnapshot.avatarAssets['PER-SCENE-WORK-001'].url).toBe('blob:verified-avatar');
  });

  it('rejects held tag injection, privacy fields, and remote avatar paths', () => {
    const held = clone(personas);
    held.personas[0].source_tag_ids = ['L0-SVC-019'];
    expect(() => validatePersonasOverlay(insightsSnapshot, manifest, held, personaTags, release)).toThrow(
      /来源标签绑定异常|未晋级标签/,
    );

    const privacyLeak = clone(personaTags) as PersonaTagsData & { author_pseudonym?: string };
    privacyLeak.author_pseudonym = 'anon_forbidden';
    expect(() => validatePersonasOverlay(insightsSnapshot, manifest, personas, privacyLeak, release)).toThrow(/字段集合异常/);

    const remoteAvatar = clone(personas);
    remoteAvatar.personas[0].avatar.asset_path = 'https://example.com/persona.svg';
    expect(() => validatePersonasOverlay(insightsSnapshot, manifest, remoteAvatar, personaTags, release)).toThrow(
      /头像路径/,
    );
  });

  it('rejects persona metric drift and consumer_card identity overclaims', () => {
    const metricDrift = clone(personas);
    metricDrift.personas[0].metrics.matched_entities += 1;
    expect(() => validatePersonasOverlay(insightsSnapshot, manifest, metricDrift, personaTags, release)).toThrow(
      /实体计数/,
    );

    const identityOverclaim = clone(manifest);
    identityOverclaim.boundaries.consumer_card_is_reference_not_persona_id = false;
    expect(() => validatePersonasOverlay(insightsSnapshot, identityOverclaim, personas, personaTags, release)).toThrowError(
      PersonasContractError,
    );
  });

  it('rejects an ungoverned persona source stratum', () => {
    const sourceDrift = clone(personaTags);
    sourceDrift.assignments[0].source_stratum = 'unknown';

    expect(() => validatePersonasOverlay(insightsSnapshot, manifest, personas, sourceDrift, release)).toThrow(
      /来源层不受治理/,
    );
  });
});

v3Describe('V3 governed content-evidence persona contract', () => {
  let v3Manifest: V3PersonaManifest;
  let v3Personas: V3PersonasData;
  let v3Tags: V3PersonaTagsData;
  let v3Bridge: V3PersonaCohortBridge;
  let v3Catalog: V3PersonaAtomicCatalog;

  beforeAll(() => {
    v3Manifest = readJson<V3PersonaManifest>(v3PersonasDirectory, 'manifest.json');
    v3Personas = readJson<V3PersonasData>(v3PersonasDirectory, 'personas.json');
    v3Tags = readJson<V3PersonaTagsData>(v3PersonasDirectory, 'persona-tags.json');
    v3Bridge = readJson<V3PersonaCohortBridge>(v3PersonasDirectory, 'persona-cohort-bridge.json');
    v3Catalog = readJson<V3PersonaAtomicCatalog>(v3PersonasDirectory, 'persona-atomic-catalog.json');
  });

  function createV3Fetch(options?: { tamperPath?: string }) {
    return vi.fn(async (input: RequestInfo | URL) => {
      const pathname = new URL(String(input), 'http://localhost').pathname;
      const relativePath = pathname.replace('/fixtures/personas-a4/', '');
      const original = readFileSync(resolve(v3PersonasDirectory, relativePath));
      const bytes = pathname === options?.tamperPath
        ? Buffer.concat([original, Buffer.from('\n')])
        : original;
      const mediaType = pathname.endsWith('.svg') ? 'image/svg+xml' : 'application/json';
      return {
        ok: true,
        status: 200,
        headers: { get: (name: string) => name.toLowerCase() === 'content-type' ? mediaType : null },
        arrayBuffer: async () => arrayBufferOf(bytes),
      } as Response;
    });
  }

  it('accepts the formal a4 five-document contract with 8 cohorts and 82 atomic references', () => {
    const validated = validateV3PersonasOverlay(
      v3Manifest,
      v3Personas,
      v3Tags,
      v3Bridge,
      v3Catalog,
    );

    expect(validated.data.personas).toHaveLength(8);
    expect(validated.catalog.atomic_personas).toHaveLength(82);
    expect(validated.tags.post_count + validated.tags.comment_count).toBe(validated.tags.assignment_count);
    expect(validated.data.personas.every((cohort) => (
      cohort.post_count + cohort.comment_count === cohort.assignment_count
    ))).toBe(true);
    expect(validated.manifest.boundaries.author_level_personas).toBe(false);
    expect(validated.manifest.boundaries.population_share_supported).toBe(false);
    expect(validated.manifest.boundaries.real_user_images).toBe(false);
  });

  it('loads only the governed public projection documents and verified local SVG assets', async () => {
    const fetchMock = createV3Fetch();
    const createObjectURL = vi.fn((blob: Blob) => `blob:v3-${blob.size}`);
    vi.stubGlobal('fetch', fetchMock);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });

    const manifestSha256 = createHash('sha256')
      .update(readFileSync(resolve(v3PersonasDirectory, 'manifest.json')))
      .digest('hex');
    const snapshot = await loadRedditV3Personas({
      basePath: '/fixtures/personas-a4',
      expectedManifestSha256: manifestSha256,
      releaseId: 'reddit_voc_release_personas_a4_fixture',
    });

    expect(snapshot.data.personas).toHaveLength(8);
    expect(snapshot.catalog.atomic_personas).toHaveLength(82);
    expect(Object.values(snapshot.avatarAssets).every((asset) => asset.url?.startsWith('blob:v3-'))).toBe(true);
    const paths = fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost').pathname);
    expect(paths).not.toContain('/fixtures/personas-a4/persona-atomic-facts.jsonl');
    expect(paths).toEqual(expect.arrayContaining([
      '/fixtures/personas-a4/manifest.json',
      '/fixtures/personas-a4/personas.json',
      '/fixtures/personas-a4/persona-tags.json',
      '/fixtures/personas-a4/persona-cohort-bridge.json',
      '/fixtures/personas-a4/persona-atomic-catalog.json',
    ]));
    const commentAssignment = snapshot.tags.assignments.find((assignment) => assignment.source_entity_type === 'comment');
    if (!commentAssignment) throw new Error('fixture lacks a comment assignment');
    const evidenceHref = buildV3PersonaEvidenceHref(
      commentAssignment,
      snapshot.manifest.snapshot_id,
      snapshot.releaseId,
    );
    const evidenceUrl = new URL(evidenceHref, 'http://localhost');
    const expectedParentPostId = commentAssignment.parent_post_id.startsWith('t3_')
      ? commentAssignment.parent_post_id
      : `t3_${commentAssignment.parent_post_id}`;
    expect(evidenceUrl.searchParams.get('q')).toBe(expectedParentPostId);
    expect(evidenceUrl.searchParams.get('post')).toBe(expectedParentPostId);
    expect(evidenceUrl.searchParams.get('comment')).toBe(commentAssignment.entity_id);
    expect(evidenceUrl.searchParams.get('release')).toBe('reddit_voc_release_personas_a4_fixture');
  });

  it('dispatches the real hook loader from the current-release V3 persona binding without legacy fallback', async () => {
    const manifestSha256 = createHash('sha256')
      .update(readFileSync(resolve(v3PersonasDirectory, 'manifest.json')))
      .digest('hex');
    const releaseId = 'reddit_voc_release_personas_a4_fixture';
    const v3Release = {
      ...release,
      release_id: releaseId,
      datasets: {
        ...release.datasets,
        personas: {
          dataset_version: v3Manifest.snapshot_id,
          manifest_path: `data/reddit-voc/${v3Manifest.snapshot_id}/manifest.json`,
          public_manifest_sha256: manifestSha256,
          lineage_manifest_sha256: manifestSha256,
        },
      },
    };
    const basePath = `/data/reddit-voc/${v3Manifest.snapshot_id}`;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const pathname = new URL(String(input), 'http://localhost').pathname;
      let bytes: Buffer;
      if (pathname === '/data/reddit-voc/current-release.json') {
        bytes = Buffer.from(JSON.stringify(v3Release));
      } else {
        const relativePath = pathname.replace(`${basePath}/`, '');
        bytes = readFileSync(resolve(v3PersonasDirectory, relativePath));
      }
      const mediaType = pathname.endsWith('.svg') ? 'image/svg+xml' : 'application/json';
      return {
        ok: true,
        status: 200,
        headers: { get: (name: string) => name.toLowerCase() === 'content-type' ? mediaType : null },
        text: async () => bytes.toString('utf8'),
        arrayBuffer: async () => arrayBufferOf(bytes),
      } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn((blob: Blob) => `blob:v3-hook-${blob.size}`) });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });

    const snapshot = await loadRedditPersonas();

    expect('catalog' in snapshot).toBe(true);
    if (!('catalog' in snapshot)) throw new Error('current-release V3 dispatch returned legacy personas');
    expect(snapshot.releaseId).toBe(releaseId);
    expect(snapshot.data.personas).toHaveLength(8);
    expect(snapshot.catalog.atomic_personas).toHaveLength(82);
    const paths = fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost').pathname);
    expect(paths.filter((path) => path === `${basePath}/manifest.json`)).toHaveLength(2);
    expect(paths.some((path) => path.includes(release.datasets.insights.dataset_version))).toBe(false);
  });

  it('fails closed on exact-key, count, evidence-scope and manifest-byte tampering', async () => {
    const extraKey = { ...clone(v3Manifest), unexpected: true };
    expect(() => validateV3PersonasOverlay(extraKey, v3Personas, v3Tags, v3Bridge, v3Catalog)).toThrow(/字段集合异常/);

    const countDrift = clone(v3Catalog);
    (countDrift as { atomic_persona_count: number }).atomic_persona_count = 81;
    expect(() => validateV3PersonasOverlay(v3Manifest, v3Personas, v3Tags, v3Bridge, countDrift)).toThrow(/82|原子/);

    const inheritedParentPersona = clone(v3Tags);
    const comment = inheritedParentPersona.assignments.find((assignment) => assignment.source_entity_type === 'comment');
    if (!comment) throw new Error('fixture lacks a comment assignment');
    comment.evidence_scope = ['cross_context'];
    expect(() => validateV3PersonasOverlay(v3Manifest, v3Personas, inheritedParentPersona, v3Bridge, v3Catalog)).toThrow(
      /评论正文|current_comment_body/,
    );

    const manifestSha256 = createHash('sha256')
      .update(readFileSync(resolve(v3PersonasDirectory, 'manifest.json')))
      .digest('hex');
    vi.stubGlobal('fetch', createV3Fetch({ tamperPath: '/fixtures/personas-a4/manifest.json' }));
    await expect(loadRedditV3Personas({
      basePath: '/fixtures/personas-a4',
      expectedManifestSha256: manifestSha256,
      releaseId: 'reddit_voc_release_personas_a4_fixture',
    })).rejects.toThrow(/manifest SHA-256/);
  });
});
