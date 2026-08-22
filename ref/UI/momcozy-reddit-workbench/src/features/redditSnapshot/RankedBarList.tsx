interface RankedBarItem {
  label: string;
  value: number;
  detail?: string;
}

interface RankedBarListProps {
  items: RankedBarItem[];
  valueFormatter?: (value: number) => string;
  colorClass?: string;
}

export function RankedBarList({
  items,
  valueFormatter = (value) => value.toLocaleString('zh-CN'),
  colorClass = 'bg-primary',
}: RankedBarListProps) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);

  return (
    <div className="space-y-4">
      {items.map((item) => (
        <div key={item.label}>
          <div className="mb-1.5 flex items-center justify-between gap-3 text-body-sm">
            <span className="min-w-0 truncate text-foreground-secondary" title={item.label}>
              {item.label}
            </span>
            <span className="shrink-0 font-medium text-foreground">
              {valueFormatter(item.value)}
            </span>
          </div>
          {item.detail && (
            <p className="mb-1.5 break-words text-tiny leading-relaxed text-foreground-muted">
              {item.detail}
            </p>
          )}
          <div className="h-2 overflow-hidden rounded-full bg-surface-tertiary">
            <div
              className={`h-full rounded-full ${colorClass}`}
              style={{ width: `${Math.max((item.value / maxValue) * 100, 2)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
