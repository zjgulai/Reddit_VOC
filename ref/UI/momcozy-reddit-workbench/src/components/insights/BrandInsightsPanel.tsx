import {
  Megaphone,
  GitCompare,
  BrainCircuit,
} from 'lucide-react';
import SectionCard from '../SectionCard';
import HighlightText from '../HighlightText';
import type { InsightsData } from '../../services/insightService';
import { RadarChart, BarChart, LineChart } from '../charts';
import { BRAND_COLORS } from '../../constants/colors';

interface Props {
  data: InsightsData;
  searchQuery?: string;
}

export default function BrandInsightsPanel({ data, searchQuery = '' }: Props) {
  const { brandVoiceInsights, brandPositioning, mindShareTrends } = data;

  const q = searchQuery.toLowerCase();
  const filteredVoice = q
    ? brandVoiceInsights.filter((b) => b.dimension.toLowerCase().includes(q))
    : brandVoiceInsights;
  const filteredPositioning = q
    ? brandPositioning.filter((bp) => bp.attribute.toLowerCase().includes(q))
    : brandPositioning;

  const empty = (
    <div className="text-center py-8 text-body-sm text-foreground-muted">
      未找到匹配 "{searchQuery}" 的结果
    </div>
  );

  return (
    <div className="space-y-6">
      <SectionCard title="品牌声量对比" subtitle="Momcozy vs 竞品多维度声量" tag="品牌" icon={<Megaphone className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <RadarChart
            data={filteredVoice.map((b) => ({
              subject: b.dimension,
              value: b.momcozy,
              fullMark: 100,
            }))}
            title="Momcozy 品牌雷达"
            height={280}
            color={BRAND_COLORS.primary}
          />
          <BarChart
            data={filteredVoice.map((b) => ({
              name: b.dimension,
              value: b.momcozy,
              color: BRAND_COLORS.primary,
            }))}
            title="Momcozy 各维度得分"
            height={280}
          />
        </div>
      </SectionCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title="品牌定位差异" subtitle="各品牌属性认知对比" tag="品牌" icon={<GitCompare className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          {filteredPositioning.length === 0 ? (
            empty
          ) : (
            <div className="space-y-4">
              {filteredPositioning.map((bp) => (
                <div key={bp.attribute} className="space-y-1">
                  <div className="text-body-sm font-medium text-foreground">
                    <HighlightText text={bp.attribute} keyword={searchQuery} />
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <div className="flex justify-between text-tiny text-foreground-muted mb-1">
                        <span>Momcozy</span>
                        <span>{bp.momcozy}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-surface-tertiary overflow-hidden">
                        <div className="h-full rounded-full bg-primary" style={{ width: `${bp.momcozy}%` }} />
                      </div>
                    </div>
                    <div className="w-px h-6 bg-border-divider" />
                    <div className="flex-1">
                      <div className="flex justify-between text-tiny text-foreground-muted mb-1">
                        <span>Elvie</span>
                        <span>{bp.elvie}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-surface-tertiary overflow-hidden">
                        <div className="h-full rounded-full bg-secondary" style={{ width: `${bp.elvie}%` }} />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="用户心智份额趋势" subtitle="6个月品牌心智份额变化" tag="品牌" icon={<BrainCircuit className="w-5 h-5 text-primary" strokeWidth={1.5} />}>
          <LineChart
            data={mindShareTrends.map((d) => ({ label: d.date, value: d.momcozy }))}
            title="Momcozy 心智份额"
            color={BRAND_COLORS.primary}
            height={280}
          />
          <div className="mt-4 grid grid-cols-3 gap-3">
            <div className="bg-surface-tertiary rounded-xl p-3 text-center">
              <div className="text-caption text-foreground-muted">Momcozy</div>
              <div className="text-h4 font-semibold text-primary mt-1">{mindShareTrends[mindShareTrends.length - 1].momcozy}%</div>
            </div>
            <div className="bg-surface-tertiary rounded-xl p-3 text-center">
              <div className="text-caption text-foreground-muted">Elvie</div>
              <div className="text-h4 font-semibold text-foreground mt-1">{mindShareTrends[mindShareTrends.length - 1].elvie}%</div>
            </div>
            <div className="bg-surface-tertiary rounded-xl p-3 text-center">
              <div className="text-caption text-foreground-muted">Spectra</div>
              <div className="text-h4 font-semibold text-foreground mt-1">{mindShareTrends[mindShareTrends.length - 1].spectra}%</div>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
