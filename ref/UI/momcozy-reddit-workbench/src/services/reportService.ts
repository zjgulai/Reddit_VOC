import { generateReportData } from '../data/reportEngine';
import type { DailyReportData, WeeklyReportData, MonthlyReportData } from '../data/reportEngine';
import api from '../lib/api';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

export async function getDailyReport(seed?: number): Promise<DailyReportData> {
  if (USE_MOCK) {
    return generateReportData('daily', seed) as DailyReportData;
  }
  return api.reports.getDaily() as Promise<DailyReportData>;
}

export async function getWeeklyReport(seed?: number): Promise<WeeklyReportData> {
  if (USE_MOCK) {
    return generateReportData('weekly', seed) as WeeklyReportData;
  }
  return api.reports.getWeekly() as Promise<WeeklyReportData>;
}

export async function getMonthlyReport(seed?: number): Promise<MonthlyReportData> {
  if (USE_MOCK) {
    return generateReportData('monthly', seed) as MonthlyReportData;
  }
  return api.reports.getMonthly() as Promise<MonthlyReportData>;
}
