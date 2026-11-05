import {
  Activity,
  BarChart3,
  ExternalLink,
  FileText,
  Hash,
  MessageSquare,
  MessagesSquare,
  ShieldCheck,
  Tag,
  Target,
  TrendingUp,
  Users,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import ProductAnalysisPanel from './ProductAnalysisPanel';
import RiskThemePanel from './RiskThemePanel';
import OperationalReportSupplement from './OperationalReportSupplement';
import ReportIndicatorMonitor from './ReportIndicatorMonitor';
import SectionCard from '../SectionCard';
import { RankedBarList } from '../../features/redditSnapshot/RankedBarList';
import { SnapshotMetricCard } from '../../features/redditSnapshot/SnapshotMetricCard';
import {
  MetricComparisonCard,
  type MetricComparisonValue,
} from '../../features/redditSnapshot/MetricComparisonCard';
import {
  decodeHtmlEntities,
  formatDateTime,
  formatPainPoint,
  formatSeriesLabel,
  formatTopic,
  SENTIMENT_LABELS,
} from '../../features/redditSnapshot/format';
import type {
  DisplayableRedditReport,
  RedditReport,
  ReportBrandBinding,
  ReportPeriod,
  RiskRedditReport,
  V3CurrentReport,
} from '../../features/redditSnapshot/reports';
import {
  historicalCompletenessPresentation,
  isRiskReport,
  isV3Report,
} from '../../features/redditSnapshot/reports';
import type {
  RedditSnapshotCore,
  RiskComparison,
  RiskEntityType,
  RiskObservedCount,
  RiskShareMetric,
} from '../../features/redditSnapshot/types';

const BINDING_LABELS: Partial<Record<ReportBrandBinding, string>> = {
  momcozy_sentence_bound: 'Momcozy 同句绑定',
  momcozy_entity_cooccurrence: 'Momcozy 实体共现',
  multi_brand: '多品牌内容',
  competitor_explicit: '竞品明确',
  category_general: '通用品类',
};

function formatPercent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

export function formatReportTimelineLabel(value: string, bucketGrain: 'hour' | 'day'): string {
  return bucketGrain === 'day'
    ? formatSeriesLabel(value.slice(0, 10), 'day')
    : formatSeriesLabel(value, 'hour', 'Asia/Shanghai');
}

export function formatReportTrendLabel(value: string, period: ReportPeriod): string {
  if (period === 'monthly') return formatSeriesLabel(value.slice(0, 7), 'month');
  return formatSeriesLabel(value.slice(0, 10), period === 'weekly' ? 'week' : 'day');
}

function ObservedVolumeChart({ report }: { report: RedditReport }) {
  const completeness = historicalCompletenessPresentation(report);
  const data = report.observed_timeline.map((point) => ({
    label: formatReportTimelineLabel(point.bucket_start_local, report.window.bucket_grain),
    帖子: point.posts,
    评论: point.voc_comments,
  }));
  return (
    <SectionCard
      title="已观察记录量"
      subtitle={`${report.window.bucket_grain === 'hour' ? '小时' : '日期'}粒度 · 帖子 ${report.headline.posts.toLocaleString('zh-CN')} · VOC 评论 ${report.headline.voc_comments.toLocaleString('zh-CN')} · ${completeness.label}`}
      tag="舆情"
      icon={<BarChart3 className="h-5 w-5 text-primary" strokeWidth={1.5} />}
    >
      <div className="mb-3 flex items-center gap-4 text-tiny text-foreground-muted" aria-hidden="true">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-primary" />帖子</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-chart-1" />VOC 评论</span>
      </div>
      <div className="h-[280px]" aria-label="窗口内已观察帖子与评论记录量图表">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: '#6B7280' }}
              axisLine={{ stroke: '#E5E7EB' }}
              tickLine={false}
              minTickGap={18}
            />
            <YAxis tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip
              contentStyle={{
                backgroundColor: '#fff',
                border: '1px solid #EDEDED',
                borderRadius: '12px',
                boxShadow: '0 4px 12px rgba(0,0,0,0.06)',
                fontSize: '12px',
              }}
            />
            <Bar dataKey="帖子" fill="#E85D75" radius={[3, 3, 0, 0]} />
            <Bar dataKey="评论" fill="#7C8CF8" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </SectionCard>
  );
}

function SignalCards({ report }: { report: RedditReport }) {
  return (
    <section className="card p-6" aria-labelledby="promoted-signals-title">
      <div className="mb-6 flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light">
          <Tag className="h-[18px] w-[18px] text-primary" strokeWidth={1.5} />
        </div>
        <div>
          <h2 id="promoted-signals-title" className="text-h3 text-foreground">已通过门禁的标签信号</h2>
          <p className="mt-0.5 text-caption text-foreground-muted">
            只包含工作场景与强烈推荐；计数是内容实体，不是用户或画像规模
          </p>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {report.promoted_signals.map((signal) => (
          <article key={signal.tag_id} className="rounded-card border border-border-divider p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-tiny font-medium text-primary">{signal.tag_id}</p>
                <h3 className="mt-1 text-body font-semibold text-foreground">{signal.name_cn}</h3>
                <p className="mt-0.5 text-caption text-foreground-muted">{signal.theme}</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-semibold leading-none text-foreground">{signal.matched_entities}</p>
                <p className="mt-1 text-tiny text-foreground-muted">匹配内容实体</p>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-caption">
              <div className="rounded-icon bg-surface-tertiary px-3 py-2 text-foreground-secondary">帖子 {signal.matched_posts}</div>
              <div className="rounded-icon bg-surface-tertiary px-3 py-2 text-foreground-secondary">评论 {signal.matched_comments}</div>
            </div>
            <dl className="mt-4 space-y-2 text-caption">
              {(Object.entries(signal.binding_counts) as [ReportBrandBinding, number][]).map(([binding, count]) => (
                <div key={binding} className="flex items-center justify-between gap-3">
                  <dt className="text-foreground-muted">{BINDING_LABELS[binding] ?? binding}</dt>
                  <dd className={`font-medium ${binding === 'momcozy_sentence_bound' ? 'text-primary' : 'text-foreground'}`}>{count}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-4 rounded-icon bg-primary-light/60 px-3 py-2 text-caption leading-relaxed text-foreground-secondary">
              字典参考卡片：{signal.dictionary_reference.consumer_card}（仅映射维度，不是用户画像）
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function AttentionList({ report }: { report: RedditReport }) {
  return (
    <SectionCard
      title="关注项"
      subtitle="确定性筛选的负面或高规则严重度帖子；不代表危机等级或响应 SLA"
      tag="舆情"
      icon={<Target className="h-5 w-5 text-primary" strokeWidth={1.5} />}
    >
      {report.attention_items.length ? (
        <div className="divide-y divide-border-divider">
          {report.attention_items.map((item) => (
            <a
              key={item.attention_id}
              href={item.permalink}
              target="_blank"
              rel="noreferrer"
              className="group flex items-start justify-between gap-4 py-4 first:pt-0 last:pb-0"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-tiny text-foreground-muted">
                  <span>r/{item.subreddit}</span><span>·</span>
                  <time dateTime={item.created_at_utc}>{formatDateTime(item.created_at_utc)}</time>
                  <span className="rounded-badge bg-status-warningBg px-2 py-0.5 text-status-warning">{item.severity}</span>
                  <span className="rounded-badge bg-status-errorBg px-2 py-0.5 text-status-error">{SENTIMENT_LABELS[item.sentiment]}</span>
                </div>
                <h3 className="mt-1.5 line-clamp-2 text-body-sm font-medium text-foreground group-hover:text-primary">{decodeHtmlEntities(item.title)}</h3>
                <p className="mt-1 text-tiny text-foreground-muted">{item.score} 分 · {item.linked_comment_count} 条关联评论</p>
              </div>
              <ExternalLink className="mt-1 h-4 w-4 shrink-0 text-foreground-muted group-hover:text-primary" strokeWidth={1.5} />
            </a>
          ))}
        </div>
      ) : (
        <p className="text-body-sm text-foreground-muted">当前窗口没有符合规则的关注项。</p>
      )}
    </SectionCard>
  );
}

function EvidenceList({ report }: { report: RedditReport }) {
  return (
    <SectionCard
      title="证据帖子"
      subtitle="按当前窗口互动记录排序，点击返回 Reddit 原文"
      tag="舆情"
      icon={<FileText className="h-5 w-5 text-primary" strokeWidth={1.5} />}
    >
      <div className="divide-y divide-border-divider">
        {report.evidence_posts.slice(0, 8).map((post) => (
          <a
            key={post.post_id}
            href={post.permalink}
            target="_blank"
            rel="noreferrer"
            className="group block py-4 first:pt-0 last:pb-0"
          >
            <div className="flex flex-wrap items-center gap-2 text-tiny text-foreground-muted">
              <span>r/{post.subreddit}</span><span>·</span>
              <span>{formatTopic(post.topic)}</span><span>·</span>
              <time dateTime={post.created_at_utc}>{formatDateTime(post.created_at_utc)}</time>
            </div>
            <div className="mt-1.5 flex items-start justify-between gap-3">
              <h3 className="line-clamp-2 text-body-sm font-medium text-foreground group-hover:text-primary">{decodeHtmlEntities(post.title)}</h3>
              <ExternalLink className="mt-0.5 h-4 w-4 shrink-0 text-foreground-muted group-hover:text-primary" strokeWidth={1.5} />
            </div>
            <p className="mt-1 text-tiny text-foreground-muted">{post.score} 分 · {post.linked_comment_count} 条关联评论</p>
          </a>
        ))}
      </div>
    </SectionCard>
  );
}

function BoundaryCard({ report }: { report: RedditReport }) {
  const completeness = historicalCompletenessPresentation(report);
  return (
    <section className="card p-6" aria-labelledby="report-boundaries-title">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-status-successBg">
            <ShieldCheck className="h-[18px] w-[18px] text-status-success" strokeWidth={1.5} />
          </div>
          <div>
            <h2 id="report-boundaries-title" className="text-h3 text-foreground">当前数据边界</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">未支持能力统一收口，不用空图或 Mock 补齐</p>
          </div>
        </div>
        <span className="rounded-badge bg-status-successBg px-2.5 py-1 text-tiny font-medium text-status-success">仅展示已验证数据</span>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-card border border-border-divider p-4">
          <p className="text-body-sm font-medium text-foreground">当前支持</p>
          <p className="mt-2 text-caption leading-relaxed text-foreground-secondary">已观察数量、情感、社区、帖子主题、痛点、品牌样本提及、晋级标签与原始证据。</p>
        </div>
        <div className="rounded-card border border-border-divider p-4">
          <p className="text-body-sm font-medium text-foreground">条件支持</p>
          <p className="mt-2 text-caption leading-relaxed text-foreground-secondary">{completeness.label}：{completeness.detail}；画像需要独立 dim_persona_v1 与 persona_tags 管线。</p>
        </div>
        <div className="rounded-card border border-border-divider p-4">
          <p className="text-body-sm font-medium text-foreground">当前不展示</p>
          <p className="mt-2 text-caption leading-relaxed text-foreground-secondary">市场份额、ROI、NPS、响应时长、转化率、KPI 达成、预测及用户画像规模。</p>
        </div>
      </div>
      <p className="mt-4 rounded-card bg-surface-tertiary p-4 text-caption leading-relaxed text-foreground-secondary">
        评论按自身创建时间进入窗口，隔离评论不计入报告。
      </p>
    </section>
  );
}

function LegacyReportView({ report }: { report: RedditReport }) {
  const isGap = report.window.coverage_status === 'coverage_gap';
  const completeness = historicalCompletenessPresentation(report);
  const negativeEntities =
    report.headline.post_sentiment.counts.negative
    + report.headline.comment_sentiment.counts.negative;
  const gapNote = `${completeness.label}，不解释为零讨论`;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SnapshotMetricCard icon={FileText} value={isGap ? '—' : report.headline.posts} label="已观察帖子" note={isGap ? gapNote : '按唯一 Reddit 帖子编号统计；帖子按自身创建时间入窗'} />
        <SnapshotMetricCard icon={MessagesSquare} value={isGap ? '—' : report.headline.voc_comments} label="VOC 评论" note={isGap ? gapNote : '评论按自身创建时间入窗；排除机器人和删除内容'} tone="success" />
        <SnapshotMetricCard icon={MessageSquare} value={isGap ? '—' : negativeEntities} label="负面内容实体" note={isGap ? gapNote : '帖子与 VOC 评论负面实体之和，不是用户数'} tone="warning" />
        <SnapshotMetricCard icon={Target} value={isGap ? '—' : report.attention_items.length} label="关注项" note={isGap ? gapNote : '负面或高规则严重度的确定性筛选，不是危机 SLA'} tone="warning" />
      </div>

      {!isGap && (
        <>
          <ObservedVolumeChart report={report} />

          <div className="grid gap-6 xl:grid-cols-3">
            <SectionCard title="活跃社区" subtitle="帖子与窗口内评论的已观察实体量" tag="舆情" icon={<Users className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
              <RankedBarList items={report.communities.slice(0, 8).map((row) => ({ label: `r/${row.subreddit}`, value: row.observed_entities, detail: `· 帖子 ${row.posts}` }))} />
            </SectionCard>
            <SectionCard title="帖子主题" subtitle={`帖子分母 ${report.headline.posts.toLocaleString('zh-CN')}`} tag="品类" icon={<Hash className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
              <RankedBarList items={report.topics.slice(0, 8).map((row) => ({ label: formatTopic(row.topic), value: row.post_entities, detail: `· ${formatPercent(row.share.value)}` }))} colorClass="bg-chart-2" />
            </SectionCard>
            <SectionCard title="痛点集中" subtitle="帖子与评论的匹配实体数，可一条命中多个痛点" tag="品类" icon={<Activity className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
              <RankedBarList items={report.pain_points.slice(0, 8).map((row) => ({ label: formatPainPoint(row.pain_point), value: row.total_entities, detail: `· 帖 ${row.post_entities}/评 ${row.comment_entities}` }))} colorClass="bg-status-warning" />
            </SectionCard>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard title="品牌样本提及" subtitle="窗口内明确提及该品牌的唯一帖子数；多品牌可重复计数，不是市场份额" tag="品牌" icon={<Tag className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
              <RankedBarList items={report.brand_mentions.slice(0, 10).map((row) => ({ label: row.brand, value: row.sample_mention_posts, detail: `· 样本 ${formatPercent(row.sample_mention_share.value)}` }))} />
            </SectionCard>
            <SignalCards report={report} />
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <AttentionList report={report} />
            <EvidenceList report={report} />
          </div>
        </>
      )}

      <BoundaryCard report={report} />
    </div>
  );
}

function metricValue(metric: RiskObservedCount | RiskShareMetric): string {
  if (metric.value === null) return '—';
  return 'denominator' in metric ? `${(metric.value * 100).toFixed(1)}%` : metric.value.toLocaleString('zh-CN');
}

function deltaValue(comparison: RiskComparison): string {
  if (comparison.absolute_delta === null) return '—';
  return comparison.metric_name === 'negative_evidence_share'
    ? `${(comparison.absolute_delta * 100).toFixed(1)}pp`
    : comparison.absolute_delta.toLocaleString('zh-CN');
}

const comparisonReasonLabels: Record<string, string> = {
  baseline_observation_absent_under_incomplete_coverage: '覆盖不完整，基期没有可用观察值',
  comment_coverage_not_thread_complete: '评论线程覆盖不完整',
  current_observation_absent_under_incomplete_coverage: '覆盖不完整，当前期没有可用观察值',
  event_time_coverage_partial: '事件时间覆盖不完整',
  observation_absent_under_incomplete_coverage: '覆盖不完整，缺少可用观察值',
  search_has_next_truncates_window: '搜索仍有下一页，窗口尚未完全穷尽',
};

function comparisonReasons(reasonCodes: string[]): string {
  return reasonCodes
    .map((reasonCode) => comparisonReasonLabels[reasonCode] ?? `未识别覆盖原因：${reasonCode}`)
    .join(' · ');
}

function comparisonPresentation(comparison: RiskComparison): { status: string; detail: string; className: string } {
  if (comparison.comparison_status === 'unavailable') {
    return {
      status: '不可比较',
      detail: comparisonReasons(comparison.reason_codes) || '基期或覆盖证据缺失',
      className: 'text-foreground-muted',
    };
  }
  if (comparison.comparison_status === 'provisional_observed_sample') {
    return {
      status: '已观察样本',
      detail: `样本差值 ${deltaValue(comparison)} · ${comparisonReasons(comparison.reason_codes)}`,
      className: 'text-primary',
    };
  }
  if (!comparison.direction_claim_supported || comparison.absolute_delta === null) {
    return { status: '可比较', detail: '差值可用，方向条件未满足', className: 'text-primary' };
  }
  const direction = comparison.absolute_delta > 0 ? '上升' : comparison.absolute_delta < 0 ? '下降' : '持平';
  return {
    status: `${direction} ${Math.abs(comparison.metric_name === 'negative_evidence_share' ? comparison.absolute_delta * 100 : comparison.absolute_delta).toLocaleString('zh-CN')}${comparison.metric_name === 'negative_evidence_share' ? 'pp' : ''}`,
    detail: `当前 ${metricValue(comparison.current)} · 基期 ${comparison.baseline ? metricValue(comparison.baseline) : '—'}`,
    className: comparison.absolute_delta > 0 ? 'text-status-error' : 'text-status-success',
  };
}

function metricCardComparison(label: '环比' | '同比', comparison: RiskComparison): MetricComparisonValue {
  const reasonCodes = comparison.reason_codes.map(
    (reasonCode) => comparisonReasonLabels[reasonCode] ?? reasonCode,
  );
  if (
    comparison.comparison_status !== 'comparable'
    || !comparison.direction_claim_supported
    || comparison.absolute_delta === null
  ) {
    return { label, display: '—', direction: 'unavailable', reasonCodes };
  }

  const delta = comparison.metric_name === 'negative_evidence_share'
    ? comparison.absolute_delta * 100
    : comparison.relative_delta === null ? null : comparison.relative_delta * 100;
  if (delta === null) {
    return {
      label,
      display: '—',
      direction: 'unavailable',
      reasonCodes: [...reasonCodes, '基期为 0，无法计算相对变化'],
    };
  }
  const direction = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
  const unit = comparison.metric_name === 'negative_evidence_share' ? 'pp' : '%';
  return {
    label,
    display: `${delta > 0 ? '+' : ''}${delta.toFixed(1)}${unit}`,
    direction,
    reasonCodes,
  };
}

function PeriodComparisonPanel({ report }: { report: RiskRedditReport }) {
  const cards = (['post', 'comment'] as const).flatMap((entityType) => {
    const entityLabel = entityType === 'post' ? '帖子' : '评论';
    const count = report.momcozy_metrics.observed_count[entityType];
    const negative = report.momcozy_metrics.negative_evidence_share[entityType];
    const countSeries = report.trend.points.map((point) => ({
      label: formatReportTrendLabel(point.window.start_local, report.identity.period),
      value: point.observed_count[entityType].value,
    }));
    const negativeSeries = report.trend.points.map((point) => ({
      label: formatReportTrendLabel(point.window.start_local, report.identity.period),
      value: point.negative_evidence_share[entityType].value === null
        ? null
        : point.negative_evidence_share[entityType].value * 100,
    }));
    return [
      {
        key: `${entityType}-count`,
        title: `${entityLabel}观察量`,
        value: count.value,
        displayValue: count.value?.toLocaleString('zh-CN'),
        unit: '条',
        explanation: `${entityLabel}口径内 Momcozy 品牌绑定的观察实体数；计数不是独立用户人数。`,
        help: {
          definition: `${entityLabel}口径内，经治理品牌事实关联 Momcozy 的去重内容实体数。`,
          formula: `${entityLabel}观察量 = count(distinct ${entityType}_entity_id where promoted brand_id = "momcozy" and entity_event_date in period)`,
          notes: ['内容实体数不是独立用户人数。'],
        },
        comparisons: [
          metricCardComparison('环比', report.observed_count_comparisons.previous_period[entityType]),
          metricCardComparison('同比', report.observed_count_comparisons.year_over_year[entityType]),
        ],
        series: countSeries,
      },
      {
        key: `${entityType}-negative`,
        title: `${entityLabel}负面证据占比`,
        value: negative.value,
        displayValue: negative.value === null ? undefined : `${(negative.value * 100).toFixed(1)}%`,
        unit: undefined,
        explanation: `${entityLabel}中负面 Momcozy 观察实体数 ÷ 已完成情感分类的 Momcozy 观察实体数。`,
        help: {
          definition: `${entityLabel}口径内，负向 Momcozy 内容实体占已完成情感分类实体的比例。`,
          formula: '负面证据占比 = negative_entities / classified_entities × 100%',
          notes: ['未分类实体不进入分母。'],
        },
        comparisons: [
          metricCardComparison('环比', report.period_comparisons.previous_period[entityType]),
          metricCardComparison('同比', report.period_comparisons.year_over_year[entityType]),
        ],
        series: negativeSeries,
      },
    ];
  });
  return (
    <section className="card p-5 sm:p-6" aria-labelledby="period-comparison-title">
      <div className="mb-5 flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light">
          <TrendingUp className="h-[18px] w-[18px] text-primary" strokeWidth={1.5} />
        </div>
        <div>
          <h2 id="period-comparison-title" className="text-h3 text-foreground">环比与同比诊断</h2>
          <p className="mt-0.5 text-caption text-foreground-muted">Momcozy 已观察量与负面证据占比；帖子、评论分别呈现</p>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {cards.map(({ key, ...card }) => <MetricComparisonCard key={key} {...card} />)}
      </div>
    </section>
  );
}

function TrendChart({ report, entityType }: { report: RiskRedditReport; entityType: RiskEntityType }) {
  const rows = report.trend.points.map((point) => ({
    label: formatReportTrendLabel(point.window.start_local, report.identity.period),
    观察量: point.observed_count[entityType].value,
    负面占比: point.negative_evidence_share[entityType].value === null
      ? null
      : Number((point.negative_evidence_share[entityType].value * 100).toFixed(1)),
  }));
  const displayRows = rows.filter(row => row.观察量 !== null || row.负面占比 !== null);
  const direction = report.trend.direction_claim_supported_by_metric;
  return (
    <SectionCard
      title={`${entityType === 'post' ? '帖子' : '评论'}趋势`}
      subtitle={direction.observed_count && direction.negative_evidence_share ? '相邻闭合期覆盖门禁均通过，可解释方向' : '趋势点仅为观察值；方向门禁未完整通过'}
      tag="舆情"
      icon={<TrendingUp className="h-5 w-5 text-primary" strokeWidth={1.5} />}
    >
      <div className="mb-3 flex flex-wrap items-center gap-4 text-tiny text-foreground-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-primary" />观察量</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-status-warning" />负面占比</span>
      </div>
      <div className="h-[270px]" aria-label={`${entityType === 'post' ? '帖子' : '评论'}观察量与负面占比趋势图`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={displayRows} margin={{ top: 8, right: 8, left: -10, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={{ stroke: '#E5E7EB' }} tickLine={false} minTickGap={18} />
            <YAxis yAxisId="count" tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={false} tickLine={false} allowDecimals={false} />
            <YAxis yAxisId="share" orientation="right" domain={[0, 100]} tickFormatter={(value) => `${value}%`} tick={{ fontSize: 11, fill: '#6B7280' }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #EDEDED', borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.06)', fontSize: '12px' }} />
            <Bar yAxisId="count" dataKey="观察量" fill="#E85D75" radius={[3, 3, 0, 0]} isAnimationActive={false} minPointSize={0} />
            <Line yAxisId="share" type="monotone" dataKey="负面占比" stroke="#D68A17" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </SectionCard>
  );
}

function ProductPeriodPanel({ report }: { report: RiskRedditReport }) {
  const levels = [
    ['品类', report.product_period_analysis.category],
    ['产品族', report.product_period_analysis.product_family],
    ['SPU', report.product_period_analysis.spu_exact],
  ] as const;
  return (
    <section className="card p-5 sm:p-6" aria-labelledby="product-period-title">
      <div className="mb-5 flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light">
          <Tag className="h-[18px] w-[18px] text-primary" strokeWidth={1.5} />
        </div>
        <div>
          <h2 id="product-period-title" className="text-h3 text-foreground">Momcozy 产品周期诊断</h2>
          <p className="mt-0.5 text-caption text-foreground-muted">三层范围均包含当前量、负面占比、环比、同比与趋势门禁</p>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        {levels.map(([label, rows]) => (
          <section key={label} className="rounded-card border border-border-divider p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-body-sm font-semibold text-foreground">{label}</h3>
              <span className="text-tiny text-foreground-muted">{rows.length} 项</span>
            </div>
            {rows.length ? (
              <div className="space-y-3">
                {rows.slice(0, 6).map((row) => (
                  <article key={row.scope_id} className="rounded-icon bg-surface-tertiary p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-caption font-medium text-foreground">{row.scope_name_cn || row.scope_name_en}</p>
                        <p className="mt-0.5 truncate font-mono text-tiny text-foreground-muted">{row.scope_id}</p>
                      </div>
                      <span className={`rounded-badge px-2 py-0.5 text-tiny ${row.trend.direction_claim_supported ? 'bg-status-successBg text-status-success' : 'bg-white text-foreground-muted'}`}>
                        {row.trend.direction_claim_supported ? '趋势可解释' : '仅观察'}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-tiny">
                      {(['post', 'comment'] as const).map((entityType) => {
                        const current = row.current[entityType];
                        const pop = comparisonPresentation(row.period_comparisons.previous_period[entityType].negative_evidence_share);
                        const yoy = comparisonPresentation(row.period_comparisons.year_over_year[entityType].negative_evidence_share);
                        return (
                          <div key={entityType} className="rounded-icon bg-white p-2.5">
                            <p className="font-medium text-foreground">{entityType === 'post' ? '帖子' : '评论'}</p>
                            <p className="mt-1 text-foreground-secondary">量 {metricValue(current.observed_count)}</p>
                            <p className="text-foreground-secondary">负面 {metricValue(current.negative_evidence_share)}</p>
                            <p className="mt-1 truncate text-foreground-muted" title={pop.detail}>环比 {pop.status}</p>
                            <p className="truncate text-foreground-muted" title={yoy.detail}>同比 {yoy.status}</p>
                          </div>
                        );
                      })}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <p className="rounded-icon bg-surface-tertiary p-3 text-caption text-foreground-muted">当前周期没有该层级受控绑定。</p>
            )}
          </section>
        ))}
      </div>
    </section>
  );
}

function CompetitorReportPanel({ report }: { report: RiskRedditReport }) {
  const visibleCompetitors = report.competitor_context.slice(0, 6);
  return (
    <SectionCard title="竞品同样本对照" subtitle="不是市场份额、SOV、渗透率或销量；只描述受控绑定的观察样本" tag="品牌" icon={<Users className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
      {report.competitor_context.length ? (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <span className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-tiny text-foreground-secondary">
              展示 {visibleCompetitors.length}/{report.competitor_context.length}
            </span>
            {report.competitor_context.length > visibleCompetitors.length && (
              <span className="text-tiny text-foreground-muted">其余条目保留在版本化报告附录中</span>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {visibleCompetitors.map((competitor) => (
              <article key={competitor.brand_id} className="rounded-card border border-border-divider p-4">
                <h3 className="text-body-sm font-semibold text-foreground">{competitor.brand_name}</h3>
                <p className="mt-0.5 font-mono text-tiny text-foreground-muted">{competitor.brand_id}</p>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-caption">
                  <div className="rounded-icon bg-surface-tertiary p-3"><dt className="text-tiny text-foreground-muted">帖子负面</dt><dd className="mt-1 font-semibold text-foreground">{metricValue(competitor.negative_evidence_share.post)}</dd></div>
                  <div className="rounded-icon bg-surface-tertiary p-3"><dt className="text-tiny text-foreground-muted">评论负面</dt><dd className="mt-1 font-semibold text-foreground">{metricValue(competitor.negative_evidence_share.comment)}</dd></div>
                </dl>
              </article>
            ))}
          </div>
        </>
      ) : <p className="text-caption text-foreground-muted">当前周期没有满足受控绑定的竞品对照记录。</p>}
    </SectionCard>
  );
}

function RiskBoundaryCard({ report }: { report: RiskRedditReport }) {
  const completeness = historicalCompletenessPresentation(report);
  return (
    <section className="card p-6" aria-labelledby="risk-report-boundaries-title">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-status-successBg">
          <ShieldCheck className="h-[18px] w-[18px] text-status-success" strokeWidth={1.5} />
        </div>
        <div>
          <h2 id="risk-report-boundaries-title" className="text-h3 text-foreground">指标与运行边界</h2>
          <p className="mt-0.5 text-caption text-foreground-muted">空值与原因保留，不用零值或 Mock 补齐</p>
        </div>
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <div className="rounded-card border border-border-divider p-4"><p className="text-body-sm font-medium text-foreground">支持</p><p className="mt-2 text-caption leading-relaxed text-foreground-secondary">闭合期观察量、负面证据占比、受控风险优先级、产品三层范围、覆盖门禁下的环比/同比/趋势。</p></div>
        <div className="rounded-card border border-border-divider p-4"><p className="text-body-sm font-medium text-foreground">条件支持</p><p className="mt-2 text-caption leading-relaxed text-foreground-secondary">{completeness.label}：{completeness.detail}。旧版数据在证据不足时不表达变化方向。</p></div>
        <div className="rounded-card border border-border-divider p-4"><p className="text-body-sm font-medium text-foreground">不支持</p><p className="mt-2 text-caption leading-relaxed text-foreground-secondary">市场份额、SOV、销量、ROI、NPS、响应时长、行动完成率；帖子与评论不合并。</p></div>
      </div>
    </section>
  );
}

function RiskReportView({ report, snapshot }: { report: RiskRedditReport; snapshot?: RedditSnapshotCore }) {
  const observedPosts = report.momcozy_metrics.observed_count.post;
  const observedComments = report.momcozy_metrics.observed_count.comment;
  const negativePosts = report.momcozy_metrics.negative_evidence_share.post;
  const negativeComments = report.momcozy_metrics.negative_evidence_share.comment;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SnapshotMetricCard icon={FileText} value={metricValue(observedPosts)} label="Momcozy 已观察帖子" note={observedPosts.observation_status === 'provisional_observed_sample' ? '已观察样本；覆盖不支持方向结论' : '品牌受控绑定帖子'} />
        <SnapshotMetricCard icon={MessagesSquare} value={metricValue(observedComments)} label="Momcozy 已观察评论" note={observedComments.observation_status === 'provisional_observed_sample' ? '已观察样本；评论覆盖不完整' : '品牌受控绑定 VOC 评论'} tone="success" />
        <SnapshotMetricCard icon={Activity} value={metricValue(negativePosts)} label="帖子负面证据占比" note={`${negativePosts.numerator ?? '—'}/${negativePosts.denominator ?? '—'} · 与评论分开`} tone="warning" />
        <SnapshotMetricCard icon={MessageSquare} value={metricValue(negativeComments)} label="评论负面证据占比" note={`${negativeComments.numerator ?? '—'}/${negativeComments.denominator ?? '—'} · 与帖子分开`} tone="warning" />
      </div>

      <PeriodComparisonPanel report={report} />
      <div className="grid gap-6 xl:grid-cols-2">
        <TrendChart report={report} entityType="post" />
        <TrendChart report={report} entityType="comment" />
      </div>
      <RiskThemePanel
        themes={report.risk_themes}
        title="本期 Momcozy 风险主题"
        subtitle="按影响程度、产品范围和真实证据组织，点击可回到原帖核查"
        evidenceContext={snapshot ? {
          releaseId: snapshot.release.release_id,
          snapshotId: snapshot.manifest.dataset_version,
          source: 'reports',
        } : undefined}
      />
      <ProductAnalysisPanel analysis={report.product_analysis} />
      <ProductPeriodPanel report={report} />
      <CompetitorReportPanel report={report} />

      <ObservedVolumeChart report={report} />
      <div className="grid gap-6 xl:grid-cols-3">
        <SectionCard title="活跃社区" subtitle="全观察样本的帖子与评论记录量" tag="舆情" icon={<Users className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
          <RankedBarList items={report.communities.slice(0, 8).map((row) => ({ label: `r/${row.subreddit}`, value: row.observed_entities, detail: `· 帖子 ${row.posts}` }))} />
        </SectionCard>
        <SectionCard title="帖子主题" subtitle={`全样本帖子分母 ${report.headline.posts.toLocaleString('zh-CN')}`} tag="品类" icon={<Hash className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
          <RankedBarList items={report.topics.slice(0, 8).map((row) => ({ label: formatTopic(row.topic), value: row.post_entities, detail: `· ${formatPercent(row.share.value)}` }))} colorClass="bg-chart-2" />
        </SectionCard>
        <SectionCard title="痛点集中" subtitle="全观察样本；一条内容可命中多个痛点" tag="品类" icon={<Activity className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
          <RankedBarList items={report.pain_points.slice(0, 8).map((row) => ({ label: formatPainPoint(row.pain_point), value: row.total_entities, detail: `· 帖 ${row.post_entities}/评 ${row.comment_entities}` }))} colorClass="bg-status-warning" />
        </SectionCard>
      </div>
      <RiskBoundaryCard report={report} />
    </div>
  );
}

function V3ReportView({
  report,
  snapshot,
  posterMode = false,
}: {
  report: V3CurrentReport;
  snapshot?: RedditSnapshotCore;
  posterMode?: boolean;
}) {
  const completeness = historicalCompletenessPresentation(report);
  return (
    <div className="space-y-6">
      <section
        className={`card border p-5 sm:p-6 ${completeness.supported ? 'border-status-success/30 bg-status-successBg/40' : 'border-border-divider'}`}
        aria-labelledby="v3-report-completeness-title"
      >
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-white">
            <ShieldCheck className={`h-[18px] w-[18px] ${completeness.supported ? 'text-status-success' : 'text-foreground-muted'}`} strokeWidth={1.5} />
          </div>
          <div className="min-w-0">
            <h2 id="v3-report-completeness-title" className="text-h3 text-foreground">{completeness.label}</h2>
            <p className="mt-1 break-words text-caption leading-relaxed text-foreground-secondary">{completeness.detail}</p>
          </div>
        </div>
      </section>

      {snapshot && <OperationalReportSupplement report={report} snapshot={snapshot} posterMode={posterMode} />}
      {!snapshot && <ReportIndicatorMonitor indicators={report.indicators} />}
    </div>
  );
}

export default function RealReportView({
  report,
  snapshot,
  posterMode = false,
}: {
  report: DisplayableRedditReport;
  snapshot?: RedditSnapshotCore;
  posterMode?: boolean;
}) {
  if (isV3Report(report)) return <V3ReportView report={report} snapshot={snapshot} posterMode={posterMode} />;
  return isRiskReport(report) ? <RiskReportView report={report} snapshot={snapshot} /> : <LegacyReportView report={report} />;
}
