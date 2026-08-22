import { useState, useMemo } from 'react';
import {
  Users,
  TrendingUp,
  TrendingDown,
  Minus,
  Inbox,
  Award,
  CheckCircle2,
} from 'lucide-react';
import SectionCard from './SectionCard';
import DetailModal from './DetailModal';
import { getInfluencers, getInfluencerSegments, type InfluencerData } from '../data/influencerMock';
import { PieChart } from './charts';
import type { TimeRange } from '../types';
import { CHART_PALETTE, BRAND_COLORS } from '../constants/colors';

interface InfluencerIdentificationProps {
  timeRange?: TimeRange;
}

const trendIcons = {
  up: <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} />,
  down: <TrendingDown className="w-3.5 h-3.5" strokeWidth={1.5} />,
  stable: <Minus className="w-3.5 h-3.5" strokeWidth={1.5} />,
};

const trendLabels = {
  up: '上升',
  down: '下降',
  stable: '平稳',
};

function InfluencerAvatar({ name }: { name: string }) {
  const initial = name.charAt(0).toUpperCase();
  const colors = CHART_PALETTE.slice(0, 6);
  const color = colors[name.length % colors.length];

  return (
    <div
      className="w-10 h-10 rounded-full flex items-center justify-center text-white font-semibold text-sm flex-shrink-0"
      style={{ backgroundColor: color }}
    >
      {initial}
    </div>
  );
}

function InfluencerCard({ influencer }: { influencer: InfluencerData }) {
  const sentimentColor =
    influencer.avgSentiment > 0.5 ? 'text-status-success' : influencer.avgSentiment > 0 ? 'text-status-warning' : 'text-status-error';

  return (
    <div className="card p-5 hover:shadow-card-hover transition-all duration-300 group">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <InfluencerAvatar name={influencer.displayName} />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-h4 font-semibold text-foreground">{influencer.displayName}</span>
              {influencer.isVerified && (
                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-badge bg-status-infoBg text-status-info text-tiny">
                  <CheckCircle2 className="w-3 h-3" strokeWidth={1.5} />
                  认证
                </span>
              )}
            </div>
            <span className="text-caption text-foreground-muted">u/{influencer.username}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="flex items-center gap-1 justify-end">
            <Award className="w-4 h-4 text-status-warning" strokeWidth={1.5} />
            <span className="text-body font-semibold text-foreground">{influencer.influenceScore}</span>
          </div>
          <span className="text-tiny text-foreground-muted">影响力分</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="rounded-icon bg-surface-tertiary p-3 text-center">
          <span className="text-tiny text-foreground-muted block mb-1">帖子</span>
          <span className="text-body font-semibold text-foreground">{influencer.postCount}</span>
        </div>
        <div className="rounded-icon bg-surface-tertiary p-3 text-center">
          <span className="text-tiny text-foreground-muted block mb-1">互动</span>
          <span className="text-body font-semibold text-foreground">{influencer.totalEngagement.toLocaleString()}</span>
        </div>
        <div className="rounded-icon bg-surface-tertiary p-3 text-center">
          <span className="text-tiny text-foreground-muted block mb-1">情感</span>
          <span className={`text-body font-semibold ${sentimentColor}`}>
            {influencer.avgSentiment > 0 ? '+' : ''}
            {influencer.avgSentiment.toFixed(2)}
          </span>
        </div>
      </div>

      <div className="mb-3">
        <span className="text-tiny text-foreground-muted block mb-1.5">活跃社区</span>
        <div className="flex flex-wrap gap-1.5">
          {influencer.topSubreddits.map((s) => (
            <span key={s} className="px-2 py-0.5 rounded-badge bg-surface-tertiary text-caption text-foreground-secondary">
              r/{s}
            </span>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between pt-3 border-t border-border-divider">
        <div className="flex items-center gap-1">
          <span className="text-tiny text-foreground-muted">趋势</span>
          <span
            className={`inline-flex items-center gap-0.5 text-tiny ${
              influencer.trend === 'up' ? 'text-status-success' : influencer.trend === 'down' ? 'text-status-error' : 'text-foreground-muted'
            }`}
          >
            {trendIcons[influencer.trend]}
            {trendLabels[influencer.trend]}
          </span>
        </div>
        <span className="text-tiny text-foreground-muted">活跃 {influencer.lastActive}</span>
      </div>
    </div>
  );
}

function InfluencerTable({ influencers: data }: { influencers: InfluencerData[] }) {
  return (
    <div className="overflow-x-auto -mx-6">
      <table className="w-full min-w-[700px]">
        <thead>
          <tr className="border-b border-border-divider">
            <th className="text-left px-6 py-3 text-tiny font-medium text-foreground-muted">影响者</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">影响力</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">帖子</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">互动</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">情感</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">趋势</th>
            <th className="text-left px-4 py-3 text-tiny font-medium text-foreground-muted">认证</th>
          </tr>
        </thead>
        <tbody>
          {data.map((influencer) => {
            const sentimentColor =
              influencer.avgSentiment > 0.5
                ? 'text-status-success'
                : influencer.avgSentiment > 0
                ? 'text-status-warning'
                : 'text-status-error';

            return (
              <tr key={influencer.id} className="border-b border-border-divider hover:bg-surface-tertiary/50 transition-colors">
                <td className="px-6 py-3">
                  <div className="flex items-center gap-2">
                    <InfluencerAvatar name={influencer.displayName} />
                    <div>
                      <div className="text-body-sm font-medium text-foreground">{influencer.displayName}</div>
                      <div className="text-caption text-foreground-muted">u/{influencer.username}</div>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 rounded-full bg-surface-tertiary overflow-hidden">
                      <div className="h-full bg-primary rounded-full" style={{ width: `${influencer.influenceScore}%` }} />
                    </div>
                    <span className="text-body-sm font-medium text-foreground">{influencer.influenceScore}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-body-sm text-foreground-secondary">{influencer.postCount}</td>
                <td className="px-4 py-3 text-body-sm text-foreground-secondary">{influencer.totalEngagement.toLocaleString()}</td>
                <td className="px-4 py-3">
                  <span className={`text-body-sm font-medium ${sentimentColor}`}>
                    {influencer.avgSentiment > 0 ? '+' : ''}
                    {influencer.avgSentiment.toFixed(2)}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex items-center gap-0.5 text-tiny ${
                      influencer.trend === 'up' ? 'text-status-success' : influencer.trend === 'down' ? 'text-status-error' : 'text-foreground-muted'
                    }`}
                  >
                    {trendIcons[influencer.trend]}
                    {trendLabels[influencer.trend]}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {influencer.isVerified ? (
                    <span className="inline-flex items-center gap-0.5 text-tiny text-status-info">
                      <CheckCircle2 className="w-3.5 h-3.5" strokeWidth={1.5} />
                      已认证
                    </span>
                  ) : (
                    <span className="text-tiny text-foreground-muted">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-14 h-14 rounded-full bg-surface-tertiary flex items-center justify-center mb-4">
        <Inbox className="w-7 h-7 text-foreground-muted" strokeWidth={1.5} />
      </div>
      <h3 className="text-body font-medium text-foreground mb-1">暂无影响者数据</h3>
      <p className="text-caption text-foreground-secondary">当前时间范围内没有识别到高影响力用户</p>
    </div>
  );
}

export default function InfluencerIdentification({ timeRange = '7d' }: InfluencerIdentificationProps) {
  const [viewMode, setViewMode] = useState<'card' | 'table'>('card');
  const [showModal, setShowModal] = useState(false);
  const influencers = getInfluencers(timeRange);
  const segments = getInfluencerSegments(timeRange);

  const segmentChartData = useMemo(() => {
    return segments.map((s) => ({
      name: s.name,
      value: s.count,
      color: s.name === '专家型' ? BRAND_COLORS.primary : s.name === '经验型' ? BRAND_COLORS.secondary : BRAND_COLORS.tertiary,
    }));
  }, [segments]);

  if (!influencers || influencers.length === 0) {
    return (
      <SectionCard
        title="影响者识别"
        subtitle="识别 Reddit 上的高影响力用户与潜在 KOL"
        icon={<Users className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '查看全部', onClick: () => setShowModal(true) }}
      >
        <EmptyState />
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="影响者识别"
      subtitle="识别 Reddit 上的高影响力用户与潜在 KOL"
      icon={<Users className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '查看全部', onClick: () => setShowModal(true) }}
    >
      <div className="flex items-center gap-2 mb-5">
        {([
          { key: 'card' as const, label: '卡片视图' },
          { key: 'table' as const, label: '数据表格' },
        ]).map((v) => (
          <button
            key={v.key}
            onClick={() => setViewMode(v.key)}
            className={`px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
              viewMode === v.key
                ? 'bg-primary text-white'
                : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <div className="lg:col-span-1">
          <div className="text-body font-medium text-foreground mb-3">影响者类型分布</div>
          <PieChart data={segmentChartData} height={220} showLegend={true} innerRadius={0.5} />
        </div>
        <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-3 gap-4">
          {segments.map((seg) => (
            <div key={seg.name} className="card p-4">
              <div className="text-tiny text-foreground-muted mb-1">{seg.name}</div>
              <div className="text-h3 font-semibold text-foreground mb-1">{seg.count}</div>
              <div className="text-caption text-foreground-secondary mb-2">{seg.description}</div>
              <div className="flex items-center gap-1">
                <span className="text-tiny text-foreground-muted">平均影响力:</span>
                <span className="text-tiny font-medium text-primary">{seg.avgInfluenceScore}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {viewMode === 'card' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {influencers.map((influencer) => (
            <InfluencerCard key={influencer.id} influencer={influencer} />
          ))}
        </div>
      ) : (
        <InfluencerTable influencers={influencers} />
      )}

      <DetailModal
        open={showModal}
        onClose={() => setShowModal(false)}
        title="影响者识别详情"
        subtitle="Reddit 上的高影响力用户与潜在 KOL 完整列表"
      >
        <InfluencerTable influencers={influencers} />
      </DetailModal>
    </SectionCard>
  );
}
