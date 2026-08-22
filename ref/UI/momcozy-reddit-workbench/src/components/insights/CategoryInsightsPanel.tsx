import {
  Funnel,
  ShoppingCart,
  ThumbsDown,
  MessageSquare,
  Crosshair,
} from 'lucide-react';
import SectionCard from '../SectionCard';
import HighlightText from '../HighlightText';
import type { InsightsData } from '../../services/insightService';
import { FunnelChart } from '../charts';

interface Props {
  data: InsightsData;
  searchQuery?: string;
}

export default function CategoryInsightsPanel({ data, searchQuery = '' }: Props) {
  const { productOpportunities, userPainPoints, productFeedbacks, marketGaps, categoryFunnelData } = data;

  const densityConfig = {
    low: { label: '低', color: 'text-status-success', bg: 'bg-status-successBg' },
    medium: { label: '中', color: 'text-status-warning', bg: 'bg-status-warningBg' },
    high: { label: '高', color: 'text-status-error', bg: 'bg-status-errorBg' },
  };

  const q = searchQuery.toLowerCase();
  const filteredOpportunities = q
    ? productOpportunities.filter((po) => po.title.toLowerCase().includes(q) || po.description.toLowerCase().includes(q))
    : productOpportunities;
  const filteredPainPoints = q
    ? userPainPoints.filter((up) => up.painPoint.toLowerCase().includes(q) || up.productCategory.toLowerCase().includes(q))
    : userPainPoints;
  const filteredFeedbacks = q
    ? productFeedbacks.filter((pf) => pf.product.toLowerCase().includes(q) || pf.feedback.toLowerCase().includes(q) || pf.source.toLowerCase().includes(q))
    : productFeedbacks;
  const filteredGaps = q
    ? marketGaps.filter((mg) => mg.gap.toLowerCase().includes(q) || mg.demandEvidence.toLowerCase().includes(q))
    : marketGaps;

  const empty = (
    <div className="text-center py-8 text-body-sm text-foreground-muted">
      未找到匹配 "{searchQuery}" 的结果
    </div>
  );

  return (
    <div className="space-y-6">
      <SectionCard title="用户需求转化漏斗" subtitle="从 Reddit 讨论到最终转化的全链路分析" tag="品类" icon={<Funnel className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <FunnelChart
              data={categoryFunnelData}
              title="转化漏斗"
              height={320}
            />
          </div>
          <div className="space-y-3">
            {categoryFunnelData.map((item, index) => {
              const prevValue = index > 0 ? categoryFunnelData[index - 1].value : item.value;
              const conversionRate = index > 0 ? Math.round((item.value / prevValue) * 100) : 100;
              return (
                <div key={item.name} className="p-3 rounded-xl border border-border-divider bg-white">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                      <span className="text-body-sm font-medium text-foreground">
                        <HighlightText text={item.name} keyword={searchQuery} />
                      </span>
                    </div>
                    <span className="text-body-sm font-semibold text-foreground">{item.value.toLocaleString()}</span>
                  </div>
                  {index > 0 && (
                    <div className="mt-1 text-tiny text-foreground-muted">
                      转化率 <span className="text-status-success font-medium">{conversionRate}%</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="新品机会" subtitle="基于用户需求的潜在新品方向" tag="品类" icon={<ShoppingCart className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        {filteredOpportunities.length === 0 ? (
          empty
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {filteredOpportunities.map((po) => (
              <div key={po.id} className="card p-5 hover:shadow-card-hover transition-all duration-300">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-body font-medium text-foreground">
                    <HighlightText text={po.title} keyword={searchQuery} />
                  </span>
                  <span className="text-tiny font-medium text-status-success bg-status-successBg px-2 py-0.5 rounded-badge">
                    ROI {po.potentialROI}x
                  </span>
                </div>
                <p className="text-caption text-foreground-secondary">
                  <HighlightText text={po.description} keyword={searchQuery} />
                </p>
                <div className="flex items-center gap-4 mt-3">
                  <div className="flex-1">
                    <div className="flex justify-between text-tiny text-foreground-muted mb-1">
                      <span>需求度</span>
                      <span>{po.demandScore}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-surface-tertiary overflow-hidden">
                      <div className="h-full rounded-full bg-primary" style={{ width: `${po.demandScore}%` }} />
                    </div>
                  </div>
                  <div className="flex-1">
                    <div className="flex justify-between text-tiny text-foreground-muted mb-1">
                      <span>竞争度</span>
                      <span>{po.competitionScore}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-surface-tertiary overflow-hidden">
                      <div className="h-full rounded-full bg-status-warning" style={{ width: `${po.competitionScore}%` }} />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title="用户痛点" subtitle="各品类用户痛点聚类" tag="品类" icon={<ThumbsDown className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          {filteredPainPoints.length === 0 ? (
            empty
          ) : (
            <div className="space-y-3">
              {filteredPainPoints.map((up) => (
                <div key={up.id} className="p-3 rounded-xl border border-border-divider bg-white">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-body-sm font-medium text-foreground">
                      <HighlightText text={up.painPoint} keyword={searchQuery} />
                    </span>
                    <span className="text-tiny text-foreground-muted">
                      <HighlightText text={up.productCategory} keyword={searchQuery} />
                    </span>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="flex-1">
                      <div className="flex justify-between text-tiny text-foreground-muted">
                        <span>提及 {up.frequency} 次</span>
                        <span>严重度 {up.severity}/10</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="产品反馈" subtitle="近期用户产品反馈汇总" tag="品类" icon={<MessageSquare className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          {filteredFeedbacks.length === 0 ? (
            empty
          ) : (
            <div className="space-y-3">
              {filteredFeedbacks.map((pf) => (
                <div key={pf.id} className="p-3 rounded-xl border border-border-divider bg-white">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-body-sm font-medium text-foreground">
                      <HighlightText text={pf.product} keyword={searchQuery} />
                    </span>
                    <span className={`text-tiny font-medium px-2 py-0.5 rounded-badge ${
                      pf.sentiment === 'positive' ? 'bg-status-successBg text-status-success' :
                      pf.sentiment === 'negative' ? 'bg-status-errorBg text-status-error' :
                      'bg-surface-tertiary text-foreground-muted'
                    }`}>
                      {pf.sentiment === 'positive' ? '正面' : pf.sentiment === 'negative' ? '负面' : '中性'}
                    </span>
                  </div>
                  <p className="text-caption text-foreground-secondary">
                    <HighlightText text={pf.feedback} keyword={searchQuery} />
                  </p>
                  <div className="flex items-center gap-3 mt-1 text-tiny text-foreground-muted">
                    <span>
                      <HighlightText text={pf.source} keyword={searchQuery} />
                    </span>
                    <span>{pf.upvotes} upvotes</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </div>

      <SectionCard title="市场空白" subtitle="未被充分满足的市场需求" tag="品类" icon={<Crosshair className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        {filteredGaps.length === 0 ? (
          empty
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {filteredGaps.map((mg) => (
              <div key={mg.id} className="card p-5 hover:shadow-card-hover transition-all duration-300">
                <div className="text-body-sm font-medium text-foreground mb-2">
                  <HighlightText text={mg.gap} keyword={searchQuery} />
                </div>
                <p className="text-caption text-foreground-secondary mb-3">
                  <HighlightText text={mg.demandEvidence} keyword={searchQuery} />
                </p>
                <div className="flex items-center justify-between">
                  <span className={`text-tiny font-medium px-2 py-0.5 rounded-badge ${densityConfig[mg.competitiveDensity].bg} ${densityConfig[mg.competitiveDensity].color}`}>
                    竞争密度: {densityConfig[mg.competitiveDensity].label}
                  </span>
                  <span className="text-tiny text-foreground-muted">
                    预估市场: {mg.estimatedMarketSize}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
