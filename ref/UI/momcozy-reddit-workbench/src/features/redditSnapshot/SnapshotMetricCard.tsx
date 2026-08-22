import { CircleHelp } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

interface SnapshotMetricCardProps {
  icon: LucideIcon;
  value: string | number;
  label: string;
  note: string;
  tone?: 'default' | 'success' | 'warning';
  businessPriority?: string;
  help?: string;
  trend?: number[];
}

const toneStyles = {
  default: 'bg-surface-tertiary text-foreground-secondary',
  success: 'bg-status-successBg text-status-success',
  warning: 'bg-status-warningBg text-status-warning',
};

export function SnapshotMetricCard({
  icon: Icon,
  value,
  label,
  note,
  tone = 'default',
  businessPriority,
  help = note,
  trend,
}: SnapshotMetricCardProps) {
  const trendDirection = trend && trend.length > 1
    ? trend[trend.length - 1] > trend[0]
      ? 'up'
      : trend[trend.length - 1] < trend[0]
        ? 'down'
        : 'flat'
    : null;
  const trendColor = trendDirection === 'up'
    ? '#E85D75'
    : trendDirection === 'down'
      ? '#18A874'
      : '#98A2B3';
  const trendPoints = trend && trend.length > 1
    ? (() => {
        const minimum = Math.min(...trend);
        const range = Math.max(...trend) - minimum || 1;
        return trend.map((point, index) => {
          const x = (index / (trend.length - 1)) * 96 + 2;
          const y = 34 - ((point - minimum) / range) * 28;
          return `${x},${y}`;
        }).join(' ');
      })()
    : null;

  return (
    <div className="card p-6" data-business-priority={businessPriority}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className={`flex h-9 w-9 items-center justify-center rounded-icon ${toneStyles[tone]}`}>
          <Icon className="h-[18px] w-[18px]" strokeWidth={1.5} />
        </div>
        <button
          type="button"
          className="flex h-7 w-7 items-center justify-center rounded-full text-foreground-muted transition-colors hover:bg-surface-tertiary hover:text-foreground"
          aria-label={`${label}指标说明`}
          title={help}
        >
          <CircleHelp className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
        </button>
      </div>
      <div className="flex items-end justify-between gap-4">
        <p className="text-[30px] font-semibold leading-none tracking-tight text-foreground">
          {typeof value === 'number' ? value.toLocaleString('zh-CN') : value}
        </p>
        {trendPoints && (
          <svg
            viewBox="0 0 100 40"
            className="h-10 w-24 shrink-0"
            role="img"
            aria-label={`${label}${trendDirection === 'up' ? '上升' : trendDirection === 'down' ? '下降' : '持平'}趋势`}
          >
            <polyline
              points={trendPoints}
              fill="none"
              stroke={trendColor}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </div>
      <p className="mt-2 text-body-sm font-medium text-foreground">{label}</p>
      <p className="mt-1 text-tiny leading-relaxed text-foreground-muted">{note}</p>
    </div>
  );
}
