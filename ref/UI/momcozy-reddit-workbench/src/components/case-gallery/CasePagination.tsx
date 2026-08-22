import {
  Filter,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

interface CasePaginationProps {
  resultsLength: number;
  isLoading: boolean;
  onClearFilters: () => void;
  page?: number;
  totalPages?: number;
  hasPrev?: boolean;
  hasMore?: boolean;
  onPrevPage?: () => void;
  onNextPage?: () => void;
}

export default function CasePagination({
  resultsLength,
  isLoading,
  onClearFilters,
  page = 1,
  totalPages = 1,
  hasPrev = false,
  hasMore = false,
  onPrevPage,
  onNextPage,
}: CasePaginationProps) {
  return (
    <>
      {/* Empty State */}
      {resultsLength === 0 && !isLoading && (
        <div className="card p-16 text-center">
          <Filter className="w-12 h-12 text-foreground-muted mx-auto mb-4" strokeWidth={1.5} />
          <p className="text-body text-foreground-muted mb-2">未找到匹配的案例</p>
          <p className="text-caption text-foreground-muted mb-6">请尝试其他关键词或分类</p>
          <button
            onClick={onClearFilters}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-button bg-primary text-white text-body-sm font-medium hover:bg-primary-hover transition-all"
          >
            <ArrowRight className="w-4 h-4" strokeWidth={1.5} />
            查看全部案例
          </button>
        </div>
      )}

      {/* Loading Skeleton */}
      {isLoading && resultsLength === 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-6 animate-pulse">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className="h-5 w-16 rounded-badge bg-surface-tertiary" />
                  <div className="h-4 w-24 rounded bg-surface-tertiary" />
                </div>
              </div>
              <div className="h-5 w-3/4 rounded bg-surface-tertiary mb-2" />
              <div className="h-4 w-full rounded bg-surface-tertiary mb-1" />
              <div className="h-4 w-5/6 rounded bg-surface-tertiary mb-4" />
              <div className="flex items-center justify-between pt-4 border-t border-border-divider">
                <div className="flex gap-2">
                  <div className="h-5 w-12 rounded-badge bg-surface-tertiary" />
                  <div className="h-5 w-12 rounded-badge bg-surface-tertiary" />
                </div>
                <div className="h-4 w-16 rounded bg-surface-tertiary" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pagination Controls */}
      {resultsLength > 0 && totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-8 mt-4">
          <button
            onClick={onPrevPage}
            disabled={!hasPrev}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-button text-body-sm font-medium text-foreground-secondary hover:bg-surface-tertiary disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            <ChevronLeft className="w-4 h-4" strokeWidth={1.5} />
            上一页
          </button>
          <span className="text-caption text-foreground-muted px-2">
            第 {page} / {totalPages} 页
          </span>
          <button
            onClick={onNextPage}
            disabled={!hasMore}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-button text-body-sm font-medium text-foreground-secondary hover:bg-surface-tertiary disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            下一页
            <ChevronRight className="w-4 h-4" strokeWidth={1.5} />
          </button>
        </div>
      )}
    </>
  );
}
