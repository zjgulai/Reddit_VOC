import { useMemo } from 'react';
import MetricHelpPopover from '../../components/MetricHelpPopover';
import type { MetricHelpContent } from '../../components/MetricHelpPopover';

export type MetricDirection = 'up' | 'down' | 'flat' | 'unavailable';

export interface MetricComparisonValue {
  label: '环比' | '同比';
  display: string;
  direction: MetricDirection;
  reasonCodes: string[];
}

export interface MetricSparklinePoint {
  label: string;
  value: number | null;
}

interface MetricComparisonCardProps {
  title: string;
  value: number | null;
  displayValue?: string;
  unit?: string;
  explanation: string;
  help?: MetricHelpContent;
  comparisons: MetricComparisonValue[];
  series: MetricSparklinePoint[];
  seriesDirection?: MetricDirection;
}

const DIRECTION_STYLES: Record<MetricDirection, string> = {
  up: 'text-status-error',
  down: 'text-status-success',
  flat: 'text-foreground-muted',
  unavailable: 'text-foreground-muted',
};

function trendDirection(points: MetricSparklinePoint[]): Exclude<MetricDirection, 'unavailable'> | 'unavailable' {
  const finite = points.filter((point): point is MetricSparklinePoint & { value: number } => (
    typeof point.value === 'number' && Number.isFinite(point.value)
  ));
  if (finite.length < 2) return 'unavailable';
  if (finite.at(-1)!.value > finite[0].value) return 'up';
  if (finite.at(-1)!.value < finite[0].value) return 'down';
  return 'flat';
}

function sparklinePaths(points: MetricSparklinePoint[]): string[] {
  const finiteValues = points
    .map((point) => point.value)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (finiteValues.length < 2) return [];
  const minimum = Math.min(...finiteValues);
  const maximum = Math.max(...finiteValues);
  const range = Math.max(maximum - minimum, 1);
  const x = (index: number) => points.length === 1 ? 50 : (index / (points.length - 1)) * 100;
  const y = (value: number) => 36 - ((value - minimum) / range) * 32;
  const paths: string[] = [];
  let segment: string[] = [];

  points.forEach((point, index) => {
    if (typeof point.value === 'number' && Number.isFinite(point.value)) {
      segment.push(`${x(index).toFixed(2)},${y(point.value).toFixed(2)}`);
      return;
    }
    if (segment.length >= 2) paths.push(segment.join(' '));
    segment = [];
  });
  if (segment.length >= 2) paths.push(segment.join(' '));
  return paths;
}

function TrendSparkline({
  points,
  title,
  artifactDirection,
}: {
  points: MetricSparklinePoint[];
  title: string;
  artifactDirection?: MetricDirection;
}) {
  const direction = artifactDirection ?? trendDirection(points);
  const paths = useMemo(() => sparklinePaths(points), [points]);
  const stroke = direction === 'up' ? '#E95A76' : direction === 'down' ? '#00A86B' : '#9CA3AF';

  if (paths.length === 0) {
    return (
      <div
        className="flex h-12 w-28 items-center justify-center text-h3 text-foreground-muted"
        aria-label={`${title}趋势不可用`}
        data-trend-direction="unavailable"
      >
        —
      </div>
    );
  }

  return (
    <svg
      viewBox="0 0 100 40"
      className="h-12 w-28 overflow-visible"
      role="img"
      aria-label={`${title}${direction === 'up' ? '上升' : direction === 'down' ? '下降' : direction === 'flat' ? '持平' : '不可用'}趋势`}
      data-trend-direction={direction}
    >
      {paths.map((path, index) => (
        <polyline
          key={`${path}-${index}`}
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
  );
}

export function MetricComparisonCard({
  title,
  value,
  displayValue,
  unit,
  explanation,
  help,
  comparisons,
  series,
  seriesDirection,
}: MetricComparisonCardProps) {
  const comparisonNotes = comparisons.flatMap((comparison) => comparison.reasonCodes.map((reason) => (
    `${comparison.label}：${reason}`
  )));

  return (
    <article className="card relative p-5" data-metric-card={title}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-body-sm font-medium text-foreground-secondary">{title}</h3>
          <p className="mt-3 text-[30px] font-semibold leading-none text-foreground">
            {value === null ? '—' : (displayValue ?? value.toLocaleString('zh-CN'))}
            {value !== null && unit ? <span className="ml-1 text-body text-foreground-secondary">{unit}</span> : null}
          </p>
        </div>
        <MetricHelpPopover
          label={title}
          dialogLabel={`${title}指标说明`}
          definition={help?.definition ?? explanation}
          formula={help?.formula}
          notes={[...(help?.notes ?? []), ...comparisonNotes]}
        />
      </div>

      <div className="mt-4 flex items-end justify-between gap-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-body-sm">
          {comparisons.map((comparison) => (
            <span key={comparison.label} className={DIRECTION_STYLES[comparison.direction]}>
              <span className="text-foreground-muted">{comparison.label}</span>{' '}
              {comparison.direction === 'up' ? '▲ ' : comparison.direction === 'down' ? '▼ ' : ''}
              {comparison.display || '—'}
            </span>
          ))}
        </div>
        <TrendSparkline points={series} title={title} artifactDirection={seriesDirection} />
      </div>
    </article>
  );
}
