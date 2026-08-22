import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';

interface SectionCardProps {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  action?: { label: string; onClick?: () => void };
  tag?: '运营' | '舆情' | '品牌' | '品类';
  children: ReactNode;
  className?: string;
}

const tagStyle: Record<string, string> = {
  '运营': 'bg-chart-0/10 text-chart-0',
  '舆情': 'bg-chart-1/10 text-chart-1',
  '品牌': 'bg-chart-2/10 text-chart-2',
  '品类': 'bg-chart-3/10 text-chart-3',
};

export default function SectionCard({ title, subtitle, icon, action, tag, children, className = '' }: SectionCardProps) {
  return (
    <div className={`card p-6 ${className}`}>
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-center gap-3">
          {icon && <div className="w-9 h-9 rounded-icon bg-primary-light flex items-center justify-center flex-shrink-0">{icon}</div>}
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-h3 text-foreground">{title}</h3>
              {tag && (
                <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-badge ${tagStyle[tag]}`}>
                  {tag}
                </span>
              )}
            </div>
            {subtitle && <p className="text-caption text-foreground-muted mt-0.5">{subtitle}</p>}
          </div>
        </div>
        {action && (
          <button
            onClick={action.onClick}
            className="inline-flex items-center gap-1 text-body-sm text-primary hover:text-primary-hover transition-colors"
          >
            {action.label}
            <ChevronRight className="w-4 h-4" strokeWidth={1.5} />
          </button>
        )}
      </div>
      {children}
    </div>
  );
}
