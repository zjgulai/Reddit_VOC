import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { PostIntent } from '../../types';
import api from '../../lib/api';
import { generateReportData } from '../../data/reportEngine';
import type { DailyReportData, WeeklyReportData, MonthlyReportData } from '../../data/reportEngine';

vi.mock('../../lib/api', () => ({
  default: {
    reports: {
      getDaily: vi.fn(),
      getWeekly: vi.fn(),
      getMonthly: vi.fn(),
    },
  },
}));

vi.mock('../../data/reportEngine', () => ({
  generateReportData: vi.fn(),
}));

const mockOverview = {
  newPosts: 48,
  newPostsTrend: 5.2,
  positiveRate: 58,
  negativeRate: 12,
  neutralRate: 30,
  alerts: 3,
  highIntent: 24,
  ugc: 8,
  updatedAt: '2024-01-15T08:00:00Z',
};

const mockAlert = {
  id: 'a1',
  level: 'warning' as const,
  title: 'Test Alert',
  subreddit: 'test',
  upvotes: 10,
  comments: 5,
  growth: 2,
  summary: 'summary',
  time: '08:00',
};

const mockNewPost = {
  id: 'p1',
  title: 'Test Post',
  subreddit: 'test',
  author: 'u1',
  time: '08:00',
  upvotes: 5,
  comments: 2,
  intentScore: 8,
  sentiment: 'positive' as const,
  intent: 'Purchase Intent' as PostIntent,
  action: 'reply' as const,
};

const mockCommunityStatus = {
  name: 'test',
  displayName: 'Test',
  newPosts: 5,
  sentiment: 'positive' as const,
  trend: 'up' as const,
};

const mockActionItem = {
  id: 'i1',
  type: 'reply' as const,
  title: 'Reply',
  urgency: 'high' as const,
  due: '2024-01-15',
  completed: false,
};

const createMockDailyData = (): DailyReportData => ({
  period: 'daily',
  overview: { ...mockOverview },
  sentimentTrend: [{ label: '08:00', positive: 60, negative: 10, neutral: 30, volume: 5 }],
  alerts: [mockAlert],
  newPosts: [mockNewPost],
  communityStatus: [mockCommunityStatus],
  actionItems: [mockActionItem],
  responseMetrics: { avgResponseTime: 30, completionRate: 95, escalationRate: 5 },
  sentimentThermometer: { positive: 60, negative: 10, neutral: 30, level: 'watch' as const, trend24h: 5, previousPositive: 55, previousNegative: 15, previousNeutral: 30 },
});

const createMockWeeklyData = (): WeeklyReportData => ({
  period: 'weekly',
  overview: { ...mockOverview, newPosts: 340, alerts: 9 },
  sentimentTrend: [{ label: 'Mon', positive: 55, negative: 15, neutral: 30, volume: 10 }],
  alerts: [mockAlert],
  newPosts: [mockNewPost],
  communityStatus: [mockCommunityStatus],
  actionItems: [mockActionItem],
  weeklyTrends: [],
  weeklyOpportunities: [],
  weeklyRisks: [],
  weeklyCompetitors: [],
  weeklyReviews: [],
  weeklyPlans: [],
  painPoints: [],
  topicLifecycles: [],
  operationReviews: [],
  brandVoiceTrend: [],
});

const createMockMonthlyData = (): MonthlyReportData => ({
  period: 'monthly',
  overview: { ...mockOverview, newPosts: 1250, alerts: 40, sentimentLevel: 'calm', sentimentLevelLabel: '平稳' },
  sentimentTrend: [{ label: 'Week 1', positive: 53, negative: 14, neutral: 33, volume: 50 }],
  alerts: [mockAlert],
  newPosts: [mockNewPost],
  communityStatus: [mockCommunityStatus],
  actionItems: [mockActionItem],
  monthlyBrandHealth: [],
  monthlyBrandHealthTrend: [],
  monthlyCompetitorShares: [],
  monthlyCommunityROI: [],
  monthlyTopicEvolution: [],
  monthlyKPIs: [],
  monthlyStrategicAdvices: [],
  brandHealthScore: 85,
  brandHealthRadar: [],
  competitiveMatrix: [],
  categoryMatrix: [],
  kpiTrend: [],
  monthlyCategoryValues: [],
});

describe('reportService', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('getDailyReport', () => {
    it('returns mock data when VITE_USE_MOCK=true', async () => {
      vi.stubEnv('VITE_USE_MOCK', 'true');
      const mockData = createMockDailyData();
      vi.mocked(generateReportData).mockReturnValue(mockData);

      const { getDailyReport } = await import('../reportService');
      const result = await getDailyReport(42);

      expect(generateReportData).toHaveBeenCalledTimes(1);
      expect(generateReportData).toHaveBeenCalledWith('daily', 42);
      expect(result).toEqual(mockData);
      expect(result.period).toBe('daily');
      expect(result.overview).toBeDefined();
      expect(result.overview.newPosts).toBe(48);
      expect(result.newPosts).toBeDefined();
      expect(Array.isArray(result.newPosts)).toBe(true);
      expect(result.alerts).toBeDefined();
      expect(Array.isArray(result.alerts)).toBe(true);
      expect(result.sentimentTrend).toBeDefined();
      expect(result.communityStatus).toBeDefined();
      expect(result.actionItems).toBeDefined();
      expect(result.responseMetrics).toBeDefined();
      expect(result.sentimentThermometer).toBeDefined();
    });

    it('calls api.reports.getDaily when VITE_USE_MOCK=false', async () => {
      vi.stubEnv('VITE_USE_MOCK', 'false');
      const apiData = createMockDailyData();
      vi.mocked(api.reports.getDaily).mockResolvedValue(apiData);

      const { getDailyReport } = await import('../reportService');
      const result = await getDailyReport();

      expect(api.reports.getDaily).toHaveBeenCalledTimes(1);
      expect(result).toEqual(apiData);
      expect(result.period).toBe('daily');
      expect(result.overview).toBeDefined();
      expect(result.newPosts).toBeDefined();
      expect(Array.isArray(result.newPosts)).toBe(true);
      expect(result.alerts).toBeDefined();
      expect(Array.isArray(result.alerts)).toBe(true);
      expect(result.sentimentTrend).toBeDefined();
      expect(result.communityStatus).toBeDefined();
      expect(result.actionItems).toBeDefined();
    });
  });

  describe('getWeeklyReport', () => {
    it('returns mock data when VITE_USE_MOCK=true', async () => {
      vi.stubEnv('VITE_USE_MOCK', 'true');
      const mockData = createMockWeeklyData();
      vi.mocked(generateReportData).mockReturnValue(mockData);

      const { getWeeklyReport } = await import('../reportService');
      const result = await getWeeklyReport(123);

      expect(generateReportData).toHaveBeenCalledTimes(1);
      expect(generateReportData).toHaveBeenCalledWith('weekly', 123);
      expect(result).toEqual(mockData);
      expect(result.period).toBe('weekly');
      expect(result.overview).toBeDefined();
      expect(result.overview.newPosts).toBe(340);
      expect(result.newPosts).toBeDefined();
      expect(Array.isArray(result.newPosts)).toBe(true);
      expect(result.alerts).toBeDefined();
      expect(Array.isArray(result.alerts)).toBe(true);
      expect(result.weeklyTrends).toBeDefined();
      expect(result.weeklyOpportunities).toBeDefined();
      expect(result.weeklyRisks).toBeDefined();
      expect(result.weeklyCompetitors).toBeDefined();
      expect(result.weeklyReviews).toBeDefined();
      expect(result.weeklyPlans).toBeDefined();
      expect(result.painPoints).toBeDefined();
      expect(result.topicLifecycles).toBeDefined();
      expect(result.operationReviews).toBeDefined();
      expect(result.brandVoiceTrend).toBeDefined();
    });

    it('calls api.reports.getWeekly when VITE_USE_MOCK=false', async () => {
      vi.stubEnv('VITE_USE_MOCK', 'false');
      const apiData = createMockWeeklyData();
      vi.mocked(api.reports.getWeekly).mockResolvedValue(apiData);

      const { getWeeklyReport } = await import('../reportService');
      const result = await getWeeklyReport();

      expect(api.reports.getWeekly).toHaveBeenCalledTimes(1);
      expect(result).toEqual(apiData);
      expect(result.period).toBe('weekly');
      expect(result.overview).toBeDefined();
      expect(result.newPosts).toBeDefined();
      expect(Array.isArray(result.newPosts)).toBe(true);
      expect(result.alerts).toBeDefined();
      expect(Array.isArray(result.alerts)).toBe(true);
      expect(result.sentimentTrend).toBeDefined();
      expect(result.communityStatus).toBeDefined();
      expect(result.actionItems).toBeDefined();
    });
  });

  describe('getMonthlyReport', () => {
    it('returns mock data when VITE_USE_MOCK=true', async () => {
      vi.stubEnv('VITE_USE_MOCK', 'true');
      const mockData = createMockMonthlyData();
      vi.mocked(generateReportData).mockReturnValue(mockData);

      const { getMonthlyReport } = await import('../reportService');
      const result = await getMonthlyReport(999);

      expect(generateReportData).toHaveBeenCalledTimes(1);
      expect(generateReportData).toHaveBeenCalledWith('monthly', 999);
      expect(result).toEqual(mockData);
      expect(result.period).toBe('monthly');
      expect(result.overview).toBeDefined();
      expect(result.overview.newPosts).toBe(1250);
      expect(result.newPosts).toBeDefined();
      expect(Array.isArray(result.newPosts)).toBe(true);
      expect(result.alerts).toBeDefined();
      expect(Array.isArray(result.alerts)).toBe(true);
      expect(result.monthlyBrandHealth).toBeDefined();
      expect(result.monthlyBrandHealthTrend).toBeDefined();
      expect(result.monthlyCompetitorShares).toBeDefined();
      expect(result.monthlyCommunityROI).toBeDefined();
      expect(result.monthlyTopicEvolution).toBeDefined();
      expect(result.monthlyKPIs).toBeDefined();
      expect(result.monthlyStrategicAdvices).toBeDefined();
      expect(result.brandHealthScore).toBe(85);
      expect(result.brandHealthRadar).toBeDefined();
      expect(result.competitiveMatrix).toBeDefined();
      expect(result.categoryMatrix).toBeDefined();
      expect(result.kpiTrend).toBeDefined();
      expect(result.monthlyCategoryValues).toBeDefined();
    });

    it('calls api.reports.getMonthly when VITE_USE_MOCK=false', async () => {
      vi.stubEnv('VITE_USE_MOCK', 'false');
      const apiData = createMockMonthlyData();
      vi.mocked(api.reports.getMonthly).mockResolvedValue(apiData);

      const { getMonthlyReport } = await import('../reportService');
      const result = await getMonthlyReport();

      expect(api.reports.getMonthly).toHaveBeenCalledTimes(1);
      expect(result).toEqual(apiData);
      expect(result.period).toBe('monthly');
      expect(result.overview).toBeDefined();
      expect(result.newPosts).toBeDefined();
      expect(Array.isArray(result.newPosts)).toBe(true);
      expect(result.alerts).toBeDefined();
      expect(Array.isArray(result.alerts)).toBe(true);
      expect(result.sentimentTrend).toBeDefined();
      expect(result.communityStatus).toBeDefined();
      expect(result.actionItems).toBeDefined();
    });
  });
});
