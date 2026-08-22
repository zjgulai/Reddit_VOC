import { useEffect, useState } from 'react';
import { loadRedditQuarterInsights } from './quarterInsights';
import type { RedditPublicQuarterInsights } from './quarterInsights';

export interface QuarterInsightsState {
  data: RedditPublicQuarterInsights | null;
  error: string | null;
  isLoading: boolean;
}

export function useRedditQuarterInsights(): QuarterInsightsState {
  const [state, setState] = useState<QuarterInsightsState>({ data: null, error: null, isLoading: true });

  useEffect(() => {
    let active = true;
    loadRedditQuarterInsights()
      .then((data) => {
        if (active) setState({ data, error: null, isLoading: false });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = error instanceof Error ? error.message : '季度洞察数据加载失败';
        setState({ data: null, error: message, isLoading: false });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}
