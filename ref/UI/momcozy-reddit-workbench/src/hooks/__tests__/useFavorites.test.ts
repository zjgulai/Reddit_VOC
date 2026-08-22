import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useFavorites } from '../useFavorites';

const STORAGE_KEY = 'momcozy_favorites_v1';
const VERSION = 1;

function readStorage(): string[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed.data as string[];
  } catch {
    return null;
  }
}

describe('useFavorites', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('initializes with empty favorites when localStorage is empty', () => {
    const { result } = renderHook(() => useFavorites());
    expect(result.current.favoriteIds).toEqual([]);
    expect(result.current.isFavorite('1')).toBe(false);
  });

  it('loads favorites from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: VERSION, data: ['a', 'b', 'c'] }));
    const { result } = renderHook(() => useFavorites());
    expect(result.current.favoriteIds).toEqual(['a', 'b', 'c']);
    expect(result.current.isFavorite('b')).toBe(true);
    expect(result.current.isFavorite('z')).toBe(false);
  });

  it('toggles favorite on and persists to localStorage', () => {
    const { result } = renderHook(() => useFavorites());

    act(() => {
      result.current.toggleFavorite('item-1');
    });

    expect(result.current.favoriteIds).toContain('item-1');
    expect(result.current.isFavorite('item-1')).toBe(true);

    const stored = readStorage();
    expect(stored).toContain('item-1');
  });

  it('toggles favorite off and updates localStorage', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: VERSION, data: ['item-1', 'item-2'] }));
    const { result } = renderHook(() => useFavorites());

    act(() => {
      result.current.toggleFavorite('item-1');
    });

    expect(result.current.favoriteIds).not.toContain('item-1');
    expect(result.current.favoriteIds).toContain('item-2');

    const stored = readStorage();
    expect(stored).not.toContain('item-1');
  });

  it('clears all favorites and removes from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: VERSION, data: ['x', 'y'] }));
    const { result } = renderHook(() => useFavorites());

    act(() => {
      result.current.clearFavorites();
    });

    expect(result.current.favoriteIds).toEqual([]);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
