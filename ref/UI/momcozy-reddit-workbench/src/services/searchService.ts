import { searchPosts } from '../data/searchMock';
import type { SearchPost } from '../data/searchMock';
import api from '../lib/api';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

export async function getSearchPosts(): Promise<SearchPost[]> {
  if (USE_MOCK) {
    return [...searchPosts];
  }
  return api.search.execute('default', { page: 1, pageSize: 100 }) as Promise<SearchPost[]>;
}

export type { SearchPost };
