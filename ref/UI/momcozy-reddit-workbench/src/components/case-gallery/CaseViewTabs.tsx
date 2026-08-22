import { BookOpenCheck, RotateCcw, ShieldCheck } from 'lucide-react';

export type CaseGalleryView = 'reference' | 'operations' | 'review';

const views: Array<{
  id: CaseGalleryView;
  label: string;
  description: string;
  icon: typeof BookOpenCheck;
}> = [
  { id: 'reference', label: '参考案例', description: '人工精选、可直接访问', icon: BookOpenCheck },
  { id: 'operations', label: '运营闭环', description: '只读治理事件', icon: ShieldCheck },
  { id: 'review', label: '待复核', description: '不开放外部跳转', icon: RotateCcw },
];

interface CaseViewTabsProps {
  activeView: CaseGalleryView;
  onChange: (view: CaseGalleryView) => void;
}

export default function CaseViewTabs({ activeView, onChange }: CaseViewTabsProps) {
  return (
    <div className="card p-2" role="tablist" aria-label="案例广场业务视图">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {views.map((view) => {
          const Icon = view.icon;
          const selected = activeView === view.id;
          return (
            <button
              key={view.id}
              type="button"
              role="tab"
              aria-label={view.label}
              aria-selected={selected}
              onClick={() => onChange(view.id)}
              className={`rounded-card px-4 py-3 text-left transition-colors ${
                selected ? 'bg-primary-light text-primary' : 'text-foreground-secondary hover:bg-surface-tertiary'
              }`}
            >
              <span className="flex items-center gap-2 text-body-sm font-semibold">
                <Icon className="w-4 h-4" strokeWidth={1.5} />
                {view.label}
              </span>
              <span className="mt-1 block text-caption text-foreground-muted">{view.description}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
