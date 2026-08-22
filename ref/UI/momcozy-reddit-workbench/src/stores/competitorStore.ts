import { create } from 'zustand';

export interface CompetitorBrand {
  id: string;
  name: string;
  color: string;
  subreddits: string[];
  keywords: string[];
  enabled: boolean;
}

interface CompetitorState {
  // 竞品品牌列表
  brands: CompetitorBrand[];

  // 加载状态
  isLoading: boolean;

  // 时间戳
  lastUpdated: Date | null;

  // Actions
  setBrands: (brands: CompetitorBrand[]) => void;
  addBrand: (brand: CompetitorBrand) => void;
  updateBrand: (id: string, brand: Partial<CompetitorBrand>) => void;
  removeBrand: (id: string) => void;
  toggleBrand: (id: string) => void;
  setLoading: (loading: boolean) => void;
  setLastUpdated: (date: Date | null) => void;

  // Getter
  enabledBrands: () => CompetitorBrand[];
  brandCount: () => number;
}

export const DEFAULT_BRANDS: CompetitorBrand[] = [
  { id: 'momcozy', name: 'Momcozy', color: '#F8A67B', subreddits: ['breastfeeding', 'breastpumps'], keywords: ['momcozy'], enabled: true },
  { id: 'spectra', name: 'Spectra', color: '#4A7FB5', subreddits: ['breastpumps'], keywords: ['spectra'], enabled: true },
  { id: 'medela', name: 'Medela', color: '#D19A5C', subreddits: ['breastfeeding', 'breastpumps'], keywords: ['medela'], enabled: true },
  { id: 'lansinoh', name: 'Lansinoh', color: '#2D8A5E', subreddits: ['breastfeeding'], keywords: ['lansinoh'], enabled: true },
  { id: 'haakaa', name: 'Haakaa', color: '#E85D4E', subreddits: ['breastfeeding'], keywords: ['haakaa'], enabled: true },
  { id: 'elvie', name: 'Elvie', color: '#9A5AB5', subreddits: ['breastpumps'], keywords: ['elvie'], enabled: true },
  { id: 'willow', name: 'Willow', color: '#D4940A', subreddits: ['breastpumps'], keywords: ['willow'], enabled: true },
  { id: 'freemie', name: 'Freemie', color: '#6B8E23', subreddits: ['breastpumps'], keywords: ['freemie'], enabled: true },
  { id: 'tsrete', name: 'Tsrete', color: '#5A9A9A', subreddits: ['breastpumps'], keywords: ['tsrete'], enabled: true },
];

export const useCompetitorStore = create<CompetitorState>((set, get) => ({
  brands: DEFAULT_BRANDS,
  isLoading: false,
  lastUpdated: null,

  setBrands: (brands) => set({ brands }),
  addBrand: (brand) =>
    set((state) => ({
      brands: [...state.brands, brand],
    })),
  updateBrand: (id, brand) =>
    set((state) => {
      // 如果尝试修改 id，需检查是否与其他品牌冲突
      if (brand.id && brand.id !== id && state.brands.some((b) => b.id === brand.id)) {
        console.warn(`[competitorStore] updateBrand: id "${brand.id}" 已存在，忽略 id 修改`);
        const { id: _ignored, ...safeUpdates } = brand;
        return {
          brands: state.brands.map((b) => (b.id === id ? { ...b, ...safeUpdates } : b)),
        };
      }
      return {
        brands: state.brands.map((b) => (b.id === id ? { ...b, ...brand } : b)),
      };
    }),
  removeBrand: (id) =>
    set((state) => ({
      brands: state.brands.filter((b) => b.id !== id),
    })),
  toggleBrand: (id) =>
    set((state) => ({
      brands: state.brands.map((b) => (b.id === id ? { ...b, enabled: !b.enabled } : b)),
    })),
  setLoading: (loading) => set({ isLoading: loading }),
  setLastUpdated: (date) => set({ lastUpdated: date }),

  enabledBrands: () => {
    return get().brands.filter((b) => b.enabled);
  },

  brandCount: () => {
    return get().brands.length;
  },
}));
