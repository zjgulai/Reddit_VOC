import { useState, useMemo } from 'react';
import { TrendingUp, TrendingDown, Users, SearchX } from 'lucide-react';
import SectionCard from './SectionCard';
import DetailModal from './DetailModal';
import {
  getSentimentOverview,
  getSentimentTrend,
  getSentimentBySubreddit,
} from '../data/analyticsMock';
import { SentimentTrendChart } from './charts';
import type { TimeRange } from '../types';
import { SENTIMENT_COLORS } from '../constants/colors';

interface SentimentAnalysisProps {
  timeRange?: TimeRange;
}

function DonutChart({ data }: { data: { positive: number; neutral: number; negative: number; total: number } }) {
  const { positive, neutral, negative, total } = data;
  const pPos = Math.round((positive / total) * 100);
  const pNeu = Math.round((neutral / total) * 100);
  const pNeg = Math.round((negative / total) * 100);

  const grad = `conic-gradient(
    ${SENTIMENT_COLORS.positive} 0deg ${pPos * 3.6}deg,
    ${SENTIMENT_COLORS.neutral} ${pPos * 3.6}deg ${(pPos + pNeu) * 3.6}deg,
    ${SENTIMENT_COLORS.negative} ${(pPos + pNeu) * 3.6}deg 360deg
  )`;

  return (
    <div className="flex items-center gap-8">
      <div className="relative flex-shrink-0">
        <div
          className="w-40 h-40 rounded-full"
          style={{
            background: grad,
            maskImage: 'radial-gradient(transparent 55%, black 56%)',
            WebkitMaskImage: 'radial-gradient(transparent 55%, black 56%)',
          }}
        />
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-h2 font-semibold text-foreground">{total}</span>
          <span className="text-caption text-foreground-muted">总帖子数</span>
        </div>
      </div>

      <div className="flex-1 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-status-success" />
            <span className="text-body-sm text-foreground-secondary">正面</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-body font-semibold text-foreground">{positive}</span>
            <span className="text-caption text-foreground-muted">({pPos}%)</span>
          </div>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-status-warning" />
            <span className="text-body-sm text-foreground-secondary">中性</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-body font-semibold text-foreground">{neutral}</span>
            <span className="text-caption text-foreground-muted">({pNeu}%)</span>
          </div>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-status-error" />
            <span className="text-body-sm text-foreground-secondary">负面</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-body font-semibold text-foreground">{negative}</span>
            <span className="text-caption text-foreground-muted">({pNeg}%)</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function SubredditHeatmap({ timeRange }: { timeRange: TimeRange }) {
  const data = getSentimentBySubreddit(timeRange);
  const maxVal = Math.max(...data.map((s) => s.positive + s.neutral + s.negative));

  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-foreground-muted">
        <SearchX className="w-12 h-12 mb-3 opacity-40" strokeWidth={1.5} />
        <p className="text-body-sm">暂无社区情感热力数据</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {data.map((s) => {
        const total = s.positive + s.neutral + s.negative;
        const pPos = (s.positive / total) * 100;
        const pNeu = (s.neutral / total) * 100;
        const pNeg = (s.negative / total) * 100;
        const intensity = Math.round((total / maxVal) * 100);

        return (
          <div key={s.name} className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-body-sm font-medium text-foreground">r/{s.name}</span>
                <span className="text-caption text-foreground-muted">{total} 帖</span>
              </div>
              <div className="flex items-center gap-1">
                <Users className="w-3.5 h-3.5 text-foreground-muted" strokeWidth={1.5} />
                <span className="text-tiny text-foreground-muted">热度 {intensity}%</span>
              </div>
            </div>
            <div className="flex h-2.5 rounded-full overflow-hidden bg-surface-tertiary">
              <div className="h-full bg-status-success transition-all" style={{ width: `${pPos}%` }} />
              <div className="h-full bg-status-warning transition-all" style={{ width: `${pNeu}%` }} />
              <div className="h-full bg-status-error transition-all" style={{ width: `${pNeg}%` }} />
            </div>
            <div className="flex items-center gap-3">
              <span className="text-tiny text-status-success">{Math.round(pPos)}% 正面</span>
              <span className="text-tiny text-status-warning">{Math.round(pNeu)}% 中性</span>
              <span className="text-tiny text-status-error">{Math.round(pNeg)}% 负面</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function SentimentAnalysis({ timeRange = '7d' }: SentimentAnalysisProps) {
  const overview = getSentimentOverview(timeRange);
  const trendData = getSentimentTrend(timeRange);
  const labelDays = timeRange === '7d' ? '7' : timeRange === '30d' ? '30' : '90';
  const [showTrendModal, setShowTrendModal] = useState(false);
  const [showHeatmapModal, setShowHeatmapModal] = useState(false);

  const trendSummary = useMemo(() => {
    const first = trendData[0].total;
    const last = trendData[trendData.length - 1].total;
    const change = ((last - first) / first) * 100;
    return { change: Math.round(change * 10) / 10, up: change >= 0 };
  }, [trendData]);

  if (!overview || overview.total === 0) {
    return (
      <div className="space-y-6">
        <SectionCard title="情感分布" subtitle="基于 VADER 算法的正负面判定" icon={<TrendingUp className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          <div className="flex flex-col items-center justify-center py-16 text-foreground-muted">
            <SearchX className="w-12 h-12 mb-3 opacity-40" strokeWidth={1.5} />
            <p className="text-body-sm">暂无情感分析数据</p>
          </div>
        </SectionCard>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title="情感分布" subtitle="基于 VADER 算法的正负面判定" icon={<TrendingUp className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          <DonutChart data={overview} />
        </SectionCard>

        <SectionCard
          title="情感趋势"
          subtitle={`近${labelDays}天帖子量与情感走势`}
          icon={<TrendingUp className="w-5 h-5 text-primary" strokeWidth={1.5} />}
          action={{ label: '查看详情', onClick: () => setShowTrendModal(true) }}
        >
          <div className="flex items-center gap-2 mb-4">
            <span className="text-tiny text-foreground-muted bg-surface-tertiary px-2 py-1 rounded-button">近{labelDays}天</span>
            <div className="ml-auto flex items-center gap-1.5">
              {trendSummary.up ? (
                <TrendingUp className="w-4 h-4 text-status-success" strokeWidth={1.5} />
              ) : (
                <TrendingDown className="w-4 h-4 text-status-error" strokeWidth={1.5} />
              )}
              <span className={`text-body-sm font-medium ${trendSummary.up ? 'text-status-success' : 'text-status-error'}`}>
                {trendSummary.up ? '+' : ''}{trendSummary.change}%
              </span>
            </div>
          </div>

          <SentimentTrendChart
            data={trendData.map((d) => ({ label: d.date, positive: d.positive, negative: d.negative, neutral: d.neutral }))}
            title={`近${labelDays}天情感趋势`}
            height={240}
          />
        </SectionCard>
      </div>

      <SectionCard
        title="社区情感热力"
        subtitle="各 subreddit 的情感构成与讨论热度"
        icon={<Users className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '查看全部', onClick: () => setShowHeatmapModal(true) }}
      >
        <SubredditHeatmap timeRange={timeRange} />
      </SectionCard>

      {/* 情感趋势详情弹窗 */}
      <DetailModal
        open={showTrendModal}
        onClose={() => setShowTrendModal(false)}
        title="情感趋势详情"
        subtitle={`近${labelDays}天情感走势数据`}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-divider">
                <th className="text-left py-3 px-2 text-tiny font-medium text-foreground-muted">日期</th>
                <th className="text-right py-3 px-2 text-tiny font-medium text-foreground-muted">正面</th>
                <th className="text-right py-3 px-2 text-tiny font-medium text-foreground-muted">负面</th>
                <th className="text-right py-3 px-2 text-tiny font-medium text-foreground-muted">中性</th>
                <th className="text-right py-3 px-2 text-tiny font-medium text-foreground-muted">总量</th>
              </tr>
            </thead>
            <tbody>
              {trendData.map((d) => (
                <tr key={d.date} className="border-b border-border-divider/50 hover:bg-surface-tertiary/50">
                  <td className="py-3 px-2 text-foreground">{d.date}</td>
                  <td className="text-right py-3 px-2 text-status-success">{d.positive}</td>
                  <td className="text-right py-3 px-2 text-status-error">{d.negative}</td>
                  <td className="text-right py-3 px-2 text-status-warning">{d.neutral}</td>
                  <td className="text-right py-3 px-2 font-medium text-foreground">{d.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DetailModal>

      {/* 社区情感热力详情弹窗 */}
      <DetailModal
        open={showHeatmapModal}
        onClose={() => setShowHeatmapModal(false)}
        title="社区情感热力详情"
        subtitle="各 subreddit 的完整情感构成与讨论热度"
      >
        <div className="space-y-4">
          {getSentimentBySubreddit(timeRange).map((s) => {
            const total = s.positive + s.neutral + s.negative;
            const pPos = Math.round((s.positive / total) * 100);
            const pNeu = Math.round((s.neutral / total) * 100);
            const pNeg = Math.round((s.negative / total) * 100);
            return (
              <div key={s.name} className="card p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-body-sm font-medium text-foreground">r/{s.name}</span>
                  <span className="text-caption text-foreground-muted">{total} 帖</span>
                </div>
                <div className="flex h-2.5 rounded-full overflow-hidden bg-surface-tertiary mb-2">
                  <div className="h-full bg-status-success" style={{ width: `${pPos}%` }} />
                  <div className="h-full bg-status-warning" style={{ width: `${pNeu}%` }} />
                  <div className="h-full bg-status-error" style={{ width: `${pNeg}%` }} />
                </div>
                <div className="flex items-center gap-4 text-tiny">
                  <span className="text-status-success">{pPos}% 正面</span>
                  <span className="text-status-warning">{pNeu}% 中性</span>
                  <span className="text-status-error">{pNeg}% 负面</span>
                </div>
              </div>
            );
          })}
        </div>
      </DetailModal>
    </div>
  );
}
