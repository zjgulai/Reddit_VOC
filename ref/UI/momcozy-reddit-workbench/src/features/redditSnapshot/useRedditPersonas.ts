import { useEffect, useState } from 'react';
import { loadRedditPersonas } from './personas';
import type { AnyRedditPersonasSnapshot } from './personas';

export interface PersonasState {
  data: AnyRedditPersonasSnapshot | null;
  error: string | null;
  isLoading: boolean;
}

export function useRedditPersonas(): PersonasState {
  const [state, setState] = useState<PersonasState>({ data: null, error: null, isLoading: true });

  useEffect(() => {
    let active = true;
    loadRedditPersonas()
      .then((data) => {
        if (active) setState({ data, error: null, isLoading: false });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = error instanceof Error ? error.message : '真实用户画像加载失败';
        setState({ data: null, error: message, isLoading: false });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}
