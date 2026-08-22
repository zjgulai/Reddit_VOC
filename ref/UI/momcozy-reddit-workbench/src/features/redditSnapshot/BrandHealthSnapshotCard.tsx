import BrandScoreCard from '../../components/BrandScoreCard';
import type { MetricHelpContent } from '../../components/MetricHelpPopover';
import type { BrandHealthDimensionId } from './brandHealth';
import type { BrandHealthState } from './useRedditBrandHealth';

const DIMENSION_HELP: Record<BrandHealthDimensionId, MetricHelpContent> = {
  reputation: {
    definition: '口碑健康把已完成情感分类的 Momcozy 帖子 VOC 与评论上下文 VOC 分开计分，再等权合并。正向=1，中性=0，负向=-1。',
    formula: '单一 grain 得分 = 50 + 50 × Σ情感极性 / 去重已分类实体数；维度 = mean(帖子得分, 评论上下文得分)。',
    notes: ['同一实体在同一周期与范围内只计一次。', '仅描述 Reddit 已观察样本，不代表 NPS。'],
  },
  product_experience: {
    definition: '产品体验仅在产品已绑定且问题分类完成的实体中，计算已晋级负向产品问题的发生结构。',
    formula: '单一 grain 得分 = 100 × (1 - 负向产品问题实体数 / 已完整分类的产品绑定实体数)；维度 = mean(帖子得分, 评论上下文得分)。',
    notes: ['held、unprocessed、failed 不按健康值 0 计入。', '帖子与评论上下文各占 50%，避免评论量压过帖子。'],
  },
  recommendation_trust: {
    definition: '推荐信任只纳入推荐分类完成的 Momcozy 实体。明确推荐=1，不信任或避免购买=-1，二者并存或均无=0。',
    formula: '单一 grain 得分 = 50 + 50 × Σ推荐倾向 / 去重已完成推荐分类实体数；维度 = mean(帖子得分, 评论上下文得分)。',
    notes: ['推荐证据必须已晋级，不能用标签字典裸命中替代。', '仅描述观察样本中的推荐倾向。'],
  },
  risk_resilience: {
    definition: '风险韧性根据已完成优先级分类的实体计算。每个实体只取最高权重：无风险=0、P2=0.3、P1=0.7、P0=1。',
    formula: '风险暴露 = 100 × Σ最高优先级权重 / 去重已分类实体数；单一 grain 风险韧性 = 100 - 风险暴露；维度 = mean(帖子得分, 评论上下文得分)。',
    notes: ['未运行分类不能解释为无风险。', '该指标衡量样本内风险承受表现，不代表危机已经处置。'],
  },
};

const OVERALL_HELP: MetricHelpContent = {
  definition: '品牌健康度指数由口碑健康、产品体验、推荐信任、风险韧性四维构成；各维先对帖子 VOC 与评论上下文 VOC 50/50 合并。',
  formula: '总分 = round_half_up(mean(口碑健康, 产品体验, 推荐信任, 风险韧性))。',
  notes: [
    '总分直接使用已发布的治理投影，浏览器不临时补算或改权重。',
    '阶段性值保留真实计算结果；不代表市场份额、销量或 NPS。',
  ],
};

export function BrandHealthSnapshotCard({
  data,
  error,
  isLoading,
  sampleSize,
}: BrandHealthState & { sampleSize?: number | null }) {
  if (isLoading) {
    return (
      <section className="card p-6" aria-label="Momcozy 品牌健康度指数">
        <h2 className="text-h3 text-foreground">品牌健康度指数</h2>
        <p className="mt-2 text-caption text-foreground-muted">正在加载已验证的品牌健康数据……</p>
      </section>
    );
  }

  const dimensions = data?.data.dimensions.flatMap((item) => (
    item.score === null ? [] : [{
      dimension: item.label,
      score: item.score,
      fullMark: 100,
      help: item.status === 'provisional'
        ? { ...DIMENSION_HELP[item.dimension_id], notes: [...(DIMENSION_HELP[item.dimension_id].notes ?? []), '当前为阶段性计算值，覆盖状态只限制外推，不清空数值。'] }
        : DIMENSION_HELP[item.dimension_id],
    }]
  )) ?? [];
  const overall = data?.data.overall.score ?? null;
  if (!data || overall === null || dimensions.length !== 4) {
    return (
      <section className="card border-status-error/20 p-6" aria-label="Momcozy 品牌健康度指数" data-ui-severity="error">
        <h2 className="text-h3 text-foreground">品牌健康度指数</h2>
        <p className="mt-2 text-caption text-status-error">已验证品牌健康投影不可用，未使用临时公式或少数维度平均值替代。{error ? ` ${error}` : ''}</p>
      </section>
    );
  }

  const strongest = [...dimensions].sort((left, right) => right.score - left.score)[0];
  const weakest = [...dimensions].sort((left, right) => left.score - right.score)[0];
  const overallIsProvisional = data.data.overall.status === 'provisional';
  const sampleDescription = typeof sampleSize === 'number'
    ? `${sampleSize.toLocaleString('zh-CN')} 条品牌相关去重帖子及其评论上下文`
    : '品牌相关去重帖子及其评论上下文';

  return (
    <section className="space-y-3" aria-label="Momcozy 品牌健康度指数">
      <BrandScoreCard
        brandName="Momcozy"
        overallScore={overall}
        title="品牌健康度指数"
        subtitle={`Momcozy · 当前已验证独立投影 · ${sampleDescription}`}
        help={OVERALL_HELP}
        data={dimensions}
        scoreStatusLabel={overallIsProvisional ? '真实样本计算值 · 阶段性' : '真实样本计算值'}
      />
      <div className="grid gap-3 rounded-card border border-border-divider bg-surface-secondary px-4 py-4 md:grid-cols-3">
        <div>
          <p className="text-tiny font-semibold uppercase tracking-wide text-primary">总体判断</p>
          <p className="mt-1 text-body-sm leading-relaxed text-foreground-secondary">品牌健康度为 <strong className="text-foreground">{overall}</strong> 分，四维差异明显，需将优势与短板分开管理。</p>
        </div>
        <div className="border-border-divider md:border-l md:pl-4">
          <p className="text-tiny font-semibold uppercase tracking-wide text-status-success">核心优势</p>
          <p className="mt-1 text-body-sm text-foreground-secondary">{strongest.dimension} <strong className="text-foreground">{strongest.score}</strong> 分</p>
        </div>
        <div className="border-border-divider md:border-l md:pl-4">
          <p className="text-tiny font-semibold uppercase tracking-wide text-status-error">优先改进</p>
          <p className="mt-1 text-body-sm text-foreground-secondary">{weakest.dimension} <strong className="text-foreground">{weakest.score}</strong> 分</p>
        </div>
      </div>
      <p className="px-1 text-tiny leading-relaxed text-foreground-muted">
        口径：总分与四个维度均来自同一份隐私安全的独立投影，不随概览页上方时间 Tab 切换；该投影不证明历史采集覆盖完整，阶段性值也不代表市场份额、销量或 NPS。
      </p>
    </section>
  );
}
