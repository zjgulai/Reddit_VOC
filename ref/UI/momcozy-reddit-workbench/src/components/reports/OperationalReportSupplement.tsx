import {
  Activity,
  FileText,
  GitBranch,
  Hash,
  HelpCircle,
  Lightbulb,
  PackageSearch,
  Target,
  TrendingUp,
  Users,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { LineChart, PieChart } from '../charts';
import SectionCard from '../SectionCard';
import { RankedBarList } from '../../features/redditSnapshot/RankedBarList';
import { buildSnapshotEvidenceHref } from '../../features/redditSnapshot/evidenceLinks';
import { formatDateTime, formatTopic, SENTIMENT_LABELS } from '../../features/redditSnapshot/format';
import { derivePeriodMetrics } from '../../features/redditSnapshot/operational';
import type {
  ReportPeriod,
  V3CurrentReport,
  V3BrandHealthDimensionRow,
  V3ReportComparison,
  V3ReportIndicator,
} from '../../features/redditSnapshot/reports';
import type { RedditSnapshotCore } from '../../features/redditSnapshot/types';
import ReportIndicatorMonitor from './ReportIndicatorMonitor';
import {
  formatReportIndicatorValue,
  isDisplayableReportIndicator,
} from './reportIndicatorPresentation';

interface ReportStoryConfig {
  eyebrow: string;
  title: string;
  question: string;
  signalTitle: string;
  actionLabel: string;
  actionHorizon: string;
  path: string[];
}

const STORY_CONFIG: Record<ReportPeriod, ReportStoryConfig> = {
  daily: {
    eyebrow: '日报 · 作战指挥室',
    title: '本期发生了什么，下一步先处理什么',
    question: '用完整自然日识别即时声量、负向证据和高互动内容。',
    signalTitle: '当日信号',
    actionLabel: '下一步行动',
    actionHorizon: '下一步',
    path: ['完整自然日信号', '异常与风险', '帖子证据', '下一步行动'],
  },
  weekly: {
    eyebrow: '周报 · 策略雷达',
    title: '本周结构如何变化，下周资源放在哪里',
    question: '用完整自然周识别趋势、品类机会、社区风险与竞品差异。',
    signalTitle: '周度变化',
    actionLabel: '下周计划',
    actionHorizon: '下周',
    path: ['环比与同比', '主题 / 品类驱动', '竞品差异', '下周资源'],
  },
  monthly: {
    eyebrow: '月报 · 战略复盘',
    title: '本月品牌发生了什么，下一阶段如何取舍',
    question: '用完整自然月复盘品牌声量、口碑、产品范围与竞争语境。',
    signalTitle: '月度大盘',
    actionLabel: '战略建议',
    actionHorizon: '下月',
    path: ['品牌健康', '月环比 / 同比', '品类与 SPU', '风险与机会', '下月指标'],
  },
};

function daysBefore(value: string, days: number): string {
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return new Date(timestamp - days * 86_400_000).toISOString().slice(0, 10);
}

function numeric(value: unknown): number | null {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (String(value).trim() === '') return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function contextDays(report: V3CurrentReport): number {
  if (report.grain === 'daily') return 30;
  if (report.grain === 'weekly') return 42;
  return 92;
}

function indicatorById(report: V3CurrentReport, metricId: string): V3ReportIndicator | null {
  const indicator = report.indicators.find((item) => item.metric_id === metricId);
  return indicator && isDisplayableReportIndicator(indicator) ? indicator : null;
}

function periodBrandHealth(report: V3CurrentReport) {
  const rows = report.brand_health.rows;
  const qualified = rows.find((row) => row.comparison_side === 'qualified_organic');
  return qualified && qualified.status !== 'unavailable' && numeric(qualified.value) !== null
    ? qualified
    : null;
}

const HEALTH_DIMENSION_LABELS: Record<V3BrandHealthDimensionRow['dimension_id'], string> = {
  reputation: '品牌声誉',
  product_experience: '产品体验',
  recommendation_trust: '推荐信任',
  risk_resilience: '风险韧性',
};

function qualifiedHealthDimensions(report: V3CurrentReport): V3BrandHealthDimensionRow[] {
  return report.brand_health.dimension_rows.filter((row) => (
    row.comparison_side === 'qualified_organic'
      && row.status !== 'unavailable'
      && numeric(row.dimension_value) !== null
      && numeric(row.contribution_points) !== null
  ));
}

function displayableComparison(comparison: V3ReportComparison): boolean {
  return comparison.status !== 'unavailable'
    && comparison.value !== null
    && comparison.display !== '—';
}

function comparisonLabel(comparison: V3ReportComparison, fallback: string): string {
  return comparison.display_label?.trim() || fallback;
}

function comparisonPhrase(indicator: V3ReportIndicator, includeYearOverYear = false): string {
  const fragments: string[] = [];
  if (displayableComparison(indicator.comparisons.period_over_period)) {
    const comparison = indicator.comparisons.period_over_period;
    fragments.push(`${comparisonLabel(comparison, '环比')} ${comparison.display}`);
  }
  if (includeYearOverYear && displayableComparison(indicator.comparisons.year_over_year)) {
    const comparison = indicator.comparisons.year_over_year;
    fragments.push(`${comparisonLabel(comparison, '同比')} ${comparison.display}`);
  }
  return fragments.length > 0 ? `（${fragments.join('，')}）` : '';
}

function indicatorFact(indicator: V3ReportIndicator | null, includeYearOverYear = false): string | null {
  if (!indicator) return null;
  const status = indicator.current.status === 'provisional' ? '观察值' : '';
  return `${indicator.name_cn} ${formatReportIndicatorValue(indicator)}${status ? `（${status}）` : ''}${comparisonPhrase(indicator, includeYearOverYear)}`;
}

function directionImpact(
  indicator: V3ReportIndicator | null,
  labels: { up: string; down: string; flat: string },
): string | null {
  const direction = indicator?.comparisons.period_over_period.direction ?? indicator?.sparkline.direction;
  if (!indicator || !direction) return null;
  return labels[direction];
}

function uniqueStrings(values: Array<string | null>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}

export default function OperationalReportSupplement({
  report,
  snapshot,
  posterMode = false,
}: {
  report: V3CurrentReport;
  snapshot: RedditSnapshotCore;
  posterMode?: boolean;
}) {
  const story = STORY_CONFIG[report.grain];
  const brandHealth = periodBrandHealth(report);
  const healthDimensions = qualifiedHealthDimensions(report);
  const activity = report.period_activity;
  const current = derivePeriodMetrics(snapshot, report.period);
  const lookbackDays = contextDays(report);
  const isHistorical = report.artifact_role === 'historical_complete_calendar_period'
    || report.artifact_role === 'historical_observed_calendar_period_unattested';
  const useContext = current.momcozyPostCount === 0
    && !isHistorical;
  const context = useContext
    ? derivePeriodMetrics(snapshot, {
        start: daysBefore(report.period.end, lookbackDays),
        end: report.period.end,
      })
    : current;
  const contextLabel = useContext ? `截至周期末的近 ${lookbackDays} 日背景` : '本期 Momcozy 帖子';

  const observation = indicatorById(report, 'RV-BR-01');
  const negativeRate = indicatorById(report, 'RV-BR-02');
  const netSentiment = indicatorById(report, 'RV-BR-03');
  const recommendationRate = indicatorById(report, 'RV-BR-04');
  const competitorGap = indicatorById(report, 'RV-BR-05');
  const urgency = indicatorById(report, 'RV-IN-01');
  const acceleration = indicatorById(report, 'RV-IN-05');
  const productIssueRate = indicatorById(report, 'RV-PS-02');
  const evidenceCompleteness = indicatorById(report, 'RV-DH-05');
  const displayableIndicators = report.indicators.filter(isDisplayableReportIndicator);

  const observationTrend = observation?.sparkline.points.flatMap((point) => {
    const value = numeric(point.value);
    return value === null ? [] : [{ label: point.label, value }];
  }) ?? [];
  const evidenceLimit = report.grain === 'daily' ? 5 : report.grain === 'weekly' ? 8 : 10;
  const evidencePosts = [...context.momcozyPosts]
    .sort((left, right) => (
      Number(right.analysis.sentiment_label === 'negative') - Number(left.analysis.sentiment_label === 'negative')
      || right.linked_comment_count - left.linked_comment_count
      || right.score - left.score
    ))
    .slice(0, evidenceLimit);

  const topTopic = context.topics[0];
  const topProduct = context.products[0];
  const topCommunity = context.subreddits[0];
  const topEvidence = evidencePosts[0];
  const signalFacts = uniqueStrings([
    brandHealth ? `品牌健康度指数 ${brandHealth.display}${brandHealth.status === 'provisional' ? '（观察值）' : ''}` : null,
    report.grain === 'daily' && activity
      ? `当日治理口径 Momcozy 新帖 ${activity.momcozy.new_post_count} 条、新增评论 ${activity.momcozy.new_comment_count} 条`
      : report.grain === 'daily' && current.momcozyPostCount > 0
      ? `当日新发 Momcozy 相关帖子 ${current.momcozyPostCount} 条`
      : null,
    indicatorFact(observation, true),
    indicatorFact(negativeRate, true),
    indicatorFact(netSentiment, true),
    indicatorFact(competitorGap),
    indicatorFact(acceleration, true),
  ]).slice(0, 5);
  const driverFacts = uniqueStrings([
    topTopic ? `${contextLabel}最高频主题：${formatTopic(topTopic.id)}（${topTopic.value} 条）` : null,
    topProduct ? `${contextLabel}最高频产品范围：${topProduct.label}（${topProduct.value} 条）` : null,
    topCommunity ? `${contextLabel}最活跃社区：${topCommunity.label}（${topCommunity.value} 条）` : null,
    topEvidence ? `最高优先证据：${topEvidence.title}` : null,
  ]).slice(0, 4);
  const impactFacts = uniqueStrings([
    directionImpact(observation, {
      up: '声量较基期抬升，需要增加高互动内容抽检与响应容量。',
      down: '声量较基期回落，不能把低讨论量直接解释为口碑改善。',
      flat: '声量与基期基本持平，维持既有监测节奏。',
    }),
    directionImpact(negativeRate, {
      up: '负向证据占比较基期上升，产品与客服复核优先级应前移。',
      down: '负向证据占比较基期回落，但仍需跟踪高互动负面线程。',
      flat: '负向证据占比基本稳定，重点看结构而不是总量。',
    }),
    competitorGap && numeric(competitorGap.current.value) !== null
      ? numeric(competitorGap.current.value)! >= 0
        ? `Momcozy 净情感较同样本竞品高 ${Math.abs(numeric(competitorGap.current.value)!).toFixed(2)}pp；这是 Reddit 样本差，不是市场份额。`
        : `Momcozy 净情感较同样本竞品低 ${Math.abs(numeric(competitorGap.current.value)!).toFixed(2)}pp；需复核差距来自哪些主题。`
      : null,
    context.negativePosts > 0
      ? `${contextLabel}包含 ${context.negativePosts} 条负面帖子和 ${context.highSeverityPosts} 条高严重度帖子。`
      : `${contextLabel}未出现负面帖子；只陈述当前样本，不外推 Reddit 总体。`,
  ]).slice(0, 4);

  const commonEvidenceAction = topEvidence
    ? `复核高优先证据“${topEvidence.title}”，确认是否需要客服、产品或社区运营跟进。`
    : null;
  const actionFacts = report.grain === 'daily'
    ? uniqueStrings([
        context.negativePosts > 0
          ? `${story.actionHorizon}先复核 ${context.negativePosts} 条负面帖子，按互动量与严重度排序。`
          : `${story.actionHorizon}维持新帖与评论信号监测，不因零负面样本降低监测频率。`,
        topProduct ? `围绕 ${topProduct.label} 检查高频问题与可复用正向内容。` : null,
        commonEvidenceAction ?? '从当日高互动帖子中抽取五条证据，形成客服、产品与社区运营的共享清单。',
        '在下一个完整自然日复核声量与异常加速度，确认风险是延续、回落还是一次性波动。',
      ]).slice(0, 3)
    : report.grain === 'weekly'
      ? uniqueStrings([
          topCommunity ? `${story.actionHorizon}将社区抽检重点放在 ${topCommunity.label}，同步跟踪高互动线程。` : null,
          topProduct ? `围绕 ${topProduct.label} 汇总产品问题与推荐表达，形成产品/内容联合复盘。` : null,
          competitorGap ? '复核 Momcozy 与竞品净情感差的主题来源，避免把同样本差异误读为市场份额。' : null,
          commonEvidenceAction,
          '将本周证据与上周行动清单逐项对照；当前数据包未含行动回写，不自动生成完成率。',
        ]).slice(0, 4)
      : uniqueStrings([
          topProduct ? `${story.actionHorizon}把 ${topProduct.label} 作为产品体验与内容策略的优先复盘范围。` : null,
          competitorGap ? '把竞品净情感差纳入月度品牌复盘，并拆解到主题、品类与社区。' : null,
          topCommunity ? `资源规划优先覆盖 ${topCommunity.label}，但仅以真实讨论与证据质量为依据。` : null,
          commonEvidenceAction,
          '把品牌健康度、净情感、负向率与异常加速度列为下月固定复盘指标。',
        ]).slice(0, 4);

  const monitoringPreview = uniqueStrings([
    brandHealth ? `品牌健康度指数 ${brandHealth.display}` : null,
    ...displayableIndicators.slice(0, 4).map((indicator) => (
      `${indicator.name_cn} ${formatReportIndicatorValue(indicator)}`
    )),
  ]).slice(0, 4);

  return (
    <section
      className={posterMode ? 'space-y-4' : 'space-y-6'}
      aria-labelledby="report-operational-body-title"
      data-report-poster-body={posterMode ? report.grain : undefined}
    >
      <div>
        <p className="text-tiny font-semibold uppercase tracking-[0.18em] text-primary">{story.eyebrow}</p>
        <h2 id="report-operational-body-title" className="mt-1 text-h2 text-foreground">{story.title}</h2>
        <p className="mt-1 text-caption text-foreground-muted">{story.question} 页面只展示可计算项，所有数字来自已校验的当前数据与日周月报告。</p>
      </div>

      <ol
        className="grid overflow-hidden rounded-card border border-border-divider bg-white sm:grid-cols-2 lg:flex"
        aria-label={`${story.eyebrow.split(' · ')[0]}叙事路径`}
      >
        {story.path.map((step, index) => (
          <li key={step} className="flex min-w-0 flex-1 items-center gap-3 border-b border-border-divider px-4 py-3 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0 sm:[&:nth-child(odd)]:border-r lg:border-b-0 lg:border-r lg:last:border-r-0">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-light text-tiny font-semibold text-primary">{index + 1}</span>
            <span className="text-caption font-medium text-foreground-secondary">{step}</span>
          </li>
        ))}
      </ol>

      {report.grain === 'daily' && activity ? (
        <SectionCard
          title="本期活动拆分"
          subtitle="按评论自身发布时间归入完整自然日；历史活跃帖指父帖早于本期、但本期产生了新评论。Momcozy 采用治理后的品牌事实口径。"
          icon={<Activity className="h-5 w-5" strokeWidth={1.5} />}
        >
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="daily-period-activity">
            {[
              { label: 'Momcozy 新帖', value: activity.momcozy.new_post_count, note: `全池 ${activity.all_observed.new_post_count} 条` },
              { label: 'Momcozy 新增评论', value: activity.momcozy.new_comment_count, note: `全池 ${activity.all_observed.new_comment_count} 条` },
              { label: '历史帖新增评论', value: activity.momcozy.comments_on_historical_posts, note: `全池 ${activity.all_observed.comments_on_historical_posts} 条` },
              { label: '被重新激活的历史帖', value: activity.momcozy.active_historical_post_count, note: `全池 ${activity.all_observed.active_historical_post_count} 条` },
            ].map((item) => (
              <div key={item.label} className="rounded-card border border-border-divider bg-surface-subtle p-4">
                <p className="text-caption text-foreground-muted">{item.label}</p>
                <p className="mt-2 text-h2 font-semibold text-foreground">{item.value}<span className="ml-1 text-body-sm font-normal text-foreground-muted">条</span></p>
                <p className="mt-1 text-tiny text-foreground-muted">{item.note}</p>
              </div>
            ))}
          </div>
          {activity.momcozy.unresolved_parent_comment_count > 0 ? (
            <p className="mt-3 text-tiny text-status-warning">
              另有 {activity.momcozy.unresolved_parent_comment_count} 条 Momcozy 评论缺少可关联父帖，未归入新帖或历史帖评论。
            </p>
          ) : null}
        </SectionCard>
      ) : null}

      {report.grain === 'monthly' && healthDimensions.length > 0 ? (
        <SectionCard
          title="品牌健康四维构成"
          subtitle="治理后有机口径 · 四维各占 25%；贡献分用于解释本月指数构成，不等同于环比变化贡献"
          tag="品牌"
          icon={<Target className="h-5 w-5 text-primary" strokeWidth={1.5} />}
        >
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="monthly-brand-health-dimensions">
            {healthDimensions.map((row) => {
              const value = numeric(row.dimension_value)!;
              const contribution = numeric(row.contribution_points)!;
              return (
                <article key={row.dimension_id} className="rounded-card border border-border-divider bg-surface-subtle p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-caption font-medium text-foreground-secondary">{HEALTH_DIMENSION_LABELS[row.dimension_id]}</p>
                      <p className="mt-2 text-h2 font-semibold text-foreground">{value.toFixed(2)}</p>
                    </div>
                    <span
                      className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border-divider bg-white text-foreground-muted"
                      title="维度分：帖子维度分 × 50% + 评论维度分 × 50%；指数构成贡献：维度分 × 25%。四维贡献合计因展示精度可能与总指数有 0.01 分舍入差。"
                      aria-label={`${HEALTH_DIMENSION_LABELS[row.dimension_id]}计算公式`}
                    >
                      <HelpCircle className="h-3.5 w-3.5" strokeWidth={1.8} />
                    </span>
                  </div>
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-white" aria-hidden="true">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
                  </div>
                  <p className="mt-3 text-tiny text-foreground-muted">对总指数贡献 {contribution.toFixed(2)} 分</p>
                </article>
              );
            })}
          </div>
        </SectionCard>
      ) : null}

      {report.grain === 'weekly' && report.action_review && !posterMode ? (
        <SectionCard
          title="行动复盘"
          subtitle="建议行动与真实执行记录分开管理；当前未接入人工或业务系统回写账本"
          tag="运营"
          icon={<Lightbulb className="h-5 w-5 text-primary" strokeWidth={1.5} />}
        >
          <div className="rounded-card border border-dashed border-border-divider bg-surface-subtle p-5" data-testid="weekly-action-review-empty">
            <p className="text-body-sm font-semibold text-foreground">尚无执行回写</p>
            <p className="mt-2 text-caption leading-relaxed text-foreground-muted">
              本页继续提供下周建议，但不把建议推断为已执行事项，也不显示完成率数值。待行动负责人、状态、结果证据和复核信息进入账本后，才计算完成率与行动效果。
            </p>
          </div>
        </SectionCard>
      ) : null}

      <section
        className="card overflow-hidden p-5 sm:p-7"
        aria-labelledby="report-story-map-title"
        data-testid="report-insight-mind-map"
        data-period-id={report.period.period_id}
        data-brand-health={brandHealth?.value ?? undefined}
        data-evidence-count={evidencePosts.length}
      >
        <div className="mx-auto max-w-3xl rounded-card border-2 border-primary/30 bg-primary-light/55 p-5 text-center shadow-sm">
          <div className="flex items-center justify-center gap-2 text-primary">
            <GitBranch className="h-5 w-5" strokeWidth={1.5} />
            <p className="text-tiny font-semibold tracking-[0.12em]">管理摘要</p>
          </div>
          <h3 id="report-story-map-title" className="mt-2 text-h3 text-foreground">管理摘要</h3>
          <p className="mt-2 text-body-sm leading-relaxed text-foreground-secondary">
            {signalFacts.slice(0, 3).join('；')}。
          </p>
          {useContext ? (
            <p className="mt-2 text-tiny leading-relaxed text-foreground-muted">
              本期数据中无新增 Momcozy 帖子；主题、产品、社区与帖子证据明确采用{contextLabel}，不计入本期指标。
            </p>
          ) : null}
        </div>

        <div className="mx-auto h-7 w-px bg-primary/30" aria-hidden="true" />
        <div className="relative grid gap-4 lg:grid-cols-3">
          <div className="absolute left-[16.66%] right-[16.66%] top-0 hidden h-px bg-primary/30 lg:block" aria-hidden="true" />
          {[
            { title: '核心信号', eyebrow: story.signalTitle, items: signalFacts, tone: 'border-primary/20 bg-primary-light/25' },
            { title: '驱动诊断', eyebrow: '主题 · 品类 · 社区 · 证据', items: driverFacts, tone: 'border-chart-2/20 bg-chart-2/5' },
            { title: '业务影响', eyebrow: '影响判断', items: impactFacts, tone: 'border-status-warning/20 bg-status-warningBg/35' },
          ].map((node) => (
            <article key={node.title} className={`relative rounded-card border p-5 ${node.tone}`}>
              <span className="absolute left-1/2 top-[-1rem] hidden h-4 w-px bg-primary/30 lg:block" aria-hidden="true" />
              <p className="text-tiny font-semibold text-foreground-muted">{node.eyebrow}</p>
              <h3 className="mt-1 text-body font-semibold text-foreground">{node.title}</h3>
              <ul className="mt-3 space-y-2 text-caption leading-relaxed text-foreground-secondary">
                {node.items.map((item) => (
                  <li key={item} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />{item}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>

        <div className="mx-auto h-7 w-px bg-primary/30" aria-hidden="true" />
        <div className="grid gap-4 lg:grid-cols-2">
          <article className="rounded-card border border-status-success/20 bg-status-successBg/30 p-5">
            <p className="text-tiny font-semibold text-status-success">{story.actionLabel}</p>
            <h3 className="mt-1 text-body font-semibold text-foreground">建议行动</h3>
            <ol className="mt-3 space-y-2 text-caption leading-relaxed text-foreground-secondary">
              {actionFacts.map((item, index) => (
                <li key={item} className="flex gap-2"><span className="font-semibold text-status-success">{index + 1}.</span>{item}</li>
              ))}
            </ol>
          </article>
          <article className="rounded-card border border-border-divider bg-surface-secondary p-5">
            <p className="text-tiny font-semibold text-foreground-muted">指标追踪</p>
            <h3 className="mt-1 text-body font-semibold text-foreground">持续监测</h3>
            <ul className="mt-3 grid gap-2 text-caption text-foreground-secondary sm:grid-cols-2">
              {monitoringPreview.map((item) => (
                <li key={item} className="rounded-icon bg-white px-3 py-2">{item}</li>
              ))}
            </ul>
          </article>
        </div>
      </section>

      {posterMode ? (
        <section className="rounded-card border border-border-divider bg-white p-5" aria-label="海报关键指标">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-tiny font-semibold uppercase tracking-[0.12em] text-primary">关键指标</p>
              <h3 className="mt-1 text-h3 text-foreground">本期经营监测</h3>
            </div>
            <p className="text-tiny text-foreground-muted">只展示当前值可计算的指标</p>
          </div>
          <div className="mt-4 grid grid-cols-4 gap-3">
            {displayableIndicators.slice(0, 4).map((indicator) => (
              <article key={indicator.metric_id} className="rounded-card bg-surface-subtle p-4" data-report-poster-indicator={indicator.metric_id}>
                <p className="truncate text-caption text-foreground-muted">{indicator.name_cn}</p>
                <p className="mt-2 text-h2 font-semibold text-foreground">{formatReportIndicatorValue(indicator)}</p>
                <p className="mt-1 truncate text-tiny text-foreground-muted">
                  {comparisonPhrase(indicator, true) || '本期真实观察值'}
                </p>
              </article>
            ))}
          </div>
          {report.grain !== 'daily' && observationTrend.length > 1 ? (
            <div className="mt-3 border-t border-border-divider pt-3">
              <div className="mb-2 flex items-center justify-between gap-4">
                <p className="text-caption font-medium text-foreground-secondary">同粒度完整周期声量趋势</p>
                <p className="text-tiny text-foreground-muted">{comparisonPhrase(observation!, true).replace(/[（）]/g, '') || '趋势序列'}</p>
              </div>
              <LineChart
                data={observationTrend}
                color={observation?.sparkline.direction === 'down' ? '#18A874' : observation?.sparkline.direction === 'up' ? '#E85D75' : '#98A2B3'}
                height={150}
              />
            </div>
          ) : null}
        </section>
      ) : (
        <>
      {(observationTrend.length > 1 || context.momcozyPostCount > 0) ? (
        <div className="grid gap-6 xl:grid-cols-2">
          {observationTrend.length > 1 ? (
            <SectionCard
              title="声量趋势"
              subtitle={`同粒度完整周期 · ${comparisonPhrase(observation!, true).replace(/[（）]/g, '') || '趋势序列'}`}
              tag="舆情"
              icon={<TrendingUp className="h-5 w-5 text-primary" strokeWidth={1.5} />}
            >
              <LineChart
                data={observationTrend}
                color={observation?.sparkline.direction === 'down' ? '#18A874' : observation?.sparkline.direction === 'up' ? '#E85D75' : '#98A2B3'}
                height={280}
              />
            </SectionCard>
          ) : null}

          {context.momcozyPostCount > 0 ? (
            <SectionCard
              title={`${contextLabel}情感构成`}
              subtitle="帖子事实独立计算；不与评论混成一个分母"
              tag="品牌"
              icon={<Activity className="h-5 w-5 text-primary" strokeWidth={1.5} />}
            >
              <PieChart
                data={[
                  { name: SENTIMENT_LABELS.positive, value: context.positivePosts, color: '#18A874' },
                  { name: SENTIMENT_LABELS.neutral, value: context.neutralPosts, color: '#98A2B3' },
                  { name: SENTIMENT_LABELS.negative, value: context.negativePosts, color: '#E85D75' },
                ]}
                innerRadius={0.58}
                height={280}
              />
            </SectionCard>
          ) : null}
        </div>
      ) : null}

      {(context.topics.length > 0 || context.products.length > 0 || context.subreddits.length > 0) ? (
        <section className="space-y-4" aria-labelledby="report-driver-details-title">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-icon bg-primary-light">
              <Hash className="h-[18px] w-[18px] text-primary" strokeWidth={1.5} />
            </div>
            <div>
              <h3 id="report-driver-details-title" className="text-h3 text-foreground">驱动与范围拆解</h3>
              <p className="mt-0.5 text-caption text-foreground-muted">{contextLabel} · 只呈现存在真实绑定或计数的维度</p>
            </div>
          </div>
          <div className="grid gap-6 xl:grid-cols-3">
            {context.topics.length > 0 ? (
              <SectionCard title="主题结构" subtitle="Momcozy 帖子 analysis.topic" tag="舆情" icon={<Hash className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
                <RankedBarList items={context.topics.map((item) => ({ label: formatTopic(item.id), value: item.value }))} />
              </SectionCard>
            ) : null}
            {context.products.length > 0 ? (
              <SectionCard title="品类 / 产品 / SPU" subtitle="每条帖子采用最细可用产品范围" tag="品类" icon={<PackageSearch className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
                <RankedBarList items={context.products.map((item) => ({ label: item.label, value: item.value }))} colorClass="bg-chart-2" />
              </SectionCard>
            ) : null}
            {context.subreddits.length > 0 ? (
              <SectionCard title="社区分布" subtitle="Momcozy 帖子所在 subreddit" tag="运营" icon={<Users className="h-5 w-5 text-primary" strokeWidth={1.5} />}>
                <RankedBarList items={context.subreddits.map((item) => ({ label: item.label, value: item.value }))} colorClass="bg-chart-3" />
              </SectionCard>
            ) : null}
          </div>
        </section>
      ) : null}

      {evidencePosts.length > 0 ? (
        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <SectionCard
            title="真实帖子证据"
            subtitle={`${contextLabel} · 负面优先，再按关联评论与 Score 排序`}
            tag="舆情"
            icon={<FileText className="h-5 w-5 text-primary" strokeWidth={1.5} />}
          >
            <div className="divide-y divide-border-divider">
              {evidencePosts.map((post) => (
                <Link
                  key={post.post_id}
                  to={buildSnapshotEvidenceHref({
                    postId: post.post_id,
                    releaseId: snapshot.release.release_id,
                    snapshotId: snapshot.manifest.dataset_version,
                    source: 'reports',
                  })}
                  className="block py-4 first:pt-0 last:pb-0 hover:text-primary"
                >
                  <div className="flex flex-wrap items-center gap-2 text-tiny text-foreground-muted">
                    <span>r/{post.subreddit || 'unknown'}</span><span>·</span><time dateTime={post.created_at_utc}>{formatDateTime(post.created_at_utc)}</time><span>·</span><span>{SENTIMENT_LABELS[post.analysis.sentiment_label]}</span>
                  </div>
                  <h3 className="mt-1.5 line-clamp-2 text-body-sm font-medium text-foreground">{post.title}</h3>
                  <p className="mt-1 text-tiny text-foreground-muted">Score {post.score} · {post.linked_comment_count} 条关联评论</p>
                </Link>
              ))}
            </div>
          </SectionCard>

          <section className="card p-6" aria-labelledby="report-action-checklist-title">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-status-successBg">
                <Lightbulb className="h-[18px] w-[18px] text-status-success" strokeWidth={1.5} />
              </div>
              <div>
                <p className="text-tiny font-semibold text-status-success">{story.actionLabel}</p>
                <h3 id="report-action-checklist-title" className="mt-0.5 text-h3 text-foreground">从洞察到行动</h3>
              </div>
            </div>
            <ol className="mt-5 space-y-3">
              {actionFacts.map((item, index) => (
                <li key={item} className="flex gap-3 rounded-card bg-surface-tertiary p-4 text-caption leading-relaxed text-foreground-secondary">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white font-semibold text-primary">{index + 1}</span>
                  <span>{item}</span>
                </li>
              ))}
            </ol>
          </section>
        </div>
      ) : null}

      <ReportIndicatorMonitor indicators={report.indicators} />

      <section className="card flex flex-col gap-3 border border-border-divider bg-surface-secondary p-5 text-caption leading-relaxed text-foreground-secondary sm:flex-row sm:items-center sm:justify-between" aria-label="报告口径说明">
        <div className="flex items-start gap-3">
          <Target className="mt-0.5 h-4 w-4 shrink-0 text-primary" strokeWidth={1.5} />
          <p>{report.comparison_contract_proven
            ? '历史采集完整性按数据所有者确认 100% 执行；帖子与评论共同进入治理后的 VOC 指标，但帖子仍保持独立分析。所有比较均为 Reddit 同口径样本，不代表市场份额、销量或 NPS。'
            : '当前日历周期已闭合，但历史采集覆盖未获数据所有者完整性证明；同环比与六期趋势按同源同口径观测值展示，仅用于运营判断，不代表全量市场趋势。'}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-tiny text-foreground-muted">
          {recommendationRate ? <span>推荐表达 {formatReportIndicatorValue(recommendationRate)}</span> : null}
          {urgency ? <span>紧急度 {formatReportIndicatorValue(urgency)}</span> : null}
          {acceleration ? <span>加速度 {formatReportIndicatorValue(acceleration)}</span> : null}
          {productIssueRate ? <span>产品问题 {formatReportIndicatorValue(productIssueRate)}</span> : null}
          {evidenceCompleteness ? <span>证据完整 {formatReportIndicatorValue(evidenceCompleteness)}</span> : null}
        </div>
      </section>
        </>
      )}
    </section>
  );
}
