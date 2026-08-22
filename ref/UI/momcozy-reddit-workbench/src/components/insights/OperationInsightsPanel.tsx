import type { ElementType } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Gauge,
  Users,
  Lightbulb,
} from 'lucide-react';
import type { InsightsData } from '../../services/insightService';
import type { OperationInsight, TeamWorkload, BestPractice } from '../../data/insightsMock';
import SectionCard from '../SectionCard';
import HighlightText from '../HighlightText';

interface Props {
  data: InsightsData;
  searchQuery?: string;
}

export default function OperationInsightsPanel({ data, searchQuery = '' }: Props) {
  const { operationInsights, teamWorkloads, bestPractices } = data;
  const trendConfig: Record<'up' | 'down' | 'stable', { icon: ElementType; color: string }> = {
    up: { icon: TrendingUp, color: 'text-status-success' },
    down: { icon: TrendingDown, color: 'text-status-error' },
    stable: { icon: Minus, color: 'text-foreground-muted' },
  };

  const q = searchQuery.toLowerCase();
  const filteredOps = q
    ? operationInsights.filter((i) => i.title.toLowerCase().includes(q))
    : operationInsights;
  const filteredTeam = q
    ? teamWorkloads.filter((w) => w.member.toLowerCase().includes(q))
    : teamWorkloads;
  const filteredBP = q
    ? bestPractices.filter((bp) => bp.title.toLowerCase().includes(q) || bp.description.toLowerCase().includes(q))
    : bestPractices;

  const empty = (
    <div className="text-center py-8 text-body-sm text-foreground-muted">
      未找到匹配 "{searchQuery}" 的结果
    </div>
  );

  return (
    <div className="space-y-6">
      <SectionCard title="运营效率指标" subtitle="核心运营效率监控" tag="运营" icon={<Gauge className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        {filteredOps.length === 0 ? (
          empty
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {filteredOps.map((item: OperationInsight) => {
              const TrendIcon = trendConfig[item.trend].icon;
              return (
                <div key={item.id} className="card p-5 hover:shadow-card-hover transition-all duration-300">
                  <div className="text-caption text-foreground-muted">
                    <HighlightText text={item.title} keyword={searchQuery} />
                  </div>
                  <div className="flex items-end gap-2 mt-2">
                    <span className="text-[24px] font-semibold text-foreground">{item.value}</span>
                    <span className="text-body-sm text-foreground-muted mb-1">{item.unit}</span>
                  </div>
                  <div className="text-tiny text-foreground-muted mt-1">目标 {item.target}{item.unit}</div>
                  <div className={`inline-flex items-center gap-1 text-tiny font-medium mt-2 ${trendConfig[item.trend].color}`}>
                    <TrendIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                    {item.change >= 0 ? '+' : ''}{item.change}%
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </SectionCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title="团队工作负载" subtitle="各成员任务分配与效率" tag="运营" icon={<Users className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          {filteredTeam.length === 0 ? (
            empty
          ) : (
            <div className="space-y-3">
              {filteredTeam.map((member: TeamWorkload) => (
                <div key={member.member} className="flex items-center gap-4 p-3 rounded-xl border border-border-divider bg-white">
                  <div className="w-10 h-10 rounded-full bg-primary-light flex items-center justify-center">
                    <span className="text-sm font-medium text-primary">{member.member.slice(-1)}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-body-sm font-medium text-foreground">
                      <HighlightText text={member.member} keyword={searchQuery} />
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-tiny text-foreground-muted">
                      <span>{member.tasksCompleted}/{member.tasksAssigned} 任务</span>
                      <span>平均响应 {member.avgResponseTime}分钟</span>
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-h4 font-semibold text-foreground">{member.efficiency}</div>
                    <div className="text-tiny text-foreground-muted">效率</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="最佳实践推荐" subtitle="可复用的运营策略" tag="运营" icon={<Lightbulb className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          {filteredBP.length === 0 ? (
            empty
          ) : (
            <div className="space-y-3">
              {filteredBP.map((bp: BestPractice) => (
                <div key={bp.id} className="p-4 rounded-xl border border-border-divider bg-white hover:shadow-card-hover transition-all duration-200">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-body-sm font-medium text-foreground">
                      <HighlightText text={bp.title} keyword={searchQuery} />
                    </span>
                    <span className={`text-tiny font-medium px-2 py-0.5 rounded-badge ${
                      bp.impact === 'high' ? 'bg-status-successBg text-status-success' : 'bg-status-warningBg text-status-warning'
                    }`}>
                      {bp.impact === 'high' ? '高影响' : '中影响'}
                    </span>
                  </div>
                  <p className="text-caption text-foreground-secondary">
                    <HighlightText text={bp.description} keyword={searchQuery} />
                  </p>
                  <div className="mt-2 text-tiny text-foreground-muted">已应用 {bp.appliedCount} 次</div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
