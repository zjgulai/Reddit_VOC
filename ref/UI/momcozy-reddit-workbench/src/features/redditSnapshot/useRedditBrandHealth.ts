import { useEffect, useState } from 'react';
import { loadRedditBrandHealth } from './brandHealth';
import type { RedditPublicBrandHealth } from './brandHealth';

export interface BrandHealthState {
  data: RedditPublicBrandHealth | null;
  error: string | null;
  isLoading: boolean;
}

export function useRedditBrandHealth(): BrandHealthState {
  const [state, setState] = useState<BrandHealthState>({ data: null, error: null, isLoading: true });

  useEffect(() => {
    let active = true;
    loadRedditBrandHealth()
      .then((data) => {
        if (active) setState({ data, error: null, isLoading: false });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = error instanceof Error ? error.message : '品牌健康数据加载失败';
        setState({ data: null, error: message, isLoading: false });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}
