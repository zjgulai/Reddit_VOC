import { useState } from 'react';
import { MessageCircle, TrendingUp, TrendingDown, Minus, ArrowUpRight, Inbox } from 'lucide-react';
import SectionCard from './SectionCard';
import DetailModal from './DetailModal';
import { getTopicClusters, type TopicCluster as TopicClusterType } from '../data/analyticsMock';
import type { TimeRange } from '../types';

interface TopicClusterProps {
  timeRange?: TimeRange;
}

const vibeColors: Record<string, string> = {
  positive: 'bg-status-successBg text-status-success border-status-successBg',
  neutral: 'bg-status-warningBg text-status-warning border-status-warningBg',
  negative: 'bg-status-errorBg text-status-error border-status-errorBg',
};

const vibeLabels: Record<string, string> = {
  positive: '正面',
  neutral: '中性',
  negative: '负面',
};

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

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-14 h-14 rounded-full bg-surface-tertiary flex items-center justify-center mb-4">
        <Inbox className="w-7 h-7 text-foreground-muted" strokeWidth={1.5} />
      </div>
      <h3 className="text-body font-medium text-foreground mb-1">暂无话题聚类数据</h3>
      <p className="text-caption text-foreground-secondary">当前时间范围内没有足够的数据生成话题聚类</p>
    </div>
  );
}

function BubbleView({ clusters }: { clusters: TopicClusterType[] }) {
  if (clusters.length === 0) return <EmptyState />;

  const maxCount = Math.max(...clusters.map((c) => c.count));
  const minCount = Math.min(...clusters.map((c) => c.count));

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      {clusters.map((cluster) => {
        const sizeRatio = (cluster.count - minCount) / (maxCount - minCount || 1);
        const bubbleSize = 80 + sizeRatio * 60;

        const bgOpacity = 0.06 + sizeRatio * 0.1;
        const bgColor =
          cluster.sentiment === 'positive'
            ? `rgba(45, 138, 94, ${bgOpacity})`
            : cluster.sentiment === 'negative'
            ? `rgba(196, 90, 108, ${bgOpacity})`
            : `rgba(212, 148, 10, ${bgOpacity})`;

        return (
          <div
            key={cluster.id}
            className="flex flex-col items-center justify-center p-5 rounded-card transition-all duration-300 hover:shadow-card-hover cursor-pointer group"
            style={{ backgroundColor: bgColor, minHeight: bubbleSize }}
          >
            <span className="text-h3 font-semibold text-foreground group-hover:text-primary transition-colors">
              {cluster.count}
            </span>
            <span className="text-body-sm font-medium text-foreground-secondary text-center mt-1">
              {cluster.name}
            </span>
            <div className="flex items-center gap-2 mt-2">
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-badge text-tiny border ${vibeColors[cluster.sentiment]}`}>
                {vibeLabels[cluster.sentiment]}
              </span>
              <span
                className={`inline-flex items-center gap-0.5 text-tiny ${
                  cluster.trend === 'up' ? 'text-status-success' : cluster.trend === 'down' ? 'text-status-error' : 'text-foreground-muted'
                }`}
              >
                {trendIcons[cluster.trend]}
                {cluster.growth > 0 ? '+' : ''}{cluster.growth}%
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ListView({ clusters }: { clusters: TopicClusterType[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (clusters.length === 0) return <EmptyState />;

  return (
    <div className="space-y-3">
      {clusters.map((cluster, idx) => {
        const isExpanded = expandedId === cluster.id;
        const maxCount = Math.max(...clusters.map((c) => c.count));
        const barWidth = (cluster.count / maxCount) * 100;

        return (
          <div
            key={cluster.id}
            className="rounded-card border border-border-divider overflow-hidden transition-all duration-200 hover:border-border-hover"
          >
            <button
              onClick={() => setExpandedId(isExpanded ? null : cluster.id)}
              className="w-full flex items-center gap-4 p-4 text-left"
            >
              <span className="text-caption text-foreground-muted w-6">{String(idx + 1).padStart(2, '0')}</span>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 mb-1.5">
                  <span className="text-body font-medium text-foreground">{cluster.name}</span>
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-badge text-tiny ${vibeColors[cluster.sentiment]}`}>
                    {vibeLabels[cluster.sentiment]}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex-1 h-1.5 rounded-full bg-surface-tertiary overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        cluster.sentiment === 'positive'
                          ? 'bg-status-success'
                          : cluster.sentiment === 'negative'
                          ? 'bg-status-error'
                          : 'bg-status-warning'
                      }`}
                      style={{ width: `${barWidth}%` }}
                    />
                  </div>
                  <span className="text-body-sm font-semibold text-foreground w-10 text-right">{cluster.count}</span>
                </div>
              </div>

              <div className="flex items-center gap-1 text-foreground-muted">
                {trendIcons[cluster.trend]}
                <span
                  className={`text-tiny ${
                    cluster.trend === 'up' ? 'text-status-success' : cluster.trend === 'down' ? 'text-status-error' : ''
                  }`}
                >
                  {trendLabels[cluster.trend]}
                </span>
              </div>

              <ArrowUpRight
                className={`w-4 h-4 text-foreground-muted transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                strokeWidth={1.5}
              />
            </button>

            {isExpanded && (
              <div className="px-4 pb-4 pt-0 border-t border-border-divider">
                <div className="pt-3 space-y-3">
                  <div>
                    <span className="text-tiny text-foreground-muted block mb-1.5">关联话题</span>
                    <div className="flex flex-wrap gap-1.5">
                      {cluster.relatedTopics.map((t) => (
                        <span key={t} className="px-2.5 py-1 rounded-badge bg-surface-tertiary text-caption text-foreground-secondary">
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div>
                    <span className="text-tiny text-foreground-muted block mb-1.5">高频关键词</span>
                    <div className="flex flex-wrap gap-1.5">
                      {cluster.keywords.map((k) => (
                        <span key={k} className="px-2.5 py-1 rounded-badge bg-primary-light text-caption text-primary">
                          {k}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function TopicCluster({ timeRange = '7d' }: TopicClusterProps) {
  const [viewMode, setViewMode] = useState<'bubble' | 'list'>('bubble');
  const [showModal, setShowModal] = useState(false);
  const clusters = getTopicClusters(timeRange);

  return (
    <SectionCard
      title="话题聚类"
      subtitle="基于讨论内容自动聚合的热门话题分布"
      icon={<MessageCircle className="w-5 h-5 text-primary" strokeWidth={1.5} />}
      action={{ label: '全部话题', onClick: () => setShowModal(true) }}
    >
      <div className="flex items-center gap-2 mb-5">
        {([
          { key: 'bubble' as const, label: '气泡图' },
          { key: 'list' as const, label: '列表' },
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

      {viewMode === 'bubble' ? <BubbleView clusters={clusters} /> : <ListView clusters={clusters} />}

      <DetailModal
        open={showModal}
        onClose={() => setShowModal(false)}
        title="全部话题"
        subtitle="基于讨论内容自动聚合的热门话题完整列表"
      >
        <div className="space-y-3">
          {clusters.map((cluster, idx) => (
            <div key={cluster.id} className="card p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-caption text-foreground-muted w-6">{String(idx + 1).padStart(2, '0')}</span>
                  <span className="text-body-sm font-medium text-foreground">{cluster.name}</span>
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-badge text-tiny ${vibeColors[cluster.sentiment]}`}>
                    {vibeLabels[cluster.sentiment]}
                  </span>
                </div>
                <span className="text-body-sm font-semibold text-foreground">{cluster.count}</span>
              </div>
              <div className="flex items-center gap-2 mb-2">
                <span className={`inline-flex items-center gap-0.5 text-tiny ${cluster.trend === 'up' ? 'text-status-success' : cluster.trend === 'down' ? 'text-status-error' : 'text-foreground-muted'}`}>
                  {trendIcons[cluster.trend]}
                  {cluster.growth > 0 ? '+' : ''}{cluster.growth}%
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {cluster.keywords.map((k) => (
                  <span key={k} className="px-2 py-0.5 rounded-badge bg-primary-light text-caption text-primary">
                    {k}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </DetailModal>
    </SectionCard>
  );
}
