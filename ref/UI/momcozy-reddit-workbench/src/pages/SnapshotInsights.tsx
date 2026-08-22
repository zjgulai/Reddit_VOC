import {
  BadgeCheck,
  Ban,
  BookOpenCheck,
  Braces,
  ChevronRight,
  CircleUserRound,
  DatabaseZap,
  FileText,
  Fingerprint,
  Gauge,
  Lightbulb,
  MessagesSquare,
  PackageSearch,
  Scale,
  Shield,
  ShieldCheck,
  Tags,
  TrendingUp,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import AggregatePersonaPanel from '../components/personas/AggregatePersonaPanel';
import SnapshotInsightsV3 from '../components/insights/SnapshotInsightsV3';
import ProductAnalysisPanel from '../components/reports/ProductAnalysisPanel';
import RiskThemePanel from '../components/reports/RiskThemePanel';
import { SnapshotMetricCard } from '../features/redditSnapshot/SnapshotMetricCard';
import {
  loadRedditCasebook,
  type RedditPublicCasebook,
} from '../features/redditSnapshot/casebook';
import {
  SnapshotErrorPage,
  SnapshotLoadingPage,
  SnapshotPageLayout,
} from '../features/redditSnapshot/SnapshotPageLayout';
import { createBaseDataFreshness } from '../features/redditSnapshot/freshness';
import { buildSnapshotEvidenceHref } from '../features/redditSnapshot/evidenceLinks';
import {
  createInsightsGovernanceContract,
  DataScopeBar,
  GovernanceStatusBadge,
  mapHighPriorityStatus,
  ReleaseEvidenceCard,
} from '../features/redditSnapshot/governance';
import { isRiskInsightsData } from '../features/redditSnapshot/service';
import { isV3InsightsSnapshot } from '../features/redditSnapshot/insights';
import type {
  CompetitorContext,
  InsightsHeldTag,
  InsightsSignal,
  RedditInsightsSnapshot,
  RiskComparison,
  RiskInsightsData,
  RiskShareMetric,
} from '../features/redditSnapshot/types';
import { useRedditInsights } from '../features/redditSnapshot/useRedditInsights';
import { useRedditPersonas } from '../features/redditSnapshot/useRedditPersonas';
import { useRedditQuarterInsights } from '../features/redditSnapshot/useRedditQuarterInsights';
import { useRedditSnapshot } from '../features/redditSnapshot/useRedditSnapshot';

const dimensionLabels: Record<string, string> = {
  consumer_card: '洞察卡片映射',
  aipl_node: 'AIPL 阶段',
  story_lines: '故事线',
  intent_type: '意图类型',
  problem_type: '问题类型',
};

const failedCheckLabels: Record<string, string> = {
  sample_count: '样本量',
  label_precision: '标签精确率',
  wilson_lower_bound_95: '置信下界',
  taxonomy_fit_rate: '字典适配',
  ambiguous_rate: '歧义率',
  governance_fit: '治理定义',
};

const reasonLabels: Record<string, string> = {
  theme_scope_mismatch: '礼貌用语与客服正向反馈混淆，theme 范围不匹配。',
  definition_business_fit: '业务概念成立，但当前词法规则缺少语境、主体或极性约束。',
  zendesk_source_definition_mismatch: '定义限定 Zendesk 工单，不能直接迁移到 Reddit。',
  telephony_definition_product_mismatch: '字典指电话/音频，真实文本指可穿戴泵等产品。',
};

function percent(value: number): string {
  return `${(value * 100).toFixed(value === 1 ? 0 : 1)}%`;
}

function SignalCard({
  signal,
  releaseId,
  snapshotId,
}: {
  signal: InsightsSignal;
  releaseId: string;
  snapshotId: string;
}) {
  const reference = signal.dictionary_reference;
  return (
    <article className="group relative overflow-hidden rounded-[24px] border border-border-divider bg-white shadow-card transition-all duration-300 hover:-translate-y-0.5 hover:shadow-cardHover">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-[#27A67A] to-[#E9A23B]" />
      <div className="p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="rounded-badge bg-status-successBg px-2.5 py-1 text-tiny font-semibold text-status-success">
                已通过语义门禁
              </span>
              <span className="font-mono text-tiny text-foreground-muted">{signal.tag_id}</span>
            </div>
            <h3 className="text-[24px] font-semibold tracking-tight text-foreground">{signal.name_cn}</h3>
            <p className="mt-1 text-caption text-foreground-muted">{signal.name_en} · {signal.theme}</p>
          </div>
          <div className="rounded-[18px] bg-surface-tertiary px-4 py-3 text-right">
            <p className="text-[26px] font-semibold leading-none text-foreground">{signal.matched_entities}</p>
            <p className="mt-1 text-tiny text-foreground-muted">规则命中实体</p>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ['帖子', signal.matched_posts],
            ['评论', signal.matched_comments],
            ['样本精确率', percent(signal.review_metrics.label_precision)],
            ['95% 置信下界', percent(signal.review_metrics.wilson_lower_bound_95)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-card border border-border-divider/80 px-3 py-3">
              <p className="text-body-sm font-semibold text-foreground">{value}</p>
              <p className="mt-0.5 text-tiny text-foreground-muted">{label}</p>
            </div>
          ))}
        </div>

        <div className="mt-5 rounded-[18px] border border-primary/10 bg-primary-light/55 p-4">
          <div className="mb-3 flex items-center gap-2">
            <Fingerprint className="h-4 w-4 text-primary" strokeWidth={1.5} />
            <p className="text-caption font-semibold text-foreground">字典参考维度</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              `卡片 · ${reference.consumer_card}`,
              `AIPL · ${reference.aipl_node}`,
              `故事线 · ${reference.story_lines}`,
              `意图 · ${reference.intent_type}`,
              `问题 · ${reference.problem_type}`,
            ].map((item) => (
              <span key={item} className="rounded-badge border border-primary/10 bg-white px-2.5 py-1 text-tiny text-foreground-secondary">
                {item}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <BookOpenCheck className="h-4 w-4 text-foreground-secondary" strokeWidth={1.5} />
              <p className="text-caption font-semibold text-foreground">审核证据切片</p>
            </div>
            <span className="text-tiny text-foreground-muted">展示 3/{signal.evidence_examples.length}</span>
          </div>
          <div className="grid gap-3 lg:grid-cols-3">
            {signal.evidence_examples.slice(0, 3).map((evidence) => (
              <div key={evidence.audit_id} className="flex min-h-44 flex-col rounded-[18px] bg-[#F7F8FA] p-4">
                <div className="flex items-center justify-between gap-2 text-tiny text-foreground-muted">
                  <span>{evidence.entity_type === 'post' ? '帖子' : '评论'} · {evidence.source_stratum}</span>
                  <span className="font-mono">{evidence.reddit_id}</span>
                </div>
                <blockquote className="mt-3 line-clamp-5 flex-1 text-caption leading-relaxed text-foreground-secondary">
                  “{evidence.context_excerpt}”
                </blockquote>
                <Link
                  className="mt-3 inline-flex items-center gap-1 text-tiny font-medium text-primary hover:underline"
                  to={buildSnapshotEvidenceHref({
                    postId: evidence.post_id,
                    commentId: evidence.entity_type === 'comment' ? evidence.reddit_id : null,
                    releaseId,
                    snapshotId,
                    source: 'insights',
                  })}
                >
                  在原始帖子中核查
                  <ChevronRight className="h-3.5 w-3.5" strokeWidth={1.5} />
                </Link>
              </div>
            ))}
          </div>
        </div>
      </div>
    </article>
  );
}

function HeldTagRow({ tag }: { tag: InsightsHeldTag }) {
  const reason = reasonLabels[tag.governance_review.reason_code] ?? tag.governance_review.note;
  return (
    <tr className="border-t border-border-divider align-top first:border-t-0">
      <td className="min-w-48 px-4 py-4">
        <p className="text-caption font-semibold text-foreground">{tag.name_cn}</p>
        <p className="mt-1 font-mono text-tiny text-foreground-muted">{tag.tag_id}</p>
      </td>
      <td className="px-4 py-4 text-caption font-medium text-foreground">{tag.matched_entities}</td>
      <td className="px-4 py-4 text-caption text-foreground-secondary">
        {percent(tag.review_metrics.label_precision)}
        <span className="ml-1 text-tiny text-foreground-muted">({tag.review_metrics.correct}/{tag.review_metrics.correct + tag.review_metrics.incorrect})</span>
      </td>
      <td className="min-w-52 px-4 py-4">
        <div className="flex flex-wrap gap-1.5">
          {tag.failed_checks.map((check) => (
            <span key={check} className="rounded-badge bg-surface-tertiary px-2 py-0.5 text-tiny text-foreground-muted" data-governance-status="provisional">
              {failedCheckLabels[check] ?? check}
            </span>
          ))}
        </div>
      </td>
      <td className="min-w-72 px-4 py-4 text-caption leading-relaxed text-foreground-secondary">{reason}</td>
    </tr>
  );
}

function share(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function highPriorityStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    governed: '已按冻结证据门禁治理',
    unavailable_unfrozen_evidence_threshold: '风险证据阈值待审核',
  };
  return labels[status] ?? `未识别状态：${status}`;
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

function comparisonSummary(comparison: RiskComparison<RiskShareMetric>): { value: string; note: string; tone: string } {
  if (comparison.comparison_status === 'unavailable') {
    return { value: '不可比较', note: comparisonReasons(comparison.reason_codes) || '基期或覆盖证据缺失', tone: 'text-foreground-muted' };
  }
  if (comparison.comparison_status === 'provisional_observed_sample') {
    const delta = comparison.absolute_delta === null ? '差值不可用' : `样本差值 ${(comparison.absolute_delta * 100).toFixed(1)}pp`;
    return { value: '已观察样本', note: `${delta} · ${comparisonReasons(comparison.reason_codes)}`, tone: 'text-primary' };
  }
  if (!comparison.direction_claim_supported || comparison.absolute_delta === null) {
    return { value: '可比较', note: '差值可用，但方向结论条件未满足', tone: 'text-primary' };
  }
  const direction = comparison.absolute_delta > 0 ? '上升' : comparison.absolute_delta < 0 ? '下降' : '持平';
  return {
    value: `${direction} ${Math.abs(comparison.absolute_delta * 100).toFixed(1)}pp`,
    note: `当前 ${share(comparison.current.value)} · 基期 ${share(comparison.baseline?.value ?? null)}`,
    tone: comparison.absolute_delta > 0 ? 'text-status-error' : 'text-status-success',
  };
}

function RiskMomentumPanel({ insights }: { insights: RiskInsightsData }) {
  const momentum = insights.risk_command_center.primary_kpis.risk_momentum;
  const groups = [
    ['环比', momentum.previous_period],
    ['同比', momentum.year_over_year],
  ] as const;
  return (
    <section className="card p-5 sm:p-6" aria-labelledby="risk-momentum-title">
      <div className="mb-5 flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light">
          <TrendingUp className="h-[18px] w-[18px] text-primary" strokeWidth={1.5} />
        </div>
        <div>
          <h2 id="risk-momentum-title" className="text-h3 text-foreground">风险动量：环比与同比</h2>
          <p className="mt-0.5 text-caption text-foreground-muted">Momcozy 负面证据占比；帖子、评论保持独立口径</p>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map(([label, comparisons]) => (
          <article key={label} className="min-w-0 rounded-card border border-border-divider p-4">
            <h3 className="text-body-sm font-semibold text-foreground">{label}</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {(['post', 'comment'] as const).map((entityType) => {
                const summary = comparisonSummary(comparisons[entityType]);
                return (
                  <div key={entityType} className="min-w-0 rounded-icon bg-surface-tertiary p-3">
                    <p className="text-tiny text-foreground-muted">{entityType === 'post' ? '帖子' : '评论'}</p>
                    <p className={`mt-1 text-body-sm font-semibold ${summary.tone}`}>{summary.value}</p>
                    <p className="mt-1 break-words text-tiny leading-relaxed text-foreground-muted">{summary.note}</p>
                  </div>
                );
              })}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function CompetitorContextPanel({ competitors }: { competitors: CompetitorContext[] }) {
  const visibleCompetitors = competitors.slice(0, 6);
  return (
    <section className="card p-5 sm:p-6" aria-labelledby="competitor-context-title">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-surface-tertiary">
            <Scale className="h-[18px] w-[18px] text-foreground-secondary" strokeWidth={1.5} />
          </div>
          <div>
            <h2 id="competitor-context-title" className="text-h3 text-foreground">竞品同样本语境</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">竞品只作对照方，不解释为市场份额、SOV、渗透率或销量</p>
          </div>
        </div>
        {competitors.length > 0 && (
          <span className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-tiny text-foreground-secondary">
            展示 {visibleCompetitors.length}/{competitors.length}
          </span>
        )}
      </div>
      {competitors.length ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {visibleCompetitors.map((competitor) => (
              <article key={competitor.brand_id} className="rounded-card border border-border-divider p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-body-sm font-semibold text-foreground">{competitor.brand_name}</h3>
                    <p className="mt-0.5 font-mono text-tiny text-foreground-muted">{competitor.brand_id}</p>
                  </div>
                  <span className="rounded-badge bg-surface-tertiary px-2 py-1 text-tiny text-foreground-muted">同样本</span>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-caption">
                  <div className="rounded-icon bg-surface-tertiary p-3">
                    <dt className="text-tiny text-foreground-muted">帖子负面</dt>
                    <dd className="mt-1 font-semibold text-foreground">{share(competitor.negative_evidence_share.post.value)}</dd>
                  </div>
                  <div className="rounded-icon bg-surface-tertiary p-3">
                    <dt className="text-tiny text-foreground-muted">评论负面</dt>
                    <dd className="mt-1 font-semibold text-foreground">{share(competitor.negative_evidence_share.comment.value)}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
          {competitors.length > visibleCompetitors.length && (
            <p className="mt-4 text-tiny leading-relaxed text-foreground-muted">
              其余 {competitors.length - visibleCompetitors.length} 项保留在版本化数据与报告附录中，不延长当前决策主线。
            </p>
          )}
        </>
      ) : (
        <p className="rounded-card border border-dashed border-border-divider bg-surface-tertiary p-4 text-caption text-foreground-muted">当前窗口没有满足受控绑定的竞品对照记录。</p>
      )}
    </section>
  );
}

function RiskInsightsView({
  snapshot,
  personasState,
}: {
  snapshot: RedditInsightsSnapshot & { insights: RiskInsightsData };
  personasState: ReturnType<typeof useRedditPersonas>;
}) {
  const { manifest, insights } = snapshot;
  const command = insights.risk_command_center;
  const highPriority = command.primary_kpis.high_priority_risk_themes;
  const highPriorityGovernanceStatus = mapHighPriorityStatus(highPriority.status);
  const highPriorityUnavailable = highPriority.value === null || highPriorityGovernanceStatus === 'unavailable';
  const highPriorityValue = highPriorityUnavailable ? '—' : (highPriority.value ?? '—');
  const governanceContract = createInsightsGovernanceContract(
    snapshot.core.release,
    snapshot.core,
    snapshot.manifest,
  );
  const productBindingRate = insights.product_analysis.coverage.binding_rate;
  return (
    <SnapshotPageLayout
      icon={Lightbulb}
      title="风险治理洞察"
      description="Momcozy 风险主线 · 产品三层分析 · 竞品同样本对照"
      datasetVersion={manifest.dataset_version}
      freshness={createBaseDataFreshness(snapshot.core, {
        projectionDatasetVersion: manifest.dataset_version,
        projectionGeneratedAtUtc: null,
      })}
    >
      <DataScopeBar contract={governanceContract} />

      <section className="relative overflow-hidden rounded-[28px] bg-[#17212B] px-5 py-7 text-white shadow-card sm:px-8 sm:py-9">
        <div className="absolute -right-24 -top-24 h-72 w-72 rounded-full border border-white/10" />
        <div className="relative grid gap-7 lg:grid-cols-[1.45fr_0.55fr] lg:items-end">
          <div>
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-tiny text-white/75">
              <Shield className="h-3.5 w-3.5 text-[#78D8B0]" strokeWidth={1.5} />
              Momcozy 为决策主干 · 竞品仅作同样本对照
            </div>
            <h2 className="max-w-3xl text-[30px] font-semibold leading-tight tracking-[-0.03em] sm:text-[42px]">
              先识别品牌风险，
              <span className="block text-[#78D8B0]">再定位到品类、产品族与 SPU。</span>
            </h2>
            <p className="mt-4 max-w-2xl text-body-sm leading-relaxed text-white/65">
              观察窗口 {command.window.start_local} 至 {command.window.end_local}。帖子和评论分开计算；只有覆盖门禁通过时才表达变化方向。
            </p>
          </div>
          <div
            className="flex flex-col items-start gap-3 lg:items-end"
            data-business-priority={highPriorityUnavailable ? undefined : 'P0-P1'}
          >
            <div className="flex items-end gap-3">
              <span className="text-[72px] font-semibold leading-[0.82] tracking-[-0.06em] text-white">{highPriorityValue}</span>
              <span className="pb-1 text-caption leading-relaxed text-white/55">P0/P1<br />治理风险主题</span>
            </div>
            {highPriorityUnavailable && (
              <div className="flex flex-wrap items-center gap-2 text-tiny text-white/70">
                <GovernanceStatusBadge
                  status="unavailable"
                  label={highPriorityStatusLabel(highPriority.status)}
                />
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Momcozy 风险摘要">
        <SnapshotMetricCard icon={Shield} value={highPriorityValue} label="P0/P1 风险主题" note={highPriorityUnavailable ? '证据阈值未冻结，不进入高优先级排序' : '冻结证据门禁后的去重主题数'} businessPriority={highPriorityUnavailable ? undefined : 'P0-P1'} />
        <SnapshotMetricCard icon={FileText} value={share(command.primary_kpis.negative_evidence_share.post.value)} label="帖子负面证据占比" note={`${command.primary_kpis.negative_evidence_share.post.numerator ?? '—'}/${command.primary_kpis.negative_evidence_share.post.denominator ?? '—'} · Momcozy 受控绑定`} />
        <SnapshotMetricCard icon={MessagesSquare} value={share(command.primary_kpis.negative_evidence_share.comment.value)} label="评论负面证据占比" note={`${command.primary_kpis.negative_evidence_share.comment.numerator ?? '—'}/${command.primary_kpis.negative_evidence_share.comment.denominator ?? '—'} · 与帖子不合并`} />
        <SnapshotMetricCard icon={PackageSearch} value={typeof productBindingRate === 'number' ? share(productBindingRate) : '—'} label="产品范围绑定率" note="可进入品类、产品族或受控 SPU 分析的内容实体" />
      </section>

      <RiskMomentumPanel insights={insights} />
      <RiskThemePanel
        themes={command.risk_themes}
        evidenceContext={{
          releaseId: snapshot.core.release.release_id,
          snapshotId: snapshot.core.manifest.dataset_version,
          source: 'insights',
        }}
      />
      <ProductAnalysisPanel analysis={insights.product_analysis} />
      <CompetitorContextPanel competitors={command.competitor_context} />

      <AggregatePersonaPanel {...personasState} />

      <section aria-labelledby="control-evidence-title">
        <div className="card p-5 sm:p-6">
          <div className="mb-5 flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-surface-tertiary">
              <ShieldCheck className="h-[18px] w-[18px] text-foreground-secondary" strokeWidth={1.5} />
            </div>
            <div>
              <h2 id="control-evidence-title" className="text-h3 text-foreground">C · 受控开发、测试与发布证据</h2>
              <p className="mt-0.5 text-caption text-foreground-muted">本模块分别展示构建产物、当前服务身份、生产提升与生产验收，不合并为一个成功状态</p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              ['基础数据', insights.control_evidence.base_dataset_version],
              ['语义治理', insights.control_evidence.semantic_governance_version],
              ['覆盖台账', insights.control_evidence.coverage_ledger_version ?? '未提供'],
              ['风险门禁', `${insights.control_evidence.risk_gate_policy_version ?? '未提供'} · ${insights.control_evidence.risk_gate_policy_status}`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-card bg-surface-tertiary p-3">
                <p className="text-tiny text-foreground-muted">{label}</p>
                <p className="mt-1 break-all text-caption font-medium text-foreground">{value}</p>
              </div>
            ))}
          </div>
          <p className="mt-4 border-t border-border-divider pt-3 text-tiny leading-relaxed text-foreground-muted">
            以下为离线数据产物生成边界 / receipt；不代表当前站点未运行或未部署。生产提升与生产验收只有在存在独立部署证据源时才可确认。
          </p>
        </div>
        <ReleaseEvidenceCard contract={governanceContract} className="mt-4" />
      </section>
    </SnapshotPageLayout>
  );
}

export default function SnapshotInsights() {
  const { data, error, isLoading } = useRedditInsights();
  const baseState = useRedditSnapshot();
  const personasState = useRedditPersonas();
  const quarterInsightsState = useRedditQuarterInsights();
  const [casebookState, setCasebookState] = useState<{
    data: RedditPublicCasebook | null;
    error: string | null;
    isLoading: boolean;
  }>({ data: null, error: null, isLoading: true });

  useEffect(() => {
    if (!data || !isV3InsightsSnapshot(data)) return;
    let active = true;
    loadRedditCasebook()
      .then((casebook) => {
        if (active) setCasebookState({ data: casebook, error: null, isLoading: false });
      })
      .catch((casebookError: unknown) => {
        if (!active) return;
        setCasebookState({
          data: null,
          error: casebookError instanceof Error ? casebookError.message : '社区治理案例加载失败',
          isLoading: false,
        });
      });
    return () => { active = false; };
  }, [data]);

  const v3 = Boolean(data && isV3InsightsSnapshot(data));
  if (isLoading || (v3 && (baseState.isLoading || quarterInsightsState.isLoading))) {
    return <SnapshotLoadingPage icon={Lightbulb} title="季度经营洞察" />;
  }
  if (error || !data) return <SnapshotErrorPage icon={Lightbulb} title="风险治理洞察" error={error ?? '未知错误'} />;

  if (isV3InsightsSnapshot(data)) {
    if (baseState.error || !baseState.data) {
      return <SnapshotErrorPage icon={Lightbulb} title="风险治理洞察" error={baseState.error ?? '真实 Base 快照不可用'} />;
    }
    if (quarterInsightsState.error || !quarterInsightsState.data) {
      return (
        <SnapshotErrorPage
          icon={Lightbulb}
          title="季度经营洞察"
          error={quarterInsightsState.error ?? '季度洞察公开投影不可用'}
        />
      );
    }
    return (
      <SnapshotInsightsV3
        snapshot={data}
        baseSnapshot={baseState.data}
        quarterInsights={quarterInsightsState.data.data}
        personasState={personasState}
        casebookState={casebookState}
      />
    );
  }

  const { manifest, audit, insights } = data;
  if (isRiskInsightsData(insights)) {
    return <RiskInsightsView snapshot={{ ...data, insights }} personasState={personasState} />;
  }
  const {
    audited_tags: auditedTags = 0,
    held_tags: heldTags = 0,
    promoted_tags: promotedTags = 0,
    reviewed_assignments: reviewedAssignments = 0,
  } = insights.headline;
  const qualityGate = audit.quality_gate;
  if (!qualityGate) return <SnapshotErrorPage icon={Lightbulb} title="语义洞察" error="语义复核质量门禁缺失" />;
  const governanceContract = createInsightsGovernanceContract(data.core.release, data.core, manifest);
  return (
    <SnapshotPageLayout
      icon={Lightbulb}
      title="语义洞察"
      description="只有通过标签语义门禁的真实数据信号才会显示"
      datasetVersion={manifest.dataset_version}
      freshness={createBaseDataFreshness(data.core, {
        projectionDatasetVersion: manifest.dataset_version,
        projectionGeneratedAtUtc: null,
      })}
    >
      <DataScopeBar contract={governanceContract} />

      <section className="relative overflow-hidden rounded-[28px] bg-[#17212B] px-5 py-7 text-white shadow-card sm:px-8 sm:py-9">
        <div className="absolute -right-24 -top-24 h-72 w-72 rounded-full border border-white/10" />
        <div className="absolute -right-8 -top-8 h-40 w-40 rounded-full border border-white/10" />
        <div className="relative grid gap-7 lg:grid-cols-[1.5fr_0.5fr] lg:items-end">
          <div>
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-tiny text-white/75">
              <ShieldCheck className="h-3.5 w-3.5 text-[#78D8B0]" strokeWidth={1.5} />
              {reviewedAssignments.toLocaleString('zh-CN')} 条上下文复核 · 仅展示已验证结果
            </div>
            <h2 className="max-w-3xl text-[30px] font-semibold leading-tight tracking-[-0.03em] sm:text-[42px]">
              高频不等于可信。
              <span className="block text-[#78D8B0]">{auditedTags} 个候选标签，只有 {promotedTags} 个可进入洞察。</span>
            </h2>
            <p className="mt-4 max-w-2xl text-body-sm leading-relaxed text-white/65">
              每个标签按帖子、评论和三类来源分层抽样；精确率、置信下界、字典适配、歧义率与治理定义必须同时通过。
            </p>
          </div>
          <div className="flex items-end gap-3 lg:justify-end">
            <span className="text-[72px] font-semibold leading-[0.82] tracking-[-0.06em] text-white">{promotedTags}</span>
            <span className="pb-1 text-caption leading-relaxed text-white/55">promoted<br />of {auditedTags} audited</span>
          </div>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="语义复核摘要">
        <SnapshotMetricCard
          icon={BookOpenCheck}
          value={reviewedAssignments}
          label="上下文复核条目"
          note={`${auditedTags} 标签 × 每标签 ${qualityGate.required_samples_per_tag} 条；非独立人工金标准`}
          tone="success"
        />
        <SnapshotMetricCard icon={BadgeCheck} value={insights.headline.promoted_tags ?? 0} label="晋级洞察标签" note="工作场景、强烈推荐通过全部门禁" tone="success" />
        <SnapshotMetricCard icon={Ban} value={insights.headline.held_tags ?? 0} label="暂缓标签" note="失败诊断保留，但不计入洞察信号" />
        <SnapshotMetricCard icon={DatabaseZap} value={insights.headline.promoted_rule_assignments ?? 0} label="晋级规则分配" note="内容实体命中次数，不是用户数量" />
      </section>

      <section aria-labelledby="promoted-signals-title">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Gauge className="h-5 w-5 text-primary" strokeWidth={1.5} />
              <h2 id="promoted-signals-title" className="text-h2 text-foreground">通过门禁的信号</h2>
            </div>
            <p className="mt-1 text-caption text-foreground-muted">每项均保留抽样质量、字典关系与原始上下文证据</p>
          </div>
          <span className="rounded-badge border border-status-success/20 bg-status-successBg px-3 py-1.5 text-tiny font-medium text-status-success">
            {insights.headline.unique_posts_with_promoted_tags ?? 0} 帖子 · {insights.headline.unique_comments_with_promoted_tags ?? 0} 评论
          </span>
        </div>
        <div className="space-y-4">
          {insights.signals.map((signal) => (
            <SignalCard
              key={signal.tag_id}
              signal={signal}
              releaseId={data.core.release.release_id}
              snapshotId={data.core.manifest.dataset_version}
            />
          ))}
        </div>
      </section>

      <AggregatePersonaPanel {...personasState} />

      <section className="card overflow-hidden" aria-labelledby="persona-reference-title">
        <div className="grid lg:grid-cols-[0.72fr_1.28fr]">
          <div className="bg-[#FFF7E8] p-5 sm:p-6">
            <div className="flex h-10 w-10 items-center justify-center rounded-icon bg-white text-[#B86B00] shadow-sm">
              <CircleUserRound className="h-5 w-5" strokeWidth={1.5} />
            </div>
            <h2 id="persona-reference-title" className="mt-4 text-h3 text-foreground">画像相关映射，只作参考维度</h2>
            <p className="mt-2 text-caption leading-relaxed text-foreground-secondary">
              `consumer_card` 是标签到洞察卡片的字典映射，不是用户级 `persona_id`。下列数字是内容实体命中数，不能解释为用户规模。
            </p>
            <div className="mt-4 rounded-card border border-[#E9A23B]/20 bg-white/70 p-3 text-tiny leading-relaxed text-[#8B5707]">
              当前 Insights v1 本身 persona_tags_generated=false；上方画像来自独立、版本化的 dim_persona_v1 + persona-tags 数据集
            </div>
          </div>
          <div className="grid gap-px bg-border-divider sm:grid-cols-2 xl:grid-cols-3">
            {Object.entries(insights.reference_dimensions).map(([dimension, values]) => (
              <div key={dimension} className="bg-white p-5">
                <div className="mb-3 flex items-center gap-2">
                  <Braces className="h-4 w-4 text-primary" strokeWidth={1.5} />
                  <h3 className="text-caption font-semibold text-foreground">{dimensionLabels[dimension] ?? dimension}</h3>
                </div>
                <dl className="space-y-2.5">
                  {Object.entries(values).map(([label, count]) => (
                    <div key={label} className="flex items-center justify-between gap-3 text-caption">
                      <dt className="text-foreground-secondary">{label}</dt>
                      <dd className="font-semibold text-foreground">{count}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card overflow-hidden" aria-labelledby="held-tags-title">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-divider p-5 sm:p-6">
          <div>
            <div className="flex items-center gap-2">
              <Tags className="h-5 w-5 text-foreground-secondary" strokeWidth={1.5} />
              <h2 id="held-tags-title" className="text-h3 text-foreground">暂缓标签诊断</h2>
            </div>
            <p className="mt-1 text-caption text-foreground-muted">原始命中量仍可审计，但不会进入上方业务信号</p>
          </div>
          <span className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-tiny font-medium text-foreground-muted" data-governance-status="provisional">{heldTags} 项 held</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead className="bg-surface-tertiary text-tiny font-medium text-foreground-muted">
              <tr>
                <th className="px-4 py-3">标签</th>
                <th className="px-4 py-3">原命中</th>
                <th className="px-4 py-3">样本精确率</th>
                <th className="px-4 py-3">失败门禁</th>
                <th className="px-4 py-3">诊断</th>
              </tr>
            </thead>
            <tbody>{insights.held_tags.map((tag) => <HeldTagRow key={tag.tag_id} tag={tag} />)}</tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="card p-5 sm:p-6">
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-status-success" strokeWidth={1.5} />
            <h2 className="text-h3 text-foreground">晋级条件</h2>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-caption sm:grid-cols-3">
            {[
              ['每标签样本', `≥ ${qualityGate.required_samples_per_tag}`],
              ['样本精确率', `≥ ${percent(qualityGate.minimum_label_precision)}`],
              ['95% 置信下界', `≥ ${percent(qualityGate.minimum_wilson_lower_bound_95)}`],
              ['字典适配率', `≥ ${percent(qualityGate.minimum_taxonomy_fit_rate)}`],
              ['最大歧义率', `≤ ${percent(qualityGate.maximum_ambiguous_rate)}`],
              ['治理状态', qualityGate.governance_status_required],
            ].map(([label, value]) => (
              <div key={label} className="rounded-card bg-surface-tertiary p-3">
                <dt className="text-tiny text-foreground-muted">{label}</dt>
                <dd className="mt-1 font-semibold text-foreground">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="card p-5 sm:p-6">
          <div className="mb-4 flex items-center gap-2">
            <MessagesSquare className="h-5 w-5 text-primary" strokeWidth={1.5} />
            <h2 className="text-h3 text-foreground">解释与运行边界</h2>
          </div>
          <ul className="space-y-2.5 text-caption leading-relaxed text-foreground-secondary">
            <li>晋级代表分层样本通过门禁，不代表全量样本已由独立人员复核。</li>
            <li>不支持市场份额、ROI、趋势或因果结论；页面不做此类推算。</li>
            <li>未变更线上环境、未调用外部分析服务、未写入业务数据库、未触发对外发送。</li>
          </ul>
          <p className="mt-4 border-t border-border-divider pt-3 font-mono text-tiny text-foreground-muted">
            基础数据版本 {manifest.base_dataset_version} · 已通过完整性校验
          </p>
        </div>
      </section>
    </SnapshotPageLayout>
  );
}
