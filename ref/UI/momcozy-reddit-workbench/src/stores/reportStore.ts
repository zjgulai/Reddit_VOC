import { create } from 'zustand';
import type { DailyReportData, WeeklyReportData, MonthlyReportData } from '../data/reportEngine';

export type ReportPeriod = 'daily' | 'weekly' | 'monthly';

interface ReportState {
  // 各周期报告数据
  dailyReport: DailyReportData | null;
  weeklyReport: WeeklyReportData | null;
  monthlyReport: MonthlyReportData | null;

  // 当前激活周期
  activePeriod: ReportPeriod;

  // 加载状态
  isLoading: boolean;
  isRefreshing: boolean;

  // 时间戳
  lastRefreshedAt: Date | null;
  dataSeed: number;

  // 数据一致性
  consistency: { valid: boolean; issues: string[] } | null;

  // Actions
  setActivePeriod: (period: ReportPeriod) => void;
  setDailyReport: (data: DailyReportData | null) => void;
  setWeeklyReport: (data: WeeklyReportData | null) => void;
  setMonthlyReport: (data: MonthlyReportData | null) => void;
  setLoading: (loading: boolean) => void;
  setRefreshing: (refreshing: boolean) => void;
  setLastRefreshedAt: (date: Date | null) => void;
  setDataSeed: (seed: number) => void;
  setConsistency: (c: { valid: boolean; issues: string[] } | null) => void;

  // 聚合方法
  refreshAll: () => Promise<void>;
  refreshPeriod: (period: ReportPeriod) => Promise<void>;

  // Getter
  getCurrentReport: () => DailyReportData | WeeklyReportData | MonthlyReportData | null;
}

export const useReportStore = create<ReportState>((set, get) => ({
  dailyReport: null,
  weeklyReport: null,
  monthlyReport: null,
  activePeriod: 'daily',
  isLoading: false,
  isRefreshing: false,
  lastRefreshedAt: null,
  dataSeed: Date.now(),
  consistency: null,

  setActivePeriod: (period) => set({ activePeriod: period }),
  setDailyReport: (data) => set({ dailyReport: data }),
  setWeeklyReport: (data) => set({ weeklyReport: data }),
  setMonthlyReport: (data) => set({ monthlyReport: data }),
  setLoading: (loading) => set({ isLoading: loading }),
  setRefreshing: (refreshing) => set({ isRefreshing: refreshing }),
  setLastRefreshedAt: (date) => set({ lastRefreshedAt: date }),
  setDataSeed: (seed) => set({ dataSeed: seed }),
  setConsistency: (c) => set({ consistency: c }),

  refreshAll: async () => {
    const { dataSeed } = get();
    set({ isRefreshing: true, isLoading: true });
    try {
      const { generateReportData, validateReportConsistency } = await import('../data/reportEngine');
      const [daily, weekly, monthly] = await Promise.all([
        Promise.resolve().then(() => generateReportData('daily', dataSeed)),
        Promise.resolve().then(() => generateReportData('weekly', dataSeed)),
        Promise.resolve().then(() => generateReportData('monthly', dataSeed)),
      ]);
      // 基于已生成的真实数据进行一致性校验，而非重新生成副本
      const consistency = validateReportConsistency(daily, weekly, monthly, dataSeed);
      set({
        dailyReport: daily as DailyReportData,
        weeklyReport: weekly as WeeklyReportData,
        monthlyReport: monthly as MonthlyReportData,
        lastRefreshedAt: new Date(),
        consistency,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set({
        consistency: { valid: false, issues: [`refreshAll 失败: ${message}`] },
      });
    } finally {
      set({ isLoading: false, isRefreshing: false });
    }
  },

  refreshPeriod: async (period) => {
    const { dataSeed, dailyReport, weeklyReport, monthlyReport } = get();
    set({ isLoading: true });
    try {
      const { generateReportData, validateReportConsistency } = await import('../data/reportEngine');
      const data = generateReportData(period, dataSeed);

      // 更新对应周期数据
      if (period === 'daily') {
        set({ dailyReport: data as DailyReportData });
      } else if (period === 'weekly') {
        set({ weeklyReport: data as WeeklyReportData });
      } else {
        set({ monthlyReport: data as MonthlyReportData });
      }

      set({ lastRefreshedAt: new Date() });

      // 如果三套数据都已存在，基于当前 store 数据重新校验一致性
      const currentDaily = period === 'daily' ? data : dailyReport;
      const currentWeekly = period === 'weekly' ? data : weeklyReport;
      const currentMonthly = period === 'monthly' ? data : monthlyReport;

      if (currentDaily && currentWeekly && currentMonthly) {
        const consistency = validateReportConsistency(
          currentDaily,
          currentWeekly,
          currentMonthly,
          dataSeed
        );
        set({ consistency });
      } else {
        // 数据不完整，清除一致性状态避免过期判断
        set({ consistency: null });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set({
        consistency: { valid: false, issues: [`refreshPeriod(${period}) 失败: ${message}`] },
      });
    } finally {
      set({ isLoading: false });
    }
  },

  getCurrentReport: () => {
    const { activePeriod, dailyReport, weeklyReport, monthlyReport } = get();
    if (activePeriod === 'daily') return dailyReport;
    if (activePeriod === 'weekly') return weeklyReport;
    return monthlyReport;
  },
}));
