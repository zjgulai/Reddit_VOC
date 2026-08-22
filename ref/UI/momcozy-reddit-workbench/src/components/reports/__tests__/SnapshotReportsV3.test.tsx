import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SnapshotReports, { buildV3ExportSections } from '../../../pages/SnapshotReports';
import { validateCurrentRelease } from '../../../features/redditSnapshot/release';
import {
  validateV3CurrentReport,
  type V3BusinessHistoryIndex,
  type V3CurrentReport,
  type V3RedditReportsSnapshot,
  type V3ReportIndex,
  type V3ReportsManifest,
} from '../../../features/redditSnapshot/reports';
import { validateSnapshotCore } from '../../../features/redditSnapshot/service';
import type {
  SnapshotAggregates,
  SnapshotManifest,
  SnapshotPost,
  SnapshotTagDictionary,
} from '../../../features/redditSnapshot/types';
import { useRedditReports } from '../../../features/redditSnapshot/useRedditReports';
import { useRedditSnapshot } from '../../../features/redditSnapshot/useRedditSnapshot';
import * as reportsModule from '../../../features/redditSnapshot/reports';
import { formatReportIndicatorValue, isDisplayableReportIndicator } from '../reportIndicatorPresentation';

vi.mock('../../../features/redditSnapshot/useRedditReports', () => ({
  useRedditReports: vi.fn(),
}));
vi.mock('../../../features/redditSnapshot/useRedditSnapshot', () => ({
  useRedditSnapshot: vi.fn(),
}));

const publicDirectory = resolve(process.cwd(), 'public');
const release = validateCurrentRelease(JSON.parse(readFileSync(
  resolve(publicDirectory, 'data/reddit-voc/current-release.json'),
  'utf8',
)));
const baseDirectory = resolve(publicDirectory, 'data/reddit-voc', release.datasets.base.dataset_version);
const reportsDirectory = resolve(publicDirectory, 'data/reddit-voc', release.datasets.reports.dataset_version, 'public');

function readJson<T>(directory: string, filename: string): T {
  return JSON.parse(readFileSync(resolve(directory, filename), 'utf8')) as T;
}

const snapshot = validateSnapshotCore(
  readJson<SnapshotManifest>(baseDirectory, 'manifest-public.json'),
  readJson<SnapshotAggregates>(baseDirectory, 'aggregates-public.json'),
  readJson<SnapshotPost[]>(baseDirectory, 'posts-public.json'),
  readJson<SnapshotTagDictionary>(baseDirectory, 'tag-dictionary-public.json'),
  release,
);
const reports: V3RedditReportsSnapshot = {
  release,
  manifest: readJson<V3ReportsManifest>(reportsDirectory, 'manifest.json'),
  index: readJson<V3ReportIndex>(reportsDirectory, 'report-index.json'),
  historyIndex: readJson<V3BusinessHistoryIndex>(reportsDirectory, 'business-history-index.json'),
  current: {
    daily: validateV3CurrentReport(readJson<V3CurrentReport>(reportsDirectory, 'current/daily.json')),
    weekly: validateV3CurrentReport(readJson<V3CurrentReport>(reportsDirectory, 'current/weekly.json')),
    monthly: validateV3CurrentReport(readJson<V3CurrentReport>(reportsDirectory, 'current/monthly.json')),
  },
};
const dailyHistoryIt = reports.historyIndex?.reports.daily.length ? it : it.skip;

function EvidenceRoute() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(-1)}>返回报告</button>;
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
}

describe('SnapshotReports V3 business story', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(useRedditReports).mockReturnValue({
      data: reports,
      error: null,
      isLoading: false,
      isReloading: false,
      reload: vi.fn().mockResolvedValue(undefined),
    });
    vi.mocked(useRedditSnapshot).mockReturnValue({ data: snapshot, error: null, isLoading: false });
  });

  it('renders a deterministic monthly poster without application chrome or controls', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/dashboard/reports?period=monthly&capture=poster']}>
        <SnapshotReports />
      </MemoryRouter>,
    );

    const root = container.querySelector<HTMLElement>('[data-report-capture-root="poster"]');
    expect(root).not.toBeNull();
    expect(root).toHaveAttribute('data-report-ready', 'true');
    expect(root).toHaveAttribute('data-report-period', 'monthly');
    expect(root).toHaveAttribute('data-report-period-id', reports.current.monthly.period.period_id);
    expect(root).toHaveAttribute('data-report-release-id', reports.release.release_id);
    expect(root).toHaveAttribute('data-report-dataset-version', reports.manifest.dataset_version);
    expect(root).toHaveAttribute('data-report-data-as-of', reports.index.as_of_date);
    expect(root).toHaveAttribute('data-report-source-freshness', snapshot.release.freshness?.status ?? 'missing');
    expect(root).toHaveAttribute(
      'data-report-coverage',
      String(reports.current.monthly.completeness_percent ?? ''),
    );
    expect(root).toHaveAttribute('data-report-capture-width', '1440');
    expect(root).toHaveAttribute('data-report-capture-height', '2200');
    expect(root).toHaveStyle({ height: '2200px' });
    expect(screen.getByText('Momcozy Reddit VOC 月报')).toBeInTheDocument();
    expect(screen.getByLabelText('海报关键指标')).toBeInTheDocument();
    expect(container.querySelector('[data-snapshot-capture-layout="poster"]')).not.toBeNull();
    expect(screen.queryByRole('button', { name: /重新读取当前发布版本/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /导出/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: '选择历史报告周期' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('报告周期')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('移动端工作台导航')).not.toBeInTheDocument();

    const posterIndicators = reports.current.monthly.indicators
      .filter(isDisplayableReportIndicator)
      .slice(0, 4);
    const exportRows = buildV3ExportSections(reports.current.monthly)[1].rows;
    for (const indicator of posterIndicators) {
      const card = container.querySelector(
        `[data-report-poster-indicator="${indicator.metric_id}"]`,
      );
      expect(card).toHaveTextContent(formatReportIndicatorValue(indicator));
      expect(exportRows).toContainEqual(expect.arrayContaining([
        indicator.metric_id,
        indicator.name_cn,
        indicator.current.display,
      ]));
    }
  });

  it('fails closed on an unsupported report period instead of silently showing daily data', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/reports?period=live']}>
        <SnapshotReports />
      </MemoryRouter>,
    );

    expect(screen.getByText(/不支持的报告周期：live/)).toBeInTheDocument();
    expect(screen.getByText(/系统未回退到其他周期/)).toBeInTheDocument();
    expect(screen.queryByText('日报 · 作战指挥室')).not.toBeInTheDocument();
  });

  dailyHistoryIt('stores the selected history period in the URL and renders the verified historical report', async () => {
    const entry = reports.historyIndex!.reports.daily[0];
    const historical = validateV3CurrentReport(
      readJson<V3CurrentReport>(reportsDirectory, entry.artifact_path),
    );
    const loader = vi.spyOn(reportsModule, 'loadV3HistoricalReport').mockResolvedValue(historical);

    render(
      <MemoryRouter initialEntries={['/dashboard/reports?period=daily']}>
        <SnapshotReports />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByRole('combobox', { name: '选择历史报告周期' }), {
      target: { value: entry.period.period_id },
    });

    await waitFor(() => expect(loader).toHaveBeenCalledWith(reports, 'daily', entry.period.period_id));
    expect(screen.getByTestId('location-search')).toHaveTextContent(
      `period_id=${encodeURIComponent(entry.period.period_id)}`,
    );
    expect(screen.getByText(`${entry.period.start} · Asia/Shanghai`)).toBeInTheDocument();
  });

  dailyHistoryIt('does not expand a zero-observation historical period into lookback context', async () => {
    const entry = reports.historyIndex!.reports.daily[0];
    const historical = validateV3CurrentReport(
      readJson<V3CurrentReport>(reportsDirectory, entry.artifact_path),
    );
    const earlierMomcozyPost = snapshot.posts.find((post) => post.post_id === '1uk7ame');
    if (!earlierMomcozyPost) throw new Error('expected earlier Momcozy fixture post');
    vi.mocked(useRedditSnapshot).mockReturnValue({
      data: { ...snapshot, posts: [earlierMomcozyPost] },
      error: null,
      isLoading: false,
    });
    vi.spyOn(reportsModule, 'loadV3HistoricalReport').mockResolvedValue(historical);

    render(
      <MemoryRouter initialEntries={['/dashboard/reports?period=daily']}>
        <SnapshotReports />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByRole('combobox', { name: '选择历史报告周期' }), {
      target: { value: entry.period.period_id },
    });

    const mindMap = await screen.findByTestId('report-insight-mind-map');
    expect(mindMap).toHaveAttribute('data-evidence-count', '0');
    expect(document.body).not.toHaveTextContent('截至周期末的近 30 日背景');
  });

  dailyHistoryIt('disables export while history is pending and ignores a stale result after switching to current', async () => {
    const entry = reports.historyIndex!.reports.daily[0];
    const historical = validateV3CurrentReport(
      readJson<V3CurrentReport>(reportsDirectory, entry.artifact_path),
    );
    let resolveHistory!: (value: V3CurrentReport) => void;
    const pending = new Promise<V3CurrentReport>((resolve) => { resolveHistory = resolve; });
    vi.spyOn(reportsModule, 'loadV3HistoricalReport').mockReturnValue(pending);

    render(
      <MemoryRouter initialEntries={['/dashboard/reports?period=daily']}>
        <SnapshotReports />
      </MemoryRouter>,
    );

    const selector = screen.getByRole('combobox', { name: '选择历史报告周期' });
    fireEvent.change(selector, { target: { value: entry.period.period_id } });
    await screen.findByText('正在校验并加载所选历史报告…');
    expect(screen.getByRole('button', { name: '报告校验后可导出' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '导出' })).not.toBeInTheDocument();

    fireEvent.change(selector, { target: { value: 'current' } });
    await waitFor(() => expect(screen.getByRole('button', { name: '导出' })).toBeInTheDocument());
    await act(async () => { resolveHistory(historical); });
    expect(screen.getByText(`${reports.current.daily.period.start} 完整自然日`)).toBeInTheDocument();
    expect(screen.queryByText(`${entry.period.start} · Asia/Shanghai`)).not.toBeInTheDocument();
  });

  dailyHistoryIt('keeps export disabled when a selected history report fails integrity loading', async () => {
    const entry = reports.historyIndex!.reports.daily[0];
    vi.spyOn(reportsModule, 'loadV3HistoricalReport').mockRejectedValue(
      new Error('真实报告文件 SHA-256 不一致'),
    );

    render(
      <MemoryRouter initialEntries={['/dashboard/reports?period=daily']}>
        <SnapshotReports />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByRole('combobox', { name: '选择历史报告周期' }), {
      target: { value: entry.period.period_id },
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('真实报告文件 SHA-256 不一致');
    expect(screen.getByRole('button', { name: '报告校验后可导出' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '导出' })).not.toBeInTheDocument();
  });

  it('renders the daily management story map and only scalar metrics that have real values', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/dashboard/reports']}>
        <SnapshotReports />
      </MemoryRouter>,
    );

    const mindMap = screen.getByTestId('report-insight-mind-map');
    for (const title of ['核心信号', '驱动诊断', '业务影响', '建议行动', '持续监测']) {
      expect(within(mindMap).getByRole('heading', { name: title })).toBeInTheDocument();
    }
    expect(screen.getByText('日报 · 作战指挥室')).toBeInTheDocument();
    const dailyPath = screen.getByRole('list', { name: '日报叙事路径' });
    for (const step of ['完整自然日信号', '异常与风险', '帖子证据', '下一步行动']) {
      expect(within(dailyPath).getByText(step)).toBeInTheDocument();
    }
    expect(Number(mindMap.dataset.evidenceCount)).toBeGreaterThan(0);
    expect(within(mindMap).getByText(
      `当日治理口径 Momcozy 新帖 ${reports.current.daily.period_activity!.momcozy.new_post_count} 条、`
      + `新增评论 ${reports.current.daily.period_activity!.momcozy.new_comment_count} 条`,
    )).toBeInTheDocument();
    expect(screen.getByTestId('daily-period-activity')).toHaveTextContent('历史帖新增评论');
    expect(screen.getByRole('region', { name: '报告可用周期' })).toHaveTextContent(
      `${reports.current.daily.period.start} 完整自然日`,
    );
    const periodSelector = screen.getByRole('combobox', { name: '选择历史报告周期' });
    expect(within(periodSelector).getAllByRole('option')).toHaveLength(
      reports.historyIndex!.reports.daily.length + 1,
    );
    expect(within(periodSelector).getByRole('option', {
      name: reports.index.comparison_contract_proven ? '最新完整周期' : '最新闭合周期（覆盖未证明）',
    })).toBeInTheDocument();
    expect(screen.getByText(
      reports.index.comparison_contract_proven
        ? '环比与同比基期内置；内部比较归档不作为业务入口。'
        : reports.historyIndex!.reports.daily.length > 0
          ? '历史已观测周期可选择；同环比与六期趋势按观测口径展示，全量采集完整性与正式趋势结论仍保持关闭。'
          : '历史采集覆盖未获完整性证明；当前版本尚未发布历史已观测周期。',
    )).toBeInTheDocument();
    const renderedMetricIds = [...document.querySelectorAll<HTMLElement>('[data-report-indicator]')]
      .map((element) => element.dataset.reportIndicator);
    expect(renderedMetricIds.length).toBeGreaterThan(0);
    expect(renderedMetricIds.every((metricId) => (
      reports.current.daily.indicators.find((indicator) => indicator.metric_id === metricId)?.current.status
        !== 'unavailable'
    ))).toBe(true);
    expect(document.querySelector('[data-report-indicator="RV-BR-01"]')).toHaveTextContent(
      `${reports.current.daily.indicators.find(({ metric_id }) => metric_id === 'RV-BR-01')!.current.display}条`,
    );
    expect(document.querySelector('[data-report-indicator="RV-BR-02"]')).toBeNull();
    expect(within(mindMap).queryByText(/品牌健康度指数/)).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('显式 bot/template 排除率');
    expect(document.body).not.toHaveTextContent('产品问题排行');
    expect(document.body).not.toHaveTextContent('v3-unavailable-appendix');
    expect(document.body).not.toHaveTextContent('专项口径暂缺');
    const evidenceLink = container.querySelector<HTMLAnchorElement>('a[href*="from=reports"]');
    expect(evidenceLink).not.toBeNull();
    const evidenceUrl = new URL(evidenceLink!.href);
    expect(evidenceUrl.searchParams.get('q')).toBe(evidenceUrl.searchParams.get('post'));
    expect(evidenceUrl.searchParams.get('release')).toBe(snapshot.release.release_id);
    expect(evidenceUrl.searchParams.get('snapshot')).toBe(snapshot.manifest.dataset_version);
    expect(document.body).not.toHaveTextContent('Management brief');
    expect(document.body).not.toHaveTextContent('V3 artifact');
    expect(document.body).not.toHaveTextContent('Base 中');
  });

  it('renders the governed daily split for new posts and comments on historical threads', () => {
    const dailyWithActivity = validateV3CurrentReport({
      ...reports.current.daily,
      period_activity: {
        all_observed: {
          active_historical_post_count: 4,
          comments_on_current_period_posts: 14,
          comments_on_historical_posts: 11,
          new_comment_count: 25,
          new_post_count: 7,
          unresolved_parent_comment_count: 0,
        },
        comparison_contract_proven: reports.current.daily.period_activity!.comparison_contract_proven,
        coverage_profile_hash: reports.current.daily.indicators[0].current.coverage_profile_hash,
        data_owner_coverage_attestation_sha256: reports.current.daily.data_owner_coverage_attestation_sha256,
        grain: 'daily',
        momcozy: {
          active_historical_post_count: 2,
          comments_on_current_period_posts: 5,
          comments_on_historical_posts: 9,
          new_comment_count: 14,
          new_post_count: 2,
          unresolved_parent_comment_count: 0,
        },
        period_complete: reports.current.daily.period_activity!.period_complete,
        period_id: reports.current.daily.period.period_id,
        retrieval_contract_hash: reports.current.daily.indicators[0].current.retrieval_contract_hash,
        scope_contract: {
          all_observed: 'canonical_observation_pool',
          momcozy: 'governed_brand_fact_equals_momcozy',
        },
        source_calendar_date: reports.current.daily.period.start,
        source_selection_profile_hash: reports.current.daily.indicators[0].current.source_selection_profile_hash,
        time_precision: 'calendar_day_assignment_v1',
      },
    });
    vi.mocked(useRedditReports).mockReturnValue({
      data: {
        ...reports,
        current: { ...reports.current, daily: dailyWithActivity },
      },
      error: null,
      isLoading: false,
      isReloading: false,
      reload: vi.fn().mockResolvedValue(undefined),
    });

    render(
      <MemoryRouter initialEntries={['/dashboard/reports']}>
        <SnapshotReports />
      </MemoryRouter>,
    );

    const activity = screen.getByTestId('daily-period-activity');
    expect(within(activity).getByText('Momcozy 新帖')).toBeInTheDocument();
    expect(within(activity).getByText('Momcozy 新增评论')).toBeInTheDocument();
    expect(within(activity).getByText('历史帖新增评论')).toBeInTheDocument();
    expect(within(activity).getByText('被重新激活的历史帖')).toBeInTheDocument();
    expect(screen.getByText('当日治理口径 Momcozy 新帖 2 条、新增评论 14 条')).toBeInTheDocument();
    expect(activity).toHaveTextContent('全池 7 条');
    expect(activity).toHaveTextContent('全池 25 条');
    expect(activity).toHaveTextContent('全池 11 条');
    expect(activity).toHaveTextContent('全池 4 条');
  });

  it('switches the story, period values and decision horizon across weekly and monthly booklets', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard/reports']}>
        <SnapshotReports />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: /周报/ }));
    expect(screen.getByText('周报 · 策略雷达')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '本周结构如何变化，下周资源放在哪里' })).toBeInTheDocument();
    expect(document.querySelector('[data-report-indicator="RV-BR-01"]')).toHaveTextContent(
      `${reports.current.weekly.indicators.find(({ metric_id }) => metric_id === 'RV-BR-01')!.current.display}条`,
    );
    expect(document.body).not.toHaveTextContent('品牌健康度指数 —');
    expect(screen.getAllByText('下周计划').length).toBeGreaterThan(0);
    expect(screen.getByTestId('weekly-action-review-empty')).toHaveTextContent('尚无执行回写');
    expect(screen.getByTestId('weekly-action-review-empty')).not.toHaveTextContent('0%');
    const weeklyPath = screen.getByRole('list', { name: '周报叙事路径' });
    for (const step of ['环比与同比', '主题 / 品类驱动', '竞品差异', '下周资源']) {
      expect(within(weeklyPath).getByText(step)).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole('button', { name: /月报/ }));
    expect(screen.getByText('月报 · 战略复盘')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '本月品牌发生了什么，下一阶段如何取舍' })).toBeInTheDocument();
    expect(document.querySelector('[data-report-indicator="RV-BR-01"]')).toHaveTextContent(
      `${reports.current.monthly.indicators.find(({ metric_id }) => metric_id === 'RV-BR-01')!.current.display}条`,
    );
    expect(document.body).not.toHaveTextContent('品牌健康度指数 —');
    expect(screen.getAllByText('战略建议').length).toBeGreaterThan(0);
    const dimensions = screen.getByTestId('monthly-brand-health-dimensions');
    for (const label of ['品牌声誉', '产品体验', '推荐信任', '风险韧性']) {
      expect(within(dimensions).getByText(label)).toBeInTheDocument();
    }
    expect(dimensions).toHaveTextContent('对总指数贡献');
    const monthlyPath = screen.getByRole('list', { name: '月报叙事路径' });
    for (const step of ['品牌健康', '月环比 / 同比', '品类与 SPU', '风险与机会', '下月指标']) {
      expect(within(monthlyPath).getByText(step)).toBeInTheDocument();
    }
  });

  it('restores the selected report period after opening evidence and using browser back', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/dashboard/reports']}>
        <Routes>
          <Route path="/dashboard/reports" element={<SnapshotReports />} />
          <Route path="/dashboard/search" element={<EvidenceRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: /周报/ }));
    const evidenceLink = container.querySelector<HTMLAnchorElement>('a[href*="from=reports"]');
    if (!evidenceLink) throw new Error('expected report evidence link');
    fireEvent.click(evidenceLink);
    fireEvent.click(screen.getByRole('button', { name: '返回报告' }));

    expect(screen.getByRole('button', { name: /周报/ })).toHaveAttribute('aria-pressed', 'true');
    expect(document.querySelector('[data-report-indicator="RV-BR-01"]')).toHaveTextContent(
      `${reports.current.weekly.indicators.find(({ metric_id }) => metric_id === 'RV-BR-01')!.current.display}条`,
    );
  });
});
