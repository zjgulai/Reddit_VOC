import { useMemo } from 'react';
import MetricHelpPopover from '../MetricHelpPopover';
import type {
  V3ReportComparison,
  V3ReportIndicator,
} from '../../features/redditSnapshot/reports';
import {
  formatReportIndicatorValue,
  isDisplayableReportIndicator,
  numericReportValue,
} from './reportIndicatorPresentation';

const INDICATOR_GROUPS = [
  {
    id: 'brand',
    label: '品牌脉搏',
    metricIds: ['RV-BR-01', 'RV-BR-02', 'RV-BR-03', 'RV-BR-04', 'RV-BR-05'],
  },
  {
    id: 'risk',
    label: '风险与产品',
    metricIds: ['RV-IN-01', 'RV-IN-05', 'RV-PS-02', 'RV-PS-04'],
  },
  {
    id: 'quality',
    label: '证据质量',
    metricIds: ['RV-DH-03', 'RV-DH-05'],
  },
] as const;

function displayableComparison(comparison: V3ReportComparison): boolean {
  return comparison.status !== 'unavailable'
    && comparison.value !== null
    && comparison.display !== '—';
}

function directionStyle(comparison: V3ReportComparison): string {
  if (comparison.line_color === 'blue') return 'text-blue-600';
  if (comparison.line_color === 'red') return 'text-status-error';
  if (comparison.line_color === 'green') return 'text-status-success';
  return 'text-foreground-muted';
}

function comparisonText(label: '环比' | '同比', comparison: V3ReportComparison) {
  if (!displayableComparison(comparison)) return null;
  const arrow = comparison.direction === 'up' ? '▲' : comparison.direction === 'down' ? '▼' : '•';
  const displayLabel = comparison.display_label ?? label;
  return (
    <span className={`${directionStyle(comparison)} inline-flex whitespace-nowrap`}>
      <span className="text-foreground-muted">{displayLabel}</span> {arrow} {comparison.display}
    </span>
  );
}

function sparklineSegments(indicator: V3ReportIndicator): string[] {
  if (indicator.sparkline.status === 'unavailable') return [];
  const points = indicator.sparkline.points.map((point) => numericReportValue(point.value));
  const finite = points.filter((value): value is number => value !== null);
  if (finite.length < 2) return [];
  const minimum = Math.min(...finite);
  const maximum = Math.max(...finite);
  const range = Math.max(maximum - minimum, 1);
  const x = (index: number) => points.length === 1 ? 50 : (index / (points.length - 1)) * 100;
  const y = (value: number) => 33 - ((value - minimum) / range) * 27;
  const segments: string[] = [];
  let segment: string[] = [];
  points.forEach((value, index) => {
    if (value !== null) {
      segment.push(`${x(index).toFixed(2)},${y(value).toFixed(2)}`);
      return;
    }
    if (segment.length >= 2) segments.push(segment.join(' '));
    segment = [];
  });
  if (segment.length >= 2) segments.push(segment.join(' '));
  return segments;
}

function IndicatorSparkline({ indicator }: { indicator: V3ReportIndicator }) {
  const segments = useMemo(() => sparklineSegments(indicator), [indicator]);
  if (segments.length === 0 || indicator.sparkline.direction === null) return null;
  const stroke = indicator.sparkline.line_color === 'blue'
    ? '#3978F6'
    : indicator.sparkline.direction === 'up'
    ? '#E95A76'
    : indicator.sparkline.direction === 'down'
      ? '#00A86B'
      : '#9CA3AF';
  const directionLabel = indicator.sparkline.direction === 'up'
    ? '上升'
    : indicator.sparkline.direction === 'down'
      ? '下降'
      : '持平';
  const observed = indicator.sparkline.status === 'provisional'
    && indicator.sparkline.reason_codes.includes('owner_attestation_missing_observed_same_profile');
  return (
    <div className="flex flex-col items-end gap-0.5">
      <svg
        viewBox="0 0 100 36"
        className="h-9 w-24 shrink-0 overflow-visible"
        role="img"
        aria-label={`${indicator.name_cn}${observed ? '六期观测' : ''}${directionLabel}趋势`}
        data-report-trend={indicator.sparkline.direction}
      >
        {segments.map((path) => (
          <polyline
            key={path}
            points={path}
            fill="none"
            stroke={stroke}
            strokeWidth="2.25"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <span className={observed ? 'text-tiny text-blue-600' : 'text-tiny text-foreground-muted'}>
        {observed ? '六期观测趋势' : '六期趋势'}
      </span>
    </div>
  );
}

function IndicatorRow({ indicator }: { indicator: V3ReportIndicator }) {
  const periodOverPeriod = comparisonText('环比', indicator.comparisons.period_over_period);
  const yearOverYear = comparisonText('同比', indicator.comparisons.year_over_year);
  return (
    <article
      className="grid gap-3 border-b border-border-divider/70 py-3 last:border-b-0 sm:grid-cols-[minmax(8rem,1fr)_auto_auto] sm:items-center"
      data-report-indicator={indicator.metric_id}
      data-current-value={indicator.current.value ?? undefined}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <h4 className="min-w-0 text-body-sm font-medium text-foreground">{indicator.name_cn}</h4>
          <MetricHelpPopover
            label={indicator.name_cn}
            align="left"
            definition={
              indicator.metric_id === 'RV-BR-01'
                ? `${indicator.name_cn}（${indicator.metric_id}）：本期 Momcozy 新帖 + 关联到这些新帖的评论；历史帖的新增评论不计入观察量（见"本期活动拆分"卡）。`
                : `${indicator.name_cn}（${indicator.metric_id}）来自受治理报告产物。`
            }
            notes={[
              indicator.comparison_help.text,
              ...indicator.comparisons.period_over_period.reason_codes.map((reason) => `环比：${reason}`),
              ...indicator.comparisons.year_over_year.reason_codes.map((reason) => `同比：${reason}`),
            ]}
          />
        </div>
        {(periodOverPeriod || yearOverYear || indicator.current.status === 'provisional' || !indicator.current.comparison_contract_proven) ? (
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-tiny">
            {indicator.current.status === 'provisional' || !indicator.current.comparison_contract_proven ? (
              <span className="shrink-0 whitespace-nowrap rounded-badge bg-blue-50 px-2 py-0.5 text-tiny text-blue-700">观测口径</span>
            ) : null}
            {periodOverPeriod}
            {yearOverYear}
          </div>
        ) : null}
      </div>
      <p className="text-xl font-semibold text-foreground sm:text-right">{formatReportIndicatorValue(indicator)}</p>
      <IndicatorSparkline indicator={indicator} />
    </article>
  );
}

export default function ReportIndicatorMonitor({
  indicators,
}: {
  indicators: V3ReportIndicator[];
}) {
  const visibleIndicators = indicators.filter(isDisplayableReportIndicator);
  if (visibleIndicators.length === 0) return null;
  const byId = new Map(visibleIndicators.map((indicator) => [indicator.metric_id, indicator]));
  const groupedIds = new Set<string>(INDICATOR_GROUPS.flatMap((group) => [...group.metricIds]));
  const groups = [
    ...INDICATOR_GROUPS.map((group) => ({
      id: group.id,
      label: group.label,
      indicators: group.metricIds.flatMap((metricId) => {
        const indicator = byId.get(metricId);
        return indicator ? [indicator] : [];
      }),
    })),
    {
      id: 'other',
      label: '其他可计算指标',
      indicators: visibleIndicators.filter((indicator) => !groupedIds.has(indicator.metric_id)),
    },
  ].filter((group) => group.indicators.length > 0);

  return (
    <section className="card p-5 sm:p-6" aria-labelledby="report-monitor-title">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-tiny font-semibold tracking-[0.12em] text-primary">指标追踪</p>
          <h3 id="report-monitor-title" className="mt-1 text-h3 text-foreground">持续监测</h3>
          <p className="mt-1 text-caption text-foreground-muted">同环比与六期趋势按同源同口径观测值展示；蓝色表示覆盖未获所有者确认，不代表全量市场趋势。</p>
        </div>
        <span className="rounded-badge bg-primary-light px-2.5 py-1 text-tiny font-medium text-primary">
          {visibleIndicators.length} 项可计算
        </span>
      </div>
      {/* 列数跟随分组数：只有 1 个分组时 xl:grid-cols-2 会让右半张卡整块空白。 */}
      <div
        className="mt-5 grid gap-4"
        style={{ gridTemplateColumns: `repeat(${Math.min(groups.length || 1, 3)}, minmax(0, 1fr))` }}
      >
        {groups.map((group) => (
          <section key={group.id} className="rounded-card border border-border-divider px-4 py-3">
            <h4 className="text-caption font-semibold text-foreground-secondary">{group.label}</h4>
            <div className="mt-1">
              {group.indicators.map((indicator) => (
                <IndicatorRow key={indicator.metric_id} indicator={indicator} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </section>
  );
}
