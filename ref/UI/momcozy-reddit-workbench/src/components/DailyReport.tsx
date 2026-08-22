import { useMemo } from 'react';
import { generateReportData } from '../data/reportEngine';
import type { UnifiedReportData } from '../data/reportEngine';
import ReportDailyView from './reports/ReportDailyView';
import ReportWeeklyView from './reports/ReportWeeklyView';
import ReportMonthlyView from './reports/ReportMonthlyView';

export interface DailyReportProps {
  period: 'daily' | 'weekly' | 'monthly';
  data?: UnifiedReportData;
  favoriteIds?: string[];
  onToggleFavorite?: (id: string) => void;
}

export function ReportSkeleton({ period }: { period: 'daily' | 'weekly' | 'monthly' }) {
  const periodLabel = { daily: '日报', weekly: '周报', monthly: '月报' }[period];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-center py-4 animate-fade-in">
        <div className="inline-flex items-center gap-2 text-body text-foreground-muted">
          <div className="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          正在生成 {periodLabel} 报告...
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="card p-5 space-y-3">
            <div className="w-9 h-9 rounded-icon shimmer" />
            <div className="h-7 w-16 shimmer" />
            <div className="h-4 w-24 shimmer" />
          </div>
        ))}
      </div>
      <div className="card p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-icon shimmer" />
          <div className="space-y-2">
            <div className="h-5 w-32 shimmer" />
            <div className="h-4 w-48 shimmer" />
          </div>
        </div>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 rounded-xl shimmer" />
          ))}
        </div>
      </div>
      <div className="card p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-icon shimmer" />
          <div className="space-y-2">
            <div className="h-5 w-32 shimmer" />
            <div className="h-4 w-48 shimmer" />
          </div>
        </div>
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div key={i} className="h-20 rounded-xl shimmer" />
          ))}
        </div>
      </div>
      <div className="card p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-icon shimmer" />
          <div className="space-y-2">
            <div className="h-5 w-32 shimmer" />
            <div className="h-4 w-48 shimmer" />
          </div>
        </div>
        <div className="h-40 rounded-xl shimmer" />
      </div>
    </div>
  );
}

export default function DailyReport({ period, data, favoriteIds = [], onToggleFavorite = () => {} }: DailyReportProps) {
  const generatedData = useMemo(() => generateReportData(period), [period]);
  const reportData = data ?? generatedData;
  switch (period) {
    case 'daily': {
      return (
        <ReportDailyView
          data={reportData}
          favoriteIds={favoriteIds}
          onToggleFavorite={onToggleFavorite}
        />
      );
    }
    case 'weekly': {
      return (
        <ReportWeeklyView
          data={reportData}
        />
      );
    }
    case 'monthly': {
      return (
        <ReportMonthlyView
          data={reportData}
        />
      );
    }
    default:
      return null;
  }
}
