import { useState, useCallback, useEffect } from 'react';
import { DEFAULT_BRANDS, type CompetitorBrand } from '../stores/competitorStore';
import { getStorage, setStorage } from '../utils/storage';

/** 竞品全局配置 */
export interface CompetitorConfig {
  brands: CompetitorBrand[];
  maxBrands: number;
}

const STORAGE_KEY = 'momcozy_competitor_config_v1';
const VERSION = 1;
const MAX_BRANDS = 9;

function normalizeBrand(brand: Partial<CompetitorBrand>): CompetitorBrand {
  return {
    id: brand.id || '',
    name: brand.name || '',
    color: brand.color || '',
    subreddits: brand.subreddits || [],
    keywords: brand.keywords || [],
    enabled: brand.enabled ?? true,
  };
}

function loadConfig(): CompetitorConfig {
  const fallback: CompetitorConfig = { brands: DEFAULT_BRANDS, maxBrands: MAX_BRANDS };
  try {
    const parsed = getStorage<CompetitorConfig>(STORAGE_KEY, VERSION, fallback);
    // 校验数据完整性
    if (Array.isArray(parsed.brands) && parsed.brands.length <= MAX_BRANDS) {
      return { brands: parsed.brands.map(normalizeBrand), maxBrands: MAX_BRANDS };
    }
  } catch {
    // 解析失败回退到默认值
  }
  return fallback;
}

function saveConfig(config: CompetitorConfig): void {
  setStorage<CompetitorConfig>(STORAGE_KEY, VERSION, config);
}

/** 生成确定性伪随机数（基于字符串种子） */
function seededRandom(seed: string): number {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    const char = seed.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash = hash & hash;
  }
  const x = Math.sin(hash) * 10000;
  return x - Math.floor(x);
}

/** 生成品牌颜色（当未指定时） */
export function generateBrandColor(seed: string): string {
  const hue = Math.floor(seededRandom(seed) * 360);
  const saturation = 55 + Math.floor(seededRandom(seed + 's') * 25);
  const lightness = 40 + Math.floor(seededRandom(seed + 'l') * 20);
  return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
}

/** 竞品配置管理 Hook */
export function useCompetitorConfig() {
  const [config, setConfig] = useState<CompetitorConfig>(loadConfig);

  // localStorage 持久化
  useEffect(() => {
    saveConfig(config);
  }, [config]);

  const activeBrands = config.brands.filter((b) => b.enabled);
  const canAdd = config.brands.length < MAX_BRANDS;

  /** 添加新品牌 */
  const addBrand = useCallback(
    (name: string, color?: string) => {
      if (!canAdd) return null;
      const id = `brand-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const newBrand: CompetitorBrand = {
        id,
        name: name.trim(),
        color: color || generateBrandColor(name),
        subreddits: [],
        keywords: [],
        enabled: true,
      };
      setConfig((prev) => ({
        ...prev,
        brands: [...prev.brands, newBrand],
      }));
      return newBrand;
    },
    [canAdd]
  );

  /** 移除品牌 */
  const removeBrand = useCallback((id: string) => {
    setConfig((prev) => ({
      ...prev,
      brands: prev.brands.filter((b) => b.id !== id),
    }));
  }, []);

  /** 更新品牌属性 */
  const updateBrand = useCallback((id: string, updates: Partial<Omit<CompetitorBrand, 'id'>>) => {
    setConfig((prev) => ({
      ...prev,
      brands: prev.brands.map((b) => (b.id === id ? { ...b, ...updates } : b)),
    }));
  }, []);

  /** 切换品牌启用状态 */
  const toggleBrand = useCallback((id: string) => {
    setConfig((prev) => ({
      ...prev,
      brands: prev.brands.map((b) =>
        b.id === id ? { ...b, enabled: !b.enabled } : b
      ),
    }));
  }, []);

  /** 重置为默认配置 */
  const resetToDefaults = useCallback(() => {
    setConfig({ brands: DEFAULT_BRANDS, maxBrands: MAX_BRANDS });
  }, []);

  /** 重新排序品牌 */
  const reorderBrands = useCallback((newOrder: CompetitorBrand[]) => {
    setConfig((prev) => ({
      ...prev,
      brands: newOrder.slice(0, MAX_BRANDS),
    }));
  }, []);

  return {
    config,
    activeBrands,
    canAdd,
    addBrand,
    removeBrand,
    updateBrand,
    toggleBrand,
    resetToDefaults,
    reorderBrands,
    maxBrands: MAX_BRANDS,
  };
}

export default useCompetitorConfig;
