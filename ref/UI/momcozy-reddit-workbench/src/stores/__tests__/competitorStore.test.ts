import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useCompetitorStore, type CompetitorBrand, DEFAULT_BRANDS } from '../competitorStore';

describe('useCompetitorStore', () => {
  beforeEach(() => {
    act(() => {
      useCompetitorStore.setState({
        brands: DEFAULT_BRANDS,
        isLoading: false,
        lastUpdated: null,
      });
    });
  });

  it('initial state: 9 default brands all enabled', () => {
    const { result } = renderHook(() => useCompetitorStore());

    expect(result.current.brands).toHaveLength(9);
    expect(result.current.brands.every((b) => b.enabled)).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.lastUpdated).toBeNull();
    expect(result.current.brands[0].name).toBe('Momcozy');
    expect(result.current.brands[8].name).toBe('Tsrete');
  });

  it('toggleBrand disables and re-enables a brand', () => {
    const { result } = renderHook(() => useCompetitorStore());

    act(() => {
      result.current.toggleBrand('momcozy');
    });

    expect(result.current.brands.find((b) => b.id === 'momcozy')?.enabled).toBe(false);

    act(() => {
      result.current.toggleBrand('momcozy');
    });

    expect(result.current.brands.find((b) => b.id === 'momcozy')?.enabled).toBe(true);
    expect(result.current.brands).toHaveLength(9);
  });

  it('enabledBrands returns only enabled brands', () => {
    const { result } = renderHook(() => useCompetitorStore());

    expect(result.current.enabledBrands()).toHaveLength(9);

    act(() => {
      result.current.toggleBrand('spectra');
      result.current.toggleBrand('medela');
    });

    const enabled = result.current.enabledBrands();
    expect(enabled).toHaveLength(7);
    expect(enabled.some((b) => b.id === 'spectra')).toBe(false);
    expect(enabled.some((b) => b.id === 'medela')).toBe(false);
    expect(enabled.some((b) => b.id === 'momcozy')).toBe(true);
  });

  it('addBrand appends a new brand', () => {
    const { result } = renderHook(() => useCompetitorStore());
    const newBrand: CompetitorBrand = {
      id: 'newbrand',
      name: 'NewBrand',
      color: '#123456',
      subreddits: ['test'],
      keywords: ['newbrand'],
      enabled: true,
    };

    act(() => {
      result.current.addBrand(newBrand);
    });

    expect(result.current.brands).toHaveLength(10);
    expect(result.current.brands.find((b) => b.id === 'newbrand')).toEqual(newBrand);
    expect(result.current.brands[9].name).toBe('NewBrand');
  });

  it('updateBrand modifies name and color', () => {
    const { result } = renderHook(() => useCompetitorStore());

    act(() => {
      result.current.updateBrand('lansinoh', { name: 'Lansinoh Plus', color: '#FFFFFF' });
    });

    const updated = result.current.brands.find((b) => b.id === 'lansinoh');
    expect(updated?.name).toBe('Lansinoh Plus');
    expect(updated?.color).toBe('#FFFFFF');
    expect(updated?.subreddits).toEqual(['breastfeeding']);
    expect(updated?.keywords).toEqual(['lansinoh']);
    expect(result.current.brands).toHaveLength(9);
  });

  it('removeBrand deletes a brand by id', () => {
    const { result } = renderHook(() => useCompetitorStore());

    act(() => {
      result.current.removeBrand('haakaa');
    });

    expect(result.current.brands).toHaveLength(8);
    expect(result.current.brands.find((b) => b.id === 'haakaa')).toBeUndefined();
    expect(result.current.brands.find((b) => b.id === 'momcozy')).toBeDefined();
  });

  it('brandCount returns correct total', () => {
    const { result } = renderHook(() => useCompetitorStore());

    expect(result.current.brandCount()).toBe(9);

    act(() => {
      result.current.removeBrand('willow');
    });
    expect(result.current.brandCount()).toBe(8);

    act(() => {
      result.current.addBrand({
        id: 'brandX',
        name: 'BrandX',
        color: '#000000',
        subreddits: [],
        keywords: [],
        enabled: true,
      });
    });
    expect(result.current.brandCount()).toBe(9);
  });
});
