import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import RealReportView from '../RealReportView';
import {
  historicalCompletenessPresentation,
  ReportsContractError,
  validateV3CurrentReport,
  type V3CurrentReport,
  type V3ReportComparison,
  type V3ReportIndicator,
} from '../../../features/redditSnapshot/reports';

const HASH = 'a'.repeat(64);
const ATTESTATION_HASH = 'b'.repeat(64);

function comparison(
  display: string,
  direction: 'up' | 'down' | 'flat',
  value: string,
): V3ReportComparison {
  return {
    baseline_period_id: 'daily:2026-07-14:2026-07-15',
    baseline_status: 'available',
    direction,
    display,
    line_color: direction === 'up' ? 'red' : direction === 'down' ? 'green' : 'gray',
    profile_hashes: {
      baseline: {
        source_selection_profile_hash: HASH,
        coverage_profile_hash: HASH,
        retrieval_contract_hash: HASH,
      },
      current: {
        source_selection_profile_hash: HASH,
        coverage_profile_hash: HASH,
        retrieval_contract_hash: HASH,
      },
    },
    reason_codes: [],
    status: 'available',
    unit: 'percent',
    value,
  };
}

function zeroBaselineComparison(): V3ReportComparison {
  return {
    baseline_period_id: 'daily:2025-07-15:2025-07-16',
    baseline_status: 'available',
    direction: null,
    display: '—',
    line_color: 'gray',
    profile_hashes: {
      baseline: {
        source_selection_profile_hash: HASH,
        coverage_profile_hash: HASH,
        retrieval_contract_hash: HASH,
      },
      current: {
        source_selection_profile_hash: HASH,
        coverage_profile_hash: HASH,
        retrieval_contract_hash: HASH,
      },
    },
    reason_codes: ['baseline_zero_relative_change_undefined'],
    status: 'unavailable',
    unit: 'percent',
    value: null,
  };
}

function indicator(
  metricId: string,
  name: string,
  currentValue: string,
  pop: V3ReportComparison,
  yoy: V3ReportComparison,
  points: string[],
  direction: 'up' | 'down',
): V3ReportIndicator {
  return {
    comparison_help: {
      symbol: '?',
      text: '环比采用上一完整自然日；同比采用上年同日。不可比时显示 — 并保留原因码。',
    },
    comparisons: {
      period_over_period: pop,
      year_over_year: yoy,
    },
    current: {
      comparison_contract_proven: true,
      coverage_profile_hash: HASH,
      data_owner_coverage_attestation_sha256: ATTESTATION_HASH,
      evidence_ids: [`evidence:${metricId}`],
      grain: 'daily',
      metric_id: metricId,
      metric_policy_version: 'reddit-voc-indicator-registry-v1',
      name_cn: name,
      observed_time_precision: 'day',
      observed_voc_type: 'post_voc',
      period_complete: true,
      period_id: 'daily:2026-07-15:2026-07-16',
      retrieval_contract_hash: HASH,
      scope: 'momcozy',
      source_calendar_date: '2026-07-15',
      source_selection_profile_hash: HASH,
      status: 'available',
      time_precision: 'calendar_day_assignment_v1',
      unavailable_reason_codes: [],
      unit: 'count',
      value: currentValue,
      voc_type: 'post_voc+comment_context_voc',
      display: currentValue,
    },
    direction,
    line_color: direction === 'up' ? 'red' : 'green',
    metric_id: metricId,
    name_cn: name,
    sparkline: {
      direction,
      line_color: direction === 'up' ? 'red' : 'green',
      points: points.map((value, index) => ({ label: `07-${13 + index}`, value })),
      reason_codes: [],
      status: 'available',
      trend_claim_supported: true,
    },
  };
}

function comparableReport(): V3CurrentReport {
  return {
    artifact_role: 'latest_complete_calendar_period',
    boundaries: {
      database_write: false,
      deploy: false,
      live_send: false,
      production_unchanged: true,
      provider_call: false,
      remote_write: false,
    },
    comparison_contract_basis: 'owner_attested_dataset_scope_window',
    comparison_contract_proven: true,
    comparison_archive_path: 'archive/daily.json',
    completeness_percent: 100,
    coverage_attestation: {
      attestation_basis: 'data_owner_declaration',
      completeness_percent: 100,
      coverage_window: {
        end_calendar_date_inclusive: '2026-07-15',
        start_calendar_date_inclusive: '2013-04-28',
      },
      evidence_class: 'owner_attested_not_crawler_proof',
      scope: 'canonical_observation_pool',
      source_snapshot_id: 'reddit_add_data_20260715_v1',
    },
    data_owner_coverage_attestation_sha256: ATTESTATION_HASH,
    entry_label: '最新完整周期',
    fixture_only: false,
    grain: 'daily',
    brand_health: {
      dimension_rows: (['raw_observed', 'qualified_organic'] as const).flatMap((side) => (
        (['reputation', 'product_experience', 'recommendation_trust', 'risk_resilience'] as const).map((dimension) => ({
          comparison_side: side,
          contribution_points: '18.75',
          dimension_id: dimension,
          dimension_value: '75.00',
          grain: 'daily' as const,
          period_id: 'daily:2026-07-15:2026-07-16',
          status: 'available' as const,
          unavailable_reason_codes: [],
          unit: 'index_points' as const,
          weight_percent: '25.00' as const,
        }))
      )),
      metric_id: 'brand_health_index_v2',
      rows: [
        { comparison_side: 'raw_observed', display: '75.00', status: 'available', value: '75.00' },
        { comparison_side: 'qualified_organic', display: '75.00', status: 'available', value: '75.00' },
      ],
      scope: 'momcozy',
    },
    indicators: [
      indicator(
        'RV-BR-01',
        '帖子观察量',
        '120',
        comparison('+20%', 'up', '20'),
        comparison('+50%', 'up', '50'),
        ['80', '100', '120'],
        'up',
      ),
      indicator(
        'RV-BR-02',
        '评论观察量',
        '80',
        comparison('-20%', 'down', '-20'),
        zeroBaselineComparison(),
        ['120', '100', '80'],
        'down',
      ),
    ],
    period: {
      end: '2026-07-16',
      grain: 'daily',
      is_complete: true,
      period_id: 'daily:2026-07-15:2026-07-16',
      start: '2026-07-15',
    },
    schema_version: 'reddit_voc_report_v3',
    source: {
      coverage_attestation_sha256: ATTESTATION_HASH,
      metrics_candidate_manifest_sha256: HASH,
      metrics_input_manifest_sha256: HASH,
      metrics_validation_receipt_sha256: HASH,
      periodized_metrics_sha256: HASH,
      source_snapshot_id: 'reddit_add_data_20260715_v1',
    },
  };
}

function observedReport(): V3CurrentReport {
  const report = comparableReport();
  report.artifact_role = 'latest_closed_calendar_period_unattested';
  report.entry_label = '最新闭合周期（覆盖未证明）';
  report.comparison_contract_basis = 'not_owner_attested';
  report.comparison_contract_proven = false;
  report.completeness_percent = null;
  report.coverage_attestation = null;
  report.data_owner_coverage_attestation_sha256 = null;
  report.indicators.forEach((item) => {
    item.current.comparison_contract_proven = false;
    item.current.period_complete = false;
    item.current.data_owner_coverage_attestation_sha256 = null;
    item.direction = null;
    item.line_color = 'gray';
    Object.entries(item.comparisons).forEach(([kind, value]) => {
      if (value.status === 'unavailable') return;
      value.status = 'provisional';
      value.line_color = 'blue';
      value.comparison_basis = 'exact_period';
      value.display_label = kind === 'period_over_period' ? '环比（观测口径）' : '同比（观测口径）';
      value.reason_codes = ['owner_attestation_missing_observed_same_profile'];
    });
    item.sparkline.status = 'provisional';
    item.sparkline.line_color = 'blue';
    item.sparkline.reason_codes = ['owner_attestation_missing_observed_same_profile'];
    item.sparkline.trend_claim_supported = false;
  });
  return report;
}

describe('RealReportView V3 comparable artifact', () => {
  it('renders owner-confirmed coverage, compact artifact comparisons and red-up/green-down lines without unavailable comparisons', () => {
    const report = validateV3CurrentReport(comparableReport());
    render(<RealReportView report={report} />);

    expect(screen.getByRole('heading', { name: '历史采集完整性：数据所有者确认100%' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '持续监测' })).toBeInTheDocument();

    const risingRow = screen.getByText('帖子观察量').closest('[data-report-indicator]');
    expect(risingRow).not.toBeNull();
    expect(risingRow).toHaveTextContent('环比 ▲ +20%');
    expect(risingRow?.querySelector('.text-status-error')).toHaveTextContent('环比 ▲ +20%');
    expect(within(risingRow as HTMLElement).getByRole('img', { name: '帖子观察量上升趋势' }).querySelector('polyline'))
      .toHaveAttribute('stroke', '#E95A76');

    const fallingRow = screen.getByText('评论观察量').closest('[data-report-indicator]');
    expect(fallingRow).not.toBeNull();
    expect(fallingRow).toHaveTextContent('环比 ▼ -20%');
    expect(fallingRow?.querySelector('.text-status-success')).toHaveTextContent('环比 ▼ -20%');
    expect(within(fallingRow as HTMLElement).queryByText(/^同比\s/)).not.toBeInTheDocument();
    expect(within(fallingRow as HTMLElement).getByRole('img', { name: '评论观察量下降趋势' }).querySelector('polyline'))
      .toHaveAttribute('stroke', '#00A86B');
    expect(document.body).not.toHaveTextContent('baseline_zero_relative_change_undefined');
  });

  it('renders explicitly labeled observed comparisons and six-period trends without a completeness claim', () => {
    const report = validateV3CurrentReport(observedReport());
    render(<RealReportView report={report} />);

    expect(screen.getByRole('heading', { name: '已观测周期：同环比与趋势可用（覆盖未证明）' })).toBeInTheDocument();
    const row = screen.getByText('帖子观察量').closest('[data-report-indicator]');
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent('环比（观测口径） ▲ +20%');
    expect(row).toHaveTextContent('同比（观测口径） ▲ +50%');
    expect(row).toHaveTextContent('六期观测趋势');
    expect(within(row as HTMLElement).getByRole('img', { name: '帖子观察量六期观测上升趋势' }).querySelector('polyline'))
      .toHaveAttribute('stroke', '#3978F6');
    expect(screen.getByText(/不代表全量市场趋势/)).toBeInTheDocument();
  });

  it('rejects a positive comparison when the V3 comparison contract is not proven', () => {
    const report = comparableReport();
    report.indicators[0].current.comparison_contract_proven = false;

    expect(() => validateV3CurrentReport(report)).toThrowError(ReportsContractError);
    expect(() => validateV3CurrentReport(report)).toThrow(/缺少数据所有者 100% 完整性强绑定/);
  });

  it('rejects positive V3 directions when the report-level owner attestation is absent', () => {
    const report = comparableReport();
    report.coverage_attestation = null;

    expect(() => validateV3CurrentReport(report)).toThrowError(ReportsContractError);
    expect(() => validateV3CurrentReport(report)).toThrow(/缺少数据所有者 100% 完整性强绑定/);
  });

  it('rejects owner-confirmed wording and directions for a fixture-only V3 report', () => {
    const report = comparableReport();
    report.fixture_only = true;

    expect(historicalCompletenessPresentation(report)).toMatchObject({
      supported: false,
      label: '历史采集完整性：不可用',
    });
    expect(() => validateV3CurrentReport(report)).toThrowError(ReportsContractError);
    expect(() => validateV3CurrentReport(report)).toThrow(/缺少数据所有者 100% 完整性强绑定/);
  });

  it('allows unavailable completeness reason codes to wrap inside a mobile flex card', () => {
    const report = comparableReport();
    report.fixture_only = true;

    render(<RealReportView report={report} />);

    const heading = screen.getByRole('heading', { name: '历史采集完整性：不可用' });
    expect(heading.parentElement).toHaveClass('min-w-0');
    expect(heading.nextElementSibling).toHaveClass('break-words');
  });
});
