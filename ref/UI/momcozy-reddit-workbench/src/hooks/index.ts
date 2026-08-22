import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getStorage, setStorage } from '../utils/storage';

/** 通用防抖 Hook */
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

/** 带搜索状态管理的 Hook */
export function useSearch<T>(
  items: T[],
  searchFn: (item: T, query: string) => boolean,
  debounceMs = 300
) {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const debouncedQuery = useDebounce(query, debounceMs);

  const results = debouncedQuery
    ? items.filter((item) => searchFn(item, debouncedQuery.toLowerCase()))
    : items;

  useEffect(() => {
    if (query !== debouncedQuery) {
      setIsSearching(true);
    } else {
      setIsSearching(false);
    }
  }, [query, debouncedQuery]);

  return { query, setQuery, results, isSearching, debouncedQuery };
}

/** 分页 Hook */
export function usePagination<T>(items: T[], pageSize = 10) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const paginated = items.slice((page - 1) * pageSize, page * pageSize);
  const hasMore = page < totalPages;
  const hasPrev = page > 1;

  const goToPage = (p: number) => setPage(Math.max(1, Math.min(p, totalPages)));
  const nextPage = () => goToPage(page + 1);
  const prevPage = () => goToPage(page - 1);

  return { page, totalPages, paginated, hasMore, hasPrev, goToPage, nextPage, prevPage, setPage };
}

/** URL 查询参数同步 Hook（基于 react-router-dom useSearchParams） */
export function useUrlParams() {
  const [searchParams, setSearchParams] = useSearchParams();

  const getParam = useCallback((key: string): string | null => {
    return searchParams.get(key);
  }, [searchParams]);

  const setParam = useCallback((key: string, value: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value === null || value === '') {
        next.delete(key);
      } else {
        next.set(key, value);
      }
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  return { getParam, setParam };
}

/** 本地状态持久化 Hook */
export function usePersistentState<T>(key: string, version: number, defaultValue: T): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => getStorage<T>(key, version, defaultValue));

  useEffect(() => {
    setStorage<T>(key, version, value);
  }, [key, version, value]);

  return [value, setValue];
}

/** 异步状态管理 Hook */
export function useAsync<T>(
  asyncFn: () => Promise<T>,
  deps: React.DependencyList = []
) {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [error, setError] = useState<Error | null>(null);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    setError(null);

    asyncFn()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setStatus('success');
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err : new Error(String(err)));
          setStatus('error');
        }
      });

    return () => {
      cancelled = true;
    };
  }, deps);

  return { data, status, error, isLoading: status === 'loading', isError: status === 'error' };
}

export { useAutoRefresh, type AutoRefreshConfig } from './useAutoRefresh';
export { useFavorites } from './useFavorites';
export { useCompetitorConfig } from './useCompetitorConfig';
export { useWebhookPoller } from './useWebhookPoller';
export { useWebhookConfig } from './useWebhookConfig';
export { useNotificationSender } from './useNotificationSender';
