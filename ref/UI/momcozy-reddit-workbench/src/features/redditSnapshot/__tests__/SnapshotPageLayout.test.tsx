import { render, screen, within } from '@testing-library/react';
import { LayoutDashboard } from 'lucide-react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { SnapshotPageLayout } from '../SnapshotPageLayout';

describe('SnapshotPageLayout V2 navigation and width contract', () => {
  it('keeps every production workspace reachable from mobile navigation', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <SnapshotPageLayout
          icon={LayoutDashboard}
          title="概览"
          description="测试布局"
          datasetVersion="release-test"
          freshness={{
            status: 'verified',
            statusLabel: '版本完整性已校验',
            recencyStatus: 'fresh',
            recencyLabel: '数据周期已更新',
            coverageStatus: 'complete',
            coverageLabel: '覆盖完整',
            currentTime: '2026-07-19T01:00:00Z',
            currentTimeLabel: '当前北京时间',
            dataAsOfLabel: '最新观测事件',
            dataAsOf: '2026-07-18T00:00:00Z',
            dataAsOfBasis: '测试证据',
            observationMax: '2026-07-18T00:00:00Z',
            expectedPeriodEnd: '2026-07-18T23:00:00Z',
            deadline: '2026-07-19T00:30:00Z',
            lagSeconds: 90_000,
            collectorRunId: null,
            sourceBatchId: null,
            releaseId: 'reddit_voc_release_test',
            releaseGeneratedAtUtc: '2026-07-19T00:00:00Z',
            centerSnapshotId: 'reddit_voc_center_test',
            projectionDatasetVersion: 'reddit_voc_site_snapshot_test',
            projectionGeneratedAtUtc: '2026-07-18T00:00:00Z',
            projectionAsOfLabel: null,
            projectionAsOf: null,
            projectionAsOfBasis: null,
            completenessPercent: 100,
            completenessBasis: 'data_owner_declaration',
            evidenceClass: null,
            releaseWindowStart: null,
            releaseWindowEnd: null,
            coverageWindowStart: null,
            coverageWindowEnd: null,
          }}
        >
          <div>页面内容</div>
        </SnapshotPageLayout>
      </MemoryRouter>,
    );

    const navigation = screen.getByRole('navigation', { name: '移动端工作台导航' });
    const mobile = within(navigation);
    expect(navigation).toHaveClass('max-w-container');
    expect(mobile.getByRole('link', { name: '概览' })).toHaveAttribute('href', '/dashboard');
    expect(mobile.getByRole('link', { name: '报告' })).toHaveAttribute('href', '/dashboard/reports');
    expect(mobile.getByRole('link', { name: '搜索' })).toHaveAttribute('href', '/dashboard/search');
    expect(mobile.getByRole('link', { name: '分析' })).toHaveAttribute('href', '/dashboard/analytics');
    expect(mobile.getByRole('link', { name: '洞察' })).toHaveAttribute('href', '/dashboard/insights');
    expect(mobile.getByRole('link', { name: '案例广场' })).toHaveAttribute('href', '/cases');
    expect(mobile.getByRole('link', { name: '高价值内容' })).toHaveAttribute('href', '/dashboard/ugc-showcase');
    expect(mobile.getByRole('link', { name: '舆情信号' })).toHaveAttribute('href', '/dashboard/messages');
    expect(mobile.getByRole('link', { name: '指标口径' })).toHaveAttribute('href', '/dashboard/settings');
    const freshness = screen.getByRole('region', { name: '数据版本与新鲜度证据' });
    expect(freshness).toHaveClass('rounded-card');
    expect(freshness.nextElementSibling).toHaveTextContent('页面内容');
  });
});
