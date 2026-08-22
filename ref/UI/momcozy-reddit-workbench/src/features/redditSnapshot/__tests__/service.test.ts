import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  isRiskInsightsData,
  SnapshotContractError,
  loadRedditInsights,
  resetSnapshotCacheForTests,
  validateInsightsOverlay,
  validateSnapshotComments,
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
  SnapshotAggregates,
  SnapshotComment,
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
const snapshotDirectory = resolve(publicDirectory, 'data/reddit-voc', snapshotDatasetVersion);
const insightsDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  insightsDatasetVersion,
  'public',
);
const snapshotManifest = JSON.parse(
  readFileSync(resolve(snapshotDirectory, 'manifest-public.json'), 'utf8'),
) as SnapshotManifest;
const isV3CurrentRelease = snapshotManifest.schema_version === 'reddit_voc_site_snapshot_manifest_v3';
const legacyIt = isV3CurrentRelease ? it.skip : it;
const legacyDescribe = isV3CurrentRelease ? describe.skip : describe;

function readJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(snapshotDirectory, filename), 'utf8')) as T;
}

function loadFixture() {
  return {
    manifest: readJson<SnapshotManifest>('manifest-public.json'),
    aggregates: readJson<SnapshotAggregates>('aggregates-public.json'),
    posts: readJson<SnapshotPost[]>('posts-public.json'),
    comments: readJson<SnapshotComment[]>('comments-public.json'),
    tagDictionary: readJson<SnapshotTagDictionary>('tag-dictionary-public.json'),
  };
}

function loadV3BaseFixture() {
  const read = <T>(filename: string): T => JSON.parse(
    readFileSync(resolve(snapshotDirectory, filename), 'utf8'),
  ) as T;
  const manifest = read<SnapshotManifest>('manifest-public.json');
  return {
    release,
    manifest,
    aggregates: read<SnapshotAggregates>('aggregates-public.json'),
    posts: read<SnapshotPost[]>('posts-public.json'),
    comments: read<SnapshotComment[]>('comments-public.json'),
    tagDictionary: read<SnapshotTagDictionary>('tag-dictionary-public.json'),
  };
}

function asV2Manifest(manifest: SnapshotManifest): SnapshotManifest {
  const v2Manifest = structuredClone(manifest);
  v2Manifest.schema_version = 'reddit_voc_site_snapshot_manifest_v2';
  return v2Manifest;
}

function readInsightsJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(insightsDirectory, filename), 'utf8')) as T;
}

function loadInsightsFixture() {
  return {
    manifest: readInsightsJson<InsightsManifest>('manifest.json'),
    audit: readInsightsJson<InsightsSemanticAudit>('semantic-audit.json'),
    insights: readInsightsJson<InsightsData>('insights.json'),
  };
}

function createPublicFetch(overrides: Record<string, string> = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname;
    const body = overrides[pathname]
      ?? readFileSync(resolve(publicDirectory, pathname.slice(1)), 'utf8');
    return {
      ok: true,
      status: 200,
      json: async () => JSON.parse(body) as unknown,
      text: async () => body,
    } as Response;
  });
}

describe('Reddit static snapshot contract', () => {
  it('validates the exact public snapshot copied into the UI', () => {
    const fixture = loadFixture();
    const core = validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    );
    const comments = validateSnapshotComments(core, fixture.comments);

    expect(core.manifest.dataset_version).toBe(snapshotDatasetVersion);
    expect(core.posts).toHaveLength(core.manifest.canonical_counts.posts);
    expect(comments).toHaveLength(core.manifest.canonical_counts.linked_comments);
    expect(core.aggregates.headline.comments_in_voc_metrics).toBeLessThanOrEqual(comments.length);
    expect(core.aggregates.headline.quarantined_comments).toBe(0);
    expect(core.manifest.production_unchanged).toBe(true);
    expect(core.manifest.provider_call).toBe(false);
    expect(core.manifest.live_send).toBe(false);
  });

  legacyIt('accepts the governed Base v2 event-time, coverage, and product-ledger contract', () => {
    const fixture = loadFixture();
    const v2Manifest = asV2Manifest(fixture.manifest);

    const core = validateSnapshotCore(
      v2Manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    );
    const comments = validateSnapshotComments(core, fixture.comments);

    expect(core.manifest.schema_version).toBe('reddit_voc_site_snapshot_manifest_v2');
    expect(core.aggregates.coverage_grade.post_only).toBe(1);
    expect(comments).toHaveLength(core.manifest.canonical_counts.linked_comments);
  });

  it('loads the complete V3 Base with preserved day precision and explicit pending linkage', () => {
    const fixture = loadV3BaseFixture();
    const core = validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      fixture.release,
    );
    const comments = validateSnapshotComments(core, fixture.comments);

    expect(core.posts).toHaveLength(core.manifest.canonical_counts.posts);
    expect(comments).toHaveLength(core.manifest.canonical_counts.linked_comments);
    expect(core.manifest.canonical_counts.stored_comments).toBe(
      core.manifest.canonical_counts.linked_comments
        + (core.manifest.canonical_counts.unresolved_parent_comments ?? 0)
        + (core.manifest.canonical_counts.quarantined_comments ?? 0),
    );
    expect(core.posts.some((post) => post.event_time_precision === 'day')).toBe(true);
    expect(comments.some((comment) => comment.event_time_precision === 'day')).toBe(true);
    expect(core.posts.every((post) => post.author_pseudonym === null)).toBe(true);
    expect(comments.every((comment) => comment.author_pseudonym === null)).toBe(true);
  });

  it('accepts a complete local-only V3 translation candidate without making it promotable', () => {
    const fixture = loadV3BaseFixture();
    const manifest = structuredClone(fixture.manifest);
    const translatedDatasetVersion = `${manifest.dataset_version}_zh_deepseek_fixture`;
    manifest.dataset_version = translatedDatasetVersion;
    manifest.generated_at_utc = '2026-08-09T14:00:00Z';
    manifest.status = 'validated_local_translation_candidate';
    manifest.artifact_stage = 'local_translation_candidate';
    manifest.consumption_status = 'eligible_for_frontend_candidate_consumption';
    manifest.promotable = false;
    manifest.provider_call = true;
    if (!manifest.boundaries) throw new Error('fixture missing boundaries');
    manifest.boundaries.provider_call = true;
    manifest.files['post-translations-public.json'] = { bytes: 1, sha256: 'a'.repeat(64) };
    manifest.files['comment-translations-public.json'] = { bytes: 1, sha256: 'b'.repeat(64) };
    manifest.translations = {
      schema_version: 'reddit_voc_translation_extension_v1',
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      provider_call: true,
      provider_authorization_id: 'reddit_voc_p2d2_translation_20260809',
      source_dataset_version: fixture.manifest.dataset_version,
      source_public_manifest_sha256: 'c'.repeat(64),
      translation_prompt_sha256: 'd'.repeat(64),
      translation_terms_sha256: 'e'.repeat(64),
      checkpoint_sha256: 'f'.repeat(64),
      provider_attempt_log_sha256: '1'.repeat(64),
      quality_gate: 'deterministic_contract_v1',
      semantic_validation: 'not_run',
      independent_human_review: false,
      coverage: {
        posts: manifest.canonical_counts.posts,
        post_titles: manifest.canonical_counts.posts,
        post_contents: manifest.canonical_counts.posts,
        comments: manifest.canonical_counts.linked_comments,
        comments_total: manifest.canonical_counts.linked_comments,
        comments_status: 'complete',
        comments_unavailable_reason: null,
        post_translation_status: 'complete',
        translated_items:
          manifest.canonical_counts.posts * 2 + manifest.canonical_counts.linked_comments,
      },
      provider_attempts: 1,
      usage: {
        prompt_tokens: 10,
        completion_tokens: 5,
        prompt_cache_hit_tokens: 0,
        prompt_cache_miss_tokens: 10,
        total_tokens: 15,
      },
    };
    const translatedRelease = structuredClone(fixture.release);
    translatedRelease.datasets.base.dataset_version = translatedDatasetVersion;

    const core = validateSnapshotCore(
      manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      translatedRelease,
    );

    expect(core.manifest.status).toBe('validated_local_translation_candidate');
    expect(core.manifest.promotable).toBe(false);
    expect(core.manifest.translations?.independent_human_review).toBe(false);
  });

  it('accepts explicit partial comment translation coverage while posts stay complete', () => {
    const fixture = loadV3BaseFixture();
    const manifest = structuredClone(fixture.manifest);
    manifest.dataset_version = `${manifest.dataset_version}_zh_partial_comments`;
    manifest.status = 'validated_local_translation_candidate';
    manifest.artifact_stage = 'local_translation_candidate';
    manifest.consumption_status = 'eligible_for_frontend_candidate_consumption';
    manifest.promotable = false;
    manifest.provider_call = true;
    if (!manifest.boundaries) throw new Error('fixture missing boundaries');
    manifest.boundaries.provider_call = true;
    manifest.files['post-translations-public.json'] = { bytes: 1, sha256: 'a'.repeat(64) };
    manifest.files['comment-translations-public.json'] = { bytes: 1, sha256: 'b'.repeat(64) };
    manifest.translations = {
      schema_version: 'reddit_voc_translation_extension_v1',
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      provider_call: true,
      provider_authorization_id: 'reddit_voc_p2d2_translation_20260809',
      source_dataset_version: fixture.manifest.dataset_version,
      source_public_manifest_sha256: 'c'.repeat(64),
      translation_prompt_sha256: 'd'.repeat(64),
      translation_terms_sha256: 'e'.repeat(64),
      checkpoint_sha256: 'f'.repeat(64),
      provider_attempt_log_sha256: '1'.repeat(64),
      quality_gate: 'deterministic_contract_v1',
      semantic_validation: 'not_run',
      independent_human_review: false,
      coverage: {
        posts: manifest.canonical_counts.posts,
        post_titles: manifest.canonical_counts.posts,
        post_contents: manifest.canonical_counts.posts,
        comments: 0,
        comments_total: manifest.canonical_counts.linked_comments,
        comments_status: 'partial',
        comments_unavailable_reason: 'provider_http_402_balance_blocked',
        post_translation_status: 'complete',
        translated_items: manifest.canonical_counts.posts * 2,
      },
      provider_attempts: 1,
      usage: {
        prompt_tokens: 10,
        completion_tokens: 5,
        prompt_cache_hit_tokens: 0,
        prompt_cache_miss_tokens: 10,
        total_tokens: 15,
      },
    };
    const translatedRelease = structuredClone(fixture.release);
    translatedRelease.datasets.base.dataset_version = manifest.dataset_version;

    expect(validateSnapshotCore(
      manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      translatedRelease,
    ).manifest.translations?.coverage.comments_status).toBe('partial');
  });

  it('fails closed when V3 day precision is converted into a fabricated instant', () => {
    const fixture = loadV3BaseFixture();
    const posts = structuredClone(fixture.posts);
    const dayPost = posts.find((post) => post.event_time_precision === 'day');
    if (!dayPost) throw new Error('fixture missing day precision post');
    dayPost.event_created_at_utc = `${dayPost.created_at_utc}T00:00:00+00:00`;

    expect(() => validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      posts,
      fixture.tagDictionary,
      fixture.release,
    )).toThrow('伪造了日精度时刻');
  });

  it('fails closed for an unknown Base schema', () => {
    const fixture = loadFixture();
    const invalidManifest = {
      ...fixture.manifest,
      schema_version: 'reddit_voc_site_snapshot_manifest_v4',
    } as unknown as SnapshotManifest;

    expect(() => validateSnapshotCore(
      invalidManifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    )).toThrow('快照 manifest schema 不受支持');
  });

  it('fails closed for an unknown structural coverage grade', () => {
    const fixture = loadFixture();
    const invalidPosts = [...fixture.posts];
    invalidPosts[0] = {
      ...invalidPosts[0],
      structural_coverage_grade: 'unknown_grade',
    } as unknown as SnapshotPost;

    expect(() => validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      invalidPosts,
      fixture.tagDictionary,
      release,
    )).toThrow('帖子结构覆盖等级不受支持');
  });

  it('fails closed when aggregate structural coverage no longer conserves posts', () => {
    const fixture = loadFixture();
    const invalidAggregates = structuredClone(fixture.aggregates);
    invalidAggregates.coverage_grade.full = (invalidAggregates.coverage_grade.full ?? 0) + 1;

    expect(() => validateSnapshotCore(
      fixture.manifest,
      invalidAggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    )).toThrow('帖子结构覆盖计数不守恒');
  });

  legacyIt('fails closed when Base v2 event-time coverage mapping drifts', () => {
    const fixture = loadFixture();
    const invalidManifest = asV2Manifest(fixture.manifest);
    const semanticBoundaries = invalidManifest.semantic_boundaries as SnapshotManifest['semantic_boundaries'] & {
      comment_coverage_status_mapping: Record<string, string>;
    };
    semanticBoundaries.comment_coverage_status_mapping.partial = 'thread_complete';

    expect(() => validateSnapshotCore(
      invalidManifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    )).toThrow('v2 评论覆盖映射异常');
  });

  legacyIt('fails closed when the Base v2 product ledger hash drifts', () => {
    const fixture = loadFixture();
    const invalidManifest = asV2Manifest(fixture.manifest);
    const semanticBoundaries = invalidManifest.semantic_boundaries as SnapshotManifest['semantic_boundaries'] & {
      product_entity_ledger_sha256: string;
    };
    semanticBoundaries.product_entity_ledger_sha256 = '0'.repeat(64);

    expect(() => validateSnapshotCore(
      invalidManifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    )).toThrow('v2 产品实体 ledger 哈希不一致');
  });

  legacyIt('fails closed when the Base v2 product coverage ledger is not conserved', () => {
    const fixture = loadFixture();
    const invalidManifest = asV2Manifest(fixture.manifest);
    const tagging = invalidManifest.tagging as SnapshotManifest['tagging'] & {
      product_entity_resolution: {
        coverage: { posts: { bound_record_count: number } };
      };
    };
    tagging.product_entity_resolution.coverage.posts.bound_record_count += 1;

    expect(() => validateSnapshotCore(
      invalidManifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    )).toThrow('v2 产品覆盖账本不守恒：posts');
  });

  it('fails closed when upstream validation is not green', () => {
    const fixture = loadFixture();
    const invalidManifest = { ...fixture.manifest, all_checks_passed: false };

    expect(() => validateSnapshotCore(
      invalidManifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    )).toThrowError(SnapshotContractError);
  });

  it('fails closed when entity counts drift from the manifest', () => {
    const fixture = loadFixture();
    const missingPost = fixture.posts.slice(1);

    expect(() => validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      missingPost,
      fixture.tagDictionary,
      release,
    )).toThrow('帖子数组数量与 manifest 不一致');
  });

  it('fails closed when a comment points to a missing post', () => {
    const fixture = loadFixture();
    const core = validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    );
    const invalidComments = [...fixture.comments];
    invalidComments[0] = { ...invalidComments[0], post_id: 'missing-post' };

    expect(() => validateSnapshotComments(core, invalidComments)).toThrow('评论关联了不存在的帖子');
  });
});

legacyDescribe('Reddit semantic insights overlay contract', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    resetSnapshotCacheForTests();
    resetCurrentReleaseCacheForTests();
  });

  it('loads and hashes the exact public files through the browser-facing loader', async () => {
    const fetchMock = createPublicFetch();
    vi.stubGlobal('fetch', fetchMock);
    resetSnapshotCacheForTests();

    const result = await loadRedditInsights();

    expect(result.insights.headline.promoted_tags).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(8);
    expect(new Set(fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost').pathname)))
      .toEqual(new Set([
        '/data/reddit-voc/current-release.json',
        `/data/reddit-voc/${snapshotDatasetVersion}/manifest-public.json`,
        `/data/reddit-voc/${snapshotDatasetVersion}/aggregates-public.json`,
        `/data/reddit-voc/${snapshotDatasetVersion}/posts-public.json`,
        `/data/reddit-voc/${snapshotDatasetVersion}/tag-dictionary-public.json`,
        `/data/reddit-voc/${insightsDatasetVersion}/public/manifest.json`,
        `/data/reddit-voc/${insightsDatasetVersion}/public/semantic-audit.json`,
        `/data/reddit-voc/${insightsDatasetVersion}/public/insights.json`,
      ]));
  });

  it('fails closed before parsing when the pointer-bound Insights manifest changes', async () => {
    const manifestPath = `/data/reddit-voc/${insightsDatasetVersion}/public/manifest.json`;
    vi.stubGlobal('fetch', createPublicFetch({ [manifestPath]: '{' }));
    resetSnapshotCacheForTests();

    await expect(loadRedditInsights()).rejects.toThrow('发布 manifest SHA-256 不一致：insights');
  });

  it('validates the versioned public overlay and binds it to the real snapshot', () => {
    const fixture = loadFixture();
    const overlay = loadInsightsFixture();
    const core = validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    );

    const result = validateInsightsOverlay(core, overlay.manifest, overlay.audit, overlay.insights, release);

    expect(result.manifest.dataset_version).toBe(insightsDatasetVersion);
    if (!isRiskInsightsData(result.insights)) {
      throw new Error('当前发布未加载 v2 风险洞察');
    }
    expect(result.insights.risk_command_center.decision_subject).toEqual({
      brand_id: 'momcozy',
      brand_role: 'primary',
      competitors_role: 'comparison_context_only',
    });
    expect(result.insights.product_analysis.scope_order).toEqual([
      'category',
      'product_family',
      'spu_exact',
    ]);
    expect(result.insights.risk_command_center.risk_themes).toHaveLength(42);
    const firstTheme = result.insights.risk_command_center.risk_themes[0];
    expect(Object.keys(firstTheme.evidence_refs[0]).sort()).toEqual([
      'entity_id',
      'entity_type',
      'post_id',
    ]);
    expect(firstTheme).not.toHaveProperty('dictionary_default_priority');
    expect(firstTheme).not.toHaveProperty('business_impact');
  });

  it('fails closed when consumer_card is presented as a user persona', () => {
    const fixture = loadFixture();
    const overlay = loadInsightsFixture();
    const core = validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    );
    if (!isRiskInsightsData(overlay.insights)) {
      throw new Error('当前发布未加载 v2 风险洞察');
    }
    overlay.insights.interpretation_boundaries.consumer_card_is_reference_not_user_identity = false;

    expect(() => validateInsightsOverlay(core, overlay.manifest, overlay.audit, overlay.insights, release))
      .toThrow('v2 洞察解释边界异常');
  });

  it('fails closed when an unapproved tag is added to the promoted signal set', () => {
    const fixture = loadFixture();
    const overlay = loadInsightsFixture();
    const core = validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      release,
    );
    overlay.manifest.audit_summary.promoted_tag_ids = [
      ...overlay.manifest.audit_summary.promoted_tag_ids,
      'L0-SVC-010',
    ];

    expect(() => validateInsightsOverlay(core, overlay.manifest, overlay.audit, overlay.insights, release))
      .toThrow('v2 晋级标签集合不一致');
  });

  it('fails closed when the pointer-selected base version drifts from the manifest', () => {
    const fixture = loadFixture();
    const driftedRelease = validateCurrentRelease({
      ...release,
      datasets: {
        ...release.datasets,
        base: {
          ...release.datasets.base,
          dataset_version: 'reddit_voc_site_snapshot_drift_fixture',
          manifest_path: 'data/reddit-voc/reddit_voc_site_snapshot_drift_fixture/manifest-public.json',
        },
      },
    });

    expect(() => validateSnapshotCore(
      fixture.manifest,
      fixture.aggregates,
      fixture.posts,
      fixture.tagDictionary,
      driftedRelease,
    )).toThrow('快照版本与 current release 不一致');
  });
});
