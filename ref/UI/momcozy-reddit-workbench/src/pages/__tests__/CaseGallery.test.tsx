import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { seedCases, type CaseItem } from '../../data/casesMock';
import { legacyUnverifiedCases } from '../../services/caseSearchService';
import { searchCases } from '../../services/caseService';
import {
  loadRedditCasebook,
  type PublicCasebookData,
  type PublicCasebookManifest,
} from '../../features/redditSnapshot/casebook';
import CaseGallery from '../CaseGallery';

vi.mock('../../components/Sidebar', () => ({ default: () => null }));
vi.mock('../../hooks/useAutoRefresh', () => ({
  useAutoRefresh: () => ({
    config: { enabled: false, intervalMinutes: 15 },
    setConfig: vi.fn(),
    lastRefreshAt: null,
    setLastRefreshAt: vi.fn(),
    nextRefreshIn: 0,
    isRefreshing: false,
    doRefresh: vi.fn(),
  }),
}));
vi.mock('../../services/caseService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/caseService')>();
  return { ...actual, searchCases: vi.fn() };
});
vi.mock('../../features/redditSnapshot/casebook', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../features/redditSnapshot/casebook')>();
  return { ...actual, loadRedditCasebook: vi.fn() };
});

const casebookDirectory = resolve(
  process.cwd(),
  'public/data/reddit-voc/reddit_voc_casebook_20260716_public_a1',
);
const publicCasebook = {
  manifest: JSON.parse(readFileSync(resolve(casebookDirectory, 'manifest.json'), 'utf8')) as PublicCasebookManifest,
  data: JSON.parse(readFileSync(resolve(casebookDirectory, 'casebook.json'), 'utf8')) as PublicCasebookData,
};

const approvedDelta: CaseItem = {
  id: 'delta-ui-1',
  title: '已审核增量案例',
  description: '用于验证来源徽标和版本元数据。',
  source: 'Reddit_VOC 审核台账',
  url: 'https://example.com/approved-case',
  category: 'insight',
  tags: ['审核增量'],
  date: '2026-07-15',
  sourceKind: 'approved_delta',
  verificationStatus: 'verified',
  canonicalUrl: 'https://example.com/approved-case',
  contentHash: `sha256:${'b'.repeat(64)}`,
  updatedAt: '2026-07-15T00:00:00.000Z',
  lastVerifiedAt: '2026-07-15T00:00:00.000Z',
  provenance: 'manual_review_ledger:ui-1',
};

beforeEach(() => {
  localStorage.clear();
  vi.mocked(searchCases).mockReset();
  vi.mocked(loadRedditCasebook).mockReset();
  vi.mocked(loadRedditCasebook).mockResolvedValue(publicCasebook);
});

describe('CaseGallery source truthfulness', () => {
  it('exposes the three governed business views with reference cases selected by default', async () => {
    vi.mocked(searchCases).mockResolvedValue({
      items: seedCases.slice(5, 7).map((item) => ({ ...item, verificationStatus: 'curated', defaultEligible: true })),
      total: 2,
      query: '',
      category: 'all',
      searchedAt: '2026-07-16T01:00:00.000Z',
      meta: {
        status: 'verified_index',
        datasetVersion: 'case_catalog_20260715_v1',
        generatedAt: '2026-07-15T00:00:00.000Z',
        asOf: '2026-07-15T00:00:00.000Z',
        staleAfter: '2026-08-15T00:00:00.000Z',
        freshness: 'fresh',
        seedCount: 38,
        legacyUnverifiedCount: 12,
        approvedDeltaCount: 0,
      },
    });

    render(
      <MemoryRouter initialEntries={['/cases']}>
        <CaseGallery />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('tab', { name: '参考案例' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '运营闭环' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '待复核' })).toBeInTheDocument();
    expect(screen.getByText(/人工精选参考/)).toBeInTheDocument();
    expect(screen.getByText(/人工精选.*不等同于在线内容审核或业务授权/)).toBeInTheDocument();
    expect(screen.queryByText('已核验、可直接访问')).not.toBeInTheDocument();
  });

  it('keeps the layout and distinguishes seed, legacy-unverified and approved delta', async () => {
    const items = [seedCases[0], legacyUnverifiedCases[0], approvedDelta];
    vi.mocked(searchCases).mockResolvedValue({
      items,
      total: items.length,
      query: '',
      category: 'all',
      searchedAt: '2026-07-15T01:00:00.000Z',
      meta: {
        status: 'verified_index',
        datasetVersion: 'case_catalog_20260715_v1',
        generatedAt: '2026-07-15T00:00:00.000Z',
        asOf: '2026-07-15T00:00:00.000Z',
        staleAfter: '2026-08-15T00:00:00.000Z',
        freshness: 'fresh',
        seedCount: 1,
        legacyUnverifiedCount: 1,
        approvedDeltaCount: 1,
      },
    });

    render(
      <MemoryRouter initialEntries={['/cases']}>
        <CaseGallery />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('已加载 3 条案例')).toBeInTheDocument());
    expect(screen.getByLabelText('静态案例目录：已验证')).toHaveAttribute('data-governance-status', 'verified');
    expect(screen.getByRole('status', { name: '静态案例目录时间信息' })).toHaveTextContent('生成于 2026-07-15');
    expect(screen.getByRole('status', { name: '静态案例目录时间信息' })).toHaveTextContent('复核/过期日 2026-08-15');
    expect(document.querySelector('[data-ui-severity="error"]')).not.toBeInTheDocument();
    expect(document.querySelector('[data-governance-component="data-scope-bar"]')).not.toBeInTheDocument();
    expect(screen.getAllByText('精选存量').length).toBeGreaterThan(0);
    expect(screen.getAllByText('待核验存量').length).toBeGreaterThan(0);
    expect(screen.getAllByText('已验证增量').length).toBeGreaterThan(0);
    expect(screen.getByText('精选存量: 1')).toBeInTheDocument();
    expect(screen.getByText('待核验存量: 1')).toBeInTheDocument();
    expect(screen.getByText('已验证增量: 1')).toBeInTheDocument();
    expect(screen.getByTitle('case_catalog_20260715_v1')).toHaveTextContent('索引更新:');
    expect(screen.getByText('自动检查增量')).toBeInTheDocument();
  });

  it('shows an explicit seed-only boundary when the index fails closed', async () => {
    vi.mocked(searchCases).mockResolvedValue({
      items: seedCases.filter((item) => !['geo1', 'geo2', 'geo3', 'geo4', 'in1'].includes(item.id)).map((item) => ({
        ...item,
        verificationStatus: 'curated',
        defaultEligible: true,
      })),
      total: 33,
      query: '',
      category: 'all',
      searchedAt: '2026-07-15T01:00:00.000Z',
      meta: {
        status: 'seed_only',
        datasetVersion: 'case_seed_bundled_v1',
        generatedAt: null,
        freshness: 'unknown',
        seedCount: 38,
        legacyUnverifiedCount: 0,
        approvedDeltaCount: 0,
        fallbackReason: '案例 index SHA-256 不一致',
      },
    });

    render(
      <MemoryRouter initialEntries={['/cases']}>
        <CaseGallery />
      </MemoryRouter>,
    );

    expect(await screen.findByLabelText('静态案例目录：失败')).toHaveAttribute('data-governance-status', 'failed');
    expect(screen.getByRole('status')).toHaveTextContent('当前仅使用 38 条人工 seed；本视图显示 33 条');
    expect(screen.getByRole('status')).toHaveTextContent('案例 index SHA-256 不一致');
    expect(screen.getByRole('status')).toHaveAttribute('data-ui-severity', 'error');
    expect(seedCases).toHaveLength(38);
    expect(screen.getByText('已加载 33 条案例')).toBeInTheDocument();
    expect(screen.getByText('第 1 / 3 页')).toBeInTheDocument();
    expect(screen.getByText(seedCases[5].title)).toBeInTheDocument();
    expect(screen.queryByText(seedCases[17].title)).not.toBeInTheDocument();
    expect(screen.getByText('待核验存量: 0')).toBeInTheDocument();
    expect(screen.getByText('已验证增量: 0')).toBeInTheDocument();
    expect(screen.queryByText(legacyUnverifiedCases[0].title)).not.toBeInTheDocument();
    expect(screen.queryByText(approvedDelta.title)).not.toBeInTheDocument();
  });

  it('opens the read-only five-stage operations dossier without external navigation or confirmed attribution', async () => {
    vi.mocked(searchCases).mockResolvedValue({
      items: [], total: 0, query: '', category: 'all', searchedAt: '2026-07-16T01:00:00.000Z',
      meta: {
        status: 'verified_index', datasetVersion: 'case_catalog_20260715_v1',
        generatedAt: '2026-07-15T00:00:00.000Z', freshness: 'fresh',
        seedCount: 38, legacyUnverifiedCount: 12, approvedDeltaCount: 0,
      },
    });
    render(<MemoryRouter initialEntries={['/cases']}><CaseGallery /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('tab', { name: '运营闭环' }));
    expect(await screen.findByText('Momcozy 社区信任与疑似非自然推广治理事件')).toBeInTheDocument();
    expect(screen.getByText('C2 商业关系')).toBeInTheDocument();
    expect(screen.getByText('I3 完整性风险')).toBeInTheDocument();
    expect(screen.getByText('品牌控制未确认')).toBeInTheDocument();
    expect(screen.getByText('Momcozy 社区信任与疑似非自然推广治理事件').closest('a')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '查看治理闭环' }));
    const dialog = await screen.findByRole('dialog', { name: 'Momcozy 社区信任与疑似非自然推广治理事件' });
    for (const label of ['洞察', '证据', '行动', '监测', '复盘']) {
      expect(within(dialog).getByRole('heading', { name: label })).toBeInTheDocument();
    }
    expect(within(dialog).getAllByText(/建议方案/)).toHaveLength(2);
    expect(within(dialog).getByText(/brand_control_confirmed=false/)).toBeInTheDocument();
    expect(within(dialog).queryByRole('link')).not.toBeInTheDocument();
    expect(within(dialog).queryByText('已确认品牌机器人项目')).not.toBeInTheDocument();
  });

  it('routes review-only cases to a non-navigable review view', async () => {
    const reviewItems = [
      ...seedCases
        .filter((item) => ['geo1', 'geo2', 'geo3', 'geo4', 'in1'].includes(item.id))
        .map((item) => ({ ...item, verificationStatus: 'pending' as const, defaultEligible: false })),
      ...legacyUnverifiedCases.map((item) => ({ ...item, defaultEligible: false })),
    ];
    vi.mocked(searchCases).mockImplementation(async (_query, _category, _signal, options) => ({
      items: options?.view === 'review' ? reviewItems : [],
      total: options?.view === 'review' ? reviewItems.length : 0,
      query: '', category: 'all', searchedAt: '2026-07-16T01:00:00.000Z',
      meta: {
        status: 'verified_index', datasetVersion: 'case_catalog_20260715_v1',
        generatedAt: '2026-07-15T00:00:00.000Z', freshness: 'fresh',
        seedCount: 38, legacyUnverifiedCount: 12, approvedDeltaCount: 0,
      },
    }));
    render(<MemoryRouter initialEntries={['/cases']}><CaseGallery /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('tab', { name: '待复核' }));
    await waitFor(() => expect(searchCases).toHaveBeenLastCalledWith('', 'all', expect.any(AbortSignal), { refresh: false, view: 'review' }));
    const reviewTitle = await screen.findByText(reviewItems[0].title);
    expect(reviewTitle.closest('article')).toHaveAttribute('data-external-navigation', 'disabled');
    expect(reviewTitle.closest('a')).toBeNull();
    expect(screen.getByText('已加载 17 条案例')).toBeInTheDocument();
  });
});
