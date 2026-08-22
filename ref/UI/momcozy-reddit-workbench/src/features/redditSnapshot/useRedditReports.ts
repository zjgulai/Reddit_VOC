import { useCallback, useEffect, useState } from 'react';
import { loadRedditReports, reloadRedditReports } from './reports';
import type { AnyRedditReportsSnapshot } from './reports';

interface ReportsState {
  data: AnyRedditReportsSnapshot | null;
  error: string | null;
  isLoading: boolean;
  isReloading: boolean;
  reload: () => Promise<void>;
}

export function useRedditReports(): ReportsState {
  const [data, setData] = useState<AnyRedditReportsSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReloading, setIsReloading] = useState(false);

  useEffect(() => {
    let active = true;
    loadRedditReports()
      .then((snapshot) => {
        if (active) {
          setData(snapshot);
          setError(null);
          setIsLoading(false);
        }
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setData(null);
        setError(loadError instanceof Error ? loadError.message : '真实报告加载失败');
        setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setIsReloading(true);
    try {
      const snapshot = await reloadRedditReports();
      setData(snapshot);
      setError(null);
    } catch (reloadError: unknown) {
      setData(null);
      setError(reloadError instanceof Error ? reloadError.message : '真实报告重新加载失败');
    } finally {
      setIsReloading(false);
    }
  }, []);

  return { data, error, isLoading, isReloading, reload };
}
