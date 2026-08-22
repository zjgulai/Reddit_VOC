import { useState, useMemo } from 'react';
import { Cloud, Tag, Inbox, Info } from 'lucide-react';
import SectionCard from './SectionCard';
import DetailModal from './DetailModal';
import WordCloudChart from './charts/WordCloudChart';
import {
  getEnhancedWordCloudData,
  wordCloudCategories,
  sentimentColorMap,
  type WordCloudCategory,
  type WordCloudSentiment,
} from '../data/enhancedWordCloudMock';
import type { TimeRange } from '../types';

interface EnhancedWordCloudProps {
  timeRange?: TimeRange;
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-14 h-14 rounded-full bg-surface-tertiary flex items-center justify-center mb-4">
        <Inbox className="w-7 h-7 text-foreground-muted" strokeWidth={1.5} />
      </div>
      <h3 className="text-body font-medium text-foreground mb-1">暂无词云数据</h3>
      <p className="text-caption text-foreground-secondary">当前时间范围内没有足够的数据生成词云</p>
    </div>
  );
}

export default function EnhancedWordCloud({ timeRange = '7d' }: EnhancedWordCloudProps) {
  const [activeCategory, setActiveCategory] = useState<WordCloudCategory | 'all'>('all');
  const [hoveredSentiment, setHoveredSentiment] = useState<WordCloudSentiment | null>(null);
  const [showModal, setShowModal] = useState(false);

  const rawData = useMemo(() => getEnhancedWordCloudData(timeRange), [timeRange]);

  const filteredData = useMemo(() => {
    let data = rawData;
    if (activeCategory !== 'all') {
      data = data.filter((d) => d.category === activeCategory);
    }
    return data.map((d) => ({
      text: d.text,
      value: d.value,
      color: sentimentColorMap[d.sentiment],
      sourcePostIds: d.sourcePostIds,
      sentimentConfidence: d.sentimentConfidence,
    }));
  }, [rawData, activeCategory]);

  const stats = useMemo(() => {
    const total = rawData.length;
    const positive = rawData.filter((d) => d.sentiment === 'positive').length;
    const negative = rawData.filter((d) => d.sentiment === 'negative').length;
    const neutral = rawData.filter((d) => d.sentiment === 'neutral').length;
    const avgConfidence = rawData.reduce((sum, d) => sum + d.sentimentConfidence, 0) / (total || 1);
    const totalSourcePosts = new Set(rawData.flatMap((d) => d.sourcePostIds)).size;
    return { total, positive, negative, neutral, avgConfidence, totalSourcePosts };
  }, [rawData]);

  const categoryStats = useMemo(() => {
    return wordCloudCategories
      .filter((c) => c.key !== 'all')
      .map((c) => ({
        key: c.key,
        label: c.label,
        count: rawData.filter((d) => d.category === c.key).length,
      }));
  }, [rawData]);

  if (!rawData || rawData.length === 0) {
    return (
      <SectionCard
        title="增强词云"
        subtitle="基于情感与分类的多维关键词可视化"
        icon={<Cloud className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '查看全部', onClick: () => setShowModal(true) }}
      >
        <EmptyState />
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="增强词云"
      subtitle="基于情感与分类的多维关键词可视化"
      icon={<Cloud className="w-5 h-5 text-primary" strokeWidth={1.5} />}
      action={{ label: '查看全部', onClick: () => setShowModal(true) }}
    >
      <div className="space-y-5">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-center gap-2 flex-wrap">
            {wordCloudCategories.map((c) => (
              <button
                key={c.key}
                onClick={() => setActiveCategory(c.key)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
                  activeCategory === c.key
                    ? 'bg-primary text-white'
                    : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
                }`}
              >
                <Tag className="w-3.5 h-3.5" strokeWidth={1.5} />
                {c.label}
                {c.key !== 'all' && (
                  <span className={`ml-0.5 ${activeCategory === c.key ? 'text-white/80' : 'text-foreground-muted'}`}>
                    {categoryStats.find((s) => s.key === c.key)?.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <span className="text-tiny text-foreground-muted flex items-center gap-1">
              <Info className="w-3.5 h-3.5" strokeWidth={1.5} />
              情感颜色:
            </span>
            {(
              [
                { key: 'positive' as const, label: '正面', color: sentimentColorMap.positive },
                { key: 'neutral' as const, label: '中性', color: sentimentColorMap.neutral },
                { key: 'negative' as const, label: '负面', color: sentimentColorMap.negative },
              ] as const
            ).map((s) => (
              <button
                key={s.key}
                onMouseEnter={() => setHoveredSentiment(s.key)}
                onMouseLeave={() => setHoveredSentiment(null)}
                className="inline-flex items-center gap-1.5 text-tiny transition-opacity"
                style={{ opacity: hoveredSentiment && hoveredSentiment !== s.key ? 0.4 : 1 }}
              >
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }} />
                <span className="text-foreground-secondary">{s.label}</span>
                <span className="text-foreground-muted">
                  {s.key === 'positive' ? stats.positive : s.key === 'negative' ? stats.negative : stats.neutral}
                </span>
              </button>
            ))}
          </div>
        </div>

        <WordCloudChart data={filteredData} height={320} />

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <div className="rounded-icon bg-surface-tertiary p-3">
            <div className="text-tiny text-foreground-muted mb-1">总关键词</div>
            <div className="text-body font-semibold text-foreground">{stats.total}</div>
          </div>
          <div className="rounded-icon bg-status-successBg/50 p-3">
            <div className="text-tiny text-foreground-muted mb-1">正面词汇</div>
            <div className="text-body font-semibold text-status-success">{stats.positive}</div>
          </div>
          <div className="rounded-icon bg-surface-tertiary p-3">
            <div className="text-tiny text-foreground-muted mb-1">中性词汇</div>
            <div className="text-body font-semibold text-foreground-secondary">{stats.neutral}</div>
          </div>
          <div className="rounded-icon bg-status-errorBg/50 p-3">
            <div className="text-tiny text-foreground-muted mb-1">负面词汇</div>
            <div className="text-body font-semibold text-status-error">{stats.negative}</div>
          </div>
          <div className="rounded-icon bg-primary-light p-3">
            <div className="text-tiny text-foreground-muted mb-1">平均置信度</div>
            <div className="text-body font-semibold text-primary">{(stats.avgConfidence * 100).toFixed(0)}%</div>
          </div>
          <div className="rounded-icon bg-surface-tertiary p-3">
            <div className="text-tiny text-foreground-muted mb-1">来源帖子</div>
            <div className="text-body font-semibold text-foreground">{stats.totalSourcePosts}</div>
          </div>
        </div>
      </div>

      <DetailModal
        open={showModal}
        onClose={() => setShowModal(false)}
        title="词云详情"
        subtitle="基于情感与分类的多维关键词完整列表"
      >
        <div className="space-y-4">
          {rawData.map((d) => (
            <div key={d.text} className="flex items-center justify-between p-3 rounded-icon bg-surface-tertiary">
              <div className="flex items-center gap-3">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: sentimentColorMap[d.sentiment] }} />
                <span className="text-body-sm font-medium text-foreground">{d.text}</span>
                <span className="px-1.5 py-0.5 rounded-badge text-tiny bg-surface-warm text-foreground-muted">
                  {wordCloudCategories.find((c) => c.key === d.category)?.label || d.category}
                </span>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-tiny text-foreground-muted">置信度 {(d.sentimentConfidence * 100).toFixed(0)}%</span>
                <span className="text-body-sm font-semibold text-primary">{d.value}</span>
              </div>
            </div>
          ))}
        </div>
      </DetailModal>
    </SectionCard>
  );
}
