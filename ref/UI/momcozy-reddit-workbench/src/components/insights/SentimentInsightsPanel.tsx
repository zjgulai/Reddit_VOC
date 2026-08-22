import {
  AlertCircle,
  ShieldAlert,
  Flame,
  BrainCircuit,
  BarChart3,
  Tag,
  ArrowRight,
} from 'lucide-react';
import SectionCard from '../SectionCard';
import HighlightText from '../HighlightText';
import type { InsightsData } from '../../services/insightService';
import { StackedBarChart, SankeyChart, WordCloudChart } from '../charts';
import { CHART_PALETTE } from '../../constants/colors';

interface Props {
  data: InsightsData;
  searchQuery?: string;
}

export default function SentimentInsightsPanel({ data, searchQuery = '' }: Props) {
  const { sentimentTrendHistory, warningHistory, negativeSpreads, crisisReviews, sentimentSankeyNodes, sentimentSankeyLinks, sentimentWordCloudData } = data;

  const statusConfig = {
    resolved: { label: '已解决', color: 'text-status-success', bg: 'bg-status-successBg' },
    pending: { label: '处理中', color: 'text-status-warning', bg: 'bg-status-warningBg' },
    escalated: { label: '已升级', color: 'text-status-error', bg: 'bg-status-errorBg' },
  };

  const levelConfig = {
    critical: { color: 'text-status-error', bg: 'bg-status-errorBg' },
    warning: { color: 'text-status-warning', bg: 'bg-status-warningBg' },
    info: { color: 'text-status-info', bg: 'bg-status-infoBg' },
  };

  const q = searchQuery.toLowerCase();
  const filteredWarnings = q
    ? warningHistory.filter((w) => w.title.toLowerCase().includes(q))
    : warningHistory;
  const filteredSpreads = q
    ? negativeSpreads.filter((ns) => ns.source.toLowerCase().includes(q) || ns.spreadPath.some((p) => p.toLowerCase().includes(q)))
    : negativeSpreads;
  const filteredCrisis = q
    ? crisisReviews.filter((cr) => cr.title.toLowerCase().includes(q) || cr.resolution.toLowerCase().includes(q) || cr.lesson.toLowerCase().includes(q))
    : crisisReviews;

  const empty = (
    <div className="text-center py-8 text-body-sm text-foreground-muted">
      未找到匹配 "{searchQuery}" 的结果
    </div>
  );

  return (
    <div className="space-y-6">
      <SectionCard title="情感趋势" subtitle="7天情感分布与预警数量" tag="舆情" icon={<ShieldAlert className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <StackedBarChart
          data={sentimentTrendHistory.map((s) => ({
            name: s.date,
            正面: s.positive,
            负面: s.negative,
            中性: s.neutral,
          }))}
          keys={[
            { key: '正面', color: CHART_PALETTE[4], name: '正面' },
            { key: '负面', color: CHART_PALETTE[2], name: '负面' },
            { key: '中性', color: CHART_PALETTE[1], name: '中性' },
          ]}
          title="情感趋势分布"
          height={260}
        />
      </SectionCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title="预警历史" subtitle="近期预警事件处理状态" tag="舆情" icon={<ShieldAlert className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          {filteredWarnings.length === 0 ? (
            empty
          ) : (
            <div className="space-y-3">
              {filteredWarnings.map((w) => (
                <div key={w.id} className="flex items-start gap-3 p-3 rounded-xl border border-border-divider bg-white">
                  <div className={`w-8 h-8 rounded-icon flex items-center justify-center shrink-0 ${levelConfig[w.level].bg}`}>
                    <AlertCircle className={`w-4 h-4 ${levelConfig[w.level].color}`} strokeWidth={1.5} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-body-sm font-medium text-foreground">
                      <HighlightText text={w.title} keyword={searchQuery} />
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-tiny text-foreground-muted">
                      <span>{w.date}</span>
                      <span>响应 {w.responseTime}</span>
                    </div>
                  </div>
                  <span className={`text-tiny font-medium px-2 py-0.5 rounded-badge ${statusConfig[w.status].bg} ${statusConfig[w.status].color}`}>
                    {statusConfig[w.status].label}
                  </span>
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="负面传播路径" subtitle="负面信息传播路径与 containment" tag="舆情" icon={<Flame className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          {filteredSpreads.length === 0 ? (
            empty
          ) : (
            <div className="space-y-3">
              {filteredSpreads.map((ns, i) => (
                <div key={i} className="p-4 rounded-xl border border-border-divider bg-white">
                  <div className="text-body-sm font-medium text-foreground mb-2">
                    <HighlightText text={ns.source} keyword={searchQuery} />
                  </div>
                  <div className="flex items-center gap-2 flex-wrap mb-2">
                    {ns.spreadPath.map((path, j) => (
                      <span key={path} className="inline-flex items-center gap-2">
                        <span className="text-tiny text-foreground-secondary bg-surface-tertiary px-2 py-1 rounded-badge">
                          <HighlightText text={path} keyword={searchQuery} />
                        </span>
                        {j < ns.spreadPath.length - 1 && (
                          <ArrowRight className="w-3.5 h-3.5 text-foreground-muted" strokeWidth={1.5} />
                        )}
                      </span>
                    ))}
                  </div>
                  <div className="flex items-center gap-4 text-tiny text-foreground-muted">
                    <span>影响 {ns.affectedPosts} 帖</span>
                    <span>遏制时间 {ns.containmentTime}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </div>

      <SectionCard title="危机处理复盘" subtitle="重大舆情事件处理总结" tag="舆情" icon={<BrainCircuit className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        {filteredCrisis.length === 0 ? (
          empty
        ) : (
          <div className="space-y-3">
            {filteredCrisis.map((cr) => (
              <div key={cr.id} className="p-4 rounded-xl border border-border-divider bg-white">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-body-sm font-medium text-foreground">
                    <HighlightText text={cr.title} keyword={searchQuery} />
                  </span>
                  <span className="text-tiny text-foreground-muted">{cr.date}</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-2">
                  <div className="bg-surface-tertiary rounded-lg p-2">
                    <div className="text-tiny text-foreground-muted">严重度</div>
                    <div className="text-body-sm font-medium text-status-error">{cr.severity === 'high' ? '高' : cr.severity === 'medium' ? '中' : '低'}</div>
                  </div>
                  <div className="bg-surface-tertiary rounded-lg p-2">
                    <div className="text-tiny text-foreground-muted">响应时间</div>
                    <div className="text-body-sm font-medium text-foreground">{cr.responseTime}</div>
                  </div>
                  <div className="bg-surface-tertiary rounded-lg p-2">
                    <div className="text-tiny text-foreground-muted">处理方式</div>
                    <div className="text-body-sm font-medium text-foreground">
                      <HighlightText text={cr.resolution} keyword={searchQuery} />
                    </div>
                  </div>
                </div>
                <div className="text-tiny text-status-success bg-status-successBg rounded-lg px-3 py-2">
                  <span className="font-medium">经验：</span>
                  <HighlightText text={cr.lesson} keyword={searchQuery} />
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* 桑基图 + 词云 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title="舆情流向分析" subtitle="情感 → 意图 → 社区关联分布" tag="舆情" icon={<BarChart3 className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          <SankeyChart
            nodes={sentimentSankeyNodes}
            links={sentimentSankeyLinks}
            height={320}
            nodeWidth={18}
            nodePadding={14}
          />
        </SectionCard>

        <SectionCard title="关键词云" subtitle="高频提及词与情感置信度" tag="舆情" icon={<Tag className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          <WordCloudChart
            data={sentimentWordCloudData}
            height={320}
          />
        </SectionCard>
      </div>
    </div>
  );
}
