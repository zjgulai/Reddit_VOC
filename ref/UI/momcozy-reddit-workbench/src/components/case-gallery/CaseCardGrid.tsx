import {
  ExternalLink,
  Calendar,
  Globe,
  Lightbulb,
  TrendingUp,
  Briefcase,
  Database,
  BadgeCheck,
  History,
} from 'lucide-react';
import { caseCategories, type CaseCategory, type CaseItem } from '../../data/casesMock';

const categoryIcons: Record<CaseCategory, typeof Globe> = {
  geo: Globe,
  newproduct: Lightbulb,
  insight: TrendingUp,
  business: Briefcase,
};

interface CaseCardGridProps {
  groupedResults: [CaseCategory, typeof caseCategories[CaseCategory]][];
  results: CaseItem[];
  searchQuery: string;
  handleTagClick: (tag: string) => void;
  allowExternalNavigation?: boolean;
}

export default function CaseCardGrid({
  groupedResults,
  results,
  searchQuery,
  handleTagClick,
  allowExternalNavigation = true,
}: CaseCardGridProps) {
  return (
    <div className="space-y-12">
      {groupedResults.map(([catKey, catCfg]) => {
        const catCases = results.filter((c) => c.category === catKey);
        if (catCases.length === 0) return null;
        const Icon = categoryIcons[catKey];

        return (
          <section key={catKey}>
            <div className="flex items-center gap-3 mb-6">
              <div className={`w-10 h-10 rounded-icon flex items-center justify-center ${catCfg.bg}`}>
                <Icon className={`w-5 h-5 ${catCfg.color}`} strokeWidth={1.5} />
              </div>
              <div>
                <h2 className="text-h2 font-semibold text-foreground">{catCfg.label}</h2>
                <p className="text-caption text-foreground-muted">{catCfg.desc}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 gap-5">
              {catCases.map((c) => {
                const content = (
                  <>
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-badge text-tiny font-medium ${catCfg.bg} ${catCfg.color}`}>
                        {catCfg.label}
                      </span>
                      <span className="text-caption text-foreground-muted">{c.source}</span>
                      {c.sourceKind === 'curated_seed' && (
                        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-badge bg-surface-tertiary text-foreground-muted text-tiny">
                          <Database className="w-3 h-3" strokeWidth={1.5} />
                          精选存量
                        </span>
                      )}
                      {c.sourceKind === 'legacy_unverified' && (
                        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-badge bg-surface-tertiary text-foreground-muted text-tiny" data-governance-status="unavailable" aria-label="核验状态：待核验存量">
                          <History className="w-3 h-3" strokeWidth={1.5} />
                          待核验存量
                        </span>
                      )}
                      {c.sourceKind === 'approved_delta' && (
                        <span
                          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-badge bg-status-successBg text-status-success text-tiny"
                          title={c.lastVerifiedAt ? `核验时间：${c.lastVerifiedAt}` : undefined}
                        >
                          <BadgeCheck className="w-3 h-3" strokeWidth={1.5} />
                          已验证增量
                        </span>
                      )}
                    </div>
                    {allowExternalNavigation && <ExternalLink
                      className="w-4 h-4 text-foreground-muted opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                      strokeWidth={1.5}
                    />}
                  </div>

                  <h3 className="text-body font-semibold text-foreground mb-2 group-hover:text-primary transition-colors line-clamp-2">
                    {c.title}
                  </h3>

                  <p className="text-caption text-foreground-secondary leading-relaxed mb-4 flex-1 line-clamp-3">
                    {c.description}
                  </p>

                  <div className="flex items-center justify-between mt-auto pt-4 border-t border-border-divider">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {c.tags.map((tag) => (
                        <span
                          key={tag}
                          className={`px-2 py-0.5 rounded-badge text-tiny transition-colors cursor-pointer hover:bg-primary-light hover:text-primary ${
                            searchQuery === tag ? 'bg-primary-light text-primary' : 'bg-surface-tertiary text-foreground-muted'
                          }`}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleTagClick(tag);
                          }}
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                    <div className="flex items-center gap-1 text-foreground-muted flex-shrink-0 ml-2">
                      <Calendar className="w-3 h-3" strokeWidth={1.5} />
                      <span className="text-tiny">{c.date}</span>
                    </div>
                  </div>
                  </>
                );
                const className = "card p-6 group hover:shadow-card-hover transition-all duration-300 flex flex-col h-full";
                return allowExternalNavigation ? (
                  <a key={c.id} href={c.url} target="_blank" rel="noopener noreferrer" className={className}>{content}</a>
                ) : (
                  <article key={c.id} className={className} data-external-navigation="disabled">{content}</article>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
