import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import AggregatePersonaPanel from '../AggregatePersonaPanel';
import type {
  RedditPersonasSnapshot,
  V3PersonaAtomicCatalog,
  V3PersonaCohortBridge,
  V3PersonaManifest,
  V3PersonaTagsData,
  V3PersonasData,
  V3RedditPersonasSnapshot,
} from '../../../features/redditSnapshot/personas';
import { validateV3PersonasOverlay } from '../../../features/redditSnapshot/personas';

const snapshot = {
  manifest: {
    dataset_version: 'reddit_voc_personas_20260714_v1',
  },
  data: {
    persona_count: 2,
    personas: [
      {
        persona_id: 'PER-SCENE-WORK-001',
        persona_kind: 'content_evidence_cohort',
        name_cn: '工作场景需求群',
        status: 'promoted',
        definition: '内容中出现并通过语义门禁的明确工作场景需求',
        source_tag_ids: ['L0-GEN-075'],
        evidence_logic: 'ANY promoted tag',
        metrics: {
          matched_entities: 57,
          matched_posts: 11,
          matched_comments: 46,
          distinct_pseudonyms: 51,
          threads: 31,
        },
        dictionary_reference: {
          consumer_card: '场景任务卡',
          aipl_node: 'L1',
          story_lines: ['场景使用冲突'],
          intent_type: ['产品咨询'],
          problem_type: ['产品性能'],
        },
        avatar: {
          asset_path: 'assets/persona-work-scenario.svg',
          asset_sha256: 'a'.repeat(64),
          media_type: 'image/svg+xml',
          width: 512,
          height: 512,
          synthetic: true,
          real_user_image: false,
          derived_from_reddit_media: false,
          identity_claim: false,
          alt_text: '工作场景需求群的合成角色插画，非真实用户',
        },
        coverage_status: 'observed_corpus_only',
        population_share_supported: false,
      },
      {
        persona_id: 'PER-BEHAVIOR-ADVOCATE-001',
        persona_kind: 'content_evidence_cohort',
        name_cn: '显式推荐表达群',
        status: 'promoted',
        definition: '内容中出现并通过语义门禁的显式推荐表达',
        source_tag_ids: ['L0-GEN-103'],
        evidence_logic: 'ANY promoted tag',
        metrics: {
          matched_entities: 52,
          matched_posts: 3,
          matched_comments: 49,
          distinct_pseudonyms: 48,
          threads: 33,
        },
        dictionary_reference: {
          consumer_card: '画像卡',
          aipl_node: 'L3',
          story_lines: ['复购准备度'],
          intent_type: ['口碑推荐'],
          problem_type: ['个性化'],
        },
        avatar: {
          asset_path: 'assets/persona-explicit-advocate.svg',
          asset_sha256: 'b'.repeat(64),
          media_type: 'image/svg+xml',
          width: 512,
          height: 512,
          synthetic: true,
          real_user_image: false,
          derived_from_reddit_media: false,
          identity_claim: false,
          alt_text: '显式推荐表达群的合成角色插画，非真实用户',
        },
        coverage_status: 'observed_corpus_only',
        population_share_supported: false,
      },
    ],
  },
  tags: {
    assignments: [
      { persona_id: 'PER-SCENE-WORK-001', post_id: 'post-work' },
      { persona_id: 'PER-BEHAVIOR-ADVOCATE-001', post_id: 'post-advocate' },
    ],
  },
  releaseId: 'reddit_voc_release_legacy_personas_fixture',
  avatarAssets: {
    'PER-SCENE-WORK-001': { url: 'blob:verified-work', error: null },
    'PER-BEHAVIOR-ADVOCATE-001': { url: null, error: '头像 SHA-256 校验失败' },
  },
} as unknown as RedditPersonasSnapshot;

const publicDirectory = resolve(process.cwd(), 'public');
const currentRelease = JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
) as {
  datasets: {
    base: { dataset_version: string };
    personas: { dataset_version: string };
  };
};
const publicBasePostIds = new Set(
  (JSON.parse(readFileSync(resolve(
    publicDirectory,
    'data/reddit-voc',
    currentRelease.datasets.base.dataset_version,
    'posts-public.json',
  ), 'utf8')) as Array<{ post_id: string; reddit_id: string }>).flatMap((post) => [post.post_id, post.reddit_id]),
);
const v3FixtureDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  currentRelease.datasets.personas.dataset_version,
);

function readV3Json<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(v3FixtureDirectory, filename), 'utf8')) as T;
}

const v3Overlay = validateV3PersonasOverlay(
  readV3Json<V3PersonaManifest>('manifest.json'),
  readV3Json<V3PersonasData>('personas.json'),
  readV3Json<V3PersonaTagsData>('persona-tags.json'),
  readV3Json<V3PersonaCohortBridge>('persona-cohort-bridge.json'),
  readV3Json<V3PersonaAtomicCatalog>('persona-atomic-catalog.json'),
);
const v3Snapshot: V3RedditPersonasSnapshot = {
  ...v3Overlay,
  releaseId: 'reddit_voc_release_personas_a4_fixture',
  avatarAssets: Object.fromEntries(v3Overlay.data.personas.map((cohort) => [
    cohort.cohort_id,
    { url: `blob:${cohort.cohort_id}`, error: null, isFallback: false },
  ])) as V3RedditPersonasSnapshot['avatarAssets'],
};

describe('AggregatePersonaPanel', () => {
  it('renders all 8 V3 cohorts with atomic references, grain splits and canonical evidence deep links', () => {
    render(
      <MemoryRouter>
        <AggregatePersonaPanel data={v3Snapshot} error={null} isLoading={false} />
      </MemoryRouter>,
    );

    const cards = screen.getAllByTestId('persona-cohort-card');
    const distributionBars = screen.getAllByTestId('persona-distribution-bar');
    const momcozyAssignments = v3Snapshot.tags.assignments.filter((assignment) => (
      assignment.scope === 'momcozy_direct' || assignment.scope === 'momcozy_multi'
    ));
    const categoryContextAssignments = v3Snapshot.tags.assignments.filter((assignment) => (
      assignment.scope === 'category_context'
    ));
    expect(cards).toHaveLength(8);
    expect(momcozyAssignments.length + categoryContextAssignments.length).toBe(v3Snapshot.tags.assignments.length);
    expect(screen.getByRole('heading', { name: '用户画像' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Momcozy 相关内容画像赋值占比' })).toBeInTheDocument();
    expect(screen.getByTestId('persona-distribution-chart')).toHaveTextContent(
      `${momcozyAssignments.length.toLocaleString('en-US')} 次 Momcozy 画像赋值`,
    );
    expect(screen.getByTestId('persona-distribution-chart')).toHaveTextContent(
      `另有 ${categoryContextAssignments.length.toLocaleString('en-US')} 次母婴品类语境赋值`,
    );
    expect(distributionBars).toHaveLength(8);
    expect(distributionBars.reduce((sum, bar) => sum + Number(bar.getAttribute('data-share')), 0)).toBeCloseTo(100, 8);
    expect(screen.getAllByRole('img', { name: /合成编辑插画，非真实用户/ })).toHaveLength(8);
    expect(screen.getByText(/8 类用户画像.*真实帖子与评论证据/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('画像原子');
    expect(document.body.textContent).not.toMatch(/L0-[A-Z]+-\d+/);
    expect(document.body).not.toHaveTextContent(v3Snapshot.manifest.snapshot_id);
    for (const cohort of v3Snapshot.data.personas) {
      const card = screen.getByRole('heading', { name: cohort.name_cn }).closest('article');
      if (!(card instanceof HTMLElement)) throw new Error(`missing persona card: ${cohort.cohort_id}`);
      const assignments = momcozyAssignments.filter((assignment) => assignment.cohort_id === cohort.cohort_id);
      const expectedMetrics = {
        画像样本: assignments.length,
        帖子: assignments.filter((assignment) => assignment.source_entity_type === 'post').length,
        评论: assignments.filter((assignment) => assignment.source_entity_type === 'comment').length,
        证据线程: new Set(assignments.map((assignment) => assignment.thread_id)).size,
        画像依据: cohort.persona_atomic_tag_count,
      };
      for (const [label, expectedValue] of Object.entries(expectedMetrics)) {
        const labelElement = within(card).getByText(label);
        expect(labelElement.previousElementSibling).toHaveTextContent(String(expectedValue));
      }
      expect(within(card).getByText(/根据 Momcozy 相关真实帖子与评论/)).toBeInTheDocument();
    }
    expect(screen.getAllByText(/不是用户人数|非用户人数/).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/PER-[A-Z]+-\d{3}/);
    const evidenceLinks = screen.getAllByRole('link', { name: '查看证据' });
    expect(evidenceLinks).toHaveLength(8);
    for (const link of evidenceLinks) {
      const evidenceUrl = new URL(link.getAttribute('href') ?? '', 'http://localhost');
      const queryPostId = evidenceUrl.searchParams.get('q');
      expect(evidenceUrl.pathname).toBe('/dashboard/search');
      expect(queryPostId).toBe(evidenceUrl.searchParams.get('post'));
      expect(publicBasePostIds.has(queryPostId ?? '')).toBe(true);
    }
    const commentEvidenceLink = evidenceLinks
      .find((link) => link.getAttribute('href')?.includes('comment=t1_'));
    expect(commentEvidenceLink).toBeDefined();
    expect(commentEvidenceLink).toHaveAttribute('href', expect.stringContaining('post=t3_'));
    expect(commentEvidenceLink).toHaveAttribute('href', expect.stringContaining('release=reddit_voc_release_personas_a4_fixture'));
    expect(commentEvidenceLink).toHaveAttribute(
      'href',
      expect.stringContaining(`snapshot=${v3Snapshot.manifest.snapshot_id}`),
    );
    expect(commentEvidenceLink).toHaveAttribute('href', expect.stringContaining('from=personas'));
  });

  it('filters V3 persona assignments to an explicit quarter allowlist without treating assignments as people', () => {
    const selected = v3Snapshot.data.personas.flatMap((cohort) => {
      const assignment = v3Snapshot.tags.assignments.find((row) => (
        row.cohort_id === cohort.cohort_id
        && (row.scope === 'momcozy_direct' || row.scope === 'momcozy_multi')
      ));
      return assignment ? [assignment.assignment_id] : [];
    });
    render(
      <MemoryRouter>
        <AggregatePersonaPanel
          data={v3Snapshot}
          error={null}
          isLoading={false}
          assignmentIds={selected}
          periodLabel="最近一个季度"
          categoryContextAssignmentCount={2_691}
          categoryContextUniqueEntityCount={1_999}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: '最近一个季度 · Momcozy 相关内容画像赋值占比' })).toBeInTheDocument();
    expect(screen.getByTestId('persona-distribution-chart')).toHaveTextContent(`${selected.length} 次 Momcozy 画像赋值`);
    expect(screen.getByTestId('persona-distribution-chart')).toHaveTextContent('2,691 次');
    expect(screen.getByTestId('persona-distribution-chart')).toHaveTextContent('1,999 个内容实体');
    expect(screen.getAllByTestId('persona-distribution-bar')
      .reduce((sum, bar) => sum + Number(bar.getAttribute('data-share')), 0)).toBeCloseTo(100, 8);
    expect(screen.getAllByText(/不是用户人数|非用户人数/).length).toBeGreaterThan(0);
  });

  it('renders evidence cohorts with verified synthetic avatar disclosure', () => {
    render(
      <MemoryRouter>
        <AggregatePersonaPanel data={snapshot} error={null} isLoading={false} />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: '用户画像' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '不同用户画像分组占比' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '工作场景需求群' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '显式推荐表达群' })).toBeInTheDocument();
    expect(screen.getAllByText('合成插画 · 不代表真实 Reddit 用户')).toHaveLength(2);
    const avatar = screen.getByRole('img', { name: /工作场景需求群的合成角色插画/ });
    expect(avatar).toHaveAttribute('src', 'blob:verified-work');
    expect(avatar).toHaveAttribute('width', '80');
    expect(avatar).toHaveAttribute('height', '80');
    expect(avatar).toHaveAttribute('loading', 'lazy');
    expect(avatar).toHaveAttribute('decoding', 'async');
    expect(screen.getByText('头像资源不可用')).toBeInTheDocument();
    expect(screen.getByText(/SHA-256/)).toBeInTheDocument();
    expect(screen.getByLabelText('头像状态：资源不可用，已使用合成占位')).toHaveAttribute('data-governance-status', 'unavailable');
    expect(document.querySelector('[data-ui-severity="error"]')).not.toBeInTheDocument();
    const legacyEvidenceLinks = screen.getAllByRole('link', { name: '查看证据' });
    expect(legacyEvidenceLinks).toHaveLength(2);
    for (const link of legacyEvidenceLinks) {
      const evidenceUrl = new URL(link.getAttribute('href') ?? '', 'http://localhost');
      expect(evidenceUrl.searchParams.get('release')).toBe(snapshot.releaseId);
      expect(evidenceUrl.searchParams.get('snapshot')).toBe(snapshot.manifest.dataset_version);
      expect(evidenceUrl.searchParams.get('from')).toBe('personas');
    }
    expect(screen.queryByText('新手准妈妈')).not.toBeInTheDocument();
    expect(screen.queryByText(/岁/)).not.toBeInTheDocument();
    expect(screen.queryByText(/设备/)).not.toBeInTheDocument();
  });

  it('replaces an image that fails browser decoding with a neutral placeholder', () => {
    render(
      <MemoryRouter>
        <AggregatePersonaPanel data={snapshot} error={null} isLoading={false} />
      </MemoryRouter>,
    );

    fireEvent.error(screen.getByRole('img', { name: /工作场景需求群的合成角色插画/ }));

    expect(screen.getAllByText('头像资源不可用')).toHaveLength(2);
    expect(screen.queryByRole('img', { name: /工作场景需求群的合成角色插画/ })).not.toBeInTheDocument();
  });

  it('fails only the persona module closed without rendering mock or stale cards', () => {
    render(
      <MemoryRouter>
        <AggregatePersonaPanel data={null} error="画像数据完整性校验失败" isLoading={false} />
      </MemoryRouter>,
    );

    expect(screen.getByText('真实用户画像不可用，未回退 Mock')).toBeInTheDocument();
    expect(screen.getByText('画像数据完整性校验失败')).toBeInTheDocument();
    expect(screen.getByText('真实用户画像不可用，未回退 Mock').closest('section')).toHaveAttribute('data-ui-severity', 'error');
    expect(screen.queryByText('工作场景需求群')).not.toBeInTheDocument();
    expect(screen.queryByText('新手准妈妈')).not.toBeInTheDocument();
  });

  it('exposes an accessible loading state', () => {
    render(
      <MemoryRouter>
        <AggregatePersonaPanel data={null} error={null} isLoading />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('正在加载用户画像')).toHaveAttribute('aria-busy', 'true');
  });

  it('renders quarter cohort counts when the persona assignment id space is disjoint', () => {
    // Production shape: the frozen persona snapshot's assignment ids are a
    // different namespace from the quarter's live ids, so the allowlist filter
    // matches nothing. The panel must read the quarter's per-cohort counts.
    const quarterCounts: Record<string, number> = {
      scenario_adapter: 320,
      service_support_seeker: 77,
      operations_troubleshooter: 91,
      fit_output_optimizer: 80,
      product_evaluator: 0,
      purchase_decision: 0,
      competitor_comparer: 187,
      recommendation_expression: 0,
    };
    const total = Object.values(quarterCounts).reduce((sum, count) => sum + count, 0);

    render(
      <MemoryRouter>
        <AggregatePersonaPanel
          data={v3Snapshot}
          error={null}
          isLoading={false}
          assignmentIds={['assignment-from-a-disjoint-namespace']}
          periodLabel="最近一个季度"
          cohortAssignmentCounts={quarterCounts}
          declaredMainAssignmentCount={total}
        />
      </MemoryRouter>,
    );

    const bars = screen.getAllByTestId('persona-distribution-bar');
    expect(bars).toHaveLength(8);
    const shares = bars.reduce((sum, bar) => sum + Number(bar.getAttribute('data-share')), 0);
    expect(shares).toBeCloseTo(100, 6);

    // The largest cohort must be the scenario_adapter count, not zero.
    const sorted = [...bars].sort(
      (left, right) => Number(right.getAttribute('data-share')) - Number(left.getAttribute('data-share')),
    );
    expect(Number(sorted[0].getAttribute('data-share'))).toBeCloseTo((320 / total) * 100, 1);

    // A cohort whose quarter count is non-zero must never render as empty. Cohorts
    // that are genuinely zero (product_evaluator here) legitimately show 0.00%.
    const barsByLabel = bars.map((bar) => bar.textContent ?? '');
    const fundedCounts = Object.values(quarterCounts).filter((count) => count > 0);
    expect(fundedCounts.length).toBeGreaterThan(0);
    const emptyBars = barsByLabel.filter((label) => /0\.00%\s*·\s*0\s*条/.test(label));
    expect(emptyBars).toHaveLength(8 - fundedCounts.length);
    expect(screen.getByText('合计 100.00%')).toBeInTheDocument();
  });

  it('does not print 合计 100.00% when the displayed sum differs from the declared quarter total', () => {
    const quarterCounts: Record<string, number> = {
      scenario_adapter: 320,
      service_support_seeker: 0,
      operations_troubleshooter: 0,
      fit_output_optimizer: 0,
      product_evaluator: 0,
      purchase_decision: 0,
      competitor_comparer: 0,
      recommendation_expression: 0,
    };

    render(
      <MemoryRouter>
        <AggregatePersonaPanel
          data={v3Snapshot}
          error={null}
          isLoading={false}
          assignmentIds={['assignment-from-a-disjoint-namespace']}
          periodLabel="最近一个季度"
          cohortAssignmentCounts={quarterCounts}
          declaredMainAssignmentCount={755}
        />
      </MemoryRouter>,
    );

    expect(screen.queryByText('合计 100.00%')).not.toBeInTheDocument();
    expect(screen.getByTestId('persona-denominator-note')).toHaveTextContent('分母不可用');
    expect(screen.getByTestId('persona-denominator-note')).toHaveTextContent('320');
    expect(screen.getByTestId('persona-denominator-note')).toHaveTextContent('755');
  });

  it('keeps post and comment splits only when the assignment count matches the quarter count', () => {
    const quarterCounts: Record<string, number> = {
      scenario_adapter: 320,
      service_support_seeker: 0,
      operations_troubleshooter: 0,
      fit_output_optimizer: 0,
      product_evaluator: 0,
      purchase_decision: 0,
      competitor_comparer: 0,
      recommendation_expression: 0,
    };

    render(
      <MemoryRouter>
        <AggregatePersonaPanel
          data={v3Snapshot}
          error={null}
          isLoading={false}
          assignmentIds={['assignment-from-a-disjoint-namespace']}
          periodLabel="最近一个季度"
          cohortAssignmentCounts={quarterCounts}
          declaredMainAssignmentCount={320}
        />
      </MemoryRouter>,
    );

    // The local assignment rows cannot be attributed to the quarter counts, so the
    // grain split is unknown and must read "—" rather than a fabricated 0.
    const scenarioCard = screen.getByRole('heading', { name: '工作与家庭场景适配者' }).closest('article');
    expect(scenarioCard).not.toBeNull();
    const splits = (scenarioCard as HTMLElement).textContent ?? '';
    expect(splits).toContain('—');
    expect(splits).toContain('320');
  });
});
