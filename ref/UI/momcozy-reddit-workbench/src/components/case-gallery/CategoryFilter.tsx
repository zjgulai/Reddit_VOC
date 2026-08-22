import { caseCategories, type CaseCategory } from '../../data/casesMock';
import { Globe, Lightbulb, TrendingUp, Briefcase } from 'lucide-react';

const categoryIcons: Record<CaseCategory, typeof Globe> = {
  geo: Globe,
  newproduct: Lightbulb,
  insight: TrendingUp,
  business: Briefcase,
};

interface CategoryFilterProps {
  activeCategory: CaseCategory | 'all';
  setActiveCategory: (cat: CaseCategory | 'all') => void;
  total: number;
  categoryCounts: Record<CaseCategory, number>;
}

export default function CategoryFilter({
  activeCategory,
  setActiveCategory,
  total,
  categoryCounts,
}: CategoryFilterProps) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button
        onClick={() => setActiveCategory('all')}
        className={`px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
          activeCategory === 'all'
            ? 'bg-primary text-white'
            : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
        }`}
      >
        全部 ({total})
      </button>
      {(Object.entries(caseCategories) as [CaseCategory, typeof caseCategories[CaseCategory]][]).map(
        ([key, cfg]) => {
          const Icon = categoryIcons[key];
          return (
            <button
              key={key}
              onClick={() => setActiveCategory(key)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
                activeCategory === key
                  ? 'bg-primary text-white'
                  : `${cfg.bg} ${cfg.color} hover:bg-surface-warm`
              }`}
            >
              <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
              {cfg.label} ({categoryCounts[key]})
            </button>
          );
        }
      )}
    </div>
  );
}
