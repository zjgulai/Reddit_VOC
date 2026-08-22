import { describe, it, expect, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { useReportStore } from '../reportStore';
import type { DailyReportData, WeeklyReportData, MonthlyReportData } from '../../data/reportEngine';

const initialState = {
  dailyReport: null,
  weeklyReport: null,
  monthlyReport: null,
  activePeriod: 'daily' as const,
  isLoading: false,
  isRefreshing: false,
  lastRefreshedAt: null,
  dataSeed: Date.now(),
  consistency: null,
};

const mockDailyReport: DailyReportData = {
  period: 'daily',
  overview: {
    newPosts: 10,
    newPostsTrend: 5,
    positiveRate: 60,
    negativeRate: 20,
    neutralRate: 20,
    alerts: 2,
    highIntent: 5,
    ugc: 3,
    updatedAt: '2024-01-01',
  },
  sentimentTrend: [],
  alerts: [],
  newPosts: [],
  communityStatus: [],
  actionItems: [],
};

const mockWeeklyReport: WeeklyReportData = {
  period: 'weekly',
  overview: {
    newPosts: 50,
    newPostsTrend: 10,
    positiveRate: 55,
    negativeRate: 15,
    neutralRate: 30,
    alerts: 5,
    highIntent: 20,
    ugc: 10,
    updatedAt: '2024-01-01',
  },
  sentimentTrend: [],
  alerts: [],
  newPosts: [],
  communityStatus: [],
  actionItems: [],
  weeklyTrends: [],
  weeklyOpportunities: [],
  weeklyRisks: [],
  weeklyCompetitors: [],
  weeklyReviews: [],
  weeklyPlans: [],
};

const mockMonthlyReport: MonthlyReportData = {
  period: 'monthly',
  overview: {
    newPosts: 200,
    newPostsTrend: 15,
    positiveRate: 58,
    negativeRate: 18,
    neutralRate: 24,
    alerts: 10,
    highIntent: 50,
    ugc: 30,
    updatedAt: '2024-01-01',
  },
  sentimentTrend: [],
  alerts: [],
  newPosts: [],
  communityStatus: [],
  actionItems: [],
  monthlyBrandHealth: [],
  monthlyBrandHealthTrend: [],
  monthlyCompetitorShares: [],
  monthlyCommunityROI: [],
  monthlyTopicEvolution: [],
  monthlyKPIs: [],
  monthlyStrategicAdvices: [],
};

describe('useReportStore', () => {
  beforeEach(() => {
    act(() => {
      useReportStore.setState(initialState);
    });
  });

  it('should have correct initial state with activePeriod daily and all reports null', () => {
    const state = useReportStore.getState();
    expect(state.activePeriod).toBe('daily');
    expect(state.dailyReport).toBeNull();
    expect(state.weeklyReport).toBeNull();
    expect(state.monthlyReport).toBeNull();
    expect(state.isLoading).toBe(false);
    expect(state.isRefreshing).toBe(false);
    expect(state.lastRefreshedAt).toBeNull();
  });

  it('should switch active period via setActivePeriod', () => {
    act(() => {
      useReportStore.getState().setActivePeriod('weekly');
    });
    expect(useReportStore.getState().activePeriod).toBe('weekly');

    act(() => {
      useReportStore.getState().setActivePeriod('monthly');
    });
    expect(useReportStore.getState().activePeriod).toBe('monthly');

    act(() => {
      useReportStore.getState().setActivePeriod('daily');
    });
    expect(useReportStore.getState().activePeriod).toBe('daily');
  });

  it('should set daily report and getCurrentReport returns correct data', () => {
    act(() => {
      useReportStore.getState().setDailyReport(mockDailyReport);
    });

    const report = useReportStore.getState().getCurrentReport();
    expect(report).toEqual(mockDailyReport);
    expect(report?.period).toBe('daily');
    expect(useReportStore.getState().dailyReport).toEqual(mockDailyReport);
    expect(useReportStore.getState().weeklyReport).toBeNull();
    expect(useReportStore.getState().monthlyReport).toBeNull();
  });

  it('should return the correct report after switching activePeriod', () => {
    act(() => {
      useReportStore.getState().setDailyReport(mockDailyReport);
      useReportStore.getState().setWeeklyReport(mockWeeklyReport);
      useReportStore.getState().setMonthlyReport(mockMonthlyReport);
    });

    // Default activePeriod is daily
    expect(useReportStore.getState().getCurrentReport()?.period).toBe('daily');

    act(() => {
      useReportStore.getState().setActivePeriod('weekly');
    });
    expect(useReportStore.getState().getCurrentReport()?.period).toBe('weekly');
    expect(useReportStore.getState().getCurrentReport()).toEqual(mockWeeklyReport);

    act(() => {
      useReportStore.getState().setActivePeriod('monthly');
    });
    expect(useReportStore.getState().getCurrentReport()?.period).toBe('monthly');
    expect(useReportStore.getState().getCurrentReport()).toEqual(mockMonthlyReport);

    act(() => {
      useReportStore.getState().setActivePeriod('daily');
    });
    expect(useReportStore.getState().getCurrentReport()?.period).toBe('daily');
    expect(useReportStore.getState().getCurrentReport()).toEqual(mockDailyReport);
  });
});
