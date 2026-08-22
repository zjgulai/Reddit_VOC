import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  isRiskInsightsData,
  validateInsightsOverlay,
  validateSnapshotCore,
} from '../../features/redditSnapshot/service';
import {
  isRiskReport,
  validateReportsSnapshot,
} from '../../features/redditSnapshot/reports';
import {
  validatePersonasOverlay,
} from '../../features/redditSnapshot/personas';
import {
  BRAND_HEALTH_PUBLIC_BASE_PATH,
  validatePublicBrandHealthData,
  validatePublicBrandHealthManifest,
} from '../../features/redditSnapshot/brandHealth';
import type { RedditPublicBrandHealth } from '../../features/redditSnapshot/brandHealth';
import { validateCurrentRelease } from '../../features/redditSnapshot/release';
import type {
  InsightsData,
  InsightsManifest,
  InsightsSemanticAudit,
  RedditInsightsSnapshot,
  RedditSnapshotCore,
  SnapshotAggregates,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../../features/redditSnapshot/types';
import type {
  RedditReport,
  RedditReportsSnapshot,
  ReportIndex,
  ReportManifest,
} from '../../features/redditSnapshot/reports';
import type {
  PersonaManifest,
  PersonaTagsData,
  PersonasData,
  RedditPersonasSnapshot,
} from '../../features/redditSnapshot/personas';
import { useRedditInsights } from '../../features/redditSnapshot/useRedditInsights';
import { useRedditPersonas } from '../../features/redditSnapshot/useRedditPersonas';
import { useRedditReports } from '../../features/redditSnapshot/useRedditReports';
import { useRedditSnapshot } from '../../features/redditSnapshot/useRedditSnapshot';
import { useRedditBrandHealth } from '../../features/redditSnapshot/useRedditBrandHealth';
import SnapshotDashboard from '../SnapshotDashboard';
import SnapshotAnalytics from '../SnapshotAnalytics';
import SnapshotInsights from '../SnapshotInsights';
import SnapshotReports from '../SnapshotReports';
import SnapshotSearch from '../SnapshotSearch';

vi.mock('../../features/redditSnapshot/useRedditSnapshot', () => ({
  useRedditSnapshot: vi.fn(),
}));
vi.mock('../../features/redditSnapshot/useRedditInsights', () => ({
  useRedditInsights: vi.fn(),
}));
vi.mock('../../features/redditSnapshot/useRedditReports', () => ({
  useRedditReports: vi.fn(),
}));
vi.mock('../../features/redditSnapshot/useRedditPersonas', () => ({
  useRedditPersonas: vi.fn(),
}));
vi.mock('../../features/redditSnapshot/useRedditBrandHealth', () => ({
  useRedditBrandHealth: vi.fn(),
}));

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(
  readFileSync(resolve(publicDirectory, 'data/reddit-voc/current-release.json'), 'utf8'),
));
const snapshotDirectory = resolve(publicDirectory, 'data/reddit-voc', release.datasets.base.dataset_version);
const insightsDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  release.datasets.insights.dataset_version,
  'public',
);
const reportsDirectory = resolve(
  publicDirectory,
  'data/reddit-voc',
  release.datasets.reports.dataset_version,
  'public',
);
const personasDirectory = resolve(publicDirectory, 'data/reddit-voc', release.datasets.personas.dataset_version);
const brandHealthDirectory = resolve(publicDirectory, BRAND_HEALTH_PUBLIC_BASE_PATH.slice(1));
const isV3CurrentRelease = release.datasets.insights.dataset_version.includes('_v3_');
const legacyDescribe = isV3CurrentRelease ? describe.skip : describe;

function readJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(snapshotDirectory, filename), 'utf8')) as T;
}

function readInsightsJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(insightsDirectory, filename), 'utf8')) as T;
}

function readReportJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(reportsDirectory, filename), 'utf8')) as T;
}

function readPersonaJson<T>(filename: string): T {
  return JSON.parse(readFileSync(resolve(personasDirectory, filename), 'utf8')) as T;
}

let snapshot: RedditSnapshotCore;
let insightsSnapshot: RedditInsightsSnapshot;
let reportsSnapshot: RedditReportsSnapshot;
let personasSnapshot: RedditPersonasSnapshot;
let brandHealthSnapshot: RedditPublicBrandHealth;

beforeAll(() => {
  if (isV3CurrentRelease) return;
  snapshot = validateSnapshotCore(
    readJson<SnapshotManifest>('manifest-public.json'),
    readJson<SnapshotAggregates>('aggregates-public.json'),
    readJson<SnapshotPost[]>('posts-public.json'),
    readJson<SnapshotTagDictionary>('tag-dictionary-public.json'),
    release,
  );
  insightsSnapshot = validateInsightsOverlay(
    snapshot,
    readInsightsJson<InsightsManifest>('manifest.json'),
    readInsightsJson<InsightsSemanticAudit>('semantic-audit.json'),
    readInsightsJson<InsightsData>('insights.json'),
    release,
  );
  const reportManifest = readReportJson<ReportManifest>('manifest.json');
  const reportIndex = readReportJson<ReportIndex>('report-index.json');
  const reportsByPath = Object.fromEntries(
    Object.keys(reportManifest.files)
      .filter((filename) => filename !== 'report-index.json')
      .map((filename) => [filename, readReportJson<RedditReport>(filename)]),
  );
  reportsSnapshot = validateReportsSnapshot(reportManifest, reportIndex, reportsByPath, release);
  const personaOverlay = validatePersonasOverlay(
    insightsSnapshot,
    readPersonaJson<PersonaManifest>('manifest.json'),
    readPersonaJson<PersonasData>('personas.json'),
    readPersonaJson<PersonaTagsData>('persona-tags.json'),
    release,
  );
  personasSnapshot = {
    ...personaOverlay,
    releaseId: release.release_id,
    avatarAssets: Object.fromEntries(
      personaOverlay.data.personas.map((persona) => [
        persona.persona_id,
        {
          url: `/data/reddit-voc/${release.datasets.personas.dataset_version}/${persona.avatar.asset_path}`,
          error: null,
        },
      ]),
    ),
  };
  brandHealthSnapshot = {
    manifest: validatePublicBrandHealthManifest(JSON.parse(
      readFileSync(resolve(brandHealthDirectory, 'manifest.json'), 'utf8'),
    )),
    data: validatePublicBrandHealthData(JSON.parse(
      readFileSync(resolve(brandHealthDirectory, 'brand-health.json'), 'utf8'),
    )),
  };
});

beforeEach(() => {
  vi.mocked(useRedditSnapshot).mockReturnValue({ data: snapshot, error: null, isLoading: false });
  vi.mocked(useRedditInsights).mockReturnValue({ data: insightsSnapshot, error: null, isLoading: false });
  vi.mocked(useRedditReports).mockReturnValue({
    data: reportsSnapshot,
    error: null,
    isLoading: false,
    isReloading: false,
    reload: vi.fn().mockResolvedValue(undefined),
  });
  vi.mocked(useRedditPersonas).mockReturnValue({
    data: personasSnapshot,
    error: null,
    isLoading: false,
  });
  vi.mocked(useRedditBrandHealth).mockReturnValue({
    data: brandHealthSnapshot,
    error: null,
    isLoading: false,
  });
});

legacyDescribe('real snapshot pages', () => {
  it('renders audited headline counts and explicit boundaries on Dashboard', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <SnapshotDashboard />
      </MemoryRouter>,
    );

    expect(screen.getByText('唯一 Reddit ID 帖子')).toBeInTheDocument();
    expect(release.release_id).toBe('reddit_voc_release_20260715_70a917e5bdf0');
    expect(snapshot.manifest.canonical_counts).toEqual({
      posts: 1322,
      stored_comments: 16591,
      linked_comments: 16581,
      quarantined_comments: 10,
    });
    expect(screen.getByText('1,322')).toBeInTheDocument();
    expect(screen.getByText('16,581')).toBeInTheDocument();
    expect(screen.getAllByText('16,417').length).toBeGreaterThan(0);
    expect(screen.getAllByText('隔离评论').length).toBeGreaterThan(0);
    expect(screen.queryByRole('region', { name: 'Momcozy 品牌使命横幅' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Momcozy 品牌使命' })).not.toBeInTheDocument();
    const brandHealth = screen.getByRole('region', { name: 'Momcozy 品牌健康指数' });
    expect(within(brandHealth).getByRole('img', { name: 'Momcozy 品牌健康四维雷达' })).toBeInTheDocument();
    expect(within(brandHealth).getByText('100')).toBeInTheDocument();
    expect(within(brandHealth).getByText('50.41')).toBeInTheDocument();
    expect(within(brandHealth).getAllByText('—').length).toBeGreaterThanOrEqual(3);
    expect(within(brandHealth).getByText(/未用可用维度平均替代/)).toBeInTheDocument();
    const latestTitle = [...snapshot.posts]
      .sort((left, right) => right.created_at_utc.localeCompare(left.created_at_utc))[0].title;
    expect(screen.getAllByText(latestTitle).length).toBeGreaterThan(0);
    expect(screen.getByText('同标题多 ID 组')).toBeInTheDocument();
    expect(document.querySelectorAll('[data-governance-component="data-scope-bar"]')).toHaveLength(1);
    expect(document.querySelector('[data-ui-severity="error"]')).not.toBeInTheDocument();
  });

  it.each([
    ['/dashboard', SnapshotDashboard],
    ['/dashboard/analytics', SnapshotAnalytics],
    ['/dashboard/insights', SnapshotInsights],
    ['/dashboard/reports', SnapshotReports],
    ['/dashboard/search', SnapshotSearch],
  ])('renders exactly one governed data scope bar on %s without system-error severity', (path, Page) => {
    const { container } = render(
      <MemoryRouter initialEntries={[path]}>
        <Page />
      </MemoryRouter>,
    );

    expect(container.querySelectorAll('[data-governance-component="data-scope-bar"]')).toHaveLength(1);
    expect(container.querySelector('[data-ui-severity="error"]')).not.toBeInTheDocument();
  });

  it('exposes the collector backend as safe shared external links before Settings', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <SnapshotDashboard />
      </MemoryRouter>,
    );

    const collectorLinks = screen.getAllByRole('link', { name: '最新完整日报' });
    expect(collectorLinks).toHaveLength(2);
    for (const link of collectorLinks) {
      expect(link).toHaveAttribute('href', '/dashboard/reports?period=daily');
    }
    expect(collectorLinks[0].nextElementSibling).toBe(screen.getByRole('link', { name: '设置' }));
  });

  it('derives snapshot page counts from the validated snapshot instead of release-specific copy', () => {
    const dynamicSnapshot: RedditSnapshotCore = {
      ...snapshot,
      manifest: {
        ...snapshot.manifest,
        canonical_counts: { ...snapshot.manifest.canonical_counts, posts: 321 },
      },
      aggregates: {
        ...snapshot.aggregates,
        headline: { ...snapshot.aggregates.headline, unique_posts: 321 },
      },
    };
    vi.mocked(useRedditSnapshot).mockReturnValue({ data: dynamicSnapshot, error: null, isLoading: false });

    const dashboard = render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <SnapshotDashboard />
      </MemoryRouter>,
    );
    expect(screen.getByText('已成功关联到 321 个帖子')).toBeInTheDocument();
    dashboard.unmount();

    render(
      <MemoryRouter initialEntries={['/dashboard/search']}>
        <SnapshotSearch />
      </MemoryRouter>,
    );
    expect(screen.getByText('检索融合后的 321 条唯一帖子；无 Mock 回退')).toBeInTheDocument();
  });

  it('searches the real post corpus by Reddit ID without intent-score semantics', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/search?q=t3_1d9ggl']}>
        <SnapshotSearch />
      </MemoryRouter>,
    );

    expect(screen.getByDisplayValue('t3_1d9ggl')).toBeInTheDocument();
    expect(screen.getByText('Lansinoh Manual Pump - is it really as good as its reviews? (X-post from r/breast pumps)')).toBeInTheDocument();
    expect(screen.getByText(/找到/)).toHaveTextContent('找到 1 条真实帖子');
    expect(screen.getByText('分析置信度 80%')).toBeInTheDocument();
    expect(screen.queryByText(/意向分/)).not.toBeInTheDocument();
  });

  it('renders the V2 Momcozy risk story, governed evidence, Top 6 competitors, and one persona title', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/insights']}>
        <SnapshotInsights />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: '风险治理洞察' })).toBeInTheDocument();
    expect(screen.getByText('先识别品牌风险，')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Momcozy 风险主题' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Momcozy 产品三层分析' })).toBeInTheDocument();
    const riskInsights = isRiskInsightsData(insightsSnapshot.insights)
      ? insightsSnapshot.insights
      : null;
    expect(riskInsights).not.toBeNull();
    expect(screen.getByText(`展示 8/${riskInsights!.risk_command_center.risk_themes.length}`)).toBeInTheDocument();
    expect(screen.getAllByText(/搜索仍有下一页，窗口尚未完全穷尽/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('heading', { name: '用户画像' })).toHaveLength(1);
    expect(screen.getByRole('heading', { name: '工作场景需求群' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '显式推荐表达群' })).toBeInTheDocument();
    expect(screen.getAllByText('合成插画 · 不代表真实 Reddit 用户')).toHaveLength(2);
    expect(screen.getAllByRole('img', { name: /合成.*插画，非真实用户/ })).toHaveLength(2);
    expect(screen.getByRole('heading', { name: 'C · 受控开发、测试与发布证据' })).toBeInTheDocument();
    const releaseEvidence = screen.getByRole('region', { name: '发布证据' });
    expect(within(releaseEvidence).getAllByText(release.release_id)).toHaveLength(2);
    expect(releaseEvidence.querySelector('[data-release-check="promotion"]')).toHaveAttribute('data-governance-status', 'unavailable');
    expect(releaseEvidence.querySelector('[data-release-check="acceptance"]')).toHaveAttribute('data-governance-status', 'unavailable');
    expect(releaseEvidence).not.toHaveAttribute('data-ui-severity', 'error');

    const competitorSection = screen.getByRole('heading', { name: '竞品同样本语境' }).closest('section');
    expect(competitorSection).not.toBeNull();
    expect(within(competitorSection!).getByText(`展示 6/${riskInsights!.risk_command_center.competitor_context.length}`)).toBeInTheDocument();
    for (const competitor of isRiskInsightsData(insightsSnapshot.insights)
      ? insightsSnapshot.insights.risk_command_center.competitor_context.slice(0, 6)
      : []) {
      expect(within(competitorSection!).getByText(competitor.brand_name)).toBeInTheDocument();
    }
    const seventhCompetitor = isRiskInsightsData(insightsSnapshot.insights)
      ? insightsSnapshot.insights.risk_command_center.competitor_context[6]
      : undefined;
    expect(seventhCompetitor).toBeDefined();
    expect(within(competitorSection!).queryByText(seventhCompetitor!.brand_name)).not.toBeInTheDocument();
    expect(screen.getAllByRole('link').some((link) => link.getAttribute('href')?.startsWith('/dashboard/search?q='))).toBe(true);
    for (const status of screen.getAllByText('已观察样本')) {
      expect(status).not.toHaveClass('text-status-warning');
    }
    expect(document.body).not.toHaveTextContent('dictionary_default_priority');
    expect(document.body).not.toHaveTextContent('suggested_action');
    expect(document.body).not.toHaveTextContent('search_has_next_truncates_window');
    expect(screen.queryByText('市场份额 27.3%')).not.toBeInTheDocument();
  });

  it('hides business priority when the high-priority risk threshold is unavailable', () => {
    if (!isRiskInsightsData(insightsSnapshot.insights)) {
      throw new Error('当前发布未加载 v2 风险洞察');
    }
    const riskInsights = insightsSnapshot.insights;
    const dynamicInsights: RedditInsightsSnapshot = {
      ...insightsSnapshot,
      insights: {
        ...riskInsights,
        risk_command_center: {
          ...riskInsights.risk_command_center,
          primary_kpis: {
            ...riskInsights.risk_command_center.primary_kpis,
            high_priority_risk_themes: {
              ...riskInsights.risk_command_center.primary_kpis.high_priority_risk_themes,
              value: null,
              status: 'unavailable_unfrozen_evidence_threshold',
            },
          },
        },
      },
    };
    vi.mocked(useRedditInsights).mockReturnValue({ data: dynamicInsights, error: null, isLoading: false });

    render(
      <MemoryRouter initialEntries={['/dashboard/insights']}>
        <SnapshotInsights />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('风险证据阈值待审核：不可用')).toHaveAttribute('data-governance-status', 'unavailable');
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(document.querySelector('[data-business-priority="P0-P1"]')).not.toBeInTheDocument();
  });

  it('exposes P0-P1 business priority only after the risk metric is governed', () => {
    if (!isRiskInsightsData(insightsSnapshot.insights)) {
      throw new Error('当前发布未加载 v2 风险洞察');
    }
    const riskInsights = insightsSnapshot.insights;
    const dynamicInsights: RedditInsightsSnapshot = {
      ...insightsSnapshot,
      insights: {
        ...riskInsights,
        risk_command_center: {
          ...riskInsights.risk_command_center,
          primary_kpis: {
            ...riskInsights.risk_command_center.primary_kpis,
            high_priority_risk_themes: {
              ...riskInsights.risk_command_center.primary_kpis.high_priority_risk_themes,
              value: 3,
              status: 'governed',
            },
          },
        },
      },
    };
    vi.mocked(useRedditInsights).mockReturnValue({ data: dynamicInsights, error: null, isLoading: false });

    render(
      <MemoryRouter initialEntries={['/dashboard/insights']}>
        <SnapshotInsights />
      </MemoryRouter>,
    );

    expect(screen.queryByLabelText('风险证据阈值待审核：不可用')).not.toBeInTheDocument();
    expect(document.querySelectorAll('[data-business-priority="P0-P1"]')).toHaveLength(2);
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
  });

  it('fails only the persona module closed while keeping verified Insights visible', () => {
    vi.mocked(useRedditPersonas).mockReturnValue({
      data: null,
      error: '画像 manifest SHA-256 不一致',
      isLoading: false,
    });

    render(
      <MemoryRouter initialEntries={['/dashboard/insights']}>
        <SnapshotInsights />
      </MemoryRouter>,
    );

    expect(screen.getByText('先识别品牌风险，')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Momcozy 风险主题' })).toBeInTheDocument();
    expect(screen.getByText('真实用户画像不可用，未回退 Mock')).toBeInTheDocument();
    expect(screen.getByText('画像 manifest SHA-256 不一致')).toBeInTheDocument();
    expect(screen.getByText('真实用户画像不可用，未回退 Mock').closest('section')).toHaveAttribute('data-ui-severity', 'error');
    expect(document.querySelectorAll('[data-governance-component="data-scope-bar"]')).toHaveLength(1);
    expect(screen.queryByRole('heading', { name: '工作场景需求群' })).not.toBeInTheDocument();
    expect(screen.queryByText('新手准妈妈')).not.toBeInTheDocument();
  });

  it.each([
    ['/dashboard', SnapshotDashboard, '唯一 Reddit ID 帖子'],
    ['/dashboard/analytics', SnapshotAnalytics, 'VOC 有效评论'],
    ['/dashboard/search', SnapshotSearch, '检索融合后的'],
  ])('fails the Base-dependent page closed on %s without rendering governed metrics', (path, Page, staleMetricCopy) => {
    vi.mocked(useRedditSnapshot).mockReturnValue({
      data: null,
      error: 'Base manifest SHA-256 不一致',
      isLoading: false,
    });

    const { container } = render(
      <MemoryRouter initialEntries={[path]}>
        <Page />
      </MemoryRouter>,
    );

    expect(screen.getByText('真实数据不可用，页面已停止渲染指标')).toBeInTheDocument();
    expect(screen.getByText('Base manifest SHA-256 不一致')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-ui-severity="error"]')).toHaveLength(1);
    expect(container.querySelector('[data-governance-component="data-scope-bar"]')).not.toBeInTheDocument();
    expect(screen.queryByText(staleMetricCopy, { exact: false })).not.toBeInTheDocument();
  });

  it('fails the Insights page closed while leaving no stale risk or persona metrics', () => {
    vi.mocked(useRedditInsights).mockReturnValue({
      data: null,
      error: 'Insights manifest SHA-256 不一致',
      isLoading: false,
    });

    const { container } = render(
      <MemoryRouter initialEntries={['/dashboard/insights']}>
        <SnapshotInsights />
      </MemoryRouter>,
    );

    expect(screen.getByText('Insights manifest SHA-256 不一致')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-ui-severity="error"]')).toHaveLength(1);
    expect(container.querySelector('[data-governance-component="data-scope-bar"]')).not.toBeInTheDocument();
    expect(screen.queryByText('先识别品牌风险，')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '内容证据 cohort' })).not.toBeInTheDocument();
  });

  it('fails the Reports page closed without rendering stale report metrics', () => {
    vi.mocked(useRedditReports).mockReturnValue({
      data: null,
      error: 'Reports manifest SHA-256 不一致',
      isLoading: false,
      isReloading: false,
      reload: vi.fn().mockResolvedValue(undefined),
    });

    const { container } = render(
      <MemoryRouter initialEntries={['/dashboard/reports']}>
        <SnapshotReports />
      </MemoryRouter>,
    );

    expect(screen.getByText('Reports manifest SHA-256 不一致')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-ui-severity="error"]')).toHaveLength(1);
    expect(container.querySelector('[data-governance-component="data-scope-bar"]')).not.toBeInTheDocument();
    expect(screen.queryByText('Momcozy 已观察帖子')).not.toBeInTheDocument();
  });

  it('renders V2 daily, weekly, monthly report booklets, Top 6 competitors, and separated release evidence', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/reports']}>
        <SnapshotReports />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: reportsSnapshot.index.current.daily.display_name })).toBeInTheDocument();
    expect(within(screen.getByText('Momcozy 已观察帖子').closest('.card')!).getByText('8')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '环比与同比诊断' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '帖子观察量指标说明' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '评论负面证据占比指标说明' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '本期 Momcozy 风险主题' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Momcozy 产品周期诊断' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '竞品同样本对照' })).toBeInTheDocument();
    expect(screen.getByText('展示 6/15')).toBeInTheDocument();
    expect(screen.getAllByText(/覆盖不完整/).length).toBeGreaterThan(0);
    const dailyReport = reportsSnapshot.current.daily;
    if (!isRiskReport(dailyReport)) throw new Error('当前日报未加载 v2 风险报告');
    const reportCompetitorCard = screen.getByRole('heading', { name: '竞品同样本对照' }).closest<HTMLElement>('.card');
    expect(reportCompetitorCard).not.toBeNull();
    for (const competitor of dailyReport.competitor_context.slice(0, 6)) {
      expect(within(reportCompetitorCard!).getByText(competitor.brand_name)).toBeInTheDocument();
    }
    expect(within(reportCompetitorCard!).queryByText(dailyReport.competitor_context[6].brand_name)).not.toBeInTheDocument();
    const releaseEvidence = screen.getByRole('region', { name: '发布证据' });
    expect(within(releaseEvidence).getAllByText(release.release_id)).toHaveLength(2);
    expect(releaseEvidence.querySelector('[data-release-check="promotion"]')).toHaveAttribute('data-governance-status', 'unavailable');
    expect(releaseEvidence.querySelector('[data-release-check="acceptance"]')).toHaveAttribute('data-governance-status', 'unavailable');
    expect(releaseEvidence).not.toHaveAttribute('data-ui-severity', 'error');
    expect(document.body).not.toHaveTextContent('baseline_observation_absent_under_incomplete_coverage');
    expect(screen.queryByText('紧急警报')).not.toBeInTheDocument();
    expect(screen.queryByText('刷新数据')).not.toBeInTheDocument();
    expect(screen.queryByText('推送中…')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: '报告可用周期' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '最新完整周期' })).not.toBeInTheDocument();
    expect(screen.queryByText('当前闭合期')).not.toBeInTheDocument();
    expect(screen.queryByText('闭合归档')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /周报/ }));
    expect(screen.getByRole('heading', { name: reportsSnapshot.index.current.weekly.display_name })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /月报/ }));
    expect(screen.getByRole('heading', { name: reportsSnapshot.index.current.monthly.display_name })).toBeInTheDocument();
    expect(reportsSnapshot.archive.monthly.window.comparison_status).toBe('provisional_observed_sample');
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});
