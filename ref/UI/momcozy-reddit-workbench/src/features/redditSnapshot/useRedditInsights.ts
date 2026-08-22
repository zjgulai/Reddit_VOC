import { useEffect, useState } from 'react';
import { loadRedditInsights } from './insights';
import type { AnyRedditInsightsSnapshot } from './insights';

interface InsightsState {
  data: AnyRedditInsightsSnapshot | null;
  error: string | null;
  isLoading: boolean;
}

export function useRedditInsights(): InsightsState {
  const [state, setState] = useState<InsightsState>({ data: null, error: null, isLoading: true });

  useEffect(() => {
    let active = true;
    loadRedditInsights()
      .then((data) => {
        if (active) setState({ data, error: null, isLoading: false });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = error instanceof Error ? error.message : '真实洞察加载失败';
        setState({ data: null, error: message, isLoading: false });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}
