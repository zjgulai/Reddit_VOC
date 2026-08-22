import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DataFreshnessBar from '../DataFreshnessBar';
import type { DataFreshnessEvidence } from '../freshness';

const evidence: DataFreshnessEvidence = {
  status: 'verified',
  statusLabel: '版本完整性已校验',
  recencyStatus: 'stalled',
  recencyLabel: '数据链路已停滞 17天5小时',
  coverageStatus: 'partial',
  coverageLabel: '覆盖部分完成',
  currentTime: '2026-08-09T04:43:00Z',
  currentTimeLabel: '当前北京时间',
  dataAsOfLabel: '报告数据锚点',
  dataAsOf: '2026-07-19',
  dataAsOfBasis: '来自报告 index.as_of_date',
  observationMax: '2026-07-18T22:52:13Z',
  expectedPeriodEnd: '2026-08-08T23:00:00Z',
  deadline: '2026-08-09T00:30:00Z',
  lagSeconds: 1_489_380,
  collectorRunId: 'daily_collect_20260723_0700',
  sourceBatchId: 'server_snapshot_20260706_20260723',
  releaseId: 'reddit_voc_release_20260719_v3_center_refresh_003',
  releaseGeneratedAtUtc: '2026-07-19T00:00:00Z',
  centerSnapshotId: 'reddit_voc_center_20260718_v3_canonical_v2',
  projectionDatasetVersion: 'reddit_voc_reports_20260716_v3_984feb57d25f',
  projectionGeneratedAtUtc: null,
  projectionAsOfLabel: '报告业务截至',
  projectionAsOf: '2026-07-19',
  projectionAsOfBasis: '来自报告周期',
  completenessPercent: 100,
  completenessBasis: 'data_owner_declaration',
  evidenceClass: 'owner_attested_not_crawler_proof',
  releaseWindowStart: '2026-07-17T23:00:00Z',
  releaseWindowEnd: '2026-07-18T23:00:00Z',
  coverageWindowStart: '2013-04-28',
  coverageWindowEnd: '2026-07-18',
  structuralCoverage: {
    full: 790,
    partial: 433,
    postOnly: 1,
    sourceObserved: 2311,
    unresolvedParentComments: 6953,
  },
};

describe('DataFreshnessBar', () => {
  it('shows verified release facts while keeping collector and structure debt explicit', () => {
    render(<DataFreshnessBar evidence={evidence} />);

    const bar = screen.getByRole('region', { name: '数据版本与新鲜度证据' });
    expect(bar).toHaveAttribute('data-evidence-status', 'verified');
    expect(bar).toHaveAttribute('data-recency-status', 'stalled');
    expect(bar).toHaveAttribute('data-coverage-status', 'partial');
    expect(within(bar).getByText('版本完整性已校验')).toBeInTheDocument();
    expect(within(bar).getByText('数据链路已停滞 17天5小时')).toBeInTheDocument();
    expect(within(bar).getByText('当前北京时间')).toBeInTheDocument();
    expect(within(bar).getByText('报告数据锚点')).toBeInTheDocument();

    fireEvent.click(within(bar).getByText('查看数据证据'));
    const dialog = screen.getByRole('dialog', { name: '数据证据与口径' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(within(dialog).getByText(/运行：daily_collect_20260723_0700/)).toBeInTheDocument();
    expect(within(dialog).getByText(/批次：server_snapshot_20260706_20260723/)).toBeInTheDocument();
    expect(within(dialog).getByText('数据所有者确认，非 crawler proof')).toBeInTheDocument();
    expect(within(dialog).getByText(/待父帖关联评论 6,953/)).toBeInTheDocument();
    expect(within(dialog).getByText(evidence.releaseId)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: '关闭数据证据' }));
    expect(screen.queryByRole('dialog', { name: '数据证据与口径' })).not.toBeInTheDocument();
  });

  it('renders unavailable facts as unavailable instead of deriving them from version names', () => {
    render(<DataFreshnessBar evidence={{
      ...evidence,
      status: 'unavailable',
      statusLabel: '完整性证据未提供',
      recencyStatus: 'unavailable',
      recencyLabel: '新鲜度证据未提供',
      coverageStatus: 'unavailable',
      coverageLabel: '覆盖证据未提供',
      dataAsOf: null,
      centerSnapshotId: null,
    }} />);
    const bar = screen.getByRole('region', { name: '数据版本与新鲜度证据' });
    expect(bar).toHaveAttribute('data-evidence-status', 'unavailable');
    expect(within(bar).getAllByText('未提供').length).toBeGreaterThan(0);
    expect(bar).not.toHaveTextContent('2026-07-18_v3');
  });
});
