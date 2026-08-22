import { useState, useMemo, useCallback } from 'react';
import {
  Target,
  TrendingUp,
  TrendingDown,
  Minus,
  Inbox,
  Award,
  Settings,
  Plus,
  Trash2,
  RotateCcw,
  X,
} from 'lucide-react';
import {
  LineChart as ReLineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import SectionCard from './SectionCard';
import DetailModal from './DetailModal';
import { BarChart, RadarChart } from './charts';
import { useCompetitorStore, type CompetitorBrand, DEFAULT_BRANDS } from '../stores';
import {
  generateCompetitorMetrics,
  generateCompetitorDimensions,
  generateCompetitorTrend,
  type CompetitorMetric,
} from '../data/competitorMock';
import type { TimeRange } from '../types';
import { BRAND_COLORS } from '../constants/colors';

interface CompetitorComparisonProps {
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

function CompetitorCard({ competitor, rank }: { competitor: CompetitorMetric; rank: number }) {
  const totalMentions = competitor.positiveMentions + competitor.negativeMentions;
  const posRate = totalMentions > 0 ? Math.round((competitor.positiveMentions / totalMentions) * 100) : 0;

  return (
    <div className="card p-5 hover:shadow-card-hover transition-all duration-300 group">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-icon flex items-center justify-center text-white font-semibold text-sm"
            style={{ backgroundColor: competitor.color }}
          >
            {competitor.name.charAt(0)}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-h4 font-semibold text-foreground">{competitor.name}</span>
              {rank === 0 && (
                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-badge bg-status-successBg text-status-success text-tiny">
                  <Award className="w-3 h-3" strokeWidth={1.5} />
                  领先
                </span>
              )}
            </div>
            <span className="text-caption text-foreground-muted">{competitor.mentions} 次提及</span>
          </div>
        </div>
        <div
          className={`inline-flex items-center gap-0.5 text-tiny font-medium px-2 py-1 rounded-badge ${
            competitor.trend === 'up'
              ? 'bg-status-successBg text-status-success'
              : competitor.trend === 'down'
              ? 'bg-status-errorBg text-status-error'
              : 'bg-surface-tertiary text-foreground-muted'
          }`}
        >
          {trendIcons[competitor.trend]}
          {trendLabels[competitor.trend]}
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="rounded-icon bg-surface-tertiary p-3">
          <span className="text-tiny text-foreground-muted block mb-1">声量占比</span>
          <span className="text-body font-semibold text-foreground">{competitor.shareOfVoice}%</span>
        </div>
        <div className="rounded-icon bg-surface-tertiary p-3">
          <span className="text-tiny text-foreground-muted block mb-1">情感得分</span>
          <span
            className={`text-body font-semibold ${
              competitor.sentiment > 0.5 ? 'text-status-success' : competitor.sentiment > 0 ? 'text-status-warning' : 'text-status-error'
            }`}
          >
            {competitor.sentiment > 0 ? '+' : ''}
            {competitor.sentiment.toFixed(2)}
          </span>
        </div>
      </div>

      {/* Sentiment bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-tiny text-foreground-muted">正面提及率</span>
          <span className="text-tiny font-medium text-status-success">{posRate}%</span>
        </div>
        <div className="flex h-2 rounded-full overflow-hidden bg-surface-tertiary">
          <div className="h-full bg-status-success" style={{ width: `${posRate}%` }} />
          <div
            className="h-full bg-status-error"
            style={{ width: `${100 - posRate}%` }}
          />
        </div>
      </div>

      {/* Keywords */}
      <div className="pt-3 border-t border-border-divider">
        <span className="text-tiny text-foreground-muted block mb-1.5">热门关键词</span>
        <div className="flex flex-wrap gap-1.5">
          {competitor.topKeywords.slice(0, 4).map((k) => (
            <span key={k} className="px-2 py-0.5 rounded-badge bg-surface-tertiary text-caption text-foreground-secondary">
              {k}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-14 h-14 rounded-full bg-surface-tertiary flex items-center justify-center mb-4">
        <Inbox className="w-7 h-7 text-foreground-muted" strokeWidth={1.5} />
      </div>
      <h3 className="text-body font-medium text-foreground mb-1">暂无竞品对比数据</h3>
      <p className="text-caption text-foreground-secondary">当前时间范围内没有足够的数据生成竞品对比</p>
    </div>
  );
}

interface ConfigPanelProps {
  brands: { id: string; name: string; color: string; enabled: boolean }[];
  canAdd: boolean;
  onAdd: (name: string, color: string) => boolean;
  onRemove: (id: string) => void;
  onUpdate: (id: string, updates: Partial<{ name: string; color: string; enabled: boolean }>) => void;
  onReset: () => void;
  maxBrands: number;
  onClose: () => void;
}

function CompetitorConfigPanel({
  brands,
  canAdd,
  onAdd,
  onRemove,
  onUpdate,
  onReset,
  maxBrands,
  onClose,
}: ConfigPanelProps) {
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState('#6B6B6B');

  const handleAdd = () => {
    if (newName.trim() && onAdd(newName.trim(), newColor)) {
      setNewName('');
      setNewColor('#6B6B6B');
    }
  };

  return (
    <div className="mb-6 p-4 sm:p-5 rounded-card bg-surface-tertiary border border-border-divider">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h4 className="text-body font-semibold text-foreground">竞品配置</h4>
          <p className="text-caption text-foreground-muted">
            已配置 {brands.length}/{maxBrands} 个品牌
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onReset}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-button text-tiny text-foreground-secondary hover:bg-surface-warm hover:text-foreground transition-all"
            title="重置为默认"
          >
            <RotateCcw className="w-3.5 h-3.5" strokeWidth={1.5} />
            重置
          </button>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-icon flex items-center justify-center text-foreground-muted hover:bg-surface-warm hover:text-foreground transition-all"
          >
            <X className="w-4 h-4" strokeWidth={1.5} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
        {brands.map((brand) => (
          <div
            key={brand.id}
            className={`flex items-center gap-2 p-2.5 rounded-icon border transition-all ${
              brand.enabled
                ? 'bg-white border-border-divider'
                : 'bg-surface-tertiary border-transparent opacity-50'
            }`}
          >
            <input
              type="color"
              value={brand.color}
              onChange={(e) => onUpdate(brand.id, { color: e.target.value })}
              className="w-7 h-7 rounded-icon border-0 p-0 cursor-pointer flex-shrink-0"
              title="品牌颜色"
            />
            <input
              type="text"
              value={brand.name}
              onChange={(e) => onUpdate(brand.id, { name: e.target.value })}
              className="flex-1 min-w-0 bg-transparent text-body-sm font-medium text-foreground focus:outline-none"
              disabled={brand.id === 'momcozy'}
            />
            <button
              onClick={() => onUpdate(brand.id, { enabled: !brand.enabled })}
              className={`px-2 py-0.5 rounded-badge text-tiny font-medium transition-colors ${
                brand.enabled
                  ? 'bg-status-successBg text-status-success'
                  : 'bg-surface-tertiary text-foreground-muted'
              }`}
            >
              {brand.enabled ? '启用' : '禁用'}
            </button>
            {brand.id !== 'momcozy' && (
              <button
                onClick={() => onRemove(brand.id)}
                className="text-foreground-muted hover:text-status-error transition-colors p-0.5"
                title="移除"
              >
                <Trash2 className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
            )}
          </div>
        ))}
      </div>

      {canAdd && (
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={newColor}
            onChange={(e) => setNewColor(e.target.value)}
            className="w-7 h-7 rounded-icon border-0 p-0 cursor-pointer flex-shrink-0"
          />
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder="输入新品牌名称..."
            className="input-field flex-1 min-w-0"
          />
          <button
            onClick={handleAdd}
            className="btn-primary px-3 py-2"
            disabled={!newName.trim()}
          >
            <Plus className="w-4 h-4" strokeWidth={1.5} />
          </button>
        </div>
      )}
    </div>
  );
}

export default function CompetitorComparison({ timeRange = '7d' }: CompetitorComparisonProps) {
  const [viewMode, setViewMode] = useState<'overview' | 'trend' | 'radar'>('overview');
  const [showConfig, setShowConfig] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);

  const {
    brands,
    enabledBrands,
    addBrand: storeAddBrand,
    removeBrand,
    updateBrand,
    setBrands,
  } = useCompetitorStore();

  const MAX_BRANDS = 9;

  const activeBrands = useMemo(() => enabledBrands(), [enabledBrands, brands]);
  const canAdd = brands.length < MAX_BRANDS;
  const maxBrands = MAX_BRANDS;

  const addBrand = useCallback(
    (name: string, color: string) => {
      if (!canAdd) return null;
      const id = `brand-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const newBrand: CompetitorBrand = {
        id,
        name: name.trim(),
        color,
        subreddits: [],
        keywords: [],
        enabled: true,
      };
      storeAddBrand(newBrand);
      return newBrand;
    },
    [canAdd, storeAddBrand]
  );

  const resetToDefaults = useCallback(() => {
    setBrands(DEFAULT_BRANDS);
  }, [setBrands]);

  const primaryBrand = useMemo(() => activeBrands[0], [activeBrands]);

  const competitors = useMemo(() => generateCompetitorMetrics(activeBrands), [activeBrands]);
  const competitorDimensions = useMemo(() => generateCompetitorDimensions(activeBrands), [activeBrands]);
  const trendData = useMemo(
    () => generateCompetitorTrend(timeRange === '7d' ? '7d' : timeRange === '30d' ? '30d' : '90d', activeBrands),
    [timeRange, activeBrands]
  );

  const barData = useMemo(
    () =>
      competitors.map((c) => ({
        name: c.name,
        value: c.mentions,
        color: c.color,
      })),
    [competitors]
  );

  const radarData = useMemo(() => {
    if (!primaryBrand) return [];
    return competitorDimensions.map((d) => ({
      subject: d.dimension,
      value: d.scores[primaryBrand.name] ?? 0,
      fullMark: 100,
    }));
  }, [competitorDimensions, primaryBrand]);

  const lineData = useMemo(() => {
    return trendData.map((d) => {
      const point: Record<string, string | number> = { name: d.date };
      activeBrands.forEach((b) => {
        point[b.name] = d.values[b.name] ?? 0;
      });
      return point;
    });
  }, [trendData, activeBrands]);

  if (!competitors || competitors.length === 0) {
    return (
      <SectionCard
        title="竞品对比"
        subtitle="Momcozy 与主要竞品的舆情表现对比"
        icon={<Target className="w-5 h-5 text-primary" strokeWidth={1.5} />}
      >
        <EmptyState />
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="竞品对比"
      subtitle="Momcozy 与主要竞品的舆情表现对比"
      icon={<Target className="w-5 h-5 text-primary" strokeWidth={1.5} />}
      action={{ label: '查看全部', onClick: () => setShowDetailModal(true) }}
    >
      {/* Header: view toggle + settings */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div className="flex items-center gap-2">
          {([
            { key: 'overview' as const, label: '概览' },
            { key: 'trend' as const, label: '趋势' },
            { key: 'radar' as const, label: '能力雷达' },
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
        <button
          onClick={() => setShowConfig(!showConfig)}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
            showConfig
              ? 'bg-primary text-white'
              : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
          }`}
        >
          <Settings className="w-3.5 h-3.5" strokeWidth={1.5} />
          配置
        </button>
      </div>

      {showConfig && (
        <CompetitorConfigPanel
          brands={brands}
          canAdd={canAdd}
          onAdd={(name, color) => {
            const result = addBrand(name, color);
            return result !== null;
          }}
          onRemove={removeBrand}
          onUpdate={updateBrand}
          onReset={resetToDefaults}
          maxBrands={maxBrands}
          onClose={() => setShowConfig(false)}
        />
      )}

      {viewMode === 'overview' && (
        <div className="space-y-6">
          {/* Mentions bar chart */}
          <div>
            <div className="text-body font-medium text-foreground mb-3">品牌提及量对比</div>
            <BarChart data={barData} height={240} />
          </div>

          {/* Competitor cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {competitors.map((c, i) => (
              <CompetitorCard key={c.name} competitor={c} rank={i} />
            ))}
          </div>
        </div>
      )}

      {viewMode === 'trend' && (
        <div className="space-y-6">
          <div>
            <div className="text-body font-medium text-foreground mb-3">提及量趋势对比</div>
            <div style={{ height: 300 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ReLineChart
                  data={lineData}
                  margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 12, fill: '#6B7280' }}
                    axisLine={{ stroke: '#E5E7EB' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 12, fill: '#6B7280' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#fff',
                      border: '1px solid #EDEDED',
                      borderRadius: '16px',
                      boxShadow: '0 4px 12px rgba(0,0,0,0.06)',
                    }}
                  />
                  <Legend
                    iconType="circle"
                    iconSize={8}
                    wrapperStyle={{ fontSize: '12px', paddingTop: '8px' }}
                  />
                  {activeBrands.map((brand) => (
                    <Line
                      key={brand.name}
                      type="monotone"
                      dataKey={brand.name}
                      stroke={brand.color}
                      strokeWidth={2}
                      dot={{ r: 3, stroke: '#fff', strokeWidth: 1.5, fill: brand.color }}
                      activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2, fill: brand.color }}
                      animationDuration={800}
                      animationEasing="ease-out"
                    />
                  ))}
                </ReLineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {viewMode === 'radar' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            <div className="text-body font-medium text-foreground mb-3">
              {primaryBrand?.name ?? 'Momcozy'} 能力雷达
            </div>
            <RadarChart data={radarData} height={300} color={primaryBrand?.color ?? BRAND_COLORS.primary} fillOpacity={0.2} />
          </div>
          <div className="space-y-3">
            <div className="text-body font-medium text-foreground mb-2">维度说明</div>
            {competitorDimensions.map((d) => (
              <div key={d.dimension} className="flex items-center justify-between p-3 rounded-icon bg-surface-tertiary">
                <span className="text-body-sm text-foreground">{d.dimension}</span>
                <div className="flex items-center gap-3">
                  <span className="text-tiny text-foreground-muted">{primaryBrand?.name ?? 'Momcozy'}</span>
                  <div className="w-24 h-2 rounded-full bg-surface-tertiary overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full"
                      style={{ width: `${d.scores[primaryBrand?.name ?? 'Momcozy'] ?? 0}%` }}
                    />
                  </div>
                  <span className="text-body-sm font-semibold text-primary w-8 text-right">
                    {d.scores[primaryBrand?.name ?? 'Momcozy'] ?? 0}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <DetailModal
        open={showDetailModal}
        onClose={() => setShowDetailModal(false)}
        title="竞品详细对比"
        subtitle="Momcozy 与主要竞品的完整舆情数据"
      >
        <div className="space-y-6">
          {/* Summary table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-divider">
                  <th className="text-left py-3 px-2 text-tiny font-medium text-foreground-muted">品牌</th>
                  <th className="text-right py-3 px-2 text-tiny font-medium text-foreground-muted">提及量</th>
                  <th className="text-right py-3 px-2 text-tiny font-medium text-foreground-muted">声量占比</th>
                  <th className="text-right py-3 px-2 text-tiny font-medium text-foreground-muted">情感得分</th>
                  <th className="text-right py-3 px-2 text-tiny font-medium text-foreground-muted">正面率</th>
                  <th className="text-center py-3 px-2 text-tiny font-medium text-foreground-muted">趋势</th>
                </tr>
              </thead>
              <tbody>
                {competitors.map((c, i) => {
                  const totalMentions = c.positiveMentions + c.negativeMentions;
                  const posRate = totalMentions > 0 ? Math.round((c.positiveMentions / totalMentions) * 100) : 0;
                  return (
                    <tr key={c.name} className="border-b border-border-divider/50 hover:bg-surface-tertiary/50">
                      <td className="py-3 px-2">
                        <div className="flex items-center gap-2">
                          <div className="w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-semibold" style={{ backgroundColor: c.color }}>
                            {c.name.charAt(0)}
                          </div>
                          <span className="font-medium text-foreground">{c.name}</span>
                          {i === 0 && <Award className="w-3.5 h-3.5 text-status-warning" strokeWidth={1.5} />}
                        </div>
                      </td>
                      <td className="text-right py-3 px-2 text-foreground">{c.mentions}</td>
                      <td className="text-right py-3 px-2 text-foreground">{c.shareOfVoice}%</td>
                      <td className={`text-right py-3 px-2 font-medium ${c.sentiment > 0.5 ? 'text-status-success' : c.sentiment > 0 ? 'text-status-warning' : 'text-status-error'}`}>
                        {c.sentiment > 0 ? '+' : ''}{c.sentiment.toFixed(2)}
                      </td>
                      <td className="text-right py-3 px-2 text-status-success">{posRate}%</td>
                      <td className="text-center py-3 px-2">
                        <span className={`inline-flex items-center gap-0.5 text-tiny ${c.trend === 'up' ? 'text-status-success' : c.trend === 'down' ? 'text-status-error' : 'text-foreground-muted'}`}>
                          {trendIcons[c.trend]}
                          {trendLabels[c.trend]}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Keywords */}
          <div>
            <h4 className="text-body-sm font-semibold text-foreground mb-3">热门关键词</h4>
            <div className="space-y-3">
              {competitors.map((c) => (
                <div key={c.name} className="flex items-start gap-3">
                  <span className="text-tiny font-medium text-foreground-muted w-16 shrink-0">{c.name}</span>
                  <div className="flex flex-wrap gap-1.5">
                    {c.topKeywords.map((k) => (
                      <span key={k} className="px-2 py-0.5 rounded-badge bg-surface-tertiary text-caption text-foreground-secondary">
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </DetailModal>
    </SectionCard>
  );
}
