import { useEffect, useState } from 'react';
import { loadRedditSnapshot } from './service';
import type { RedditSnapshotCore } from './types';

interface SnapshotState {
  data: RedditSnapshotCore | null;
  error: string | null;
  isLoading: boolean;
}

export function useRedditSnapshot(): SnapshotState {
  const [state, setState] = useState<SnapshotState>({ data: null, error: null, isLoading: true });

  useEffect(() => {
    let active = true;
    loadRedditSnapshot()
      .then((data) => {
        if (active) setState({ data, error: null, isLoading: false });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = error instanceof Error ? error.message : '真实数据加载失败';
        setState({ data: null, error: message, isLoading: false });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}
