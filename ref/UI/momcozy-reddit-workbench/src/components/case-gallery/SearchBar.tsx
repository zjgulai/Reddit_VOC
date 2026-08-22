import {
  Search,
  Loader2,
  X,
  Zap,
  TrendingUp as TrendingUpIcon,
  Clock,
  Database,
  Globe,
} from 'lucide-react';
import { hotSearchTags } from '../../data/casesMock';
import type { CaseCatalogMeta } from '../../services/caseService';

interface SearchBarProps {
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  isLoading: boolean;
  showHistory: boolean;
  setShowHistory: (show: boolean) => void;
  searchHistory: string[];
  handleHistoryClick: (item: string) => void;
  clearHistory: () => void;
  clearSearch: () => void;
  handleTagClick: (tag: string) => void;
  total: number;
  lastSearchedAt: string | null;
  fromCache: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
  seedCount?: number;
  legacyUnverifiedCount?: number;
  approvedDeltaCount?: number;
  catalogMeta?: CaseCatalogMeta | null;
}

export default function SearchBar({
  searchQuery,
  setSearchQuery,
  isLoading,
  showHistory,
  setShowHistory,
  searchHistory,
  handleHistoryClick,
  clearHistory,
  clearSearch,
  handleTagClick,
  total,
  lastSearchedAt,
  fromCache,
  inputRef,
  seedCount,
  legacyUnverifiedCount,
  approvedDeltaCount,
  catalogMeta,
}: SearchBarProps) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
        <div className="relative w-full sm:w-96">
          <input
            ref={inputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onFocus={() => searchHistory.length > 0 && setShowHistory(true)}
            onBlur={() => setTimeout(() => setShowHistory(false), 200)}
            placeholder="搜索案例、标签或关键词..."
            className="input-field pl-10 pr-10"
          />
          {isLoading ? (
            <Loader2
              className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-primary animate-spin"
              strokeWidth={1.5}
            />
          ) : (
            <Search
              className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-muted"
              strokeWidth={1.5}
            />
          )}
          {searchQuery && (
            <button
              onClick={clearSearch}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-foreground-muted hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" strokeWidth={1.5} />
            </button>
          )}

          {/* 搜索历史下拉 */}
          {showHistory && searchHistory.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-white rounded-card border border-border-divider shadow-elevated z-30 py-2">
              <div className="flex items-center justify-between px-4 py-1.5 border-b border-border-divider">
                <span className="text-caption text-foreground-muted flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" strokeWidth={1.5} />
                  搜索历史
                </span>
                <button
                  onClick={clearHistory}
                  className="text-tiny text-foreground-muted hover:text-foreground transition-colors"
                >
                  清空
                </button>
              </div>
              {searchHistory.map((item, idx) => (
                <button
                  key={idx}
                  onClick={() => handleHistoryClick(item)}
                  className="w-full text-left px-4 py-2 text-body-sm text-foreground hover:bg-surface-tertiary transition-colors flex items-center gap-2"
                >
                  <Clock className="w-3.5 h-3.5 text-foreground-muted flex-shrink-0" strokeWidth={1.5} />
                  <span className="truncate">{item}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 检索状态提示 */}
        <div className="flex items-center gap-2 text-caption text-foreground-muted">
          {isLoading ? (
            <span className="inline-flex items-center gap-1.5">
              <Loader2 className="w-3.5 h-3.5 animate-spin" strokeWidth={1.5} />
              正在检查版本化索引…
            </span>
          ) : lastSearchedAt ? (
            <span className="inline-flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-status-success" strokeWidth={1.5} />
              已加载 {total} 条案例
              {fromCache && (
                <span className="inline-flex items-center gap-1 ml-1 px-1.5 py-0.5 rounded-badge bg-status-infoBg text-status-info text-tiny">
                  <Database className="w-3 h-3" strokeWidth={1.5} />
                  缓存
                </span>
              )}
            </span>
          ) : null}
        </div>
      </div>

      {/* 检索来源分布 */}
      {lastSearchedAt && (
        <div className="flex items-center gap-2 flex-wrap text-caption text-foreground-muted">
          <span className="inline-flex items-center gap-1 mr-1">
            <Database className="w-3.5 h-3.5" strokeWidth={1.5} />
            精选存量: {seedCount ?? 0}
          </span>
          <span className="inline-flex items-center gap-1">
            <Globe className="w-3.5 h-3.5" strokeWidth={1.5} />
            待核验存量: {legacyUnverifiedCount ?? 0}
          </span>
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-badge bg-status-successBg text-status-success">
            已验证增量: {approvedDeltaCount ?? 0}
          </span>
          {catalogMeta?.generatedAt && (
            <span title={catalogMeta.datasetVersion}>
              索引更新: {new Date(catalogMeta.generatedAt).toLocaleString('zh-CN', { hour12: false })}
            </span>
          )}
        </div>
      )}

      {/* 热门检索标签 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="inline-flex items-center gap-1 text-caption text-foreground-muted mr-1">
          <TrendingUpIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
          热门检索：
        </span>
        {hotSearchTags.map((tag) => (
          <button
            key={tag.label}
            onClick={() => handleTagClick(tag.label)}
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-tiny font-medium transition-all ${
              searchQuery === tag.label
                ? 'bg-primary text-white'
                : 'bg-surface-tertiary text-foreground-secondary hover:bg-primary-light hover:text-primary'
            }`}
          >
            {tag.label}
            <span className="opacity-60">{tag.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
