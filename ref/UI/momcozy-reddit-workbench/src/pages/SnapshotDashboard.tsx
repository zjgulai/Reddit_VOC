import {
  ArrowRight,
  BarChart3,
  Database,
  FileText,
  GitCompare,
  Lightbulb,
  ListChecks,
  MessagesSquare,
  PackageSearch,
  ScanSearch,
  ShieldAlert,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import MetricHelpPopover from '../components/MetricHelpPopover';
import type { MetricHelpContent } from '../components/MetricHelpPopover';
import SectionCard from '../components/SectionCard';
import { ComposedChart } from '../components/charts';
import { SENTIMENT_COLORS } from '../constants/colors';
import { RankedBarList } from '../features/redditSnapshot/RankedBarList';
import { BrandHealthSnapshotCard } from '../features/redditSnapshot/BrandHealthSnapshotCard';
import {
  CROSS_PAGE_RECONCILIATION_RULE_CN,
  crossPageReconciliationAttributes,
} from '../features/redditSnapshot/crossPageReconciliation';
import { createBaseDataFreshness } from '../features/redditSnapshot/freshness';
import {
  createBaseGovernanceContract,
  DataScopeBar,
} from '../features/redditSnapshot/governance';
import {
  SnapshotErrorPage,
  SnapshotLoadingPage,
  SnapshotPageLayout,
} from '../features/redditSnapshot/SnapshotPageLayout';
import { buildSnapshotEvidenceHref } from '../features/redditSnapshot/evidenceLinks';
import {
  formatDateTime,
} from '../features/redditSnapshot/format';
import {
  highValueContent,
  isMomcozyPost,
  prioritySignals,
} from '../features/redditSnapshot/operational';
import type {
  RedditSnapshotCore,
  SnapshotPost,
} from '../features/redditSnapshot/types';
import type { QuarterDashboardWindow, QuarterInsightRanking } from '../features/redditSnapshot/quarterInsights';
import { useRedditBrandHealth } from '../features/redditSnapshot/useRedditBrandHealth';
import { useRedditQuarterInsights } from '../features/redditSnapshot/useRedditQuarterInsights';
import { useRedditSnapshot } from '../features/redditSnapshot/useRedditSnapshot';
import { useRedditSnapshotSummary } from '../features/redditSnapshot/useRedditSnapshotSummary';

type DashboardRange = 'near1week' | 'near1month' | 'near6months';

const DASHBOARD_RANGES: Array<{
  id: DashboardRange;
  label: string;
  windowId: QuarterDashboardWindow['id'];
}> = [
  { id: 'near1week', label: '近1周', windowId: 'rolling_7_days' },
  { id: 'near1month', label: '近1月', windowId: 'rolling_30_days' },
  { id: 'near6months', label: '近半年', windowId: 'rolling_183_days' },
];

const DASHBOARD_RANGE_IDS = new Set(DASHBOARD_RANGES.map((item) => item.id));

function formatShanghaiDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}`;
}

function postBusinessDate(post: SnapshotPost): string {
  if (post.event_time_precision === 'day' && post.source_calendar_date) {
    return post.source_calendar_date.slice(0, 10);
  }
  return formatShanghaiDate(post.event_created_at_utc ?? post.created_at_utc);
}

function rangeOption(range: DashboardRange) {
  return DASHBOARD_RANGES.find((item) => item.id === range) ?? DASHBOARD_RANGES[1];
}

function postsInRange(posts: SnapshotPost[], start: string, end: string): SnapshotPost[] {
  return posts.filter((post) => {
    const date = postBusinessDate(post);
    return date >= start && date <= end;
  });
}

interface DashboardTrendPoint {
  label: string;
  barValue: number;
  barValue2: number;
  lineValue: number;
}

function buildRangeTrend(
  window: QuarterDashboardWindow,
): DashboardTrendPoint[] {
  return window.buckets.map((bucket) => ({
    label: window.bucket_grain === 'day' ? bucket.bucket.slice(5) : bucket.bucket,
    barValue: bucket.post_vocs,
    barValue2: bucket.comment_context_vocs,
    lineValue: bucket.negative_rate ?? Number.NaN,
  }));
}

function rankedQuarterItems(rows: QuarterInsightRanking[], detail: string) {
  return rows.map((row) => ({
    label: row.label,
    value: row.count,
    detail,
  }));
}

// exact_spu_rankings 必须是真实 SPU 级证据。当生产者只给出主题级计数（与
// product_rankings 完全同值）时，把它当成 SPU 展示就是"家族冒充精确 SPU"——
// 返回空数组，让卡片渲染诚实空态。family_only_ids 里有对应 _family 后缀时
// 同样视为无 SPU 数据。
function dedupeSpuRankings(
  exactSpu: QuarterInsightRanking[],
  productRankings: QuarterInsightRanking[],
): QuarterInsightRanking[] {
  if (exactSpu.length === 0) return [];
  const sameAsProduct =
    exactSpu.length === productRankings.length &&
    exactSpu.every((row, index) => row.id === productRankings[index]?.id && row.count === productRankings[index]?.count);
  return sameAsProduct ? [] : exactSpu;
}

function DashboardStoryMap({
  topDriver,
  riskCount,
  topProduct,
  topCompetitor,
  opportunityCount,
}: {
  topDriver: string;
  riskCount: number;
  topProduct: string;
  topCompetitor: string;
  opportunityCount: number;
}) {
  const highlights = [
    {
      title: '用户痛点',
      description: `最近季度首要体验阻力为“${topDriver}”；从品类、产品族、SPU 与证据帖定位真实使用阻力。`,
      href: '/dashboard/insights?theme=pain',
      icon: ScanSearch,
      action: '查看痛点证据',
    },
    {
      title: '舆情与内容合规',
      description: `最近季度有 ${riskCount.toLocaleString('zh-CN')} 条 Momcozy 高严重度 VOC；机器人与自动化评论只作内容类型观察，不直接归因品牌。`,
      href: '/dashboard/insights?theme=reputation',
      icon: ShieldAlert,
      action: '查看风险与合规',
    },
    {
      title: '新品机会',
      description: `围绕“${topProduct}”等品类证据识别未满足需求；产品家族与精确 SPU 分层，不把家族证据冒充具体商品。`,
      href: '/dashboard/insights?theme=new-product',
      icon: PackageSearch,
      action: '查看需求机会',
    },
    {
      title: 'GEO 优化机会',
      description: `${opportunityCount.toLocaleString('zh-CN')} 条比较 / 决策型 Reddit 帖子构成问题库；“${topCompetitor}”是主要竞对语境，优先补齐透明、可验证的决策内容。`,
      href: '/dashboard/insights?theme=geo',
      icon: Lightbulb,
      action: '查看 GEO 问题库',
    },
  ];

  return (
    <section
      className="card p-6"
      data-testid="dashboard-insight-story"
      aria-labelledby="dashboard-story-title"
    >
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-tiny font-semibold uppercase tracking-[0.18em] text-primary">Executive digest</p>
          <h2 id="dashboard-story-title" className="mt-1 text-h2 text-foreground">四类经营决策入口</h2>
          <p className="mt-1 text-caption text-foreground-muted">以最近季度 Reddit 数据为主干，从问题判断直接进入证据与行动</p>
        </div>
        <Link to="/dashboard/reports" className="inline-flex items-center gap-1 text-body-sm font-medium text-primary hover:text-primary-hover">
          进入日报 / 周报 / 月报 <ArrowRight className="h-4 w-4" strokeWidth={1.5} />
        </Link>
      </div>

      <div className="divide-y divide-border-divider border-y border-border-divider">
        {highlights.map((item) => {
          const Icon = item.icon;
          return (
            <Link key={item.title} to={item.href} className="group grid gap-3 py-4 transition-colors hover:bg-primary-light/25 sm:grid-cols-[auto_1fr_auto] sm:items-center sm:px-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-light text-primary">
                <Icon className="h-4.5 w-4.5" strokeWidth={1.5} aria-hidden="true" />
              </span>
              <span>
                <strong className="block text-body-sm font-semibold text-foreground">{item.title}</strong>
                <span className="mt-0.5 block text-caption leading-relaxed text-foreground-secondary">{item.description}</span>
              </span>
              <span className="inline-flex items-center gap-1 text-tiny font-semibold text-primary">
                {item.action} <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden="true" />
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function DashboardRangeSummary({
  activeRange,
  anchorDate,
  sourceSnapshotId,
  startDate,
  endDate,
  momcozyPostCount,
  commentContextVocCount,
  totalVocCount,
  negativeRate,
  topCompetitor,
  onRangeChange,
}: {
  activeRange: DashboardRange;
  anchorDate: string;
  sourceSnapshotId: string;
  startDate: string;
  endDate: string;
  momcozyPostCount: number;
  commentContextVocCount: number;
  totalVocCount: number;
  negativeRate: number | null;
  topCompetitor: QuarterDashboardWindow['top_competitor'];
  onRangeChange: (range: DashboardRange) => void;
}) {
  const reconciliationAttributes = crossPageReconciliationAttributes({
    page: 'overview',
    sourceSnapshotId,
    scope: 'momcozy',
    vocType: 'post_voc+comment_context_voc',
    startDate,
    endDate,
    endBoundary: 'inclusive',
  });
  const items: Array<{
    icon: ReactNode;
    label: string;
    value: string;
    note: string;
    rawValue: string;
    help: MetricHelpContent;
  }> = [
    {
      icon: <FileText className="h-4 w-4" />,
      label: 'Momcozy 相关帖子',
      value: momcozyPostCount.toLocaleString('zh-CN'),
      rawValue: String(momcozyPostCount),
      note: '经治理品牌事实确认的帖子 VOC',
      help: {
        definition: '时间窗口内，经 promoted entity-brand fact 确认 brand_id = momcozy 的去重帖子 VOC。',
        formula: 'Momcozy 帖子 VOC = count(distinct post_voc where exists promoted entity_brand_fact(brand_id = "momcozy") and content_entity_event_date in window)。',
        notes: ['每条内容实体使用自身事件日落窗，时区为 Asia/Shanghai。', '不使用公开明细中的提及词或产品词进行启发式估算。'],
      },
    },
    {
      icon: <MessagesSquare className="h-4 w-4" />,
      label: 'VOC 观察量',
      value: totalVocCount.toLocaleString('zh-CN'),
      rawValue: String(totalVocCount),
      note: `${momcozyPostCount.toLocaleString('zh-CN')} 帖子 VOC + ${commentContextVocCount.toLocaleString('zh-CN')} 评论上下文 VOC`,
      help: {
        definition: '帖子本身是一条 post_voc；已关联评论是一条 comment_context_voc。两者均必须通过 Momcozy 治理品牌事实。',
        formula: 'VOC 观察量 = count(post_voc) + count(comment_context_voc), where promoted entity_brand_fact.brand_id = "momcozy" and content_entity_event_date in window。',
        notes: ['帖子与评论均按各自内容实体事件日落窗，不按父帖日期替评论落窗。', '待父帖关联评论不伪造上下文。'],
      },
    },
    {
      icon: <ShieldAlert className="h-4 w-4" />,
      label: '负面 VOC 占比',
      value: negativeRate === null ? '—' : `${negativeRate.toFixed(2)}%`,
      rawValue: negativeRate === null ? '' : String(negativeRate),
      note: '已分类 Momcozy 帖子 + 评论上下文 VOC',
      help: {
        definition: '时间窗口内，已确认 Momcozy 品牌关联的 VOC 中，情感分类为负向的占比。',
        formula: '负面 VOC 占比 = negative_vocs / classified_vocs × 100%；classified_vocs = positive + neutral + negative。',
        notes: ['未分类 VOC 不进入分母。', '该指标不代表市场份额或 Reddit 全站舆情。'],
      },
    },
    {
      icon: <GitCompare className="h-4 w-4" />,
      label: '主要竞对语境',
      value: topCompetitor.label,
      rawValue: String(topCompetitor.voc_count),
      note: `${topCompetitor.voc_count.toLocaleString('zh-CN')} 条已确认品牌关联 VOC，与 Momcozy 可重叠`,
      help: {
        definition: '同一窗口内，通过 promoted entity-brand facts 关联的非 Momcozy 品牌中，VOC 数量最高的品牌。',
        formula: '主要竞对 = argmax_brand count(distinct content_voc_id where promoted entity_brand_fact.brand_id = brand and brand ≠ "momcozy" and content_entity_event_date in window)。',
        notes: ['同一 VOC 可同时关联 Momcozy 和竞品，因此不是互斥份额。', '该数据不代表市场份额或销量。'],
      },
    },
  ];

  return (
    <section
      className="card p-5 sm:p-6"
      aria-labelledby="dashboard-window-title"
      data-testid="dashboard-range-summary"
      data-range={activeRange}
      data-anchor-date={anchorDate}
      data-start-date={startDate}
      data-end-date={endDate}
      {...reconciliationAttributes}
    >
      <div className="flex flex-col gap-4 border-b border-border-divider pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-tiny font-semibold uppercase tracking-[0.16em] text-primary">Latest business window</p>
          <h2 id="dashboard-window-title" className="mt-1 text-h2 text-foreground">核心经营指标</h2>
          <p className="mt-1 text-caption text-foreground-muted">
            {startDate} 至 {endDate} · 锚定最新业务日 {anchorDate} · Momcozy 为主干
          </p>
          <p className="mt-2 max-w-3xl text-tiny leading-relaxed text-foreground-muted">
            {CROSS_PAGE_RECONCILIATION_RULE_CN} 当前为滚动业务窗口。
          </p>
        </div>
        <div className="inline-flex w-fit rounded-button border border-border-divider bg-surface-secondary p-1" role="tablist" aria-label="概览时间范围">
          {DASHBOARD_RANGES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={activeRange === item.id}
              onClick={() => onRangeChange(item.id)}
              className={`rounded-[9px] px-4 py-2 text-body-sm font-medium transition-all ${
                activeRange === item.id
                  ? 'bg-white text-primary shadow-card ring-1 ring-primary/25'
                  : 'text-foreground-muted hover:text-foreground'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <dl className="grid gap-4 pt-5 sm:grid-cols-2 xl:grid-cols-4 xl:divide-x xl:divide-border-divider">
        {items.map((item, index) => (
          <div key={item.label} className="min-w-0 xl:px-5 first:xl:pl-0 last:xl:pr-0" data-kpi-label={item.label} data-kpi-value={item.rawValue}>
            <div className="flex items-start justify-between gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light text-primary">{item.icon}</span>
              <MetricHelpPopover label={item.label} align={index === 0 ? 'left' : 'right'} {...item.help} />
            </div>
            <dd className="mt-4 truncate text-[30px] font-semibold leading-none tracking-[-0.02em] text-foreground">{item.value}</dd>
            <dt className="mt-2 text-body-sm font-semibold text-foreground-secondary">{item.label}</dt>
            <p className="mt-1 text-tiny leading-relaxed text-foreground-muted">{item.note}</p>
          </div>
        ))}
      </dl>
    </section>
  );
}

function EvidenceList({
  title,
  posts,
  emptyText,
  snapshot,
}: {
  title: string;
  posts: SnapshotPost[];
  emptyText: string;
  snapshot: RedditSnapshotCore;
}) {
  return (
    <div>
      <h3 className="text-body-sm font-semibold text-foreground">{title}</h3>
      {posts.length > 0 ? (
        <div className="mt-3 divide-y divide-border-divider">
          {posts.slice(0, 3).map((post) => (
            <Link
              key={post.post_id}
              to={buildSnapshotEvidenceHref({
                postId: post.post_id,
                releaseId: snapshot.release.release_id,
                snapshotId: snapshot.manifest.dataset_version,
                source: 'dashboard',
              })}
              className="block py-3 first:pt-0 hover:text-primary"
            >
              <div className="flex flex-wrap items-center gap-2 text-tiny text-foreground-muted">
                <span>r/{post.subreddit || 'unknown'}</span><span>·</span><time dateTime={post.created_at_utc}>{formatDateTime(post.created_at_utc)}</time><span>·</span><span>{post.score} Score / {post.linked_comment_count} 评论</span>
              </div>
              <p className="mt-1 line-clamp-2 text-body-sm font-medium text-foreground">{post.title}</p>
            </Link>
          ))}
        </div>
      ) : <p className="mt-3 text-caption text-foreground-muted">{emptyText}</p>}
    </div>
  );
}

function EvidenceListLoading({ title, error }: { title: string; error?: string | null }) {
  return (
    <div aria-busy={error ? undefined : 'true'}>
      <h3 className="text-body-sm font-semibold text-foreground">{title}</h3>
      <div className="mt-3 rounded-card border border-dashed border-border-divider bg-surface-secondary/50 px-4 py-5 text-caption text-foreground-muted">
        {error ? `证据明细暂不可用：${error}` : '核心指标已呈现，真实帖子证据正在后台加载……'}
      </div>
    </div>
  );
}

export default function SnapshotDashboard() {
  const { data: summary, error: summaryError, isLoading: summaryIsLoading } = useRedditSnapshotSummary();
  const { data: snapshot, error: snapshotError } = useRedditSnapshot();
  const brandHealth = useRedditBrandHealth();
  const quarterInsights = useRedditQuarterInsights();
  const [searchParams, setSearchParams] = useSearchParams();

  if (summaryIsLoading || quarterInsights.isLoading) return <SnapshotLoadingPage icon={BarChart3} title="真实数据概览" />;
  if (summaryError || !summary || quarterInsights.error || !quarterInsights.data) {
    return (
      <SnapshotErrorPage
        icon={BarChart3}
        title="真实数据概览"
        error={summaryError ?? quarterInsights.error ?? '未知错误'}
      />
    );
  }

  const { manifest } = summary;
  const posts = snapshot?.posts ?? [];
  const quarterData = quarterInsights.data.data;
  const governance = createBaseGovernanceContract(summary.release, summary);
  const rangeParam = searchParams.get('range');
  const activeRange: DashboardRange = DASHBOARD_RANGE_IDS.has(rangeParam as DashboardRange)
    ? rangeParam as DashboardRange
    : 'near1month';
  const selectedRange = rangeOption(activeRange);
  const dashboardWindow = quarterData.dashboard_windows.find((window) => window.id === selectedRange.windowId);
  if (!dashboardWindow) {
    return <SnapshotErrorPage icon={BarChart3} title="真实数据概览" error={`${selectedRange.windowId}窗口投影缺失`} />;
  }
  const anchorDate = quarterData.period.anchor_date;
  const startDate = dashboardWindow.start_date;
  const endDate = dashboardWindow.end_date;
  const rangePosts = postsInRange(posts, startDate, endDate);
  const momcozyPosts = rangePosts.filter(isMomcozyPost);
  const rangeSnapshot = snapshot ? { ...snapshot, posts: rangePosts } : null;
  const riskSignals = rangeSnapshot ? prioritySignals(rangeSnapshot) : [];
  const contentOpportunities = rangeSnapshot ? highValueContent(rangeSnapshot) : [];
  const governedMetrics = dashboardWindow.momcozy;

  const changeRange = (range: DashboardRange) => {
    const next = new URLSearchParams(searchParams);
    next.set('range', range);
    setSearchParams(next);
  };

  const painRankings = quarterData.themes.pain.rankings;
  const reputationRankings = quarterData.themes.reputation.rankings;
  // 家族/品类/SPU 是三层不同的口径：family_rankings 是产品家族、category_rankings
  // 是品类议题、exact_spu_rankings 只有已批准的精确 SPU。历史 bug：家族列绑了
  // product_rankings（主题计数），而 exact_spu_rankings 的生产者把主题计数原样
  // 复制进来，两列同值——家族证据冒充了精确 SPU。SPU 无真实数据时显示空态。
  const familyRankings = quarterData.themes.new_product.family_rankings;
  const categoryRankings = quarterData.themes.new_product.category_rankings;
  // product_rankings 是主题级计数（问题排查/产品评价），仍用于"产品归因下钻"
  // 行动卡等主题语境；家族/品类/SPU 三列各自绑定对应口径。
  const productRankings = quarterData.themes.new_product.product_rankings;
  const exactSpuRankings = dedupeSpuRankings(
    quarterData.themes.new_product.exact_spu_rankings,
    quarterData.themes.new_product.product_rankings,
  );

  const topCompetitor = dashboardWindow.top_competitor;
  const topBrands = [
    {
      label: 'Momcozy（主品牌）',
      value: governedMetrics.total_vocs,
      detail: `· ${selectedRange.label}已确认品牌关联 VOC，内容实体事件日落窗`,
    },
    {
      label: topCompetitor.label,
      value: topCompetitor.voc_count,
      detail: `· ${selectedRange.label}已确认品牌关联 VOC，与 Momcozy 可重叠，非市场份额`,
    },
  ];
  const rangeTrend = buildRangeTrend(dashboardWindow);

  const titleCounts = new Map<string, number>();
  for (const post of posts) titleCounts.set(post.title, (titleCounts.get(post.title) ?? 0) + 1);
  const duplicateTitleGroups = [...titleCounts.values()].filter((count) => count > 1).length;

  return (
    <SnapshotPageLayout
      icon={BarChart3}
      title="真实数据概览"
      description="Momcozy 主干 · 从品牌健康判断到可执行行动"
      datasetVersion={manifest.dataset_version}
      freshness={createBaseDataFreshness(summary, {
        projectionAsOfLabel: '季度业务截至',
        projectionAsOf: anchorDate,
        projectionAsOfBasis: '来自季度正式投影 period.anchor_date，按 Asia/Shanghai 业务日解释',
        projectionDatasetVersion: quarterData.dataset_version,
        projectionGeneratedAtUtc: quarterData.generated_at_utc,
      })}
    >
      <div className="space-y-4 sm:space-y-5" data-testid="dashboard-primary-story">
        <DataScopeBar contract={governance} />

        <DashboardRangeSummary
          activeRange={activeRange}
          anchorDate={anchorDate}
          sourceSnapshotId={quarterData.source.source_snapshot_id}
          startDate={startDate}
          endDate={endDate}
          momcozyPostCount={governedMetrics.post_vocs}
          commentContextVocCount={governedMetrics.comment_context_vocs}
          totalVocCount={governedMetrics.total_vocs}
          negativeRate={governedMetrics.negative_rate}
          topCompetitor={topCompetitor}
          onRangeChange={changeRange}
        />

        <div id="overall-judgement" className="scroll-mt-24">
          <BrandHealthSnapshotCard {...brandHealth} sampleSize={snapshot ? snapshot.posts.filter(isMomcozyPost).length : null} />
        </div>

        <section
          id="trend-change"
          className="scroll-mt-24"
          aria-labelledby="trend-change-title"
          data-dashboard-window={dashboardWindow.id}
          data-bucket-grain={dashboardWindow.bucket_grain}
          data-bucket-count={dashboardWindow.buckets.length}
        >
          <SectionCard
            title="趋势变化"
            subtitle={`${selectedRange.label} · ${startDate} 至 ${endDate} · 已确认品牌关联的内容实体按自身事件日落窗，线为已分类 VOC 负面占比`}
            tag="舆情"
            icon={<TrendingUp className="h-5 w-5 text-primary" strokeWidth={1.5} />}
          >
            <ComposedChart
              data={rangeTrend}
              height={320}
              barName="Momcozy 帖子 VOC"
              secondBarName="Momcozy 评论上下文 VOC"
              lineName="负面 VOC 占比（%）"
              barColor="#F8A67B"
              secondBarColor="#D19A5C"
              lineColor={SENTIMENT_COLORS.negative}
              leftAxisLabel="观察量"
              rightAxisLabel="占比 %"
              ariaLabel={`${selectedRange.label} Momcozy 帖子 VOC、评论上下文 VOC 与负面 VOC 占比双坐标趋势`}
            />
          </SectionCard>
        </section>

        <DashboardStoryMap
          topDriver={painRankings[0]?.label ?? '待继续观察'}
          riskCount={quarterData.themes.reputation.high_severity_vocs}
          topProduct={categoryRankings[0]?.label ?? productRankings[0]?.label ?? '待继续观察'}
          topCompetitor={topCompetitor.label}
          opportunityCount={quarterData.themes.geo.comparison_decision_posts}
        />

        <section id="priority-actions" className="card scroll-mt-24 p-6" aria-labelledby="priority-actions-title" data-testid="dashboard-priority-actions">
          <div className="mb-5 flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light text-primary"><ListChecks className="h-5 w-5" strokeWidth={1.5} /></span>
            <div><h2 id="priority-actions-title" className="text-h3 text-foreground">优先行动</h2><p className="mt-0.5 text-caption text-foreground-muted">最近季度正式投影 · 不生成虚构回复、处理状态、责任人或截止时间</p></div>
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            <Link to="/dashboard/messages" className="rounded-card border border-status-error/15 bg-status-errorBg/55 p-4 transition-colors hover:border-status-error/30">
              <p className="text-tiny font-semibold text-status-error">P0 · 风险复核</p>
              <p className="mt-2 text-body-sm font-semibold text-foreground">先复核 {quarterData.themes.reputation.high_severity_vocs.toLocaleString('zh-CN')} 条高严重度 VOC</p>
              <p className="mt-1 text-caption text-foreground-muted">以季度正式投影为总量，下方站内真实原帖只作可点击证据入口。</p>
            </Link>
            <Link to="/dashboard/analytics" className="rounded-card border border-primary/15 bg-primary-light/55 p-4 transition-colors hover:border-primary/30">
              <p className="text-tiny font-semibold text-primary">P1 · 产品归因</p>
              <p className="mt-2 text-body-sm font-semibold text-foreground">下钻 {productRankings[0]?.label ?? '主要品类'}</p>
              <p className="mt-1 text-caption text-foreground-muted">联合情感、主题、互动量和证据帖，验证问题是否集中在特定 SPU。</p>
            </Link>
            <Link to="/dashboard/insights?theme=geo" className="rounded-card border border-status-success/15 bg-status-successBg/55 p-4 transition-colors hover:border-status-success/30">
              <p className="text-tiny font-semibold text-status-success">P1 · GEO 内容建设</p>
              <p className="mt-2 text-body-sm font-semibold text-foreground">覆盖 {quarterData.themes.geo.comparison_decision_posts.toLocaleString('zh-CN')} 条比较 / 决策问题</p>
              <p className="mt-1 text-caption text-foreground-muted">先回答适用人群、失败模式、排障与竞品差异，保留透明品牌披露。</p>
            </Link>
          </div>
          <div className="mt-6 grid gap-6 border-t border-border-divider pt-5 lg:grid-cols-2">
            {snapshot ? <EvidenceList title="站内高互动原帖（仅证据下钻）" posts={contentOpportunities} emptyText="当前没有达到 Score 或评论阈值的真实帖子。" snapshot={snapshot} /> : <EvidenceListLoading title="站内高互动原帖（仅证据下钻）" error={snapshotError} />}
            {snapshot ? <EvidenceList title="站内最新 Momcozy 原帖（仅证据下钻）" posts={[...momcozyPosts].sort((left, right) => right.created_at_utc.localeCompare(left.created_at_utc))} emptyText="当前没有 Momcozy 相关帖子。" snapshot={snapshot} /> : <EvidenceListLoading title="站内最新 Momcozy 原帖（仅证据下钻）" error={snapshotError} />}
          </div>
        </section>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <section id="key-drivers" className="scroll-mt-24" aria-labelledby="key-drivers-title">
          <SectionCard title="关键驱动" subtitle="最近季度 Momcozy 已确认品牌关联 VOC 痛点排名；多标签可重叠，不是互斥份额" tag="品牌" icon={<Sparkles className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
            <RankedBarList items={rankedQuarterItems(painRankings, '· 最近季度已确认品牌关联 VOC，多标签')} />
          </SectionCard>
        </section>

        <section id="risk-focus" className="scroll-mt-24" aria-labelledby="risk-focus-title">
          <SectionCard title="风险焦点" subtitle="最近季度正式风险投影；自动化评论仅为内容类型观察，不是 Momcozy 机器人归因" tag="舆情" icon={<ShieldAlert className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
            <RankedBarList items={rankedQuarterItems(reputationRankings, '· 最近季度已确认品牌关联 VOC / 审计证据')} />
            <div className="mt-5 border-t border-border-divider pt-5">
              {snapshot ? <EvidenceList title="站内可下钻风险原帖（仅证据入口）" posts={riskSignals} emptyText="当前没有命中原帖筛选规则的真实帖子。" snapshot={snapshot} /> : <EvidenceListLoading title="站内可下钻风险原帖（仅证据入口）" error={snapshotError} />}
            </div>
          </SectionCard>
        </section>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <section id="product-opportunity" className="scroll-mt-24" aria-labelledby="product-opportunity-title">
          <SectionCard title="品类机会" subtitle="最近季度已确认品牌关联 VOC；产品家族与精确 SPU 分层展示，不把家族证据冒充精确 SPU" tag="品类" icon={<PackageSearch className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
            <div className="grid gap-6 md:grid-cols-3">
              <div>
                <h3 className="mb-3 text-body-sm font-semibold text-foreground">品类</h3>
                <RankedBarList items={rankedQuarterItems(categoryRankings, '· 品类议题证据')} />
              </div>
              <div>
                <h3 className="mb-3 text-body-sm font-semibold text-foreground">产品家族</h3>
                <RankedBarList items={rankedQuarterItems(familyRankings, '· 产品家族证据')} />
              </div>
              <div>
                <h3 className="mb-3 text-body-sm font-semibold text-foreground">精确 SPU</h3>
                {exactSpuRankings.length > 0
                  ? <RankedBarList items={rankedQuarterItems(exactSpuRankings, '· 已批准精确 SPU 证据')} />
                  : <p className="text-body-sm text-foreground-muted">暂无已批准的精确 SPU 映射；产品家族证据不冒充精确 SPU。</p>}
              </div>
            </div>
          </SectionCard>
        </section>

        <section id="competitor-reference" className="scroll-mt-24" aria-labelledby="competitor-reference-title">
          <SectionCard title="竞品参照" subtitle="Momcozy 为主干；竞对按同窗口受治理品牌事实统计，品牌可重叠，不是市场份额" tag="品牌" icon={<GitCompare className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
            <RankedBarList items={topBrands} />
          </SectionCard>
        </section>
      </div>

      <details className="card p-5">
        <summary className="flex cursor-pointer list-none items-center gap-3 text-body-sm font-semibold text-foreground">
          <Database className="h-5 w-5 text-primary" strokeWidth={1.5} />
          数据基础与来源边界
        </summary>
        <div className="mt-4 grid gap-3 text-caption text-foreground-secondary md:grid-cols-2">
          {Object.entries(manifest.source_boundaries ?? {}).map(([key, value]) => (
            <div key={key} className="rounded-card bg-surface-tertiary p-3"><strong className="block text-tiny uppercase tracking-wide text-foreground-muted">{key.replaceAll('_', ' ')}</strong><span className="mt-1 block leading-relaxed">{value}</span></div>
          ))}
          {!manifest.source_boundaries && <div className="rounded-card bg-surface-tertiary p-3">公开数据不展示内部来源路径；数据来源由版本化校验记录约束。</div>}
          <div className="rounded-card bg-surface-tertiary p-3">同标题多 Reddit ID 组：<strong className="ml-1 text-foreground">{duplicateTitleGroups}</strong>；转帖保留，不当作重复 ID 删除。</div>
          {manifest.schema_version === 'reddit_voc_site_snapshot_manifest_v3' && (
            <div className="rounded-card bg-surface-tertiary p-3">待关联评论：<strong className="ml-1 text-foreground">{(manifest.canonical_counts.unresolved_parent_comments ?? 0).toLocaleString('zh-CN')}</strong>；已保留在数据账本，父帖关系确认前不进入帖子评论明细。</div>
          )}
        </div>
      </details>

    </SnapshotPageLayout>
  );
}
