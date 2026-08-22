import { useEffect, useState } from 'react';
import { loadRedditSnapshotSummary } from './service';
import type { RedditSnapshotSummary } from './types';

interface SnapshotSummaryState {
  data: RedditSnapshotSummary | null;
  error: string | null;
  isLoading: boolean;
}

export function useRedditSnapshotSummary(): SnapshotSummaryState {
  const [state, setState] = useState<SnapshotSummaryState>({ data: null, error: null, isLoading: true });

  useEffect(() => {
    let active = true;
    loadRedditSnapshotSummary()
      .then((data) => {
        if (active) setState({ data, error: null, isLoading: false });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setState({ data: null, error: error instanceof Error ? error.message : '数据摘要加载失败', isLoading: false });
      });
    return () => { active = false; };
  }, []);

  return state;
}
