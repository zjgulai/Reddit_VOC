import { BarChart3, CalendarRange, Hash, MessageSquare, Tags, Users } from 'lucide-react';
import SectionCard from '../components/SectionCard';
import {
  BarChart,
  LineChart,
  PieChart,
  SankeyChart,
  WordCloudChart,
} from '../components/charts';
import { RankedBarList } from '../features/redditSnapshot/RankedBarList';
import { createBaseDataFreshness } from '../features/redditSnapshot/freshness';
import { SnapshotMetricCard } from '../features/redditSnapshot/SnapshotMetricCard';
import {
  createBaseGovernanceContract,
  DataScopeBar,
} from '../features/redditSnapshot/governance';
import {
  SnapshotErrorPage,
  SnapshotLoadingPage,
  SnapshotPageLayout,
} from '../features/redditSnapshot/SnapshotPageLayout';
import { formatDate, formatPainPoint, formatTopic } from '../features/redditSnapshot/format';
import { isMomcozyPost } from '../features/redditSnapshot/operational';
import type { SnapshotPost } from '../features/redditSnapshot/types';
import { useRedditSnapshot } from '../features/redditSnapshot/useRedditSnapshot';

function topEntries(values: Record<string, number>, limit: number) {
  return Object.entries(values)
    .sort((left, right) => right[1] - left[1])
    .slice(0, limit);
}

function brandObservationScore(posts: SnapshotPost[]): number {
  if (posts.length === 0) return 0;
  const positive = posts.filter((post) => post.analysis.sentiment_label === 'positive').length;
  const negative = posts.filter((post) => post.analysis.sentiment_label === 'negative').length;
  return Math.round((50 + (50 * (positive - negative)) / posts.length) * 10) / 10;
}

export default function SnapshotAnalytics() {
  const { data: snapshot, error, isLoading } = useRedditSnapshot();

  if (isLoading) return <SnapshotLoadingPage icon={BarChart3} title="真实数据分析" />;
  if (error || !snapshot) return <SnapshotErrorPage icon={BarChart3} title="真实数据分析" error={error ?? '未知错误'} />;

  const { manifest, aggregates } = snapshot;
  const governance = createBaseGovernanceContract(snapshot.release, snapshot);
  const topicItems = topEntries(aggregates.post_topics, 8).map(([label, value]) => ({
    label: formatTopic(label),
    value,
  }));
  const painPointItems = topEntries(aggregates.pain_points, 9).map(([label, value]) => ({
    label: formatPainPoint(label),
    value,
  }));
  const subredditItems = topEntries(aggregates.subreddit_posts, 10).map(([label, value]) => ({
    label: label ? `r/${label}` : '未知社区',
    value,
    detail: `· ${(aggregates.subreddit_comments[label] ?? 0).toLocaleString('zh-CN')} 评论`,
  }));
  const recentMonths = Object.entries(aggregates.monthly_posts)
    .sort(([left], [right]) => left.localeCompare(right))
    .slice(-12)
    .map(([label, value]) => ({ label, value }));
  const topTags = aggregates.tagging.top_tags.slice(0, 10).map((tag) => ({
    label: `${tag.name_cn} · ${tag.theme}`,
    value: tag.total_entities,
    detail: `· 帖子 ${tag.post_entities} / 评论 ${tag.comment_entities}`,
  }));
  const topTopics = new Set(topEntries(aggregates.post_topics, 5).map(([topic]) => topic));
  const topSubreddits = new Set(topEntries(aggregates.subreddit_posts, 5).map(([subreddit]) => subreddit));
  const sentimentNodeIds = ['positive', 'neutral', 'negative'];
  const sankeyNodes = [
    ...[...topSubreddits].map((subreddit) => ({ id: `subreddit:${subreddit}`, name: subreddit ? `r/${subreddit}` : '未知社区' })),
    ...[...topTopics].map((topic) => ({ id: `topic:${topic}`, name: formatTopic(topic) })),
    ...sentimentNodeIds.map((sentiment) => ({ id: `sentiment:${sentiment}`, name: sentiment === 'positive' ? '正面' : sentiment === 'negative' ? '负面' : '中性' })),
  ];
  const linkCounts = new Map<string, number>();
  for (const post of snapshot.posts) {
    if (!topTopics.has(post.analysis.topic) || !topSubreddits.has(post.subreddit)) continue;
    const first = `subreddit:${post.subreddit}|topic:${post.analysis.topic}`;
    const second = `topic:${post.analysis.topic}|sentiment:${post.analysis.sentiment_label}`;
    linkCounts.set(first, (linkCounts.get(first) ?? 0) + 1);
    linkCounts.set(second, (linkCounts.get(second) ?? 0) + 1);
  }
  const sankeyLinks = [...linkCounts.entries()].map(([key, value]) => {
    const [source, target] = key.split('|');
    return { source, target, value };
  });
  const tagCloud = aggregates.tagging.top_tags.slice(0, 28).map((tag) => ({
    text: tag.name_cn,
    value: tag.total_entities,
  }));
  const productCounts = new Map<string, number>();
  snapshot.posts.filter(isMomcozyPost).forEach((post) => {
    post.product_bindings?.forEach((binding) => {
      const label = binding.exact_spu?.spu_name
        ?? binding.product_family?.name_cn
        ?? binding.category.name_cn;
      productCounts.set(label, (productCounts.get(label) ?? 0) + 1);
    });
  });
  const productData = [...productCounts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0], 'zh-CN'))
    .slice(0, 10)
    .map(([name, value]) => ({ name, value }));
  const comparisonBrands = [
    'Momcozy',
    ...aggregates.brand_sample_mentions
      .map((item) => item.brand)
      .filter((brand) => brand.toLowerCase() !== 'momcozy')
      .slice(0, 7),
  ];
  const brandScoreData = comparisonBrands.map((brand, index) => {
    const posts = index === 0
      ? snapshot.posts.filter(isMomcozyPost)
      : snapshot.posts.filter((post) => post.mentioned_brands.some((item) => item.toLowerCase() === brand.toLowerCase()));
    return {
      name: brand,
      value: brandObservationScore(posts),
      color: index === 0 ? '#E85D75' : undefined,
    };
  });

  return (
    <SnapshotPageLayout
      icon={BarChart3}
      title="真实数据分析"
      description="只基于已融合实体与可审计聚合，不展示推算型业务指标"
      datasetVersion={manifest.dataset_version}
      freshness={createBaseDataFreshness(snapshot)}
    >
      <div className="rounded-card border border-primary/15 bg-primary-light/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-body-sm text-foreground-secondary">
            <CalendarRange className="h-4 w-4 text-primary" strokeWidth={1.5} />
            数据范围：{formatDate(aggregates.date_range.posts[0])} 至 {formatDate(aggregates.date_range.posts[1])}
          </div>
          <span className="text-caption text-foreground-muted">
            静态全量窗口 · 不伪造 7/30/90 天实时趋势
          </span>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SnapshotMetricCard icon={MessageSquare} value={aggregates.headline.comments_in_voc_metrics} label="VOC 有效评论" note="分析分母已排除机器人和删除内容" />
        <SnapshotMetricCard icon={Tags} value={aggregates.headline.posts_with_rule_tags} label="有规则标签的帖子" note={`共 ${aggregates.headline.unique_posts} 条帖子`} />
        <SnapshotMetricCard icon={Hash} value={aggregates.headline.comments_with_rule_tags_in_voc_metrics} label="有规则标签的评论" note="规则提取 · 未晋级语义洞察" />
        <SnapshotMetricCard icon={Users} value={Object.keys(aggregates.subreddit_posts).length} label="覆盖社区" note="包含空社区字段的独立占位项" />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionCard title="帖子月度趋势" subtitle="连续展示最近 12 个有数据月份；均为真实帖子创建月份" tag="运营">
          <LineChart data={recentMonths} color="#E85D75" height={280} />
        </SectionCard>
        <SectionCard title="帖子情感构成" subtitle="正面、中性、负面帖子事实；与评论分母分开" tag="品牌">
          <PieChart
            data={[
              { name: '正面', value: aggregates.post_sentiment.positive, color: '#18A874' },
              { name: '中性', value: aggregates.post_sentiment.neutral, color: '#98A2B3' },
              { name: '负面', value: aggregates.post_sentiment.negative, color: '#E85D75' },
            ]}
            innerRadius={0.58}
            height={280}
          />
        </SectionCard>
        <SectionCard title="主题规模对比" subtitle="帖子 analysis.topic 的真实分布" tag="品类">
          <BarChart data={topicItems.map((item) => ({ name: item.label, value: item.value }))} height={300} />
        </SectionCard>
        <SectionCard title="品牌提及对比" subtitle="定向样本中的品牌提及帖子数，不是市场份额" tag="品牌">
          <BarChart
            data={aggregates.brand_sample_mentions.slice(0, 8).map((item) => ({ name: item.brand, value: item.posts }))}
            height={300}
          />
        </SectionCard>
      </div>

      <SectionCard title="社区 → 主题 → 情感流转" subtitle="真实帖子事实形成的三层关联；用于发现讨论语境，不代表用户旅程" tag="舆情">
        <SankeyChart nodes={sankeyNodes} links={sankeyLinks} height={380} />
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionCard title="Momcozy 品类 / SPU 讨论" subtitle="优先显示 exact SPU，其次产品族和品类；同一帖子可绑定多个层级对象" tag="品类">
          <BarChart data={productData} height={320} />
        </SectionCard>
        <SectionCard title="Momcozy 与竞品口碑观察分" subtitle="同一 Reddit 帖子样本内按净情感映射到 0–100；仅作描述性对比，不代表市场份额" tag="品牌">
          <BarChart data={brandScoreData} height={320} />
        </SectionCard>
      </div>

      <SectionCard title="标签词云" subtitle={`${manifest.tagging.dictionary_version} · 帖子与评论规则命中实体量`} tag="品类">
        <WordCloudChart data={tagCloud} height={330} />
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="card p-6" aria-labelledby="topic-analysis-title">
          <div className="mb-6">
            <h2 id="topic-analysis-title" className="text-h3 text-foreground">帖子主题</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">来自 analysis.topic；置信度是分析置信度，不是购买意向分</p>
          </div>
          <RankedBarList items={topicItems} />
        </section>

        <section className="card p-6" aria-labelledby="pain-point-title">
          <div className="mb-6">
            <h2 id="pain-point-title" className="text-h3 text-foreground">评论痛点信号</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">实体可多选，因此各维度之和不等于评论总数</p>
          </div>
          <RankedBarList items={painPointItems} colorClass="bg-status-warning" />
        </section>

        <section className="card p-6" aria-labelledby="subreddit-analysis-title">
          <div className="mb-6">
            <h2 id="subreddit-analysis-title" className="text-h3 text-foreground">社区样本构成</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">帖子数与已关联评论数；不是 Reddit 全站覆盖率</p>
          </div>
          <RankedBarList items={subredditItems} colorClass="bg-chart-1" />
        </section>

        <section className="card p-6" aria-labelledby="monthly-volume-title">
          <div className="mb-6">
            <h2 id="monthly-volume-title" className="text-h3 text-foreground">最近 12 个有数据月份</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">按帖子创建月份聚合；无数据月份未补零</p>
          </div>
          <RankedBarList items={recentMonths} colorClass="bg-chart-2" />
        </section>
      </div>

      <section className="card p-6" aria-labelledby="tag-analysis-title">
        <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="tag-analysis-title" className="text-h3 text-foreground">高频规则标签</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">
              {manifest.tagging.dictionary_version} · 词法规则匹配 · 待语义复核
            </p>
          </div>
          <span className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-tiny font-medium text-foreground-muted">
            规则提取 · 未晋级语义洞察
          </span>
        </div>
        <div className="grid gap-x-10 gap-y-4 lg:grid-cols-2">
          <RankedBarList items={topTags.slice(0, 5)} colorClass="bg-chart-3" />
          <RankedBarList items={topTags.slice(5)} colorClass="bg-chart-3" />
        </div>
      </section>

      <DataScopeBar contract={governance} />
    </SnapshotPageLayout>
  );
}
