import { useState, useEffect, useRef, useCallback } from 'react';
import { getStorage, setStorage } from '../utils/storage';

export interface AutoRefreshConfig {
  enabled: boolean;
  intervalMinutes: number;
}

const STORAGE_KEY = 'momcozy_auto_refresh_v1';
const VERSION = 1;

function loadConfig(): AutoRefreshConfig {
  return getStorage<AutoRefreshConfig>(STORAGE_KEY, VERSION, { enabled: true, intervalMinutes: 15 });
}

function saveConfig(config: AutoRefreshConfig) {
  setStorage<AutoRefreshConfig>(STORAGE_KEY, VERSION, config);
}

export function useAutoRefresh(onRefresh: () => Promise<void>) {
  const [config, setConfigState] = useState<AutoRefreshConfig>(loadConfig);
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(new Date().toISOString());
  const [nextRefreshIn, setNextRefreshIn] = useState<number>(0);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const refreshFnRef = useRef(onRefresh);
  refreshFnRef.current = onRefresh;

  const isRunningRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const setConfig = useCallback(
    (next: AutoRefreshConfig | ((prev: AutoRefreshConfig) => AutoRefreshConfig)) => {
      setConfigState((prev) => {
        const updated = typeof next === 'function' ? next(prev) : next;
        saveConfig(updated);
        return updated;
      });
    },
    []
  );

  const doRefresh = useCallback(async () => {
    if (isRunningRef.current) return;
    isRunningRef.current = true;
    setIsRefreshing(true);
    try {
      await refreshFnRef.current();
    } catch (err) {
      if (import.meta.env.DEV) {
        console.error('Auto-refresh failed:', err);
      }
    } finally {
      if (mountedRef.current) {
        setLastRefreshAt(new Date().toISOString());
        setIsRefreshing(false);
      }
      isRunningRef.current = false;
    }
  }, []);

  useEffect(() => {
    if (!config.enabled || !lastRefreshAt) {
      setNextRefreshIn(0);
      return;
    }

    const intervalMs = config.intervalMinutes * 60 * 1000;

    const tick = () => {
      const last = new Date(lastRefreshAt).getTime();
      const next = last + intervalMs;
      const remaining = Math.max(0, Math.ceil((next - Date.now()) / 1000));
      setNextRefreshIn(remaining);

      if (remaining <= 0) {
        doRefresh();
      }
    };

    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [config.enabled, config.intervalMinutes, lastRefreshAt, doRefresh]);

  return {
    config,
    setConfig,
    lastRefreshAt,
    setLastRefreshAt,
    nextRefreshIn,
    isRefreshing,
    doRefresh,
  };
}
