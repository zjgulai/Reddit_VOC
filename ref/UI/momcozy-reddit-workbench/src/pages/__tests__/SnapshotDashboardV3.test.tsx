import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  validatePublicBrandHealthData,
  validatePublicBrandHealthManifest,
} from '../../features/redditSnapshot/brandHealth';
import {
  validatePublicQuarterInsightsData,
  validatePublicQuarterInsightsManifest,
} from '../../features/redditSnapshot/quarterInsights';
import { createBaseDataFreshness } from '../../features/redditSnapshot/freshness';
import { validateCurrentRelease } from '../../features/redditSnapshot/release';
import { validateSnapshotCore } from '../../features/redditSnapshot/service';
import type {
  SnapshotAggregates,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../../features/redditSnapshot/types';
import { useRedditBrandHealth } from '../../features/redditSnapshot/useRedditBrandHealth';
import { useRedditQuarterInsights } from '../../features/redditSnapshot/useRedditQuarterInsights';
import { useRedditSnapshot } from '../../features/redditSnapshot/useRedditSnapshot';
import { useRedditSnapshotSummary } from '../../features/redditSnapshot/useRedditSnapshotSummary';
import SnapshotDashboard from '../SnapshotDashboard';

vi.mock('../../features/redditSnapshot/useRedditSnapshot', () => ({ useRedditSnapshot: vi.fn() }));
vi.mock('../../features/redditSnapshot/useRedditSnapshotSummary', () => ({ useRedditSnapshotSummary: vi.fn() }));
vi.mock('../../features/redditSnapshot/useRedditBrandHealth', () => ({ useRedditBrandHealth: vi.fn() }));
vi.mock('../../features/redditSnapshot/useRedditQuarterInsights', () => ({ useRedditQuarterInsights: vi.fn() }));

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8')));
const snapshotDirectory = resolve(publicDirectory, 'data/reddit-voc', release.datasets.base.dataset_version);
const brandHealthDirectory = resolve(
  publicDirectory,
  release.datasets.brand_health!.manifest_path.replace(/\/manifest\.json$/, ''),
);
const quarterInsightsDirectory = resolve(
  publicDirectory,
  release.datasets.quarter_insights!.manifest_path.replace(/\/manifest\.json$/, ''),
);
const readSnapshot = <T,>(filename: string): T => JSON.parse(readFileSync(resolve(snapshotDirectory, filename), 'utf8')) as T;
const snapshot = validateSnapshotCore(
  readSnapshot<SnapshotManifest>('manifest-public.json'),
  readSnapshot<SnapshotAggregates>('aggregates-public.json'),
  readSnapshot<SnapshotPost[]>('posts-public.json'),
  readSnapshot<SnapshotTagDictionary>('tag-dictionary-public.json'),
  release,
);
const brandHealth = {
  manifest: validatePublicBrandHealthManifest(JSON.parse(readFileSync(resolve(brandHealthDirectory, 'manifest.json'), 'utf8'))),
  data: validatePublicBrandHealthData(JSON.parse(readFileSync(resolve(brandHealthDirectory, 'brand-health.json'), 'utf8'))),
};
const quarterInsights = {
  manifest: validatePublicQuarterInsightsManifest(JSON.parse(readFileSync(resolve(quarterInsightsDirectory, 'manifest.json'), 'utf8'))),
  data: validatePublicQuarterInsightsData(JSON.parse(readFileSync(resolve(quarterInsightsDirectory, 'quarter-insights.json'), 'utf8'))),
};

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="dashboard-location-search">{location.search}</output>;
}

describe('V3 dashboard management story', () => {
  beforeEach(() => {
    vi.mocked(useRedditSnapshot).mockReturnValue({ data: snapshot, error: null, isLoading: false });
    vi.mocked(useRedditSnapshotSummary).mockReturnValue({ data: snapshot, error: null, isLoading: false });
    vi.mocked(useRedditBrandHealth).mockReturnValue({ data: brandHealth, error: null, isLoading: false });
    vi.mocked(useRedditQuarterInsights).mockReturnValue({ data: quarterInsights, error: null, isLoading: false });
  });

  it('renders the executive story before the large post evidence file finishes loading', () => {
    vi.mocked(useRedditSnapshot).mockReturnValue({ data: null, error: null, isLoading: true });

    render(<MemoryRouter><SnapshotDashboard /></MemoryRouter>);

    expect(screen.getByTestId('dashboard-primary-story')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '品牌健康度指数' })).toBeInTheDocument();
    expect(screen.getAllByText('核心指标已呈现，真实帖子证据正在后台加载……').length).toBeGreaterThan(0);
    expect(screen.queryByText('正在加载 Reddit 真实数据')).not.toBeInTheDocument();
  });

  it('renders the formal brand-health score and all four finite dimensions', () => {
    const { container } = render(<MemoryRouter><SnapshotDashboard /></MemoryRouter>);

    expect(screen.queryByRole('region', { name: 'Momcozy 品牌使命横幅' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Momcozy 品牌使命' })).not.toBeInTheDocument();
    expect(container.querySelectorAll('img[src="/assets/momcozy-brand-mission-v1.png"]')).toHaveLength(0);
    expect(screen.getByRole('heading', { name: '品牌健康度指数' })).toBeInTheDocument();
    expect(screen.queryByText('Momcozy Reddit VOC 品牌观察指数')).not.toBeInTheDocument();
    const [brandRegion] = screen.getAllByRole('region', { name: 'Momcozy 品牌健康度指数' });
    expect(screen.getAllByRole('region', { name: 'Momcozy 品牌健康度指数' })).toHaveLength(1);
    expect(within(brandRegion).getByTestId('brand-health-overall-score')).toHaveTextContent(
      String(brandHealth.data.overall.score),
    );
    expect(within(brandRegion).getAllByRole('img', { name: 'Momcozy 品牌健康四维雷达' })).toHaveLength(1);
    expect(within(brandRegion).getByTestId('brand-health-radar')).toHaveAttribute('data-radar-grid', 'circle');
    expect(within(brandRegion).getByTestId('brand-health-radar-grid')).toHaveAttribute('data-grid-type', 'circle');
    expect(within(brandRegion).queryByText('—')).not.toBeInTheDocument();
    const dimensionScores = [...container.querySelectorAll<HTMLElement>('[data-dimension-score]')];
    expect(dimensionScores).toHaveLength(4);
    expect(dimensionScores.map((node) => Number(node.dataset.dimensionScore)).every(Number.isFinite)).toBe(true);
    expect(dimensionScores.map((node) => Number(node.dataset.dimensionScore))).toEqual(
      brandHealth.data.dimensions.map((dimension) => dimension.score),
    );

    fireEvent.click(within(brandRegion).getByRole('button', { name: '品牌健康度指数指标说明' }));
    const formula = within(brandRegion).getByRole('dialog', { name: '品牌健康度指数计算口径' });
    expect(formula).toHaveTextContent('总分 = round_half_up(mean(口碑健康, 产品体验, 推荐信任, 风险韧性))');
    expect(brandRegion.querySelectorAll('button[aria-expanded]')).toHaveLength(5);
    fireEvent.click(within(brandRegion).getByRole('button', { name: '产品体验指标说明' }));
    expect(within(brandRegion).getByRole('dialog', { name: '产品体验计算口径' })).toHaveTextContent('负向产品问题实体数 / 已完整分类的产品绑定实体数');
  });

  it('anchors URL-backed ranges to the latest Shanghai business date and updates real KPI values', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/dashboard?range=near1month']}>
        <SnapshotDashboard />
        <LocationProbe />
      </MemoryRouter>,
    );

    const primaryStory = screen.getByTestId('dashboard-primary-story');
    const freshness = screen.getByRole('region', { name: '数据版本与新鲜度证据' });
    const expectedFreshness = createBaseDataFreshness(snapshot);
    expect(within(freshness).getByText('季度业务截至')).toBeInTheDocument();
    expect(within(freshness).getByText(quarterInsights.data.period.end_date)).toBeInTheDocument();
    expect(freshness).toHaveAttribute('data-recency-status', expectedFreshness.recencyStatus);
    expect(within(freshness).getByText(expectedFreshness.recencyLabel)).toBeInTheDocument();
    fireEvent.click(within(freshness).getByText('查看数据证据'));
    const evidenceDialog = screen.getByRole('dialog', { name: '数据证据与口径' });
    expect(within(evidenceDialog).getByText(/投影：reddit_voc_quarter_insights_/)).toBeInTheDocument();
    expect(within(evidenceDialog).getByText(
      `运行：${release.freshness?.collector_run_id}`,
    )).toBeInTheDocument();
    const scope = within(primaryStory).getByRole('region', { name: '数据治理范围' });
    const brandHealth = within(primaryStory).getByRole('region', { name: 'Momcozy 品牌健康度指数' });
    const [story] = within(primaryStory).getAllByTestId('dashboard-insight-story');
    const actions = within(primaryStory).getByTestId('dashboard-priority-actions');
    const summary = within(primaryStory).getByTestId('dashboard-range-summary');
    expect(screen.getAllByTestId('dashboard-insight-story')).toHaveLength(1);
    expect(primaryStory.children).toHaveLength(6);
    expect(primaryStory.children[0]).toBe(scope);
    expect(primaryStory.children[1]).toBe(summary);
    expect(primaryStory.children[2]).toContainElement(brandHealth);
    expect(primaryStory.children[4]).toBe(story);
    expect(primaryStory.children[5]).toBe(actions);
    const rolling30 = quarterInsights.data.dashboard_windows.find((window) => window.id === 'rolling_30_days')!;
    expect(summary).toHaveAttribute('data-range', 'near1month');
    expect(summary).toHaveAttribute('data-anchor-date', quarterInsights.data.period.anchor_date);
    expect(summary).toHaveAttribute('data-start-date', rolling30.start_date);
    expect(container.querySelector('[data-kpi-label="Momcozy 相关帖子"]')).toHaveAttribute('data-kpi-value', String(rolling30.momcozy.post_vocs));
    expect(container.querySelector('[data-kpi-label="VOC 观察量"]')).toHaveAttribute('data-kpi-value', String(rolling30.momcozy.total_vocs));
    expect(container.querySelector('[data-kpi-label="负面 VOC 占比"]')).toHaveAttribute('data-kpi-value', String(rolling30.momcozy.negative_rate));
    expect(container.querySelector('[data-kpi-label="主要竞对语境"]')).toHaveTextContent(
      `${rolling30.top_competitor.voc_count} 条已确认品牌关联 VOC`,
    );
    expect(screen.getByRole('tab', { name: '近1月' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('dual-axis-trend-chart')).toHaveAttribute('aria-label', expect.stringContaining('帖子 VOC、评论上下文 VOC 与负面 VOC 占比双坐标趋势'));
    expect(document.querySelector('#trend-change')).toHaveAttribute('data-dashboard-window', 'rolling_30_days');
    expect(document.querySelector('#trend-change')).toHaveAttribute('data-bucket-grain', 'day');
    expect(document.querySelector('#trend-change')).toHaveAttribute('data-bucket-count', String(rolling30.buckets.length));

    fireEvent.click(screen.getByRole('tab', { name: '近1周' }));
    const rolling7 = quarterInsights.data.dashboard_windows.find((window) => window.id === 'rolling_7_days')!;
    expect(screen.getByTestId('dashboard-location-search')).toHaveTextContent('?range=near1week');
    expect(summary).toHaveAttribute('data-range', 'near1week');
    expect(summary).toHaveAttribute('data-start-date', rolling7.start_date);
    expect(container.querySelector('[data-kpi-label="Momcozy 相关帖子"]')).toHaveAttribute('data-kpi-value', String(rolling7.momcozy.post_vocs));
    expect(container.querySelector('[data-kpi-label="VOC 观察量"]')).toHaveAttribute('data-kpi-value', String(rolling7.momcozy.total_vocs));
    if (rolling7.momcozy.negative_rate === null) {
      expect(container.querySelector('[data-kpi-label="负面 VOC 占比"]')).toHaveTextContent('—');
    } else {
      expect(container.querySelector('[data-kpi-label="负面 VOC 占比"]')).toHaveAttribute('data-kpi-value', String(rolling7.momcozy.negative_rate));
    }
    expect(document.querySelector('#trend-change')).toHaveAttribute('data-dashboard-window', 'rolling_7_days');
    expect(document.querySelector('#trend-change')).toHaveAttribute('data-bucket-count', String(rolling7.buckets.length));

    fireEvent.click(screen.getByRole('tab', { name: '近半年' }));
    const rolling183 = quarterInsights.data.dashboard_windows.find((window) => window.id === 'rolling_183_days')!;
    expect(screen.getByTestId('dashboard-location-search')).toHaveTextContent('?range=near6months');
    expect(summary).toHaveAttribute('data-start-date', rolling183.start_date);
    expect(container.querySelector('[data-kpi-label="Momcozy 相关帖子"]')).toHaveAttribute('data-kpi-value', String(rolling183.momcozy.post_vocs));
    expect(container.querySelector('[data-kpi-label="VOC 观察量"]')).toHaveAttribute('data-kpi-value', String(rolling183.momcozy.total_vocs));
    expect(container.querySelector('[data-kpi-label="负面 VOC 占比"]')).toHaveAttribute('data-kpi-value', String(rolling183.momcozy.negative_rate));
    expect(document.querySelector('#trend-change')).toHaveAttribute('data-dashboard-window', 'rolling_183_days');
    expect(document.querySelector('#trend-change')).toHaveAttribute('data-bucket-grain', 'month');
    expect(document.querySelector('#trend-change')).toHaveAttribute('data-bucket-count', String(rolling183.buckets.length));

    fireEvent.click(screen.getByRole('button', { name: 'VOC 观察量指标说明' }));
    const vocFormula = screen.getByRole('dialog', { name: 'VOC 观察量计算口径' });
    expect(vocFormula).toHaveTextContent('promoted entity_brand_fact.brand_id = "momcozy"');
    expect(vocFormula).toHaveTextContent('帖子与评论均按各自内容实体事件日落窗');
    expect(vocFormula).not.toHaveTextContent('评论按父帖业务日落窗');
  });

  it('季度正式投影加载中或失效时停止渲染指标', () => {
    vi.mocked(useRedditQuarterInsights).mockReturnValue({ data: null, error: null, isLoading: true });
    const { rerender } = render(<MemoryRouter><SnapshotDashboard /></MemoryRouter>);
    expect(screen.getByText('加载真实数据')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-range-summary')).not.toBeInTheDocument();

    vi.mocked(useRedditQuarterInsights).mockReturnValue({ data: null, error: '季度投影校验失败', isLoading: false });
    rerender(<MemoryRouter><SnapshotDashboard /></MemoryRouter>);
    expect(screen.getByText('季度投影校验失败')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-range-summary')).not.toBeInTheDocument();
  });

  it('compresses four decision themes and the report entry into one executive digest without restoring the mission image', () => {
    render(<MemoryRouter><SnapshotDashboard /></MemoryRouter>);

    const story = screen.getByTestId('dashboard-insight-story');
    expect(within(story).getByRole('heading', { name: '四类经营决策入口' })).toBeInTheDocument();
    expect(within(story).getByRole('link', { name: /进入日报 \/ 周报 \/ 月报/ })).toHaveAttribute('href', '/dashboard/reports');
    expect(within(story).getByRole('link', { name: /查看痛点证据/ })).toHaveAttribute('href', '/dashboard/insights?theme=pain');
    expect(within(story).getByRole('link', { name: /查看风险与合规/ })).toHaveAttribute('href', '/dashboard/insights?theme=reputation');
    expect(within(story).getByRole('link', { name: /查看需求机会/ })).toHaveAttribute('href', '/dashboard/insights?theme=new-product');
    expect(within(story).getByRole('link', { name: /查看 GEO 问题库/ })).toHaveAttribute('href', '/dashboard/insights?theme=geo');
    expect(screen.getByRole('heading', { name: '趋势变化' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '关键驱动' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '风险焦点' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '品类机会' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '竞品参照' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '优先行动' })).toBeInTheDocument();
    expect(screen.getAllByText('操作与可靠性').length).toBeGreaterThan(0);
    expect(screen.getAllByText('自动化评论').length).toBeGreaterThan(0);
    expect(screen.getAllByText('M5 Smart 产品家族').length).toBeGreaterThan(0);
    expect(screen.getAllByText('M6 吸奶器').length).toBeGreaterThan(0);
    expect(screen.getByText(new RegExp(`${quarterInsights.data.themes.geo.comparison_decision_posts} 条比较 \\/ 决策问题`))).toBeInTheDocument();
    expect(screen.getByText(/^Momcozy 为主干；竞对/)).toHaveTextContent('不是市场份额');
    expect(screen.queryByText(/governed|entity-brand facts|公开 Base/)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Momcozy 品牌使命横幅' })).not.toBeInTheDocument();
  });
});
