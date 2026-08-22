import { useState, useMemo, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Search,
  Bell,
  Zap,
  BarChart3,
  ShieldAlert,
  Award,
  Layers,
} from 'lucide-react';
import Sidebar from '../components/Sidebar';
import ExportButton from '../components/ExportButton';
import type { ExportSection } from '../components/ExportButton';
import { useAsync, useUrlParams } from '../hooks';
import InsightsSkeleton from '../components/insights/InsightsSkeleton';
import OperationInsightsPanel from '../components/insights/OperationInsightsPanel';
import SentimentInsightsPanel from '../components/insights/SentimentInsightsPanel';
import BrandInsightsPanel from '../components/insights/BrandInsightsPanel';
import CategoryInsightsPanel from '../components/insights/CategoryInsightsPanel';

import { getInsights } from '../services/insightService';
import type { InsightsData } from '../services/insightService';

type InsightTab = 'operation' | 'sentiment' | 'brand' | 'category';

const tabConfig: Record<InsightTab, { label: string; icon: typeof Zap; desc: string }> = {
  operation: { label: '运营洞察', icon: BarChart3, desc: '运营效率、团队负载、最佳实践' },
  sentiment: { label: '舆情洞察', icon: ShieldAlert, desc: '情感趋势、预警历史、危机复盘' },
  brand: { label: '品牌洞察', icon: Award, desc: '品牌声量、定位分析、心智份额' },
  category: { label: '品类洞察', icon: Layers, desc: '新品机会、用户痛点、市场空白' },
};

function buildInsightsExport(data: InsightsData | null | undefined): { csvData: Record<string, string | number>[]; sections: ExportSection[] } {
  if (!data) return { csvData: [], sections: [] };

  const csvData: Record<string, string | number>[] = [
    // 运营洞察
    ...data.operationInsights.map((i) => ({
      维度: '运营洞察',
      指标: i.title,
      当前值: `${i.value}${i.unit}`,
      目标值: `${i.target}${i.unit}`,
      变化: `${i.change > 0 ? '+' : ''}${i.change}%`,
      趋势: i.trend === 'up' ? '上升' : i.trend === 'down' ? '下降' : '平稳',
    })),
    // 舆情预警
    ...data.warningHistory.map((w) => ({
      维度: '舆情预警',
      指标: w.title,
      当前值: w.level === 'critical' ? '严重' : w.level === 'warning' ? '警告' : '信息',
      目标值: w.status === 'resolved' ? '已解决' : w.status === 'pending' ? '处理中' : '已升级',
      变化: w.responseTime,
      趋势: w.date,
    })),
    // 品牌声量
    ...data.brandVoiceInsights.map((b) => ({
      维度: '品牌声量',
      指标: b.dimension,
      当前值: b.momcozy,
      目标值: `${b.elvie} / ${b.spectra} / ${b.medela}`,
      变化: b.momcozy - b.elvie,
      趋势: b.momcozy >= b.elvie ? '领先' : '追赶',
    })),
    // 产品机会
    ...data.productOpportunities.map((p) => ({
      维度: '产品机会',
      指标: p.title,
      当前值: `需求${p.demandScore}`,
      目标值: `竞争${p.competitionScore}`,
      变化: p.potentialROI,
      趋势: p.demandScore > 75 ? '高潜力' : '中潜力',
    })),
  ];

  const sections: ExportSection[] = [
    {
      title: '运营洞察',
      headers: ['指标', '当前值', '目标值', '变化', '趋势'],
      rows: data.operationInsights.map((i) => [
        i.title,
        `${i.value}${i.unit}`,
        `${i.target}${i.unit}`,
        `${i.change > 0 ? '+' : ''}${i.change}%`,
        i.trend === 'up' ? '上升' : i.trend === 'down' ? '下降' : '平稳',
      ]),
    },
    {
      title: '团队负载',
      headers: ['成员', '任务分配', '已完成', '平均响应', '效率'],
      rows: data.teamWorkloads.map((w) => [
        w.member,
        w.tasksAssigned,
        w.tasksCompleted,
        `${w.avgResponseTime}分钟`,
        `${w.efficiency}%`,
      ]),
    },
    {
      title: '舆情预警历史',
      headers: ['标题', '等级', '日期', '状态', '响应时间'],
      rows: data.warningHistory.map((w) => [
        w.title,
        w.level === 'critical' ? '严重' : w.level === 'warning' ? '警告' : '信息',
        w.date,
        w.status === 'resolved' ? '已解决' : w.status === 'pending' ? '处理中' : '已升级',
        w.responseTime,
      ]),
    },
    {
      title: '品牌声量对比',
      headers: ['维度', 'Momcozy', 'Elvie', 'Spectra', 'Medela'],
      rows: data.brandVoiceInsights.map((b) => [
        b.dimension,
        b.momcozy,
        b.elvie,
        b.spectra,
        b.medela,
      ]),
    },
    {
      title: '产品机会',
      headers: ['机会点', '需求分', '竞争度', 'ROI', '描述'],
      rows: data.productOpportunities.map((p) => [
        p.title,
        p.demandScore,
        p.competitionScore,
        p.potentialROI,
        p.description,
      ]),
    },
    {
      title: '用户痛点',
      headers: ['痛点', '频次', '严重度', '品类'],
      rows: data.userPainPoints.map((u) => [
        u.painPoint,
        u.frequency,
        u.severity,
        u.productCategory,
      ]),
    },
  ];

  return { csvData, sections };
}

export default function Insights() {
  const { getParam, setParam } = useUrlParams();
  const [searchQuery, setSearchQuery] = useState(() => getParam('q') || '');
  const [activeTab, setActiveTab] = useState<InsightTab>('operation');

  const { data: insightsData, isLoading } = useAsync(async () => getInsights(), []);

  const { csvData, sections } = useMemo(() => buildInsightsExport(insightsData), [insightsData]);

  useEffect(() => {
    if (searchQuery.trim()) {
      setParam('q', searchQuery.trim());
    } else {
      setParam('q', null);
    }
  }, [searchQuery, setParam]);

  return (
    <div className="flex min-h-screen bg-surface-tertiary">
      <Sidebar />

      <main className="flex-1 min-w-0">
        {/* Top Bar */}
        <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-xl border-b border-border-divider/60">
          <div className="flex items-center justify-between px-6 py-3.5">
            <div className="flex items-center gap-4">
              <div className="relative w-72">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="搜索洞察内容..."
                  className="input-field pl-10 bg-surface-tertiary border-transparent focus:bg-white"
                />
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-muted" strokeWidth={1.5} />
              </div>
            </div>

            <div className="flex items-center gap-3">
              <ExportButton
                filename="深度洞察报告"
                title="深度洞察报告"
                subtitle={`生成日期：${new Date().toLocaleDateString('zh-CN')} · ${tabConfig[activeTab].label}`}
                data={csvData}
                sections={sections}
              />
              <Link to="/dashboard/messages" className="relative w-9 h-9 rounded-icon flex items-center justify-center text-foreground-secondary hover:bg-surface-tertiary transition-all duration-200" aria-label="消息中心">
                <Bell className="w-[18px] h-[18px]" strokeWidth={1.5} />
                <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-primary rounded-full" />
              </Link>
              <div className="w-9 h-9 rounded-full bg-primary-light flex items-center justify-center">
                <span className="text-sm font-medium text-primary">M</span>
              </div>
            </div>
          </div>
        </header>

        <div className="p-6 space-y-6">
          {/* Page Header */}
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <Zap className="w-5 h-5 text-primary" strokeWidth={1.5} />
                <h1 className="text-h1 text-foreground">深度洞察</h1>
              </div>
              <p className="text-body text-foreground-secondary">
                从运营、舆情、品牌、品类四个维度，深度解读数据背后的业务价值
              </p>
            </div>
          </div>

          {/* Tab Switch */}
          <div className="flex items-center gap-1 bg-surface-tertiary rounded-card p-1.5 w-fit">
            {(Object.keys(tabConfig) as InsightTab[]).map((tab) => {
              const TabIconComp = tabConfig[tab].icon;
              return (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`flex items-center gap-2 px-5 py-2.5 rounded-button transition-all duration-200 ${
                    activeTab === tab
                      ? 'bg-white text-foreground shadow-sm'
                      : 'text-foreground-muted hover:text-foreground'
                  }`}
                >
                  <TabIconComp className="w-4 h-4" strokeWidth={1.5} />
                  <span className="text-body-sm font-medium">{tabConfig[tab].label}</span>
                </button>
              );
            })}
          </div>

          {/* Content */}
          {isLoading || !insightsData ? (
            <div className="space-y-3">
              <p className="text-body-sm text-foreground-secondary animate-fade-in">
                正在生成洞察报告...
              </p>
              <InsightsSkeleton />
            </div>
          ) : (
            <div className="animate-fade-in">
              {activeTab === 'operation' && <OperationInsightsPanel data={insightsData} searchQuery={searchQuery} />}
              {activeTab === 'sentiment' && <SentimentInsightsPanel data={insightsData} searchQuery={searchQuery} />}
              {activeTab === 'brand' && <BrandInsightsPanel data={insightsData} searchQuery={searchQuery} />}
              {activeTab === 'category' && <CategoryInsightsPanel data={insightsData} searchQuery={searchQuery} />}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

