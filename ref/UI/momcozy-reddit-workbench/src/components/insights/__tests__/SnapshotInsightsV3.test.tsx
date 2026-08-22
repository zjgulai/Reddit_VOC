import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { beforeAll, describe, expect, it } from 'vitest';
import {
  CASEBOOK_PUBLIC_BASE_PATH,
  validatePublicCasebookData,
  validatePublicCasebookManifest,
  type RedditPublicCasebook,
} from '../../../features/redditSnapshot/casebook';
import {
  validatePublicQuarterInsightsData,
  type RedditQuarterInsightsData,
} from '../../../features/redditSnapshot/quarterInsights';
import { validateCurrentRelease } from '../../../features/redditSnapshot/release';
import { validateSnapshotCore } from '../../../features/redditSnapshot/service';
import type {
  RedditSnapshotCore,
  SnapshotAggregates,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../../../features/redditSnapshot/types';
import {
  validateV3PersonasOverlay,
  type V3PersonaAtomicCatalog,
  type V3PersonaCohortBridge,
  type V3PersonaManifest,
  type V3PersonaTagsData,
  type V3PersonasData,
  type V3RedditPersonasSnapshot,
} from '../../../features/redditSnapshot/personas';
import type { V3RedditInsightsSnapshot } from '../../../features/redditSnapshot/insightsV3';
import SnapshotInsightsV3 from '../SnapshotInsightsV3';

const publicDirectory = resolve(process.cwd(), 'public');

function readJson(directory: string, filename: string): unknown {
  return JSON.parse(readFileSync(resolve(directory, filename), 'utf8')) as unknown;
}

let baseSnapshot: RedditSnapshotCore;
let casebook: RedditPublicCasebook;
let personas: V3RedditPersonasSnapshot;
let quarterInsights: RedditQuarterInsightsData;

beforeAll(() => {
  const baseRelease = validateCurrentRelease(readJson(resolve(publicDirectory, 'data/reddit-voc'), 'current-release.json'));
  const baseDirectory = resolve(publicDirectory, 'data/reddit-voc', baseRelease.datasets.base.dataset_version);
  baseSnapshot = validateSnapshotCore(
    readJson(baseDirectory, 'manifest-public.json') as SnapshotManifest,
    readJson(baseDirectory, 'aggregates-public.json') as SnapshotAggregates,
    readJson(baseDirectory, 'posts-public.json') as SnapshotPost[],
    readJson(baseDirectory, 'tag-dictionary-public.json') as SnapshotTagDictionary,
    baseRelease,
  );

  const casebookDirectory = resolve(publicDirectory, CASEBOOK_PUBLIC_BASE_PATH.slice(1));
  casebook = {
    manifest: validatePublicCasebookManifest(readJson(casebookDirectory, 'manifest.json')),
    data: validatePublicCasebookData(readJson(casebookDirectory, 'casebook.json')),
  };

  const quarterDirectory = resolve(
    publicDirectory,
    'data/reddit-voc',
    baseRelease.datasets.quarter_insights!.dataset_version,
  );
  quarterInsights = validatePublicQuarterInsightsData(readJson(quarterDirectory, 'quarter-insights.json'));

  const personasDirectory = resolve(publicDirectory, 'data/reddit-voc', baseRelease.datasets.personas.dataset_version);
  const personasOverlay = validateV3PersonasOverlay(
    readJson(personasDirectory, 'manifest.json') as V3PersonaManifest,
    readJson(personasDirectory, 'personas.json') as V3PersonasData,
    readJson(personasDirectory, 'persona-tags.json') as V3PersonaTagsData,
    readJson(personasDirectory, 'persona-cohort-bridge.json') as V3PersonaCohortBridge,
    readJson(personasDirectory, 'persona-atomic-catalog.json') as V3PersonaAtomicCatalog,
  );
  personas = {
    ...personasOverlay,
    releaseId: baseRelease.release_id,
    avatarAssets: Object.fromEntries(personasOverlay.data.personas.map((cohort) => [
      cohort.cohort_id,
      { url: `blob:${cohort.cohort_id}`, error: null, isFallback: false },
    ])) as V3RedditPersonasSnapshot['avatarAssets'],
  };
});

const unusedLegacySnapshot = {} as V3RedditInsightsSnapshot;

function Component() {
  return (
    <SnapshotInsightsV3
      snapshot={unusedLegacySnapshot}
      baseSnapshot={baseSnapshot}
      quarterInsights={quarterInsights}
      personasState={{ data: personas, error: null, isLoading: false }}
      casebookState={{ data: casebook, error: null, isLoading: false }}
    />
  );
}

function renderPage(initialEntry = '/dashboard/insights') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Component />
    </MemoryRouter>,
  );
}

function EvidenceRoute() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(-1)}>返回洞察</button>;
}

describe('SnapshotInsightsV3 quarterly story', () => {
  it('renders the governed quarter scope, then quarter personas, then the theme story', () => {
    const { container } = renderPage();

    expect(screen.getByText('Momcozy Reddit VOC 洞察')).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(
      `${quarterInsights.period.start_date} 至 ${quarterInsights.period.end_date}`,
    )).length).toBeGreaterThan(0);
    expect(screen.getByTestId('quarter-scope-metrics')).toHaveTextContent(
      quarterInsights.counts.momcozy.post_vocs.toLocaleString('en-US'),
    );
    expect(screen.getByTestId('quarter-scope-metrics')).toHaveTextContent(
      quarterInsights.counts.momcozy.comment_context_vocs.toLocaleString('en-US'),
    );
    expect(screen.getByTestId('quarter-scope-metrics')).toHaveTextContent(
      quarterInsights.counts.momcozy.total_vocs.toLocaleString('en-US'),
    );
    expect(screen.getByText(new RegExp(
      `${quarterInsights.counts.unresolved_parent_comments.toLocaleString('en-US')} 条评论在本季度仍缺少可关联父帖`,
    ))).toBeInTheDocument();
    expect(screen.getByText(/全站待关联评论共 6,953 条/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(
      `竞品并集 ${quarterInsights.counts.competitor_union_vocs.toLocaleString('en-US')} 条，与 Momcozy 重叠 ${quarterInsights.counts.momcozy_competitor_overlap_vocs.toLocaleString('en-US')} 条`,
    ))).toBeInTheDocument();

    expect(container.querySelector('#user-personas')).not.toBeNull();
    expect(screen.getAllByTestId('persona-cohort-card')).toHaveLength(8);
    expect(screen.getByTestId('persona-distribution-chart')).toHaveTextContent(
      `${quarterInsights.personas.main_assignment_count.toLocaleString('en-US')} 次 Momcozy 画像赋值`,
    );
    expect(screen.getByTestId('persona-distribution-chart')).toHaveTextContent(
      `${quarterInsights.personas.category_context_assignment_count.toLocaleString('en-US')} 次母婴品类语境赋值`,
    );
    const shares = screen.getAllByTestId('persona-distribution-bar').map((bar) => Number(bar.getAttribute('data-share')));
    expect(shares.reduce((sum, share) => sum + share, 0)).toBeCloseTo(100, 8);

    const steps = [...container.querySelectorAll('[data-insight-story-step]')]
      .map((element) => element.getAttribute('data-insight-story-step'));
    expect(steps).toEqual(['scope', 'personas', 'themes']);
    expect(container.innerHTML).not.toContain('bg-[#17212B]');
    expect(document.body).not.toHaveTextContent('日报洞察');
    expect(document.body).not.toHaveTextContent('内容证据 cohort');
  });

  it('provides four URL-backed tabs with the fixed management narrative sequence', () => {
    renderPage('/dashboard/insights?theme=reputation');

    expect(screen.getByRole('tab', { name: /舆情与内容合规/ })).toHaveAttribute('aria-selected', 'true');
    const panel = screen.getByRole('tabpanel');
    expect(within(panel).getByText('管理问题')).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: '核心信号' })).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: 'Reddit 证据' })).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: '业务解释' })).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: 'P0 / P1 / P2 建议' })).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: '案例方法参照' })).toBeInTheDocument();
    expect(within(panel).getAllByText(
      quarterInsights.themes.reputation.automation_comments.toLocaleString('en-US'),
    ).length).toBeGreaterThan(0);
    expect(within(panel).getByText(/自动化评论 ≠ 品牌机器人/)).toBeInTheDocument();
    expect(within(panel).getByText(/不支持确认 Momcozy 使用机器人/)).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: /Momcozy 社区信任与疑似非自然推广治理事件/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /新品机会/ }));
    expect(screen.getByRole('tab', { name: /新品机会/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: '精确 SPU' })).toBeInTheDocument();
    expect(screen.getByText(/4 个受治理产品家族仍只具备家族级映射/)).toBeInTheDocument();
    expect(screen.getByText('暂无已审核案例方法参照')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /浏览案例广场候选方法/ })).toHaveAttribute('href', '/cases');

    fireEvent.click(screen.getByRole('tab', { name: /GEO 优化机会/ }));
    expect(screen.getByRole('tabpanel')).toHaveAttribute('data-theme', 'geo');
    expect(screen.getAllByText(
      quarterInsights.themes.geo.comparison_decision_posts.toLocaleString('en-US'),
    ).length).toBeGreaterThan(0);
    expect(screen.getByText(/不证明页面已被 AI 引用/)).toBeInTheDocument();
  });

  it('builds post and comment evidence links with the current release identity', () => {
    const { container } = renderPage('/dashboard/insights?theme=reputation');
    const link = container.querySelector<HTMLAnchorElement>('#quarter-theme-panel a[href*="comment="]');
    if (!link) throw new Error('expected comment-level reputation evidence link');

    const url = new URL(link.href);
    expect(url.searchParams.get('q')).toBe('t3_1uubl6f');
    expect(url.searchParams.get('post')).toBe('t3_1uubl6f');
    expect(url.searchParams.get('comment')).toBe('t1_ox33k0h');
    expect(url.searchParams.get('release')).toBe(baseSnapshot.release.release_id);
    expect(url.searchParams.get('snapshot')).toBe(baseSnapshot.manifest.dataset_version);
    expect(url.searchParams.get('from')).toBe('insights');
  });

  it('restores the selected theme after evidence navigation and browser back', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/insights?theme=geo']}>
        <Routes>
          <Route path="/dashboard/insights" element={<Component />} />
          <Route path="/dashboard/search" element={<EvidenceRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole('tab', { name: /GEO 优化机会/ })).toHaveAttribute('aria-selected', 'true');
    const evidenceLink = document.querySelector<HTMLAnchorElement>('#quarter-theme-panel a[href*="from=insights"]');
    if (!evidenceLink) throw new Error('expected GEO evidence link');
    fireEvent.click(evidenceLink);
    fireEvent.click(screen.getByRole('button', { name: '返回洞察' }));
    expect(screen.getByRole('tab', { name: /GEO 优化机会/ })).toHaveAttribute('aria-selected', 'true');
  });
});
