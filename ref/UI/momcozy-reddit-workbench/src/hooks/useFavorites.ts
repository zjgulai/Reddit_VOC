import { useState, useCallback } from 'react';
import { getStorage, setStorage, removeStorage } from '../utils/storage';

const STORAGE_KEY = 'momcozy_favorites_v1';
const VERSION = 1;

export function useFavorites() {
  const [favoriteIds, setFavoriteIds] = useState<string[]>(() =>
    getStorage<string[]>(STORAGE_KEY, VERSION, [])
  );

  const toggleFavorite = useCallback((id: string) => {
    setFavoriteIds((prev) => {
      const next = prev.includes(id) ? prev.filter((f) => f !== id) : [...prev, id];
      setStorage<string[]>(STORAGE_KEY, VERSION, next);
      return next;
    });
  }, []);

  const isFavorite = useCallback(
    (id: string) => favoriteIds.includes(id),
    [favoriteIds]
  );

  const clearFavorites = useCallback(() => {
    setFavoriteIds([]);
    removeStorage(STORAGE_KEY);
  }, []);

  return { favoriteIds, toggleFavorite, isFavorite, clearFavorites };
}
