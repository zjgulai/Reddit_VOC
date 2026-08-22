import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  LayoutGrid,
  RefreshCw,
  Database,
  Search,
  Bell,
  ArrowRight,
  ShieldCheck,
} from 'lucide-react';
import Sidebar from '../components/Sidebar';
import {
  searchCases,
  caseCategories,
  type CaseCatalogMeta,
  type CaseCategory,
  type CaseItem,
} from '../services/caseService';
import { useDebounce, usePersistentState, usePagination, useUrlParams } from '../hooks';
import { useAutoRefresh } from '../hooks/useAutoRefresh';
import SearchBar from '../components/case-gallery/SearchBar';
import CategoryFilter from '../components/case-gallery/CategoryFilter';
import CaseCardGrid from '../components/case-gallery/CaseCardGrid';
import CasePagination from '../components/case-gallery/CasePagination';
import CaseViewTabs, { type CaseGalleryView } from '../components/case-gallery/CaseViewTabs';
import CaseDossierDrawer from '../components/case-gallery/CaseDossierDrawer';
import {
  GovernanceStatusBadge,
  type GovernanceStatus,
} from '../features/redditSnapshot/governance';
import {
  loadRedditCasebook,
  type PublicCaseDossier,
} from '../features/redditSnapshot/casebook';

function formatTimeAgo(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${Math.floor(diff / 86400)}天前`;
}

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function formatCatalogDate(value: string | null | undefined): string {
  if (!value) return '未提供';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(parsed).replaceAll('/', '-');
}

export default function CaseGallery() {
  const [activeView, setActiveView] = useState<CaseGalleryView>('reference');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState<CaseCategory | 'all'>('all');
  const [results, setResults] = useState<CaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [lastSearchedAt, setLastSearchedAt] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [searchHistory, setSearchHistory] = usePersistentState<string[]>('case-gallery-search-history', 1, []);
  const [topBarSearch, setTopBarSearch] = useState('');
  const [catalogMeta, setCatalogMeta] = useState<CaseCatalogMeta | null>(null);
  const [operationsDossier, setOperationsDossier] = useState<PublicCaseDossier | null>(null);
  const [selectedDossier, setSelectedDossier] = useState<PublicCaseDossier | null>(null);
  const [casebookError, setCasebookError] = useState<string | null>(null);

  // 统计来源分布
  const seedCount = results.filter((item) => item.sourceKind === 'curated_seed').length;
  const legacyUnverifiedCount = results.filter((item) => item.sourceKind === 'legacy_unverified').length;
  const approvedDeltaCount = results.filter((item) => item.sourceKind === 'approved_delta').length;
  const catalogGovernanceStatus: GovernanceStatus | null = catalogMeta
    ? catalogMeta.status === 'seed_only'
      ? 'failed'
      : catalogMeta.freshness === 'fresh'
        ? 'verified'
        : 'provisional'
    : null;

  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const debouncedQuery = useDebounce(searchQuery, 400);

  const { getParam, setParam } = useUrlParams();

  const ITEMS_PER_PAGE = 12;

  const {
    page,
    totalPages,
    paginated,
    hasMore,
    hasPrev,
    nextPage,
    prevPage,
    setPage,
  } = usePagination(results, ITEMS_PER_PAGE);

  // 当搜索条件变化时重置到第一页
  useEffect(() => {
    setPage(1);
  }, [debouncedQuery, activeCategory, activeView, setPage]);

  // 加载本地 seed + 同源版本化增量索引
  const performSearch = useCallback(
    async (
      query: string,
      category: CaseCategory | 'all',
      refresh = false,
      view: 'reference' | 'review' = 'reference',
    ) => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      setIsLoading(true);
      try {
        const res = await searchCases(query, category, controller.signal, { refresh, view });
        setResults(res.items);
        setTotal(res.total);
        setLastSearchedAt(res.searchedAt);
        setCatalogMeta(res.meta);
      } catch (err) {
        if (err instanceof Error && err.message === 'Aborted') return;
        if (import.meta.env.DEV) {
          console.error('案例索引加载失败:', err);
        }
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  // 定时刷新 Hook
  const queryRef = useRef(debouncedQuery);
  queryRef.current = debouncedQuery;
  const categoryRef = useRef(activeCategory);
  categoryRef.current = activeCategory;
  const viewRef = useRef(activeView);
  viewRef.current = activeView;

  const {
    config: autoRefreshConfig,
    setConfig: setAutoRefreshConfig,
    lastRefreshAt,
    setLastRefreshAt,
    nextRefreshIn,
    isRefreshing,
    doRefresh,
  } = useAutoRefresh(
    useCallback(async () => {
      if (viewRef.current === 'operations') return;
      await performSearch(
        queryRef.current,
        categoryRef.current,
        true,
        viewRef.current === 'review' ? 'review' : 'reference',
      );
    }, [performSearch])
  );

  // 同步搜索时间到刷新时间
  useEffect(() => {
    if (lastSearchedAt) {
      setLastRefreshAt(lastSearchedAt);
    }
  }, [lastSearchedAt, setLastRefreshAt]);

  // 初始化：从 URL 读取搜索参数
  useEffect(() => {
    const urlQuery = getParam('q');
    const urlCategory = getParam('cat') as CaseCategory | 'all' | null;
    const urlView = getParam('view') as CaseGalleryView | null;
    if (urlQuery) setSearchQuery(urlQuery);
    if (urlCategory && (urlCategory === 'all' || ['geo', 'newproduct', 'insight', 'business'].includes(urlCategory))) {
      setActiveCategory(urlCategory);
    }
    if (urlView && ['reference', 'operations', 'review'].includes(urlView)) setActiveView(urlView);
  }, []);

  // 当防抖后的查询或分类变化时，自动执行检索
  useEffect(() => {
    if (activeView === 'operations') return;
    performSearch(debouncedQuery, activeCategory, false, activeView);
  }, [debouncedQuery, activeCategory, activeView, performSearch]);

  useEffect(() => {
    if (activeView !== 'operations' || operationsDossier) return;
    let active = true;
    setCasebookError(null);
    loadRedditCasebook()
      .then((casebook) => {
        if (active) setOperationsDossier(casebook.data.dossiers[0] ?? null);
      })
      .catch((error: unknown) => {
        if (active) setCasebookError(error instanceof Error ? error.message : '运营闭环数据加载失败');
      });
    return () => { active = false; };
  }, [activeView, operationsDossier]);

  // 同步 URL 参数
  useEffect(() => {
    setParam('q', debouncedQuery);
    setParam('cat', activeCategory === 'all' ? null : activeCategory);
    setParam('view', activeView === 'reference' ? null : activeView);
  }, [debouncedQuery, activeCategory, activeView]);

  // 记录搜索历史
  useEffect(() => {
    if (activeView !== 'operations' && debouncedQuery.trim() && !isLoading) {
      setSearchHistory((prev) => {
        const next = [debouncedQuery.trim(), ...prev.filter((h) => h !== debouncedQuery.trim())];
        return next.slice(0, 10);
      });
    }
  }, [activeView, debouncedQuery, isLoading, setSearchHistory]);

  const handleViewChange = (view: CaseGalleryView) => {
    abortRef.current?.abort();
    setActiveView(view);
    setResults([]);
    setTotal(0);
    setCatalogMeta(null);
  };

  const handleTagClick = (tag: string) => {
    setSearchQuery(tag);
    setShowHistory(false);
    inputRef.current?.focus();
  };

  const handleHistoryClick = (item: string) => {
    setSearchQuery(item);
    setShowHistory(false);
  };

  const clearHistory = () => {
    setSearchHistory([]);
    setShowHistory(false);
  };

  const clearSearch = () => {
    setSearchQuery('');
    inputRef.current?.focus();
  };

  const clearFilters = () => {
    setSearchQuery('');
    setActiveCategory('all');
  };

  const categoryCounts = Object.entries(caseCategories).reduce(
    (acc, [key]) => {
      acc[key as CaseCategory] = results.filter((c) => c.category === key).length;
      return acc;
    },
    {} as Record<CaseCategory, number>
  );

  // 按分类分组展示结果
  const groupedResults =
    activeCategory === 'all'
      ? (Object.entries(caseCategories) as [CaseCategory, typeof caseCategories[CaseCategory]][])
      : ([[activeCategory, caseCategories[activeCategory]]] as [CaseCategory, typeof caseCategories[CaseCategory]][]);

  return (
    <div className="flex min-h-screen bg-surface-tertiary">
      <Sidebar />

      <main className="flex-1 min-w-0">
        {/* Top Bar */}
        <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-xl border-b border-border-divider/60">
          <div className="flex items-center justify-between px-4 sm:px-6 py-3.5">
            <div className="flex items-center gap-4">
              <div className="relative w-72 max-w-[calc(100vw-12rem)]">
                <input
                  type="text"
                  value={topBarSearch}
                  onChange={(e) => setTopBarSearch(e.target.value)}
                  placeholder="搜索帖子或关键词..."
                  className="input-field pl-10 bg-surface-tertiary border-transparent focus:bg-white"
                />
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-muted" strokeWidth={1.5} />
              </div>
            </div>

            <div className="flex items-center gap-3">
              <Link to="/dashboard/messages" className="relative w-9 h-9 rounded-icon flex items-center justify-center text-foreground-secondary hover:bg-surface-tertiary transition-all duration-200" aria-label="消息中心">
                <Bell className="w-[18px] h-[18px]" strokeWidth={1.5} />
              </Link>
              <div className="w-9 h-9 rounded-full bg-primary-light flex items-center justify-center">
                <span className="text-sm font-medium text-primary">M</span>
              </div>
            </div>
          </div>
        </header>

        <div className="p-4 sm:p-6 space-y-6">
          {/* Page Header */}
          <div className="text-center mb-12">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-badge bg-primary-light text-primary text-body-sm font-medium mb-6">
              <LayoutGrid className="w-4 h-4" strokeWidth={1.5} />
              案例广场
            </div>
            <h1 className="text-display font-semibold text-foreground mb-4">
              Reddit 数据应用案例精选
            </h1>
            <p className="text-body text-foreground-secondary max-w-2xl mx-auto">
              人工精选参考、只读运营闭环与待复核内容分区展示，保留存量案例及其原始顺序与内容。
              <br />
              默认仅展示 URL 结构可导航的精选存量与已验证增量；“人工精选”不等同于在线内容审核或业务授权。
            </p>
          </div>

          <CaseViewTabs activeView={activeView} onChange={handleViewChange} />

          {/* Auto-refresh Controls */}
          {activeView !== 'operations' && <div className="card p-4 mb-8">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="flex items-center gap-4 flex-wrap">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setAutoRefreshConfig((prev) => ({ ...prev, enabled: !prev.enabled }))}
                    className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                      autoRefreshConfig.enabled ? 'bg-primary' : 'bg-foreground-muted/30'
                    }`}
                    role="switch"
                    aria-checked={autoRefreshConfig.enabled}
                  >
                    <span
                      className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition duration-200 ease-in-out ${
                        autoRefreshConfig.enabled ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                  <span className="text-body-sm font-medium text-foreground">
                    自动检查增量
                  </span>
                </div>
                {autoRefreshConfig.enabled && (
                  <div className="flex items-center gap-1 flex-wrap">
                    {[5, 15, 30, 60].map((min) => (
                      <button
                        key={min}
                        onClick={() => setAutoRefreshConfig((prev) => ({ ...prev, intervalMinutes: min }))}
                        className={`px-2.5 py-1 rounded-button text-tiny font-medium transition-all ${
                          autoRefreshConfig.intervalMinutes === min
                            ? 'bg-primary text-white'
                            : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
                        }`}
                      >
                        {min === 60 ? '1小时' : `${min}分钟`}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                {catalogGovernanceStatus && (
                  <GovernanceStatusBadge status={catalogGovernanceStatus} label="静态案例目录" />
                )}
                {autoRefreshConfig.enabled && nextRefreshIn > 0 && lastRefreshAt && (
                  <span className="text-caption text-foreground-muted font-medium">
                    下次刷新: {formatCountdown(nextRefreshIn)}
                  </span>
                )}
                {lastRefreshAt && (
                  <span className="text-caption text-foreground-muted hidden sm:inline-flex items-center gap-1">
                    <Database className="w-3 h-3" strokeWidth={1.5} />
                    已检查 {formatTimeAgo(lastRefreshAt)}
                  </span>
                )}
                <button
                  onClick={doRefresh}
                  disabled={isRefreshing || isLoading}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-body-sm font-medium transition-all border border-border hover:border-border-hover bg-white hover:bg-surface-tertiary disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <RefreshCw className={`w-4 h-4 ${isRefreshing || isLoading ? 'animate-spin' : ''}`} strokeWidth={1.5} />
                  检查增量
                </button>
              </div>
            </div>
          </div>}

          {activeView !== 'operations' && catalogMeta?.status === 'verified_index' && (
            <div
              className="rounded-card border border-border-divider bg-white px-4 py-3 text-caption text-foreground-secondary"
              role="status"
              aria-label="静态案例目录时间信息"
              data-case-catalog-freshness={catalogMeta.freshness}
            >
              <strong className="font-semibold text-foreground">静态案例目录</strong>
              <span className="mx-2 text-border-divider">·</span>
              生成于 {formatCatalogDate(catalogMeta.generatedAt)}
              <span className="mx-2 text-border-divider">·</span>
              内容截至 {formatCatalogDate(catalogMeta.asOf)}
              <span className="mx-2 text-border-divider">·</span>
              复核/过期日 {formatCatalogDate(catalogMeta.staleAfter)}
            </div>
          )}

          {activeView !== 'operations' && catalogMeta?.status === 'seed_only' && (
            <div className="rounded-card border border-status-error/20 bg-status-errorBg px-4 py-3 text-caption text-foreground-secondary" role="status" data-ui-severity="error">
              增量索引未通过校验，当前仅使用 {catalogMeta.seedCount} 条人工 seed；本视图显示 {total} 条符合筛选条件的内容。
              {catalogMeta.fallbackReason && <span className="ml-1">原因：{catalogMeta.fallbackReason}</span>}
            </div>
          )}

          {activeView !== 'operations' && catalogMeta?.freshness === 'stale' && (
            <div className="rounded-card border border-border-divider bg-surface-tertiary px-4 py-3 text-caption text-foreground-secondary" role="status" data-governance-status="provisional" aria-label="案例索引状态：时效待更新">
              案例索引已超过 freshness 窗口，内容仍可浏览，但不视为最新增量。
            </div>
          )}

          {activeView !== 'operations' && <>
          {/* Search & Filter */}
          <div className="flex flex-col gap-4 mb-10">
            <SearchBar
              searchQuery={searchQuery}
              setSearchQuery={setSearchQuery}
              isLoading={isLoading}
              showHistory={showHistory}
              setShowHistory={setShowHistory}
              searchHistory={searchHistory}
              handleHistoryClick={handleHistoryClick}
              clearHistory={clearHistory}
              clearSearch={clearSearch}
              handleTagClick={handleTagClick}
              total={total}
              lastSearchedAt={lastSearchedAt}
              fromCache={false}
              inputRef={inputRef}
              seedCount={seedCount}
              legacyUnverifiedCount={legacyUnverifiedCount}
              approvedDeltaCount={approvedDeltaCount}
              catalogMeta={catalogMeta}
            />

            <CategoryFilter
              activeCategory={activeCategory}
              setActiveCategory={setActiveCategory}
              total={total}
              categoryCounts={categoryCounts}
            />
          </div>

          {/* Category Sections & Empty State & Loading */}
          <CaseCardGrid
            groupedResults={groupedResults}
            results={paginated}
            searchQuery={searchQuery}
            handleTagClick={handleTagClick}
            allowExternalNavigation={activeView === 'reference'}
          />

          <CasePagination
            resultsLength={results.length}
            isLoading={isLoading}
            onClearFilters={clearFilters}
            page={page}
            totalPages={totalPages}
            hasPrev={hasPrev}
            hasMore={hasMore}
            onPrevPage={prevPage}
            onNextPage={nextPage}
          />
          </>}

          {activeView === 'operations' && (
            <section aria-label="运营闭环案例">
              {casebookError && (
                <div role="alert" className="rounded-card border border-status-error/20 bg-status-errorBg p-4 text-caption text-foreground-secondary">
                  运营闭环数据未通过校验：{casebookError}
                </div>
              )}
              {!casebookError && !operationsDossier && (
                <div role="status" className="card p-6 text-caption text-foreground-muted">正在校验运营闭环数据…</div>
              )}
              {operationsDossier && (
                <article className="card overflow-hidden" data-external-navigation="disabled">
                  <div className="border-b border-border-divider bg-gradient-to-r from-primary-light to-white p-6">
                    <div className="flex items-center gap-2 text-caption font-medium text-primary">
                      <ShieldCheck className="h-4 w-4" strokeWidth={1.5} />
                      社区治理 · {operationsDossier.lifecycle_status}
                    </div>
                    <h2 className="mt-3 text-h2 font-semibold text-foreground">{operationsDossier.title}</h2>
                    <p className="mt-2 max-w-3xl text-caption leading-relaxed text-foreground-secondary">{operationsDossier.business_question}</p>
                  </div>
                  <div className="grid gap-4 p-6 md:grid-cols-[1fr_auto] md:items-center">
                    <div className="flex flex-wrap gap-2">
                      <span className="rounded-badge bg-surface-tertiary px-3 py-1 text-caption font-medium text-foreground-secondary">C2 商业关系</span>
                      <span className="rounded-badge bg-surface-tertiary px-3 py-1 text-caption font-medium text-foreground-secondary">I3 完整性风险</span>
                      <span className="rounded-badge bg-status-warningBg px-3 py-1 text-caption font-medium text-status-warning">品牌控制未确认</span>
                      <span className="rounded-badge bg-surface-tertiary px-3 py-1 text-caption font-medium text-foreground-secondary">仅风险观察</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedDossier(operationsDossier)}
                      className="inline-flex items-center justify-center gap-2 rounded-button bg-primary px-4 py-2.5 text-body-sm font-medium text-white hover:bg-primary-hover"
                    >
                      查看治理闭环
                      <ArrowRight className="h-4 w-4" strokeWidth={1.5} />
                    </button>
                  </div>
                </article>
              )}
            </section>
          )}
        </div>
      </main>
      <CaseDossierDrawer dossier={selectedDossier} onClose={() => setSelectedDossier(null)} />
    </div>
  );
}
