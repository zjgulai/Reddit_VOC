import { useState } from 'react';
import {
  UserCircle,
  Inbox,
  Clock,
  Heart,
  Activity,
  Smartphone,
} from 'lucide-react';
import SectionCard from './SectionCard';
import DetailModal from './DetailModal';
import {
  getPersonaSegments,
  getAudienceDemographics,
  audienceRadarData,
  type PersonaSegment,
} from '../data/audienceMock';
import { PieChart, RadarChart, BarChart, AreaChart } from './charts';
import type { TimeRange } from '../types';
import { BRAND_COLORS, SENTIMENT_COLORS, NEUTRAL_COLORS } from '../constants/colors';

interface AudiencePersonaProps {
  timeRange?: TimeRange;
}

function PersonaCard({ persona }: { persona: PersonaSegment }) {
  const sentimentColor =
    persona.sentiment > 0.5 ? 'text-status-success' : persona.sentiment > 0.3 ? 'text-status-warning' : 'text-status-error';

  return (
    <div className="card p-5 hover:shadow-card-hover transition-all duration-300 group">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-icon flex items-center justify-center text-white font-semibold text-sm flex-shrink-0"
            style={{ backgroundColor: persona.color }}
          >
            {persona.name.charAt(0)}
          </div>
          <div>
            <span className="text-h4 font-semibold text-foreground">{persona.name}</span>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-caption text-foreground-muted">{persona.percentage}%</span>
              <span className="text-caption text-foreground-muted">·</span>
              <span className="text-caption text-foreground-muted">{persona.avgAge}岁</span>
            </div>
          </div>
        </div>
        <span className={`text-body font-semibold ${sentimentColor}`}>
          {persona.sentiment > 0 ? '+' : ''}
          {persona.sentiment.toFixed(2)}
        </span>
      </div>

      <p className="text-body-sm text-foreground-secondary mb-3">{persona.description}</p>

      <div className="mb-3">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Heart className="w-3.5 h-3.5 text-foreground-muted" strokeWidth={1.5} />
          <span className="text-tiny text-foreground-muted">主要关注点</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {persona.topConcerns.map((c) => (
            <span key={c} className="px-2 py-0.5 rounded-badge bg-surface-tertiary text-caption text-foreground-secondary">
              {c}
            </span>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-1.5 pt-3 border-t border-border-divider">
        <Clock className="w-3.5 h-3.5 text-foreground-muted" strokeWidth={1.5} />
        <span className="text-tiny text-foreground-muted">{persona.activityPattern}</span>
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
      <h3 className="text-body font-medium text-foreground mb-1">暂无受众画像数据</h3>
      <p className="text-caption text-foreground-secondary">当前时间范围内没有足够的数据生成受众画像</p>
    </div>
  );
}

export default function AudiencePersona({ timeRange = '7d' }: AudiencePersonaProps) {
  const [activeTab, setActiveTab] = useState<'persona' | 'demographics' | 'behavior'>('persona');
  const [showModal, setShowModal] = useState(false);
  const personaSegments = getPersonaSegments(timeRange);
  const demographics = getAudienceDemographics(timeRange);

  const momStageData = demographics.momStage.map((d) => ({
    name: d.name,
    value: d.value,
    color: d.color,
  }));

  const interestsData = demographics.interests.map((d) => ({
    name: d.name,
    value: d.value,
  }));

  const painPointsData = demographics.painPoints.map((d) => ({
    name: d.name,
    value: d.value,
    color: d.sentiment < -0.3 ? BRAND_COLORS.primary : d.sentiment < -0.15 ? SENTIMENT_COLORS.neutral : NEUTRAL_COLORS.gray500,
  }));

  const activityData = demographics.activityByHour.map((d) => ({
    label: `${d.hour}:00`,
    value: d.value,
  }));

  const deviceData = demographics.deviceUsage.map((d) => ({
    name: d.name,
    value: d.value,
    color: d.color,
  }));

  const radarData = audienceRadarData.map((d) => ({
    subject: d.dimension,
    value: d.score,
    fullMark: d.fullMark,
  }));

  if (!personaSegments || personaSegments.length === 0) {
    return (
      <SectionCard
        title="受众画像"
        subtitle="基于讨论行为分析的核心受众群体特征"
        icon={<UserCircle className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '查看详情', onClick: () => setShowModal(true) }}
      >
        <EmptyState />
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="受众画像"
      subtitle="基于讨论行为分析的核心受众群体特征"
      icon={<UserCircle className="w-5 h-5 text-primary" strokeWidth={1.5} />}
        action={{ label: '查看详情', onClick: () => setShowModal(true) }}
    >
      <div className="flex items-center gap-2 mb-6">
        {([
          { key: 'persona' as const, label: '用户画像' },
          { key: 'demographics' as const, label: '人口统计' },
          { key: 'behavior' as const, label: '行为特征' },
        ]).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
              activeTab === tab.key
                ? 'bg-primary text-white'
                : 'bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'persona' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {personaSegments.map((persona) => (
              <PersonaCard key={persona.id} persona={persona} />
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <div className="text-body font-medium text-foreground mb-3">受众特征雷达</div>
              <RadarChart data={radarData} height={280} color={BRAND_COLORS.primary} fillOpacity={0.2} />
            </div>
            <div>
              <div className="text-body font-medium text-foreground mb-3">妈妈阶段分布</div>
              <PieChart data={momStageData} height={280} showLegend={true} innerRadius={0.45} />
            </div>
          </div>
        </div>
      )}

      {activeTab === 'demographics' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <div className="text-body font-medium text-foreground mb-3">妈妈阶段分布</div>
              <PieChart data={momStageData} height={280} showLegend={true} innerRadius={0.45} />
            </div>
            <div>
              <div className="text-body font-medium text-foreground mb-3">兴趣分布</div>
              <BarChart data={interestsData} height={280} />
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <div className="text-body font-medium text-foreground mb-3">使用设备分布</div>
              <PieChart data={deviceData} height={260} showLegend={true} innerRadius={0.45} />
            </div>
            <div className="card p-5">
              <div className="text-body font-medium text-foreground mb-4">画像概览</div>
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-icon bg-primary-light flex items-center justify-center">
                    <Activity className="w-[18px] h-[18px] text-primary" strokeWidth={1.5} />
                  </div>
                  <div>
                    <div className="text-body-sm font-medium text-foreground">最活跃时段</div>
                    <div className="text-caption text-foreground-secondary">20:00 - 23:00 (晚间)</div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-icon bg-status-infoBg flex items-center justify-center">
                    <Smartphone className="w-[18px] h-[18px] text-status-info" strokeWidth={1.5} />
                  </div>
                  <div>
                    <div className="text-body-sm font-medium text-foreground">主要设备</div>
                    <div className="text-caption text-foreground-secondary">手机 (68%)、电脑 (24%)、平板 (8%)</div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-icon bg-status-successBg flex items-center justify-center">
                    <Heart className="w-[18px] h-[18px] text-status-success" strokeWidth={1.5} />
                  </div>
                  <div>
                    <div className="text-body-sm font-medium text-foreground">品牌好感度</div>
                    <div className="text-caption text-foreground-secondary">62% 正面情感，34% 中性，4% 负面</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'behavior' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <div className="text-body font-medium text-foreground mb-3">用户痛点分布</div>
              <BarChart data={painPointsData} height={280} />
            </div>
            <div>
              <div className="text-body font-medium text-foreground mb-3">兴趣分布</div>
              <BarChart data={interestsData} height={280} />
            </div>
          </div>
          <div>
            <div className="text-body font-medium text-foreground mb-3">24小时活跃分布</div>
            <AreaChart data={activityData} height={260} />
          </div>
        </div>
      )}

      <DetailModal
        open={showModal}
        onClose={() => setShowModal(false)}
        title="受众画像详情"
        subtitle="基于讨论行为分析的核心受众群体特征"
      >
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {personaSegments.map((persona) => (
              <PersonaCard key={persona.id} persona={persona} />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <div className="text-body font-medium text-foreground mb-3">受众特征雷达</div>
              <RadarChart data={radarData} height={280} color={BRAND_COLORS.primary} fillOpacity={0.2} />
            </div>
            <div>
              <div className="text-body font-medium text-foreground mb-3">妈妈阶段分布</div>
              <PieChart data={momStageData} height={280} showLegend={true} innerRadius={0.45} />
            </div>
          </div>
        </div>
      </DetailModal>
    </SectionCard>
  );
}
